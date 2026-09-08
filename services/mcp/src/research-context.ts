/** Read-only original-conversation candidates; never select or resume a task. */
import { z } from "zod";

const text = (maximum: number) => z.string().min(1).refine(value => Array.from(value).length <= maximum);
const task = z.object({
  task_id: z.string().regex(/^task_[0-9a-f]{32}$/), title: text(200), objective_excerpt: text(400),
  objective_truncated: z.boolean(), status: z.enum(["planned", "running", "completed", "failed", "cancelled"]),
  version: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER),
  stage: z.enum(["planning", "data_preparation", "research", "strategy", "approval", "training", "prediction",
    "backtest", "comparison", "blocked", "completed"]).nullable(),
  next_action: text(160).nullable(), blocked_reason: text(160).nullable(),
}).strict().refine(value => !value.objective_truncated || Array.from(value.objective_excerpt).length === 400);
const schema = z.object({
  schema_version: z.literal("research-task-context.v1"), status: z.enum(["available", "none_bound"]),
  tasks: z.array(task).max(20), has_more: z.boolean(),
}).strict().refine(value =>
  new Set(value.tasks.map(item => item.task_id)).size === value.tasks.length
  && (value.status === "none_bound" ? value.tasks.length === 0 && !value.has_more : value.tasks.length > 0)
  && (!value.has_more || value.tasks.length === 20));

function unavailable() {
  return { schema_version: "research-task-context.v1" as const, status: "unavailable" as const,
    tasks: [] as never[], has_more: null };
}
export type ResearchContext = z.infer<typeof schema> | ReturnType<typeof unavailable>;
type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;

async function boundedJson(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error("missing context body");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 128 * 1024) {
        await reader.cancel();
        throw new Error("context response bound exceeded");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
}

export async function fetchResearchContext(backendUrl: string, fetcher: Fetcher = fetch): Promise<ResearchContext> {
  try {
    const response = await fetcher(`${backendUrl}/v1/agent/research-context`, {
      method: "GET", headers: { accept: "application/json" }, signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) { await response.body?.cancel(); return unavailable(); }
    const parsed = schema.safeParse(await boundedJson(response));
    return parsed.success ? parsed.data : unavailable();
  } catch {
    return unavailable();
  }
}
