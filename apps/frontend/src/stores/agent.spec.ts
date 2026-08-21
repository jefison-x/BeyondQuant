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
});
