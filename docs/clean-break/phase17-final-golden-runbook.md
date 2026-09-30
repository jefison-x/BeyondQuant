# Phase 17 final Golden runbook

Status: prepared execution plan; external calls are **NOT_AUTHORIZED / NOT_RUN**.
Phase 17 remains **OPEN**. This runbook complements the
[residual audit](phase17-residual-simplification.md) and
[verification gate](verification-gates.md).

## Execution identity and prepared environment

- Source: `a39849a2a6795a63cf843fb9f8dea111da8bc3ab`, branch
  `codex/clean-break-phase17`, worktree
  `/home/jefison/projects/.byq-worktrees/clean-break-phase17`.
- Build: `dsh-0.1.5rc1-post-u8.277`; manifest
  `sha256:36d14cca3d16f0eed89060630e84177fa8d9193bda3132cf66aa66320d2dfbd5`.
  Source/dependency/build inputs stay frozen during execution. Later evidence
  Markdown is outside the build inventory.
- New disposable scope: `byq-dev-dd33416d94`, 13 services. Gateway and Frontend
  use dynamic loopback ports; observe current ports rather than assume them.
- Current fresh Workspace: `workspace_3d969bf48cbe43f88262bd3d2745b723`.
  Reset E must observe its post-reset identity and new object IDs.
- Root completed the reviewed empty-scope clean/init, then
  `python3 scripts/dev/environment.py start --profile full`, `seed`, and `test`.
  Both external provider credentials are empty. Data and ML Workers are stopped.
- Private environment/image/resource/seed pin:
  `/tmp/byq-phase17-a39849a2/environment.json`; private browser preflight:
  `/tmp/byq-phase17-a39849a2/browser-preflight.json`.
  Existing Playwright tooling was reused without copying old Product state.

The environment check passed 3 offline governance and 13 lifecycle cases. Their
mock reset/cleanup output is not a live populated reset. Gateway durable login
and real browser durable login passed, with 38 browser requests and zero foreign
origins. These are preparation evidence, not Golden A–F completion.

## Final source for rebuild

The scoped-import repair passed focused Tester and independent Reviewer source
gates. Selected `.278` manifest:
`sha256:8c9eeb1569643054a67e71e31ecab10d843035050de944b638b1485cd83afe3e`.
Its identity gate passed current/revision/retirement 3/4/5 tests and the changed
architecture selector. Final execution requires a fresh committed-source
rebuild of only `byq-dev-dd33416d94`; the `.277` image/resource pins above are
historical preparation. Preserve the validated logical export outside target
volumes. New execution/image/Workspace pins will be recorded privately under
`/tmp/byq-phase17-278` after rebuild.

Before actual cache bootstrap, stop the target application services/Workers and
use a single reviewed Backend-image import runner on the exact target network.
This exclusive bootstrap window prevents Product/scheduler writes between the
read-only emptiness precheck and domain imports. Verify target identities and
empty credentials, qualified export hash/status/counts, empty domain facts/Jobs
and zero coverage projections before any Store constructor. Store methods use
separate transactions; partial failure permits read-only reconciliation and
never automatic re-execution. Source DB permission is spent.

## Common stages and exact-write discipline

For each flow, create a private mode-0600 manifest under the pinned evidence
directory. Record scope, source/build, Workspace, conversation, task, inputs,
approval, idempotency key, request digest, attempt state and observed result IDs.
Record an attempt **before** any Product write. A timeout or lost response permits
read-only reconciliation of that exact operation; it never permits a replacement
key, another model turn, duplicate Job or broader request. Stop on ambiguous
receipt identity or unknown external outcome.

Authenticate through Gateway `/api/auth/login` and verify `/api/auth/me` against
the pinned Workspace. Browser requests use only Frontend/Gateway Product routes.
Agent domain actions use BYQ MCP. Root's explicit human decisions use Product
API/browser; no Product DSH Engineering privileges are added.

Create a fresh custom single-symbol pool through
`POST /api/product/paper/pools` with one saved idempotency key and
`symbols=["000001.SZ"]`; record its new frozen snapshot ID. No old pool, Task,
Job, strategy approval, Artifact, session or user history is restored.

