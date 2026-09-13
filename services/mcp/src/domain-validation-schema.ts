import { z } from "zod";
import { strategyValidationInputSchema } from "./strategy.js";

const dateWindowSchema = z.object({
  start: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  end: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
}).strict();
const lightgbmParametersSchema = z.object({
  num_leaves: z.number().int().min(2).max(255).optional(),
  learning_rate: z.number().min(0.001).max(0.5).optional(),
  max_depth: z.number().int().min(-1).max(32).optional(),
  min_data_in_leaf: z.number().int().min(5).max(10000).optional(),
  feature_fraction: z.number().min(0.1).max(1).optional(),
  bagging_fraction: z.number().min(0.1).max(1).optional(),
  num_boost_round: z.number().int().min(10).max(2000).optional(),
  early_stopping_rounds: z.number().int().min(1).max(200).optional(),
}).strict();
const learnerReferenceSchema = z.union([
  z.object({ profile: z.literal("byq-lightgbm-cpu-v1"), parameters: lightgbmParametersSchema.optional() }).strict(),
  z.object({ profile: z.literal("byq-ridge-cpu-v1"), parameters: z.object({
    alpha: z.number().min(0.000001).max(1000000).optional(),
    fit_intercept: z.boolean().optional(),
  }).strict().optional() }).strict(),
]);
const v1MlStrategySchema = z.object({
  schema_version: z.literal("ml-strategy-version.v1"),
  name: z.string().min(1).max(128),
  learner: z.object({ kind: z.literal("lightgbm_regression"), profile: z.literal("byq-lightgbm-cpu-v1") }).strict(),
  feature_set: z.object({ id: z.literal("price-volume-basic-v1") }).strict(),
  target: z.object({ kind: z.literal("forward_return"), horizon_sessions: z.number().int().min(1).max(20) }).strict(),
  split: z.object({ train: dateWindowSchema, validation: dateWindowSchema, prediction: dateWindowSchema }).strict(),
  learner_parameters: lightgbmParametersSchema.optional(),
  signal_policy: z.object({
    kind: z.literal("top_n_equal_weight"), top_n: z.number().int().min(1).max(100),
    rebalance: z.enum(["daily", "weekly", "monthly"]),
  }).strict(),
}).strict();
const v2MlBase = {
  schema_version: z.literal("ml-strategy-version.v2"),
  name: z.string().min(1).max(128),
  feature_set: z.object({ id: z.literal("price-volume-basic-v1"), parameters: z.object({}).strict().optional() }).strict(),
  target: z.object({ id: z.literal("forward-return-v1"), parameters: z.object({
    horizon_sessions: z.number().int().min(1).max(20).optional(),
  }).strict().optional() }).strict(),
  validation_plan: z.object({ id: z.literal("walk-forward-purged-v1"), parameters: z.object({
    mode: z.enum(["expanding", "rolling"]).optional(),
    train_sessions: z.number().int().min(60).max(1500).optional(),
    validation_sessions: z.number().int().min(10).max(250).optional(),
    step_sessions: z.number().int().min(10).max(250).optional(),
    folds: z.number().int().min(2).max(12).optional(),
    purge_sessions: z.number().int().min(1).max(20).optional(),
    embargo_sessions: z.number().int().min(0).max(20).optional(),
  }).strict().optional() }).strict(),
  learner: learnerReferenceSchema,
  portfolio_policy: z.object({ id: z.literal("top-n-equal-weight-v1"), parameters: z.object({
    top_n: z.number().int().min(1).max(100).optional(),
    rebalance: z.enum(["daily", "weekly", "monthly"]).optional(),
  }).strict().optional() }).strict(),
  development_window: dateWindowSchema,
  prediction_window: dateWindowSchema,
};
const v2SingleMlStrategySchema = z.object(v2MlBase).strict();
const expertSchema = z.object({
  key: z.enum(["risk_on", "neutral", "risk_off"]),
  learner: learnerReferenceSchema,
  training_regimes: z.array(z.enum(["risk_on", "neutral", "risk_off"])).min(1).max(3)
    .refine(items => new Set(items).size === items.length, "training regimes must be unique"),
}).strict();
const v2RegimeMlStrategySchema = z.object({
  ...v2MlBase,
  regime: z.object({
    definition: z.literal("hs300-trend-volatility-v1"), enabled: z.literal(true),
    parameters: z.object({
      risk_on_return_60_min: z.number().min(-0.2).max(0.3).optional(),
      risk_on_ma_distance_60_min: z.number().min(-0.1).max(0.2).optional(),
      risk_off_return_20_max: z.number().min(-0.3).max(0.1).optional(),
      risk_off_volatility_20_min: z.number().min(0.005).max(0.1).optional(),
      risk_off_ma_distance_60_max: z.number().min(-0.2).max(0.05).optional(),
    }).strict().optional(),
  }).strict(),
  routing_policy: z.object({
    id: z.literal("regime-expert-map-v1"),
    fallback: z.enum(["risk_on", "neutral", "risk_off"]),
  }).strict(),
  experts: z.array(expertSchema).min(2).max(3),
}).strict().superRefine((value, context) => {
  const keys = value.experts.map(item => item.key);
  if (new Set(keys).size !== keys.length) context.addIssue({ code: z.ZodIssueCode.custom, message: "expert keys must be unique", path: ["experts"] });
  if (!keys.includes(value.routing_policy.fallback)) context.addIssue({ code: z.ZodIssueCode.custom, message: "fallback must reference a configured expert", path: ["routing_policy", "fallback"] });
});

export const domainValidationSchemas = {
  byq_factor_compute: z.object({
    task_id: z.string(),
    experiment_id: z.string().optional(),
    trace_id: z.string(),
    idempotency_key: z.string(),
    as_of_date: z.string(),
    factor: z.object({
      name: z.enum(["daily_return", "momentum"]),
      version: z.string(),
      lookback: z.number().int().min(1).max(252),
    }),
    securities: z.array(z.object({
      symbol: z.string(),
      exchange: z.string().optional(),
      asset_type: z.enum(["stock", "etf"]),
      list_date: z.string().nullable().optional(),
      delist_date: z.string().nullable().optional(),
    })),
    sessions: z.array(z.object({ trade_date: z.string(), is_open: z.boolean() })),
    statuses: z.array(z.object({
      symbol: z.string(),
      trade_date: z.string(),
      state: z.enum(["trading", "suspended"]),
      reason: z.string().nullable().optional(),
    })).optional(),
    bars: z.array(z.object({
      symbol: z.string(),
      trade_date: z.string(),
      open: z.number(),
      high: z.number(),
      low: z.number(),
      close: z.number(),
    })),
    universe_snapshots: z.array(z.object({ snapshot_date: z.string(), symbols: z.array(z.string()) })),
    sources: z.array(z.object({
      provider: z.string(),
      endpoint: z.string(),
      request_fingerprint: z.string(),
      dataset_id: z.string(),
      announcement_date: z.string().nullable().optional(),
      effective_date: z.string().nullable().optional(),
    })),
  }).extend({ agent_run_id: z.string().min(1).max(128) }).strict(),
  byq_strategy_validate: strategyValidationInputSchema.extend({ agent_run_id: z.string().min(1).max(128) }),
  byq_ml_strategy_create: z.object({
    task_id: z.string(), experiment_id: z.string().optional(), idempotency_key: z.string().min(1).max(128),
    agent_run_id: z.string().min(1).max(128),
    strategy: z.union([v1MlStrategySchema, v2RegimeMlStrategySchema, v2SingleMlStrategySchema]),
  }).strict(),
};
