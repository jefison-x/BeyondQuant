import os
import re
import secrets
import time
from datetime import datetime, timedelta

from fastapi import BackgroundTasks, FastAPI
from fastapi import HTTPException, Request
from collections.abc import Callable
from typing import Any

from .data_provider import (
    DAILY_BASIC_FIELDS,
    FINANCIAL_INDICATOR_FIELDS,
    DailyRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderRateLimited,
    TushareProvider,
)
from .data_sync import (
    DataSyncConflict,
    DataSyncNotFound,
    DataSyncPersistenceError,
    DataSyncStore,
)
from .data_demand import (
    DataDemandConflict,
    DataDemandNotFound,
    DataDemandPersistenceError,
    DataDemandStore,
)
from .market_automation import (
    MarketAutomationConflict,
    MarketAutomationNotFound,
    MarketAutomationPersistenceError,
    MarketAutomationStore,
)
from .provider_runtime import resolved_tushare_provider
from .security_master import (
    SecurityMasterConflict,
    SecurityMasterNotFound,
    SecurityMasterPersistenceError,
    SecurityMasterStore,
)
from .conversation_catalog import (
    ConversationCatalogStore,
    ConversationConflict,
    ConversationNotFound,
    ConversationPersistenceError,
)
from .market_data import MarketDataPersistenceError, MarketDataStore
from .market_readiness import MarketReadinessPersistenceError, MarketReadinessStore
from .signal_producer import (
    SignalJobStore,
    SignalProducerConflict,
    SignalProducerNotFound,
    SignalProducerPersistenceError,
    prepare_signal_job_input,
)
from .credentials import (
    MODEL_CATALOG,
    MODEL_PROVIDERS,
    CredentialConflict,
    CredentialForbidden,
    CredentialNotFound,
    CredentialPersistenceError,
    CredentialStore,
    CredentialUnavailable,
    authorize_resolver,
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
    build_backtest_analysis,
    load_result,
    build_manifest,
    normalize_backtest_request,
    normalize_signal_snapshot,
    normalize_execution_profile,
    project_backtest_summary,
    signal_snapshot_content_sha256,
    membership_fingerprint,
)
from .backtest_task import (
    is_ml_backtest_task,
    ml_prediction_id_from_task,
    project_backtest_task,
    signal_job_id_from_task,
    task_id_from_ml_prediction,
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
from .product_feedback import (
    FeedbackConflict,
    FeedbackForbidden,
    FeedbackNotFound,
    FeedbackPersistenceError,
    FeedbackRateLimited,
    FeedbackUnsafe,
    ProductFeedbackStore,
)
from .paper_trading import (
    PaperTradingConflict,
    PaperTradingForbidden,
    PaperTradingNotFound,
    PaperTradingPersistenceError,
    PaperTradingStore,
)
from .stock_pool_producer import (
    StockPoolProducerConflict,
    StockPoolProducerForbidden,
    StockPoolProducerNotFound,
    StockPoolProducerPersistenceError,
    StockPoolProducerStore,
)
from .user_auth import (
    UserAuthError,
    UserAuthPersistenceError,
    UserAuthStore,
    UserConflict,
    UserForbidden,
    UserNotFound,
)
from .workspace_tenancy import WorkspaceTenancyStore
from .user_policy import (
    UserPolicyConflict,
    UserPolicyNotFound,
    UserPolicyStore,
    UserPolicyError,
    UserPolicyPersistenceError,
    public_policy,
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
    prepare_strategy_draft,
    strategy_draft_content,
    strategy_version_content,
    strategy_output_method,
    validate_version_content,
)
from .ml_strategy import ml_capability_catalog, normalize_ml_strategy, validate_ml_strategy_version
from .ml_capabilities import STRATEGY_SCHEMA as ML_V2_SCHEMA, strategy_data_window
from .ml_regime import BENCHMARK_SYMBOL, validate_model_bundle
from .ml_training import (
    MLTrainingConflict,
    MLTrainingNotFound,
    MLTrainingPersistenceError,
    MLTrainingRunStore,
    aggregate_ml_readiness,
)
from .task_progress import task_progress
from .ml_prediction import (
    MLPredictionConflict,
    MLPredictionNotFound,
    MLPredictionPersistenceError,
    MLPredictionRunStore,
)
from .operations import (
    OperationsConflict,
    OperationsForbidden,
    OperationsPersistenceError,
    OperationsStore,
)
from .plugin_center import (
    PluginCenterConflict,
    PluginCenterForbidden,
    PluginCenterNotFound,
    PluginCenterPersistenceError,
    PluginCenterStore,
)


SERVICE = "byq-backend"
VERSION = "0.1.0"

app = FastAPI(title="BeyondQuant Backend", version=VERSION)
# Tests may install an explicit provider at this seam. Production resolves the
# active database credential at call time so rotation takes effect immediately.
data_provider: TushareProvider | None = None
research_store = ResearchStore.from_env()
agent_store = AgentResearchStore.from_env()
learning_store = LearningLoopStore.from_env(research_store)
engineering_store = EngineeringTaskStore.from_env()
paper_store = PaperTradingStore.from_env()
stock_pool_producer_store = StockPoolProducerStore.from_env()
user_store = UserAuthStore.from_env()
feedback_store = ProductFeedbackStore.from_env()
user_policy_store = UserPolicyStore.from_env()
credential_store = CredentialStore.from_env()
operations_store = OperationsStore.from_env()
plugin_center_store = PluginCenterStore.from_env()
market_data_store = MarketDataStore.from_env()
market_readiness_store = MarketReadinessStore.from_env()
signal_job_store = SignalJobStore.from_env()
ml_training_store = MLTrainingRunStore.from_env()
ml_prediction_store = MLPredictionRunStore.from_env()
data_sync_store = DataSyncStore.from_env()
data_demand_store = DataDemandStore.from_env()
market_automation_store = MarketAutomationStore.from_env()
security_master_store = SecurityMasterStore.from_env()
conversation_store = ConversationCatalogStore.from_env()
backtest_store = BacktestJobStore.from_env()
workspace_tenancy_store = WorkspaceTenancyStore.from_env()
CREDENTIAL_RESOLVER_TOKEN = os.environ.get("BYQ_CREDENTIAL_RESOLVER_TOKEN")
FEEDBACK_PUBLISHER_TOKEN = os.environ.get("BYQ_FEEDBACK_PUBLISHER_TOKEN")
FEEDBACK_HUB_RELAY_TOKEN = os.environ.get("BYQ_FEEDBACK_HUB_RELAY_TOKEN")
if os.environ.get("BYQ_BOOTSTRAP_ADMIN_USERNAME") and os.environ.get("BYQ_BOOTSTRAP_ADMIN_PASSWORD"):
    user_store.ensure_bootstrap_admin(
        os.environ["BYQ_BOOTSTRAP_ADMIN_USERNAME"],
        os.environ["BYQ_BOOTSTRAP_ADMIN_PASSWORD"],
    )
backtest_objects = LocalObjectStore.from_env()


def _resolved_tushare_provider() -> tuple[TushareProvider, dict[str, object]]:
    if data_provider is not None:
        return data_provider, {"source": "test_override", "credential_id": None, "version": None}
    return resolved_tushare_provider(credential_store)


def _operations_call(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except OperationsForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OperationsConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OperationsPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _plugin_center_call(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except PluginCenterForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PluginCenterNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PluginCenterConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PluginCenterPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _ml_call(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except (MLTrainingNotFound, MLPredictionNotFound, ResearchNotFound, PaperTradingNotFound, SecurityMasterNotFound,
            MarketAutomationNotFound) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (MLTrainingConflict, MLPredictionConflict, PaperTradingConflict, SecurityMasterConflict,
            MarketAutomationConflict, IdempotencyConflict, InvalidTransition) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaperTradingForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (MLTrainingPersistenceError, MLPredictionPersistenceError, ResearchPersistenceError, PaperTradingPersistenceError,
            SecurityMasterPersistenceError, MarketReadinessPersistenceError,
            MarketAutomationPersistenceError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


def _conversation_owner(request: Request) -> str:
    owner = request.headers.get("x-byq-owner-principal")
    workspace_id = request.headers.get("x-byq-workspace-id")
    try:
        workspace_tenancy_store.resolve_context(owner, workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="trusted workspace context required") from exc
    assert owner is not None
    return owner


def _feedback_call(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except FeedbackNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FeedbackForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FeedbackConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FeedbackRateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (FeedbackUnsafe, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FeedbackPersistenceError as exc:
        raise HTTPException(status_code=503, detail="feedback storage is unavailable") from exc


def _conversation_call(call: Callable[[], dict[str, object] | list[dict[str, object]]]) -> Any:
    try:
        return call()
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConversationConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConversationPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/v1/product/conversations", status_code=201)
def create_conversation(payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _conversation_call(lambda: {"conversation": conversation_store.create(
        _conversation_owner(request), payload.get("runtime_session_id"), payload.get("trace_id")
    )})


@app.get("/v1/product/conversations")
def list_conversations(
    request: Request,
    status: str = "active",
    search: str = "",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, object]:
    return _conversation_call(lambda: conversation_store.list(
        _conversation_owner(request), status=status, search=search, limit=limit, offset=offset
    ))


@app.get("/v1/product/conversations/by-runtime/{session_id}")
def conversation_by_runtime(session_id: str, request: Request) -> dict[str, object]:
    return _conversation_call(lambda: {"conversation": conversation_store.get_by_runtime_session(
        _conversation_owner(request), session_id
    )})


@app.get("/v1/product/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict[str, object]:
    owner = _conversation_owner(request)
    return _conversation_call(lambda: {
        "conversation": conversation_store.get(owner, conversation_id),
        "messages": conversation_store.messages(owner, conversation_id),
    })


@app.post("/v1/product/conversations/{conversation_id}/messages", status_code=201)
def append_conversation_message(conversation_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    owner = _conversation_owner(request)
    role = payload.get("role", "user")
    if role == "user":
        return _conversation_call(lambda: {"message": conversation_store.append_user_message(
            owner, conversation_id, payload.get("content")
        )})
    if role == "assistant":
        return _conversation_call(lambda: {"message": conversation_store.append_assistant_message(
            owner, conversation_id, payload.get("content"), payload.get("workflow_sequence")
        )})
    return _conversation_call(lambda: (_ for _ in ()).throw(ValueError("role must be user or assistant")))


@app.patch("/v1/product/conversations/{conversation_id}")
def update_conversation(conversation_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _conversation_call(lambda: {"conversation": conversation_store.update(
        _conversation_owner(request), conversation_id, payload
    )})


@app.delete("/v1/product/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request) -> dict[str, object]:
    return _conversation_call(lambda: conversation_store.delete(
        _conversation_owner(request), conversation_id
    ))


def _feedback_context(request: Request) -> dict[str, str]:
    return _required_agent_context(request, include_workspace=True)


def _feedback_client_context(request: Request) -> tuple[str, str]:
    browser = request.headers.get("x-byq-feedback-browser-family", "unavailable")
    operating_system = request.headers.get("x-byq-feedback-os-family", "unavailable")
    allowed_browsers = {"chrome", "edge", "firefox", "safari", "other", "unavailable"}
    allowed_systems = {"windows", "macos", "linux", "android", "ios", "other", "unavailable"}
    return (
        browser if browser in allowed_browsers else "unavailable",
        operating_system if operating_system in allowed_systems else "unavailable",
    )


def _feedback_moderator(request: Request) -> tuple[str, str]:
    actor = request.headers.get("x-byq-actor-principal", "").strip()
    role = request.headers.get("x-byq-actor-role", "").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="actor principal is required")
    if role != "admin":
        raise HTTPException(status_code=403, detail="feedback moderator role required")
    return actor, role


@app.get("/v1/feedback/options")
def feedback_options(request: Request) -> dict[str, object]:
    _feedback_context(request)
    return feedback_store.public_options()


@app.get("/v1/feedback/items")
def feedback_items(
    request: Request, status: str = "all", category: str = "all", query: str = "",
    limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.list_owner(
        trusted_workspace=context["workspace_id"], status=status, category=category,
        query=query, limit=limit, offset=offset,
    ))


@app.post("/v1/feedback/items", status_code=201)
def feedback_create(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.create(
        payload, trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    ))


@app.get("/v1/feedback/items/{feedback_id}")
def feedback_get(feedback_id: str, request: Request) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.get_owner(
        feedback_id, trusted_workspace=context["workspace_id"],
    ))


@app.put("/v1/feedback/items/{feedback_id}")
def feedback_update(feedback_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.update(
        feedback_id, payload, trusted_workspace=context["workspace_id"],
        trusted_actor=context["actor_principal"],
    ))


@app.get("/v1/feedback/items/{feedback_id}/revisions")
def feedback_revisions(
    feedback_id: str, request: Request, limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.list_revisions(
        feedback_id, trusted_workspace=context["workspace_id"], limit=limit, offset=offset,
    ))


@app.post("/v1/feedback/items/{feedback_id}/preview")
def feedback_preview(feedback_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    if set(payload) != {"expected_version"}:
        raise HTTPException(status_code=422, detail="feedback preview request has invalid fields")
    context = _feedback_context(request)
    browser, operating_system = _feedback_client_context(request)
    return _feedback_call(lambda: feedback_store.preview(
        feedback_id, trusted_workspace=context["workspace_id"], expected_version=payload["expected_version"],
        browser_family=browser, os_family=operating_system,
    ))


@app.post("/v1/feedback/items/{feedback_id}/submit")
def feedback_submit(feedback_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _feedback_context(request)
    submit_payload = dict(payload)
    approval_id = submit_payload.pop("agent_approval_id", None)
    if approval_id is not None:
        try:
            _approved_agent_domain_request(
                approval_id, expected_action="byq_feedback_submit",
                expected_resource_type="product_feedback", expected_resource_id=feedback_id,
                context=context,
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    browser, operating_system = _feedback_client_context(request)
    return _feedback_call(lambda: feedback_store.submit(
        feedback_id, submit_payload, trusted_workspace=context["workspace_id"],
        trusted_actor=context["actor_principal"], browser_family=browser, os_family=operating_system,
    ))


@app.post("/v1/feedback/items/{feedback_id}/withdraw")
def feedback_withdraw(feedback_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _feedback_context(request)
    return _feedback_call(lambda: feedback_store.withdraw(
        feedback_id, payload, trusted_workspace=context["workspace_id"], trusted_actor=context["actor_principal"],
    ))


@app.get("/v1/feedback/moderation/items")
def feedback_moderation_items(
    request: Request, status: str = "submitted", category: str = "all", query: str = "",
    limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    _actor, role = _feedback_moderator(request)
    return _feedback_call(lambda: feedback_store.list_moderation(
        actor_role=role, status=status, category=category, query=query, limit=limit, offset=offset,
    ))


@app.get("/v1/feedback/moderation/items/{feedback_id}")
def feedback_moderation_get(feedback_id: str, request: Request) -> dict[str, object]:
    _actor, role = _feedback_moderator(request)
    return _feedback_call(lambda: feedback_store.get_moderation(feedback_id, actor_role=role))


@app.get("/v1/feedback/moderation/items/{feedback_id}/audit")
def feedback_moderation_audit(
    feedback_id: str, request: Request, limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    _actor, role = _feedback_moderator(request)
    return _feedback_call(lambda: feedback_store.list_audit(
        feedback_id, actor_role=role, limit=limit, offset=offset,
    ))


@app.post("/v1/feedback/moderation/items/{feedback_id}/{action}")
def feedback_moderate(feedback_id: str, action: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    actor, role = _feedback_moderator(request)
    return _feedback_call(lambda: feedback_store.moderate(
        feedback_id, action, payload, trusted_actor=actor, actor_role=role,
    ))


@app.get("/v1/feedback/moderation/publisher-status")
def feedback_publisher_status(request: Request) -> dict[str, object]:
    _actor, role = _feedback_moderator(request)
    return _feedback_call(lambda: feedback_store.outbox_summary(actor_role=role))


def _require_feedback_publisher(request: Request) -> None:
    supplied = request.headers.get("x-byq-feedback-publisher-token", "")
    if not FEEDBACK_PUBLISHER_TOKEN:
        raise HTTPException(status_code=503, detail="feedback publisher endpoint is disabled")
    if not supplied or not secrets.compare_digest(supplied, FEEDBACK_PUBLISHER_TOKEN):
        raise HTTPException(status_code=401, detail="feedback publisher authentication failed")


@app.post("/internal/feedback-publications/heartbeat")
def feedback_publisher_heartbeat(payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_publisher(request)
    return _feedback_call(lambda: feedback_store.publisher_heartbeat(payload))


@app.post("/internal/feedback-publications/claim")
def feedback_publication_claim(payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_publisher(request)
    return _feedback_call(lambda: feedback_store.claim_publications(payload))


@app.post("/internal/feedback-publications/{event_id}/complete")
def feedback_publication_complete(event_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_publisher(request)
    return _feedback_call(lambda: feedback_store.complete_publication(event_id, payload))


@app.post("/internal/feedback-publications/{event_id}/retry")
def feedback_publication_retry(event_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_publisher(request)
    return _feedback_call(lambda: feedback_store.retry_publication(event_id, payload))


def _require_feedback_hub_relay(request: Request) -> None:
    supplied = request.headers.get("x-byq-feedback-hub-relay-token", "")
    if not FEEDBACK_HUB_RELAY_TOKEN:
        raise HTTPException(status_code=503, detail="feedback hub relay endpoint is disabled")
    if not supplied or not secrets.compare_digest(supplied, FEEDBACK_HUB_RELAY_TOKEN):
        raise HTTPException(status_code=401, detail="feedback hub relay authentication failed")


@app.post("/internal/feedback-hub/heartbeat")
def feedback_hub_heartbeat(payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.hub_relay_heartbeat(payload))


@app.post("/internal/feedback-hub/claim")
def feedback_hub_claim(payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.claim_hub_deliveries(payload))


@app.post("/internal/feedback-hub/{event_id}/complete")
def feedback_hub_complete(event_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.complete_hub_delivery(event_id, payload))


@app.post("/internal/feedback-hub/{event_id}/retry")
def feedback_hub_retry(event_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.retry_hub_delivery(event_id, payload))


@app.get("/internal/feedback-hub/status-candidates")
def feedback_hub_status_candidates(request: Request, limit: int = 10) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.hub_status_candidates(limit=limit))


@app.post("/internal/feedback-hub/{event_id}/status")
def feedback_hub_status(event_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_feedback_hub_relay(request)
    return _feedback_call(lambda: feedback_store.update_hub_status(event_id, payload))


@app.get("/v1/operations/overview")
def operations_overview(request: Request) -> dict[str, object]:
    """Return bounded aggregate state to the admin Product BFF only."""

    return _operations_call(lambda: operations_store.overview(
        actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.put("/v1/operations/budget")
def operations_budget_update(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Update monitoring thresholds; this grants no DSH execution authority."""

    return _operations_call(lambda: operations_store.update_budget(
        payload,
        actor_principal=request.headers.get("x-byq-actor-principal"),
        actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.get("/v1/plugin-center")
def plugin_center_projection(request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.projection(
        actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.get("/v1/plugin-center/plugins/{plugin_id}")
def plugin_center_detail(plugin_id: str, request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.detail(
        plugin_id, actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.post("/v1/plugin-center/changes", status_code=202)
def plugin_center_change(payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.request_change(
        payload,
        actor_principal=request.headers.get("x-byq-actor-principal"),
        actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.post("/v1/plugin-center/qualifications", status_code=202)
def plugin_center_qualification(payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.request_qualification(
        payload,
        actor_principal=request.headers.get("x-byq-actor-principal"),
        actor_role=request.headers.get("x-byq-actor-role"),
    ))


@app.get("/internal/plugin-center/requests/{request_id}")
def plugin_deployment_input(request_id: str, request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.deployment_input(
        request_id, service_token=request.headers.get("x-byq-plugin-deployment-token"),
    ))


@app.post("/internal/plugin-center/requests/{request_id}/result")
def plugin_deployment_result(request_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    return _plugin_center_call(lambda: plugin_center_store.record_result(
        request_id, payload, service_token=request.headers.get("x-byq-plugin-deployment-token"),
    ))


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
        provider, _metadata = _resolved_tushare_provider()
        result = provider.fetch_daily(request)
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


def _market_research_read(call: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return call()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (
        MarketReadinessPersistenceError,
        MarketDataPersistenceError,
        SecurityMasterPersistenceError,
    ) as error:
        raise HTTPException(status_code=503, detail="market research data is unavailable") from error


def _closed_market_research_payload(payload: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    if set(payload) - allowed:
        raise HTTPException(status_code=422, detail="market research request contains unsupported fields")
    return payload


@app.post("/v1/data/research/valuation")
def research_valuation(payload: dict[str, Any]) -> dict[str, object]:
    """Read exact-session valuation evidence already persisted by the Data Plane."""

    request = _closed_market_research_payload(payload, {"symbols", "trade_date", "fields"})
    return _market_research_read(lambda: market_readiness_store.research_valuation(
        symbols=request.get("symbols"),
        trade_date=request.get("trade_date"),
        fields=request.get("fields"),
    ))


@app.post("/v1/data/research/daily")
def research_daily(payload: dict[str, Any]) -> dict[str, object]:
    """Read durable daily bars; Agent research never triggers a Provider call."""

    request = _closed_market_research_payload(
        payload, {"ts_code", "trade_date", "start_date", "end_date"},
    )
    normalized = DailyRequest(
        ts_code=request.get("ts_code"), trade_date=request.get("trade_date"),
        start_date=request.get("start_date"), end_date=request.get("end_date"),
    )
    return _market_research_read(lambda: market_data_store.research_daily(normalized))


@app.get("/v1/data/research/session-context")
def research_market_session_context() -> dict[str, object]:
    """Read verified exchange-session and durable market-data cutoff facts."""

    return _market_research_read(market_automation_store.market_session_context)


@app.post("/v1/data/research/fundamentals")
def research_fundamentals(payload: dict[str, Any]) -> dict[str, object]:
    """Read announcement-visible fundamentals already persisted by the Data Plane."""

    request = _closed_market_research_payload(payload, {"symbols", "as_of_date", "fields"})
    return _market_research_read(lambda: market_readiness_store.research_fundamentals(
        symbols=request.get("symbols"),
        as_of_date=request.get("as_of_date"),
        fields=request.get("fields"),
    ))


def _require_data_admin(request: Request) -> tuple[str, str]:
    actor = request.headers.get("x-byq-actor-principal", "").strip()
    role = request.headers.get("x-byq-actor-role", "").strip()
    if role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    if not actor:
        raise HTTPException(status_code=401, detail="actor principal is required")
    return actor, role


def _data_sync_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (DataSyncNotFound, SecurityMasterNotFound, PaperTradingNotFound, PaperTradingForbidden) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (DataSyncConflict, SecurityMasterConflict) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (DataSyncPersistenceError, SecurityMasterPersistenceError, CredentialUnavailable, CredentialPersistenceError) as error:
        raise HTTPException(status_code=503, detail="data synchronization is unavailable") from error


def _data_demand_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except DataDemandNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DataDemandConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except DataDemandPersistenceError as error:
        raise HTTPException(status_code=503, detail="data demand is unavailable") from error


def _market_automation_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except MarketAutomationNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except MarketAutomationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except MarketAutomationPersistenceError as error:
        raise HTTPException(status_code=503, detail="market synchronization automation is unavailable") from error


def _resolved_daily_sync_payload(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("sync job request must be an object")
    selection = payload.get("selection") or {"type": "explicit"}
    if not isinstance(selection, dict):
        raise ValueError("selection must be an object")
    selection_type = selection.get("type", "explicit")
    result = dict(payload)
    if selection_type == "explicit":
        if set(selection) != {"type"}:
            raise ValueError("explicit selection has unknown fields")
        result["selection"] = {"type": "explicit"}
    elif selection_type == "selected":
        if set(selection) - {"type", "snapshot_id"}:
            raise ValueError("selected security selection has unknown fields")
        symbols, evidence = security_master_store.resolve_selected_symbols(
            payload.get("symbols"), snapshot_id=selection.get("snapshot_id"),
        )
        result["symbols"] = symbols
        result["selection"] = evidence
    elif selection_type == "security_master":
        if set(selection) - {"type", "statuses", "exchanges", "query"}:
            raise ValueError("security-master selection has unknown fields")
        statuses = selection.get("statuses", ["L"])
        exchanges = selection.get("exchanges", [])
        if not isinstance(statuses, list) or not isinstance(exchanges, list):
            raise ValueError("security-master statuses and exchanges must be lists")
        symbols, evidence = security_master_store.resolve_symbols(
            statuses=tuple(str(item) for item in statuses),
            exchanges=tuple(str(item) for item in exchanges),
            query=str(selection.get("query") or ""),
        )
        result["symbols"] = symbols
        result["selection"] = evidence
    elif selection_type == "stock_pool":
        if set(selection) != {"type", "snapshot_id"}:
            raise ValueError("stock-pool selection must name exactly one snapshot_id")
        context = _required_agent_context(request)
        snapshot = paper_store.get_pool_snapshot(
            selection.get("snapshot_id"), trusted_owner=context["owner_principal"],
        )
        symbols = sorted(str(item["symbol"]) for item in snapshot.get("members", []))
        if not symbols:
            raise ValueError("stock-pool snapshot has no members")
        result["symbols"] = symbols
        result["selection"] = {
            "type": "stock_pool",
            "pool_id": snapshot["pool_id"],
            "snapshot_id": snapshot["snapshot_id"],
            "membership_fingerprint": snapshot["membership_fingerprint"],
        }
    else:
        raise ValueError("selection.type is invalid")
    return result


def _security_master_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except SecurityMasterNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SecurityMasterConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SecurityMasterPersistenceError as error:
        raise HTTPException(status_code=503, detail="security master is unavailable") from error


def _source_credentials(actor: str, role: str) -> list[dict[str, object]]:
    return [
        item
        for item in credential_store.list_credentials(actor, actor_role=role)
        if item.get("purpose") == "tushare_token" and item.get("provider") == "tushare"
    ]


@app.get("/v1/data-center/status")
def data_center_status(request: Request, view: str = "full") -> dict[str, object]:
    actor = request.headers.get("x-byq-actor-principal", "").strip()
    role = request.headers.get("x-byq-actor-role", "user").strip()
    if not actor:
        raise HTTPException(status_code=401, detail="actor principal is required")
    if view not in {"summary", "full"}:
        raise HTTPException(status_code=422, detail="data-center view is invalid")
    include_activity = view == "full"
    credentials = _source_credentials(actor, role) if role == "admin" else []
    active = [item for item in credentials if item.get("status") == "active"]
    jobs = data_sync_store.list_jobs(limit=50) if role == "admin" and include_activity else []
    security_jobs = security_master_store.list_sync_jobs(limit=20) if role == "admin" and include_activity else []
    security_master = security_master_store.catalogue_status()
    coverage = data_sync_store.coverage_audit(limit=100)
    environment_configured = bool(os.environ.get("TUSHARE_TOKEN", "").strip())
    demands = data_demand_store.refresh_recent(
        readiness_store=market_readiness_store, automation_store=market_automation_store, limit=50,
    ) if role == "admin" and include_activity else []
    ml_runs = ml_training_store.list_recent(limit=50) if role == "admin" and include_activity else []

    data_tasks: list[dict[str, object]] = []
    for demand in demands:
        progress = dict(demand.get("progress") or {})
        data_tasks.append({
            "schema_version": "data-task.v1", "task_id": demand["demand_id"],
            "kind": "data_demand", "purpose": demand["purpose"], "title": "按需准备研究数据",
            "status": demand["status"], "stage": progress.get("stage", "queued"),
            "progress": task_progress(int(progress.get("completed_units") or 0),
                                      int(progress.get("total_units") or 0),
                                      fallback=int(progress.get("percent") or 0),
                                      unit=str(progress.get("unit") or "symbol_session_cells")),
            "rows": 0, "safe_error": demand["notification"] if demand["status"] in {"failed", "partial"} else None,
            "reference": {"kind": "data_demand", "id": demand["demand_id"]},
            "created_at": demand["created_at"], "updated_at": demand["updated_at"],
        })
    for job in jobs:
        total = int(job.get("symbol_count") or 0)
        completed = round(total * int(job.get("progress") or 0) / 100)
        data_tasks.append({
            "schema_version": "data-task.v1", "task_id": job["job_id"], "kind": "manual_sync",
            "purpose": "market_data", "title": "行情同步", "status": job["status"],
            "stage": "finished" if job["status"] in {"completed", "failed"} else "synchronizing",
            "progress": task_progress(completed, total, fallback=int(job.get("progress") or 0), unit="symbols"),
            "rows": int(job.get("rows_inserted") or 0), "safe_error": job.get("error_message"),
            "reference": {"kind": "data_sync_job", "id": job["job_id"]},
            "created_at": job["created_at"], "updated_at": job["updated_at"],
        })
    for job in security_jobs:
        received = int(job.get("records_received") or 0)
        completed_records = received if job["status"] == "completed" else int(job.get("records_imported") or 0)
        data_tasks.append({
            "schema_version": "data-task.v1", "task_id": job["job_id"], "kind": "security_master",
            "purpose": "catalogue", "title": "股票基本资料同步", "status": job["status"],
            "stage": "finished" if job["status"] in {"completed", "failed"} else "synchronizing",
            "progress": task_progress(completed_records, received,
                                      fallback=int(job.get("progress") or 0), unit="records"),
            "rows": int(job.get("records_imported") or 0), "safe_error": job.get("error_message"),
            "reference": {"kind": "security_master_sync_job", "id": job["job_id"]},
            "created_at": job["created_at"], "updated_at": job["updated_at"],
        })
    for run in ml_runs:
        readiness = dict(run.get("readiness") or {})
        total = int(readiness.get("required_cell_count") or 0)
        completed = max(0, total - int(readiness.get("missing_count") or 0))
        stage = "preparing_data" if run["status"] == "waiting_for_data" else "training" if run["status"] in {"queued", "running"} else "finished"
        data_tasks.append({
            "schema_version": "data-task.v1", "task_id": run["training_run_id"], "kind": "ml_preparation",
            "purpose": "machine_learning", "title": "机器学习数据准备与训练", "status": run["status"],
            "stage": stage, "progress": task_progress(completed, total, fallback=100 if run["status"] == "completed" else 0,
                                                        unit="symbol_session_cells"),
            "rows": 0, "safe_error": run.get("error_detail"),
            "reference": {"kind": "ml_training_run", "id": run["training_run_id"]},
            "created_at": run["created_at"], "updated_at": run["updated_at"],
        })
    data_tasks.sort(key=lambda item: (str(item.get("updated_at")), str(item["task_id"])), reverse=True)
    automation = market_automation_store.status()
    if not include_activity:
        automation = {**automation, "jobs": [], "run_requests": [], "index_catalog_sync_runs": []}
    return {
        "schema_version": "data-center.v3",
        "provider": "tushare",
        "provider_budget": {
            "schema_version": "provider-budget.v1",
            "profile": "tushare-personal-2000",
            "official_calls_per_minute": 200,
            "official_calls_per_api_per_day": 100_000,
            "daily_rows_per_call": 6_000,
            "configured_request_interval_seconds": float(os.environ.get("TUSHARE_REQUEST_INTERVAL_SECONDS", "0.34")),
            "actual_credential_tier_detected": False,
        },
        "legacy_providers": [],
        "source": {
            "configured": len(active) == 1 or (not active and environment_configured),
            "effective_source": "credential_store" if len(active) == 1 else "ambiguous" if len(active) > 1 else "environment" if environment_configured else "none",
            "credentials": credentials,
            "encryption": credential_store.encryption_status(),
            "secrets_exposed": False,
            "can_manage": role == "admin",
        },
        "jobs": jobs,
        "data_demands": demands,
        "data_tasks": data_tasks[:100],
        "security_master_jobs": security_jobs,
        "security_master": security_master,
        "coverage": coverage,
        "automation": automation,
        "index_catalog": stock_pool_producer_store.list_index_catalog(limit=100),
        "migration": "ready" if coverage["row_count"] else "not_started",
        "quality": coverage["quality"],
    }


@app.get("/v1/data-sync/automation")
def get_market_sync_automation(request: Request) -> dict[str, object]:
    _require_data_admin(request)
    return _market_automation_call(lambda: {"automation": market_automation_store.status()})


@app.put("/v1/data-sync/automation/config")
def update_market_sync_automation(payload: dict[str, Any], request: Request) -> dict[str, object]:
    actor, _role = _require_data_admin(request)
    return _market_automation_call(lambda: {
        "config": market_automation_store.update_config(payload, actor=actor),
    })


@app.post("/v1/data-sync/automation/run-now", status_code=202)
def run_market_sync_automation_now(payload: dict[str, Any], request: Request) -> dict[str, object]:
    actor, _role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        run_request, created = market_automation_store.request_run_now(payload, actor=actor)
        return {"run_request": run_request, "created": created}

    return _market_automation_call(operation)


@app.get("/v1/data-sync/automation/run-now/{request_id}")
def get_market_sync_automation_run(request_id: str, request: Request) -> dict[str, object]:
    _require_data_admin(request)
    return _market_automation_call(lambda: {
        "run_request": market_automation_store.get_run_request(request_id),
    })


@app.post("/v1/data-sources/tushare/credentials", status_code=201)
def create_tushare_credential(payload: dict[str, Any], request: Request) -> dict[str, object]:
    actor, role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        credential_store.assert_tushare_create_allowed(payload.get("idempotency_key"))
        return {"credential": credential_store.create_credential(
            actor,
            {**payload, "purpose": "tushare_token", "provider": "tushare", "scope": "system"},
            actor=actor,
            actor_role=role,
        )}

    return _credential_call(operation)


@app.put("/v1/data-sources/tushare/credentials/{credential_id}")
def update_tushare_credential(
    credential_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    actor, role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        existing = credential_store.get_credential(credential_id, owner=actor, actor_role=role)
        if existing.get("purpose") != "tushare_token" or existing.get("provider") != "tushare":
            raise CredentialNotFound("Tushare credential not found")
        return {"credential": credential_store.update_credential(
            credential_id, actor, payload, actor=actor, actor_role=role,
        )}

    return _credential_call(operation)


@app.post("/v1/data-sources/tushare/credentials/{credential_id}/revoke")
def revoke_tushare_credential(
    credential_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    actor, role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        existing = credential_store.get_credential(credential_id, owner=actor, actor_role=role)
        if existing.get("purpose") != "tushare_token" or existing.get("provider") != "tushare":
            raise CredentialNotFound("Tushare credential not found")
        return {"credential": credential_store.revoke_credential(
            credential_id, actor, actor=actor,
            expected_version=payload.get("expected_version"),
            request_id=payload.get("request_id"), actor_role=role,
        )}

    return _credential_call(operation)


@app.post("/v1/data-sources/tushare/test")
def test_tushare_connection(payload: dict[str, Any], request: Request) -> dict[str, object]:
    _require_data_admin(request)
    allowed = {"symbol", "trade_date"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise HTTPException(status_code=422, detail=f"connection test has unknown fields: {', '.join(unknown)}")
    try:
        provider, metadata = _resolved_tushare_provider()
        check = DailyRequest(
            ts_code=str(payload.get("symbol", "000001.SZ")),
            trade_date=str(payload.get("trade_date", "20240102")),
        ).normalized()
        started = time.monotonic()
        result = provider.fetch_daily(check)
        latency_ms = round((time.monotonic() - started) * 1000)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ProviderCredentialsMissing as error:
        raise HTTPException(status_code=409, detail="Tushare credentials are not configured") from error
    except ProviderAuthorizationError as error:
        raise HTTPException(status_code=422, detail="Tushare rejected the configured credentials") from error
    except ProviderRateLimited as error:
        raise HTTPException(status_code=429, detail="Tushare request was rate limited") from error
    except ProviderError as error:
        raise HTTPException(status_code=502, detail="Tushare connection test failed") from error
    return {
        "test": {
            "status": "passed",
            "provider": "tushare",
            "endpoint": "daily",
            "credential_source": metadata["source"],
            "credential_id": metadata["credential_id"],
            "credential_version": metadata["version"],
            "row_count": len(result.bars),
            "latency_ms": latency_ms,
            "checked_at": result.provenance.retrieved_at,
        }
    }


@app.post("/v1/data-sync/jobs", status_code=201)
def create_data_sync_job(
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    actor, _role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        resolved_payload = _resolved_daily_sync_payload(payload, request)
        job, created = data_sync_store.create_job(resolved_payload, actor=actor)
        if created or job["status"] == "queued":
            background_tasks.add_task(
                data_sync_store.run_job,
                job["job_id"],
                provider_factory=lambda: _resolved_tushare_provider()[0],
                market_store=market_data_store,
            )
        return {"job": job, "created": created}

    return _data_sync_call(operation)


_DEMAND_DECLARED_FIELDS = {"benchmark", "index_universe", "daily_basic", "fundamentals"}
_DEMAND_INDEX = re.compile(r"^\d{6}\.(?:SH|SZ)$")


def _partition_market_requirements(
    *, symbols: list[str], start: datetime, end: datetime,
    membership_fingerprint_value: str, security_master_snapshot_id: str,
    declared: dict[str, object],
) -> list[dict[str, object]]:
    """Create bounded atomic readiness units for one aggregate frozen scope."""
    requirements: list[dict[str, object]] = []
    cursor = start
    max_chunk_days = min(180, max(1, int(50_000 / len(symbols) * 1.25)))
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=max_chunk_days - 1))
        requirements.append(market_readiness_store.requirement(
            symbols=symbols, start_date=cursor.strftime("%Y%m%d"),
            end_date=chunk_end.strftime("%Y%m%d"),
            membership_fingerprint=membership_fingerprint_value,
            security_master_snapshot_id=security_master_snapshot_id,
            data_requirements=declared,
        ))
        cursor = chunk_end + timedelta(days=1)
    if not requirements or len(requirements) > 32:
        raise ValueError("market data preparation partition plan exceeds 32 units")
    return requirements


def _ml_pool_market_scope(
    pool: dict[str, object], pool_snapshot: dict[str, object],
) -> tuple[dict[str, object], str]:
    """Derive immutable optional-data declarations from the frozen ML pool identity."""
    pool_type = str(pool.get("pool_type"))
    if pool_type == "index":
        provenance = pool_snapshot.get("provenance")
        index_symbol = provenance.get("index_symbol") if isinstance(provenance, dict) else None
        if not isinstance(index_symbol, str) or not index_symbol:
            raise ValueError("index stock pool has no canonical index identity")
        return {
            "index_universe": index_symbol,
            "benchmark": index_symbol,
        }, "point_in_time"
    if pool_type == "dynamic":
        raise ValueError("dynamic stock pool historical membership is not supported by Phase 72")
    return {}, "fixed_snapshot"


def _data_demand_requirements(payload: dict[str, Any], context: dict[str, str]) -> tuple[dict[str, object], list[dict[str, object]]]:
    snapshot = paper_store.get_pool_snapshot(
        payload.get("stock_pool_snapshot_id"), trusted_owner=context["owner_principal"],
    )
    symbols = sorted(str(item["symbol"]) for item in snapshot.get("members", []))
    if not symbols:
        raise ValueError("stock-pool snapshot has no members")
    if len(symbols) > 500:
        raise ValueError("data demand stock-pool snapshot must not exceed 500 members")
    start_raw, end_raw = str(payload.get("start_date", "")), str(payload.get("end_date", ""))
    start_canonical, end_canonical = start_raw.replace("-", ""), end_raw.replace("-", "")
    DailyRequest(ts_code=symbols[0], start_date=start_canonical, end_date=end_canonical).normalized()
    start = datetime.strptime(start_canonical, "%Y%m%d")
    end = datetime.strptime(end_canonical, "%Y%m%d")
    if (end - start).days + 1 > 1_827:
        raise ValueError("data demand date range must not exceed five years")
    declared = payload.get("data_requirements") or {}
    if not isinstance(declared, dict) or set(declared) - _DEMAND_DECLARED_FIELDS:
        raise ValueError("data_requirements contains unsupported fields")
    for field in ("benchmark", "index_universe"):
        value = declared.get(field)
        if value is not None and (not isinstance(value, str) or _DEMAND_INDEX.fullmatch(value) is None):
            raise ValueError(f"data_requirements.{field} is invalid")
    for field in ("daily_basic", "fundamentals"):
        value = declared.get(field, [])
        if not isinstance(value, list) or len(value) > 12 or any(not isinstance(item, str) for item in value):
            raise ValueError(f"data_requirements.{field} is invalid")
        supported = DAILY_BASIC_FIELDS if field == "daily_basic" else FINANCIAL_INDICATOR_FIELDS
        if any(item not in supported for item in value):
            raise ValueError(f"data_requirements.{field} contains unsupported fields")
    latest = security_master_store.latest_snapshot()
    if latest is None:
        raise ValueError("security master must be synchronized before requesting data")
    requirements = _partition_market_requirements(
        symbols=symbols, start=start, end=end,
        membership_fingerprint_value=membership_fingerprint(symbols),
        security_master_snapshot_id=str(latest["snapshot_id"]), declared=declared,
    )
    scope = {
        "stock_pool_snapshot_id": snapshot["snapshot_id"], "pool_id": snapshot["pool_id"],
        "membership_fingerprint": snapshot["membership_fingerprint"], "symbol_count": len(symbols),
        "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"),
        "partition_count": len(requirements), "datasets": list(requirements[0]["datasets"]),
        "declared": declared,
    }
    return scope, requirements


def _require_data_demand_admin(context: dict[str, str]) -> None:
    tenancy = workspace_tenancy_store.resolve_context(context["owner_principal"], context["workspace_id"])
    user = user_store.get_user(tenancy["owner_user_id"])
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="administrator-owned workspace required")


@app.post("/v1/agent/data-demands", status_code=202)
def create_agent_data_demand(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    _require_data_demand_admin(context)

    def operation() -> dict[str, object]:
        scope, requirements = _data_demand_requirements(payload, context)
        existing = data_demand_store.find_idempotent(
            payload, context=context, scope=scope, requirements=requirements,
        )
        if existing is not None:
            return {"demand": data_demand_store.refresh(
                existing["demand_id"], trusted_owner=context["owner_principal"],
                readiness_store=market_readiness_store, automation_store=market_automation_store,
            ), "created": False}
        repairs = [market_automation_store.request_data_repair(
            requirement=requirement, requested_by=f"agent-data-demand:{context['owner_principal']}",
        ) for requirement in requirements]
        demand, created = data_demand_store.create(
            payload, context=context, scope=scope, requirements=requirements,
            repair_request_ids=[str(item["request_id"]) for item in repairs],
        )
        return {"demand": data_demand_store.refresh(
            demand["demand_id"], trusted_owner=context["owner_principal"],
            readiness_store=market_readiness_store, automation_store=market_automation_store,
        ), "created": created}

    return _data_demand_call(operation)


@app.get("/v1/agent/data-demands/{demand_id}")
def get_agent_data_demand(demand_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _data_demand_call(lambda: {"demand": data_demand_store.refresh(
        demand_id, trusted_owner=context["owner_principal"],
        readiness_store=market_readiness_store, automation_store=market_automation_store,
    )})


@app.get("/v1/agent/data-demand-notifications")
def get_agent_data_demand_notifications(request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        demands = data_demand_store.list_for_session(
            trusted_owner=context["owner_principal"], session_id=context["session_id"],
        )
        refreshed = [data_demand_store.refresh(
            item["demand_id"], trusted_owner=context["owner_principal"],
            readiness_store=market_readiness_store, automation_store=market_automation_store,
        ) for item in demands]
        data_notifications = [
            {**item, "kind": "data_demand_progress"}
            for item in refreshed if item["status"] in {"ready", "partial", "failed"}
        ]
        ml_notifications = ml_training_store.list_agent_notifications(
            trusted_workspace=context["workspace_id"],
            trusted_owner=context["owner_principal"],
        )
        return {"notifications": [*data_notifications, *ml_notifications]}

    return _data_demand_call(operation)


@app.get("/v1/data-sync/jobs")
def list_data_sync_jobs(request: Request, limit: int = 50) -> dict[str, object]:
    _require_data_admin(request)
    return _data_sync_call(lambda: {"jobs": data_sync_store.list_jobs(limit=limit)})


@app.get("/v1/data-sync/jobs/{job_id}")
def get_data_sync_job(job_id: str, request: Request) -> dict[str, object]:
    _require_data_admin(request)
    return _data_sync_call(lambda: {"job": data_sync_store.get_job(job_id)})


@app.get("/v1/data-center/coverage")
def get_data_coverage(request: Request, limit: int = 100) -> dict[str, object]:
    if not request.headers.get("x-byq-actor-principal", "").strip():
        raise HTTPException(status_code=401, detail="actor principal is required")
    return _data_sync_call(lambda: {"coverage": data_sync_store.coverage_audit(limit=limit)})


_READINESS_DATASET_LABELS = {
    "trading_calendar": "交易日历", "security_lifecycle": "证券上市状态",
    "trading_status": "停复牌与交易状态", "stock_daily": "日线行情",
    "price_limits": "涨跌停价格", "adjustment_factors": "复权因子",
    "corporate_actions": "公司行动", "index_daily": "基准行情",
    "index_weights": "指数权重", "index_membership": "指数成分",
    "daily_basic": "估值数据", "financial_indicators": "财务指标",
}


@app.post("/v1/data-center/readiness")
def query_data_readiness(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Explain whether an explicit, bounded task can use durable market data."""

    if not request.headers.get("x-byq-actor-principal", "").strip():
        raise HTTPException(status_code=401, detail="actor principal is required")

    def operation() -> dict[str, object]:
        if not isinstance(payload, dict) or set(payload) - {
            "symbols", "start_date", "end_date", "use_case", "data_requirements",
        }:
            raise ValueError("readiness request contains unsupported fields")
        raw_symbols = payload.get("symbols")
        if not isinstance(raw_symbols, list) or not 1 <= len(raw_symbols) <= 20:
            raise ValueError("symbols must contain between 1 and 20 entries")
        symbols: list[str] = []
        for value in raw_symbols:
            normalized = DailyRequest(ts_code=value, trade_date="20000101").normalized().ts_code
            if normalized is not None and normalized not in symbols:
                symbols.append(normalized)
        use_case = str(payload.get("use_case", "research")).strip()
        if use_case not in {"research", "backtest"}:
            raise ValueError("use_case must be research or backtest")
        start_date = str(payload.get("start_date", ""))
        end_date = str(payload.get("end_date", ""))
        DailyRequest(ts_code=symbols[0], start_date=start_date, end_date=end_date).normalized()
        data_requirements = payload.get("data_requirements", {})
        if not isinstance(data_requirements, dict):
            raise ValueError("data_requirements must be an object")
        latest = security_master_store.latest_snapshot()
        if latest is None:
            raise ValueError("security master must be synchronized before checking readiness")
        requirement = market_readiness_store.requirement(
            symbols=symbols, start_date=start_date, end_date=end_date,
            membership_fingerprint=membership_fingerprint(symbols),
            security_master_snapshot_id=str(latest["snapshot_id"]),
            data_requirements=data_requirements,
        )
        assessment = market_readiness_store.assess(requirement)
        grouped: dict[str, int] = {}
        public_issues: list[dict[str, object]] = []
        missing = assessment.get("missing", [])
        for item in missing if isinstance(missing, list) else []:
            if not isinstance(item, dict):
                continue
            dataset = str(item.get("dataset", "unknown"))
            grouped[dataset] = grouped.get(dataset, 0) + 1
            if len(public_issues) < 50:
                public_issues.append({
                    "symbol": item.get("symbol"), "trade_date": item.get("trade_date"),
                    "label": f"缺少{_READINESS_DATASET_LABELS.get(dataset, '必要数据')}",
                    "impact": "当前范围不能完整用于回测" if use_case == "backtest" else "当前范围的研究结论可能不完整",
                    "recommended_action": "前往数据同步补齐该范围",
                })
        state = str(assessment.get("state", "missing"))
        missing_count = int(assessment.get("missing_count") or 0)
        required_count = int(assessment.get("required_cell_count") or 0)
        return {
            "schema_version": "data-readiness-product.v1",
            "verdict": "usable" if state == "ready" else "limited" if state == "partial" else "unavailable",
            "scope": {
                "selection_type": "explicit", "symbol_count": len(symbols), "symbols": symbols,
                "start_date": start_date.replace("-", ""), "end_date": end_date.replace("-", ""),
                "use_case": use_case,
            },
            "summary": {
                "required_sessions": int(assessment.get("required_session_count") or 0),
                "ready_items": max(0, required_count - missing_count), "missing_items": missing_count,
                "calendar_complete": bool(assessment.get("calendar_complete")),
            },
            "datasets": [{
                "label": _READINESS_DATASET_LABELS.get(dataset, "必要数据"),
                "state": "missing", "missing_count": count,
            } for dataset, count in sorted(grouped.items())],
            "issues": public_issues,
            "issues_truncated": missing_count > len(public_issues),
            "checked_against": "persisted_byq",
        }

    return _market_research_read(operation)


@app.post("/v1/data-sync/security-master/jobs", status_code=201)
def create_security_master_sync_job(
    payload: dict[str, Any],
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, object]:
    actor, _role = _require_data_admin(request)

    def operation() -> dict[str, object]:
        job, created = security_master_store.create_sync_job(payload, actor=actor)
        if created or job["status"] == "queued":
            background_tasks.add_task(
                security_master_store.run_sync_job,
                job["job_id"],
                provider_factory=lambda: _resolved_tushare_provider()[0],
            )
        return {"job": job, "created": created}

    return _security_master_call(operation)


@app.get("/v1/data-sync/security-master/jobs/{job_id}")
def get_security_master_sync_job(job_id: str, request: Request) -> dict[str, object]:
    _require_data_admin(request)
    return _security_master_call(lambda: {"job": security_master_store.get_sync_job(job_id)})


@app.get("/v1/data-center/securities")
def list_security_master(
    request: Request,
    query: str = "",
    statuses: str = "",
    exchanges: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    if not request.headers.get("x-byq-actor-principal", "").strip():
        raise HTTPException(status_code=401, detail="actor principal is required")
    return _security_master_call(lambda: security_master_store.list_securities(
        query=query,
        statuses=tuple(item for item in statuses.split(",") if item),
        exchanges=tuple(item for item in exchanges.split(",") if item),
        limit=limit,
        offset=offset,
    ))


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
    except ResearchPersistenceError as error:
        raise HTTPException(status_code=503, detail="research storage is unavailable") from error
    except BacktestStorageError as error:
        raise HTTPException(status_code=503, detail="backtest storage is unavailable") from error


def _signal_producer_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ResearchNotFound, PaperTradingNotFound, SignalProducerNotFound) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SignalProducerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except SignalProducerPersistenceError as error:
        raise HTTPException(status_code=503, detail="signal producer storage is unavailable") from error


def _backtest_task_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ResearchNotFound, PaperTradingNotFound, SignalProducerNotFound, BacktestNotFound, MLPredictionNotFound) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (SignalProducerConflict, BacktestConflict, MLPredictionConflict) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (SignalProducerPersistenceError, BacktestStorageError, MLPredictionPersistenceError) as error:
        raise HTTPException(status_code=503, detail="backtest task storage is unavailable") from error


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


def _stock_pool_producer_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except StockPoolProducerForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except StockPoolProducerNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except StockPoolProducerConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except StockPoolProducerPersistenceError as error:
        raise HTTPException(status_code=503, detail="stock-pool producer storage is unavailable") from error


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


def _authenticated_user_payload(user: dict[str, object], *, session_id: object | None = None) -> dict[str, object]:
    workspace = workspace_tenancy_store.public_workspace(str(user["user_id"]))
    result: dict[str, object] = {"user": user, "workspace": workspace}
    if session_id is not None:
        result["session_id"] = session_id
    return result


def _login_user(username: object, password: object) -> dict[str, object]:
    result = user_store.login(username, password)
    return _authenticated_user_payload(result["user"], session_id=result["session_id"])


def _agent_context(request: Request, payload: dict[str, Any]) -> dict[str, str | None]:
    """Resolve trusted runtime context without forwarding credentials."""

    header_values = {
        "workspace_id": request.headers.get("x-byq-workspace-id"),
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


def _required_agent_context(
    request: Request, payload: dict[str, Any] | None = None, *, include_workspace: bool = False,
) -> dict[str, str]:
    context = _agent_context(request, payload or {})
    missing = sorted(field for field, value in context.items() if value is None)
    if missing:
        raise HTTPException(status_code=401, detail="trusted agent context is required")
    complete = {field: value for field, value in context.items() if value is not None}
    try:
        workspace_tenancy_store.resolve_context(complete["owner_principal"], complete["workspace_id"])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="trusted workspace context is invalid") from exc
    # workspace_id is an authorization-boundary value, not a domain command
    # field. Persistence stamps it from the validated owner via database
    # triggers, keeping existing framework-neutral domain contracts stable.
    return complete if include_workspace else {field: value for field, value in complete.items() if field != "workspace_id"}


def _strategy_payload(payload: object, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("strategy request must be an object")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"strategy request has unknown fields: {', '.join(unknown)}")
    return payload


def _approved_agent_domain_request(
    approval_id: object, *, expected_action: str, expected_resource_type: str,
    expected_resource_id: str, context: dict[str, str],
) -> dict[str, object]:
    """Bind an Agent-origin domain approval to one exact owner-scoped resource."""
    approval = agent_store.get_approval(
        approval_id, trusted_owner=context["owner_principal"],
    )
    if (
        approval.get("status") != "approved"
        or approval.get("execution_outcome") != "authorized"
        or approval.get("action") != expected_action
        or approval.get("resource_type") != expected_resource_type
        or approval.get("resource_id") != expected_resource_id
        or approval.get("actor_principal") != context["actor_principal"]
        or approval.get("source_session_id") != context["session_id"]
        or not isinstance(approval.get("decision_by"), str)
    ):
        raise ValueError("agent approval does not authorize this exact domain action")
    return approval


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
def create_research_task(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        if payload.get("owner_principal") != context["owner_principal"]:
            raise ValueError("research task owner must match trusted context")
        return research_store.create_task(payload)

    return _research_call(operation)


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


@app.post("/v1/research/web-evidence", status_code=201)
def create_web_research_evidence(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Promote bounded search evidence through the trusted BYQ domain boundary."""

    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        allowed = {"task_id", "experiment_id", "content", "lineage", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"unknown fields: {', '.join(unknown)}")
        task = research_store.get_task(payload.get("task_id"))
        if task["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("research task not found")
        artifact_payload = {
            **payload,
            "kind": "web_research_evidence",
            "trace_id": context["trace_id"],
        }
        return research_store.create_artifact(artifact_payload)

    return _research_call(operation)


@app.post("/v1/research/web-evidence-records", status_code=201)
def create_web_research_evidence_record(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Atomically create a ResearchTask and its bounded web-evidence Artifact."""

    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        return research_store.create_web_evidence_record(
            {
                **payload,
                "owner_principal": context["owner_principal"],
                "trace_id": context["trace_id"],
            }
        )

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
def create_strategy_approval(payload: dict[str, Any], http_request: Request) -> dict[str, object]:
    context = _required_agent_context(http_request)

    def operation() -> dict[str, object]:
        request = _strategy_payload(
            payload,
            {
                "task_id", "experiment_id", "strategy_version_artifact_id", "reviewer_principal",
                "decision", "rationale", "trace_id", "idempotency_key", "agent_approval_id",
            },
        )
        version_artifact = research_store.get_artifact(request.get("strategy_version_artifact_id"))
        if version_artifact["owner_principal"] != context["owner_principal"]:
            raise ResearchNotFound("strategy version not found")
        if version_artifact["kind"] != "strategy_version":
            raise ValueError("strategy_version_artifact_id must reference a strategy_version artifact")
        if version_artifact["task_id"] != request.get("task_id"):
            raise ValueError("strategy version artifact does not belong to task_id")
        if version_artifact["status"] != "validated":
            raise ValueError("strategy version must be validated before approval")
        version_content = validate_version_content(version_artifact["content"])
        agent_approval_id = request.get("agent_approval_id")
        reviewer = request.get("reviewer_principal")
        if agent_approval_id is not None:
            linked = _approved_agent_domain_request(
                agent_approval_id,
                expected_action="byq_strategy_approve",
                expected_resource_type="strategy_version",
                expected_resource_id=str(version_artifact["artifact_id"]),
                context=context,
            )
            reviewer = linked["decision_by"]
        elif reviewer != context["actor_principal"]:
            raise ValueError("reviewer_principal must match the trusted product actor")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer.strip()) > 128:
            raise ValueError("reviewer_principal must be a non-empty string")
        decision = request.get("decision")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        if agent_approval_id is not None and decision != "approved":
            raise ValueError("approved Agent request cannot materialize a rejected strategy decision")
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


def _ml_agent_artifact_projection(artifact: dict[str, Any]) -> dict[str, object] | None:
    kind = artifact.get("kind")
    allowed = {
        "ml_strategy_version": {
            "schema_version", "version_id", "name", "learner", "feature_set", "target",
            "split", "learner_parameters", "signal_policy", "validation_plan", "portfolio_policy",
            "development_window", "prediction_window", "capability_lock", "runtime_lock",
            "regime", "routing_policy", "experts",
        },
        "ml_strategy_approval": {
            "schema_version", "ml_strategy_version_id", "ml_strategy_artifact_id",
            "decision", "rationale", "execution_authorized", "execution_outcome",
        },
        "ml_model": {
            "schema_version", "training_run_id", "strategy_version_artifact_id",
            "feature_snapshot_artifact_id", "stock_pool_snapshot_id", "split",
            "feature_order", "best_iteration", "metrics", "counts", "runtime_lock",
            "runtime_identity", "content_sha256", "learner_profile", "validation_plan", "folds",
            "selection_rule", "capability_lock", "development_window", "prediction_window",
            "expert_key", "training_regimes", "coverage",
        },
        "ml_model_bundle": {
            "schema_version", "strategy_version_artifact_id", "feature_snapshot_artifact_id",
            "regime_snapshot_artifact_id", "stock_pool_snapshot_id", "training_run_id",
            "routing_policy", "experts", "prediction_window", "content_sha256",
        },
        "ml_regime_snapshot": {
            "schema_version", "definition", "benchmark_symbol", "lookback_sessions", "counts",
            "content_sha256",
        },
        "ml_prediction_snapshot": {
            "schema_version", "model_artifact_id", "stock_pool_snapshot_id",
            "prediction_split", "runtime_lock", "runtime_identity", "counts",
            "content_sha256", "mode", "model_bundle_artifact_id",
            "regime_snapshot_artifact_id", "prediction_window",
        },
        "signal_snapshot": {
            "schema_version", "strategy_version_id", "strategy_version_artifact_id",
            "execution", "source", "content_sha256",
        },
    }
    if kind not in allowed:
        return None
    content = artifact.get("content")
    safe_content = (
        {key: value for key, value in content.items() if key in allowed[str(kind)]}
        if isinstance(content, dict) else {}
    )
    return {
        "artifact_id": artifact.get("artifact_id"),
        "task_id": artifact.get("task_id"),
        "kind": kind,
        "status": artifact.get("status"),
        "content_sha256": artifact.get("content_sha256"),
        "created_at": artifact.get("created_at"),
        "content": safe_content,
    }


def _approved_ml_strategy_artifact(
    *, owner_principal: str, workspace_id: str, strategy_artifact_id: str
) -> str | None:
    artifact = research_store.get_ml_strategy_approval(
        owner_principal=owner_principal,
        workspace_id=workspace_id,
        ml_strategy_artifact_id=strategy_artifact_id,
    )
    return None if artifact is None else str(artifact["artifact_id"])


@app.get("/v1/research/ml/capabilities")
def get_ml_capabilities(request: Request) -> dict[str, object]:
    _required_agent_context(request, include_workspace=True)
    return ml_capability_catalog()


def _ml_workspace_options(context: dict[str, str]) -> dict[str, object]:
    tasks = [
        task for task in research_store.list_tasks(owner_principal=context["owner_principal"])["tasks"]
        if task.get("workspace_id") == context["workspace_id"]
    ]
    raw_pools = paper_store.list_pools(
        trusted_owner=context["owner_principal"], limit=100, offset=0
    )["pools"]
    return {
        "tasks": [
            {key: task.get(key) for key in ("task_id", "title", "status", "created_at")}
            for task in tasks[:100]
        ],
        "pools": [
            {key: pool.get(key) for key in (
                "pool_id", "name", "pool_type", "status", "current_snapshot_id", "member_count",
            )}
            for pool in raw_pools
        ],
    }


@app.get("/v1/research/ml/options")
def get_ml_options(request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return {"schema_version": "ml-options.v1", **_ml_workspace_options(context)}


@app.get("/v1/research/ml/studies")
def list_ml_studies(
    request: Request, query: str = "", status: str = "all", limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _research_call(lambda: {
        "schema_version": "ml-study-catalog.v1",
        **research_store.list_ml_strategy_catalog(
            owner_principal=context["owner_principal"], workspace_id=context["workspace_id"],
            query=query, status=status, limit=limit, offset=offset,
        ),
    })


@app.get("/v1/research/ml/studies/{strategy_artifact_id}")
def get_ml_study(strategy_artifact_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        strategy = research_store.get_ml_artifact_metadata(
            strategy_artifact_id, owner_principal=context["owner_principal"],
            workspace_id=context["workspace_id"],
        )
        if strategy.get("kind") != "ml_strategy_version" or strategy.get("status") == "superseded":
            raise ResearchNotFound("ML study not found")
        training_page = ml_training_store.list_runs(
            trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"],
            strategy_artifact_id=strategy_artifact_id, limit=20, offset=0,
        )
        prediction_page = ml_prediction_store.list_runs(
            trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"],
            strategy_artifact_id=strategy_artifact_id, limit=20, offset=0,
        )
        backtest_page = backtest_store.list_backtest_summaries(
            owner_principal=context["owner_principal"], strategy_artifact_id=strategy_artifact_id,
            workspace_id=context["workspace_id"], limit=20, offset=0,
        )
        approval = research_store.get_ml_strategy_approval(
            owner_principal=context["owner_principal"], workspace_id=context["workspace_id"],
            ml_strategy_artifact_id=strategy_artifact_id,
        )
        artifact_ids: set[str] = {strategy_artifact_id}
        if approval is not None:
            artifact_ids.add(str(approval["artifact_id"]))
        for run in training_page["runs"]:
            for key in ("model_artifact_id",):
                if isinstance(run.get(key), str):
                    artifact_ids.add(str(run[key]))
        for run in prediction_page["runs"]:
            for key in ("model_artifact_id", "prediction_artifact_id", "signal_artifact_id"):
                if isinstance(run.get(key), str):
                    artifact_ids.add(str(run[key]))
        artifacts: list[dict[str, object]] = []
        pending = list(sorted(artifact_ids))
        loaded: set[str] = set()
        while pending and len(loaded) < 20:
            identity = pending.pop(0)
            if identity in loaded:
                continue
            artifact = research_store.get_ml_artifact_metadata(
                identity, owner_principal=context["owner_principal"],
                workspace_id=context["workspace_id"],
            )
            loaded.add(identity)
            projected = _ml_agent_artifact_projection(artifact)
            if projected is not None:
                artifacts.append(projected)
            content = artifact.get("content")
            if artifact.get("kind") == "ml_model_bundle" and isinstance(content, dict):
                regime_id = content.get("regime_snapshot_artifact_id")
                if isinstance(regime_id, str):
                    pending.append(regime_id)
                experts = content.get("experts")
                if isinstance(experts, list):
                    pending.extend(
                        str(item["model_artifact_id"])
                        for item in experts
                        if isinstance(item, dict) and isinstance(item.get("model_artifact_id"), str)
                    )
        return {
            "schema_version": "ml-study-detail.v1",
            "study": _ml_agent_artifact_projection(strategy),
            "management": research_store.get_ml_study_management(
                strategy_artifact_id,
                owner_principal=context["owner_principal"],
                workspace_id=context["workspace_id"],
            ),
            "approval_artifact_id": None if approval is None else approval["artifact_id"],
            "training_runs": training_page,
            "prediction_runs": prediction_page,
            "backtests": backtest_page,
            "artifacts": artifacts,
        }

    return _research_call(operation)


@app.post("/v1/research/ml/studies/{strategy_artifact_id}/lifecycle")
def update_ml_study_lifecycle(
    strategy_artifact_id: str, payload: dict[str, Any], request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _research_call(lambda: {
        "schema_version": "ml-study-lifecycle.v1",
        **research_store.set_ml_study_lifecycle(
            strategy_artifact_id,
            {"status": payload.get("status"), "idempotency_key": payload.get("idempotency_key")},
            owner_principal=context["owner_principal"],
            workspace_id=context["workspace_id"],
        ),
    })


@app.delete("/v1/research/ml/studies/{strategy_artifact_id}")
def delete_ml_study(strategy_artifact_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _research_call(lambda: {
        "schema_version": "ml-study-delete.v1",
        **research_store.supersede_unexecuted_ml_study(
            strategy_artifact_id,
            owner_principal=context["owner_principal"],
            workspace_id=context["workspace_id"],
        ),
    })


@app.get("/v1/research/ml/workspace")
def get_ml_agent_workspace(request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    options = _ml_workspace_options(context)
    artifacts = [
        projected
        for artifact in research_store.list_ml_workspace_artifacts(
            owner_principal=context["owner_principal"], workspace_id=context["workspace_id"]
        )
        for projected in [_ml_agent_artifact_projection(artifact)]
        if projected is not None
    ]
    training_runs = ml_training_store.list_runs(
        trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"]
    )["runs"]
    prediction_runs = ml_prediction_store.list_runs(
        trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"]
    )["runs"]
    return {
        "schema_version": "ml-agent-workspace.v1",
        "tasks": options["tasks"],
        "pools": options["pools"],
        "artifacts": artifacts,
        "training_runs": training_runs,
        "prediction_runs": prediction_runs,
        "prediction_available_via_agent": True,
    }


@app.post("/v1/research/ml/strategies/versions", status_code=201)
def create_ml_strategy_version(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        data = _strategy_payload(
            payload, {"task_id", "experiment_id", "strategy", "trace_id", "idempotency_key"}
        )
        task = research_store.get_task(data.get("task_id"))
        if task["owner_principal"] != context["owner_principal"] or task.get("workspace_id") != context["workspace_id"]:
            raise ResearchNotFound("research task not found")
        normalized = normalize_ml_strategy(data.get("strategy"))
        fingerprint = content_sha256(normalized)
        artifact = research_store.find_artifact_by_content(
            str(task["task_id"]), "ml_strategy_version", fingerprint
        )
        if artifact is None:
            artifact = research_store.create_artifact({
                "task_id": task["task_id"], "experiment_id": data.get("experiment_id"),
                "kind": "ml_strategy_version", "content": normalized, "lineage": [],
                "trace_id": data.get("trace_id"), "idempotency_key": data.get("idempotency_key"),
            })
        if artifact["status"] == "draft":
            artifact = research_store.transition(
                "artifact", artifact["artifact_id"], "validated",
                f"ml-strategy-validate-{str(normalized['version_id'])[-24:]}",
            )
        return {"ml_strategy_version": normalized, "artifact": artifact}

    return _research_call(operation)


@app.post("/v1/research/ml/strategies/approvals", status_code=201)
def create_ml_strategy_approval(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        data = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "ml_strategy_artifact_id", "decision", "rationale",
             "trace_id", "idempotency_key", "agent_approval_id"},
        )
        task = research_store.get_task(data.get("task_id"))
        version = research_store.get_artifact(data.get("ml_strategy_artifact_id"))
        if (
            task["owner_principal"] != context["owner_principal"]
            or task.get("workspace_id") != context["workspace_id"]
            or version["owner_principal"] != context["owner_principal"]
            or version.get("workspace_id") != context["workspace_id"]
        ):
            raise ResearchNotFound("ML strategy version not found")
        if version["kind"] != "ml_strategy_version" or version["status"] != "validated":
            raise ValueError("ml_strategy_artifact_id must reference a validated ML strategy version")
        if version["task_id"] != task["task_id"]:
            raise ValueError("ML strategy version does not belong to task")
        normalized = validate_ml_strategy_version(version["content"])
        decision = data.get("decision")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        if data.get("agent_approval_id") is not None and decision != "approved":
            raise ValueError("approved Agent request cannot materialize a rejected ML strategy decision")
        rationale = data.get("rationale", "")
        if not isinstance(rationale, str) or len(rationale) > 4000:
            raise ValueError("rationale must be a string of at most 4000 characters")
        reviewer = context["actor_principal"]
        if data.get("agent_approval_id") is not None:
            linked = _approved_agent_domain_request(
                data["agent_approval_id"],
                expected_action="byq_ml_strategy_approve",
                expected_resource_type="ml_strategy_version",
                expected_resource_id=str(version["artifact_id"]),
                context=context,
            )
            reviewer = str(linked["decision_by"])
        content = {
            "schema_version": "ml-strategy-approval.v1",
            "ml_strategy_version_id": normalized["version_id"],
            "ml_strategy_artifact_id": version["artifact_id"],
            "decision": decision,
            "reviewer_principal": reviewer,
            "rationale": rationale,
            "execution_authorized": decision == "approved",
            "execution_outcome": "not_started",
        }
        artifact = research_store.create_artifact({
            "task_id": task["task_id"], "experiment_id": data.get("experiment_id"),
            "kind": "ml_strategy_approval", "content": content,
            "lineage": [{"kind": "artifact", "id": version["artifact_id"]}],
            "trace_id": data.get("trace_id"), "idempotency_key": data.get("idempotency_key"),
        })
        if artifact["status"] == "draft":
            artifact = research_store.transition(
                "artifact", artifact["artifact_id"], "validated",
                f"ml-approval-validate-{str(artifact['artifact_id'])[-24:]}",
            )
        return {"approval": content, "artifact": artifact}

    return _research_call(operation)


@app.post("/v1/research/ml/training-runs", status_code=202)
def create_ml_training_run(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        data = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "ml_strategy_artifact_id", "stock_pool_snapshot_id",
             "trace_id", "idempotency_key"},
        )
        task = research_store.get_task(data.get("task_id"))
        version = research_store.get_artifact(data.get("ml_strategy_artifact_id"))
        if (
            task["owner_principal"] != context["owner_principal"]
            or task.get("workspace_id") != context["workspace_id"]
            or version["owner_principal"] != context["owner_principal"]
            or version.get("workspace_id") != context["workspace_id"]
        ):
            raise ResearchNotFound("ML strategy version not found")
        if version["kind"] != "ml_strategy_version" or version["status"] != "validated":
            raise ValueError("ml_strategy_artifact_id must reference a validated ML strategy version")
        if version["task_id"] != task["task_id"]:
            raise ValueError("ML strategy version does not belong to task")
        if _approved_ml_strategy_artifact(
            owner_principal=context["owner_principal"],
            workspace_id=context["workspace_id"],
            strategy_artifact_id=str(version["artifact_id"]),
        ) is None:
            raise ValueError("ML strategy requires explicit human approval before training")
        experiment_id = data.get("experiment_id")
        if experiment_id is not None:
            experiment = research_store.get_experiment(experiment_id)
            if experiment["task_id"] != task["task_id"]:
                raise ValueError("experiment does not belong to ML research task")
        strategy = validate_ml_strategy_version(version["content"])
        pool_snapshot = paper_store.get_pool_snapshot(
            data.get("stock_pool_snapshot_id"), trusted_owner=context["owner_principal"]
        )
        pool = paper_store.get_pool(pool_snapshot["pool_id"], trusted_owner=context["owner_principal"])
        if pool["status"] != "active":
            raise ValueError("stock pool must be active for ML training")
        symbols = sorted(str(member["symbol"]) for member in pool_snapshot.get("members", []))
        if not symbols or len(symbols) > 1000:
            raise ValueError("ML training stock pool must contain between 1 and 1000 symbols")
        declared, membership_mode = _ml_pool_market_scope(pool, pool_snapshot)
        regime = strategy.get("regime")
        if isinstance(regime, dict) and regime.get("enabled") is True:
            declared = {**declared, "benchmark": BENCHMARK_SYMBOL}
        master = security_master_store.latest_snapshot()
        if master is None:
            raise ValueError("security master must be synchronized before ML training")
        data_start, data_end = strategy_data_window(strategy)
        requirement_start = datetime.strptime(data_start.replace("-", ""), "%Y%m%d")
        if isinstance(regime, dict) and regime.get("enabled") is True:
            # Freeze enough pre-development calendar history for the 60-session
            # regime warmup. The feature/label windows remain those in strategy.
            requirement_start -= timedelta(days=120)
        requirements = _partition_market_requirements(
            symbols=symbols,
            start=requirement_start,
            end=datetime.strptime(data_end.replace("-", ""), "%Y%m%d"),
            membership_fingerprint_value=str(pool_snapshot["membership_fingerprint"]),
            security_master_snapshot_id=str(master["snapshot_id"]), declared=declared,
        )
        assessments = [market_readiness_store.assess(requirement) for requirement in requirements]
        readiness = aggregate_ml_readiness(assessments)
        repair_request_ids = []
        for requirement, assessment in zip(requirements, assessments, strict=True):
            if assessment.get("state") == "ready":
                continue
            repair = market_automation_store.request_data_repair(
                requirement=requirement, requested_by=f"ml:{context['owner_principal']}"
            )
            repair_request_ids.append(str(repair["request_id"]))
        preparation = {
            "strategy": strategy,
            "requirements": requirements,
            "repair_request_ids": repair_request_ids,
            "universe": {
                "membership_mode": membership_mode,
                "stock_pool_id": pool_snapshot["pool_id"],
                "stock_pool_snapshot_id": pool_snapshot["snapshot_id"],
                "membership_fingerprint": pool_snapshot["membership_fingerprint"],
                "symbols": symbols,
                "index_symbol": declared.get("index_universe"),
            },
        }
        run = ml_training_store.create_waiting(
            workspace_id=context["workspace_id"], owner_principal=context["owner_principal"],
            task_id=task["task_id"], experiment_id=data.get("experiment_id"),
            ml_strategy_artifact_id=version["artifact_id"],
            stock_pool_snapshot_id=pool_snapshot["snapshot_id"], preparation=preparation,
            requirement=requirements[0], readiness=readiness, trace_id=data.get("trace_id"),
            idempotency_key=data.get("idempotency_key"),
        )
        paper_store.record_pool_reference(
            pool_snapshot["snapshot_id"], domain="ml_training", reference_id=run["training_run_id"],
            trusted_owner=context["owner_principal"],
        )
        return {"training_run": run}

    return _ml_call(operation)


@app.get("/v1/research/ml/training-runs")
def list_ml_training_runs(
    request: Request, strategy_artifact_id: str | None = None,
    limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _ml_call(lambda: ml_training_store.list_runs(
        trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"],
        strategy_artifact_id=strategy_artifact_id, limit=limit, offset=offset,
    ))


@app.get("/v1/research/ml/training-runs/reconcile")
def get_ml_training_run_by_idempotency(
    idempotency_key: str, request: Request,
) -> dict[str, object]:
    """Reconcile an outcome-unknown create without exposing cross-workspace state."""
    context = _required_agent_context(request, include_workspace=True)
    return _ml_call(lambda: {"training_run": ml_training_store.get_by_idempotency(
        idempotency_key, trusted_workspace=context["workspace_id"],
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/research/ml/training-runs/{training_run_id}")
def get_ml_training_run(training_run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _ml_call(lambda: {"training_run": ml_training_store.get(
        training_run_id, trusted_workspace=context["workspace_id"],
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/research/ml/training-runs/{training_run_id}/cancel")
def cancel_ml_training_run(training_run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _ml_call(lambda: {"training_run": ml_training_store.cancel(
        training_run_id, trusted_workspace=context["workspace_id"],
        trusted_owner=context["owner_principal"],
    )})


@app.post("/v1/research/ml/prediction-runs", status_code=202)
def create_ml_prediction_run(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        data = _strategy_payload(
            payload,
            {"task_id", "experiment_id", "model_artifact_id", "approval_artifact_id",
             "execution", "trace_id", "idempotency_key"},
        )
        task = research_store.get_task(data.get("task_id"))
        model_artifact = research_store.get_artifact(data.get("model_artifact_id"))
        approval_artifact = research_store.get_artifact(data.get("approval_artifact_id"))
        for artifact in (model_artifact, approval_artifact):
            if (
                artifact["owner_principal"] != context["owner_principal"]
                or artifact.get("workspace_id") != context["workspace_id"]
                or artifact["task_id"] != task["task_id"]
            ):
                raise ResearchNotFound("ML prediction artifact not found")
        if task["owner_principal"] != context["owner_principal"] or task.get("workspace_id") != context["workspace_id"]:
            raise ResearchNotFound("ML research task not found")
        if model_artifact["kind"] not in {"ml_model", "ml_model_bundle"} or model_artifact["status"] != "validated":
            raise ValueError("model_artifact_id must reference a validated ML model or bundle")
        if approval_artifact["kind"] != "ml_strategy_approval" or approval_artifact["status"] != "validated":
            raise ValueError("approval_artifact_id must reference a validated ML strategy approval")
        model = model_artifact.get("content")
        approval = approval_artifact.get("content")
        if not isinstance(model, dict) or not isinstance(approval, dict):
            raise ValueError("ML model or approval content is invalid")
        strategy_artifact = research_store.get_artifact(model.get("strategy_version_artifact_id"))
        if (
            strategy_artifact["kind"] != "ml_strategy_version"
            or strategy_artifact["status"] != "validated"
            or strategy_artifact["owner_principal"] != context["owner_principal"]
            or strategy_artifact.get("workspace_id") != context["workspace_id"]
            or strategy_artifact["task_id"] != task["task_id"]
        ):
            raise ValueError("model strategy lineage is invalid")
        if (
            approval.get("ml_strategy_artifact_id") != strategy_artifact["artifact_id"]
            or approval.get("decision") != "approved"
            or approval.get("execution_authorized") is not True
        ):
            raise ValueError("ML strategy is not approved for signal production")
        strategy = validate_ml_strategy_version(strategy_artifact["content"])
        bundle = model if model_artifact["kind"] == "ml_model_bundle" else None
        expert_models: dict[str, dict[str, object]] = {}
        regime_content: dict[str, object] | None = None
        if bundle is not None:
            validate_model_bundle(bundle)
            if strategy.get("schema_version") != ML_V2_SCHEMA or not isinstance(strategy.get("regime"), dict):
                raise ValueError("ML model bundle requires an approved regime strategy")
            for expert in bundle["experts"]:
                expert_artifact = research_store.get_artifact(expert["model_artifact_id"])
                if (
                    expert_artifact["kind"] != "ml_model"
                    or expert_artifact["status"] != "validated"
                    or expert_artifact["owner_principal"] != context["owner_principal"]
                    or expert_artifact.get("workspace_id") != context["workspace_id"]
                    or expert_artifact["task_id"] != task["task_id"]
                    or not isinstance(expert_artifact.get("content"), dict)
                    or expert_artifact["content"].get("content_sha256") != expert["model_content_sha256"]
                ):
                    raise ValueError("model bundle expert lineage is invalid")
                expert_models[str(expert["key"])] = {
                    "artifact_id": expert_artifact["artifact_id"],
                    "content": expert_artifact["content"],
                }
            regime_artifact = research_store.get_artifact(bundle["regime_snapshot_artifact_id"])
            if (
                regime_artifact["kind"] != "ml_regime_snapshot"
                or regime_artifact["status"] != "validated"
                or regime_artifact["owner_principal"] != context["owner_principal"]
                or regime_artifact.get("workspace_id") != context["workspace_id"]
                or regime_artifact["task_id"] != task["task_id"]
                or not isinstance(regime_artifact.get("content"), dict)
                or regime_artifact["content"].get("content_sha256") != bundle["regime_snapshot_sha256"]
            ):
                raise ValueError("model bundle regime lineage is invalid")
            regime_content = regime_artifact["content"]
        feature_artifact = research_store.get_artifact(model.get("feature_snapshot_artifact_id"))
        if (
            feature_artifact["kind"] != "ml_feature_snapshot"
            or feature_artifact["status"] != "validated"
            or feature_artifact["owner_principal"] != context["owner_principal"]
            or feature_artifact.get("workspace_id") != context["workspace_id"]
            or feature_artifact["task_id"] != task["task_id"]
        ):
            raise ValueError("model feature lineage is invalid")
        material = ml_training_store.prediction_material(
            model.get("training_run_id"), trusted_workspace=context["workspace_id"],
            trusted_owner=context["owner_principal"],
        )
        if material.get("model_artifact_id") != model_artifact["artifact_id"]:
            raise ValueError("completed training run does not authorize this model")
        requirement = material.get("requirement")
        preparation = material.get("preparation")
        frozen_readiness = material.get("readiness")
        if not isinstance(requirement, dict) or not isinstance(preparation, dict) or not isinstance(frozen_readiness, dict):
            raise ValueError("training data provenance is unavailable")
        raw_requirements = preparation.get("requirements", [requirement])
        if not isinstance(raw_requirements, list) or not raw_requirements or any(
            not isinstance(item, dict) for item in raw_requirements
        ):
            raise ValueError("training data partition provenance is unavailable")
        requirements = [dict(item) for item in raw_requirements]
        if (
            frozen_readiness.get("state") != "ready"
            or not isinstance(frozen_readiness.get("ready_input_sha256"), str)
        ):
            raise ValueError("completed training data identity is unavailable")
        feature_content = feature_artifact.get("content")
        if not isinstance(feature_content, dict):
            raise ValueError("frozen feature snapshot is unavailable")
        raw_execution = data.get("execution")
        if not isinstance(raw_execution, dict) or "initial_capital" not in raw_execution or "lot_size" not in raw_execution:
            raise ValueError("execution must explicitly freeze initial_capital and lot_size")
        execution = normalize_execution_profile(raw_execution)
        experiment_id = data.get("experiment_id")
        if experiment_id is not None and research_store.get_experiment(experiment_id)["task_id"] != task["task_id"]:
            raise ValueError("experiment does not belong to ML research task")
        run = ml_prediction_store.create(
            workspace_id=context["workspace_id"], owner_principal=context["owner_principal"],
            task_id=task["task_id"], experiment_id=experiment_id,
            ml_strategy_artifact_id=strategy_artifact["artifact_id"],
            approval_artifact_id=approval_artifact["artifact_id"],
            model_artifact_id=model_artifact["artifact_id"],
            feature_artifact_id=feature_artifact["artifact_id"],
            stock_pool_snapshot_id=model.get("stock_pool_snapshot_id"),
            input_document={"strategy": strategy, "model": model, "feature": feature_content,
                            **({"expert_models": expert_models, "regime_snapshot": regime_content} if bundle is not None else {}),
                            "requirements": requirements, "readiness": {
                                "requirement_sha256": content_sha256([
                                    item.get("requirement_sha256") for item in requirements
                                ]),
                                "ready_input_sha256": frozen_readiness.get("ready_input_sha256"),
                            }, "execution": execution},
            trace_id=data.get("trace_id"), idempotency_key=data.get("idempotency_key"),
        )
        paper_store.record_pool_reference(
            model.get("stock_pool_snapshot_id"), domain="ml_prediction",
            reference_id=run["prediction_run_id"], trusted_owner=context["owner_principal"],
        )
        return {
            "prediction_run": run,
            "backtest_task": _ml_backtest_task_view(
                run, owner_principal=context["owner_principal"]
            ),
        }

    return _ml_call(operation)


@app.get("/v1/research/ml/prediction-runs")
def list_ml_prediction_runs(
    request: Request, strategy_artifact_id: str | None = None,
    limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _ml_call(lambda: ml_prediction_store.list_runs(
        trusted_workspace=context["workspace_id"], trusted_owner=context["owner_principal"],
        strategy_artifact_id=strategy_artifact_id, limit=limit, offset=offset,
    ))


@app.get("/v1/research/ml/prediction-runs/{prediction_run_id}")
def get_ml_prediction_run(prediction_run_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    def operation() -> dict[str, object]:
        run = ml_prediction_store.get(
            prediction_run_id, trusted_workspace=context["workspace_id"],
            trusted_owner=context["owner_principal"],
        )
        return {
            "prediction_run": run,
            "backtest_task": _ml_backtest_task_view(
                run, owner_principal=context["owner_principal"]
            ),
        }

    return _ml_call(operation)


@app.get("/v1/research/ml/prediction-runs/{prediction_run_id}/rows")
def get_ml_prediction_rows(
    prediction_run_id: str, request: Request, query: str = "", limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)

    def operation() -> dict[str, object]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if len(query) > 100:
            raise ValueError("query must not exceed 100 characters")
        run = ml_prediction_store.get(
            prediction_run_id, trusted_workspace=context["workspace_id"],
            trusted_owner=context["owner_principal"],
        )
        artifact_id = run.get("prediction_artifact_id")
        if not isinstance(artifact_id, str):
            raise MLPredictionNotFound("prediction rows are not available")
        result = research_store.list_ml_prediction_rows(
            artifact_id=artifact_id,
            owner_principal=context["owner_principal"],
            workspace_id=context["workspace_id"],
            query=query,
            limit=limit,
            offset=offset,
        )
        page = [
            {key: value for key, value in row.items() if value is not None}
            for row in result["rows"] if isinstance(row, dict)
        ]
        total = int(result["total"])
        return {
            "schema_version": "ml-prediction-rows.v1",
            "prediction_run_id": prediction_run_id,
            "prediction_artifact_id": artifact_id,
            "rows": page,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": offset + limit < total,
        }

    return _ml_call(operation)


_STRATEGY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")


@app.get("/v1/research/strategies")
def list_strategy_artifacts(
    request: Request, lifecycle: str = "active", limit: int = 50, offset: int = 0
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _research_call(
        lambda: research_store.list_strategy_artifacts(
            owner_principal=context["owner_principal"],
            lifecycle=lifecycle,
            limit=limit,
            offset=offset,
        )
    )


@app.get("/v1/research/strategies/versions/{artifact_id}/approval")
def get_strategy_version_approval(artifact_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        version = research_store.get_artifact(artifact_id)
        if (
            version.get("owner_principal") != context["owner_principal"]
            or version.get("kind") != "strategy_version"
        ):
            raise ResearchNotFound("strategy version not found")
        approval = research_store.get_strategy_approval(
            owner_principal=context["owner_principal"], strategy_version_artifact_id=artifact_id
        )
        return {"approval": approval}

    return _research_call(operation)


@app.get("/v1/research/task-options")
def list_research_task_options(request: Request, limit: int = 50) -> dict[str, object]:
    context = _required_agent_context(request)
    return _research_call(lambda: {
        "tasks": research_store.list_task_options(
            owner_principal=context["owner_principal"], limit=limit
        )
    })


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
    artifacts = research_store.list_strategy_versions(
        owner_principal=context["owner_principal"], strategy_id=strategy_id
    )
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
    artifacts = research_store.list_strategy_versions(
        owner_principal=context["owner_principal"], strategy_id=strategy_id
    )
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
    if version_artifact["kind"] not in {"strategy_version", "ml_strategy_version"}:
        raise ValueError("strategy_version_artifact_id must reference a supported strategy version")
    if version_artifact["status"] != "validated":
        raise ValueError("strategy version must be validated before backtest")
    if version_artifact["task_id"] != request.get("task_id"):
        raise ValueError("strategy version artifact does not belong to task_id")
    is_ml = version_artifact["kind"] == "ml_strategy_version"
    validated_version = (
        validate_ml_strategy_version(version_artifact["content"])
        if is_ml else validate_version_content(version_artifact["content"])
    )
    approval_artifact = research_store.get_artifact(request.get("approval_artifact_id"))
    expected_approval_kind = "ml_strategy_approval" if is_ml else "strategy_approval"
    if approval_artifact["kind"] != expected_approval_kind or approval_artifact["status"] != "validated":
        raise ValueError("approval_artifact_id must reference a validated strategy approval")
    if approval_artifact["task_id"] != request.get("task_id"):
        raise ValueError("approval artifact does not belong to task_id")
    approval = approval_artifact["content"]
    if not isinstance(approval, dict):
        raise ValueError("strategy approval content is invalid")
    approval_strategy_id = (
        approval.get("ml_strategy_artifact_id") if is_ml
        else approval.get("strategy_version_artifact_id")
    )
    if approval_strategy_id != version_artifact["artifact_id"]:
        raise ValueError("approval does not authorize this strategy version")
    if approval.get("decision") != "approved" or approval.get("execution_authorized") is not True:
        raise ValueError("strategy version is not approved for execution")
    if is_ml:
        source = snapshot_content.get("source") if isinstance(snapshot_content, dict) else None
        ml_lineage = source.get("ml_lineage") if isinstance(source, dict) else None
        if not isinstance(ml_lineage, dict):
            raise ValueError("ML backtest requires a frozen ML signal lineage")
        if (
            ml_lineage.get("ml_strategy_artifact_id") != version_artifact["artifact_id"]
            or ml_lineage.get("ml_strategy_approval_artifact_id") != approval_artifact["artifact_id"]
        ):
            raise ValueError("ML signal lineage does not match the selected approval")
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
            benchmark=snapshot_content.get("benchmark", []),
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
            "signal_snapshot_artifact_id": snapshot_artifact_id,
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


def _signal_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    normalized = value.strip()
    try:
        parsed = datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error
    return parsed.strftime("%Y-%m-%d")


def _prepare_signal_producer(
    data: dict[str, Any], *, owner_principal: str, request_repair: bool
) -> dict[str, object]:
    """Shared BYQ preflight for signal jobs and the backtest task facade."""
    task = research_store.get_task(data.get("task_id"))
    if task["owner_principal"] != owner_principal:
        raise ResearchNotFound("research task not found")
    version = research_store.get_artifact(data.get("strategy_version_artifact_id"))
    if version["owner_principal"] != owner_principal:
        raise ResearchNotFound("strategy version not found")
    if version["kind"] != "strategy_version" or version["status"] != "validated":
        raise ValueError("strategy_version_artifact_id must reference a validated strategy version")
    if version["task_id"] != task["task_id"]:
        raise ValueError("strategy version does not belong to task_id")
    version_content = validate_version_content(version["content"])
    strategy_snapshot = version_content.get("snapshot")
    if not isinstance(strategy_snapshot, dict):
        raise ValueError("strategy version snapshot is invalid")
    script = strategy_snapshot.get("script")
    if not isinstance(script, str):
        raise ValueError("strategy source is unavailable")
    if strategy_output_method(script) != "generate_signals":
        raise ValueError("execution_profile_unsupported: generate_target_weights is not supported")

    pool_snapshot = paper_store.get_pool_snapshot(
        data.get("stock_pool_snapshot_id"), trusted_owner=owner_principal
    )
    pool = paper_store.get_pool(pool_snapshot["pool_id"], trusted_owner=owner_principal)
    if pool["status"] != "active":
        raise ValueError("stock pool must be active for signal production")
    symbols = sorted(
        str(item["symbol"])
        for item in pool_snapshot.get("members", [])
        if isinstance(item, dict) and isinstance(item.get("symbol"), str)
    )
    if not symbols:
        raise ValueError("stock pool snapshot has no members")
    start_date = _signal_date(data.get("start_date"), "start_date")
    end_date = _signal_date(data.get("end_date"), "end_date")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    parameters = data.get("parameters", strategy_snapshot.get("parameters", {}))
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    execution = data.get("execution", {})
    if not isinstance(execution, dict):
        raise ValueError("execution must be an object")
    order_quantity = data.get("order_quantity", 100)
    if not isinstance(order_quantity, int) or isinstance(order_quantity, bool) or order_quantity < 1:
        raise ValueError("order_quantity must be a positive integer")
    lot_size = execution.get("lot_size", 100)
    if not isinstance(lot_size, int) or isinstance(lot_size, bool) or lot_size < 1:
        raise ValueError("execution.lot_size must be a positive integer")
    if order_quantity % lot_size:
        raise ValueError("order_quantity must be aligned to execution.lot_size")

    master_snapshot = security_master_store.latest_snapshot()
    if master_snapshot is None:
        raise ValueError("security master must be synchronized before backtest data preparation")
    fingerprint = membership_fingerprint(symbols)
    requirement = market_readiness_store.requirement(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        membership_fingerprint=fingerprint,
        security_master_snapshot_id=str(master_snapshot["snapshot_id"]),
        data_requirements=(
            strategy_snapshot.get("data_requirements")
            if isinstance(strategy_snapshot.get("data_requirements"), dict) else {}
        ),
    )
    readiness = market_readiness_store.assess(requirement)
    if readiness["state"] != "ready":
        if any(item.get("dataset") == "security_lifecycle" for item in readiness["missing"]):
            raise ValueError("stock pool contains symbols absent from the frozen security master")
        if request_repair:
            market_automation_store.request_data_repair(
                requirement=requirement, requested_by=f"signal:{owner_principal}"
            )
    preparation = {
        "strategy_version_artifact_id": str(version["artifact_id"]),
        "strategy_version_id": str(version_content["version_id"]),
        "source_fingerprint": str(version_content["source_fingerprint"]),
        "script": script,
        "stock_pool_snapshot_id": str(pool_snapshot["snapshot_id"]),
        "stock_pool_id": str(pool_snapshot["pool_id"]),
        "membership_fingerprint": fingerprint,
        "symbols": symbols,
        "parameters": parameters,
        "execution": execution,
        "order_quantity": order_quantity,
    }
    return {
        "task": task,
        "version": version,
        "pool_snapshot": pool_snapshot,
        "preparation": preparation,
        "requirement": requirement,
        "readiness": readiness,
    }


@app.post("/v1/research/signal-producer/jobs", status_code=202)
def create_signal_producer_job(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Freeze owner-scoped BYQ inputs before isolated strategy execution."""
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        data = _strategy_payload(
            payload,
            {
                "task_id", "experiment_id", "strategy_version_artifact_id",
                "stock_pool_snapshot_id", "start_date", "end_date", "parameters",
                "execution", "order_quantity", "trace_id", "idempotency_key",
            },
        )
        prepared = _prepare_signal_producer(
            data, owner_principal=context["owner_principal"], request_repair=True
        )
        task = prepared["task"]
        version = prepared["version"]
        pool_snapshot = prepared["pool_snapshot"]
        job = signal_job_store.create_waiting(
            owner_principal=context["owner_principal"],
            task_id=task["task_id"],
            experiment_id=data.get("experiment_id"),
            strategy_version_artifact_id=version["artifact_id"],
            stock_pool_snapshot_id=pool_snapshot["snapshot_id"],
            preparation=prepared["preparation"], requirement=prepared["requirement"],
            readiness=prepared["readiness"],
            trace_id=data.get("trace_id"),
            idempotency_key=data.get("idempotency_key"),
        )
        paper_store.record_pool_reference(
            pool_snapshot["snapshot_id"], domain="signal_producer", reference_id=job["job_id"],
            trusted_owner=context["owner_principal"],
        )
        return {"job": job}

    return _signal_producer_call(operation)


@app.get("/v1/research/signal-producer/jobs")
def list_signal_producer_jobs(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    context = _required_agent_context(request)
    return _signal_producer_call(
        lambda: signal_job_store.list_jobs(
            trusted_owner=context["owner_principal"], limit=limit, offset=offset
        )
    )


@app.get("/v1/research/signal-producer/jobs/{job_id}")
def get_signal_producer_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _signal_producer_call(
        lambda: {"job": signal_job_store.get(job_id, trusted_owner=context["owner_principal"])}
    )


def _approved_strategy_artifact(owner_principal: str, version_artifact_id: str) -> str | None:
    for artifact in research_store.list_strategy_approvals(owner_principal=owner_principal):
        content = artifact.get("content")
        if (
            artifact.get("kind") == "strategy_approval"
            and artifact.get("status") == "validated"
            and isinstance(content, dict)
            and content.get("strategy_version_artifact_id") == version_artifact_id
            and content.get("decision") == "approved"
            and content.get("execution_authorized") is True
        ):
            return str(artifact["artifact_id"])
    return None


def _backtest_task_view(signal_job: dict[str, Any], *, owner_principal: str) -> dict[str, object]:
    approval_id = _approved_strategy_artifact(
        owner_principal, str(signal_job["strategy_version_artifact_id"])
    )
    snapshot_id = signal_job.get("result_artifact_id")
    backtest_job = None
    if isinstance(snapshot_id, str):
        backtest_job = backtest_store.find_by_signal_snapshot(
            owner_principal=owner_principal, signal_snapshot_artifact_id=snapshot_id
        )
    readiness = signal_job.get("readiness")
    return project_backtest_task(
        research_task_id=str(signal_job["task_id"]),
        strategy_version_artifact_id=str(signal_job["strategy_version_artifact_id"]),
        approval_artifact_id=approval_id,
        stock_pool_snapshot_id=str(signal_job["stock_pool_snapshot_id"]),
        readiness=readiness if isinstance(readiness, dict) else None,
        signal_job=signal_job,
        backtest_job=backtest_job,
    )


def _ml_backtest_task_view(
    prediction_run: dict[str, Any], *, owner_principal: str
) -> dict[str, object]:
    snapshot_id = prediction_run.get("signal_artifact_id")
    backtest_job = None
    if isinstance(snapshot_id, str):
        backtest_job = backtest_store.find_by_signal_snapshot(
            owner_principal=owner_principal, signal_snapshot_artifact_id=snapshot_id
        )
    signal_projection = {
        "job_id": prediction_run["prediction_run_id"],
        "status": prediction_run["status"],
        "attempt_count": prediction_run.get("attempt_count"),
        "result_artifact_id": snapshot_id,
        "error_code": prediction_run.get("error_code"),
        "error_detail": prediction_run.get("error_detail"),
    }
    return project_backtest_task(
        research_task_id=str(prediction_run["task_id"]),
        strategy_version_artifact_id=str(prediction_run["ml_strategy_artifact_id"]),
        approval_artifact_id=str(prediction_run["approval_artifact_id"]),
        stock_pool_snapshot_id=str(prediction_run["stock_pool_snapshot_id"]),
        readiness={"state": "ready", "source": "frozen_ml_prediction"},
        signal_job=signal_projection,
        backtest_job=backtest_job,
        backtest_task_id=task_id_from_ml_prediction(prediction_run["prediction_run_id"]),
        signal_cancellable=False,
    )


def _backtest_task_input(payload: object, *, include_idempotency: bool) -> dict[str, Any]:
    allowed = {
        "task_id", "experiment_id", "strategy_version_artifact_id",
        "stock_pool_snapshot_id", "start_date", "end_date", "parameters",
        "execution", "order_quantity",
    }
    if include_idempotency:
        allowed.add("idempotency_key")
    return _strategy_payload(payload, allowed)


@app.post("/v1/research/backtest-tasks/prepare")
def prepare_backtest_task(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Read-only preflight; no AgentRun, repair request, signal job, or backtest job."""
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        data = _backtest_task_input(payload, include_idempotency=False)
        prepared = _prepare_signal_producer(
            data, owner_principal=context["owner_principal"], request_repair=False
        )
        version = prepared["version"]
        approval_id = _approved_strategy_artifact(
            context["owner_principal"], str(version["artifact_id"])
        )
        return {"task": project_backtest_task(
            research_task_id=str(prepared["task"]["task_id"]),
            strategy_version_artifact_id=str(version["artifact_id"]),
            approval_artifact_id=approval_id,
            stock_pool_snapshot_id=str(prepared["pool_snapshot"]["snapshot_id"]),
            readiness=prepared["readiness"],
        )}

    return _backtest_task_call(operation)


@app.post("/v1/research/backtest-tasks", status_code=202)
def create_backtest_task(payload: dict[str, Any], request: Request) -> dict[str, object]:
    """Create the existing signal-preparation component and return its derived facade."""
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        data = _backtest_task_input(payload, include_idempotency=True)
        prepared = _prepare_signal_producer(
            data, owner_principal=context["owner_principal"], request_repair=True
        )
        version = prepared["version"]
        if _approved_strategy_artifact(
            context["owner_principal"], str(version["artifact_id"])
        ) is None:
            raise ValueError("strategy version must be approved before task creation")
        job = signal_job_store.create_waiting(
            owner_principal=context["owner_principal"],
            task_id=prepared["task"]["task_id"],
            experiment_id=data.get("experiment_id"),
            strategy_version_artifact_id=version["artifact_id"],
            stock_pool_snapshot_id=prepared["pool_snapshot"]["snapshot_id"],
            preparation=prepared["preparation"],
            requirement=prepared["requirement"],
            readiness=prepared["readiness"],
            trace_id=context["trace_id"],
            idempotency_key=data.get("idempotency_key"),
        )
        paper_store.record_pool_reference(
            str(prepared["pool_snapshot"]["snapshot_id"]),
            domain="signal_producer",
            reference_id=str(job["job_id"]),
            trusted_owner=context["owner_principal"],
        )
        return {"task": _backtest_task_view(job, owner_principal=context["owner_principal"])}

    return _backtest_task_call(operation)


@app.get("/v1/research/backtest-tasks/{backtest_task_id}")
def get_backtest_task(backtest_task_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        if is_ml_backtest_task(backtest_task_id):
            ml_context = _required_agent_context(request, include_workspace=True)
            prediction_run = ml_prediction_store.get(
                ml_prediction_id_from_task(backtest_task_id),
                trusted_workspace=ml_context["workspace_id"],
                trusted_owner=ml_context["owner_principal"],
            )
            return {"task": _ml_backtest_task_view(
                prediction_run, owner_principal=ml_context["owner_principal"]
            )}
        signal_job = signal_job_store.get(
            signal_job_id_from_task(backtest_task_id),
            trusted_owner=context["owner_principal"],
        )
        return {"task": _backtest_task_view(signal_job, owner_principal=context["owner_principal"])}

    return _backtest_task_call(operation)


@app.post("/v1/research/backtest-tasks/{backtest_task_id}/execute")
def execute_backtest_task(backtest_task_id: str, request: Request) -> dict[str, object]:
    """Materialize and run only after the trusted worker produced a frozen snapshot."""
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        if is_ml_backtest_task(backtest_task_id):
            ml_context = _required_agent_context(request, include_workspace=True)
            prediction_run = ml_prediction_store.get(
                ml_prediction_id_from_task(backtest_task_id),
                trusted_workspace=ml_context["workspace_id"],
                trusted_owner=ml_context["owner_principal"],
            )
            current = _ml_backtest_task_view(
                prediction_run, owner_principal=ml_context["owner_principal"]
            )
            if current["phase"] not in {"ready_to_execute", "queued"}:
                return {"task": current}
            references = current["references"]
            backtest_job_id = references.get("backtest_job_id")
            if backtest_job_id is None:
                created = create_backtest_job(
                    {
                        "task_id": prediction_run["task_id"],
                        "experiment_id": prediction_run.get("experiment_id"),
                        "strategy_version_artifact_id": prediction_run["ml_strategy_artifact_id"],
                        "approval_artifact_id": prediction_run["approval_artifact_id"],
                        "signal_snapshot_artifact_id": prediction_run["signal_artifact_id"],
                        "stock_pool_snapshot_id": prediction_run["stock_pool_snapshot_id"],
                        "trace_id": ml_context["trace_id"],
                        "idempotency_key": f"backtest-task-{backtest_task_id.removeprefix('backtesttask_ml_')}",
                    },
                    request,
                )
                backtest_job_id = created["job"]["job_id"]
            job = backtest_store.get(backtest_job_id)
            if job["status"] == "queued":
                run_backtest_job(str(backtest_job_id), request)
            refreshed = ml_prediction_store.get(
                prediction_run["prediction_run_id"],
                trusted_workspace=ml_context["workspace_id"],
                trusted_owner=ml_context["owner_principal"],
            )
            return {"task": _ml_backtest_task_view(
                refreshed, owner_principal=ml_context["owner_principal"]
            )}
        signal_job = signal_job_store.get(
            signal_job_id_from_task(backtest_task_id),
            trusted_owner=context["owner_principal"],
        )
        current = _backtest_task_view(signal_job, owner_principal=context["owner_principal"])
        if current["phase"] not in {"ready_to_execute", "queued"}:
            return {"task": current}
        references = current["references"]
        backtest_job_id = references.get("backtest_job_id")
        if backtest_job_id is None:
            created = create_backtest_job(
                {
                    "task_id": signal_job["task_id"],
                    "experiment_id": signal_job.get("experiment_id"),
                    "strategy_version_artifact_id": signal_job["strategy_version_artifact_id"],
                    "approval_artifact_id": references["approval_artifact_id"],
                    "signal_snapshot_artifact_id": signal_job["result_artifact_id"],
                    "stock_pool_snapshot_id": signal_job["stock_pool_snapshot_id"],
                    "trace_id": context["trace_id"],
                    "idempotency_key": f"backtest-task-{backtest_task_id.removeprefix('backtesttask_')}",
                },
                request,
            )
            backtest_job_id = created["job"]["job_id"]
        job = backtest_store.get(backtest_job_id)
        if job["status"] == "queued":
            run_backtest_job(str(backtest_job_id), request)
        refreshed = signal_job_store.get(
            signal_job_id_from_task(backtest_task_id),
            trusted_owner=context["owner_principal"],
        )
        return {"task": _backtest_task_view(refreshed, owner_principal=context["owner_principal"])}

    return _backtest_task_call(operation)


@app.post("/v1/research/backtest-tasks/{backtest_task_id}/cancel")
def cancel_backtest_task(backtest_task_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        if is_ml_backtest_task(backtest_task_id):
            ml_context = _required_agent_context(request, include_workspace=True)
            prediction_run = ml_prediction_store.get(
                ml_prediction_id_from_task(backtest_task_id),
                trusted_workspace=ml_context["workspace_id"],
                trusted_owner=ml_context["owner_principal"],
            )
            current = _ml_backtest_task_view(
                prediction_run, owner_principal=ml_context["owner_principal"]
            )
            backtest_job_id = current["references"].get("backtest_job_id")
            if isinstance(backtest_job_id, str):
                cancel_backtest_job(backtest_job_id, request)
            refreshed = ml_prediction_store.get(
                prediction_run["prediction_run_id"],
                trusted_workspace=ml_context["workspace_id"],
                trusted_owner=ml_context["owner_principal"],
            )
            return {"task": _ml_backtest_task_view(
                refreshed, owner_principal=ml_context["owner_principal"]
            )}
        signal_job = signal_job_store.get(
            signal_job_id_from_task(backtest_task_id),
            trusted_owner=context["owner_principal"],
        )
        current = _backtest_task_view(signal_job, owner_principal=context["owner_principal"])
        backtest_job_id = current["references"].get("backtest_job_id")
        if isinstance(backtest_job_id, str):
            cancel_backtest_job(backtest_job_id, request)
        else:
            signal_job_store.cancel(
                signal_job["job_id"], trusted_owner=context["owner_principal"]
            )
        refreshed = signal_job_store.get(
            signal_job["job_id"], trusted_owner=context["owner_principal"]
        )
        return {"task": _backtest_task_view(refreshed, owner_principal=context["owner_principal"])}

    return _backtest_task_call(operation)


@app.post("/v1/research/backtests", status_code=202)
def create_backtest_job(
    payload: dict[str, Any], request: Request, projection: str = "full",
) -> dict[str, object]:
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
                corporate_actions=manifest["corporate_actions"],
                benchmark=manifest.get("benchmark", []), execution=manifest["execution"],
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
        return {"job": project_backtest_summary(job) if projection == "summary" else job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/options")
def backtest_options(request: Request) -> dict[str, object]:
    """Return runnable backtest options for the wizard (Phase 32, ADR-0017).

    Aggregates validated strategy versions that have an approved
    strategy_approval for the caller, with the task/approval identities the
    wizard needs to submit a backtest referencing a signal_snapshot.
    """
    context = _required_agent_context(request)
    versions_list = research_store.list_validated_strategy_versions(
        owner_principal=context["owner_principal"]
    )
    artifacts = versions_list + research_store.list_strategy_approvals(
        owner_principal=context["owner_principal"]
    )
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
        snapshot = content.get("snapshot")
        data_requirements = (
            snapshot.get("data_requirements")
            if isinstance(snapshot, dict) and isinstance(snapshot.get("data_requirements"), dict)
            else {}
        )
        benchmark_symbol = data_requirements.get("benchmark")
        options.append(
            {
                "strategy_version_artifact_id": version_id,
                "task_id": item["task_id"],
                "approval_artifact_id": approved_by_version[version_id],
                "strategy_id": content.get("strategy_id"),
                "strategy_version_id": content.get("version_id"),
                "benchmark_symbol": benchmark_symbol if isinstance(benchmark_symbol, str) else None,
            }
        )
    return {"options": options}


@app.get("/v1/research/backtests/catalog")
def list_backtest_catalog(
    request: Request, query: str = "", status: str = "", limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _backtest_call(lambda: backtest_store.list_backtest_summaries(
        owner_principal=context["owner_principal"], query=query, status=status,
        workspace_id=context["workspace_id"], limit=limit, offset=offset,
    ))


@app.get("/v1/research/backtests/{job_id}")
def get_backtest_job(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        return {"job": job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/{job_id}/summary")
def get_backtest_job_summary(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get_backtest_summary(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        return {"job": job}

    return _backtest_call(operation)


@app.get("/v1/research/backtests/{job_id}/manifest")
def get_backtest_job_manifest(job_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get_backtest_summary(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        return {"job_id": job_id, "input_manifest": backtest_store.get_input_manifest(job_id)}

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


def _backtest_feature_diagnostics(
    *, owner_principal: str, signal_snapshot_artifact_id: object,
) -> dict[str, object] | None:
    if not isinstance(signal_snapshot_artifact_id, str):
        return None
    try:
        snapshot = research_store.get_artifact(signal_snapshot_artifact_id)
    except ResearchNotFound:
        return None
    if snapshot.get("owner_principal") != owner_principal or snapshot.get("kind") != "signal_snapshot":
        return None
    content = snapshot.get("content")
    source = content.get("source") if isinstance(content, dict) else None
    lineage = source.get("ml_lineage") if isinstance(source, dict) else None
    feature_id = lineage.get("feature_snapshot_artifact_id") if isinstance(lineage, dict) else None
    if not isinstance(feature_id, str):
        return None
    try:
        feature = research_store.get_artifact(feature_id)
    except ResearchNotFound:
        return None
    if feature.get("owner_principal") != owner_principal or feature.get("kind") != "ml_feature_snapshot":
        return None
    feature_content = feature.get("content")
    if not isinstance(feature_content, dict):
        return None
    coverage = feature_content.get("coverage")
    excluded = feature_content.get("excluded")
    return {
        "coverage": coverage if isinstance(coverage, dict) else {},
        "excluded": excluded if isinstance(excluded, dict) else {},
        "reason_definitions": {
            "warmup_or_missing": "required rolling history is unavailable within the point-in-time universe",
            "label_outside_split": "future label would cross the declared split boundary",
            "non_finite": "feature or label is not finite",
        },
    }


@app.get("/v1/research/backtests/{job_id}/analysis")
def get_backtest_analysis(
    job_id: str, request: Request, section: str = "summary", limit: int = 50,
    offset: int = 0, query: str = "",
) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.analysis_context(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest analysis not found")
        reference = job.get("result_reference_json")
        if not isinstance(reference, dict):
            raise BacktestConflict("backtest job has no result yet")
        try:
            result = load_result(backtest_objects, reference)
        except ObjectIntegrityError as error:
            raise BacktestStorageError("backtest result object is unavailable") from error
        diagnostics = _backtest_feature_diagnostics(
            owner_principal=context["owner_principal"],
            signal_snapshot_artifact_id=job.get("signal_snapshot_artifact_id"),
        )
        analysis = build_backtest_analysis(
            result, section=section, limit=limit, offset=offset, query=query,
            execution=job.get("execution") if isinstance(job.get("execution"), dict) else {},
            feature_diagnostics=diagnostics,
        )
        return {"job_id": job_id, "analysis": analysis}

    return _backtest_call(operation)


@app.get("/v1/research/backtests")
def list_backtest_jobs(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _backtest_call(lambda: backtest_store.list_backtests(owner_principal=context["owner_principal"]))


@app.post("/v1/research/backtests/{job_id}/run")
def run_backtest_job(
    job_id: str, request: Request, projection: str = "full",
) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        worker = BacktestWorker(backtest_store, research_store, backtest_objects)
        updated = worker.run_once(job_id)
        return {"job": project_backtest_summary(updated) if projection == "summary" else updated}

    return _backtest_call(operation)


@app.post("/v1/research/backtests/{job_id}/cancel")
def cancel_backtest_job(
    job_id: str, request: Request, projection: str = "full",
) -> dict[str, object]:
    context = _required_agent_context(request)

    def operation() -> dict[str, object]:
        job = backtest_store.get(job_id)
        if job["owner_principal"] != context["owner_principal"]:
            raise BacktestNotFound("backtest job not found")
        updated = backtest_store.cancel(job_id)
        return {"job": project_backtest_summary(updated) if projection == "summary" else updated}

    return _backtest_call(operation)

@app.delete("/v1/research/backtests/{job_id}")
def delete_backtest_job(
    job_id: str, request: Request, projection: str = "full",
) -> dict[str, object]:
    context = _required_agent_context(request)
    def operation() -> dict[str, object]:
        deleted = backtest_store.delete(job_id, owner_principal=context["owner_principal"])
        _gc_deleted_backtest_objects(deleted, owner_principal=context["owner_principal"])
        return {"job": project_backtest_summary(deleted) if projection == "summary" else deleted}

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
    clean_payload = {
        key: value for key, value in payload.items()
        if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}
    }

    def operation() -> dict[str, object]:
        base = agent_store.authorize(
            clean_payload,
            trusted_owner=context["owner_principal"],
            trusted_actor=context["actor_principal"],
        )
        effective = user_policy_store.evaluate_authorization(context["owner_principal"], base)
        if effective.get("decision") == "policy_denied":
            agent_store.record_audit(
                {
                    "run_id": clean_payload.get("run_id"),
                    "action": "policy.enforce",
                    "outcome": "denied",
                    "resource_type": clean_payload.get("resource_type"),
                    "resource_id": clean_payload.get("resource_id"),
                    "detail": {
                        "domain_action": clean_payload.get("action"),
                        "policy_rule_id": effective.get("policy_rule_id"),
                    },
                },
                trusted_owner=context["owner_principal"],
                trusted_actor=context["actor_principal"],
            )
        return {"authorization": effective}

    return _agent_call(operation)


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
def list_agent_approvals(
    request: Request, status: str | None = None, limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _agent_call(lambda: agent_store.list_approvals(
        trusted_owner=context["owner_principal"], status=status, limit=limit, offset=offset,
    ))


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


@app.post("/v1/agents/approvals/{approval_id}/continuation")
def update_agent_approval_continuation(
    approval_id: str, payload: dict[str, Any], request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    if set(payload) - {
        "status", "owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id",
    }:
        raise HTTPException(status_code=422, detail="continuation request has invalid fields")
    return _agent_call(lambda: {"approval": agent_store.set_continuation_status(
        approval_id, payload.get("status"), trusted_owner=context["owner_principal"],
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


@app.delete("/v1/paper/accounts/{account_id}")
def delete_paper_account(account_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: paper_store.delete_account(
        account_id,
        {key: value for key, value in payload.items() if key not in {
            "owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"
        }},
        trusted_owner=context["owner_principal"],
        trusted_actor=context["actor_principal"],
    ))


@app.post("/v1/paper/pools", status_code=201)
def create_stock_pool(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload)
    return _paper_call(lambda: {"pool": paper_store.create_pool(
        {key: value for key, value in payload.items() if key not in {"owner_principal", "actor_principal", "trace_id", "session_id", "dsh_run_id"}},
        trusted_owner=context["owner_principal"],
    )})


@app.get("/v1/paper/index-pools/catalog")
def list_index_pool_catalog(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    _required_agent_context(request)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.list_index_catalog(limit=limit, offset=offset))


@app.post("/v1/paper/index-pools", status_code=202)
def create_index_pool(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.create_index_pool(
        payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    ))


@app.post("/v1/paper/dynamic-pools/preview")
def preview_dynamic_pool(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.preview_dynamic_pool(
        payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    ))


@app.post("/v1/paper/dynamic-pools", status_code=202)
def create_dynamic_pool(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.create_dynamic_pool(
        payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    ))


@app.post("/v1/paper/producer-imports", status_code=201)
def import_stock_pool_producer(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.import_inactive_definition(
        payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    ))


@app.get("/v1/paper/pools/{pool_id}/producer")
def get_stock_pool_producer(pool_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _stock_pool_producer_call(lambda: {"producer": stock_pool_producer_store.get_definition(
        pool_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )})


@app.get("/v1/paper/pools/{pool_id}/materializations")
def list_stock_pool_materializations(
    pool_id: str, request: Request, limit: int = 50, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    return _stock_pool_producer_call(lambda: stock_pool_producer_store.list_runs(
        pool_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
        limit=limit, offset=offset,
    ))


@app.put("/v1/paper/pools/{pool_id}/producer")
def update_stock_pool_producer(pool_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: {"producer": stock_pool_producer_store.update_dynamic_definition(
        pool_id, payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )})


@app.post("/v1/paper/pools/{pool_id}/materializations", status_code=202)
def refresh_stock_pool_producer(pool_id: str, payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request, payload, include_workspace=True)
    return _stock_pool_producer_call(lambda: {"run": stock_pool_producer_store.enqueue_pool_refresh(
        pool_id, payload, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )})


@app.get("/v1/paper/pools/{pool_id}")
def get_stock_pool(pool_id: str, request: Request, include_members: bool = True) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"pool": paper_store.get_pool(
        pool_id,
        trusted_owner=context["owner_principal"],
        include_members=include_members,
    )})


@app.get("/v1/paper/pools/{pool_id}/members")
def list_stock_pool_members(
    pool_id: str, request: Request, query: str = "", limit: int = 20, offset: int = 0,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: paper_store.list_pool_members(
        pool_id,
        trusted_owner=context["owner_principal"],
        query=query,
        limit=limit,
        offset=offset,
    ))


@app.get("/v1/paper/pools")
def list_stock_pools(request: Request, limit: int = 50, offset: int = 0) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    def catalog() -> dict[str, object]:
        result = paper_store.list_pools(trusted_owner=context["owner_principal"], limit=limit, offset=offset)
        for pool in result["pools"]:
            if pool.get("pool_type") == "custom":
                pool["readiness"] = {
                    "schema_version": "stock-pool-readiness.v1", "pool_id": pool["pool_id"],
                    "state": "current" if pool.get("current_snapshot_id") and pool.get("status") == "active" else "paused",
                    "current_snapshot_id": pool.get("current_snapshot_id"),
                }
            else:
                pool["readiness"] = stock_pool_producer_store.get_readiness(
                    pool["pool_id"], trusted_owner=context["owner_principal"],
                    trusted_workspace=context["workspace_id"],
                )
        return result
    return _paper_call(catalog)


@app.get("/v1/paper/pools/{pool_id}/readiness")
def get_stock_pool_readiness(pool_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request, include_workspace=True)
    pool = paper_store.get_pool(pool_id, trusted_owner=context["owner_principal"])
    if pool["pool_type"] == "custom":
        return {"readiness": {
            "schema_version": "stock-pool-readiness.v1", "pool_id": pool_id,
            "state": "current" if pool.get("current_snapshot_id") and pool.get("status") == "active" else "paused",
            "current_snapshot_id": pool.get("current_snapshot_id"),
        }}
    return _stock_pool_producer_call(lambda: {"readiness": stock_pool_producer_store.get_readiness(
        pool_id, trusted_owner=context["owner_principal"], trusted_workspace=context["workspace_id"],
    )})


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


@app.get("/v1/paper/pools/{pool_id}/snapshot-diff")
def diff_stock_pool_snapshots(
    pool_id: str, request: Request, from_snapshot_id: str, to_snapshot_id: str,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _paper_call(lambda: {"diff": paper_store.diff_pool_snapshots(
        pool_id, from_snapshot_id, to_snapshot_id, trusted_owner=context["owner_principal"],
    )})


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
    return _user_call(lambda: _login_user(payload.get("username"), payload.get("password")))


@app.post("/v1/auth/logout")
def logout(payload: dict[str, Any]) -> dict[str, object]:
    return _user_call(lambda: user_store.logout(payload.get("session_id")))


@app.get("/v1/auth/session")
def get_session(request: Request) -> dict[str, object]:
    session_id = request.headers.get("x-byq-session-id")
    if not session_id:
        raise HTTPException(status_code=401, detail="session required")
    return _user_call(lambda: _authenticated_user_payload(user_store.get_session_user(session_id)))


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


@app.get("/v1/users/{user_id}/ui-preferences")
def get_user_ui_preferences(user_id: str, request: Request) -> dict[str, object]:
    owner_user_id = request.headers.get("x-byq-owner-user-id")
    if owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="UI preferences read is owner-scoped")
    return _user_call(lambda: {"preferences": user_store.get_ui_preferences(user_id)})


@app.put("/v1/users/{user_id}/ui-preferences")
def update_user_ui_preferences(
    user_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    owner_user_id = request.headers.get("x-byq-owner-user-id")
    if owner_user_id != user_id:
        raise HTTPException(status_code=403, detail="UI preferences update is owner-scoped")
    return _user_call(lambda: {"preferences": user_store.update_ui_preferences(user_id, payload)})


def _policy_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except UserPolicyNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except UserPolicyConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UserPolicyPersistenceError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _credential_call(operation: Callable[[], dict[str, object]]) -> dict[str, object]:
    try:
        return operation()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CredentialNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CredentialForbidden as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except CredentialConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (CredentialUnavailable, CredentialPersistenceError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/v1/users/model-catalog")
def get_model_catalog(request: Request) -> dict[str, object]:
    _required_agent_context(request)
    return {"providers": [dict(item) for item in MODEL_PROVIDERS],
            "models": [
                {key: value for key, value in item.items() if key != "runtime_provider"}
                for item in MODEL_CATALOG
            ], "agents": [
        {"agent_id": "byq-product", "name": "小巴 Product Agent"},
    ]}


@app.get("/v1/users/model-credentials")
def list_model_credentials(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {
        "credentials": credential_store.list_credentials(context["owner_principal"]),
        "encryption": credential_store.encryption_status(),
    })


@app.post("/v1/users/model-credentials", status_code=201)
def create_model_credential(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"credential": credential_store.create_credential(
        context["owner_principal"],
        {**payload, "purpose": "model_api_key", "scope": "user"},
        actor=context["actor_principal"],
    )})


@app.put("/v1/users/model-credentials/{credential_id}")
def update_model_credential(
    credential_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"credential": credential_store.update_credential(
        credential_id,
        context["owner_principal"],
        payload,
        actor=context["actor_principal"],
    )})


@app.post("/v1/users/model-credentials/{credential_id}/revoke")
def revoke_model_credential(
    credential_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"credential": credential_store.revoke_credential(
        credential_id,
        context["owner_principal"],
        actor=context["actor_principal"],
        expected_version=payload.get("expected_version"),
        request_id=payload.get("request_id"),
    )})


@app.get("/v1/users/model-profiles")
def list_model_profiles(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"profiles": credential_store.list_profiles(
        context["owner_principal"],
    )})


@app.post("/v1/users/model-profiles", status_code=201)
def create_model_profile(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"profile": credential_store.create_profile(
        context["owner_principal"],
        payload,
    )})


@app.post("/v1/users/model-profiles/{profile_id}/delete")
def delete_model_profile(
    profile_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"profile": credential_store.delete_profile(
        profile_id,
        context["owner_principal"],
        expected_version=payload.get("expected_version"),
    )})


@app.get("/v1/users/model-bindings")
def list_model_bindings(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"bindings": credential_store.list_bindings(
        context["owner_principal"],
    )})


@app.put("/v1/users/model-bindings/{agent_id}")
def put_model_binding(
    agent_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"binding": credential_store.bind(
        context["owner_principal"],
        agent_id,
        payload.get("profile_id"),
        expected_version=payload.get("expected_version"),
    )})


@app.get("/v1/users/model-credential-audit")
def list_model_credential_audit(request: Request, limit: int = 100) -> dict[str, object]:
    context = _required_agent_context(request)
    return _credential_call(lambda: {"events": credential_store.list_audit(
        context["owner_principal"],
        limit=limit,
    )})


@app.post("/internal/credentials/model-resolution")
def resolve_model_credential(payload: dict[str, Any], request: Request) -> dict[str, object]:
    try:
        authorize_resolver(
            request.headers.get("x-byq-credential-resolver-token"),
            CREDENTIAL_RESOLVER_TOKEN,
        )
        owner = payload.get("owner_principal")
        agent_id = payload.get("agent_id")
        # Validate correlation fields even though they are never persisted.
        _required = {
            "session_id": payload.get("session_id"),
            "trace_id": payload.get("trace_id"),
        }
        for field, value in _required.items():
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f"{field} is not valid")
        resolution = credential_store.resolve_model(owner, agent_id)
        if resolution is None:
            raise CredentialNotFound("personal model binding not found")
        return {"resolution": resolution}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except CredentialNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CredentialForbidden as error:
        raise HTTPException(status_code=403, detail="credential resolver denied") from error
    except CredentialUnavailable as error:
        raise HTTPException(status_code=409, detail="selected model binding is unavailable") from error


@app.get("/v1/users/agent-policy")
def get_user_agent_policy(request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {
        "policy": public_policy(user_policy_store.get(context["owner_principal"])),
        "rules": user_policy_store.list_rules(context["owner_principal"]),
        "presets": user_policy_store.list_presets(),
        "audit": user_policy_store.list_audit(context["owner_principal"]),
    })


@app.put("/v1/users/agent-policy")
def update_user_agent_policy(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {"policy": public_policy(user_policy_store.update(context["owner_principal"], payload))})


@app.post("/v1/users/agent-policy/rules", status_code=201)
def create_user_agent_policy_rule(payload: dict[str, Any], request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {"rule": user_policy_store.create_rule(
        context["owner_principal"],
        payload,
        actor=context["actor_principal"],
    )})


@app.put("/v1/users/agent-policy/rules/{rule_id}")
def update_user_agent_policy_rule(
    rule_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: {"rule": user_policy_store.update_rule(
        rule_id,
        context["owner_principal"],
        payload,
        actor=context["actor_principal"],
    )})


@app.post("/v1/users/agent-policy/rules/{rule_id}/delete")
def delete_user_agent_policy_rule(
    rule_id: str,
    payload: dict[str, Any],
    request: Request,
) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: user_policy_store.delete_rule(
        rule_id,
        context["owner_principal"],
        actor=context["actor_principal"],
        expected_version=payload.get("expected_version"),
    ))


@app.post("/v1/users/agent-policy/presets/{preset_id}/apply")
def apply_user_agent_policy_preset(preset_id: str, request: Request) -> dict[str, object]:
    context = _required_agent_context(request)
    return _policy_call(lambda: user_policy_store.apply_preset(
        context["owner_principal"],
        preset_id,
        actor=context["actor_principal"],
    ))
