<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  cancelSession,
  createAgentSession,
  resumeSession,
  streamWorkflowEvents,
  submitTurn,
} from "@/api/agent";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const agent = useAgentStore();
const prompt = ref("");
const error = ref("");
const busy = ref(false);

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
  void ensureSession().catch((exc) => {
    error.value = exc instanceof Error ? exc.message : "初始化失败";
  });
});
</script>

<template>
  <section class="agent-workbench">
    <aside class="agent-sessions">
      <h2>会话</h2>
      <button type="button" @click="ensureSession">新建会话</button>
      <ul>
        <li v-for="session in agent.sessions" :key="session.session_id">{{ session.session_id.slice(-8) }}</li>
      </ul>
    </aside>
    <main class="agent-conversation">
      <h2>研究对话</h2>
      <p v-if="error" class="page-error">{{ error }}</p>
      <div class="message-list">
        <div v-for="(message, index) in agent.messages" :key="index" :class="['message', message.role]">
          {{ message.text }}
        </div>
      </div>
      <form class="agent-composer" @submit.prevent="send">
        <textarea v-model="prompt" rows="3" placeholder="输入研究问题..." />
        <button type="submit" :disabled="busy">{{ busy ? "发送中..." : "发送" }}</button>
        <button type="button" @click="resume">恢复</button>
        <button type="button" @click="cancel">取消</button>
      </form>
    </main>
    <aside class="agent-trace">
      <h2>WorkflowTrace</h2>
      <ol>
        <li v-for="event in agent.events" :key="event.sequence">
          <strong>{{ event.kind }}</strong>
          <span>{{ event.source }}</span>
        </li>
      </ol>
    </aside>
  </section>
</template>
