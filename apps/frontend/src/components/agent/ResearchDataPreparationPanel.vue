<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  createConversationResearchPreparation,
  DataCenterRequestError,
  getConversationResearchPreparation,
  listConversationResearchPreparations,
  queryDataReadiness,
  retryConversationResearchPreparation,
  stopConversationResearchContinuation,
  type ConversationResearchPreparationReceipt,
} from "@/api/dataCenter";
import type { DataReadinessResult } from "@/api/types";
import {
  FINANCIAL_FIELDS,
  formatResearchPreparationDate,
  normalizeResearchPreparationScope,
  type ResearchPreparationScope,
  VALUATION_FIELDS,
} from "@/researchPreparation";

const props = withDefaults(defineProps<{
  conversationId: string; enabled: boolean; canContinue: boolean; ownerKey: string; observe?: boolean;
}>(), { observe: true });
const emit = defineEmits<{ continue: [draft: string] }>();

const expanded = ref(false);
const dismissedCompletionId = ref("");
const symbols = ref("");
const startDate = ref("");
const endDate = ref("");
const valuationFields = ref<string[]>([]);
const financialFields = ref<string[]>([]);
const checking = ref(false);
const error = ref("");
const checkedScope = ref<ResearchPreparationScope | null>(null);
const readiness = ref<DataReadinessResult | null>(null);
const preparation = ref<ConversationResearchPreparationReceipt | null>(null);
const preparationError = ref("");
const preparing = ref(false);
const refreshingPreparation = ref(false);
const retryingPreparation = ref(false);
const stoppingContinuation = ref(false);
const retryConfirmed = ref(false);
const preparationUncertain = ref(false);
const automaticStatusRefreshFailed = ref(false);
let generation = 0;
let preparationGeneration = 0;
let automaticStatusTimer: ReturnType<typeof setTimeout> | null = null;
let componentMounted = false;
let pollingAutomaticStatus = false;

const AUTO_STATUS_POLL_MS = 30_000;
const AUTO_CONTINUATION_STATUSES = ["waiting", "dispatching", "bound", "succeeded", "failed", "cancelled"] as const;
type AutoContinuationStatus = typeof AUTO_CONTINUATION_STATUSES[number];

const storageKey = computed(() => props.conversationId && props.ownerKey
  ? `byq-research-preparation:${props.ownerKey}:${props.conversationId}` : "");
const completionStorageKey = computed(() => storageKey.value && `${storageKey.value}:dismissed-completion`);
const parsedCurrentScope = computed(() => normalizeResearchPreparationScope({
  symbols: symbols.value.split(/[，,\s]+/).filter(Boolean),
  start_date: startDate.value,
  end_date: endDate.value,
  use_case: "research",
  data_requirements: {
    ...(valuationFields.value.length ? { daily_basic: valuationFields.value } : {}),
    ...(financialFields.value.length ? { fundamentals: financialFields.value } : {}),
  },
}));
const hasUnsavedScopeChanges = computed(() => !checkedScope.value || !parsedCurrentScope.value
  || JSON.stringify(parsedCurrentScope.value) !== JSON.stringify(checkedScope.value));
const currentReadiness = computed(() => !hasUnsavedScopeChanges.value ? readiness.value : null);
const emptyTradingScope = computed(() => currentReadiness.value?.summary.calendar_complete === true
  && (currentReadiness.value.summary.required_sessions === 0
    || (currentReadiness.value.verdict === "usable" && currentReadiness.value.summary.ready_items === 0)));
const scopeUsable = computed(() => currentReadiness.value?.verdict === "usable" && !emptyTradingScope.value
  && (currentReadiness.value?.summary.required_sessions ?? 0) > 0);
const preparationMatchesCurrentScope = computed(() => Boolean(preparation.value && checkedScope.value
  && sameScope(preparation.value.scope, checkedScope.value)));
const autoContinuationStatus = computed(() => preparation.value?.auto_continuation?.status ?? null);
const isIndexHistory = computed(() => preparation.value?.scope.asset_type === "index");
const completionId = computed(() => autoContinuationStatus.value === "succeeded"
  ? preparation.value?.request_id ?? "succeeded" : "");
const showCompletionNotice = computed(() => Boolean(completionId.value && completionId.value !== dismissedCompletionId.value));
const showAutomaticStatus = computed(() => Boolean((autoContinuationStatus.value || isIndexHistory.value) && !completionId.value));
const automaticContinuationCanStop = computed(() => ["waiting", "dispatching"].includes(autoContinuationStatus.value ?? "")
  && Boolean(preparation.value?.request_id) && !stoppingContinuation.value);
