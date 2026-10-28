<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  AGENT_EXECUTION_OPTIONS_SCHEMA,
  getAgentExecutionOptions,
  isAgentExecutionOptionsRecord,
  listAgentSessions,
  updateAgentExecutionOptions,
} from "@/api/agent";
import type { AgentExecutionOptions, AgentExecutionOptionsRecord } from "@/api/agent";
import type { AgentSession } from "@/api/types";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const sessions = ref<AgentSession[]>([]);
const sessionTotal = ref(0);
const sessionOffset = ref(0);
const sessionsLoading = ref(false);
const sessionsError = ref("");
const selectedConversationId = ref("");
const requestedConversationId = ref("");
const selectedSessionMissing = ref(false);
const options = ref<AgentExecutionOptionsRecord | null>(null);
const optionsFor = ref("");
const optionsLoadingFor = ref("");
const optionsError = ref("");
const saveNotice = ref("");
const savingConversationIds = ref(new Set<string>());
const updateOperations = new Map<string, symbol>();
let optionsGeneration = 0;
let sessionListGeneration = 0;
let disposed = false;

type NumericOptionKey = Exclude<keyof AgentExecutionOptions, "auto_continue">;

const parameterGroups: Array<{
  label: string;
  fields: Array<{ key: NumericOptionKey; label: string; unit: string; description: string }>;
}> = [
  {
    label: "调用次数与并发",
    fields: [
      { key: "max_provider_calls", label: "模型请求次数上限", unit: "次", description: "每轮模型请求总数。" },
      { key: "max_provider_attempts", label: "模型请求尝试上限", unit: "次", description: "每轮模型请求尝试总数。" },
      { key: "max_tool_calls", label: "工具调用次数上限", unit: "次", description: "每轮工具调用总数。" },
      { key: "max_concurrent_provider_calls", label: "并发模型请求上限", unit: "次", description: "每轮同时进行的模型请求数。" },
    ],
  },
  {
    label: "输入、输出与工具载荷",
    fields: [
      { key: "max_input_bytes_per_call", label: "单次输入大小上限", unit: "字节", description: "单次模型请求的输入大小。" },
      { key: "max_input_bytes_total", label: "累计输入大小上限", unit: "字节", description: "每轮输入大小总和。" },
      { key: "max_output_tokens_per_call", label: "单次输出上限", unit: "token", description: "单次模型请求声明的输出 token 上限。" },
      { key: "max_output_tokens_total", label: "累计输出上限", unit: "token", description: "每轮各请求声明输出上限之和，不是实际消耗。" },
      { key: "max_tool_payload_bytes_per_call", label: "单个工具载荷上限", unit: "字节", description: "单个工具调用的载荷大小。" },
      { key: "max_tool_payload_bytes_total", label: "工具载荷累计上限", unit: "字节", description: "每轮工具载荷大小总和。" },
    ],
  },
  {
    label: "自动接续与执行时长",
    fields: [
      { key: "max_continuations", label: "自动接续次数上限", unit: "次", description: "同一会话、任务和参数版本后续自动接续事件数。" },
      { key: "max_runtime_seconds", label: "单轮时长上限", unit: "秒", description: "单轮执行的最长时长。" },
      { key: "max_no_progress_seconds", label: "单轮无进展时限", unit: "秒", description: "单轮执行无进展的最长时间。" },
      { key: "max_child_runtime_seconds", label: "子 Agent 时长上限", unit: "秒", description: "分别作用于每个子 Agent 执行。" },
      { key: "max_child_no_progress_seconds", label: "子 Agent 无进展时限", unit: "秒", description: "分别作用于每个子 Agent 执行。" },
    ],
  },
];

const numericOptionKeys = parameterGroups.flatMap((group) => group.fields.map((field) => field.key));
const draftAutoContinue = ref<boolean | null>(null);
const draftNumericValues = ref<Record<NumericOptionKey, string> | null>(null);

