from __future__ import annotations
import importlib.util, sys
from pathlib import Path
MODULE=Path(__file__).parents[1]/"relay.py"; SPEC=importlib.util.spec_from_file_location("feedback_hub_relay",MODULE)
assert SPEC and SPEC.loader
relay=importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=relay; SPEC.loader.exec_module(relay)

def test_config_requires_https_and_users_need_no_github_values(monkeypatch) -> None:
    monkeypatch.setenv("BYQ_FEEDBACK_HUB_URL","https://feedback.example.org")
    monkeypatch.setenv("BYQ_FEEDBACK_HUB_RELAY_TOKEN","relay-token")
    config=relay.Config.from_env(); assert config.hub_url=="https://feedback.example.org"
    assert not any("github" in field for field in config.__dataclass_fields__)

def test_delivery_preserves_exact_snapshot_and_receipt(monkeypatch) -> None:
    calls=[]; config=relay.Config("http://backend","relay-token","https://feedback.example.org","relay-worker",15)
    event={"event_id":"feedback_hub_event_"+"a"*32,"installation_id":"byq-installation-"+"b"*32,
           "snapshot_hash":"c"*64,"snapshot":{"schema_version":"submitted-feedback-snapshot.v1"},"lease_fence":3}
    monkeypatch.setattr(relay,"_json_request",lambda url,**kwargs:calls.append((url,kwargs)) or {"receipt_id":"central_feedback_"+"d"*32,"status_token":"e"*64})
    monkeypatch.setattr(relay,"_backend",lambda _config,path,**kwargs:calls.append((path,kwargs)) or {})
    relay._deliver(config,event)
    assert calls[0][1]["payload"]["snapshot_hash"]=="c"*64
    assert calls[1][0].endswith("/complete") and calls[1][1]["payload"]["status_token"]=="e"*64
