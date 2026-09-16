/** Transport classification only: never retries or schedules domain actions. */
export function isWriteRequest(init: RequestInit): boolean {
  return ["POST", "PUT", "PATCH", "DELETE"].includes((init.method ?? "GET").toUpperCase());
}

export function unknownWriteResult(init: RequestInit) {
  let key: unknown;
  try { key = typeof init.body === "string" ? JSON.parse(init.body)?.idempotency_key : undefined; } catch { /* no raw body projection */ }
  const payload = {
    service: "beyondquant-mcp", status: "outcome_unknown", retryable: false,
    ...(typeof key === "string" && /^[A-Za-z0-9_.:-]{1,128}$/.test(key) ? { idempotency_key: key } : {}),
    next_action: "Preserve the original request and verify its exact result within a bounded reconciliation budget. Do not repeat the write with a new identity or infer absence from a partial list.",
  };
  return { content: [{ type: "text" as const, text: JSON.stringify(payload) }], isError: false };
}

/** Artifact-producing writes can use the existing exact original-key read tool. */
export function unknownArtifactWriteResult(init: RequestInit) {
  const response = unknownWriteResult(init);
  const body = JSON.parse(response.content[0].text);
  let taskId: unknown;
  try { taskId = typeof init.body === 'string' ? JSON.parse(init.body)?.task_id : undefined; } catch { /* no raw input */ }
  if (typeof taskId === 'string' && /^task_[0-9a-f]{32}$/.test(taskId)
      && typeof body.idempotency_key === 'string') {
    body.reconciliation = { tool:'byq_research_get', arguments:{
      entity_type:'artifact', task_id:taskId, idempotency_key:body.idempotency_key,
    } };
  }
  return { content:[{type:'text' as const,text:JSON.stringify(body)}], isError:false };
}
