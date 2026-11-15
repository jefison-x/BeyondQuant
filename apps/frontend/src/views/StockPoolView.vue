<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  PoolCreationRejected,
  submitPoolCreation,
  reconcilePoolCreation,
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
import type { DynamicStockPoolPreview, DynamicStockPoolRule, IndexPoolCatalogItem, SecurityRecord, StockPool, StockPoolMaterializationRun, StockPoolMember, StockPoolProducerDefinition, StockPoolReadiness, StockPoolSnapshot, StockPoolSnapshotDiff } from "@/api/types";
import { useAuthStore } from "@/stores/auth";
import { listSecurities } from "@/api/dataCenter";
import { formatChinaTime } from "@/time";
import { statusLabel } from "@/display";
import IndexSnapshotPreparation from "@/components/IndexSnapshotPreparation.vue";
import ManagementWorkspace from "@/components/layout/ManagementWorkspace.vue";
import ManagementActionBar from "@/components/layout/ManagementActionBar.vue";
import ListFilterPagination from "@/components/ui/ListFilterPagination.vue";
import { useUnsavedChanges } from "@/composables/useUnsavedChanges";
import { beginPoolSubmission, readPoolSubmission, finishPoolSubmission, type PoolSubmission } from "@/api/poolSubmission";
import { createRequestId } from "@/utils/requestId";
import { useFilteredPagination } from "@/composables/useFilteredPagination";

const auth = useAuthStore();
const pendingCreation = ref<PoolSubmission | null>(null);
function creationScope() {
  if (!auth.user?.workspace?.workspace_id) throw new Error("请先登录并选择工作区");
  return JSON.stringify([auth.user.subject, auth.user.workspace.workspace_id]);
}
async function recoverCreation(retry = false) {
  if (!pendingCreation.value || busy.value) return;
  busy.value = true; error.value = "";
  try {
    const original = pendingCreation.value;
    const scope = creationScope();
    const result = retry
      ? {state:"confirmed", ...(await submitPoolCreation(original.kind, {...original.payload, idempotency_key:original.key}, auth.token))}
      : await reconcilePoolCreation(original.kind, original.key, auth.token);
    if (result.state !== "confirmed" || !("pool" in result)) { error.value = "尚未确认原提交，可使用原请求重试；不要更换提交键。"; return; }
    if (creationScope() !== scope) throw new Error("工作区已改变，请重新核对原请求。");
    finishPoolSubmission(scope, original.key);
    pendingCreation.value = null;
    selected.value = result.pool;
    showCreate.value = false;
    await loadPools();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "原请求未确认";
  }
  finally { busy.value = false; }
}
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
type MemberDraft = { symbol: string; name: string; weightPercent: number | null };
type DynamicFilterDraft = { filter: DynamicStockPoolRule["filters"][number]; managed: boolean };
type SecurityOption = Pick<SecurityRecord, "symbol" | "name">;
const createSymbols = ref<string[]>([]);
const editMemberSymbols = ref<string[]>([]);
const createMembers = ref<MemberDraft[]>([]);
const editMembers = ref<MemberDraft[]>([]);
const securityOptions = ref<SecurityOption[]>([]);
const securitySearchLoading = ref(false);
const securitySearchError = ref("");
const securitySearchQuery = ref("");
const manualCodeAllowed = computed(() => /^\d{6}\.(SH|SZ|BJ)$/.test(securitySearchQuery.value));
let securitySearchRequest = 0;
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
const indexTrackingMode = ref<"follow_index" | "historical_snapshot">("follow_index");
const indexDefinitionKnown = computed(() => selected.value?.pool_type === "index"
  && producer.value?.pool_id === selected.value.pool_id);
const isHistoricalIndex = computed(() => selected.value?.pool_type === "index"
  && indexDefinitionKnown.value && producer.value?.definition?.tracking_mode === "historical_snapshot");
const canRefreshPool = computed(() => selected.value?.pool_type === "dynamic"
  || (indexDefinitionKnown.value && !isHistoricalIndex.value));
const requestedAsOf = ref("");
const dynamicMinimumMarketCap = ref<number | null>(null);
const dynamicIndustry = ref("");
const dynamicPeTtmMaximum = ref<number | null>(null);
const dynamicPbMaximum = ref<number | null>(null);
const dynamicDividendYieldMinimum = ref<number | null>(null);
const dynamicNetProfitYoyMinimum = ref<number | null>(null);
const dynamicTopN = ref(50);
const dynamicRanking = ref<string | null>("daily_basic.total_mv");
const dynamicDirection = ref<"asc" | "desc">("desc");
const dynamicCadence = ref<"manual" | "daily" | "weekly" | "monthly">("manual");
const dynamicWeightMode = ref<"unweighted" | "equal_weight">("equal_weight");
const dynamicActivate = ref(true);
const dynamicPreview = ref<DynamicStockPoolPreview | null>(null);
const dynamicRuleText = ref("");
const dynamicRuleBaseline = ref("");
const dynamicRuleError = ref("");
const dynamicRuleDraft = ref<DynamicStockPoolRule>(emptyDynamicRule());
const dynamicFilterDraft = ref<DynamicFilterDraft[]>([]);
let dynamicPreviewRequestGeneration = 0;

function invalidateDynamicPreview() {
  dynamicPreviewRequestGeneration += 1;
  dynamicPreview.value = null;
}

watch([dynamicRuleText, requestedAsOf], invalidateDynamicPreview, { flush: "sync" });

let successfulPoolCreation = false;
const description = ref("");
const filter = ref<"all" | "custom" | "index" | "dynamic">("all");
const search = ref("");
const editName = ref("");
const editDescription = ref("");
const editDefinition = ref("{}");
const showCreate = ref(false);
const metadataBaseline = ref("");
const snapshotBaseline = ref("");

const metadataDirty = computed(() => Boolean(selected.value) && JSON.stringify({
  name: editName.value,
  description: editDescription.value,
}) !== metadataBaseline.value);
const snapshotDirty = computed(() => Boolean(selected.value?.pool_type === "custom") && JSON.stringify({
  members: editMembers.value,
  definition: editDefinition.value,
}) !== snapshotBaseline.value);
const dynamicDefinitionDirty = computed(() => !showCreate.value && selected.value?.pool_type === "dynamic" && dynamicRuleText.value !== dynamicRuleBaseline.value);
const createDirty = computed(() => showCreate.value && Boolean(name.value || description.value || createMembers.value.length || indexSymbol.value || requestedAsOf.value || poolType.value !== "custom"));
const dirty = computed(() => metadataDirty.value || snapshotDirty.value || dynamicDefinitionDirty.value || createDirty.value);
const { confirmDiscard } = useUnsavedChanges(dirty);

function syncEditBaseline() {
  metadataBaseline.value = JSON.stringify({ name: editName.value, description: editDescription.value });
  snapshotBaseline.value = JSON.stringify({ members: editMembers.value, definition: editDefinition.value });
}

function memberDraftsFor(symbols: string[], existing: MemberDraft[]): MemberDraft[] {
  const previous = new Map(existing.map((member) => [member.symbol, member]));
  return symbols.map((symbol) => {
    const current = previous.get(symbol);
    const searched = securityOptions.value.find((item) => item.symbol === symbol);
    return {
      symbol,
      name: searched?.name || current?.name || "",
      weightPercent: current?.weightPercent ?? null,
    };
  });
}

function setEqualWeights(rows: MemberDraft[]) {
  if (!rows.length) return;
  // Allocate integer hundredths of a percentage so the visible values total
  // 100.00% exactly, including when the number of members does not divide 100.
  const totalHundredths = 10_000;
  const each = Math.floor(totalHundredths / rows.length);
  const remainder = totalHundredths % rows.length;
  rows.forEach((row, index) => {
    row.weightPercent = (each + (index < remainder ? 1 : 0)) / 100;
  });
}

