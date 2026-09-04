<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  AgentRequestError, cancelSession, createAgentSession, deleteAgentSession, getAgentSession, listAgentSessions, resumeSession,
  streamWorkflowEvents, submitTurn, updateAgentSession,
} from "@/api/agent";
import { continueApproval } from "@/api/research";
import { foldWorkflowCards, workflowActivities, workflowRunState } from "@/api/workflow";
import type { AgentReplayMessage, AgentSession, WorkflowCardEvent, WorkflowTraceEvent } from "@/api/types";
import AgentActivityPanel from "@/components/agent/AgentActivityPanel.vue";
import RichMessage from "@/components/agent/RichMessage.vue";
import WorkflowCard from "@/components/agent/WorkflowCard.vue";
import { useAgentStore, type AgentMessage } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";
import { workflowCardDestination } from "@/router/workflowCardNavigation";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const agent = useAgentStore();
const prompt = ref("");
const error = ref("");
const busy = ref(false);
const loading = ref(false);
const initialized = ref(false);
const activityOpen = ref(false);
const historyOpen = ref(false);
const historyStatus = ref<"active" | "archived">("active");
const historySearch = ref("");
const historyItems = ref<AgentSession[]>([]);
const historyTotal = ref(0);
const selectedHistoryIds = ref<Set<string>>(new Set());
const historyBatchBusy = ref(false);
const stopping = ref(false);
const localRunStartedAt = ref("");
const clock = ref(Date.now());
const conversationRef = ref<HTMLElement | null>(null);
const starters = ["筛选一组可研究的股票候选", "起草一个可验证的量化策略", "根据最近回测提出优化建议"];
let conversationGeneration = 0;
let streamController: AbortController | null = null;
let clockTimer: ReturnType<typeof setInterval> | null = null;
let approvalContinuationTimer: ReturnType<typeof setTimeout> | null = null;
let continuationWarningShown = false;
let reconciliationTimer: ReturnType<typeof setTimeout> | null = null;
let lastStreamEventAt = 0;

const activeSession = computed(() => agent.sessions.find((item) => item.session_id === agent.activeSessionId));
const userDisplayName = computed(() => auth.user?.display_name?.trim() || "我");
const activities = computed(() => workflowActivities(agent.events));
const activeActivityCount = computed(() => activities.value.filter((item) =>
  ["started", "progress", "waiting_approval"].includes(item.payload.state),
).length);
const replayRun = computed(() => workflowRunState(agent.events));
const runFailureMessage = computed(() => {
  if (!replayRun.value.failed) return "";
  const messages: Record<string, string> = {
    "runtime-no-progress-timeout": "本轮在较长时间内没有形成可展示的结论，系统为避免持续占用已停止。已完成的读取步骤仍保留，可以直接重试。",
    "runtime-run-timeout": "本轮总处理时间超过运行上限，系统已停止任务。对话内容已保留，可以直接重试或缩小分析范围。",
    "runtime-subagent-timeout": "本轮专项分析超过等待上限，系统已停止任务。对话内容已保留，可以直接重试。",
    "model-run-failed": "模型服务本轮未能完成回答。对话内容已保留，可以直接重试；若持续失败，请联系管理员。",
  };
  return messages[replayRun.value.failureCode ?? ""]
    ?? "本轮运行未能完成。对话内容已保留，可以直接重试；若持续失败，请联系管理员。";
});
const activeActivity = computed(() => [...activities.value].reverse().find((item) =>
  item.payload.state === "started" || item.payload.state === "progress" || item.payload.state === "waiting_approval",
));
const runActive = computed(() => replayRun.value.running || Boolean(localRunStartedAt.value));
const processingVisible = computed(() => runActive.value && !replayRun.value.answerStarted);
const runStartedAt = computed(() => replayRun.value.startedAt || localRunStartedAt.value);
const elapsedSeconds = computed(() => {
  const started = Date.parse(runStartedAt.value || "");
  return Number.isFinite(started) ? Math.max(0, Math.floor((clock.value - started) / 1000)) : 0;
});
const allHistorySelected = computed(() => historyItems.value.length > 0
  && historyItems.value.every((item) => selectedHistoryIds.value.has(item.session_id)));
