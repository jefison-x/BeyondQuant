<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { confirmContinuationPermission, getContinuationPermission, revokeContinuationPermission,
  type ContinuationAvailableProfile, type ContinuationExecutionProfileBinding,
  type ContinuationPermissionView, type ContinuationRequestLimits,
  type ContinuationRequestUsage } from '@/api/research';
import { formatChinaTime } from '@/time';
import { createRequestId } from '@/utils/requestId';

const PROFILE_ID = 'task-ready-read.v1' as const;
const PROFILE_VERSION = 1;
const PROFILE_SCHEMA = 'task-continuation-permission.v2' as const;
const props = defineProps<{ taskId: string; artifacts: Array<Record<string, unknown>> }>();
const view = ref<ContinuationPermissionView | null>(null);
const busy = ref(false);
const error = ref('');
type UnknownMutation =
  | { kind: 'grant'; taskId: string; confirmationId: string; confirmedArtifactIds: string[]; profile: ContinuationAvailableProfile }
  | { kind: 'revoke'; taskId: string; grantVersion: number };
const pendingByTask = new Map<string, UnknownMutation>();
const pendingUnknown = ref<UnknownMutation | null>(null);
const mutationNeedsRefresh = computed(() => pendingUnknown.value !== null);
const selected = ref<string[]>([]);
const confirmed = ref(false);
let generation = 0;
let key = createRequestId();

const eligible = computed(() => props.artifacts.filter(a => a.task_id === props.taskId
  && a.status === 'validated' && ['strategy_version', 'ml_strategy_version'].includes(String(a.kind))));
const eligibleIds = computed(() => new Set(eligible.value.map(a => String(a.artifact_id)).filter(Boolean)));
const reasons: Record<string, string> = {
  permission_missing: '尚未授权后台续接。',
  permission_revoked: '许可已撤销，不会启动新的后台请求。',
  task_terminal: '任务已结束，不会启动新的后台请求。',
  conversation_inactive: '原对话已归档，后台续接已暂停。',
  permission_expired: '许可已到期，不会启动新的后台请求。',
  budget_enforcement_unqualified: '旧版预算执行尚未通过完整验证，当前不会自动继续。',
  continuation_result_unconfirmed: '上次请求结果尚未确认；系统不会自动重放，请刷新状态核对。',
  continuation_usage_unconfirmed: '上次请求的用量记录尚未确认，请刷新状态核对。',
  continuation_request_limit_exceeded: '上次请求超过已记录的资源上限，自动续接已停止。',
  continuation_request_exhausted: '本许可的一次后台请求已用完。',
  request_profile_unqualified: '此请求档案尚未通过运行资格验证。',
  legacy_continuation_read_only: '旧版许可及其历史额度只供核对，不能用于新请求或重新授权。',
  model_or_executor_unqualified: '旧版许可不具备当前请求档案所需的执行资格。',
  waiting_for_event: '尚未确认续接已排队；系统会核对原任务交接及业务完成记录。',
  continuation_needs_attention: '后台请求已结束，但研究目标尚未确认完成，请查看原对话中的进展或阻塞原因。',
};
function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

const limitKeys: Array<keyof ContinuationRequestLimits> = [
  'max_provider_calls', 'max_attempts', 'max_concurrent', 'max_input_bytes', 'max_total_input_bytes',
  'max_output_tokens', 'max_total_output_tokens', 'max_tool_payload_bytes', 'max_total_tool_payload_bytes',
  'max_tool_calls', 'deadline_ms',
];

function isProfileBinding(value: unknown): value is ContinuationExecutionProfileBinding {
  if (!isObject(value)) return false;
  return value.profile_id === PROFILE_ID && Number.isSafeInteger(value.profile_version)
    && value.profile_version === PROFILE_VERSION && typeof value.profile_sha256 === 'string'
    && /^[0-9a-f]{64}$/.test(value.profile_sha256);
}

function isRequestLimits(value: unknown): value is ContinuationRequestLimits {
  if (!isObject(value)) return false;
  const keys = Object.keys(value).sort();
  const expected = [...limitKeys].sort();
  return keys.length === expected.length && keys.every((item, index) => item === expected[index])
    && limitKeys.every(item => Number.isSafeInteger(value[item]) && Number(value[item]) > 0);
}

