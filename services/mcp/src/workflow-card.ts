import { z } from "zod";


const symbol = z.string().regex(/^[0-9]{6}\.(SH|SZ|BJ)$/);
const identifier = z.string().regex(/^[A-Za-z0-9_-]{1,160}$/);
const metrics = z.object({
  total_return: z.number().finite().optional(),
  max_drawdown: z.number().finite().optional(),
  sharpe_ratio: z.number().finite().optional(),
  volatility: z.number().finite().optional(),
  win_rate: z.number().finite().optional(),
}).strict();

const strategy = z.object({
  kind: z.literal("strategy_draft"),
  title: z.string().trim().min(1).max(160),
  summary: z.string().trim().min(1).max(2000),
  name: z.string().trim().min(1).max(160),
  artifact_id: identifier.optional(),
  strategy_id: z.string().trim().min(1).max(128).optional(),
  validation_status: z.enum(["unknown", "draft"]).optional(),
}).strict();

const stocks = z.object({
  kind: z.literal("stock_candidates"),
  title: z.string().trim().min(1).max(160),
  summary: z.string().trim().min(1).max(2000).optional(),
  items: z.array(z.object({
    symbol,
    name: z.string().trim().min(1).max(80).optional(),
    reason: z.string().trim().min(1).max(500).optional(),
  }).strict()).min(1).max(50).refine(
    (items) => new Set(items.map((item) => item.symbol)).size === items.length,
    "candidate symbols must be unique",
  ),
  as_of: z.string().regex(/^[0-9]{8}$/).optional(),
  pool_id: identifier.optional(),
}).strict();

const optimization = z.object({
  kind: z.literal("optimization"),
  title: z.string().trim().min(1).max(160),
  summary: z.string().trim().min(1).max(2000).optional(),
  objective: z.string().trim().min(1).max(1000),
  changes: z.array(z.object({
    area: z.string().trim().min(1).max(80),
    before: z.string().trim().max(500).optional(),
    after: z.string().trim().min(1).max(500),
    reason: z.string().trim().min(1).max(500),
  }).strict()).min(1).max(20),
  strategy_artifact_id: identifier.optional(),
  baseline_job_id: identifier.optional(),
  metrics: metrics.optional(),
}).strict();

export const workflowCardProposalSchema = z.discriminatedUnion("kind", [strategy, stocks, optimization]);
export type WorkflowCardProposal = z.infer<typeof workflowCardProposalSchema>;

export function proposeWorkflowCard(input: unknown) {
  const proposal = workflowCardProposalSchema.parse(input);
  const { kind, ...payload } = proposal;
  return {
    content: [{
      type: "text" as const,
      text: JSON.stringify({
        service: "beyondquant-mcp",
        status: "ok",
        candidate: { kind: `agent.card.${kind}`, payload },
      }),
    }],
    isError: false,
  };
}
