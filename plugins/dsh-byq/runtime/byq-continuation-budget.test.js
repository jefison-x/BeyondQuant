import assert from 'node:assert/strict';
import test from 'node:test';
import { createBudgetGate } from './byq-continuation-budget.js';

const request = { provider: 'deepseek-official', model: 'deepseek-v4-flash', maxTokens: 8 };
const ceiling = 1048576 + 8;
const config = { tokenLimit: ceiling, expiresAt: 1000, reservationId: 'reservation-synthetic' };

test('exact ceiling admits once; one-token shortage refuses before storage', () => {
  const records = [];
  const gate = createBudgetGate(config, r => records.push(r), () => 1, () => 1);
  assert.equal(gate(request).charged_ceiling, ceiling);
  assert.throws(() => gate(request), /EXHAUSTED/);
  assert.equal(records.length, 1);
  assert.throws(() => createBudgetGate({ ...config, tokenLimit: ceiling - 1 },
    () => assert.fail('must not persist'), () => 1, () => 1)(request), /EXHAUSTED/);
});

test('unknown calls retain full ceiling; concurrent intents cannot overspend', async () => {
  const records = [];
  const gate = createBudgetGate(config, r => records.push(r), () => 1, () => 1);
  const results = await Promise.allSettled(Array.from({ length: 8 }, () => Promise.resolve().then(() => gate(request))));
  assert.equal(results.filter(r => r.status === 'fulfilled').length, 1);
  assert.equal(records.length, 1);
});

test('journal failure poisons gate rather than retrying a possibly persisted charge', () => {
  let writes = 0;
  const gate = createBudgetGate(config, () => { writes++; throw new Error('synthetic'); }, () => 1, () => 1);
  assert.throws(() => gate(request), /STORAGE_FAILED/);
  assert.throws(() => gate(request), /CLOSED/);
  assert.equal(writes, 1);
});

test('expiry and monotonic hard timeout each close admission', () => {
  let wall = 1, elapsed = 1;
  const gate = createBudgetGate(config, () => assert.fail('closed'), () => wall, () => elapsed);
  wall = 1000;
  assert.throws(() => gate(request), /CLOSED/);
  wall = 1; elapsed = 900001;
  assert.throws(() => gate(request), /CLOSED/);
});

test('invalid allowances and unsupported route/output reject', () => {
  for (const tokenLimit of [true, 0, -1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => createBudgetGate({ ...config, tokenLimit }, () => {}), /INVALID/);
  }
  const gate = createBudgetGate(config, () => assert.fail('unqualified'), () => 1, () => 1);
  for (const change of [{ provider: 'opencode-go-chat' }, { model: 'unknown' },
    { maxTokens: undefined }, { maxTokens: true }, { maxTokens: 393217 }]) {
    assert.throws(() => gate({ ...request, ...change }), /UNQUALIFIED/);
  }
});
