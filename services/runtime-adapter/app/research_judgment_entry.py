"""ADR-0085 P4: the minimal trusted internal entry for one bounded judgment turn.

This is the only production caller of ``run_bounded_research_judgment``. The
Runtime Adapter derives every identity/tool/URL/header/call value server-side and
never accepts a model result, a next action, an approval, an idempotency key or a
routing decision from the caller. The flow is exactly:

    admit (Backend) -> real DSH bounded turn (DshBoundedTurnRunner)
    -> closed result -> atomic Backend result

It adds no generic plan/event/proposal write route and no second harness.
"""

from __future__ import annotations

from .research_judgment import run_bounded_research_judgment
from .research_judgment_turn import DshBoundedTurnRunner

_REQUIRED_IDENTITY = ("owner_principal", "workspace_id", "actor_principal", "trace_id",
                      "session_id", "dsh_run_id")


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
