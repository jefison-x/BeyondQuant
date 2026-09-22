# Jev P3 bounded-decision benchmark v1

This directory contains a deterministic, offline benchmark for evaluating Jev / System One on the research-judgment portion of ADR-0085 P3. It does **not** call a model, production database, paid API, provider, workflow, order path, or production object store.

The numbers are synthetic perturbations anchored to repository schemas and test/evidence distributions. IDs and state are explicitly marked `offline_synthetic`. No row is a production observation.

## Scope boundary

Allowed questions cover strategy drafts, bounded backtest analysis, round comparison, revision proposals, evidence sufficiency, robustness and escalation. Workflow `next_action`, identity, approvals, idempotency, routing, recovery and continuation remain deterministic BYQ responsibilities and are represented only as refusal/calibration cases.

## Source inventory

| Data family | Repository basis | Reused shape/distribution |
|---|---|---|
| Backtest, risk-adjusted metrics, drawdown, costs, wins | `services/backend/app/backtest.py`; `services/backend/tests/test_backtest.py` | `backtest-analysis.v1`, total/benchmark/excess return, annualized return/volatility, Sharpe, Calmar, max drawdown, fee and slippage totals/ratios, trade counts, closed-trade win rate and profit factor; fixtures supply normal, empty and unavailable diagnostics. `derived_portfolio_turnover` is explicitly test-only and derived from bounded trade/cost summaries because the current analysis schema has no portfolio-turnover field. |
| Bounded analysis projection | `services/mcp/src/server.ts`; `docs/contracts/product-agent-run-guards.md` | Owner-scoped bounded summaries and call limits; raw result series and full signal snapshots are excluded. |
| Iteration and experiment comparison | `services/backend/app/learning_loop.py`; `services/backend/tests/test_learning_loop.py` | Evaluation signals with metric/value/artifact lineage and deterministic experiment comparison (fixture Sharpe 1.2 vs 0.8). |
| Regime, experts and model bundles | `services/backend/app/ml_regime.py`; `services/backend/tests/test_ml_training.py`; `services/backend/tests/test_ml_prediction.py` | `risk_on`, `neutral`, `risk_off`, `unknown`; HS300 point-in-time regime metrics; 2–4 expert bundle, validation RMSE/rank IC, fold and frozen-route lineage. |
| Research evidence and artifact lineage | `services/backend/app/research.py`; `docs/evidence/v090-composite-research/observations.v2.json` | Bounded `{kind,id}` lineage, validated artifacts, strategy/approval/signal/backtest relationships, real journey baseline vs candidate comparison. |
| Evidence completeness and failure values | `docs/evidence/v090-composite-research/acceptance-matrix.v2.json`; `verdict.v2.json` | Required PASS/BLOCKED truthfulness: a healthy route, label, fixture or page is not a substitute for business evidence. |
| Continuation failure boundary | `docs/evidence/harness-continuation-audit-20260922/README.md`; ADR-0085 | Historical oversized raw snapshot motivates bounded state and keeps Jev out of deterministic continuation. |

## Files and reproducibility

- `benchmark.v1.jsonl`: 60 stable cases, 10 per category.
- `decision-rubric.v1.json`: thresholds, precedence, scope, machine-readable rule IDs and the SHA-256 binding for the JSONL file.
- `validate_benchmark.py`: standard-library validation of schema, category balance, choices, expected result, escalation tags, source paths, payload bounds and secret/raw-snapshot exclusions.

Run from the repository root:

```bash
python3 tests/jev/validate_benchmark.py
```

## Useful calibration slices

- High-return and tiny-sample traps: `F01`, `F02`, `F03`, `F04`.
- Overconfidence / forced winner: `A02`, `A08`, `D02`, `D06`, `F10`.
- Escalation gate: `D01`–`D10`, especially the distinction between ambiguity (`D02`) and missing data (`D03`, `D07`).
- Missing abstention paired test: `F06` and `F07` share the same state, but only `F07` offers “证据不足”.
- Closest ADR-0085 P3 tasks: `A01`–`A10`, `C01`–`C10`, and regime analysis `E01`–`E10`.

The expected answer is an evaluation oracle, not a production policy. Revision choices are research proposals for a later offline round and never trading instructions.
