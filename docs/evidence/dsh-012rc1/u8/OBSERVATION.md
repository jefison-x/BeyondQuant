# U8 — CLOSED_EARLY_REMEDIATION_REQUIRED

U8 observation is closed early by maintainer decision on 2026-09-07. It is NOT a
24-hour acceptance PASS or a semantic stability certification. Product Phase 97
remains unchanged; no release/tag is authorized here.

## Final disposition — 2026-09-07

The maintainer explicitly requested stopping observation, inventorying failures,
and proceeding with post-U8 reliability and stock-pool remediation. Data Center
dataset expansion is deferred. Current DSH 0.1.2rc1 stays deployed; no rollback.
This decision supersedes the earlier requirement to wait for 24 hours before
starting remediation. U8 closeout/merge may proceed with failed acceptance intact.

The user-level unit `byq-u8-observe-20260906T2303.service` was stopped explicitly;
confirmed inactive/dead with success. All 11 production containers remain running.
No production process, business record, backup or raw observation file was deleted.
The observer checkpoint intentionally retains its last OBSERVING value: it is an
unaltered historical sample, not the final disposition. No window-result.json exists.

- 78 samples, 15,900 monotonic seconds (4h25m), zero failed samples or infrastructure
  alerts; maximum sample gap 300.000323 seconds. Last sample began 03:27:43 UTC and
  checkpoint completed 03:27:45 UTC. The remaining 24-hour duration gate is waived
  for early closure, NOT passed. No post-fix observation may reuse this elapsed time.
- Runtime process count 2–4; session disk 27,272–117,912 KiB; available host memory
  minimum 3,676,400 KiB; available disk minimum 74,151,657,472 bytes. Runtime container
  memory first/last 245.4/273.5 MiB; final active prompts zero, two idle session records.
  These aggregates do not prove leak absence or SDK child ownership.
- Final read-only domain inventory: four newly created Agent runs still active
  (one orchestrator, two market researchers, one ML researcher); one approved approval
  continuation submitted; one training completed; zero new prediction/backtest jobs.
- Confirmed failures: fixed child timeout; missing unanswered subject during resume;
  unrelated same-workspace research selected; service health incorrectly used to deny
  a recorded timeout; stale Agent lifecycle; ML create timeout before durable receipt;
  late successful training without prediction/backtest continuation; misleading activity
  completion/failed labels; wrong strategy-type tool and insufficient validation feedback.
- Existing index-pool audit additionally found missing import-triggered refresh wiring
  and absent Agent index creation access. These are BYQ remediation scope, not claims
  that DSH upgrade introduced them.
- Unique-key/semantic duplication and every child ownership path are not certified
  by the aggregate inventory. They remain explicit regression/audit requirements.

Same-release regeneration/operator checks already recorded below remain valid for
their narrow scope. Production semantic acceptance remains failed; T40 must not be
promoted to an unconditional PASS. Historical reports and failures remain unchanged.
Post-U8 repair must use new worktrees/build identities and repeat affected business
journeys plus a fresh deployment observation window after separately authorized rollout.

The sections below preserve the original observation setup and pending-gate record;
this final disposition governs their current status.

## Authorization and actual deployment

The maintainer explicitly authorized restoration of stopped BYQ production,
private backups under `/home/jefison/backups/byq-dsh-u7`, DSH 0.1.2rc1 deployment
and continuous 24-hour observation. The clarified G3 requested one strategy
approval and authoritative progress after approval, without large training.
Isolated G3 passed with one approval and zero training/prediction runs. Original
failed reports remain unchanged in U7 evidence. No model calls are made by U8 monitoring.

U7 PR #258 merged after required CI and fresh ADR-0015/0059 checks. Actual production
deployment finished at **2026-09-06T22:51:59.788327Z**. Runtime is the qualified
`dsh-0.1.2rc1-u7.3` image
`sha256:82cebf2842c01930c50723e8152fa98cab123a9b8741f8c2a040af7531649da4`.
SDK/runtime-bin are both 0.1.2rc1. Profile `byq-product-candidate` has composition
`sha256:e584cee23c7e39ffaaf7d4c583d4762556032b4d4d173285c14c038d98ec6f98`;
only compaction, guard and web-search are active. Interaction/spill remain blocked.
Authenticated Product Plugin Center reports Desired = Active.

Private receipts are in `release-20260906T220612Z` under the approved root. They
include deployment, installed-identity, drain, session-backup and synthetic-smoke
receipts. No credentials or raw production conversations are committed. The initial
operator check used the wrong installed manifest path; corrected path
`/opt/byq/builds/build.identity.json` passed the full recheck. The error is retained.

Frontend ingress closed, then 10 zero-active-prompt samples covered 91 seconds
before Gateway/Runtime stopped for session backup. Qualified old G1 and new G5
used one synthetic ordinary user and the same public conversation. G5 was submitted
once through Chrome. Desktop 1440×1000 and mobile 390×844 showed the final answer
without residual processing or horizontal overflow. Browser fetch/XHR stayed on
Gateway/Product API. Synthetic user's business object counts remained zero.
PostgreSQL and Workers retained container identities/start times throughout deployment;
no production database restore occurred.

