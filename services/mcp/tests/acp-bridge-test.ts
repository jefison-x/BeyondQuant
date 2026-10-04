import assert from "node:assert/strict";
import {
  acpAgentRunRegistrationFetcher,
  addAcpObservationHeader,
  abortAcpToolIngressBeforeDispatch,
  bindAcpAgentRun,
  getAcpAgentBindingStatus,
  observeAcpDomainCall,
  observeAcpToolIngress,
  settleAcpToolIngress,
} from "../src/acp-bridge.js";
import type { AcpAgentClaims } from "../src/acp-auth.js";

const claims: AcpAgentClaims = {
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
  expires_at: Date.now() + 60_000,
};
const childClaims: AcpAgentClaims = {
  ...claims,
  native_agent_session_id: "00000000-0000-4000-8000-000000000002",
  native_parent_session_id: claims.native_root_session_id,
  origin: "subagent",
  depth: 1,
};
const proof = "synthetic-backend-proof-token";
const validRunId = "agent_run_" + "c".repeat(32);
const validParentRunId = "agent_run_" + "d".repeat(32);

const actionArgs = { task_id: "task_1", agent_run_id: "untrusted-run", strategy: { script: "synthetic" } };
let observeCalls = 0;
const observed = await observeAcpDomainCall("http://backend", proof, claims, "byq_strategy_validate", actionArgs,
  async (input, init) => {
    observeCalls += 1;
    assert.equal(String(input), "http://backend/internal/acp/domain-call-observe");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("authorization"), `Bearer ${proof}`);
    assert.equal(headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
    assert.equal(headers.get("x-byq-owner-principal"), claims.owner_principal);
    assert.equal(headers.get("x-byq-acp-native-agent-session-id"), null,
      "domain observation identity comes from its body, native registration headers are not reused");
    assert.equal(init?.method, "POST");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.equal(body.schema_version, "byq-acp-domain-call-observe.v1");
    assert.equal(body.root_run_id, claims.root_run_id);
    assert.equal(body.native_agent_session_id, claims.native_agent_session_id);
    assert.equal(body.action, "byq_strategy_validate");
    assert.deepEqual(body.arguments, actionArgs);
    const receipt = { schema_version: "byq-acp-domain-call-observation-receipt.v1",
      mcp_request_id: body.mcp_request_id, root_run_id: claims.root_run_id,
      sequence: 2, event_sha256: "e".repeat(64) };
    return Response.json(receipt);
  });
assert.ok(observed);
assert.equal(observeCalls, 1);

let ingressCalls = 0;
const ingressArgs = { task_id: "task_1", filter: { symbols: ["000001.SZ"] } };
const ingress = await observeAcpToolIngress("http://backend", proof, claims, "byq_market_daily", ingressArgs,
  async (input, init) => {
    ingressCalls += 1;
    assert.equal(String(input), "http://backend/internal/acp/tool-ingress-observe");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("authorization"), `Bearer ${proof}`);
    assert.equal(headers.get("x-byq-root-run-id"), claims.root_run_id);
    assert.equal(headers.get("x-byq-runtime-boot-id"), claims.runtime_boot_id);
    assert.equal(init?.method, "POST");
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.deepEqual(body, { schema_version: "byq-acp-tool-ingress-observe.v1",
      mcp_request_id: body.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: "byq_market_daily", arguments: ingressArgs });
    const receipt = { schema_version: "byq-acp-tool-ingress-receipt.v1",
      mcp_request_id: body.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: "byq_market_daily", agent_run_id: validRunId,
      sequence: 3, event_sha256: "a".repeat(64) };
    return Response.json(receipt);
  });