function clearWeights(rows: MemberDraft[]) {
  rows.forEach((row) => { row.weightPercent = null; });
}

function setCreateEqualWeights() { setEqualWeights(createMembers.value); }
function clearCreateWeights() { clearWeights(createMembers.value); }
function setEditEqualWeights() { setEqualWeights(editMembers.value); }
function clearEditWeights() { clearWeights(editMembers.value); }

function syncCreateMembers(symbols = createSymbols.value) {
  const directorySymbols = new Set(securityOptions.value.map((item) => item.symbol));
  const invalidSymbols = symbols.filter((symbol) => !directorySymbols.has(symbol) && !/^\d{6}\.(SH|SZ|BJ)$/.test(symbol));
  if (invalidSymbols.length) {
    ElMessage.warning("名称只能从已同步目录中选择；手动添加时请输入六位股票代码和交易所后缀，例如 600036.SH。");
    symbols = symbols.filter((symbol) => directorySymbols.has(symbol) || /^\d{6}\.(SH|SZ|BJ)$/.test(symbol));
  }
  createSymbols.value = symbols;
  createMembers.value = memberDraftsFor(symbols, createMembers.value);
}

function syncEditMembers(symbols = editMemberSymbols.value) {
  const directorySymbols = new Set(securityOptions.value.map((item) => item.symbol));
  const invalidSymbols = symbols.filter((symbol) => !directorySymbols.has(symbol) && !/^\d{6}\.(SH|SZ|BJ)$/.test(symbol));
  if (invalidSymbols.length) {
    ElMessage.warning("名称只能从已同步目录中选择；手动添加时请输入六位股票代码和交易所后缀，例如 600036.SH。");
    symbols = symbols.filter((symbol) => directorySymbols.has(symbol) || /^\d{6}\.(SH|SZ|BJ)$/.test(symbol));
  }
  editMemberSymbols.value = symbols;
  editMembers.value = memberDraftsFor(symbols, editMembers.value);
}

async function searchSecurities(query: string) {
  const request = ++securitySearchRequest;
  securitySearchError.value = "";
  const normalizedQuery = query.trim();
  securitySearchQuery.value = normalizedQuery;
  if (!normalizedQuery) {
    securityOptions.value = [];
    securitySearchLoading.value = false;
    return;
  }
  securityOptions.value = [];
  securitySearchLoading.value = true;
  try {
    const result = await listSecurities({ query: normalizedQuery, limit: 30 });
    if (request !== securitySearchRequest) return;
    securityOptions.value = result.securities.map(({ symbol, name }) => ({ symbol, name }));
    createMembers.value = memberDraftsFor(createSymbols.value, createMembers.value);
    editMembers.value = memberDraftsFor(editMemberSymbols.value, editMembers.value);
  } catch (cause) {
    if (request === securitySearchRequest) {
      securitySearchError.value = cause instanceof Error ? cause.message : "股票搜索失败";
    }
  } finally {
    if (request === securitySearchRequest) securitySearchLoading.value = false;
  }
}

function stockOptionLabel(item: SecurityOption) {
  return `${item.name || "名称待同步"}（${item.symbol}）`;
}

function openSecurityDataCenter() {
  if (auth.isAdmin) void router.push("/settings/system/data");
}

function stockOptionsFor(membersToKeep: MemberDraft[]): SecurityOption[] {
  const options = new Map(securityOptions.value.map((item) => [item.symbol, item]));
  for (const member of membersToKeep) {
    if (!options.has(member.symbol)) options.set(member.symbol, { symbol: member.symbol, name: member.name || "名称待同步" });
  }
  return [...options.values()];
}

function weightToPercent(weight: string | null | undefined): number | null {
  if (weight === null || weight === undefined || weight === "") return null;
  const value = Number(weight);
  return Number.isFinite(value) ? value * 100 : null;
}

function formatPoolWeight(weight: unknown) {
  if (weight === null || weight === undefined || weight === "") return "未设置";
  const value = Number(weight);
  return Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : String(weight);
}

function memberWeightMap(rows: MemberDraft[]): Record<string, number> {
  if (rows.every((row) => row.weightPercent === null || row.weightPercent === undefined)) return {};
  if (rows.some((row) => row.weightPercent === null || row.weightPercent === undefined
    || !Number.isFinite(row.weightPercent) || row.weightPercent <= 0 || row.weightPercent > 100)) {
    throw new Error("请为每只股票填写大于 0 的权重，或将全部权重留空。");
  }
  // Match the Product API's 12-decimal fractions without division noise such
  // as 20.01 / 100 producing 0.20010000000000003.
  const weights = Object.fromEntries(rows.map((row) => [row.symbol, Number((row.weightPercent! / 100).toFixed(12))]));
  if (Math.abs(Object.values(weights).reduce((sum, weight) => sum + weight, 0) - 1) > 1e-8) {
    throw new Error("所有股票的权重合计必须为 100%，或将全部权重留空。");
  }
  return weights;
}

function closeCreate() {
  if (createDirty.value && !window.confirm("创建内容尚未提交，确定放弃吗？")) return;
  invalidateDynamicPreview();
  showCreate.value = false;
  name.value = "";
  description.value = "";
  createSymbols.value = [];
  createMembers.value = [];
  indexSymbol.value = "";
  indexTrackingMode.value = "follow_index";
  requestedAsOf.value = "";
  resetDynamicRule();
  poolType.value = "custom";
  restoreDynamicEditorAfterCreateClose();
}

function openCreate() {
  successfulPoolCreation = false;
  invalidateDynamicPreview();
  resetDynamicRule();
  showCreate.value = true;
}

function restoreDynamicEditorAfterCreateClose() {
  if (successfulPoolCreation) {
    successfulPoolCreation = false;
    return;
  }
  if (selected.value?.pool_type === "dynamic" && producer.value?.producer_kind === "dynamic") {
    loadDynamicRuleDefinition(producer.value.definition);
    dynamicRuleBaseline.value = dynamicRuleText.value;
  } else {
    resetDynamicRule();
  }
}

function emptyDynamicRule(): DynamicStockPoolRule {
  return {
    schema_version: "dynamic-stock-pool-rule.v1",
    base_universe: { kind: "security_master" },
    filters: [],
    ranking: { field: "daily_basic.total_mv", direction: "desc" },
    top_n: 50,
    missing_policy: "exclude",
    weight_mode: "equal_weight",
    cadence: "manual",
  };
}

const SIMPLE_DYNAMIC_FILTERS = [
  ["security.industry", "eq"],
  ["daily_basic.total_mv", "gte"],
  ["daily_basic.pe_ttm", "lte"],
  ["daily_basic.pb", "lte"],
  ["daily_basic.dv_ttm", "gte"],
  ["financial.netprofit_yoy", "gte"],
] as const;

function simpleFilterPair(item: DynamicStockPoolRule["filters"][number]) {
  return SIMPLE_DYNAMIC_FILTERS.find(([field, operator]) => item.field === field && item.operator === operator);
}

function isCompatibleSimpleFilter(item: DynamicStockPoolRule["filters"][number]) {
  const simple = simpleFilterPair(item);
  if (!simple) return false;
  return simple[0] === "security.industry"
    ? typeof item.value === "string"
    : typeof item.value === "number" && Number.isFinite(item.value);
}

const dynamicAdvancedConditionNotice = computed(() =>
  dynamicFilterDraft.value.some((item) => !item.managed && Boolean(simpleFilterPair(item.filter))));

function filterValue(rule: DynamicStockPoolRule, field: string, operator: string): string | number | null {
  const item = rule.filters.find((candidate) => candidate.field === field
    && candidate.operator === operator && isCompatibleSimpleFilter(candidate));
  if (field === "security.industry" && operator === "eq") {
    return typeof item?.value === "string" ? item.value : null;
  }
  return typeof item?.value === "number" && Number.isFinite(item.value) ? item.value : null;
}

