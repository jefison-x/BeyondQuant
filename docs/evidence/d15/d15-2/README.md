# D15-2 — Session V3 migration qualification

Status: **PASS at the session-format layer only.** This proves that historical
D15 fixtures are decoded, migrated to V3, encoded, fsynced and re-read without
losing sequence, ids or context evidence. It does **not** prove runtime recovery,
SessionHandle/`flush()` durability, live lease behavior, or that a real
AgentSession keeps its original goal, does not duplicate a domain action, keeps a
valid approval, or stays result-traceable after a process/host fault. Those are
deferred to a real isolated runtime qualification (D15-3 native seam and the
still-unrun D15-4..D15-G, plus a BYQ runtime-level continuity run). No native
resume (D15-3), subagent continuity (D15-4), persistent terminal (D15-5) or
Go/No-Go (D15-G) claim. Production default remains `dsh-0.1.2rc1`; R3_RESUME = NO.

- Fixture index (immutable, sha256): [`../fixtures/sessions/index.v1.json`](../fixtures/sessions/index.v1.json)
- Migration results (current, invariant-checked verdict): [`migration-results.v2.json`](migration-results.v2.json)
- Compact verdict: [`verdict.v2.json`](verdict.v2.json)
- Fail-closed results (current): [`fail-closed.v2.json`](fail-closed.v2.json)
- Negative controls proving the verdict/exit code fail closed: [`negative-controls.v2.json`](negative-controls.v2.json)
- Historical format-layer evidence (preserved, unchanged): [`migration-results.v1.json`](migration-results.v1.json), [`fail-closed.v1.json`](fail-closed.v1.json)
- Harness: [`../../../../scripts/d15/harness/migration_harness.mjs`](../../../../scripts/d15/harness/migration_harness.mjs)
  + [`migration_verdict.mjs`](../../../../scripts/d15/harness/migration_verdict.mjs)
  + [`migration_negative_controls.mjs`](../../../../scripts/d15/harness/migration_negative_controls.mjs)

## What was qualified

For every committed fixture the harness copies the immutable original to a
fresh scratch directory, runs the **real DSH 0.1.5-rc.1 migration path** through
the first-party catalog (`@deepseek-ai/dsh-session-format-catalog`, which
dispatches to `sessionFormatV2ToV3`), then exercises
`read → resume → append → close → reopen` and records the result.

| fixture | category | source format | migration | read | resume | append | close | reopen | downgradable |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| f-normal | normal | v0 (REAL) | migrated | pass | pass | pass | pass | pass | no |
| f-completed | completed | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-interrupted | interrupted | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-compacted | compacted | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-large | large | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-subagent | subagent | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-continuable | continuable-subagent | v3 | current | pass | pass | pass | pass | pass | no |
| f-forked | forked | v2 | migrated | pass | pass | pass | pass | pass | no |
| f-old-lifecycle | with-old-lifecycle-evidence | v2 | migrated | pass | pass | pass | pass | pass | no |

Summary from `migration-results.v2.json`:
`fixture_count=9, migrated_count=8, current_count=1, blocked_count=0,
all_post_migration_stages_pass=true, downgradable_count=0,
non_downgradable_count=9`, and the invariant verdict `all_pass=true`
(`exit_code=0`).

### Verdict integrity and negative controls

`migration_verdict.mjs` turns the observed evidence into an explicit gate over
every required invariant: migration completion, sequence continuity, id
continuity (session id + `missing_from_target` + `missing_from_reopen`),
context preservation (system prompts / provider-models), append+reopen,
non-downgradability, no blockers, and every fail-closed rejection case. The
harness process exits `0` only when `verdict.all_pass` is true; fail-closed
rejections and every blocker now count.

`negative-controls.v2.json` runs the real harness CLI once per injected fault and
records the observed exit code and verdict. For the sequence / ids / context /
reopen / blockers / fail-closed faults all stage statuses still pass, so
`legacy_exit_code=0` is recorded alongside `exit_code=1` and
`all_pass=false`: that is direct proof the pre-fix stage-only gate would have
reported PASS on a broken invariant. A real `blocked_migration` control (an
unclassified event injected into the configured source) fails through the actual
pipeline with `blocked_count=1`.

