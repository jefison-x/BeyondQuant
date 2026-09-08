import { afterEach, describe, expect, it, vi } from "vitest";
import { beginTaskSubmission, finishTaskSubmission, readTaskSubmission } from "./taskSubmission";

describe("durable research submission identity", () => {
  afterEach(() => { localStorage.clear(); vi.restoreAllMocks(); });
  it("retains the original request across reload and refuses changed meaning", () => {
    const pending = beginTaskSubmission("alice:workspace-a", "Research A", "Original goal");
    expect(readTaskSubmission("alice:workspace-a")).toEqual(pending);
    expect(beginTaskSubmission("alice:workspace-a", "Research A", "Original goal")).toEqual(pending);
    expect(() => beginTaskSubmission("alice:workspace-a", "Research B", "Other goal")).toThrow("原任务");
    finishTaskSubmission("alice:workspace-a", "wrong-acknowledgement");
    expect(readTaskSubmission("alice:workspace-a")).toEqual(pending);
    finishTaskSubmission("alice:workspace-a", pending.key);
    expect(readTaskSubmission("alice:workspace-a")).toBeNull();
    expect(beginTaskSubmission("alice:workspace-a", "Research A", "Original goal").key).not.toBe(pending.key);
  });
  it("isolates owners and workspaces", () => {
    const pending = beginTaskSubmission("alice:workspace-a", "Research", "Goal");
    expect(readTaskSubmission("bob:workspace-a")).toBeNull();
    expect(readTaskSubmission("alice:workspace-b")).toBeNull();
    expect(beginTaskSubmission("bob:workspace-a", "Research", "Goal").key).not.toBe(pending.key);
  });
  it("fails closed if storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage denied"); });
    expect(() => beginTaskSubmission("alice", "Research", "Goal")).toThrow("storage denied");
  });
});