function loadDynamicRule(rule: DynamicStockPoolRule, text = JSON.stringify(rule, null, 2)) {
  syncingDynamicRule = true;
  dynamicRuleDraft.value = JSON.parse(JSON.stringify(rule)) as DynamicStockPoolRule;
  const managedPairs = new Set<string>();
  dynamicFilterDraft.value = dynamicRuleDraft.value.filters.map((filter) => {
    const simple = simpleFilterPair(filter);
    if (!simple || !isCompatibleSimpleFilter(filter)) return { filter, managed: false };
    const key = `${simple[0]}:${simple[1]}`;
    if (managedPairs.has(key)) return { filter, managed: false };
    managedPairs.add(key);
    return { filter, managed: true };
  });
  const industry = filterValue(rule, "security.industry", "eq");
  const marketCap = filterValue(rule, "daily_basic.total_mv", "gte");
  const peTtm = filterValue(rule, "daily_basic.pe_ttm", "lte");
  const pb = filterValue(rule, "daily_basic.pb", "lte");
  const dividend = filterValue(rule, "daily_basic.dv_ttm", "gte");
  const profitGrowth = filterValue(rule, "financial.netprofit_yoy", "gte");
  dynamicIndustry.value = typeof industry === "string" ? industry : "";
  dynamicMinimumMarketCap.value = typeof marketCap === "number" ? marketCap : null;
  dynamicPeTtmMaximum.value = typeof peTtm === "number" ? peTtm : null;
  dynamicPbMaximum.value = typeof pb === "number" ? pb : null;
  dynamicDividendYieldMinimum.value = typeof dividend === "number" ? dividend : null;
  dynamicNetProfitYoyMinimum.value = typeof profitGrowth === "number" ? profitGrowth : null;
  dynamicTopN.value = Number.isInteger(rule.top_n) ? rule.top_n : 50;
  dynamicRanking.value = rule.ranking?.field ?? "";
  dynamicDirection.value = rule.ranking?.direction ?? "desc";
  dynamicCadence.value = rule.cadence;
  dynamicWeightMode.value = rule.weight_mode;
  dynamicRuleText.value = text;
  dynamicRuleError.value = "";
  syncingDynamicRule = false;
}

function resetDynamicRule() {
  const rule = emptyDynamicRule();
  loadDynamicRule(rule);
  dynamicRuleBaseline.value = dynamicRuleText.value;
  dynamicRuleError.value = "";
}

function parseDynamicRuleText(text: string): DynamicStockPoolRule {
  const parsed: unknown = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("规则必须是 JSON 对象");
  }
  const value = parsed as Record<string, unknown>;
  const has = (key: string) => Object.prototype.hasOwnProperty.call(value, key);
  const ruleKeys = new Set([
    "schema_version", "base_universe", "filters", "ranking", "top_n",
    "missing_policy", "weight_mode", "cadence",
  ]);
  if (Object.keys(parsed).some((key) => !ruleKeys.has(key))) {
    throw new Error("规则包含不支持的顶层字段");
  }
  const schemaVersion = has("schema_version") ? value.schema_version : "dynamic-stock-pool-rule.v1";
  if (schemaVersion !== "dynamic-stock-pool-rule.v1") {
    throw new Error("规则版本无效");
  }

  const rawBase = value.base_universe;
  if (!rawBase || typeof rawBase !== "object" || Array.isArray(rawBase)) {
    throw new Error("基础股票范围格式无效");
  }
  const base = rawBase as Record<string, unknown>;
  const baseKeys = Object.keys(base);
  let baseUniverse: DynamicStockPoolRule["base_universe"];
  if (base.kind === "security_master" && baseKeys.every((key) => key === "kind" || key === "snapshot_id")) {
    baseUniverse = { kind: "security_master" };
  } else if (base.kind === "stock_pool_snapshot" && baseKeys.length === 2
    && typeof base.snapshot_id === "string" && Boolean(base.snapshot_id.trim())
    && base.snapshot_id.trim().length <= 96) {
    baseUniverse = { kind: "stock_pool_snapshot", snapshot_id: base.snapshot_id.trim() };
  } else {
    throw new Error("基础股票范围格式无效");
  }

  const rawFilters = has("filters") ? value.filters : [];
  if (!Array.isArray(rawFilters)) throw new Error("筛选条件格式无效");
  const operators = new Set<string>(["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte"]);
  const isOperator = (candidate: unknown): candidate is DynamicStockPoolRule["filters"][number]["operator"] =>
    typeof candidate === "string" && operators.has(candidate);
  const isScalar = (entry: unknown): entry is string | number | boolean =>
    typeof entry === "string" ? Boolean(entry.trim()) && entry.trim().length <= 128
      : typeof entry === "number" ? Number.isFinite(entry)
        : typeof entry === "boolean";
  const filters: DynamicStockPoolRule["filters"] = [];
  for (const item of rawFilters) {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new Error("筛选条件格式无效");
    }
    const filter = item as Record<string, unknown>;
    if (Object.keys(filter).length !== 3 || typeof filter.field !== "string"
      || !isOperator(filter.operator)) {
      throw new Error("筛选条件格式无效");
    }
    if (filter.operator === "in" || filter.operator === "not_in") {
      if (!Array.isArray(filter.value) || filter.value.length === 0 || filter.value.length > 50
        || !filter.value.every(isScalar)) throw new Error("筛选条件格式无效");
      filters.push({
        field: filter.field,
        operator: filter.operator,
        value: filter.value,
      });
    } else {
      if (Array.isArray(filter.value) || !isScalar(filter.value)) throw new Error("筛选条件格式无效");
      filters.push({
        field: filter.field,
        operator: filter.operator,
        value: filter.value,
      });
    }
  }

  const rawRanking = has("ranking") ? value.ranking : null;
  let ranking: DynamicStockPoolRule["ranking"];
  if (rawRanking === null) {
    ranking = null;
  } else if (rawRanking && typeof rawRanking === "object" && !Array.isArray(rawRanking)) {
    const rankingRecord = rawRanking as Record<string, unknown>;
    if (Object.keys(rankingRecord).length !== 2 || typeof rankingRecord.field !== "string"
      || (rankingRecord.direction !== "asc" && rankingRecord.direction !== "desc")) {
      throw new Error("排序规则格式无效");
    }
    ranking = { field: rankingRecord.field, direction: rankingRecord.direction };
  } else {
    throw new Error("排序规则格式无效");
  }

  const topN = value.top_n;
  if (typeof topN !== "number" || !Number.isInteger(topN) || topN < 1 || topN > 500) {
    throw new Error("规则结构不完整；top_n 必须是 1 到 500 的整数");
  }
  const missingPolicy = has("missing_policy") ? value.missing_policy : "exclude";
  const weightMode = has("weight_mode") ? value.weight_mode : "unweighted";
  const cadence = has("cadence") ? value.cadence : "manual";
  if (missingPolicy !== "exclude" || (weightMode !== "unweighted" && weightMode !== "equal_weight")
    || (cadence !== "manual" && cadence !== "daily" && cadence !== "weekly" && cadence !== "monthly")) {
    throw new Error("缺值、权重或更新频率设置无效");
  }
  return {
    schema_version: "dynamic-stock-pool-rule.v1",
    base_universe: baseUniverse,
    filters,
    ranking,
    top_n: topN,
    missing_policy: missingPolicy,
    weight_mode: weightMode,
    cadence,
  };
}

function loadDynamicRuleDefinition(definition: Record<string, unknown>) {
  const text = JSON.stringify(definition, null, 2);
  try {
    loadDynamicRule(parseDynamicRuleText(text), text);
  } catch (cause) {
    loadDynamicRule(emptyDynamicRule(), text);
    dynamicRuleError.value = cause instanceof Error ? cause.message : "动态规则结构无效";
  }
}

function onDynamicRuleTextInput(text: string) {
  dynamicRuleText.value = text;
  try {
    loadDynamicRule(parseDynamicRuleText(text), text);
  } catch (cause) {
    dynamicRuleError.value = cause instanceof Error ? cause.message : "规则 JSON 格式无效";
  }
}

