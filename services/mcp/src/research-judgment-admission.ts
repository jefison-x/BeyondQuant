/** ADR-0085 P3 stage-scoped runtime enforcement for a bounded judgment turn.
 *
 * When the trusted runtime adapter marks a request with the judgment-stage
 * header, this wrapper admits ONLY the exact read-only tools for that stage and
 * blocks every other tool (including every write/approval/execute tool). The
 * agent cannot set the header: DSH's MCP client supplies it from the adapter,
 * and an unknown stage fails closed. The single proposal channel is the trusted
 * internal adapter invocation, never an agent-facing MCP write.
 *
 * tests/architecture/test_architecture.py fails CI if this table diverges from
 * packages/contracts/research_judgment.py STAGE_ALLOWED_TOOLS.
 */
import { boundedBody } from './domain-schema-observation.js';

type Handler = { fetch(request: Request, options?: { parsedBody?: unknown }): Promise<Response> };

export const RESEARCH_JUDGMENT_STAGE_HEADER = 'x-byq-research-judgment-stage';

export const STAGE_READ_TOOLS: Record<string, readonly string[]> = {
  strategy_draft: ['byq_agent_context', 'byq_research_get', 'byq_research_stage_input_get'],
  backtest_analysis: ['byq_agent_context', 'byq_backtest_analysis_get', 'byq_backtest_task_get',
    'byq_research_get', 'byq_research_stage_input_get'],
  iteration_comparison: ['byq_agent_context', 'byq_backtest_analysis_get', 'byq_backtest_task_get',
    'byq_research_get', 'byq_research_stage_input_get'],
  final_selection: ['byq_agent_context', 'byq_backtest_analysis_get', 'byq_research_get',
    'byq_research_stage_input_get'],
};

function blocked(reason: string): Response {
  return Response.json({ jsonrpc: '2.0', id: null, result: { isError: true,
    content: [{ type: 'text', text: JSON.stringify({ status: 'blocked',
      reason, message: 'This tool is outside the bounded research-judgment stage. Stop and report the blocker; do not switch tools or approve anything.' }) }] } });
}

export function researchJudgmentAdmission(handler: Handler): Handler {
  return { async fetch(request, options) {
    const stage = request.headers.get(RESEARCH_JUDGMENT_STAGE_HEADER);
    if (stage === null) return handler.fetch(request, options);
    const allowed = STAGE_READ_TOOLS[stage];
    if (allowed === undefined) return blocked('research_judgment_stage_unknown');
    if (request.method !== 'POST') return handler.fetch(request, options);
    const body = options?.parsedBody ?? await boundedBody(request);
    if (!body || typeof body !== 'object' || Array.isArray(body)) return blocked('research_judgment_envelope_invalid');
    const envelope = body as Record<string, unknown>;
    if (envelope.method !== 'tools/call') return handler.fetch(request, { ...options, parsedBody: body });
    const params = envelope.params as Record<string, unknown> | undefined;
    const tool = params && typeof params.name === 'string' ? params.name : undefined;
    if (tool !== undefined && allowed.includes(tool)) {
      return handler.fetch(request, { ...options, parsedBody: body });
    }
    return blocked('research_judgment_tool_not_allowed');
  } };
}
