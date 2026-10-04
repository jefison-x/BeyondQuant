import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import {
  ACP_AGENT_MAX_DEPTH,
  areAcpCredentialsSeparated,
  classifyMcpBearer,
  verifyAcpAgentBearer,
  type AcpAgentClaims,
} from "../src/acp-auth.js";

const now = 1_800_000_000_000;
const key = "synthetic-acp-signing-key-with-at-least-32-bytes";
assert.equal(areAcpCredentialsSeparated("legacy-bearer", "discovery-bearer", "backend-proof", key), true);
assert.equal(areAcpCredentialsSeparated("same", "same", "backend-proof", key), false,
  "legacy and discovery bearers must be distinct");
assert.equal(areAcpCredentialsSeparated("legacy", "discovery", "discovery", key), false,
  "Backend proof bearer must be distinct from discovery bearer");
assert.equal(areAcpCredentialsSeparated("proof", "discovery", "proof", key), false,
  "Backend proof bearer must be distinct from legacy bearer");
assert.equal(areAcpCredentialsSeparated("legacy", "discovery", "proof", "discovery"), false,
  "signing key cannot reuse any bearer credential");
assert.equal(areAcpCredentialsSeparated("legacy", "discovery", "proof", "proof"), false);
assert.equal(areAcpCredentialsSeparated(undefined, "discovery", "proof", key), false,
  "ACP discovery cannot start without all dedicated bearer credentials");
const root: AcpAgentClaims = {
  v: 1,
  aud: "byq-product-mcp",
  root_run_id: "a".repeat(32),
  runtime_boot_id: "b".repeat(32),
  owner_principal: "alice",
  workspace_id: "workspace_alice",
  actor_principal: "byq-product-agent-session-root",
  trace_id: "trace-root",
  session_id: "session-root",
  dsh_run_id: "generation-root",
  native_root_session_id: "00000000-0000-4000-8000-000000000001",
  native_agent_session_id: "00000000-0000-4000-8000-000000000001",
  native_parent_session_id: null,
  origin: "root",
  depth: 0,
  expires_at: now + 60_000,
};

function sign(payload: string, signingKey = key): string {
  const bytes = Buffer.from(payload, "utf8");
  const mac = createHmac("sha256", Buffer.from(signingKey, "utf8")).update(bytes).digest();
  return `byq-acp-v1.${bytes.toString("base64url")}.${mac.toString("base64url")}`;
}

function tokenFor(claims: AcpAgentClaims): string {
  const sorted: Record<string, unknown> = {};
  for (const field of Object.keys(claims).sort()) sorted[field] = (claims as unknown as Record<string, unknown>)[field];
  return sign(JSON.stringify(sorted));
}

const rootToken = tokenFor(root);
assert.deepEqual(verifyAcpAgentBearer(rootToken, key, now), root);

const childId = "00000000-0000-4000-8000-000000000002";
const child: AcpAgentClaims = {
  ...root,
  actor_principal: "byq-product-agent-session-child",
  session_id: "session-child",
  native_agent_session_id: childId,
  native_parent_session_id: root.native_root_session_id,
  origin: "subagent",
  depth: 1,
};
assert.deepEqual(verifyAcpAgentBearer(tokenFor(child), key, now), child);
assert.equal(ACP_AGENT_MAX_DEPTH, 1);

const [prefix, encodedClaims, encodedMac] = rootToken.split(".");
const badMac = `${prefix}.${encodedClaims}.${encodedMac.startsWith("A") ? "B" : "A"}${encodedMac.slice(1)}`;
assert.equal(verifyAcpAgentBearer(badMac, key, now), undefined);
assert.equal(verifyAcpAgentBearer(rootToken, undefined, now), undefined);
assert.equal(verifyAcpAgentBearer(rootToken, "short", now), undefined);
assert.equal(verifyAcpAgentBearer("byq-acp-v1..", key, now), undefined);
assert.equal(verifyAcpAgentBearer(rootToken + "=", key, now), undefined);

for (const claims of [
  { ...root, expires_at: now },
  { ...root, expires_at: now + 24 * 60 * 60 * 1000 + 1 },
  { ...root, expires_at: now + 1.5 },
  { ...root, aud: "other" },
  { ...root, extra: true },
  { ...root, root_run_id: "A".repeat(32) },
  { ...root, runtime_boot_id: "not-a-boot" },
  { ...root, owner_principal: "has control\nchar" },
  { ...root, actor_principal: "alice" },
  { ...root, workspace_id: "bad workspace" },
  { ...root, native_agent_session_id: "not-a-uuid" },
  { ...root, native_parent_session_id: "00000000-0000-4000-8000-000000000009" },
  { ...root, origin: "subagent", depth: 1 },
  { ...child, depth: 2 },
  { ...child, native_parent_session_id: null },
]) {
  assert.equal(verifyAcpAgentBearer(tokenFor(claims as AcpAgentClaims), key, now), undefined,
    "invalid signed claims must be rejected");
}

const unsortedPayload = JSON.stringify(root);
assert.equal(verifyAcpAgentBearer(sign(unsortedPayload), key, now), undefined,
  "valid HMAC over noncanonical key order must fail closed");
const duplicateKeyPayload = sign(
  `{"actor_principal":"byq-product-agent-session-root",${JSON.stringify(root).slice(1)}`,
);
assert.equal(verifyAcpAgentBearer(duplicateKeyPayload, key, now), undefined,
  "duplicate JSON keys must fail canonical byte comparison");

assert.deepEqual(classifyMcpBearer("Bearer discovery", {
  legacyToken: "legacy", discoveryToken: "discovery", signingKey: key, nowMs: now,
}), { kind: "discovery" });
assert.deepEqual(classifyMcpBearer("Bearer legacy", {
  legacyToken: "legacy", discoveryToken: "discovery", signingKey: key, nowMs: now,
}), { kind: "legacy" });
assert.equal(classifyMcpBearer("Bearer " + rootToken, {
  legacyToken: "legacy", discoveryToken: "discovery", signingKey: key, nowMs: now,
})?.kind, "acp-agent");
assert.equal(classifyMcpBearer("Bearer discovery", {
  legacyToken: "legacy", discoveryToken: "discovery", signingKey: key, nowMs: now,
})?.kind, "discovery");
assert.equal(classifyMcpBearer("Bearer invalid", {
  legacyToken: "legacy", discoveryToken: "discovery", signingKey: key, nowMs: now,
}), undefined);

console.log("ACP MCP auth: canonical HMAC, claim bounds, expiry, and carrier classification PASS");
