import assert from 'node:assert/strict';
import { createHmac, randomUUID } from 'node:crypto';
import { chmodSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import {
  installProductAcpIdentity,
  signAcpAgentToken,
  validateClaims,
} from './byq-acp-mcp-identity.js';

const NOW = 1_800_000_000_000;
const SIGNING_KEY = 'synthetic-acp-signing-key-32-bytes-minimum';
const ROOT_ID = 'b'.repeat(32);
const BOOT_ID = 'c'.repeat(32);
const RESERVATION_ID = `continuation_${'d'.repeat(32)}`;

function claims(overrides = {}) {
  const rootSession = '8b90c2b5-3a08-4eae-9fc7-04baf12910de';
  return {
    v: 1,
    aud: 'byq-product-mcp',
    root_run_id: ROOT_ID,
    runtime_boot_id: BOOT_ID,
    owner_principal: 'alice@example.test',
    workspace_id: 'workspace_alice',
    actor_principal: 'byq-product-agent-public-session-1',
    trace_id: 'trace-1',
    session_id: 'public-session-1',
    dsh_run_id: 'generation-1',
    native_root_session_id: rootSession,
    native_agent_session_id: rootSession,
    native_parent_session_id: null,
    origin: 'root',
    depth: 0,
    expires_at: NOW + 24 * 60 * 60 * 1000,
    ...overrides,
  };
}

function identityEnv(home, overrides = {}) {
  return {
    DSH_HOME: home,
    DSH_SESSION_ROOT: tmpdir(),
    BYQ_MCP_URL: 'http://mcp.test/mcp/v1',
    BYQ_MCP_ACP_DISCOVERY_TOKEN: 'synthetic-discovery-token',
    BYQ_MCP_ACP_SIGNING_KEY: SIGNING_KEY,
    BYQ_RUNTIME_BOOT_ID: BOOT_ID,
    BYQ_OWNER_PRINCIPAL: 'alice@example.test',
    BYQ_WORKSPACE_ID: 'workspace_alice',
    BYQ_ACTOR_PRINCIPAL: 'byq-product-agent-public-session-1',
    BYQ_TRACE_ID: 'trace-1',
    BYQ_SESSION_ID: 'public-session-1',
    BYQ_DSH_RUN_ID: 'generation-1',
    BYQ_ROOT_RUN_ID: ROOT_ID,
    BYQ_CONTINUATION_RESERVATION_ID: RESERVATION_ID,
    ...overrides,
  };
}

function fakeContext() {
  const handlers = new Map();
  const eventOptions = new Map();
  const globalConfigs = [];
  const context = {
    sessions: new Map(),
    async plugin(plugin, config) {
      assert.equal(plugin, McpClient);
      globalConfigs.push(config);
    },
    on(name, handler, options) {
      handlers.set(name, handler);
      eventOptions.set(name, options);
      return () => handlers.delete(name);
    },
  };
  const McpClient = { apply: async () => undefined };
  context.sessions.get = context.sessions.get.bind(context.sessions);
  return { context, handlers, eventOptions, globalConfigs, McpClient };
}

function fakeAgent(id, cwd, { parentSession, origin, delegationDepth } = {}) {
  const header = {
    id,
    cwd,
    ...(parentSession === undefined ? {} : { parentSession }),
    ...(origin === undefined ? {} : { origin }),
    ...(delegationDepth === undefined ? {} : { delegationDepth }),
  };
  const scopedConfigs = [];
  const agent = {
    id,
    session: { id, header },
    options: delegationDepth === undefined ? {} : { subagentDepth: delegationDepth },
    ctx: {
      async plugin(plugin, config) {
        scopedConfigs.push(config);
      },
    },
  };
  return { agent, scopedConfigs };
}

function tokenClaims(token) {
  const [prefix, encoded] = token.split('.');
  assert.equal(prefix, 'byq-acp-v1');
  return JSON.parse(Buffer.from(encoded, 'base64url').toString('utf8'));
}

test('signed identity uses exact compact sorted JSON bytes and 24 hour maximum expiry', () => {
  const input = claims();
  const token = signAcpAgentToken(input, SIGNING_KEY, NOW);
  const [prefix, encoded, signature] = token.split('.');
  assert.equal(prefix, 'byq-acp-v1');
  assert.equal(token.split('.').length, 3);
  const payload = Buffer.from(encoded, 'base64url');
  const parsed = JSON.parse(payload.toString('utf8'));
  const expectedPayload = Buffer.from(JSON.stringify(Object.fromEntries(
    Object.keys(input).sort().map(key => [key, input[key]]))), 'utf8');
  assert.deepEqual(payload, expectedPayload);
  const expectedSignature = createHmac('sha256', Buffer.from(SIGNING_KEY, 'utf8'))
    .update(expectedPayload).digest('base64url');
  assert.equal(signature, expectedSignature);
  assert.equal(parsed.expires_at, NOW + 24 * 60 * 60 * 1000);
  assert.equal(parsed.owner_principal, 'alice@example.test');
  assert.equal(parsed.native_parent_session_id, null);

  assert.throws(() => signAcpAgentToken(claims({ expires_at: NOW + 24 * 60 * 60 * 1000 + 1 }),
    SIGNING_KEY, NOW));
  assert.throws(() => signAcpAgentToken(claims(), 'short', NOW));
  assert.throws(() => validateClaims(claims({ native_agent_session_id: randomUUID() }), NOW));
});

test('official Agent creation mounts distinct root and child tokens under discovery bootstrap', async () => {
  const home = mkdtempSync(join(tmpdir(), 'byq-acp-identity-'));
  const previousCwd = process.cwd();
  process.chdir(home);
  try {
    const { context, handlers, eventOptions, globalConfigs, McpClient } = fakeContext();
    // The fixed profile composition owns exactly one process-wide discovery
    // client; the identity plugin must not install a duplicate namespace.
    await context.plugin(McpClient, {
      transport: 'streamable-http', serverName: 'byq', url: 'http://mcp.test/mcp/v1',
      headers: { Authorization: 'Bearer synthetic-discovery-token' }, failOnStartupError: true,
    });
    await installProductAcpIdentity(context, { maxDepth: 1 }, {
      McpClient, env: identityEnv(home), now: () => NOW,
    });
    assert.equal(globalConfigs.length, 1);
    assert.deepEqual(globalConfigs[0].headers, { Authorization: 'Bearer synthetic-discovery-token' });
    assert.equal(globalConfigs[0].failOnStartupError, true);
    assert.equal(eventOptions.get('agent/created').global, true);
    assert.equal(eventOptions.get('tools/pre-execute').global, true);
    assert.equal(eventOptions.get('agent/disposed').global, true);

    const rootId = '8b90c2b5-3a08-4eae-9fc7-04baf12910de';
    const childId = '39d11d7a-06b5-4f1b-9c68-9e1f782c0ef5';
    const { agent: root, scopedConfigs: rootConfigs } = fakeAgent(rootId, home);
    context.sessions.set(rootId, root.session);
    await handlers.get('agent/created')({ agent: root, source: 'startup' });
    assert.equal(rootConfigs.length, 1);

    const rootToken = rootConfigs[0].headers.Authorization.slice('Bearer '.length);
    const rootClaims = tokenClaims(rootToken);
    assert.equal(rootClaims.origin, 'root');
    assert.equal(rootClaims.native_root_session_id, rootId);
    assert.equal(rootClaims.native_agent_session_id, rootId);
    assert.equal(rootClaims.native_parent_session_id, null);
    assert.equal(rootClaims.depth, 0);
    assert.equal(rootConfigs[0].headers['X-BYQ-Continuation-Reservation'], RESERVATION_ID);

    const { agent: child, scopedConfigs: childConfigs } = fakeAgent(childId, home, {
      parentSession: rootId, origin: 'subagent', delegationDepth: 1,
    });
    context.sessions.set(childId, child.session);
    await handlers.get('agent/created')({ agent: child, source: 'startup' });
    assert.equal(childConfigs.length, 1);
    const childToken = childConfigs[0].headers.Authorization.slice('Bearer '.length);
    const childClaims = tokenClaims(childToken);
    assert.equal(childClaims.origin, 'subagent');
    assert.equal(childClaims.native_root_session_id, rootId);
    assert.equal(childClaims.native_agent_session_id, childId);
    assert.equal(childClaims.native_parent_session_id, rootId);
    assert.equal(childClaims.depth, 1);
    assert.notEqual(childToken, rootToken);

    let dispatched = false;
    const preExecute = handlers.get('tools/pre-execute');
    const allowed = await preExecute({ name: 'mcp__byq__byq_agent_context', agent: child }, async () => {
      dispatched = true;
      return { kind: 'allow' };
    });
    assert.deepEqual(allowed, { kind: 'allow' });
    assert.equal(dispatched, true);
    const denied = await preExecute({ name: 'mcp__byq__byq_agent_context', agent: {} }, async () => {
      throw new Error('unscoped tool reached execution');
    });
    assert.equal(denied.kind, 'deny');
    assert.equal(denied.reason, 'BYQ_AGENT_IDENTITY_UNAVAILABLE');

    const { agent: sibling } = fakeAgent(randomUUID(), home, {
      parentSession: randomUUID(), origin: 'subagent', delegationDepth: 1,
    });
    await assert.rejects(handlers.get('agent/created')({ agent: sibling, source: 'startup' }));
    const marker = join(home, '.byq-acp-root-binding.json');
    assert.deepEqual(JSON.parse(readFileSync(marker, 'utf8')), {
      schema_version: 'byq-acp-root-binding.v1', native_root_session_id: rootId, cwd: home,
    });
    assert.equal(statSync(marker).mode & 0o777, 0o600);

    handlers.get('agent/disposed')({ agent: child });
    const disposed = await preExecute({ name: 'mcp__byq__byq_agent_context', agent: child }, async () => {
      throw new Error('disposed Agent reached execution');
    });
    assert.equal(disposed.kind, 'deny');
  } finally {
    process.chdir(previousCwd);
    rmSync(home, { recursive: true, force: true });
  }
});

test('resume requires the exact persisted native root marker and exact process identity', async () => {
  const home = mkdtempSync(join(tmpdir(), 'byq-acp-resume-'));
  const previousCwd = process.cwd();
  process.chdir(home);
  try {
    const { context, handlers, McpClient } = fakeContext();
    const rootId = '8b90c2b5-3a08-4eae-9fc7-04baf12910de';
    const marker = join(home, '.byq-acp-root-binding.json');
    writeFileSync(marker, JSON.stringify({
      schema_version: 'byq-acp-root-binding.v1', native_root_session_id: rootId, cwd: home,
    }), { mode: 0o600 });
    chmodSync(marker, 0o600);
    const env = identityEnv(home, { BYQ_NATIVE_ROOT_SESSION_ID: rootId });
    await installProductAcpIdentity(context, { maxDepth: 1 }, { McpClient, env, now: () => NOW });
    const { agent: root, scopedConfigs } = fakeAgent(rootId, home);
    context.sessions.set(rootId, root.session);
    await handlers.get('agent/created')({ agent: root, source: 'resume' });
    assert.equal(scopedConfigs.length, 1);
    assert.equal(tokenClaims(scopedConfigs[0].headers.Authorization.slice(7)).native_root_session_id, rootId);
  } finally {
    process.chdir(previousCwd);
    rmSync(home, { recursive: true, force: true });
  }
});

test('invalid scoped identity setup fails closed before tool dispatch', async () => {
  const home = mkdtempSync(join(tmpdir(), 'byq-acp-invalid-'));
  const previousCwd = process.cwd();
  process.chdir(home);
  try {
    const { context, handlers, McpClient } = fakeContext();
    await installProductAcpIdentity(context, { maxDepth: 1 }, {
      McpClient, env: identityEnv(home), now: () => NOW,
    });
    const rootId = '8b90c2b5-3a08-4eae-9fc7-04baf12910de';
    const { agent: root } = fakeAgent(rootId, home);
    context.sessions.set(rootId, root.session);
    await handlers.get('agent/created')({ agent: root, source: 'startup' });
    const { agent: child, scopedConfigs } = fakeAgent(randomUUID(), home, {
      parentSession: randomUUID(), origin: 'subagent', delegationDepth: 1,
    });
    await assert.rejects(handlers.get('agent/created')({ agent: child, source: 'startup' }));
    assert.equal(scopedConfigs.length, 0);
  } finally {
    process.chdir(previousCwd);
    rmSync(home, { recursive: true, force: true });
  }
});
