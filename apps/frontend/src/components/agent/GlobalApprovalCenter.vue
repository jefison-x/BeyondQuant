<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Bell } from "@element-plus/icons-vue";
import { decideApproval, getResearchEntity, listApprovals, listArtifacts, listTasks } from "@/api/research";
import { useAuthStore } from "@/stores/auth";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";
import ProductApprovalRequestPanel from "./ProductApprovalRequestPanel.vue";
import ContinuationPermissionPanel from "@/components/ContinuationPermissionPanel.vue";
import EntityPagination from "@/components/ui/EntityPagination.vue";

const open = ref(false);
const activeTab = ref("agent");
const approvals = ref<Array<Record<string, unknown>>>([]);
const pendingTotal = ref(0);
const productPendingTotal = ref(0);
const error = ref("");
const busyId = ref("");
const loading = ref(false);
const page = ref(1);
const PAGE_SIZE = 20;
const tasks = ref<Array<Record<string, unknown>>>([]);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const continuationTask = ref("");
const taskListCapped = ref(false);
const candidatesLoading = ref(false);
const candidatesError = ref("");
const exactTaskId = ref("");
const exactTaskLoading = ref(false);
const exactTaskError = ref("");
const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const authScope = computed(() => `${auth.user?.subject ?? ""}\u0000${auth.user?.workspace?.workspace_id ?? ""}`);
let scopeGeneration = 0;
let candidateLoadGeneration = 0;
let exactTaskGeneration = 0;
let approvalLoadGeneration = 0;
let decisionGeneration = 0;
let refreshTimer: number | null = null;
const manualApprovals = computed(() => approvals.value.filter((item) => item.status === "pending"));
const pending = computed(() => pendingTotal.value + productPendingTotal.value);

watch(authScope, () => {
  scopeGeneration += 1;
  candidateLoadGeneration += 1;
  exactTaskGeneration += 1;
  approvalLoadGeneration += 1;
  decisionGeneration += 1;
  approvals.value = [];
  pendingTotal.value = 0;
  productPendingTotal.value = 0;
  page.value = 1;
  loading.value = false;
  error.value = "";
  busyId.value = "";
  tasks.value = [];
  artifacts.value = [];
  continuationTask.value = "";
  taskListCapped.value = false;
  exactTaskId.value = "";
  candidatesLoading.value = false;
  candidatesError.value = "";
  exactTaskLoading.value = false;
  exactTaskError.value = "";
  void refresh();
}, { flush: "sync" });

async function refresh() {
  const request = ++approvalLoadGeneration;
  const scopeVersion = scopeGeneration;
  const scope = authScope.value;
  const requestedPage = page.value;
  if (!auth.user?.subject || !auth.user.workspace?.workspace_id) {
    approvals.value = [];
    pendingTotal.value = 0;
    loading.value = false;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const response = await listApprovals({
      status: "pending", limit: PAGE_SIZE, offset: (requestedPage - 1) * PAGE_SIZE,
    });
    if (request !== approvalLoadGeneration || scopeVersion !== scopeGeneration
        || scope !== authScope.value || requestedPage !== page.value) return;
    approvals.value = response.approvals ?? [];
    pendingTotal.value = response.pending_count ?? response.total ?? approvals.value.length;
  } catch (exc) {
    if (request === approvalLoadGeneration && scopeVersion === scopeGeneration && scope === authScope.value) {
      error.value = exc instanceof Error ? exc.message : "读取 Agent 审批失败";
    }
  } finally {
    if (request === approvalLoadGeneration && scopeVersion === scopeGeneration && scope === authScope.value) {
      loading.value = false;
    }
  }
}

async function decide(item: Record<string, unknown>, decision: "approved" | "rejected") {
  const approvalId = String(item.approval_id ?? "");
  const scope = authScope.value;
  const scopeVersion = scopeGeneration;
  const routeAtStart = route.fullPath;
  if (busyId.value || !approvalId || !auth.user?.subject || !auth.user.workspace?.workspace_id
      || !approvals.value.some(row => row.approval_id === approvalId && row.status === "pending")) return;
  const request = ++decisionGeneration;
  const isCurrentDecision = () => request === decisionGeneration && scopeVersion === scopeGeneration
    && scope === authScope.value && routeAtStart === route.fullPath;
  busyId.value = approvalId;
  error.value = "";
  try {
    const result = await decideApproval(approvalId, decision, "BYQ Product 人工审批");
    if (!isCurrentDecision()) return;
    page.value = 1;
    await refresh();
    if (!isCurrentDecision()) return;
    open.value = false;
    window.dispatchEvent(new Event("byq:approvals-changed"));
    const conversationId = String(result.approval.conversation_id ?? "");
    const continuationStatus = String(result.approval.continuation_status ?? "");
    if (["outcome_unknown", "needs_attention"].includes(continuationStatus)) {
      ElMessage.warning("审批决定已保存，续接结果尚未确认；不会自动重发，请检查原任务状态。");
    } else {
      ElMessage.success(decision === "approved" ? "已批准，正在返回原会话核对后续动作" : "已拒绝，正在返回原会话");
    }
    if (conversationId) {
      await router.push({
        path: "/agent",
        query: {
          session: conversationId,
          ...(continuationStatus === "submitted" ? {} : { approval: approvalId }),
        },
      });
    }
  } catch (exc) {
    if (isCurrentDecision()) {
      error.value = exc instanceof Error ? exc.message : "审批失败";
    }
  } finally {
    if (isCurrentDecision()) busyId.value = "";
  }
}

