// Task budget enforcement candidate. Loaded only by an explicitly qualified
// continuation composition; the ordinary Product composition does not load it.
import { openSync, writeSync, fsyncSync, closeSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { dirname } from 'node:path';

const INPUT_CEILING = 1048576;
const OUTPUT_CEILING = 393216;
const MAX_CALLS = 256;

function positive(value) {
  return Number.isSafeInteger(value) && value > 0;
}

export function createBudgetGate(config, append, now = Date.now, monotonic = () => performance.now()) {
  if (!config || !positive(config.tokenLimit) || !positive(config.expiresAt)
      || typeof config.reservationId !== 'string' || !/^[a-zA-Z0-9_-]{8,128}$/.test(config.reservationId)) {
    throw new Error('BYQ_CONTINUATION_BUDGET_INVALID');
  }
  const started = monotonic();
  let charged = 0;
  let calls = 0;
  let failed = false;
  return (options) => {
    if (failed || now() >= config.expiresAt || monotonic() - started >= 900000) {
      throw new Error('BYQ_CONTINUATION_BUDGET_CLOSED');
    }
    // This ceiling is a candidate for the official text-only DeepSeek route.
    // Other routes and model aliases require separate provider qualification.
    if (options.provider !== 'deepseek-official' || options.model !== 'deepseek-v4-flash'
        || !positive(options.maxTokens) || options.maxTokens > OUTPUT_CEILING) {
      throw new Error('BYQ_CONTINUATION_ROUTE_UNQUALIFIED');
    }
    const ceiling = INPUT_CEILING + options.maxTokens;
    if (calls >= MAX_CALLS || ceiling > config.tokenLimit - charged) {
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
