"""Runner-persisted signed cleanup receipt verification (keyless)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.research_judgment_acp_turn as turn
from app.research_judgment_acp_runner_client import (
    read_cleanup_receipt,
    scope_digest,
    sign_runner_reply,
)

SECRET = b"c" * 32
SCOPE = {
    "task_id": "task_" + "a" * 32,
    "call_identity": "byq-judgment-" + "b" * 32,
    "attempt_binding": "1:strategy_draft:1",
    "root_run_id": "c" * 32,
    "runtime_boot_id": "d" * 32,
    "authority_epoch": 1,
}


def _receipt(**overrides):
    value = {
        "schema_version": "byq-acp-judgment-runner-cleanup.v1",
        "scope_digest": scope_digest(SCOPE),
        "task_id": SCOPE["task_id"], "call_identity": SCOPE["call_identity"],
        "root_run_id": SCOPE["root_run_id"], "runtime_boot_id": SCOPE["runtime_boot_id"],
        "authority_epoch": SCOPE["authority_epoch"], "runner_instance_id": "e" * 64,
        "code": 0, "signal": None, "reason": "process_exit", "cleanup": "proven",
    }
    value.update(overrides)
    value["mac"] = sign_runner_reply(value, SECRET)
    return value


def _persist(directory, raw):
    receipts = Path(directory) / "cleanup-receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{scope_digest(SCOPE)}.json").write_bytes(raw)


def test_a_valid_signed_receipt_verifies(tmp_path):
    _persist(tmp_path, json.dumps(_receipt()).encode())
    assert read_cleanup_receipt(tmp_path, SECRET, SCOPE) is not None


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(cleanup="unknown"),
    lambda r: r.update(runtime_boot_id="f" * 32),   # wrong generation
    lambda r: r.update(root_run_id="f" * 32),        # wrong root
    lambda r: r.update(mac="0" * 64),                # wrong signature
    lambda r: r.update(schema_version="other"),
])
def test_a_tampered_receipt_never_proves_cleanup(tmp_path, mutate):
    receipt = _receipt()
    mutate(receipt)
    _persist(tmp_path, json.dumps(receipt).encode())
    assert read_cleanup_receipt(tmp_path, SECRET, SCOPE) is None


def test_a_corrupt_or_missing_receipt_never_proves_cleanup(tmp_path):
    assert read_cleanup_receipt(tmp_path, SECRET, SCOPE) is None
    _persist(tmp_path, b"{not json")
    assert read_cleanup_receipt(tmp_path, SECRET, SCOPE) is None


class _Journal:
    def __init__(self, path, phase, begin):
        self.path = Path(path)
        self.path.write_text("{}")
        self._phase = phase
        self._begin = begin

    def snapshot(self):
        return {"phase": self._phase, "begin": self._begin}


BEGIN = {"call_identity": SCOPE["call_identity"], "attempt_binding": SCOPE["attempt_binding"],
         "root": {"root_run_id": SCOPE["root_run_id"], "runtime_boot_id": SCOPE["runtime_boot_id"]}}
TASK = SCOPE["task_id"]


def _recover(tmp_path, monkeypatch, receipt):
    journal = _Journal(tmp_path / "j.json", "prompt_may_have_dispatched", BEGIN)
    calls = []
    monkeypatch.setattr(turn._control, "exact_status", lambda **k: {})
    monkeypatch.setattr(turn._control, "settlement_request",
                        lambda *a, **k: {"sentinel": "settlement"})
    monkeypatch.setattr(turn._control, "submit_settlement_once", lambda **k: {"sentinel": "sub"})
    monkeypatch.setattr(turn._control, "close_settled_root_once",
                        lambda **k: calls.append("close") or {"sentinel": "terminal"})
    out = turn.recover_judgment_acp_root(
        journal=journal, backend_url="http://backend", task_id=TASK,
        trusted_headers={}, cleanup_receipt=receipt)
    return out, calls


def test_restart_with_a_verified_receipt_closes_the_root(tmp_path, monkeypatch):
    out, calls = _recover(tmp_path, monkeypatch, _receipt())
    assert out["status"] == "settled" and out["terminal"] is not None
    assert calls == ["close"]


def test_restart_without_a_receipt_stays_needs_attention(tmp_path, monkeypatch):
    out, calls = _recover(tmp_path, monkeypatch, None)
    assert out["status"] == "settled_needs_attention" and out["terminal"] is None
    assert calls == []