const automaticContinuationNeedsObservation = computed(() => ["waiting", "dispatching", "bound"].includes(autoContinuationStatus.value ?? ""));
const preparationNeedsObservation = computed(() => ["queued", "running"].includes(preparation.value?.status ?? ""));
const shouldObservePreparation = computed(() => preparationNeedsObservation.value || automaticContinuationNeedsObservation.value);
const manualFallbackAvailable = computed(() => !isIndexHistory.value && ["failed", "cancelled"].includes(autoContinuationStatus.value ?? ""));
const manualToolsAvailable = computed(() => (props.enabled || manualFallbackAvailable.value)
  && !automaticContinuationNeedsObservation.value && autoContinuationStatus.value !== "succeeded");
const manualToolsVisible = computed(() => manualToolsAvailable.value && (expanded.value || Boolean(preparation.value)));

function openManualTools() {
  if (!manualToolsAvailable.value) return false;
  expanded.value = true;
  return true;
}

defineExpose({ manualToolsAvailable, openManualTools });
const canPrepare = computed(() => Boolean(currentReadiness.value && checkedScope.value
  && currentReadiness.value.verdict !== "usable" && !emptyTradingScope.value
  && !preparationUncertain.value && !preparing.value
  && !(preparationMatchesCurrentScope.value && ["queued", "running"].includes(preparation.value?.status ?? ""))
  && !(preparationMatchesCurrentScope.value && ["failed", "completed", "ready"].includes(preparation.value?.status ?? ""))));
const statusLabel = computed(() => emptyTradingScope.value ? "日期范围内没有可检查的交易日或有效数据"
  : currentReadiness.value?.verdict === "usable" ? "所选范围覆盖检查通过"
  : currentReadiness.value?.verdict === "limited" ? "所选范围部分缺失"
    : currentReadiness.value?.verdict === "unavailable" ? "所选范围暂不可用" : "");
const automaticStatusLabel = computed(() => {
  const status = autoContinuationStatus.value;
  if (status === "waiting") return ["queued", "running"].includes(preparation.value?.status ?? "")
    ? "后台正在准备数据；完成后将自动复查并继续原研究。"
    : "数据准备已结束，正在等待自动复查并继续原研究。";
  if (status === "dispatching") return "数据已核验，正在原会话自动继续研究。";
  if (status === "bound") return "小巴已在原会话继续研究；如需停止当前回复，请使用会话下方的“停止本轮”。";
  if (isIndexHistory.value) {
    if (status === "failed") return preparation.value?.error ?? "本次续研未能读取已核验的指数数据。";
    if (status === "cancelled") return "已停止自动续研。";
    return preparation.value?.error ?? "";
  }
  if (status === "failed") return "自动续研未完成。可展开数据准备面板手动检查或准备数据。";
  if (status === "cancelled") return "自动续研已停止。可展开数据准备面板手动检查或准备数据。";
  return "";
});
const preparationStatusLabel = computed(() => autoContinuationStatus.value ? ({
  waiting: "等待自动续研",
  dispatching: "正在自动续研",
  bound: "小巴正在继续研究",
  succeeded: "已自动继续研究",
  failed: "自动续研未完成",
  cancelled: "已停止自动续研",
} satisfies Record<AutoContinuationStatus, string>)[autoContinuationStatus.value] : ({
  queued: "补数请求已排队",
  running: "补数正在处理中",
  failed: "补数失败",
  completed: "补数任务已结束，请复查数据覆盖",
  ready: "该范围当前已就绪，请复查数据覆盖",
  not_published: "所需行情尚未发布，暂未创建补数任务",
}[preparation.value?.status ?? ""] ?? (preparation.value ? "数据准备状态待核对" : "")));
const preparationScopeLabel = computed(() => preparation.value
  ? `${preparation.value.scope.symbols.join("、")} · ${formatResearchPreparationDate(preparation.value.scope.start_date)} 至 ${formatResearchPreparationDate(preparation.value.scope.end_date)}`
  : "");
const retryEligible = computed(() => Boolean(preparationMatchesCurrentScope.value && preparation.value?.request_id
  && preparation.value.retry_token && preparation.value.status === "failed"
  && !retryingPreparation.value && !refreshingPreparation.value && !preparationUncertain.value));
const canRetryPreparation = computed(() => retryEligible.value && retryConfirmed.value);

function saveScope(scope: ResearchPreparationScope) {
  if (!storageKey.value) return;
  try { sessionStorage.setItem(storageKey.value, JSON.stringify(scope)); } catch { /* storage is optional */ }
}

