<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  createDynamicStockPool,
  createIndexStockPool,
  createStockPool,
  deleteStockPool,
  diffStockPoolSnapshots,
  getStockPoolAsOf,
  getStockPool,
  getStockPoolProducer,
  getStockPoolReadiness,
  getStockPoolSnapshot,
  listIndexPoolCatalog,
  listStockPoolMaterializations,
  listStockPoolMembers,
  listStockPoolReferences,
  listStockPoolSnapshots,
  listStockPools,
  previewDynamicStockPool,
  refreshIndexStockPool,
  replaceStockPoolSnapshot,
  setStockPoolLifecycle,
  updateStockPoolMetadata,
  updateDynamicStockPoolDefinition,
} from "@/api/paper";
import type { DynamicStockPoolPreview, DynamicStockPoolRule, IndexPoolCatalogItem, StockPool, StockPoolMaterializationRun, StockPoolMember, StockPoolProducerDefinition, StockPoolReadiness, StockPoolSnapshot, StockPoolSnapshotDiff } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { formatChinaTime } from "@/time";
import { statusLabel } from "@/display";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import ManagementActionBar from "@/components/layout/ManagementActionBar.vue";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";
import { createRequestId } from "@/utils/requestId";
import { useFilteredPagination } from "@/composables/useFilteredPagination";

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
const indexCatalog = ref<IndexPoolCatalogItem[]>([]);
const availableIndexCount = computed(() => indexCatalog.value.filter((item) => item.selectable).length);
const materializations = ref<StockPoolMaterializationRun[]>([]);
const producer = ref<StockPoolProducerDefinition | null>(null);
const readiness = ref<StockPoolReadiness | null>(null);
const snapshotDiff = ref<StockPoolSnapshotDiff | null>(null);
const members = ref<StockPoolMember[]>([]);
const memberTotal = ref(0);
const memberPage = ref(1);
const memberQuery = ref("");
const memberLoading = ref(false);
const fullMembersLoaded = ref(false);
const MEMBER_PAGE_SIZE = 20;
const activeTab = ref("overview");
const historicalSnapshot = ref<StockPoolSnapshot | null>(null);
const asOfDate = ref("");
const name = ref("");
const poolType = ref<"custom" | "index" | "dynamic">("custom");
const indexSymbol = ref("");
const requestedAsOf = ref("");
const dynamicMinimumMarketCap = ref<number | null>(null);
const dynamicTopN = ref(50);
const dynamicRanking = ref("daily_basic.total_mv");
const dynamicDirection = ref<"asc" | "desc">("desc");
const dynamicCadence = ref<"manual" | "daily" | "weekly" | "monthly">("manual");
const dynamicWeightMode = ref<"unweighted" | "equal_weight">("equal_weight");
const dynamicActivate = ref(true);
const dynamicPreview = ref<DynamicStockPoolPreview | null>(null);
const dynamicRuleText = ref("");
const dynamicRuleBaseline = ref("");
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
const dynamicDefinitionDirty = computed(() => selected.value?.pool_type === "dynamic" && dynamicRuleText.value !== dynamicRuleBaseline.value);
const createDirty = computed(() => showCreate.value && Boolean(name.value || description.value || symbolsText.value || weightsText.value || indexSymbol.value || requestedAsOf.value || poolType.value !== "custom"));
const dirty = computed(() => metadataDirty.value || snapshotDirty.value || dynamicDefinitionDirty.value || createDirty.value);
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
  indexSymbol.value = "";
  requestedAsOf.value = "";
  dynamicPreview.value = null;
  poolType.value = "custom";
}

function buildDynamicRule(): DynamicStockPoolRule {
  const filters: DynamicStockPoolRule["filters"] = [];
  if (dynamicMinimumMarketCap.value !== null) {
    filters.push({ field: "daily_basic.total_mv", operator: "gte", value: dynamicMinimumMarketCap.value });
  }
  return {
    schema_version: "dynamic-stock-pool-rule.v1",
    base_universe: { kind: "security_master" },
    filters,
    ranking: { field: dynamicRanking.value, direction: dynamicDirection.value },
    top_n: dynamicTopN.value,
    missing_policy: "exclude",
    weight_mode: dynamicWeightMode.value,
    cadence: dynamicCadence.value,
  };
}