For a foreground turn, first save its exact prompt, create/verify the Product
session with `/v1/agent/sessions`, then submit once to
`POST /v1/agent/sessions/{conversation_id}/turns`. Read that same session and
`/v1/workflows/{conversation_id}/events` to reconcile exact normalized activity,
assistant output and domain IDs. Prompt instructions constrain the symbols,
window, tool actions, approvals, delegation and the permitted external calls.

## Market-data preflight

Preserve the validated 98-session TuShare window for `000001.SZ`,
2024-01-02–2024-05-31. Use a bounded canonical Data Plane export, validate units,
source, adjustment, lifecycle, calendar, provenance and content hashes, then
import into the **new** scope with domain import conflict checks. Do not use a DB
snapshot/restore, constructors that bootstrap old schema, or ordinary databases,
backups or Community storage. A partial research-daily response lacks the full
canonical provenance and units and cannot stand in for this export. The precise
read-only export/import operation requires qualification before execution.

New real-provider qualification, if authorized, permits at most one SSE calendar
request for `20260929` and one daily request for `000001.SZ` on that date. If the
calendar is closed or another dataset/provider request is needed, stop and scope
that gap; do not choose a replacement date automatically. Keep Data Worker
stopped so enabling a credential cannot run an unbounded scheduler. No download
of the existing 98-session window is permitted. New model/provider credentials
are never copied into Git or printed.

## Authorized one-time source read and validation

The maintainer explicitly authorized the reviewed one-time read exception. The
export ran once against the exact Phase 15 source below; its permission is spent.
No further source query is authorized by this grant. External model/provider
authorization remains separate. The existing-database ban otherwise remains.

Prepared exact source: project `byq-dev-ea551690f4`, Postgres container
`byq-dev-ea551690f4-postgres-1`, ID
`6f2b0297307bcb562071062aceff20cb6080c4a82c2b8c22ff02bc0b93e9fe41`,
database `byq_domain`. The wrapper verified the exact source Backend/Postgres
project and service labels, container identity and database before execution.

Prepared private exporter:
`/tmp/byq-phase17-a39849a2/export-phase15-market-readonly.py`, SHA-256
`7b27bebd6f7db1aedf83c5bbe692cc84aefadd4035365f70a503629338d91a55`.
It was syntax checked and executed once with a specific source
read-authorization marker. It checked the exact database URL/name and used one
repeatable-read, read-only transaction with 10-second statements, 1-second lock
waits and a 30-second idle limit; it ends with rollback. No Store constructor,
DDL, source import/update, DB dump or backup access is used.

Before full catalogue member reads, the exporter checks that the latest snapshot
is TuShare `stock_basic`, exactly L/P/D, with nonempty counts within the allowed
bounds. A latest snapshot that fails those conditions stops the export.

Prepared wrapper:
`/tmp/byq-phase17-a39849a2/run-authorized-source-export.py`. After the separately
recorded grant, its only execution mode is `--authorized-exact-source-read`.
It rechecks exact source container labels, Postgres ID and product-network alias,
checks the reviewed exporter hash, uses `umask 077` and exclusive mode-0600 files,
records the read attempt before invocation, and captures the complete stdout and
stderr directly into private files. It uses Python `-B` and disables bytecode
writes in the source container. Only payload hash, table counts and status appear
in tool output; a failed/unknown attempt cannot be automatically repeated.

The finite read list is:

| Source table | Predicate / maximum exported rows |
|---|---|
| `market_daily_bars` | `000001.SZ`, 20240102–20240531; 200 rows. |
| `market_trading_sessions` | Same date interval; 200 rows. |
| `market_daily_status` | Same symbol/date interval; 200 rows. |
| `market_adjustment_factors` | Same symbol/date interval; 200 rows. |
| `market_corporate_actions` | Same symbol/ex-date interval; 200 rows. |
| `market_session_supplement_completeness` | Same date interval; 200 rows. |
| `security_master_snapshots` | One latest immutable snapshot metadata row. |
| `security_master_snapshot_members` | Only that complete L/P/D snapshot; at most 10,000 rows. |
| `security_master_snapshot_quarantine` | Only that snapshot; at most 10,000 rows. |

