<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { confirmContinuationPermission, getContinuationPermission, revokeContinuationPermission,
  type ContinuationPermissionView } from '@/api/research';
import { formatChinaTime } from '@/time';

const props = defineProps<{ taskId: string; artifacts: Array<Record<string, unknown>> }>();
const view = ref<ContinuationPermissionView | null>(null);
const busy = ref(false);
const error = ref('');
const tokenLimit = ref<number | undefined>();
const selected = ref<string[]>([]);
const confirmed = ref(false);
let generation = 0;
let key = crypto.randomUUID();
const eligible = computed(() => props.artifacts.filter(a => a.task_id === props.taskId && a.status === 'validated'));
const reasons: Record<string, string> = {
  permission_missing: '尚未授权后台续接。',
  permission_revoked: '许可已撤销，不会启动新的后台回合。',
  task_terminal: '任务已结束，不会启动新的后台回合。',
  conversation_inactive: '原对话已归档，后台续接已暂停。',
  permission_expired: '许可已到期，不会启动新的后台回合。',
  budget_enforcement_unqualified: '后台预算执行尚未通过完整验证，当前不会自动继续。',
  continuation_result_unconfirmed: '上次执行结果尚未确认，已预留额度不会自动返还。',
  model_or_executor_unqualified: '所选模型暂不支持已验证的后台预算控制，请在原对话中手动继续。',
  waiting_for_event: '正在等待本任务的训练、预测、信号或回测结果；有结果后按许可检查下一步。',
  budget_exhausted: '后台 token 额度或回合额度不足，自动续接已停止。',
  continuation_needs_attention: '后台回合已结束，但研究目标尚未确认完成，请查看原对话中的进展或阻塞原因。',
};
const status = computed(() => view.value?.can_start ? '许可有效；下一步仍按任务权限检查。'
  : reasons[view.value?.blocked_reason ?? ''] ?? '当前不能启动后台续接。');

async function act(operation: () => Promise<ContinuationPermissionView>) {
  if (busy.value) return;
  const current = generation;
  busy.value = true;
  error.value = '';
  try {
    const result = await operation();
    if (current === generation) {
      if (result.task_id !== props.taskId) throw new Error('许可返回的任务身份不一致，请刷新核对。');
      view.value = result;
    }
  } catch (exc) {
    if (current === generation) error.value = exc instanceof Error ? exc.message : '操作结果未确认，请刷新核对。';
  } finally {
    if (current === generation) busy.value = false;
  }
}
function refresh() { return act(() => getContinuationPermission(props.taskId)); }
function submit() {
  if (!confirmed.value || !Number.isSafeInteger(tokenLimit.value) || !tokenLimit.value || tokenLimit.value < 1
      || !selected.value.length) {
    error.value = '请填写明确的 token 总额度，选择已验证资产并确认许可范围。';
    return;
  }
  const payload = { idempotency_key: key, token_limit: tokenLimit.value, confirmed_artifact_ids: [...selected.value] };
  return act(() => confirmContinuationPermission(props.taskId, payload));
}
function revoke() {
  if (view.value?.permission) {
    const version = view.value.permission.grant_version;
    return act(() => revokeContinuationPermission(props.taskId, version));
  }
}
watch(() => props.taskId, () => {
  generation++; view.value = null; busy.value = false; error.value = '';
  selected.value = []; tokenLimit.value = undefined; confirmed.value = false; key = crypto.randomUUID();
  void refresh();
}, { immediate: true });
</script>

<template>
  <section aria-label="任务后台续接许可" class="continuation-panel" v-loading="busy">
    <h3>后台续接许可</h3>
    <p class="task-identity">任务：{{ taskId }}</p>
    <p>仅恢复本任务原目标。许可有效期 24 小时，最多 8 个后台回合，每回合最多 15 分钟；训练、预测和回测仍逐项检查权限。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <p v-if="view" role="status">{{ status }}</p>
    <template v-if="view?.permission">
      <p>总额度：{{ view.permission.token_limit }} token；到期：{{ formatChinaTime(view.permission.expires_at) }}</p>
      <p v-if="view.budget">可用：{{ view.budget.available_tokens }}；已预留：{{ view.budget.reserved_tokens }}；已记账：{{ view.budget.charged_tokens }} token；剩余回合：{{ view.budget.turns_remaining }}</p>
      <p>预留与记账额度不代表精确费用账单。未知结果会继续占用预留额度。</p>
      <el-button v-if="!view.permission.revoked_at" :disabled="busy" type="danger" plain @click="revoke">撤销后台续接许可</el-button>
    </template>
    <el-form v-else-if="view" label-position="top" @submit.prevent="submit">
      <el-form-item label="任务累计 token 额度（必须明确填写）">
        <p>采用保守 token 上界记账，每次模型请求至少预留 1,056,768 token；后台不使用联网搜索。</p>
        <el-input-number aria-label="任务累计 token 额度" v-model="tokenLimit" :min="1" :max="Number.MAX_SAFE_INTEGER" :precision="0" :disabled="busy" />
      </el-form-item>
      <el-form-item label="确认本任务使用的已验证资产">
        <el-select v-model="selected" multiple :multiple-limit="16" :disabled="busy" placeholder="选择已验证资产" style="width: 100%">
          <el-option v-for="asset in eligible" :key="String(asset.artifact_id)" :value="String(asset.artifact_id)"
            :label="`${asset.kind} · ${asset.artifact_id}`" />
        </el-select>
        <p v-if="!eligible.length">当前列表没有本任务的已验证资产，请先在原研究对话中准备资产。</p>
      </el-form-item>
      <el-checkbox v-model="confirmed" :disabled="busy">我确认上述任务、资产、额度与有效期；已保存许可不代表后台执行已启用。</el-checkbox>
      <div><el-button native-type="submit" type="primary" :disabled="busy || !confirmed">保存续接许可</el-button></div>
    </el-form>
    <el-button :disabled="busy" @click="refresh">刷新许可状态</el-button>
  </section>
</template>

<style scoped>
.continuation-panel { margin-top: 16px; max-width: 760px; }
.continuation-panel p { line-height: 1.6; }
.task-identity { overflow-wrap: anywhere; }
.continuation-panel .el-button { margin-top: 12px; }
</style>
