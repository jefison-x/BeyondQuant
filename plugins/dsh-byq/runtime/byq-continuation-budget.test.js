import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import {
  DISPLAY_PROVIDER_RUNTIME_ROUTES,
  QUALIFIED_CONTINUATION_ROUTES,
  continuationRouteQualified,
  createBudgetGate,
  runtimeRouteFor,
} from './byq-continuation-budget.js';

const request = { provider: 'deepseek-official', model: 'deepseek-v4-flash', maxTokens: 8 };
const ceiling = 1048576 + 8;
const config = { tokenLimit: ceiling, expiresAt: 1000, reservationId: 'reservation-synthetic' };

// The composition is present in the repository and in the architecture lane,
// but the runtime helper container mounts only this directory. When it is
// absent the authoritative composition drift assertion lives in
// tests/architecture/test_architecture.py.
const compositionUrl = new URL('../compositions/byq-product-sdk.cordis.yml', import.meta.url);
const compositionAvailable = existsSync(compositionUrl);

function compositionProviderModels(source) {
  const lines = source.split('\n');
  const start = lines.indexOf('- id: llm-opencode');
  assert.notEqual(start, -1, 'composition llm-opencode entry is required');
  let providersIndex = -1;
  for (let index = start + 1; index < lines.length; index += 1) {
    if (lines[index].startsWith('- ')) break;
    if (lines[index] === '    providers:') {
      providersIndex = index;
      break;
    }
  }
  assert.notEqual(providersIndex, -1, 'composition llm-opencode providers are required');
  const providers = {};
  let current = null;
  let inModels = false;
  for (const line of lines.slice(providersIndex + 1)) {
    if (line.trim() === '') continue;
    if (line.startsWith('- ')) break;
    const indent = line.length - line.trimStart().length;
    if (indent <= 4) break;
    if (indent === 6 && line.trimEnd().endsWith(':')) {
      current = line.trim().slice(0, -1);
      providers[current] = [];
      inModels = false;
    } else if (indent === 8 && line.trim() === 'models:') {
      inModels = true;
    } else if (indent === 8) {
      inModels = false;
    } else if (indent === 10 && inModels && line.trim().startsWith('- id:')) {
      providers[current].push(line.trim().slice('- id:'.length).trim());
    }
  }
  return providers;
}

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
  for (const change of [{ provider: 'unqualified-provider' }, { model: 'unknown' },
    { maxTokens: undefined }, { maxTokens: true }, { maxTokens: 393217 }]) {
    assert.throws(() => gate({ ...request, ...change }), /UNQUALIFIED/);
  }
});

test('every allowlisted route and model is qualified, including discovered models', () => {
  for (const [provider, models] of Object.entries(QUALIFIED_CONTINUATION_ROUTES)) {
    for (const model of models) {
      assert.equal(continuationRouteQualified(provider, model), true, `${provider}/${model}`);
    }
  }
  // The production admin profile is opencode-go / deepseek-v4.1-flash; the
  // backend maps it to the opencode-go-chat runtime route that DSH exposes.
  assert.equal(continuationRouteQualified('opencode-go-chat', 'deepseek-v4.1-flash'), true);
  assert.equal(continuationRouteQualified('opencode-go-messages', 'minimax-m3'), true);
  assert.equal(continuationRouteQualified('opencode-zen-messages', 'claude-opus-5'), true);
});

test('display providers normalize to the exact runtime route the Backend admits', () => {
  // Mirrors services/backend/app/credentials.py::_runtime_provider_for: the
  // first empty or matching model prefix wins, so the guard evaluates the same
  // runtime route the Backend resolved before admission.
  assert.equal(runtimeRouteFor('opencode-go', 'deepseek-v4.1-flash'), 'opencode-go-chat');
  assert.equal(runtimeRouteFor('opencode-go', 'deepseek-v4-flash'), 'opencode-go-chat');
  assert.equal(runtimeRouteFor('opencode-go', 'gpt-5.6-luna'), 'opencode-go-responses');
  assert.equal(runtimeRouteFor('opencode-go', 'grok-4.6'), 'opencode-go-responses');
  assert.equal(runtimeRouteFor('opencode-go', 'minimax-m3'), 'opencode-go-messages');
  assert.equal(runtimeRouteFor('opencode-go', 'qwen3.8-max'), 'opencode-go-messages');
  assert.equal(runtimeRouteFor('opencode-zen', 'claude-opus-5'), 'opencode-zen-messages');
  assert.equal(runtimeRouteFor('opencode-zen', 'deepseek-v4-flash'), 'opencode-zen-chat');
  assert.equal(runtimeRouteFor('opencode-zen', 'gpt-5.6-sol'), 'opencode-zen-responses');
  assert.equal(runtimeRouteFor('deepseek', 'deepseek-chat'), 'deepseek-official');
  // A runtime route and an unknown provider resolve without inventing a route.
  assert.equal(runtimeRouteFor('opencode-go-chat', 'deepseek-v4.1-flash'), 'opencode-go-chat');
  assert.equal(runtimeRouteFor('deepseek-official', 'deepseek-v4-flash'), 'deepseek-official');
  assert.equal(runtimeRouteFor('unqualified-provider', 'deepseek-v4-flash'), null);
  assert.equal(runtimeRouteFor('opencode-go', undefined), null);
  // Every normalization target is itself one of the qualified runtime routes,
  // so the prefix map can never introduce a route outside the single allowlist.
  for (const [provider, prefixes] of Object.entries(DISPLAY_PROVIDER_RUNTIME_ROUTES)) {
    assert.ok(prefixes.length > 0, provider);
    for (const [, runtime] of prefixes) {
      assert.ok(runtime in QUALIFIED_CONTINUATION_ROUTES, `${provider} -> ${runtime}`);
    }
  }
});

