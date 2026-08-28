# DSH Plugin Registry

BYQ 的 Product 插件事实来源位于 `plugins/dsh-byq/registry/`。Registry 固定 official npm
source、exact version/integrity、runtime baseline、qualification、完整 capability、risk、
credential reference、Agent allow/deny 和 Product policy。它不是运行时数据库或安装服务。

## 状态与风险

`AVAILABLE` 只表示上游存在；`QUALIFIED` 表示当前精确 baseline 的全部 gate 通过；
`ENABLED` 由 QUALIFIED + Product policy + Agent assignment 派生。`BLOCKED`、`REJECTED`、
`DEPRECATED` 不能进入 composition。

风险为 LOW/MEDIUM/HIGH/PROHIBITED。shell、terminal、code execution、Git/source write、
Docker socket、runtime mutation、subprocess、database 和 Engineering capability 在 Product
Plane 为 PROHIBITED。

## Profiles 与 generation

- `core`：Guard + Compaction；
- `research`：core + search-only Web Search；
- `interaction`：当前等于 core，并记录被 runtime transport 阻塞的 Interaction candidate。

运行：

```bash
python3 scripts/dsh/plugin_registry.py validate
python3 scripts/dsh/plugin_registry.py qualify
python3 scripts/dsh/plugin_registry.py build --check
```

非 check 的 `build` 只在源码/build lifecycle 生成 committed Cordis 与 identity；它不安装
package。Runtime readiness 只报告 runtime version、profile、composition hash 和 enabled IDs。

## 安全边界

Frontend 仍只访问 Gateway/Product API；Runtime Adapter 仍通过 official SDK/stdio JSON-RPC
拥有 DSH process；Agent-to-Domain 仍只经 BYQ MCP。Registry 不能定义 workspace、owner、
domain invariant、approval 或 audit semantics。Web result 不是权威 quantitative input；
compaction/spill 不是 BYQ Artifact 或 database。
