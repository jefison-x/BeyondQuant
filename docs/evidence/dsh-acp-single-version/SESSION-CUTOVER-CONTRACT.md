# D3 — SDK → ACP session cutover contract (proposal)

Status: **Proposed, pending maintainer acceptance for the user-visible parts.**
Fail-closed classification below can proceed; the marked user-visible /
incompatible parts wait for explicit acceptance. No storage is migrated or
deleted by this document.

## Storage facts

- SDK `0.1.5rc1` sessions: `DSH_SESSION_ROOT=/var/lib/byq/dsh-sessions/dsh-0.1.5rc1`
  on the `byq_dsh_sessions` volume, in the SDK native format (opaque to ACP).
- ACP `rc.2` native sessions: `/var/lib/byq/dsh-sessions/dsh-v0.2.0-rc.2-acp/<workspace>/…`
  on the group product-session volume, in the official rc.2 native format
  (`sessions/<native-id>/session.v4.jsonl.zstd` + `session.lock`).
- The formats and volumes are different. The SDK store is **not** an ACP native
  format and MUST NOT be mounted as ACP native state.

## Prohibited in all cases

- Mounting or copying the SDK data directory as ACP native state.
- Replaying a pending or unknown input.
- Editing/deleting official native files or locks to force a resume.
- Automatically reconstructing the original child Agent instance (ADR-0102
  decides this path).

## Classification at cutover (fail-closed)

| Existing session state | Action | Acceptance |
| --- | --- | --- |
| BYQ session ended (terminal) | Reject new input; historical public transcript remains viewable | Within Accepted contracts; no change |
| Active root at cutover (running/pending) | Drain / block: no new root until exact Backend terminal closure + cleanup proof; never migrate mid-flight | Within Accepted ADR-0093/0096/0100; no change |
| Business outcome `unknown` / pending ingress | Block; reconcile by exact business ID / Backend readback before any continuation; do not classify as "not happened", do not replay | Within Accepted contracts; no change |
| Completed root, no pending/unknown, public transcript durable | Continue on ACP with a **fresh native session** built only from verified completed public history; BYQ public session ID and transcript stay stable; new root/new MCP identity; send only the new input | **Needs explicit acceptance** (see below) |
| SDK session with native-only state but no durable public completion (e.g., interrupted before public answer) | Treat as interrupted; require exact reconciliation; do not adopt native state | Within Accepted contracts |

## The point needing explicit acceptance

Whether a **pre-cutover completed SDK conversation** may be continued on ACP at
all, and on what user-visible basis:

- Proposed: the conversation continues (same public session ID, same durable
  public transcript, same history view); the runtime starts a fresh ACP native
  session and supplies only the verified completed public history, because the
  SDK native log cannot be adopted. This preserves the user-visible conversation
  but does **not** carry over any native-only model context.
- Alternative: require a new conversation for pre-cutover sessions (stricter,
  clearly user-visible).

This is a user-visible continuity decision. Work that does not depend on it —
fail-closed blocking of active/unknown sessions, ended-session rejection,
builder for the authoritative manifest, F6 and judgment wiring — continues.

## Required evidence before cutover

- Proof that no SDK session is mounted as ACP native state.
- A bounded, read-only inventory of pre-cutover sessions classified by the table
  above (counts by state, no PII), with the active/unknown set explicitly
  drained or blocked.
- Exact Backend closure/ACK for every active root before it is re-admitted.
- Independent Tester/Reviewer on the exact final head; exact-head CI; merge and
  deployment gates.
