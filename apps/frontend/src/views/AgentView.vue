<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { cancelSession, createAgentSession, listAgentSessions, resumeSession, streamWorkflowEvents, submitTurn } from "@/api/agent";
import { foldWorkflowCards, workflowActivities } from "@/api/workflow";
import type { WorkflowCardEvent } from "@/api/types";
import { decideApproval, getApproval, listApprovals } from "@/api/research";
import AgentActivityPanel from "@/components/agent/AgentActivityPanel.vue";
import ApprovalManagementPanel from "@/components/agent/ApprovalManagementPanel.vue";
import WorkflowCard from "@/components/agent/WorkflowCard.vue";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const agent = useAgentStore();
const prompt = ref("");
const error = ref("");
const busy = ref(false);
const approvalBusy = ref("");
const approvals = ref<Array<Record<string, unknown>>>([]);
const approvalStates = ref<Record<string, Record<string, unknown>>>({});
const starters = ["筛选一组可研究的股票候选", "起草一个可验证的量化策略", "根据最近回测提出优化建议"];
const activities = computed(() => workflowActivities(agent.events));
const cards = computed(() => foldWorkflowCards(agent.events).map((event) => {
  if (event.kind !== "agent.card.approval") return event;
  const latest = approvalStates.value[event.payload.approval_id];
  return latest ? { ...event, payload: { ...event.payload, ...latest } } as WorkflowCardEvent : event;
}));

function handleEvent(event: Parameters<typeof agent.addEvent>[0]) {
  if (event.session_id !== agent.activeSessionId) return;
  if (agent.events.some((current) => current.sequence === event.sequence)) return;
  agent.addEvent(event);
  if (event.kind === "agent.output.delta" && typeof event.payload.delta === "string") {
    const last = agent.messages[agent.messages.length - 1];
    if (last?.role === "agent") last.text += event.payload.delta;
    else agent.addMessage({ role: "agent", text: event.payload.delta });
  }
}

function startStream(sessionId: string) {
  void streamWorkflowEvents(sessionId, auth.token, handleEvent, "0").catch((exc) => {
    error.value = exc instanceof Error ? exc.message : "事件流失败";
  });
}

async function ensureSession() {
  if (agent.activeSessionId) return;
  await createNewSession();
}

async function createNewSession() {
  const session = await createAgentSession(auth.token);
  agent.addSession(session);
  startStream(session.session_id);
}

function selectSession(sessionId: string) {
  agent.setActiveSession(sessionId);
  startStream(sessionId);
}

async function refreshApprovals() {
  const response = await listApprovals();
  approvals.value = response.approvals;
}

async function decide(approval: Record<string, unknown>, decision: "approved" | "rejected") {
  const approvalId = String(approval.approval_id ?? "");
  if (!approvalId) return;
  approvalBusy.value = approvalId;
  error.value = "";
  try {
    const freshBody = await getApproval(approvalId);
    const fresh = (freshBody.approval ?? freshBody) as Record<string, unknown>;
    if (fresh.status === "pending") {
      const response = await decideApproval(approvalId, decision, `BYQ Product decision by ${auth.user?.subject ?? "user"}`);
      approvalStates.value[approvalId] = response.approval;
    } else {
      approvalStates.value[approvalId] = fresh;
    }
    await refreshApprovals();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "审批决策失败";
  } finally { approvalBusy.value = ""; }
}

function navigateCard(event: WorkflowCardEvent) {
  if (event.kind === "agent.card.stock_candidates") void router.push({ path: "/stock-pool", query: event.payload.pool_id ? { pool: event.payload.pool_id } : {} });
  else if (event.kind === "agent.card.backtest_context") void router.push({ path: "/backtest", query: { job: event.payload.job_id } });
  else if (event.kind === "agent.card.approval") void router.push("/research-center");
  else if (event.kind === "agent.card.strategy_draft") void router.push({ path: "/strategy", query: event.payload.artifact_id ? { artifact: event.payload.artifact_id } : {} });
  else void router.push({ path: "/strategy", query: event.payload.strategy_artifact_id ? { artifact: event.payload.strategy_artifact_id } : {} });
}

function decideCard(event: WorkflowCardEvent, decision: "approved" | "rejected") {
  void decide(event.payload, decision);
}

async function send(value = prompt.value) {
  const content = value.trim();
  if (!content) return;
  error.value = ""; busy.value = true;
  try {
    await ensureSession();
    agent.addMessage({ role: "user", text: content });
    await submitTurn(agent.activeSessionId, content, auth.token);
    prompt.value = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发送失败";
  } finally { busy.value = false; }
}

