<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { createResearchPreparation, DataCenterRequestError, getResearchPreparation, retryResearchPreparation } from "@/api/dataCenter";
import {
  FINANCIAL_FIELDS,
  formatResearchPreparationDate,
  researchPreparationScopeFromHandoffQuery,
  VALUATION_FIELDS,
} from "@/researchPreparation";
import type { ResearchPreparationSubmission } from "@/api/dataCenter";
import { useAuthStore } from "@/stores/auth";

const emit = defineEmits<{ securities: [] }>();
const route = useRoute();
const auth = useAuthStore();
const confirming = ref(false);
const retrying = ref(false);
const refreshing = ref(false);
const confirmed = ref(false);
const retryConfirmed = ref(false);
const uncertain = ref(false);
const submission = ref<ResearchPreparationSubmission | null>(null);
const error = ref("");
let generation = 0;
const handoffValue = computed(() => route.query.researchPreparation);
const scope = computed(() => researchPreparationScopeFromHandoffQuery(handoffValue.value));
const invalidHandoff = computed(() => handoffValue.value !== undefined && !scope.value);
const requirementLabels = computed(() => {
  if (!scope.value) return [];
  const labels = new Map<string, string>([
    ...VALUATION_FIELDS.map((field) => [field.value, field.label] as const),
    ...FINANCIAL_FIELDS.map((field) => [field.value, field.label] as const),
  ]);
  return [
    ...(scope.value.data_requirements.daily_basic ?? []),
    ...(scope.value.data_requirements.fundamentals ?? []),
  ].map((field) => labels.get(field) ?? field);
});
const statusLabel = computed(() => {
  const status = submission.value?.status;
  if (status === "ready") return "提交时的覆盖检查显示范围已就绪；原用户仍需复查";
  if (status === "queued" || status === "pending") return "请求已进入排队";
  if (status === "running" || status === "syncing") return "请求正在处理";
  if (status === "waiting_for_sessions") return "等待目标交易日数据";
  if (status === "completed") return "准备任务已完成，需复查数据覆盖";
  if (status === "failed") return "准备任务失败，需要查看原因";
  return status ? "准备请求状态待核对" : "";
});
const canRetry = computed(() => Boolean(submission.value?.request_id && submission.value.retry_token
  && ["completed", "failed"].includes(submission.value.status)));
const failureReasonLabel = computed(() => ({
  session_repair_failed: "分区数据修复失败",
  readiness_not_satisfied: "任务结束后数据覆盖仍不完整",
  readiness_assessment_failed: "复核数据覆盖时发生错误",
  preparation_failed: "数据准备失败",
}[submission.value?.failure_reason ?? ""] ?? ""));

watch(handoffValue, () => {
  generation++;
  confirming.value = false;
  retrying.value = false;
  refreshing.value = false;
  confirmed.value = false;
  retryConfirmed.value = false;
  uncertain.value = false;
  submission.value = null;
  error.value = "";
});

function validReceipt(value: ResearchPreparationSubmission): boolean {
  return typeof value.status === "string"
    && (value.request_id === null || (typeof value.request_id === "string" && Boolean(value.request_id)))
    && (value.retry_token === undefined || value.retry_token === null || typeof value.retry_token === "string")
    && (value.failure_reason === undefined || value.failure_reason === null || typeof value.failure_reason === "string")
    && (value.failure_message === undefined || value.failure_message === null || typeof value.failure_message === "string");
}

function currentScopeMatches(encoded: string): boolean {
  return Boolean(scope.value && JSON.stringify(scope.value) === encoded);
}

