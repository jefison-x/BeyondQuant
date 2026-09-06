# U6 validation — in progress

U6 is not release-ready. No production deployment, default switch, production
database restore, Hub moderation or external publication was performed.

## Implemented and tested

- Shared local-filesystem admission gate, read-only in Gateway/Runtime; its only
  writer is the trusted Engineering operator script. Unconfigured deployments
  preserve prior behavior. Configured missing/malformed/symlink gates fail closed.
- Exclusive operator locking waits for in-flight admission; tests cover threads
  and a separate serving process. Closing admission is followed by bounded Runtime
  drain, not treated as proof that model execution has already finished.
- Maintenance rejects new sessions/turns/resume before history writes, but keeps
  health, release and existing normalized event streams available.
- Approval decisions remain durable and queued while closed. A missing Runtime
  session during continuation is replaced using the existing public-context
  rehydration path; the original approval continuation idempotency key is retained.
- Frontend maintenance rejection preserves the composer and removes only the
  unaccepted optimistic message. Ambiguous non-maintenance failures are unchanged.

Local results on 2026-09-06:

| Check | Result |
|---|---|
| Shared gate, isolation and rehearsal safety tests | 16 PASS after fixture corrections |
| Gateway complete suite | 91 PASS |
| Candidate Runtime complete suite | 77 PASS, 2 SKIP; skips are not qualification evidence |
| Frontend complete Vitest suite | 150 PASS |
| Frontend type check and production build | PASS |
| Full root/architecture suite | Initial 163-test run failed on build-input drift; final independent identity and fixed-scenario safety suite: 171 PASS |
| Required full CI / U6 PR | `local-u6-verify-20260906`: 26/26 PASS, exit 0; U6 PR not created |

## Historical identity protection gate

The maintenance gate changes both Runtime Dockerfiles and adds a shared module.
The existing release descriptors therefore correctly reject the changed build
inputs. A proposed update to old/new descriptors, together with loosening the
archived-failure test's expected error text, was rejected by safety review because
it could overwrite historical release identity and weaken audit protection.

That patch was not applied. Neither old/new release descriptor nor generated
identity has been rewritten; historical U5 reports and their failure assertion
remain intact. No alternate command bypassed the rejection.

The maintainer subsequently explicitly authorized preserving historical release
descriptors, reports and failure tests while adding independent U6 build identity
and requalifying. [ADR-0061](../../../architecture/adr/ADR-0061-u6-independent-build-identity.md)
records that decision. The two uncommitted Dockerfile additions were moved into
new U6 Dockerfiles; historical files now match their registered hashes and Git
baseline exactly. Historical reports and failure assertions remain unchanged.

New immutable `byq-dsh-build.v1` manifests bind current BYQ source inputs plus
the unchanged release descriptor hash. Initial `u6.1` files were superseded by
new `u6.2` files after adding frontend type-check inputs; neither revision was
overwritten. The `u6.2` full CI finished 25 PASS / 1 FAIL: the mocked feedback
login helper navigated before the asynchronous post-login route settled. Its
original feedback assertions remain unchanged. Adding the existing suite's
post-login `/agent` URL assertion fixed the race; both feedback tests passed
three consecutive repetitions (6 PASS). A new immutable `u6.3` binds that test
change. Earlier revisions and the failed CI result remain uncertified history.
Current selected manifests:

- Old `dsh-0.1.1rc1-u6.3`:
  `sha256:bc84ddeff4851d90541008a5baf0507840f374cd160bc2b16853b882a6837c1f`.
- Candidate `dsh-0.1.2rc1-u6.3`:
  `sha256:c76bff7fd0dd4189c02cddf77777d1812a98bf74bd07e630308d8622868bf0a6`.

The failed CI scope `local-u6-build-20260906` finished cleanup with zero scoped
containers, networks and volumes. Its mocked failure trace was overwritten by
the subsequent real-browser suite's shared output directory; only the observed
failure metadata/log is claimed. Mocked tests now use a scope-specific artifact
directory, separate from the real-browser outputs. Final `u6.3` CI uses scope
`local-u6-final-20260906`; its 20 mocked browser tests have passed.

