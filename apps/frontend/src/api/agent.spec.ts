import { afterEach, describe, expect, it, vi } from "vitest";
import { cancelSession, createAgentSession, submitTurn } from "./agent";

describe("agent api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("creates a product session with the bearer token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session_id: "s1", trace_id: "t1", status: "ready" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const session = await createAgentSession("test-token");
    expect(session.session_id).toBe("s1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/agent/sessions",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer test-token" }) }),
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
});
