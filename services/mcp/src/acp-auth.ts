import { createHmac, timingSafeEqual } from "node:crypto";

export type AcpAgentClaims = {
  v: 1;
  aud: "byq-product-mcp";
  root_run_id: string;
  runtime_boot_id: string;
  owner_principal: string;
  workspace_id: string;
  actor_principal: string;
  trace_id: string;
  session_id: string;
  dsh_run_id: string;
  native_root_session_id: string;
  native_agent_session_id: string;
  native_parent_session_id: string | null;
  origin: "root" | "subagent";
  depth: number;
  expires_at: number;
};

/** A separately signed, root-only scope for the opt-in ADR-0097 MCP surface. */
export type AcpJudgmentRootClaims = Omit<AcpAgentClaims,
  "aud" | "native_parent_session_id" | "origin" | "depth"> & {
  aud: "byq-product-acp-judgment-mcp";
  native_parent_session_id: null;
  origin: "root";
  depth: 0;
  task_id: string;
  call_identity: string;
};

export type McpBearerIdentity =
  | { kind: "legacy" }
  | { kind: "discovery" }
  | { kind: "acp-agent"; claims: AcpAgentClaims }
  | { kind: "acp-judgment-root"; claims: AcpJudgmentRootClaims };

const CLAIM_KEYS = [
  "actor_principal", "aud", "depth", "dsh_run_id", "expires_at", "native_agent_session_id",
  "native_parent_session_id", "native_root_session_id", "origin", "owner_principal", "root_run_id",
  "runtime_boot_id", "session_id", "trace_id", "v", "workspace_id",
] as const;
const ACP_JUDGMENT_CLAIM_KEYS = [
  "actor_principal", "aud", "call_identity", "depth", "dsh_run_id", "expires_at",
  "native_agent_session_id", "native_parent_session_id", "native_root_session_id", "origin",
  "owner_principal", "root_run_id", "runtime_boot_id", "session_id", "task_id", "trace_id",
  "v", "workspace_id",
] as const;
const PRINCIPAL = /^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$/;
const TRACE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const NATIVE_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ROOT_ID = /^[0-9a-f]{32}$/;
const JUDGMENT_TASK_ID = /^task_[0-9a-f]{32}$/;
const JUDGMENT_CALL_IDENTITY = /^byq-judgment-[0-9a-f]{32}$/;
const MAX_TOKEN_BYTES = 8192;
const MAX_PAYLOAD_BYTES = 6144;
export const ACP_AGENT_MAX_DEPTH = 1;
export const ACP_TOKEN_MAX_LIFETIME_MS = 24 * 60 * 60 * 1000;

function canonicalClaimsJson(value: Record<string, unknown>): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(value).sort()) sorted[key] = value[key];
  return JSON.stringify(sorted);
}

function validText(value: unknown, pattern: RegExp, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength
    && pattern.test(value);
}

function validateClaims(value: unknown, nowMs: number): AcpAgentClaims | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const claims = value as Record<string, unknown>;
  const actualKeys = Object.keys(claims).sort();
  if (actualKeys.length !== CLAIM_KEYS.length
    || actualKeys.some((key, index) => key !== CLAIM_KEYS[index])) return undefined;
  if (claims.v !== 1 || claims.aud !== "byq-product-mcp") return undefined;
  if (!validText(claims.root_run_id, ROOT_ID, 32)
    || !validText(claims.runtime_boot_id, ROOT_ID, 32)
    || !validText(claims.owner_principal, PRINCIPAL, 128)
    || !validText(claims.workspace_id, TRACE, 64)
    || !validText(claims.actor_principal, PRINCIPAL, 128)
    || !validText(claims.trace_id, TRACE, 64)
    || !validText(claims.session_id, TRACE, 64)
    || !validText(claims.dsh_run_id, TRACE, 64)
    || !validText(claims.native_root_session_id, NATIVE_SESSION_ID, 128)
    || !validText(claims.native_agent_session_id, NATIVE_SESSION_ID, 128)) return undefined;
  if (claims.native_parent_session_id !== null
    && !validText(claims.native_parent_session_id, NATIVE_SESSION_ID, 128)) return undefined;
  if (claims.origin !== "root" && claims.origin !== "subagent") return undefined;
  if (!Number.isSafeInteger(claims.depth) || (claims.depth as number) < 0
    || (claims.depth as number) > ACP_AGENT_MAX_DEPTH) return undefined;
  if (!Number.isSafeInteger(claims.expires_at)) return undefined;
  const expiresAt = claims.expires_at as number;
  if (!Number.isSafeInteger(nowMs) || expiresAt <= nowMs
    || expiresAt > nowMs + ACP_TOKEN_MAX_LIFETIME_MS) return undefined;
  if (claims.actor_principal !== `byq-product-agent-${claims.session_id}`) return undefined;

  if (claims.origin === "root") {
    if (claims.depth !== 0 || claims.native_parent_session_id !== null
      || claims.native_agent_session_id !== claims.native_root_session_id) return undefined;
  } else if (claims.depth !== 1 || claims.native_parent_session_id === null
    || claims.native_parent_session_id !== claims.native_root_session_id
    || claims.native_agent_session_id === claims.native_root_session_id) {
    return undefined;
  }
  return claims as AcpAgentClaims;
}

