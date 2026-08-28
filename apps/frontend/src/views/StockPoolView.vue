<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createStockPool,
  deleteStockPool,
  getStockPoolAsOf,
  getStockPool,
  getStockPoolSnapshot,
  listStockPoolReferences,
  listStockPoolSnapshots,
  listStockPools,
  replaceStockPoolSnapshot,
  setStockPoolLifecycle,
  updateStockPoolMetadata,
} from "@/api/paper";
import type { StockPool, StockPoolSnapshot } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";
import { statusLabel } from "@/display";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";
import { createRequestId } from "@/utils/requestId";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const pools = ref<Array<Record<string, unknown>>>([]);
const selected = ref<StockPool | null>(null);
const snapshots = ref<StockPoolSnapshot[]>([]);
const references = ref<Array<Record<string, unknown>>>([]);
const activeTab = ref("overview");
const historicalSnapshot = ref<StockPoolSnapshot | null>(null);
const asOfDate = ref("");
const name = ref("");
const poolType = ref<"custom" | "index" | "dynamic">("custom");
const description = ref("");
const symbolsText = ref("");
const weightsText = ref("");
const filter = ref<"all" | "custom" | "index" | "dynamic">("all");
const search = ref("");
const editName = ref("");
const editDescription = ref("");
const editSymbols = ref("");
const editWeights = ref("");
const editDefinition = ref("{}");
const showCreate = ref(false);
const metadataBaseline = ref("");
const snapshotBaseline = ref("");

const metadataDirty = computed(() => Boolean(selected.value) && JSON.stringify({
  name: editName.value,
  description: editDescription.value,
}) !== metadataBaseline.value);
const snapshotDirty = computed(() => Boolean(selected.value?.pool_type === "custom") && JSON.stringify({
  symbols: editSymbols.value,
  weights: editWeights.value,
  definition: editDefinition.value,
}) !== snapshotBaseline.value);
const createDirty = computed(() => showCreate.value && Boolean(name.value || description.value || symbolsText.value || weightsText.value));
const dirty = computed(() => metadataDirty.value || snapshotDirty.value || createDirty.value);
const { confirmDiscard } = useUnsavedChanges(dirty);

function syncEditBaseline() {
  metadataBaseline.value = JSON.stringify({ name: editName.value, description: editDescription.value });
  snapshotBaseline.value = JSON.stringify({ symbols: editSymbols.value, weights: editWeights.value, definition: editDefinition.value });
}

function closeCreate() {
  if (createDirty.value && !window.confirm("创建内容尚未提交，确定放弃吗？")) return;
  showCreate.value = false;
  name.value = "";
  description.value = "";
  symbolsText.value = "";
  weightsText.value = "";
}

async function refreshPools() {
  if (confirmDiscard()) await loadPools();
}

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
    const requested = typeof route.query.pool === "string" ? route.query.pool : "";
    const target = requested
      ? pools.value.find((row) => String(row.pool_id) === requested) ?? { pool_id: requested }
      : selected.value
        ? pools.value.find((row) => String(row.pool_id) === selected.value?.pool_id)
        : pools.value[0];
    if (target) await select(target, false);
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
    selected.value = created.pool;
    showCreate.value = false;
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

async function select(row: Record<string, unknown>, updateRoute = true) {
  if (updateRoute && !confirmDiscard()) return;
  const poolId = String(row.pool_id ?? "");
  if (!poolId) return;
  busy.value = true;
  try {
    const [detail, history, refs] = await Promise.all([
      getStockPool(poolId, auth.token),
      listStockPoolSnapshots(poolId, auth.token),
      listStockPoolReferences(poolId, auth.token),
    ]);
    selected.value = detail.pool;
    snapshots.value = history.snapshots;
    references.value = refs.references;
    editName.value = detail.pool.name ?? "";
    editDescription.value = detail.pool.description ?? "";
    editSymbols.value = (detail.pool.snapshot?.members ?? []).map((item) => item.symbol).join(",");
    editWeights.value = JSON.stringify(detail.pool.weights ?? {}, null, 2);
    editDefinition.value = JSON.stringify(detail.pool.snapshot?.definition ?? {}, null, 2);
    syncEditBaseline();
    if (updateRoute && route.query.pool !== poolId) {
      await router.replace({ path: route.path, query: { ...route.query, pool: poolId } });
    }
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载股票池详情失败");
  } finally {
    busy.value = false;
  }
}