function isAvailableProfile(value: unknown): value is ContinuationAvailableProfile {
  return isObject(value) && isProfileBinding(value.execution_profile) && isRequestLimits(value.request_limits);
}

function sameProfile(a: ContinuationAvailableProfile, b: ContinuationAvailableProfile): boolean {
  return a.execution_profile.profile_id === b.execution_profile.profile_id
    && a.execution_profile.profile_version === b.execution_profile.profile_version
    && a.execution_profile.profile_sha256 === b.execution_profile.profile_sha256
    && limitKeys.every(name => a.request_limits[name] === b.request_limits[name]);
}

const availableProfile = computed<ContinuationAvailableProfile | null>(() => {
  const current = view.value;
  if (!current || current.schema_version !== PROFILE_SCHEMA || !isAvailableProfile(current.available_profile)) return null;
  return current.available_profile;
});
const permissionProfile = computed<ContinuationAvailableProfile | null>(() => {
  const permission = view.value?.schema_version === PROFILE_SCHEMA ? view.value.permission : null;
  if (!permission || !isProfileBinding(permission.execution_profile) || !isRequestLimits(permission.request_limits)) return null;
  return { execution_profile: permission.execution_profile, request_limits: permission.request_limits };
});
const displayedProfile = computed(() => permissionProfile.value ?? availableProfile.value);
const status = computed(() => {
  if (view.value && view.value.schema_version !== PROFILE_SCHEMA) {
    return '旧版许可与预算记录仅供查看；不会创建、升级或重放后台请求。';
  }
  if (view.value?.schema_version === PROFILE_SCHEMA && view.value.permission && !permissionProfile.value) {
    return 'Backend 返回的请求档案无法核对；当前不能把该许可视为已验证。';
  }
  return view.value?.can_start ? '许可有效；实际请求仍按任务权限和交接条件检查。'
    : reasons[view.value?.blocked_reason ?? ''] ?? '当前不能启动后台续接。';
});
const canCreate = computed(() => {
  const current = view.value;
  return current?.schema_version === PROFILE_SCHEMA && current.permission === null
    && current.request_state.requests_reserved === 0 && current.request_state.unconfirmed_requests === 0
    && current.request_state.requests_remaining === 1 && availableProfile.value !== null;
});
const selectedAssetsValid = computed(() => selected.value.length >= 1 && selected.value.length <= 16
  && new Set(selected.value).size === selected.value.length && selected.value.every(id => eligibleIds.value.has(id)));
const canSubmit = computed(() => canCreate.value && !busy.value && !mutationNeedsRefresh.value
  && confirmed.value && selectedAssetsValid.value);
const latestUsage = computed<ContinuationRequestUsage | null>(() => {
  const current = view.value;
  return current?.schema_version === PROFILE_SCHEMA ? current.request_state.request_usage : null;
});

function usageValue(value: number | 'unknown' | null | undefined): string {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('zh-CN') : '未知';
}

function usageCompleteness(value: ContinuationRequestUsage['actual_usage']['completeness']): string {
  return value === 'known' ? '完整' : value === 'partial' ? '部分' : '未知';
}

function sameIds(actual: unknown, expected: string[]): boolean {
  if (!Array.isArray(actual) || actual.length !== expected.length) return false;
  const sortedActual = [...actual].sort();
  const sortedExpected = [...expected].sort();
  return sortedActual.every((item, index) => item === sortedExpected[index]);
}

function rememberUnknown(mutation: UnknownMutation) {
  pendingByTask.set(mutation.taskId, mutation);
  if (mutation.taskId === props.taskId) pendingUnknown.value = mutation;
}

function clearUnknown(taskId: string) {
  pendingByTask.delete(taskId);
  if (taskId === props.taskId) pendingUnknown.value = null;
}

