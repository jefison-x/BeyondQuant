# U8 — DEPLOYED_OBSERVING

U8 is NOT COMPLETE. Product Phase 97 remains unchanged. Production deployment
and observation completion are separate gates; no release/tag is authorized here.

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

## Pending gates and limitations

Actual 24-hour duration, first-30-minute review, bounded approval backlog/job
idempotency review, failure/timeout classification and final resource trends remain
pending. Process count is not SDK child ownership state; idle session metadata is
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
