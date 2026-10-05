"""Closed, nonsecret provider selection from one ADR-0097 root receipt.

This builder is not wired to the ACP entry yet. It derives BYQ provider-request
limits from the existing named stage registry and refuses a user credential
whose stable nonsecret identity/version is unavailable. The caller must prove
the receipt and resolution came from the same current trusted Backend scope,
and durably bind request_started_at_ms before Backend root admission. The pure
builder cannot prove that a caller did not supply a later timestamp.
"""

from __future__ import annotations

import json
import hmac
import re
import time
from dataclasses import dataclass, field

from packages.contracts.research_request_budget import stage_request_limits
from packages.contracts.research_judgment import attempt_binding, stage_model_call_limit

from .research_judgment_acp_journal import _provider_limits
from .research_judgment_boundary import derive_call_identity
from .research_judgment_acp_provider_routes import selected_route


@dataclass(frozen=True)
class AcpJudgmentProviderProfile:
    _public_json: bytes = field(repr=False)
    upstream_credential: str = field(repr=False)

    @property
    def public(self) -> dict:
        return json.loads(self._public_json)


def require_current_model_resolution(profile: AcpJudgmentProviderProfile,
                                     resolution: dict) -> None:
    """Reject a changed private selection before an eventual ACP dispatch.

    The trusted caller must repeat the Backend resolver request for the exact
    admitted owner/session/trace. This comparison alone does not prove that
    caller performed that request.
    """
    if not isinstance(profile, AcpJudgmentProviderProfile) or not isinstance(resolution, dict):
        raise ValueError("current trusted model resolution is required")
    public = profile.public
    source = resolution.get("source")
    reference = {"source": source}
    if source == "user_binding":
        reference.update({key: resolution.get(key) for key in (
            "profile_id", "profile_version", "credential_id",
            "credential_version", "binding_version")})
    credential = resolution.get("api_key")
    if (source not in {"environment", "user_binding"}
            or resolution.get("provider") != public.get("provider_route")
            or resolution.get("model") != public.get("model")
            or reference != public.get("credential_reference")
            or not isinstance(credential, str) or not credential
            or not hmac.compare_digest(credential.encode("utf-8"),
                                       profile.upstream_credential.encode("utf-8"))):
        raise ValueError("selected ACP judgment model binding changed")


