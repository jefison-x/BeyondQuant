<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { queryDataReadiness } from "@/api/dataCenter";
import type { DataReadinessResult } from "@/api/types";
import {
  buildResearchPreparationHandoffUrl,
  FINANCIAL_FIELDS,
  formatResearchPreparationDate,
  normalizeResearchPreparationScope,
  type ResearchPreparationScope,
  VALUATION_FIELDS,
} from "@/researchPreparation";

const props = defineProps<{ conversationId: string; enabled: boolean; canContinue: boolean; ownerKey: string }>();
const emit = defineEmits<{ continue: [draft: string] }>();

const expanded = ref(false);
const symbols = ref("");
const startDate = ref("");
const endDate = ref("");
const valuationFields = ref<string[]>([]);
const financialFields = ref<string[]>([]);
const checking = ref(false);
const error = ref("");
const checkedScope = ref<ResearchPreparationScope | null>(null);
const readiness = ref<DataReadinessResult | null>(null);
const copyMessage = ref("");
let generation = 0;

const storageKey = computed(() => props.conversationId && props.ownerKey
  ? `byq-research-preparation:${props.ownerKey}:${props.conversationId}` : "");
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
const handoffUrl = computed(() => currentReadiness.value && currentReadiness.value.verdict !== "usable" && !emptyTradingScope.value
  && checkedScope.value ? buildResearchPreparationHandoffUrl(checkedScope.value) : "");
const statusLabel = computed(() => emptyTradingScope.value ? "日期范围内没有可检查的交易日或有效数据"
  : currentReadiness.value?.verdict === "usable" ? "所选范围覆盖检查通过"
  : currentReadiness.value?.verdict === "limited" ? "所选范围部分缺失"
    : currentReadiness.value?.verdict === "unavailable" ? "所选范围暂不可用" : "");

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
  copyMessage.value = "";
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

watch(storageKey, restoreScope, { immediate: true });
watch([symbols, startDate, endDate, valuationFields, financialFields], () => {
  generation++;
  checking.value = false;
  checkedScope.value = null;
  readiness.value = null;
  error.value = "";
  copyMessage.value = "";
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
  copyMessage.value = "";
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

async function copyHandoff() {
  if (!handoffUrl.value) return;
  try {
    await navigator.clipboard.writeText(handoffUrl.value);
    copyMessage.value = "管理员审核链接已复制；链接只包含标的、日期和数据字段。";
  } catch {
    copyMessage.value = "无法自动复制，请手动复制下方链接；链接只包含标的、日期和数据字段。";
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
  <section v-if="enabled && conversationId" class="research-preparation" aria-label="研究数据准备">
    <button class="entry-button" type="button" :aria-expanded="expanded" @click="expanded = !expanded">
      {{ expanded ? "收起数据准备" : "准备研究数据" }}
    </button>
    <div v-if="expanded" class="preparation-body">
      <p class="intro">在当前会话确认需要的标的和日期，再检查已保存数据。这里不会创建股票池或直接同步数据。</p>
      <label class="field-label">股票代码 <small>用逗号分隔，最多 20 只；填写规范代码，如 600036.SH</small>
        <textarea v-model="symbols" rows="2" placeholder="600036.SH, 601398.SH" :disabled="checking" />
      </label>
      <div class="date-fields">
        <label class="field-label">开始日期<input v-model="startDate" type="date" :disabled="checking" /></label>
        <label class="field-label">结束日期<input v-model="endDate" type="date" :disabled="checking" /></label>
      </div>
      <fieldset>
        <legend>数据范围</legend>
        <p>基础日线、交易状态、涨跌停和复权信息固定纳入检查。后台市场数据按交易日获取；标的列表用于限定研究范围，不代表 Provider 按股票逐只请求。</p>
        <details>
          <summary>可选估值字段</summary>
          <label v-for="field in VALUATION_FIELDS" :key="field.value" class="option">
            <input v-model="valuationFields" type="checkbox" :value="field.value" :disabled="checking" /> {{ field.label }}
          </label>
        </details>
        <details>
          <summary>可选财务字段</summary>
          <label v-for="field in FINANCIAL_FIELDS" :key="field.value" class="option">
            <input v-model="financialFields" type="checkbox" :value="field.value" :disabled="checking" /> {{ field.label }}
          </label>
        </details>
      </fieldset>
      <button type="button" class="primary-button" :disabled="checking" @click="checkReadiness">
        {{ checking ? "正在检查…" : checkedScope && !hasUnsavedScopeChanges ? "复查数据" : "确认范围并检查数据" }}
      </button>
      <p v-if="error" class="error" role="alert">{{ error }}</p>

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
        <div v-else-if="handoffUrl" class="handoff">
          <p>需要补齐数据时，可把范围交给管理员审核。管理员只会看到下面列出的范围，不会看到本会话内容。</p>
          <a :href="handoffUrl" target="_blank" rel="noopener noreferrer">打开管理员数据准备审核页</a>
          <button type="button" @click="copyHandoff">复制管理员审核链接</button>
          <input readonly :value="handoffUrl" aria-label="管理员审核链接" @focus="($event.target as HTMLInputElement).select()" />
          <small v-if="copyMessage" role="status">{{ copyMessage }}</small>
        </div>
      </div>
      <p v-else-if="checkedScope && hasUnsavedScopeChanges" class="stale-note">范围已修改，请重新检查后再交接或继续研究。</p>
    </div>
  </section>
</template>

<style scoped>
.research-preparation { width: min(900px, 100%); margin: 0 auto 1rem; padding: 0 .75rem; color: var(--byq-text); }
.entry-button, .primary-button, .handoff button { border: 1px solid var(--byq-border); border-radius: 7px; padding: .55rem .8rem; color: var(--byq-text); background: var(--byq-surface); cursor: pointer; }
.primary-button { color: white; background: var(--el-color-primary); border-color: var(--el-color-primary); }
button:disabled { opacity: .6; cursor: wait; }
.preparation-body { margin-top: .65rem; padding: 1rem; border: 1px solid var(--byq-border); border-radius: 12px; background: var(--byq-surface); display: grid; gap: .8rem; }
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
.readiness-result, .handoff, .next-step { display: grid; gap: .5rem; }
.readiness-result { border-top: 1px solid var(--byq-border); padding-top: .8rem; }
.readiness-result ul { margin: 0; padding-left: 1.25rem; }
.handoff a { overflow-wrap: anywhere; }
.error { color: var(--el-color-danger); margin: 0; }
.stale-note { margin: 0; color: var(--el-color-warning); }
@media (max-width: 640px) { .date-fields { grid-template-columns: 1fr; } }
</style>