assert.ok(ingress);
assert.equal(ingressCalls, 1);
assert.equal(ingress.schema_version, "byq-acp-tool-ingress-receipt.v1");
assert.equal(ingress.native_agent_session_id, claims.native_agent_session_id);
let settlementCalls = 0;
const settledIngress = await settleAcpToolIngress("http://backend", proof, claims, ingress, "settled",
  async (input, init) => {
    settlementCalls += 1;
    assert.equal(String(input), "http://backend/internal/acp/tool-ingress-settle");
    assert.equal(new Headers(init?.headers).get("authorization"), `Bearer ${proof}`);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.deepEqual(body, { schema_version: "byq-acp-tool-ingress-settle.v1",
      mcp_request_id: ingress.mcp_request_id, root_run_id: ingress.root_run_id,
      runtime_boot_id: ingress.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: ingress.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: ingress.tool_name, sequence: ingress.sequence,
      event_sha256: ingress.event_sha256, outcome: "settled" });
    return Response.json({ schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
      mcp_request_id: ingress.mcp_request_id, root_run_id: ingress.root_run_id,
      runtime_boot_id: ingress.runtime_boot_id, native_agent_session_id: ingress.native_agent_session_id,
      tool_name: ingress.tool_name, sequence: ingress.sequence, event_sha256: ingress.event_sha256,
      outcome: "settled", settlement_sha256: "9".repeat(64) });
  });
assert.equal(settledIngress?.outcome, "settled");
assert.equal(settlementCalls, 1);
const unknownSettlement = await settleAcpToolIngress("http://backend", proof, claims, ingress, "unknown",
  async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.equal(body.outcome, "unknown");
    return Response.json({ schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
      mcp_request_id: ingress.mcp_request_id, root_run_id: ingress.root_run_id,
      runtime_boot_id: ingress.runtime_boot_id, native_agent_session_id: ingress.native_agent_session_id,
      tool_name: ingress.tool_name, sequence: ingress.sequence, event_sha256: ingress.event_sha256,
      outcome: "unknown", settlement_sha256: "8".repeat(64) });
  });
assert.equal(unknownSettlement?.outcome, "unknown");
const mismatchedSettlement = await settleAcpToolIngress("http://backend", proof, claims, ingress, "settled",
  async () => Response.json({ schema_version: "byq-acp-tool-ingress-settle-receipt.v1",
    mcp_request_id: ingress.mcp_request_id, root_run_id: ingress.root_run_id,
    runtime_boot_id: ingress.runtime_boot_id, native_agent_session_id: ingress.native_agent_session_id,
    tool_name: ingress.tool_name, sequence: ingress.sequence, event_sha256: ingress.event_sha256,
    outcome: "unknown", settlement_sha256: "8".repeat(64) }));
assert.equal(mismatchedSettlement, undefined, "changed or malformed settlement receipt fails closed");
let unknownSettleCalls = 0;
assert.equal(await settleAcpToolIngress("http://backend", proof, claims, ingress, "settled",
  async () => { unknownSettleCalls += 1; throw new Error("settlement outcome unknown"); }), undefined);
assert.equal(unknownSettleCalls, 1, "settlement transport unknown is never retried");

const bootstrapIngress = await observeAcpToolIngress("http://backend", proof, claims,
  "byq_agent_context", {}, async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return Response.json({ schema_version: "byq-acp-tool-ingress-receipt.v1",
      mcp_request_id: body.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: "byq_agent_context", agent_run_id: null,
      sequence: 1, event_sha256: "b".repeat(64) });
  });
assert.equal(bootstrapIngress?.agent_run_id, null,
  "only the bounded bootstrap tools may have a null pre-bind Backend AgentRun");
const rejectedUnboundIngress = await observeAcpToolIngress("http://backend", proof, claims,
  "byq_market_daily", {}, async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    return Response.json({ schema_version: "byq-acp-tool-ingress-receipt.v1",
      mcp_request_id: body.mcp_request_id, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, tool_name: "byq_market_daily", agent_run_id: null,
      sequence: 2, event_sha256: "c".repeat(64) });
  });
assert.equal(rejectedUnboundIngress, undefined,
  "non-bootstrap Backend-facing tools require a durable bound AgentRun receipt");
