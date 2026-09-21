#!/usr/bin/env python3
"""Fail-able observer/verdict for the 0.9 step-5 B4 `terminal-dsh-runtime-restart` slice.

Separation of concerns:

* ``format_valid`` — the observations artifact is well formed and every check
  that ran passed. A structurally valid report can still be an unqualified run.
* ``all_pass`` — the slice passed: both REQUIRED scenarios are present and PASS
  with the contract-derived assertions, every required cross-check passed, every
  negative was rejected, and there are no structural violations.

The contract is the only source of truth. The observer derives the real DSH
runtime restart, the attachment durability, the honest-lost / orphan-lost
classification and the terminal-lifetime independence from raw identifiers,
pids, generations and counters, so it never trusts a self-declared
``identityStable``/``assertions_ok``/``all_pass`` boolean.

Distinguishing a *correct* honest ``lost`` from a *not-implemented* / label-only
PASS is explicit:

* generation A must have established a REAL native terminal (a live PTY with a
  marker echoed through it) and a durable BYQ attachment;
* the DSH runtime OS process must have been TRULY terminated and a NEW process
  generation must have started (different runtime pid, advanced generation);
* the honest-loss scenario must then prove a real native failure (old PTY pid
  dead, native session absent, a specific rebind error) and reject a fake
  reattach;
* the orphan scenario must prove a genuinely SURVIVING PTY with no attachment is
  reconciled as ``lost`` and never reused/adopted;
* a merely claimed ``PASS``/``lost`` with no such evidence fails the verdict.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE / "dsh_runtime_restart_contract.v1.json"

DIMENSIONS = ("pty_process", "attachment", "io_rebind", "terminal_identity")
HONEST_LOST_STATUSES = {"lost", "interrupted"}


class Failure(Exception):
    """Raised only for an unreadable contract/observations artifact."""


def _load(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Failure(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Failure(f"malformed artifact: {path}: {exc}") from exc


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Contract-authoritative derivation from raw observations.
# ---------------------------------------------------------------------------

def _derive_honest_lost(observation: dict) -> dict[str, bool]:
    runtime_a = observation.get("runtimeAPid")
    runtime_b = observation.get("runtimeBPid")
    gen_a = observation.get("runtimeAGeneration")
    gen_b = observation.get("runtimeBGeneration")
    real_restart = (
        _is_int(runtime_a) and _is_int(runtime_b) and runtime_a > 0 and runtime_b > 0
        and runtime_a != runtime_b
        and _is_int(gen_a) and _is_int(gen_b) and gen_b > gen_a
        and observation.get("oldPidAliveAfterRuntimeRestart") is False
        and observation.get("pidAliveBeforeFault") is True
    )
    status = observation.get("reattachStatus")
    fake_rejected = (
        observation.get("reattachOk") is False
        and isinstance(status, str) and status in HONEST_LOST_STATUSES
        and _is_nonempty_str(observation.get("rebindError"))
        and observation.get("identityStable") is not True
        and observation.get("returnedSessionId") is None
        and observation.get("returnedPid") is None
    )
    conversation_ok = (
        observation.get("conversationSurvived") is True
        and observation.get("conversationStatusAfterLoss") == "active"
        and _is_nonempty_str(observation.get("conversationId"))
    )
    job_ok = (
        observation.get("durableJobSurvived") is True
        and observation.get("durableJobStatusAfterLoss") == "active"
        and _is_nonempty_str(observation.get("durableJobId"))
    )
    return {
        "byq_minted_attachment": observation.get("byqMintedAttachmentId") is True
        and observation.get("attachmentIdIsNotNativeId") is True,
        "durable_attachment_loaded": observation.get("durableStoreFilePresent") is True
        and observation.get("durableRecordsLoadedSameId") is True,
        "fresh_adapter_os_process": observation.get("freshAdapterOsProcess") is True
        and _is_int(observation.get("adapterAPid")) and _is_int(observation.get("adapterBPid"))
        and observation.get("adapterAPid") != observation.get("adapterBPid"),
        "generation_a_native_terminal_real": observation.get("marker1InFirstViewport") == 1
        and observation.get("pidAliveBeforeFault") is True and _is_int(observation.get("nativePid")),
        "real_dsh_runtime_restart": real_restart,
        "old_pty_pid_dead": observation.get("oldPidAliveAfterRuntimeRestart") is False,
        "native_session_absent": observation.get("nativeSessionPresent") is False
        and observation.get("nativeSessionsInNewRuntime") == 0,
        "honest_lost_status": fake_rejected,
        "fake_reattach_rejected": observation.get("fakeReattachRejected") is True
        and observation.get("returnedSessionId") is None and observation.get("returnedPid") is None
        and observation.get("identityStable") is not True,
        "reattach_retry_same_loss": observation.get("reattachRetrySameLoss") is True,
        "conversation_survived": conversation_ok,
        "durable_job_survived": job_ok,
        "terminal_not_defining_conversation": observation.get("terminalLifetimeDefinesConversation") is False,
    }


def _derive_orphan_lost(observation: dict) -> dict[str, bool]:
    conversation_ok = (
        observation.get("conversationSurvived") is True
        and observation.get("conversationStatusAfter") == "active"
        and _is_nonempty_str(observation.get("conversationId"))
    )
    job_ok = (
        observation.get("durableJobSurvived") is True
        and observation.get("durableJobStatusAfter") == "active"
        and _is_nonempty_str(observation.get("durableJobId"))
    )
    return {
        "byq_minted_attachment": observation.get("byqMintedAttachmentId") is True
        and observation.get("attachmentIdIsNotNativeId") is True,
        "durable_attachment_loaded": observation.get("durableStoreFilePresent") is True
        and observation.get("durableRecordsLoadedSameId") is True,
        "fresh_adapter_os_process": observation.get("freshAdapterOsProcess") is True
        and _is_int(observation.get("adapterAPid")) and _is_int(observation.get("adapterBPid"))
        and observation.get("adapterAPid") != observation.get("adapterBPid"),
        "orphan_record_dropped": observation.get("dropped") is True
        and observation.get("remainingAttachmentRecords") == 0,
        "surviving_pty_alive": observation.get("nativePtyAliveBeforeDrop") is True
        and observation.get("nativePtyAliveAfterDrop") is True and _is_int(observation.get("nativePid")),
        "orphan_reconcile_ran": observation.get("orphanReconcileRan") is True,
        "orphan_detected": observation.get("orphanNativeSessionsDetected") == 1,
        "orphan_classified_lost": observation.get("orphanClassified") == "lost",
        "orphan_not_reused": observation.get("orphanReused") is False
        and observation.get("orphanAdoptedAsAttachment") is False,
        "orphan_reuse_attempt_rejected": observation.get("orphanReuseAttemptError") == "ORPHAN_NOT_REUSABLE",
        "old_attachment_rejected": observation.get("oldAttachmentIdReattachError") == "UNKNOWN_ATTACHMENT",
        "orphan_cleanup_no_orphans": observation.get("cleanupKilledOrphan") is True
        and observation.get("orphanPidAliveAfterCleanup") is False
        and observation.get("orphans") == 0
        and observation.get("nativeSessionsAfterCleanup") == 0,
        "conversation_survived": conversation_ok,
        "durable_job_survived": job_ok,
        "terminal_not_defining_conversation": observation.get("terminalLifetimeDefinesConversation") is False,
    }


def _derive_durable(observation: dict) -> dict[str, bool]:
    return {
        "attachment_id_byq_minted": observation.get("attachmentIdByqMinted") is True,
        "attachment_id_not_native_identity": observation.get("attachmentIdNotNativeIdentity") is True,
        "durable_store_persisted": observation.get("durableStorePersisted") is True,
        "reloaded_same_attachment_id": observation.get("reloadedSameAttachmentId") is True,
        "audit_linkage_present": observation.get("auditLinkagePresent") is True,
        "record_has_owner_generation_epoch_state": observation.get("recordHasOwnerGenerationEpochState") is True,
        "no_second_session_store": observation.get("oneStoreFile") is True,
    }


def _derive_runtime_restart(observation: dict) -> dict[str, bool]:
    runtime_a = observation.get("runtimeAPid")
    runtime_b = observation.get("runtimeBPid")
    gen_a = observation.get("runtimeAGeneration")
    gen_b = observation.get("runtimeBGeneration")
    return {
        "runtime_os_process_restarted": _is_int(runtime_a) and _is_int(runtime_b)
        and runtime_a > 0 and runtime_b > 0 and runtime_a != runtime_b
        and observation.get("runtimeOsProcessRestart") is True,
        "runtime_generation_advanced": _is_int(gen_a) and _is_int(gen_b) and gen_b > gen_a
        and observation.get("dshRuntimeRestarted") is True,
        "generation_a_pty_was_alive": observation.get("pidAliveBeforeFault") is True,
        "old_pty_pid_dead_after_restart": observation.get("oldPidAliveAfterRuntimeRestart") is False,
        "new_runtime_has_no_sessions": observation.get("nativeSessionsInNewRuntime") == 0,
    }


def _derive_permission(observation: dict) -> dict[str, bool]:
    return {
        "foreign_principal_rejected": observation.get("foreignPrincipalError") == "UNAUTHORIZED_PRINCIPAL",
        "foreign_owner_send_rejected": observation.get("foreignSendError") == "FOREIGN_SESSION",
        "foreign_owner_read_rejected": observation.get("foreignReadError") == "FOREIGN_SESSION",
    }


def _derive_stale(observation: dict) -> dict[str, bool]:
    return {
        "stale_generation_rejected": observation.get("staleGenerationError") == "STALE_GENERATION",
        "stale_epoch_rejected": observation.get("staleEpochError") == "STALE_EPOCH",
        "orphan_world_generation_fenced": observation.get("orphanWorldStaleGenerationError") == "STALE_GENERATION",
        "orphan_world_epoch_fenced": observation.get("orphanWorldStaleEpochError") == "STALE_EPOCH",
    }


def _derive_wrong_terminal(observation: dict) -> dict[str, bool]:
    requested = observation.get("requestedUnknownSessionId")
    real = observation.get("realSessionId")
    return {
        "unknown_attachment_rejected": observation.get("unknownAttachmentError") == "UNKNOWN_ATTACHMENT",
        "wrong_terminal_does_not_reach_real_pty": observation.get("unknownReadError") == "NO_SESSION"
        and _is_nonempty_str(real) and requested != real,
    }


def _derive_idempotent(observation: dict) -> dict[str, bool]:
    return {
        "reattach_retry_same_loss": observation.get("reattachRetrySameLoss") is True,
        "orphan_reconcile_idempotent": observation.get("orphanReconcileIdempotent") is True,
        "close_idempotent": observation.get("closeIdempotent") is True,
    }


def _derive_cleanup(observation: dict) -> dict[str, bool]:
    return {
        "restart_world_no_orphans": observation.get("restartWorldOrphans") == 0,
        "orphan_world_killed_orphan": observation.get("orphanCleanupKilled") is True,
        "orphan_pid_dead_after_cleanup": observation.get("orphanPidAliveAfterCleanup") is False,
        "no_native_sessions_after_cleanup": observation.get("nativeSessionsAfterCleanup") == 0,
    }


def _derive_lifetime(observation: dict) -> dict[str, bool]:
    return {
        "restart_conversation_survived": observation.get("restartConversationSurvived") is True
        and observation.get("conversationStatusAfterLoss") == "active",
        "restart_durable_job_survived": observation.get("restartDurableJobSurvived") is True
        and observation.get("durableJobStatusAfterLoss") == "active",
        "orphan_conversation_survived": observation.get("orphanConversationSurvived") is True
        and observation.get("orphanConversationStatus") == "active",
        "orphan_durable_job_survived": observation.get("orphanDurableJobSurvived") is True
        and observation.get("orphanDurableJobStatus") == "active",
    }


_SCENARIO_DERIVERS: dict[str, Callable[[dict], dict[str, bool]]] = {
    "honest_lost": _derive_honest_lost,
    "orphan_lost": _derive_orphan_lost,
}

_CHECK_DERIVERS: dict[str, Callable[[dict], dict[str, bool]]] = {
    "durable-attachment-lifecycle": _derive_durable,
    "real-dsh-runtime-restart": _derive_runtime_restart,
    "permission-boundary": _derive_permission,
    "stale-generation-fenced": _derive_stale,
    "wrong-terminal-rejected": _derive_wrong_terminal,
    "idempotent-transitions": _derive_idempotent,
    "cleanup-no-orphans": _derive_cleanup,
    "terminal-lifetime-independent": _derive_lifetime,
}

_FORBIDDEN = ("required", "assertions_ok", "coverage", "allowed_continuity",
              "forbidden_continuity", "expected_dimensions")


def _check_scenario(row: dict, spec: dict, failures: list[str]) -> dict:
    row_id = row.get("id")
    ctx = f"scenario[{row_id}]"
    result = row.get("result")
    required = bool(spec.get("required", False))
    expected_assertions = list(spec.get("assertions", []))
    out: dict[str, Any] = {"id": row_id, "result": result, "required": required,
                           "dimensions": row.get("dimensions"), "assertions": {}, "assertions_ok": False}
    for forbidden in _FORBIDDEN:
        if forbidden in row:
            failures.append(f"{ctx}: observation may not declare '{forbidden}'; the contract is authoritative")

    if result not in {"PASS", "FAIL", "NOT_RUN", "BLOCKED"}:
        failures.append(f"{ctx}: invalid result {result!r}")
        return out
    if result in {"NOT_RUN", "BLOCKED"}:
        if not _is_nonempty_str(row.get("not_run_reason")):
            failures.append(f"{ctx}: {result} without a reason")
        out["not_run_reason"] = row.get("not_run_reason")
        return out
    if result != "PASS":
        failures.append(f"{ctx}: result {result!r} is not PASS")
        return out
    if spec.get("requires_fault") and row.get("fault_applied") is not True:
        failures.append(f"{ctx}: fault_applied is not true (the fault was not actually exercised)")

    dimensions = row.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        failures.append(f"{ctx}: PASS without the exact four-way dimensions {list(DIMENSIONS)}")
        return out

    observation = row.get("observation")
    if not isinstance(observation, dict):
        failures.append(f"{ctx}: PASS without an observation object")
        return out

    deriver = _SCENARIO_DERIVERS.get(spec.get("expects"))
    if deriver is None:
        failures.append(f"{ctx}: no contract deriver for expects={spec.get('expects')!r}")
        return out
    derived = deriver(observation)
    out["assertions"] = {name: bool(derived.get(name)) for name in expected_assertions}
    out["assertions_ok"] = (not expected_assertions) or all(out["assertions"].values())
    if not out["assertions_ok"]:
        false_names = [name for name, value in out["assertions"].items() if not value]
        failures.append(f"{ctx}: false assertions {false_names or 'none-derived'}")

    if spec.get("expects") == "honest_lost":
        if derived.get("real_dsh_runtime_restart") is not True:
            failures.append(f"{ctx}: honest loss claimed without a real DSH runtime restart")
        if derived.get("honest_lost_status") is True:
            if dimensions.get("terminal_identity") not in {"lost", "changed"}:
                failures.append(f"{ctx}: honest-lost status but dimensions do not record a lost identity")
            if dimensions.get("attachment") != "present":
                failures.append(f"{ctx}: honest-lost scenario must retain the durable attachment")
        if derived.get("fake_reattach_rejected") is not True:
            failures.append(f"{ctx}: fake reattach not rejected")
        if derived.get("terminal_not_defining_conversation") is not True:
            failures.append(f"{ctx}: terminal lifetime must not define conversation/durable-job lifetime")
    if spec.get("expects") == "orphan_lost":
        if derived.get("surviving_pty_alive") is not True:
            failures.append(f"{ctx}: orphan reconciliation claimed without a surviving PTY")
        if derived.get("orphan_classified_lost") is True:
            if dimensions.get("terminal_identity") not in {"lost", "changed"}:
                failures.append(f"{ctx}: orphan lost but dimensions do not record a lost identity")
            if dimensions.get("attachment") != "absent" or dimensions.get("pty_process") != "present":
                failures.append(f"{ctx}: orphan scenario must record a surviving PTY with no attachment")
        if derived.get("orphan_not_reused") is not True:
            failures.append(f"{ctx}: a surviving PTY with no attachment must never be reused/adopted")
    out["observation_keys"] = sorted(observation.keys())
    return out


def _check_cross_check(item: dict, spec: dict, failures: list[str]) -> dict:
    check_id = item.get("id")
    ctx = f"cross_check[{check_id}]"
    out: dict[str, Any] = {"id": check_id, "result": item.get("result"), "assertions": {}, "assertions_ok": False}
    for forbidden in _FORBIDDEN:
        if forbidden in item:
            failures.append(f"{ctx}: observation may not declare '{forbidden}'; the contract is authoritative")
    if item.get("result") != "PASS":
        failures.append(f"{ctx}: result {item.get('result')!r} is not PASS")
        return out
    observation = item.get("observation")
    if not isinstance(observation, dict):
        failures.append(f"{ctx}: PASS without an observation object")
        return out
    deriver = _CHECK_DERIVERS.get(check_id)
    if deriver is None:
        failures.append(f"{ctx}: no contract deriver for a required cross-check")
        return out
    expected_assertions = list(spec.get("assertions", []))
    derived = deriver(observation)
    out["assertions"] = {name: bool(derived.get(name)) for name in expected_assertions}
    out["assertions_ok"] = all(out["assertions"].values())
    if not out["assertions_ok"]:
        false_names = [name for name, value in out["assertions"].items() if not value]
        failures.append(f"{ctx}: false assertions {false_names or 'none-derived'}")
    out["observation_keys"] = sorted(observation.keys())
    return out


def _check_negatives(observations: dict, contract: dict, failures: list[str]) -> list[dict]:
    negatives = observations.get("negatives")
    if not isinstance(negatives, list) or not negatives:
        failures.append("negatives must be a non-empty list")
        return []
    rows = []
    for index, item in enumerate(negatives):
        if not isinstance(item, dict):
            failures.append(f"negatives[{index}] is not an object")
            continue
        rejected = item.get("rejected") is True
        rows.append({"kind": item.get("kind"), "rejected": rejected,
                     "errorCode": item.get("errorCode"), "errorClass": item.get("errorClass")})
        if contract.get("negatives_must_all_be_rejected") and not rejected:
            failures.append(f"negative {item.get('kind')!r} was not rejected")
    return rows


def compute_verdict(contract: dict, observations: dict, *, allow_unit_fixture: bool = False) -> dict:
    failures: list[str] = []

    if not isinstance(observations, dict):
        raise Failure("observations must be an object")

    candidate = contract["candidate"]
    observed_candidate = observations.get("candidate")
    if not isinstance(observed_candidate, dict) or observed_candidate.get("release") != candidate["release"]:
        failures.append(f"candidate mismatch: expected {candidate['release']!r}, got {observed_candidate!r}")

    required_class = contract.get("required_evidence_class")
    observed_class = observations.get("evidence_class")
    if allow_unit_fixture:
        if not _is_nonempty_str(observed_class):
            failures.append("evidence_class must be declared")
    elif observed_class != required_class:
        failures.append(
            f"evidence_class {observed_class!r} is not native runtime evidence {required_class!r}; "
            "a synthetic/unit fixture or a format-layer artifact is not a B4 attachment pass")

    llm = observations.get("llm")
    if not isinstance(llm, dict) or llm.get("class") != contract["llm_evidence_class"] \
            or llm.get("real_llm_quality") is True:
        failures.append("LLM evidence class must be explicitly not-applicable with real_llm_quality not true")

    required = {item["id"]: item for item in contract.get("required_scenarios", [])}
    optional = {item["id"]: item for item in contract.get("optional_scenarios", [])}
    row_specs = {**required, **optional}
    check_specs = {item["id"]: item for item in contract.get("required_cross_checks", [])}

    scenarios_value = observations.get("scenarios")
    if not isinstance(scenarios_value, list):
        failures.append("scenarios must be a list")
        scenarios_value = []
    observed_ids = [item.get("id") if isinstance(item, dict) else None for item in scenarios_value]
    if len(observed_ids) != len(set(map(str, observed_ids))):
        failures.append("duplicate scenario id in observations")

    scenario_results = []
    for item in scenarios_value:
        if not isinstance(item, dict):
            failures.append("scenario entry is not an object")
            continue
        spec = row_specs.get(item.get("id"), {"required": False})
        scenario_results.append(_check_scenario(item, spec, failures))

    seen = set(observed_ids)
    for scenario_id in required:
        if scenario_id not in seen:
            failures.append(f"missing required scenario {scenario_id!r}")

    rows = {row["id"]: row for row in scenario_results}
    required_coverage: dict[str, str] = {}
    for scenario_id in required:
        row = rows.get(scenario_id)
        required_coverage[scenario_id] = row["result"] if row is not None else "MISSING"
    optional_coverage: dict[str, str] = {}
    for scenario_id in optional:
        row = rows.get(scenario_id)
        optional_coverage[scenario_id] = row["result"] if row is not None else "MISSING"

    required_coverage_ok = all(value == "PASS" for value in required_coverage.values()) \
        and len(required_coverage) == len(required) \
        and all(row.get("assertions_ok") for row in scenario_results if row["id"] in required)

    checks_value = observations.get("cross_checks")
    if not isinstance(checks_value, list):
        failures.append("cross_checks must be a list")
        checks_value = []
    check_ids = [item.get("id") if isinstance(item, dict) else None for item in checks_value]
    if len(check_ids) != len(set(map(str, check_ids))):
        failures.append("duplicate cross-check id in observations")
    check_results = []
    for item in checks_value:
        if not isinstance(item, dict):
            failures.append("cross-check entry is not an object")
            continue
        spec = check_specs.get(item.get("id"), {"required": False})
        check_results.append(_check_cross_check(item, spec, failures))
    for check_id in check_specs:
        if check_id not in set(check_ids):
            failures.append(f"missing required cross-check {check_id!r}")
    cross_checks_ok = all(
        row["result"] == "PASS" and row["assertions_ok"]
        for row in check_results if row["id"] in check_specs
    ) and len([row for row in check_results if row["id"] in check_specs]) == len(check_specs)

    negatives = _check_negatives(observations, contract, failures)
    negatives_ok = bool(negatives) and all(item["rejected"] for item in negatives)

    failed = [row["id"] for row in scenario_results if row["result"] == "FAIL"]
    uncovered = [row["id"] for row in scenario_results if row["result"] in {"NOT_RUN", "BLOCKED"}]
    reason_uncovered = [scenario_id for scenario_id, value in required_coverage.items()
                        if value in {"NOT_RUN", "BLOCKED", "MISSING"}]

    format_valid = not failures
    all_pass = format_valid and not failed and required_coverage_ok and cross_checks_ok and negatives_ok
    return {
        "schema_version": "byq-v090-step5-b4-verdict.v1",
        "all_pass": all_pass,
        "format_valid": format_valid,
        "qualification_passed": all_pass,
        "exit_code": 0 if all_pass else 1,
        "candidate": candidate,
        "evidence_class": observed_class,
        "llm_evidence_class": contract["llm_evidence_class"],
        "existence_dimensions": list(DIMENSIONS),
        "required_scenario_count": len(required),
        "optional_scenario_count": len(optional),
        "required_coverage": required_coverage,
        "required_coverage_ok": required_coverage_ok,
        "optional_coverage": optional_coverage,
        "cross_checks_ok": cross_checks_ok,
        "failed_scenarios": failed,
        "uncovered_scenarios": uncovered,
        "reason_uncovered": reason_uncovered,
        "negatives": negatives,
        "negatives_ok": negatives_ok,
        "scenarios": scenario_results,
        "cross_checks": check_results,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Legacy (pre-fix) algorithm, executed only to prove the pre-fix behaviour.
# ---------------------------------------------------------------------------

def legacy_compute_verdict(contract: dict, observations: dict) -> dict:
    """Pre-fix algorithm: the result string alone decided; it ignored the
    honest-lost/orphan distinction, derived assertions, cross-checks and
    negatives, so a not-implemented/label-only or fake-reattach report still
    passed."""
    failures: list[str] = []
    scenarios = observations.get("scenarios") if isinstance(observations.get("scenarios"), list) else []
    for item in scenarios:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if result == "FAIL":
            failures.append(f"scenario {item.get('id')!r} FAIL")
        elif result in {"NOT_RUN", "BLOCKED"}:
            if not _is_nonempty_str(item.get("not_run_reason")):
                failures.append(f"scenario {item.get('id')!r} {result} without reason")
        elif result == "PASS":
            pass
        else:
            failures.append(f"scenario {item.get('id')!r} invalid result {result!r}")
    all_pass = not failures
    return {"algorithm": "legacy-pre-fix", "all_pass": all_pass, "exit_code": 0 if all_pass else 1,
            "failures": failures}


# ---------------------------------------------------------------------------
# Unit fixture + negative controls (selfcheck).
# ---------------------------------------------------------------------------

def _runtime_restart_observation() -> dict:
    return {
        "attachmentId": "byq-att-abc123", "nativeSessionId": "pty-1", "nativePid": 4242,
        "expectedAttachmentId": "byq-att-abc123", "expectedSessionId": "pty-1", "expectedPid": 4242,
        "conversationId": "byq-conv-1", "durableJobId": "byq-job-1",
        "byqMintedAttachmentId": True, "attachmentIdIsNotNativeId": True,
        "durableStoreFilePresent": True, "durableRecordsLoadedSameId": True,
        "recordHasOwnerGenerationEpochState": True, "auditLinkagePresent": True,
        "auditEvents": ["create", "lost"],
        "marker1": "B4_RESTART_MARK_ONE_x", "marker1InFirstViewport": 1, "pidAliveBeforeFault": True,
        "runtimeAPid": 1111, "runtimeAGeneration": 1, "runtimeBPid": 2222, "runtimeBGeneration": 2,
        "runtimeOsProcessRestart": True, "dshRuntimeRestarted": True,
        "oldPidAliveAfterRuntimeRestart": False, "oldPidAliveReported": False,
        "adapterAPid": 3333, "adapterBPid": 4444, "freshAdapterOsProcess": True,
        "reattachAttempted": True, "reattachOk": False, "reattachStatus": "lost",
        "rebindError": "NATIVE_SESSION_UNAVAILABLE", "nativeSessionPresent": False,
        "nativeSessionsInNewRuntime": 0, "returnedSessionId": None, "returnedPid": None,
        "identityStable": False, "fakeReattachRejected": True, "reattachRetrySameLoss": True,
        "conversationStatusAfterLoss": "active", "durableJobStatusAfterLoss": "active",
        "conversationSurvived": True, "durableJobSurvived": True, "terminalLifetimeDefinesConversation": False,
        "foreignPrincipalError": "UNAUTHORIZED_PRINCIPAL", "staleGenerationError": "STALE_GENERATION",
        "staleEpochError": "STALE_EPOCH", "foreignSendError": "FOREIGN_SESSION",
        "foreignReadError": "FOREIGN_SESSION", "unknownAttachmentError": "UNKNOWN_ATTACHMENT",
        "unknownReadError": "NO_SESSION", "requestedUnknownSessionId": "pty-x",
        "unknownReadRealSessionId": "pty-1", "closeIdempotent": True, "runtimeShutdownOrphans": 0,
    }


def _orphan_observation() -> dict:
    return {
        "attachmentId": "byq-att-abc123", "nativeSessionId": "pty-1", "nativePid": 4242,
        "conversationId": "byq-conv-1", "durableJobId": "byq-job-1",
        "byqMintedAttachmentId": True, "attachmentIdIsNotNativeId": True,
        "durableStoreFilePresent": True, "durableRecordsLoadedSameId": True,
        "nativePtyAliveBeforeDrop": True, "dropped": True, "nativePtyAliveAfterDrop": True,
        "remainingAttachmentRecords": 0, "adapterAPid": 3333, "adapterBPid": 4444,
        "freshAdapterOsProcess": True, "orphanReconcileRan": True, "orphanNativeSessionsDetected": 1,
        "orphanClassified": "lost", "orphanReused": False, "orphanAdoptedAsAttachment": False,
        "orphanReuseAttemptError": "ORPHAN_NOT_REUSABLE", "orphanReconcileIdempotent": True,
        "oldAttachmentIdReattachError": "UNKNOWN_ATTACHMENT",
        "conversationStatusAfter": "active", "durableJobStatusAfter": "active",
        "conversationSurvived": True, "durableJobSurvived": True, "terminalLifetimeDefinesConversation": False,
        "foreignPrincipalError": "UNAUTHORIZED_PRINCIPAL", "staleGenerationError": "STALE_GENERATION",
        "staleEpochError": "STALE_EPOCH", "foreignSendError": "FOREIGN_SESSION",
        "foreignReadError": "FOREIGN_SESSION", "unknownAttachmentError": "UNKNOWN_ATTACHMENT",
        "cleanupKilledOrphan": True, "orphanPidAliveAfterCleanup": False, "orphans": 0,
        "nativeSessionsAfterCleanup": 0, "cleanupOrphansFound": 1,
    }


def _scenario_fixture(scenario_id: str) -> dict:
    if scenario_id == "dsh-runtime-restart-terminal-lost":
        return {
            "id": scenario_id, "result": "PASS", "fault_applied": True,
            "dimensions": {"pty_process": "absent", "attachment": "present",
                           "io_rebind": "rejected", "terminal_identity": "lost"},
            "observation": _runtime_restart_observation(),
        }
    return {
        "id": scenario_id, "result": "PASS", "fault_applied": True,
        "dimensions": {"pty_process": "present", "attachment": "absent",
                       "io_rebind": "rejected", "terminal_identity": "lost"},
        "observation": _orphan_observation(),
    }


def _cross_checks() -> list[dict]:
    return [
        {"id": "durable-attachment-lifecycle", "result": "PASS",
         "observation": {"attachmentIdByqMinted": True, "attachmentIdNotNativeIdentity": True,
                         "durableStorePersisted": True, "reloadedSameAttachmentId": True,
                         "recordHasOwnerGenerationEpochState": True, "auditLinkagePresent": True,
                         "oneStoreFile": True}},
        {"id": "real-dsh-runtime-restart", "result": "PASS",
         "observation": {"runtimeAPid": 1111, "runtimeBPid": 2222,
                         "runtimeAGeneration": 1, "runtimeBGeneration": 2,
                         "runtimeOsProcessRestart": True, "dshRuntimeRestarted": True,
                         "pidAliveBeforeFault": True,
                         "oldPidAliveAfterRuntimeRestart": False, "nativeSessionsInNewRuntime": 0}},
        {"id": "permission-boundary", "result": "PASS",
         "observation": {"foreignPrincipalError": "UNAUTHORIZED_PRINCIPAL",
                         "foreignSendError": "FOREIGN_SESSION", "foreignReadError": "FOREIGN_SESSION"}},
        {"id": "stale-generation-fenced", "result": "PASS",
         "observation": {"staleGenerationError": "STALE_GENERATION", "staleEpochError": "STALE_EPOCH",
                         "orphanWorldStaleGenerationError": "STALE_GENERATION",
                         "orphanWorldStaleEpochError": "STALE_EPOCH"}},
        {"id": "wrong-terminal-rejected", "result": "PASS",
         "observation": {"unknownAttachmentError": "UNKNOWN_ATTACHMENT", "unknownReadError": "NO_SESSION",
                         "requestedUnknownSessionId": "pty-x", "realSessionId": "pty-1"}},
        {"id": "idempotent-transitions", "result": "PASS",
         "observation": {"reattachRetrySameLoss": True, "orphanReconcileIdempotent": True,
                         "closeIdempotent": True}},
        {"id": "cleanup-no-orphans", "result": "PASS",
         "observation": {"restartWorldOrphans": 0, "orphanCleanupKilled": True,
                         "orphanPidAliveAfterCleanup": False, "nativeSessionsAfterCleanup": 0}},
        {"id": "terminal-lifetime-independent", "result": "PASS",
         "observation": {"restartConversationSurvived": True, "conversationStatusAfterLoss": "active",
                         "restartDurableJobSurvived": True, "durableJobStatusAfterLoss": "active",
                         "orphanConversationSurvived": True, "orphanConversationStatus": "active",
                         "orphanDurableJobSurvived": True, "orphanDurableJobStatus": "active"}},
    ]


def valid_fixture(contract: dict) -> dict:
    """Synthetic UNIT fixture. Never runtime PASS evidence (evidence_class=unit-fixture)."""
    scenarios = [_scenario_fixture(spec["id"]) for spec in contract.get("required_scenarios", [])]
    for spec in contract.get("optional_scenarios", []):
        scenarios.append({"id": spec["id"], "result": "NOT_RUN", "fault_applied": False,
                          "dimensions": {dim: "unknown" for dim in DIMENSIONS},
                          "not_run_reason": "injected unit fixture"})
    return {
        "schema_version": "byq-v090-step5-b4-native-observations.v1",
        "evidence_class": "unit-fixture",
        "candidate": dict(contract["candidate"]),
        "llm": {"class": contract["llm_evidence_class"], "real_llm_quality": False,
                "note": "negative-control unit fixture (not runtime evidence)"},
        "scenarios": scenarios,
        "cross_checks": _cross_checks(),
        "negatives": [
            {"kind": "fake-reattach-after-dsh-runtime-restart", "rejected": True,
             "errorCode": "NATIVE_SESSION_UNAVAILABLE"},
            {"kind": "orphan-reuse", "rejected": True, "errorCode": "ORPHAN_NOT_REUSABLE"},
            {"kind": "stale-generation", "rejected": True, "errorCode": "STALE_GENERATION"},
        ],
    }


def _mutations(fixture: dict) -> list[tuple[str, dict]]:
    mutations: list[tuple[str, dict]] = []

    def add(name: str, mutate) -> None:
        value = copy.deepcopy(fixture)
        mutate(value)
        mutations.append((name, value))

    def scenario(value: dict, scenario_id: str) -> dict:
        return next(item for item in value["scenarios"] if item["id"] == scenario_id)

    def check(value: dict, check_id: str) -> dict:
        return next(item for item in value["cross_checks"] if item["id"] == check_id)

    restart_id = "dsh-runtime-restart-terminal-lost"
    orphan_id = "surviving-pty-without-attachment-lost"

    add("missing-required-scenario", lambda v: v["scenarios"].pop(0))
    add("required-scenario-fail", lambda v: scenario(v, restart_id).update({"result": "FAIL"}))
    add("required-blocked", lambda v: scenario(v, restart_id).update(
        {"result": "BLOCKED", "not_run_reason": "injected"}))
    add("blocked-without-reason", lambda v: scenario(v, restart_id).update(
        {"result": "BLOCKED", "fault_applied": False, "not_run_reason": ""}))
    add("fabricated-reattach-session-drift", lambda v: scenario(v, restart_id)["observation"].update(
        {"returnedSessionId": "pty-1", "returnedPid": 4242, "reattachOk": True,
         "reattachStatus": "reattached", "identityStable": True}))
    add("fabricated-reattach-pid-drift", lambda v: scenario(v, restart_id)["observation"].update(
        {"returnedPid": 4242, "identityStable": True, "reattachOk": True,
         "reattachStatus": "reattached"}))
    add("false-identity-claim", lambda v: scenario(v, restart_id)["observation"].update(
        {"identityStable": True, "reattachOk": True, "reattachStatus": "reattached"}))
    add("fault-not-applied", lambda v: scenario(v, restart_id).update({"fault_applied": False}))
    add("missing-dimension", lambda v: scenario(v, restart_id)["dimensions"].pop("terminal_identity"))
    add("dimension-contradicts-lost", lambda v: scenario(v, restart_id)["dimensions"].update(
        {"terminal_identity": "stable"}))
    add("label-only-pass-positive", lambda v: scenario(v, restart_id)["observation"].update(
        {"marker1InFirstViewport": 0, "pidAliveBeforeFault": False,
         "durableRecordsLoadedSameId": False}))
    add("not-implemented-positive-missing", lambda v: scenario(v, restart_id).update({"result": "FAIL"}))
    add("not-implemented-label-pass", lambda v: (
        scenario(v, restart_id)["observation"].update(
            {"durableStoreFilePresent": False, "durableRecordsLoadedSameId": False,
             "freshAdapterOsProcess": False, "marker1InFirstViewport": 0}),
        scenario(v, orphan_id)["observation"].update(
            {"dropped": False, "remainingAttachmentRecords": 1}),
    ))
    add("runtime-not-restarted", lambda v: scenario(v, restart_id)["observation"].update(
        {"runtimeBPid": 1111}))
    add("runtime-generation-not-advanced", lambda v: scenario(v, restart_id)["observation"].update(
        {"runtimeBGeneration": 1}))
    add("runtime-restart-flag-only", lambda v: scenario(v, restart_id)["observation"].update(
        {"runtimeAPid": 1111, "runtimeBPid": 1111}))
    add("lost-without-native-failure", lambda v: scenario(v, restart_id)["observation"].update(
        {"oldPidAliveAfterRuntimeRestart": True, "nativeSessionPresent": True,
         "nativeSessionsInNewRuntime": 1}))
    add("old-pty-still-alive", lambda v: scenario(v, restart_id)["observation"].update(
        {"oldPidAliveAfterRuntimeRestart": True}))
    add("lost-status-not-lost", lambda v: scenario(v, restart_id)["observation"].update(
        {"reattachOk": True, "reattachStatus": "reattached", "rebindError": None}))
    add("fake-reattach-accepted", lambda v: scenario(v, restart_id)["observation"].update(
        {"fakeReattachRejected": False, "returnedSessionId": "pty-1", "returnedPid": 4242}))
    add("reattach-retry-flips", lambda v: scenario(v, restart_id)["observation"].update(
        {"reattachRetrySameLoss": False}))
    add("conversation-terminated-on-terminal-loss", lambda v: scenario(v, restart_id)["observation"].update(
        {"conversationSurvived": False, "conversationStatusAfterLoss": "terminated",
         "terminalLifetimeDefinesConversation": True}))
    add("durable-job-terminated-on-terminal-loss", lambda v: scenario(v, restart_id)["observation"].update(
        {"durableJobSurvived": False, "durableJobStatusAfterLoss": "terminated",
         "terminalLifetimeDefinesConversation": True}))
    add("durable-not-loaded", lambda v: scenario(v, restart_id)["observation"].update(
        {"durableRecordsLoadedSameId": False}))
    add("orphan-not-surviving", lambda v: scenario(v, orphan_id)["observation"].update(
        {"nativePtyAliveAfterDrop": False, "nativePtyAliveBeforeDrop": False}))
    add("orphan-not-detected", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanNativeSessionsDetected": 0, "orphanClassified": "none"}))
    add("orphan-classified-attached", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanClassified": "attached"}))
    add("orphan-reused", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanReused": True, "orphanReuseAttemptError": None}))
    add("orphan-adopted-as-attachment", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanAdoptedAsAttachment": True}))
    add("orphan-reuse-attempt-accepted", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanReuseAttemptError": "OK"}))
    add("orphan-cleanup-left-alive", lambda v: scenario(v, orphan_id)["observation"].update(
        {"orphanPidAliveAfterCleanup": True, "cleanupKilledOrphan": False,
         "orphans": 1, "nativeSessionsAfterCleanup": 1}))
    add("orphan-dimensions-not-lost", lambda v: scenario(v, orphan_id)["dimensions"].update(
        {"terminal_identity": "stable"}))
    add("orphan-dimensions-hide-surviving-pty", lambda v: scenario(v, orphan_id)["dimensions"].update(
        {"pty_process": "absent"}))
    add("permission-bypass", lambda v: check(v, "permission-boundary")["observation"].update(
        {"foreignSendError": None}))
    add("wrong-terminal-accepted", lambda v: check(v, "wrong-terminal-rejected")["observation"].update(
        {"unknownReadError": "OK"}))
    add("stale-not-fenced", lambda v: check(v, "stale-generation-fenced")["observation"].update(
        {"staleGenerationError": None}))
    add("runtime-restart-cross-check-fake", lambda v: check(v, "real-dsh-runtime-restart")["observation"].update(
        {"runtimeBPid": 1111, "oldPidAliveAfterRuntimeRestart": True}))
    add("lifetime-cross-check-fake", lambda v: check(v, "terminal-lifetime-independent")["observation"].update(
        {"restartConversationSurvived": False, "conversationStatusAfterLoss": "terminated"}))
    add("cleanup-cross-check-fake", lambda v: check(v, "cleanup-no-orphans")["observation"].update(
        {"orphanPidAliveAfterCleanup": True, "nativeSessionsAfterCleanup": 1}))
    add("idempotent-cross-check-fake", lambda v: check(v, "idempotent-transitions")["observation"].update(
        {"closeIdempotent": False}))
    add("durable-cross-check-fake", lambda v: check(v, "durable-attachment-lifecycle")["observation"].update(
        {"attachmentIdByqMinted": False}))
    add("negative-not-rejected", lambda v: v["negatives"][0].update({"rejected": False}))
    add("candidate-mismatch", lambda v: v.update({"candidate": {"release": "dsh-0.1.2rc1"}}))
    add("non-native-evidence-class", lambda v: v.update({"evidence_class": "format-layer"}))
    add("llm-claims-real-quality", lambda v: v["llm"].update({"class": "real-llm", "real_llm_quality": True}))
    add("pass-without-observation", lambda v: scenario(v, restart_id).pop("observation"))
    add("self-declared-coverage", lambda v: scenario(v, restart_id).update(
        {"required": False, "assertions_ok": True}))
    add("fresh-adapter-not-fresh", lambda v: scenario(v, restart_id)["observation"].update(
        {"adapterBPid": 3333}))
    return mutations


def _fully_qualified_fixture(contract: dict) -> dict:
    fixture = valid_fixture(contract)
    fixture["scenarios"] = [_scenario_fixture(spec["id"]) for spec in contract.get("required_scenarios", [])]
    for spec in contract.get("optional_scenarios", []):
        fixture["scenarios"].append({"id": spec["id"], "result": "NOT_RUN", "fault_applied": False,
                                     "dimensions": {dim: "unknown" for dim in DIMENSIONS},
                                     "not_run_reason": "injected unit fixture"})
    return fixture


def selfcheck(contract: dict) -> dict:
    baseline = _fully_qualified_fixture(contract)
    good = compute_verdict(contract, baseline, allow_unit_fixture=True)

    strict_baseline = copy.deepcopy(baseline)
    strict_baseline["evidence_class"] = contract["required_evidence_class"]
    strict_good = compute_verdict(contract, strict_baseline, allow_unit_fixture=False)
    controls = []

    def record(name: str, mutated: dict, *, strict: bool = True) -> None:
        fixed = compute_verdict(contract, mutated, allow_unit_fixture=not strict)
        legacy = legacy_compute_verdict(contract, mutated)
        controls.append({"name": name, "fixed_all_pass": fixed["all_pass"],
                         "fixed_exit_code": fixed["exit_code"], "legacy_all_pass": legacy["all_pass"]})

    for name, mutated in _mutations(strict_baseline):
        record(name, mutated, strict=True)
    all_controls_pass = strict_good["format_valid"] and strict_good["all_pass"] and all(
        (not item["fixed_all_pass"]) for item in controls)
    defect_targeting = [item for item in controls if item["legacy_all_pass"] and not item["fixed_all_pass"]]
    return {
        "schema_version": "byq-v090-step5-b4-negative-controls.v1",
        "known_good_unit_fixture_format_valid": good["format_valid"],
        "known_good_unit_fixture_all_pass": good["all_pass"],
        "control_count": len(controls),
        "controls": controls,
        "all_controls_pass": all_controls_pass,
        "defect_targeting_pre_fix_passed_count": len(defect_targeting),
        "defect_targeting_pre_fix_passed": [item["name"] for item in defect_targeting],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--allow-unit-fixture", action="store_true")
    args = parser.parse_args(argv)

    contract = _load(args.contract)
    if args.selfcheck:
        result = selfcheck(contract)
        code = 0 if result["all_controls_pass"] and result["known_good_unit_fixture_format_valid"] else 1
    else:
        if args.observations is None:
            parser.error("--observations is required unless --selfcheck")
        result = compute_verdict(contract, _load(args.observations), allow_unit_fixture=args.allow_unit_fixture)
        code = result["exit_code"]
        print(json.dumps({"all_pass": result["all_pass"], "format_valid": result["format_valid"],
                          "required_coverage": result["required_coverage"],
                          "cross_checks_ok": result["cross_checks_ok"],
                          "failed_scenarios": result["failed_scenarios"],
                          "uncovered_scenarios": result["uncovered_scenarios"],
                          "negatives_ok": result["negatives_ok"],
                          "failures": result["failures"]}, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
