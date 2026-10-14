<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  getApproval,
  getContinuationPermission,
  listApprovals,
  listProductApprovalRequests,
  type ProductApprovalRequest,
} from "@/api/research";
import { getStrategyVersionApproval } from "@/api/quant";
import { useAuthStore } from "@/stores/auth";
import EntityPagination from "@/components/ui/EntityPagination.vue";

type HistoryTab = "agent-history" | "product-history" | "approval-record";
type ApprovalSource = "agent" | "strategy" | "continuation";

const tab = ref<HistoryTab>("agent-history");
const approvalId = ref("");
const approvalSource = ref<ApprovalSource>("agent");
const result = ref<unknown>(null);
const resultSource = ref("");
const error = ref("");
const historyBusy = ref(false);
const approvalBusy = ref(false);
const approvals = ref<Array<Record<string, unknown>>>([]);
const productRequests = ref<ProductApprovalRequest[]>([]);
const agentHistoryStatus = ref<"approved" | "rejected">("approved");
const productHistoryStatus = ref<"approved" | "rejected">("approved");
const agentHistoryPage = ref(1);
const productHistoryPage = ref(1);
const agentHistoryTotal = ref(0);
const productHistoryTotal = ref(0);
const HISTORY_PAGE_SIZE = 20;

const auth = useAuthStore();
const authScope = computed(() => [
  auth.user?.subject ?? "",
  auth.user?.workspace?.workspace_id ?? "",
].join("\u0000"));
let scopeGeneration = 0;
let inboxGeneration = 0;
let agentHistoryGeneration = 0;
let productHistoryGeneration = 0;
let approvalGeneration = 0;

function requestIsCurrent(scope: string, epoch: number) {
  return scope === authScope.value && epoch === scopeGeneration;
}

function clearHistory() {
  approvals.value = [];
  productRequests.value = [];
  agentHistoryPage.value = 1;
  productHistoryPage.value = 1;
  agentHistoryTotal.value = 0;
  productHistoryTotal.value = 0;
}

async function loadInbox() {
  const request = ++inboxGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const owner = auth.user?.subject ?? "";
  const workspaceId = auth.user?.workspace?.workspace_id ?? "";
  const agentStatus = agentHistoryStatus.value;
  const agentPage = agentHistoryPage.value;
  const productStatus = productHistoryStatus.value;
  const productPage = productHistoryPage.value;
  const isCurrent = () => request === inboxGeneration && requestIsCurrent(scope, epoch)
    && agentStatus === agentHistoryStatus.value && agentPage === agentHistoryPage.value
    && productStatus === productHistoryStatus.value && productPage === productHistoryPage.value;
  if (!owner || !workspaceId) {
    clearHistory();
    historyBusy.value = false;
    return;
  }
  historyBusy.value = true;
  error.value = "";
  try {
    const [agent, product] = await Promise.all([
      listApprovals({
        status: agentStatus,
        limit: HISTORY_PAGE_SIZE,
        offset: (agentPage - 1) * HISTORY_PAGE_SIZE,
      }),
      listProductApprovalRequests({
        status: productStatus,
        limit: HISTORY_PAGE_SIZE,
        offset: (productPage - 1) * HISTORY_PAGE_SIZE,
      }),
    ]);
    if (!isCurrent()) return;
    if ((agent.approvals ?? []).some(item => item.status !== agentStatus)
        || (product.requests ?? []).some(item => item.status !== productStatus)) {
      throw new Error("审批历史返回了与已决状态筛选不符的记录；未将待核对事项显示为历史结果。");
    }
    if ((product.requests ?? []).some(item =>
      item.owner_principal !== owner || item.workspace_id !== workspaceId)) {
      throw new Error("业务审批历史返回了其他身份或工作区的记录；已拒绝显示。");
    }
    approvals.value = agent.approvals ?? [];
    agentHistoryTotal.value = agent.total ?? 0;
    productRequests.value = product.requests ?? [];
    productHistoryTotal.value = product.total ?? 0;
  } catch (exc) {
    if (isCurrent()) {
      error.value = exc instanceof Error ? exc.message : "读取审批历史失败";
    }
  } finally {
    if (isCurrent()) historyBusy.value = false;
  }
}

async function loadAgentHistory() {
  const request = ++agentHistoryGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const status = agentHistoryStatus.value;
  const requestedPage = agentHistoryPage.value;
  const requestedTab = tab.value;
  if (!auth.user?.subject || !auth.user.workspace?.workspace_id) return;
  historyBusy.value = true;
  error.value = "";
  try {
    const response = await listApprovals({
      status,
      limit: HISTORY_PAGE_SIZE,
      offset: (requestedPage - 1) * HISTORY_PAGE_SIZE,
    });
    if (request !== agentHistoryGeneration || !requestIsCurrent(scope, epoch)
        || status !== agentHistoryStatus.value || requestedPage !== agentHistoryPage.value) return;
    if ((response.approvals ?? []).some(item => item.status !== status)) {
      throw new Error("Agent 审批历史返回了与已决状态筛选不符的记录。");
    }
    approvals.value = response.approvals ?? [];
    agentHistoryTotal.value = response.total ?? 0;
  } catch (exc) {
    if (request === agentHistoryGeneration && requestIsCurrent(scope, epoch)
        && requestedTab === tab.value) {
      error.value = exc instanceof Error ? exc.message : "读取 Agent 审批历史失败";
    }
  } finally {
    if (request === agentHistoryGeneration && requestIsCurrent(scope, epoch)) historyBusy.value = false;
  }
}