watch(() => route.fullPath, () => {
  decisionGeneration += 1;
  busyId.value = "";
});

function refreshWhenVisible() {
  if (document.visibilityState === "visible") void refresh().catch(() => undefined);
}

async function loadContinuationCandidates() {
  if (candidatesLoading.value) return;
  const generation = ++candidateLoadGeneration;
  const scopeVersion = scopeGeneration;
  const scope = authScope.value;
  candidatesLoading.value = true;
  candidatesError.value = "";
  try {
    const [taskPage, artifactPage] = await Promise.all([listTasks(), listArtifacts()]);
    if (scopeVersion !== scopeGeneration || scope !== authScope.value || generation !== candidateLoadGeneration) return;
    const owner = auth.user?.subject ?? "";
    const workspaceId = auth.user?.workspace?.workspace_id ?? "";
    taskListCapped.value = (taskPage.tasks ?? []).length >= 200;
    const scopedTasks = (taskPage.tasks ?? []).filter(item => item.owner_principal === owner && item.workspace_id === workspaceId);
    const scopedArtifacts = (artifactPage.artifacts ?? []).filter(item => item.owner_principal === owner && item.workspace_id === workspaceId);
    tasks.value = mergeByIdentity(tasks.value, scopedTasks, "task_id");
    artifacts.value = mergeByIdentity(artifacts.value, scopedArtifacts, "artifact_id");
  } catch (exc) {
    if (scopeVersion === scopeGeneration && scope === authScope.value && generation === candidateLoadGeneration) {
      candidatesError.value = exc instanceof Error ? exc.message : "读取续接许可候选失败";
    }
  } finally {
    if (scopeVersion === scopeGeneration && scope === authScope.value && generation === candidateLoadGeneration) {
      candidatesLoading.value = false;
    }
  }
}

function mergeByIdentity(
  current: Array<Record<string, unknown>>,
  incoming: Array<Record<string, unknown>>,
  field: "task_id" | "artifact_id",
) {
  const byId = new Map<string, Record<string, unknown>>();
  for (const item of [...current, ...incoming]) {
    const id = typeof item[field] === "string" ? item[field] as string : "";
    if (id) byId.set(id, item);
  }
  return [...byId.values()];
}

async function loadExactContinuationTask(taskId = exactTaskId.value) {
  const id = taskId.trim();
  const owner = auth.user?.subject ?? "";
  const workspaceId = auth.user?.workspace?.workspace_id ?? "";
  if (!id || !owner || !workspaceId) {
    exactTaskError.value = "请先登录并输入完整 Task ID。";
    return;
  }
  const generation = ++exactTaskGeneration;
  const scopeVersion = scopeGeneration;
  const scope = authScope.value;
  const selectedTaskAtStart = continuationTask.value;
  exactTaskLoading.value = true;
  exactTaskError.value = "";
  try {
    const task = await getResearchEntity("tasks", id);
    if (scopeVersion !== scopeGeneration || scope !== authScope.value || generation !== exactTaskGeneration
        || exactTaskId.value.trim() !== id || continuationTask.value !== selectedTaskAtStart) return;
    if (task.task_id !== id || task.owner_principal !== owner || task.workspace_id !== workspaceId) {
      throw new Error("精确 Task 响应与当前用户、工作区或任务 ID 不一致。");
    }
    if (typeof task.conversation_id !== "string" || !task.conversation_id) {
      throw new Error("该任务没有可续接的原研究对话。");
    }
    tasks.value = mergeByIdentity(tasks.value, [task], "task_id");
    continuationTask.value = id;
    exactTaskId.value = id;
  } catch (exc) {
    if (scopeVersion === scopeGeneration && scope === authScope.value && generation === exactTaskGeneration) {
      exactTaskError.value = exc instanceof Error ? exc.message : "精确读取 Task 失败。";
    }
  } finally {
    if (scopeVersion === scopeGeneration && scope === authScope.value && generation === exactTaskGeneration) {
      exactTaskLoading.value = false;
    }
  }
}

async function changePage(value: number) {
  page.value = value;
  await refresh();
}

function openCenter() {
  page.value = 1;
  void refresh().catch(() => undefined);
}

function openForRequest(event: Event) {
  const detail = (event as CustomEvent<{ tab?: string; taskId?: string }>).detail;
  activeTab.value = detail?.tab === "continuation" ? "continuation" : "business";
  if (detail?.taskId) {
    continuationTask.value = "";
    exactTaskId.value = detail.taskId;
    void loadExactContinuationTask(detail.taskId);
  }
  open.value = true;
  window.dispatchEvent(new Event("byq:approvals-changed"));
  if (activeTab.value === "continuation") void loadContinuationCandidates();
}

