# Phase 17 final Golden runbook

Status: prepared execution plan; external calls are **NOT_AUTHORIZED / NOT_RUN**.
Phase 17 remains **OPEN**. This runbook complements the
[residual audit](phase17-residual-simplification.md) and
[verification gate](verification-gates.md).

## Historical `.277` preparation

- Source: `a39849a2a6795a63cf843fb9f8dea111da8bc3ab`, branch
  `codex/clean-break-phase17`, worktree
  `/home/jefison/projects/.byq-worktrees/clean-break-phase17`.
- Build: `dsh-0.1.5rc1-post-u8.277`; manifest
  `sha256:36d14cca3d16f0eed89060630e84177fa8d9193bda3132cf66aa66320d2dfbd5`.
  Source/dependency/build inputs stay frozen during execution. Later evidence
  Markdown is outside the build inventory.
- New disposable scope: `byq-dev-dd33416d94`, 13 services. Gateway and Frontend
  use dynamic loopback ports; observe current ports rather than assume them.
- Historical `.277` Workspace: `workspace_3d969bf48cbe43f88262bd3d2745b723`.
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

## Current `.278` execution identity and cache preparation

Execution source: `6a2a391fb6a6ccd2493944d9a19df27fa64b2b71`, isolated branch
`codex/clean-break-phase17`; selected immutable `.278` manifest:
`sha256:8c9eeb1569643054a67e71e31ecab10d843035050de944b638b1485cd83afe3e`.
The scoped-import repair passed focused Tester, independent Reviewer and Root
source gates. Current/revision/retirement identity tests passed 3/4/5 plus the
changed architecture selector; this evidence is reused without another rerun.

The exact disposable scope `byq-dev-dd33416d94` was rebuilt from committed
source with `.278`, seeded and checked. Independent Tester verified all 13
container/image/label pins, five volumes, two networks, actual Backend source
inventory and the Runtime's embedded manifest. New Workspace:
`workspace_af43ba7a82524108ba11d4695613aafc`. Both model/TuShare credentials remain
empty; Data/ML Workers remain stopped. Private original environment pins:
`/tmp/byq-phase17-278/environment.json`. Actual post-bootstrap origins are in
`environment-after-bootstrap.json`; observe current ports before each journey.

The reviewed once-only Engineering bootstrap completed while target apps were
stopped. Its read-only precheck covered 24 market/security tables, sync Jobs and
empty coverage projections before Store constructors. Store methods used separate
transactions; the whole bundle is not claimed atomic. The original ten running
apps were restored and the import runner removed. No source DB query was repeated;
that permission is spent. No old Product objects were restored.

Independent target verification used one repeatable-read, read-only transaction
and passed all 31 checks: 98 bars/status/factors, 151 calendar days (98 open),
98 symbol-scoped proofs, zero actions and zero global completeness, plus 5,909
security members and one quarantine. Source/target values and canonical hashes
match. The original `target-market-validation.json` retains initial local checker
false positives caused by the import-time `provenance` versus stored
`provenance_json` field alias; corrected offline rehash passes all 98 bars with
no second DB query. This was a checker correction, not a product change.
The separate offline final report `final-target-market-validation.json` preserves
those diagnostics as `initial_checker_false_positive`, records final
`mismatches=[]`, and leaves the original report unchanged. Final SHA-256:
`337b3c9d66a55f5d3851d97bbcdf31e9a31c82e50d8e132b878907d27b6f1c78`.

Real browser Product cache preflight passed: `000001.SZ` usable 98/98,
`600000.SH` unavailable, 43 requests with zero foreign origins. The fresh pool
is `stock_pool_ba455d1da20c435a8b6ab3c233c5d8a4`, frozen snapshot
`stock_pool_snapshot_48f5fdb0812f50ff82b66f1d5bd86ae8c7dc5b826d201426e95728fe649915de`.
Use these new identities for A1; do not recreate the pool. Private import,
validation and Product records are under `/tmp/byq-phase17-278`.

Tester **PASS**, independent Reviewer **Functional / Tests / Clean Break
Architecture PASS**, Root **CACHE PREPARATION PASS**, limited to this fresh
target bootstrap and Product cache preflight. Golden A–F, enabled F6 and all
new external calls remain **NOT_RUN / NOT_AUTHORIZED**.

## Common stages and exact-write discipline

For each flow, create a private mode-0600 manifest under the pinned evidence
directory. Record scope, source/build, Workspace, conversation, task, inputs,
approval, idempotency key, request digest, attempt state and observed result IDs.
Record an attempt **before** any Product write. A timeout or lost response permits
read-only reconciliation of that exact operation; it never permits a replacement
key, another model turn, duplicate Job or broader request. Stop on ambiguous
receipt identity or unknown external outcome.

Agent session creation and turn ingress have no caller-supplied idempotency-key
contract. A private local operation ID and O_EXCL attempt file prevent this driver
from sending twice; they do not provide server-side deduplication. Gateway uses
the persisted user-message ID as its internal Adapter prompt key. Unknown
session/turn outcomes permit only read-only reconciliation, never resubmission.

Authenticate through Gateway `/api/auth/login` and verify `/api/auth/me` against
the pinned Workspace. Browser requests use only Frontend/Gateway Product routes.
Agent domain actions use BYQ MCP. Root's explicit human decisions use Product
API/browser; no Product DSH Engineering privileges are added.

The fresh custom single-symbol pool was created once through
`POST /api/product/paper/pools` with a saved idempotency key and
`symbols=["000001.SZ"]`; its frozen snapshot is recorded above. Read it back
before A1; do not replay its creation. No old pool, Task,
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

## Actual enabled F6 and external-call budget — authorization pending

