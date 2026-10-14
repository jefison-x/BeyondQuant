<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { getApproval, getContinuationPermission, getResearchEntity, listApprovals, listArtifacts, listProductApprovalRequests, listTasks, type ProductApprovalRequest } from "@/api/research";
import { getStrategyVersionApproval } from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";
import { researchProgress } from "@/researchProgress";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import EntityPagination from "@/components/ui/EntityPagination.vue";
import TaskHandoffPanel from "@/components/TaskHandoffPanel.vue";
import { useFilteredPagination } from "@/composables/useFilteredPagination";

const tab = ref<"tasks" | "research" | "approval" | "assets" | "inbox">("tasks");
const entityType = ref<"tasks" | "experiments" | "artifacts">("artifacts");
const entityId = ref("");
const approvalId = ref("");
const result = ref<unknown>(null);
const resultSource = ref("");
const error = ref("");
const busy = ref(false);
const artifacts = ref<Array<Record<string, unknown>>>([]);
const approvals = ref<Array<Record<string, unknown>>>([]);
const productRequests = ref<ProductApprovalRequest[]>([]);
const tasks = ref<Array<Record<string, unknown>>>([]);
const handoffTask = ref("");
const approvalSource = ref<"agent" | "strategy" | "continuation">("agent");
const agentHistoryStatus = ref<"approved" | "rejected">("approved");
const productHistoryStatus = ref<"approved" | "rejected">("approved");
const agentHistoryPage = ref(1);
const productHistoryPage = ref(1);
const agentHistoryTotal = ref(0);
const productHistoryTotal = ref(0);
const historyBusy = ref(false);
const HISTORY_PAGE_SIZE = 20;
const auth = useAuthStore();
const authScope = computed(() => `${auth.user?.subject ?? ""}\u0000${auth.user?.workspace?.workspace_id ?? ""}`);
let scopeGeneration = 0;
let taskGeneration = 0;
let artifactGeneration = 0;
let inboxGeneration = 0;
let agentHistoryGeneration = 0;
let productHistoryGeneration = 0;
let entityGeneration = 0;
let approvalGeneration = 0;
const taskPages = useFilteredPagination(computed(() => tasks.value), (row) => `${row.title ?? ""} ${row.objective ?? ""} ${row.status ?? ""}`, 20);
const artifactPages = useFilteredPagination(computed(() => artifacts.value), (row) => `${row.kind ?? ""} ${row.artifact_id ?? ""} ${row.status ?? ""}`, 20);

function requestIsCurrent(scope: string, epoch: number) {
  return scope === authScope.value && epoch === scopeGeneration;
}

