/** Closed correction hints: never forward arbitrary Backend detail or input values. */
const hints: Record<string, string> = {
  'input_snapshot.sources must be a non-empty list': 'Provide input_snapshot.sources with real provider, endpoint and request_fingerprint provenance; do not invent evidence.',
  'input_snapshot.sources entries must be objects': 'Each input_snapshot.sources entry must be an object with provider, endpoint and request_fingerprint.',
  'strategy version is not approved for execution': 'Read the exact strategy approval. A human Agent approval is not a materialized strategy approval; complete the bound strategy approval before preparing execution.',
  'strategy version must be approved before task creation': 'Complete the exact bound strategy approval before creating a backtest task.',
  'strategy version does not belong to task_id': 'Use the strategy version belonging to this exact research task; do not select another task by recency.',
  'strategy_version_artifact_id must reference a validated strategy version': 'Use the validated strategy_version artifact ID for this exact task, not a draft or an approval ID.',
  'security master must be synchronized before backtest data preparation': 'Security master data is unavailable. Report the data blocker; repeating backtest preparation does not repair it.',
};
const fields = new Set(['task_id', 'experiment_id', 'name', 'trace_id', 'idempotency_key',
  'input_snapshot', 'source.provider', 'source.endpoint', 'source.request_fingerprint',
  'start_date', 'end_date', 'order_quantity', 'execution.lot_size', 'strategy_version_artifact_id',
  'stock_pool_snapshot_id']);

export function safeRequestValidation(payload: unknown) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return undefined;
  const detail = (payload as Record<string, unknown>).detail;
  if (typeof detail !== 'string' || detail.length > 512) return undefined;
  const hint = Object.hasOwn(hints, detail) ? hints[detail] : undefined;
  if (hint) return { message: hint, repair_limit: 1 };
  const match = /^([a-z_.]+) (?:must be|is invalid|is required)\b/.exec(detail);
  if (match && fields.has(match[1])) return { field: match[1], repair_limit: 1,
    message: `Check ${match[1]} against the tool schema and the exact task's authoritative data. Repair once; if still rejected, report the blocker.` };
  return undefined;
}