Each bounded data query selects at most one extra probe row to detect overflow:
SQL limits are 201 for the six date/symbol tables and 10,001 for the two snapshot
member tables. An overflow stops export. The one latest snapshot metadata query
has limit 1. The requested read exception includes those finite probe rows.

Complete security snapshot rows are necessary to reconstruct a genuine validated
catalogue with the existing Data Plane import contract; a one-symbol file cannot
be presented as a complete stock-basic snapshot. There is no read of users,
credentials, Workspace, Agent sessions, Jobs, Artifacts or audit history. The
export checks bar units/source/adjustment and original bar hashes and snapshot
counts, then writes a private logical bundle for further provenance, lifecycle,
calendar and supplemental-hash validation.

### Observed export and offline qualification

Private bundle: `/tmp/byq-phase17-a39849a2/source-market-export.json`;
payload SHA-256
`b6208258fc9725d56e2fa78b7f1c31b460d5bce9b0fd26a32178549246237eab`.
The authorization, attempt and full output are private mode-0600 files. Source
execution completed with rollback; no source DDL/DML or provider call occurred.

Independent offline validation is **QUALIFIED_PARTIAL**: 98 bars/status/factors,
151 calendar days (98 open), 5,909 security members and one quarantine row all
match their original canonical hashes; the full security dataset ID recomputes.
Selected-symbol corporate actions are zero. The 98 source supplemental proofs
attest to full-market factors/actions, whose rows are absent from this export.
Their global aggregate hashes cannot be independently recomputed from the subset.
They must not be copied into target global completeness or regenerated with
one-symbol counts. No target import or Product readiness is established yet.

A bounded domain repair adds symbol/date supplemental proofs plus providerless
canonical calendar import. Scoped completeness must bind actual imported row
hashes, the source bundle and the original source attestation. Native full-market
replacement must invalidate scoped proofs in the same transaction. Engineering
bootstrap remains separate from Product DSH; no new HTTP/MCP privilege is added.

Target import remains limited to the fresh `byq-dev-dd33416d94` Data Plane, after
validation and a reviewed import operation. Filtered supplemental rows must not
falsely mark target full-market coverage using source-wide row counts. No old
business-state or database restoration is allowed.

## Golden A and E — research and populated reset

A uses at most three foreground turns: initial market/public-source research,
a bounded follow-up, and one delegated research request. Use cached qualified
market data through BYQ MCP, genuine Web Search within the request budget, and
at most one delegated run. Observe the returned sources, lineage, durable
Artifacts and normalized browser projection. Do not count synthetic seed data
or a tool name appearing in the transcript as real provider evidence.

After B/C/D and F6, run E on the populated **exact new scope** through the dev
runtime/workspace reset lifecycle. Record pre-reset object/session/Job/Artifact
IDs and post-reset absence, new seed identities and an actual new authorized
research/delegation journey (at most two foreground turns and one delegated run).
Market canonical data may be re-imported from the separately validated logical
export; old Product state is never restored. Offline mock reset tests do not
qualify E.

## Golden B — Agent backtests, revision and optimization

Use at most five foreground turns: Agent creates/validates StrategyVersion A;
Root approves that exact version; Agent prepares and executes its exact
BacktestTask once; Agent reads the result and creates revised B; Root approves
exact B; Agent executes B once; Agent creates the comparison OptimizationJob.
The five turns correspond to version A, run A, version B, run B and optimization.
Use one-symbol cached data, saved execution parameters and no benchmark/provider
fallback. Record each task, Job, source digest, parameter revision, approval,
result Artifact and optimization candidate lineage. Open the actual comparison
Artifact in a real browser through Product API.

Do not invoke `phase15-golden-b-bound.py` unmodified: it pins the old Workspace
and pool and submits optimization through a Root Product POST, which cannot
prove Agent initiation of the final OptimizationJob.

## Golden C and D — one CPU Job and independent continuation