That `u6.3` run subsequently finished 25 PASS / 1 FAIL. The real Stock Pool login
test timed out before finding the username field. Its retained Chrome trace shows
three JavaScript imports failing with `net::ERR_NETWORK_CHANGED`, leaving an empty
`#app`; the other eight real Product journeys passed. This is observed browser
transport failure, not evidence that the username locator changed. No assertion,
retry count or timeout was relaxed. Trace retained locally:
`apps/frontend/test-results/real-product-real-Product--43a52--and-Stock-Pool-create-flow/trace.zip`,
SHA-256 `40162545912a97b5c1833ac60d3bd32036b2d41fe8a0fff84c30e0c534a95c24`.
Exact-label cleanup verified zero containers, networks and volumes. One bounded
full rerun, `local-u6-verify-20260906`, uses unchanged `u6.3` inputs; its real-browser
output has a separate scope-specific directory so the earlier trace is preserved.
Lifecycle benchmark JSON is now persisted per scope as well as emitted to stdout;
the shell retains pipefail, so writing evidence cannot hide a benchmark failure.

The bounded full rerun completed 26/26 PASS with exit 0: Backend 331 PASS / 1
documented SKIP / 7 subtests, Gateway 91 PASS, Runtime 77 PASS / 2 documented
SKIP, seven real candidate/role tests PASS, frontend 150 unit / 20 mocked browser /
nine real Product browser tests PASS, and smoke, restart persistence, two-user
isolation and cleanup PASS. Separate final root/operator tests: 171 PASS.

[Raw lifecycle comparison](lifecycle-comparison.json) retains all 20 samples per
release. Baseline/candidate medians are 0.654086/0.955040 seconds; both had zero
retained sessions and owned lifecycle threads. RSS was 206.270/282.648 MiB against
the frozen candidate ceiling 279.524 MiB. The 3.124 MiB (1.12%) excess requires an
explicit release exception, not a claim that the formula passed. Peak process
breakdown is old/new main 169.219/243.508 MiB and Adapter 37.051/39.141 MiB; the
official carrier is the dominant difference, consistent with the retained U5
finding. No safety feature was removed to obtain these results.

Runtime build inputs remain `u6.3`. Implementation commit is
`3d3e0b82b0241e57a63a1b9965f8f0efe0a8a5c8`; final operator/probe credential
isolation and raw samples are frozen at `81aceecc6926fed3661a3bf5f4c1e87608e1acb7`.
The latter changes no bound image source. Final live/Chrome requalification is
still pending and cannot be inferred from the keyless CI result.

The first final-artifact rehearsal `byq-u5-u6-qmlnn5y-` stopped before service
startup or paid model calls: the runner incorrectly assumed CI image tags survive
cleanup. Read-only investigation confirmed `cleanup-resources.sh` intentionally
removes those exact tags/images. Result remains FAIL, cleanup PASS, at
`/tmp/byq-u6-qmlnn5y_/result.json`; no replacement image was used. The successful
CI result remains valid test evidence, but those removed artifacts cannot be
promoted or used for final live requalification.

The corrected handoff is explicit local `--retain-u6-artifacts`, after all full
checks pass and before unchanged CI resource cleanup. It retains seven exact
application images plus a checksummed archive under separate operator artifact
identities. No production image is retagged; no test cleanup assertion is relaxed.
The runner validates receipt/build/archive/image equality before use. Negative
tests cover invalid scope, production-tag substitution, output overwrite, archive
drift and partial/hosted CI rejection. Final artifact CI/rehearsal must now use this
handoff; the earlier removed-image benchmark remains retained history.

Images embed the exact manifest. CI checks source inventory/hashes before building;
live rehearsal checks the embedded manifest before model calls and switches.
Negative tests reject missing/extra inputs, drift, cross-release claims and wrong
image manifests. U6 release-ready requires v2 evidence binding both build-manifest
hashes and image IDs: v1 U5 reports cannot certify these builds. Final CI/live
acceptance remains in progress; prior diagnostic PASS is not new-image certification.

## Chrome MCP maintenance review

Actual isolated context `byq-u6-rehearsal`, local frontend
`http://127.0.0.1:18210`, synthetic account `u5-admin`.
Initial rehearsal scope: `byq-u5-u6-y9xyako5`.
Conversation: `conversation_600a2b798450408c9a7f7f3ebe0eff06`.
Approval: `agent_approval_679830e79d86435d9e0e64c2b9e60dc7`.

The old Runtime produced one real G6 preview and pending approval. During the
closed-gate review window, actual Send clicks with the fixed G5 prompt returned
HTTP 503. The composer remained unchanged, the maintenance message was visible,
and there was no phantom G5 transcript bubble or processing indicator. DOM checks
confirmed these properties at 1440×1000 and 390×844; document width equalled the
viewport width at both sizes. Pending approval and existing history remained visible.