function restoreScope() {
  generation++;
  checking.value = false;
  symbols.value = "";
  startDate.value = "";
  endDate.value = "";
  valuationFields.value = [];
  financialFields.value = [];
  checkedScope.value = null;
  readiness.value = null;
  error.value = "";
  preparation.value = null;
  preparationError.value = "";
  preparationUncertain.value = false;
  if (!storageKey.value) return;
  try {
    const raw = sessionStorage.getItem(storageKey.value);
    if (!raw) return;
    const scope = normalizeResearchPreparationScope(JSON.parse(raw));
    if (!scope) return;
    symbols.value = scope.symbols.join(", ");
    startDate.value = formatResearchPreparationDate(scope.start_date);
    endDate.value = formatResearchPreparationDate(scope.end_date);
    valuationFields.value = scope.data_requirements.daily_basic ?? [];
    financialFields.value = scope.data_requirements.fundamentals ?? [];
  } catch { /* a malformed local draft never changes the request */ }
}

function dismissCompletionNotice() {
  if (!completionId.value) return;
  dismissedCompletionId.value = completionId.value;
  if (!completionStorageKey.value) return;
  try { sessionStorage.setItem(completionStorageKey.value, completionId.value); } catch { /* storage is optional */ }
}

watch(completionStorageKey, (key) => {
  dismissedCompletionId.value = "";
  if (!key) return;
  try { dismissedCompletionId.value = sessionStorage.getItem(key) ?? ""; } catch { /* storage is optional */ }
}, { immediate: true });
watch(storageKey, restoreScope, { immediate: true });
watch([storageKey, () => props.observe], ([key, observe]) => {
  preparationGeneration++;
  preparation.value = null;
  preparationError.value = "";
  preparationUncertain.value = false;
  if (observe && key && props.conversationId) void discoverPreparation(true);
}, { immediate: true });
watch([() => preparation.value?.request_id, () => preparation.value?.status, autoContinuationStatus, () => props.observe], () => {
  scheduleAutomaticStatusPoll();
}, { flush: "post" });
watch([symbols, startDate, endDate, valuationFields, financialFields], () => {
  generation++;
  checking.value = false;
  checkedScope.value = null;
  readiness.value = null;
  error.value = "";
  retryConfirmed.value = false;
  const scope = parsedCurrentScope.value;
  if (scope) saveScope(scope);
  else if (storageKey.value) {
    try { sessionStorage.removeItem(storageKey.value); } catch { /* storage is optional */ }
  }
});

async function checkReadiness() {
  const scope = parsedCurrentScope.value;
  if (!scope) {
    error.value = "请填写 1–20 个规范股票代码和有效起止日期。单次最多覆盖 180 个自然日，请只选支持的数据字段。";
    readiness.value = null;
    checkedScope.value = null;
    return;
  }
  const currentGeneration = ++generation;
  checking.value = true;
  error.value = "";
  readiness.value = null;
  checkedScope.value = null;
  try {
    const value = await queryDataReadiness({
      symbols: scope.symbols,
      start_date: scope.start_date,
      end_date: scope.end_date,
      use_case: "research",
      data_requirements: scope.data_requirements,
    });
    if (currentGeneration !== generation || storageKey.value === "") return;
    const responseSymbols = [...value.scope.symbols].map((symbol) => symbol.toUpperCase()).sort();
    const expectedSymbols = [...scope.symbols].sort();
    if (JSON.stringify(responseSymbols) !== JSON.stringify(expectedSymbols)
        || value.scope.start_date.replaceAll("-", "") !== scope.start_date
        || value.scope.end_date.replaceAll("-", "") !== scope.end_date
        || value.scope.use_case !== "research") {
      throw new Error("可用性结果与刚才确认的标的或日期范围不一致，未保存本次检查结果。");
    }
    checkedScope.value = scope;
    readiness.value = value;
    saveScope(scope);
  } catch (caught) {
    if (currentGeneration === generation) error.value = caught instanceof Error ? caught.message : "检查未完成，请稍后重新检查。";
  } finally {
    if (currentGeneration === generation) checking.value = false;
  }
}

function sameScope(left: ResearchPreparationScope, right: ResearchPreparationScope): boolean {
  const sameSet = (leftValues: string[], rightValues: string[]) => leftValues.length === rightValues.length
    && leftValues.every((value) => rightValues.includes(value));
  return left.asset_type === right.asset_type && sameSet(left.symbols, right.symbols)
    && left.start_date === right.start_date
    && left.end_date === right.end_date
    && left.use_case === right.use_case
    && sameSet(left.data_requirements.daily_basic ?? [], right.data_requirements.daily_basic ?? [])
    && sameSet(left.data_requirements.fundamentals ?? [], right.data_requirements.fundamentals ?? []);
}

