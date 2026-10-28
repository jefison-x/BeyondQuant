<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { reconcileProductApprovalRequest, listProductApprovalRequests, type ProductApprovalRequest } from "@/api/research";
import { decideProductApprovalRequestOnce } from "@/api/approvalRequestSubmissions";
import { useAuthStore } from "@/stores/auth";
import EntityPagination from "@/components/ui/EntityPagination.vue";

const emit = defineEmits<{ pendingCount: [count: number] }>();
const auth = useAuthStore();
const pendingRequests = ref<ProductApprovalRequest[]>([]);
const unresolvedRequests = ref<ProductApprovalRequest[]>([]);
const pendingTotal = ref(0);
const unresolvedTotal = ref(0);
const attentionTotal = ref(0);
const pendingCount = ref(0);
const pendingPage = ref(1);
const unresolvedPage = ref(1);
const loading = ref(false);
const error = ref("");
const busyId = ref("");
const PAGE_SIZE = 10;
let loadGeneration = 0;
let scopeGeneration = 0;
let decisionPromptGeneration = 0;
let actionGeneration = 0;
const authScope = computed(() => `${auth.user?.subject ?? ""}\u0000${auth.user?.workspace?.workspace_id ?? ""}`);

function isCurrent(scope: string, generation: number) {
  return generation === scopeGeneration && scope === authScope.value;
}

const typeLabel = (request: ProductApprovalRequest) => ({
  continuation_consent: "后台续接许可申请",
  strategy_version: "策略版本执行申请",
  ml_strategy_version: "模型策略执行申请",
}[request.request_type]);
const statusLabel = (status: ProductApprovalRequest["status"]) => ({
  pending: "待审批",
  decision_recorded: "决定已记录，待核对",
  outcome_unknown: "结果未确认，需核对",
  needs_attention: "领域动作未完成，需人工处理",
  approved: "已批准",
  rejected: "已拒绝",
}[status]);
const OBSERVED_STATE_LABELS: Record<NonNullable<ProductApprovalRequest["observed_state"]>, string> = {
  confirmed: "已找到匹配的领域事实",
  missing: "未找到领域事实",
  draft: "领域事实仍为草稿",
  mismatch: "领域事实与申请摘要不匹配",
  unavailable: "当前无法读取领域事实",
};
const observedStateLabel = (state: ProductApprovalRequest["observed_state"]) =>
  state ? OBSERVED_STATE_LABELS[state] : "未返回现场观察";
const MATERIALIZATION_ERROR_LABELS: Record<string, string> = {
  domain_validation_failed: "审批条件校验未通过",
  domain_conflict: "目标已有冲突事实",
  domain_scope_unavailable: "精确资源或授权范围不存在",
  domain_request_rejected: "领域请求被明确拒绝",
  domain_unavailable: "领域服务不可用",
  domain_fact_missing: "未找到目标领域事实",
  domain_fact_draft: "领域事实仍为草稿",
  domain_fact_mismatch: "事实与申请摘要不一致",
};
const materializationErrorLabel = (code: string | null | undefined) =>
  MATERIALIZATION_ERROR_LABELS[code ?? ""] ?? "需要人工处理";

