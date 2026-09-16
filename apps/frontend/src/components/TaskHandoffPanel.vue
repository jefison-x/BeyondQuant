<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { getTaskHandoff, type TaskHandoffView } from '@/api/research';
import { researchProgress } from '@/researchProgress';

const props = defineProps<{ taskId: string }>();
const view = ref<TaskHandoffView | null>(null);
const error = ref('');
const busy = ref(false);
let generation = 0;
const labels: Record<string, string> = {
  completed: '任务已完成', failed: '任务失败', cancelled: '任务已取消',
  waiting_approval: '等待动作审批', waiting_job: '已有作业，等待结果',
  conversation_active: '原会话有活动，尚不能确认本任务正在执行',
  continuation_queued: '后台续接已排队', approval_continuation_queued: '审批续接已排队',
  needs_permission: '需要确认后台续接许可', needs_reconciliation: '执行结果需要核对',
  blocked: '暂无已确认的后续执行',
};
const reasons: Record<string, string> = {
  permission_missing: '尚未授权后台续接，请在原对话中继续，或查看任务许可。',
  permission_revoked: '后台续接许可已撤销。', permission_expired: '后台续接许可已到期。',
  conversation_binding_missing: '尚未绑定原研究对话。', conversation_inactive: '原研究对话已归档。',
  no_registered_executor: '尚未发现已登记的作业或续接投递，请核对下一步。',
  task_execution_unconfirmed: '会话活动不等于本任务已有执行者。',
  continuation_result_unconfirmed: '续接提交或执行结果尚未确认，请先核对原回执。',
  approval_continuation_unconfirmed: '审批续接提交尚未确认。',
  budget_exhausted: '后台额度或回合预算不足。',
  budget_enforcement_unqualified: '后台执行当前未启用。',
  completion_evidence_missing: '任务虽已标记完成，但缺少可核对的完成证据。',
  approval_binding_invalid: '审批绑定的业务对象需要核对。',
  evidence_limit_reached: '关联记录超出本次核对范围，不能据此判定无人执行。',
};
async function refresh() {
  const current = ++generation;
  const task = props.taskId;
  view.value = null;
  error.value = '';
  busy.value = true;
  try {
    const result = await getTaskHandoff(task);
    if (current !== generation) return;
    if (result.schema_version !== 'research-task-handoff.v1' || result.task_id !== task) {
      throw new Error('交接记录与当前任务不一致，请重新核对。');
    }
    view.value = result;
  } catch (exc) {
    if (current === generation) error.value = exc instanceof Error ? exc.message : '交接信息读取失败';
  } finally {
    if (current === generation) busy.value = false;
  }
}
watch(() => props.taskId, refresh, { immediate: true });
onBeforeUnmount(() => { generation++; });
</script>

<template>
  <section aria-label="任务交接状态" class="quant-panel" style="display: block">
    <el-button :loading="busy" @click="refresh">刷新交接状态</el-button>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="view">
      <h3>{{ labels[view.state] ?? '交接状态需要核对' }}</h3>
      <p>原目标：{{ view.objective }}</p>
      <p>下一步：{{ researchProgress(view.progress).next }}</p>
      <p v-if="view.reason">{{ reasons[view.reason] ?? '请在原对话核对阻塞原因。' }}</p>
      <p v-if="researchProgress(view.progress).blocker">任务记录的阻塞：{{ researchProgress(view.progress).blocker }}</p>
      <p>完成证据：{{ researchProgress(view.progress).evidence }} 项</p>
      <p v-for="item in view.references" :key="`${item.kind}:${item.id}`" style="overflow-wrap: anywhere">{{ item.id }}：{{ item.status }}</p>
      <small>这是最近一次对持久业务记录的核对；刷新可查看变化。回合结束不代表任务完成。</small>
    </template>
  </section>
</template>
