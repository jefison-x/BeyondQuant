# BeyondQuant / DeepSeek Harness compatibility matrix

验证日期：2026-08-28

## 版本决策

| Surface | 观察到的最高 official release | BYQ 决策 | 原因 |
| --- | --- | --- | --- |
| GitHub Releases | `dsh-v0.1.1-rc.2` | Not qualified | 没有匹配的 official Python SDK/runtime-bin |
| GitHub latest observed | `dsh-v0.1.2-alpha.1` | AVAILABLE / Not qualified | alpha release；没有匹配的 official Python SDK/runtime-bin，也未进入 BYQ Upgrade Lane |
| PyPI SDK | `0.1.1rc1` | Qualified | 准确依赖 runtime-bin `0.1.1rc1` |
| PyPI runtime-bin | `0.1.1rc1` | Qualified | 与 SDK 使用相同 Python prerelease |
| npm BYQ runtime closure | 已发布 `0.1.1-rc.2` | `0.1.1-rc.1` qualified | 与 Python 匹配；完整准确 closure 可解析且不混合 prerelease |
| Rollback | `0.1.0rc6` / `0.1.0-rc.6` | Retained | 先前已验证的 BYQ stack 和 lockfile |

Official release 证据：

- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.1>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.2>
- <https://pypi.org/project/deepseek-harness-sdk/0.1.1rc1/>
- <https://pypi.org/project/deepseek-harness-runtime-bin/0.1.1rc1/>

## Artifact 与 closure 证据

| Artifact | Qualified version | Integrity |
| --- | --- | --- |
| `deepseek-harness-sdk` universal wheel | `0.1.1rc1` | SHA-256 `2113aec229039da435bc44b275b487216d2b1c308d850521b88cea6ce3c1b762` |
| runtime-bin Linux x86_64 wheel | `0.1.1rc1` | SHA-256 `8eb31e3ab2bc3ff45474fe419eb389e32553391f1a40789ea2cc3dc8d6de137b` |
| runtime-bin Linux arm64 wheel | `0.1.1rc1` | SHA-256 `e73987c6c08d8322bce2b8b2ce75db6a139ecf546417b6015ce7a8de5e5f19b5` |
| runtime-bin macOS arm64 wheel | `0.1.1rc1` | SHA-256 `2707cd666ba49ee0963228873abf7850ca7ec5e782cca61e3603793bace0d1cf` |
| JSON-RPC carrier | `0.1.1-rc.1` | SHA-512 `CTWwd1g5/AKkNvuSu1lVdbfenhvR9UhuELQm7uhYhRGI3d3tnCnOReky0rbc7VW6tzvllMl8ShA2V5tOMQunEQ==` |
| JSON-RPC server | `0.1.1-rc.1` | SHA-512 `C1fHyeVJ4Zc3yJ7mxQfFSO7B2FXcDOTMxkmd2NjC8haSO8j8wOLFf8W58f0fKVbf/bcPhYqbImIjBfNfSPLF3w==` |
| MCP client | `0.1.1-rc.1` | SHA-512 `GXifDFUgiWcm3dr2Cbnpi9mbQgzP3GtIpGSX+7RlXlCHIHuavXCdgvGHSbq/KGPM5vAwrkZS+xcLwTSqpQL47A==` |

其余 official `@deepseek-ai/*` closure package 已重新通过 npm 核对，并准确固定在当前
stable version：`cordis@4.0.1`、`cordis-plugin-group@1.0.1`、
`cordis-plugin-include@1.0.6`、`cordis-plugin-loader@1.0.2`、
`cordis-plugin-timer@1.1.3`、`cosmokit@1.8.2` 和 `schemastery@3.18.1`。

仓库中的 npm manifest 将 DSH closure 的每个 package 列为准确 direct pin。clean lock
Phase 63 扩展后的 clean lock 包含 78 个 `@deepseek-ai/*` package：71 个
`@deepseek-ai/dsh-*` 均为
`0.1.1-rc.1`，另有上述七个 stable support package。manifest 与 lock 的 package set
相等。clean install 和 `npm audit --audit-level=high` 报告零 vulnerability。BYQ 顶层
DSH pin 不使用 `latest`、caret 或 tilde，也不使用 override、force 或 legacy peer
resolution。upstream-declared range 仍以 metadata 形式保留在 lockfile，但每个解析后的
DSH node 都受到对应 BYQ accurate direct pin 的约束。

已故意测试并拒绝 partial rc.1 manifest：npm 选择了
`@deepseek-ai/dsh-tools@0.1.1-rc.2`，它要求 rc.2 peer 并产生 `ERESOLVE`。这是完整
closure pinning 的 fail-closed 证据。

## Compatibility 验证

