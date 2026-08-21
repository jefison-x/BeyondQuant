<script setup lang="ts">
import type { WorkflowActivityPayload } from "@/api/types";

defineProps<{ activities: Array<{ sequence: number; timestamp: string; payload: WorkflowActivityPayload }> }>();
const stateType = (state: WorkflowActivityPayload["state"]) => ({ started: "primary", progress: "warning", completed: "success", failed: "danger", waiting_approval: "warning" }[state] as "primary" | "warning" | "success" | "danger");
</script>

<template>
  <section class="activity-panel" aria-label="公开执行进度">
    <div class="panel-heading"><span class="panel-title">执行进度</span><el-tag size="small">{{ activities.length }}</el-tag></div>
    <el-empty v-if="!activities.length" description="尚无公开执行进度" :image-size="52" />
    <ol v-else><li v-for="activity in activities" :key="`${activity.payload.activity_id}-${activity.sequence}`"><span class="activity-dot" :class="activity.payload.state" /><div><strong>{{ activity.payload.label }}</strong><small>{{ activity.payload.phase }}</small></div><el-tag size="small" :type="stateType(activity.payload.state)">{{ activity.payload.state }}</el-tag></li></ol>
    <p class="privacy-note">仅展示规范化的公开阶段，不展示模型隐藏推理或工具参数。</p>
  </section>
</template>

<style scoped>
.activity-panel { display: grid; gap: .65rem; } ol { display: grid; gap: .45rem; list-style: none; margin: 0; padding: 0; }
li { align-items: center; display: grid; gap: .55rem; grid-template-columns: 8px minmax(0, 1fr) auto; }
.activity-dot { background: var(--byq-text-soft); border-radius: 50%; height: 8px; width: 8px; }
.activity-dot.completed { background: var(--el-color-success); } .activity-dot.failed { background: var(--el-color-danger); } .activity-dot.started, .activity-dot.progress { background: var(--byq-brand); }
li div { display: grid; } li strong { color: var(--byq-text); font-size: 12px; } li small, .privacy-note { color: var(--byq-text-soft); font-size: 11px; }
.privacy-note { border-top: 1px solid var(--byq-border-subtle); margin: 0; padding-top: .55rem; }
</style>
