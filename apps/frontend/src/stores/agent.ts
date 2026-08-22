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
    replaceSessions(sessions: AgentSession[]) {
      this.sessions = [...sessions];
    },
    addSession(session: AgentSession) {
      this.sessions = [session, ...this.sessions.filter((current) => current.session_id !== session.session_id)];
      this.activeSessionId = session.session_id;
      this.messages = [];
      this.events = [];
    },
    setActiveSession(sessionId: string) {
      this.activeSessionId = sessionId;
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