async function previewDynamic() {
  busy.value = true;
  try {
    dynamicPreview.value = await previewDynamicStockPool(
      buildDynamicRule(), requestedAsOf.value?.replaceAll("-", "") || undefined, auth.token,
    );
    ElMessage.success(`预览完成：${dynamicPreview.value.member_count} 只成分（非权威快照）`);
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "动态股票池预览失败");
  } finally {
    busy.value = false;
  }
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
const poolPages = useFilteredPagination(filteredPools, (row) => `${row.name ?? ""} ${row.pool_id ?? ""}`, 20);

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

async function loadIndexCatalog() {
  try {
    indexCatalog.value = (await listIndexPoolCatalog(auth.token)).indices;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "加载指数目录失败";
  }
}

async function submit() {
  error.value = "";
  const symbols = symbolsText.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (poolType.value !== "index" && !name.value.trim()) {
    ElMessage.warning("请填写股票池名称");
    return;
  }
  if (poolType.value === "custom" && !symbols.length) {
    ElMessage.warning("请填写成分股");
    return;
  }
  let weights: Record<string, number> | undefined;
  if (poolType.value === "custom" && weightsText.value.trim()) {
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
    if (poolType.value === "index" && !indexSymbol.value) {
      ElMessage.warning("请选择指数");
      return;
    }
    if (poolType.value === "index" && !indexCatalog.value.some(
      (item) => item.index_symbol === indexSymbol.value && item.selectable,
    )) {
      ElMessage.warning("该指数尚无已验证的完整权重快照");
      return;
    }
    const created = poolType.value === "index"
      ? await createIndexStockPool({
          index_symbol: indexSymbol.value,
          name: name.value.trim() || undefined,
          description: description.value.trim() || undefined,
          requested_as_of: requestedAsOf.value?.replaceAll("-", "") || undefined,
        }, auth.token)
      : poolType.value === "dynamic"
        ? await createDynamicStockPool({
            name: name.value.trim(), description: description.value.trim() || undefined,
            rule: buildDynamicRule(), requested_as_of: requestedAsOf.value?.replaceAll("-", "") || undefined,
            activate: dynamicActivate.value,
          }, auth.token)
        : await createStockPool(name.value.trim(), symbols, auth.token, {
          poolType: "custom", description: description.value.trim() || undefined, weights,
        });
    selected.value = created.pool;
    showCreate.value = false;
    ElMessage.success(poolType.value === "custom" ? "股票池已创建" : `${poolType.value === "index" ? "指数" : "动态"}池已创建，正在生成成分快照`);
    name.value = "";
    description.value = "";
    symbolsText.value = "";
    weightsText.value = "";
    indexSymbol.value = "";
    requestedAsOf.value = "";
    poolType.value = "custom";
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
    const [detail, history, refs, readinessResult] = await Promise.all([
      getStockPool(poolId, auth.token, { includeMembers: false }),
      listStockPoolSnapshots(poolId, auth.token),
      listStockPoolReferences(poolId, auth.token),
      getStockPoolReadiness(poolId, auth.token),
    ]);
    selected.value = detail.pool;
    members.value = [];
    memberTotal.value = detail.pool.member_count ?? 0;
    memberPage.value = 1;
    memberQuery.value = "";
    fullMembersLoaded.value = false;
    snapshots.value = history.snapshots;
    references.value = refs.references;
    readiness.value = readinessResult.readiness;
    snapshotDiff.value = null;
    if (detail.pool.pool_type === "index" || detail.pool.pool_type === "dynamic") {
      const [definitionResult, runsResult] = await Promise.all([
        getStockPoolProducer(poolId, auth.token),
        listStockPoolMaterializations(poolId, auth.token),
      ]);
      producer.value = definitionResult.producer;
      materializations.value = runsResult.runs;
      dynamicRuleText.value = detail.pool.pool_type === "dynamic" ? JSON.stringify(definitionResult.producer.definition, null, 2) : "";
      dynamicRuleBaseline.value = dynamicRuleText.value;
    } else {
      producer.value = null;
      materializations.value = [];
    }
    editName.value = detail.pool.name ?? "";
    editDescription.value = detail.pool.description ?? "";
    editSymbols.value = "";
    editWeights.value = "{}";
    editDefinition.value = JSON.stringify(detail.pool.snapshot?.definition ?? {}, null, 2);
    syncEditBaseline();
    if (activeTab.value === "members") await loadMemberPage();
    if (updateRoute && route.query.pool !== poolId) {
      await router.replace({ path: route.path, query: { ...route.query, pool: poolId } });
    }
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载股票池详情失败");
  } finally {
    busy.value = false;
  }
}

