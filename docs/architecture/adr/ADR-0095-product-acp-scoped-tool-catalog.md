# ADR-0095 — Product ACP scoped MCP tool catalog

- Status: **Accepted (2026-10-04)**. The maintainer selected supported official
  DSH scoped filtering in the development chat. No new DSH version, candidate
  implementation, PR, merge or deployment is authorized by this ADR alone.
- Date: 2026-10-04
- Scope: fixed official `dsh-v0.2.0-rc.2` Product ACP candidate and the
  Accepted ADR-0085 research-judgment minimum tool surface.
- Depends on: ADR-0085, ADR-0093 and ADR-0094. This proposal does not alter
  their Accepted status or advance `STATUS.md`.

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
allowlist. Accepted ADR-0085 requires these capabilities to be
absent from this role's model catalog. The ACP profile also currently sets
this role's `maxDepth: 0`; the official provider defines zero as forbidding
the delegation itself. The probe used depth one only to examine the intended
child, so it is evidence of the catalog problem, not proof that the shipped
profile can launch the role.

This is a Product capability contract conflict, not a missing implementation
assertion. Current ACP candidate promotion is **blocked**. The retained
`0.1.5rc1` runtime remains the exact rollback and deployable baseline.

## Decision

Preserve ADR-0085's exact model-visible minimum tool catalog and ADR-0094's
per-Agent signed MCP identity. Use only a documented official DSH mechanism
that filters an Agent's own scoped MCP registrations before model schema
projection and also rejects disallowed execution. The fixed official
`dsh-v0.2.0-rc.2` candidate has not demonstrated this mechanism and remains
blocked from default Product promotion. Do not silently advance its source
pin. When an official release documents the needed behavior, make a separate
candidate decision, pin and audit its exact source, and repeat the affected
qualification before promotion.

The evaluated alternatives were:

1. **Selected: supported DSH scoped filtering.** Prove the exact judgment
   child catalog and one-level depth with a pinned-source keyless probe, then
   repeat affected BYQ qualification.
2. **Not selected: BYQ MCP catalog gate.** This would extend the
   ADR-0094 signed per-Agent claim with an authenticated role/capability
   identity derived from a documented DSH child creation field, not model
   text, tool arguments, a prompt label or a guessed session ID. BYQ MCP would
   return only the role's exact tools from `tools/list`, and deny every other
   `tools/call` before Backend forwarding. Prove the claim is available before
   MCP discovery and cannot be confused across root, siblings, resumes or
   users. No such official role proof has yet been identified; this option is
   **not authorized** by this decision.
3. **Rejected: amend ADR-0085 to allow catalog exposure with pre-dispatch
   denial.** This would weaken an Accepted minimum exposure boundary and change
   model-visible behavior. It requires a separate maintainer decision and
   cannot be inferred from acceptance of ADR-0094. Even after acceptance,
   a new trusted role-aware dispatch guard would need implementation and
   qualification; the current Product identity guard is insufficient.

The role's `maxDepth` must be corrected and tested under any choice: the
parent may start this one child, and that child may not start a grandchild.
No option permits a DSH fork, a second Agent harness, direct business DB
access, Product Engineering privileges, or automatic replay of unknown calls.

## Evidence required for a new candidate

- Fixed official source and profile identity, exact child creation metadata,
  model-visible tool schemas, and pre-execute denial transcript.
- Exact five-tool judgment catalog, no extra write/approval/execute/routing
  tools, no grandchild delegation, and root/other-delegate catalog checks.
- Signed native Agent lineage through MCP and Backend, two-user isolation,
  late request fence and terminal ACK under the chosen catalog mechanism.
- Independent Tester and Reviewer on the actual diff, followed by Root
  qualification and the original PR/release/deployment gates.

Until an official mechanism is pinned and proved, keep the affected
implementation and promotion on hold. Local evidence collection and
fail-closed fixes that do not weaken the catalog boundary may continue.
