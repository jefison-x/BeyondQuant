"""Exact Backend result and terminal reconciliation for one ADR-0097 root.

This is a named business control path, not a DSH session manager. Its caller
must durably retain the request before dispatch and must prove ACP cleanup
before reporting settlement. Neither operation repeats a model prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error

from packages.contracts.agent_run_lifecycle import lifecycle_receipt
from packages.contracts.research_judgment import (
    attempt_binding as make_attempt_binding,
    validate_acp_judgment_result_request,
    validate_stage_input,
)

from .research_judgment import ResearchJudgmentError, _http_post


class AcpJudgmentOutcomeUnknown(ResearchJudgmentError):
    """The exact Backend result or terminal outcome has not been proven."""


_SETTLEMENT_REQUEST_SCHEMA = "byq-research-judgment-acp-settlement-request.v1"
_SETTLEMENT_EVIDENCE_SCHEMA = "byq-research-judgment-acp-settlement-evidence.v1"
_SETTLEMENT_RECEIPT_SCHEMA = "byq-research-judgment-acp-settlement-receipt.v1"
_SETTLEMENT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ROOT_ID = re.compile(r"^[0-9a-f]{32}$")
_TASK_ID = re.compile(r"^task_[0-9a-f]{32}$")
_CALL_ID = re.compile(r"^byq-judgment-[0-9a-f]{32}$")
_DSH_RUN_ID = re.compile(r"^byqjudg-[0-9a-f]{32}$")
_JUDGMENT_SESSION_ID = re.compile(r"^byqjdg-[0-9a-f]{32}$")
_AGENT_RUN_ID = re.compile(r"^agent_run_[0-9a-f]{32}$")
_NATIVE_SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_CANCEL_INTENT_ID = re.compile(r"^byqcancel-[0-9a-f]{32}$")


def _matches(pattern: re.Pattern, value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _canonical_sha256(value: object) -> str:
    """Use the Backend's canonical ``_hash`` encoding for settlement identity."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _nonempty(value: object, field: str, *, maximum: int = 128) -> str:
    if (not isinstance(value, str) or not value or value.strip() != value
            or len(value) > maximum):
        raise ResearchJudgmentError(f"ACP judgment settlement {field} is invalid")
    return value


def _validate_settlement_begin(task_id: str, begin: dict) -> dict:
    """Validate the complete Backend begin receipt before deriving any settlement fields."""
    if not isinstance(begin, dict):
        raise ResearchJudgmentError("exact admitted ACP judgment Backend begin receipt is required")
    fields = {"schema_version", "status", "task_id", "call_identity", "attempt_binding",
              "plan_version", "task_version", "stage", "iteration", "call_index",
              "model_call_limit", "stage_input", "root"}
    if "created" in begin:
        fields.add("created")
    if (not isinstance(begin, dict) or set(begin) != fields
            or begin.get("schema_version") != "byq-research-judgment-acp-root-receipt.v1"
            or begin.get("status") != "admitted" or begin.get("task_id") != task_id
            or not _matches(_TASK_ID, task_id)
            or ("created" in begin and type(begin["created"]) is not bool)):
        raise ResearchJudgmentError("exact admitted ACP judgment Backend begin receipt is required")

    root = begin.get("root")
    root_fields = {"root_run_id", "owner_principal", "workspace_id", "actor_principal",
                   "session_id", "trace_id", "runtime_boot_id", "authority_epoch", "dsh_run_id"}
    if not isinstance(root, dict) or set(root) != root_fields:
        raise ResearchJudgmentError("exact ACP judgment Backend root receipt is required")
    if (not _matches(_ROOT_ID, root.get("root_run_id"))
            or not _matches(_ROOT_ID, root.get("runtime_boot_id"))
            or type(root.get("authority_epoch")) is not int
            or not 1 <= root["authority_epoch"] <= 2**63 - 1
            or not _matches(_DSH_RUN_ID, root.get("dsh_run_id"))
            or not _matches(_JUDGMENT_SESSION_ID, root.get("session_id"))
            or root.get("actor_principal") != f"byq-product-agent-{root.get('session_id')}"
            or _nonempty(root.get("owner_principal"), "owner_principal") is None
            or _nonempty(root.get("workspace_id"), "workspace_id") is None
            or _nonempty(root.get("trace_id"), "trace_id") is None):
        raise ResearchJudgmentError("ACP judgment Backend root receipt identity is invalid")

    stage_input = begin.get("stage_input")
    try:
        validate_stage_input(stage_input)
    except (TypeError, ValueError) as error:
        raise ResearchJudgmentError("ACP judgment Backend stage input receipt is invalid") from error
    plan_version = begin.get("plan_version")
    task_version = begin.get("task_version")
    iteration = begin.get("iteration")
    call_index = begin.get("call_index")
    model_call_limit = begin.get("model_call_limit")
    if (any(type(value) is not int or value < 1 for value in (
                plan_version, task_version, iteration, call_index, model_call_limit))
            or call_index > model_call_limit
            or begin.get("stage") != stage_input.get("stage")
            or stage_input.get("task_id") != task_id
            or stage_input.get("plan_version") != plan_version
            or stage_input.get("task_version") != task_version
            or stage_input.get("iteration") != iteration
            or stage_input.get("model_call_limit") != model_call_limit):
        raise ResearchJudgmentError("ACP judgment begin receipt attempt fields are inconsistent")
    try:
        expected_attempt = make_attempt_binding(plan_version, begin["stage"], iteration)
    except (TypeError, ValueError) as error:
        raise ResearchJudgmentError("ACP judgment begin receipt attempt is invalid") from error
    expected_call = "byq-judgment-" + hashlib.sha256(
        f"{task_id}:{expected_attempt}".encode("utf-8")).hexdigest()[:32]
    if (begin.get("attempt_binding") != expected_attempt
            or begin.get("call_identity") != expected_call
            or not _matches(_CALL_ID, expected_call)):
        raise ResearchJudgmentError("ACP judgment begin receipt call identity is inconsistent")
    return root


