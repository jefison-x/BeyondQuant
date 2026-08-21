import os
import re

from fastapi import FastAPI
from fastapi import HTTPException, Request
from collections.abc import Callable
from typing import Any

from .data_provider import (
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderRateLimited,
    TushareProvider,
)
from .factor_research import compute_factor
from .backtest import (
    BacktestConflict,
    BacktestError,
    BacktestJobStore,
    BacktestNotFound,
    ObjectIntegrityError,
    BacktestStorageError,
    BacktestWorker,
    LocalObjectStore,
    load_result,
    build_manifest,
    normalize_backtest_request,
    normalize_signal_snapshot,
    signal_snapshot_content_sha256,
    membership_fingerprint,
)
from .agent_research import (
    AgentConflict,
    AgentForbidden,
    AgentNotFound,
    AgentPersistenceError,
    AgentResearchStore,
    AgentUnauthorized,
    role_catalog,
)
from .learning_loop import (
    LearningConflict,
    LearningForbidden,
    LearningNotFound,
    LearningPersistenceError,
    LearningUnauthorized,
    LearningLoopStore,
)
from .engineering import (
    EngineeringConflict,
    EngineeringForbidden,
    EngineeringNotFound,
    EngineeringPersistenceError,
    EngineeringUnauthorized,
    EngineeringTaskStore,
)
from .paper_trading import (
    PaperTradingConflict,
    PaperTradingForbidden,
    PaperTradingNotFound,
    PaperTradingPersistenceError,
    PaperTradingStore,
)
from .user_auth import (
    UserAuthError,
    UserAuthPersistenceError,
    UserAuthStore,
    UserConflict,
    UserForbidden,
    UserNotFound,
)
from .user_policy import UserPolicyStore, UserPolicyError, UserPolicyPersistenceError, public_policy
from .research import (
    IdempotencyConflict,
    InvalidTransition,
    ResearchNotFound,
    ResearchPersistenceError,
    ResearchStore,
)
from .strategy_artifact import (
    content_sha256,
    export_strategy_version,
    prepare_strategy,
    prepare_strategy_draft,
    strategy_draft_content,
    strategy_version_content,
    validate_version_content,
)


SERVICE = "byq-backend"
VERSION = "0.1.0"

app = FastAPI(title="BeyondQuant Backend", version=VERSION)
data_provider = TushareProvider.from_env()
research_store = ResearchStore.from_env()
agent_store = AgentResearchStore.from_env()
learning_store = LearningLoopStore.from_env(research_store)
engineering_store = EngineeringTaskStore.from_env()
paper_store = PaperTradingStore.from_env()
user_store = UserAuthStore.from_env()
user_policy_store = UserPolicyStore.from_env()
if os.environ.get("BYQ_BOOTSTRAP_ADMIN_USERNAME") and os.environ.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD"):
    user_store.ensure_bootstrap_admin(
        os.environ["BYQ_BOOTSTRAP_ADMIN_USERNAME"],
        os.environ["BYQ_BOOTSTRAP_ADMIN_PASSWORD"],
    )
backtest_store = BacktestJobStore.from_env()
backtest_objects = LocalObjectStore.from_env()


def _health_payload() -> dict[str, str]:
    return {
        "service": SERVICE,
        "status": "ok",
        "version": VERSION,
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return _health_payload()


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return _health_payload()


@app.get("/v1/data/daily")
def daily_data(
    ts_code: str | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, object]:
    try:
        request = DailyRequest(
            ts_code=ts_code,
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
        ).normalized()
        result = data_provider.fetch_daily(
            request
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ProviderCredentialsMissing as error:
        raise HTTPException(status_code=503, detail="data provider is unavailable") from error
    except ProviderAuthorizationError as error:
        raise HTTPException(status_code=503, detail="data provider is unavailable") from error
    except ProviderRateLimited as error:
        raise HTTPException(status_code=429, detail="data provider is rate limited") from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail="data provider request failed") from error

    return {
        "data": [bar.as_dict() for bar in result.bars],
        "provenance": result.provenance.as_dict(),
    }


def _research_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ResearchNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (IdempotencyConflict, InvalidTransition) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ResearchPersistenceError as error:
        raise HTTPException(status_code=503, detail="research storage is unavailable") from error


def _backtest_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ResearchNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except BacktestNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except BacktestConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except BacktestStorageError as error:
        raise HTTPException(status_code=503, detail="backtest storage is unavailable") from error


def _agent_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AgentUnauthorized as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except AgentForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except AgentNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AgentConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except AgentPersistenceError as error:
        raise HTTPException(status_code=503, detail="agent research storage is unavailable") from error


def _learning_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LearningUnauthorized as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except LearningForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LearningNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LearningConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ResearchNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except LearningPersistenceError as error:
        raise HTTPException(status_code=503, detail="learning storage is unavailable") from error


def _engineering_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except EngineeringUnauthorized as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except EngineeringForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except EngineeringNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except EngineeringConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except EngineeringPersistenceError as error:
        raise HTTPException(status_code=503, detail="engineering storage is unavailable") from error


def _paper_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except PaperTradingForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except PaperTradingNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PaperTradingConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PaperTradingPersistenceError as error:
        raise HTTPException(status_code=503, detail="paper trading storage is unavailable") from error


def _user_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except UserForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except UserNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UserConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UserAuthPersistenceError as error:
        raise HTTPException(status_code=503, detail="user storage is unavailable") from error


def _agent_context(request: Request, payload: dict[str, Any]) -> dict[str, str | None]:
    """Resolve trusted runtime context without forwarding credentials."""

    header_values = {
        "owner_principal": request.headers.get("x-byq-owner-principal"),
        "actor_principal": request.headers.get("x-byq-actor-principal"),
        "trace_id": request.headers.get("x-byq-trace-id"),
        "session_id": request.headers.get("x-byq-session-id"),
        "dsh_run_id": request.headers.get("x-byq-dsh-run-id"),
    }
    for field, header_value in header_values.items():
        body_value = payload.get(field)
        if header_value and body_value not in {None, header_value}:
            raise HTTPException(status_code=401, detail=f"{field} does not match trusted runtime context")
    return {
        field: header_value or (str(payload[field]) if payload.get(field) is not None else None)
        for field, header_value in header_values.items()
    }


def _required_agent_context(request: Request, payload: dict[str, Any] | None = None) -> dict[str, str]:
    context = _agent_context(request, payload or {})
    missing = sorted(field for field, value in context.items() if value is None)
    if missing:
        raise HTTPException(status_code=401, detail="trusted agent context is required")
    return {field: value for field, value in context.items() if value is not None}


def _strategy_payload(payload: object, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("strategy request must be an object")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"strategy request has unknown fields: {', '.join(unknown)}")
    return payload


def _transition_args(payload: dict[str, Any]) -> tuple[object, object]:
    if set(payload) != {"target_status", "idempotency_key"}:
        raise ValueError("transition request has invalid fields")
    return payload["target_status"], payload["idempotency_key"]


def _research_transition(
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any],
) -> dict[str, object]:
    return _research_call(
        lambda: research_store.transition(
            entity_type,
            entity_id,
            *_transition_args(payload),
        )
    )