Observed network requests used only same-origin Gateway auth, Product approvals,
Agent endpoints and normalized WorkflowTrace SSE. The initial unauthenticated
auth check returned expected 401; login succeeded; history/SSE returned 200 and
the two rejected turn requests returned 503. This is actual Chrome MCP review,
not mocked Playwright evidence. No screenshot file is claimed.

First attempt `byq-u5-u6-y9xyako5` was retained as FAIL. Logical backup/restore
succeeded (270919 bytes, mode 0600,
SHA-256 `04e71f07b41ded67d052fe2c558da3c1dd3fd260bc7927ce6f39095cad51d9d3`),
with equal public table counts and validated constraints. Old→new replacement
preserved the other seven container IDs/start times. Approval queued during
maintenance and resumed once under the candidate: one feedback, one fake-Hub
attempt/intake, zero publications, including a duplicate continuation request.

The fixture then incorrectly called `resume` on an IDLE session and received
HTTP 409, so rollback was not reached. Existing Runtime behavior is correct;
the fixture now uses the ordinary Product turn path, which also rehydrates a
missing Runtime session after replacement. A regression test locks this behavior.
Cleanup was PASS: the eight synthetic containers, four volumes and three networks
were removed. The synthetic dump and safe result metadata remain in the private
temporary backup directory for diagnosis; no production data was removed.

A second attempt `/tmp/byq-u6-5_lofi4s` stopped before builds/model calls because
the random temporary-directory underscore was not a valid Compose scope. Scope
generation now maps underscores to hyphens while retaining the strict allowlist;
its regression test passes. No test services were started by that attempt.

The corrected full diagnostic journey `byq-u5-u6-rn6hbbk0` completed PASS, with
cleanup PASS and exit code 0. Safe result metadata remains at
`/tmp/byq-u6-rn6hbbk0/result.json` and is summarized below. T38/T39 final release
qualification is still pending artifact identity/CI freeze; T40 remains NOT_RUN.
Diagnostic images cannot be used as certified promotion artifacts.

### Corrected diagnostic result

- Public conversation `conversation_2ff59392d0634fd986d4873c440fff53` survived
  old→new→old; fixed G5 follow-ups succeeded under both releases with unchanged
  domain object counts.
- Approval `agent_approval_6950474950a6478bb29b590c6e4f0d80` stayed queued during
  maintenance and continued under the candidate. A duplicate continuation request
  and rollback did not repeat its effect: one feedback, one fake intake/attempt,
  zero publications. Fake snapshot hash:
  `e6ba2fb5a71a59bdf408d39beb6c5c6882d49cd56fa074692dc4e4f93260ec80`.
- Actual old Runtime image:
  `sha256:b8266df0a2c2793a2ecc79b0f841e75742a9ac7cb38e233e55d664e28d3916d7`.
  Actual candidate Runtime image:
  `sha256:9419bfd84c99dce424f2d8dd24f54b01fe823a8f773b787deae03fc7ac7bc5eb`.
  These are local Docker image IDs, not registry digests or certified attestations.
- On each switch, all seven non-Runtime container IDs and start times remained
  unchanged. Each switch was preceded by closed admission and active prompts zero.
- Release namespace file digests were unchanged while the opposite release ran:
  old (1 file) `404b1c4e822a41549ceb22cef81f66ccb800634e4825f6780e502b9d5edc5d6e`;
  candidate (1668 files) `574ab7f5181d7fa75b8c2be012a8897410e539e025d97eb66eff5eef6e953239`.
  Cross-namespace writes observed: zero. No hidden state migration was performed.
- Logical dump: 270035 bytes, mode 0600,
  SHA-256 `cbac3d21eb76b30de4b2c6ac0fe5842683acda1ad67b7db4eab468d090d2d0d9`.
  Actual restore into isolated `byq_u6_restore` matched counts for all 105 public
  tables and validated all constraints. This is synthetic backup evidence only.
- After cleanup, independent exact-label queries confirmed zero containers
  (including stopped ones), networks and volumes. Test database data can be
  restored from the retained synthetic logical dump; image caches and metadata
  remain. Production resources and the real Hub record were not removed.

## Separately observed production state

A read-only container status listing at approximately 2026-09-06T12:40Z showed
the production ML, signal and data workers in restart loops. PostgreSQL, Backend,
MCP, Runtime, frontend and signal sandbox were stopped with exit code 0; Gateway
and feedback relay were healthy. No production container was changed or restarted
by U6. The cause and intent of that state are unknown. Production readiness must
not be claimed; restoring a healthy baseline and production deployment require
separate operator authority and preflight before U7.
