"""Trusted Runtime Adapter entry points for research judgment.

The dedicated ACP root owns the production lifecycle path. The older bounded
Python-SDK helper remains separate and is no longer dispatched by the HTTP API.
No generic plan/event/proposal write route or second harness is added.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .research_judgment import run_bounded_research_judgment
from .research_judgment_turn import DshBoundedTurnRunner

_REQUIRED_IDENTITY = ("owner_principal", "workspace_id", "actor_principal", "trace_id",
                      "session_id", "dsh_run_id")

_JUDGMENT_ENABLE_ENV = "BYQ_JUDGMENT_ACP_LIFECYCLE_ENABLED"


def judgment_acp_lifecycle_enabled(environment: dict | None = None) -> bool:
    """The dedicated ACP judgment entry is opt-in and defaults to protected."""

    env = os.environ if environment is None else environment
    return env.get(_JUDGMENT_ENABLE_ENV) == "1"


def judgment_provider_resolution(environment: dict) -> tuple[str, str, str]:
    """Resolve (provider, model, api_key) from the exact selected provider route.

    ADR-0105: the credential env is selected by the resolved provider route
    (OpenCode Go/Zen vs DeepSeek official); the entry must never assume
    DeepSeek. A missing credential for the selected route fails closed.
    """

    from .research_judgment_acp_turn import judgment_proxy_token_env

    provider = environment.get("BYQ_DSH_PROVIDER", "deepseek-official")
    model = environment.get("BYQ_DSH_MODEL", "deepseek-v4-flash")
    api_key = environment.get(judgment_proxy_token_env(provider), "")
    if not api_key:
        raise ValueError("selected provider credential is unavailable")
    return provider, model, api_key


def _judgment_control_root(environment: dict, workspace_id: str, task_id: str) -> Path:
    """Pre-provision one private, durable journal directory for the exact task."""

    session_root = environment.get("DSH_SESSION_ROOT", "/var/lib/byq/dsh-sessions")
    root = Path(session_root) / workspace_id / "research-judgment-control" / task_id
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    info = os.lstat(root)
    if (not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_uid != os.geteuid()):
        raise ValueError("judgment control journal directory is not private")
    return root


def _judgment_journal(environment: dict, identity: dict, task_id: str,
                      call_identity: str, trusted_headers: dict):
    from .research_judgment_acp_journal import AcpJudgmentJournal

    backend_url = environment.get("BYQ_BACKEND_URL", "http://backend:8000")
    authority_token = environment.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    if not authority_token:
        raise ValueError("runtime authority service credential is unavailable")
    control_root = _judgment_control_root(environment, identity["workspace_id"], task_id)
    journal_headers = {"authorization": f"Bearer {authority_token}"}
    for name in ("x-byq-owner-principal", "x-byq-workspace-id", "x-byq-runtime-boot-id"):
        if isinstance(trusted_headers.get(name), str) and trusted_headers[name]:
            journal_headers[name] = trusted_headers[name]
    return AcpJudgmentJournal(
        control_root, task_id, call_identity,
        backend_url=backend_url, authority_headers=journal_headers), backend_url


def recover_acp_judgment_root(*, task_id: str, identity: dict, call_identity: str,
                              trusted_headers: dict, environment: dict,
                              timeout: float = 15.0) -> dict:
    """Reconcile one in-flight dedicated root after a restart without replay."""

    from .research_judgment_acp_runner_client import RunnerClient
    from .research_judgment_acp_turn import (
        judgment_runner_scope,
        recover_judgment_acp_root as _recover,
    )

    for field in _REQUIRED_IDENTITY:
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            raise ValueError(f"trusted identity is missing {field}")
    journal, backend_url = _judgment_journal(
        environment, identity, task_id, call_identity, trusted_headers)
    # Read the runner-persisted signed cleanup receipt for the exact scope; an
    # absent/invalid receipt leaves the fence unproven (needs_attention).
    cleanup_receipt = None
    snapshot = journal.snapshot()
    if isinstance(snapshot, dict) and isinstance(snapshot.get("begin"), dict):
        try:
            cleanup_receipt = RunnerClient.from_environment().cleanup_receipt(
                judgment_runner_scope(snapshot["begin"]))
        except (ValueError, OSError):
            cleanup_receipt = None
    return _recover(journal=journal, backend_url=backend_url, task_id=task_id,
                    trusted_headers=trusted_headers, timeout=timeout,
                    cleanup_receipt=cleanup_receipt)


def run_acp_judgment_root(*, task_id: str, identity: dict, attempt: str,
                          call_identity: str, trusted_headers: dict,
                          environment: dict, timeout: float = 15.0,
                          cancel_event=None) -> dict:
    """Run one full dedicated ACP judgment root from the trusted Adapter entry.

    The caller supplies the authenticated trusted context headers and the runtime
    authority bearer. Every endpoint, credential, scope and overlay is derived
    server-side here; no model value is accepted.
    """

    from .compat import ACP_COMPATIBILITY_FAMILY, compatibility_for_release
    from .research_judgment_acp_journal import AcpJudgmentJournal
    from .research_judgment_acp_provider_proxy import AcpJudgmentProviderProxy
    from .research_judgment_acp_runner_client import RunnerClient
    from .research_judgment_acp_turn import (
        DEFAULT_JUDGMENT_SESSION_ROOT,
        IsolatedJudgmentAcpDriver,
        run_judgment_acp_root,
    )

    for field in _REQUIRED_IDENTITY:
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            raise ValueError(f"trusted identity is missing {field}")
    backend_url = environment.get("BYQ_BACKEND_URL", "http://backend:8000")
    authority_token = environment.get("BYQ_RUNTIME_AUTHORITY_TOKEN", "")
    if not authority_token:
        raise ValueError("runtime authority service credential is unavailable")
    provider, model, api_key = judgment_provider_resolution(environment)
    mcp_url = environment.get("BYQ_MCP_ACP_JUDGMENT_URL", "")
    if not mcp_url:
        raise ValueError("isolated judgment MCP endpoint is unavailable")
    mcp_product_url = environment.get("BYQ_MCP_URL") or None
    signing_master = environment.get("BYQ_MCP_ACP_JUDGMENT_SIGNING_KEY", "")
    if not signing_master:
        raise ValueError("dedicated judgment MCP master key is unavailable")

    control_root = _judgment_control_root(environment, identity["workspace_id"], task_id)
    # The journal makes its own authenticated Backend status/result/close calls
    # through the runtime-authority seam, which also requires the trusted owner /
    # Workspace / runtime-boot scope headers.
    journal_headers = {"authorization": f"Bearer {authority_token}"}
    for name in ("x-byq-owner-principal", "x-byq-workspace-id", "x-byq-runtime-boot-id"):
        if isinstance(trusted_headers.get(name), str) and trusted_headers[name]:
            journal_headers[name] = trusted_headers[name]
    journal = AcpJudgmentJournal(
        control_root, task_id, call_identity,
        backend_url=backend_url,
        authority_headers=journal_headers)
    resolution = {"source": "environment", "provider": provider, "model": model,
                  "api_key": api_key}
    # Dedicated judgment always uses the one authoritative ACP family. It does
    # not inherit the Product selector environment or fall back to the SDK path.
    compatibility = compatibility_for_release(ACP_COMPATIBILITY_FAMILY)
    runner_client = RunnerClient.from_environment()
    acp = IsolatedJudgmentAcpDriver(
        runner_client=runner_client, compatibility=compatibility,
        provider=provider, model=model)
    # The private provider proxy must bind an address the isolated runner's DSH
    # child can reach over the internal judgment network; the overlay serves that
    # exact address. It is a trusted configuration value, never a model input.
    proxy_bind = environment.get("BYQ_ACP_JUDGMENT_PROXY_BIND")
    if proxy_bind:
        def proxy_factory(journal, profile):
            return AcpJudgmentProviderProxy.from_frozen_profile(
                journal, profile, bind_host=proxy_bind)
    else:
        proxy_factory = AcpJudgmentProviderProxy.from_frozen_profile
    return run_judgment_acp_root(
        task_id=task_id, call_identity=call_identity, attempt=attempt,
        journal=journal, resolution=resolution, backend_url=backend_url,
        trusted_headers=trusted_headers, proxy_factory=proxy_factory,
        acp=acp, mcp_url=mcp_url, mcp_product_url=mcp_product_url,
        signing_master=signing_master, session_root=DEFAULT_JUDGMENT_SESSION_ROOT,
        timeout=timeout, cancel_event=cancel_event)


def run_stage_judgment(*, task_id: str, call_identity: str, backend_url: str,
                       trusted_headers: dict, identity: dict, provider: str, model: str,
                       session_root: str, compatibility, attempt: str | None = None,
                       environment: dict | None = None,
                       transport=None, timeout: float = 8.0,
                       runner_factory=DshBoundedTurnRunner) -> dict:
    """Run one real bounded judgment turn and commit its closed result.

    ``trusted_headers`` are sent to the Backend internal seam; ``identity`` is the
    server-derived BYQ identity used for the DSH harness env. The caller cannot
    supply the persona tool, the composition, the read-only endpoint or the model
    result.
    """

    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task_id is required")
    if not isinstance(call_identity, str) or not call_identity:
        raise ValueError("call_identity is required")
    if not isinstance(backend_url, str) or not backend_url:
        raise ValueError("backend_url is required")
    for field in _REQUIRED_IDENTITY:
        if not isinstance(identity.get(field), str) or not identity[field].strip():
            raise ValueError(f"trusted identity is missing {field}")
    runner = runner_factory(
        compatibility=compatibility, identity=identity, provider=provider, model=model,
        session_root=session_root, session_id=identity["session_id"],
        environment=environment or {})
    result = run_bounded_research_judgment(
        backend_url=backend_url, task_id=task_id, trusted_headers=trusted_headers,
        call_identity=call_identity, turn_runner=runner, transport=transport,
        attempt=attempt, timeout=timeout)
    # ADR-0086: expose the request-scoped gate limits/receipts for audit. A replay
    # (no model turn) carries no gate because no provider request was issued.
    gate_summary = getattr(runner, "gate_summary", None)
    summary = gate_summary() if callable(gate_summary) else None
    if summary is not None and isinstance(result, dict):
        return {**result, "request_gate": summary}
    return result