function buildDynamicRuleFromForm(): DynamicStockPoolRule {
  const managedKeys = new Set<string>();
  const filters: DynamicStockPoolRule["filters"] = [];
  const nextFilterDraft: DynamicFilterDraft[] = [];
  const currentValue = (field: string): string | number | null => {
    if (field === "security.industry") return dynamicIndustry.value.trim() || null;
    if (field === "daily_basic.total_mv") return dynamicMinimumMarketCap.value;
    if (field === "daily_basic.pe_ttm") return dynamicPeTtmMaximum.value;
    if (field === "daily_basic.pb") return dynamicPbMaximum.value;
    if (field === "daily_basic.dv_ttm") return dynamicDividendYieldMinimum.value;
    if (field === "financial.netprofit_yoy") return dynamicNetProfitYoyMinimum.value;
    return null;
  };

  for (const draft of dynamicFilterDraft.value) {
    const simple = simpleFilterPair(draft.filter);
    if (!draft.managed || !simple) {
      filters.push(draft.filter);
      nextFilterDraft.push(draft);
      continue;
    }
    const key = `${simple[0]}:${simple[1]}`;
    if (managedKeys.has(key)) {
      filters.push(draft.filter);
      nextFilterDraft.push({ filter: draft.filter, managed: false });
      continue;
    }
    managedKeys.add(key);
    const value = currentValue(simple[0]);
    if (value !== null && value !== "") {
      const updated = { field: simple[0], operator: simple[1], value };
      filters.push(updated);
      nextFilterDraft.push({ filter: updated, managed: true });
    } else {
      // Keep the slot managed even when the visible control is cleared, so an
      // opaque duplicate is never accidentally promoted on the next edit.
      nextFilterDraft.push(draft);
    }
  }

  for (const [field, operator] of SIMPLE_DYNAMIC_FILTERS) {
    const key = `${field}:${operator}`;
    if (managedKeys.has(key)) continue;
    const value = currentValue(field);
    if (value === null || value === "") continue;
    const added = { field, operator, value };
    filters.push(added);
    nextFilterDraft.push({ filter: added, managed: true });
    managedKeys.add(key);
  }
  dynamicFilterDraft.value = nextFilterDraft;
  return {
    ...dynamicRuleDraft.value,
    filters,
    ranking: dynamicRanking.value ? { field: dynamicRanking.value, direction: dynamicDirection.value } : null,
    top_n: dynamicTopN.value,
    missing_policy: "exclude",
    weight_mode: dynamicWeightMode.value,
    cadence: dynamicCadence.value,
  };
}

function syncDynamicRuleFromForm() {
  if (syncingDynamicRule || dynamicRuleError.value) return;
  const rule = buildDynamicRuleFromForm();
  dynamicRuleDraft.value = rule;
  dynamicRuleText.value = JSON.stringify(rule, null, 2);
}

let syncingDynamicRule = false;
watch(() => [
  dynamicIndustry.value, dynamicMinimumMarketCap.value, dynamicPeTtmMaximum.value,
  dynamicPbMaximum.value, dynamicDividendYieldMinimum.value, dynamicNetProfitYoyMinimum.value,
  dynamicTopN.value, dynamicRanking.value, dynamicDirection.value, dynamicCadence.value, dynamicWeightMode.value,
], syncDynamicRuleFromForm, { flush: "sync" });

function buildDynamicRule(): DynamicStockPoolRule {
  if (dynamicRuleError.value) throw new Error(`请先修正规则 JSON：${dynamicRuleError.value}`);
  return buildDynamicRuleFromForm();
}

async function previewDynamic() {
  const requestGeneration = ++dynamicPreviewRequestGeneration;
  dynamicPreview.value = null;
  busy.value = true;
  try {
    const preview = await previewDynamicStockPool(
      buildDynamicRule(), requestedAsOf.value?.replaceAll("-", "") || undefined, auth.token,
    );
    if (requestGeneration !== dynamicPreviewRequestGeneration) return;
    dynamicPreview.value = preview;
    ElMessage.success("筛选预览完成；仅供查看，尚未保存成员版本");
  } catch (exc) {
    if (requestGeneration === dynamicPreviewRequestGeneration) {
      ElMessage.error(exc instanceof Error ? exc.message : "动态股票池预览失败");
    }
  } finally {
    busy.value = false;
  }
}

function manifestCount(manifest: Record<string, unknown> | undefined, path: string[]): number | null {
  let value: unknown = manifest;
  for (const key of path) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    value = (value as Record<string, unknown>)[key];
  }
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

const dynamicPreviewInputCount = computed(() => manifestCount(dynamicPreview.value?.input_manifest, ["base_universe", "row_count"]));
const dynamicPreviewRecordCount = computed(() => manifestCount(dynamicPreview.value?.input_manifest, ["record_count"]));

function formatDynamicPreviewDate(value: string) {
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : value || "日期未提供";
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
  let hadPrevious = false;
  error.value = "";
  if (poolType.value === "index" && indexTrackingMode.value === "historical_snapshot" && !requestedAsOf.value) {
    ElMessage.warning("固定历史快照必须选择截至日期");
    return;
  }
  const symbols = createMembers.value.map((item) => item.symbol);
  if (poolType.value !== "index" && !name.value.trim()) {
    ElMessage.warning("请填写股票池名称");
    return;
  }
  if (poolType.value === "custom" && !symbols.length) {
    ElMessage.warning("请填写成分股");
    return;
  }
  busy.value = true;
  try {
    const weights = poolType.value === "custom" ? memberWeightMap(createMembers.value) : {};
    if (poolType.value === "index" && !indexSymbol.value) {
      ElMessage.warning("请选择指数");
      return;
    }
    if (poolType.value === "index" && !indexCatalog.value.some(
      (item) => item.index_symbol === indexSymbol.value && (indexTrackingMode.value === "historical_snapshot" || item.selectable),
    )) {
      ElMessage.warning("该指数尚无已验证的完整权重快照");
      return;
    }
    const today = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date()).replaceAll("-", "");
    const payload = poolType.value === "index" ? {
      index_symbol:indexSymbol.value, tracking_mode:indexTrackingMode.value, name:name.value.trim() || undefined,
      description:description.value.trim() || undefined, requested_as_of:requestedAsOf.value?.replaceAll("-", "") || today,
    } : poolType.value === "dynamic" ? {
      name:name.value.trim(), description:description.value.trim() || undefined, rule:buildDynamicRule(),
      requested_as_of:requestedAsOf.value?.replaceAll("-", "") || today, activate:dynamicActivate.value,
    } : {name:name.value.trim(), pool_type:"custom", description:description.value.trim() || null, symbols, weights};
    const scope = creationScope();
    hadPrevious = readPoolSubmission(scope) !== null;
    pendingCreation.value = beginPoolSubmission(scope, poolType.value, payload);
    const original = pendingCreation.value;
    const created = await submitPoolCreation(original.kind, {...original.payload, idempotency_key:original.key}, auth.token);
    if (creationScope() !== scope) throw new Error("工作区已改变，请重新核对原请求。");
    finishPoolSubmission(scope, original.key);
    pendingCreation.value = null;
    selected.value = created.pool;
    successfulPoolCreation = true;
    showCreate.value = false;
    ElMessage.success(poolType.value === "custom" ? "股票池已创建" : `${poolType.value === "index" ? "指数" : "动态"}池已创建，正在生成成分快照`);
    name.value = "";
    description.value = "";
    createSymbols.value = [];
    createMembers.value = [];
    indexSymbol.value = "";
    indexTrackingMode.value = "follow_index";
    requestedAsOf.value = "";
    resetDynamicRule();
    poolType.value = "custom";
    await loadPools();
  } catch (exc) {
    if (!hadPrevious && exc instanceof PoolCreationRejected && pendingCreation.value) {
      finishPoolSubmission(creationScope(), pendingCreation.value.key); pendingCreation.value = null;
    }
    if (pendingCreation.value) showCreate.value = false;
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
      if (detail.pool.pool_type === "dynamic") {
        loadDynamicRuleDefinition(definitionResult.producer.definition);
        dynamicRuleBaseline.value = dynamicRuleText.value;
      } else {
        dynamicRuleText.value = "";
        dynamicRuleBaseline.value = "";
      }
    } else {
      producer.value = null;
      materializations.value = [];
      dynamicRuleText.value = "";
      dynamicRuleBaseline.value = "";
    }
    editName.value = detail.pool.name ?? "";
    editDescription.value = detail.pool.description ?? "";
    editMemberSymbols.value = [];
    editMembers.value = [];
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
    editMemberSymbols.value = allMembers.map((item) => item.symbol);
    editMembers.value = allMembers.map((item) => ({
      symbol: item.symbol,
      name: item.name || securityOptions.value.find((option) => option.symbol === item.symbol)?.name || "",
      weightPercent: weightToPercent(item.weight),
    }));
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
    const rule = buildDynamicRule();
    const result = await updateDynamicStockPoolDefinition(selected.value.pool_id, {
      rule, status, expected_version: producer.value.version,
    }, auth.token);
    loadDynamicRuleDefinition(result.producer.definition);
    producer.value = result.producer;
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
  if (!canRefreshPool.value) return;
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
    ElMessage.success("目录信息已保存，成员名单未改变");
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
    const symbols = editMembers.value.map((item) => item.symbol);
    const weights = memberWeightMap(editMembers.value);
    const definition = editDefinition.value.trim() ? JSON.parse(editDefinition.value) : {};
    await replaceStockPoolSnapshot(selected.value.pool_id, {
      expected_current_snapshot_id: selected.value.current_snapshot_id,
      idempotency_key: createRequestId(), symbols, weights, definition,
    }, auth.token);
    await select({ pool_id: selected.value.pool_id }, false);
    await loadPools();
    ElMessage.success("新成员名单版本已保存");
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : "快照保存失败");
  } finally {
    busy.value = false;
  }
}

