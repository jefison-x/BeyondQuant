# DSH 0.1.2rc1 U0 baseline and test record

Date: 2026-09-06

Observed Git base: `origin/main` at `6168fde45b3e72849435edeabf2a055ddfdaceb2`.
Branch/worktree: `docs/dsh-u0-compatibility-decision` in the dedicated U0 worktree.

## Authorization boundary

The maintainer authorized U0 development, push and a Draft PR. After reviewing this evidence, the
maintainer explicitly accepted ADR-0058 and authorized recording U0 as `VERIFIED`. Merge,
production deployment, production/default version switching, paid-model testing and U1 remain
explicitly unauthorized; PR #250 remains Draft.

## Old 0.1.1rc1 baseline

| Scenario required by U0 | Evidence layer | Result | Evidence/limitation |
|---|---|---|---|
| Startup and identity | actual deployed runtime, read-only observation | PASS | healthy exact SDK/runtime/image/profile/composition; zero active sessions at observation |
| Read-only MCP | prior isolated real DSH + live test MCP (Phase 63) and current L0 tests | PASS | Phase 63 named stack initialized, exercised MCP lifecycle and cleaned resources; no production model call was made in U0 |
| Root/child lifecycle | MOCK/L0 | PASS | Runtime Adapter process/normalization suite covers owned session, trusted descendant activity, timeout and cleanup |
| Long reasoning/quiet-window behavior | MOCK/L0 | PASS | controlled-clock watchdog cases preserve useful activity and 900/180/120 defaults without waiting 900 seconds |
| Terminal failure | MOCK/L0 | PASS | error finish, startup/crash/cancel and fresh-runtime recovery cases pass |
| Public-context recovery | MOCK/L0 plus prior Product evidence | PASS | durable completed public messages rehydrate a fresh generation; no private DSH log migration |
| Old paid/live-model fixed scenarios G1–G6 | LIVE/L3 | NOT_RUN | expressly outside U0 authorization; no model budget/credential used |
| Ten-run keyless performance/RSS baseline | L1 | NOT_RUN | belongs to final old/new candidate fixture in U5; U0 did not yet implement a release-selectable runner |

Historical runtime evidence: [`phase-63/qualification-report.md`](../../phase-63/qualification-report.md).
It is cited only for the old qualified baseline, not copied as 0.1.2rc1 qualification.

## Tests run in this worktree

| Command/check | Layer | Result |
|---|---|---|
| `python3 -m unittest discover -s tests/architecture -p 'test_*.py'` | L0 | PASS, 104 tests |
| `python3 -m unittest discover -s tests -p 'test_dsh_*.py'` | L0 | PASS, 15 tests |
| `python3 scripts/dsh/plugin_registry.py validate` | L0 | PASS |
| `python3 scripts/dsh/plugin_registry.py build --check` | L0 | PASS, generated composition unchanged |
| current runtime image: Node time tests + Runtime Adapter pytest | real old artifact + L0 fixtures | PASS, 3 Node + 66 Python tests; 2 existing FastAPI deprecation warnings |
| old manifest with exact new npm version resolution | isolated dependency install | expected FAIL, unforced Cordis peer conflict documented in `UPSTREAM.md` |
| exact 0.1.2rc1 bundled runtime + scripted model/MCP | L1 | PASS; see `CARRIER.md` |

The host lacked `pytest`, so the runtime suite ran in an automatically removed container based on
the already-built exact old image and mounted U0 worktree sources, matching the repository CI test
entry point. The first read-only-mount attempt failed before test execution because nested Docker
mountpoints could not be created; the automatically removed retry used the existing CI mount shape.
Neither outcome changed a running service.

## U0 applicability against the test matrix

U0 establishes preliminary T01 artifact identity/download evidence, negative T04 peer-resolution
evidence, T12 public launcher/initialize/prompt/shutdown feasibility, and T23/T27 roster/time-hook
feasibility. It does not mark T01–T30 qualified: deterministic descriptors, SBOM, release selection,
full role roster, contained-path negatives, adapter integration and isolated Product stack are U1–U5
deliverables. T31–T40 and all production/live-model checks are `NOT_RUN` at U0.

## Resource and deployment result

The loopback fixture processes and one-off test containers were stopped/removed. The exact
448 MiB U0 temporary directory containing downloaded wheels, extracted runtime, source checkout
and synthetic logs was deleted after the hashes/results above were recorded; none of it was
committed. No image, volume, network, database, service, credential, Product phase, active release
or production default was changed. Rollback is therefore not applicable; 0.1.1rc1 remains the
deployed/default baseline.
