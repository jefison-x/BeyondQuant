# D15-G architecture Go/No-Go

- Verdict: **NO-GO (NOT-PASS)** — the decision is honest and valid; it is not a
  qualification pass.
- Date: 2026-09-20
- Candidate: coherent `dsh-0.1.5rc1` / Python SDK `0.1.5rc1` / bundled npm
  `0.1.5-rc.1`
- Scope: architecture decision over D15-2..D15-5 only. It does not accept or
  implement the Proposed ADR-0082/0083, does not open R3, and does not change the
  production DSH selector/default or deploy anything.
- `R3_RESUME = NO`; production selector `dsh-0.1.2rc1` (unchanged).

## Read this first

| artifact | what it is |
| --- | --- |
| [`decision-input.v1.json`](decision-input.v1.json) | the D15-G report: claimed verdict, per-capability statuses, named blockers |
| [`capability-matrix.v1.json`](capability-matrix.v1.json) | the D15-2..D15-5 capability/failure matrix with per-item DSH-native result / BYQ fallback / R-series owner |
| [`provenance.v1.json`](provenance.v1.json) | sha256 + introducing commit for every reused source evidence file |
| [`verdict.v1.json`](verdict.v1.json) | fail-able observer output: independently derived `verdict=NO_GO`, `decision_valid=true` (the NO_GO is honest), `all_pass=false` (NOT-PASS), `go_granted=false`, exit 1 |
| [`negative-controls.v1.json`](negative-controls.v1.json) | selfcheck: known-good GO fixture passes; 14 controls all rejected (13 defect-targeting) |
| contract + observer | `scripts/d15/go_no_go/contract.v1.json`, `scripts/d15/go_no_go/observer.py`, `scripts/d15/go_no_go/build_provenance.py` |

## The Go/No-Go contract and fail-able observer

D15-G is a **decision**, not a qualification. The observer is the Go-gate: it
exits 0 only when the decision is valid and honest **and** every required
capability is actually `PASS` (GO). A truthful NO-GO is `decision_valid=true`
but `all_pass=false` (NOT-PASS) and exits non-zero. The observer fails
(non-zero) when a report is invalid or dishonest:

- `format_valid` — the decision artifact is well formed and every required source
  evidence file exists and matches its `provenance.v1.json` sha256.
- `honest` — every claimed capability status, the claimed verdict and the claimed
  blocker set equal what the observer **independently derives** from the committed
  D15-2..D15-5 evidence. A report may not declare its own verdict or coverage.
- `verdict` / `go_granted` — GO is granted **only** when every required
  capability is actually `PASS`. One `BLOCKED`/`NOT_RUN`/`FAIL` required
  capability forces `NO_GO` and must be named as a blocker.
- `all_pass` — `decision_valid` **and** `go_granted`; the stage is NOT-PASS here.

The observer rejects, non-zero:

1. `claim-go-on-partial-sources` — a partial report claiming GO
   (`aggregation_rejected=true`; legacy result-trusting gate would pass);
2. a required capability claimed `PASS` while its source says `BLOCKED`/`FAIL`;
3. a blocker missing from the named blocker set;
4. a claimed capability set that is not the closed required set;
5. missing or hash-mismatched source evidence;
6. self-declared `go_authorized`/`coverage` fields;
7. candidate/decision-vocabulary violations.

`negative-controls.v1.json` records 14 controls, all rejected by the fixed
observer; **13 are defect-targeting** (the reconstructed pre-fix algorithm that
trusted the report's own verdict/claims passed them). The known-good all-PASS
synthetic fixture yields an honest `GO` and passes, proving the gate is not
simply always-fail.

## Verdict: NO-GO

Because a required capability that is not PASS must force NO-GO, and the
following required capabilities did not pass, the derived verdict is **NO_GO**:

| capability | derived | layer |
| --- | --- | --- |
| root-session-persistence | PASS | D15-2/D15-3 |
| process-restart-resume | PASS | D15-3/D15-3R |
| host-reboot-resume | NOT_RUN | D15-3 (persistence model only) |
| fork-continuity | PASS | D15-4 |
| subagent-resume | BLOCKED | D15-4 |
| subagent-child-crash | BLOCKED | D15-4 |
| subagent-byq-adapter-restart | BLOCKED | D15-4 |
| terminal-client-reattach | PASS | D15-5 |
| terminal-persistence | BLOCKED | D15-5 |
| terminal-adapter-restart | BLOCKED | D15-5 |
| terminal-dsh-runtime-restart | BLOCKED | D15-5 |

**Primary named blockers:** `subagent-child-crash`,
`subagent-byq-adapter-restart`, `terminal-adapter-restart`,
`terminal-dsh-runtime-restart`. **Secondary:** `host-reboot-resume` `NOT_RUN`.
The aggregate capabilities `subagent-resume` and `terminal-persistence` are
`BLOCKED` because they contain those required items.

### Why the passing layers do not make this a GO

D15-2 is format/codec migration only. D15-3 is persistence-layer resumability in
one OS process per generation. D15-3R is a scripted keyless service-boundary pass.
D15-4 PASSes six native subagent scenarios but its `child-crash` and BYQ
`adapter-restart` required items are BLOCKED. D15-5 PASSes four client-side
terminal rows but its `adapter-restart` and `dsh-runtime-restart` required rows
are BLOCKED. Aggregating any of these into a GO would be exactly the
partial-PASS-aggregation defect the observer rejects.

## What a GO would and would not mean

A future GO would mean DSH 0.1.5-rc.1 native continuity is adoption-ready. It
would **not** authorize a production cutover: "BYQ compatible with DSH
0.1.5-rc.1" and "production default = DSH 0.1.5-rc.1" are independent decisions
(ADR-0081 §6). GO also does not accept ADR-0082/0083, which remain Proposed and
unimplemented.

## Constraints (confirmed)

- `R3_RESUME = NO`; R3 remains frozen.
- Production default selector `dsh-0.1.2rc1`, `compose.yml` and
  `deployment.json` are unchanged.
- Proposed ADR-0082/0083 are **not accepted and not implemented**.
- No deployment, release, tag, paid run, production change or host reboot.

## Reproduce

```bash
python3 scripts/d15/go_no_go/observer.py --selfcheck \
    --out docs/evidence/d15/d15-g/negative-controls.v1.json
python3 scripts/d15/go_no_go/observer.py \
    --decision docs/evidence/d15/d15-g/decision-input.v1.json \
    --provenance docs/evidence/d15/d15-g/provenance.v1.json \
    --out docs/evidence/d15/d15-g/verdict.v1.json
```

The provenance record is generated create-only with
`python3 scripts/d15/go_no_go/build_provenance.py --out docs/evidence/d15/d15-g/provenance.v1.json`.
