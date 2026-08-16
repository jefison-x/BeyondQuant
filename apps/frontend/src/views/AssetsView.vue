<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { exportAssets, getAssetSummary, importAssets } from "@/api/settings";
import type { AssetSummary } from "@/api/types";

const router = useRouter();
const importInput = ref<HTMLInputElement | null>(null);
const loading = ref(true);
const error = ref("");
const summary = ref<AssetSummary | null>(null);
const busy = ref(false);

const assetStats = computed(() => ({
  strategies: summary.value?.summary.strategies ?? 0,
  backtests: summary.value?.summary.backtests ?? 0,
  pools: summary.value?.summary.pools ?? 0,
  paperAccounts: summary.value?.summary.paper_accounts ?? 0,
  poolSymbols: (summary.value?.pools ?? []).reduce((sum, pool) => {
    const symbols = Array.isArray(pool.symbols) ? pool.symbols : [];
    return sum + symbols.length;
  }, 0),
}));

async function loadAssets() {
  loading.value = true;
  error.value = "";
  try {
    summary.value = await getAssetSummary();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "读取用户资产失败";
  } finally {
    loading.value = false;
  }
}

onMounted(loadAssets);

function go(path: string) {
  router.push(path);
}

async function downloadBundle() {
  busy.value = true;
  try {
    const bundle = await exportAssets();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `beyondquant-assets-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    ElMessage.success("资产包已导出");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "资产包导出失败");
  } finally {
    busy.value = false;
  }
}

function openImport() {
  importInput.value?.click();
}

async function handleImport(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  busy.value = true;
  try {
    const bundle = JSON.parse(await file.text()) as Record<string, unknown>;
    await ElMessageBox.confirm("将按当前所有者导入股票池和模拟账户；策略与回测资产需要重新验证或重算，将被跳过。", "确认导入资产包", {
      confirmButtonText: "继续导入",
      cancelButtonText: "取消",
      type: "warning",
    });
    const report = await importAssets(bundle);
    ElMessage.success(`已导入 ${report.imported.pools} 个股票池、${report.imported.paper_accounts} 个模拟账户`);
    await loadAssets();
  } catch (exc) {
    if (exc !== "cancel" && exc !== "close") {
      ElMessage.error(exc instanceof Error ? exc.message : "资产包格式错误或导入失败");
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="my-space-page">
    <input ref="importInput" type="file" accept="application/json,.json" hidden @change="handleImport" />

    <section class="stats-strip">
      <el-card shadow="never"><div class="stat-label">策略</div><strong>{{ assetStats.strategies }}</strong></el-card>
      <el-card shadow="never"><div class="stat-label">股票池</div><strong>{{ assetStats.pools }}</strong><small>{{ assetStats.poolSymbols }} 只成分</small></el-card>
      <el-card shadow="never"><div class="stat-label">回测</div><strong>{{ assetStats.backtests }}</strong></el-card>
      <el-card shadow="never"><div class="stat-label">模拟账户</div><strong>{{ assetStats.paperAccounts }}</strong></el-card>
    </section>

    <section class="asset-toolbar">
      <div class="toolbar-title">
        <div class="page-card-title">用户资产</div>
        <div class="page-card-sub">策略、股票池、回测与模拟账户</div>
      </div>
      <div class="toolbar-actions">
        <el-button :loading="busy" @click="downloadBundle">导出资产包</el-button>
        <el-button type="primary" :loading="busy" @click="openImport">导入资产包</el-button>
      </div>
    </section>

    <div v-if="loading" class="base-loading">加载中...</div>
    <div v-else-if="error" class="base-error">{{ error }}</div>
    <template v-else>
      <el-card shadow="never">
        <template #header><div class="panel-heading"><div><strong>我的策略</strong></div><el-button link type="primary" @click="go('/strategy')">前往策略管理</el-button></div></template>
        <el-table :data="summary?.strategies ?? []" size="small">
          <el-table-column prop="artifact_id" label="策略版本" min-width="260" show-overflow-tooltip />
          <el-table-column prop="kind" label="类型" width="150" />
          <el-table-column prop="status" label="状态" width="120" />
        </el-table>
        <el-empty v-if="!summary?.strategies.length" description="暂无策略" :image-size="60" />
      </el-card>

      <el-card shadow="never">
        <template #header><div class="panel-heading"><div><strong>我的股票池</strong></div><el-button link type="primary" @click="go('/stock-pool')">前往股票管理</el-button></div></template>
        <el-table :data="summary?.pools ?? []" size="small">
          <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
          <el-table-column prop="pool_id" label="ID" min-width="180" show-overflow-tooltip />
          <el-table-column label="成分" width="90" align="right">
            <template #default="scope">{{ Array.isArray(scope.row.symbols) ? scope.row.symbols.length : 0 }}</template>
          </el-table-column>
          <el-table-column prop="version" label="版本" width="90" />
        </el-table>
        <el-empty v-if="!summary?.pools.length" description="暂无股票池" :image-size="60" />
      </el-card>

      <el-card shadow="never">
        <template #header><div class="panel-heading"><div><strong>我的回测</strong></div><el-button link type="primary" @click="go('/backtest')">前往回测管理</el-button></div></template>
        <el-table :data="summary?.backtests ?? []" size="small">
          <el-table-column prop="job_id" label="任务" min-width="220" show-overflow-tooltip />
          <el-table-column prop="status" label="状态" width="120" />
          <el-table-column prop="created_at" label="创建时间" width="170" />
        </el-table>
        <el-empty v-if="!summary?.backtests.length" description="暂无回测任务" :image-size="60" />
      </el-card>
    </template>
  </section>
</template>

<style scoped>
.my-space-page {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.stats-strip {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat-label {
  color: var(--byq-text-muted);
  font-size: 12px;
}

.asset-toolbar,
.panel-heading {
  align-items: center;
  display: flex;
  gap: 1rem;
  justify-content: space-between;
}

.toolbar-title {
  min-width: 0;
}

.toolbar-actions {
  display: flex;
  gap: 0.5rem;
}

.page-card-title {
  font-size: 16px;
  font-weight: 700;
}

.page-card-sub {
  color: var(--byq-text-muted);
  font-size: 12px;
  margin-top: 0.3rem;
}

@media (max-width: 900px) {
  .stats-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .asset-toolbar,
  .panel-heading {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
