<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  cancelSession, createAgentSession, getAgentSession, listAgentSessions, resumeSession,
  streamWorkflowEvents, submitTurn, updateAgentSession,
} from "@/api/agent";
import { foldWorkflowCards, workflowActivities } from "@/api/workflow";
import type { AgentReplayMessage, AgentSession, WorkflowCardEvent, WorkflowTraceEvent } from "@/api/types";
import { decideApproval, getApproval, listApprovals } from "@/api/research";
import AgentActivityPanel from "@/components/agent/AgentActivityPanel.vue";
import ApprovalManagementPanel from "@/components/agent/ApprovalManagementPanel.vue";
import WorkflowCard from "@/components/agent/WorkflowCard.vue";
import { useAgentStore, type AgentMessage } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const agent = useAgentStore();
const prompt = ref("");
const error = ref("");
const busy = ref(false);
const loading = ref(false);
const approvalBusy = ref("");
const approvals = ref<Array<Record<string, unknown>>>([]);
const approvalStates = ref<Record<string, Record<string, unknown>>>({});
const initialized = ref(false);
const activityOpen = ref(false);
const historyOpen = ref(false);
const historyStatus = ref<"active" | "archived">("active");
const historySearch = ref("");
const historyItems = ref<AgentSession[]>([]);
const historyTotal = ref(0);
const conversationRef = ref<HTMLElement | null>(null);
const starters = ["筛选一组可研究的股票候选", "起草一个可验证的量化策略", "根据最近回测提出优化建议"];
let conversationGeneration = 0;
let streamController: AbortController | null = null;

const activeSession = computed(() => agent.sessions.find((item) => item.session_id === agent.activeSessionId));
const activities = computed(() => workflowActivities(agent.events));
const cards = computed(() => foldWorkflowCards(agent.events).map((event) => {
  if (event.kind !== "agent.card.approval") return event;
  const latest = approvalStates.value[event.payload.approval_id];
  return latest ? { ...event, payload: { ...event.payload, ...latest } } as WorkflowCardEvent : event;
}));
const timeline = computed(() => [
  ...agent.messages.map((message, index) => ({ type: "message" as const, at: message.createdAt ?? "", key: `message-${index}`, message })),
  ...cards.value.map((card) => ({ type: "card" as const, at: card.timestamp, key: `card-${card.payload.card_id}`, card })),
].sort((left, right) => left.at.localeCompare(right.at)));

function replayMessages(messages: AgentReplayMessage[], events: WorkflowTraceEvent[]): AgentMessage[] {
  const ordered = [
    ...messages.map((message) => ({ kind: "user" as const, at: message.created_at, text: message.content })),
    ...events.filter((event) => event.kind === "agent.output.delta" && typeof event.payload.delta === "string")
      .map((event) => ({ kind: "agent" as const, at: event.timestamp, text: String(event.payload.delta) })),
  ].sort((left, right) => left.at.localeCompare(right.at));
  const result: AgentMessage[] = [];
  for (const item of ordered) {
    const last = result[result.length - 1];
    if (item.kind === "agent" && last?.role === "agent") last.text += item.text;
    else result.push({ role: item.kind, text: item.text, createdAt: item.at });
  }
  return result;
}

function stopStream() { streamController?.abort(); streamController = null; }

function handleEvent(event: WorkflowTraceEvent, generation: number) {
  if (generation !== conversationGeneration || event.session_id !== agent.activeSessionId) return;
  if (agent.events.some((current) => current.sequence === event.sequence)) return;
  agent.addEvent(event);
  if (event.kind === "agent.output.delta" && typeof event.payload.delta === "string") {
    const last = agent.messages[agent.messages.length - 1];
    if (last?.role === "agent") last.text += event.payload.delta;
    else agent.addMessage({ role: "agent", text: event.payload.delta, createdAt: event.timestamp });
  }
  void nextTick(() => conversationRef.value?.scrollTo({ top: conversationRef.value.scrollHeight, behavior: "smooth" }));
}

function startStream(sessionId: string, afterSequence: number, generation: number) {
  stopStream();
  const controller = new AbortController();
  streamController = controller;
  void streamWorkflowEvents(sessionId, auth.token, (event) => handleEvent(event, generation), String(afterSequence), controller.signal)
    .catch((exc) => {
      if (controller.signal.aborted || generation !== conversationGeneration) return;
      error.value = exc instanceof Error ? exc.message : "事件流失败";
    });
}

