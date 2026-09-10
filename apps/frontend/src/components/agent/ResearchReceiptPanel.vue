<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { getResearchReceipts, type ResearchReceipt } from '@/api/research';

const props = defineProps<{ conversationId: string }>();
const receipts = ref<ResearchReceipt[]>([]);
const unavailable = ref(false);
const loading = ref(false);
let generation = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const names = { research_task: '研究任务', experiment: '实验', artifact: '研究成果' };
const states = { awaiting_receipt: '正在核对创建结果', confirmed: '已确认创建',
  conflict: '请求身份冲突，需核查', needs_attention: '核对已停止，结果仍未确认' };

async function refresh(version = generation) {
  if (!props.conversationId || loading.value) return;
  const conversation = props.conversationId;
  loading.value = true;
  try {
    const value = await getResearchReceipts(conversation);
    if (version !== generation) return;
    if (value.schema_version !== 'research-receipt-list.v1' || value.conversation_id !== conversation || !Array.isArray(value.receipts)) {
      throw new Error('invalid receipt projection');
    }
    receipts.value = value.receipts;
    unavailable.value = false;
  } catch {
    if (version === generation) unavailable.value = true;
  } finally {
    if (version === generation) {
      loading.value = false;
      clearTimeout(timer);
      timer = setTimeout(() => { void refresh(version); }, 10000);
    }
  }
}

watch(() => props.conversationId, () => {
  generation += 1;
  clearTimeout(timer);
  loading.value = false;
  receipts.value = [];
  unavailable.value = false;
  void refresh(generation);
}, { immediate: true });
onBeforeUnmount(() => { generation += 1; clearTimeout(timer); });
</script>

<template>
  <section v-if="receipts.length || unavailable" class="receipt-panel" aria-label="研究提交核对">
    <header><strong>研究提交核对</strong><button type="button" :disabled="loading" @click="refresh()">刷新状态</button></header>
    <p v-if="unavailable" role="status">暂时无法读取核对状态，已有结果保持不变。请勿重复提交。</p>
    <ul v-if="receipts.length">
      <li v-for="receipt in receipts" :key="receipt.watch_id">
        <div><strong>{{ names[receipt.entity_type] }}</strong> · {{ states[receipt.status] }}</div>
        <small>已核对 {{ receipt.attempts }}/{{ receipt.max_attempts }} 次 · 截止 {{ new Date(receipt.deadline_at).toLocaleString() }}</small>
        <p v-if="receipt.status === 'confirmed'">仅确认对象已创建，不代表研究或计算已完成。</p>
        <p v-else>只查询原请求，不重新执行写入。未查到结果不代表未创建；需关注时请核查原请求。</p>
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
