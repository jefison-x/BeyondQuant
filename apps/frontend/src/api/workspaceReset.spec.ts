import { afterEach, describe, expect, it, vi } from "vitest";
import { resetCurrentWorkspace, resetCurrentWorkspaceRuntime, WorkspaceResetRequestError } from "./workspaceReset";

describe("workspace reset Product API", () => {
  afterEach(() => vi.restoreAllMocks());

  it("resets only the current runtime through the Gateway Product API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "reset", workspace_id: "workspace_alice", archived_conversation_count: 2,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const receipt = await resetCurrentWorkspaceRuntime("workspace_alice");

    expect(receipt.archived_conversation_count).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith("/v1/workspaces/current/runtime-reset", {
      method: "POST", credentials: "include",
    });
  });

  it("sends a bodyless workspace reset with a stable idempotency header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "reset", workspace_id: "workspace_alice", deleted: { research_tasks: 2, artifacts: 1 }, already_empty: false,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const receipt = await resetCurrentWorkspace("workspace_alice", "stable-reset-key");

    expect(receipt.deleted).toEqual({ research_tasks: 2, artifacts: 1 });
    expect(fetchMock).toHaveBeenCalledWith("/v1/workspaces/current/reset", {
      method: "POST", credentials: "include", headers: { "Idempotency-Key": "stable-reset-key" },
    });
  });

  it("rejects a receipt scoped to another workspace", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "reset", workspace_id: "workspace_bob", deleted: {}, already_empty: true,
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(resetCurrentWorkspace("workspace_alice", "stable-reset-key"))
      .rejects.toMatchObject({ status: 502, message: expect.stringContaining("当前工作区") });
  });

  it("keeps Gateway blockers visible for retry instead of hiding them", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({
      detail: "active or unconfirmed Agent run prevents workspace reset",
    }), { status: 409 })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(resetCurrentWorkspace("workspace_alice", "stable-reset-key"))
      .rejects.toBeInstanceOf(WorkspaceResetRequestError);
    await expect(resetCurrentWorkspace("workspace_alice", "stable-reset-key"))
      .rejects.toMatchObject({ status: 409, message: "active or unconfirmed Agent run prevents workspace reset" });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/v1/workspaces/current/reset", expect.objectContaining({
      headers: { "Idempotency-Key": "stable-reset-key" },
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/v1/workspaces/current/reset", expect.objectContaining({
      headers: { "Idempotency-Key": "stable-reset-key" },
    }));
  });

  it("marks a finalized blocker so the next attempt uses a new request key", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "运行中的任务阻止重置", reset_terminal: true,
    }), { status: 409 })));

    await expect(resetCurrentWorkspace("workspace_alice", "stable-reset-key"))
      .rejects.toMatchObject({ status: 409, terminal: true });
  });
});
