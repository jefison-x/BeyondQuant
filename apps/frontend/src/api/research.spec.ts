import { afterEach, describe, expect, it, vi } from "vitest";
import { createTask, decideApproval, getApproval, getResearchEntity, listApprovals, listArtifacts } from "./research";

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
    const task = await createTask("Momentum research", "Evaluate a bounded signal strategy");
    expect(task.task_id).toBe("task_1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/product/research/tasks",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
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
});
