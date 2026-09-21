# 0.9 Closeout Governance & Gap Ledger (fact audit)

Status: **audit only — Draft PR, not merged, no implementation, no deployment, no
tag/release.** This batch performs a fact audit, a plan/STATUS revision, a
machine-readable acceptance matrix and the necessary audit tests.

Base commit (read dynamically): `origin/main` = `80fb9f809a6b796b7e98df23c19640286612a740`
("feat(data): P100-B Tushare index_dailybasic contract, storage, incremental sync and readiness (#337)").
Product Phase marker stays **97**. Worktree/branch: `codex/v090-closeout-audit`.

This audit deliberately does **not** implement Proposed ADR-0082/0083, does **not**
switch the production selector, does **not** deploy, and does **not** create or move
any tag/release.

## Deliverables in this directory

- [gap-ledger.v1.json](gap-ledger.v1.json) — machine-readable historical-evidence mapping to
  `covered | superseded | open | blocked`, with precise evidence paths and the base commit.
- [acceptance-matrix.v1.json](acceptance-matrix.v1.json) — machine-readable closeout acceptance
  matrix: formal 0.9.0 manifest requirements, remaining 0.9.x gates, the serial DSH
  0.1.5-rc.1 closeout slices with per-blocker owner/repro/acceptance/failure-closure, and the
  ADR-0082/0083 sufficiency items.
- [BETA-VS-FORMAL-0.9.0.md](BETA-VS-FORMAL-0.9.0.md) — `v0.9.0-beta` versus a formal 0.9.0
  closeout, and the missing formal-manifest items.
- [DSH-015RC1-CLOSEOUT-SLICES.md](DSH-015RC1-CLOSEOUT-SLICES.md) — the minimal serial DSH slices
  and the gating order to D15-G / R3 / R4 / R5 / R6 / independent production Go/No-Go.
- [ADR-0082-0083-SUFFICIENCY.md](ADR-0082-0083-SUFFICIENCY.md) — sufficiency review and the
  maintainer decision package. Both ADRs stay Proposed **at audit time**; the 2026-09-21
  step-4 maintainer decision later accepted them without implementing them.
- [gsplit-decision.v1.json](gsplit-decision.v1.json) — machine-readable record of the
  2026-09-21 step-5 `G-split` gate-order decision: B1 stays a mandatory external blocker,
  the strict internal order B2 → terminal-adapter-restart → terminal-dsh-runtime-restart is
  enabled, D15-G stays `NO_GO` until B1 PASSes, `R3_RESUME = NO`, and 0.9 is not closed.

The consistency of these files (schema, status vocabulary, evidence paths, the four
D15-G atomic blockers, the beta-vs-formal distinction and the frozen constraints) is
asserted by `tests/test_v090_closeout_governance.py`.

## Gap ledger vs VERSION_PLAN 0.9.0/0.9.x gates

The gate text is taken from [VERSION_PLAN](../../roadmap/VERSION_PLAN.md):

| Version | Deliverable | Completion gate |
|---|---|---|
| 0.9.0 | 为现有 Beta 建立统一产品版本和已知限制基线 | 发布清单绑定源码、镜像和实际服务组合，完成独立发布验收 |
| 0.9.x | 完整 F2、剩余全接口审计、复合研究故障回归 | Post-U8 各项有最新结论；不把 F6 完成或健康检查等同整体关闭 |
| 0.10.0 | S3、历史成分准备、可版本化特征与时点数据基础 | 真实数据基准可复现；同时完成 HIST 数据可行性及深度学习环境资格调查 |

S3 / historical constituent preparation belongs to the **0.10.0** row, **not** to 0.9. It is
removed from the 0.9 gate and from the 0.9 strict order.

Item-by-item result (business evidence, not old doc PASS or CI labels):

| Item | Status | Latest conclusion | Precise evidence (on the base commit) |
|---|---|---|---|
| F2 | **open** | Named child slices covered; no current whole-F2 closure | [F2 watch](../post-u8-f2-research-watch/AUDIT.md); [publisher pagination](../post-u8-interface-audit/AUDIT.md); [H4 asset-import idempotency](../research-handoff-h4/ASSET-IMPORT-IDEMPOTENCY.md); [H4 cross-process](../research-handoff-h4/CROSS-PROCESS.md) |
| S3 | **superseded → 0.10.0** | Historical Post-U8 fact was `blocked`; transferred to frozen Phase 100, does **not** gate 0.9 | [S3 preparation](../post-u8-r1/S3-HISTORICAL-PREPARATION.md); [H5 index preparation](../research-handoff-h5/INDEX-PREPARATION.md); [HIST qualification](../../roadmap/V1_HIST_DATA_QUALIFICATION.md); [Phase 99 execution](../phase-99/QUALIFICATION-EXECUTION.md) |
| full-interface audit | **open** | H4 ledger `complete=true` only at its own commit; `complete=false` now | [INTERFACE-REVIEW.json](../research-handoff-h4/INTERFACE-REVIEW.json); [CURRENT-INVENTORY.json](../research-handoff-h4/CURRENT-INVENTORY.json); [H4 integration](../research-handoff-h4/INTEGRATION.md); `scripts/ci/check-reliability-review.py` |
| composite research fault regression | **open** | Three-round live research covered; composite journey + R1–R5 fault matrix not executed | [remediation scope](../../roadmap/POST_U8_AGENT_RELIABILITY_REMEDIATION.md); [H5 live research](../research-handoff-h5/LIVE-RESEARCH.md); [H5 contract](../research-handoff-h5/COMPLETE-RESEARCH-CONTRACT.md) |
| H1–H5 | **covered** | H1–H5 completed; H5 real three-round research passed | [handoff plan](../../roadmap/RESEARCH_HANDOFF_PLAN.md); [H2](../research-handoff-h2/AUDIT.md); [H3](../research-handoff-h3/AUDIT.md); [H5](../research-handoff-h5/LIVE-RESEARCH.md) |
| U8 | **superseded** | `CLOSED_EARLY_REMEDIATION_REQUIRED`; not a stability PASS | [U8 observation](../dsh-012rc1/u8/OBSERVATION.md); [remediation scope](../../roadmap/POST_U8_AGENT_RELIABILITY_REMEDIATION.md); [ADR-0062](../../architecture/adr/ADR-0062-post-u8-reliability-boundaries.md) |
| D15 | **open** | D15-G `NO_GO`; four atomic required capabilities BLOCKED | [D15-G verdict](../d15/d15-g/verdict.v1.json); [capability matrix](../d15/d15-g/capability-matrix.v1.json); [D15-G decision input](../d15/d15-g/decision-input.v1.json); [D15 plan](../../roadmap/DSH_015RC1_UPGRADE_PLAN.md) |