async function loadProductHistory() {
  const request = ++productHistoryGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const owner = auth.user?.subject ?? "";
  const workspaceId = auth.user?.workspace?.workspace_id ?? "";
  const status = productHistoryStatus.value;
  const requestedPage = productHistoryPage.value;
  const requestedTab = tab.value;
  if (!owner || !workspaceId) return;
  historyBusy.value = true;
  error.value = "";
  try {
    const response = await listProductApprovalRequests({
      status,
      limit: HISTORY_PAGE_SIZE,
      offset: (requestedPage - 1) * HISTORY_PAGE_SIZE,
    });
    if (request !== productHistoryGeneration || !requestIsCurrent(scope, epoch)
        || status !== productHistoryStatus.value || requestedPage !== productHistoryPage.value) return;
    if ((response.requests ?? []).some(item =>
      item.owner_principal !== owner || item.workspace_id !== workspaceId)) {
      throw new Error("业务审批历史返回了其他身份或工作区的记录；已拒绝显示。");
    }
    if ((response.requests ?? []).some(item => item.status !== status)) {
      throw new Error("业务审批历史返回了与已决状态筛选不符的记录；未将待核对事项显示为历史结果。");
    }
    productRequests.value = response.requests ?? [];
    productHistoryTotal.value = response.total ?? 0;
  } catch (exc) {
    if (request === productHistoryGeneration && requestIsCurrent(scope, epoch)
        && requestedTab === tab.value) {
      error.value = exc instanceof Error ? exc.message : "读取业务审批历史失败";
    }
  } finally {
    if (request === productHistoryGeneration && requestIsCurrent(scope, epoch)) historyBusy.value = false;
  }
}

async function loadApproval() {
  if (!approvalId.value.trim()) {
    error.value = "请输入准确的审批 ID、策略版本 Artifact ID 或续接 Task ID。";
    return;
  }
  const request = ++approvalGeneration;
  const scope = authScope.value;
  const epoch = scopeGeneration;
  const requestedId = approvalId.value.trim();
  const source = approvalSource.value;
  const token = auth.token;
  const requestedTab = tab.value;
  if (!auth.user?.subject || !auth.user.workspace?.workspace_id) return;
  approvalBusy.value = true;
  error.value = "";
  result.value = null;
  resultSource.value = "";
  try {
    let response: unknown;
    let responseLabel = "";
    if (source === "agent") {
      response = await getApproval(requestedId);
      responseLabel = "AgentApproval 精确只读 Product API";
    } else if (source === "strategy") {
      response = await getStrategyVersionApproval(requestedId, token);
      responseLabel = "策略版本领域审批精确只读 Product API";
    } else {
      const permission = await getContinuationPermission(requestedId);
      responseLabel = "任务续接许可精确只读 Product API";
      if (permission.task_id !== requestedId) {
        throw new Error("续接许可回包的 Task ID 不匹配；已拒绝显示。");
      }
      response = permission;
    }
    if (request !== approvalGeneration || !requestIsCurrent(scope, epoch)
        || requestedId !== approvalId.value.trim() || source !== approvalSource.value
        || requestedTab !== tab.value) return;
    result.value = response;
    resultSource.value = responseLabel;
  } catch (exc) {
    if (request === approvalGeneration && requestIsCurrent(scope, epoch)
        && requestedId === approvalId.value.trim() && source === approvalSource.value
        && requestedTab === tab.value) {
      error.value = exc instanceof Error ? exc.message : "读取审批历史详情失败";
    }
  } finally {
    if (request === approvalGeneration && requestIsCurrent(scope, epoch)) approvalBusy.value = false;
  }
}

function handleHistoryTabChange(value: string | number) {
  if (value !== "approval-record") {
    approvalGeneration += 1;
    approvalBusy.value = false;
    result.value = null;
    resultSource.value = "";
  }
}

function handleAgentHistoryStatusChange(value: unknown) {
  if (value !== "approved" && value !== "rejected") return;
  agentHistoryStatus.value = value;
  agentHistoryPage.value = 1;
  void loadAgentHistory();
}

function handleProductHistoryStatusChange(value: unknown) {
  if (value !== "approved" && value !== "rejected") return;
  productHistoryStatus.value = value;
  productHistoryPage.value = 1;
  void loadProductHistory();
}

async function changeAgentHistoryPage(page: number) {
  agentHistoryPage.value = page;
  await loadAgentHistory();
}