async function submit() {
  const current = scope.value;
  if (!auth.isAdmin || !confirmed.value || !current || confirming.value || retrying.value) return;
  const currentGeneration = generation;
  const encodedScope = JSON.stringify(current);
  confirming.value = true;
  error.value = "";
  submission.value = null;
  uncertain.value = false;
  try {
    const result = await createResearchPreparation({
      symbols: current.symbols,
      start_date: current.start_date,
      end_date: current.end_date,
      use_case: "research",
      data_requirements: current.data_requirements,
    });
    if (!validReceipt(result)) {
      throw new Error("服务端未返回可确认的准备任务回执，请勿据此判断数据已就绪。");
    }
    if (currentGeneration !== generation || !currentScopeMatches(encodedScope)) return;
    submission.value = result;
  } catch (caught) {
    if (currentGeneration !== generation) return;
    uncertain.value = !(caught instanceof DataCenterRequestError) || caught.status >= 500;
    error.value = caught instanceof Error ? caught.message : "请求未确认；请保留此范围并核对准备状态。";
  } finally {
    if (currentGeneration === generation) confirming.value = false;
  }
}

async function refreshReceipt() {
  const currentId = submission.value?.request_id;
  if (!currentId || refreshing.value || !scope.value) return;
  const currentGeneration = generation;
  const encodedScope = JSON.stringify(scope.value);
  refreshing.value = true;
  error.value = "";
  try {
    const result = await getResearchPreparation(currentId);
    if (!validReceipt(result)) throw new Error("服务端返回的任务状态无法确认。");
    if (currentGeneration !== generation || !currentScopeMatches(encodedScope)
        || submission.value?.request_id !== currentId) return;
    submission.value = result;
    uncertain.value = false;
    retryConfirmed.value = false;
  } catch (caught) {
    if (currentGeneration === generation) error.value = caught instanceof Error ? caught.message : "任务状态暂时无法读取。";
  } finally {
    if (currentGeneration === generation) refreshing.value = false;
  }
}

async function retry() {
  const current = submission.value;
  const currentScope = scope.value;
  if (!auth.isAdmin || !retryConfirmed.value || !current?.request_id || !current.retry_token
      || !currentScope || !canRetry.value || retrying.value || uncertain.value) return;
  const currentGeneration = generation;
  const encodedScope = JSON.stringify(currentScope);
  const requestId = current.request_id;
  const retryToken = current.retry_token;
  retrying.value = true;
  error.value = "";
  try {
    const result = await retryResearchPreparation(requestId, retryToken);
    if (!validReceipt(result)) throw new Error("服务端未返回可确认的重试回执。");
    if (currentGeneration !== generation || !currentScopeMatches(encodedScope)
        || submission.value?.request_id !== requestId) return;
    submission.value = result;
    uncertain.value = false;
    retryConfirmed.value = false;
  } catch (caught) {
    if (currentGeneration !== generation) return;
    uncertain.value = true;
    retryConfirmed.value = false;
    error.value = caught instanceof Error ? caught.message : "重试结果未确认；请先只读刷新原任务状态。";
  } finally {
    if (currentGeneration === generation) retrying.value = false;
  }
}
</script>

