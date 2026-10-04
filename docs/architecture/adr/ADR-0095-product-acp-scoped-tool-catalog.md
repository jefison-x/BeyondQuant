# ADR-0095 — Product ACP research-judgment tool visibility and dispatch

- Status: **Accepted, amended (2026-10-04)**. The maintainer superseded the
  earlier official-filter choice and explicitly allowed model-visible tools
  with trusted role-aware pre-dispatch denial. Implementation and Product
  promotion gates remain separate.
- Date: 2026-10-04
- Scope: fixed official `dsh-v0.2.0-rc.2` Product ACP candidate and the
  ADR-0085 research-judgment execution boundary.
- Current authority: ADR-0088 and the Clean Break baseline; builds on
  ADR-0093 and ADR-0094. ADR-0085 is historical context. This decision does
  not advance `STATUS.md`.

## Observed conflict

The fixed official DSH `tools.restrict` contract filters inherited global
registrations and explicitly leaves an Agent's own scoped registrations
visible. ADR-0094's Product identity plugin mounts an official MCP client in
each Agent scope to give root and child distinct signed identities. The MCP
client registers the complete BYQ tool list in that scope. The existing
`tool-subagent.toolFilter` uses `tools.restrict`, so it cannot hide those
registrations.

A keyless fixed-source probe created the actual `research-judgment-turn`
child through official `tool-subagent` and `spawn` components with its exact
five-tool allowlist and the Product identity plugin. The child model catalog
contained all 13 fixture tools, including strategy validation/approval,
backtest execute/cancel, ML approval/training, and Agent authorization. The
five-tool assertion failed. A role-aware pre-execute guard could deny an
unqualified call if a trusted role identity were available; the current
Product identity plugin checks Agent registration, not this role's tool
allowlist. This ADR supersedes ADR-0085's historical minimum-catalog rule for
Product ACP by allowing visibility with proven pre-dispatch denial. The ACP
profile also currently sets this role's `maxDepth: 0`; the official provider
defines zero as forbidding the delegation itself. The probe used depth one
only to examine the intended child, so it is evidence of the catalog problem,
not proof that the shipped profile can launch the role.

The model-visible catalog is now permitted by contract, but the trusted
execution guard is absent and the delegation depth is wrong. Current ACP
candidate promotion is **blocked**. The retained `0.1.5rc1` runtime remains
the exact rollback and deployable baseline.

## Decision

For the Product ACP research-judgment child, extra Product MCP tool names and
schemas may be visible to the model. Visibility confers no execution
authority. Retain ADR-0094's per-Agent signed MCP identity and the exact five
bounded read-only capabilities as the child's model-executable allowlist. At
the Product MCP boundary, every `tools/call` must verify a signed trusted
role/capability claim and reject a judgment child call outside those five
tools **before** its handler, Backend ingress or external side effect. This
includes direct MCP calls that bypass DSH's model-facing dispatcher. DSH's
pre-execute/delegation guard must separately deny forbidden local tools and
grandchild creation. Record the exact Agent/root/tool denial. Prompt text,
persona, tool arguments, display labels and a plain child session ID are
insufficient role proof. The role claim must derive from documented DSH
child-creation facts, bind to signed Agent lineage and BYQ
root/boot/generation, and remain correct across resume, siblings and users.
Before a child obtains an executable per-Agent MCP client, this claim must
be established; otherwise it may receive discovery only and all calls fail
closed.

The five allowed reads also require a bound native AgentRun in Backend.
`byq_agent_run_start` is **not** a sixth model-executable capability. A
trusted, non-model control path must register the exact judgment child and
parent AgentRun under a dedicated least-privilege judgment role before those
reads are admitted. The current public role catalogue has no such dedicated
role; neither the model nor an untrusted token may select a broader existing
role. Missing or ambiguous registration proof fails closed.

The fixed `dsh-v0.2.0-rc.2` source pin remains unchanged. No trustworthy
role-to-Agent claim or qualified pre-dispatch guard has yet been demonstrated
in this branch, so this ADR does not qualify the candidate for default
Product use. It does not authorize a DSH fork or a second Agent harness.

The evaluated alternatives were:

1. **Selected: catalog visibility with role-aware pre-dispatch denial.** This
   supersedes ADR-0085's historical model-visible minimum for Product ACP. The
   guard and its trusted role proof are mandatory, not optional follow-up.
2. **Superseded preference: official scoped catalog filtering.** An official
   filter may be evaluated later as defense in depth, but this candidate no
   longer waits for one solely to hide extra tool schemas. A new release still
   requires a separate pin and qualification decision.
3. **Not selected: BYQ MCP `tools/list` catalog gate.** Hiding forbidden tools
   at discovery is no longer required. A trusted role claim and denial of
   forbidden `tools/call` before any handler remain required; the present
   identity plugin does not provide that role authorization.

The fixed-source depth rule was checked separately: `maxDepth: 0` rejects a
first child; `maxDepth: 1` permits depth one and rejects depth two. The ACP
candidate profile remains at `0` until the role-aware dispatch guard is
qualified. Then set the role to `1` and verify through the actual delegation
path that the parent can start one child and that child cannot start a
grandchild.

No option permits a DSH fork, a second Agent harness, direct business DB
access, Product Engineering privileges, or automatic replay of unknown calls.

## Evidence required before this candidate can be promoted

- Fixed official source and profile identity, exact trusted child creation
  metadata, model-visible tool schemas, and pre-dispatch denial transcript.
- Exact five-tool **model-executable** judgment allowlist plus trusted
  non-model AgentRun registration and parent binding. Attempted write,
  approval, execution, routing, identity, job and out-of-role read calls must
  be denied before MCP handler/Backend/side effects, including through direct
  MCP use, resume and late requests. Prove one child and no grandchild.
- Signed native Agent lineage and dedicated judgment role through MCP and
  Backend, two-user isolation, late request fence and terminal ACK under the
  chosen dispatch mechanism.
- Independent Tester and Reviewer on the actual diff, followed by Root
  qualification and the original PR/release/deployment gates.

Until the trusted role claim and dispatch guard are implemented and proved,
keep the affected Product promotion on hold. The accepted visibility change
alone does not turn the fixed-source probe from a qualification FAIL into a
runtime PASS. The retained `0.1.5rc1` image/configuration remain the exact
rollback path.