const elapsedLabel = computed(() => {
  const minutes = Math.floor(elapsedSeconds.value / 60);
  const seconds = elapsedSeconds.value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
});
const cards = computed(() => foldWorkflowCards(agent.events));
const timeline = computed(() => [
  ...agent.messages.map((message, index) => ({ type: "message" as const, at: message.createdAt ?? "", key: `message-${index}`, message })),
  ...cards.value.map((card) => ({ type: "card" as const, at: card.timestamp, key: `card-${card.payload.card_id}`, card })),
].sort((left, right) => left.at.localeCompare(right.at)));

function replayMessages(messages: AgentReplayMessage[], events: WorkflowTraceEvent[]): AgentMessage[] {
  const persistedAnswerSequences = new Set(messages
    .filter((message) => message.role === "assistant" && typeof message.workflow_sequence === "number")
    .map((message) => message.workflow_sequence));
  const ordered = [
    ...messages.map((message) => ({
      kind: message.role === "assistant" ? "agent" as const : "user" as const,
      at: message.created_at,
      text: message.content,
    })),
    ...events.filter((event) => event.kind === "agent.output.delta"
      && typeof event.payload.delta === "string" && !persistedAnswerSequences.has(event.sequence))
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
function stopReconciliation() {
  if (reconciliationTimer) clearTimeout(reconciliationTimer);
  reconciliationTimer = null;
}

function scrollConversation(behavior?: ScrollBehavior) {
  const canvas = conversationRef.value;
  if (!canvas || typeof canvas.scrollTo !== "function") return;
  canvas.scrollTo({ top: canvas.scrollHeight, behavior });
}

function handleEvent(event: WorkflowTraceEvent, generation: number) {
  if (generation !== conversationGeneration || event.session_id !== agent.activeSessionId) return;
  if (agent.events.some((current) => current.sequence === event.sequence)) return;
  agent.addEvent(event);
  if (event.kind === "agent.card.approval") {
    window.dispatchEvent(new Event("byq:approvals-changed"));
  }
  if (["session.result", "session.failed", "session.cancelled", "session.result.discarded"].includes(event.kind)) {
    localRunStartedAt.value = "";
    stopping.value = false;
    stopReconciliation();
  }
  if (event.kind === "agent.output.delta" && typeof event.payload.delta === "string") {
    const last = agent.messages[agent.messages.length - 1];
    if (last?.role === "agent") last.text += event.payload.delta;
    else agent.addMessage({ role: "agent", text: event.payload.delta, createdAt: event.timestamp });
  }
  void nextTick(() => scrollConversation("smooth"));
}

function reconnectDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

async function replayMissedEvents(sessionId: string, generation: number): Promise<number> {
  const replay = await getAgentSession(sessionId, auth.token);
  if (generation !== conversationGeneration || sessionId !== agent.activeSessionId) return 0;
  let maximum = 0;
  for (const event of [...replay.events].sort((left, right) => left.sequence - right.sequence)) {
    maximum = Math.max(maximum, event.sequence);
    handleEvent(event, generation);
  }
  return maximum;
}

async function maintainStream(
  sessionId: string,
  afterSequence: number,
  generation: number,
  controller: AbortController,
) {
  let cursor = afterSequence;
  let delay = 500;
  while (!controller.signal.aborted && generation === conversationGeneration) {
    try {
      await streamWorkflowEvents(sessionId, auth.token, (event) => {
        cursor = Math.max(cursor, event.sequence);
        delay = 500;
        lastStreamEventAt = Date.now();
        handleEvent(event, generation);
      }, String(cursor), controller.signal);
    } catch (exc) {
      if (controller.signal.aborted || generation !== conversationGeneration) return;
      if (exc instanceof AgentRequestError && [401, 403, 404, 410].includes(exc.status)) return;
    }
    try {
      cursor = Math.max(cursor, await replayMissedEvents(sessionId, generation));
    } catch {
      delay = Math.min(delay * 2, 5_000);
    }
    await reconnectDelay(delay, controller.signal);
  }
}

function startStream(sessionId: string, afterSequence: number, generation: number) {
  stopStream();
  const controller = new AbortController();
  streamController = controller;
  lastStreamEventAt = Date.now();
  void maintainStream(sessionId, afterSequence, generation, controller);
}

function scheduleRunReconciliation(sessionId: string, generation: number) {
  stopReconciliation();
  if (!localRunStartedAt.value) return;
  reconciliationTimer = setTimeout(async () => {
    reconciliationTimer = null;
    if (generation !== conversationGeneration || sessionId !== agent.activeSessionId || !localRunStartedAt.value) return;
    if (Date.now() - lastStreamEventAt >= 10_000) {
      try { await replayMissedEvents(sessionId, generation); }
      catch { /* the live stream remains primary; the next bounded poll retries */ }
    }
    if (localRunStartedAt.value) scheduleRunReconciliation(sessionId, generation);
  }, 5_000);
}

async function openSession(sessionId: string, updateRoute = true) {
  const generation = ++conversationGeneration;
  stopStream(); stopReconciliation(); localRunStartedAt.value = ""; stopping.value = false;
  loading.value = true; error.value = "";
  try {
    const replay = await getAgentSession(sessionId, auth.token);
    if (generation !== conversationGeneration) return;
    agent.replaceSession({ ...replay.conversation, session_id: sessionId });
    agent.hydrateSession(sessionId, replayMessages(replay.messages, replay.events), replay.events);
    if (updateRoute) await router.replace({ path: "/agent", query: { session: sessionId } });
    const lastSequence = replay.events.reduce((maximum, event) => Math.max(maximum, event.sequence), 0);
    startStream(sessionId, lastSequence, generation);
    await nextTick();
    scrollConversation();
  } catch (exc) {
    if (generation === conversationGeneration) error.value = exc instanceof Error ? exc.message : "会话加载失败";
  } finally { if (generation === conversationGeneration) loading.value = false; }
}

async function persistNewSession() {
  const session = await createAgentSession(auth.token);
  agent.addSession(session);
  await openSession(session.session_id, false);
}

function startNewSession(preservePrompt = false) {
  conversationGeneration += 1;
  stopStream(); stopReconciliation();
  localRunStartedAt.value = ""; stopping.value = false; loading.value = false; error.value = "";
  agent.clearActiveSession();
  if (!preservePrompt) prompt.value = "";
}

async function refreshCatalog() {
  const response = await listAgentSessions(auth.token, { limit: 100 });
  agent.replaceSessions(response.sessions);
}

async function loadHistory() {
  const response = await listAgentSessions(auth.token, { status: historyStatus.value, search: historySearch.value, limit: 50 });
  historyItems.value = response.sessions; historyTotal.value = response.total;
  selectedHistoryIds.value = new Set(
    [...selectedHistoryIds.value].filter((sessionId) => response.sessions.some((item) => item.session_id === sessionId)),
  );
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

async function deleteHistorySession(session: AgentSession) {
  await ElMessageBox.confirm(
    `永久删除会话“${session.title || "新投研对话"}”？删除后无法恢复。`,
    "删除会话",
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
  );
  const wasActive = agent.activeSessionId === session.session_id;
  await deleteAgentSession(session.session_id, auth.token);
  agent.removeSession(session.session_id);
  if (wasActive) {
    startNewSession();
    await router.replace({ path: "/agent" });
  }
  await Promise.all([refreshCatalog(), loadHistory()]);
  ElMessage.success("会话已删除");
}

function toggleHistorySelection(sessionId: string, selected: boolean) {
  const next = new Set(selectedHistoryIds.value);
  if (selected) next.add(sessionId);
  else next.delete(sessionId);
  selectedHistoryIds.value = next;
}

function toggleAllHistory(selected: boolean) {
  selectedHistoryIds.value = selected ? new Set(historyItems.value.map((item) => item.session_id)) : new Set();
}

async function batchArchiveHistory() {
  const sessions = historyItems.value.filter((item) => selectedHistoryIds.value.has(item.session_id));
  if (!sessions.length) return;
  const target = historyStatus.value === "active" ? "archived" : "active";
  await ElMessageBox.confirm(
    `${target === "archived" ? "归档" : "恢复"}选中的 ${sessions.length} 个会话？`,
    target === "archived" ? "批量归档" : "批量恢复",
  );
  historyBatchBusy.value = true;
  try {
    const results = await Promise.allSettled(
      sessions.map((session) => updateAgentSession(session.session_id, { status: target }, auth.token)),
    );
    const failedIds = sessions.filter((_, index) => results[index].status === "rejected").map((item) => item.session_id);
    selectedHistoryIds.value = new Set(failedIds);
    await Promise.all([refreshCatalog(), loadHistory()]);
    if (failedIds.length) ElMessage.warning(`${sessions.length - failedIds.length} 个会话已更新，${failedIds.length} 个失败，请重试`);
    else ElMessage.success(target === "archived" ? "所选会话已归档" : "所选会话已恢复");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量更新会话失败";
  } finally { historyBatchBusy.value = false; }
}

async function batchDeleteHistory() {
  const sessions = historyItems.value.filter((item) => selectedHistoryIds.value.has(item.session_id));
  if (!sessions.length) return;
  await ElMessageBox.confirm(
    `永久删除选中的 ${sessions.length} 个会话？删除后无法恢复。`,
    "批量删除会话",
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" },
  );
  historyBatchBusy.value = true;
  try {
    const results = await Promise.allSettled(
      sessions.map((session) => deleteAgentSession(session.session_id, auth.token)),
    );
    const deletedIds = new Set(sessions.filter((_, index) => results[index].status === "fulfilled").map((item) => item.session_id));
    const failedIds = sessions.filter((_, index) => results[index].status === "rejected").map((item) => item.session_id);
    const activeDeleted = deletedIds.has(agent.activeSessionId);
    for (const sessionId of deletedIds) agent.removeSession(sessionId);
    if (activeDeleted) {
      startNewSession();
      await router.replace({ path: "/agent" });
    }
    selectedHistoryIds.value = new Set(failedIds);
    await Promise.all([refreshCatalog(), loadHistory()]);
    if (failedIds.length) ElMessage.warning(`${deletedIds.size} 个会话已删除，${failedIds.length} 个失败，请重试`);
    else ElMessage.success("所选会话已删除");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "批量删除会话失败";
  } finally { historyBatchBusy.value = false; }
}

function navigateCard(event: WorkflowCardEvent) {
  void router.push(workflowCardDestination(event, agent.activeSessionId));
}

async function send(value = prompt.value) {
  const content = value.trim();
  if (!content || busy.value || runActive.value) return;
  error.value = ""; busy.value = true;
  try {
    if (!agent.activeSessionId) await persistNewSession();
    if (replayRun.value.failed) await resumeSession(agent.activeSessionId, auth.token);
    agent.addMessage({ role: "user", text: content, createdAt: new Date().toISOString() });
    localRunStartedAt.value = new Date().toISOString();
    await submitTurn(agent.activeSessionId, content, auth.token);
    scheduleRunReconciliation(agent.activeSessionId, conversationGeneration);
    prompt.value = ""; await refreshCatalog();
  } catch (exc) { localRunStartedAt.value = ""; error.value = exc instanceof Error ? exc.message : "发送失败"; }
  finally { busy.value = false; }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== "Enter" || !event.ctrlKey) return;
  event.preventDefault();
  if (!runActive.value) void send();
}

function applyRouteDraft(value: unknown) {
  if (typeof value !== "string" || !value.trim()) return;
  prompt.value = value.trim().slice(0, 2000);
}

async function retryApprovalContinuation(value: unknown) {
  if (typeof value !== "string" || !value) return;
  if (approvalContinuationTimer) {
    clearTimeout(approvalContinuationTimer);
    approvalContinuationTimer = null;
  }
  try {
    const result = await continueApproval(value);
    if (result.approval.continuation_status === "submitted" && agent.activeSessionId) {
      localRunStartedAt.value = new Date().toISOString();
      scheduleRunReconciliation(agent.activeSessionId, conversationGeneration);
      continuationWarningShown = false;
      const { approval: _approval, ...query } = route.query;
      await router.replace({ path: "/agent", query });
      return;
    }
    const delay = result.approval.continuation_status === "submitting" ? 31_000 : 5_000;
    approvalContinuationTimer = setTimeout(() => void retryApprovalContinuation(value), delay);
  } catch {
    if (!continuationWarningShown) {
      continuationWarningShown = true;
      ElMessage.warning("审批已记录，正在等待原会话可继续执行");
    }
    approvalContinuationTimer = setTimeout(() => void retryApprovalContinuation(value), 5_000);
  }
}

async function stopCurrentRun() {
  if (!agent.activeSessionId || stopping.value || !runActive.value) return;
  stopping.value = true;
  try {
    await cancelSession(agent.activeSessionId, "hard", auth.token);
    await resumeSession(agent.activeSessionId, auth.token);
    localRunStartedAt.value = "";
    stopReconciliation();
    ElMessage.success("本轮已停止，可以继续提问");
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "停止失败";
  } finally {
    stopping.value = false;
  }
}

onMounted(async () => {
  clockTimer = setInterval(() => { clock.value = Date.now(); }, 1000);
  applyRouteDraft(route.query.draft);
  try {
    await refreshCatalog();
    const requested = typeof route.query.session === "string" ? route.query.session : "";
    if (typeof route.query.new === "string") startNewSession(typeof route.query.draft === "string");
    else if (requested && agent.sessions.some((item) => item.session_id === requested)) await openSession(requested, false);
    else if (agent.sessions[0]) await openSession(agent.sessions[0].session_id, false);
    else startNewSession(typeof route.query.draft === "string");
    await retryApprovalContinuation(route.query.approval);
    if (route.query.history) await showHistory();
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "初始化失败"; }
  finally { initialized.value = true; }
});
watch(() => route.query.new, (value, previous) => { if (initialized.value && typeof value === "string" && value !== previous) startNewSession(typeof route.query.draft === "string"); });
watch(() => route.query.session, async (value, previous) => { if (initialized.value && typeof value === "string" && value !== previous) await openSession(value, false); });
watch(() => route.query.history, async (value) => { if (initialized.value && value) await showHistory(); });
watch(() => route.query.draft, applyRouteDraft);
watch(() => route.query.approval, retryApprovalContinuation);
watch(historyOpen, (open) => {
  if (open || !route.query.history) return;
  const { history: _history, ...query } = route.query;
  void router.replace({ path: "/agent", query });
});
watch([historyStatus, historySearch], () => { if (historyOpen.value) void loadHistory(); });
onBeforeUnmount(() => {
  stopStream();
  stopReconciliation();
  if (clockTimer) clearInterval(clockTimer);
  if (approvalContinuationTimer) clearTimeout(approvalContinuationTimer);
});
</script>

<template>
  <section class="conversation-workspace">
    <header class="conversation-header">
      <div><strong>{{ activeSession?.title || "小巴投研对话" }}</strong><small>{{ activeSession ? "BYQ 规范化工作流 · 持久会话" : "发送第一条消息后保存" }}</small></div>
      <div class="header-actions">
        <el-button text @click="activityOpen = true">活动 <el-badge v-if="activeActivityCount" :value="activeActivityCount" type="info" /></el-button>
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
            <span class="message-author" :title="item.message.role === 'user' ? userDisplayName : '小巴'">{{ item.message.role === "user" ? userDisplayName : "小巴" }}</span>
            <div class="message-body">
              <RichMessage v-if="item.message.role === 'agent'" :content="item.message.text" />
              <template v-else>{{ item.message.text }}</template>
            </div>
          </article>
          <WorkflowCard v-else :event="item.card" @navigate="navigateCard" />
        </template>
        <article v-if="processingVisible" class="conversation-message agent assistant-processing" role="status" aria-live="polite">
          <span class="message-author">小巴</span>
          <div class="thinking-status">
            <button type="button" class="thinking-summary" @click="activityOpen = true">
              <span class="thinking-spark" aria-hidden="true"><i></i><i></i><i></i></span>
              <strong>{{ stopping ? "正在停止" : (activeActivity?.payload.label || "正在思考") }}</strong>
              <span>已用时 {{ elapsedLabel }}</span>
            </button>
            <small>查看小巴正在进行的公开步骤</small>
          </div>
        </article>
        <article v-else-if="runFailureMessage" class="conversation-message agent run-failure" role="alert">
          <span class="message-author">小巴</span>
          <div class="message-body">{{ runFailureMessage }}</div>
        </article>
      </div>
    </main>
    <footer class="composer-wrap">
      <form class="agent-composer" @submit.prevent="send()">
        <el-input v-model="prompt" class="composer-input" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }" placeholder="向小巴描述你的投研问题…" @keydown="handleComposerKeydown" />
        <el-button
          v-if="runActive"
          class="composer-action composer-stop"
          circle
          :loading="stopping"
          aria-label="停止本轮"
          title="停止本轮"
          @click="stopCurrentRun"
        ><span class="stop-square" aria-hidden="true"></span></el-button>
        <el-button v-else class="composer-action" type="primary" :loading="busy" :disabled="!prompt.trim()" @click="send()">发送</el-button>
      </form>
    </footer>
    <el-drawer v-model="activityOpen" title="活动与执行上下文" size="min(440px, 92vw)">
      <AgentActivityPanel :activities="activities" />
    </el-drawer>
    <el-drawer v-model="historyOpen" title="历史会话" size="min(520px, 94vw)">
      <div class="history-tools"><el-input v-model="historySearch" clearable placeholder="搜索标题或最近消息" />
        <el-segmented v-model="historyStatus" :options="[{ label: '进行中', value: 'active' }, { label: '已归档', value: 'archived' }]" /></div>
      <div class="history-batch-bar">
        <el-checkbox :model-value="allHistorySelected" :indeterminate="selectedHistoryIds.size > 0 && !allHistorySelected" @change="toggleAllHistory(Boolean($event))">全选当前列表</el-checkbox>
        <span class="history-count">共 {{ historyTotal }} 个会话 · 已选 {{ selectedHistoryIds.size }} 个</span>
        <el-button size="small" :disabled="!selectedHistoryIds.size" :loading="historyBatchBusy" @click="batchArchiveHistory">{{ historyStatus === "active" ? "批量归档" : "批量恢复" }}</el-button>
        <el-button size="small" type="danger" plain :disabled="!selectedHistoryIds.size" :loading="historyBatchBusy" @click="batchDeleteHistory">批量删除</el-button>
      </div>
      <div class="history-catalog">
        <article v-for="session in historyItems" :key="session.session_id" class="history-item">
          <el-checkbox :model-value="selectedHistoryIds.has(session.session_id)" :aria-label="`选择会话 ${session.title || '新投研对话'}`" @change="toggleHistorySelection(session.session_id, Boolean($event))" />
          <button type="button" @click="historyOpen = false; openSession(session.session_id)"><strong>{{ session.title || "新投研对话" }}</strong>
            <span>{{ session.last_message_preview || "尚未发送消息" }}</span><small>{{ session.message_count || 0 }} 轮提问 · {{ session.updated_at?.slice(0, 16).replace('T', ' ') }}</small></button>
          <el-dropdown trigger="click"><el-button text>···</el-button><template #dropdown><el-dropdown-menu>
            <el-dropdown-item @click="historyAction(session, 'pin')">{{ session.pinned ? "取消置顶" : "置顶" }}</el-dropdown-item>
            <el-dropdown-item @click="historyAction(session, 'rename')">重命名</el-dropdown-item>
            <el-dropdown-item v-if="historyStatus === 'active'" divided @click="historyAction(session, 'archive')">归档</el-dropdown-item>
            <el-dropdown-item v-else @click="historyAction(session, 'restore')">恢复</el-dropdown-item>
            <el-dropdown-item divided @click="deleteHistorySession(session)">删除</el-dropdown-item>
          </el-dropdown-menu></template></el-dropdown>
        </article><el-empty v-if="!historyItems.length" description="没有匹配的会话" />
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.conversation-workspace { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; height: 100%; min-height: 0; }
.conversation-header { align-items: center; backdrop-filter: blur(10px); background: color-mix(in srgb, var(--byq-surface) 92%, transparent); border-bottom: 1px solid var(--byq-border-subtle); display: flex; justify-content: space-between; padding: .7rem 1.2rem; z-index: 2; }
.conversation-header > div:first-child { display: grid; gap: .15rem; } .conversation-header strong { color: var(--byq-text); font-size: 14px; } .conversation-header small { color: var(--byq-text-soft); font-size: 10px; }
.header-actions { align-items: center; display: flex; gap: .15rem; }
.conversation-canvas { min-height: 0; overflow-y: auto; padding: 2.2rem max(1rem, calc((100% - 860px) / 2)); }
.conversation-empty { margin: clamp(2rem, 9vh, 7rem) auto 0; max-width: 720px; text-align: center; }
.xiaoba-mark { align-items: center; background: var(--byq-brand-contrast); border-radius: 18px; color: var(--byq-on-brand); display: inline-flex; font-size: 13px; font-weight: 900; height: 56px; justify-content: center; width: 56px; }
.conversation-empty h1 { color: var(--byq-text); font-size: clamp(24px, 3vw, 34px); margin: 1rem 0 .55rem; }.conversation-empty p { color: var(--byq-text-muted); line-height: 1.7; margin: 0 auto 1.4rem; max-width: 620px; }
.starter-grid { display: grid; gap: .65rem; grid-template-columns: repeat(3, 1fr); }.starter-grid button { background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: var(--byq-radius); color: var(--byq-text-muted); cursor: pointer; line-height: 1.5; padding: .85rem; text-align: left; }.starter-grid button:hover { border-color: var(--byq-brand); color: var(--byq-text); }
.timeline { display: grid; gap: 1.15rem; margin: 0 auto; max-width: 860px; }.conversation-message { display: grid; gap: .7rem; grid-template-columns: minmax(42px, max-content) minmax(0, 1fr); }.message-author { align-items: center; background: var(--byq-surface-muted); border-radius: 12px; color: var(--byq-text-muted); display: flex; font-size: 11px; font-weight: 850; height: 36px; justify-content: center; max-width: 96px; min-width: 36px; overflow: hidden; padding: 0 7px; text-overflow: ellipsis; white-space: nowrap; }.conversation-message.agent .message-author { background: var(--byq-brand-contrast); color: var(--byq-on-brand); width: 36px; }.message-body { color: var(--byq-text); line-height: 1.75; padding: .35rem 0; white-space: pre-wrap; }.conversation-message.user .message-body { background: var(--byq-brand-soft); border-radius: 16px; justify-self: start; padding: .7rem .9rem; }
.thinking-status { align-items: flex-start; display: grid; gap: .15rem; padding: .35rem 0; }.thinking-summary { align-items: center; background: transparent; border: 0; color: var(--byq-text-muted); cursor: pointer; display: flex; font: inherit; gap: .55rem; padding: 0; text-align: left; }.thinking-summary strong { color: var(--byq-text); font-size: 13px; }.thinking-summary > span:last-child, .thinking-status small { color: var(--byq-text-soft); font-size: 11px; }.thinking-spark { align-items: center; display: inline-flex; gap: 3px; height: 16px; }.thinking-spark i { animation: thinking-dot 1.15s ease-in-out infinite; background: var(--byq-brand); border-radius: 50%; display: block; height: 5px; width: 5px; }.thinking-spark i:nth-child(2) { animation-delay: .16s; }.thinking-spark i:nth-child(3) { animation-delay: .32s; }
.composer-wrap { background: linear-gradient(transparent, var(--byq-bg) 22%); padding: 1rem max(1rem, calc((100% - 860px) / 2)) 1.2rem; }.agent-composer { align-items: center; background: var(--byq-surface); border: 1px solid var(--byq-border); border-radius: 18px; box-shadow: var(--byq-shadow-sm); display: flex; gap: .65rem; padding: .65rem .7rem .65rem .9rem; }.composer-input { flex: 1; min-width: 0; }.agent-composer :deep(.el-textarea__inner) { box-shadow: none; line-height: 1.55; padding: .35rem 0; resize: none; }.composer-action { align-self: center; flex: 0 0 auto; margin-left: 0; }
.composer-stop { background: var(--byq-text); border-color: var(--byq-text); color: var(--byq-surface); }.stop-square { background: currentColor; border-radius: 2px; display: block; height: 10px; width: 10px; }
@keyframes thinking-dot { 0%, 60%, 100% { opacity: .28; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-3px); } }
.history-tools { display: grid; gap: .75rem; }.history-batch-bar { align-items: center; display: flex; flex-wrap: wrap; gap: .45rem; margin: .75rem 0; }.history-count { color: var(--byq-text-soft); flex: 1; font-size: 11px; min-width: 130px; }.history-catalog { display: grid; gap: .55rem; }.history-item { align-items: center; border: 1px solid var(--byq-border-subtle); border-radius: var(--byq-radius-sm); display: flex; gap: .25rem; padding: .35rem .5rem .35rem .75rem; }.history-item > button { background: transparent; border: 0; cursor: pointer; display: grid; flex: 1; gap: .25rem; min-width: 0; padding: .35rem; text-align: left; }.history-item strong, .history-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.history-item span, .history-item small { color: var(--byq-text-soft); }.conversation-state { margin: 2rem auto; max-width: 860px; }
@media (max-width: 760px) { .conversation-header { align-items: flex-start; padding: .6rem .7rem; }.conversation-header small { display: none; }.header-actions .el-button:first-child { display: none; }.conversation-canvas { padding: 1.2rem .7rem; }.starter-grid { grid-template-columns: 1fr; }.conversation-message { gap: .4rem; grid-template-columns: minmax(32px, max-content) minmax(0, 1fr); }.message-author { border-radius: 9px; height: 28px; max-width: 72px; min-width: 28px; }.conversation-message.agent .message-author { width: 28px; }.composer-wrap { padding: .75rem .7rem; } }
@media (prefers-reduced-motion: reduce) { .thinking-spark i { animation: none; opacity: 1; } }
</style>
