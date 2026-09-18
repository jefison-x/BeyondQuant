/** Closed correction hints: never forward arbitrary Backend detail or input values. */
type CorrectionHint = { message: string; repair_limit: number };
const hints: Record<string, CorrectionHint> = {
  'input_snapshot.sources must be a non-empty list': { repair_limit: 1,
    message: 'Provide input_snapshot.sources with real provider, endpoint and request_fingerprint provenance; do not invent evidence.' },
  'input_snapshot.sources entries must be objects': { repair_limit: 1,
    message: 'Each input_snapshot.sources entry must be an object with provider, endpoint and request_fingerprint.' },
  'strategy version is not approved for execution': { repair_limit: 1,
    message: 'Read the exact strategy approval. A human Agent approval is not a materialized strategy approval; complete the bound strategy approval before preparing execution.' },
  'strategy version must be approved before task creation': { repair_limit: 1,
    message: 'Complete the exact bound strategy approval before creating a backtest task.' },
  'strategy version does not belong to task_id': { repair_limit: 1,
    message: 'Use the strategy version belonging to this exact research task; do not select another task by recency.' },
  'strategy_version_artifact_id must reference a validated strategy version': { repair_limit: 1,
    message: 'Use the validated strategy_version artifact ID for this exact task, not a draft or an approval ID.' },
  'security master must be synchronized before backtest data preparation': { repair_limit: 1,
    message: 'Security master data is unavailable. Report the data blocker; repeating backtest preparation does not repair it.' },
  'market data requirement exceeds 50000 symbol-session cells': { repair_limit: 0,
    message: 'The requested universe multiplied by the date window exceeds one bounded readiness partition of 50000 symbol-session cells. This is a data-scale blocker: report it to the user and do not resubmit the identical oversized request or invent partition work.' },
  'start_date must not be after end_date': { repair_limit: 1,
    message: 'Correct the date window so start_date is on or before end_date, then prepare once; do not resubmit an inverted window.' },
  'order_quantity must be aligned to execution.lot_size': { repair_limit: 1,
    message: 'order_quantity must be a positive multiple of execution.lot_size. Align the order quantity to the execution lot size and repair once.' },
  'stock pool must be active for signal production': { repair_limit: 1,
    message: 'The stock pool snapshot must belong to an active pool before it can produce signals. Read the pool status and select an active pool; do not assume a non-active pool is usable.' },
  'stock pool snapshot has no members': { repair_limit: 0,
    message: 'The stock pool snapshot has no members, so it cannot produce signals. This is a domain blocker: report it and do not resubmit the same snapshot or invent membership.' },
  'stock-pool snapshot has no members': { repair_limit: 0,
    message: 'The stock pool snapshot has no members, so it cannot produce signals. This is a domain blocker: report it and do not resubmit the same snapshot or invent membership.' },
  'stock pool contains symbols absent from the frozen security master': { repair_limit: 0,
    message: 'The stock pool references symbols missing from the frozen security master. This is a data-integrity blocker: report it and do not resubmit the identical pool or fabricate security-master coverage.' },
  'execution_profile_unsupported: generate_target_weights is not supported': { repair_limit: 0,
    message: 'The strategy produces target weights, which this execution profile does not support. Report the capability blocker; do not resubmit the identical request.' },
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
  if (hint) return { message: hint.message, repair_limit: hint.repair_limit };
  const match = /^([a-z_.]+) (?:must be|is invalid|is required)\b/.exec(detail);
  if (match && fields.has(match[1])) return { field: match[1], repair_limit: 1,
    message: `Check ${match[1]} against the tool schema and the exact task's authoritative data. Repair once; if still rejected, report the blocker.` };
  return undefined;
}
