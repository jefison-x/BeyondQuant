// Task budget enforcement candidate. Loaded only by an explicitly qualified
// continuation composition; the ordinary Product composition does not load it.
import { openSync, writeSync, fsyncSync, closeSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { dirname } from 'node:path';

// Conservative per-call ceilings. Every admitted `llm/stream` call re-sends its
// whole input, so the guard charges the input ceiling plus that call's output
// bound. These values are the single source of truth mirrored by the Backend
// reservation sizing (services/backend/app/research_continuation.py) and the
// runtime-adapter output cap (services/runtime-adapter/app/continuation_budget.py);
// tests/architecture/test_architecture.py fails CI on any divergence.
export const CONTINUATION_INPUT_CEILING = 1048576;
export const CONTINUATION_OUTPUT_CEILING = 393216;

// A data-ready auto-continuation is a bounded tool-calling turn, not a single
// model call: the first call returns tool calls and the next call resumes after
// the tools ran. One reservation therefore covers a bounded number of calls for
// one event, each charged the conservative per-call ceiling, for a fixed total
// token budget. `DATA_READY_MAX_CALLS` is the per-turn call bound and
// `DATA_READY_TOKEN_LIMIT` is the total budget the Backend reserves for the
// event. `createBudgetGate` also enforces the call bound derived from that
// total, so an exhausted reservation fails closed on either bound.
export const DATA_READY_MAX_OUTPUT_TOKENS = 8192;
export const DATA_READY_MAX_CALLS = 8;
export const DATA_READY_CALL_CEILING = CONTINUATION_INPUT_CEILING + DATA_READY_MAX_OUTPUT_TOKENS;
export const DATA_READY_TOKEN_LIMIT = DATA_READY_MAX_CALLS * DATA_READY_CALL_CEILING;

// ADR-0085 P3: a genuine research-judgment stage uses at most two model calls by
// default. BYQ owns and enforces the durable-progress fence; this guard mirrors
// the SAME default so a single stage reservation can never fund more than two
// calls. tests/architecture/test_architecture.py fails CI if it diverges from
// packages/contracts/research_judgment.py DEFAULT_MAX_MODEL_CALLS_PER_STAGE.
export const RESEARCH_JUDGMENT_MAX_CALLS = 2;

// Absolute process-local safety cap, independent of any single reservation.
const MAX_CALLS = 256;

// Qualified continuation routes. This mirrors the single Backend authority,
// RUNTIME_MODEL_ALLOWLIST in services/backend/app/credentials.py (ADR-0075 /
// ADR-0076): deepseek-official plus the six closed opencode-* DSH runtime
// providers, each with the exact model ids the DSH composition accepts.
// tests/architecture/test_architecture.py parses this table together with
// plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml and fails CI on any
// divergence, so the guard can never silently drift stricter (blocking an
// admitted route) or looser (admitting an unconfigured route) than admission.
export const QUALIFIED_CONTINUATION_ROUTES = {
  "deepseek-official": ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
  "opencode-go-responses": ["gpt-5.6-luna", "grok-4.6"],
  "opencode-go-chat": ["deepseek-v4-flash", "deepseek-v4.1-flash", "deepseek-v4-pro", "glm-5.3", "kimi-k3"],
  "opencode-go-messages": ["minimax-m3", "qwen3.8-max"],
  "opencode-zen-responses": ["gpt-5.6-sol", "gpt-5.6-terra", "grok-4.6"],
  "opencode-zen-chat": ["deepseek-v4-flash", "minimax-m3"],
  "opencode-zen-messages": ["claude-opus-5", "claude-sonnet-5", "qwen3.7-max"],
};

// Display/credential provider -> DSH runtime route by model prefix. The
// Backend owns this exact semantics in services/backend/app/credentials.py
// (_MODEL_RUNTIME_PREFIXES / _runtime_provider_for): a model profile stores a
// display provider such as "opencode-go", while DSH registers one route per
// wire protocol (opencode-go-chat / -responses / -messages). The first entry
// whose prefix is empty or is a prefix of the model id wins, exactly as the
// Backend resolves it. services/backend/tests/test_credentials.py parses this
// table and fails CI if it diverges from the Backend mapping, so the guard
// admits the same (provider, model) pair the Backend already admitted without
// keeping a second model list.
export const DISPLAY_PROVIDER_RUNTIME_ROUTES = {
  "deepseek": [
    ["", "deepseek-official"],
  ],
  "opencode-go": [
    ["gpt-", "opencode-go-responses"],
    ["grok-", "opencode-go-responses"],
    ["deepseek-", "opencode-go-chat"],
    ["glm-", "opencode-go-chat"],
    ["kimi-", "opencode-go-chat"],
    ["minimax-", "opencode-go-messages"],
    ["qwen", "opencode-go-messages"],
  ],
  "opencode-zen": [
    ["gpt-", "opencode-zen-responses"],
    ["grok-", "opencode-zen-responses"],
    ["claude-", "opencode-zen-messages"],
    ["qwen", "opencode-zen-messages"],
    ["deepseek-", "opencode-zen-chat"],
    ["minimax-", "opencode-zen-messages"],
  ],
};

// Resolve the runtime route the guard should evaluate for one call. An
// already-runtime provider is returned unchanged; a display provider is
// normalized through the Backend mapping; an unknown provider resolves to
// null so it can only fail closed.
export function runtimeRouteFor(provider, model) {
  if (Object.prototype.hasOwnProperty.call(QUALIFIED_CONTINUATION_ROUTES, provider)) {
    return provider;
  }
  const prefixes = DISPLAY_PROVIDER_RUNTIME_ROUTES[provider];
  if (!Array.isArray(prefixes) || typeof model !== 'string') {
    return null;
  }
  for (const [prefix, runtime] of prefixes) {
    if (prefix === '' || model.startsWith(prefix)) {
      return runtime;
    }
  }
  return null;
}

export function continuationRouteQualified(provider, model) {
  const runtime = runtimeRouteFor(provider, model);
  if (runtime === null) {
    return false;
  }
  const models = QUALIFIED_CONTINUATION_ROUTES[runtime];
  return Array.isArray(models) && typeof model === 'string' && models.includes(model);
}

function positive(value) {
  return Number.isSafeInteger(value) && value > 0;
}

export function createBudgetGate(config, append, now = Date.now, monotonic = () => performance.now()) {
  if (!config || !positive(config.tokenLimit) || !positive(config.expiresAt)
      || typeof config.reservationId !== 'string' || !/^[a-zA-Z0-9_-]{8,128}$/.test(config.reservationId)) {
    throw new Error('BYQ_CONTINUATION_BUDGET_INVALID');
  }
  const started = monotonic();
  // Capture the admitted remaining lifetime once; wall-clock rollback must
  // never extend this reservation, including after a long-running model call.
  const lifetime = Math.max(0, Math.min(86400000, config.expiresAt - now()));
  // Strict per-reservation call bound. Every admitted call costs at least the
  // input ceiling plus one output token, so the fixed total budget can never
  // fund more than this many calls even before the absolute MAX_CALLS cap.
  const maxCalls = Math.max(1, Math.min(MAX_CALLS,
    Math.floor(config.tokenLimit / (CONTINUATION_INPUT_CEILING + 1))));
  let charged = 0;
  let calls = 0;
  let failed = false;
  return (options) => {
    if (failed || now() >= config.expiresAt || monotonic() - started >= lifetime) {
      throw new Error('BYQ_CONTINUATION_BUDGET_CLOSED');
    }
    // The route must be one admission already qualified (ADR-0075): an exact
    // (provider, model) pair from the Backend runtime allowlist. Unknown
    // providers, a known route with an unlisted model, and the official route
    // with an unknown model all fail closed before any budget is charged.
    if (!continuationRouteQualified(options.provider, options.model)
        || !positive(options.maxTokens) || options.maxTokens > CONTINUATION_OUTPUT_CEILING) {
      throw new Error('BYQ_CONTINUATION_ROUTE_UNQUALIFIED');
    }
    const ceiling = CONTINUATION_INPUT_CEILING + options.maxTokens;
    if (calls >= maxCalls || ceiling > config.tokenLimit - charged) {
      throw new Error('BYQ_CONTINUATION_BUDGET_EXHAUSTED');
    }
    const record = { reservation_id: config.reservationId, call: calls + 1,
      reserved_tokens: ceiling, charged_ceiling: charged + ceiling };
    // Synchronous durable append precedes next(). Shared in-process children
    // cannot interleave between the availability check and the charge.
    try { append(record); } catch {
      failed = true;
      throw new Error('BYQ_CONTINUATION_BUDGET_STORAGE_FAILED');
    }
    charged += ceiling;
    calls += 1;
    return record;
  };
}

export const name = 'byq-continuation-budget';
export const inject = ['llm', 'agents'];

export function apply(ctx, config) {
  if (!config || typeof config.journalPath !== 'string' || !config.journalPath.startsWith('/')) {
    throw new Error('BYQ_CONTINUATION_BUDGET_INVALID');
  }
  // Reopening the same reservation is refused. Crash recovery must reconcile
  // its original receipt; it must not reset the process-local allowance.
  const fd = openSync(config.journalPath, 'wx', 0o600);
  let closed = false;
  const close = () => { if (!closed) { closed = true; closeSync(fd); } };
  try {
    const append = record => {
      const data = Buffer.from(JSON.stringify(record) + '\n');
      let offset = 0;
      while (offset < data.length) {
        const written = writeSync(fd, data, offset, data.length - offset);
        if (written <= 0) throw new Error('short budget journal write');
        offset += written;
      }
      fsyncSync(fd);
    };
    const gate = createBudgetGate(config, append);
    const initiators = new Set();
    let stopped = false;
    ctx.effect(() => close);
    ctx.on('llm/stream', async function* (options, next) {
      const initiator = ctx.agents.currentInitiator();
      if (initiator) initiators.add(initiator);
      try {
        if (stopped) throw new Error('BYQ_CONTINUATION_BUDGET_CLOSED');
        gate(options);
      } catch (error) {
        if (!stopped) {
          stopped = true;
          try { append({ blocked_reason: error.message, blocked_purpose: options.purpose === 'compaction' ? 'compaction' : 'model' }); } catch { /* unreadable evidence retains the full reservation */ }
        }
        // Public DSH cancellation closes the owned agent drivers, including
        // an 'always' retry policy; it does not cancel BYQ business jobs.
        for (const agent of initiators) {
          try { agent.cancel({ kind: 'hook', reason: 'byq-continuation-budget' }); } catch { /* disposal already fences this driver */ }
        }
        throw error;
      }
      yield* next();
    });
    append({ schema_version: 'continuation-budget-guard.v1', reservation_id: config.reservationId,
      token_limit: config.tokenLimit, ready: true });
    const directory = openSync(dirname(config.journalPath), 'r');
    try { fsyncSync(directory); } finally { closeSync(directory); }
  } catch (error) {
    close();
    throw error;
  }
}
