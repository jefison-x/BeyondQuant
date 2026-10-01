import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync, unlinkSync } from 'node:fs';
import {
  ALLOWED_TOOL_NAMES,
  PROFILE_LIMITS,
  createToolGuard,
  inject,
  apply,
} from './byq-continuation-budget.js';

const reservationId = `continuation_${'a'.repeat(32)}`;
const config = {
  reservationId,
  deadlineEpochMs: Date.now() + PROFILE_LIMITS.deadline_ms,
  journalPath: '/private/request/continuation-tool-guard.jsonl',
  executionProfile: {
    profile_id: 'task-ready-read.v1',
    profile_version: 1,
    profile_sha256: 'a'.repeat(64),
  },
  requestLimits: { ...PROFILE_LIMITS },
};
const allowedTool = ALLOWED_TOOL_NAMES[0];

test('profile limits and DSH plugin dependencies are closed request scope', () => {
  assert.deepEqual(PROFILE_LIMITS, {
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
  assert.deepEqual(inject, ['tools', 'agents']);
  assert.deepEqual(ALLOWED_TOOL_NAMES, [
    'mcp__byq__byq_research_get',
    'mcp__byq__byq_backtest_task_get',
    'mcp__byq__byq_agent_run_start',
    'mcp__byq__byq_agent_authorize',
    'mcp__byq__byq_agent_audit',
  ]);
});

test('seventeenth tool dispatch is denied before dispatch, with exact journal facts', () => {
  const rows = [];
  const cancellations = [];
  const guard = createToolGuard(config, row => rows.push(row), agents => cancellations.push([...agents]));
  const agents = Array.from({ length: 17 }, () => ({ cancel: () => {} }));
  for (let index = 0; index < 16; index += 1) {
    assert.equal(guard.beforeExecute({ name: allowedTool, agent: agents[index] }).kind, 'allow');
  }
  const seventeenth = guard.beforeExecute({ name: allowedTool, agent: agents[16] });
  assert.deepEqual(seventeenth, { kind: 'deny', reason: 'BYQ_CONTINUATION_TOOL_LIMIT' });
  assert.equal(guard.calls, 16);
  assert.equal(rows.filter(row => row.phase === 'tool').length, 16);
  assert.deepEqual(rows.at(-1), {
    phase: 'blocked', reservation_id: reservationId,
    blocked_reason: 'BYQ_CONTINUATION_TOOL_LIMIT', tool_name: allowedTool,
  });
  assert.equal(cancellations.length, 1);
  assert.equal(cancellations[0].length, 17);
  assert.deepEqual(guard.beforeExecute({ name: allowedTool }), seventeenth);
});

test('unknown tools are denied before admission and stop the owned agent drivers', () => {
  const rows = [];
  const cancelled = [];
  const agent = { cancel: detail => cancelled.push(detail) };
  const guard = createToolGuard(config, row => rows.push(row));
  const decision = guard.beforeExecute({ name: 'mcp__byq__byq_artifact_create', agent });
  assert.deepEqual(decision, { kind: 'deny', reason: 'BYQ_CONTINUATION_TOOL_UNQUALIFIED' });
  assert.equal(guard.calls, 0);
  assert.equal(rows.filter(row => row.phase === 'tool').length, 0);
  assert.equal(rows.at(-1).phase, 'blocked');
  assert.equal(cancelled.length, 1);
});

test('pre-cancelled DSH execution never reaches allow and poisons this request', () => {
  const rows = [];
  const guard = createToolGuard(config, row => rows.push(row));
  assert.deepEqual(guard.beforeExecute({ name: allowedTool, signal: { aborted: true } }), {
    kind: 'deny', reason: 'BYQ_CONTINUATION_CANCELLED',
  });
  assert.equal(guard.calls, 0);
  assert.equal(rows.at(-1).blocked_reason, 'BYQ_CONTINUATION_CANCELLED');
});

test('expired request deadline denies tool dispatch before journal admission', () => {
  const rows = [];
  const cancelled = [];
  const expired = { ...config, deadlineEpochMs: 5000 };
  const agent = { cancel: detail => cancelled.push(detail) };
  const guard = createToolGuard(expired, row => rows.push(row), undefined, () => 5000);
  assert.deepEqual(guard.beforeExecute({ name: allowedTool, agent }), {
    kind: 'deny', reason: 'BYQ_CONTINUATION_DEADLINE_EXCEEDED',
  });
  assert.equal(guard.calls, 0);
  assert.equal(rows.some(row => row.phase === 'tool'), false);
  assert.equal(rows.at(-1).blocked_reason, 'BYQ_CONTINUATION_DEADLINE_EXCEEDED');
  assert.equal(cancelled.length, 1);
});

test('journal failure denies and cancels rather than dispatching or replaying', () => {
  let calls = 0;
  const guard = createToolGuard(config, () => { calls += 1; throw new Error('synthetic storage failure'); });
  const agent = { cancel: () => { calls += 10; } };
  assert.deepEqual(guard.beforeExecute({ name: allowedTool, agent }), {
    kind: 'deny', reason: 'BYQ_CONTINUATION_TOOL_STORAGE_FAILED',
  });
  assert.equal(guard.calls, 0);
  assert.equal(calls, 12); // attempted admission append + agent cancellation
});


test('production plugin restricts each published Agent scope and keeps one shared dispatch cap', async () => {
  const hooks = new Map();
  const effects = [];
  const ctx = {
    effect: effect => effects.push(effect),
    on: (event, hook) => hooks.set(event, hook),
  };
  const runtimeConfig = { ...config, journalPath: `/tmp/byq-continuation-${process.pid}.jsonl` };
  apply(ctx, runtimeConfig);
  assert.deepEqual([...hooks.keys()], ['agent/created', 'agent/disposed', 'tools/pre-execute']);
  const header = JSON.parse(readFileSync(runtimeConfig.journalPath, 'utf8').trim().split(/\r?\n/)[0]);
  assert.equal(header.ready, true);
  assert.equal(header.reservation_id, reservationId);
  assert.throws(() => hooks.get('agent/created')({ agent: {} }), /TOOL_RESTRICTION_UNQUALIFIED/);

  const releases = [];
  const scopeReleases = new Map();
  const makeAgent = name => {
    const calls = [];
    const agent = { name, cancel() {} };
    agent.ctx = { tools: { restrict: filter => {
      calls.push(filter);
      const release = () => releases.push(name);
      scopeReleases.set(agent, release);
      return release;
    } } };
    assert.equal(hooks.get('agent/created')({ agent }), undefined);
    assert.deepEqual(calls, [{ allow: [...ALLOWED_TOOL_NAMES] }]);
    return agent;
  };
  const rootAgent = makeAgent('root');
  const childAgent = makeAgent('child');

  const preExecute = hooks.get('tools/pre-execute');
  for (let index = 0; index < 16; index += 1) {
    const agent = index % 2 === 0 ? rootAgent : childAgent;
    assert.deepEqual(await preExecute({ name: allowedTool, agent }, async () => ({ kind: 'allow' })), {
      kind: 'allow',
    });
  }
  assert.deepEqual(await preExecute({ name: allowedTool, agent: childAgent }, async () => ({ kind: 'allow' })), {
    kind: 'deny', reason: 'BYQ_CONTINUATION_TOOL_LIMIT',
  });
  const journal = readFileSync(runtimeConfig.journalPath, 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(journal.filter(row => row.phase === 'tool').length, 16);
  assert.equal(journal.filter(row => row.phase === 'blocked').length, 1);

  // DSH unwinds an Agent's scope before publishing agent/disposed. Model that
  // scope-owned disposer, then verify process cleanup releases the live root.
  scopeReleases.get(childAgent)();
  hooks.get('agent/disposed')({ agent: childAgent });
  effects[0]()();
  assert.deepEqual(releases, ['child', 'root']);
  unlinkSync(runtimeConfig.journalPath);
});

test('v1 money grants and widened or malformed profile carriers fail closed', () => {
  for (const invalid of [
    { ...config, tokenLimit: 16000000 },
    { ...config, requestLimits: { ...config.requestLimits, max_tool_calls: 17 } },
    { ...config, executionProfile: { ...config.executionProfile, profile_id: 'other.v1' } },
    { ...config, executionProfile: { ...config.executionProfile, profile_sha256: 'bad' } },
    { ...config, reservationId: 'not-a-v2-id' },
  ]) {
    assert.throws(() => createToolGuard(invalid, () => {}), /GUARD_INVALID/);
  }
});