Latest logical backup `baseline-20260906T221001Z`: 2284257709 bytes, SHA-256
`f8358ede979968f849e81b21b72b9f974c6d86577132df6c60efa1891bb05202`.
Actual isolated restore scope `byq-u7-restore-4f200b8d2e95` verified 105 tables,
8 critical hashes, constraints and cleanup. This snapshot precedes synthetic
production smoke and is not atomic with the later session backup.

## Actual observation window

- Start: **2026-09-06T23:02:43.471381Z** (2026-09-07 07:02:43 Asia/Shanghai).
- Earliest duration gate: **2026-09-07T23:02:43.471381Z**; final review still required.
- One-off unit: `byq-u8-observe-20260906T2303.service`, maximum 90000 seconds.
- Private output: `release-20260906T220612Z/u8-observation-20260906T230243Z`.
- First 30 minutes: 60-second samples; then 300-second samples. Final sample after
  86400 monotonic seconds. Failed probes/gaps remain recorded; no reboot/resume stitching.

This is a bounded, explicitly authorized host observer, not a permanent scheduler,
deployment controller or Product capability. It records allowlisted aggregate
identity/session/token/resource metrics, never logs, content or credentials. It
does not submit tasks, call models, restart services, alter admission or delete data.

Initial sample: 11 services running, no health/identity/restart delta alerts,
zero active prompts and one idle session metadata record. Runtime Docker memory
245.4 MiB; session disk 27272 KiB; available host memory 5850376 KiB; available host
disk 74185756672 bytes. These are initial values, not stability or peak evidence.
Historical Worker restart counters are compared to the deployment baseline.
Capacity guardrails (1 GiB host memory / 10 GiB disk free) do not change qualification
thresholds: U7's documented RSS excess of 2.5118 MiB remains an exception, not PASS.

### Production semantic incident (acceptance blocker)

During the observation window, a real research turn delegated bounded market
research and then failed with `runtime-subagent-timeout`. The user's next short
continuation resumed into a fresh private DSH generation, but the rehydration
projection omitted the unanswered trailing user prompt. The new run therefore
received no subject-bearing public context and selected an unrelated, pre-existing
ML/backtest object from the same owner/workspace. Its final answer was internally
consistent with that old object but did not answer the current research subject.

Bounded read-only review found no new Artifact, training, prediction or backtest
mutation in the incident window and no cross-owner/workspace access. The delegated
BYQ Agent run remained durably `active` after the runtime process had failed and
closed, so stale run termination is a second issue. Raw conversation content,
owner/workspace identifiers and private DSH logs are not committed here.

This is not cleared by healthy containers or zero monitor alerts. The maintainer
explicitly dispositioned implementation to the unified
[post-U8 Agent reliability remediation](../../../roadmap/POST_U8_AGENT_RELIABILITY_REMEDIATION.md),
after U8 observation and merge. U8 may finish its observation/closeout with the
defect explicitly unresolved, but must not claim semantic stability or that the
production defect is fixed. Increasing the timeout alone is not acceptable.
Rollback is not assumed to solve the issue: the BYQ Gateway/adapter resume behavior
is shared by the certified old/new builds.

## Pending gates and limitations

Actual 24-hour duration, bounded approval backlog/job
idempotency final review and resource trends remain pending. The first dense period
had no infrastructure alerts, but the semantic incident above occurred immediately
after it. Process count is not SDK child ownership state; idle session metadata is
not a leaked running process. Zero traffic/errors cannot prove scenario coverage.
User feedback has not been inferred from metrics.

Both exact release checks, both frozen U7.3 build checks and promotion check passed
at observation start. Same-release generation and output revalidation passed for
both registered old/new releases into fresh private `u8-regeneration-old` and
`u8-regeneration-new` directories. No manual version edit, invented future version
or application/Compose diff was used. Full DSH operator/contract suite: 83 PASS.

Initial bounded READ ONLY domain aggregate at 2026-09-06T23:06:50Z found no
queued/submitting/failed approval continuations, no new domain runs/training/
prediction since observation start, and zero duplicate approval/training/
prediction/backtest idempotency keys. Statement timeout was 5 seconds. This does
not detect semantic duplication under different keys, prove SDK child termination
or replace the pending final review. No production row content was retrieved.

Current and compatible R1 images/configurations/backups must be retained for
**at least 7 days AND until maintainer stable confirmation**. R1 runtime image:
`sha256:b18dbc0f130ed89402c7e3590fb2812f84dbdf4afef933002103ed75f76ddf87`.
Qualified private rollback uses a fresh old-runtime namespace and preserves current
PostgreSQL/domain state. No automatic cleanup or rollback.

Daily upgrade lane: observe → classify → candidate → verify → PR → authorized
deploy → observe. Discovery does not itself authorize external PR/Issue writes,
new schedules or deployments outside the current explicit grant.