function parseReceipt(value: unknown): ConversationResearchPreparationReceipt | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const scope = normalizeResearchPreparationScope(candidate.scope, { allowIndexHistory: true });
  if (!scope || typeof candidate.status !== "string"
      || !(candidate.request_id === null || (typeof candidate.request_id === "string" && Boolean(candidate.request_id)))
      || !(candidate.retry_token === undefined || candidate.retry_token === null || typeof candidate.retry_token === "string")
      || !(candidate.error === undefined || candidate.error === null || typeof candidate.error === "string")) return null;
  const autoContinuation = typeof candidate.auto_continuation === "object" && candidate.auto_continuation !== null
    && !Array.isArray(candidate.auto_continuation)
    && AUTO_CONTINUATION_STATUSES.includes((candidate.auto_continuation as { status?: unknown }).status as AutoContinuationStatus)
    ? { status: (candidate.auto_continuation as { status: AutoContinuationStatus }).status }
    : undefined;
  return {
    request_id: candidate.request_id as string | null,
    status: candidate.status,
    retry_token: candidate.retry_token as string | null | undefined,
    error: candidate.error as string | null | undefined,
    scope,
    ...(autoContinuation ? { auto_continuation: autoContinuation } : {}),
  };
}

function fillScope(scope: ResearchPreparationScope) {
  symbols.value = scope.symbols.join(", ");
  startDate.value = formatResearchPreparationDate(scope.start_date);
  endDate.value = formatResearchPreparationDate(scope.end_date);
  valuationFields.value = scope.data_requirements.daily_basic ?? [];
  financialFields.value = scope.data_requirements.fundamentals ?? [];
}

async function discoverPreparation(hydrateEmptyScope = false) {
  const currentGeneration = ++preparationGeneration;
  if (hydrateEmptyScope) refreshingPreparation.value = true;
  preparationError.value = "";
  try {
    const result = await listConversationResearchPreparations(props.conversationId);
    if (currentGeneration !== preparationGeneration || !props.observe) return;
    if (!Array.isArray(result.preparations)) throw new Error("服务端未返回会话准备记录列表。");
    const receipts = result.preparations.map(parseReceipt).filter((receipt): receipt is ConversationResearchPreparationReceipt => receipt !== null);
    const latest = receipts[0] ?? null;
    const savedScope = parsedCurrentScope.value;
    const selected = latest?.auto_continuation || !savedScope
      ? latest
      : receipts.find((receipt) => sameScope(receipt.scope, savedScope)) ?? latest;
    preparation.value = selected;
    preparationUncertain.value = false;
    if (hydrateEmptyScope && selected && !selected.scope.asset_type && !symbols.value.trim() && !startDate.value && !endDate.value) fillScope(selected.scope);
  } catch (caught) {
    if (currentGeneration === preparationGeneration) preparationError.value = caught instanceof Error ? caught.message : "无法读取当前会话的数据准备记录。";
  } finally {
    if (hydrateEmptyScope && currentGeneration === preparationGeneration) refreshingPreparation.value = false;
  }
}

async function submitPreparation() {
  const scope = checkedScope.value;
  if (!scope || !canPrepare.value || !currentReadiness.value || !props.conversationId) return;
  const currentGeneration = ++preparationGeneration;
  preparing.value = true;
  preparationError.value = "";
  retryConfirmed.value = false;
  try {
    const result = parseReceipt(await createConversationResearchPreparation(props.conversationId, scope));
    if (!result || !sameScope(result.scope, scope)) throw new Error("服务端回执与刚才检查的范围不一致，未采纳该回执。");
    if (currentGeneration !== preparationGeneration) return;
    if (!parsedCurrentScope.value || !checkedScope.value || !currentReadiness.value
        || !sameScope(scope, parsedCurrentScope.value) || !sameScope(scope, checkedScope.value)) {
      preparationUncertain.value = true;
      preparationError.value = "请求可能已提交，但表单范围已变化。请先只读刷新当前会话准备记录。";
      return;
    }
    preparation.value = result;
    preparationUncertain.value = false;
  } catch (caught) {
    if (currentGeneration !== preparationGeneration) return;
    preparationUncertain.value = !(caught instanceof DataCenterRequestError) || caught.status >= 500;
    preparationError.value = caught instanceof Error ? caught.message : "准备请求未确认，请刷新当前会话记录。";
  } finally {
    if (currentGeneration === preparationGeneration) preparing.value = false;
  }
}

async function refreshPreparation() {
  const current = preparation.value;
  if (refreshingPreparation.value || preparing.value || !props.conversationId) return;
  const currentGeneration = ++preparationGeneration;
  refreshingPreparation.value = true;
  preparationError.value = "";
  try {
    if (current?.request_id) {
      const result = parseReceipt(await getConversationResearchPreparation(props.conversationId, current.request_id));
      if (!result || result.request_id !== current.request_id || !sameScope(result.scope, current.scope)) {
        throw new Error("服务端回执与当前请求不一致，未采纳刷新结果。");
      }
      if (currentGeneration !== preparationGeneration) return;
      preparation.value = result;
    } else {
      const result = await listConversationResearchPreparations(props.conversationId);
      if (!Array.isArray(result.preparations)) throw new Error("服务端未返回会话准备记录列表。");
      if (currentGeneration !== preparationGeneration) return;
      const receipts = result.preparations.map(parseReceipt).filter((receipt): receipt is ConversationResearchPreparationReceipt => receipt !== null);
      preparation.value = (current?.scope && receipts.find((receipt) => sameScope(receipt.scope, current.scope))) ?? receipts[0] ?? null;
    }
    preparationUncertain.value = false;
    retryConfirmed.value = false;
    automaticStatusRefreshFailed.value = false;
  } catch (caught) {
    if (currentGeneration === preparationGeneration) preparationError.value = caught instanceof Error ? caught.message : "暂时无法刷新准备状态。";
  } finally {
    if (currentGeneration === preparationGeneration) refreshingPreparation.value = false;
  }
}