async function loadMemberPage() {
  if (!selected.value?.pool_id || activeTab.value !== "members") return;
  memberLoading.value = true;
  try {
    const result = await listStockPoolMembers(selected.value.pool_id, auth.token, {
      query: memberQuery.value,
      limit: MEMBER_PAGE_SIZE,
      offset: (memberPage.value - 1) * MEMBER_PAGE_SIZE,
    });
    members.value = result.members;
    memberTotal.value = result.total;
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载股票池成员失败");
  } finally {
    memberLoading.value = false;
  }
}

async function loadFullMembersForEditing() {
  if (!selected.value?.pool_id || selected.value.pool_type !== "custom") return;
  memberLoading.value = true;
  try {
    const detail = await getStockPool(selected.value.pool_id, auth.token);
    selected.value = detail.pool;
    const allMembers = detail.pool.snapshot?.members ?? [];
    editSymbols.value = allMembers.map((item) => item.symbol).join(",");
    editWeights.value = JSON.stringify(
      Object.fromEntries(allMembers.filter((item) => item.weight !== null).map((item) => [item.symbol, item.weight])),
      null,
      2,
    );
    fullMembersLoaded.value = true;
    syncEditBaseline();
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "加载完整成员失败");
  } finally {
    memberLoading.value = false;
  }
}

let memberSearchTimer: number | undefined;
watch(activeTab, (tab) => {
  if (tab === "members") void loadMemberPage();
});
watch(memberPage, () => void loadMemberPage());
watch(memberQuery, () => {
  window.clearTimeout(memberSearchTimer);
  memberSearchTimer = window.setTimeout(() => {
    memberPage.value = 1;
    void loadMemberPage();
  }, 250);
});

onBeforeUnmount(() => window.clearTimeout(memberSearchTimer));

async function compareLatestSnapshots() {
  if (!selected.value?.pool_id || snapshots.value.length < 2) return;
  busy.value = true;
  try {
    snapshotDiff.value = (await diffStockPoolSnapshots(
      selected.value.pool_id, snapshots.value[1].snapshot_id, snapshots.value[0].snapshot_id, auth.token,
    )).diff;
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "快照差异加载失败");
  } finally {
    busy.value = false;
  }
}

async function saveDynamicDefinition(status: "draft" | "active" | "paused" = producer.value?.status ?? "draft") {
  if (!selected.value?.pool_id || selected.value.pool_type !== "dynamic" || !producer.value) return;
  busy.value = true;
  try {
    const rule = JSON.parse(dynamicRuleText.value) as DynamicStockPoolRule;
    const result = await updateDynamicStockPoolDefinition(selected.value.pool_id, {
      rule, status, expected_version: producer.value.version,
    }, auth.token);
    producer.value = result.producer;
    dynamicRuleText.value = JSON.stringify(result.producer.definition, null, 2);
    dynamicRuleBaseline.value = dynamicRuleText.value;
    await select({ pool_id: selected.value.pool_id }, false);
    ElMessage.success(status === "active" ? "动态规则已激活" : status === "paused" ? "动态规则已暂停" : "动态规则草稿已保存");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "动态规则保存失败");
  } finally {
    busy.value = false;
  }
}

