"""Durable one-call fence for a dedicated ADR-0097 judgment ACP root.

The journal stores no model credential or DSH transcript. A prompt is marked
as possibly dispatched *before* calling ACP; restart never replays that prompt.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path

from packages.contracts.agent_run_lifecycle import lifecycle_receipt
from packages.contracts.research_request_budget import profile_for_stage
from packages.contracts.research_judgment import validate_acp_judgment_result_request

from .research_judgment_acp_control import (
    AcpJudgmentOutcomeUnknown, exact_status, result_request_sha256,
)
from .research_judgment_acp_provider_usage import AcpProviderStreamReceipt

_TASK = re.compile(r"task_[0-9a-f]{32}\Z")
_CALL = re.compile(r"byq-judgment-[0-9a-f]{32}\Z")
_MAX_BYTES = 128 * 1024
_SCHEMA = "byq-acp-judgment-control-journal.v1"
_PROVIDER_LIMIT_KEYS = frozenset({"max_calls", "max_input_bytes", "max_total_input_bytes",
                                  "max_output_tokens", "max_total_output_tokens",
                                  "max_tool_payload_bytes", "max_total_tool_payload_bytes",
                                  "deadline_at_ms"})
_PROVIDER_PROFILE_KEYS = frozenset({
    "schema_version", "task_id", "call_identity", "attempt_binding",
    "plan_version", "task_version", "stage", "iteration", "call_index",
    "model_call_limit", "root_run_id", "runtime_boot_id", "authority_epoch",
    "dsh_run_id", "owner_principal", "workspace_id", "actor_principal",
    "session_id", "trace_id", "provider_route", "model",
    "credential_reference", "budget_profile_id", "limits",
})


def _provider_limits(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != _PROVIDER_LIMIT_KEYS
            or any(type(item) is not int or item <= 0 for item in value.values())
            or value["max_calls"] > 16
            or value["max_input_bytes"] > 8 * 1024 * 1024
            or value["max_total_input_bytes"] > 32 * 1024 * 1024
            or value["max_output_tokens"] > 65536
            or value["max_total_output_tokens"] > 262144
            or value["max_tool_payload_bytes"] > 8 * 1024 * 1024
            or value["max_total_tool_payload_bytes"] > 32 * 1024 * 1024):
        raise ValueError("closed ACP provider limits are required")
    return dict(value)


def _contains_secret(value: object, secret: str) -> bool:
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(_contains_secret(key, secret) or _contains_secret(item, secret)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item, secret) for item in value)
    return False


class AcpJudgmentJournal:
    """One exact task/call journal, locked across concurrent Adapter requests."""

    def __init__(self, root: Path, task_id: str, call_identity: str, *,
                 backend_url: str, authority_headers: dict, transport=None) -> None:
        if not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None:
            raise ValueError("exact judgment task identity required")
        if not isinstance(call_identity, str) or _CALL.fullmatch(call_identity) is None:
            raise ValueError("exact judgment call identity required")
        self.task_id = task_id
        self.call_identity = call_identity
        if (not isinstance(backend_url, str) or not backend_url.startswith(("http://", "https://"))
                or not isinstance(authority_headers, dict)
                or not authority_headers.get("authorization")):
            raise ValueError("trusted Backend authority channel is required")
        self._backend_url = backend_url
        self._authority_headers = dict(authority_headers)
        self._transport = transport
        self.directory = Path(root)
        self.path = self.directory / f"{task_id}.{call_identity}.json"
        self.lock_path = self.directory / f"{task_id}.{call_identity}.lock"
        try:
            info = os.lstat(self.directory)
        except FileNotFoundError as error:
            raise AcpJudgmentOutcomeUnknown(
                "pre-provisioned judgment control journal directory is required") from error
        if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_uid != os.geteuid()):
            raise AcpJudgmentOutcomeUnknown("judgment control journal directory is not private")
        # Flush the pre-provisioned directory entry before any prompt fence can
        # be written. The Adapter never recreates a missing root on recovery.
        parent_fd = os.open(self.directory.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

    def _read(self) -> dict | None:
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            return None
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or info.st_nlink != 1
                or info.st_size > _MAX_BYTES):
            raise AcpJudgmentOutcomeUnknown("judgment control journal is not a private regular file")
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            opened = os.fstat(source.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise AcpJudgmentOutcomeUnknown("judgment control journal changed during read")
            raw = source.read(_MAX_BYTES + 1)
        if len(raw) > _MAX_BYTES:
            raise AcpJudgmentOutcomeUnknown("judgment control journal exceeds its bound")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError) as error:
            raise AcpJudgmentOutcomeUnknown("judgment control journal is invalid") from error
        if (not isinstance(value, dict) or value.get("schema_version") != _SCHEMA
                or value.get("task_id") != self.task_id
                or value.get("call_identity") != self.call_identity):
            raise AcpJudgmentOutcomeUnknown("judgment control journal identity differs")
        return value

    def _write(self, value: dict) -> None:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if len(raw) > _MAX_BYTES:
            raise AcpJudgmentOutcomeUnknown("judgment control journal exceeds its bound")
        fd, temporary = tempfile.mkstemp(prefix=".judgment-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory_fd = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _locked(self, action):
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "rb+") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.geteuid() or info.st_nlink != 1):
                raise AcpJudgmentOutcomeUnknown("judgment control lock is not private")
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                return action(self._read())
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def snapshot(self) -> dict | None:
        return self._locked(lambda value: value)

    def record_request_start(self, started_at_ms: int) -> dict:
        """Persist the exact task/call clock before asking Backend to admit it."""
        if (type(started_at_ms) is not int or started_at_ms <= 0
                or started_at_ms > int(time.time() * 1000)):
            raise ValueError("judgment request start time is required")

        def save(value):
            if value is not None:
                if value.get("request_started_at_ms") != started_at_ms:
                    raise AcpJudgmentOutcomeUnknown("judgment request start time changed")
                return value
            value = {"schema_version": _SCHEMA, "task_id": self.task_id,
                     "call_identity": self.call_identity, "phase": "prepared",
                     "request_started_at_ms": started_at_ms}
            self._write(value)
            return value

        return self._locked(save)

    def record_begin(self, begin: dict) -> dict:
        """Persist the fresh Backend response immediately; never cache its creation bit."""
        if (not isinstance(begin, dict) or begin.get("task_id") != self.task_id
                or begin.get("call_identity") != self.call_identity
                or begin.get("status") != "admitted" or not isinstance(begin.get("root"), dict)
                or type(begin.get("created")) is not bool):
            raise ValueError("exact admitted judgment root receipt required")
        stable_begin = {key: value for key, value in begin.items() if key != "created"}

        def save(value):
            if value is not None:
                if value.get("phase") == "prepared":
                    if begin["created"] is not True:
                        raise AcpJudgmentOutcomeUnknown(
                            "replayed judgment root has no durable Backend begin receipt")
                    value = {**value, "phase": "begun", "begin": stable_begin}
                    self._write(value)
                    return value
                if value.get("begin") != stable_begin:
                    raise AcpJudgmentOutcomeUnknown("judgment begin receipt differs from durable journal")
                return value
            if begin["created"] is not True:
                raise AcpJudgmentOutcomeUnknown(
                    "replayed judgment root has no durable prompt fence")
            value = {"schema_version": _SCHEMA, "task_id": self.task_id,
                     "call_identity": self.call_identity, "phase": "begun", "begin": stable_begin}
            self._write(value)
            return value

        return self._locked(save)

    def record_binding(self, binding: dict) -> dict:
        if not isinstance(binding, dict) or binding.get("schema_version") != "byq-acp-agent-bind-receipt.v1":
            raise ValueError("exact judgment Agent binding receipt required")

        def save(value):
            if value is None or value.get("phase") not in {"begun", "bound"}:
                raise AcpJudgmentOutcomeUnknown("judgment root is not ready for Agent binding")
            root = value["begin"]["root"]
            if (binding.get("root_run_id") != root.get("root_run_id")
                    or binding.get("runtime_boot_id") != root.get("runtime_boot_id")
                    or binding.get("origin") != "root" or binding.get("depth") != 0
                    or binding.get("native_parent_session_id") is not None
                    or binding.get("status") != "bound"):
                raise AcpJudgmentOutcomeUnknown("judgment Agent binding differs from admitted root")
            if value.get("phase") == "bound":
                if value.get("binding") != binding:
                    raise AcpJudgmentOutcomeUnknown("judgment Agent binding changed")
                return value
            value = {**value, "phase": "bound", "binding": binding}
            self._write(value)
            return value

        return self._locked(save)

    def record_provider_profile(self, profile) -> dict:
        """Freeze the nonsecret selected provider under the exact admitted root.

        This method is not yet called by the ACP entry. The credential stays in
        Adapter memory; only its nonsecret identity/version is persisted.
        """
        from .research_judgment_acp_provider_profile import AcpJudgmentProviderProfile

        if not isinstance(profile, AcpJudgmentProviderProfile):
            raise ValueError("built ACP provider profile is required")
        public = profile.public
        if not isinstance(public, dict):
            raise ValueError("exact nonsecret ACP provider profile is required")
        reference = public.get("credential_reference")
        if (set(public) != _PROVIDER_PROFILE_KEYS
                or not isinstance(profile.upstream_credential, str)
                or not profile.upstream_credential
                or _contains_secret(public, profile.upstream_credential)
                or public.get("schema_version") != "byq-acp-judgment-provider-profile.v1"
                or not isinstance(reference, dict)
                or set(reference) != ({"source"} if reference.get("source") == "environment"
                                     else {"source", "profile_id", "profile_version",
                                           "credential_id", "credential_version",
                                           "binding_version"})
                or reference.get("source") not in {"environment", "user_binding"}
                or not isinstance(public.get("provider_route"), str)
                or not isinstance(public.get("model"), str)
                or not public["model"] or len(public["model"]) > 128
                or any(ord(char) < 32 for char in public["model"])):
            raise ValueError("exact nonsecret ACP provider profile is required")
        limits = _provider_limits(public.get("limits"))
        named = profile_for_stage(public.get("stage"), profile=public.get("budget_profile_id"))
        ceiling = {
            "max_calls": min(named["max_provider_calls"], named["max_attempts"]),
            "max_input_bytes": named["max_input_bytes"],
            "max_total_input_bytes": named["max_input_bytes"],
            "max_output_tokens": named["max_output_tokens"],
            "max_total_output_tokens": named["max_output_tokens"],
            "max_tool_payload_bytes": named["max_tool_payload_bytes"],
            "max_total_tool_payload_bytes": named["max_tool_payload_bytes"],
        }
        if (any(limits[key] > maximum for key, maximum in ceiling.items())
                or limits["deadline_at_ms"] > int(time.time() * 1000) + named["deadline_ms"]
                or (reference["source"] == "user_binding" and (
                    not isinstance(reference["profile_id"], str)
                    or re.fullmatch(r"profile_[0-9a-f]{32}", reference["profile_id"]) is None
                    or not isinstance(reference["credential_id"], str)
                    or re.fullmatch(r"cred_[0-9a-f]{32}", reference["credential_id"]) is None
                    or any(type(reference[key]) is not int or reference[key] <= 0
                           for key in ("profile_version", "credential_version",
                                       "binding_version"))))):
            raise ValueError("provider profile exceeds named budget or has invalid credential reference")

        def save(value):
            if value is None or value.get("phase") not in {"begun", "bound"}:
                raise AcpJudgmentOutcomeUnknown("judgment provider profile must precede prompt dispatch")
            started_at_ms = value.get("request_started_at_ms")
            if (type(started_at_ms) is not int or started_at_ms <= 0
                    or limits["deadline_at_ms"] > started_at_ms + named["deadline_ms"]):
                raise AcpJudgmentOutcomeUnknown(
                    "provider deadline is not bound to durable request start")
            begin = value["begin"]
            root = begin["root"]
            for field in ("task_id", "call_identity", "attempt_binding", "plan_version",
                          "task_version", "stage", "iteration", "call_index",
                          "model_call_limit"):
                if public.get(field) != begin.get(field):
                    raise AcpJudgmentOutcomeUnknown("provider profile differs from Backend admission")
            for field in ("root_run_id", "runtime_boot_id", "authority_epoch",
                          "dsh_run_id", "owner_principal", "workspace_id",
                          "actor_principal", "session_id", "trace_id"):
                if public.get(field) != root.get(field):
                    raise AcpJudgmentOutcomeUnknown("provider profile differs from Backend root")
            if value.get("provider_profile") is not None:
                if value["provider_profile"] != public:
                    raise AcpJudgmentOutcomeUnknown("judgment provider profile changed")
                return value
            value = {**value, "provider_profile": public, "provider_limits": limits}
            self._write(value)
            return value

        return self._locked(save)

    def mark_prompt_may_dispatch(self) -> dict:
        def save(value):
            if value is None or value.get("phase") != "bound":
                raise AcpJudgmentOutcomeUnknown("judgment prompt may already have been dispatched")
            if value.get("provider_profile") is None:
                raise AcpJudgmentOutcomeUnknown("judgment provider profile is not frozen")
            value = {**value, "phase": "prompt_may_have_dispatched"}
            self._write(value)
            return value

        return self._locked(save)

    def reserve_provider_attempt(self, *, route: str, body: bytes,
                                 declared_output_tokens: int, limits: dict,
                                 now_ms: int | None = None) -> dict:
        """Fsync one exact may-have-dispatched fact before outbound I/O.

        A missing completion after this write is unknown on every restart. The
        journal deliberately serializes provider calls within this root.
        """
        limits = _provider_limits(limits)
        if (not isinstance(route, str) or not route or len(route) > 80
                or not isinstance(body, bytes) or not body
                or type(declared_output_tokens) is not int or declared_output_tokens <= 0):
            raise ValueError("exact provider attempt inputs are required")
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        if type(now_ms) is not int or now_ms <= 0:
            raise ValueError("provider attempt time is invalid")
        digest = "sha256:" + hashlib.sha256(body).hexdigest()

        def save(value):
            if value is None or value.get("phase") != "prompt_may_have_dispatched":
                raise AcpJudgmentOutcomeUnknown("judgment prompt is not active")
            attempts = value.get("provider_attempts", [])
            if not isinstance(attempts, list) or any(not isinstance(row, dict)
                                                     or row.get("phase") != "completed"
                                                     for row in attempts):
                raise AcpJudgmentOutcomeUnknown("previous provider attempt is unknown")
            if value.get("provider_limits") not in (None, limits):
                raise AcpJudgmentOutcomeUnknown("provider limits changed within root")
            profile = value.get("provider_profile")
            if profile is None or (
                    route != profile.get("provider_route")
                    or limits != profile.get("limits")):
                raise AcpJudgmentOutcomeUnknown("provider request differs from frozen root profile")
            if (now_ms >= limits["deadline_at_ms"]
                    or len(attempts) >= limits["max_calls"]
                    or len(body) > limits["max_input_bytes"]
                    # Every tool schema/result byte is contained in the
                    # serialized request. Charge the whole request as a safe
                    # upper bound until each provider shape is measured.
                    or len(body) > limits["max_tool_payload_bytes"]
                    or sum(row["input_bytes"] for row in attempts) + len(body)
                       > limits["max_total_input_bytes"]
                    or sum(row["tool_payload_upper_bound_bytes"] for row in attempts)
                       + len(body) > limits["max_total_tool_payload_bytes"]
                    or declared_output_tokens > limits["max_output_tokens"]
                    or sum(row["declared_output_tokens"] for row in attempts)
                       + declared_output_tokens > limits["max_total_output_tokens"]):
                raise AcpJudgmentOutcomeUnknown("ACP provider request budget exhausted")
            attempt = {"index": len(attempts) + 1, "phase": "may_have_dispatched",
                       "route": route, "request_sha256": digest,
                       "input_bytes": len(body),
                       "tool_payload_upper_bound_bytes": len(body),
                       "declared_output_tokens": declared_output_tokens,
                       "at_ms": now_ms}
            value = {**value, "provider_limits": limits,
                     "provider_attempts": [*attempts, attempt]}
            self._write(value)
            return attempt

        return self._locked(save)

    def settle_provider_attempt(self, *, index: int, status: int,
                                receipt: AcpProviderStreamReceipt | None,
                                transport_complete: bool,
                                now_ms: int | None = None) -> dict:
        """Close a proven attempt; all other outcomes remain permanently unknown."""
        if type(index) is not int or index <= 0 or type(status) is not int:
            raise ValueError("exact provider attempt receipt is required")
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        if type(now_ms) is not int or now_ms <= 0:
            raise ValueError("provider completion time is invalid")

        def save(value):
            if value is None or value.get("phase") != "prompt_may_have_dispatched":
                raise AcpJudgmentOutcomeUnknown("judgment prompt is not active")
            attempts = value.get("provider_attempts", [])
            if (not isinstance(attempts, list) or len(attempts) != index
                    or attempts[index - 1].get("phase") != "may_have_dispatched"):
                raise AcpJudgmentOutcomeUnknown("provider attempt is not pending")
            attempt = attempts[index - 1]
            limits = value.get("provider_limits")
            proved = (transport_complete is True and status == 200
                      and isinstance(receipt, AcpProviderStreamReceipt)
                      and receipt.output_proven
                      and receipt.usage_state == "known"
                      and all(type(count) is int and count >= 0 for count in (
                          receipt.actual_input_tokens, receipt.actual_output_tokens,
                          receipt.actual_cache_read_tokens, receipt.actual_cache_write_tokens))
                      and receipt.actual_output_tokens <= attempt["declared_output_tokens"]
                      and now_ms < limits["deadline_at_ms"])
            completed = {**attempt, "phase": "completed" if proved else "unknown",
                         "status": status, "completed_at_ms": now_ms,
                         "actual_input_tokens": (receipt.actual_input_tokens if receipt else "unknown"),
                         "actual_output_tokens": (receipt.actual_output_tokens if receipt else "unknown"),
                         "actual_cache_read_tokens": (receipt.actual_cache_read_tokens if receipt else "unknown"),
                         "actual_cache_write_tokens": (receipt.actual_cache_write_tokens if receipt else "unknown")}
            value = {**value, "provider_attempts": [*attempts[:-1], completed]}
            self._write(value)
            return completed

        return self._locked(save)

    def record_result_request(self, request: dict) -> dict:
        validate_acp_judgment_result_request(request)

        def save(value):
            if value is None or value.get("phase") not in {
                    "prompt_may_have_dispatched", "result_prepared"}:
                raise AcpJudgmentOutcomeUnknown("judgment result has no dispatched prompt")
            if value.get("provider_profile") is None:
                raise AcpJudgmentOutcomeUnknown("judgment result has no frozen provider profile")
            attempts = value.get("provider_attempts")
            if (not isinstance(attempts, list) or not attempts
                    or any(not isinstance(row, dict) or row.get("phase") != "completed"
                           for row in attempts)):
                raise AcpJudgmentOutcomeUnknown("provider outcome is unknown before result")
            root = value["begin"]["root"]
            if (request.get("call_identity") != self.call_identity
                    or request.get("attempt_binding") != value["begin"].get("attempt_binding")
                    or request.get("root_run_id") != root.get("root_run_id")
                    or request.get("runtime_boot_id") != root.get("runtime_boot_id")
                    or request.get("authority_epoch") != root.get("authority_epoch")
                    or request.get("dsh_run_id") != root.get("dsh_run_id")
                    or request.get("agent_run_id") != value["binding"].get("agent_run_id")
                    or request.get("native_root_session_id") != value["binding"].get("native_agent_session_id")):
                raise AcpJudgmentOutcomeUnknown("judgment result differs from durable root and Agent")
            if value.get("phase") == "result_prepared":
                if value.get("result_request") != request:
                    raise AcpJudgmentOutcomeUnknown("judgment result request changed")
                return value
            value = {**value, "phase": "result_prepared", "result_request": request,
                     "result_request_sha256": result_request_sha256(request)}
            self._write(value)
            return value

        return self._locked(save)

    def _require_exact_status(self, value: dict, status: dict) -> None:
        root = value["begin"]["root"]
        request = value["result_request"]
        if (not isinstance(status, dict)
                or status.get("schema_version") != "byq-research-judgment-acp-status-receipt.v1"
                or status.get("task_id") != self.task_id
                or status.get("call_identity") != self.call_identity
                or status.get("attempt_binding") != value["begin"].get("attempt_binding")
                or status.get("root_run_id") != root.get("root_run_id")
                or status.get("runtime_boot_id") != root.get("runtime_boot_id")
                or status.get("authority_epoch") != root.get("authority_epoch")
                or status.get("dsh_run_id") != root.get("dsh_run_id")
                or status.get("native_root_session_id") != request.get("native_root_session_id")
                or status.get("agent_run_id") != request.get("agent_run_id")
                or status.get("stage_call_status") != "completed"
                or status.get("result_request_sha256") != value["result_request_sha256"]):
            raise AcpJudgmentOutcomeUnknown("Backend status does not prove the exact judgment result")

    def _backend_status(self, value: dict) -> dict:
        root = value["begin"]["root"]
        return exact_status(
            backend_url=self._backend_url, task_id=self.task_id,
            call_identity=self.call_identity,
            attempt=value["begin"]["attempt_binding"],
            root_run_id=root["root_run_id"], runtime_boot_id=root["runtime_boot_id"],
            headers=self._authority_headers, transport=self._transport,
        )

    def record_result_receipt(self, receipt: dict) -> dict:
        if (not isinstance(receipt, dict)
                or receipt.get("schema_version") != "research-judgment-result-receipt.v1"
                or receipt.get("call_identity") != self.call_identity):
            raise ValueError("exact judgment result receipt required")

        def save(value):
            if value is None or value.get("phase") not in {"result_prepared", "result_committed"}:
                raise AcpJudgmentOutcomeUnknown("judgment result request was not durably prepared")
            backend_status = self._backend_status(value)
            self._require_exact_status(value, backend_status)
            if backend_status.get("result_receipt") != receipt:
                raise AcpJudgmentOutcomeUnknown("Backend status does not prove the judgment receipt")
            if value.get("phase") == "result_committed":
                if value.get("result_receipt") != receipt:
                    raise AcpJudgmentOutcomeUnknown("judgment result receipt changed")
                return value
            value = {**value, "phase": "result_committed", "result_receipt": receipt,
                     "result_backend_status": backend_status}
            self._write(value)
            return value

        return self._locked(save)

    def record_terminal_receipt(self, receipt: dict) -> dict:
        def save(value):
            if value is None or value.get("phase") not in {"result_committed", "terminal_closed"}:
                raise AcpJudgmentOutcomeUnknown("judgment result is not committed before close")
            root_id = value["begin"]["root"]["root_run_id"]
            expected = lifecycle_receipt({"schema_version": "agent-run-lifecycle.v1",
                                          "root_run_id": root_id, "sequence": 2,
                                          "outcome": "completed"})
            if receipt != expected:
                raise AcpJudgmentOutcomeUnknown("judgment terminal receipt differs from exact root")
            backend_status = self._backend_status(value)
            self._require_exact_status(value, backend_status)
            if (backend_status.get("result_receipt") != value.get("result_receipt")
                    or backend_status.get("root_status") != "completed"
                    or backend_status.get("root_authority_status") != "closed"
                    or backend_status.get("terminal_sequence") != receipt["sequence"]
                    or backend_status.get("terminal_event_sha256") != receipt["event_sha256"]
                    or type(backend_status.get("terminal_acp_ingress_sequence")) is not int
                    or backend_status["terminal_acp_ingress_sequence"] < 0
                    or not isinstance(backend_status.get("terminal_acp_ingress_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", backend_status["terminal_acp_ingress_sha256"]) is None
                    or type(backend_status.get("terminal_unknown_claim_count")) is not int
                    or backend_status["terminal_unknown_claim_count"] != 0
                    or not isinstance(backend_status.get("terminal_unknown_claims_sha256"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", backend_status["terminal_unknown_claims_sha256"]) is None):
                raise AcpJudgmentOutcomeUnknown("Backend status does not prove the terminal ACK")
            if value.get("phase") == "terminal_closed":
                return value
            value = {**value, "phase": "terminal_closed", "terminal_receipt": receipt,
                     "terminal_backend_status": backend_status}
            self._write(value)
            return value

        return self._locked(save)