async function changeProductHistoryPage(page: number) {
  productHistoryPage.value = page;
  await loadProductHistory();
}

watch(authScope, () => {
  scopeGeneration += 1;
  inboxGeneration += 1;
  agentHistoryGeneration += 1;
  productHistoryGeneration += 1;
  approvalGeneration += 1;
  clearHistory();
  approvalId.value = "";
  result.value = null;
  resultSource.value = "";
  historyBusy.value = false;
  approvalBusy.value = false;
  error.value = "";
  if (auth.user?.subject && auth.user.workspace?.workspace_id) void loadInbox();
}, { flush: "sync" });

onMounted(() => {
  void loadInbox();
});

onUnmounted(() => {
  scopeGeneration += 1;
  inboxGeneration += 1;
  agentHistoryGeneration += 1;
  productHistoryGeneration += 1;
  approvalGeneration += 1;
});
</script>

<template>
  <section class="research-history" aria-label="审批历史">
    <el-card shadow="never" class="top-band">
      <h2>审批历史</h2>
      <p>只读查看已决定的审批记录与相关领域事实。新的申请、决定和许可撤销由审批中心处理。</p>
      <el-tabs v-model="tab" @tab-change="handleHistoryTabChange">
        <el-tab-pane label="Agent 审批历史" name="agent-history">
          <div class="history-toolbar">
            <el-select v-model="agentHistoryStatus" aria-label="Agent 审批历史状态" style="width: 160px" @change="handleAgentHistoryStatusChange">
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
          <EntityPagination
            :page="agentHistoryPage"
            :page-size="HISTORY_PAGE_SIZE"
            :total="agentHistoryTotal"
            label="Agent 审批历史分页"
            @update:page="changeAgentHistoryPage"
          />
        </el-tab-pane>

        <el-tab-pane label="BYQ 业务审批历史" name="product-history">
          <div class="history-toolbar">
            <el-select v-model="productHistoryStatus" aria-label="BYQ 业务审批历史状态" style="width: 160px" @change="handleProductHistoryStatusChange">
              <el-option label="已批准" value="approved" />
              <el-option label="已拒绝" value="rejected" />
            </el-select>
            <el-button :loading="historyBusy" @click="loadProductHistory">刷新</el-button>
          </div>
          <p>只显示已批准或已拒绝的 typed request。待审批及结果未决记录可在审批中心核对。</p>
          <el-table :data="productRequests" v-loading="historyBusy" empty-text="暂无此类终态申请">
            <el-table-column prop="request_id" label="Request ID" min-width="230" show-overflow-tooltip />
            <el-table-column prop="request_type" label="申请类型" min-width="180" />
            <el-table-column prop="task_id" label="Task ID" min-width="220" show-overflow-tooltip />
            <el-table-column label="单一资源 Artifact" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">{{ row.resource_artifact_id ?? "多资产绑定" }}</template>
            </el-table-column>
            <el-table-column prop="content_sha256" label="内容 SHA-256" min-width="250" show-overflow-tooltip />
            <el-table-column prop="decision" label="决定" width="110" />
            <el-table-column prop="decision_by" label="决定人" min-width="140" />
            <el-table-column prop="status" label="状态" width="110" />
          </el-table>
          <EntityPagination
            :page="productHistoryPage"
            :page-size="HISTORY_PAGE_SIZE"
            :total="productHistoryTotal"
            label="BYQ 业务审批历史分页"
            @update:page="changeProductHistoryPage"
          />
        </el-tab-pane>

        <el-tab-pane label="精确历史详情" name="approval-record">
          <p>按已知 ID 精确读取现有审批或许可记录；此处不扫描任务、资产或全量领域对象。</p>
          <div class="history-toolbar">
            <el-select v-model="approvalSource" aria-label="精确历史详情来源" style="width: 240px">
              <el-option label="AgentApproval ID" value="agent" />
              <el-option label="策略版本 Artifact ID" value="strategy" />
              <el-option label="续接许可 Task ID" value="continuation" />
            </el-select>
            <el-input
              v-model="approvalId"
              :placeholder="approvalSource === 'agent' ? '精确 Approval ID' : approvalSource === 'strategy' ? '精确 strategy_version Artifact ID' : '精确 Task ID'"
              style="width: min(420px, 100%)"
            />
            <el-button type="primary" :loading="approvalBusy" @click="loadApproval">读取历史详情</el-button>
          </div>
          <p v-if="resultSource" role="status">来源：{{ resultSource }}。这是单条精确读取，不是全量历史扫描。</p>
          <pre v-if="result !== null" class="quant-result">{{ JSON.stringify(result, null, 2) }}</pre>
        </el-tab-pane>
      </el-tabs>
      <p v-if="error" class="page-error" role="alert">{{ error }}</p>
    </el-card>
  </section>
</template>

<style scoped>
.history-toolbar { display: flex; align-items: center; gap: 10px; margin: 12px 0; flex-wrap: wrap; }
.quant-result { overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
