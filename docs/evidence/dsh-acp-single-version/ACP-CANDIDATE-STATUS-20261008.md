# ACP candidate status — precise PASS / FAIL / NOT_RUN (updated 2026-10-08)

Isolated `byq-acpf6` stack. Production (`beyondquant-*`) untouched. No push/PR/merge/deploy/default/
release/tag/Phase. **Single-version default remains the SDK rollback** (no promotion).

This is the current-state view; it is internally consistent (no append-only contradictions). Historical
digests and failure records live in their owning evidence docs, referenced inline.

## Candidate images — current running values (read-only `docker inspect`, 2026-10-08)
| service | current image id | notes |
|---|---|---|
| runtime-adapter | `sha256:c324ef803409c0a38e9c34b68bcc847942614eb1e907d13ac2b0a30952b1b0b9` | diagnostic-hardened rebuild (`JUDGMENT-TURN-DIAGNOSTIC-HARDENING-20261008`); prior `sha256:3ac2410b…` kept as tag `byq-acpf6-runtime-adapter:pre-diag-20261008` |
| acp-product-runner (primary + chain) | `sha256:3da73530d1ec4caf720c9d27caefbec228b2dc405b3570ba9f12f001f6cd58b2` | count-only validator + persona fix |
| backend | `sha256:9d3bb3c863ee7e8597f5868d5f4a56a9fc6175dcdd69a69e21148a2b3b6987e6` | ADR-0107 consumer + ADR-0108 plan route |
| gateway | `sha256:b40114c4aa71f0904726a74873ef672836ecf93ff1ac817cb31d007523e0b043` | public session status projection + ADR-0108 plan route |
| judgment-consumer | `sha256:ca221acd5c952c4625ad5b73e9f0a332f8d578cf450e7ed9d21cb7c01dbaf883` | built image; no running container |
| acp-judgment-runner | `sha256:6592810009079dff51f42bf87f56076e84ae665eaf5a2f722b1b57ccb4b7666c` | unchanged |
| mcp-acp-judgment | `sha256:d255bad17617a382f1bde40bcaeff800bbe2a39574e9dc1372adcad4907f4b2c` | unchanged |
| mcp | `sha256:3e5d6671a28594d73a646536be9f50282d8ea89a994ddd3c551069edfa427392` | unchanged |
| frontend | `sha256:2a6ae157c72e6307a642f9e7149f6b222fe35674459c29b08a66e67e16885d00` | public UI |

Per-evidence tested digests are authoritative where they differ from the current table (each evidence
doc records the digest it ran against).

## PASS (current, all bounded)
- **Ordinary ACP Product path (ADR-0096/0100)** — normal answer, second-turn native root reuse,
  soft stop/continue, hard-cancel containment, end rejection, two-group isolation, forged/old-root
  ingress denial, read-only tool ingress, bounded delegation. `docs/evidence/dsh-acp-upgrade/PRODUCT-INTEGRATION-20261005.md`.
- **Public session status projection** — Gateway-only browser read (active→cancelled; banner).
  `PUBLIC-SESSION-STATUS-PROJECTION-20261008` (tested gateway `839e964a…`).
- **Ordinary count-only real turn + 17th keyless boundary** — real `byq_research_get` guard
  observation; 16 admitted, 17th blocked `BYQ_CONTINUATION_TOOL_LIMIT`. `ORDINARY-COUNT-ONLY-CANDIDATE-20261008`.
- **ADR-0106 ordinary provider budget** — closed ordinary ACP budget profile. `ADR-0106-ORDINARY-BUDGET-20261008`.
- **Dedicated judgment internal chain** — committed result + exact terminal ACK; `outcome_unknown`
  containment. `JUDGMENT-ACP-REAL-ACCEPTANCE-20261008`.
- **ADR-0107 judgment consumer** — atomic once claim/dispatch-intent, unknown-safe reconcile-only,
  real service auth, business gate; real trigger + continuous service. `JUDGMENT-CONSUMER-ACCEPTANCE-20261008`.
- **Judgment live-turn abort + restart recovery** — client-disconnect abort settles
  `outcome_unknown`/`interrupted` with exact terminal ACK; restart settles without false ACK.
  `JUDGMENT-LIVE-QUALIFICATION-20261006`.
