<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { getResearchReceipts, ResearchRequestError, type ResearchReceipt } from '@/api/research';

const props = defineProps<{ conversationId: string }>();
const receipts = ref<ResearchReceipt[]>([]);
const unavailable = ref(false);
const sessionExpired = ref(false);
const loading = ref(false);
const refreshFeedback = ref('');
const lastSuccessfulRefreshAt = ref('');
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const loginHref = computed(() => {
  const returnPath = `/agent?session=${encodeURIComponent(props.conversationId)}`;
  return `/login?redirect=${encodeURIComponent(returnPath)}`;
});
const names = { research_task: '研究任务', experiment: '实验', artifact: '研究成果' };
const states = { awaiting_receipt: '正在核对创建结果', confirmed: '已确认创建',
  conflict: '请求身份冲突，需核查', needs_attention: '核对已停止，结果仍未确认' };
const outstandingReceipts = computed(() => receipts.value.filter((receipt) => receipt.status !== 'confirmed'));

async function refresh(version = generation, manual = true) {
  if (!props.conversationId || loading.value) return;
  const conversation = props.conversationId;
  loading.value = true;
  refreshFeedback.value = '';
  try {
    const value = await getResearchReceipts(conversation);
    if (version !== generation) return;
    if (value.schema_version !== 'research-receipt-list.v1' || value.conversation_id !== conversation || !Array.isArray(value.receipts)) {
      throw new Error('invalid receipt projection');
    }
    receipts.value = value.receipts;
    unavailable.value = false;
    sessionExpired.value = false;
    lastSuccessfulRefreshAt.value = new Date().toISOString();
    if (manual) refreshFeedback.value = '核对记录已刷新';
  } catch (error) {
    if (version === generation) {
      const loginRequired = error instanceof ResearchRequestError
        && [401, 403].includes(error.status)
        && ['session_invalid', 'product_authentication_required'].includes(error.code ?? '');
      sessionExpired.value = loginRequired;
      unavailable.value = !loginRequired;
    }
  } finally {
    if (version === generation) {
      loading.value = false;
      clearTimeout(timer);
      if (!sessionExpired.value) timer = setTimeout(() => { void refresh(version, false); }, 10000);
    }
  }
}

watch(() => props.conversationId, () => {
  generation += 1;
  clearTimeout(timer);
  loading.value = false;
  receipts.value = [];
  unavailable.value = false;
  sessionExpired.value = false;
  refreshFeedback.value = '';
  lastSuccessfulRefreshAt.value = '';
  void refresh(generation, false);
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; clearTimeout(timer); });
</script>

<template>
  <section v-if="outstandingReceipts.length || unavailable || sessionExpired" class="receipt-panel" aria-label="研究提交回执待确认">
    <header><strong>提交结果待确认</strong><button type="button" :disabled="loading" @click="refresh()">刷新核对记录</button></header>
    <p v-if="loading" role="status">正在刷新核对记录…</p>
    <p v-else-if="refreshFeedback" role="status">{{ refreshFeedback }}</p>
    <p v-if="lastSuccessfulRefreshAt" class="refresh-time">最近成功刷新：<time data-test="last-successful-refresh" :datetime="lastSuccessfulRefreshAt">{{ new Date(lastSuccessfulRefreshAt).toLocaleString() }}</time></p>
    <p v-if="unavailable" role="status">暂时无法读取核对状态，已有结果保持不变。请勿重复提交。</p>
    <p v-if="sessionExpired" role="status">登录已失效，已有结果保持不变。请重新登录后返回当前会话查看核对状态。 <a :href="loginHref">登录并返回此会话</a></p>
    <ul v-if="outstandingReceipts.length">
      <li v-for="receipt in outstandingReceipts" :key="receipt.watch_id">
        <div><strong>{{ names[receipt.entity_type] }}提交回执</strong> · {{ states[receipt.status] }}</div>
        <p v-if="receipt.status === 'awaiting_receipt'">只核对原提交，不重新执行写入。尚未取得创建回执不代表提交失败。</p>
        <p v-else>原提交需要核查；不会自动重发。提交回执只说明请求结果，不代表研究或计算任务已完成。</p>
        <details><summary>核对编号</summary><code>{{ receipt.watch_id }}</code><code v-if="receipt.entity_id">{{ receipt.entity_id }}</code></details>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.receipt-panel { margin: 1rem auto; max-width: 860px; padding: 1rem; border: 1px solid var(--byq-border); border-radius: 12px; background: var(--byq-surface); font-size: 13px; overflow-wrap: anywhere; }
header { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
button { background: transparent; border: 1px solid var(--byq-border); border-radius: 6px; padding: .3rem .6rem; color: var(--byq-text); cursor: pointer; }
ul { list-style: none; padding: 0; margin: .7rem 0 0; display: grid; gap: .75rem; }
li { border-top: 1px solid var(--byq-border-subtle); padding-top: .6rem; }
small, p, details { color: var(--byq-text-muted); } p { margin: .3rem 0; } code { display: block; white-space: normal; }
</style>
