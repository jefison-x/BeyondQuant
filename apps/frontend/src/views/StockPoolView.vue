<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createStockPool, listStockPools } from "@/api/paper";
import type { StockPool } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";

const auth = useAuthStore();
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const pools = ref<Array<Record<string, unknown>>>([]);
const selected = ref<Record<string, unknown> | null>(null);
const name = ref("");
const poolType = ref<"custom" | "index" | "dynamic">("custom");
const description = ref("");
const symbolsText = ref("");
const weightsText = ref("");
const filter = ref<"all" | "custom" | "index" | "dynamic">("all");
const search = ref("");

const POOL_TYPE_LABELS: Record<string, string> = {
  custom: "自建",
  index: "指数",
  dynamic: "动态",
};

const filteredPools = computed(() =>
  pools.value.filter((row) => {
    const matchesType = filter.value === "all" || row.pool_type === filter.value;
    const matchesSearch =
      !search.value ||
      String(row.name ?? "").includes(search.value) ||
      String(row.pool_id ?? "").includes(search.value);
    return matchesType && matchesSearch;
  }),
);

async function loadPools() {
  loading.value = true;
  error.value = "";
  try {
    pools.value = (await listStockPools(auth.token)).pools;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载股票池失败";
  } finally {
    loading.value = false;
  }
}

async function submit() {
  error.value = "";
  const symbols = symbolsText.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!name.value.trim()) {
    ElMessage.warning("请填写股票池名称");
    return;
  }
  if (!symbols.length) {
    ElMessage.warning("请填写成分股");
    return;
  }
  let weights: Record<string, number> | undefined;
  if (weightsText.value.trim()) {
    try {
      const parsed = JSON.parse(weightsText.value) as Record<string, unknown>;
      weights = Object.fromEntries(
        Object.entries(parsed).map(([symbol, value]) => [symbol, Number(value)]),
      );
    } catch {
      ElMessage.error("权重 JSON 格式错误");
      return;
    }
  }
  busy.value = true;
  try {
    const created = await createStockPool(name.value.trim(), symbols, auth.token, {
      poolType: poolType.value,
      description: description.value.trim() || undefined,
      weights,
    });
    selected.value = created.pool as unknown as Record<string, unknown>;
    ElMessage.success("股票池已创建");
    name.value = "";
    description.value = "";
    symbolsText.value = "";
    weightsText.value = "";
    await loadPools();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "创建失败";
  } finally {
    busy.value = false;
  }
}

function select(row: Record<string, unknown>) {
  selected.value = row;
}

onMounted(loadPools);
</script>

<template>
  <section class="stock-page">
    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="card-heading">
          <span class="card-title">创建版本化股票池</span>
          <small class="card-sub">Symbol 以逗号分隔，例如 000001.SZ,600000.SH</small>
        </div>
      </template>
      <el-form label-position="top">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="股票池名称">
              <el-input v-model="name" placeholder="Pool name" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="类型">
              <el-radio-group v-model="poolType">
                <el-radio-button label="custom">自建</el-radio-button>
                <el-radio-button label="index">指数</el-radio-button>
                <el-radio-button label="dynamic">动态</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="description" placeholder="股票池用途或说明" />
        </el-form-item>
        <el-form-item label="成分股">
          <el-input v-model="symbolsText" type="textarea" placeholder="000001.SZ,600000.SH" />
        </el-form-item>
        <el-form-item label="权重（可选 JSON）">
          <el-input v-model="weightsText" type="textarea" :rows="3" placeholder='{"000001.SZ": 0.6, "600000.SH": 0.4}' />
        </el-form-item>
        <el-button type="primary" :loading="busy" @click="submit">创建股票池</el-button>
      </el-form>
    </el-card>

    <p v-if="error" class="page-error">{{ error }}</p>

    <el-card shadow="never" class="top-band">
      <template #header>
        <div class="panel-heading">
          <span class="card-title">股票池列表</span>
          <div class="list-toolbar">
            <el-input v-model="search" placeholder="搜索名称 / ID" clearable />
            <el-radio-group v-model="filter" size="small">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="custom">自建</el-radio-button>
              <el-radio-button label="index">指数</el-radio-button>
              <el-radio-button label="dynamic">动态</el-radio-button>
            </el-radio-group>
            <el-button size="small" @click="loadPools">刷新</el-button>
          </div>
        </div>
      </template>
      <div v-if="loading" class="base-loading">加载中...</div>
      <el-empty v-else-if="!filteredPools.length" description="暂无股票池" />
      <el-table v-else :data="filteredPools" highlight-current-row @current-change="select">
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ POOL_TYPE_LABELS[String(row.pool_type ?? "custom")] ?? row.pool_type }}</template>
        </el-table-column>
        <el-table-column label="成分" width="80" align="right">
          <template #default="{ row }">{{ Array.isArray(row.symbols) ? row.symbols.length : 0 }}</template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="description" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="更新时间" min-width="160">
          <template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template>
        </el-table-column>
      </el-table>

      <div class="mobile-list">
        <el-card
          v-for="row in filteredPools"
          :key="String(row.pool_id)"
          shadow="never"
          class="mobile-card"
          @click="select(row)"
        >
          <div class="mobile-card-head">
            <strong>{{ row.name }}</strong>
            <el-tag size="small">{{ POOL_TYPE_LABELS[String(row.pool_type ?? "custom")] ?? row.pool_type }}</el-tag>
          </div>
          <div class="mobile-card-meta">
            <span>{{ Array.isArray(row.symbols) ? row.symbols.length : 0 }} 只成分</span>
            <span>{{ formatChinaTime(row.created_at) }}</span>
          </div>
        </el-card>
      </div>
    </el-card>

    <el-card v-if="selected" shadow="never" class="top-band">
      <template #header>
        <div class="card-heading">
          <span class="card-title">股票池详情</span>
          <small class="card-sub">{{ String(selected.pool_id ?? "") }}</small>
        </div>
      </template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="名称">{{ selected.name }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ POOL_TYPE_LABELS[String(selected.pool_type ?? "custom")] ?? selected.pool_type }}</el-descriptions-item>
        <el-descriptions-item label="版本">{{ selected.version }}</el-descriptions-item>
        <el-descriptions-item label="说明">{{ selected.description ?? "-" }}</el-descriptions-item>
      </el-descriptions>
      <el-table :data="Array.isArray(selected.symbols) ? selected.symbols.map((symbol: string) => ({ symbol })) : []" size="small">
        <el-table-column prop="symbol" label="成分" min-width="160" />
      </el-table>
      <pre class="quant-result">{{ JSON.stringify(selected.weights ?? {}, null, 2) }}</pre>
    </el-card>
  </section>
</template>

<style scoped>
.panel-heading {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  justify-content: space-between;
}

.list-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.quant-result {
  background: var(--byq-surface-subtle);
  border-radius: var(--byq-radius-sm);
  font-size: 12px;
  margin-top: 0.75rem;
  overflow: auto;
  padding: 0.75rem;
}

.mobile-list {
  display: none;
}

@media (max-width: 900px) {
  .mobile-list {
    display: grid;
    gap: 0.6rem;
    margin-top: 0.75rem;
  }

  .mobile-card {
    cursor: pointer;
  }

  .mobile-card-head {
    align-items: center;
    display: flex;
    gap: 0.5rem;
    justify-content: space-between;
  }

  .mobile-card-meta {
    color: var(--byq-text-muted);
    display: flex;
    font-size: 12px;
    gap: 0.75rem;
    justify-content: space-between;
    margin-top: 0.4rem;
  }
}
</style>
