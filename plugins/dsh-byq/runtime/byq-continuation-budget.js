// ADR-0090: one fresh task-ready background request. Durable business
// permission and settlement stay in Backend; this hook fences DSH tool
// dispatch only. Provider HTTP requests are bounded by Runtime Adapter's
// request-scoped proxy, not by a persisted token balance.
import { closeSync, fsyncSync, mkdirSync, openSync, writeSync } from 'node:fs';
import { dirname } from 'node:path';

export const PROFILE_LIMITS = Object.freeze({
  max_provider_calls: 16,
  max_attempts: 16,
  max_concurrent: 1,
  max_input_bytes: 262144,
  max_total_input_bytes: 4194304,
  max_output_tokens: 8192,
  max_total_output_tokens: 131072,
  max_tool_payload_bytes: 65536,
  max_total_tool_payload_bytes: 1048576,
  max_tool_calls: 16,
  deadline_ms: 180000,
});

export const ALLOWED_TOOL_NAMES = Object.freeze([
  'mcp__byq__byq_research_get',
  'mcp__byq__byq_backtest_task_get',
  'mcp__byq__byq_agent_run_start',
  'mcp__byq__byq_agent_authorize',
  'mcp__byq__byq_agent_audit',
]);

const PROFILE_ID = 'task-ready-read.v1';
const PROFILE_VERSION = 1;
const JOURNAL_SCHEMA = 'continuation-tool-guard.v1';
const TOOL_LIMIT = PROFILE_LIMITS.max_tool_calls;
const MAX_JOURNAL_BYTES = 128 * 1024;
const ALLOWED = new Set(ALLOWED_TOOL_NAMES);

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function sameClosedLimits(value) {
  if (!isRecord(value) || Object.keys(value).length !== Object.keys(PROFILE_LIMITS).length) return false;
  return Object.entries(PROFILE_LIMITS).every(([name, limit]) =>
    Number.isSafeInteger(value[name]) && value[name] === limit);
}

function validateConfig(config) {
  if (!isRecord(config)
      || Object.keys(config).sort().join(',') !== 'deadlineEpochMs,executionProfile,journalPath,requestLimits,reservationId'
      || typeof config.journalPath !== 'string' || !config.journalPath.startsWith('/')
      || typeof config.reservationId !== 'string'
      || !/^continuation_[a-f0-9]{32}$/.test(config.reservationId)
      || !Number.isSafeInteger(config.deadlineEpochMs) || config.deadlineEpochMs <= 0
      || !isRecord(config.executionProfile)
      || Object.keys(config.executionProfile).sort().join(',') !== 'profile_id,profile_sha256,profile_version'
      || config.executionProfile.profile_id !== PROFILE_ID
      || config.executionProfile.profile_version !== PROFILE_VERSION
      || typeof config.executionProfile.profile_sha256 !== 'string'
      || !/^[a-f0-9]{64}$/.test(config.executionProfile.profile_sha256)
      || !sameClosedLimits(config.requestLimits)) {
    throw new Error('BYQ_CONTINUATION_GUARD_INVALID');
  }
}

/** Pure pre-dispatch guard shared with focused offline tests. */
export function createToolGuard(config, append, cancelAgents = () => {}, now = () => Date.now()) {
  validateConfig(config);
  if (typeof append !== 'function' || typeof cancelAgents !== 'function' || typeof now !== 'function') {
    throw new Error('BYQ_CONTINUATION_GUARD_INVALID');
  }
  let calls = 0;
  let stopped = false;
  let blockedReason = null;
  const agents = new Set();

  const cancel = () => {
    for (const agent of agents) {
      try { agent.cancel({ kind: 'hook', reason: 'byq-continuation-guard' }); } catch { /* already disposed */ }
    }
    try { cancelAgents(agents); } catch { /* caller cancellation is best effort */ }
  };
  const block = (reason, toolName) => {
    if (!stopped) {
      stopped = true;
      blockedReason = reason;
      try {
        append({ phase: 'blocked', reservation_id: config.reservationId,
          blocked_reason: reason, tool_name: toolName });
      } catch { /* original block remains fail-closed */ }
      cancel();
    }
    return { kind: 'deny', reason: blockedReason };
  };

  return {
    beforeExecute(exec) {
      const toolName = typeof exec?.name === 'string' ? exec.name.slice(0, 192) : '';
      if (exec?.agent && typeof exec.agent.cancel === 'function') agents.add(exec.agent);
      if (stopped) return { kind: 'deny', reason: blockedReason };
      if (exec?.signal?.aborted) return block('BYQ_CONTINUATION_CANCELLED', toolName);
      if (now() >= config.deadlineEpochMs) return block('BYQ_CONTINUATION_DEADLINE_EXCEEDED', toolName);
      if (!ALLOWED.has(toolName)) return block('BYQ_CONTINUATION_TOOL_UNQUALIFIED', toolName);
      if (calls >= TOOL_LIMIT) return block('BYQ_CONTINUATION_TOOL_LIMIT', toolName);
      const ordinal = calls + 1;
      try {
        // Durable intent precedes DSH dispatch. The plugin is inserted at the
        // root composition (untagged/global listener), so one in-memory count
        // covers root and child agents in this single owned process.
        append({ phase: 'tool', reservation_id: config.reservationId,
          call: ordinal, tool_name: toolName });
      } catch {
        return block('BYQ_CONTINUATION_TOOL_STORAGE_FAILED', toolName);
      }
      calls = ordinal;
      return { kind: 'allow', call: ordinal };
    },
    get calls() { return calls; },
    get blockedReason() { return blockedReason; },
  };
}