def build_provider_profile(begin: dict, resolution: dict, *,
                           request_started_at_ms: int) -> AcpJudgmentProviderProfile:
    now_ms = int(time.time() * 1000)
    if (type(request_started_at_ms) is not int
            or request_started_at_ms <= 0
            or request_started_at_ms > now_ms):
        raise ValueError("judgment request start time is required")
    if (not isinstance(begin, dict)
            or begin.get("schema_version") != "byq-research-judgment-acp-root-receipt.v1"
            or begin.get("status") != "admitted" or begin.get("created") is not True
            or not isinstance(begin.get("root"), dict)):
        raise ValueError("new exact Backend judgment root receipt is required")
    root = begin["root"]
    if (not isinstance(begin.get("task_id"), str)
            or re.fullmatch(r"task_[0-9a-f]{32}", begin["task_id"]) is None
            or not isinstance(begin.get("call_identity"), str)
            or re.fullmatch(r"byq-judgment-[0-9a-f]{32}", begin["call_identity"]) is None
            or not isinstance(begin.get("attempt_binding"), str)
            or re.fullmatch(r"[0-9]+:[a-z_]+:[0-9]+", begin["attempt_binding"]) is None
            or not isinstance(root.get("root_run_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", root["root_run_id"]) is None
            or not isinstance(root.get("runtime_boot_id"), str)
            or re.fullmatch(r"[0-9a-f]{32}", root["runtime_boot_id"]) is None
            or type(root.get("authority_epoch")) is not int
            or root["authority_epoch"] <= 0
            or not isinstance(root.get("dsh_run_id"), str)
            or re.fullmatch(r"byqjudg-[0-9a-f]{32}", root["dsh_run_id"]) is None
            or any(not isinstance(root.get(key), str) or not root[key]
                   for key in ("owner_principal", "workspace_id", "session_id", "trace_id"))
            or root.get("actor_principal") != "byq-product-agent-" + root["session_id"]
            or any(type(begin.get(key)) is not int or begin[key] <= 0
                   for key in ("plan_version", "task_version", "iteration",
                               "call_index", "model_call_limit"))):
        raise ValueError("Backend judgment root identity is incomplete")
    if begin["call_identity"] != derive_call_identity(
            begin["task_id"], begin["attempt_binding"]):
        raise ValueError("Backend judgment call differs from exact task attempt")
    if (begin["attempt_binding"] != attempt_binding(
            begin["plan_version"], begin.get("stage"), begin["iteration"])
            or begin["model_call_limit"] != stage_model_call_limit(begin.get("stage"))
            or begin["call_index"] > begin["model_call_limit"]):
        raise ValueError("Backend judgment stage admission differs from its contract")
    if (not isinstance(resolution, dict)
            or resolution.get("source") not in {"environment", "user_binding"}
            or not isinstance(resolution.get("model"), str)
            or not resolution["model"] or len(resolution["model"]) > 128
            or any(ord(char) < 32 for char in resolution["model"])
            or not isinstance(resolution.get("api_key"), str)
            or not resolution["api_key"]):
        raise ValueError("trusted model resolution is incomplete")
    route = selected_route(resolution.get("provider"))
    source = resolution["source"]
    credential_reference = {"source": source}
    if source == "user_binding":
        required = ("profile_id", "profile_version", "credential_id",
                    "credential_version", "binding_version")
        if (not isinstance(resolution.get("profile_id"), str)
                or re.fullmatch(r"profile_[0-9a-f]{32}", resolution["profile_id"]) is None
                or not isinstance(resolution.get("credential_id"), str)
                or re.fullmatch(r"cred_[0-9a-f]{32}", resolution["credential_id"]) is None
                or any(type(resolution.get(key)) is not int or resolution[key] <= 0
                       for key in ("profile_version", "credential_version", "binding_version"))):
            raise ValueError("user model credential has no stable nonsecret version")
        credential_reference.update({key: resolution[key] for key in required})
    budget = stage_request_limits(
        begin.get("stage"), request_id=begin["call_identity"],
        started_at_ms=request_started_at_ms)
    if budget["deadline_at_ms"] <= now_ms:
        raise ValueError("judgment provider deadline expired during admission")
    limits = _provider_limits({
        "max_calls": min(budget["max_provider_calls"], budget["max_attempts"]),
        "max_input_bytes": budget["max_input_bytes"],
        "max_total_input_bytes": budget["max_input_bytes"],
        "max_output_tokens": budget["max_output_tokens"],
        "max_total_output_tokens": budget["max_output_tokens"],
        "max_tool_payload_bytes": budget["max_tool_payload_bytes"],
        "max_total_tool_payload_bytes": budget["max_tool_payload_bytes"],
        "deadline_at_ms": budget["deadline_at_ms"],
    })
    public = {
        "schema_version": "byq-acp-judgment-provider-profile.v1",
        "task_id": begin["task_id"], "call_identity": begin["call_identity"],
        "attempt_binding": begin["attempt_binding"],
        "plan_version": begin["plan_version"], "task_version": begin["task_version"],
        "stage": begin["stage"], "iteration": begin["iteration"],
        "call_index": begin["call_index"],
        "model_call_limit": begin["model_call_limit"],
        "root_run_id": root["root_run_id"],
        "runtime_boot_id": root["runtime_boot_id"],
        "authority_epoch": root["authority_epoch"],
        "dsh_run_id": root["dsh_run_id"],
        "owner_principal": root["owner_principal"],
        "workspace_id": root["workspace_id"],
        "actor_principal": root["actor_principal"],
        "session_id": root["session_id"], "trace_id": root["trace_id"],
        "provider_route": route.name, "model": resolution["model"],
        "credential_reference": credential_reference,
        "budget_profile_id": budget["profile_id"], "limits": limits,
    }
    return AcpJudgmentProviderProfile(
        json.dumps(public, sort_keys=True, separators=(",", ":")).encode(),
        resolution["api_key"])