function clearAutomaticStatusTimer() {
  if (automaticStatusTimer !== null) clearTimeout(automaticStatusTimer);
  automaticStatusTimer = null;
}

function pageIsVisible(): boolean {
  return typeof document !== "undefined" && document.visibilityState === "visible";
}

function scheduleAutomaticStatusPoll(delay = AUTO_STATUS_POLL_MS) {
  clearAutomaticStatusTimer();
  const current = preparation.value;
  if (!componentMounted || !props.observe || !pageIsVisible() || !shouldObservePreparation.value || !current?.request_id) return;
  automaticStatusTimer = setTimeout(() => { void pollAutomaticStatus(); }, delay);
}

async function pollAutomaticStatus() {
  const current = preparation.value;
  if (!current?.request_id || !props.observe || !pageIsVisible() || !shouldObservePreparation.value) return;
  if (refreshingPreparation.value || preparing.value || retryingPreparation.value || stoppingContinuation.value || pollingAutomaticStatus) {
    scheduleAutomaticStatusPoll();
    return;
  }
  const currentGeneration = preparationGeneration;
  const requestId = current.request_id;
  pollingAutomaticStatus = true;
  try {
    const result = parseReceipt(await getConversationResearchPreparation(props.conversationId, requestId));
    if (!result || result.request_id !== requestId || !sameScope(result.scope, current.scope)) {
      throw new Error("服务端回执与当前请求不一致，未采纳自动状态刷新。");
    }
    if (currentGeneration !== preparationGeneration || preparation.value?.request_id !== requestId) return;
    preparation.value = result;
    preparationUncertain.value = false;
    automaticStatusRefreshFailed.value = false;
  } catch {
    if (currentGeneration === preparationGeneration && preparation.value?.request_id === requestId) {
      automaticStatusRefreshFailed.value = true;
    }
  } finally {
    pollingAutomaticStatus = false;
    scheduleAutomaticStatusPoll();
  }
}

async function stopAutomaticContinuation() {
  const current = preparation.value;
  if (!automaticContinuationCanStop.value || !current?.request_id || !props.conversationId) return;
  const currentGeneration = ++preparationGeneration;
  const requestId = current.request_id;
  stoppingContinuation.value = true;
  preparationError.value = "";
  try {
    const result = parseReceipt(await stopConversationResearchContinuation(props.conversationId, requestId));
    if (!result || result.request_id !== requestId || !sameScope(result.scope, current.scope)) {
      throw new Error("服务端回执与当前续研请求不一致，未采纳停止结果。");
    }
    if (currentGeneration !== preparationGeneration) return;
    preparation.value = result;
    preparationUncertain.value = false;
    automaticStatusRefreshFailed.value = false;
  } catch (caught) {
    if (currentGeneration !== preparationGeneration) return;
    preparationUncertain.value = true;
    preparationError.value = caught instanceof Error ? caught.message : "停止结果未确认，请只读刷新当前会话状态。";
  } finally {
    if (currentGeneration === preparationGeneration) stoppingContinuation.value = false;
    scheduleAutomaticStatusPoll();
  }
}

function onVisibilityChange() {
  if (pageIsVisible()) scheduleAutomaticStatusPoll(0);
  else clearAutomaticStatusTimer();
}

onMounted(() => {
  componentMounted = true;
  document.addEventListener("visibilitychange", onVisibilityChange);
  scheduleAutomaticStatusPoll();
});

onBeforeUnmount(() => {
  componentMounted = false;
  generation++;
  preparationGeneration++;
  clearAutomaticStatusTimer();
  document.removeEventListener("visibilitychange", onVisibilityChange);
});