const selectedSession = computed(() => sessions.value.find((item) => item.session_id === selectedConversationId.value));
const hasMoreSessions = computed(() => sessionOffset.value < sessionTotal.value);
const optionsLoading = computed(() => optionsLoadingFor.value === selectedConversationId.value
  && Boolean(selectedConversationId.value));
const optionsSaving = computed(() => savingConversationIds.value.has(selectedConversationId.value));

function resetDraft(value: AgentExecutionOptions | null): void {
  draftAutoContinue.value = value?.auto_continue ?? null;
  draftNumericValues.value = value
    ? Object.fromEntries(numericOptionKeys.map((key) => [key, value[key] === null ? "" : String(value[key])])) as Record<NumericOptionKey, string>
    : null;
}

const draftValidation = computed(() => {
  const errors: Partial<Record<NumericOptionKey, string>> = {};
  if (draftAutoContinue.value === null || !draftNumericValues.value) return { options: null, errors };

  const numericOptions = {} as Record<NumericOptionKey, number | null>;
  for (const key of numericOptionKeys) {
    const raw = draftNumericValues.value[key].trim();
    if (!raw) {
      numericOptions[key] = null;
      continue;
    }
    if (!/^\d+$/.test(raw)) {
      errors[key] = "请输入正整数，或留空表示不限";
      continue;
    }
    const parsed = Number(raw);
    if (!Number.isSafeInteger(parsed) || parsed < 1) {
      errors[key] = "请输入可精确表示的正整数，或留空表示不限";
      continue;
    }
    numericOptions[key] = parsed;
  }
  if (Object.keys(errors).length) return { options: null, errors };
  return { options: { auto_continue: draftAutoContinue.value, ...numericOptions }, errors };
});

const draftChanged = computed(() => {
  if (!options.value || !draftNumericValues.value || draftAutoContinue.value === null) return false;
  if (draftAutoContinue.value !== options.value.options.auto_continue) return true;
  return numericOptionKeys.some((key) => {
    const value = draftNumericValues.value?.[key].trim() ?? "";
    const original = options.value?.options[key];
    return value !== (original === null || original === undefined ? "" : String(original));
  });
});

function returnPath(): string {
  if (selectedConversationId.value) return `/agent?session=${encodeURIComponent(selectedConversationId.value)}`;
  const candidate = typeof route.query.returnTo === "string" ? route.query.returnTo : "";
  if (!candidate.startsWith("/") || candidate.startsWith("//")) return "/agent";
  try {
    const parsed = new URL(candidate, window.location.origin);
    if (parsed.origin === window.location.origin && !parsed.pathname.startsWith("/settings/")
        && !parsed.pathname.startsWith("/admin") && parsed.pathname !== "/login") return candidate;
  } catch { /* use the Agent entry when the return path is malformed */ }
  return "/agent";
}

function principalScope(): string {
  const user = auth.user;
  if (!user?.subject || !user.workspace?.workspace_id) return "";
  return JSON.stringify([user.subject, user.workspace.workspace_id]);
}

function conversationFromPath(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/")) return "";
  try {
    const parsed = new URL(value, window.location.origin);
    if (parsed.origin !== window.location.origin || parsed.pathname !== "/agent") return "";
    return parsed.searchParams.get("session") ?? "";
  } catch {
    return "";
  }
}

function requestedSessionFromRoute(): string {
  return (typeof route.query.conversation_id === "string" && route.query.conversation_id)
    || conversationFromPath(route.query.returnTo);
}

function sameOwnerScope(record: AgentExecutionOptionsRecord, scope: string): boolean {
  if (!scope || !auth.user) return false;
  return record.owner_principal === auth.user.subject
    && record.workspace_id === auth.user.workspace.workspace_id;
}

function isCurrentOptionsTarget(conversationId: string, generation: number, scope: string): boolean {
  return !disposed && generation === optionsGeneration
    && conversationId === selectedConversationId.value
    && scope === principalScope();
}

function isCurrentSessionListTarget(generation: number, scope: string): boolean {
  return !disposed && generation === sessionListGeneration && scope === principalScope();
}

