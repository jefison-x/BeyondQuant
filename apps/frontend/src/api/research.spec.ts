import { afterEach, describe, expect, it, vi } from "vitest";
import { continueApproval, createTask, decideApproval, getApproval, getResearchEntity, listApprovals, listArtifacts } from "./research";

describe("research api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads research entities through product api", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ task_id: "task_1", status: "completed" }), { status: 200 })),
    );
    const entity = await getResearchEntity("tasks", "task_1");
    expect(entity).toMatchObject({ task_id: "task_1" });
  });

  it("reads approval records through product api", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ approval_id: "agent_approval_1", status: "approved" }), { status: 200 })),
    );
    const approval = await getApproval("agent_approval_1");
    expect(approval).toMatchObject({ approval_id: "agent_approval_1" });
  });

  it("creates a research task through the product boundary", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ task_id: "task_1", owner_principal: "alice" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const task = await createTask("Momentum research", "Evaluate a bounded signal strategy", "stable-task-request-1");
    expect(task.task_id).toBe("task_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/research/tasks",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: expect.objectContaining({ "x-idempotency-key": "stable-task-request-1" }),
        body: JSON.stringify({ title: "Momentum research", objective: "Evaluate a bounded signal strategy" }),
      }),
    );
  });

  it("lists artifacts and approvals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(new Response(JSON.stringify({ artifacts: [{ artifact_id: "artifact_1" }] }), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({ approvals: [{ approval_id: "agent_approval_1" }] }), { status: 200 })),
    );
    expect((await listArtifacts()).artifacts).toHaveLength(1);
    expect((await listApprovals()).approvals).toHaveLength(1);
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/product/approvals?limit=50&offset=0",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("does not expose transport failures as a rejected task submission", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("private transport details")));
    await expect(createTask("Task", "Goal", "stable-task-request-1")).rejects.toMatchObject({
      status: 503, message: "提交结果尚未确认，请核对本次提交；不要新建任务。",
    });
  });

  it("decides an approval through the product path", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ approval: { approval_id: "agent_approval_1", status: "approved" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await decideApproval("agent_approval_1", "approved", "ok");
    expect(result.approval.status).toBe("approved");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/approvals/agent_approval_1/decision",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("retries a durable approval continuation through Product API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ approval: { continuation_status: "submitted" } }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect((await continueApproval("agent_approval_1")).approval.continuation_status).toBe("submitted");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/approvals/agent_approval_1/continue",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });
});