### Fixtures and provenance

- **f-normal is real.** It was produced by running the official DSH
  `0.1.2-rc.1` bundled runtime in isolation (keyless synthetic loopback provider
  and MCP, `--network none`) through the BYQ runtime adapter, then decompressing
  the released-v0 multi-frame zstd log losslessly to raw JSONL. The original
  compressed artifact is retained as `session.origin.zstd`
  (`sha256:54a461dc...`) alongside the raw `session.jsonl`
  (`sha256:a17a7226...`).
- The remaining fixtures are **deterministic released-v2 artifacts** encoded
  with the official 0.1.5-rc.1 `releasedV2SessionFormatCodec`, except
  **f-continuable**, which is a v3 current-format child produced by running the
  real catalog migration over a v2 subagent base and re-encoding with the
  released v3 codec. The continuable activation descriptor is deferred to
  D15-4.
- **f-old-lifecycle** carries a synthetic BYQ lifecycle-evidence sibling. The
  harness only ever reads `session.jsonl`; it never reads or mutates the BYQ
  lifecycle journal (asserted by test).

### Version-bump decision

D15-2 adds test code, fixtures and evidence. `scripts/` and `tests/` are part of
the BYQ build-input inventory, so per repository rules the production build
revision advances `post-u8.147` → `post-u8.148`. This is an inventory/rebuild
identity bump only: no selector, `compose.yml`, `deployment.json` or 0.1.2
artifact/evidence changes and no deployment.

## Harness scope and boundary

The harness operates at the **session-format catalog layer**. The
`SessionHandle` persistence backend (`dsh-session-persistence-jsonl`) delegates
historical decoding and migration to this catalog, so the migration path
exercised here is exactly the one the runtime uses on a write open. Because the
harness does not run a live `SessionWriteLease`/worker-thread publication:

- `resume` is validated through the installed `Session.fromRestore` (the same
  call the catalog's `restoreCurrent` uses);
- `append` encodes real v3 events with `encodeCurrentEvent`;
- `close` is an `fsync` of the resulting `session.v3.jsonl` generation;
- `reopen` re-reads and re-validates through the installed `Session`.

The `SessionHandle.flush()` durability barrier and live lease behavior are
D15-3/D15-5 concerns; D15-2 qualifies the format boundary that those stages
depend on.

**This is format-layer evidence, not runtime recovery.** Concretely, the four
steps above are `Session.fromRestore`, a hand-built `encodeCurrentEvent` append,
a file `fsync`, and a file re-read. No BYQ runtime adapter, Gateway, DSH process,
`SessionHandle`, `SessionWriteLease`, worker-thread publication, AgentSession,
approval record, domain action or result object is exercised. D15-2 therefore
cannot support any claim about process recovery, original-goal survival,
domain-action at-most-once, approval validity or result traceability; those
remain the required next step for a real isolated runtime qualification and are
not satisfied here.

## Fail-closed semantics

`fail-closed.v1.json` records four refusals. In every case
`treated_as_new_session=false` and `successor_generation_written=false`:

| case | catalog status | surfaced error | documented refusal |
| --- | --- | --- | --- |
| unknown-future-format (v99) | unsupported | `SessionFormatUnsupportedMigrationError` | yes |
| unclassified-event | migration-required | `SessionFormatUnsupportedMigrationError` | yes |
| malformed-header | malformed | `SessionFormatError` | yes |
| refused-surface-migration | migration-required | `SessionFormatUnsupportedMigrationError` | yes |

A migration failure therefore surfaces the documented refusal and is recorded
as a blocker; it is never converted into a fresh session.

## Downgrade feasibility

**Not downgradable (9/9).** DSH `0.1.2-rc.1` predates the `dsh-session-format`
family entirely and selects the log by generation filename (`session.jsonl` /
`session.v2.jsonl`). The migrated v3 header is refused both by the released v2
physical codec (`releasedV2SessionFormatCodec.decodeHeader`) and by a simulated
v2-max migration chain, and the successor is written as `session.v3.jsonl`,
which a 0.1.2 reader does not select. Rollback must therefore restore the
original historical generation, not read the migrated one.