async function refresh() {
  const generation = ++loadGeneration;
  const scopeVersion = scopeGeneration;
  const scope = authScope.value;
  if (!auth.user?.subject || !auth.user.workspace?.workspace_id) {
    loading.value = false;
    error.value = "";
    pendingRequests.value = [];
    unresolvedRequests.value = [];
    pendingTotal.value = 0;
    unresolvedTotal.value = 0;
    attentionTotal.value = 0;
    pendingCount.value = 0;
    emit("pendingCount", 0);
    return;
  }
  const expectedOwner = auth.user.subject;
  const expectedWorkspaceId = auth.user.workspace.workspace_id;
  loading.value = true;
  error.value = "";
  try {
    const [pendingResult, unresolvedResult] = await Promise.all([
      listProductApprovalRequests({ status: "pending", limit: PAGE_SIZE, offset: (pendingPage.value - 1) * PAGE_SIZE }),
      listProductApprovalRequests({ status: "unresolved", limit: PAGE_SIZE, offset: (unresolvedPage.value - 1) * PAGE_SIZE }),
    ]);
    if (generation !== loadGeneration || !isCurrent(scope, scopeVersion)) return;
    if ((pendingResult.requests ?? []).some(request => request.status !== "pending")
        || (unresolvedResult.requests ?? []).some(request =>
          !["decision_recorded", "outcome_unknown", "needs_attention"].includes(request.status))) {
      throw new Error("审批列表返回了与待审批或待核对筛选不符的状态；已拒绝显示。");
    }
    if ([...(pendingResult.requests ?? []), ...(unresolvedResult.requests ?? [])].some(request =>
      request.owner_principal !== expectedOwner || request.workspace_id !== expectedWorkspaceId)) {
      throw new Error("审批列表返回了其他身份或工作区的记录；已拒绝显示，请刷新并人工核对。");
    }
    pendingRequests.value = pendingResult.requests ?? [];
    unresolvedRequests.value = unresolvedResult.requests ?? [];
    pendingTotal.value = pendingResult.total ?? 0;
    unresolvedTotal.value = unresolvedResult.total ?? 0;
    attentionTotal.value = unresolvedResult.attention_count ?? unresolvedResult.total ?? 0;
    pendingCount.value = pendingResult.pending_count ?? 0;
    emit("pendingCount", pendingCount.value);
  } catch (cause) {
    if (generation === loadGeneration && isCurrent(scope, scopeVersion)) error.value = cause instanceof Error ? cause.message : "读取业务审批申请失败";
  } finally {
    if (generation === loadGeneration && isCurrent(scope, scopeVersion)) loading.value = false;
  }
}

watch(
  authScope,
  () => {
    scopeGeneration += 1;
    loadGeneration += 1;
    pendingRequests.value = [];
    unresolvedRequests.value = [];
    pendingTotal.value = 0;
    unresolvedTotal.value = 0;
    attentionTotal.value = 0;
    pendingCount.value = 0;
    loading.value = false;
    busyId.value = "";
    error.value = "";
    pendingPage.value = 1;
    unresolvedPage.value = 1;
    emit("pendingCount", 0);
    void refresh();
  },
  { flush: "sync" },
);

