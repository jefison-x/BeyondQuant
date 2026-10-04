import {
  closeSync,
  constants as fsConstants,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  openSync,
  readFileSync,
  realpathSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { createHmac, randomBytes } from 'node:crypto';
import { createRequire } from 'node:module';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

const SERVER_NAME = 'byq';
const AUDIENCE = 'byq-product-mcp';
const TOKEN_PREFIX = 'byq-acp-v1';
const TOKEN_TTL_MS = 24 * 60 * 60 * 1000;
const MAX_DELEGATION_DEPTH = 1;
const ROOT_BINDING_MARKER = '.byq-acp-root-binding.json';
const ACP_NATIVE_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ROOT_ID = /^[0-9a-f]{32}$/;
const PRINCIPAL = /^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$/;
const TRACE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const CLAIM_KEYS = Object.freeze([
  'actor_principal', 'aud', 'depth', 'dsh_run_id', 'expires_at', 'native_agent_session_id',
  'native_parent_session_id', 'native_root_session_id', 'origin', 'owner_principal',
  'root_run_id', 'runtime_boot_id', 'session_id', 'trace_id', 'v', 'workspace_id',
]);

export const name = 'byq-acp-mcp-identity';
export const inject = ['tools', 'sessions'];

function fail() {
  throw new Error('BYQ_ACP_AGENT_IDENTITY_UNAVAILABLE');
}

function exactObjectKeys(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

function validString(value, pattern) {
  return typeof value === 'string' && pattern.test(value);
}

function validSigningKey(key) {
  return typeof key === 'string' && Buffer.byteLength(key, 'utf8') >= 32
    && Buffer.byteLength(key, 'utf8') <= 4096;
}

function base64url(bytes) {
  return Buffer.from(bytes).toString('base64url');
}

function canonicalPayload(claims) {
  const sorted = Object.fromEntries(Object.keys(claims).sort().map(key => [key, claims[key]]));
  return Buffer.from(JSON.stringify(sorted), 'utf8');
}

/** Canonical v1 signer shared with the trusted MCP ingress verifier. */
export function signAcpAgentToken(claims, signingKey, now = Date.now()) {
  validateClaims(claims, now);
  if (!validSigningKey(signingKey)) fail();
  const payload = canonicalPayload(claims);
  const signature = createHmac('sha256', Buffer.from(signingKey, 'utf8')).update(payload).digest();
  return `${TOKEN_PREFIX}.${base64url(payload)}.${base64url(signature)}`;
}

/** Validate exact signed claims before mounting the token on a scoped client. */
export function validateClaims(claims, now = Date.now()) {
  if (!exactObjectKeys(claims, CLAIM_KEYS)
      || claims.v !== 1 || claims.aud !== AUDIENCE
      || !validString(claims.root_run_id, ROOT_ID)
      || !validString(claims.runtime_boot_id, ROOT_ID)
      || !validString(claims.owner_principal, PRINCIPAL)
      || !validString(claims.actor_principal, PRINCIPAL)
      || !validString(claims.workspace_id, TRACE)
      || !validString(claims.trace_id, TRACE)
      || !validString(claims.session_id, TRACE)
      || !validString(claims.dsh_run_id, TRACE)
      || !validString(claims.native_root_session_id, ACP_NATIVE_SESSION_ID)
      || !validString(claims.native_agent_session_id, ACP_NATIVE_SESSION_ID)
      || !(claims.native_parent_session_id === null
        || validString(claims.native_parent_session_id, ACP_NATIVE_SESSION_ID))
      || !['root', 'subagent'].includes(claims.origin)
      || !Number.isSafeInteger(claims.depth)
      || !Number.isSafeInteger(claims.expires_at)
      || !Number.isSafeInteger(now)
      || claims.expires_at <= now || claims.expires_at > now + TOKEN_TTL_MS) fail();
  if (claims.actor_principal !== `byq-product-agent-${claims.session_id}`) fail();
  if (claims.origin === 'root') {
    if (claims.depth !== 0 || claims.native_parent_session_id !== null
        || claims.native_agent_session_id !== claims.native_root_session_id) fail();
  } else if (claims.depth !== 1
      || claims.native_parent_session_id !== claims.native_root_session_id
      || claims.native_agent_session_id === claims.native_root_session_id) fail();
  return claims;
}

function runtimeIdentity(env) {
  const endpoint = env.BYQ_MCP_URL;
  let parsed;
  try { parsed = new URL(endpoint); } catch { fail(); }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname
      || parsed.username || parsed.password || parsed.search || parsed.hash) fail();
  if (typeof env.BYQ_MCP_ACP_DISCOVERY_TOKEN !== 'string'
      || env.BYQ_MCP_ACP_DISCOVERY_TOKEN.length === 0
      || !validSigningKey(env.BYQ_MCP_ACP_SIGNING_KEY)
      || !validString(env.BYQ_ROOT_RUN_ID, ROOT_ID)
      || !validString(env.BYQ_RUNTIME_BOOT_ID, ROOT_ID)
      || !validString(env.BYQ_OWNER_PRINCIPAL, PRINCIPAL)
      || !validString(env.BYQ_ACTOR_PRINCIPAL, PRINCIPAL)
      || !validString(env.BYQ_WORKSPACE_ID, TRACE)
      || !validString(env.BYQ_TRACE_ID, TRACE)
      || !validString(env.BYQ_SESSION_ID, TRACE)
      || !validString(env.BYQ_DSH_RUN_ID, TRACE)
      || env.BYQ_ACTOR_PRINCIPAL !== `byq-product-agent-${env.BYQ_SESSION_ID}`) fail();
  if (env.BYQ_NATIVE_ROOT_SESSION_ID !== undefined
      && !validString(env.BYQ_NATIVE_ROOT_SESSION_ID, ACP_NATIVE_SESSION_ID)) fail();
  const reservation = env.BYQ_CONTINUATION_RESERVATION_ID;
  if (reservation !== undefined
      && (!/^continuation_[0-9a-f]{32}$/.test(reservation)
        || !validString(env.BYQ_ROOT_RUN_ID, ROOT_ID))) fail();
  return {
    endpoint,
    discoveryToken: env.BYQ_MCP_ACP_DISCOVERY_TOKEN,
    signingKey: env.BYQ_MCP_ACP_SIGNING_KEY,
    rootRunId: env.BYQ_ROOT_RUN_ID,
    runtimeBootId: env.BYQ_RUNTIME_BOOT_ID,
    owner: env.BYQ_OWNER_PRINCIPAL,
    workspace: env.BYQ_WORKSPACE_ID,
    actor: env.BYQ_ACTOR_PRINCIPAL,
    trace: env.BYQ_TRACE_ID,
    publicSession: env.BYQ_SESSION_ID,
    dshRunId: env.BYQ_DSH_RUN_ID,
    expectedNativeRootId: env.BYQ_NATIVE_ROOT_SESSION_ID,
    continuationReservationId: reservation,
  };
}

function mcpConfig(identity, bearer, { includeReservation = false } = {}) {
  const headers = { Authorization: `Bearer ${bearer}` };
  if (includeReservation && identity.continuationReservationId !== undefined) {
    headers['X-BYQ-Continuation-Reservation'] = identity.continuationReservationId;
  }
  return {
    transport: 'streamable-http',
    serverName: SERVER_NAME,
    url: identity.endpoint,
    headers,
    failOnStartupError: true,
    toolCallTimeoutMs: 60_000,
  };
}

function canonicalDirectory(value) {
  if (typeof value !== 'string' || !value.startsWith('/')) fail();
  const resolved = realpathSync(value);
  if (resolve(value) !== resolved) fail();
  return resolved;
}

function rootMarkerPath(home) {
  return join(home, ROOT_BINDING_MARKER);
}

function readRootMarker(markerPath) {
  const info = lstatSync(markerPath);
  if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600 || info.size > 4096) fail();
  const fd = openSync(markerPath, fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW ?? 0));
  let raw;
  try {
    const opened = fstatSync(fd);
    if ((opened.dev !== info.dev) || (opened.ino !== info.ino)
        || !opened.isFile() || (opened.mode & 0o777) !== 0o600 || opened.size > 4096) fail();
    raw = readFileSync(fd);
  } finally {
    closeSync(fd);
  }
  const value = JSON.parse(raw.toString('utf8'));
  if (!exactObjectKeys(value, ['schema_version', 'native_root_session_id', 'cwd'])
      || value.schema_version !== 'byq-acp-root-binding.v1'
      || !validString(value.native_root_session_id, ACP_NATIVE_SESSION_ID)
      || typeof value.cwd !== 'string'
      || !raw.equals(Buffer.from(JSON.stringify(value), 'utf8'))) fail();
  return value;
}

