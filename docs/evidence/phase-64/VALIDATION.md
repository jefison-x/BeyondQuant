# Phase 64 Validation

## Outcome

Phase 64 — Research Agent Web Search 深化通过验收。DSH baseline 未升级：Python SDK 与
runtime-bin 均为 `0.1.1rc1`，npm runtime/plugin closure 为 `0.1.1-rc.1`。运行 profile 为
`research`，composition hash 为
`sha256:bdfedf9055d2dc6ea110918d4e00e53af4aa04c2cbcc6911840ac770bf12a667`，enabled plugin IDs
为 `compaction`、`guard`、`web-search`。

## Evidence

- Accepted decision：`docs/architecture/adr/ADR-0039-market-research-web-evidence.md`
- Contracts：`docs/contracts/agent-research.md`、`docs/contracts/artifact.md`
- Versioned validator：`services/backend/app/web_research.py`
- Credentialed journey：`scripts/evidence/phase64-web-research-journey.py`
- Generated identity：`plugins/dsh-byq/compositions/byq-product-sdk.identity.json`

## Validation results

- Architecture/registry unit suite：52 tests PASS。
- Backend Web Evidence、Agent permission 与 Phase 58 regression：PASS。
- Full isolated CI：`scripts/ci/local-ci.sh --base=origin/main
  --only=architecture,backend,gateway,runtime,mcp --build --with-smoke`，9/9 checks PASS。
- Fresh isolated Compose smoke：Runtime Adapter → generated composition → DSH → MCP 的 initialize、
  health、session、tool visibility、cleanup、restart PASS。
- Existing real Product API Playwright journey：3/3 PASS；two-user Product coherence PASS。
- Credentialed Phase 64 Product journey：durable Product login → bounded Market Research delegation →
  official-source Web Search → normalized source-bearing answer → strict `web_research_evidence`
  promotion → conversation replay check → cleanup，PASS。
- Secret/raw-schema checks：Product answer、WorkflowTrace/replay、readiness 与 public metadata 不含
  credential value、raw DSH event/schema 或 internal token，PASS。
- MCP 422 repair boundary：只返回固定 `validation_issue`，原始 Backend detail/input 不回显；
  contract test PASS。
- `python3 scripts/dsh/plugin_registry.py build --check` 与 `git diff --check`：PASS。

实网结果和 provider credential 未保存为 fixture、文档或日志；报告只记录结构化通过状态。

## Security conclusions

- `market_researcher` 可使用 `web_search` 和专用 evidence promotion；Factor、Strategy、Backtest
  role/composition assignment 均无 Web capability。
- Web source URL 只作为 inert provenance 保存，Backend 不 fetch；local/private/credential URL、
  duplicate query/URL、future/unknown time support 与危险 usage policy fail closed。
- Web evidence 的 `research_only=true`、`deterministic_input=false`、
  `authoritative_market_data=false` 不可修改；deterministic consumers 明确拒绝该 kind。
- 未启用 `web_fetch`、shell、terminal、filesystem mutation、runtime install、direct DB/provider
  或 Browser → DSH 路径。

## Known limitations

- rc.1 root tool-registry seam 仍使 Coordinator 在 runtime registry 中看见 qualified Web Search；
  Product role contract 强制委派，Factor/Strategy/Backtest 的 subagent toolFilter 为硬拒绝。更细的
  root visibility 只能经未来完整 DSH Upgrade Lane 处理。
- Credentialed smoke 的端到端延迟受外部模型和搜索 provider 影响，因此只作为可选部署验收，
  不进入公网依赖的 deterministic CI golden fixture。
