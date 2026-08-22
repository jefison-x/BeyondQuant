<script setup lang="ts">
import type { OperationsStatus } from "@/api/types";
defineProps<{ data: OperationsStatus }>();
</script>
<template><div class="ops-workbench"><el-alert title="该视图以 BYQ AgentRun/WorkflowTrace 投影替代 Community Graph runtime；不展示 DSH checkpoint 或内部节点对象。" type="info" show-icon :closable="false" /><el-card shadow="never"><template #header><strong>规范化工作流运行</strong></template><el-table :data="data.graphs.recent_runs" empty-text="暂无规范化 Agent 运行" max-height="560"><el-table-column prop="run_id" label="Run ID" min-width="230" show-overflow-tooltip /><el-table-column prop="role_id" label="角色" min-width="180" /><el-table-column prop="status" label="状态" width="120" /><el-table-column prop="trace_id" label="Trace" min-width="210" show-overflow-tooltip /><el-table-column prop="parent_run_id" label="父运行" min-width="210" show-overflow-tooltip /><el-table-column prop="updated_at" label="更新时间" min-width="190" /></el-table></el-card></div></template>