async function changeLifecycle(status: "active" | "inactive") {
  if (!selected.value?.pool_id) return;
  if (!confirmDiscard()) return;
  await setStockPoolLifecycle(selected.value.pool_id, status, status === "active" ? "用户重新启用" : "用户暂停使用", auth.token);
  await select({ pool_id: selected.value.pool_id }, false);
  await loadPools();
}

async function removeSelected() {
  if (!selected.value?.pool_id) return;
  if (!confirmDiscard()) return;
  await ElMessageBox.confirm("删除后不能恢复，但历史版本和已有研究结果会保留。", "删除股票池", { type: "warning" });
  await deleteStockPool(selected.value.pool_id, auth.token);
  selected.value = null;
  await loadPools();
  ElMessage.success("股票池已删除，历史版本仍可查看");
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

function sendStockPoolToAgent() {
  const pool = selected.value;
  const snapshotId = String(pool?.current_snapshot_id ?? "");
  if (!pool?.pool_id || !snapshotId) return;
  const draft = `请分析股票池“${pool.name}”中的股票，比较估值和分红情况；列明使用的数据日期和来源，缺少数据时说明缺口，不要补造数据。股票池 ID：${pool.pool_id}；成员名单版本 ID：${snapshotId}。`;
  void router.push({ path: "/agent", query: { new: createRequestId(), draft, context: "stock-pool" } });
}

onMounted(async () => {
  if (auth.user) {
    try { pendingCreation.value = readPoolSubmission(creationScope()); }
    catch (cause) { error.value = cause instanceof Error ? cause.message : "原提交记录未确认"; }
  }
  await Promise.all([loadPools(), loadIndexCatalog()]);
});
</script>

<template>
  <section class="stock-page">
    <el-alert v-if="pendingCreation" title="有一笔股票池创建尚未确认" type="warning" :closable="false">
      <p>{{ pendingCreation.payload.name || pendingCreation.payload.index_symbol }} · 原请求保留，刷新页面后仍可核对。</p>
      <el-button :disabled="busy" @click="recoverCreation()">核对原创建请求</el-button>
      <el-button :disabled="busy" @click="recoverCreation(true)">使用原请求重试</el-button>
    </el-alert>
    <el-dialog v-model="showCreate" title="创建版本化股票池" width="min(680px, 94vw)" @close="invalidateDynamicPreview" @closed="restoreDynamicEditorAfterCreateClose">
      <p class="dialog-intro">自建池由你维护成员；指数池和动态池由系统依据已验证数据生成成分，已完成的研究会保留当时使用的股票名单。</p>
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
              <el-input v-model="name" placeholder="例如：银行观察池" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="类型">
              <el-tag type="primary">{{ POOL_TYPE_LABELS[poolType] }}</el-tag>
              <small class="card-sub">{{ poolType === "custom" ? "成员由你维护" : "成员和权重由系统生成，只能查看" }}</small>
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
                :disabled="!item.selectable && indexTrackingMode !== 'historical_snapshot'"
              >
                <span>{{ item.name }}（{{ item.index_symbol }}）</span>
                <small class="catalog-option-meta">
                  {{ item.selectable ? `${item.member_count}只 · ${item.latest_snapshot_date}` : "等待可信数据同步" }}
                </small>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="更新方式">
            <el-radio-group v-model="indexTrackingMode" aria-label="指数股票池更新方式">
              <el-radio-button value="follow_index">持续跟踪指数</el-radio-button>
              <el-radio-button value="historical_snapshot">固定历史快照</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-alert :title="indexTrackingMode === 'historical_snapshot'
            ? '只生成所选日期前的已验证成分快照，之后不会随新成分更新；缺少历史数据时不会使用未来成分替代。'
            : '首次按截至日期生成；后续已验证成分导入后自动更新当前池，已完成的研究仍使用当时的成分名单。'"
            type="info" :closable="false" />
          <el-form-item :label="indexTrackingMode === 'historical_snapshot' ? '截至日期（必选）' : '首次截至日期（可选）'">
            <el-date-picker v-model="requestedAsOf" value-format="YYYY-MM-DD" :placeholder="indexTrackingMode === 'historical_snapshot' ? '选择历史截至日期' : '默认使用当前日期前最新完整快照'" />
          </el-form-item>
          <IndexSnapshotPreparation v-if="indexTrackingMode === 'historical_snapshot'"
            :index-symbol="indexSymbol" :requested-as-of="requestedAsOf" @ready="loadIndexCatalog" />
          <el-alert
            v-if="availableIndexCount < indexCatalog.length"
            :title="`当前 ${availableIndexCount}/${indexCatalog.length} 个指数具备已验证快照；其余指数将在数据中心可信同步完成后开放。`"
            type="warning"
            :closable="false"
          />
        </template>
        <template v-if="poolType === 'dynamic'">
          <el-alert type="info" :closable="false" class="dynamic-data-note">
            <template #title>规则会按“截至日期”前最近的已验证交易日计算</template>
            <p>行业按该日期可见的证券资料精确匹配；估值与股息使用该交易日完整的日线数据；利润同比使用截至日期可见的财务记录。市值单位为万元，市盈率/市净率为倍，股息率和同比增长率为百分比。</p>
            <p>任何筛选或排序所需字段缺失的股票都会被排除。预览是非权威结果，创建时会再次核验；可用日期和结果数量取决于已验证的数据覆盖。</p>
          </el-alert>
          <el-row :gutter="14" class="dynamic-form-row">
            <el-col :xs="24" :sm="12">
              <el-form-item label="行业（可选，精确匹配）">
                <el-input v-model="dynamicIndustry" data-testid="dynamic-create-industry" placeholder="例如：银行" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="最低总市值（万元，可选）">
                <el-input-number v-model="dynamicMinimumMarketCap" data-testid="dynamic-create-min-market-cap" :min="0" :step="10000" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="滚动市盈率上限（倍，可选）">
                <el-input-number v-model="dynamicPeTtmMaximum" data-testid="dynamic-create-pe-ttm-max" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="市净率上限（倍，可选）">
                <el-input-number v-model="dynamicPbMaximum" data-testid="dynamic-create-pb-max" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="近 12 个月股息率至少（%，可选）">
                <el-input-number v-model="dynamicDividendYieldMinimum" data-testid="dynamic-create-dividend-yield-min" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="净利润同比至少（%，可选）">
                <el-input-number v-model="dynamicNetProfitYoyMinimum" data-testid="dynamic-create-net-profit-yoy-min" controls-position="right" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="最多成分数">
                <el-input-number v-model="dynamicTopN" data-testid="dynamic-create-top-n" :min="1" :max="500" controls-position="right" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="14">
            <el-col :xs="24" :sm="12"><el-form-item label="排序字段"><el-select v-model="dynamicRanking" data-testid="dynamic-create-ranking" style="width:100%"><el-option label="按股票代码" value="" /><el-option label="总市值" value="daily_basic.total_mv" /><el-option label="市净率" value="daily_basic.pb" /><el-option label="滚动市盈率" value="daily_basic.pe_ttm" /><el-option label="近 12 个月股息率" value="daily_basic.dv_ttm" /><el-option label="净利润同比" value="financial.netprofit_yoy" /><el-option label="换手率" value="daily_basic.turnover_rate" /><el-option label="20日平均成交额" value="window.avg_amount_20" /></el-select></el-form-item></el-col>
            <el-col :xs="24" :sm="12"><el-form-item label="排序方向"><el-select v-model="dynamicDirection" style="width:100%"><el-option label="从高到低" value="desc" /><el-option label="从低到高" value="asc" /></el-select></el-form-item></el-col>
          </el-row>
          <el-row :gutter="14">
            <el-col :xs="24" :sm="12"><el-form-item label="刷新频率"><el-select v-model="dynamicCadence" style="width:100%"><el-option label="手动" value="manual" /><el-option label="每日交易日" value="daily" /><el-option label="每周" value="weekly" /><el-option label="每月" value="monthly" /></el-select></el-form-item></el-col>
            <el-col :xs="24" :sm="12"><el-form-item label="权重模式"><el-select v-model="dynamicWeightMode" style="width:100%"><el-option label="等权" value="equal_weight" /><el-option label="无权重" value="unweighted" /></el-select></el-form-item></el-col>
          </el-row>
          <el-form-item label="截至日期（可选）"><el-date-picker v-model="requestedAsOf" value-format="YYYY-MM-DD" placeholder="默认使用当前日期前最新完整交易日" /></el-form-item>
          <el-form-item label="创建后立即激活"><el-switch v-model="dynamicActivate" /></el-form-item>
          <details class="dynamic-advanced" data-testid="dynamic-create-advanced">
            <summary>高级规则 JSON（可选）</summary>
            <el-input v-model="dynamicRuleText" data-testid="dynamic-create-rule-json" type="textarea" :rows="10" aria-label="动态股票池高级规则 JSON" @input="onDynamicRuleTextInput" />
            <p class="edit-state">高级规则会与上方常用条件一起提交；不支持的字段和操作会由系统拒绝。</p>
          </details>
          <p v-if="dynamicAdvancedConditionNotice" class="dynamic-rule-notice" data-testid="dynamic-advanced-condition-notice" role="status">重复或类型不兼容的高级条件仍会参与筛选；上方控件不会改写它们，可在高级规则 JSON 中查看。</p>
          <p v-if="dynamicRuleError" class="dynamic-rule-error" data-testid="dynamic-rule-error" role="alert">{{ dynamicRuleError }}</p>
          <div class="preview-actions"><el-button data-testid="dynamic-preview" :disabled="Boolean(dynamicRuleError)" :loading="busy" @click="previewDynamic">预览规则结果</el-button></div>
          <div v-if="dynamicPreview" class="dynamic-preview-result" data-testid="dynamic-preview-result">
            <strong>数据截至 {{ formatDynamicPreviewDate(dynamicPreview.effective_trade_date) }}</strong>
            <span>输入证券 {{ dynamicPreviewInputCount ?? "未提供" }} 只 · 参与计算 {{ dynamicPreviewRecordCount ?? "未提供" }} 只 · 符合 {{ dynamicPreview.member_count }} 只</span>
            <small>缺少筛选或排序字段的股票会被排除；本次预览不证明全市场覆盖，尚未保存成员版本。</small>
          </div>
          <el-table v-if="dynamicPreview" :data="dynamicPreview.members" size="small" max-height="180"><el-table-column prop="symbol" label="预览成分" /><el-table-column label="权重"><template #default="{ row }">{{ formatPoolWeight(row.weight) }}</template></el-table-column></el-table>
        </template>
        <el-form-item v-if="poolType === 'custom'" label="搜索股票">
          <el-select
            v-model="createSymbols"
            multiple
            filterable
            remote
            :allow-create="manualCodeAllowed"
            reserve-keyword
            :debounce="250"
            :remote-method="searchSecurities"
            :loading="securitySearchLoading"
            aria-label="按代码或中文名称搜索股票"
            data-testid="stock-pool-create-search"
            placeholder="输入股票代码或中文名称"
            style="width: 100%"
            @change="syncCreateMembers"
          >
            <el-option v-for="item in stockOptionsFor(createMembers)" :key="item.symbol" :label="stockOptionLabel(item)" :value="item.symbol" />
          </el-select>
          <div v-if="securitySearchQuery && !securitySearchLoading && !securitySearchError && !securityOptions.length" class="security-search-empty">
            <span>当前同步的股票目录中没有“{{ securitySearchQuery }}”的匹配项。可手动添加规范代码（如 600036.SH）；中文名称仅能从目录选择。</span>
            <el-button v-if="auth.isAdmin" link @click="openSecurityDataCenter">查看数据中心</el-button>
          </div>
          <small v-if="securitySearchError" class="card-sub" role="alert">{{ securitySearchError }}</small>
          <small v-else class="card-sub">输入代码或中文名称搜索，可同时选择多只股票；名称未匹配时只接受规范股票代码。</small>
        </el-form-item>
        <el-form-item v-if="poolType === 'custom'" label="成员与权重">
          <p class="member-weight-hint">权重按百分比填写；每只股票须大于 0，合计为 100%。全部留空表示不设置权重。</p>
          <div class="member-weight-actions">
            <el-button size="small" :disabled="busy || !createMembers.length" data-testid="stock-pool-create-equal-weights" @click="setCreateEqualWeights">设为等权</el-button>
            <el-button size="small" :disabled="busy || !createMembers.length" data-testid="stock-pool-create-clear-weights" @click="clearCreateWeights">清空权重</el-button>
            <span>无法均分时，按列表顺序分配 0.01% 余量，合计仍为 100%。</span>
          </div>
          <el-table :data="createMembers" size="small" empty-text="先搜索并选择股票">
            <el-table-column prop="symbol" label="股票代码" min-width="130" />
            <el-table-column label="股票名称（中文）" min-width="140"><template #default="{ row }">{{ row.name || "名称待同步" }}</template></el-table-column>
            <el-table-column label="权重（%）" min-width="150">
              <template #default="{ row }"><el-input-number v-model="row.weightPercent" :min="0" :max="100" :step="1" :precision="2" controls-position="right" placeholder="未设置" /></template>
            </el-table-column>
          </el-table>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="closeCreate">取消</el-button>
        <el-button type="primary" :loading="busy" :disabled="poolType === 'dynamic' && Boolean(dynamicRuleError)" @click="submit">{{ poolType === "custom" ? "创建股票池" : "创建并生成快照" }}</el-button>
      </template>
    </el-dialog>

    <p v-if="error" class="page-error">{{ error }}</p>

    <ManagementWorkspace
      eyebrow="核心研究资产"
      title="股票池目录与快照"
      description="创建和维护股票池，查看成员名单、历史版本和使用记录。"
      catalog-label="股票池"
      :count="filteredPools.length"
      @return="returnToConversation"
    >
      <template #return>返回投研对话</template>
      <template #actions>
        <el-button @click="refreshPools">刷新</el-button>
        <el-button type="primary" @click="openCreate">新建股票池</el-button>
      </template>
      <template #summary>更新名单不会改变已完成研究使用的股票</template>
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
      <div v-else-if="!filteredPools.length && !pools.length" class="pool-empty">
        <el-empty description="还没有股票池" />
        <p>添加几只关注的股票，保存后即可继续研究。</p>
        <el-button type="primary" @click="openCreate">新建股票池</el-button>
      </div>
      <div v-else-if="!filteredPools.length" class="pool-empty">
        <el-empty description="没有找到符合条件的股票池" />
        <p>试试其他名称，或清除当前搜索和类型筛选。</p>
        <el-button @click="search = ''; filter = 'all'">清除筛选</el-button>
      </div>
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
        :description="selected.status === 'active' ? '停用后不能用于新的研究、回测或模拟交易；已有结果仍会保留当时的股票名单。' : '重新启用后可继续使用；删除后不能恢复，但历史研究结果仍会保留。'"
      >
        <template #status><el-tag size="small">{{ statusLabel(selected.status) }}</el-tag></template>
        <el-button v-if="selected.current_snapshot_id" :disabled="busy" data-testid="stock-pool-agent-research" @click="sendStockPoolToAgent">让小巴比较估值与分红</el-button>
        <el-button v-if="canRefreshPool" :loading="busy" @click="refreshIndexPool">刷新成分</el-button>
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
            <el-descriptions-item label="数据就绪度"><el-tag>{{ statusLabel(readiness?.state) }}</el-tag></el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type !== 'custom'" label="物化状态">
              <el-tag>{{ materializations[0]?.status ? statusLabel(materializations[0].status) : "等待任务" }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'index'" label="指数代码">
              {{ producer?.definition?.index_symbol ?? "-" }}
            </el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'index'" label="更新方式">{{ !indexDefinitionKnown ? "待核对" : isHistoricalIndex ? "固定历史快照（不自动更新）" : "持续跟踪指数" }}</el-descriptions-item>
            <el-descriptions-item v-if="isHistoricalIndex" label="名单截至日期">{{ producer?.definition?.frozen_as_of ?? "待核对" }}</el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'index'" label="数据中心成分日">{{ readiness?.source_snapshot_date ?? "待验证" }}</el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'index'" label="当前池成分日">{{ readiness?.current_snapshot_date ?? "待生成" }}</el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type !== 'custom'" label="最近生成时间">{{ readiness?.updated_at ? formatChinaTime(readiness.updated_at) : "尚未完成" }}</el-descriptions-item>
            <el-descriptions-item v-if="selected.pool_type === 'dynamic'" label="规则状态">{{ producer?.status ?? "-" }}</el-descriptions-item>
          </el-descriptions>
          <el-form label-position="top" class="detail-form">
            <el-form-item label="名称"><el-input v-model="editName" /></el-form-item>
            <el-form-item label="说明"><el-input v-model="editDescription" /></el-form-item>
            <span class="edit-state" aria-live="polite">{{ metadataDirty ? "目录信息有未保存更改" : "目录信息已保存" }}</span>
            <el-button :disabled="!metadataDirty || busy" @click="saveMetadata">保存目录信息</el-button>
          </el-form>
          <section v-if="selected.pool_type === 'dynamic' && producer" class="dynamic-definition">
            <h3 class="section-title">动态选股条件</h3>
            <el-alert type="info" :closable="false" class="dynamic-data-note">
              <template #title>常用条件与创建时使用相同的规则</template>
              <p>行业按当次截止日期可见的证券资料精确匹配；估值和股息使用当次完整交易日数据，财务指标按当次截止日期可见记录筛选。市值单位为万元，PE/PB为倍，股息率和净利润同比为百分比。</p>
              <p>规则所需字段或排序值缺失的股票会被排除。修改并保存会生成新的规则版本；已有成员快照不会被改写。</p>
            </el-alert>
            <el-row :gutter="14" class="dynamic-form-row">
              <el-col :xs="24" :sm="12"><el-form-item label="行业（可选，精确匹配）"><el-input v-model="dynamicIndustry" data-testid="dynamic-edit-industry" placeholder="例如：银行" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="最低总市值（万元，可选）"><el-input-number v-model="dynamicMinimumMarketCap" data-testid="dynamic-edit-min-market-cap" :min="0" :step="10000" controls-position="right" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="滚动市盈率上限（倍，可选）"><el-input-number v-model="dynamicPeTtmMaximum" data-testid="dynamic-edit-pe-ttm-max" controls-position="right" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="市净率上限（倍，可选）"><el-input-number v-model="dynamicPbMaximum" data-testid="dynamic-edit-pb-max" controls-position="right" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="近 12 个月股息率至少（%，可选）"><el-input-number v-model="dynamicDividendYieldMinimum" data-testid="dynamic-edit-dividend-yield-min" controls-position="right" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="净利润同比至少（%，可选）"><el-input-number v-model="dynamicNetProfitYoyMinimum" data-testid="dynamic-edit-net-profit-yoy-min" controls-position="right" /></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="最多成分数"><el-input-number v-model="dynamicTopN" data-testid="dynamic-edit-top-n" :min="1" :max="500" controls-position="right" /></el-form-item></el-col>
            </el-row>
            <el-row :gutter="14">
              <el-col :xs="24" :sm="12"><el-form-item label="排序字段"><el-select v-model="dynamicRanking" data-testid="dynamic-edit-ranking" style="width:100%"><el-option label="按股票代码" value="" /><el-option label="总市值" value="daily_basic.total_mv" /><el-option label="市净率" value="daily_basic.pb" /><el-option label="滚动市盈率" value="daily_basic.pe_ttm" /><el-option label="近 12 个月股息率" value="daily_basic.dv_ttm" /><el-option label="净利润同比" value="financial.netprofit_yoy" /><el-option label="换手率" value="daily_basic.turnover_rate" /><el-option label="20日平均成交额" value="window.avg_amount_20" /></el-select></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="排序方向"><el-select v-model="dynamicDirection" style="width:100%"><el-option label="从高到低" value="desc" /><el-option label="从低到高" value="asc" /></el-select></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="刷新频率"><el-select v-model="dynamicCadence" style="width:100%"><el-option label="手动" value="manual" /><el-option label="每日交易日" value="daily" /><el-option label="每周" value="weekly" /><el-option label="每月" value="monthly" /></el-select></el-form-item></el-col>
              <el-col :xs="24" :sm="12"><el-form-item label="权重模式"><el-select v-model="dynamicWeightMode" style="width:100%"><el-option label="等权" value="equal_weight" /><el-option label="无权重" value="unweighted" /></el-select></el-form-item></el-col>
            </el-row>
            <details class="dynamic-advanced" data-testid="dynamic-edit-advanced">
              <summary>高级规则 JSON（可选）</summary>
              <el-input v-model="dynamicRuleText" data-testid="dynamic-rule-json" type="textarea" :rows="10" aria-label="动态股票池高级规则 JSON" @input="onDynamicRuleTextInput" />
              <p class="edit-state">上方条件与高级 JSON 是同一份规则；保存后会进行服务端校验。</p>
            </details>
            <p v-if="dynamicAdvancedConditionNotice" class="dynamic-rule-notice" data-testid="dynamic-advanced-condition-notice" role="status">重复或类型不兼容的高级条件仍会参与筛选；上方控件不会改写它们，可在高级规则 JSON 中查看。</p>
            <p v-if="dynamicRuleError" class="dynamic-rule-error" data-testid="dynamic-rule-error" role="alert">{{ dynamicRuleError }}</p>
            <p class="edit-state">{{ dynamicDefinitionDirty ? "规则有未保存更改" : `规则 v${producer.version} 已保存` }}</p>
            <div class="button-row"><el-button :disabled="!dynamicDefinitionDirty || Boolean(dynamicRuleError) || busy" @click="saveDynamicDefinition('draft')">保存草稿</el-button><el-button type="primary" :disabled="Boolean(dynamicRuleError) || busy" @click="saveDynamicDefinition('active')">校验并激活</el-button><el-button :disabled="Boolean(dynamicRuleError) || busy" @click="saveDynamicDefinition('paused')">暂停调度</el-button></div>
          </section>
        </el-tab-pane>
        <el-tab-pane label="成员与权重" name="members" lazy>
          <el-alert v-if="selected.pool_type !== 'custom'" title="指数与动态股票池的成分由系统生成，不能在这里直接修改。" type="info" :closable="false" />
          <div v-else-if="!fullMembersLoaded" class="member-edit-loader">
            <span>成员清单按页加载；编辑前请先读取全部成员，保存后会创建一个新版本。</span>
            <el-button :loading="memberLoading" @click="loadFullMembersForEditing">加载完整成员并编辑</el-button>
          </div>
          <el-form v-else label-position="top">
            <el-form-item label="搜索股票">
              <el-select
                v-model="editMemberSymbols"
                multiple
                filterable
                remote
                :allow-create="manualCodeAllowed"
                reserve-keyword
                :debounce="250"
                :remote-method="searchSecurities"
                :loading="securitySearchLoading"
                aria-label="按代码或中文名称搜索股票"
                data-testid="stock-pool-edit-search"
                placeholder="输入股票代码或中文名称"
                style="width: 100%"
                @change="syncEditMembers"
              >
                <el-option v-for="item in stockOptionsFor(editMembers)" :key="item.symbol" :label="stockOptionLabel(item)" :value="item.symbol" />
              </el-select>
              <div v-if="securitySearchQuery && !securitySearchLoading && !securitySearchError && !securityOptions.length" class="security-search-empty">
                <span>当前同步的股票目录中没有“{{ securitySearchQuery }}”的匹配项。可手动添加规范代码（如 600036.SH）；中文名称仅能从目录选择。</span>
                <el-button v-if="auth.isAdmin" link @click="openSecurityDataCenter">查看数据中心</el-button>
              </div>
              <small v-if="securitySearchError" class="card-sub" role="alert">{{ securitySearchError }}</small>
            </el-form-item>
            <el-form-item label="成员与权重">
              <p class="member-weight-hint">权重按百分比填写；每只股票须大于 0，合计为 100%。全部留空表示不设置权重。</p>
              <div class="member-weight-actions">
                <el-button size="small" :disabled="busy || !editMembers.length" data-testid="stock-pool-edit-equal-weights" @click="setEditEqualWeights">设为等权</el-button>
                <el-button size="small" :disabled="busy || !editMembers.length" data-testid="stock-pool-edit-clear-weights" @click="clearEditWeights">清空权重</el-button>
                <span>无法均分时，按列表顺序分配 0.01% 余量，合计仍为 100%。</span>
              </div>
              <el-table :data="editMembers" size="small" empty-text="搜索并选择股票，或清空当前名单">
                <el-table-column prop="symbol" label="股票代码" min-width="130" />
                <el-table-column label="股票名称（中文）" min-width="140"><template #default="{ row }">{{ row.name || "名称待同步" }}</template></el-table-column>
                <el-table-column label="权重（%）" min-width="150">
                  <template #default="{ row }"><el-input-number v-model="row.weightPercent" :min="0" :max="100" :step="1" :precision="2" controls-position="right" placeholder="未设置" /></template>
                </el-table-column>
              </el-table>
            </el-form-item>
            <span class="edit-state" aria-live="polite">{{ snapshotDirty ? "成员名单有未保存更改" : "成员名单已保存" }}</span>
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
            <el-table-column label="权重" min-width="120"><template #default="{ row }">{{ formatPoolWeight(row.weight) }}</template></el-table-column>
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
        <el-tab-pane label="来源与使用记录" name="provenance" lazy>
          <pre class="quant-result">{{ JSON.stringify(selected.snapshot?.provenance ?? {}, null, 2) }}</pre>
          <el-table :data="references" size="small" empty-text="暂无使用记录">
            <el-table-column prop="domain" label="使用场景" />
            <el-table-column prop="snapshot_id" label="成员版本" min-width="260" show-overflow-tooltip />
            <el-table-column prop="reference_count" label="使用数" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="历史版本" name="history" lazy>
          <div class="button-row">
            <el-button :disabled="snapshots.length < 2" @click="compareLatestSnapshots">比较最近两个快照</el-button>
            <span v-if="snapshots.length < 2" class="edit-state">至少要有两个历史版本才能比较</span>
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
        <el-empty description="选择一个股票池查看成员名单、来源和历史版本" />
      </el-card>
      </template>
    </ManagementWorkspace>

    <el-dialog :model-value="historicalSnapshot !== null" title="历史成员名单（仅查看）" width="min(760px, 92vw)" @update:model-value="toggleHistorical">
      <el-descriptions v-if="historicalSnapshot" :column="2" border>
        <el-descriptions-item label="版本">v{{ historicalSnapshot.version_number }}</el-descriptions-item>
        <el-descriptions-item label="生效日">{{ historicalSnapshot.effective_trade_date ?? "-" }}</el-descriptions-item>
        <el-descriptions-item label="成员指纹" :span="2">{{ historicalSnapshot.membership_fingerprint }}</el-descriptions-item>
      </el-descriptions>
      <el-table v-if="historicalSnapshot" :data="historicalSnapshot.members ?? []" size="small">
        <el-table-column prop="symbol" label="股票代码" />
        <el-table-column prop="name" label="股票名称（中文）"><template #default="{ row }">{{ row.name || "-" }}</template></el-table-column>
        <el-table-column label="权重"><template #default="{ row }">{{ formatPoolWeight(row.weight) }}</template></el-table-column>
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
.member-weight-hint { color: var(--byq-text-muted); font-size: 12px; margin: 0 0 8px; }
.member-weight-actions { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.member-weight-actions span { color: var(--byq-text-muted); font-size: 12px; }
.pool-empty { align-items: center; display: flex; flex-direction: column; padding: 16px; text-align: center; }
.pool-empty p { color: var(--byq-text-muted); margin: 0 0 12px; }
.security-search-empty { align-items: center; color: var(--byq-text-muted); display: flex; flex-wrap: wrap; font-size: 12px; gap: 8px; margin-top: 6px; }
.catalog-option-meta { color: var(--byq-text-muted); float: right; margin-left: 18px; }
.section-title { font-size: 14px; margin: 20px 0 10px; }
.dynamic-form-row { margin-top: 14px; }
.dynamic-data-note { margin-bottom: 12px; }
.dynamic-data-note p { margin: 6px 0 0; }
.dynamic-advanced { border-top: 1px solid var(--byq-border-subtle); margin: 14px 0; padding-top: 12px; }
.dynamic-advanced summary { color: var(--byq-text-muted); cursor: pointer; font-size: 13px; }
.dynamic-advanced .el-input { margin-top: 10px; }
.dynamic-rule-notice { background: var(--byq-surface-subtle); border-radius: 6px; color: var(--byq-text-muted); font-size: 12px; margin: 8px 0; padding: 8px 10px; }
.dynamic-rule-error { color: var(--el-color-danger); font-size: 12px; margin: 8px 0; }
.dynamic-preview-result { background: var(--byq-surface-subtle); border-radius: 8px; display: grid; font-size: 12px; gap: 4px; margin: 8px 0 12px; padding: 10px 12px; }
.dynamic-preview-result small { color: var(--byq-text-muted); }
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