async function refreshIndexPool() {
  if (!selected.value?.pool_id || !["index", "dynamic"].includes(selected.value.pool_type ?? "")) return;
  busy.value = true;
  try {
    await refreshIndexStockPool(selected.value.pool_id, undefined, auth.token);
    await select({ pool_id: selected.value.pool_id }, false);
    ElMessage.success("物化刷新任务已提交");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "提交刷新失败");
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

onMounted(async () => Promise.all([loadPools(), loadIndexCatalog()]));
</script>

<template>
  <section class="stock-page">
    <el-dialog v-model="showCreate" title="创建版本化股票池" width="min(680px, 94vw)">
      <p class="dialog-intro">自建池由你维护成员；指数池和动态池由可信 Data Worker 生成不可变快照。</p>
      <el-form label-position="top">
        <el-form-item label="股票池类型">
          <el-radio-group v-model="poolType">
            <el-radio-button value="custom">自建股票池</el-radio-button>
            <el-radio-button value="index">指数型股票池</el-radio-button>
            <el-radio-button value="dynamic">动态股票池</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-row :gutter="14">
          <el-col :xs="24" :sm="12">
            <el-form-item label="股票池名称">
              <el-input v-model="name" placeholder="Pool name" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="类型">
              <el-tag type="primary">{{ POOL_TYPE_LABELS[poolType] }}</el-tag>
              <small class="card-sub">{{ poolType === "custom" ? "成员由用户维护" : "成员和权重只读，由可信 Data Worker 生成" }}</small>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="description" placeholder="股票池用途或说明" />
        </el-form-item>
        <template v-if="poolType === 'index'">
          <el-form-item label="指数">
            <el-select v-model="indexSymbol" filterable placeholder="选择已具备完整权重的指数" style="width: 100%">
              <el-option
                v-for="item in indexCatalog"
                :key="item.index_symbol"
                :label="`${item.name}（${item.index_symbol}）`"
                :value="item.index_symbol"
                :disabled="!item.selectable"
              >
                <span>{{ item.name }}（{{ item.index_symbol }}）</span>
                <small class="catalog-option-meta">
                  {{ item.selectable ? `${item.member_count}只 · ${item.latest_snapshot_date}` : "等待可信数据同步" }}
                </small>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="截至日期（可选）">
            <el-date-picker v-model="requestedAsOf" value-format="YYYY-MM-DD" placeholder="默认使用当前日期前最新完整快照" />
          </el-form-item>
          <el-alert
            v-if="availableIndexCount < indexCatalog.length"
            :title="`当前 ${availableIndexCount}/${indexCatalog.length} 个指数具备已验证快照；其余指数将在数据中心可信同步完成后开放。`"
            type="warning"
            :closable="false"
          />
        </template>
        <template v-if="poolType === 'dynamic'">
          <el-alert title="规则仅支持 BYQ 白名单字段和运算符，不执行 Python、SQL、URL、插件或模型表达式。" type="info" :closable="false" />
          <el-row :gutter="14" class="dynamic-form-row">
            <el-col :xs="24" :sm="12">
              <el-form-item label="最低总市值（万元，可选）">
                <el-input-number v-model="dynamicMinimumMarketCap" data-testid="dynamic-min-market-cap" :min="0" :step="10000" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="最多成分数">
                <el-input-number v-model="dynamicTopN" data-testid="dynamic-top-n" :min="1" :max="500" controls-position="right" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="14">
            <el-col :xs="24" :sm="12"><el-form-item label="排序字段"><el-select v-model="dynamicRanking" data-testid="dynamic-ranking" style="width:100%"><el-option label="总市值" value="daily_basic.total_mv" /><el-option label="市净率" value="daily_basic.pb" /><el-option label="滚动市盈率" value="daily_basic.pe_ttm" /><el-option label="换手率" value="daily_basic.turnover_rate" /><el-option label="20日平均成交额" value="window.avg_amount_20" /></el-select></el-form-item></el-col>
            <el-col :xs="24" :sm="12"><el-form-item label="排序方向"><el-select v-model="dynamicDirection" style="width:100%"><el-option label="从高到低" value="desc" /><el-option label="从低到高" value="asc" /></el-select></el-form-item></el-col>
          </el-row>
          <el-row :gutter="14">
            <el-col :xs="24" :sm="12"><el-form-item label="刷新频率"><el-select v-model="dynamicCadence" style="width:100%"><el-option label="手动" value="manual" /><el-option label="每日交易日" value="daily" /><el-option label="每周" value="weekly" /><el-option label="每月" value="monthly" /></el-select></el-form-item></el-col>
            <el-col :xs="24" :sm="12"><el-form-item label="权重模式"><el-select v-model="dynamicWeightMode" style="width:100%"><el-option label="等权" value="equal_weight" /><el-option label="无权重" value="unweighted" /></el-select></el-form-item></el-col>
          </el-row>
          <el-form-item label="截至日期（可选）"><el-date-picker v-model="requestedAsOf" value-format="YYYY-MM-DD" placeholder="默认使用当前日期前最新完整交易日" /></el-form-item>
          <el-form-item label="创建后立即激活"><el-switch v-model="dynamicActivate" /></el-form-item>
          <div class="preview-actions"><el-button data-testid="dynamic-preview" :loading="busy" @click="previewDynamic">预览规则结果</el-button><span v-if="dynamicPreview">非权威预览：{{ dynamicPreview.member_count }} 只 · 数据日 {{ dynamicPreview.effective_trade_date }}</span></div>
          <el-table v-if="dynamicPreview" :data="dynamicPreview.members" size="small" max-height="180"><el-table-column prop="symbol" label="预览成分" /><el-table-column prop="weight" label="权重" /></el-table>
        </template>
        <el-form-item v-if="poolType === 'custom'" label="成分股">
          <el-input v-model="symbolsText" type="textarea" placeholder="000001.SZ,600000.SH" />
        </el-form-item>
        <el-form-item v-if="poolType === 'custom'" label="权重（可选 JSON）">
          <el-input v-model="weightsText" type="textarea" :rows="3" placeholder='{"000001.SZ": 0.6, "600000.SH": 0.4}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeCreate">取消</el-button>
        <el-button type="primary" :loading="busy" @click="submit">{{ poolType === "custom" ? "创建股票池" : "创建并生成快照" }}</el-button>
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
      <ListFilterPagination v-else v-model:page="poolPages.page.value" query="" :page-size="poolPages.pageSize.value" :total="poolPages.total.value" label="股票池分页" hide-search>
      <el-table class="desktop-catalog-table" :data="poolPages.pageItems.value" highlight-current-row @current-change="select">
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
          v-for="row in poolPages.pageItems.value"
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
      </ListFilterPagination>
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
      <ManagementActionBar
        :description="selected.status === 'active' ? '停用后不再接受新的研究、回测或模拟操盘引用；历史快照和已有引用保持可复现。' : '重新启用后可接受新的下游引用；删除仍只建立不可恢复的目录墓碑。'"
      >
        <template #status><el-tag size="small">{{ statusLabel(selected.status) }}</el-tag></template>
        <el-button v-if="selected.pool_type !== 'custom'" :loading="busy" @click="refreshIndexPool">刷新成分</el-button>
        <el-button v-if="selected.status === 'active'" :disabled="busy" @click="changeLifecycle('inactive')">停用</el-button>
        <el-button v-else-if="selected.status === 'inactive'" type="primary" :disabled="busy" @click="changeLifecycle('active')">启用</el-button>
        <el-button type="danger" plain :disabled="busy" @click="removeSelected">删除</el-button>
      </ManagementActionBar>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="概览" name="overview" lazy>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="类型">{{ POOL_TYPE_LABELS[selected.pool_type ?? "custom"] }}</el-descriptions-item>
            <el-descriptions-item label="状态"><el-tag>{{ statusLabel(selected.status) }}</el-tag></el-descriptions-item>
            <el-descriptions-item label="当前版本">{{ selected.version }}</el-descriptions-item>
            <el-descriptions-item label="成员数">{{ selected.member_count }}</el-descriptions-item>
            <el-descriptions-item label="数据就绪度"><el-tag>{{ readiness?.state ?? "-" }}</el-tag></el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type !== 'custom'" label="物化状态">
              <el-tag>{{ materializations[0]?.status ?? "等待任务" }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'index'" label="指数代码">
              {{ producer?.definition?.index_symbol ?? "-" }}
            </el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'dynamic'" label="规则状态">{{ producer?.status ?? "-" }}</el-descriptions-item>
          </el-descriptions>
          <el-form label-position="top" class="detail-form">
            <el-form-item label="名称"><el-input v-model="editName" /></el-form-item>
            <el-form-item label="说明"><el-input v-model="editDescription" /></el-form-item>
            <span class="edit-state" aria-live="polite">{{ metadataDirty ? "目录信息有未保存更改" : "目录信息已保存" }}</span>
            <el-button :disabled="!metadataDirty || busy" @click="saveMetadata">保存目录信息</el-button>
          </el-form>
          <section v-if="selected.pool_type === 'dynamic' && producer" class="dynamic-definition">
            <h3 class="section-title">封闭动态规则</h3>
            <el-input v-model="dynamicRuleText" data-testid="dynamic-rule-json" type="textarea" :rows="12" aria-label="动态股票池规则 JSON" />
            <p class="edit-state">{{ dynamicDefinitionDirty ? "规则有未保存更改" : `规则 v${producer.version} 已保存` }}</p>
            <div class="button-row"><el-button :disabled="!dynamicDefinitionDirty" @click="saveDynamicDefinition('draft')">保存草稿</el-button><el-button type="primary" @click="saveDynamicDefinition('active')">校验并激活</el-button><el-button @click="saveDynamicDefinition('paused')">暂停调度</el-button></div>
          </section>
        </el-tab-pane>
        <el-tab-pane label="成员与权重" name="members" lazy>
          <el-alert v-if="selected.pool_type !== 'custom'" title="可信指数/动态池为只读，成员由 BYQ 数据或计算边界生成。" type="info" :closable="false" />
          <div v-else-if="!fullMembersLoaded" class="member-edit-loader">
            <span>成员清单按页加载；编辑前需显式读取当前完整快照，避免误覆盖未显示成员。</span>
            <el-button :loading="memberLoading" @click="loadFullMembersForEditing">加载完整成员并编辑</el-button>
          </div>
          <el-form v-else label-position="top">
            <el-form-item label="成分股（逗号分隔）"><el-input v-model="editSymbols" type="textarea" :rows="4" /></el-form-item>
            <el-form-item label="完整权重 JSON（留空表示等权/无权重）"><el-input v-model="editWeights" type="textarea" :rows="5" /></el-form-item>
            <span class="edit-state" aria-live="polite">{{ snapshotDirty ? "快照内容有未保存更改" : "快照内容已保存" }}</span>
            <el-button type="primary" :disabled="!snapshotDirty || busy" @click="saveSnapshot">创建新快照</el-button>
          </el-form>
          <ListFilterPagination
            v-model:query="memberQuery"
            v-model:page="memberPage"
            :page-size="MEMBER_PAGE_SIZE"
            :total="memberTotal"
            placeholder="按股票代码或中文名称筛选"
            label="股票池成员分页"
          >
            <el-table v-loading="memberLoading" :data="members" size="small" empty-text="暂无匹配成员">
              <el-table-column prop="symbol" label="股票代码" min-width="140" />
              <el-table-column prop="name" label="股票名称（中文）" min-width="160">
                <template #default="{ row }">{{ row.name || "名称待基础资料同步" }}</template>
              </el-table-column>
              <el-table-column prop="weight" label="权重" min-width="120" />
            </el-table>
          </ListFilterPagination>
        </el-tab-pane>
        <el-tab-pane label="定义与筛选" name="definition" lazy>
          <el-alert title="筛选条件用于解释候选来源；只有已持久化成员才是授权范围。" type="info" :closable="false" />
          <el-input v-model="editDefinition" type="textarea" :rows="10" :readonly="selected.pool_type !== 'custom'" />
          <el-button v-if="selected.pool_type === 'custom'" type="primary" class="detail-action" :disabled="!snapshotDirty || busy" @click="saveSnapshot">随新快照保存</el-button>
          <el-descriptions v-if="selected.pool_type === 'index' && producer" :column="1" border class="detail-action">
            <el-descriptions-item label="定义版本">v{{ producer.version }}</el-descriptions-item>
            <el-descriptions-item label="刷新策略">{{ producer.schedule.cadence }}</el-descriptions-item>
            <el-descriptions-item label="定义指纹">{{ producer.definition_fingerprint }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
        <el-tab-pane label="来源与引用" name="provenance" lazy>
          <pre class="quant-result">{{ JSON.stringify(selected.snapshot?.provenance ?? {}, null, 2) }}</pre>
          <el-table :data="references" size="small" empty-text="暂无下游引用">
            <el-table-column prop="domain" label="领域" />
            <el-table-column prop="snapshot_id" label="快照" min-width="260" show-overflow-tooltip />
            <el-table-column prop="reference_count" label="引用数" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="快照历史" name="history" lazy>
          <div class="button-row">
            <el-button :disabled="snapshots.length < 2" @click="compareLatestSnapshots">比较最近两个快照</el-button>
            <span v-if="snapshots.length < 2" class="edit-state">至少需要两个不可变快照</span>
          </div>
          <el-descriptions v-if="snapshotDiff" :column="3" border class="detail-action" data-testid="stock-pool-snapshot-diff">
            <el-descriptions-item label="新增">{{ snapshotDiff.added.length }}</el-descriptions-item>
            <el-descriptions-item label="移除">{{ snapshotDiff.removed.length }}</el-descriptions-item>
            <el-descriptions-item label="权重变化">{{ snapshotDiff.weight_changed.length }}</el-descriptions-item>
            <el-descriptions-item label="保留成员">{{ snapshotDiff.retained_count }}</el-descriptions-item>
            <el-descriptions-item label="新增代码" :span="2">{{ snapshotDiff.added.map((item) => item.symbol).join("、") || "-" }}</el-descriptions-item>
          </el-descriptions>
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
          <template v-if="selected.pool_type !== 'custom'">
            <h3 class="section-title">物化任务</h3>
            <el-table :data="materializations" size="small" empty-text="暂无任务">
              <el-table-column prop="status" label="状态" width="130" />
              <el-table-column prop="requested_as_of" label="请求日期" width="110" />
              <el-table-column prop="effective_trade_date" label="实际快照日" width="110" />
              <el-table-column prop="member_count" label="成员" width="80" />
              <el-table-column prop="error_message" label="说明" min-width="180" show-overflow-tooltip />
              <el-table-column label="创建时间" min-width="170"><template #default="{ row }">{{ formatChinaTime(row.created_at) }}</template></el-table-column>
            </el-table>
          </template>
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
        <el-table-column prop="symbol" label="股票代码" />
        <el-table-column prop="name" label="股票名称（中文）"><template #default="{ row }">{{ row.name || "-" }}</template></el-table-column>
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
.catalog-option-meta { color: var(--byq-text-muted); float: right; margin-left: 18px; }
.section-title { font-size: 14px; margin: 20px 0 10px; }
.dynamic-form-row { margin-top: 14px; }
.preview-actions { align-items: center; color: var(--byq-text-muted); display: flex; flex-wrap: wrap; gap: 10px; margin: 4px 0 12px; }
.dynamic-definition { border-top: 1px solid var(--byq-border-subtle); margin-top: 18px; padding-top: 2px; }
.edit-state { color: var(--byq-text-muted); display: inline-block; font-size: 12px; margin: 0 8px 8px 0; }
.member-edit-loader { align-items: center; background: var(--byq-surface-subtle); border-radius: 8px; color: var(--byq-text-muted); display: flex; gap: 12px; justify-content: space-between; margin-bottom: 12px; padding: 10px 12px; }
.stock-list-pane, .stock-detail-pane { min-width: 0; }
.detail-empty { min-height: 360px; display: grid; place-items: center; }

.list-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

:deep(.list-toolbar .el-radio-button.is-active .el-radio-button__inner) {
  color: var(--byq-on-brand);
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
  getStockPoolProducer,
  listIndexPoolCatalog,
  listStockPoolMaterializations,
  refreshIndexStockPool,