function openCenterFromButton() {
  open.value = true;
  window.dispatchEvent(new Event("byq:approvals-changed"));
}

function handleTabChange(value: string | number) {
  if (value === "continuation") void loadContinuationCandidates();
}

onMounted(() => {
  void refresh().catch(() => undefined);
  refreshTimer = window.setInterval(refreshWhenVisible, 15_000);
  window.addEventListener("focus", refreshWhenVisible);
  window.addEventListener("byq:approvals-changed", refreshWhenVisible);
  window.addEventListener("byq:approval-center-open", openForRequest);
  document.addEventListener("visibilitychange", refreshWhenVisible);
});

onUnmounted(() => {
  scopeGeneration += 1;
  candidateLoadGeneration += 1;
  exactTaskGeneration += 1;
  approvalLoadGeneration += 1;
  decisionGeneration += 1;
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
  window.removeEventListener("focus", refreshWhenVisible);
  window.removeEventListener("byq:approvals-changed", refreshWhenVisible);
  window.removeEventListener("byq:approval-center-open", openForRequest);
  document.removeEventListener("visibilitychange", refreshWhenVisible);
});
</script>

<template>
  <el-tooltip content="审批中心" placement="bottom">
    <button
      class="approval-trigger"
      type="button"
      :aria-label="pending ? `审批中心，${pending} 项待审批` : '审批中心，无待审批'"
      @click="openCenterFromButton"
    >
      <el-badge :value="pending" :hidden="pending === 0" :max="99" type="danger">
        <el-icon><Bell /></el-icon>
      </el-badge>
    </button>
  </el-tooltip>
  <el-drawer v-model="open" title="审批中心" size="min(94vw, 720px)" @open="openCenter">
    <p v-if="error" class="page-error">{{ error }}</p>
    <el-tabs v-model="activeTab" @tab-change="handleTabChange">
      <el-tab-pane label="Agent 审批" name="agent">
        <p>此处保留原 AgentApproval 流程。</p>
        <ApprovalManagementPanel :approvals="manualApprovals" :total="pendingTotal" :busy-id="busyId" @decide="decide" />
        <EntityPagination
          :page="page"
          :page-size="PAGE_SIZE"
          :total="pendingTotal"
          label="Agent 审批分页"
          @update:page="changePage"
        />
      </el-tab-pane>
      <el-tab-pane label="BYQ 业务审批" name="business">
        <ProductApprovalRequestPanel v-show="activeTab === 'business'" @pending-count="productPendingTotal = $event" />
      </el-tab-pane>
      <el-tab-pane label="续接许可" name="continuation">
        <p>申请只进入人工审批；批准本身不会创建 Job。匹配的任务完成事件可能按申请指定的执行档案和资源预算自动启动一次后台续接。</p>
        <p v-if="candidatesError" class="page-error" role="alert">{{ candidatesError }}</p>
        <p v-if="exactTaskError" class="page-error" role="alert">{{ exactTaskError }}</p>
        <p v-if="taskListCapped" role="note">任务候选列表最多返回 200 项；若目标任务未列出，可用完整 Task ID 精确读取。</p>
        <div class="continuation-picker">
          <el-select
            v-model="continuationTask"
            filterable
            clearable
            :loading="candidatesLoading"
            placeholder="选择关联原研究对话的任务"
            style="width: 100%"
            @focus="loadContinuationCandidates"
          >
            <el-option
              v-for="task in tasks.filter(item => item.conversation_id)"
              :key="String(task.task_id)"
              :value="String(task.task_id)"
              :label="`${String(task.title ?? '研究任务')} · ${String(task.task_id)}`"
            />
          </el-select>
          <div class="exact-task-lookup">
            <el-input v-model="exactTaskId" aria-label="精确 Task ID" placeholder="完整 Task ID" />
            <el-button :loading="exactTaskLoading" @click="loadExactContinuationTask()">精确读取 Task</el-button>
          </div>
        </div>
        <ContinuationPermissionPanel
          v-if="continuationTask"
          :key="`${authScope}:${continuationTask}`"
          :task-id="continuationTask"
          :artifacts="artifacts"
        />
        <el-empty v-else-if="!candidatesLoading && !exactTaskLoading && !tasks.some(item => item.conversation_id)" description="没有关联原研究对话的任务" />
      </el-tab-pane>
    </el-tabs>
  </el-drawer>
</template>

<style scoped>
.approval-trigger {
  align-items: center;
  background: var(--byq-surface);
  border: 1px solid var(--byq-border);
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text-muted);
  cursor: pointer;
  display: inline-flex;
  height: 34px;
  justify-content: center;
  width: 34px;
}

.approval-trigger:hover {
  background: var(--byq-brand-soft);
}

.approval-trigger .el-icon {
  font-size: 18px;
}
.continuation-picker { margin: 14px 0; }
.exact-task-lookup { display: flex; gap: 8px; margin-top: 10px; }
</style>