function decodeCanonicalBase64Url(value: string): Buffer | undefined {
  if (!value || !/^[A-Za-z0-9_-]+$/.test(value)) return undefined;
  try {
    const decoded = Buffer.from(value, "base64url");
    return decoded.toString("base64url") === value ? decoded : undefined;
  } catch {
    return undefined;
  }
}

export function isValidAcpSigningKey(value: unknown): value is string {
  return typeof value === "string" && Buffer.byteLength(value, "utf8") >= 32;
}

/** Keep the dedicated judgment signing key disjoint from any configured bearer/key. */
export function isAcpJudgmentSigningKeyDistinct(
  signingKey: unknown,
  otherCredentials: readonly unknown[],
): boolean {
  return isValidAcpSigningKey(signingKey)
    && otherCredentials.every(value => value === undefined || value === null || value === ""
      || (typeof value === "string" && value !== signingKey));
}

/** Require dedicated bearer credentials and reject any signing-key/bearer reuse without logging values. */
export function areAcpCredentialsSeparated(
  legacyToken: unknown,
  discoveryToken: unknown,
  backendProofToken: unknown,
  signingKey: unknown,
): boolean {
  const bearers = [legacyToken, discoveryToken, backendProofToken];
  return bearers.every(value => typeof value === "string" && value.length > 0)
    && new Set(bearers).size === bearers.length
    && typeof signingKey === "string"
    && bearers.every(value => value !== signingKey);
}

/** Verify the exact v1 token envelope and its bounded Product Agent scope. */
export function verifyAcpAgentBearer(
  token: string,
  signingKey: string | undefined,
  nowMs = Date.now(),
): AcpAgentClaims | undefined {
  if (!isValidAcpSigningKey(signingKey) || token.length > MAX_TOKEN_BYTES) return undefined;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "byq-acp-v1") return undefined;
  const payload = decodeCanonicalBase64Url(parts[1]);
  const signature = decodeCanonicalBase64Url(parts[2]);
  if (!payload || payload.byteLength > MAX_PAYLOAD_BYTES || !signature || signature.byteLength !== 32) return undefined;

  const expected = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(payload).digest();
  if (!timingSafeEqual(signature, expected)) return undefined;

  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payload));
  } catch {
    return undefined;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return undefined;
  const claimsObject = parsed as Record<string, unknown>;
  if (canonicalClaimsJson(claimsObject) !== payload.toString("utf8")) return undefined;
  const claims = validateClaims(claimsObject, nowMs);
  return claims;
}

