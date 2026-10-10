"""ADR-0107 judgment consumer core (keyless; no Backend/Adapter/model)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "workers" / "judgment" / "worker.py").is_file())
sys.path.insert(0, str(_ROOT / "workers" / "judgment"))

import worker as consumer_mod  # noqa: E402

TASK = {
    "task_id": "task_" + "a" * 32, "owner_principal": "owner-a",
    "workspace_id": "workspace-a", "conversation_id": "conversation-a",
    "plan_version": 1, "task_version": 1, "stage": "strategy_draft", "iteration": 1,
    "session_id": "byqjdg-session", "trace_id": "trace-a",
}


class _Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise AssertionError(f"unexpected status {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _Http:
    def __init__(self, *, claim: dict, intent: dict | None = None,
                 dispatch_payload: dict | None = None, status: dict | None = None) -> None:
        self.calls: list[str] = []
        self._claim = claim
        self._intent = intent if intent is not None else {"intent": True}
        self._dispatch = dispatch_payload or {"status": "completed"}
        self._status = status if status is not None else {"status": "settled"}

    def get(self, url: str, headers: dict | None = None) -> _Response:
        self.calls.append(url)
        if url.endswith("/runtime-authority/current"):
            return _Response({"boot_id": "b" * 32})
        if url.endswith("/dispatch"):
            return _Response({"kind": "judgment_turn"})
        return _Response({"stages": [TASK]})

    def post(self, url: str, headers: dict | None = None,
             json: dict | None = None, timeout: float | None = None) -> _Response:
        self.calls.append(url)
        if url.endswith("/stage-claim"):
            return _Response(self._claim)
        if url.endswith("/stage-dispatch-intent"):
            return _Response(self._intent)
        if url.endswith("/acp-root/run"):
            return _Response(self._dispatch)
        if url.endswith("/acp-root/status"):
            return _Response(self._status)
        raise AssertionError(f"unexpected post {url}")


def _consumer(http: _Http) -> "consumer_mod.JudgmentConsumer":
    return consumer_mod.JudgmentConsumer(
        backend_url="http://backend", adapter_url="http://adapter",
        judgment_token="token", claim_owner="worker-a", transport=http)  # gitleaks:allow — fixed synthetic test key


def test_consumer_claims_then_intent_then_dispatches_then_reconciles():
    http = _Http(claim={"claimed": True, "reconcile_only": False},
                 status={"status": "completed", "terminal_sequence": 2})
    outcome = _consumer(http).run_once()
    entry = outcome["outcomes"][0]
    assert entry["claimed"] is True and entry["intent"] is True
    assert entry["run"]["status"] == "completed"
    assert entry["status_receipt"] == {"status": "completed", "terminal_sequence": 2}
    # The consumer only selects, reads the business gate, claims, records the
    # intent, dispatches, and reads the trusted status receipt; it never writes
    # the plan.
    assert all(path.endswith(("/stages", "/dispatch", "/stage-claim",
                              "/stage-dispatch-intent", "/acp-root/run",
                              "/acp-root/status", "/runtime-authority/current"))
               for path in http.calls)
    assert any(path.endswith("/acp-root/run") for path in http.calls)
    assert any(path.endswith("/acp-root/status") for path in http.calls)


def test_consumer_does_not_dispatch_a_non_judgment_turn_stage():
    class _GateHttp(_Http):
        def get(self, url: str, headers: dict | None = None) -> _Response:
            self.calls.append(url)
            if url.endswith("/dispatch"):
                return _Response({"kind": "approval_wait"})
            return _Response({"stages": [TASK]})

    http = _GateHttp(claim={"claimed": True, "reconcile_only": False})
    outcome = _consumer(http).run_once()
    assert outcome["outcomes"][0] == {"task_id": TASK["task_id"], "kind": "approval_wait",
                                      "dispatched": False}
    assert not any(path.endswith("/stage-claim") for path in http.calls)
    assert not any(path.endswith("/acp-root/run") for path in http.calls)


def test_consumer_reconciles_only_and_never_reruns_when_a_root_exists():
    http = _Http(claim={"claimed": False, "reconcile_only": True, "reason": "root_exists"},
                 status={"status": "settled", "root_run_id": "r"})
    outcome = _consumer(http).run_once()
    assert outcome["outcomes"][0]["reconcile_only"] is True
    assert outcome["outcomes"][0]["status_receipt"] == {"status": "settled", "root_run_id": "r"}
    assert any(path.endswith("/acp-root/status") for path in http.calls)
    assert not any(path.endswith("/stage-dispatch-intent") for path in http.calls)
    assert not any(path.endswith("/acp-root/run") for path in http.calls)


def test_consumer_never_dispatches_when_the_dispatch_intent_is_refused():
    http = _Http(claim={"claimed": True, "reconcile_only": False},
                 intent={"intent": False, "reason": "lease_not_held_or_intent_exists"})
    outcome = _consumer(http).run_once()
    assert outcome["outcomes"][0] == {"task_id": TASK["task_id"], "claimed": True,
                                      "intent": False,
                                      "reason": "lease_not_held_or_intent_exists"}
    assert not any(path.endswith("/acp-root/run") for path in http.calls)


def test_derive_call_identity_matches_the_backend_attempt_binding():
    import hashlib

    from packages.contracts.research_judgment import attempt_binding

    task_id = "task_" + "a" * 32
    binding = attempt_binding(1, "strategy_draft", 1)
    expected = "byq-judgment-" + hashlib.sha256(
        f"{task_id}:{binding}".encode("utf-8")).hexdigest()[:32]
    assert consumer_mod.derive_call_identity(task_id, 1, "strategy_draft", 1) == expected


def test_consumer_reconcile_tolerates_a_missing_root():
    # A dispatch-intent with no root yet (run in flight / response lost) must
    # reconcile to "no_root_yet", not crash the loop on a 404.
    class _NoRootHttp(_Http):
        def post(self, url: str, headers: dict | None = None,
                 json: dict | None = None, timeout: float | None = None) -> _Response:
            self.calls.append(url)
            if url.endswith("/stage-claim"):
                return _Response({"claimed": False, "reconcile_only": True,
                                  "reason": "dispatch_intent_exists"})
            if url.endswith("/acp-root/status"):
                return _Response({}, status=404)
            raise AssertionError(f"unexpected post {url}")

    http = _NoRootHttp(claim={})
    outcome = _consumer(http).run_once()
    assert outcome["outcomes"][0]["reconcile_only"] is True
    assert outcome["outcomes"][0]["status_receipt"] == {"status": "no_root_yet"}
    assert not any(path.endswith("/acp-root/run") for path in http.calls)
