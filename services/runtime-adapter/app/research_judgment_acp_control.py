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
from packages.contracts.research_judgment import validate_acp_judgment_result_request

from .research_judgment import ResearchJudgmentError, _http_post


class AcpJudgmentOutcomeUnknown(ResearchJudgmentError):
    """The exact Backend result or terminal outcome has not been proven."""


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
