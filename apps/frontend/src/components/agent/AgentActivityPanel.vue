<script setup lang="ts">
import type { WorkflowActivityPayload } from "@/api/types";

defineProps<{ activities: Array<{ sequence: number; timestamp: string; payload: WorkflowActivityPayload }> }>();
const stateType = (state: WorkflowActivityPayload["state"]) => ({ started: "primary", progress: "warning", completed: "success", failed: "danger", waiting_approval: "warning" }[state] as "primary" | "warning" | "success" | "danger");
const stateLabel = (state: WorkflowActivityPayload["state"]) => ({ started: "进行中", progress: "处理中", completed: "已完成", failed: "未完成", waiting_approval: "等待确认" }[state]);
const phaseLabel = (phase: WorkflowActivityPayload["phase"]) => ({ understand: "理解需求", select: "研究数据", strategy: "策略研究", backtest: "回测分析", review: "结果确认", tool: "任务处理" }[phase]);
</script>

<template>
  <section class="activity-panel" aria-label="公开执行进度">
    <div class="panel-heading"><span class="panel-title">执行进度</span><el-tag size="small">{{ activities.length }}</el-tag></div>
    <el-empty v-if="!activities.length" description="尚无公开执行进度" :image-size="52" />
    <ol v-else><li v-for="activity in activities" :key="`${activity.payload.activity_id}-${activity.sequence}`"><span class="activity-dot" :class="activity.payload.state" /><div><strong>{{ activity.payload.label }}</strong><small>{{ phaseLabel(activity.payload.phase) }}</small><span v-if="activity.payload.agent_label || activity.payload.plugin_label || activity.payload.skill_label" class="execution-context"><em v-if="activity.payload.agent_label">Agent · {{ activity.payload.agent_label }}</em><em v-if="activity.payload.plugin_label">插件 · {{ activity.payload.plugin_label }}</em><em v-if="activity.payload.skill_label">Skill · {{ activity.payload.skill_label }}</em></span></div><el-tag size="small" :type="stateType(activity.payload.state)">{{ stateLabel(activity.payload.state) }}</el-tag></li></ol>
    <p class="privacy-note">这里只显示经过安全映射的公开执行信息，不展示工具参数、原始事件或内部推理。</p>
  </section>
</template>

<style scoped>
.activity-panel { display: grid; gap: .65rem; } ol { display: grid; gap: .45rem; list-style: none; margin: 0; padding: 0; }
li { align-items: center; display: grid; gap: .55rem; grid-template-columns: 8px minmax(0, 1fr) auto; }
.activity-dot { background: var(--byq-text-soft); border-radius: 50%; height: 8px; width: 8px; }
.activity-dot.completed { background: var(--el-color-success); } .activity-dot.failed { background: var(--el-color-danger); } .activity-dot.started, .activity-dot.progress { background: var(--byq-brand); }
li div { display: grid; } li strong { color: var(--byq-text); font-size: 12px; } li small, .privacy-note { color: var(--byq-text-soft); font-size: 11px; }
.execution-context { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .25rem; }.execution-context em { background: var(--byq-surface-muted); border-radius: 999px; color: var(--byq-text-muted); font-size: 10px; font-style: normal; padding: .15rem .4rem; }
.privacy-note { border-top: 1px solid var(--byq-border-subtle); margin: 0; padding-top: .55rem; }
</style>
