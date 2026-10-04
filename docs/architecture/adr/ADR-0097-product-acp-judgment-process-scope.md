# ADR-0097 — Proposed Product ACP judgment process scope

- Status: **Proposed — maintainer decision required** (2026-10-04).
- Scope: fixed official `dsh-v0.2.0-rc.2` Product ACP research-judgment
  invocation only. This does not change the normal Product conversation root.
- Would amend: Accepted ADR-0095's requirement that the judgment role claim
  come from an official DSH child-creation role field. ADR-0088 and the Clean
  Break baseline remain authoritative; ADR-0085 remains historical context.
- No implementation, version change, Product Phase change, PR, merge or
  deployment is authorized by this proposal alone.

## Evidence and problem

ADR-0095 permits the judgment child's model to see the Product MCP catalog
but requires every forbidden call to be denied before the Product MCP handler
or Backend ingress. The current BYQ ACP identity plugin signs root, native
Agent, parent, origin and depth, but no judgment role. It mounts each Agent's
executable MCP client at official `agent/created`.

In the pinned official source, a child's creation header contains parent,
origin and depth, but no invoking `tool-subagent` instance or trusted role
(`packages/subagent/subagent/src/child-agent.ts:139`). The one-shot
`subagent/descriptor` contains provider and a model-supplied description,
not the invoking tool identity (`descriptor.ts:50`). Its append occurs on
`agent/pre-step`, after the child's creation hook
(`subagent-in-process-driver/src/index.ts:80`). The `subagent/start` event
contains child ID, provider and locality, but no invoking tool identity
(`subagent/src/types.ts:75`); it is emitted after publication. None of these
observations proves that the child was created by the configured
`byq_research_judgment_turn` tool before BYQ issues an executable MCP token.
The model's description/persona and a guessed child ID remain unsuitable
authority. A narrow keyless probe of the exact hook ordering and every
alternative trusted field remains a qualification step; this source audit
does not claim that no other official extension exists.

BYQ already has a trusted, authenticated
`/internal/runtime/research-judgment/{task_id}/run` entry that binds one task
and call identity, asks Backend to admit the stage, and launches a dedicated
DSH process/composition. The retained `0.1.5rc1` implementation is evidence
of this ownership boundary, not an ACP implementation or acceptance test.
That runner operates outside a RuntimeAdapter conversation session. Its
`adapter_invocation_id` is temporary and explicitly not a persisted
RuntimeGeneration (`research_judgment_api.py:86-91,123-132`); its research
stage result receipt is not a BYQ root terminal ACK. Neither root lifecycle
nor terminal settlement is inherited from the existing entry.

## Proposed decision

Use the **dedicated judgment process** as the trusted capability boundary
instead of inferring a role from a generic child. The Runtime Adapter may
launch that process only after the exact Backend research-judgment admission;
the normal Product conversation process cannot select this mode. Reuse the
same official DSH ACP transport and Agent machinery, with a separately
attested dedicated composition; do not fork DSH or create another generic
Agent harness.

The Adapter supplies a process-scoped, non-model-controlled judgment marker
bound to the exact task, call, owner/workspace, BYQ root, boot and generation.
The BYQ identity plugin signs this scope into each root/child Agent token
alongside the existing native lineage. Product MCP verifies the signed scope
on **every** `tools/call` before handler or Backend ingress, including direct
MCP requests outside DSH's dispatcher:

- The dedicated root may use the one configured local judgment delegation
  tool but no Product MCP business tool.
- Only its depth-one child may execute the five bounded judgment reads.
  Other model-visible Product MCP tools return a denied result without
  invoking their handler, Backend ingress or an external side effect.
- Depth greater than one, a missing/mismatched process scope, wrong parent,
  stale root/boot/generation, or ambiguous role proof fails closed. DSH's
  pre-execute guard also denies non-MCP local tools and enforces depth one.

