# Phase 79 acceptance evidence

Phase 79 closes the Product Agent path from an approved LightGBM model through
sample-out prediction, immutable signal production and the existing Backtest
task facade. It does not introduce a second workflow, allow DSH to read model
objects or raw rows, or move ML strategy approval into the Agent.

## Automated acceptance

- `scripts/ci/local-ci.sh --all --build --with-e2e --with-smoke`: all checks
  passed after correcting the CI-only default credential keyring value.
- Corrected frontend/full-stack acceptance profile: all 14 checks passed.
- Real Product API browser suite: 6/6 passed, including the LightGBM journey.
- ML Worker restart preserved the same training, model, prediction and signal
  identities; a second user could not observe the owner's resources.
- Phase 48 no-mock two-user Product coherence remained green.
- Backend, MCP, runtime normalization, role authorization, SDK compatibility,
  product capability catalogue and generated-composition checks passed.

The verified owner identities were:

- training: `mlrun_2ca7c99e90da487d9cf523b407093540`
- model: `artifact_a355b5c0dd9f493984926bfa86d35f2d`
- prediction: `mlpred_d762b8473dcd4960b6f0b80c241330b5`
- prediction artifact: `artifact_be58198e10ad4f31a90a930c9b318bf3`
- frozen signal: `artifact_54db1d22821743119948b400b0767f58`

## Browser and behavior acceptance

The Chrome MCP review is recorded in `CHROME_MCP_REVIEW.md`; Community
classification is recorded in `community-feature-checklist.md`. The E2E and
Chrome captures in this directory show the completed desktop/mobile workflow.

The Xiaoba behavior boundary was evaluated at three levels:

| User intent | Agent behavior | Evidence |
|---|---|---|
| Explain how to use ML/backtest | read-only product guide and capability query; no domain mutation | product-guide skill validation, MCP help/catalogue tests |
| Prepare ML work | capability/workspace lookup and explicit missing prerequisite response | ML role/skill contract, workspace projection tests |
| Execute closed research | separately approved prediction create, derived ML Backtest task get/execute/cancel | MCP translator/tool tests and PostgreSQL prediction-to-backtest integration test |

This is a keyless contract/real-domain behavior evaluation: it validates the
same MCP tools, approvals, owner scope and WorkflowTrace projections used by the
Product runtime without substituting an external model provider for BYQ domain
execution.
