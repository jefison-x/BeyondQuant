<script setup lang="ts">
defineProps<{ approvals: Array<Record<string, unknown>>; busyId?: string }>();
const emit = defineEmits<{ decide: [approval: Record<string, unknown>, decision: "approved" | "rejected"] }>();
</script>

<template>
  <section class="approval-panel" aria-label="审批管理">
    <div class="panel-heading"><span class="panel-title">审批收件箱</span><el-tag size="small">{{ approvals.length }}</el-tag></div>
    <el-empty v-if="!approvals.length" description="暂无审批" :image-size="52" />
    <ul v-else>
      <li v-for="approval in approvals" :key="String(approval.approval_id)">
        <div><strong>{{ approval.action }}</strong><small>{{ approval.approval_id }}</small><small>执行：{{ approval.execution_outcome }}</small></div>
        <div class="approval-actions">
          <el-tag size="small">{{ approval.status }}</el-tag>
          <template v-if="approval.status === 'pending'">
            <el-button size="small" type="primary" :loading="busyId === approval.approval_id" @click="emit('decide', approval, 'approved')">通过</el-button>
            <el-button size="small" type="danger" plain :loading="busyId === approval.approval_id" @click="emit('decide', approval, 'rejected')">拒绝</el-button>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.approval-panel { display: grid; gap: .65rem; } ul { display: grid; gap: .45rem; list-style: none; margin: 0; padding: 0; }
li { align-items: center; background: var(--byq-surface-subtle); border-radius: 8px; display: flex; gap: .6rem; justify-content: space-between; padding: .55rem; }
li > div:first-child { display: grid; min-width: 0; } strong { color: var(--byq-text); font-size: 12px; } small { color: var(--byq-text-soft); font-size: 10px; overflow: hidden; text-overflow: ellipsis; }
.approval-actions { align-items: center; display: flex; flex-wrap: wrap; gap: .3rem; justify-content: flex-end; }
</style>
