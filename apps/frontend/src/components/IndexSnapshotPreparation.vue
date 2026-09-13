<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useAuthStore } from '@/stores/auth';
import type { DataDemand } from '@/api/types';

const props = defineProps<{ indexSymbol: string; requestedAsOf: string }>();
const emit = defineEmits<{ ready: [] }>();
const auth = useAuthStore();
const busy = ref(false);
const message = ref('');
const demand = ref<DataDemand | null>(null);
const date = computed(() => props.requestedAsOf?.replaceAll('-', '') ?? '');
// Domain identity is reproducible after reload, including a lost POST reply.
const key = computed(() => `index-snapshot-v1:${props.indexSymbol}:${date.value}`);
const valid = computed(() => ['000016.SH','000300.SH','000688.SH','000852.SH','000905.SH','399006.SZ'].includes(props.indexSymbol) && /^\d{8}$/.test(date.value));
let generation = 0;
watch(() => [props.indexSymbol, props.requestedAsOf, auth.user?.subject, auth.user?.workspace?.workspace_id], () => {
  generation++; demand.value = null; message.value = ''; busy.value = false;
});
async function request(path: string, init: RequestInit = {}) {
  const response = await fetch('/api/product/data-center/demands' + path, {
    ...init, credentials: 'include', headers: { 'content-type': 'application/json' },
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error('准备请求未确认，请先查询原请求；若失败，请在数据中心核查权限和数据源。');
  return response.json();
}
async function run(create: boolean) {
  if (!valid.value || busy.value) return;
  const current = generation;
  const originalKey = key.value;
  busy.value = true; message.value = '';
  try {
    let value;
    if (create) value = await request('', { method: 'POST', body: JSON.stringify({
      purpose: 'research', scope_kind: 'index_snapshot', index_symbol: props.indexSymbol,
      requested_as_of: date.value, idempotency_key: originalKey,
    }) });
    else {
      const receipt = await request('/by-key/' + encodeURIComponent(originalKey));
      if (receipt.state === 'not_found') {
        if (current === generation) message.value = '尚未查到原请求，可使用相同范围提交准备。';
        return;
      }
      if (receipt.state !== 'confirmed' || !/^datademand_[0-9a-f]{32}$/.test(receipt.demand?.demand_id)) throw new Error('原请求回执无法确认。');
      value = await request('/' + receipt.demand.demand_id);
      if (value.demand?.demand_id !== receipt.demand.demand_id) throw new Error('进度回执与原请求不一致。');
    }
    if (current !== generation) return;
    if (value.demand?.scope?.index_symbol !== props.indexSymbol || value.demand?.scope?.requested_as_of !== date.value
        || value.demand?.scope?.historical_series !== false) throw new Error('准备范围与当前选择不一致。');
    demand.value = value.demand;
    if (demand.value?.status === 'ready') emit('ready');
  } catch (error) {
    if (current === generation) message.value = error instanceof Error ? error.message : '请求未确认，请查询原请求。';
  } finally { if (current === generation) busy.value = false; }
}
</script>

<template>
  <div class="index-preparation" aria-label="历史指数数据准备">
    <p>缺少历史成分时，先准备所选时点数据，再创建股票池。单次快照不代表整段历史调仓序列或行情就绪。</p>
    <el-button v-if="auth.isAdmin" :disabled="!valid || busy" :loading="busy" @click="run(true)">准备历史成分</el-button>
    <el-button :disabled="!valid || busy" @click="run(false)">查询准备进度</el-button>
    <p v-if="!auth.isAdmin">历史数据准备需管理员提交。</p>
    <el-alert v-if="message" :title="message" type="warning" :closable="false" />
    <el-alert v-if="demand" :title="demand.notification" :type="demand.status === 'ready' ? 'success' : demand.status === 'failed' ? 'error' : 'info'" :closable="false" />
  </div>
</template>

<style scoped>
.index-preparation { margin: 12px 0; }
.index-preparation p { color: var(--el-text-color-secondary); line-height: 1.6; }
.index-preparation .el-alert { margin-top: 10px; }
</style>