async function retryPreparation() {
  const current = preparation.value;
  if (!canRetryPreparation.value || !current?.request_id || !current.retry_token || !props.conversationId) return;
  const currentGeneration = ++preparationGeneration;
  const requestId = current.request_id;
  retryingPreparation.value = true;
  preparationError.value = "";
  try {
    const result = parseReceipt(await retryConversationResearchPreparation(props.conversationId, requestId, current.retry_token));
    if (!result || result.request_id !== requestId || !sameScope(result.scope, current.scope)) {
      throw new Error("服务端重试回执与原范围不一致，未采纳该回执。");
    }
    if (currentGeneration !== preparationGeneration) return;
    preparation.value = result;
    retryConfirmed.value = false;
    preparationUncertain.value = false;
  } catch (caught) {
    if (currentGeneration !== preparationGeneration) return;
    preparationUncertain.value = true;
    retryConfirmed.value = false;
    preparationError.value = caught instanceof Error ? caught.message : "重试结果未确认，请先只读刷新原请求状态。";
  } finally {
    if (currentGeneration === preparationGeneration) retryingPreparation.value = false;
  }
}

function resumeDraft() {
  const scope = checkedScope.value;
  if (!scope || !scopeUsable.value || !props.canContinue) return;
  const fields = [
    ...(scope.data_requirements.daily_basic ?? []),
    ...(scope.data_requirements.fundamentals ?? []),
  ];
  const fieldText = fields.length ? `；已检查字段：${fields.join("、")}` : "；只包含基础日线数据";
  emit("continue", `请基于本会话此前的研究问题继续分析。刚才复查的数据范围为：${scope.symbols.join("、")}，${formatResearchPreparationDate(scope.start_date)} 至 ${formatResearchPreparationDate(scope.end_date)}${fieldText}。此次可用性检查结果为可用；请只使用该范围内已保存的数据，注明数据日期、来源和仍无法核实的内容，不创建股票池、策略或回测，也不要把按交易日获取的数据描述成逐只股票请求 Provider。`);
}
</script>

