<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Bell } from "@element-plus/icons-vue";
import { decideApproval, listApprovals } from "@/api/research";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";
import EntityPagination from "@/components/ui/EntityPagination.vue";

const open = ref(false);
const approvals = ref<Array<Record<string, unknown>>>([]);
const pendingTotal = ref(0);
const error = ref("");
const busyId = ref("");
const loading = ref(false);
const page = ref(1);
const PAGE_SIZE = 20;
const router = useRouter();
let refreshTimer: number | null = null;
const manualApprovals = computed(() => approvals.value.filter((item) => item.status === "pending"));
const pending = computed(() => pendingTotal.value);

async function refresh() {
  if (loading.value) return;
  loading.value = true;
  try {
    const response = await listApprovals({
      status: "pending", limit: PAGE_SIZE, offset: (page.value - 1) * PAGE_SIZE,
    });
    approvals.value = response.approvals ?? [];
    pendingTotal.value = response.pending_count ?? response.total ?? approvals.value.length;
  } finally {
    loading.value = false;
  }
}

async function decide(item: Record<string, unknown>, decision: "approved" | "rejected") {
  const approvalId = String(item.approval_id ?? "");
  if (!approvalId) return;
  busyId.value = approvalId;
  error.value = "";
  try {
    const result = await decideApproval(approvalId, decision, "BYQ Product 人工审批");
    page.value = 1;
    await refresh();
    open.value = false;
    window.dispatchEvent(new Event("byq:approvals-changed"));
    const conversationId = String(result.approval.conversation_id ?? "");
    const continuationStatus = String(result.approval.continuation_status ?? "");
    ElMessage.success(decision === "approved" ? "已批准，正在返回原会话继续" : "已拒绝，正在返回原会话");
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
    error.value = exc instanceof Error ? exc.message : "审批失败";
  } finally {
    busyId.value = "";
  }
}

function refreshWhenVisible() {
  if (document.visibilityState === "visible") void refresh().catch(() => undefined);
}

async function changePage(value: number) {
  page.value = value;
  await refresh();
}

function openCenter() {
  page.value = 1;
  void refresh().catch(() => undefined);
}

onMounted(() => {
  void refresh().catch(() => undefined);
  refreshTimer = window.setInterval(refreshWhenVisible, 15_000);
  window.addEventListener("focus", refreshWhenVisible);
  window.addEventListener("byq:approvals-changed", refreshWhenVisible);
  document.addEventListener("visibilitychange", refreshWhenVisible);
});

onUnmounted(() => {
  if (refreshTimer !== null) window.clearInterval(refreshTimer);
  window.removeEventListener("focus", refreshWhenVisible);
  window.removeEventListener("byq:approvals-changed", refreshWhenVisible);
  document.removeEventListener("visibilitychange", refreshWhenVisible);
});
</script>

<template>
  <el-tooltip content="待人工审批" placement="bottom">
    <button
      class="approval-trigger"
      type="button"
      :aria-label="pending ? `待人工审批，${pending} 项` : '待人工审批，无待办'"
      @click="open = true"
    >
      <el-badge :value="pending" :hidden="pending === 0" :max="99" type="danger">
        <el-icon><Bell /></el-icon>
      </el-badge>
    </button>
  </el-tooltip>
  <el-drawer v-model="open" title="待人工审批" size="min(92vw, 430px)" @open="openCenter">
    <p v-if="error" class="page-error">{{ error }}</p>
    <ApprovalManagementPanel :approvals="manualApprovals" :total="pendingTotal" :busy-id="busyId" @decide="decide" />
    <EntityPagination
      :page="page"
      :page-size="PAGE_SIZE"
      :total="pendingTotal"
      label="待审批列表分页"
      @update:page="changePage"
    />
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
</style>
