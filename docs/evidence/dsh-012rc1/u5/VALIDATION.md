# U5 DSH 0.1.2rc1 qualification

Status: BLOCKED — prior preproduction qualification withdrawn. Date: 2026-09-06.
Worktree: `/home/jefison/projects/.byq-worktrees/dsh-u5-full-qualification`.
Branch: `feat/dsh-u5-full-qualification`.
Observed base and candidate implementation commit:
`ce6493f006d9b857f38d81306bbccfcff1a8fbe4` (U4 PR #255).

## Scope and deployment state

U5 adds fail-closed qualification reporting, real candidate delegate journeys,
old/new runtime benchmarks, fixed G1-G6 live-model journeys and CI routing. The
deployment default remains `dsh-0.1.1rc1`; no production deployment or Product
Phase change was performed. One external synthetic G6 feedback delivery has
been confirmed by an authorized read-only Hub audit (see below). T38-T40 remain later-stage
gates and are not claimed here.

## Candidate identity and keyless evidence

- The final 0.1.2rc1 live candidate image had local immutable image ID
  `sha256:42cc13bec3fceaa72131a4af08006f7786f2c55dd25ec5705411527f30f60aff`.
  This is a local immutable image identity, not a registry digest.
- A real installed candidate DSH process used the isolated BYQ MCP and a local
  scripted OpenAI-style provider. The root invoked each of the five actual
  `byq_delegate_*` tools; every child invoked its role-allowed
  `mcp__byq__byq_agent_context` tool. Cross-role and generic agent tools were
  absent, child text stayed private and only the root answer was public: 5/5
  role journeys passed. Together with the U4 startup/auth cases, 7/7 candidate
  real-process tests passed.
- The same fixed scripted-provider lifecycle ran 20 create/prompt/release
  cycles on each release. A diagnostic paired run measured baseline median
  0.556149 s and peak RSS 205.527 MiB, versus candidate median 0.837117 s and
  peak RSS 279.895 MiB. Both left zero Adapter sessions, owned processes or
  lingering BYQ threads. The CI confirmation run measured 0.629739/205.547 and
  0.887529/283.723 respectively.
- The diagnostic candidate RSS exceeds the frozen formula
  (`205.527 * 1.2 + 32 = 278.6324 MiB`) by 1.263 MiB. Process breakdown placed
  the delta in the official bundled runtime main process (241.438 MiB versus
  168.633 MiB), not the Python adapter child (38.457 versus 36.895 MiB). This
  bounded 0.45% threshold excess is recorded as an explicit exception; the
  inherited Guard, compaction, subprocess, bash sandbox and permission preset
  services were not disabled to reduce memory.
- Final full local CI scope `local-u5-final2-677719` passed all 25 checks. It
  included 146 architecture tests, 331 Backend tests (1 skip), 88 Gateway
  tests, 76 Runtime Adapter tests (2 release-inapplicable skips), the 7 real
  candidate cases, both 20-cycle benchmarks, complete MCP contracts, 148
  frontend tests and dependency audit, Compose smoke, 9 real Product API
  browser tests, ML/feedback restart persistence and two-user isolation, and
  the Phase 48 no-mock Product coherence journey.
- CI-owned containers, images, networks and volumes were removed by the
  always-run cleanup. The earlier U5 diagnostic containers, three benchmark or
  state volumes and isolated network were subsequently removed by exact name.

This proves T01-T30 at keyless L0/L1/L2 layers and supplies supporting Product
evidence for T31-T37.

## Bounded live-model qualification

The maintainer authorized sending only synthetic test users, the fixed G1-G6
prompts and BYQ test object/tool context to the DeepSeek API. No production user
data, real conversations or secrets were sent. The provider was
`deepseek-official`, model `deepseek-v4-flash`, protocol
`openai-completions`. The final qualification matrix contains 12 baseline and
13 final-candidate samples; the extra candidate sample is the stricter repeat
of G4 after its persisted-content assertions were strengthened.

| Journey | Baseline result | Final candidate result |
|---|---|---|
| G1 date/session boundary | PASS, 24.280 s | PASS, 20.337 s |
| G2 bounded backtest review (3) | PASS, 116.858/159.063/96.656 s | PASS, 151.133/173.246/138.953 s |
| G3 ML approval (3 independent users) | PASS with recorded recovery, 600.887/386.991/352.410 s | PASS, 486.251/128.005/296.313 s |
| G4 public research evidence | PASS, 108.823 s | PASS, 127.072 s; strict repeat PASS, 137.024 s |
| G5 Runtime-only restart recovery (3) | PASS, 6.137/8.131/6.131 s | PASS, 10.187/8.185/10.166 s |
| G6 internal feedback approval | Internal assertions passed, 44.781 s; external isolation unproven | Internal assertions passed, 59.075 s; external isolation unproven |

Every G1/G2/G5 sample left Product object counts unchanged. Every final G3
sample created exactly one real approval and, after approval, a second public
answer; each created two research Artifacts and zero training/prediction runs.
Every continuation required one bounded retry after a durable initial answer,
without duplicate approval or business work. The strict G4 repeat created
exactly one `web_research_evidence` Artifact, with URL-bearing sources and the
exact research-only/non-deterministic/non-authoritative usage policy. G6
created exactly one approval and one internal feedback record. No local GitHub
publisher was started, but that does not prove the separate Hub relay did not
send feedback externally. Runtime-only restart recovery preserved all three
G5 conversation contexts and created no business objects. Final candidate logs
had zero secret-like field matches.

## Failures retained and fixed

- The first old-stack Runtime-only restart exposed a Gateway defect: its
  in-memory Product session referenced a missing Adapter session and resume
  returned 404. Gateway now closes the stale private trace/session, rehydrates
  from the durable conversation and retries once. Unit tests cover resume and
  turn submission without duplicating the durable user message; the final
  baseline and candidate G5 matrices passed.
- The first candidate G3 run created an ML strategy and received
  `approval_required`, but the root falsely claimed that approval was in the
  global center without creating a record. That run is a failure, not a pass.
  The candidate root contract now states that `approval_required` is not an
  approval and requires exactly one approval-request call; it may claim a
  pending approval only after receiving `approval_id`. The candidate profile,
  identity, release descriptor, provenance policy and image were regenerated,
  and the entire candidate G1-G6 matrix was rerun under the final identity.
- One baseline G3 continuation initially failed after the approval was durable;
  one reasoned continuation retry completed it. An accidental same-workspace
  repeat created no duplicate approval or object and was retained only as
  idempotency evidence, not counted as an independent sample.
- The first Compose attempt inherited fixed resource names from the developer
  environment. It was stopped before any model request, did not delete shared
  resources, and was replaced by explicit U5-only networks and volumes. Final
  cleanup removed all U5 containers, volumes and both current/legacy-named
  U5 networks; observed cleanup counts are zero.

## Qualification report contract

`scripts/dsh/release.py qualify` reads one closed-schema evidence document and
refuses to emit `QUALIFIED` unless the exact ordered T01-T40 matrix, release,
image, Git, composition and policy identities, sample minimums, thresholds and
zero cleanup counts are valid. Keyless scope requires T01-T30 PASS;
preproduction requires T01-T37 PASS with T38-T40 NOT_RUN; production-observed
requires every row PASS. Missing or failed gates, false later-stage completion,
secret-like material and unexplained threshold excess fail closed. Output is a
new directory and does not alter the deployment selector.

## Result and remaining gates

The former preproduction report is withdrawn, not a release gate. Its original
observations are retained in `withdrawn/qualification-report.withdrawn.json`,
explicitly marked `WITHDRAWN`; its historical PASS rows are not current verdicts.
The current evidence marks T35 FAIL and T36 BLOCKED, so `qualify` must refuse to emit
a preproduction report. T38-T40 remain NOT_RUN. The enabled OpenCode protocol
routes have no configured credential in this
environment; deterministic route/credential-isolation coverage passed and the
credentialed second-route limitation remains explicit. U6 must perform the
release/rollback rehearsal before any default switch. U7 production deployment
and formal version switching remain separately unauthorized.

## Post-run isolation audit and required correction

- The final candidate live stack was started using the developer `.env` and an
  unrestricted Compose `up --build`, which also started `feedback-hub-relay`.
  A subsequent value-free check confirmed that the referenced environment has
  both a Hub URL and relay token configured. This was an execution mistake:
  model-evaluation authorization did not authorize delivery to the real Hub.
- `product_feedback.submit` always queues a Hub event; the relay advertises
  itself configured and sends queued snapshots to `/v1/intake` when its URL is
  set. Therefore absence of the local GitHub publisher is insufficient evidence
  of an isolated external boundary. Delivery was initially unproven; the
  subsequently authorized read-only audit below confirmed one matching intake.
- The isolated containers and database volumes had already been removed, so
  their outbox/receipt evidence is unavailable. A narrowly filtered GitHub
  issue search on 2026-09-06 found no matching Xiaoba issue; this does not prove
  absence of Hub intake or of differently titled issues. This initial check was
  superseded by the narrowly scoped Hub audit below. No external records have
  been deleted.
- Retain synthetic G6 data scope: no evidence currently shows production user
  data, real conversations or secrets were in the test feedback. Do not infer
  absence of external delivery from that separate data-scope statement.
- T35 requires explicit service and credential allowlists, a local fake Hub,
  verified effective endpoints before any submission, and a bounded old/new
  G6 rerun. The maintainer was notified and the scoped audit is complete for the
  confirmed record; do not silently erase any external records.
- T36 also lacks a candidate-specific Chrome MCP desktop/mobile review of
  Xiaoba, approval and Plugin Center. The 9 automated browser tests remain
  valid supporting evidence but cannot replace this mandatory review.
- U5 remains unmerged; U6 cannot start until these gates are satisfied. Existing
  development/push/PR/CI-green merge authorization remains valid, but CI success
  alone does not resolve these qualification failures.
- Corrective evidence checks: 18 targeted qualification/release/publication
  tests and the complete 147-test architecture suite passed; `git diff --check`
  and isolated-worktree validation passed. A new test proves the current
  evidence cannot generate a preproduction qualification report. PR #256
  remains Draft with auto-merge unset.

## Authorized read-only Hub audit (2026-09-06)

The maintainer explicitly authorized inspection of only this G6 synthetic
feedback, with no other feedback reads, deletion or publication. They signed
into Cloudflare in their Ubuntu Chrome and enabled its native debugging
connection. The selected account's existing dashboard link identified
`byq-feedback-hub`; an authenticated read-only metadata request confirmed the
exact database name before querying. No credential or cookie was extracted.

The fixed SELECT constrained intake to 2026-09-06 UTC, U5/G6 markers, Xiaoba
and the long-task topic. It returned only receipt/status/timestamps and the
publication-queue projection, not feedback bodies. A second SELECT inspected
audit actions for the single returned receipt. Both query results reported
`rows_written=0` and `changed_db=false`.

- Confirmed receipt: `central_feedback_d5afa14dadec452db2d7434403f267c2`.
- Received: `2026-09-06T08:37:41.165Z` (16:37:41 Asia/Shanghai).
- Observed state through `2026-09-06T09:55:34Z`: `received`; unchanged since
  intake. GitHub Issue number: null. Publication outbox row: absent.
- Audit history: exactly one `receive`, null → `received`, at intake time.
  No triage, acceptance or publication action was returned.
- Conclusion: at least one synthetic G6 feedback was accidentally delivered
  to the real Hub. This is a test-isolation failure, not a hypothetical risk.
  The confirmed record had not been published to GitHub at inspection time.
- Limits: the query cannot exclude a different feedback whose generated
  snapshot omitted the test markers or topic words. It does not establish a
  global zero-delivery claim or prove the full contents of every test payload.
- External state was left unchanged. No reject/delete/accept/publish action
  was taken; any later moderation requires separate authorization.

A general-purpose interactive browser controller was rejected by safety review
before execution. The accepted alternative used fixed, single-purpose read-only
requests without an arbitrary-command interface, and disconnected after each
check without closing the user's Chrome.

## Commands

```bash
python3 -m unittest tests.test_dsh_qualification tests.test_dsh_release
scripts/ci/local-ci.sh --base=origin/main --all --auto-smoke
python3 scripts/dsh/release.py qualify \
  --release dsh-0.1.2rc1 --baseline dsh-0.1.1rc1 \
  --output docs/evidence/dsh-012rc1/u5/report-preproduction
git diff --check
```
