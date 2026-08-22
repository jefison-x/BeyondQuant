<script setup lang="ts">
import type { OperationsStatus } from "@/api/types";
defineProps<{ data: OperationsStatus }>();
</script>
<template><div class="ops-workbench"><el-alert title="BYQ 行情缓存由 PostgreSQL market_daily_bars 承载；不使用 Community Redis。" type="success" show-icon :closable="false" /><div class="ops-metrics">
  <el-card shadow="never"><span>缓存类型</span><strong>PostgreSQL</strong><small>权威 Data Plane</small></el-card><el-card shadow="never"><span>行情行数</span><strong>{{ data.cache.row_count }}</strong><small>{{ data.cache.status }}</small></el-card><el-card shadow="never"><span>覆盖分组</span><strong>{{ data.cache.groups.length }}</strong><small>来源 × 资产类型</small></el-card><el-card shadow="never"><span>Redis</span><strong>not used</strong><small>无兼容层</small></el-card>
</div><el-card shadow="never"><template #header><strong>覆盖审计</strong></template><el-table :data="data.cache.groups" empty-text="缓存为空，等待已验证迁移或增量同步"><el-table-column prop="data_source" label="来源" width="140" /><el-table-column prop="asset_type" label="资产类型" width="140" /><el-table-column prop="symbol_count" label="标的数" width="110" /><el-table-column prop="row_count" label="行数" width="110" /><el-table-column prop="date_min" label="起始日期" min-width="130" /><el-table-column prop="date_max" label="结束日期" min-width="130" /></el-table></el-card></div></template>
