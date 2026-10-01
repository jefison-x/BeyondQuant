export interface WorkspaceRuntimeResetReceipt {
  status: "reset";
  workspace_id: string;
  archived_conversation_count: number;
}

export interface WorkspaceResetReceipt {
  status: "reset";
  workspace_id: string;
  deleted: Record<string, number>;
  already_empty: boolean;
  archive: { reset_id: string; created_at: string; expires_at: string; retention_days: 7; row_count: number; payload_sha256: string };
}

export class WorkspaceResetRequestError extends Error {
  constructor(message: string, readonly status: number, readonly terminal = false) {
    super(message);
    this.name = "WorkspaceResetRequestError";
  }
}

const RUNTIME_RESET_PATH = "/v1/workspaces/current/runtime-reset";
const WORKSPACE_RESET_PATH = "/v1/workspaces/current/reset";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function post<T>(path: string, idempotencyKey?: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "include",
      ...(idempotencyKey ? { headers: { "Idempotency-Key": idempotencyKey } } : {}),
    });
  } catch {
    throw new WorkspaceResetRequestError("结果未确认，请检查会话状态后再重试。", 0);
  }

  const body = await response.json().catch(() => null) as unknown;
  if (!response.ok) {
    const detail = isRecord(body)
      ? (typeof body.detail === "string" ? body.detail
        : isRecord(body.error) && typeof body.error.message === "string" ? body.error.message
          : typeof body.message === "string" ? body.message : null)
      : null;
    throw new WorkspaceResetRequestError(
      detail ?? "重置请求失败，请重试。", response.status,
      body !== null && isRecord(body) && body.reset_terminal === true,
    );
  }
  if (!isRecord(body)) {
    throw new WorkspaceResetRequestError("服务器返回的重置结果无法确认，请重试。", response.status);
  }
  return body as T;
}

export async function resetCurrentWorkspaceRuntime(
  expectedWorkspaceId: string,
): Promise<WorkspaceRuntimeResetReceipt> {
  const receipt = await post<WorkspaceRuntimeResetReceipt>(RUNTIME_RESET_PATH);
  if (receipt.status !== "reset" || receipt.workspace_id !== expectedWorkspaceId
    || !Number.isSafeInteger(receipt.archived_conversation_count) || receipt.archived_conversation_count < 0) {
    throw new WorkspaceResetRequestError("运行时重置结果与当前工作区不一致，请重试核对。", 502);
  }
  return receipt;
}

export async function resetCurrentWorkspace(
  expectedWorkspaceId: string,
  idempotencyKey: string,
): Promise<WorkspaceResetReceipt> {
  const receipt = await post<WorkspaceResetReceipt>(WORKSPACE_RESET_PATH, idempotencyKey);
  const deletedIsValid = isRecord(receipt.deleted)
    && Object.values(receipt.deleted).every((count) => Number.isSafeInteger(count) && Number(count) >= 0);
  const archive = receipt.archive;
  const archiveIsValid = isRecord(archive) && archive.retention_days === 7
    && typeof archive.reset_id === "string" && /^[a-f0-9]{32}$/.test(archive.reset_id)
    && typeof archive.payload_sha256 === "string" && /^[a-f0-9]{64}$/.test(archive.payload_sha256)
    && Number.isSafeInteger(archive.row_count) && Number(archive.row_count) >= 0
    && typeof archive.created_at === "string" && typeof archive.expires_at === "string"
    && Number.isFinite(Date.parse(archive.created_at))
    && Date.parse(archive.expires_at) - Date.parse(archive.created_at) === 7 * 86400000;
  if (receipt.status !== "reset" || receipt.workspace_id !== expectedWorkspaceId
    || !archiveIsValid || !deletedIsValid || typeof receipt.already_empty !== "boolean") {
    throw new WorkspaceResetRequestError("工作区重置结果与当前工作区不一致，请重试核对。", 502);
  }
  return receipt;
}
