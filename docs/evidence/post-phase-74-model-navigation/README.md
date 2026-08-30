# Post-Phase 74 model navigation and strategy labels

This Product UI maintenance moves the existing quant ML workbench out of personal settings and into the primary business navigation, while making every strategy-editor input identifiable without relying on placeholder text.

Completed on 2026-08-30:

- primary navigation order is 股票池管理 → 策略管理 → 模型研究 → 回测管理 → 模拟操盘;
- `/model-research` exposes the existing persisted LightGBM training, model artifact, out-of-sample prediction, frozen signal and reproducible backtest workflow;
- `/user/models` remains scoped to personal LLM credentials, profiles and Agent bindings;
- strategy search, template selector and every editor field have persistent visible labels and accessible names;
- no Product API, ML runtime, authorization, persistence or strategy lifecycle boundary changed.

Validation:

- production frontend build passed;
- frontend unit suite: 43 files / 124 tests passed;
- architecture suite: 70 tests passed;
- targeted Playwright navigation and strategy-label flow passed;
- `scripts/ci/local-ci.sh --all --build --with-smoke --no-cleanup`: all 18 checks passed, including 6 real Product API browser flows;
- Chrome DevTools MCP desktop/mobile review passed; console was empty and all browser requests remained same-origin;
- Lighthouse desktop and mobile snapshots: Accessibility 100, Best Practices 100.

Evidence:

- `COMMUNITY_FEATURE_CHECKLIST.md`
- `CHROME_MCP_REVIEW.md`
- `01-model-research-desktop.png`
- `02-model-research-mobile.png`
- `03-strategy-labels-desktop.png`
- `04-strategy-labels-mobile.png`
- `lighthouse-desktop.json`
- `lighthouse-mobile.json`
