# D15 — DSH 0.1.5-rc.1 Native Continuity Upgrade Evidence

Status: **D15-0 complete; D15-1 candidate built, started and keylessly probed in
isolation; D15-2 session V3 migration qualified (PASS); D15-3 native session
resume qualified (PASS); D15-4..D15-G not started. No subagent/terminal/Go-No-Go
pass claims. `R3_RESUME = NO`.**

- Target decision: [`target-decision.v1.json`](target-decision.v1.json)
  (`dsh-v0.1.5-rc.1` / Python `0.1.5rc1` / bundled npm `0.1.5-rc.1`)
- Machine-readable upgrade delta: [`upgrade-recon.v1.json`](upgrade-recon.v1.json)
- Interface compatibility ledger: [`compatibility-ledger.v1.json`](compatibility-ledger.v1.json)
- Candidate declaration: [`../../config/dsh/candidates/dsh-0.1.5rc1/candidate.json`](../../../config/dsh/candidates/dsh-0.1.5rc1/candidate.json)
- D15-1 build/start/probe: [`d15-1/README.md`](d15-1/README.md)
- D15-2 session migration qualification: [`d15-2/README.md`](d15-2/README.md)
- D15-3 native session resume qualification: [`d15-3/README.md`](d15-3/README.md)
- Qualification fixture specification: [`fixtures/manifest.v1.json`](fixtures/manifest.v1.json)
- Realized fixture index (sha256): [`fixtures/sessions/index.v1.json`](fixtures/sessions/index.v1.json)
- Acceptance-criteria matrix (D15-2/D15-3 `PASS`, D15-4..D15-G `NOT_RUN`): [`acceptance-matrix.v1.json`](acceptance-matrix.v1.json)
- Stage plan / acceptance criteria: [`../../roadmap/DSH_015RC1_UPGRADE_PLAN.md`](../../roadmap/DSH_015RC1_UPGRADE_PLAN.md)

Production default remains `dsh-0.1.2rc1`. Nothing in this directory changes
the deployment selector, rebuilds the production runtime, or switches DSH.

## D15-0 — precise upgrade delta

The audit compares `0.1.2-rc.1` → `0.1.5-rc.2` on the interfaces BYQ depends on,
using byte-level diffs of the published npm packages and inspection of the
bundled Python runtime rather than release notes. The delta is carried onto the
decided `0.1.5-rc.1` qualification target; the upstream rc.2 GitHub release
changes only feedback-dialog and delivered-file card UI, outside these
interfaces. Status counts after the D15-1 keyless probe:

| status | count |
| --- | --- |
| changed | 12 |
| new | 5 |
| compatible | 9 |
| unknown-needs-probe | 0 |
| unchanged | 2 |

Notable must-change items:

- **Session storage is rewritten.** `dsh-session-persistence` drops
  `PersistenceCoordinator`/`write-behind`/`preparations` and introduces
  `SessionHandle` (read/append/flush/close) plus `SessionPersistence*Options`.
  Durability is only promised by `flush()`; `append()` is best-effort. BYQ's
  session/rehydrate path must adopt the handle/flush contract.
- **Cross-process write lease is new.** `SessionWriteLease` uses `flock(2)` on a
  `session.lock`; contention maps to `SessionAlreadyOwnedError`. A crashed
  holder does not block a successor.
- **Native Session V3 format and migration are new.**
  `dsh-session-format`, `dsh-session-format-catalog`,
  `dsh-session-format-v0-to-v1/v1-to-v2/v2-to-v3` ship a `sessionFormatV2ToV3`
  migration and fail closed on unknown versions
  (`SessionFormatUnsupportedError`, `sessionFormatVersionRefusal`).
- **Continuable subagents are new.** `dsh-subagent` adds
  `ContinuableActivationRegistry`, `Activation`, child inbox/admission,
  `startContinuable`, `sendMessage`, cold resume, settlement notices and lineage
  authorization. This is the native capability R3/R4 must not re-implement.
- **Persistent terminal is first-class.** `dsh-terminal`/`dsh-terminal-bash`
  existed before, but 0.1.5 bundles `dsh-tool-terminal`,
  `dsh-tool-bash-persistent`, `dsh-tool-pwsh-persistent`, `dsh-tmux-context`.
- **Provider/model adapter changed.** `dsh-llm-pi-ai` adds thinking-token-budget
  fields; `dsh-llm` adds `SystemMessage`/`FileBlock`/`SystemPromptUpdate`.

## D15-0-F1 — requested `0.1.5-rc.2` was not a coherent runtime pairing

`@deepseek-ai/dsh-*@0.1.5-rc.2` exists on npm (`next`), but PyPI publishes no
Python `deepseek-harness-sdk`/`runtime-bin==0.1.5rc2`. The published
`runtime-bin==0.1.5rc1` bundles npm **`0.1.5-rc.1`** (233 occurrences; zero
`0.1.5-rc.2`). An exact `0.1.5-rc.2` candidate would therefore have to splice a
non-bundled npm closure onto the shipped Python runtime. Per the task's
"do not silently bypass" rule this was recorded as an upstream packaging blocker,
not worked around.

**Maintainer decision (2026-09-19):** the qualification target is the coherent
official pairing — `dsh-v0.1.5-rc.1` / Python `0.1.5rc1` / bundled npm
`0.1.5-rc.1`. D15-0-F1 is resolved by decision
([`target-decision.v1.json`](target-decision.v1.json)); `0.1.5-rc.2` remains
not-a-coherent-pairing and is revisited only if upstream publishes a matching
Python runtime. All native-continuity surfaces (Session V3, continuable
subagent, persistent terminal) are present in the rc.1 bundle, and the Python SDK
public files are byte-identical to `0.1.2rc1`, so the adapter boundary can be
inherited unchanged while the native runtime is qualified.