async function openSession(sessionId: string, updateRoute = true) {
  const generation = ++conversationGeneration;
  stopStream(); loading.value = true; error.value = "";
  try {
    const replay = await getAgentSession(sessionId, auth.token);
    if (generation !== conversationGeneration) return;
    agent.replaceSession({ ...replay.conversation, session_id: sessionId });
    agent.hydrateSession(sessionId, replayMessages(replay.messages, replay.events), replay.events);
    if (updateRoute) await router.replace({ path: "/agent", query: { session: sessionId } });
    const lastSequence = replay.events.reduce((maximum, event) => Math.max(maximum, event.sequence), 0);
    startStream(sessionId, lastSequence, generation);
    await nextTick();
    conversationRef.value?.scrollTo({ top: conversationRef.value.scrollHeight });
  } catch (exc) {
    if (generation === conversationGeneration) error.value = exc instanceof Error ? exc.message : "会话加载失败";
  } finally { if (generation === conversationGeneration) loading.value = false; }
}

async function createNewSession() {
  const session = await createAgentSession(auth.token);
  agent.addSession(session);
  await openSession(session.session_id, false);
}

async function refreshCatalog() {
  const response = await listAgentSessions(auth.token, { limit: 100 });
  agent.replaceSessions(response.sessions);
}

async function loadHistory() {
  const response = await listAgentSessions(auth.token, { status: historyStatus.value, search: historySearch.value, limit: 50 });
  historyItems.value = response.sessions; historyTotal.value = response.total;
}

async function showHistory() {
  historyOpen.value = true;
  try { await loadHistory(); }
  catch (exc) { error.value = exc instanceof Error ? exc.message : "历史会话加载失败"; }
}

async function historyAction(session: AgentSession, action: "pin" | "rename" | "archive" | "restore") {
  let payload: { title?: string; pinned?: boolean; status?: "active" | "archived" };
  if (action === "rename") {
    const result = await ElMessageBox.prompt("输入新的会话标题", "重命名会话", { inputValue: session.title ?? "" });
    payload = { title: result.value.trim() };
  } else if (action === "pin") payload = { pinned: !session.pinned };
  else payload = { status: action === "archive" ? "archived" : "active" };
  await updateAgentSession(session.session_id, payload, auth.token);
  await Promise.all([refreshCatalog(), loadHistory()]);
  ElMessage.success(action === "restore" ? "会话已恢复" : action === "archive" ? "会话已归档" : "会话已更新");
}

async function refreshApprovals() { approvals.value = (await listApprovals()).approvals; }

async function decide(approval: Record<string, unknown>, decision: "approved" | "rejected") {
  const approvalId = String(approval.approval_id ?? "");
  if (!approvalId) return;
  approvalBusy.value = approvalId;
  try {
    const freshBody = await getApproval(approvalId);
    const fresh = (freshBody.approval ?? freshBody) as Record<string, unknown>;
    approvalStates.value[approvalId] = fresh.status === "pending"
      ? (await decideApproval(approvalId, decision, `BYQ Product decision by ${auth.user?.subject ?? "user"}`)).approval : fresh;
    await refreshApprovals();
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "审批决策失败"; }
  finally { approvalBusy.value = ""; }
}

function navigateCard(event: WorkflowCardEvent) {
  if (event.kind === "agent.card.stock_candidates") void router.push({ path: "/stock-pool", query: event.payload.pool_id ? { pool: event.payload.pool_id } : {} });
  else if (event.kind === "agent.card.backtest_context") void router.push({ path: "/backtest", query: { job: event.payload.job_id } });
  else if (event.kind === "agent.card.approval") void router.push("/research-center");
  else void router.push({ path: "/strategy", query: "artifact_id" in event.payload && event.payload.artifact_id ? { artifact: String(event.payload.artifact_id) } : {} });
}

async function send(value = prompt.value) {
  const content = value.trim();
  if (!content || busy.value) return;
  error.value = ""; busy.value = true;
  try {
    if (!agent.activeSessionId) await createNewSession();
    agent.addMessage({ role: "user", text: content, createdAt: new Date().toISOString() });
    await submitTurn(agent.activeSessionId, content, auth.token);
    prompt.value = ""; await refreshCatalog();
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "发送失败"; }
  finally { busy.value = false; }
}

onMounted(async () => {
  void refreshApprovals().catch(() => undefined);
  try {
    await refreshCatalog();
    const requested = typeof route.query.session === "string" ? route.query.session : "";
    if (typeof route.query.new === "string") await createNewSession();
    else if (requested && agent.sessions.some((item) => item.session_id === requested)) await openSession(requested, false);
    else if (agent.sessions[0]) await openSession(agent.sessions[0].session_id, false);
    else await createNewSession();
    if (route.query.history) await showHistory();
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "初始化失败"; }
  finally { initialized.value = true; }
});
watch(() => route.query.new, async (value, previous) => { if (initialized.value && typeof value === "string" && value !== previous) await createNewSession(); });
watch(() => route.query.session, async (value, previous) => { if (initialized.value && typeof value === "string" && value !== previous && value !== agent.activeSessionId) await openSession(value, false); });
watch(() => route.query.history, async (value) => { if (initialized.value && value) await showHistory(); });
watch(historyOpen, (open) => {
  if (open || !route.query.history) return;
  const { history: _history, ...query } = route.query;
  void router.replace({ path: "/agent", query });
});
watch([historyStatus, historySearch], () => { if (historyOpen.value) void loadHistory(); });
onBeforeUnmount(stopStream);
</script>