async function saveMetadata() {
  if (!selected.value?.pool_id || !selected.value.metadata_version) return;
  busy.value = true;
  try {
    const result = await updateStockPoolMetadata(selected.value.pool_id, {
      name: editName.value.trim(),
      description: editDescription.value.trim(),
      expected_metadata_version: selected.value.metadata_version,
    }, auth.token);
    selected.value = result.pool;
    await loadPools();
    ElMessage.success("目录信息已保存，成员快照未改变");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "目录信息保存失败");
  } finally {
    busy.value = false;
  }
}

async function saveSnapshot() {
  if (!selected.value?.pool_id || !selected.value.current_snapshot_id) return;
  busy.value = true;
  try {
    const symbols = editSymbols.value.split(",").map((item) => item.trim()).filter(Boolean);
    const weights = editWeights.value.trim() ? JSON.parse(editWeights.value) : {};
    const definition = editDefinition.value.trim() ? JSON.parse(editDefinition.value) : {};
    await replaceStockPoolSnapshot(selected.value.pool_id, {
      expected_current_snapshot_id: selected.value.current_snapshot_id,
      idempotency_key: createRequestId(), symbols, weights, definition,
    }, auth.token);
    await select({ pool_id: selected.value.pool_id }, false);
    await loadPools();
    ElMessage.success("新成员快照已保存");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "快照保存失败");
  } finally {
    busy.value = false;
  }
}

async function changeLifecycle(status: "active" | "inactive") {
  if (!selected.value?.pool_id) return;
  if (!confirmDiscard()) return;
  await setStockPoolLifecycle(selected.value.pool_id, status, status === "active" ? "用户重新启用" : "用户暂停新引用", auth.token);
  await select({ pool_id: selected.value.pool_id }, false);
  await loadPools();
}

async function removeSelected() {
  if (!selected.value?.pool_id) return;
  if (!confirmDiscard()) return;
  await ElMessageBox.confirm("删除后不可恢复，但历史快照与已有引用会保留。", "删除股票池", { type: "warning" });
  await deleteStockPool(selected.value.pool_id, auth.token);
  selected.value = null;
  await loadPools();
  ElMessage.success("股票池已删除并保留历史快照");
}

async function inspectSnapshot(row: StockPoolSnapshot) {
  if (!selected.value?.pool_id) return;
  historicalSnapshot.value = (await getStockPoolSnapshot(selected.value.pool_id, row.snapshot_id, auth.token)).snapshot;
}

async function resolveAsOf() {
  if (!selected.value?.pool_id || !asOfDate.value) return;
  const tradeDate = asOfDate.value.replaceAll("-", "");
  historicalSnapshot.value = (await getStockPoolAsOf(selected.value.pool_id, tradeDate, auth.token)).snapshot;
}

function toggleHistorical(open: boolean) {
  if (!open) historicalSnapshot.value = null;
}

function returnToConversation() {
  const session = typeof route.query.session === "string" ? route.query.session : "";
  void router.push({ path: "/agent", query: session ? { session } : {} });
}

onMounted(loadPools);
</script>