for (const invalidReceipt of [
  { schema_version: "byq-acp-tool-ingress-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, runtime_boot_id: claims.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id, native_agent_session_id: claims.native_agent_session_id,
    native_parent_session_id: null, origin: "root", depth: 0, tool_name: "byq_market_daily",
    agent_run_id: validRunId, sequence: 1, event_sha256: "a".repeat(64) },
  { schema_version: "byq-acp-tool-ingress-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, runtime_boot_id: claims.runtime_boot_id,
    native_root_session_id: claims.native_root_session_id, native_agent_session_id: claims.native_agent_session_id,
    native_parent_session_id: claims.native_parent_session_id, origin: claims.origin, depth: 1,
    tool_name: "byq_market_daily", agent_run_id: validRunId, sequence: 1, event_sha256: "a".repeat(64) },
]) {
  const rejected = await observeAcpToolIngress("http://backend", proof, claims, "byq_market_daily", {},
    async () => Response.json(invalidReceipt));
  assert.equal(rejected, undefined, "mismatched or malformed generic ingress receipt must fail closed");
}
let unknownIngressCalls = 0;
const unknownIngress = await observeAcpToolIngress("http://backend", proof, claims, "byq_market_daily", {},
  async () => { unknownIngressCalls += 1; throw new Error("transport outcome unknown"); });
assert.equal(unknownIngress, undefined);
assert.equal(unknownIngressCalls, 1, "an unknown generic ingress result is never automatically retried");
const lostObserveRequestId = "e".repeat(32);
const lostObserve = await observeAcpToolIngress("http://backend", proof, claims,
  "byq_market_daily", ingressArgs, async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.equal(body.mcp_request_id, lostObserveRequestId);
    throw new Error("observe response lost after request was sent");
  }, lostObserveRequestId);
assert.equal(lostObserve, undefined);
const abort = await abortAcpToolIngressBeforeDispatch("http://backend", proof, claims,
  "byq_market_daily", ingressArgs, lostObserveRequestId, async (input, init) => {
    assert.equal(String(input), "http://backend/internal/acp/tool-ingress-abort");
    assert.equal(new Headers(init?.headers).get("authorization"), `Bearer ${proof}`);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.equal(body.mcp_request_id, lostObserveRequestId);
    assert.deepEqual(body.arguments, ingressArgs);
    return Response.json({ schema_version: "byq-acp-tool-ingress-abort-receipt.v1",
      mcp_request_id: lostObserveRequestId, root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id,
      native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id,
      native_parent_session_id: null, origin: "root", depth: 0,
      tool_name: "byq_market_daily", arguments_sha256: "a".repeat(64),
      sequence: 3, event_sha256: "b".repeat(64),
      outcome: "aborted_before_dispatch", abort_sha256: "c".repeat(64) });
  });
assert.ok(abort);
assert.equal(abort.outcome, "aborted_before_dispatch");
const spoofedAbort = await abortAcpToolIngressBeforeDispatch("http://backend", proof, claims,
  "byq_market_daily", ingressArgs, lostObserveRequestId, async () => Response.json({
    ...abort, native_agent_session_id: childClaims.native_agent_session_id,
  }));
assert.equal(spoofedAbort, undefined, "abort acknowledgement must bind the exact native Agent");
const invalidAbort = await abortAcpToolIngressBeforeDispatch("http://backend", proof, claims,
  "byq_market_daily", ingressArgs, lostObserveRequestId, async () => Response.json({
    ...abort, sequence: 0, extra: "unexpected",
  }));
assert.equal(invalidAbort, undefined, "malformed abort receipt cannot release a pending ingress fence");
let lostAbortCalls = 0;
const lostAbort = await abortAcpToolIngressBeforeDispatch("http://backend", proof, claims,
  "byq_market_daily", ingressArgs, lostObserveRequestId, async () => {
    lostAbortCalls += 1;
    throw new Error("abort response lost");
  });
assert.equal(lostAbort, undefined);
assert.equal(lostAbortCalls, 1, "unknown abort outcome is never retried or treated as settled");