Use at most two foreground turns for a new current-task ML strategy validation
and the Agent's exact TrainingSubmission preparation. Retain the accepted CPU
feature/target/walk-forward profile and the 98-session cached window. Root
approves the exact ML version, then the Agent requests training approval for its
prepared `receipt_watch.watch_id`. Record new strategy/approval/pool/task IDs and
the submission key. Approve the unique exact TrainingSubmission in the actual
Product browser. This typed approval resumption is a separately counted model
input, not a free read or part of the foreground budget.

With ML Worker still stopped, prove exactly one new queued TrainingJob exists
and its receipt matches the approved task/strategy/pool/key. For D, delete only
that Job's old Product session before Worker execution. After the exact C Job
completes and its Feature/Model Artifacts validate, create a fresh authorized
session and use one foreground turn to query the **same** Job and Artifacts.
There is no extra queued-state Agent query, replacement Job, Agent-session
reattachment or DSH restart claim.

For C, inspect the exact new-scope ML Worker/container/image. Start that Worker
with a temporary 0.1 CPU limit to observe the small real workload; poll the same
Job until its first running claim, worker ID, attempt and natural lease are
visible. If it is already terminal, stop; do not fabricate a checkpoint or create
a replacement. Hard-stop only that Worker with `stop -t 0`, prove exit 137 while
the Job remains nonterminal, then restore the committed normal allocation and
start it again. Never edit the Job/lease. Observe natural lease expiry/reclaim,
a later attempt on the same Job, completion and valid Feature/LightGBM Model
Artifacts through Product API. Record actual Worker and Job identities before
and after. GPU execution/checkpoint remain **N/A** under ADR-0089.

Do not run old Golden C preflight: its completed prior TrainingJob and old
Artifact IDs are not a prerequisite for a fresh Phase 17 run. The exact Worker
interruption algorithm may be used with current identities only.

## Actual enabled F6 and external-call budget — preparation pending

The full A–F external-call plan is not approved or requested yet. F6 must use a
separate new current Task and healthy original DSH session, with a validated
current-task strategy and explicit human grant **before** its first independently
trusted terminal Job event. It cannot reuse C's deleted session or an already
completed B/C event. The exact F6 preparation/Job sequence, grant timing and its
foreground model inputs still require final review.

The proposed grant is `max_turns=1`, `token_limit=4000000`, `valid_seconds=900`,
`turn_timeout_seconds=900`, exact confirmed strategy IDs and one saved Product
permission key. These are one background turn and a conservative total allowance,
not one raw model API call. Unknown receipts are never replayed/refunded. Revoke
that exact grant and disable the executor afterward. A grantless notification or
synthetic reservation is not actual F6 execution.

Before asking for external calls, finalize a numbered input ledger that separates
foreground user turns, delegated runs, typed approval resumptions and F6; each
write/approval must specify whether it opens a model input. Establish the global
Web/provider request counter and stop boundary across roots, children and
workers. The SDK's per-run `maxUses` does not prove a global six-search ceiling.
No model/provider budget or source-read permission is inferred from this draft.

A Product turn/delegated run can contain multiple model API requests. Record the
actual provider/model, requests and usage. No automatic failed-turn replay,
changed provider route or unrelated call is authorized. Push/PR, merge and
production deployment remain separate permissions.

## Preparation acceptance and next permission

Independent Tester: **PREPARATION PASS** for actual new-scope build/resource pins,
empty model/TuShare credentials, stopped Data/ML Workers and recorded durable
browser login. Independent Sol Reviewer: **PREPARATION PASS / SOURCE-READ PLAN
PASS**, limited to proposing the exact read exception. Root: **PASS** for that
preparation scope. The later maintainer exception authorized one source export,
now completed and spent. Offline qualification is partial as documented above;
target contract qualification/import/readback and all connected Golden/provider/
model journeys remain open. The prepared `.277` environment is historical after
the scoped-import source repair; final execution needs fresh `.278` images and pins.

## Acceptance

Independent Tester verifies actual per-flow evidence and limits; independent Sol
Reviewer inspects it, followed by Root. Source-slice PASS, environment preparation
and a proposed budget never imply final Golden PASS. Final A–F and enabled F6
remain NOT_RUN until the authorized connected journeys actually finish. Hosted
CI and repository gates remain required before Phase 17 can close.