async function loadTasks() {
  const request = ++taskGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const owner = auth.user?.subject ?? "";
  const workspaceId = auth.user?.workspace?.workspace_id ?? "";
  busy.value = true;
  error.value = "";
  try {
    const response = await listTasks();
    if (request !== taskGeneration || !requestIsCurrent(scope, epoch)) return;
    const rows = response.tasks ?? [];
    if (rows.some(item => item.owner_principal !== owner || item.workspace_id !== workspaceId)) {
      throw new Error("研究任务列表返回了其他身份或工作区的记录；已拒绝显示。");
    }
    tasks.value = rows;
  } catch (exc) {
    if (request === taskGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    if (request === taskGeneration && requestIsCurrent(scope, epoch)) busy.value = false;
  }
}

async function loadAssets() {
  const request = ++artifactGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const owner = auth.user?.subject ?? "";
  const workspaceId = auth.user?.workspace?.workspace_id ?? "";
  busy.value = true;
  error.value = "";
  try {
    const response = await listArtifacts();
    if (request !== artifactGeneration || !requestIsCurrent(scope, epoch)) return;
    const rows = response.artifacts ?? [];
    if (rows.some(item => item.owner_principal !== owner || item.workspace_id !== workspaceId)) {
      throw new Error("研究资产列表返回了其他身份或工作区的记录；已拒绝显示。");
    }
    artifacts.value = rows;
  } catch (exc) {
    if (request === artifactGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    if (request === artifactGeneration && requestIsCurrent(scope, epoch)) busy.value = false;
  }
}

async function loadInbox() {
  const request = ++inboxGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const agentStatus = agentHistoryStatus.value;
  const agentPage = agentHistoryPage.value;
  const productStatus = productHistoryStatus.value;
  const productPage = productHistoryPage.value;
  historyBusy.value = true;
  error.value = "";
  try {
    const [agent, product] = await Promise.all([
      listApprovals({ status: agentStatus, limit: HISTORY_PAGE_SIZE, offset: (agentPage - 1) * HISTORY_PAGE_SIZE }),
      listProductApprovalRequests({ status: productStatus, limit: HISTORY_PAGE_SIZE, offset: (productPage - 1) * HISTORY_PAGE_SIZE }),
    ]);
    if (request !== inboxGeneration || !requestIsCurrent(scope, epoch)
        || agentStatus !== agentHistoryStatus.value || agentPage !== agentHistoryPage.value
        || productStatus !== productHistoryStatus.value || productPage !== productHistoryPage.value) return;
    if ((agent.approvals ?? []).some(item => item.status !== agentStatus)
        || (product.requests ?? []).some(item => item.status !== productStatus)) {
      throw new Error("审批历史返回了与已决状态筛选不符的记录；未将待核对事项显示为历史结果。");
    }
    if ((product.requests ?? []).some(item => item.owner_principal !== auth.user?.subject
        || item.workspace_id !== auth.user?.workspace?.workspace_id)) {
      throw new Error("业务审批历史返回了其他身份或工作区的记录；已拒绝显示。");
    }
    approvals.value = agent.approvals ?? [];
    agentHistoryTotal.value = agent.total ?? 0;
    productRequests.value = product.requests ?? [];
    productHistoryTotal.value = product.total ?? 0;
  } catch (exc) {
    if (request === inboxGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    if (request === inboxGeneration && requestIsCurrent(scope, epoch)) historyBusy.value = false;
  }
}

async function loadAgentHistory() {
  const request = ++agentHistoryGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const status = agentHistoryStatus.value;
  const requestedPage = agentHistoryPage.value;
  historyBusy.value = true;
  error.value = "";
  try {
    const response = await listApprovals({ status, limit: HISTORY_PAGE_SIZE, offset: (requestedPage - 1) * HISTORY_PAGE_SIZE });
    if (request !== agentHistoryGeneration || !requestIsCurrent(scope, epoch)
        || status !== agentHistoryStatus.value || requestedPage !== agentHistoryPage.value) return;
    if ((response.approvals ?? []).some(item => item.status !== status)) {
      throw new Error("Agent 审批历史返回了与已决状态筛选不符的记录。");
    }
    approvals.value = response.approvals ?? [];
    agentHistoryTotal.value = response.total ?? 0;
  } catch (exc) {
    if (request === agentHistoryGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "读取 Agent 审批历史失败";
  } finally { if (request === agentHistoryGeneration && requestIsCurrent(scope, epoch)) historyBusy.value = false; }
}

async function loadProductHistory() {
  const request = ++productHistoryGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const status = productHistoryStatus.value;
  const requestedPage = productHistoryPage.value;
  historyBusy.value = true;
  error.value = "";
  try {
    const response = await listProductApprovalRequests({ status, limit: HISTORY_PAGE_SIZE, offset: (requestedPage - 1) * HISTORY_PAGE_SIZE });
    if (request !== productHistoryGeneration || !requestIsCurrent(scope, epoch)
        || status !== productHistoryStatus.value || requestedPage !== productHistoryPage.value) return;
    if ((response.requests ?? []).some(item => item.owner_principal !== auth.user?.subject
        || item.workspace_id !== auth.user?.workspace?.workspace_id)) {
      throw new Error("业务审批历史返回了其他身份或工作区的记录；已拒绝显示。");
    }
    if ((response.requests ?? []).some(item => item.status !== status)) {
      throw new Error("业务审批历史返回了与已决状态筛选不符的记录；未将待核对事项显示为历史结果。");
    }
    productRequests.value = response.requests ?? [];
    productHistoryTotal.value = response.total ?? 0;
  } catch (exc) {
    if (request === productHistoryGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "读取业务审批结果失败";
  } finally { if (request === productHistoryGeneration && requestIsCurrent(scope, epoch)) historyBusy.value = false; }
}

async function loadEntity() {
  const request = ++entityGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const requestedType = entityType.value;
  const requestedId = entityId.value;
  busy.value = true;
  error.value = "";
  resultSource.value = "";
  try {
    const response = await getResearchEntity(requestedType, requestedId);
    if (request !== entityGeneration || !requestIsCurrent(scope, epoch)
        || requestedType !== entityType.value || requestedId !== entityId.value) return;
    result.value = response;
  } catch (exc) {
    if (request === entityGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    if (request === entityGeneration && requestIsCurrent(scope, epoch)) busy.value = false;
  }
}

async function loadApproval() {
  if (!approvalId.value.trim()) {
    error.value = "请输入准确的审批、策略版本 Artifact 或 Task ID";
    return;
  }
  const request = ++approvalGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const requestedId = approvalId.value.trim();
  const source = approvalSource.value;
  busy.value = true;
  error.value = "";
  try {
    let response: unknown;
    let responseSource = "";
    if (source === "agent") {
      response = await getApproval(requestedId);
      responseSource = "AgentApproval 精确只读 Product API";
    } else if (source === "strategy") {
      response = await getStrategyVersionApproval(requestedId, auth.token);
      responseSource = "策略版本领域审批精确只读 Product API";
    } else {
      response = await getContinuationPermission(requestedId);
      responseSource = "任务续接许可精确只读 Product API";
    }
    if (request !== approvalGeneration || !requestIsCurrent(scope, epoch)
        || requestedId !== approvalId.value.trim() || source !== approvalSource.value) return;
    result.value = response;
    resultSource.value = responseSource;
  } catch (exc) {
    if (request === approvalGeneration && requestIsCurrent(scope, epoch)) error.value = exc instanceof Error ? exc.message : "加载失败";
  } finally {
    if (request === approvalGeneration && requestIsCurrent(scope, epoch)) busy.value = false;
  }
}

watch(authScope, () => {
  scopeGeneration += 1;
  taskGeneration += 1;
  artifactGeneration += 1;
  inboxGeneration += 1;
  agentHistoryGeneration += 1;
  productHistoryGeneration += 1;
  entityGeneration += 1;
  approvalGeneration += 1;
  tasks.value = [];
  artifacts.value = [];
  approvals.value = [];
  productRequests.value = [];
  agentHistoryPage.value = 1;
  productHistoryPage.value = 1;
  agentHistoryTotal.value = 0;
  productHistoryTotal.value = 0;
  entityId.value = "";
  approvalId.value = "";
  result.value = null;
  resultSource.value = "";
  handoffTask.value = "";
  busy.value = false;
  historyBusy.value = false;
  error.value = "";
  if (auth.user?.subject && auth.user.workspace?.workspace_id) {
    void Promise.allSettled([loadTasks(), loadAssets(), loadInbox()]);
  }
}, { flush: "sync" });

onUnmounted(() => {
  scopeGeneration += 1;
  taskGeneration += 1;
  artifactGeneration += 1;
  inboxGeneration += 1;
  agentHistoryGeneration += 1;
  productHistoryGeneration += 1;
  entityGeneration += 1;
  approvalGeneration += 1;
});

onMounted(async () => {
  await Promise.allSettled([loadTasks(), loadAssets(), loadInbox()]);
});

async function inspectTaskPermission(taskId: string) {
  approvalSource.value = "continuation";
  approvalId.value = taskId;
  tab.value = "approval";
  result.value = null;
  await loadApproval();
}

async function inspectStrategyApproval(artifactId: string) {
  approvalSource.value = "strategy";
  approvalId.value = artifactId;
  tab.value = "approval";
  result.value = null;
  await loadApproval();
}

async function changeAgentHistoryPage(page: number) {
  agentHistoryPage.value = page;
  await loadAgentHistory();
}

async function changeProductHistoryPage(page: number) {
  productHistoryPage.value = page;
  await loadProductHistory();
}

function handleInboxTabChange(value: string | number) {
  if (value === "agent-history") void loadAgentHistory();
  else if (value === "product-history") void loadProductHistory();
}
</script>

<template>
  <section class="research-page">
    <el-card shadow="never" class="top-band">
      <el-tabs v-model="tab">
        <el-tab-pane label="研究任务" name="tasks" lazy>
          <ListFilterPagination v-model:query="taskPages.query.value" v-model:page="taskPages.page.value" :page-size="taskPages.pageSize.value" :total="taskPages.total.value" placeholder="筛选任务名称、目标或状态" label="研究任务分页">
          <el-table :data="taskPages.pageItems.value" v-loading="busy" empty-text="暂无研究任务">
            <el-table-column prop="title" label="任务名称" min-width="180" />
            <el-table-column prop="objective" label="研究目标" min-width="300" show-overflow-tooltip />
            <el-table-column label="任务记录" width="120"><template #default="{ row }">{{ row.status === "running" ? "未完成" : row.status }}</template></el-table-column>
            <el-table-column label="研究阶段与下一步" min-width="280">
              <template #default="{ row }">
                <div>{{ researchProgress(row.progress).stage }}</div>
                <div>下一步：{{ researchProgress(row.progress).next }}</div>
                <div v-if="researchProgress(row.progress).blocker">阻塞：{{ researchProgress(row.progress).blocker }}</div>
                <div v-if="researchProgress(row.progress).evidence">完成证据：{{ researchProgress(row.progress).evidence }} 项</div>
              </template>
            </el-table-column>
            <el-table-column prop="task_id" label="Task ID" min-width="260" show-overflow-tooltip />
            <el-table-column label="任务交接" width="130"><template #default="{ row }"><el-button link @click="handoffTask = row.task_id">查看交接</el-button></template></el-table-column>
            <el-table-column label="审批与许可" width="260">
              <template #default="{ row }">
                <el-button link @click="inspectTaskPermission(String(row.task_id))">读取已记录许可</el-button>
                <span>{{ row.conversation_id ? "已关联原对话" : "无关联原对话" }}</span>
              </template>
            </el-table-column>
          </el-table>
          </ListFilterPagination>
          <TaskHandoffPanel v-if="handoffTask" :task-id="handoffTask" />
          <el-empty v-if="!tasks.length && !busy" description="当前工作区暂无研究任务" />
        </el-tab-pane>

        <el-tab-pane label="研究资产" name="assets" lazy>
          <ListFilterPagination v-model:query="artifactPages.query.value" v-model:page="artifactPages.page.value" :page-size="artifactPages.pageSize.value" :total="artifactPages.total.value" placeholder="筛选资产类型、编号或状态" label="研究资产分页">
          <el-table :data="artifactPages.pageItems.value" v-loading="busy">
            <el-table-column label="类型" width="150">
              <template #default="{ row }">
                <el-tag effect="light">{{ row.kind }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="artifact_id" label="Artifact ID" min-width="260" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="120" />
            <el-table-column label="创建时间" min-width="190">
              <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="既有领域审批" width="150">
              <template #default="{ row }">
                <el-button v-if="row.kind === 'strategy_version'" link @click="inspectStrategyApproval(String(row.artifact_id))">读取精确审批</el-button>
                <span v-else>—</span>
              </template>
            </el-table-column>
          </el-table>
          </ListFilterPagination>
          <el-empty v-if="!artifacts.length && !busy" description="暂无研究资产" />
        </el-tab-pane>

        <el-tab-pane label="审批收件箱" name="inbox" lazy>
          <el-tabs @tab-change="handleInboxTabChange">
            <el-tab-pane label="Agent 审批结果" name="agent-history">
              <p>只显示已批准或已拒绝的终态审批记录；当前页面仅做分页读取。</p>
              <div class="quant-panel">
                <el-select v-model="agentHistoryStatus" style="width: 160px" @change="agentHistoryPage = 1; loadAgentHistory()">
                  <el-option label="已批准" value="approved" />
                  <el-option label="已拒绝" value="rejected" />
                </el-select>
                <el-button :loading="historyBusy" @click="loadAgentHistory">刷新</el-button>
              </div>
              <el-table :data="approvals" v-loading="historyBusy" empty-text="暂无此类终态记录">
                <el-table-column prop="approval_id" label="Approval ID" min-width="240" show-overflow-tooltip />
                <el-table-column prop="action" label="动作" min-width="160" />
                <el-table-column prop="status" label="状态" width="120" />
                <el-table-column prop="decision_by" label="决定人" min-width="140" />
              </el-table>
              <EntityPagination :page="agentHistoryPage" :page-size="HISTORY_PAGE_SIZE" :total="agentHistoryTotal" label="Agent 审批历史分页" @update:page="changeAgentHistoryPage" />
            </el-tab-pane>
            <el-tab-pane label="BYQ 业务审批结果" name="product-history">
              <p>仅显示已批准或已拒绝的 typed request 结果。待审批及结果未决记录可在顶部审批中心核对。</p>
              <div class="quant-panel">
                <el-select v-model="productHistoryStatus" style="width: 160px" @change="productHistoryPage = 1; loadProductHistory()">
                  <el-option label="已批准" value="approved" />
                  <el-option label="已拒绝" value="rejected" />
                </el-select>
                <el-button :loading="historyBusy" @click="loadProductHistory">刷新</el-button>
              </div>
              <el-table :data="productRequests" v-loading="historyBusy" empty-text="暂无此类终态申请">
                <el-table-column prop="request_id" label="Request ID" min-width="230" show-overflow-tooltip />
                <el-table-column prop="request_type" label="申请类型" min-width="180" />
                <el-table-column prop="task_id" label="Task ID" min-width="220" show-overflow-tooltip />
                <el-table-column label="单一资源 Artifact" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.resource_artifact_id ?? "多资产绑定" }}</template>
                </el-table-column>
                <el-table-column prop="content_sha256" label="内容 SHA-256" min-width="250" show-overflow-tooltip />
                <el-table-column prop="status" label="状态" width="110" />
              </el-table>
              <EntityPagination :page="productHistoryPage" :page-size="HISTORY_PAGE_SIZE" :total="productHistoryTotal" label="业务审批结果分页" @update:page="changeProductHistoryPage" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="实体查询" name="research" lazy>
          <div class="quant-panel">
            <el-select v-model="entityType" style="width: 180px">
              <el-option label="Task" value="tasks" />
              <el-option label="Experiment" value="experiments" />
              <el-option label="Artifact" value="artifacts" />
            </el-select>
            <el-input v-model="entityId" placeholder="Entity ID" style="width: 320px" />
            <el-button type="primary" :loading="busy" @click="loadEntity">查看</el-button>
          </div>
          <pre v-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
        </el-tab-pane>

        <el-tab-pane label="审批查询" name="approval" lazy>
          <div class="quant-panel">
            <el-select v-model="approvalSource" style="width: 220px">
              <el-option label="AgentApproval ID" value="agent" />
              <el-option label="策略版本 Artifact ID" value="strategy" />
              <el-option label="续接 Task ID" value="continuation" />
            </el-select>
            <el-input v-model="approvalId" :placeholder="approvalSource === 'agent' ? '精确 Approval ID' : approvalSource === 'strategy' ? '精确 strategy_version Artifact ID' : '精确 Task ID'" style="width: 320px" />
            <el-button type="primary" :loading="busy" @click="loadApproval">查看</el-button>
          </div>
          <p v-if="resultSource" role="status">来源：{{ resultSource }}。这是单条精确读取，不是全量历史扫描。</p>
          <pre v-if="result" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
        </el-tab-pane>
      </el-tabs>

      <p v-if="error" class="page-error">{{ error }}</p>
    </el-card>
  </section>
</template>
