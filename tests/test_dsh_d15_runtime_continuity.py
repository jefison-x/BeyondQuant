"""D15 runtime-continuity acceptance observer tests (fail-able verdict)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OBSERVER = ROOT / "scripts/d15/runtime_continuity/observer.py"
CONTRACT = ROOT / "scripts/d15/runtime_continuity/contract.v1.json"


def _load_observer():
    spec = importlib.util.spec_from_file_location("d15_runtime_observer", OBSERVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["d15_runtime_observer"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_contract_is_closed_and_versioned():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["schema_version"] == "byq-d15-runtime-contract.v1"
    ids = [item["id"] for item in contract["required_scenarios"]]
    assert len(ids) == len(set(ids))
    assert "adapter-process-restart" in ids
    assert "gateway-disconnect-reconnect" in ids
    assert "generation-replacement" in ids
    assert "executor-takeover" in ids
    assert contract["candidate"]["release"] == "dsh-0.1.5rc1"


def test_valid_fixture_passes_and_every_negative_control_fails():
    observer = _load_observer()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    verdict = observer.compute_verdict(contract, observer.valid_fixture(contract))
    assert verdict["all_pass"] is True
    assert verdict["exit_code"] == 0

    controls = observer.run_selfcheck(contract)
    assert controls["baseline_all_pass"] is True
    assert controls["all_controls_pass"] is True
    assert controls["control_count"] >= 18
    for control in controls["controls"]:
        assert control["observed_all_pass"] is False, control
        assert control["observed_exit_code"] == 1, control
        assert control["first_failure"], control


def test_missing_evidence_is_never_an_empty_default_pass():
    observer = _load_observer()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    default = {
        "schema_version": "byq-d15-runtime-observations.v1",
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False},
        "scenarios": [],
    }
    verdict = observer.compute_verdict(contract, default)
    assert verdict["all_pass"] is False
    assert verdict["exit_code"] == 1
    assert any("missing required scenario" in item for item in verdict["failures"])


def test_not_run_requires_a_reason():
    observer = _load_observer()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    fixture = observer.valid_fixture(contract)
    fixture["scenarios"][0] = {"id": "adapter-process-restart", "result": "NOT_RUN"}
    verdict = observer.compute_verdict(contract, fixture)
    assert verdict["all_pass"] is False
    assert any("without a reason" in item for item in verdict["failures"])


def test_observer_cli_fails_on_malformed_observations(tmp_path: Path):
    observer = _load_observer()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert observer.main(["--observations", str(bad)]) == 2


def test_observer_cli_exit_code_tracks_verdict(tmp_path: Path):
    observer = _load_observer()
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    good = tmp_path / "good.json"
    good.write_text(json.dumps(observer.valid_fixture(contract)), encoding="utf-8")
    assert observer.main(["--observations", str(good), "--out", str(tmp_path / "v.json")]) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