assert.equal(observed.schema_version, "byq-acp-domain-call-observation-receipt.v1");
assert.match(observed.mcp_request_id, /^[0-9a-f]{32}$/);
const receiptHeader = new Headers({ "x-byq-acp-observation-id": "untrusted" });
addAcpObservationHeader(receiptHeader, observed.mcp_request_id);
assert.equal(receiptHeader.get("x-byq-acp-observation-id"), observed.mcp_request_id);
addAcpObservationHeader(receiptHeader, undefined);
assert.equal(receiptHeader.get("x-byq-acp-observation-id"), null,
  "a missing private receipt removes any caller-supplied header");

for (const invalidReply of [
  { schema_version: "byq-acp-domain-call-observation-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, sequence: 1, event_sha256: "e".repeat(64) },
  { schema_version: "byq-acp-domain-call-observation-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, sequence: 0, event_sha256: "e".repeat(64) },
  { schema_version: "byq-acp-domain-call-observation-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, sequence: 1, event_sha256: "E".repeat(64) },
  { schema_version: "byq-acp-domain-call-observation-receipt.v1", mcp_request_id: "f".repeat(32),
    root_run_id: claims.root_run_id, sequence: 1, event_sha256: "e".repeat(64), extra: true },
]) {
  const rejected = await observeAcpDomainCall("http://backend", proof, claims, "byq_strategy_validate", actionArgs,
    async () => Response.json(invalidReply));
  assert.equal(rejected, undefined, "non-exact or mismatched durable observation receipts fail closed");
}
let unknownCalls = 0;
const unknown = await observeAcpDomainCall("http://backend", proof, claims, "byq_strategy_validate", actionArgs,
  async () => { unknownCalls += 1; throw new Error("transport outcome unknown"); });
assert.equal(unknown, undefined);
assert.equal(unknownCalls, 1, "an unknown observation request is never retried");

const bound = await bindAcpAgentRun("http://backend", proof, claims, validRunId, null,
  async (input, init) => {
    assert.equal(String(input), "http://backend/internal/acp/agent-bind");
    const headers = new Headers(init?.headers);
    assert.equal(headers.get("authorization"), `Bearer ${proof}`);
    assert.equal(headers.get("x-byq-root-run-id"), claims.root_run_id);
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.deepEqual(body, { schema_version: "byq-acp-agent-bind.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_root_session_id: claims.native_root_session_id,
      native_agent_session_id: claims.native_agent_session_id, native_parent_session_id: null,
      origin: "root", depth: 0, agent_run_id: validRunId, parent_run_id: null });
    return Response.json({ schema_version: "byq-acp-agent-bind-receipt.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      native_parent_session_id: null, agent_run_id: validRunId, parent_run_id: null,
      origin: "root", depth: 0, status: "bound", binding_sha256: "f".repeat(64) });
  });
assert.ok(bound);
assert.equal(bound.agent_run_id, validRunId);
assert.equal(await bindAcpAgentRun("http://backend", proof, claims, validRunId, validParentRunId,
  async () => { throw new Error("root registration must not accept a parent AgentRun"); }), undefined);
const childBound = await bindAcpAgentRun("http://backend", proof, childClaims, validRunId, validParentRunId,
  async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
    assert.equal(body.parent_run_id, validParentRunId);
    assert.equal(body.native_parent_session_id, claims.native_root_session_id);
    return Response.json({ schema_version: "byq-acp-agent-bind-receipt.v1", root_run_id: childClaims.root_run_id,
      runtime_boot_id: childClaims.runtime_boot_id, native_agent_session_id: childClaims.native_agent_session_id,
      native_parent_session_id: childClaims.native_parent_session_id, agent_run_id: validRunId,
      parent_run_id: validParentRunId, origin: "subagent", depth: 1, status: "bound", binding_sha256: "f".repeat(64) });
  });
assert.ok(childBound);

let registrationCalls = 0;
const baseFetcher = async (input: string | URL | Request, init?: RequestInit) => {
  registrationCalls += 1;
  const headers = new Headers(init?.headers);
  if (new URL(typeof input === "string" || input instanceof URL ? input : input.url).pathname === "/v1/market/daily") {
    assert.equal(headers.get("authorization"), "Bearer untouched");
    assert.equal(headers.get("x-byq-acp-native-agent-session-id"), null);
    return new Response("{}", { status: 200 });
  }
  assert.equal(headers.get("authorization"), `Bearer ${proof}`);
  assert.equal(headers.get("x-byq-owner-principal"), claims.owner_principal);
  assert.equal(headers.get("x-byq-root-run-id"), claims.root_run_id);
  assert.equal(headers.get("x-byq-acp-native-agent-session-id"), claims.native_agent_session_id);
  assert.equal(headers.get("x-byq-acp-native-parent-session-id"), "");
  assert.equal(headers.get("x-byq-acp-origin"), "root");
  assert.equal(headers.get("x-byq-acp-depth"), "0");
  return new Response("{}", { status: 200 });
};
const registrationFetcher = acpAgentRunRegistrationFetcher(claims, proof, baseFetcher);
await registrationFetcher("http://backend/v1/agents/runs", { method: "POST", headers: {
  authorization: "Bearer attacker", "x-byq-root-run-id": "f".repeat(32),
  "x-byq-acp-native-agent-session-id": "attacker-native-id",
} });
await registrationFetcher("http://backend/v1/agents/runs/registration-receipt", { method: "GET" });
await registrationFetcher("http://backend/v1/market/daily", { method: "GET", headers: { authorization: "Bearer untouched" } });
assert.equal(registrationCalls, 3);

let rootRegistrationAttempts = 0;
const exactRegistrationBody = JSON.stringify({ role_id: "quant_orchestrator", idempotency_key: "same-root-key" });
const rootRegistrationRetry = acpAgentRunRegistrationFetcher(claims, proof, async (_input, init) => {
  rootRegistrationAttempts += 1;
  assert.equal(init?.body, exactRegistrationBody, "root activation retries preserve the exact original key and body");
  assert.equal(new Headers(init?.headers).get("authorization"), `Bearer ${proof}`);
  if (rootRegistrationAttempts < 3) {
    return Response.json({ detail: "ACP root is not yet registered by Backend" }, { status: 409 });
  }
  return Response.json({ run: { run_id: validRunId, status: "active" } }, { status: 201 });
});
const rootRegistrationResponse = await rootRegistrationRetry("http://backend/v1/agents/runs", {
  method: "POST", body: exactRegistrationBody,
});
assert.equal(rootRegistrationResponse.status, 201);
assert.equal(rootRegistrationAttempts, 3,
  "only the exact pre-effect root-not-registered conflict receives a bounded retry");

let unrelatedConflictAttempts = 0;
const unrelatedConflictRetry = acpAgentRunRegistrationFetcher(claims, proof, async () => {
  unrelatedConflictAttempts += 1;
  return Response.json({ detail: "ACP parent lineage mismatch" }, { status: 409 });
});
const unrelatedConflictResponse = await unrelatedConflictRetry("http://backend/v1/agents/runs", {
  method: "POST", body: exactRegistrationBody,
});
assert.equal(unrelatedConflictResponse.status, 409);
assert.equal(unrelatedConflictAttempts, 1, "other conflicts and all unknown outcomes are never replayed");

const boundStatus = await getAcpAgentBindingStatus("http://backend", proof, claims,
  async (input, init) => {
    assert.match(String(input), /\/internal\/acp\/agent-binding\?root_run_id=[0-9a-f]{32}&native_agent_session_id=/);
    assert.equal(init?.method, "GET");
    return Response.json({ schema_version: "byq-acp-agent-binding-status.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      status: "bound", receipt: bound });
  });
assert.equal(boundStatus?.status, "bound");
const pendingStatus = await getAcpAgentBindingStatus("http://backend", proof, claims,
  async (_input, init) => {
    assert.equal(init?.method, "GET");
    return Response.json({ schema_version: "byq-acp-agent-binding-status.v1", root_run_id: claims.root_run_id,
      runtime_boot_id: claims.runtime_boot_id, native_agent_session_id: claims.native_agent_session_id,
      status: "pending" });
  });
assert.equal(pendingStatus?.status, "pending");

console.log("ACP Backend bridge: durable observe, exact receipts, identity forwarding, and no-retry behavior PASS");