function sessionLabel(session: AgentSession): string {
  const title = session.title?.trim() || "新投研对话";
  const updated = session.updated_at?.slice(0, 16).replace("T", " ");
  return updated ? `${title} · ${updated}` : title;
}

async function loadOptions(conversationId: string, generation: number, scope: string): Promise<void> {
  optionsLoadingFor.value = conversationId;
  options.value = null;
  optionsFor.value = "";
  resetDraft(null);
  optionsError.value = "";
  saveNotice.value = "";
  try {
    const current = await getAgentExecutionOptions(conversationId, auth.token);
    if (!isCurrentOptionsTarget(conversationId, generation, scope)) return;
    if (!isAgentExecutionOptionsRecord(current, conversationId) || !sameOwnerScope(current, scope)) {
      throw new Error("返回的会话参数与当前账户或工作区不匹配");
    }
    options.value = current;
    optionsFor.value = conversationId;
    resetDraft(current.options);
  } catch (error) {
    if (isCurrentOptionsTarget(conversationId, generation, scope)) {
      optionsError.value = `自动接续状态未知：${error instanceof Error ? error.message : "读取失败"}。请重试读取。`;
    }
  } finally {
    if (generation === optionsGeneration && optionsLoadingFor.value === conversationId) optionsLoadingFor.value = "";
  }
}

function updateConversationRoute(conversationId: string): void {
  const query = { ...route.query };
  if (conversationId) {
    query.conversation_id = conversationId;
    query.returnTo = `/agent?session=${encodeURIComponent(conversationId)}`;
  } else {
    delete query.conversation_id;
  }
  void router.replace({ path: route.path, query });
}

watch(selectedConversationId, (conversationId) => {
  const generation = ++optionsGeneration;
  options.value = null;
  optionsFor.value = "";
  optionsLoadingFor.value = "";
  resetDraft(null);
  optionsError.value = "";
  saveNotice.value = "";
  selectedSessionMissing.value = Boolean(!conversationId && requestedConversationId.value
    && !sessions.value.some((item) => item.session_id === requestedConversationId.value));
  updateConversationRoute(conversationId);
  if (!conversationId || !sessions.value.some((item) => item.session_id === conversationId)) return;
  const scope = principalScope();
  if (!scope) {
    optionsError.value = "当前账户或工作区身份不可用；自动接续状态未知。";
    return;
  }
  void loadOptions(conversationId, generation, scope);
}, { flush: "sync" });

async function loadSessions(): Promise<void> {
  const scope = principalScope();
  const generation = sessionListGeneration;
  if (sessionsLoading.value || !scope) return;
  sessionsLoading.value = true;
  sessionsError.value = "";
  try {
    const response = await listAgentSessions(auth.token, { limit: 50, offset: sessionOffset.value });
    if (!isCurrentSessionListTarget(generation, scope)) return;
    if (!Array.isArray(response.sessions) || !Number.isSafeInteger(response.total) || response.total < 0) {
      throw new Error("会话列表格式无效");
    }
    const known = new Set(sessions.value.map((item) => item.session_id));
    const page = response.sessions.filter((item) => typeof item?.session_id === "string" && item.session_id.length > 0);
    sessions.value = [...sessions.value, ...page.filter((item) => !known.has(item.session_id))];
    sessionTotal.value = response.total;
    sessionOffset.value += response.sessions.length;
    if (!selectedConversationId.value) {
      const candidate = requestedConversationId.value;
      if (candidate && sessions.value.some((item) => item.session_id === candidate)) {
        selectedConversationId.value = candidate;
        selectedSessionMissing.value = false;
      } else if (candidate) {
        selectedSessionMissing.value = true;
      }
    }
  } catch (error) {
    if (isCurrentSessionListTarget(generation, scope)) {
      sessionsError.value = `无法读取本人会话列表：${error instanceof Error ? error.message : "请求失败"}`;
    }
  } finally {
    if (isCurrentSessionListTarget(generation, scope)) sessionsLoading.value = false;
  }
}

