<script setup lang="ts">
import { computed } from "vue";
import type { WorkflowCardEvent } from "@/api/types";

const props = defineProps<{ event: WorkflowCardEvent }>();
const emit = defineEmits<{
  navigate: [event: WorkflowCardEvent];
}>();
const card = computed(() => props.event.payload);
const strategy = computed(() => props.event.kind === "agent.card.strategy_draft" ? props.event.payload : null);
const stocks = computed(() => props.event.kind === "agent.card.stock_candidates" ? props.event.payload : null);
const optimization = computed(() => props.event.kind === "agent.card.optimization" ? props.event.payload : null);
const backtest = computed(() => props.event.kind === "agent.card.backtest_context" ? props.event.payload : null);
const approval = computed(() => props.event.kind === "agent.card.approval" ? props.event.payload : null);
const kindLabel = computed(() => ({
  "agent.card.strategy_draft": "策略草稿",
  "agent.card.stock_candidates": "股票候选",
  "agent.card.optimization": "优化建议",
  "agent.card.backtest_context": "回测上下文",
  "agent.card.approval": "人工审批",
}[props.event.kind]));
const actionLabel = computed(() => ({
  "agent.card.strategy_draft": "打开策略工作台",
  "agent.card.stock_candidates": "打开股票池",
  "agent.card.optimization": "审阅策略",
  "agent.card.backtest_context": "查看回测",
  "agent.card.approval": "",
}[props.event.kind]));
</script>

<template>
  <article class="workflow-card" :data-card-kind="event.kind">
    <header>
      <div><span class="card-kind">{{ kindLabel }}</span><h3>{{ card.title }}</h3></div>
      <el-tag size="small" :type="card.authority === 'domain' ? 'success' : 'info'">
        {{ card.authority === "domain" ? "领域状态" : "Agent 建议" }}
      </el-tag>
    </header>
    <p v-if="card.summary" class="card-summary">{{ card.summary }}</p>
    <template v-if="strategy">
      <dl><dt>策略</dt><dd>{{ strategy.name }}</dd></dl>
    </template>
    <template v-else-if="stocks">
      <ul class="candidate-list"><li v-for="item in stocks.items" :key="item.symbol"><strong>{{ item.symbol }}</strong><span>{{ item.name }}</span><small>{{ item.reason }}</small></li></ul>
    </template>
    <template v-else-if="optimization">
      <p class="objective">{{ optimization.objective }}</p>
      <ul class="change-list"><li v-for="change in optimization.changes" :key="`${change.area}-${change.after}`"><strong>{{ change.area }}</strong><span>{{ change.after }}</span><small>{{ change.reason }}</small></li></ul>
    </template>
    <template v-else-if="backtest">
      <dl><dt>任务状态</dt><dd>{{ backtest.status }}</dd><dt>任务 ID</dt><dd>{{ backtest.job_id }}</dd></dl>
    </template>
    <template v-else-if="approval">
      <dl><dt>动作</dt><dd>{{ approval.action }}</dd><dt>审批状态</dt><dd>{{ approval.status }}</dd><dt>执行结果</dt><dd>{{ approval.execution_outcome }}</dd></dl>
    </template>
    <footer>
      <small>修订 {{ card.revision }}</small>
      <span v-if="approval" class="approval-hint">{{ approval.status === "pending" ? "请在右上角铃铛处理" : "审批状态已更新" }}</span>
      <el-button v-else size="small" text type="primary" @click="emit('navigate', event)">{{ actionLabel }}</el-button>
    </footer>
  </article>
</template>

<style scoped>
.workflow-card { background: linear-gradient(145deg, var(--byq-surface), var(--byq-surface-subtle)); border: 1px solid var(--byq-border); border-radius: 12px; display: grid; gap: .7rem; padding: .9rem; }
header, footer { align-items: center; display: flex; gap: .75rem; justify-content: space-between; }
h3 { color: var(--byq-text); font-size: 15px; margin: .15rem 0 0; }
.card-kind, footer small { color: var(--byq-text-soft); font-size: 11px; letter-spacing: .04em; }
.card-summary, .objective { color: var(--byq-text-muted); font-size: 13px; line-height: 1.6; margin: 0; }
dl { display: grid; font-size: 12px; gap: .35rem .7rem; grid-template-columns: auto minmax(0, 1fr); margin: 0; }
dt { color: var(--byq-text-soft); } dd { color: var(--byq-text); margin: 0; overflow-wrap: anywhere; }
.candidate-list, .change-list { display: grid; gap: .4rem; list-style: none; margin: 0; padding: 0; }
.candidate-list li, .change-list li { background: var(--byq-surface); border-radius: 8px; display: grid; gap: .15rem; padding: .5rem .6rem; }
li strong { color: var(--byq-text); font-size: 12px; } li span, li small { color: var(--byq-text-muted); font-size: 11px; }
footer { border-top: 1px solid var(--byq-border-subtle); padding-top: .55rem; }
.approval-hint { color: var(--byq-text-muted); font-size: 11px; }
</style>