async function decide(request: ProductApprovalRequest, decision: "approved" | "rejected") {
  if (request.status !== "pending" || busyId.value) return;
  const promptRequest = ++decisionPromptGeneration;
  const scopeVersion = scopeGeneration;
  const expectedScope = authScope.value;
  const requestIdentity = `${request.request_id}\u0000${request.request_key}\u0000${request.content_sha256}`;
  const isPendingHere = () => isCurrent(expectedScope, scopeVersion)
    && request.owner_principal === auth.user?.subject
    && request.workspace_id === auth.user?.workspace?.workspace_id
    && pendingRequests.value.some(item => `${item.request_id}\u0000${item.request_key}\u0000${item.content_sha256}` === requestIdentity
      && item.status === "pending");
  if (!isPendingHere()) return;
  let rationale: string;
  try {
    const approvalEffect = request.request_type === "continuation_consent"
      ? "批准只记录此续接许可，不会创建 Job；匹配的任务完成事件可能按申请指定的执行档案和预算自动启动一次后台续接。"
      : request.request_type === "strategy_version"
        ? "批准只记录该不可变策略版本的领域审批事实，不会自动开始回测；用户仍需另行开始。"
        : "批准只记录该不可变模型策略版本的领域审批事实，不会自动开始训练；用户仍需另行开始。";
    const response = await ElMessageBox.prompt(
      decision === "approved" ? `说明批准理由。${approvalEffect}` : "说明拒绝理由。",
      decision === "approved" ? "批准申请" : "拒绝申请",
      {
        confirmButtonText: decision === "approved" ? "确认批准" : "确认拒绝",
        cancelButtonText: "返回",
        inputPlaceholder: "审批理由",
        inputValidator: value => Boolean(value?.trim()) || "请填写审批理由",
        inputErrorMessage: "请填写审批理由",
      },
    );
    rationale = String(response.value ?? "").trim();
    if (!rationale) return;
  } catch {
    return;
  }
  if (promptRequest !== decisionPromptGeneration || !isPendingHere()) return;

  const action = ++actionGeneration;
  busyId.value = request.request_id;
  error.value = "";
  try {
    const scope = {
      ownerPrincipal: auth.user?.subject ?? "",
      workspaceId: auth.user?.workspace?.workspace_id ?? "",
    };
    const outcome = await decideProductApprovalRequestOnce(scope, request.request_id, decision, rationale);
    if (action !== actionGeneration || !isCurrent(expectedScope, scopeVersion)) return;
    if (outcome.request.request_id !== request.request_id
        || outcome.request.request_key !== request.request_key
        || outcome.request.content_sha256 !== request.content_sha256
        || outcome.request.owner_principal !== scope.ownerPrincipal
        || outcome.request.workspace_id !== scope.workspaceId) {
      throw new Error("决定回包与原申请身份、工作区或内容摘要不一致；请人工核对。先前提交结果未自动重发。");
    }
    window.dispatchEvent(new Event("byq:approvals-changed"));
    if (outcome.request.status === "approved" || outcome.request.status === "rejected") {
      const approvedMessage = request.request_type === "continuation_consent"
        ? "续接许可已批准；批准本身不会创建 Job，匹配的任务完成事件可能按申请指定的档案和预算自动启动一次续接。"
        : request.request_type === "strategy_version"
          ? "策略版本审批已记录；回测仍需由用户另行启动。"
          : "模型策略版本审批已记录；训练仍需由用户另行启动。";
      ElMessage.success(outcome.request.status === "approved" ? approvedMessage : "拒绝结果已确认。");
    } else {
      ElMessage.warning("决定结果尚未终结；已读取原申请状态，不会重发决定。请刷新核对。");
    }
    await refresh();
  } catch (cause) {
    if (action !== actionGeneration || !isCurrent(expectedScope, scopeVersion)) return;
    const message = cause instanceof Error ? cause.message : "审批结果尚未确认；请刷新核对。";
    try { await refresh(); } catch { /* retain the original decision error */ }
    if (action === actionGeneration && isCurrent(expectedScope, scopeVersion)) error.value = message;
  } finally {
    if (action === actionGeneration && isCurrent(expectedScope, scopeVersion)) busyId.value = "";
  }
}

async function reconcile(requestId: string) {
  if (busyId.value) return;
  const listed = unresolvedRequests.value.find(item => item.request_id === requestId);
  if (!listed || !["decision_recorded", "outcome_unknown", "needs_attention"].includes(listed.status)) {
    error.value = "此申请当前不属于待核对状态；请刷新列表。";
    return;
  }
  const scopeVersion = scopeGeneration;
  const scope = authScope.value;
  const action = ++actionGeneration;
  const listedIdentity = `${listed.request_id}\u0000${listed.request_key}\u0000${listed.content_sha256}`;
  if (listed.owner_principal !== auth.user?.subject || listed.workspace_id !== auth.user?.workspace?.workspace_id) return;
  busyId.value = requestId;
  error.value = "";
  try {
    const result = await reconcileProductApprovalRequest(requestId);
    if (action !== actionGeneration || !isCurrent(scope, scopeVersion)) return;
    if (result.schema_version !== "byq-product-approval-request.v1") {
      throw new Error("核对回包版本不匹配；请人工核对。");
    }
    const request = result.request;
    if (request.owner_principal !== auth.user?.subject
        || request.workspace_id !== auth.user?.workspace?.workspace_id
        || request.request_id !== requestId
        || request.request_type !== listed.request_type
        || request.task_id !== listed.task_id
        || `${request.request_id}\u0000${request.request_key}\u0000${request.content_sha256}` !== listedIdentity) {
      throw new Error("精确申请读取的身份或工作区不一致；请人工核对。");
    }
    window.dispatchEvent(new Event("byq:approvals-changed"));
    if (request.status === "approved" || request.status === "rejected") {
      ElMessage.success(request.status === "approved"
        ? request.request_type === "continuation_consent"
          ? `已核对续接许可${request.observed_state ? `：${observedStateLabel(request.observed_state)}` : ""}；批准本身不会创建 Job，匹配的任务完成事件可能按许可档案和预算自动启动一次续接。`
          : `已核对领域审批事实${request.observed_state ? `：${observedStateLabel(request.observed_state)}` : ""}；回测或训练仍需由用户另行启动。`
        : `已核对领域审批事实：申请已拒绝${request.observed_state ? `（${observedStateLabel(request.observed_state)}）` : ""}。`);
    } else if (request.status === "needs_attention") {
      ElMessage.warning(`原领域动作未完成，需要人工处理：${materializationErrorLabel(request.materialization_error_code)}。不会自动重发。`);
    } else {
      ElMessage.warning(`领域事实尚未确认${request.observed_state ? `：${observedStateLabel(request.observed_state)}` : ""}；系统不会重发决定，请稍后再核对。`);
    }
    await refresh();
  } catch (cause) {
    if (action === actionGeneration && isCurrent(scope, scopeVersion)) {
      error.value = cause instanceof Error ? cause.message : "对账结果未知；不会自动重复操作，请刷新后核对。";
    }
  } finally {
    if (action === actionGeneration && isCurrent(scope, scopeVersion)) busyId.value = "";
  }
}