function retryOptions(): void {
  const conversationId = selectedConversationId.value;
  if (!conversationId || !sessions.value.some((item) => item.session_id === conversationId)) return;
  const generation = ++optionsGeneration;
  void loadOptions(conversationId, generation, principalScope());
}

function setDraftAutoContinue(value: unknown): void {
  if (typeof value !== "boolean" || optionsSaving.value) return;
  draftAutoContinue.value = value;
  optionsError.value = "";
  saveNotice.value = "";
}

function updateNumericDraft(key: NumericOptionKey, value: string | number): void {
  if (!draftNumericValues.value || optionsSaving.value) return;
  draftNumericValues.value = { ...draftNumericValues.value, [key]: String(value) };
  optionsError.value = "";
  saveNotice.value = "";
}

function clearNumericDraft(): void {
  if (!draftNumericValues.value || optionsSaving.value) return;
  draftNumericValues.value = Object.fromEntries(numericOptionKeys.map((key) => [key, ""])) as Record<NumericOptionKey, string>;
  optionsError.value = "";
  saveNotice.value = "";
}

function cancelDraft(): void {
  if (options.value && optionsFor.value === selectedConversationId.value) resetDraft(options.value.options);
  optionsError.value = "";
  saveNotice.value = "";
}

async function saveOptions(): Promise<void> {
  const conversationId = selectedConversationId.value;
  const generation = optionsGeneration;
  const scope = principalScope();
  const current = options.value;
  const updatedOptions = draftValidation.value.options;
  if (!conversationId || !current || !updatedOptions || !scope
      || optionsFor.value !== conversationId || !sameOwnerScope(current, scope)
      || !sessions.value.some((item) => item.session_id === conversationId)
      || !draftChanged.value || updateOperations.has(conversationId)) return;

  const operation = Symbol(conversationId);
  updateOperations.set(conversationId, operation);
  savingConversationIds.value = new Set([...savingConversationIds.value, conversationId]);
  optionsError.value = "";
  saveNotice.value = "";
  try {
    const updated = await updateAgentExecutionOptions(conversationId, {
      schema_version: AGENT_EXECUTION_OPTIONS_SCHEMA,
      expected_revision: current.revision,
      options: updatedOptions,
    }, auth.token);
    if (!isCurrentOptionsTarget(conversationId, generation, scope)) return;
    if (!isAgentExecutionOptionsRecord(updated, conversationId) || !sameOwnerScope(updated, scope)) {
      throw new Error("返回的会话参数无法验证");
    }
    options.value = updated;
    optionsFor.value = conversationId;
    resetDraft(updated.options);
    saveNotice.value = "会话参数已保存";
  } catch (error) {
    if (!isCurrentOptionsTarget(conversationId, generation, scope)) return;
    const detail = error instanceof Error ? error.message : "保存结果未知";
    // Reconcile a lost/stale PUT response with one authoritative GET; never replay the write.
    try {
      const currentAfterSave = await getAgentExecutionOptions(conversationId, auth.token);
      if (!isCurrentOptionsTarget(conversationId, generation, scope)) return;
      if (!isAgentExecutionOptionsRecord(currentAfterSave, conversationId) || !sameOwnerScope(currentAfterSave, scope)) {
        throw new Error("当前会话参数无法验证");
      }
      options.value = currentAfterSave;
      optionsFor.value = conversationId;
      resetDraft(currentAfterSave.options);
      optionsError.value = `保存结果未确认：${detail}。已重新读取当前值；如需更改，请再次操作。`;
    } catch (readError) {
      if (!isCurrentOptionsTarget(conversationId, generation, scope)) return;
      options.value = null;
      optionsFor.value = "";
      resetDraft(null);
      optionsError.value = `保存结果未确认，当前值也无法读取：${readError instanceof Error ? readError.message : detail}。请重试读取。`;
    }
  } finally {
    if (updateOperations.get(conversationId) === operation) {
      updateOperations.delete(conversationId);
      const saving = new Set(savingConversationIds.value);
      saving.delete(conversationId);
      savingConversationIds.value = saving;
    }
    if (!disposed && generation !== optionsGeneration
        && conversationId === selectedConversationId.value && scope === principalScope()) {
      await loadOptions(conversationId, optionsGeneration, scope);
    }
  }
}