Summary: **covered 1, superseded 2, open 4, blocked 0** (top-level items). S3 is not a 0.9
gate item; it is listed under `deferred_to_0_10` in the machine-readable ledger.

The corrected **0.9 strict order does not start with S3**: it starts with this audit, then
full-interface re-baseline, then the composite fault regression, then ADR-0082/0083 decisions,
then the D15 pre-gate remediation slices. See [acceptance-matrix.v1.json](acceptance-matrix.v1.json)
`serial_order` and `dag`.

### Why the "full-interface audit" is not covered

The H4 ledger recorded `reviewed=560, verified=560, complete=true` at its own commit and
was cited as the whole-interface closure. On the base commit the same trusted tool now
reports:

```
python3 scripts/ci/check-reliability-review.py
  discovered 566, reviewed 560, verified 560, unreviewed 6, complete false
  errors: source drift across Backend/Gateway/MCP/Worker entries
```

The tool exits 0 without `--require-complete`; it is a read-only reporter, not a CI
pass. Source drift is the evidence that the ledger must be re-baselined before it can
support a 0.9.x closure. This is exactly why the audit does not accept the historical
`complete=true` label as current business evidence.

### Why F2 is not covered even though its child slices are

The three MCP research creation families have their own committed qualification
([F2 watch](../post-u8-f2-research-watch/AUDIT.md), 30/30 plus a real restart probe and
browser journeys), and the publisher pagination defect is locally verified
([F2-PUB-01](../post-u8-interface-audit/AUDIT.md)). But "完整 F2" spans every write
interface, and the interface-level reconciliation claim lives in the now-stale H4 ledger.
Whole-F2 is therefore **open** pending a current re-baseline.

### Why S3 is 0.10, not a 0.9 gate

S3 / historical constituent preparation is a **0.10.0** deliverable
([VERSION_PLAN](../../roadmap/VERSION_PLAN.md)). The historical Post-U8 investigation is a
`blocked` fact (real read-only source unavailable; a single static snapshot is explicitly
**not** a historical change-over-time series), but under **ADR-0068 / AGENTS rule 21** a
missing Community source is **not** a development blocker and no Community exemption is
required. It is therefore transferred to the frozen 0.10 Phase 100, to be resolved with
Tushare P100-C/P100-D point-in-time evidence — **no** current-relation backfill. It is
**superseded-to-0.10**, removed from the 0.9 strict order, and must not precede or block the
0.9 closeout.

### DAG / owner rule (no cycles)

Every D15-G atomic blocker's implementation owner is a **pre-gate D15 candidate-qualification**
node, never a post-gate R-series node. This removes the former `B1 → R6` and `B3/B4 → R4`
cycles. B1 `subagent-child-crash` is additionally an **external blocker** in DSH 0.1.5-rc.1
(no out-of-process continuable provider), so the maintainer decision package includes a
gate-order option (`G-keep` / `G-split` / `G-reorder` / `G-reclassify`); a strict serial
order is claimed only for internally ownable items. See
[DSH-015RC1-CLOSEOUT-SLICES.md](DSH-015RC1-CLOSEOUT-SLICES.md) and the machine-readable `dag`.

### Why U8 is superseded, not covered

U8 was closed early with the 24-hour gate **waived, not passed** (78 samples / 4h25m) and
semantic acceptance **failed**. It was deliberately replaced by ADR-0062 and the Post-U8
R1–R5 / S1–S3 / F1–F10 remediation. It is not a stability pass.

## Constraints frozen by this audit

- `R3_RESUME = NO`; production selector/default `dsh-0.1.2rc1`; deployment `none`.
- At audit time ADR-0082 and ADR-0083 were **Proposed, not accepted, not implemented**.
  The 2026-09-21 step-4 maintainer decision accepted them (ADR-0082 modified — Option 1
  only, Option 2 rejected; ADR-0083 as proposed) but **implemented neither**; the D15-G
  blockers remain unresolved and 0.9 is not closed. See
  [../v090-adr-decisions/README.md](../v090-adr-decisions/README.md).
- No tag/release is created or moved; the historical `v0.9.0-beta` tag is untouched.
- The paused `codex/phase-100c` branch (Draft PR #338) is **not** delivery and is not
  touched by this audit.
