<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Bell } from "@element-plus/icons-vue";
import { decideApproval, getApproval, listApprovals } from "@/api/research";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";

const open = ref(false);
const approvals = ref<Array<Record<string, unknown>>>([]);
const error = ref("");
const busyId = ref("");
const manualApprovals = computed(() => approvals.value.filter((item) => item.status === "pending"));
const pending = computed(() => manualApprovals.value.length);

async function refresh() {
  const response = await listApprovals();
  approvals.value = response.approvals;
}

async function decide(item: Record<string, unknown>, decision: "approved" | "rejected") {
  const approvalId = String(item.approval_id ?? "");
  if (!approvalId) return;
  busyId.value = approvalId;
  error.value = "";
  try {
    const freshBody = await getApproval(approvalId);
    const fresh = (freshBody.approval ?? freshBody) as Record<string, unknown>;
    if (fresh.status !== "pending") {
      await refresh();
      return;
    }
    await decideApproval(approvalId, decision, "BYQ Product 人工审批");
    await refresh();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "审批失败";
  } finally {
    busyId.value = "";
  }
}

onMounted(() => void refresh().catch(() => undefined));
</script>

<template>
  <el-tooltip content="待人工审批" placement="bottom">
    <button
      class="approval-trigger"
      type="button"
      :aria-label="pending ? `待人工审批，${pending} 项` : '待人工审批，无待办'"
      @click="open = true"
    >
      <el-badge :value="pending" :hidden="pending === 0">
        <el-icon><Bell /></el-icon>
      </el-badge>
    </button>
  </el-tooltip>
  <el-drawer v-model="open" title="待人工审批" size="min(92vw, 430px)" @open="refresh">
    <p v-if="error" class="page-error">{{ error }}</p>
    <ApprovalManagementPanel :approvals="manualApprovals" :busy-id="busyId" @decide="decide" />
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
