<script setup lang="ts">
import type { OperationsStatus } from "@/api/types";
defineProps<{ data: OperationsStatus }>();
</script>
<template><div class="ops-workbench"><el-alert title="Phase 38 仅提供配置就绪度；Tushare 凭据 CRUD、连接测试和同步任务属于 Phase 39。" type="info" show-icon :closable="false" /><div class="ops-metrics">
  <el-card shadow="never"><span>唯一数据源</span><strong>Tushare</strong><small>provider allow-list</small></el-card>
  <el-card shadow="never"><span>凭据记录</span><strong>{{ data.sources.credential_metadata.reduce((sum, row) => sum + Number(row.count ?? 0), 0) }}</strong><small>仅元数据，不返回密钥</small></el-card>
  <el-card shadow="never"><span>旧提供商</span><strong>0</strong><small>BaoStock / AKShare 均 DROP</small></el-card>
</div><el-card shadow="never"><template #header><strong>系统凭据元数据</strong></template><el-table :data="data.sources.credential_metadata" empty-text="尚未配置 Tushare 系统凭据"><el-table-column prop="provider_key" label="提供商" min-width="180" /><el-table-column prop="scope" label="范围" width="120" /><el-table-column prop="status" label="状态" width="120" /><el-table-column prop="count" label="数量" width="100" /></el-table></el-card></div></template>