- **ADR-0108 foreground plan creation** — Product `POST/GET execution-plan`, replay, wrong-binding
  404, forged-body 422, cross-user 404 (browser). `ADR0108-PLAN-ACCEPTANCE-20261008`.
- **Formal Gateway Agent → MCP `byq_research_task_create` → Product plan → ADR-0107 consumer →
  dedicated judgment — real PASS (bounded)**, durable user `admin`, `no_durable_progress`/
  `proposal=null` (bounded closure, not a plan advance). `ACP-SINGLE-VERSION-REAL-ACCEPTANCE-20261008`.
- **Judgment turn-diagnostic hardening** — bounded Root PASS for three safety fixes (first Reviewer
  FAIL retained). `JUDGMENT-TURN-DIAGNOSTIC-HARDENING-20261008`.
- **Child tool-count (rc.2 keyless)** — bounded PASS: real child `0b44497d…`, `origin:subagent`/
  `parentSession`=root, 15 child `exec.agent` pre-execute events, 15 real local MCP calls,
  process-global root-inclusive 16-tool ceiling with the 16th child call blocked.
  `child-tool-count-next-20261008/RESULT.md` (+ independent Tester/Reviewer).
- **Root ownership + exact terminal ACK + signed cleanup** — real: `agent_runtime_turns`
  owner/workspace/session/root binding, exact `terminal_event_sha256`, proven runner cleanup
  (`code:0`). Sources: `ACP-SINGLE-VERSION-REAL-ACCEPTANCE-20261008`, `JUDGMENT-CONSUMER-ACCEPTANCE-20261008`.

## FAIL / unknown (real, preserved — not converted to PASS)
- **`acpchain-user` workspace fenced** — three pre-existing `authority_revoked_unconfirmed` Agent
  turns; `can_start:false`, so that workspace cannot start a new real Agent turn. Recorded, not
  force-closed/ACKed. `ACP-SINGLE-VERSION-REAL-ACCEPTANCE-20261008`.
- **Product `POST /research/tasks` creates no bound conversation** — the Product task-create route
  still has no conversation binding (plan-create on such a task → 422). Real gap; bypassed in this
  run via the Agent entry, but the Product route gap remains. `ADR0108-PLAN-ACCEPTANCE-20261008`.
- **byq-acpcand 13 unsettled judgment roots** — no runner cleanup receipt; operator cannot safely
  close without a fence proof. Preserved. `F6-RECONCILIATION-20261006`; decision point ADR-0104 (Proposed).
- **Historical, owned by their docs (do not re-read as current):** ADR-0106 A/B/C provider-budget
  failures; background continuation #1–#9; the public-projection original hot-patch note
  (`ORDINARY-COUNT-ONLY-CANDIDATE-20261008`, `adr0106-ordinary-real-flow`).

## NOT_RUN (current)
- **F6 ACP continuation end-to-end (ADR-0103/ADR-0105)** — qualification gate returns
  `qualified:true`; ADR-0105 (OpenCode Go route) is Accepted. The **normal already-ACK/cleanup**
  background-result → new-root branch is independently verifiable and is not blocked by any draft.
  Only the **lost-old-process-without-cleanup-receipt** branch is gated by the **Proposed** ADR-0104
  / Draft A. Manifest capability `f6_continuation.evidence = NOT_RUN` (not yet evidenced end-to-end).
  The historical `JUDGMENT-LIVE-QUALIFICATION-20261006` `NOT_RUN` is a date-stamped snapshot, not the
  current state.
- **Interrupted-business continuation via new child (ADR-0102, Accepted)** — the contract is fixed:
  rc.2 does not restore the original child; use parent-session recovery → verify the existing
  Job/idempotency/result → create a **new** child with new identities; unknown stays unknown; name
  `中断后业务接续（新子Agent）`. This is **not** an open ADR decision. What is missing is the
  ADR-0102 required business-continuation evidence (`interrupted_business_continuation_new_child.evidence
  = NOT_RUN`). The raw `session/resume` child refusal (`packages/acp/acp/lib/index.js:1216`) is the
  accepted premise, not a gap.