@app.post("/v1/research/tasks", status_code=201)
def create_research_task(payload: dict[str, Any]) -> dict[str, object]:
    return _research_call(lambda: research_store.create_task(payload))


@app.get("/v1/research/tasks/{task_id}")
def get_research_task(task_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        task = research_store.get_task(task_id)
        if task["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("research task not found")
        return task

    return _research_call(operation)


@app.get("/v1/research/tasks")
def list_research_tasks(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _research_call(lambda: research_store.list_tasks(owner_principal=context["owner_principal"]))


@app.post("/v1/research/tasks/{task_id}/transitions")
def transition_research_task(task_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("research_task", task_id, payload)


@app.post("/v1/research/experiments", status_code=201)
def create_experiment(payload: dict[str, Any]) -> dict[str, object]:
    return _research_call(lambda: research_store.create_experiment(payload))


@app.get("/v1/research/experiments/{experiment_id}")
def get_experiment(experiment_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        experiment = research_store.get_experiment(experiment_id)
        if experiment["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("experiment not found")
        return experiment

    return _research_call(operation)


@app.get("/v1/research/experiments")
def list_experiments(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _research_call(lambda: research_store.list_experiments(owner_principal=context["owner_principal"]))


@app.post("/v1/research/experiments/{experiment_id}/transitions")
def transition_experiment(experiment_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("experiment", experiment_id, payload)


@app.post("/v1/research/artifacts", status_code=201)
def create_artifact(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        lineage = payload.get("lineage")
        snapshot_id = lineage.get("stock_pool_snapshot_id") if isinstance(lineage, dict) else None
        owner = payload.get("owner_principal")
        if snapshot_id is not None:
            if not isinstance(owner, str) or not owner:
                raise ValueError("stock pool lineage requires owner_principal")
            paper_store.get_pool_snapshot(snapshot_id, trusted_owner=owner)
        artifact = research_store.create_artifact(payload)
        if snapshot_id is not None:
            paper_store.record_pool_reference(
                snapshot_id, domain="research", reference_id=artifact["artifact_id"],
                trusted_owner=artifact["owner_principal"],
            )
        return artifact
    return _research_call(operation)


@app.get("/v1/research/artifacts/{artifact_id}")
def get_artifact(artifact_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        artifact = research_store.get_artifact(artifact_id)
        if artifact["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("artifact not found")
        return artifact

    return _research_call(operation)


@app.get("/v1/research/artifacts")
def list_artifacts(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _research_call(lambda: research_store.list_artifacts(owner_principal=context["owner_principal"]))


@app.post("/v1/research/factors/compute", status_code=201)
def compute_research_factor(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        computed = compute_factor(payload)
        artifact_payload = {
            "task_id": payload.get("task_id"),
            "experiment_id": payload.get("experiment_id"),
            "kind": "factor_result",
            "content": computed["artifact_content"],
            "lineage": computed["artifact_lineage"],
            "trace_id": payload.get("trace_id"),
            "idempotency_key": payload.get("idempotency_key"),
        }
        artifact = research_store.create_artifact(artifact_payload)
        return {
            "factor": computed["factor"],
            "input_manifest": computed["input_manifest"],
            "coverage": computed["coverage"],
            "artifact": artifact,
        }

    return _research_call(operation)


@app.post("/v1/research/strategies/validate", status_code=201)
def validate_strategy_draft(payload: dict[str, Any], http_request: Request) -> dict[str, object]:
    context = _required_agent_context(http_request)

    def operation() -> dict[str, object]:
        strategy_request = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "strategy", "trace_id", "idempotency_key"},
        )
        task = research_store.get_task(strategy_request.get("task_id"))
        if task["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("research task not found")
        prepared = prepare_strategy(strategy_request.get("strategy"))
        artifact = research_store.create_artifact(
            {
                "task_id": strategy_request.get("task_id"),
                "experiment_id": strategy_request.get("experiment_id"),
                "kind": "strategy_draft",
                "content": strategy_draft_content(prepared),
                "lineage": [],
                "trace_id": strategy_request.get("trace_id"),
                "idempotency_key": strategy_request.get("idempotency_key"),
            }
        )
        if artifact["status"] == "draft":
            artifact = research_store.transition(
                "artifact",
                artifact["artifact_id"],
                "validated",
                f"strategy-draft-validate-{prepared['version_id']}",
            )
        return {"strategy": prepared["snapshot"], "validation": prepared["validation"], "artifact": artifact}

    return _research_call(operation)


@app.post("/v1/research/strategies/versions", status_code=201)
def create_strategy_version(payload: dict[str, Any], http_request: Request) -> dict[str, object]:
    context = _required_agent_context(http_request)

    def operation() -> dict[str, object]:
        strategy_request = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "draft_artifact_id", "trace_id", "idempotency_key"},
        )
        draft = research_store.get_artifact(strategy_request.get("draft_artifact_id"))
        if draft["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("strategy draft not found")
        if draft["kind"] != "strategy_draft":
            raise ValueError("draft_artifact_id must reference a strategy_draft artifact")
        if draft["task_id"] != strategy_request.get("task_id"):
            raise ValueError("draft artifact does not belong to task_id")
        draft_content = draft["content"]
        if not isinstance(draft_content, dict):
            raise ValueError("strategy draft content is invalid")
        prepared = prepare_strategy(draft_content.get("snapshot"))
        if draft_content.get("validation") != prepared["validation"]:
            raise ValueError("strategy draft validation evidence does not match its snapshot")
        version_content = strategy_version_content(prepared)
        version_fingerprint = content_sha256(version_content)
        artifact = research_store.find_artifact_by_content(
            strategy_request.get("task_id"), "strategy_version", version_fingerprint
        )
        if artifact is None:
            artifact = research_store.create_artifact(
                {
                    "task_id": strategy_request.get("task_id"),
                    "experiment_id": strategy_request.get("experiment_id"),
                    "kind": "strategy_version",
                    "content": version_content,
                    "lineage": [{"kind": "artifact", "id": draft["artifact_id"]}],
                    "trace_id": strategy_request.get("trace_id"),
                    "idempotency_key": strategy_request.get("idempotency_key"),
                }
            )
        if artifact["status"] == "draft":
            artifact = research_store.transition(
                "artifact",
                artifact["artifact_id"],
                "validated",
                f"strategy-version-validate-{prepared['version_id']}",
            )
        return {
            "strategy_version": version_content,
            "artifact": artifact,
            "source_draft_artifact_id": draft["artifact_id"],
        }

    return _research_call(operation)


@app.post("/v1/research/strategies/approvals", status_code=201)
def create_strategy_approval(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        request = _strategy_payload(
            payload,
            {
                "task_id", "experiment_id", "strategy_version_artifact_id", "reviewer_principal",
                "decision", "rationale", "trace_id", "idempotency_key",
            },
        )
        version_artifact = research_store.get_artifact(request.get("strategy_version_artifact_id"))
        if version_artifact["kind"] != "strategy_version":
            raise ValueError("strategy_version_artifact_id must reference a strategy_version artifact")
        if version_artifact["task_id"] != request.get("task_id"):
            raise ValueError("strategy version artifact does not belong to task_id")
        if version_artifact["status"] != "validated":
            raise ValueError("strategy version must be validated before approval")
        version_content = validate_version_content(version_artifact["content"])
        reviewer = request.get("reviewer_principal")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 128:
            raise ValueError("reviewer_principal must be a non-empty string")
        decision = request.get("decision")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        rationale = request.get("rationale", "")
        if not isinstance(rationale, str) or len(rationale) > 4000:
            raise ValueError("rationale must be a string of at most 4000 characters")
        approval_content = {
            "schema_version": "strategy-approval-v1",
            "strategy_version_id": version_content["version_id"],
            "strategy_version_artifact_id": version_artifact["artifact_id"],
            "decision": decision,
            "reviewer_principal": reviewer.strip(),
            "rationale": rationale,
            "execution_authorized": decision == "approved",
            "execution_outcome": "not_started",
        }
        approval = research_store.create_artifact(
            {
                "task_id": request.get("task_id"),
                "experiment_id": request.get("experiment_id"),
                "kind": "strategy_approval",
                "content": approval_content,
                "lineage": [{"kind": "artifact", "id": version_artifact["artifact_id"]}],
                "trace_id": request.get("trace_id"),
                "idempotency_key": request.get("idempotency_key"),
            }
        )
        if approval["status"] == "draft":
            approval = research_store.transition(
                "artifact",
                approval["artifact_id"],
                "validated",
                f"strategy-approval-validate-{request.get('idempotency_key')}",
            )
        return {"approval": approval_content, "artifact": approval}

    return _research_call(operation)


@app.get("/v1/research/strategies/versions/{artifact_id}/export")
def export_strategy_version_artifact(artifact_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        artifact = research_store.get_artifact(artifact_id)
        if artifact["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("strategy version not found")
        if artifact["kind"] != "strategy_version":
            raise ValueError("artifact is not a strategy_version")
        exported = export_strategy_version(artifact["content"])
        return {
            "strategy_version_id": exported["version_id"],
            "content_sha256": artifact["content_sha256"],
            "export": exported,
        }

    return _research_call(operation)


_STRATEGY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")


@app.post("/v1/research/strategies/drafts", status_code=201)
def save_strategy_draft(payload: dict[str, Any], http_request: Request) -> dict[str, object]:
    """Durably save a strategy draft (Phase 33).

    Persists the current editor content as an immutable strategy_draft
    artifact. Unlike validate, this tolerates intermediate edits that do not
    yet pass static validation (validation.success records the outcome);
    creating a version still requires a validated draft.
    """
    context = _required_agent_context(http_request)

    def operation() -> dict[str, object]:
        strategy_request = _strategy_payload(
            payload, {"task_id", "experiment_id", "strategy", "trace_id", "idempotency_key"}
        )
        task = research_store.get_task(strategy_request.get("task_id"))
        if task["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("research task not found")
        prepared = prepare_strategy_draft(strategy_request.get("strategy"))
        artifact = research_store.create_artifact(
            {
                "task_id": strategy_request.get("task_id"),
                "experiment_id": strategy_request.get("experiment_id"),
                "kind": "strategy_draft",
                "content": strategy_draft_content(prepared),
                "lineage": [],
                "trace_id": strategy_request.get("trace_id"),
                "idempotency_key": strategy_request.get("idempotency_key"),
            }
        )
        return {
            "strategy": prepared["snapshot"],
            "validation": prepared["validation"],
            "artifact": artifact,
        }

    return _research_call(operation)


@app.delete("/v1/research/strategies/drafts/{artifact_id}")
def delete_strategy_draft(artifact_id: str, request: Request) -> dict[str, object]:
    """Delete (soft-supersede) an owner-scoped strategy draft (Phase 33).

    Drafts are immutable audit artifacts, so deletion is recorded as a
    superseded status transition rather than a physical row removal.
    """
    def operation() -> dict[str, object]:
        context = _required_agent_context(request)
        artifact = research_store.get_artifact(artifact_id)
        if artifact["kind"] != "strategy_draft":
            raise ValueError("artifact is not a strategy draft")
        if artifact["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("strategy draft not found")
        if artifact["status"] not in {"draft", "validated"}:
            raise ValueError("strategy draft is already superseded")
        transitioned = research_store.transition(
            "artifact", artifact_id, "superseded", f"strategy-draft-delete-{artifact_id[:16]}"
        )
        return {"artifact": transitioned}

    return _research_call(operation)


@app.get("/v1/research/strategies/{strategy_id}/versions")
def strategy_version_history(strategy_id: str, request: Request) -> dict[str, object]:
    """List version history for one strategy (Phase 33)."""
    context = _required_agent_context(request)
    if _STRATEGY_ID_RE.fullmatch(strategy_id) is None:
        raise ValueError("strategy_id has invalid format")
    artifacts = research_store.list_artifacts(owner_principal=context["owner_principal"])["artifacts"]
    versions: list[dict[str, object]] = []
    for item in artifacts:
        if item["kind"] != "strategy_version":
            continue
        content = item["content"]
        if not isinstance(content, dict) or content.get("strategy_id") != strategy_id:
            continue
        versions.append(
            {
                "artifact_id": item["artifact_id"],
                "status": item["status"],
                "version_id": content.get("version_id"),
                "source_fingerprint": content.get("source_fingerprint"),
                "created_at": item["created_at"],
            }
        )
    versions.sort(key=lambda row: str(row["created_at"]), reverse=True)
    return {"strategy_id": strategy_id, "versions": versions}


@app.get("/v1/research/strategies/{strategy_id}/backtest-count")
def strategy_backtest_count(strategy_id: str, request: Request) -> dict[str, object]:
    """Return backtest job counts per strategy version (Phase 33 projection)."""
    context = _required_agent_context(request)
    if _STRATEGY_ID_RE.fullmatch(strategy_id) is None:
        raise ValueError("strategy_id has invalid format")
    artifacts = research_store.list_artifacts(owner_principal=context["owner_principal"])["artifacts"]
    version_ids: list[str] = []
    for item in artifacts:
        if item["kind"] != "strategy_version":
            continue
        content = item["content"]
        if isinstance(content, dict) and content.get("strategy_id") == strategy_id:
            version_ids.append(item["artifact_id"])
    counts = backtest_store.count_by_strategy_versions(version_ids)
    return {
        "strategy_id": strategy_id,
        "version_count": len(version_ids),
        "backtest_count": sum(counts.values()),
        "by_version": counts,
    }


@app.post("/v1/research/artifacts/{artifact_id}/transitions")
def transition_artifact(artifact_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("artifact", artifact_id, payload)


def _validated_backtest_request(payload: dict[str, Any]) -> dict[str, object]:
    allowed = {
        "task_id", "experiment_id", "strategy_version_artifact_id", "approval_artifact_id",
        "trace_id", "idempotency_key", "universe", "bars", "signals", "execution", "corporate_actions",
        "signal_snapshot_artifact_id",
    }
    request = _strategy_payload(payload, allowed)
    snapshot_content: dict[str, Any] | None = None
    snapshot_artifact_id = request.get("signal_snapshot_artifact_id")
    if snapshot_artifact_id is not None:
        # ADR-0017: materialize the frozen input from an immutable,
        # validated signal_snapshot artifact instead of inline bars/signals.
        snapshot = research_store.get_artifact(snapshot_artifact_id)
        if snapshot["kind"] != "signal_snapshot":
            raise ValueError("signal_snapshot_artifact_id must reference a signal_snapshot artifact")
        if snapshot["status"] != "validated":
            raise ValueError("signal snapshot must be validated before backtest")
        if snapshot["task_id"] != request.get("task_id"):
            raise ValueError("signal snapshot artifact does not belong to task_id")
        snapshot_content = snapshot["content"]
        if not isinstance(snapshot_content, dict):
            raise ValueError("signal snapshot content is invalid")
        snapshot_strategy = snapshot_content.get("strategy")
        if not isinstance(snapshot_strategy, dict):
            raise ValueError("signal snapshot strategy reference is invalid")
        if snapshot_strategy.get("strategy_version_artifact_id") != request.get("strategy_version_artifact_id"):
            raise ValueError("signal snapshot does not match the selected strategy version")
        for key in ("universe", "bars", "signals", "execution", "corporate_actions"):
            if key not in snapshot_content:
                raise ValueError(f"signal snapshot content is missing {key}")
    version_artifact = research_store.get_artifact(request.get("strategy_version_artifact_id"))
    if version_artifact["kind"] != "strategy_version":
        raise ValueError("strategy_version_artifact_id must reference a strategy_version artifact")
    if version_artifact["status"] != "validated":
        raise ValueError("strategy version must be validated before backtest")
    if version_artifact["task_id"] != request.get("task_id"):
        raise ValueError("strategy version artifact does not belong to task_id")
    validated_version = validate_version_content(version_artifact["content"])
    approval_artifact = research_store.get_artifact(request.get("approval_artifact_id"))
    if approval_artifact["kind"] != "strategy_approval" or approval_artifact["status"] != "validated":
        raise ValueError("approval_artifact_id must reference a validated strategy approval")
    if approval_artifact["task_id"] != request.get("task_id"):
        raise ValueError("approval artifact does not belong to task_id")
    approval = approval_artifact["content"]
    if not isinstance(approval, dict):
        raise ValueError("strategy approval content is invalid")
    if approval.get("strategy_version_artifact_id") != version_artifact["artifact_id"]:
        raise ValueError("approval does not authorize this strategy version")
    if approval.get("decision") != "approved" or approval.get("execution_authorized") is not True:
        raise ValueError("strategy version is not approved for execution")
    if validated_version.get("version_id") != version_artifact["content"].get("version_id"):
        raise ValueError("strategy version content is inconsistent")
    task = research_store.get_task(request.get("task_id"))
    experiment_id = request.get("experiment_id")
    if experiment_id is not None:
        experiment = research_store.get_experiment(experiment_id)
        if experiment["task_id"] != task["task_id"]:
            raise ValueError("experiment does not belong to task_id")
    if snapshot_content is not None:
        manifest, input_manifest_id = build_manifest(
            strategy_version_artifact_id=version_artifact["artifact_id"],
            approval_artifact_id=approval_artifact["artifact_id"],
            universe=snapshot_content["universe"],
            bars=snapshot_content["bars"],
            signals=snapshot_content["signals"],
            corporate_actions=snapshot_content["corporate_actions"],
            execution=snapshot_content["execution"],
        )
        return {
            "task_id": task["task_id"],
            "experiment_id": experiment_id,
            "strategy_version_artifact_id": version_artifact["artifact_id"],
            "approval_artifact_id": approval_artifact["artifact_id"],
            "trace_id": request["trace_id"],
            "idempotency_key": request["idempotency_key"],
            "manifest": manifest,
            "input_manifest_id": input_manifest_id,
        }
    return normalize_backtest_request(
        request,
        strategy_version_artifact_id=version_artifact["artifact_id"],
        approval_artifact_id=approval_artifact["artifact_id"],
    )


@app.post("/v1/research/signal-snapshots", status_code=201)
def create_signal_snapshot(payload: dict[str, Any]) -> dict[str, object]:
    """Create a validated signal_snapshot artifact from a keyless import.

    ADR-0017: the snapshot is the immutable frozen input reference for a
    backtest submission. Phase 32 does not execute strategy source; this is
    the explicit keyless fixture/import path (tests and demos) until a
    dedicated signal-producer ADR lands.
    """
    def operation() -> dict[str, object]:
        request = _strategy_payload(
            payload,
            {
                "task_id", "experiment_id", "strategy_version_artifact_id", "universe",
                "bars", "signals", "execution", "corporate_actions", "source",
                "trace_id", "idempotency_key",
            },
        )
        version = research_store.get_artifact(request.get("strategy_version_artifact_id"))
        if version["kind"] != "strategy_version":
            raise ValueError("strategy_version_artifact_id must reference a strategy_version artifact")
        if version["status"] != "validated":
            raise ValueError("strategy version must be validated before creating a signal snapshot")
        if version["task_id"] != request.get("task_id"):
            raise ValueError("strategy version artifact does not belong to task_id")
        validated_version = validate_version_content(version["content"])
        document = normalize_signal_snapshot(
            {
                "universe": request.get("universe"),
                "bars": request.get("bars"),
                "signals": request.get("signals"),
                "execution": request.get("execution"),
                "corporate_actions": request.get("corporate_actions"),
                "source": request.get("source"),
            },
            strategy_version_artifact_id=version["artifact_id"],
            strategy_version_id=validated_version.get("version_id"),
        )
        fingerprint = signal_snapshot_content_sha256(document)
        artifact = research_store.find_artifact_by_content(
            request.get("task_id"), "signal_snapshot", fingerprint
        )
        if artifact is None:
            artifact = research_store.create_artifact(
                {
                    "task_id": request.get("task_id"),
                    "experiment_id": request.get("experiment_id"),
                    "kind": "signal_snapshot",
                    "content": document,
                    "lineage": [{"kind": "artifact", "id": version["artifact_id"]}],
                    "trace_id": request.get("trace_id"),
                    "idempotency_key": request.get("idempotency_key"),
                }
            )
        if artifact["status"] == "draft":
            artifact = research_store.transition(
                "artifact",
                artifact["artifact_id"],
                "validated",
                f"signal-snapshot-validate-{fingerprint[:16]}",
            )
        return {
            "snapshot": document,
            "artifact": artifact,
            "source_strategy_version_artifact_id": version["artifact_id"],
        }

    return _backtest_call(operation)


@app.get("/v1/research/signal-snapshots/{artifact_id}")
def get_signal_snapshot(artifact_id: str) -> dict[str, object]:
    return _research_call(lambda: {"snapshot": research_store.get_artifact(artifact_id)})


@app.get("/v1/research/signal-snapshots")
def list_signal_snapshots(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    artifacts = research_store.list_artifacts(owner_principal=context["owner_principal"])
    snapshots = [item for item in artifacts["artifacts"] if item["kind"] == "signal_snapshot"]
    return {"snapshots": snapshots}


@app.post("/v1/research/backtests", status_code=202)
def create_backtest_job(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        validation_payload = dict(payload)
        stock_pool_snapshot_id = validation_payload.pop("stock_pool_snapshot_id", None)
        backtest_request = _validated_backtest_request(validation_payload)
        task = research_store.get_task(backtest_request["task_id"])
        if task["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("research task not found")
        if stock_pool_snapshot_id is not None:
            snapshot = paper_store.get_pool_snapshot(
                stock_pool_snapshot_id, trusted_owner=context["owner_principal"]
            )
            pool = paper_store.get_pool(snapshot["pool_id"], trusted_owner=context["owner_principal"])
            if pool["status"] != "active":
                raise ValueError("stock pool must be active for a new backtest reference")
            manifest = backtest_request["manifest"]
            universe = manifest.get("universe") if isinstance(manifest, dict) else None
            if not isinstance(universe, dict) or not isinstance(universe.get("symbols"), list):
                raise ValueError("backtest manifest universe is invalid")
            pool_symbols = {item["symbol"] for item in snapshot.get("members", [])}
            requested = {str(item) for item in universe["symbols"]}
            if not requested.issubset(pool_symbols):
                raise ValueError("backtest universe escapes the stock pool snapshot")
            frozen_universe = dict(universe)
            frozen_universe["universe_id"] = snapshot["pool_id"]
            frozen_universe["version_id"] = snapshot["snapshot_id"]
            frozen_universe["membership_fingerprint"] = membership_fingerprint(requested)
            frozen_universe["stock_pool_snapshot_id"] = snapshot["snapshot_id"]
            rebuilt, manifest_id = build_manifest(
                strategy_version_artifact_id=backtest_request["strategy_version_artifact_id"],
                approval_artifact_id=backtest_request["approval_artifact_id"],
                universe=frozen_universe,
                bars=manifest["bars"], signals=manifest["signals"],
                corporate_actions=manifest["corporate_actions"], execution=manifest["execution"],
            )
            backtest_request["manifest"] = rebuilt
            backtest_request["input_manifest_id"] = manifest_id
            backtest_request["stock_pool_snapshot_id"] = snapshot["snapshot_id"]
        job = backtest_store.create(backtest_request, owner_principal=context["owner_principal"])
        if stock_pool_snapshot_id is not None:
            paper_store.record_pool_reference(
                stock_pool_snapshot_id,
                domain="backtest",
                reference_id=job["job_id"],
                trusted_owner=context["owner_principal"],
            )
        return {"job": job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/options")
def backtest_options(request: Request) -> dict[str, object]:
    """Return runnable backtest options for the wizard (Phase 32, ADR-0017).

    Aggregates validated strategy versions that have an approved
    strategy_approval for the caller, with the task/approval identities the
    wizard needs to submit a backtest referencing a signal_snapshot.
    """
    context = _required_agent_context(request)
    artifacts = research_store.list_artifacts(owner_principal=context["owner_principal"])["artifacts"]
    versions = {
        item["artifact_id"]: item
        for item in artifacts
        if item["kind"] == "strategy_version" and item["status"] == "validated"
    }
    approved_by_version: dict[str, str] = {}
    for item in artifacts:
        if item["kind"] != "strategy_approval" or item["status"] != "validated":
            continue
        content = item["content"]
        if not isinstance(content, dict):
            continue
        if content.get("decision") != "approved" or content.get("execution_authorized") is not True:
            continue
        version_id = content.get("strategy_version_artifact_id")
        if isinstance(version_id, str) and version_id in versions and version_id not in approved_by_version:
            approved_by_version[version_id] = item["artifact_id"]
    options: list[dict[str, object]] = []
    for version_id, item in versions.items():
        if version_id not in approved_by_version:
            continue
        content = item["content"]
        if not isinstance(content, dict):
            continue
        options.append(
            {
                "strategy_version_artifact_id": version_id,
                "task_id": item["task_id"],
                "approval_artifact_id": approved_by_version[version_id],
                "strategy_id": content.get("strategy_id"),
                "strategy_version_id": content.get("version_id"),
            }
        )
    return {"options": options}


@app.get("/v1/research/backtests/{job_id}")
def get_backtest_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        return {"job": job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/{job_id}/result")
def get_backtest_result(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    job = _backtest_call(lambda: backtest_store.get(job_id))
    if job["owner_principal"] != context["owner_principal"]:
        raise HTTPException(status_code=404, detail="backtest result not found")
    reference = job.get("result_reference")
    if not isinstance(reference, dict):
        raise HTTPException(status_code=409, detail="backtest job has no result yet")
    try:
        result = load_result(backtest_objects, reference)
    except ObjectIntegrityError as error:
        raise HTTPException(status_code=503, detail="backtest result object is unavailable") from error
    return {"job_id": job_id, "result": result}


@app.get("/v1/research/backtests")
def list_backtest_jobs(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _backtest_call(lambda: backtest_store.list_backtests(owner_principal=context["owner_principal"]))


@app.post("/v1/research/backtests/{job_id}/run")
def run_backtest_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        worker = BacktestWorker(backtest_store, research_store, backtest_objects)
        return {"job": worker.run_once(job_id)}

    return _backtest_call(operation)


@app.post("/v1/research/backtests/{job_id}/cancel")
def cancel_backtest_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        return {"job": backtest_store.cancel(job_id)}

    return _backtest_call(operation)

@app.delete("/v1/research/backtests/{job_id}")
def delete_backtest_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    def operation() -> dict[str, object]:
        deleted = backtest_store.delete(job_id, owner_principal=context["owner_principal"])
        _gc_deleted_backtest_objects(deleted, owner_principal=context["owner_principal"])
        return {"job": deleted}

    return _backtest_call(operation)


def _gc_deleted_backtest_objects(deleted_job: dict[str, object], *, owner_principal: str) -> None:
    """Best-effort garbage collection of a deleted job's result object.

    Result objects are content-addressed and may be shared across jobs, so the
    object is removed only when no other stored job still references it. GC is
    a pure side effect; the DELETE response contract is unchanged.
    """
    reference = deleted_job.get("result_reference")
    if not isinstance(reference, dict):
        return
    try:
        live_references = backtest_store.all_result_references()
        backtest_objects.delete_if_unreferenced(
            reference,
            live_references=live_references,
            actor_scope=owner_principal,
            owner_scope=deleted_job.get("owner_principal", owner_principal),
        )
    except (BacktestError, OSError):
        return


@app.get("/v1/agents/roles")
def get_agent_roles() -> dict[str, object]:
    """Return the versioned BYQ role catalogue, not DSH implementation state."""

    return {"roles": role_catalog()}


@app.post("/v1/agents/runs", status_code=201)
def start_agent_run(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = dict(payload)
    for field, value in context.items():
        if value is not None:
            request_payload[field] = value
    return _agent_call(lambda: {"run": agent_store.start_run(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/agents/authorize")
def authorize_agent_action(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _agent_call(lambda: {"authorization": agent_store.authorize(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/agents/audit")
def record_agent_audit(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _agent_call(lambda: {"audit": agent_store.record_audit(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/agents/runs/{run_id}/audit")
def get_agent_audit(run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _agent_call(lambda: agent_store.list_audit(run_id, trusted_owner=context["owner_principal"]))


@app.post("/v1/agents/approvals", status_code=201)
def create_agent_approval(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _agent_call(lambda: {"approval": agent_store.create_approval(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/agents/approvals/{approval_id}")
def get_agent_approval(approval_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _agent_call(lambda: {"approval": agent_store.get_approval(
        approval_id,
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/agents/approvals")
def list_agent_approvals(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _agent_call(lambda: agent_store.list_approvals(trusted_owner=context["owner_principal"]))


@app.post("/v1/agents/approvals/{approval_id}/decision")
def decide_agent_approval(approval_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = dict(payload)
    request_payload["approval_id"] = approval_id
    return _agent_call(lambda: {"approval": agent_store.decide_approval(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/learning/runs", status_code=201)
def start_learning_run(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["trace_id"] = context["trace_id"]
    return _learning_call(lambda: {"run": learning_store.start_run(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/learning/runs/{run_id}")
def get_learning_run(run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _learning_call(lambda: {"run": learning_store.get_run(
        run_id,
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/learning/runs/{run_id}/iterations", status_code=201)
def record_learning_iteration(run_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["run_id"] = run_id
    request_payload["trace_id"] = context["trace_id"]
    return _learning_call(lambda: learning_store.record_iteration(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    ))


@app.get("/v1/learning/runs/{run_id}/iterations")
def list_learning_iterations(run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _learning_call(lambda: learning_store.list_iterations(
        run_id,
        trusted_owner=context["owner_principal"],
    ))


@app.post("/v1/learning/runs/{run_id}/review")
def review_learning_run(run_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["run_id"] = run_id
    return _learning_call(lambda: {"run": learning_store.review_run(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/learning/signals", status_code=201)
def create_evaluation_signal(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["trace_id"] = context["trace_id"]
    return _learning_call(lambda: {"signal": learning_store.create_signal(
        request_payload,
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/learning/signals/{signal_id}")
def get_evaluation_signal(signal_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _learning_call(lambda: {"signal": learning_store.get_signal(
        signal_id,
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/learning/experiments/compare")
def compare_experiments(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    return _learning_call(lambda: learning_store.compare_experiments(
        request_payload,
        trusted_owner=context["owner_principal"],
    ))


@app.post("/v1/learning/lessons", status_code=201)
def propose_lesson(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["trace_id"] = context["trace_id"]
    return _learning_call(lambda: learning_store.propose_lesson(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    ))


@app.get("/v1/learning/lessons/{lesson_id}")
def get_lesson(lesson_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _learning_call(lambda: {"lesson": learning_store.get_lesson(
        lesson_id,
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/learning/lessons/{lesson_id}/review")
def review_lesson(lesson_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["lesson_id"] = lesson_id
    return _learning_call(lambda: {"lesson": learning_store.review_lesson(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/engineering/tasks", status_code=201)
def create_engineering_task(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["trace_id"] = context["trace_id"]
    return _engineering_call(lambda: {"task": engineering_store.create_task(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/engineering/tasks")
def list_engineering_tasks(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _engineering_call(lambda: engineering_store.list_tasks(
        trusted_owner=context["owner_principal"],
    ))


@app.get("/v1/engineering/tasks/{task_id}")
def get_engineering_task(task_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _engineering_call(lambda: {"task": engineering_store.get_task(
        task_id,
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/engineering/tasks/{task_id}/transitions", status_code=201)
def transition_engineering_task(task_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["task_id"] = task_id
    return _engineering_call(lambda: {"task": engineering_store.transition(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/engineering/tasks/{task_id}/evidence", status_code=200)
def report_engineering_evidence(task_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["task_id"] = task_id
    return _engineering_call(lambda: {"task": engineering_store.report_evidence(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/engineering/tasks/{task_id}/merge")
def record_human_engineering_merge(task_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    request_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }
    request_payload["task_id"] = task_id
    return _engineering_call(lambda: {"task": engineering_store.record_human_merge(
        request_payload,
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.post("/v1/paper/accounts", status_code=201)
def create_paper_account(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"account": paper_store.create_account(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/accounts/{account_id}")
def get_paper_account(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"account": paper_store.get_account(
        account_id,
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/accounts")
def list_paper_accounts(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_accounts(trusted_owner=context["owner_principal"]))


@app.post("/v1/paper/pools", status_code=201)
def create_stock_pool(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"pool": paper_store.create_pool(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/pools/{pool_id}")
def get_stock_pool(pool_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"pool": paper_store.get_pool(
        pool_id,
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/pools")
def list_stock_pools(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_pools(trusted_owner=context["owner_principal"], limit=limit, offset=offset))


@app.patch("/v1/paper/pools/{pool_id}/metadata")
def update_stock_pool_metadata(pool_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"pool": paper_store.update_pool_metadata(
        pool_id, payload, trusted_owner=context["owner_principal"]
    )})


@app.put("/v1/paper/pools/{pool_id}/snapshot")
def replace_stock_pool_snapshot(pool_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"snapshot": paper_store.replace_pool_snapshot(
        pool_id, payload, trusted_owner=context["owner_principal"]
    )})


@app.get("/v1/paper/pools/{pool_id}/snapshots")
def list_stock_pool_snapshots(pool_id: str, request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_pool_snapshots(
        pool_id, trusted_owner=context["owner_principal"], limit=limit, offset=offset
    ))


@app.get("/v1/paper/pools/{pool_id}/snapshots/{snapshot_id}")
def get_stock_pool_snapshot(pool_id: str, snapshot_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    def operation() -> dict[str, object]:
        snapshot = paper_store.get_pool_snapshot(snapshot_id, trusted_owner=context["owner_principal"])
        if snapshot["pool_id"] != pool_id:
            raise PaperTradingNotFound("stock pool snapshot not found")
        return {"snapshot": snapshot}
    return _paper_call(operation)


@app.get("/v1/paper/pools/{pool_id}/as-of/{trade_date}")
def get_stock_pool_as_of(pool_id: str, trade_date: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"snapshot": paper_store.get_pool_as_of(
        pool_id, trade_date, trusted_owner=context["owner_principal"]
    )})


@app.patch("/v1/paper/pools/{pool_id}/lifecycle")
def update_stock_pool_lifecycle(pool_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"pool": paper_store.set_pool_lifecycle(
        pool_id, payload, trusted_owner=context["owner_principal"], trusted_actor=context["actor_principal"]
    )})


@app.delete("/v1/paper/pools/{pool_id}")
def delete_stock_pool(pool_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    payload = {
        "status": "deleted",
        "reason": request.headers.get("x-byq-delete-reason") or "user requested deletion",
        "idempotency_key": request.headers.get("x-idempotency-key") or f"delete-{pool_id}",
    }
    return _paper_call(lambda: {"pool": paper_store.set_pool_lifecycle(
        pool_id, payload, trusted_owner=context["owner_principal"], trusted_actor=context["actor_principal"]
    )})


@app.get("/v1/paper/pools/{pool_id}/references")
def list_stock_pool_references(pool_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.pool_references(
        pool_id, trusted_owner=context["owner_principal"]
    ))


@app.post("/v1/paper/orders", status_code=201)
def submit_paper_order(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"order": paper_store.submit_order(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/accounts/{account_id}/orders")
def list_paper_orders(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_orders(
        account_id,
        trusted_owner=context["owner_principal"],
    ))


@app.get("/v1/paper/accounts/{account_id}/orders/{order_id}")
def get_paper_order(account_id: str, order_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"order": paper_store.get_order(
        account_id, order_id, trusted_owner=context["owner_principal"]
    )})


@app.get("/v1/paper/accounts/{account_id}/positions")
def list_paper_positions(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_positions(
        account_id,
        trusted_owner=context["owner_principal"],
    ))


@app.get("/v1/paper/accounts/{account_id}/fills")
def list_paper_fills(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_fills(
        account_id,
        trusted_owner=context["owner_principal"],
    ))


@app.get("/v1/paper/accounts/{account_id}/ledger")
def list_paper_ledger(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_ledger(
        account_id, trusted_owner=context["owner_principal"]
    ))


@app.get("/v1/paper/accounts/{account_id}/snapshots")
def list_paper_account_snapshots(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_snapshots(
        account_id, trusted_owner=context["owner_principal"]
    ))


@app.post("/v1/paper/accounts/{account_id}/settlements", status_code=201)
def settle_paper_account(account_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"snapshot": paper_store.settle_account(
        account_id, payload, trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/paper/accounts/{account_id}/controls")
def get_paper_account_controls(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"controls": paper_store.get_controls(
        account_id, trusted_owner=context["owner_principal"]
    )})


@app.put("/v1/paper/accounts/{account_id}/controls")
def update_paper_account_controls(account_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"controls": paper_store.update_controls(
        account_id, payload, trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.put("/v1/paper/accounts/{account_id}/binding")
def rebind_paper_account(account_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"account": paper_store.rebind_account(
        account_id, payload, trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    )})


@app.get("/v1/paper/accounts/{account_id}/export")
def export_paper_account(account_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"bundle": paper_store.export_bundle(
        account_id, trusted_owner=context["owner_principal"]
    )})


@app.post("/v1/paper/accounts/import", status_code=201)
def import_paper_account(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    bundle = payload.get("bundle", payload)
    return _paper_call(lambda: paper_store.import_bundle(
        bundle, trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    ))


@app.post("/v1/auth/login")
def login(payload: dict[str, Any]) -> dict[str, object]:
    return _user_call(lambda: user_store.login(payload.get("username"), payload.get("password")))


@app.post("/v1/auth/logout")
def logout(payload: dict[str, Any]) -> dict[str, object]:
    return _user_call(lambda: user_store.logout(payload.get("session_id")))


@app.get("/v1/auth/session")
def get_session(request: Request) -> dict[str, object]:
    session_id = request.headers.get("x-byq-session-id")
    if not session_id:
        raise HTTPException(status_code=401, detail="session required")
    return _user_call(lambda: {"user": user_store.get_session_user(session_id)})


@app.post("/v1/users", status_code=201)
def create_user(payload: dict[str, Any], request: Request) -> dict[str, object]:
    actor_role = request.headers.get("x-byq-actor-role")
    return _user_call(lambda: {"user": user_store.create_user(payload, actor_role=actor_role)})


@app.get("/v1/users")
def list_users(request: Request) -> dict[str, object]:
    actor_role = request.headers.get("x-byq-actor-role")
    return _user_call(lambda: user_store.list_users(actor_role=actor_role))


@app.post("/v1/users/{user_id}/disable")
def disable_user(user_id: str, request: Request) -> dict[str, object]:
    actor_role = request.headers.get("x-byq-actor-role")
    return _user_call(lambda: {"user": user_store.disable_user(user_id, actor_role=actor_role)})


@app.put("/v1/users/{user_id}/profile")
def update_user_profile(user_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    owner_user_id = request.headers.get("x-byq-owner-user-id")
    if owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="profile update is owner-scoped")
    return _user_call(lambda: {"user": user_store.update_profile(user_id, payload)})


def _policy_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except UserPolicyPersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/v1/users/agent-policy")
def get_user_agent_policy(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {"policy": public_policy(user_policy_store.get(context["owner_principal"]))})


@app.put("/v1/users/agent-policy")
def update_user_agent_policy(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {"policy": public_policy(user_policy_store.update(context["owner_principal"], payload))})
