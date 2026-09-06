# U3 Runtime compatibility seam

Status: VERIFIED locally; GitHub checks and merge must be confirmed separately. Date: 2026-09-06.
Worktree: /home/jefison/projects/.byq-worktrees/dsh-u3-runtime-compatibility-seam.
Branch: refactor/dsh-u3-runtime-compatibility-seam.
Observed base: 11a2d503213012acfe6e8dbb162f5358736e2a23 (U2 PR #253).

## Authorization and scope

The maintainer authorized U1-U8 sequential development, push/Draft PR and
CI-green auto-merge under ADR-0015/0059, and asked development to continue
through the remaining stages. Production deployment and the formal default
release switch remain outside this authorization.

Default DSH remains Python 0.1.1rc1 / npm 0.1.1-rc.1. This stage extracts and
validates the old-release compatibility boundary only; it does not adapt,
qualify or activate 0.1.2rc1. Product Phase 97 is unchanged.

## Implementation and boundaries

- `compat/dsh_011.py` is the sole Runtime Adapter module importing the DSH SDK,
  constructing its exact public configuration, invoking start/prompt/close and
  reading raw notification payloads.
- Immutable Adapter-private `RuntimeObservation` values carry only normalized
  lifecycle, liveness, terminal, answer candidate, tool-result and bounded
  usage fields. Reasoning text, raw tool arguments and raw notifications do not
  cross the compatibility boundary or enter WorkflowTrace.
- RuntimeAdapter retains process/session ownership, locking, one-active-prompt,
  idempotency, watchdogs, cancellation and cleanup. Public projection remains
  BYQ-owned and consumes observations without importing DSH.
- Notification callbacks are bound to the active run and private runtime
  generation. A callback from a completed run or replaced generation is
  discarded before it can refresh liveness, usage or public history.
- Existing 900/180/120-second production defaults, delegated-child handling,
  fail-closed terminal mapping, public schemas and approval state machines are
  unchanged. No cross-service protocol or second agent harness was introduced.
- The old release descriptor now hashes every compatibility implementation
  input. Deployment identity and web-evidence attestations were regenerated
  from the checked generators; the default and qualified producer remain the
  old release.

## T12-T22 evidence

| Requirement | Evidence and layer |
|---|---|
| T12 | Compatibility lifecycle test covers public SDK start/session prompt/close; the full old-release image build and keyless Compose smoke initialize and exercise the installed SDK/runtime (L0/L1). |
| T13 | Existing process-cleanup tests cover one active prompt and running/completed idempotency; full Runtime suite passed (L0/L1). |
| T14 | Reasoning/text chunks and step boundaries refresh private liveness while no reasoning content enters history; normalization/compatibility tests preserve the public answer boundary (L0/L1). |
| T15 | Existing deterministic no-progress tests close only the owned harness and preserve the other session; failure remains a public failed terminal (L0/L1). |
| T16 | Delegated calls retain their dedicated timeout, completion correlation and duplicate-safe removal; descendant activity is private (L0/L1). |
| T17 | New `test_late_notification_from_previous_run_cannot_extend_next_run` binds callbacks to their run/generation. Existing unrelated-session, malformed, heartbeat and descendant cases remain green (L0/L1). |
| T18 | Whole-run timeout wins despite activity, defaults remain 900/180/120, and existing race/late-result tests keep one terminal outcome (L0/L1). |
| T19 | Compatibility tests drop reasoning and raw arguments, suppress tool-bearing narration and child text; normalization, SSE, Gateway and real browser suites preserve bounded public schemas (L0/L1/L2). |
| T20 | Error and unknown turn reasons map to failed; max-token and failed-result normalization regressions remain green (L0/L1). |
| T21 | Run/generation binding plus existing duplicate message/usage, queued delivery and rehydration tests prevent stale completion, replay and double counting (L0/L1). |
| T22 | Runtime cleanup suite and full Compose smoke cover soft/hard cancel, startup/crash paths, owned close and adapter restart with no retained scoped resources (L0/L1). |

The architecture suite additionally asserts that `deepseek_harness` imports and
`notification.payload` reads occur only in `compat/dsh_011.py`.

## Validation runs

1. Targeted old-release Runtime Adapter container suite:
   `pytest -q`; 73 passed with two existing FastAPI deprecation warnings.
2. Root repository suite:
   `python3 -m unittest discover -s tests -p 'test_*.py'`; 140 passed.
   The architecture-only subset passed 105 tests.
3. Generated identity checks:
   `python3 scripts/dsh/release.py check` and
   `python3 scripts/dsh/web_evidence_provenance.py check`; both passed after
   regenerating the derived files from the changed old-release build inputs.
4. Full changed-component local CI:
   `scripts/ci/local-ci.sh --base=origin/main --with-e2e --auto-smoke`.
   Scope `local-3475648`; exit 0 and all 24 checks passed. Component results
   include architecture 140, Backend 331 (1 skipped, 7 subtests), Gateway 86,
   Runtime Adapter 73, complete MCP contracts, frontend unit/build checks,
   20 mocked browser tests and 9 real Product API browser tests. Full Compose
   smoke exercised the actual old keyless DSH lifecycle, persistence restart,
   MCP/Gateway boundaries, Phase 74/90 restart isolation and Phase 48 no-mock
   two-user Product coherence.

Two earlier diagnostic full-CI attempts stopped on correctly detected stale
release/provenance generated identity and are not counted as final evidence.
The generators were run, the executable source then stayed fixed for the final
24-check run. All three diagnostic/final CI scopes left zero containers,
networks and volumes.

No remote CI or merge result is claimed in this pre-PR record. Verify the PR
head, required checks and merge from GitHub rather than inferring them here.

## Limits

No paid/live-provider model call was required for U3: the compatibility risk is
covered by the actual old SDK/runtime keyless process plus deterministic
lifecycle fixtures. The 0.1.2rc1 candidate runtime has not been started or
adapted; that begins only after U3 merges, in U4. No production services,
credentials, domain data or default release were changed.