<template>
  <section v-if="conversationId && (manualToolsVisible || showCompletionNotice || showAutomaticStatus)" class="research-preparation" aria-label="研究数据准备">
    <button v-if="manualToolsVisible" class="entry-button" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      {{ expanded ? "收起数据准备" : "查看补数详情" }}
      <span v-if="preparation" class="entry-status">{{ preparationStatusLabel }}</span>
    </button>
    <div v-if="showCompletionNotice" class="completion-notice">
      <span role="status">{{ preparationStatusLabel }}</span>
      <button class="completion-dismiss" type="button" aria-label="关闭自动续研提示" title="关闭"
        @click="dismissCompletionNotice">×</button>
    </div>
    <div v-else-if="showAutomaticStatus" class="automatic-status" role="status" aria-live="polite">
      <strong>{{ preparationStatusLabel }}</strong>
      <p v-if="automaticStatusLabel">{{ automaticStatusLabel }}</p>
      <p v-if="preparation && preparationScopeLabel">研究范围：{{ preparationScopeLabel }}</p>
      <p v-if="automaticStatusRefreshFailed" class="stale-note">状态暂时无法更新，页面会在稍后重试；自动研究流程不依赖此页面运行。</p>
      <p v-if="preparationError && !manualToolsVisible" class="error" role="alert">{{ preparationError }}</p>
      <button v-if="automaticContinuationCanStop" type="button" class="secondary-button" :disabled="stoppingContinuation"
        @click="stopAutomaticContinuation">
        {{ stoppingContinuation ? "正在停止自动续研…" : "停止自动续研" }}
      </button>
    </div>
    <div v-if="expanded && manualToolsVisible" class="preparation-body">
      <p class="intro">手动补齐后，可在这里复查并继续研究。每次最多选择 20 只股票和 180 个自然日。</p>
      <label class="field-label">股票代码 <small>用逗号分隔，最多 20 只；填写规范代码，如 600036.SH</small>
        <textarea v-model="symbols" rows="2" placeholder="600036.SH, 601398.SH" :disabled="checking || preparing" />
      </label>
      <div class="date-fields">
        <label class="field-label">开始日期<input v-model="startDate" type="date" :disabled="checking || preparing" /></label>
        <label class="field-label">结束日期<input v-model="endDate" type="date" :disabled="checking || preparing" /></label>
      </div>
      <fieldset>
        <legend>数据范围</legend>
        <p>基础日线、交易状态、涨跌停和复权信息固定纳入检查。后台市场数据按交易日获取；标的列表用于限定研究范围，不代表 Provider 按股票逐只请求。</p>
        <details>
          <summary>可选估值字段</summary>
          <label v-for="field in VALUATION_FIELDS" :key="field.value" class="option">
            <input v-model="valuationFields" type="checkbox" :value="field.value" :disabled="checking || preparing" /> {{ field.label }}
          </label>
        </details>
        <details>
          <summary>可选财务字段</summary>
          <label v-for="field in FINANCIAL_FIELDS" :key="field.value" class="option">
            <input v-model="financialFields" type="checkbox" :value="field.value" :disabled="checking || preparing" /> {{ field.label }}
          </label>
        </details>
      </fieldset>
      <button type="button" class="primary-button" :disabled="checking || preparing" @click="checkReadiness">
        {{ checking ? "正在检查…" : checkedScope && !hasUnsavedScopeChanges ? "复查数据" : "确认范围并检查数据" }}
      </button>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="preparationError" class="error" role="alert">{{ preparationError }}</p>

      <div v-if="preparation" class="preparation-receipt" role="status">
        <strong>{{ preparationStatusLabel }}</strong>
        <p>准备范围：{{ preparationScopeLabel }}</p>
        <p v-if="preparation.request_id">请求编号：<code>{{ preparation.request_id }}</code></p>
        <p v-if="preparation.error">{{ preparation.error }}</p>
        <p v-if="preparation.status === 'not_published'">当前尚无可补齐的已发布行情；日历就绪不代表收盘行情已发布。可稍后重新检查该范围。</p>
        <p v-if="!autoContinuationStatus && preparationMatchesCurrentScope && ['completed', 'ready'].includes(preparation.status)">准备回执不代替浏览器重新读取覆盖情况。请复查下面的同一范围，再决定是否把续研草稿带入输入框。</p>
        <p v-if="!preparationMatchesCurrentScope">这是当前会话此前提交的其他范围；不会用于当前选中范围的续研或重试。</p>
        <button type="button" class="secondary-button" :disabled="refreshingPreparation || preparing || retryingPreparation" @click="refreshPreparation">
          {{ refreshingPreparation ? "正在刷新…" : "只读刷新准备状态" }}
        </button>
        <div v-if="retryEligible" class="retry-box">
          <p>该请求已失败。只有在读取到安全重试凭证后才可重试；重试仍使用原会话和完全相同的范围。</p>
          <label class="confirm-line"><input v-model="retryConfirmed" type="checkbox" :disabled="retryingPreparation || refreshingPreparation" /> 我已核对失败范围，并确认重试</label>
          <button type="button" class="secondary-button" :disabled="!canRetryPreparation" @click="retryPreparation">
            {{ retryingPreparation ? "正在重试…" : "确认重试此补数请求" }}
          </button>
        </div>
        <p v-if="preparationUncertain" class="stale-note">提交、重试或停止结果暂未确认。请先只读刷新原会话记录，再决定是否继续。</p>
      </div>

      <div v-if="currentReadiness" class="readiness-result" role="status">
        <strong>{{ statusLabel }}</strong>
        <p>检查范围：{{ currentReadiness.scope.symbols.join("、") }} · {{ formatResearchPreparationDate(currentReadiness.scope.start_date) }} 至 {{ formatResearchPreparationDate(currentReadiness.scope.end_date) }}</p>
        <p>基础数据已就绪 {{ currentReadiness.summary.ready_items }} 项，缺少 {{ currentReadiness.summary.missing_items }} 项；结果只反映本次检查时的已保存数据。</p>
        <p>覆盖检查只说明所需记录范围已保存；单项指标仍可能为空，研究时还需核对具体数值、口径和来源。</p>
        <ul v-if="currentReadiness.datasets.length">
          <li v-for="dataset in currentReadiness.datasets" :key="dataset.label">{{ dataset.label }}：缺少 {{ dataset.missing_count }} 项</li>
        </ul>
        <ul v-if="currentReadiness.issues.length" aria-label="当前阻塞项">
          <li v-for="issue in currentReadiness.issues.slice(0, 5)" :key="`${issue.symbol ?? ''}:${issue.trade_date ?? ''}:${issue.label}`">
            {{ issue.symbol || "所选范围" }}<span v-if="issue.trade_date"> · {{ issue.trade_date }}</span>：{{ issue.label }}（{{ issue.impact }}）
          </li>
        </ul>
        <p v-if="currentReadiness.issues_truncated">还有未展开的问题项，请缩小范围后分次检查。</p>
        <div v-if="emptyTradingScope" class="next-step">
          <p>当前日期范围内没有可检查的交易日或有效证券数据。请调整标的或日期后重新检查；不会提交空范围准备任务。</p>
        </div>
        <div v-else-if="scopeUsable" class="next-step">
          <p>该范围当前通过记录覆盖检查；单项指标仍可能为空，续研时必须继续核对实际数值、口径和来源。</p>
          <template v-if="canContinue">
          <button type="button" class="primary-button" @click="resumeDraft">带入续研草稿</button>
          <small>草稿会回到当前会话输入框，不会自动发送。</small>
          </template>
        </div>
        <div v-else-if="canPrepare" class="next-step">
          <p>当前范围有缺失项。点击后只提交上方已检查的标的、日期和数据字段；后台会再次核对范围和现有数据。</p>
          <button type="button" class="primary-button" :disabled="preparing || checking" @click="submitPreparation">
            {{ preparing ? "正在提交补数请求…" : preparationMatchesCurrentScope && preparation?.status === "not_published" ? "稍后重新检查行情是否已发布" : "为当前会话准备缺失数据" }}
          </button>
          <small>收到就绪或任务结束回执后，仍需重新检查同一范围的数据覆盖；通过后才会出现续研草稿入口。</small>
        </div>
        <div v-else-if="preparationMatchesCurrentScope && preparation?.status === 'completed'" class="next-step">
          <p>任务已结束。请再次检查当前范围；如果仍有缺失，回执会显示失败或需要管理员处理，不会自动继续研究。</p>
        </div>
        <div v-else-if="preparationMatchesCurrentScope && preparation?.status === 'failed'" class="next-step">
          <p>准备请求已失败。请查看上方原因；仅当回执提供安全重试凭证时，才可在上方明确确认重试。</p>
        </div>
      </div>
      <p v-else-if="checkedScope && hasUnsavedScopeChanges" class="stale-note">范围已修改，请重新检查后再准备数据或续研。</p>
    </div>
  </section>
