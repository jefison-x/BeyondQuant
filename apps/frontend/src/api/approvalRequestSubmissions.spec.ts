import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { submitProductApprovalRequestOnce } from "./approvalRequestSubmissions";

const taskId = `task_${"1".repeat(32)}`;
const artifactId = `artifact_${"a".repeat(32)}`;
const payload = {
  schema_version: "byq-product-approval-request.v1" as const,
  request_type: "strategy_version" as const,
  task_id: taskId,
  strategy_version_artifact_id: artifactId,
};

function requestEnvelope(requestKey: string, owner = "alice", workspace = "workspace-alice") {
  return {
    schema_version: "byq-product-approval-request.v1",
    request: {
      request_id: `approval_request_${"b".repeat(32)}`,
      request_type: "strategy_version",
      status: "pending",
      owner_principal: owner,
      workspace_id: workspace,
      task_id: taskId,
      resource_artifact_id: artifactId,
      content_sha256: "c".repeat(64),
      request_key: requestKey,
      created_at: "2026-10-14T00:00:00Z",
      updated_at: "2026-10-14T00:00:00Z",
      strategy_version_artifact_id: artifactId,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("keeps the original request key and only performs GET reconciliation after an unknown POST", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "temporary outage" } }), { status: 503 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: "temporary outage" } }), { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  await expect(submitProductApprovalRequestOnce(
    { ownerPrincipal: "alice", workspaceId: "workspace-alice" }, payload,
  )).rejects.toThrow("原申请键已保留");

  const firstPostInit = fetchMock.mock.calls[0][1] as RequestInit;
  const originalKey = JSON.parse(String(firstPostInit.body)).request_key as string;
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(requestEnvelope(originalKey, "bob", "workspace-bob")), { status: 200 }));

  await expect(submitProductApprovalRequestOnce(
    { ownerPrincipal: "alice", workspaceId: "workspace-alice" }, payload,
  )).rejects.toThrow("身份或工作区不一致");
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  expect(fetchMock.mock.calls.slice(1).every(([, init]) => (init as RequestInit).method === undefined)).toBe(true);
  expect(String(fetchMock.mock.calls[1][0])).toContain(`/by-key/${encodeURIComponent(originalKey)}`);
  expect(String(fetchMock.mock.calls[2][0])).toContain(`/by-key/${encodeURIComponent(originalKey)}`);
});