watch(() => principalScope(), (scope, previousScope) => {
  if (scope === previousScope) return;
  sessionListGeneration += 1;
  optionsGeneration += 1;
  sessions.value = [];
  sessionTotal.value = 0;
  sessionOffset.value = 0;
  sessionsLoading.value = false;
  sessionsError.value = "";
  requestedConversationId.value = "";
  selectedSessionMissing.value = false;
  selectedConversationId.value = "";
  options.value = null;
  optionsFor.value = "";
  optionsLoadingFor.value = "";
  resetDraft(null);
  optionsError.value = "";
  saveNotice.value = "";
  savingConversationIds.value = new Set();
  void router.replace({ path: route.path, query: { returnTo: "/agent" } });
  if (scope) void loadSessions();
}, { flush: "sync" });

onMounted(async () => {
  requestedConversationId.value = requestedSessionFromRoute();
  await loadSessions();
});

onBeforeUnmount(() => {
  disposed = true;
  optionsGeneration += 1;
  sessionListGeneration += 1;
});
</script>

<template>
  <section class="runtime-settings" aria-label="Agent运行参数">
    <header class="runtime-heading">
      <div>
        <h2>Agent运行参数</h2>
        <p>按会话设置自动接续；不影响其他会话。</p>
      </div>
      <el-button text @click="router.push(returnPath())">返回原页面</el-button>
    </header>

    <el-alert
      title="自动接续默认开启；这些是可选执行参数，不是许可或业务审批。空白表示不限。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="setting-card">
      <el-form-item label="选定会话">
        <el-select
          v-model="selectedConversationId"
          class="session-select"
          clearable
          filterable
          placeholder="请选择本人会话"
          aria-label="选定会话"
          :loading="sessionsLoading"
        >
          <el-option
            v-for="session in sessions"
            :key="session.session_id"
            :label="sessionLabel(session)"
            :value="session.session_id"
          />
        </el-select>
      </el-form-item>
      <el-button v-if="hasMoreSessions" text :loading="sessionsLoading" @click="loadSessions">加载更多会话</el-button>
      <p v-if="sessionsError" class="error-copy" role="alert">{{ sessionsError }} <el-button text @click="loadSessions">重试读取</el-button></p>
      <p v-else-if="selectedSessionMissing" class="warning-copy" role="status">
        当前已读取的本人会话列表中尚未找到原会话；未读取或修改其参数。{{ hasMoreSessions ? "可继续加载历史会话，或手动选择一个会话。" : "请从当前列表中手动选择会话。" }}
      </p>
      <p v-if="selectedSession" class="selected-session" aria-live="polite">
        当前会话：{{ selectedSession.title?.trim() || "新投研对话" }} · {{ selectedConversationId }}
      </p>
    </div>

    <div v-if="selectedConversationId && selectedSession" class="setting-card">
      <p v-if="optionsLoading" role="status">正在读取所选会话的当前参数；读取完成前状态未知。</p>
      <template v-else-if="options && optionsFor === selectedConversationId && draftNumericValues">
        <div class="setting-row">
          <div>
            <strong>自动接续</strong>
            <p>只作用于后续自动接续事件；不会取消已运行任务，也不改变它保存的参数快照。</p>
          </div>
          <div class="setting-value">
            <el-switch
              aria-label="允许自动接续"
              :model-value="draftAutoContinue ?? options.options.auto_continue"
              :disabled="optionsSaving"
              @change="setDraftAutoContinue"
            />
            <span role="status">{{ draftAutoContinue ? "已开启" : "已关闭" }}</span>
          </div>
        </div>

        <p class="parameter-note">每次用户请求或自动接续按一轮计算；子 Agent 时长逐个计算。已运行任务保留原参数；输入按字节计，输出按 token 计。</p>
        <section v-for="group in parameterGroups" :key="group.label" class="parameter-group">
          <h3>{{ group.label }}</h3>
          <div class="parameter-grid">
            <el-form-item
              v-for="field in group.fields"
              :key="field.key"
              :label="field.label"
              :error="draftValidation.errors[field.key]"
            >
              <el-input
                :model-value="draftNumericValues[field.key]"
                :disabled="optionsSaving"
                inputmode="numeric"
                autocomplete="off"
                :aria-label="`${field.label}，单位${field.unit}`"
                :placeholder="`不限（${field.unit}）`"
                @input="updateNumericDraft(field.key, $event)"
              >
                <template #append>{{ field.unit }}</template>
              </el-input>
              <small>{{ field.description }} 正整数或留空表示不限。</small>
            </el-form-item>
          </div>
        </section>

        <p v-if="draftChanged" class="warning-copy" role="status">有未保存的修改。</p>
        <p v-if="saveNotice" class="success-copy" role="status">{{ saveNotice }}</p>
        <div class="parameter-actions">
          <el-button text :disabled="optionsSaving" @click="clearNumericDraft">清空所有上限</el-button>
          <span>此操作只修改草稿，仍需点击“保存参数”。</span>
          <div>
            <el-button :disabled="!draftChanged || optionsSaving" @click="cancelDraft">取消修改</el-button>
            <el-button
              type="primary"
              :disabled="!draftChanged || !draftValidation.options || optionsLoading || optionsSaving"
              :loading="optionsSaving"
              @click="saveOptions"
            >保存参数</el-button>
          </div>
        </div>
      </template>
      <p v-else role="status">当前参数状态未知；未使用本地默认值。</p>
      <p v-if="optionsError" class="error-copy" role="alert">{{ optionsError }}</p>
      <el-button v-if="optionsError && !optionsLoading" text @click="retryOptions">重新读取会话参数</el-button>
    </div>

    <el-empty v-else-if="!sessionsLoading && !sessionsError && sessions.length === 0" description="当前没有可设置的会话" />
  </section>