function readonlyConfirmsMutation(result: ContinuationPermissionView, pending: UnknownMutation): boolean {
  if (result.task_id !== pending.taskId || !result.permission) return false;
  if (pending.kind === 'revoke') {
    return result.permission.grant_version === pending.grantVersion && result.permission.revoked_at !== null;
  }
  if (result.schema_version !== PROFILE_SCHEMA || !result.permission
      || result.permission.confirmation_id !== pending.confirmationId
      || !sameIds(result.permission.confirmed_artifact_ids, pending.confirmedArtifactIds)
      || !isProfileBinding(result.permission.execution_profile) || !isRequestLimits(result.permission.request_limits)) {
    return false;
  }
  return sameProfile(pending.profile, { execution_profile: result.permission.execution_profile,
    request_limits: result.permission.request_limits });
}

async function act(operation: () => Promise<ContinuationPermissionView>, mutating = false) {
  if (busy.value) return;
  const current = generation;
  busy.value = true;
  error.value = '';
  try {
    const result = await operation();
    if (current === generation) {
      if (result.task_id !== props.taskId) throw new Error('许可返回的任务身份不一致，请刷新核对。');
      view.value = result;
      if (mutating) clearUnknown(props.taskId);
    }
  } catch (exc) {
    if (current === generation) {
      error.value = exc instanceof Error ? exc.message : '操作结果未确认，请刷新核对。';
    }
  } finally {
    if (current === generation) busy.value = false;
  }
}

function refresh() {
  const pending = pendingUnknown.value;
  return act(async () => {
    const result = await getContinuationPermission(props.taskId);
    if (result.task_id !== props.taskId) throw new Error('许可返回的任务身份不一致，请刷新核对。');
    if (pending && readonlyConfirmsMutation(result, pending)) {
      clearUnknown(pending.taskId);
    }
    return result;
  });
}

function submit() {
  if (!canCreate.value || !availableProfile.value || !confirmed.value || !selectedAssetsValid.value
      || mutationNeedsRefresh.value || busy.value) {
    error.value = mutationNeedsRefresh.value
      ? '上次授权结果尚未核对；请先刷新许可状态。'
      : '请确认当前任务、已验证策略资产及系统提供的单次请求上限。';
    return;
  }
  const selectedIds = [...selected.value];
  const requestedProfile = availableProfile.value;
  const payload = {
    idempotency_key: key,
    confirmed_artifact_ids: selectedIds,
    execution_profile_id: PROFILE_ID,
  };
  rememberUnknown({ kind: 'grant', taskId: props.taskId, confirmationId: key,
    confirmedArtifactIds: selectedIds, profile: requestedProfile });
  return act(async () => {
    const result = await confirmContinuationPermission(props.taskId, payload);
    if (result.schema_version !== PROFILE_SCHEMA || !result.permission
        || result.permission.confirmation_id !== key
        || !isProfileBinding(result.permission.execution_profile) || !isRequestLimits(result.permission.request_limits)
        || !sameProfile(requestedProfile, { execution_profile: result.permission.execution_profile,
          request_limits: result.permission.request_limits })
        || !sameIds(result.permission.confirmed_artifact_ids, selectedIds)) {
      throw new Error('授权结果与已确认的请求档案或策略资产不一致；请刷新状态并核对。');
    }
    return result;
  }, true);
}

function revoke() {
  const permission = view.value?.permission;
  if (permission && permission.revoked_at === null) {
    const version = permission.grant_version;
    rememberUnknown({ kind: 'revoke', taskId: props.taskId, grantVersion: version });
    return act(async () => {
      const result = await revokeContinuationPermission(props.taskId, version);
      if (!result.permission || result.permission.grant_version !== version || result.permission.revoked_at === null) {
        throw new Error('撤销结果尚未确认；请刷新状态核对。');
      }
      return result;
    }, true);
  }
}

watch(() => props.taskId, () => {
  generation++;
  view.value = null;
  busy.value = false;
  error.value = '';
  pendingUnknown.value = pendingByTask.get(props.taskId) ?? null;
  selected.value = [];
  confirmed.value = false;
  key = createRequestId();
  void refresh();
}, { immediate: true });
</script>

