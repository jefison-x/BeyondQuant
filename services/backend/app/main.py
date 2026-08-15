from fastapi import FastAPI
from fastapi import HTTPException
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