def settlement_request(task_id: str, begin: dict, *, settlement_kind: str,
                       terminal_outcome: str, durably_recorded_evidence: dict) -> dict:
    """Build exact pre-result settlement from the Backend begin receipt.

    ``durably_recorded_evidence`` must already be persisted by the caller and
    backed by its independent journal, dispatch, usage, cancellation, and process
    cleanup observations. This helper only validates and submits that declaration;
    it does not convert a signed runner exit or local process status into a process
    fence, Backend ACK, or manufactured evidence.
    """
    root = _validate_settlement_begin(task_id, begin)
    if (not isinstance(settlement_kind, str)
            or settlement_kind not in {"never_dispatched", "cancelled_after_dispatch", "outcome_unknown"}):
        raise ResearchJudgmentError("ACP judgment settlement kind is invalid")
    if (not isinstance(terminal_outcome, str)
            or terminal_outcome not in {"failed", "cancelled", "interrupted"}):
        raise ResearchJudgmentError("ACP judgment settlement terminal outcome is invalid")
    evidence = _validate_settlement_evidence(
        durably_recorded_evidence, task_id=task_id, begin=begin,
        settlement_kind=settlement_kind, terminal_outcome=terminal_outcome)
    request = {
        "schema_version": _SETTLEMENT_REQUEST_SCHEMA,
        "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "root_run_id": root["root_run_id"],
        "runtime_boot_id": root["runtime_boot_id"],
        "authority_epoch": root["authority_epoch"],
        "dsh_run_id": root["dsh_run_id"],
        "settlement_kind": settlement_kind,
        "terminal_outcome": terminal_outcome,
        "evidence": evidence,
    }
    return request


def settlement_digest(begin: dict, request: dict) -> str:
    """Derive Backend's exact persisted settlement digest from the begin receipt."""
    task_id = begin.get("task_id") if isinstance(begin, dict) else None
    root = _validate_settlement_begin(task_id, begin)
    expected = settlement_request(
        task_id, begin, settlement_kind=request.get("settlement_kind"),
        terminal_outcome=request.get("terminal_outcome"),
        durably_recorded_evidence=request.get("evidence")) if isinstance(request, dict) else None
    if expected is None or request != expected:
        raise ResearchJudgmentError("ACP judgment settlement request differs from its exact begin receipt")
    admission = {
        "task_id": task_id,
        "owner_principal": root["owner_principal"],
        "workspace_id": root["workspace_id"],
        "actor_principal": root["actor_principal"],
        "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "root_run_id": root["root_run_id"],
        "runtime_boot_id": root["runtime_boot_id"],
        "authority_epoch": root["authority_epoch"],
        "dsh_run_id": root["dsh_run_id"],
        "plan_version": begin["plan_version"],
        "stage": begin["stage"],
        "iteration": begin["iteration"],
        "call_index": begin["call_index"],
    }
    return _canonical_sha256({
        "admission": admission,
        "request_sha256": _canonical_sha256(request),
        "settlement_kind": request["settlement_kind"],
        "terminal_outcome": request["terminal_outcome"],
        "evidence": request["evidence"],
    })