<template>
  <section class="stock-page">
    <el-dialog v-model="showCreate" title="创建版本化股票池" width="min(680px, 94vw)">
      <p class="dialog-intro">创建自建股票池；指数与动态池只能由可信 BYQ 数据或计算边界生成。</p>
      <el-form label-position="top">
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="股票池名称">
              <el-input v-model="name" placeholder="Pool name" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="类型">
              <el-tag type="primary">自建</el-tag>
              <small class="card-sub">指数/动态池只能由可信 BYQ 数据或计算边界生成</small>
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
      </el-form>
      <template #footer>
        <el-button @click="closeCreate">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submit">创建股票池</el-button>
      </template>
    </el-dialog>

    <p v-if="error" class="page-error">{{ error }}</p>

    <ManagementWorkspace
      eyebrow="核心研究资产"
      title="股票池目录与快照"
      description="管理可变目录身份、不可变成员快照以及下游冻结引用。"
      catalog-label="股票池"
      :count="filteredPools.length"
      @return="returnToConversation"
    >
      <template #return>返回投研对话</template>
      <template #actions>
        <el-button @click="refreshPools">刷新</el-button>
        <el-button type="primary" @click="showCreate = true">新建股票池</el-button>
      </template>
      <template #summary>目录变化不改写历史成员快照</template>
      <template #catalog>
      <el-card shadow="never" class="stock-list-pane">
      <template #header>
        <div class="panel-heading">
          <span class="card-title">股票池列表</span>
          <div class="list-toolbar">
            <el-input v-model="search" placeholder="搜索名称 / ID" clearable />
            <el-radio-group v-model="filter" size="small">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="custom">自建</el-radio-button>
              <el-radio-button value="index">指数</el-radio-button>
              <el-radio-button value="dynamic">动态</el-radio-button>
            </el-radio-group>
          </div>
        </div>
      </template>
      <div v-if="loading" class="base-loading" role="status" aria-live="polite">加载中...</div>
      <el-empty v-else-if="!filteredPools.length" description="暂无股票池" />
      <el-table v-else class="desktop-catalog-table" :data="filteredPools" highlight-current-row @current-change="select">
        <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">{{ POOL_TYPE_LABELS[String(row.pool_type ?? "custom")] ?? row.pool_type }}</template>
        </el-table-column>
        <el-table-column label="成分" width="80" align="right">
          <template #default="{ row }">{{ Number(row.member_count ?? 0) }}</template>
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
            <span>{{ Number(row.member_count ?? 0) }} 只成分</span>
            <span>{{ formatChinaTime(row.created_at) }}</span>
          </div>
        </el-card>
      </div>
      </el-card>
      </template>

      <template #detail>
      <el-card v-if="selected" shadow="never" class="stock-detail-pane" v-loading="busy">
      <template #header>
        <div class="card-heading">
          <span class="card-title">股票池详情</span>
          <small class="card-sub">{{ String(selected.pool_id ?? "") }}</small>
        </div>
      </template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="概览" name="overview">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="类型">{{ POOL_TYPE_LABELS[selected.pool_type ?? "custom"] }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag>{{ statusLabel(selected.status) }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="当前版本">{{ selected.version }}</el-descriptions-item>
            <el-descriptions-item label="成员数">{{ selected.member_count }}</el-descriptions-item>
          </el-descriptions>
          <el-form label-position="top" class="detail-form">
            <el-form-item label="名称"><el-input v-model="editName" /></el-form-item>
            <el-form-item label="说明"><el-input v-model="editDescription" /></el-form-item>
            <span class="edit-state" aria-live="polite">{{ metadataDirty ? "目录信息有未保存更改" : "目录信息已保存" }}</span>
            <el-button :disabled="!metadataDirty || busy" @click="saveMetadata">保存目录信息</el-button>
            <el-button v-if="selected.status === 'active'" @click="changeLifecycle('inactive')">停用</el-button>
            <el-button v-else-if="selected.status === 'inactive'" type="primary" @click="changeLifecycle('active')">启用</el-button>
            <el-button type="danger" plain @click="removeSelected">删除</el-button>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="成员与权重" name="members">
          <el-alert v-if="selected.pool_type !== 'custom'" title="可信指数/动态池为只读，成员由 BYQ 数据或计算边界生成。" type="info" :closable="false" />
          <el-form v-else label-position="top">
            <el-form-item label="成分股（逗号分隔）"><el-input v-model="editSymbols" type="textarea" :rows="4" /></el-form-item>
            <el-form-item label="完整权重 JSON（留空表示等权/无权重）"><el-input v-model="editWeights" type="textarea" :rows="5" /></el-form-item>
            <span class="edit-state" aria-live="polite">{{ snapshotDirty ? "快照内容有未保存更改" : "快照内容已保存" }}</span>
            <el-button type="primary" :disabled="!snapshotDirty || busy" @click="saveSnapshot">创建新快照</el-button>
          </el-form>
          <el-table :data="selected.snapshot?.members ?? []" size="small">
            <el-table-column prop="symbol" label="成分" min-width="160" />
            <el-table-column prop="weight" label="权重" min-width="140" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="定义与筛选" name="definition">
          <el-alert title="筛选条件用于解释候选来源；只有已持久化成员才是授权范围。" type="info" :closable="false" />
          <el-input v-model="editDefinition" type="textarea" :rows="10" :readonly="selected.pool_type !== 'custom'" />
          <el-button v-if="selected.pool_type === 'custom'" type="primary" class="detail-action" :disabled="!snapshotDirty || busy" @click="saveSnapshot">随新快照保存</el-button>
        </el-tab-pane>
        <el-tab-pane label="来源与引用" name="provenance">
          <pre class="quant-result">{{ JSON.stringify(selected.snapshot?.provenance ?? {}, null, 2) }}</pre>
          <el-table :data="references" size="small" empty-text="暂无下游引用">
            <el-table-column prop="domain" label="领域" />
            <el-table-column prop="snapshot_id" label="快照" min-width="260" show-overflow-tooltip />
            <el-table-column prop="reference_count" label="引用数" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="快照历史" name="history">
          <div v-if="selected.pool_type === 'index'" class="as-of-row">
            <el-date-picker v-model="asOfDate" value-format="YYYY-MM-DD" placeholder="选择 as-of 日期" />
            <el-button @click="resolveAsOf">按日期解析（无前视）</el-button>
          </div>
          <el-table :data="snapshots" size="small" @row-click="inspectSnapshot">
            <el-table-column prop="version_number" label="版本" width="80" />
            <el-table-column prop="member_count" label="成员" width="80" />
            <el-table-column prop="weight_mode" label="权重模式" width="120" />
            <el-table-column prop="effective_trade_date" label="生效日" width="110" />
            <el-table-column prop="membership_fingerprint" label="成员指纹" min-width="220" show-overflow-tooltip />
            <el-table-column label="创建时间" min-width="170"><template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
      </el-card>
      <el-card v-else shadow="never" class="stock-detail-pane detail-empty">
        <el-empty description="选择一个股票池查看成员、来源与快照历史" />
      </el-card>
      </template>
    </ManagementWorkspace>

    <el-dialog :model-value="historicalSnapshot !== null" title="历史快照（只读）" width="min(760px, 92vw)" @update:model-value="toggleHistorical">
      <el-descriptions v-if="historicalSnapshot" :column="2" border>
        <el-descriptions-item label="版本">v{{ historicalSnapshot.version_number }}</el-descriptions-item>
        <el-descriptions-item label="生效日">{{ historicalSnapshot.effective_trade_date ?? "-" }}</el-descriptions-item>
        <el-descriptions-item label="成员指纹" :span="2">{{ historicalSnapshot.membership_fingerprint }}</el-descriptions-item>
      </el-descriptions>
      <el-table v-if="historicalSnapshot" :data="historicalSnapshot.members ?? []" size="small">
        <el-table-column prop="symbol" label="成分" />
        <el-table-column prop="weight" label="权重" />
      </el-table>
    </el-dialog>
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

.dialog-intro { color: var(--byq-text-muted); font-size: 12px; margin: 0 0 14px; }
.edit-state { color: var(--byq-text-muted); display: inline-block; font-size: 12px; margin: 0 8px 8px 0; }
.stock-list-pane, .stock-detail-pane { min-width: 0; }
.detail-empty { min-height: 360px; display: grid; place-items: center; }

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

.detail-form {
  margin-top: 1rem;
}

.detail-action {
  margin-top: 0.75rem;
}

.as-of-row {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.mobile-list {
  display: none;
}

@media (max-width: 900px) {
  .desktop-catalog-table {
    display: none;
  }

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
    min-width: 0;
  }

  .mobile-card-head strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

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