<template>
  <section aria-label="任务后台续接许可" class="continuation-panel" v-loading="busy">
    <h3>后台续接许可</h3>
    <p class="task-identity">任务：{{ taskId }}</p>
    <p>后台仅可按同一任务的有效交接继续一次只读研究请求。新请求使用独立的资源上限；业务权限仍逐项校验。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert v-if="mutationNeedsRefresh" title="授权操作结果尚未核对。本页面不会自动重发，请先刷新许可状态。" type="warning" :closable="false" />
    <p v-if="view" role="status">{{ status }}</p>

    <template v-if="view?.schema_version === PROFILE_SCHEMA && view.permission">
      <p>请求档案：{{ view.permission.execution_profile.profile_id }} v{{ view.permission.execution_profile.profile_version }}；指纹 {{ view.permission.execution_profile.profile_sha256 }}</p>
      <p v-if="view.permission.turn_timeout_seconds">接续处理等待上限：{{ view.permission.turn_timeout_seconds }} 秒；许可到期：{{ formatChinaTime(view.permission.expires_at) }}</p>
      <p v-else>许可到期：{{ formatChinaTime(view.permission.expires_at) }}</p>
      <p>已预留请求：{{ view.request_state.requests_reserved }}；剩余请求：{{ view.request_state.requests_remaining }}；未确认请求：{{ view.request_state.unconfirmed_requests }}</p>
      <ul v-if="displayedProfile" class="request-limits" aria-label="可信单次请求资源上限">
        <li>模型请求次数：{{ displayedProfile.request_limits.max_provider_calls }}；尝试次数：{{ displayedProfile.request_limits.max_attempts }}；并发：{{ displayedProfile.request_limits.max_concurrent }}</li>
        <li>单次输入：{{ displayedProfile.request_limits.max_input_bytes }} 字节；总输入：{{ displayedProfile.request_limits.max_total_input_bytes }} 字节</li>
        <li>单次输出上限：{{ displayedProfile.request_limits.max_output_tokens }} token；总输出：{{ displayedProfile.request_limits.max_total_output_tokens }} token</li>
        <li>单次工具数据：{{ displayedProfile.request_limits.max_tool_payload_bytes }} 字节；累计工具数据：{{ displayedProfile.request_limits.max_total_tool_payload_bytes }} 字节；工具调用：{{ displayedProfile.request_limits.max_tool_calls }} 次</li>
        <li>单次请求期限：{{ displayedProfile.request_limits.deadline_ms }} 毫秒</li>
      </ul>
      <p v-if="latestUsage" aria-label="实际用量记录">
        实际用量：输入 {{ usageValue(latestUsage.actual_usage.input_tokens) }} token，缓存读取 {{ usageValue(latestUsage.actual_usage.cache_read_tokens) }} token，
        输出 {{ usageValue(latestUsage.actual_usage.output_tokens) }} token；模型尝试 {{ usageValue(latestUsage.actual_usage.provider_attempts) }} 次；
        完整性：{{ usageCompleteness(latestUsage.actual_usage.completeness) }}。
      </p>
      <p v-else>实际用量：暂无请求记录；资源上限不代表真实消耗。</p>
      <p>真实用量与安全上限分开记录；未知用量会明确显示为“未知”。</p>
      <el-button v-if="view.permission.revoked_at === null" :disabled="busy || mutationNeedsRefresh" type="danger" plain @click="revoke">撤销后台续接许可</el-button>
    </template>

    <template v-else-if="view?.schema_version === 'task-continuation-permission.v1'">
      <template v-if="view.permission">
        <p>旧版许可：总额度 {{ view.permission.token_limit }} token；到期：{{ formatChinaTime(view.permission.expires_at) }}</p>
        <p v-if="view.budget">历史预算记录：可用 {{ view.budget.available_tokens }}；预留 {{ view.budget.reserved_tokens }}；记账 {{ view.budget.charged_tokens }} token；剩余回合 {{ view.budget.turns_remaining }}。</p>
        <p>这些是旧账本记录，不代表模型实际用量或费用；未知结果仍按未确认责任处理。</p>
        <el-button v-if="view.permission.revoked_at === null" :disabled="busy || mutationNeedsRefresh" type="danger" plain @click="revoke">撤销旧版许可</el-button>
      </template>
      <p v-else>当前接口尚未提供新版授权档案，无法创建许可。请刷新后核对。</p>
    </template>

    <template v-else-if="view?.schema_version === PROFILE_SCHEMA && !view.permission">
      <el-form v-if="canCreate" label-position="top" @submit.prevent="submit">
        <p>系统为此许可提供的请求上限如下。每个许可只允许一个后台请求；仅可选择本任务已验证的策略版本。</p>
        <p>请求档案：{{ availableProfile?.execution_profile.profile_id }} v{{ availableProfile?.execution_profile.profile_version }}；指纹 {{ availableProfile?.execution_profile.profile_sha256 }}</p>
        <ul class="request-limits" aria-label="可信单次请求资源上限">
          <li>模型请求次数：{{ availableProfile?.request_limits.max_provider_calls }}；尝试次数：{{ availableProfile?.request_limits.max_attempts }}；并发：{{ availableProfile?.request_limits.max_concurrent }}</li>
          <li>单次输入：{{ availableProfile?.request_limits.max_input_bytes }} 字节；总输入：{{ availableProfile?.request_limits.max_total_input_bytes }} 字节</li>
          <li>单次输出上限：{{ availableProfile?.request_limits.max_output_tokens }} token；总输出：{{ availableProfile?.request_limits.max_total_output_tokens }} token</li>
          <li>单次工具数据：{{ availableProfile?.request_limits.max_tool_payload_bytes }} 字节；累计工具数据：{{ availableProfile?.request_limits.max_total_tool_payload_bytes }} 字节；工具调用：{{ availableProfile?.request_limits.max_tool_calls }} 次</li>
          <li>单次请求期限：{{ availableProfile?.request_limits.deadline_ms }} 毫秒</li>
        </ul>
        <p>限额来自 Backend 当前可信档案。它们是安全上限，不是预计或实际 token 用量、账单金额或业务权限。</p>
        <el-form-item label="确认本任务的策略版本">
          <el-select v-model="selected" multiple :multiple-limit="16" :disabled="busy || mutationNeedsRefresh" :fit-input-width="true"
            popper-class="continuation-assets" placeholder="选择已验证策略版本" style="width: 100%">
            <el-option v-for="asset in eligible" :key="String(asset.artifact_id)" :value="String(asset.artifact_id)"
              :label="`${asset.kind} · ${asset.artifact_id}`" />
          </el-select>
          <p v-if="!eligible.length">当前没有本任务已验证的策略版本，请先在原研究对话中准备。</p>
        </el-form-item>
        <el-checkbox v-model="confirmed" :disabled="busy || mutationNeedsRefresh">我确认任务、所选策略版本和系统显示的请求档案，并允许该许可按有效交接执行一次只读研究请求。</el-checkbox>
        <div><el-button native-type="submit" type="primary" :disabled="!canSubmit">保存单次请求许可</el-button></div>
      </el-form>
      <p v-else-if="!availableProfile">Backend 尚未提供可核对的可信请求档案。当前不能创建许可。</p>
      <p v-else>当前许可已有请求或未确认结果，不能创建第二个后台请求。请刷新状态核对。</p>
    </template>

    <el-button :disabled="busy" data-test="refresh-permission" @click="refresh">刷新许可状态</el-button>
  </section>
</template>

<style scoped>
.continuation-panel { margin-top: 16px; max-width: 760px; }
.continuation-panel p { line-height: 1.6; }
.continuation-panel ul { line-height: 1.6; padding-left: 24px; }
.task-identity { overflow-wrap: anywhere; }
.continuation-panel .el-button { margin-top: 12px; }
.continuation-panel .el-checkbox { max-width: 100%; height: auto; align-items: flex-start; }
.continuation-panel :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; line-height: 1.6; }
.continuation-panel :deep(.el-checkbox__input) { margin-top: 4px; }
</style>

<style>
.continuation-assets .el-select-dropdown__item {
  height: auto; white-space: normal; overflow-wrap: anywhere;
  line-height: 1.6; padding-top: 6px; padding-bottom: 6px;
}
</style>