def _settlement_receipt_matches(receipt: object, *, task_id: str, begin: dict,
                                request: dict, expected_digest: str) -> bool:
    if not isinstance(receipt, dict):
        return False
    root = begin["root"]
    expected = {
        "schema_version": _SETTLEMENT_RECEIPT_SCHEMA,
        "status": "settled",
        "task_id": task_id,
        "owner_principal": root["owner_principal"],
        "workspace_id": root["workspace_id"],
        "actor_principal": root["actor_principal"],
        "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "root_run_id": root["root_run_id"],
        "runtime_boot_id": root["runtime_boot_id"],
        "authority_epoch": root["authority_epoch"],
        "dsh_run_id": root["dsh_run_id"],
        "plan_version": begin["plan_version"],
        "stage": begin["stage"],
        "iteration": begin["iteration"],
        "call_index": begin["call_index"],
        "settlement_kind": request["settlement_kind"],
        "terminal_outcome": request["terminal_outcome"],
        "settlement_digest": expected_digest,
        "evidence": request["evidence"],
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        return False
    ingress = receipt.get("backend_ingress_evidence")
    if (not isinstance(ingress, dict)
            or set(ingress) != {"schema_version", "terminal_acp_ingress_sequence",
                                "terminal_acp_ingress_sha256", "terminal_unknown_claim_count",
                                "terminal_unknown_claims_sha256"}
            or ingress.get("schema_version") != "byq-acp-terminal-evidence-snapshot.v1"
            or type(ingress.get("terminal_acp_ingress_sequence")) is not int
            or ingress["terminal_acp_ingress_sequence"] < 0
            or not isinstance(ingress.get("terminal_acp_ingress_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", ingress["terminal_acp_ingress_sha256"]) is None
            or type(ingress.get("terminal_unknown_claim_count")) is not int
            or ingress["terminal_unknown_claim_count"] < 0
            or not isinstance(ingress.get("terminal_unknown_claims_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", ingress["terminal_unknown_claims_sha256"]) is None):
        return False
    attention = receipt.get("attention")
    if (not isinstance(attention, dict)
            or set(attention) != {"state", "reason", "task_status", "task_version", "plan_version"}
            or not isinstance(attention.get("state"), str)
            or not isinstance(attention.get("reason"), str)
            or not isinstance(attention.get("task_status"), str)
            or type(attention.get("task_version")) is not int
            or (attention["plan_version"] is not None
                and type(attention["plan_version"]) is not int)
            or not isinstance(receipt.get("settled_at"), str)
            or not receipt["settled_at"]):
        return False
    return True


def _status_matches_settlement(status: dict, *, task_id: str, begin: dict,
                               request: dict, expected_digest: str) -> bool:
    receipt = status.get("settlement_receipt")
    root = begin["root"]
    binding_status = status.get("binding_status")
    if (binding_status == "root_created"):
        binding_matches = (status.get("native_root_session_id") is None
                           and status.get("agent_run_id") is None)
    elif binding_status == "agent_bound":
        binding_matches = (
            _matches(_NATIVE_SESSION_ID, status.get("native_root_session_id"))
            and _matches(_AGENT_RUN_ID, status.get("agent_run_id")))
    else:
        binding_matches = False
    return (
        status.get("authority_epoch") == root["authority_epoch"]
        and type(status.get("authority_epoch")) is int
        and status.get("dsh_run_id") == root["dsh_run_id"]
        and binding_matches
        and status.get("stage_call_status") == "settled"
        and status.get("stage_call_outcome") == request["terminal_outcome"]
        and status.get("result_request_sha256") is None
        and status.get("result_receipt") is None
        and status.get("settlement_digest") == expected_digest
        and status.get("settlement_kind") == request["settlement_kind"]
        and status.get("settlement_terminal_outcome") == request["terminal_outcome"]
        and status.get("terminal_outcome") == request["terminal_outcome"]
        and status.get("settlement_evidence") == request["evidence"]
        and status.get("cancellation_intent_receipt") == request["evidence"]["cancellation_intent_receipt"]
        and _settlement_receipt_matches(receipt, task_id=task_id, begin=begin,
                                        request=request, expected_digest=expected_digest)
    )


def submit_settlement_once(*, backend_url: str, task_id: str, begin: dict,
                           request: dict, headers: dict, transport=None,
                           timeout: float = 8.0) -> dict:
    """Submit once, then prove the durable settlement by exact Backend status.

    A lost POST reply is resolved only by status readback. The declaration must
    already be durably recorded and independently evidenced by the caller.
    """
    expected_digest = settlement_digest(begin, request)
    post = transport or _http_post
    response = _post_once(
        post, f"{backend_url}/internal/research-judgment/{task_id}/acp-root/settle",
        request, headers, timeout)
    status = exact_status(
        backend_url=backend_url, task_id=task_id,
        call_identity=begin["call_identity"], attempt=begin["attempt_binding"],
        root_run_id=begin["root"]["root_run_id"],
        runtime_boot_id=begin["root"]["runtime_boot_id"],
        headers=headers, transport=post, timeout=timeout)
    receipt = status.get("settlement_receipt")
    if (not _status_matches_settlement(status, task_id=task_id, begin=begin,
                                       request=request, expected_digest=expected_digest)
            or (response is not None and {
                key: value for key, value in response.items() if key != "replayed"
            } != receipt)):
        raise AcpJudgmentOutcomeUnknown("ACP judgment settlement is not exactly committed")
    return receipt


def close_settled_root_once(*, backend_url: str, task_id: str, begin: dict,
                            settlement: dict, headers: dict, transport=None,
                            timeout: float = 8.0) -> dict:
    """Close one exactly settled non-success root and require Backend terminal ACK.

    Close is posted at most once per call. A prior close is accepted only when
    Backend status already proves the exact terminal event and ingress snapshot.
    """
    expected_digest = settlement_digest(begin, settlement)
    outcome = settlement["terminal_outcome"]
    root_id = begin["root"]["root_run_id"]
    post = transport or _http_post
    status_fields = {
        "backend_url": backend_url, "task_id": task_id,
        "call_identity": begin["call_identity"], "attempt": begin["attempt_binding"],
        "root_run_id": root_id, "runtime_boot_id": begin["root"]["runtime_boot_id"],
        "headers": headers, "transport": post, "timeout": timeout,
    }
    before = exact_status(**status_fields)
    if not _status_matches_settlement(before, task_id=task_id, begin=begin,
                                      request=settlement, expected_digest=expected_digest):
        raise AcpJudgmentOutcomeUnknown("ACP judgment settlement is not proven before close")
    event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root_id,
             "sequence": 2, "outcome": outcome}
    receipt = lifecycle_receipt(event)
    if before.get("root_status") == "active" and before.get("root_authority_status") == "active":
        _post_once(post, f"{backend_url}/internal/runtime-authority/roots/{root_id}/close",
                   {"schema_version": "byq-runtime-root-close.v1",
                    "boot_id": begin["root"]["runtime_boot_id"],
                    "sequence": receipt["sequence"], "outcome": outcome,
                    "event_sha256": receipt["event_sha256"]}, headers, timeout)
    elif before.get("root_status") != outcome or before.get("root_authority_status") != "closed":
        raise AcpJudgmentOutcomeUnknown("ACP judgment root is neither active nor exactly closed")

    after = exact_status(**status_fields)
    settled_ingress = before["settlement_receipt"]["backend_ingress_evidence"]
    no_late_ingress = (
        settlement["settlement_kind"] != "never_dispatched"
        or (
            after.get("terminal_acp_ingress_sequence") == settled_ingress["terminal_acp_ingress_sequence"]
            and after.get("terminal_acp_ingress_sha256") == settled_ingress["terminal_acp_ingress_sha256"]
            and after.get("terminal_unknown_claim_count") == settled_ingress["terminal_unknown_claim_count"]
            and after.get("terminal_unknown_claims_sha256") == settled_ingress["terminal_unknown_claims_sha256"]
        )
    )
    if (not _status_matches_settlement(after, task_id=task_id, begin=begin,
                                       request=settlement, expected_digest=expected_digest)
            or not no_late_ingress
            or after.get("root_status") != outcome
            or after.get("root_authority_status") != "closed"
            or after.get("terminal_sequence") != receipt["sequence"]
            or after.get("terminal_event_sha256") != receipt["event_sha256"]
            or type(after.get("terminal_acp_ingress_sequence")) is not int
            or after["terminal_acp_ingress_sequence"] < 0
            or not isinstance(after.get("terminal_acp_ingress_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", after["terminal_acp_ingress_sha256"]) is None
            or type(after.get("terminal_unknown_claim_count")) is not int
            or after["terminal_unknown_claim_count"] != 0
            or not isinstance(after.get("terminal_unknown_claims_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", after["terminal_unknown_claims_sha256"]) is None):
        raise AcpJudgmentOutcomeUnknown("exact ACP judgment terminal ACK is unavailable")
    return receipt


def _validate_settlement_evidence(evidence: object, *, task_id: str, begin: dict,
                                  settlement_kind: str, terminal_outcome: str) -> dict:
    fields = {"schema_version", "journal_status", "journal_sha256", "prompt_dispatch",
              "prompt_sha256", "provider_attempt", "provider_attempt_sha256",
              "process_fence", "process_fence_sha256", "known_usage",
              "cancellation_intent_receipt"}
    if (not isinstance(evidence, dict) or set(evidence) != fields
            or evidence.get("schema_version") != _SETTLEMENT_EVIDENCE_SCHEMA):
        raise ResearchJudgmentError("exact ACP judgment settlement evidence declaration is required")
    journal_status = evidence["journal_status"]
    if (not isinstance(journal_status, str)
            or journal_status not in {"available", "missing", "unavailable"}):
        raise ResearchJudgmentError("ACP judgment settlement journal status is invalid")
    journal_digest = evidence["journal_sha256"]
    if journal_digest is not None and (
            not isinstance(journal_digest, str) or _SETTLEMENT_DIGEST.fullmatch(journal_digest) is None):
        raise ResearchJudgmentError("ACP judgment settlement journal digest is invalid")
    if (journal_status == "available") != (journal_digest is not None):
        raise ResearchJudgmentError("ACP judgment settlement journal status/digest differ")
    if (not isinstance(evidence["prompt_dispatch"], str)
            or evidence["prompt_dispatch"] not in {"not_dispatched", "may_have_dispatched"}):
        raise ResearchJudgmentError("ACP judgment settlement prompt dispatch status is invalid")
    prompt_digest = evidence["prompt_sha256"]
    if prompt_digest is not None and (
            not isinstance(prompt_digest, str) or _SETTLEMENT_DIGEST.fullmatch(prompt_digest) is None):
        raise ResearchJudgmentError("ACP judgment settlement prompt digest is invalid")
    if (not isinstance(evidence["provider_attempt"], str)
            or evidence["provider_attempt"] not in {"not_started", "may_have_started"}):
        raise ResearchJudgmentError("ACP judgment settlement provider attempt is invalid")
    provider_digest = evidence["provider_attempt_sha256"]
    if provider_digest is not None and (
            not isinstance(provider_digest, str) or _SETTLEMENT_DIGEST.fullmatch(provider_digest) is None):
        raise ResearchJudgmentError("ACP judgment settlement provider digest is invalid")
    if evidence["provider_attempt"] == "not_started" and provider_digest is not None:
        raise ResearchJudgmentError("not-started ACP provider attempt cannot have a digest")
    if (not isinstance(evidence["process_fence"], str)
            or evidence["process_fence"] not in {"stopped", "unproven"}):
        raise ResearchJudgmentError("ACP judgment settlement process fence is invalid")
    process_digest = evidence["process_fence_sha256"]
    if process_digest is not None and (
            not isinstance(process_digest, str) or _SETTLEMENT_DIGEST.fullmatch(process_digest) is None):
        raise ResearchJudgmentError("ACP judgment settlement process-fence digest is invalid")
    if (evidence["process_fence"] == "stopped") != (process_digest is not None):
        raise ResearchJudgmentError("ACP judgment process-fence status/digest differ")

    usage = evidence["known_usage"]
    if usage == {"status": "unknown"}:
        pass
    elif (isinstance(usage, dict)
          and set(usage) == {"status", "input_tokens", "output_tokens", "total_tokens"}
          and usage.get("status") == "known"):
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage[field]
            if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
                raise ResearchJudgmentError(f"ACP judgment known usage {field} is invalid")
    else:
        raise ResearchJudgmentError("ACP judgment known usage declaration is invalid")

    cancel = evidence["cancellation_intent_receipt"]
    if cancel is not None:
        cancel_fields = {"schema_version", "intent_id", "task_id", "owner_principal",
                         "workspace_id", "call_identity", "root_run_id", "intent_sha256"}
        root = begin["root"]
        if (not isinstance(cancel, dict) or set(cancel) != cancel_fields
                or cancel.get("schema_version") != "byq-research-judgment-acp-cancel-intent-receipt.v1"
                or not isinstance(cancel.get("intent_id"), str)
                or not _matches(_CANCEL_INTENT_ID, cancel["intent_id"])
                or cancel.get("task_id") != task_id
                or cancel.get("owner_principal") != root["owner_principal"]
                or cancel.get("workspace_id") != root["workspace_id"]
                or cancel.get("call_identity") != begin["call_identity"]
                or cancel.get("root_run_id") != root["root_run_id"]
                or not isinstance(cancel.get("intent_sha256"), str)
                or not _matches(_SETTLEMENT_DIGEST, cancel["intent_sha256"])):
            raise ResearchJudgmentError("ACP judgment cancellation intent receipt differs from root")
    if terminal_outcome == "cancelled" and cancel is None:
        raise ResearchJudgmentError("cancelled ACP judgment settlement needs owner intent receipt")
    if terminal_outcome != "cancelled" and cancel is not None:
        raise ResearchJudgmentError("cancel intent only authorizes cancelled ACP outcome")

    if settlement_kind == "never_dispatched":
        if (terminal_outcome not in {"failed", "cancelled"}
                or journal_status != "available"
                or evidence["prompt_dispatch"] != "not_dispatched"
                or evidence["provider_attempt"] != "not_started"
                or evidence["process_fence"] != "stopped"):
            raise ResearchJudgmentError("never-dispatched settlement lacks exact no-dispatch evidence")
    elif settlement_kind == "cancelled_after_dispatch":
        if (terminal_outcome != "cancelled" or cancel is None
                or evidence["prompt_dispatch"] != "may_have_dispatched"
                or evidence["process_fence"] != "stopped"):
            raise ResearchJudgmentError("cancelled-after-dispatch settlement lacks owner intent or process fence")
    elif settlement_kind == "outcome_unknown":
        if terminal_outcome != "interrupted" or cancel is not None:
            raise ResearchJudgmentError("unknown ACP judgment outcome must be interrupted without cancel intent")
    else:
        raise ResearchJudgmentError("ACP judgment settlement kind is invalid")
    return evidence


def result_request(task_id: str, begin: dict, binding: dict, native_id: str,
                   model_result: dict) -> dict:
    """Derive the closed result from Backend receipts, never model identities."""
    if (not isinstance(begin, dict) or begin.get("task_id") != task_id
            or begin.get("status") != "admitted" or not isinstance(begin.get("root"), dict)
            or not isinstance(binding, dict) or not isinstance(model_result, dict)
            or set(model_result) - {"proposal", "durable_evidence"}):
        raise ResearchJudgmentError("exact ACP judgment result inputs are required")
    root = begin["root"]
    if (binding.get("schema_version") != "byq-acp-agent-bind-receipt.v1"
            or binding.get("status") != "bound" or binding.get("origin") != "root"
            or binding.get("depth") != 0 or binding.get("native_parent_session_id") is not None
            or binding.get("root_run_id") != root.get("root_run_id")
            or binding.get("runtime_boot_id") != root.get("runtime_boot_id")
            or binding.get("native_agent_session_id") != native_id):
        raise ResearchJudgmentError("ACP judgment native Agent binding differs from the root")
    evidence = model_result.get("durable_evidence", {"kind": "none"})
    if evidence != {"kind": "none"}:
        raise ResearchJudgmentError("ACP judgment model cannot supply durable evidence identity")
    request = {
        "schema_version": "byq-research-judgment-acp-result.v1",
        "call_identity": begin.get("call_identity"),
        "attempt_binding": begin.get("attempt_binding"),
        "root_run_id": root.get("root_run_id"),
        "runtime_boot_id": root.get("runtime_boot_id"),
        "authority_epoch": root.get("authority_epoch"),
        "dsh_run_id": root.get("dsh_run_id"),
        "agent_run_id": binding.get("agent_run_id"),
        "native_root_session_id": native_id,
        "durable_evidence": evidence,
    }
    if model_result.get("proposal") is not None:
        request["proposal"] = model_result["proposal"]
    try:
        return validate_acp_judgment_result_request(request)
    except ValueError as error:
        raise ResearchJudgmentError("closed ACP judgment result is invalid") from error


def result_request_sha256(request: dict) -> str:
    """Match Backend's canonical request digest for lost-response readback."""
    validate_acp_judgment_result_request(request)
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _post_once(post, url: str, payload: dict, headers: dict, timeout: float) -> dict | None:
    try:
        response = post(url, payload, headers, timeout)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError):
        return None
    return response if isinstance(response, dict) else None


def _status_matches_result_request(status: dict, request: dict) -> bool:
    return (status.get("authority_epoch") == request["authority_epoch"]
            and status.get("dsh_run_id") == request["dsh_run_id"]
            and status.get("agent_run_id") == request["agent_run_id"]
            and status.get("native_root_session_id") == request["native_root_session_id"]
            and status.get("stage_call_status") == "completed"
            and status.get("result_request_sha256") == result_request_sha256(request)
            and isinstance(status.get("result_receipt"), dict))


def exact_status(*, backend_url: str, task_id: str, call_identity: str,
                 attempt: str, root_run_id: str, runtime_boot_id: str, headers: dict,
                 transport=None, timeout: float = 8.0) -> dict:
    payload = {"schema_version": "byq-research-judgment-acp-status.v1",
               "call_identity": call_identity, "attempt_binding": attempt}
    post = transport or _http_post
    status = _post_once(post, f"{backend_url}/internal/research-judgment/{task_id}/acp-root/status",
                        payload, headers, timeout)
    if (not isinstance(status, dict)
            or status.get("schema_version") != "byq-research-judgment-acp-status-receipt.v1"
            or status.get("task_id") != task_id
            or status.get("call_identity") != call_identity
            or status.get("attempt_binding") != attempt
            or status.get("root_run_id") != root_run_id
            or status.get("runtime_boot_id") != runtime_boot_id):
        raise AcpJudgmentOutcomeUnknown("exact ACP judgment status is unavailable")
    return status


_BEGIN_REQUEST_SCHEMA = "byq-research-judgment-acp-root-begin.v1"
_AGENT_REGISTER_REQUEST_SCHEMA = "byq-research-judgment-acp-agent-register.v1"
_AGENT_BIND_RECEIPT_SCHEMA = "byq-acp-agent-bind-receipt.v1"
_ATTEMPT = re.compile(r"^[0-9]+:[a-z_]+:[0-9]+$")


def begin_root_once(*, backend_url: str, task_id: str, call_identity: str,
                    attempt: str, headers: dict, transport=None,
                    timeout: float = 8.0) -> dict:
    """Admit one exact ACP judgment root and validate its complete begin receipt.

    A transport failure is an unknown outcome (never a fabricated admission). A
    present but inconsistent receipt fails closed as a hard error. This helper
    performs no model/provider call.
    """

    if (not _matches(_TASK_ID, task_id) or not _matches(_CALL_ID, call_identity)
            or not _matches(_ATTEMPT, attempt)):
        raise ResearchJudgmentError("exact ACP judgment begin inputs are required")
    payload = {"schema_version": _BEGIN_REQUEST_SCHEMA,
               "call_identity": call_identity, "attempt_binding": attempt}
    post = transport or _http_post
    receipt = _post_once(
        post, f"{backend_url}/internal/research-judgment/{task_id}/acp-root/begin",
        payload, headers, timeout)
    if receipt is None:
        raise AcpJudgmentOutcomeUnknown("ACP judgment begin receipt is unavailable")
    if (receipt.get("call_identity") != call_identity
            or receipt.get("attempt_binding") != attempt):
        raise ResearchJudgmentError("ACP judgment begin receipt identity is inconsistent")
    _validate_settlement_begin(task_id, receipt)
    return receipt


def register_root_agent_once(*, backend_url: str, task_id: str, call_identity: str,
                             root_run_id: str, runtime_boot_id: str,
                             native_root_session_id: str, headers: dict,
                             transport=None, timeout: float = 8.0) -> dict:
    """Register the fixed native root AgentRun and require its bound receipt.

    The receipt must bind the exact root/boot/session as a depth-0 ``root`` origin
    with a durable ``agent_run_`` identity. A transport failure or any mismatch is
    an unknown outcome: MCP identity must never be derived from an unproven
    registration.
    """

    if (not _matches(_TASK_ID, task_id) or not _matches(_CALL_ID, call_identity)
            or not _matches(_ROOT_ID, root_run_id)
            or not _matches(_ROOT_ID, runtime_boot_id)
            or not _matches(_NATIVE_SESSION_ID, native_root_session_id)):
        raise ResearchJudgmentError(
            "exact ACP judgment Agent registration inputs are required")
    payload = {"schema_version": _AGENT_REGISTER_REQUEST_SCHEMA,
               "call_identity": call_identity, "root_run_id": root_run_id,
               "runtime_boot_id": runtime_boot_id,
               "native_root_session_id": native_root_session_id}
    post = transport or _http_post
    receipt = _post_once(
        post,
        f"{backend_url}/internal/research-judgment/{task_id}/acp-root/register-agent",
        payload, headers, timeout)
    if (not isinstance(receipt, dict)
            or receipt.get("schema_version") != _AGENT_BIND_RECEIPT_SCHEMA
            or receipt.get("status") != "bound"
            or receipt.get("root_run_id") != root_run_id
            or receipt.get("runtime_boot_id") != runtime_boot_id
            or receipt.get("native_agent_session_id") != native_root_session_id
            or receipt.get("native_parent_session_id") is not None
            or receipt.get("origin") != "root"
            or receipt.get("depth") != 0
            or not _matches(_AGENT_RUN_ID, receipt.get("agent_run_id"))):
        raise AcpJudgmentOutcomeUnknown("ACP judgment Agent registration is not bound")
    return receipt


def submit_result_once(*, backend_url: str, task_id: str, request: dict,
                       headers: dict, transport=None, timeout: float = 8.0) -> dict:
    """Post once, then require exact committed readback even if response was lost."""
    try:
        validate_acp_judgment_result_request(request)
    except ValueError as error:
        raise ResearchJudgmentError("closed ACP judgment result is invalid") from error
    post = transport or _http_post
    response = _post_once(post, f"{backend_url}/internal/research-judgment/{task_id}/acp-root/result",
                          request, headers, timeout)
    status = exact_status(backend_url=backend_url, task_id=task_id,
                          call_identity=request["call_identity"],
                          attempt=request["attempt_binding"],
                          root_run_id=request["root_run_id"], headers=headers,
                          runtime_boot_id=request["runtime_boot_id"],
                          transport=post, timeout=timeout)
    receipt = status.get("result_receipt")
    if (not _status_matches_result_request(status, request)
            or not isinstance(receipt, dict)
            or receipt.get("schema_version") != "research-judgment-result-receipt.v1"
            or receipt.get("call_identity") != request["call_identity"]
            or (response is not None and {key: value for key, value in response.items()
                                          if key != "replayed"} != receipt)):
        raise AcpJudgmentOutcomeUnknown("ACP judgment result is not exactly committed")
    return receipt


def close_result_root_once(*, backend_url: str, task_id: str, result_request: dict,
                           headers: dict, transport=None, timeout: float = 8.0) -> dict:
    """Close only a proven result; never infer success from a lost close reply."""
    root_id = result_request["root_run_id"]
    post = transport or _http_post
    status_fields = {"backend_url": backend_url, "task_id": task_id,
                     "call_identity": result_request["call_identity"],
                     "attempt": result_request["attempt_binding"],
                     "root_run_id": root_id, "headers": headers,
                     "runtime_boot_id": result_request["runtime_boot_id"],
                     "transport": post, "timeout": timeout}
    before = exact_status(**status_fields)
    if not _status_matches_result_request(before, result_request):
        raise AcpJudgmentOutcomeUnknown("ACP judgment result is not proven before close")
    event = {"schema_version": "agent-run-lifecycle.v1", "root_run_id": root_id,
             "sequence": 2, "outcome": "completed"}
    receipt = lifecycle_receipt(event)
    if before.get("root_status") == "active":
        _post_once(post, f"{backend_url}/internal/runtime-authority/roots/{root_id}/close",
                   {"schema_version": "byq-runtime-root-close.v1",
                    "boot_id": result_request["runtime_boot_id"],
                    "sequence": receipt["sequence"], "outcome": "completed",
                    "event_sha256": receipt["event_sha256"]}, headers, timeout)
    after = exact_status(**status_fields)
    if (not _status_matches_result_request(after, result_request)
            or after.get("root_status") != "completed"
            or after.get("root_authority_status") != "closed"
            or after.get("terminal_sequence") != receipt["sequence"]
            or after.get("terminal_event_sha256") != receipt["event_sha256"]
            or type(after.get("terminal_acp_ingress_sequence")) is not int
            or after["terminal_acp_ingress_sequence"] < 0
            or not isinstance(after.get("terminal_acp_ingress_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", after["terminal_acp_ingress_sha256"]) is None
            or type(after.get("terminal_unknown_claim_count")) is not int
            or after["terminal_unknown_claim_count"] != 0
            or not isinstance(after.get("terminal_unknown_claims_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", after["terminal_unknown_claims_sha256"]) is None):
        raise AcpJudgmentOutcomeUnknown("exact ACP judgment terminal ACK is unavailable")
    return receipt
