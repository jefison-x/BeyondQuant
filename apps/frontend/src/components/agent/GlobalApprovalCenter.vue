<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { decideApproval, getApproval, listApprovals } from "@/api/research";
import ApprovalManagementPanel from "./ApprovalManagementPanel.vue";

const open = ref(false);
const approvals = ref<Array<Record<string, unknown>>>([]);
const error = ref("");
const busyId = ref("");
const pending = computed(() => approvals.value.filter((item) => item.status === "pending").length);

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
  <button class="approval-trigger" type="button" aria-label="打开全局审批中心" @click="open = true">
    <span>审批</span><b v-if="pending">{{ pending }}</b>
  </button>
  <el-drawer v-model="open" title="全局审批中心" size="min(92vw, 430px)" @open="refresh">
    <p v-if="error" class="page-error">{{ error }}</p>
    <ApprovalManagementPanel :approvals="approvals" :busy-id="busyId" @decide="decide" />
  </el-drawer>
</template>

<style scoped>
.approval-trigger { align-items: center; background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 999px; bottom: 84px; box-shadow: var(--byq-shadow); color: var(--byq-text); cursor: pointer; display: flex; font-size: 12px; gap: .4rem; padding: .55rem .75rem; position: fixed; right: 24px; z-index: 30; }
.approval-trigger b { align-items: center; background: var(--el-color-danger); border-radius: 50%; color: white; display: flex; font-size: 10px; height: 18px; justify-content: center; min-width: 18px; }
@media (max-width: 767px) { .approval-trigger { bottom: 128px; right: 14px; } }
</style>