- **Single-version default switch** — manifest `config/dsh/acp/authoritative.json` exists; consumers
  not wired; default remains SDK. `SINGLE-VERSION-MANIFEST`.
- **Storage cutover** (SDK session store), **release-chain ACP coverage**, **hosted CI / release /
  deployment gates**.
- **Live/injection scenarios** — truly delayed old-root request while a new root is active; exact
  ACK/cleanup loss blocking the next turn; in-flight process fault / connection loss / unknown
  result; concurrent two-user real-model; reboot recovery; ADR-0100 live permission/old-process
  cleanup. `AUDIT-AND-GAPS`.
- **Two-user file isolation** — the candidate mounts two workspace paths as the same volume (alias);
  this is **not** a two-user file-isolation PASS. `ACP-SINGLE-VERSION-REAL-ACCEPTANCE-20261008`.
- **Real signed Product delegate-child identity / generic child Product acceptance** — only keyless
  synthetic per-Agent identity exists (ADR-0094 probes). Not real-signed.

## Boundaries
Draft A (unknown recovery) paused. Recovery responsibility per maintainer convergence (generic Agent
cancel/context/sub-Agent recovery = DSH; runner/container lifecycle = container management; BYQ keeps
attribution/authorization/idempotency/unknown-reconciliation/exact ACK). No push/PR/merge/deploy/
default/Phase/tag; model-connection failure stops without retry; old unknowns not replayed.

---

## Remaining-gates matrix (proven / unproven / reason / necessary next step)
| Gate | Proven? | Reason / current evidence | Necessary next step (minimal) |
|---|---|---|---|
| Root ownership (owner/workspace/session/root bind) | **Proven** | Real `agent_runtime_turns` + status receipts | no further bounded evidence for this row; merge is a separate human gate |
| Exact terminal ACK + signed cleanup | **Proven** | Real terminal hashes + `cleanup:proven code:0` | no further bounded evidence for this row; merge is a separate human gate |
| Ordinary ACP Product path | **Proven (bounded)** | PRODUCT-INTEGRATION-20261005; count-only | no further bounded evidence for this row; merge is a separate human gate |
| Dedicated judgment lifecycle (result / unknown / cancel / disconnect / restart) | **Proven (bounded)** | JUDGMENT-ACP-REAL-ACCEPTANCE; JUDGMENT-LIVE-QUALIFICATION | no further bounded evidence for this row; merge is a separate human gate |
| Judgment dispatch consumer (ADR-0107) | **Proven** | single-target + continuous service | no further bounded evidence for this row; merge is a separate human gate |
| Foreground plan creation (ADR-0108) | **Proven (bounded)** | Product POST/GET + browser | no further bounded evidence for this row; merge is a separate human gate |
| Formal Agent→plan→judgment real chain | **Proven (bounded)** | ACP-SINGLE-VERSION-REAL-ACCEPTANCE (`no_durable_progress` closure) | no further bounded evidence for this row; merge is a separate human gate |
| Child tool-count (keyless, rc.2) | **Proven (bounded)** | child-tool-count-next (real child id/parent/pre-execute/MCP) | no further bounded evidence for this row; merge is a separate human gate |
| Product **signed child identity** (real, signed MCP) | **Unproven** | only keyless synthetic per-Agent identity (ADR-0094) | one real Product delegate turn with the identity plugin enabled + root/child attribution evidence (see the step block below) |
| Root **late-call** handling (old-root request while new root active) | **Unproven** | NOT_RUN live/injection (AUDIT-AND-GAPS) | one real delayed-old-root injection against the candidate |
| ACK/cleanup-loss blocking next turn | **Unproven** | NOT_RUN live/injection | one real fault-injection for ACK/cleanup loss |
| In-flight fault / connection loss / unknown result | **Partly proven** | judgment disconnect/restart proven; ordinary product in-flight NOT_RUN | bounded real fault-injection for the ordinary path |
| Concurrent two-user real-model / reboot recovery | **Unproven** | NOT_RUN | bounded real two-user + reboot scenario |
| Two-user **file isolation** | **Unproven** | same-volume mount alias | explicit isolation contract/decision before any claim (no casual volume change) |
| F6 ACP continuation end-to-end (ADR-0103/ADR-0105) | **Unproven (partly)** | qualification gate `qualified:true`; ADR-0105 route accepted; background-result→new-root execution not yet end-to-end qualified. The normal already-ACK/cleanup branch is **independently verifiable**; only the lost-old-process-no-receipt branch is gated by the **Proposed** ADR-0104/Draft A. Manifest capability `f6_continuation.evidence = NOT_RUN`. | verify the normal ACK/cleanup background-result→new-root branch now; keep the unknown-old-process branch paused until ADR-0104 is accepted (do NOT require accepting 0104 to verify the normal branch) |
| Interrupted-business continuation via **new child** (ADR-0102, **Accepted**) | **Unproven (contract accepted)** | ADR-0102 fixes the contract: rc.2 does **not** restore the original child; use parent-session recovery → verify the existing Job/idempotency/result → create a **new** child with new identities; unknown stays unknown; name = 中断后业务接续（新子Agent）. The child-resume refusal is the accepted premise, **not** an open ADR question. Evidence not yet produced (`interrupted_business_continuation_new_child.evidence = NOT_RUN`). | produce the ADR-0102 required evidence: rc.2 child-resume-refusal (source line) + new-child/new-identity + Job/idempotency reconciliation with no re-submission + unknown stays unknown + old-root exact ACK/cleanup + UI distinction |
| Single-version default switch | **Unproven** | manifest exists; consumers unwired; SDK default | wire consumers + validation; switch only after live gates pass |
| Storage cutover / release chain / hosted CI | **Unproven** | NOT_RUN | separate accepted contracts + CI/release coverage |