test('a display provider and its runtime route are both admitted', () => {
  assert.equal(continuationRouteQualified('opencode-go', 'deepseek-v4.1-flash'), true);
  assert.equal(continuationRouteQualified('opencode-go-chat', 'deepseek-v4.1-flash'), true);
  assert.equal(continuationRouteQualified('opencode-go', 'gpt-5.6-luna'), true);
  assert.equal(continuationRouteQualified('opencode-go', 'minimax-m3'), true);
  assert.equal(continuationRouteQualified('opencode-zen', 'claude-opus-5'), true);
  assert.equal(continuationRouteQualified('deepseek', 'deepseek-v4-flash'), true);
});

test('an unlisted model on a known route and an unknown provider are unqualified', () => {
  assert.equal(continuationRouteQualified('opencode-go-chat', 'kimi-k3-experimental'), false);
  assert.equal(continuationRouteQualified('opencode-zen-chat', 'deepseek-v4.1-flash'), false);
  assert.equal(continuationRouteQualified('deepseek-official', 'deepseek-v4.1-flash'), false);
  assert.equal(continuationRouteQualified('unqualified-provider', 'deepseek-v4-flash'), false);
  assert.equal(continuationRouteQualified('opencode-go-chat', ''), false);
  assert.equal(continuationRouteQualified('opencode-go-chat', undefined), false);
  // A display provider whose model maps to a route that does not list it, or
  // whose model prefix the Backend cannot map at all, still fails closed.
  assert.equal(continuationRouteQualified('opencode-go', 'kimi-k3-experimental'), false);
  assert.equal(continuationRouteQualified('opencode-go', 'claude-opus-5'), false);
  assert.equal(continuationRouteQualified('opencode-zen', 'deepseek-v4.1-flash'), false);
  assert.equal(continuationRouteQualified('opencode-go', ''), false);
  assert.equal(continuationRouteQualified('opencode-go', undefined), false);
});

test('the gate blocks a non-allowlisted model on an opencode route with the stable error', () => {
  const gate = createBudgetGate(config, () => assert.fail('must not persist unqualified route'), () => 1, () => 1);
  assert.throws(
    () => gate({ provider: 'opencode-go-chat', model: 'kimi-k3-experimental', maxTokens: 8 }),
    error => error.message === 'BYQ_CONTINUATION_ROUTE_UNQUALIFIED',
  );
});

test('an admitted opencode continuation charges the same conservative ceiling', () => {
  const records = [];
  const gate = createBudgetGate(config, r => records.push(r), () => 1, () => 1);
  const record = gate({ provider: 'opencode-go-chat', model: 'deepseek-v4.1-flash', maxTokens: 8 });
  assert.deepEqual(record, { reservation_id: 'reservation-synthetic', call: 1,
    reserved_tokens: ceiling, charged_ceiling: ceiling });
  assert.equal(records.length, 1);
});

test('the gate admits the production display provider without changing its accounting', () => {
  const records = [];
  const gate = createBudgetGate(config, r => records.push(r), () => 1, () => 1);
  const record = gate({ provider: 'opencode-go', model: 'deepseek-v4.1-flash', maxTokens: 8 });
  assert.deepEqual(record, { reservation_id: 'reservation-synthetic', call: 1,
    reserved_tokens: ceiling, charged_ceiling: ceiling });
  assert.equal(records.length, 1);
  assert.throws(
    () => gate({ provider: 'opencode-go', model: 'kimi-k3-experimental', maxTokens: 8 }),
    error => error.message === 'BYQ_CONTINUATION_ROUTE_UNQUALIFIED',
  );
});

test('long reservation passes fifteen minutes but rollback cannot extend its deadline', () => {
  let wall = 1000, elapsed = 0;
  const records = [];
  const gate = createBudgetGate({ ...config, tokenLimit: ceiling * 3, expiresAt: wall + 7200000 },
    r => records.push(r), () => wall, () => elapsed);
  elapsed = 900001; wall += 900001;
  assert.equal(gate(request).call, 1);
  elapsed = 7199999; wall = 1;
  assert.equal(gate(request).call, 2);
  elapsed = 7200000;
  assert.throws(() => gate(request), /CLOSED/);
  assert.equal(records.length, 2);
});

test('an existing short reservation still stops at its original monotonic deadline', () => {
  let wall = 1000, elapsed = 0;
  const gate = createBudgetGate({ ...config, expiresAt: wall + 900000 }, () => assert.fail('expired'),
    () => wall, () => elapsed);
  elapsed = 900000; wall = 1;
  assert.throws(() => gate(request), /CLOSED/);
});

test('qualified opencode routes mirror the DSH product composition allowlist',
  { skip: compositionAvailable ? false : 'DSH composition is not mounted in this environment' }, () => {
    const composition = compositionProviderModels(readFileSync(compositionUrl, 'utf8'));
    const opencode = Object.fromEntries(Object.entries(QUALIFIED_CONTINUATION_ROUTES)
      .filter(([provider]) => provider !== 'deepseek-official'));
    assert.deepEqual(opencode, composition);
  });
