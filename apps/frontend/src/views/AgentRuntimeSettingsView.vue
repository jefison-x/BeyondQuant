<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import {
  AGENT_EXECUTION_OPTIONS_SCHEMA, getAgentExecutionOptions,
  isAgentExecutionOptionsRecord, updateAgentExecutionOptions,
} from "@/api/agent";
import type { AgentExecutionOptions, AgentExecutionOptionsRecord } from "@/api/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const options = ref<AgentExecutionOptionsRecord | null>(null);
const optionsError = ref("");
const saveNotice = ref("");
const optionsLoading = ref(false);
const savingOwners = ref(new Set<string>());
const updateOperations = new Map<string, symbol>();
let optionsGeneration = 0;
let disposed = false;
const principalScope = () => auth.user?.subject ?? "";
const optionsSaving = computed(() => savingOwners.value.has(principalScope()));

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
      { key: "max_continuations", label: "自动接续次数上限", unit: "次", description: "每个会话任务在同一用户参数版本下的后续自动接续事件数。" },
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


function isCurrentTarget(generation: number, owner: string): boolean {
  return !disposed && generation === optionsGeneration && owner === principalScope();
}

async function loadOptions(generation: number, owner: string): Promise<void> {
  optionsLoading.value = true;
  options.value = null;
  resetDraft(null);
  optionsError.value = "";
  saveNotice.value = "";
  try {
    const current = await getAgentExecutionOptions(auth.token);
    if (!isCurrentTarget(generation, owner)) return;
    if (!isAgentExecutionOptionsRecord(current, owner)) throw new Error("返回的用户参数与当前账户不匹配");
    options.value = current;
    resetDraft(current.options);
  } catch (error) {
    if (isCurrentTarget(generation, owner)) {
      optionsError.value = `当前用户参数状态未知：${error instanceof Error ? error.message : "读取失败"}。请重试读取。`;
    }
  } finally {
    if (isCurrentTarget(generation, owner)) optionsLoading.value = false;
  }
}

function retryOptions(): void {
  const owner = principalScope();
  if (owner && !optionsSaving.value) void loadOptions(++optionsGeneration, owner);
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
  if (options.value) resetDraft(options.value.options);
  optionsError.value = "";
  saveNotice.value = "";
}

async function saveOptions(): Promise<void> {
  const owner = principalScope();
  const generation = optionsGeneration;
  const current = options.value;
  const updatedOptions = draftValidation.value.options;
  if (!owner || !current || !isAgentExecutionOptionsRecord(current, owner)
      || !updatedOptions || !draftChanged.value || updateOperations.has(owner)) return;
  const operation = Symbol(owner);
  updateOperations.set(owner, operation);
  savingOwners.value = new Set([...savingOwners.value, owner]);
  optionsError.value = "";
  saveNotice.value = "";
  try {
    const updated = await updateAgentExecutionOptions({
      schema_version: AGENT_EXECUTION_OPTIONS_SCHEMA,
      expected_revision: current.revision,
      options: updatedOptions,
    }, auth.token);
    if (!isCurrentTarget(generation, owner)) return;
    if (!isAgentExecutionOptionsRecord(updated, owner)) throw new Error("返回的用户参数无法验证");
    options.value = updated;
    resetDraft(updated.options);
    saveNotice.value = "用户运行参数已保存，适用于所有会话的后续执行";
  } catch (error) {
    if (!isCurrentTarget(generation, owner)) return;
    const detail = error instanceof Error ? error.message : "保存结果未知";
    // One authoritative read reconciles a lost or stale response; never replay the write.
    try {
      const latest = await getAgentExecutionOptions(auth.token);
      if (!isCurrentTarget(generation, owner)) return;
      if (!isAgentExecutionOptionsRecord(latest, owner)) throw new Error("当前用户参数无法验证");
      options.value = latest;
      resetDraft(latest.options);
      optionsError.value = `保存结果未确认：${detail}。已读取最新用户参数，请核对后再操作。`;
    } catch (readError) {
      if (!isCurrentTarget(generation, owner)) return;
      options.value = null;
      resetDraft(null);
      optionsError.value = `保存结果未确认，当前值也无法读取：${readError instanceof Error ? readError.message : detail}。请重试读取。`;
    }
  } finally {
    if (updateOperations.get(owner) === operation) {
      updateOperations.delete(owner);
      const pending = new Set(savingOwners.value);
      pending.delete(owner);
      savingOwners.value = pending;
    }
    if (!disposed && generation !== optionsGeneration && owner === principalScope()) {
      void loadOptions(++optionsGeneration, owner);
    }
  }
}

watch(principalScope, (owner) => {
  const generation = ++optionsGeneration;
  options.value = null;
  optionsLoading.value = false;
  resetDraft(null);
  optionsError.value = "";
  saveNotice.value = "";
  if (owner) void loadOptions(generation, owner);
}, { immediate: true, flush: "sync" });

onBeforeUnmount(() => { disposed = true; optionsGeneration += 1; });
</script>

<template>
  <section class="runtime-settings" aria-label="Agent运行参数">
    <header class="runtime-heading">
      <div>
        <h2>Agent运行参数</h2>
        <p>一份用户设置，适用于本账号所有会话的后续执行。</p>
      </div>
    </header>

    <el-alert
      title="自动接续默认开启；这些是可选执行参数，不是许可或业务审批。空白表示不限。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="setting-card">
      <p v-if="optionsLoading" role="status">正在读取当前用户的运行参数；读取完成前状态未知。</p>
      <template v-else-if="options && draftNumericValues">
        <div class="setting-row">
          <div>
            <strong>自动接续</strong>
            <p>所有会话共用此配置。保存后用于后续执行；已经开始的任务保留原参数快照。</p>
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
      <el-button v-if="optionsError && !optionsLoading" text @click="retryOptions">重新读取用户参数</el-button>
    </div>

    <p class="parameter-note">原会话级参数保留为历史记录，不再单独覆盖此用户配置。</p>
  </section>
</template>

<style scoped>
.runtime-settings { display: grid; gap: 14px; max-width: 820px; }
.runtime-heading { align-items: flex-start; display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; }
.runtime-heading h2 { color: var(--byq-text); font-size: 20px; margin: 0 0 5px; }
.runtime-heading p, .setting-row p, .parameter-note, .selected-session, .parameter-actions > span, .parameter-grid small { color: var(--byq-text-muted); font-size: 12px; line-height: 1.6; margin: 0; }
.setting-card { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 12px; padding: 16px; }
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
