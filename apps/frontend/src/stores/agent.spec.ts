import { beforeEach, describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAgentStore } from "./agent";

describe("agent session store", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("replaces history without clearing the active workflow projection", () => {
    const store = useAgentStore();
    store.activeSessionId = "session-1";
    store.messages = [{ role: "agent", text: "public answer" }];
    store.events = [{
      trace_id: "trace-1",
      session_id: "session-1",
      sequence: 1,
      timestamp: "2026-08-22T00:00:00Z",
      kind: "agent.output.delta",
      source: "runtime-adapter",
      payload: { delta: "public answer" },
    }];

    store.replaceSessions([{ session_id: "session-1", trace_id: "trace-1", status: "active" }]);

    expect(store.activeSessionId).toBe("session-1");
    expect(store.messages).toHaveLength(1);
    expect(store.events).toHaveLength(1);
  });

  it("deduplicates a newly created session", () => {
    const store = useAgentStore();
    const session = { session_id: "session-1", trace_id: "trace-1", status: "active" };
    store.replaceSessions([session]);

    store.addSession(session);

    expect(store.sessions).toEqual([session]);
  });

  it("hydrates one selected replay atomically without conversation crossover", () => {
    const store = useAgentStore();
    store.hydrateSession("conversation-a", [{ role: "user", text: "A" }], []);
    store.hydrateSession("conversation-b", [{ role: "agent", text: "B" }], [{
      trace_id: "trace-b", session_id: "conversation-b", sequence: 1,
      timestamp: "2026-08-24T00:00:00Z", kind: "agent.output.delta",
      source: "runtime-adapter", payload: { delta: "B" },
    }]);
    expect(store.activeSessionId).toBe("conversation-b");
    expect(store.messages).toEqual([{ role: "agent", text: "B" }]);
    expect(store.events.every((event) => event.session_id === "conversation-b")).toBe(true);
  });

  it("removes a deleted conversation and returns an active deletion to a local blank draft", () => {
    const store = useAgentStore();
    store.replaceSessions([
      { session_id: "conversation-a", trace_id: "trace-a", status: "active" },
      { session_id: "conversation-b", trace_id: "trace-b", status: "active" },
    ]);
    store.hydrateSession("conversation-a", [{ role: "user", text: "待删除" }], []);

    store.removeSession("conversation-a");

    expect(store.sessions.map((session) => session.session_id)).toEqual(["conversation-b"]);
    expect(store.activeSessionId).toBe("");
    expect(store.messages).toEqual([]);
    expect(store.events).toEqual([]);
  });
});