async function resume() { if (agent.activeSessionId) await resumeSession(agent.activeSessionId, auth.token); }
async function cancel() { if (agent.activeSessionId) await cancelSession(agent.activeSessionId, "soft", auth.token); }

onMounted(async () => {
  void refreshApprovals().catch(() => undefined);
  try {
    const response = await listAgentSessions(auth.token);
    agent.replaceSessions(response.sessions);
    const requested = typeof route.query.session === "string" ? route.query.session : "";
    if (requested && agent.sessions.some((session) => session.session_id === requested)) selectSession(requested);
    else if (agent.activeSessionId && agent.sessions.some((session) => session.session_id === agent.activeSessionId)) selectSession(agent.activeSessionId);
    else if (agent.sessions[0]) selectSession(agent.sessions[0].session_id);
    else await createNewSession();
  } catch (exc) { error.value = exc instanceof Error ? exc.message : "初始化失败"; }
});
</script>

<template>
  <section class="agent-workbench">
    <el-card shadow="never" class="agent-sessions">
      <template #header><div class="panel-heading"><span class="panel-title">研究会话</span><el-button size="small" @click="createNewSession">新建</el-button></div></template>
      <el-empty v-if="!agent.sessions.length" description="暂无会话" :image-size="56" />
      <ul v-else class="session-list"><li v-for="session in agent.sessions" :key="session.session_id" :class="{ active: agent.activeSessionId === session.session_id }" @click="selectSession(session.session_id)"><span>会话 {{ session.session_id.slice(-8) }}</span><small>{{ session.trace_id.slice(-8) }}</small></li></ul>
      <div class="starter-panel"><strong>快速开始</strong><button v-for="starter in starters" :key="starter" type="button" @click="send(starter)">{{ starter }}</button></div>
    </el-card>

    <el-card shadow="never" class="agent-conversation">
      <template #header><div class="panel-heading"><div><span class="panel-title">研究对话</span><small class="safe-boundary">BYQ 规范化工作流</small></div><div><el-button size="small" @click="resume">恢复</el-button><el-button size="small" type="danger" plain @click="cancel">取消</el-button></div></div></template>
      <p v-if="error" class="page-error">{{ error }}</p>
      <div class="message-list">
        <el-empty v-if="!agent.messages.length && !cards.length" description="选择一个研究起点，结果会以可操作卡片呈现" :image-size="80" />
        <div v-for="(message, index) in agent.messages" :key="index" :class="['message', message.role]">{{ message.text }}</div>
        <WorkflowCard v-for="card in cards" :key="card.payload.card_id" :event="card" @navigate="navigateCard" @decide="decideCard" />
      </div>
      <form class="agent-composer" @submit.prevent="send()"><el-input v-model="prompt" type="textarea" :rows="3" placeholder="输入研究问题，或要求生成策略、股票候选与优化建议…" /><el-button type="primary" :loading="busy" @click="send()">发送</el-button></form>
    </el-card>

    <el-card shadow="never" class="agent-trace">
      <template #header><span class="panel-title">工作流上下文</span></template>
      <AgentActivityPanel :activities="activities" />
      <el-divider />
      <ApprovalManagementPanel :approvals="approvals" :busy-id="approvalBusy" @decide="decide" />
    </el-card>
  </section>
</template>

<style scoped>
.session-list { display: grid; gap: .35rem; list-style: none; margin: 0; padding: 0; }
.session-list li { border-radius: var(--byq-radius-sm); cursor: pointer; display: grid; padding: .5rem .6rem; }
.session-list li:hover { background: var(--byq-surface-subtle); } .session-list li.active { background: var(--byq-brand-soft); color: var(--byq-brand); font-weight: 700; }
.session-list small, .safe-boundary { color: var(--byq-text-soft); display: block; font-size: 10px; font-weight: 400; }
.starter-panel { border-top: 1px solid var(--byq-border); display: grid; gap: .4rem; margin-top: .8rem; padding-top: .8rem; }
.starter-panel strong { color: var(--byq-text-muted); font-size: 11px; } .starter-panel button { background: var(--byq-surface-subtle); border: 0; border-radius: 8px; color: var(--byq-text-muted); cursor: pointer; font-size: 11px; padding: .5rem; text-align: left; }
.message-list { min-height: 360px; } .message { line-height: 1.65; white-space: pre-wrap; }
.message.user { max-width: 82%; } .message.agent { max-width: 90%; }
.agent-trace { align-self: start; } .agent-trace :deep(.el-card__body) { display: grid; gap: .6rem; }
@media (max-width: 900px) { .agent-workbench { display: block; } .agent-sessions { display: block; margin-bottom: .75rem; } .agent-trace { display: block; margin-top: .75rem; } .starter-panel { grid-template-columns: 1fr; } }
</style>
