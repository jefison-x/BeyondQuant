import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelSession, createAgentSession, deleteAgentSession, getAgentSession, listAgentSessions, streamWorkflowEvents, submitTurn, updateAgentSession } from "./agent";

describe("agent api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("creates a product session with the session cookie", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session_id: "s1", trace_id: "t1", status: "ready" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const session = await createAgentSession("test-token");
    expect(session.session_id).toBe("s1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/agent/sessions",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("submits only prompt content to the product turn boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ accepted: true }), { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    await submitTurn("s1", "hello", "test-token");
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/agent/sessions/s1/turns",
      expect.objectContaining({ body: JSON.stringify({ content: "hello" }) }),
    );
  });

  it("sends the cancellation mode without exposing provider or DSH details", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "cancelled" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await cancelSession("s1", "soft", "test-token");
    expect(String(fetchMock.mock.calls[0][1]?.body)).not.toContain("deepseek");
  });

  it("deletes a durable conversation instead of treating deletion as archive", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session_id: "c1", status: "deleted" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await deleteAgentSession("c1", "token");

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/agent/sessions/c1",
      expect.objectContaining({ method: "DELETE", credentials: "include" }),
    );
  });

  it("loads and updates only the durable conversation projection", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ sessions: [], total: 0, limit: 20, offset: 0 })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ conversation: { session_id: "c1" }, messages: [], events: [] })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ session: { session_id: "c1", title: "新标题" } })));
    vi.stubGlobal("fetch", fetchMock);
    await listAgentSessions("token", { status: "archived", search: "动量", limit: 20 });
    await getAgentSession("c1", "token");
    await updateAgentSession("c1", { title: "新标题", pinned: true }, "token");

    expect(fetchMock.mock.calls[0][0]).toBe("/v1/agent/sessions?status=archived&search=%E5%8A%A8%E9%87%8F&limit=20");
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/agent/sessions/c1");
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({ method: "PATCH" }));
    expect(String(fetchMock.mock.calls[2][1]?.body)).not.toContain("runtime");
  });

  it("reports an unexpected workflow stream end so the caller can reconnect", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      'id: 3\nevent: workflow-trace\ndata: {"session_id":"s1","sequence":3,"kind":"session.result","payload":{}}\n\n',
      { status: 200, headers: { "content-type": "text/event-stream" } },
    )));
    const events: unknown[] = [];
    await expect(streamWorkflowEvents("s1", "token", (event) => events.push(event), "2"))
      .rejects.toThrow("workflow stream ended");
    expect(events).toHaveLength(1);
  });
});