async function changePendingPage(value: number) {
  pendingPage.value = value;
  await refresh();
}

async function changeUnresolvedPage(value: number) {
  unresolvedPage.value = value;
  await refresh();
}

function refreshWhenVisible() {
  if (document.visibilityState === "visible") void refresh();
}

onMounted(() => {
  void refresh();
  window.addEventListener("focus", refreshWhenVisible);
  window.addEventListener("byq:approvals-changed", refreshWhenVisible);
  document.addEventListener("visibilitychange", refreshWhenVisible);
});
onUnmounted(() => {
  scopeGeneration += 1;
  decisionPromptGeneration += 1;
  actionGeneration += 1;
  loadGeneration += 1;
  window.removeEventListener("focus", refreshWhenVisible);
  window.removeEventListener("byq:approvals-changed", refreshWhenVisible);
  document.removeEventListener("visibilitychange", refreshWhenVisible);
});
</script>

<template>
  <section class="business-approval-list" aria-label="业务审批申请">
    <p v-if="error" class="page-error" role="alert">{{ error }}</p>
    <el-empty v-if="!pendingRequests.length && !loading" description="暂无待审批的业务申请" />
    <el-card v-for="request in pendingRequests" :key="request.request_id" shadow="never" class="request-card" v-loading="busyId === request.request_id">
      <div class="request-heading">
        <strong>{{ typeLabel(request) }}</strong>
        <el-tag :type="request.status === 'pending' ? 'warning' : 'info'">{{ statusLabel(request.status) }}</el-tag>
      </div>
      <dl>
        <dt>Request ID</dt><dd>{{ request.request_id }}</dd>
        <dt>Task ID</dt><dd>{{ request.task_id }}</dd>
        <dt>单一资源 Artifact</dt><dd>{{ request.resource_artifact_id ?? "无单一资源 Artifact" }}</dd>
        <dt>内容 SHA-256</dt><dd>{{ request.content_sha256 }}</dd>
        <template v-if="request.request_type === 'continuation_consent'">
          <dt>原研究对话</dt><dd>{{ request.conversation_id }}</dd>
          <dt>确认资产绑定</dt>
          <dd><ul><li v-for="item in request.confirmed_artifacts" :key="item.artifact_id">{{ item.kind }} · {{ item.artifact_id }} · SHA-256 {{ item.content_sha256 }}</li></ul></dd>
          <dt>执行档案</dt><dd>{{ request.execution_profile_id }}</dd>
        </template>
        <template v-else-if="request.request_type === 'strategy_version'">
          <dt>策略版本</dt><dd>{{ request.strategy_version_artifact_id }}</dd>
        </template>
        <template v-else>
          <dt>模型策略版本</dt><dd>{{ request.ml_strategy_artifact_id }}</dd>
        </template>
      </dl>
      <p class="request-scope">申请人 {{ request.owner_principal }} · 工作区 {{ request.workspace_id }}</p>
      <div class="request-actions">
        <template v-if="request.status === 'pending'">
          <el-button type="primary" :disabled="!!busyId" @click="decide(request, 'approved')">批准</el-button>
          <el-button type="danger" plain :disabled="!!busyId" @click="decide(request, 'rejected')">拒绝</el-button>
        </template>
        <span v-else>仅可在待核对列表读取当前状态。</span>
      </div>
    </el-card>
    <EntityPagination
      :page="pendingPage"
      :page-size="PAGE_SIZE"
      :total="pendingTotal"
      label="待审批业务申请分页"
      @update:page="changePendingPage"
    />
    <div class="attention-heading">
      <h3>待核对结果</h3>
      <span>{{ attentionTotal }} 项</span>
    </div>
    <el-alert title="核对会读取此申请对应的已有领域事实并更新核对状态；不会重发决定或执行训练、回测、续接。待核对记录不能再次批准或拒绝。" type="warning" :closable="false" />
    <el-empty v-if="!unresolvedRequests.length && !loading" description="暂无待核对结果" />
    <el-card v-for="request in unresolvedRequests" :key="request.request_id" shadow="never" class="request-card" v-loading="busyId === request.request_id">
      <div class="request-heading">
        <strong>{{ typeLabel(request) }}</strong>
        <el-tag type="info">{{ statusLabel(request.status) }}</el-tag>
      </div>
      <dl>
        <dt>Request ID</dt><dd>{{ request.request_id }}</dd>
        <dt>Task ID</dt><dd>{{ request.task_id }}</dd>
        <dt>单一资源 Artifact</dt><dd>{{ request.resource_artifact_id ?? "无单一资源 Artifact" }}</dd>
        <dt>内容 SHA-256</dt><dd>{{ request.content_sha256 }}</dd>
        <template v-if="request.decision">
          <dt>已记录的人类决定</dt><dd>{{ request.decision === 'approved' ? '已批准' : '已拒绝' }}</dd>
        </template>
        <template v-if="request.status === 'needs_attention' && request.materialization_error_code">
          <dt>处理结果</dt><dd>{{ materializationErrorLabel(request.materialization_error_code) }}</dd>
        </template>
        <template v-if="request.observed_state">
          <dt>现场观察</dt><dd>{{ observedStateLabel(request.observed_state) }}</dd>
        </template>
        <template v-if="request.request_type === 'continuation_consent'">
          <dt>原研究对话</dt><dd>{{ request.conversation_id }}</dd>
          <dt>执行档案</dt><dd>{{ request.execution_profile_id }}</dd>
          <dt>确认资产绑定</dt>
          <dd><ul><li v-for="item in request.confirmed_artifacts" :key="item.artifact_id">{{ item.kind }} · {{ item.artifact_id }} · SHA-256 {{ item.content_sha256 }}</li></ul></dd>
        </template>
      </dl>
      <p class="request-scope">申请人 {{ request.owner_principal }} · 工作区 {{ request.workspace_id }}</p>
      <el-button :disabled="!!busyId" @click="reconcile(request.request_id)">核对现有领域事实</el-button>
    </el-card>
    <EntityPagination
      :page="unresolvedPage"
      :page-size="PAGE_SIZE"
      :total="unresolvedTotal"
      label="待核对业务申请分页"
      @update:page="changeUnresolvedPage"
    />
    <div class="list-footer">
      <el-button :loading="loading" @click="refresh">刷新申请</el-button>
    </div>
  </section>
</template>

<style scoped>
.business-approval-list { display: grid; gap: 12px; }
.request-card { border-radius: var(--byq-radius-md); }
.request-heading { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
.request-card dl { display: grid; grid-template-columns: minmax(92px, auto) 1fr; gap: 6px 12px; margin: 14px 0 8px; }
.request-card dt { color: var(--byq-text-muted); }
.request-card dd { margin: 0; overflow-wrap: anywhere; }
.request-card dd ul { margin: 0; padding-left: 18px; }
.request-scope, .request-reconcile { color: var(--byq-text-muted); overflow-wrap: anywhere; }
.request-actions { display: flex; gap: 8px; }
.list-footer { display: grid; gap: 12px; }
.attention-heading { display: flex; align-items: baseline; gap: 10px; }
.attention-heading h3 { margin: 0; }
</style>
