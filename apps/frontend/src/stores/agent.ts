import { defineStore } from "pinia";
import type { AgentSession, WorkflowTraceEvent } from "@/api/types";

export interface AgentMessage {
  role: "user" | "agent";
  text: string;
}

export const useAgentStore = defineStore("agent", {
  state: () => ({
    sessions: [] as AgentSession[],
    activeSessionId: "",
    messages: [] as AgentMessage[],
    events: [] as WorkflowTraceEvent[],
  }),
  actions: {
    addSession(session: AgentSession) {
      this.sessions.unshift(session);
      this.activeSessionId = session.session_id;
      this.messages = [];
      this.events = [];
    },
    addMessage(message: AgentMessage) {
      this.messages.push(message);
    },
    addEvent(event: WorkflowTraceEvent) {
      this.events.push(event);
    },
  },
});
