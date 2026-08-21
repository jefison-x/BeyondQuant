<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { createAgentSession, streamWorkflowEvents, submitTurn } from "@/api/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const open = ref(false);
const sessionId = ref("");
const prompt = ref("");
const answer = ref("");
const error = ref("");
const busy = ref(false);
const pageNames: Record<string, string> = { dashboard: "工作台", agent: "Agent 工作台", strategy: "策略管理", "stock-pool": "股票池", backtest: "回测管理", "paper-trading": "模拟操盘", "research-center": "研究审批", assets: "用户资产" };
const starters = ["总结当前页面可以继续做什么", "帮我梳理下一步研究动作", "解释当前工作流状态"];
const pageContext = computed(() => {
  const label = pageNames[String(route.name)] ?? "BeyondQuant 产品页";
  const identifiers = ["job", "pool", "artifact", "session", "account"]
    .flatMap((key) => {
      const value = route.query[key];
      return typeof value === "string" && /^[A-Za-z0-9_-]{1,160}$/.test(value) ? [`${key}=${value}`] : [];
    });
  return identifiers.length ? `${label}（${identifiers.join("，")}）` : label;
});

function receive(event: { kind: string; payload: Record<string, unknown> }) {
  if (event.kind === "agent.output.delta" && typeof event.payload.delta === "string") answer.value += event.payload.delta;
}

async function ensureSession() {
  if (sessionId.value) return;
  const session = await createAgentSession(auth.token);
  sessionId.value = session.session_id;
  void streamWorkflowEvents(sessionId.value, auth.token, receive, "0").catch((exc) => { error.value = exc instanceof Error ? exc.message : "事件流中断"; });
}

async function send(value = prompt.value) {
  const content = value.trim();
  if (!content) return;
  busy.value = true; error.value = ""; answer.value = "";
  try {
    await ensureSession();
    await submitTurn(sessionId.value, `页面上下文：${pageContext.value}\n用户请求：${content}`, auth.token);
    prompt.value = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发送失败";
  } finally { busy.value = false; }
}
</script>

<template>
  <button class="xiaoba-trigger" type="button" aria-label="打开小巴助手" @click="open = true"><span>小巴</span><small>问一下</small></button>
  <el-drawer v-model="open" title="小巴助手" size="min(92vw, 420px)">
    <div class="assistant-body">
      <p class="context-chip">当前：{{ pageContext }}</p>
      <div class="starter-list"><button v-for="starter in starters" :key="starter" type="button" @click="send(starter)">{{ starter }}</button></div>
      <div v-if="answer" class="assistant-answer">{{ answer }}</div>
      <el-empty v-else description="从当前页面继续你的研究" :image-size="72" />
      <p v-if="error" class="page-error">{{ error }}</p>
      <form @submit.prevent="send()"><el-input v-model="prompt" type="textarea" :rows="3" placeholder="向小巴提问…" /><el-button type="primary" :loading="busy" @click="send()">发送</el-button></form>
    </div>
  </el-drawer>
</template>

<style scoped>
.xiaoba-trigger { background: var(--byq-brand); border: 0; border-radius: 16px; bottom: 22px; box-shadow: 0 12px 28px color-mix(in srgb, var(--byq-brand) 30%, transparent); color: white; cursor: pointer; display: grid; line-height: 1.1; padding: .7rem .9rem; position: fixed; right: 24px; text-align: left; z-index: 30; }
.xiaoba-trigger span { font-size: 14px; font-weight: 800; } .xiaoba-trigger small { font-size: 10px; opacity: .8; }
.assistant-body { display: grid; gap: .85rem; } .context-chip { background: var(--byq-brand-soft); border-radius: 999px; color: var(--byq-brand); font-size: 12px; margin: 0; padding: .45rem .7rem; width: fit-content; }
.starter-list { display: flex; flex-wrap: wrap; gap: .4rem; } .starter-list button { background: var(--byq-surface-subtle); border: 1px solid var(--byq-border); border-radius: 999px; color: var(--byq-text-muted); cursor: pointer; font-size: 11px; padding: .4rem .6rem; }
.assistant-answer { background: var(--byq-surface-subtle); border-radius: 12px; color: var(--byq-text); line-height: 1.7; min-height: 120px; padding: .8rem; white-space: pre-wrap; }
form { display: grid; gap: .5rem; } form .el-button { justify-self: end; }
@media (max-width: 767px) { .xiaoba-trigger { bottom: 72px; right: 14px; } }
</style>
