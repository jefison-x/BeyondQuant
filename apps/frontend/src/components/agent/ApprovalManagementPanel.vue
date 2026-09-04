<script setup lang="ts">
defineProps<{ approvals: Array<Record<string, unknown>>; total?: number; busyId?: string }>();
const emit = defineEmits<{ decide: [approval: Record<string, unknown>, decision: "approved" | "rejected"] }>();

const ACTION_LABELS: Record<string, string> = {
  byq_feedback_submit: "提交产品反馈",
  byq_strategy_approve: "批准策略版本",
  byq_ml_strategy_approve: "批准机器学习策略",
  byq_ml_training_create: "开始机器学习训练",
  byq_ml_training_cancel: "取消机器学习训练",
  byq_ml_prediction_create: "生成机器学习预测",
  byq_backtest_task_create: "创建回测任务",
  byq_backtest_task_execute: "执行回测任务",
  byq_backtest_task_cancel: "取消回测任务",
};

function actionLabel(value: unknown) {
  const key = String(value ?? "");
  return ACTION_LABELS[key] ?? "执行受控操作";
}

function resourceLabel(item: Record<string, unknown>) {
  const type = String(item.resource_type ?? "");
  const id = String(item.resource_id ?? "");
  if (!type || !id) return "未绑定具体资源";
  const label = type === "product_feedback" ? "产品反馈" : type;
  return `${label} · ${id}`;
}
</script>

<template>
  <section class="approval-panel" aria-label="审批管理">
    <div class="panel-heading"><span class="panel-title">审批收件箱</span><el-tag size="small">{{ total ?? approvals.length }}</el-tag></div>
    <el-empty v-if="!approvals.length" description="暂无审批" :image-size="52" />
    <ul v-else>
      <li v-for="approval in approvals" :key="String(approval.approval_id)">
        <div class="approval-summary">
          <strong>{{ actionLabel(approval.action) }}</strong>
          <span v-if="approval.reason" class="reason">{{ approval.reason }}</span>
          <small :title="resourceLabel(approval)">{{ resourceLabel(approval) }}</small>
          <small v-if="approval.conversation_title">来自会话：{{ approval.conversation_title }}</small>
        </div>
        <div class="approval-actions">
          <template v-if="approval.status === 'pending'">
            <el-button size="small" type="primary" :loading="busyId === approval.approval_id" @click="emit('decide', approval, 'approved')">批准</el-button>
            <el-button size="small" type="danger" plain :loading="busyId === approval.approval_id" @click="emit('decide', approval, 'rejected')">拒绝</el-button>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.approval-panel { display: grid; gap: .65rem; } ul { display: grid; gap: .45rem; list-style: none; margin: 0; padding: 0; }
li { align-items: center; background: var(--byq-surface-subtle); border-radius: 8px; display: flex; gap: .6rem; justify-content: space-between; padding: .7rem; }
.approval-summary { display: grid; gap: .15rem; min-width: 0; } strong { color: var(--byq-text); font-size: 13px; } .reason { color: var(--byq-text-muted); font-size: 12px; line-height: 1.45; } small { color: var(--byq-text-soft); font-size: 10px; overflow: hidden; text-overflow: ellipsis; }
.approval-actions { align-items: center; display: flex; flex-wrap: wrap; gap: .3rem; justify-content: flex-end; }
</style>