<template>
  <section v-if="handoffValue !== undefined" class="approval-card" aria-label="研究数据准备审核">
    <header><strong>用户提交的研究数据范围</strong><span>管理员复核</span></header>
    <p>这是一个不包含会话内容或用户标识的范围链接。提交后，原用户需在自己的研究会话复查数据可用性。</p>
    <p>若缺少证券上市状态，请先同步证券目录。目录同步完成后，重新确认并提交同一范围。</p>
    <button v-if="auth.isAdmin" type="button" class="secondary-button" @click="emit('securities')">查看证券目录</button>
    <div v-if="invalidHandoff" class="error" role="alert">链接中的范围无效或超出支持上限。请让用户重新生成审核链接。</div>
    <template v-else-if="scope">
      <dl>
        <div><dt>股票代码</dt><dd>{{ scope.symbols.join("、") }}</dd></div>
        <div><dt>日期范围</dt><dd>{{ formatResearchPreparationDate(scope.start_date) }} 至 {{ formatResearchPreparationDate(scope.end_date) }}</dd></div>
        <div><dt>用途</dt><dd>研究</dd></div>
        <div><dt>固定数据</dt><dd>基础日线、交易状态、涨跌停和复权信息</dd></div>
        <div><dt>附加字段</dt><dd>{{ requirementLabels.length ? requirementLabels.join("、") : "未选择估值或财务字段" }}</dd></div>
      </dl>
      <p class="scope-note">后台市场数据按交易日获取。上面的标的列表限定研究范围，不表示 Provider 按股票逐只请求；不会创建股票池，也不会向管理员展示原会话。</p>
      <label class="confirm-line"><input v-model="confirmed" type="checkbox" :disabled="confirming || retrying" /> 我已核对并同意提交以上范围的数据准备</label>
      <button type="button" :disabled="!auth.isAdmin || !confirmed || confirming || retrying" @click="submit">
        {{ confirming ? "正在提交…" : "管理员确认并准备" }}
      </button>
      <p v-if="!auth.isAdmin" class="error" role="alert">当前账号没有管理员权限，未提交准备请求。</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div v-if="uncertain && !submission" class="uncertain" role="status">
        <p>提交结果暂未确认。可用相同范围再次提交。已有请求会返回原回执，未收到的请求会创建一次。</p>
        <button type="button" class="secondary-button" :disabled="confirming || !confirmed" @click="submit">使用同一范围核对原请求</button>
      </div>
      <div v-if="submission" class="receipt" role="status">
        <strong>{{ statusLabel }}</strong>
        <p v-if="failureReasonLabel">{{ failureReasonLabel }}<span v-if="submission.failure_message">：{{ submission.failure_message }}</span></p>
        <p v-if="submission.request_id">请求编号：<code>{{ submission.request_id }}</code></p>
        <p>任务回执只表示准备请求状态，不证明具体指标都有值。请让用户在原研究会话重新检查完全相同的范围；覆盖检查通过后，仍需核实实际数值、口径和来源。</p>
        <button v-if="submission.request_id" type="button" class="secondary-button" :disabled="refreshing || confirming || retrying" @click="refreshReceipt">
          {{ refreshing ? "正在刷新…" : "只读刷新原任务状态" }}
        </button>
        <div v-if="uncertain" class="uncertain" role="status">
          <p>请求结果尚未确认。请先刷新原任务状态；在确认当前终态前，不会显示重试按钮。</p>
        </div>
        <div v-if="canRetry && !uncertain" class="retry-box">
          <p>该终态可以安全重试。重试只会复用此范围和原请求记录；每次重试都需要管理员重新确认。</p>
          <label class="confirm-line"><input v-model="retryConfirmed" type="checkbox" :disabled="retrying || refreshing" /> 我已阅读上述原因，并确认重试此范围</label>
          <button type="button" :disabled="!auth.isAdmin || !retryConfirmed || retrying || refreshing" @click="retry">
            {{ retrying ? "正在安全重试…" : "管理员确认重试" }}
          </button>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.approval-card { margin: 0 0 1rem; padding: 1rem; border: 1px solid var(--byq-border); border-radius: 12px; background: var(--byq-surface); display: grid; gap: .8rem; }
header { display: flex; justify-content: space-between; gap: .5rem; align-items: center; }
header span { color: var(--el-color-warning); }
p { margin: 0; color: var(--byq-text-muted); line-height: 1.55; }
dl { margin: 0; display: grid; gap: .45rem; }
dl div { display: grid; grid-template-columns: 8rem minmax(0, 1fr); gap: .6rem; }
dt { color: var(--byq-text-muted); } dd { margin: 0; overflow-wrap: anywhere; }
.confirm-line { display: flex; align-items: center; gap: .5rem; }
button { width: fit-content; border: 1px solid var(--el-color-primary); border-radius: 7px; padding: .55rem .8rem; background: var(--el-color-primary); color: #fff; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.secondary-button { background: transparent; color: var(--byq-text); border-color: var(--byq-border); }
.error { color: var(--el-color-danger); }
.receipt { padding-top: .75rem; border-top: 1px solid var(--byq-border); display: grid; gap: .5rem; }
.retry-box, .uncertain { padding-top: .6rem; border-top: 1px solid var(--byq-border); display: grid; gap: .55rem; }
code { overflow-wrap: anywhere; }
@media (max-width: 600px) { dl div { grid-template-columns: 1fr; gap: .15rem; } }
</style>