## D15-1 — isolated candidate

- `config/dsh/candidates/dsh-0.1.5rc1/` holds a closed candidate declaration and
  Python lock. It is **outside** the immutable `config/dsh/releases` registry,
  which pins every release to an archived Git tree and must not be extended
  before qualification.
- `scripts/dsh/candidate_registry.py` validates the declaration and exposes the
  selector: `BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.5rc1`.
- `services/runtime-adapter/app/compat/dsh_015.py` + the `compat` route select
  the candidate boundary. The production default
  (`BYQ_DSH_COMPATIBILITY_RELEASE=dsh-0.1.2rc1`) is unchanged.
- Rollback is `dsh-0.1.2rc1`; no database change and no worker restart is
  permitted for this upgrade.

### Built, started and probed in isolation

The candidate image `byq-d15-1-0.1.5rc1-candidate:local`
(`sha256:96bf63272b988c049656d20e2390e60e21711d2c498e8c9ccf8ccd2af849371f`) was
built from `services/runtime-adapter/Dockerfile.dsh-0.1.5rc1-candidate` +
`requirements.dsh-0.1.5rc1-candidate.lock`, then started with `--network none`.
A keyless scripted turn (synthetic loopback MCP + scripted loopback provider)
reached `ready`/`idle`, exposed the expected product roster and emitted a
contiguous event sequence including `tool/call` and `tool/result`. Full evidence
and boundaries: [`d15-1/README.md`](d15-1/README.md).

The image is not pushed and not referenced by any production selector.

## D15-2 — session V3 migration qualification (format layer)

Nine immutable fixtures were committed under
[`fixtures/sessions/`](fixtures/sessions/index.v1.json) and qualified against the
real 0.1.5-rc.1 session-format catalog (`sessionFormatV2ToV3`). Eight migrate
(v0/v2 -> v3) and one (`f-continuable`) is already current; all nine complete
`read → resume → append → close → reopen` with contiguous sequences and
preserved message ids. The migrated store is **not downgradable** by
`0.1.2-rc.1`; fail-closed cases surface the documented refusal instead of
converting to a new session. Full detail and provenance:
[`d15-2/README.md`](d15-2/README.md).

This is **format-layer migration evidence only**: `resume` is
`Session.fromRestore`, `append` is hand-built/encoded events, and `close`/`reopen`
are file/codec operations. It is not proof of runtime/SessionHandle recovery,
unfinished-tool/subagent recovery, or AgentSession goal/approval/result
continuity.

The current harness computes an explicit invariant verdict
([`verdict.v3.json`](d15-2/verdict.v3.json)) and fails the process unless
manifest conformance (required fixture set count/uniqueness/no missing/extra and
the required rejection set, read from the single `requirements` block of
[`acceptance-matrix.v1.json`](acceptance-matrix.v1.json)), every required stage,
every invariant, every fail-closed rejection and every blocker passes. Required
evidence is never defaulted to an empty/passing value. The negative controls in
[`negative-controls.v3.json`](d15-2/negative-controls.v3.json) (17 controls)
prove empty/missing/duplicate/unexpected/missing-evidence/stage-failure faults
fail, and record the review repro `computeVerdict([], {cases:[one valid]})` as
pre-fix PASS -> post-fix FAIL. The v1 and v2 artifacts are preserved unchanged;
the v3 artifacts are additional.

The compatibility ledger's `session_format_v2_v3` interface now carries
`observed_status: "compatible"` and the migration item is moved from
`not_yet_probed` to `probed`. No native resume is claimed; `R3_RESUME = NO`
until D15-G.

## D15-3 — native session resume qualification

A new runtime generation can resume the SAME persisted DSH session natively
through the real 0.1.5-rc.1 session-persistence seam
(`SessionPersistence.open` + `SessionHandle`, cross-process `flock`
`SessionWriteLease`, `readColdSessionLog`). The isolated harness uses one OS
process per runtime generation and covers all eight failure-matrix rows: 3
`reattached` (browser/frontend/gateway, generation survives), 4
`rehydrated` via native resume (adapter restart, generation replacement, host
reboot, executor takeover), and 1 `interrupted` (DSH crash with a lost open run,
still natively resumable). A native-unavailable control (a session that never
reached the `flush()` barrier) is correctly not resumable and requires BYQ
conversation fallback. Full table, real-vs-simulated detail and the
native-vs-fallback conclusion: [`d15-3/README.md`](d15-3/README.md).

D15-3 proves the **native persistence-layer resumability** of a persisted DSH
session across a genuinely new OS process, using the shipped
`SessionPersistence`/`SessionHandle`/`SessionWriteLease`/`readColdSessionLog`
seam. The four service rows use real per-generation worker processes but a
**simulated** transport/lifecycle fault (no browser, frontend, Gateway or BYQ
runtime-adapter service is actually restarted), and D15-3 does **not** prove
semantic runtime recovery: the original goal is still on the runtime path, a
domain action is not duplicated, an approval remains valid, or a result remains
traceable end to end. That BYQ runtime-level continuity qualification (with real
services, persistence and domain assertions) is a required next step and is not
done here.

The ledger's `native_session_resume` interface is `compatible` (probed). Native
resume is viable enough that R3 must **not** re-implement it; the R3 freeze and
`R3_RESUME = NO` remain until D15-G.