No new harness, no permission/recovery-contract change, and no default promotion are proposed above.
"Proven (bounded)" rows mean the specific evidence exists; they are **not** an overall candidate-merge
PASS. Merge/deploy remain the human gate. The historical `JUDGMENT-LIVE-QUALIFICATION-20261006`
`NOT_RUN` entries are a **date-stamped snapshot (2026-10-06)** and must not be read as the 2026-10-08
state by themselves; the later ADR-0105/0106 records and the current manifest are the current sources.

Current-image scenarios still missing (from the current manifest `config/dsh/acp/authoritative.json`
and ADR-0105/0106 records — NOT inferred from the 2026-10-06 snapshot):
- F6 background-result → **new-root** execution on the normal already-ACK/cleanup branch (verify now);
  plus the revoke / insufficient-budget / lost-model-call / restart / unknown-result branches.
- Ordinary real **16-tool count** boundary (the ordinary real turns used few tools; the 17th-boundary
  evidence is keyless) and multi-turn beyond the two proven ALPHA7 turns.
- Real **signed Product child** identity/attribution; real two-user concurrent model + reboot recovery;
  delayed old-root request; ordinary in-flight fault / ACK-cleanup loss.
- Two-user **file** isolation (shared-volume alias). Default switch, storage cutover, release chain, CI.

## Minimal next step — real signed Product child acceptance (reuse existing safe boundaries)
Single bounded real acceptance on the isolated candidate, no new harness:
1. Durable user (clean workspace, e.g. `admin`/`workspace_c1b07117…`); start one Product Agent turn
   whose trusted instruction delegates to `byq_delegate_market_research` with `run_in_background:false`
   (reuse the ADR-0100 slot + ADR-0094/0097 per-Agent identity plugin **enabled**, fake-MCP NOT used).
2. Capture the **real signed per-Agent identity** actually used by the root and the child (the
   `byq-acp-mcp-identity` scoped MCP client headers/identity), the child native id + `parentSession`/
   `origin:subagent`/`delegationDepth`, the child `tools/pre-execute` `exec.agent`, and the real MCP
   `tools/call` attribution to the child run.
3. Confirm the child's real MCP call is authorized/audited under the child's own identity (no root
   impersonation) and that the root `agent_runtime_turns` ownership is unchanged.
4. Independent Tester on the raw; this is the missing "signed child identity / root ownership" evidence.
