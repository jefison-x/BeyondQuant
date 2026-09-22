/** ADR-0085 P3 read-only bounded research-judgment stage input.
 *
 * This tool reads the exact bounded stage input for a genuine research-judgment
 * stage. It is deliberately read-only: the proposal is committed through the
 * named server-side seam, never through a generic MCP plan/proposal write route.
 * Raw execution payloads (full signal snapshots, bars/frames/index lists) never
 * cross this boundary; the Backend caps the projection and this client refuses
 * an oversized or malformed response before it reaches the agent harness.
 */
const BACKEND_TIMEOUT_MS = 8000;
const STAGE_INPUT_MAX_BYTES = 96 * 1024;

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export type ByqResearchJudgmentResult = {
  content: Array<{ type: "text"; text: string }>;
  isError: boolean;
};

function result(payload: unknown, isError: boolean): ByqResearchJudgmentResult {
  return { content: [{ type: "text", text: JSON.stringify(payload) }], isError };
}

function errorStatus(status: number): string {
  if (status === 401) return "research_unauthorized";
  if (status === 403) return "research_forbidden";
  if (status === 404) return "research_not_found";
  if (status === 409) return "research_conflict";
  if (status === 422) return "research_request_invalid";
  return "research_unavailable";
}

function validStageInput(value: unknown, taskId: string): boolean {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const payload = value as Record<string, unknown>;
  if (payload.schema_version !== "research-stage-input.v1") return false;
  if (payload.task_id !== taskId) return false;
  if (!["strategy_draft", "backtest_analysis", "iteration_comparison", "final_selection"].includes(String(payload.stage))) return false;
  if (!Number.isSafeInteger(payload.plan_version) || !Number.isSafeInteger(payload.task_version)) return false;
  if (!Array.isArray(payload.proposal_kinds) || !Array.isArray(payload.allowed_tools)) return false;
  if (!Array.isArray(payload.evidence) || payload.evidence.length > 64) return false;
  return true;
}

export async function fetchByqResearchStageInput(
  backendUrl: string, taskId: string, fetcher: Fetcher = fetch,
): Promise<ByqResearchJudgmentResult> {
  if (!/^task_[0-9a-f]{32}$/.test(taskId)) {
    return result({ service: "beyondquant-mcp", status: "error",
      backend: { status: "research_request_invalid" } }, true);
  }
  try {
    const response = await fetcher(
      `${backendUrl}/v1/research/tasks/${encodeURIComponent(taskId)}/stage-input`,
      { method: "GET", headers: { accept: "application/json" },
        signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS) },
    );
    if (!response.ok) {
      await response.body?.cancel();
      return result({ service: "beyondquant-mcp", status: "error",
        backend: { status: errorStatus(response.status) } }, true);
    }
    const reader = response.body?.getReader();
    if (!reader) return result({ service: "beyondquant-mcp", status: "error",
      backend: { status: "invalid_response" } }, true);
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > STAGE_INPUT_MAX_BYTES) {
          await reader.cancel();
          return result({ service: "beyondquant-mcp", status: "error",
            backend: { status: "stage_input_bound_exceeded" } }, true);
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    let payload: unknown;
    try {
      payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    } catch {
      return result({ service: "beyondquant-mcp", status: "error",
        backend: { status: "invalid_response" } }, true);
    }
    if (!validStageInput(payload, taskId)) {
      return result({ service: "beyondquant-mcp", status: "error",
        backend: { status: "invalid_response" } }, true);
    }
    return result(payload, false);
  } catch {
    return result({ service: "beyondquant-mcp", status: "error",
      backend: { status: "research_unavailable" } }, true);
  }
}
