<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  cancelSession,
  createAgentSession,
  listAgentSessions,
  resumeSession,
  streamWorkflowEvents,
  submitTurn,
} from "@/api/agent";
import { listApprovals } from "@/api/research";
import { listBacktests } from "@/api/quant";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const agent = useAgentStore();
const prompt = ref("");
const error = ref("");
const busy = ref(false);
const approvals = ref<Array<Record<string, unknown>>>([]);
const backtests = ref<Array<Record<string, unknown>>>([]);
const thinkingSteps = computed(() =>
  agent.events
    .filter((event) => typeof event.payload?.text === "string")
    .map((event) => ({ kind: event.kind, text: String(event.payload?.text) })),
);

function handleEvent(event: Parameters<typeof agent.addEvent>[0]) {
  agent.addEvent(event);
  if (event.kind === "agent.output.delta" && event.payload?.text) {
    const last = agent.messages[agent.messages.length - 1];
    if (last?.role === "agent") {
      last.text += String(event.payload.text);
    } else {
      agent.addMessage({ role: "agent", text: String(event.payload.text) });
    }
  }
}

async function ensureSession() {
  if (agent.activeSessionId) return;
  const session = await createAgentSession(auth.token);
  agent.addSession(session);
  void streamWorkflowEvents(session.session_id, auth.token, handleEvent, "0");
}

async function send() {
  if (!prompt.value.trim()) return;
  error.value = "";
  busy.value = true;
  try {
    await ensureSession();
    agent.addMessage({ role: "user", text: prompt.value });
    await submitTurn(agent.activeSessionId, prompt.value, auth.token);
    prompt.value = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : "发送失败";
  } finally {
    busy.value = false;
  }
}

async function resume() {
  if (!agent.activeSessionId) return;
  await resumeSession(agent.activeSessionId, auth.token);
}

async function cancel() {
  if (!agent.activeSessionId) return;
  await cancelSession(agent.activeSessionId, "soft", auth.token);
}

onMounted(() => {
  void listAgentSessions(auth.token)
    .then((response) => {
      response.sessions.forEach((session) => agent.addSession(session));
    })
    .catch(() => undefined);

  void listApprovals()
    .then((response) => {
      approvals.value = response.approvals;
    })
    .catch(() => undefined);

  void listBacktests(auth.token)
    .then((response) => {
      backtests.value = response.backtests;
    })
    .catch(() => undefined);

  const sessionId = route.query.session;
  if (
    typeof sessionId === "string" &&
    agent.sessions.some((session) => session.session_id === sessionId)
  ) {
    agent.setActiveSession(sessionId);
    void streamWorkflowEvents(sessionId, auth.token, handleEvent, "0").catch((exc) => {
      error.value = exc instanceof Error ? exc.message : "事件流失败";
    });
  } else {
    void ensureSession().catch((exc) => {
      error.value = exc instanceof Error ? exc.message : "初始化失败";
    });
  }
});
</script>

<template>
  <section class="agent-workbench">
    <el-card shadow="never" class="agent-sessions">
      <template #header>
        <div class="panel-heading">
          <span class="panel-title">会话</span>
          <el-button size="small" @click="ensureSession">新建</el-button>
        </div>
      </template>
      <el-empty v-if="!agent.sessions.length" description="暂无会话" />
      <ul v-else class="session-list">
        <li v-for="session in agent.sessions" :key="session.session_id">
          {{ session.session_id.slice(-8) }}
        </li>
      </ul>
    </el-card>

    <el-card shadow="never" class="agent-conversation">
      <template #header>
        <div class="panel-heading">
          <span class="panel-title">研究对话</span>
          <div>
            <el-button size="small" @click="resume">恢复</el-button>
            <el-button size="small" type="danger" plain @click="cancel">取消</el-button>
          </div>
        </div>
      </template>
      <p v-if="error" class="page-error">{{ error }}</p>
      <div class="message-list">
        <div v-for="(message, index) in agent.messages" :key="index" :class="['message', message.role]">
          {{ message.text }}
        </div>
      </div>
      <form class="agent-composer" @submit.prevent="send">
        <el-input v-model="prompt" type="textarea" :rows="3" placeholder="输入研究问题..." />
        <el-button type="primary" :loading="busy" @click="send">发送</el-button>
      </form>
    </el-card>

    <el-card shadow="never" class="agent-trace">
      <template #header>
        <span class="panel-title">WorkflowTrace</span>
      </template>
      <div class="panel-heading">
        <span class="panel-title">思考步骤</span>
        <el-tag>{{ thinkingSteps.length }}</el-tag>
      </div>
      <el-empty v-if="!thinkingSteps.length" description="暂无思考步骤" />
      <el-collapse v-else>
        <el-collapse-item v-for="(step, index) in thinkingSteps" :key="index" :title="step.kind">
          <div class="step-text">{{ step.text }}</div>
        </el-collapse-item>
      </el-collapse>

      <el-empty v-if="!agent.events.length" description="暂无事件" />
      <el-timeline v-else>
        <el-timeline-item v-for="event in agent.events" :key="event.sequence" :timestamp="event.timestamp">
          <strong>{{ event.kind }}</strong>
          <div class="trace-source">{{ event.source }}</div>
        </el-timeline-item>
      </el-timeline>
      <div class="panel-heading">
        <span class="panel-title">审批收件箱</span>
        <el-tag>{{ approvals.length }}</el-tag>
      </div>
      <el-empty v-if="!approvals.length" description="暂无审批" />
      <ul v-else class="approval-list">
        <li v-for="approval in approvals" :key="String(approval.approval_id)">
          {{ approval.action }} - {{ approval.status }}
        </li>
      </ul>
      <div class="panel-heading">
        <span class="panel-title">回测上下文</span>
        <el-tag>{{ backtests.length }}</el-tag>
      </div>
      <el-empty v-if="!backtests.length" description="暂无回测任务" />
      <ul v-else class="approval-list">
        <li v-for="job in backtests" :key="String(job.job_id)">
          {{ job.job_id }} - {{ job.status }}
        </li>
      </ul>
    </el-card>
  </section>
</template>

<style scoped>
.session-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.session-list li {
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text);
  padding: 0.45rem 0.5rem;
}

.session-list li:hover {
  background: var(--byq-surface-subtle);
}

.trace-source {
  color: var(--byq-text-muted);
  font-size: 12px;
}

.approval-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.approval-list li {
  border-radius: var(--byq-radius-sm);
  color: var(--byq-text);
  font-size: 12px;
  padding: 0.45rem 0.5rem;
}

.approval-list li:hover {
  background: var(--byq-surface-subtle);
}

.step-text {
  color: var(--byq-text-muted);
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