</template>

<style scoped>
.research-preparation { width: min(900px, 100%); margin: 0 auto 1rem; padding: 0 .75rem; color: var(--byq-text); }
.entry-button, .primary-button { border: 1px solid var(--byq-border); border-radius: 7px; padding: .55rem .8rem; color: var(--byq-text); background: var(--byq-surface); cursor: pointer; }
.entry-button { display: inline-flex; align-items: center; gap: .55rem; }
.entry-status { color: var(--el-color-primary); font-size: .85em; }
.primary-button { color: white; background: var(--el-color-primary); border-color: var(--el-color-primary); }
button:disabled { opacity: .6; cursor: wait; }
.preparation-body { margin-top: .65rem; padding: 1rem; border: 1px solid var(--byq-border); border-radius: 12px; background: var(--byq-surface); display: grid; gap: .8rem; }
.automatic-status { width: min(900px, 100%); box-sizing: border-box; margin-top: .45rem; padding: .75rem 1rem; border: 1px solid var(--byq-border); border-radius: 9px; background: var(--byq-surface); display: grid; gap: .45rem; }
.completion-notice { display: inline-flex; align-items: center; gap: .25rem; max-width: 100%; padding: .125rem .25rem .125rem .625rem; border: 1px solid var(--byq-border); border-radius: 7px; color: var(--byq-text-muted); background: var(--byq-surface); font-size: .875rem; }
.completion-dismiss { display: inline-grid; place-items: center; flex: none; width: 1.75rem; height: 1.75rem; padding: 0; border: 0; border-radius: 4px; color: inherit; background: transparent; cursor: pointer; font: inherit; font-size: 1.125rem; }
.completion-dismiss:hover, .completion-dismiss:focus-visible { color: var(--byq-text); background: var(--el-fill-color-light); }
.automatic-status p { margin: 0; color: var(--byq-text-muted); line-height: 1.5; }
.intro, fieldset p, .readiness-result p, small { color: var(--byq-text-muted); line-height: 1.55; }
.intro, fieldset p, .readiness-result p { margin: 0; }
.field-label { display: grid; gap: .35rem; font-weight: 600; }
.field-label textarea, .field-label input, .handoff input { box-sizing: border-box; width: 100%; border: 1px solid var(--byq-border); border-radius: 6px; padding: .55rem; background: var(--byq-surface); color: var(--byq-text); font: inherit; }
.date-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem; }
fieldset { margin: 0; padding: .75rem; border: 1px solid var(--byq-border); border-radius: 8px; display: grid; gap: .6rem; }
legend { font-weight: 700; padding: 0 .3rem; }
details { border-top: 1px solid var(--byq-border); padding-top: .5rem; }
summary { cursor: pointer; font-weight: 600; }
.option { display: inline-flex; align-items: center; gap: .35rem; margin: .55rem .9rem 0 0; }
.readiness-result, .next-step { display: grid; gap: .5rem; }
.readiness-result { border-top: 1px solid var(--byq-border); padding-top: .8rem; }
.readiness-result ul { margin: 0; padding-left: 1.25rem; }
.preparation-receipt, .retry-box { display: grid; gap: .5rem; padding: .75rem; border: 1px solid var(--byq-border); border-radius: 8px; }
.preparation-receipt p, .retry-box p { margin: 0; color: var(--byq-text-muted); line-height: 1.55; }
.secondary-button { width: fit-content; border: 1px solid var(--byq-border); border-radius: 7px; padding: .5rem .7rem; color: var(--byq-text); background: var(--byq-surface); cursor: pointer; }
.confirm-line { display: flex; gap: .45rem; align-items: flex-start; }
.confirm-line input { margin-top: .25rem; }
.error { color: var(--el-color-danger); margin: 0; }
.stale-note { margin: 0; color: var(--el-color-warning); }
@media (max-width: 640px) { .date-fields { grid-template-columns: 1fr; } }
</style>