</template>

<style scoped>
.runtime-settings { display: grid; gap: 14px; max-width: 820px; }
.runtime-heading { align-items: flex-start; display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; }
.runtime-heading h2 { color: var(--byq-text); font-size: 20px; margin: 0 0 5px; }
.runtime-heading p, .setting-row p, .parameter-note, .selected-session, .parameter-actions > span, .parameter-grid small { color: var(--byq-text-muted); font-size: 12px; line-height: 1.6; margin: 0; }
.setting-card { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; padding: 16px; }
.session-select { max-width: 520px; width: 100%; }
.selected-session { overflow-wrap: anywhere; }
.setting-row { align-items: center; display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; }
.setting-row strong { color: var(--byq-text); font-size: 14px; }
.setting-row p { margin-top: 4px; max-width: 580px; }
.setting-value { align-items: center; color: var(--byq-text-muted); display: flex; gap: 9px; min-height: 32px; }
.parameter-note { margin-top: 12px; }
.parameter-group { border-top: 1px solid var(--byq-border-subtle); margin-top: 16px; padding-top: 14px; }
.parameter-group h3 { color: var(--byq-text); font-size: 14px; margin: 0 0 12px; }
.parameter-grid { display: grid; gap: 8px 18px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 290px), 1fr)); }
.parameter-grid small { display: block; margin-top: 4px; }
.parameter-actions { align-items: center; border-top: 1px solid var(--byq-border-subtle); display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; margin-top: 14px; padding-top: 14px; }
.parameter-actions > div { display: flex; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.error-copy, .warning-copy, .success-copy { font-size: 12px; line-height: 1.6; margin: 8px 0 0; }
.error-copy { color: var(--el-color-danger); }
.warning-copy { color: var(--el-color-warning); }
.success-copy { color: var(--el-color-success); }
</style>
