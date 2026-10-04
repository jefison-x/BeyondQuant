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

export type McpBearerIdentity =
  | { kind: "legacy" }
  | { kind: "discovery" }
  | { kind: "acp-agent"; claims: AcpAgentClaims };

const CLAIM_KEYS = [
  "actor_principal", "aud", "depth", "dsh_run_id", "expires_at", "native_agent_session_id",
  "native_parent_session_id", "native_root_session_id", "origin", "owner_principal", "root_run_id",
  "runtime_boot_id", "session_id", "trace_id", "v", "workspace_id",
] as const;
const PRINCIPAL = /^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$/;
const TRACE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
const NATIVE_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ROOT_ID = /^[0-9a-f]{32}$/;
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
  if (options.discoveryToken && token === options.discoveryToken) return { kind: "discovery" };
  if (options.legacyToken && token === options.legacyToken) return { kind: "legacy" };
  const claims = verifyAcpAgentBearer(token, options.signingKey, options.nowMs);
  return claims ? { kind: "acp-agent", claims } : undefined;
}