Process scope represents a judgment role only if the attested dedicated
composition has **exactly one child-creation route**, the configured judgment
delegation tool. Remove or deny `fork`, `control`, other subagent providers,
and any alternate child-creation path before issuing child MCP authority.
Audit the actual loaded official plugin/tool graph and test each reachable
route. If another route can create a depth-one child, process scope alone is
insufficient and that child's five-read authority must fail closed.

The ACP judgment path must create and persist a **distinct BYQ Backend root**
for the exact admitted task/call before launching the process or issuing its
MCP identity. Bind root, owner/workspace, call identity, current Adapter
boot/authority and a durable generation to the dedicated invocation; the
temporary `adapter_invocation_id` cannot stand in for that binding. Register
root and child native Agents under this root before any business read. Commit
the research stage result through the existing exact-call idempotency path,
then close this root with its complete ingress/unknown-outcome evidence and
obtain the exact Backend terminal ACK before reporting the turn settled or
releasing another invocation. A lost response to result commit or root close
remains unknown and must be reconciled by exact receipt; it cannot trigger a
second model or business call. The implementation must define and test the
durable state transitions across admission, root creation, registration,
result commit, close and ACK, including crash windows. This is new work,
not a capability of the retained SDK runner.

The five reads require native AgentRun registration. Product MCP/Backend must
provide a trusted, non-model registration path for the exact root and child,
with a dedicated least-privilege judgment role and exact parent binding.
`byq_agent_run_start` must not become a sixth model-executable tool, and the
model must not choose the role. Unknown registration or business outcome
retains the existing fail-closed reconciliation and terminal ACK rules.

The dedicated composition must disable shell, filesystem, job, unrestricted
delegation and other non-MCP execution surfaces. It must set the judgment
tool's `maxDepth: 1` only after the MCP dispatch guard and registration path
are qualified. A separate process is a task-specific DSH invocation under
the existing Adapter, not a second Agent harness or Engineering grant.

## Rejected and fallback paths

- Do not sign a judgment role from a model-written description, persona text,
  tool arguments, native session ID or parent/depth alone. Other depth-one
  Product delegates may need different capabilities.
- Do not rely only on DSH `tools/pre-execute`; a still-valid Agent token can
  call Product MCP directly, so MCP must enforce the same scope before each
  handler.
- If the dedicated process cannot be proven exclusive to the trusted
  judgment entry, or cannot register the child without model authority,
  retain ADR-0095's fail-closed block. The earlier official scoped-filter
  route remains an alternative future ADR decision, not an automatic version
  change.

## Qualification before accepting implementation

1. Prove the exact official hook order and absence/presence of a usable
   trusted tool-instance role field at child creation, with fixed-source
   keyless evidence. Prove that the dedicated mode cannot be selected through
   Gateway/Product input or by a normal Product DSH Agent; inspect all loaded
   child-creation routes and prove only the judgment tool remains executable.
2. In the actual dedicated ACP composition, inspect root and child catalogs,
   create exactly one depth-one judgment child, and reject a grandchild.
   The model-visible extra schemas are permitted; execution is not.
3. Exercise each allowed read and representative forbidden write, approval,
   execution, routing, identity, job and out-of-role read calls through both
   DSH and direct MCP using signed root/child tokens. Denials must precede
   handler and Backend ingress, with exact audit evidence.
4. Prove persisted, exact-call Backend root creation, trusted root/child
   AgentRun registration and correct parent binding, including crash windows
   between admission, result commit, root close and ACK. Prove two-user
   isolation, stale/late token rejection, process restart and unknown-result
   behavior. Obtain exact Backend terminal ACK; do not replay an interrupted
   model or business call.
5. Run independent Tester and Reviewer on the actual diff, then Root
   qualification and the original image, Product API/browser, PR and release
   gates. Preserve the exact `0.1.5rc1` image/configuration rollback path.

Until this amendment is accepted and these proofs pass, leave the affected
ACP judgment execution and default promotion blocked. Local source audits
and keyless probes may continue without changing the fixed candidate pin.