<template>
  <section class="conversation-workspace">
    <header class="conversation-header">
      <div><strong>{{ activeSession?.title || "小巴投研对话" }}</strong><small>BYQ 规范化工作流 · 持久会话</small></div>
      <div class="header-actions">
        <el-button text @click="showHistory">历史</el-button>
        <el-button text @click="activityOpen = true">活动与审批 <el-badge v-if="activities.length" :value="activities.length" /></el-button>
        <el-dropdown><el-button text>会话操作</el-button><template #dropdown><el-dropdown-menu>
          <el-dropdown-item @click="resumeSession(agent.activeSessionId, auth.token)">恢复运行</el-dropdown-item>
          <el-dropdown-item @click="cancelSession(agent.activeSessionId, 'soft', auth.token)">取消运行</el-dropdown-item>
        </el-dropdown-menu></template></el-dropdown>
      </div>
    </header>
    <p v-if="error" class="page-error">{{ error }}</p>
    <main ref="conversationRef" class="conversation-canvas" aria-live="polite">
      <div v-if="loading" class="conversation-state"><el-skeleton :rows="4" animated /></div>
      <div v-else-if="!timeline.length" class="conversation-empty">
        <div class="xiaoba-mark">小巴</div><h1>今天想研究什么？</h1>
        <p>从问题出发，小巴会把结论、策略草案、候选股票与回测上下文放在同一条对话时间线中。</p>
        <div class="starter-grid"><button v-for="starter in starters" :key="starter" type="button" @click="send(starter)">{{ starter }}</button></div>
      </div>
      <div v-else class="timeline">
        <template v-for="item in timeline" :key="item.key">
          <article v-if="item.type === 'message'" :class="['conversation-message', item.message.role]">
            <span class="message-author">{{ item.message.role === "user" ? "我" : "小巴" }}</span><div class="message-body">{{ item.message.text }}</div>
          </article>
          <WorkflowCard v-else :event="item.card" @navigate="navigateCard" @decide="(event, decision) => decide(event.payload, decision)" />
        </template>
      </div>
    </main>
    <footer class="composer-wrap"><form class="agent-composer" @submit.prevent="send()">
      <el-input v-model="prompt" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" placeholder="向小巴描述你的投研问题…" />
      <div class="composer-footer"><span>关键执行仍需 BYQ 审批</span><el-button type="primary" :loading="busy" @click="send()">发送</el-button></div>
    </form></footer>
    <el-drawer v-model="activityOpen" title="活动、上下文与审批" size="min(440px, 92vw)">
      <AgentActivityPanel :activities="activities" /><el-divider />
      <ApprovalManagementPanel :approvals="approvals" :busy-id="approvalBusy" @decide="decide" />
    </el-drawer>
    <el-drawer v-model="historyOpen" title="历史会话" size="min(520px, 94vw)">
      <div class="history-tools"><el-input v-model="historySearch" clearable placeholder="搜索标题或最近消息" />
        <el-segmented v-model="historyStatus" :options="[{ label: '进行中', value: 'active' }, { label: '已归档', value: 'archived' }]" /></div>
      <p class="history-count">共 {{ historyTotal }} 个会话</p>
      <div class="history-catalog">
        <article v-for="session in historyItems" :key="session.session_id" class="history-item">
          <button type="button" @click="historyOpen = false; openSession(session.session_id)"><strong>{{ session.title || "新投研对话" }}</strong>
            <span>{{ session.last_message_preview || "尚未发送消息" }}</span><small>{{ session.message_count || 0 }} 轮提问 · {{ session.updated_at?.slice(0, 16).replace('T', ' ') }}</small></button>
          <el-dropdown trigger="click"><el-button text>···</el-button><template #dropdown><el-dropdown-menu>
            <el-dropdown-item @click="historyAction(session, 'pin')">{{ session.pinned ? "取消置顶" : "置顶" }}</el-dropdown-item>
            <el-dropdown-item @click="historyAction(session, 'rename')">重命名</el-dropdown-item>
            <el-dropdown-item v-if="historyStatus === 'active'" divided @click="historyAction(session, 'archive')">归档</el-dropdown-item>
            <el-dropdown-item v-else @click="historyAction(session, 'restore')">恢复</el-dropdown-item>
          </el-dropdown-menu></template></el-dropdown>
        </article><el-empty v-if="!historyItems.length" description="没有匹配的会话" />
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.conversation-workspace { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; height: calc(100vh - 56px); margin: -.95rem -1rem -1rem; min-height: 620px; }
.conversation-header { align-items: center; backdrop-filter: blur(10px); background: color-mix(in srgb, var(--byq-surface) 92%, transparent); border-bottom: 1px solid var(--byq-border-subtle); display: flex; justify-content: space-between; padding: .7rem 1.2rem; z-index: 2; }
.conversation-header > div:first-child { display: grid; gap: .15rem; } .conversation-header strong { color: var(--byq-text); font-size: 14px; } .conversation-header small { color: var(--byq-text-soft); font-size: 10px; }
.header-actions { align-items: center; display: flex; gap: .15rem; }
.conversation-canvas { min-height: 0; overflow-y: auto; padding: 2.2rem max(1rem, calc((100% - 860px) / 2)); }
.conversation-empty { margin: clamp(2rem, 9vh, 7rem) auto 0; max-width: 720px; text-align: center; }
.xiaoba-mark { align-items: center; background: var(--byq-brand-contrast); border-radius: 18px; color: #fff; display: inline-flex; font-size: 13px; font-weight: 900; height: 56px; justify-content: center; width: 56px; }
.conversation-empty h1 { color: var(--byq-text); font-size: clamp(24px, 3vw, 34px); margin: 1rem 0 .55rem; }.conversation-empty p { color: var(--byq-text-muted); line-height: 1.7; margin: 0 auto 1.4rem; max-width: 620px; }
.starter-grid { display: grid; gap: .65rem; grid-template-columns: repeat(3, 1fr); }.starter-grid button { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: var(--byq-radius); color: var(--byq-text-muted); cursor: pointer; line-height: 1.5; padding: .85rem; text-align: left; }.starter-grid button:hover { border-color: var(--byq-brand); color: var(--byq-text); }
.timeline { display: grid; gap: 1.15rem; margin: 0 auto; max-width: 860px; }.conversation-message { display: grid; gap: .7rem; grid-template-columns: 42px minmax(0, 1fr); }.message-author { align-items: center; background: var(--byq-surface-muted); border-radius: 12px; color: var(--byq-text-muted); display: flex; font-size: 11px; font-weight: 850; height: 36px; justify-content: center; width: 36px; }.conversation-message.agent .message-author { background: var(--byq-brand-contrast); color: #fff; }.message-body { color: var(--byq-text); line-height: 1.75; padding: .35rem 0; white-space: pre-wrap; }.conversation-message.user .message-body { background: var(--byq-brand-soft); border-radius: 16px; justify-self: start; padding: .7rem .9rem; }
.composer-wrap { background: linear-gradient(transparent, var(--byq-bg) 22%); padding: 1rem max(1rem, calc((100% - 860px) / 2)) 1.2rem; }.agent-composer { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 18px; box-shadow: var(--byq-shadow-sm); padding: .7rem; }.agent-composer :deep(.el-textarea__inner) { box-shadow: none; padding: .3rem; resize: none; }.composer-footer { align-items: center; color: var(--byq-text-soft); display: flex; font-size: 10px; justify-content: space-between; padding: .35rem 0 0 .25rem; }
.history-tools { display: grid; gap: .75rem; }.history-count { color: var(--byq-text-soft); font-size: 11px; }.history-catalog { display: grid; gap: .55rem; }.history-item { align-items: center; border: 1px solid var(--byq-border-subtle); border-radius: var(--byq-radius-sm); display: flex; padding: .35rem .5rem .35rem .75rem; }.history-item > button { background: transparent; border: 0; cursor: pointer; display: grid; flex: 1; gap: .25rem; min-width: 0; padding: .35rem; text-align: left; }.history-item strong, .history-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.history-item span, .history-item small { color: var(--byq-text-soft); }.conversation-state { margin: 2rem auto; max-width: 860px; }
@media (max-width: 760px) { .conversation-workspace { height: calc(100dvh - 52px); margin: -.7rem; }.conversation-header { align-items: flex-start; padding: .6rem .7rem; }.conversation-header small { display: none; }.header-actions .el-button:first-child { display: none; }.conversation-canvas { padding: 1.2rem .7rem; }.starter-grid { grid-template-columns: 1fr; }.conversation-message { gap: .4rem; grid-template-columns: 32px minmax(0, 1fr); }.message-author { border-radius: 9px; height: 28px; width: 28px; }.composer-wrap { padding: .75rem .7rem; } }
</style>