| Contract / behavior | Evidence | Result |
| --- | --- | --- |
| Python SDK API | 在 built image 中检查 `DeepSeekHarnessConfig`、`start`、`start_session`、`close`、notification/request API | PASS |
| JSON-RPC carrier | public `dsh-jsonrpc-agent/lib/bin.js`、keyless initialize 和 shutdown | PASS |
| custom BYQ Cordis | 未改变的 composition 在 coding flag disabled 时完成 initialize | PASS |
| `dsh-mcp-client` | startup 使用 authenticated Streamable HTTP 和 `failOnStartupError: true` | PASS |
| BeyondQuant MCP | MCP Contract/auth test 加真实 runtime startup | PASS |
| session lifecycle | create、duplicate conflict、prompt ownership、release | PASS |
| persistence/resume | 同一 contained session root、hard-cancel replacement runtime、durable volume restart | PASS |
| subagent delivery | rc.1 SDK session-tree filter、lifecycle ancestry Contract；BYQ subagent plugin initialize | PASS (keyless contract) |
| WorkflowTrace normalization | normalized allowlist、secret/raw-event denial、ordering test | PASS |
| cancellation | 保留 soft-settle 和 hard process-close policy；不伪造 DSH cancel | PASS |
| process cleanup | SDK close 加 child-process reap smoke | PASS |
| full vertical path | Gateway → Runtime Adapter → DSH → BeyondQuant MCP | PASS |

subagent delivery 结果属于 keyless protocol/composition 验证。live delegated model turn
仍是可选的 credentialed smoke；测试和证据不保存 provider secret。

## 安全与 capability 决策

已验证 stack 包含 upstream 对 Bubblewrap `/proc/<pid>/root` escape、max-token
continuation、large-history stability 和 subagent report-delivery 的修复。BYQ 将 sandbox
修复视为 defense in depth。完整 pin 约束的 package 在 rc.6 transitive runtime tree
中已经存在；为 resolution 列出 package 不代表将其加载到 Cordis。Product DSH 仍没有
shell、terminal、filesystem mutation、source mount、Git mutation、database、Redis 或
Engineering capability。

Vision、image reuse、更广泛的 bundled preset、shell/PTY、filesystem、Web UI 和其他
upstream 新能力均未启用。只有在 BYQ public Contract 和必要的 Accepted ADR 采纳后，
它们才可能成为未来能力。

## 已知限制与回滚

- DSH 仍没有经过验证的 prompt-cancel 或 per-session close operation；BYQ 保留 soft
  settle 和 Adapter 自有的 hard process close。
- 在 official matching Python artifact 可用且整个 stack 通过本 Upgrade Lane 前，
  `0.1.1-rc.2` 保持 unqualified。
- 单独 profile 的 Phase 5 DSH Web diagnostic image 保持准确 rc.6 bootstrap/rollback
  baseline，且不是 Product request path。
- 真实 model-keyed subagent turn 是可选项，不是 keyless CI 的要求；provider credential
  绝不提交。

回滚会从 repository history 恢复此前 rc.6 Python pin、npm manifest、lockfile、version
reporting 和 image。部署前先 stop/release owned process；保留 Agent Plane JSONL
session volume，若无法证明 cross-version resume，则启动新 runtime session。无需回滚
或迁移 BYQ business database。

## Phase 63 Plugin Qualification summary

| Capability | Exact official packages | Qualification | Enabled | Risk | Agent assignment / reason |
| --- | --- | --- | --- | --- | --- |
| Guard | `dsh-repeat-tool-reminder`、`dsh-tool-call-timeout-policy@0.1.1-rc.1` | QUALIFIED | Yes | LOW | 全部 Product Agent；不增加工具或 authority |
| Compaction | `dsh-compaction-basic`、pruner/token-meter closure `@0.1.1-rc.1` | QUALIFIED | Yes | LOW | 全部 Product Agent；仅 Agent context |
| Web Search | `dsh-web`、`dsh-web-search-deepseek`、`dsh-tool-web@0.1.1-rc.1` | QUALIFIED | Yes | MEDIUM | Market Research + explicit root coordinator；Factor/Strategy/Backtest denied；`fetch:false` |
| Spill | `dsh-spill* @0.1.1-rc.1` | BLOCKED | No | HIGH | rc.1 无 lifecycle cleanup，locator 需要被禁止的 filesystem tool |
| Interaction | `dsh-user-questions`、`dsh-tool-ask-user@0.1.1-rc.1` | BLOCKED_BY_RUNTIME_VERSION | No | MEDIUM | 当前 SDK/JSON-RPC Product request/answer lifecycle 未证明 |

精确 integrity、capability bitmap、checks 和 evidence 路径由
`plugins/dsh-byq/registry/plugins.json` 持有；generated identity 位于
`plugins/dsh-byq/compositions/byq-product-sdk.identity.json`。Phase 63 没有升级 Python 或
npm baseline，且不使用 rc.2/alpha package。
