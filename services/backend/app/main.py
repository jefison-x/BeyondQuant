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
from .research import (
    IdempotencyConflict,
    InvalidTransition,
    ResearchNotFound,
    ResearchPersistenceError,
    ResearchStore,
)


SERVICE = "byq-backend"
VERSION = "0.1.0"

app = FastAPI(title="BeyondQuant Backend", version=VERSION)
data_provider = TushareProvider.from_env()
research_store = ResearchStore.from_env()


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


@app.post("/v1/research/artifacts/{artifact_id}/transitions")
def transition_artifact(artifact_id: str, payload: dict[str, Any]) -> dict[str, object]:
    return _research_transition("artifact", artifact_id, payload)