/** Verify a distinct canonical bearer bound to one admitted judgment root/task/call. */
export function verifyAcpJudgmentRootBearer(
  token: string,
  signingKey: string | undefined,
  nowMs = Date.now(),
): AcpJudgmentRootClaims | undefined {
  if (!isValidAcpSigningKey(signingKey) || token.length > MAX_TOKEN_BYTES) return undefined;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "byq-acp-judgment-v1") return undefined;
  const payload = decodeCanonicalBase64Url(parts[1]);
  const signature = decodeCanonicalBase64Url(parts[2]);
  if (!payload || payload.byteLength > MAX_PAYLOAD_BYTES || !signature || signature.byteLength !== 32) return undefined;

  const expected = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(payload).digest();
  if (!timingSafeEqual(signature, expected)) return undefined;

  let parsed: unknown;
  try {
    parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payload));
  } catch {
    return undefined;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return undefined;
  const claims = parsed as Record<string, unknown>;
  const actualKeys = Object.keys(claims).sort();
  if (actualKeys.length !== ACP_JUDGMENT_CLAIM_KEYS.length
    || actualKeys.some((key, index) => key !== ACP_JUDGMENT_CLAIM_KEYS[index])
    || canonicalClaimsJson(claims) !== payload.toString("utf8")) return undefined;

  if (claims.v !== 1 || claims.aud !== "byq-product-acp-judgment-mcp"
    || claims.origin !== "root" || claims.depth !== 0 || claims.native_parent_session_id !== null) return undefined;
  if (!validText(claims.root_run_id, ROOT_ID, 32)
    || !validText(claims.runtime_boot_id, ROOT_ID, 32)
    || !validText(claims.owner_principal, PRINCIPAL, 128)
    || !validText(claims.workspace_id, TRACE, 64)
    || !validText(claims.actor_principal, PRINCIPAL, 128)
    || !validText(claims.trace_id, TRACE, 64)
    || !validText(claims.session_id, TRACE, 64)
    || !validText(claims.dsh_run_id, TRACE, 64)
    || !validText(claims.native_root_session_id, NATIVE_SESSION_ID, 128)
    || !validText(claims.native_agent_session_id, NATIVE_SESSION_ID, 128)
    || !validText(claims.task_id, JUDGMENT_TASK_ID, 37)
    || !validText(claims.call_identity, JUDGMENT_CALL_IDENTITY, 45)) return undefined;
  if (claims.native_agent_session_id !== claims.native_root_session_id
    || claims.actor_principal !== `byq-product-agent-${claims.session_id}`) return undefined;
  if (!Number.isSafeInteger(claims.expires_at)) return undefined;
  const expiresAt = claims.expires_at as number;
  if (!Number.isSafeInteger(nowMs) || expiresAt <= nowMs
    || expiresAt > nowMs + ACP_TOKEN_MAX_LIFETIME_MS) return undefined;
  return claims as AcpJudgmentRootClaims;
}

export function classifyAcpJudgmentBearer(
  authorization: string | undefined,
  signingKey: string | undefined,
  nowMs = Date.now(),
): Extract<McpBearerIdentity, { kind: "acp-judgment-root" }> | undefined {
  if (typeof authorization !== "string" || !authorization.startsWith("Bearer ")) return undefined;
  const token = authorization.slice("Bearer ".length);
  if (!token || /\s/.test(token)) return undefined;
  const claims = verifyAcpJudgmentRootBearer(token, signingKey, nowMs);
  return claims ? { kind: "acp-judgment-root", claims } : undefined;
}

export function classifyMcpBearer(
  authorization: string | undefined,
  options: {
    legacyToken?: string;
    discoveryToken?: string;
    signingKey?: string;
    nowMs?: number;
  },
): McpBearerIdentity | undefined {
  if (typeof authorization !== "string" || !authorization.startsWith("Bearer ")) return undefined;
  const token = authorization.slice("Bearer ".length);
  if (!token || /\s/.test(token)) return undefined;
  // Reserve the dedicated judgment envelope so a misconfigured legacy/static
  // bearer cannot make this cross-audience credential valid on Product MCP.
  if (token.startsWith("byq-acp-judgment-v1.")) return undefined;
  if (options.discoveryToken && token === options.discoveryToken) return { kind: "discovery" };
  if (options.legacyToken && token === options.legacyToken) return { kind: "legacy" };
  const claims = verifyAcpAgentBearer(token, options.signingKey, options.nowMs);
  return claims ? { kind: "acp-agent", claims } : undefined;
}
