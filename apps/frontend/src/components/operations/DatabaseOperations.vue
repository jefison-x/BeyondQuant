<script setup lang="ts">
import type { OperationsStatus } from "@/api/types";
defineProps<{ data: OperationsStatus }>();
const bytes = (value: number) => `${(value / 1024 / 1024).toFixed(1)} MiB`;
</script>
<template><div class="ops-workbench"><div class="ops-metrics">
  <el-card shadow="never"><span>数据库</span><strong>{{ data.database.name }}</strong><small>PostgreSQL {{ data.database.server_version }}</small></el-card>
  <el-card shadow="never"><span>占用空间</span><strong>{{ bytes(data.database.size_bytes) }}</strong><small>应用数据库实时值</small></el-card>
  <el-card shadow="never"><span>业务表</span><strong>{{ data.database.table_count }}</strong><small>估算 {{ data.database.estimated_rows }} 行</small></el-card>
  <el-card shadow="never"><span>单域存储迁移</span><strong>{{ data.database.migration.single_domain_store }}</strong><small>SQLite runtime：已移除</small></el-card>
</div><el-card shadow="never"><template #header><strong>领域资源记录</strong></template><el-table :data="data.database.domain_counts" max-height="520"><el-table-column prop="resource" label="领域资源" min-width="240" /><el-table-column prop="count" label="记录数" width="160" align="right" /></el-table></el-card></div></template>
