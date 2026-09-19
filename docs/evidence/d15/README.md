# D15 — DSH 0.1.5-rc.1 Native Continuity Upgrade Evidence

Status: **D15-0 complete; D15-1 candidate built, started and keylessly probed in
isolation; live qualification (D15-2..D15-G) not started. No pass claims.**

- Target decision: [`target-decision.v1.json`](target-decision.v1.json)
  (`dsh-v0.1.5-rc.1` / Python `0.1.5rc1` / bundled npm `0.1.5-rc.1`)
- Machine-readable upgrade delta: [`upgrade-recon.v1.json`](upgrade-recon.v1.json)
- Interface compatibility ledger: [`compatibility-ledger.v1.json`](compatibility-ledger.v1.json)
- Candidate declaration: [`../../config/dsh/candidates/dsh-0.1.5rc1/candidate.json`](../../../config/dsh/candidates/dsh-0.1.5rc1/candidate.json)
- D15-1 build/start/probe: [`d15-1/README.md`](d15-1/README.md)
- Qualification fixture specification: [`fixtures/manifest.v1.json`](fixtures/manifest.v1.json)
- Acceptance-criteria matrix (D15-2..D15-G, all `NOT_RUN`): [`acceptance-matrix.v1.json`](acceptance-matrix.v1.json)
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
| compatible | 8 |
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

The image is not pushed and not referenced by any production selector. No live
native migration or resume claim is made; `R3_RESUME = NO` until D15-G.
