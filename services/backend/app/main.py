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
    BacktestJobStore,
    BacktestNotFound,
    BacktestStorageError,
    BacktestWorker,
    LocalObjectStore,
    normalize_backtest_request,
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
def get_research_task(task_id: str) -> dict[str, object]:
    return _research_call(lambda: research_store.get_task(task_id))


@app.post("/v1/research/tasks/{task_id}/transitions")
def transition_research_task(task_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("research_task", task_id, payload)


@app.post("/v1/research/experiments", status_code=201)
def create_experiment(payload: dict[str, Any]) -> dict[str, object]:
    return _research_call(lambda: research_store.create_experiment(payload))


@app.get("/v1/research/experiments/{experiment_id}")
def get_experiment(experiment_id: str) -> dict[str, object]:
    return _research_call(lambda: research_store.get_experiment(experiment_id))


@app.post("/v1/research/experiments/{experiment_id}/transitions")
def transition_experiment(experiment_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("experiment", experiment_id, payload)


@app.post("/v1/research/artifacts", status_code=201)
def create_artifact(payload: dict[str, Any]) -> dict[str, object]:
    return _research_call(lambda: research_store.create_artifact(payload))


@app.get("/v1/research/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> dict[str, object]:
    return _research_call(lambda: research_store.get_artifact(artifact_id))


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
def validate_strategy_draft(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        request = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "strategy", "trace_id", "idempotency_key"},
        )
        prepared = prepare_strategy(request.get("strategy"))
        artifact = research_store.create_artifact(
            {
                "task_id": request.get("task_id"),
                "experiment_id": request.get("experiment_id"),
                "kind": "strategy_draft",
                "content": strategy_draft_content(prepared),
                "lineage": [],
                "trace_id": request.get("trace_id"),
                "idempotency_key": request.get("idempotency_key"),
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
def create_strategy_version(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        request = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "draft_artifact_id", "trace_id", "idempotency_key"},
        )
        draft = research_store.get_artifact(request.get("draft_artifact_id"))
        if draft["kind"] != "strategy_draft":
            raise ValueError("draft_artifact_id must reference a strategy_draft artifact")
        if draft["task_id"] != request.get("task_id"):
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
            request.get("task_id"), "strategy_version", version_fingerprint
        )
        if artifact is None:
            artifact = research_store.create_artifact(
                {
                    "task_id": request.get("task_id"),
                    "experiment_id": request.get("experiment_id"),
                    "kind": "strategy_version",
                    "content": version_content,
                    "lineage": [{"kind": "artifact", "id": draft["artifact_id"]}],
                    "trace_id": request.get("trace_id"),
                    "idempotency_key": request.get("idempotency_key"),
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
def export_strategy_version_artifact(artifact_id: str) -> dict[str, object]:
    def operation() -> dict[str, object]:
        artifact = research_store.get_artifact(artifact_id)
        if artifact["kind"] != "strategy_version":
            raise ValueError("artifact is not a strategy_version")
        exported = export_strategy_version(artifact["content"])
        return {
            "strategy_version_id": exported["version_id"],
            "content_sha256": artifact["content_sha256"],
            "export": exported,
        }

    return _research_call(operation)


@app.post("/v1/research/artifacts/{artifact_id}/transitions")
def transition_artifact(artifact_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("artifact", artifact_id, payload)


def _validated_backtest_request(payload: dict[str, Any]) -> dict[str, object]:
    allowed = {
        "task_id", "experiment_id", "strategy_version_artifact_id", "approval_artifact_id",
        "trace_id", "idempotency_key", "universe", "bars", "signals", "execution", "corporate_actions",
    }
    request = _strategy_payload(payload, allowed)
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
    return normalize_backtest_request(
        request,
        strategy_version_artifact_id=version_artifact["artifact_id"],
        approval_artifact_id=approval_artifact["artifact_id"],
    )


@app.post("/v1/research/backtests", status_code=202)
def create_backtest_job(payload: dict[str, Any]) -> dict[str, object]:
    def operation() -> dict[str, object]:
        request = _validated_backtest_request(payload)
        task = research_store.get_task(request["task_id"])
        job = backtest_store.create(request, owner_principal=task["owner_principal"])
        return {"job": job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/{job_id}")
def get_backtest_job(job_id: str) -> dict[str, object]:
    return _backtest_call(lambda: {"job": backtest_store.get(job_id)})


@app.post("/v1/research/backtests/{job_id}/run")
def run_backtest_job(job_id: str) -> dict[str, object]:
    def operation() -> dict[str, object]:
        worker = BacktestWorker(backtest_store, research_store, backtest_objects)
        return {"job": worker.run_once(job_id)}

    return _backtest_call(operation)


@app.post("/v1/research/backtests/{job_id}/cancel")
def cancel_backtest_job(job_id: str) -> dict[str, object]:
    return _backtest_call(lambda: {"job": backtest_store.cancel(job_id)})


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