The full A–F external-call plan is not approved or requested yet. F6 must use a
separate new current Task and healthy original logical Product session, with a validated
current-task strategy and explicit human grant **before** its first independently
trusted terminal Job event. It cannot reuse C's deleted session or an already
completed B/C event. The exact F6 preparation/Job sequence, grant timing and its
foreground model inputs are accounted for in the reviewed ledger below; actual
execution still requires authorization and per-input manifests.

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

## Model input ledger draft — no external authorization yet

The current source review yields this input ledger. It is a planned operation
limit, not a shared cross-session SDK counter or a raw model-request limit.

| Inputs | Purpose | Planned maximum |
|---|---|---|
| A1–A3 | Research, follow-up, delegation request | 3 foreground turns |
| B1–B5 | Version A, run A, revised B, run B, Agent optimization | 5 foreground turns |
| C1–C2 | ML version validation and exact training submission preparation | 2 foreground turns |
| C-approval | Unique typed training approval resumption | 1 additional server-owned DSH run |
| D1 | New session reads the same completed C Job and Artifacts | 1 foreground turn |
| F6-1–F6-2 | New Task/validated version, then Agent initiates a new exact Job after grant | 2 foreground turns |
| F6-event | Trusted new terminal event delivered to the healthy current session | 1 grant-bound background run |
| E1–E2 | Real research/delegation after populated reset | 2 foreground turns |
| A/E children | At most one requested delegated research run for each journey | 2 delegated runs |

Totals: 15 foreground turns, at most two delegated runs, one C approval
resumption and one F6 background run. Extra F6 generic approval resumption is
not included; if required, stop before opening that additional model input.
Foreground/delegation plans do not imply one raw model API request per run.

The active profile has per-run Web `maxUses=5` and search `maxQueries=4`.
These do not enforce a global six-search ceiling. F6 background disables Web.
The remaining 18 planned non-background runs therefore have a conservative
native-config upper bound of 90 search-tool uses / 360 queries if all use Web;
no smaller global hard bound is currently established. A final scoped external
proposal must disclose the executable limits and the exact ledger, rather than
claim six globally guarded searches. Delegation/input counts still need
per-input operation manifests and review of the runnable sequence.

For F6, keep the appropriate signal Worker stopped while Agent initiates its new
Job after the exact human grant. Start only that Worker so a new terminal event
can be delivered; require the same original healthy logical Product session and matching
validated Strategy Artifact/Task. Revoke the exact grant and disable the executor
once the one background run settles. The 4M allowance admits at most three
`llm/stream` budget checks with the current conservative guard; it is not a
one-call API permission. Later root turns may create new Runtime generations;
this does not prove reuse of the same underlying DSH process or process reattach.
Actual enabled F6 viability remains unverified.

## Preparation acceptance and next permission

The historical `.277` source-read preparation passed its limited gate. The
maintainer's one-time source read was executed and is spent. `.278` source,
fresh environment, once-only target canonical import and independent readback
have now passed Tester → independent Reviewer → Root. Cache preparation is
complete; it does not close the final Golden milestone.

External model/Web/TuShare authorization is absent. The saved exact first prompt
is `/tmp/byq-phase17-278/golden-a1-input.json`; it has not been submitted and no
A1 session exists. A staged A1 grant must specify one foreground DSH run, no
delegation, no market-provider downloads, native Web limits and the lack of a
raw model-call hard cap. Later ledger inputs require the recorded external
scope; additional inputs or retries cannot be inferred from an A1-only grant.

Prepared private one-shot A1 driver: `/tmp/byq-phase17-278/run-a1-once.mjs`,
mode 0600, SHA-256
`c44ba0909998389eaefa80e27b87dd51a0d6aa4ce6c6a0440692e4c1fbc6786b`.
It requires an explicit A1-only grant and a newly verified credential-enabled
Runtime receipt bound to `.278`, source, Workspace, subject and exact input.
The old empty-credential pin alone cannot admit a run. All Product writes have
private single-attempt records and fresh authorization checks; browser routing
blocks non-Frontend origins before requests. Session/turn POSTs abort after 60s
and permit only read-only reconciliation; the 300s workflow observer does not
cancel a pending model run. No automatic input replay is supported.

The proposed route is `deepseek-official` / `deepseek-v4-flash`, with official
DeepSeek Web Search and no provider change. A1 intends one search/query; native
limits are five search uses and four queries per use. No-child/no-TuShare and
the intended search count are prompt/operation restrictions, not new SDK hard
guards. A foreground run can make multiple raw model API requests, with no
shared hard call-count cap. Enabling the existing key, any necessary target-only
Runtime recreation and new live pins require the new scoped grant first.

Independent Tester passed final-driver syntax and static admission/receipt
boundaries. A requested syscall trace was blocked by sandbox ptrace permissions
before Node started; it is not a successful network-trace test. Root separately
ran the unchanged driver with no arguments: exit 1 with the expected early guard,
empty stdout, and no grant/start marker/evidence directory. Private result:
`/tmp/byq-phase17-278/a1-noargs-guard-check.json`. This does not qualify a real
credential-enabled run or the actual provider route.

Independent Reviewer: **A1-only PLAN PASS / runbook docs PASS**, limited to the
frozen driver and the proposed scope. Root: **PLAN PASS** for the same scope.
These gates approve the prepared plan's reviewability, not external execution.
Fresh credential-enabled preflight and actual A1 remain **NOT_RUN** pending the
new explicit grant; no grant is inferred from the completed source-read exception.

## Acceptance

Independent Tester verifies actual per-flow evidence and limits; independent Sol
Reviewer inspects it, followed by Root. Source-slice PASS, environment preparation
and a proposed budget never imply final Golden PASS. Final A–F and enabled F6
remain NOT_RUN until the authorized connected journeys actually finish. Hosted
CI and repository gates remain required before Phase 17 can close.
