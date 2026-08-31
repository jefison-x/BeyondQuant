<script setup lang="ts">
import { computed } from "vue";
import type { OperationsStatus } from "@/api/types";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useFilteredPagination } from "@/composables/useFilteredPagination";
const props = defineProps<{ data: OperationsStatus }>();
const statusGroups = computed(() => props.data.agents.status_groups);
const pages = useFilteredPagination(statusGroups, (row) => `${row.role_id ?? ""} ${row.status ?? ""}`, 15);
</script>
<template><div class="ops-workbench"><div class="ops-metrics"><el-card shadow="never"><span>活跃 runtime sessions</span><strong>{{ data.runtime.sessions.active }}</strong><small>{{ data.runtime.sessions.active_prompts }} 个运行中 prompt</small></el-card><el-card shadow="never"><span>Agent 运行分组</span><strong>{{ data.agents.status_groups.length }}</strong><small>角色 × 状态</small></el-card><el-card shadow="never"><span>最近运行</span><strong>{{ data.agents.recent_runs.length }}</strong><small>最多 30 条</small></el-card></div><el-card shadow="never"><template #header><strong>Agent 运行质量</strong></template><ListFilterPagination v-model:query="pages.query.value" v-model:page="pages.page.value" :page-size="pages.pageSize.value" :total="pages.total.value" placeholder="筛选 Agent 角色或状态" label="Agent 运行分页"><el-table :data="pages.pageItems.value" empty-text="暂无 Agent 运行"><el-table-column prop="role_id" label="角色" min-width="220" /><el-table-column prop="status" label="状态" width="140" /><el-table-column prop="count" label="数量" width="100" /></el-table></ListFilterPagination></el-card></div></template>
