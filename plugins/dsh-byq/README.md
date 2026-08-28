# dsh-byq

这是 BYQ-owned Product DSH configuration bundle。它包含 MCP client、Product Agent
spine、skills/subagents，以及 Phase 63 的声明式 Plugin Registry。Product composition
只能由 `scripts/dsh/plugin_registry.py` 从受控 template、Product profile 和 Agent mapping
确定性生成。

Registry 只接受已登记的 official DeepSeek packages；package 存在或安装在 image 中不等于
QUALIFIED/ENABLED。运行中的 Runtime 不提供 npm install、extensions、hot install 或
self-modification。所有 Agent-to-Domain 调用仍只经 BYQ MCP，Product DSH 不获得 shell、
terminal、source write、database 或 Engineering capability。

`byq-product` 仍是默认且唯一 Product preset。新增插件的标准流程与风险边界见
`docs/architecture/dsh-plugin-registry.md` 和 `docs/architecture/dsh-plugin-qualification.md`。
