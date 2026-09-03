# Phase 85 Evidence

Phase 85 implements ADR-0048's domain/runtime closure for frozen HS300 regime evidence,
independent expert models, immutable ModelBundle and deterministic pre-Backtest routing.

## Implemented boundary

- `hs300-trend-volatility-v1` consumes only frozen `000300.SH` index-daily rows and emits
  `risk_on|neutral|risk_off|unknown` with inclusive, tested thresholds.
- Regime-enabled preparation freezes up to 120 calendar days before the declared development
  window for the 60-session warmup; no window-outside labels are created.
- One bounded TrainingRun stores a validated RegimeSnapshot, one independent ModelArtifact per
  expert, and one content-addressed ModelBundle with an explicit fallback.
- The trusted ML Worker dispatches exact Ridge/LightGBM formats. It never imports a client path,
  executes user source, deserializes pickle/joblib, accesses Provider credentials or reads DSH.
- Prediction validates every embedded hash and Artifact reference, routes only from the frozen
  snapshot, and records regime, expert and model identity per row.
- SignalSnapshot freezes bundle/regime/routing lineage. Backtest only consumes the frozen signal;
  it does not load models or recompute regimes/routes.
- Phase 85 does not expose a new Browser, MCP or Xiaoba entry. That Product closure is Phase 86.

## Verification

- ML strategy/registry/regime/router contract tests: 22 passed.
- Full Backend suite against a clean PostgreSQL instance: passed.
- Hardened ML Worker build/probe: passed with read-only root filesystem, dropped Linux
  capabilities and `no-new-privileges`.
- Tests cover warmup/missing benchmark, inclusive threshold order, future-row independence,
  route/bundle tamper rejection, independent expert Artifact persistence, deterministic ranking,
  v1 compatibility, restart lease fencing and owner/workspace isolation.

No Community file or database was modified. Community arbitrary ML imports and training inside
Backtest remain `REFERENCE_ONLY`/`DROP`.