function writeAll(fd, data) {
  let offset = 0;
  while (offset < data.length) {
    const written = writeSync(fd, data, offset, data.length - offset);
    if (written <= 0) throw new Error('short continuation tool journal write');
    offset += written;
  }
  fsyncSync(fd);
}

function appendJsonl(fd, row) {
  const line = Buffer.from(`${JSON.stringify(row)}\n`);
  if (line.length > MAX_JOURNAL_BYTES) throw new Error('continuation tool journal row is oversized');
  writeAll(fd, line);
}

export const name = 'byq-continuation-budget';
export const inject = ['tools', 'agents'];

export function apply(ctx, config) {
  validateConfig(config);
  mkdirSync(dirname(config.journalPath), { recursive: true, mode: 0o700 });
  const fd = openSync(config.journalPath, 'wx', 0o600);
  let closed = false;
  const agentRestrictionReleases = new Map();
  const close = () => { if (!closed) { closed = true; closeSync(fd); } };
  const releaseAllAgentRestrictions = () => {
    for (const release of agentRestrictionReleases.values()) {
      try { release(); } catch { /* agent scope may already have unwound */ }
    }
    agentRestrictionReleases.clear();
  };
  const releaseAgentRestriction = (agent) => {
    const release = agentRestrictionReleases.get(agent);
    if (release === void 0) return;
    agentRestrictionReleases.delete(agent);
    try { release(); } catch { /* the Agent scope owns normal teardown */ }
  };
  try {
    const append = row => appendJsonl(fd, row);
    const header = {
      schema_version: JOURNAL_SCHEMA,
      reservation_id: config.reservationId,
      execution_profile: config.executionProfile,
      request_limits: config.requestLimits,
      ready: true,
    };
    const restrictAgentCatalog = ({ agent }) => {
      const agentTools = agent?.ctx?.tools;
      if (!agent || !agentTools || typeof agentTools.restrict !== 'function'
          || agentRestrictionReleases.has(agent)) {
        throw new Error('BYQ_CONTINUATION_TOOL_RESTRICTION_UNQUALIFIED');
      }
      // `tools.restrict` is scoped by DSH to the calling Agent context. A
      // process-global restriction is rejected by the pinned runtime and would
      // affect unrelated Agents, so install it synchronously for every fully
      // configured Agent before `agent/session-start` starts the driver.
      const release = agentTools.restrict({ allow: [...ALLOWED_TOOL_NAMES] });
      if (typeof release !== 'function') {
        throw new Error('BYQ_CONTINUATION_TOOL_RESTRICTION_UNQUALIFIED');
      }
      agentRestrictionReleases.set(agent, release);
    };
    ctx.on('agent/created', restrictAgentCatalog);
    ctx.on('agent/disposed', ({ agent }) => {
      // DSH unwinds that Agent's scoped registrations before this event.
      // Drop our reference; the returned disposer remains available for
      // process-level cleanup if the Agent is still live when the plugin ends.
      agentRestrictionReleases.delete(agent);
    });
    const guard = createToolGuard(config, append);
    ctx.effect(() => () => {
      close();
      releaseAllAgentRestrictions();
    });
    // Pinned DSH exposes tools/pre-execute as a public waterfall before
    // dispatch. This untagged root-composition listener shares one request-wide
    // in-memory cap across root and child Agents.
    ctx.on('tools/pre-execute', async (exec, next) => {
      const decision = guard.beforeExecute(exec);
      if (decision.kind === 'deny') return decision;
      return next();
    });
    // This readiness row proves plugin setup and its mandatory lifecycle and
    // pre-dispatch listeners are installed. Runtime checks it before Session.run;
    // every Agent's tool catalog is still restricted synchronously at its own
    // agent/created event, before that Agent's driver or provider call starts.
    append(header);
    const directory = openSync(dirname(config.journalPath), 'r');
    try { fsyncSync(directory); } finally { closeSync(directory); }
  } catch (error) {
    close();
    releaseAllAgentRestrictions();
    throw error;
  }
}
