import { afterEach, describe, expect, it, vi } from "vitest";
import { getApproval, getResearchEntity } from "./research";

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
});