function writeRootMarker(markerPath, nativeRootId, cwd) {
  const directory = dirname(markerPath);
  const temporary = join(directory, `.byq-acp-root-binding.${randomBytes(16).toString('hex')}.tmp`);
  const value = {
    schema_version: 'byq-acp-root-binding.v1',
    native_root_session_id: nativeRootId,
    cwd,
  };
  let fd;
  try {
    fd = openSync(temporary, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_WRONLY
      | (fsConstants.O_NOFOLLOW ?? 0), 0o600);
    writeFileSync(fd, JSON.stringify(value), 'utf8');
    fsyncSync(fd);
    closeSync(fd);
    fd = undefined;
    // linkSync publishes the complete file atomically and refuses replacement.
    linkSync(temporary, markerPath);
    unlinkSync(temporary);
    const dirFd = openSync(directory, fsConstants.O_RDONLY);
    try { fsyncSync(dirFd); } finally { closeSync(dirFd); }
  } catch {
    if (fd !== undefined) {
      try { closeSync(fd); } catch { /* preserve the setup failure */ }
    }
    try { unlinkSync(temporary); } catch { /* a missing temp is already clean */ }
    fail();
  }
}

function verifyOrCreateRootMarker({ markerPath, nativeRootId, cwd, expectedNativeRootId, fresh }) {
  if (expectedNativeRootId !== undefined) {
    if (!validString(expectedNativeRootId, ACP_NATIVE_SESSION_ID)
        || expectedNativeRootId !== nativeRootId) fail();
    const value = readRootMarker(markerPath);
    if (value.native_root_session_id !== nativeRootId || value.cwd !== cwd) fail();
    return;
  }
  if (!fresh) {
    const value = readRootMarker(markerPath);
    if (value.native_root_session_id !== nativeRootId || value.cwd !== cwd) fail();
    return;
  }
  // A fresh ACP root gets a fresh private home. Any pre-existing marker is an
  // uncertain or stale identity and blocks creation rather than being reused.
  try {
    lstatSync(markerPath);
    fail();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  writeRootMarker(markerPath, nativeRootId, cwd);
}

function validateRootOrChild(ctx, agent, source, identity, rootBinding, expectedCwd) {
  const session = agent?.session;
  const header = session?.header;
  const agentId = agent?.id;
  if (!header || typeof agentId !== 'string' || header.id !== agentId
      || !validString(agentId, ACP_NATIVE_SESSION_ID)) fail();
  const cwd = canonicalDirectory(header.cwd);
  if (cwd !== expectedCwd) fail();

  if (header.parentSession === undefined && header.origin === undefined) {
    const headerDepth = header.delegationDepth ?? 0;
    if (headerDepth !== 0 || !['startup', 'resume', 'clear', 'compact'].includes(source)) fail();
    if (rootBinding !== undefined) {
      if (rootBinding.nativeRootId !== agentId || rootBinding.cwd !== cwd) fail();
      if (identity.expectedNativeRootId !== undefined
          && identity.expectedNativeRootId !== agentId) fail();
    } else if (identity.expectedNativeRootId !== undefined) {
      if (source !== 'resume' || identity.expectedNativeRootId !== agentId) fail();
    } else if (source !== 'startup') {
      fail();
    }
    return { nativeRootId: agentId, cwd, depth: 0, parentSessionId: null, isRoot: true };
  }

  if (source !== 'startup' || header.origin !== 'subagent'
      || typeof header.parentSession !== 'string' || rootBinding === undefined) fail();
  const parent = ctx.sessions?.get(header.parentSession);
  const parentHeader = parent?.header;
  if (!parentHeader || parentHeader.id !== header.parentSession
      || parentHeader.id !== rootBinding.nativeRootId
      || parentHeader.origin !== undefined || parentHeader.parentSession !== undefined) fail();
  if ((header.delegationDepth ?? 0) !== 1 || header.delegationDepth !== 1
      || identity.expectedNativeRootId !== undefined
        && identity.expectedNativeRootId !== rootBinding.nativeRootId) fail();
  if (agent.options?.subagentDepth !== undefined && agent.options.subagentDepth !== 1) fail();
  if (rootBinding.cwd !== cwd) fail();
  return {
    nativeRootId: rootBinding.nativeRootId,
    cwd,
    depth: 1,
    parentSessionId: parentHeader.id,
    isRoot: false,
  };
}

function makeClaims(identity, lineage, agentId, now) {
  const claims = {
    v: 1,
    aud: AUDIENCE,
    root_run_id: identity.rootRunId,
    runtime_boot_id: identity.runtimeBootId,
    owner_principal: identity.owner,
    workspace_id: identity.workspace,
    actor_principal: identity.actor,
    trace_id: identity.trace,
    session_id: identity.publicSession,
    dsh_run_id: identity.dshRunId,
    native_root_session_id: lineage.nativeRootId,
    native_agent_session_id: agentId,
    native_parent_session_id: lineage.parentSessionId,
    origin: lineage.isRoot ? 'root' : 'subagent',
    depth: lineage.depth,
    expires_at: now + TOKEN_TTL_MS,
  };
  return validateClaims(claims, now);
}

/** Test seam and shared implementation for the official Cordis Product plugin. */
export async function installProductAcpIdentity(ctx, config, { McpClient, env = process.env, now = Date.now } = {}) {
  if (!McpClient || typeof McpClient !== 'object' || typeof McpClient.apply !== 'function') fail();
  if (config !== undefined && !exactObjectKeys(config, ['maxDepth'])) fail();
  if (config?.maxDepth !== undefined && config.maxDepth !== MAX_DELEGATION_DEPTH) fail();
  const identity = runtimeIdentity(env);
  const expectedCwd = canonicalDirectory(env.DSH_HOME);
  if (expectedCwd !== canonicalDirectory(process.cwd())) fail();
  const sessionRoot = canonicalDirectory(env.DSH_SESSION_ROOT);
  const relativeHome = relative(sessionRoot, expectedCwd);
  if (relativeHome === '' || relativeHome === '..' || relativeHome.startsWith(`..${sep}`)
      || isAbsolute(relativeHome)) fail();
  const rootMarker = rootMarkerPath(expectedCwd);
  const registeredAgents = new WeakSet();
  let rootBinding;

  // The composition installs one global discovery client before this plugin.
  // Keep ownership there so a second global `byq` namespace cannot shadow the
  // discovery-only client; this plugin owns signed per-Agent clients only.

  ctx.on('tools/pre-execute', (exec, next) => {
    if (typeof exec?.name !== 'string' || !exec.name.startsWith('mcp__byq__')) return next();
    if (!exec.agent || !registeredAgents.has(exec.agent)) {
      return { kind: 'deny', reason: 'BYQ_AGENT_IDENTITY_UNAVAILABLE' };
    }
    return next();
  }, { prepend: true, global: true });

  ctx.on('agent/created', async ({ agent, source }) => {
    const lineage = validateRootOrChild(ctx, agent, source, identity, rootBinding, expectedCwd);
    const claims = makeClaims(identity, lineage, agent.id, now());
    const token = signAcpAgentToken(claims, identity.signingKey, claims.expires_at - TOKEN_TTL_MS);
    const config = mcpConfig(identity, token, { includeReservation: true });

    // Agent-scoped plugin activation is awaited by the official serial event.
    // A discovery client cannot become an execution fallback if this fails.
    await agent.ctx.plugin(McpClient, config);

    if (lineage.isRoot) {
      verifyOrCreateRootMarker({
        markerPath: rootMarker,
        nativeRootId: lineage.nativeRootId,
        cwd: lineage.cwd,
        expectedNativeRootId: identity.expectedNativeRootId,
        fresh: rootBinding === undefined && identity.expectedNativeRootId === undefined,
      });
      rootBinding = { nativeRootId: lineage.nativeRootId, cwd: lineage.cwd };
    }
    registeredAgents.add(agent);
  }, { prepend: true, global: true });

  ctx.on('agent/disposed', ({ agent }) => { registeredAgents.delete(agent); }, { global: true });
}

async function loadOfficialMcpClient() {
  const runtimeRoot = process.env.BYQ_DSH_RUNTIME_ROOT;
  if (typeof runtimeRoot !== 'string' || !runtimeRoot.startsWith('/')) fail();
  const entry = join(resolve(runtimeRoot), 'apps', 'cli', 'lib', 'bin.js');
  const requireFromDsh = createRequire(entry);
  let packageEntry;
  try { packageEntry = requireFromDsh.resolve('@deepseek-ai/dsh-mcp-client'); } catch { fail(); }
  return import(pathToFileURL(packageEntry).href);
}

export async function apply(ctx, config = {}) {
  const McpClient = await loadOfficialMcpClient();
  return installProductAcpIdentity(ctx, config, { McpClient, env: process.env });
}
