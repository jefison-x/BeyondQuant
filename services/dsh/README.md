# Product DSH Runtime

Phase 5 使用 thin Node 24 image，包含 exact
`@deepseek-ai/dsh@0.1.0-rc.6` npm artifact、`byq` profile 和
`dsh-byq` bundle。Image 只选择性复制该 bundle；不 mount/包含 BeyondQuant
source worktree、Git credentials、Codex authentication、Docker socket、
PostgreSQL/Redis access 或 source-edit capability。

Container 使用 official container-local default host 启动已验证 rc.6
custom-profile command。Rc.6 中 `web` 是 root command alias，不能在
`--profile byq` 后作为 application argument：

```text
dsh --profile byq --host 127.0.0.1 --port 3080
```

Web/bootstrap surface 只用于启动 diagnostic runtime、加载 profile、验证 MCP
composition；它不是 product API，也不 publish host port。实际 Product SDK
path 是 Runtime Adapter；其 composition 拥有 Phase 13 role skills、official
in-process subagents 和 trusted BYQ MCP context。Diagnostic Web profile 有意
不包含 product role state。

Product preset roster 也归 bundle 所有：只 scan `byq-product`，它是默认值，
并禁用 user preset root。Preset composition 不含 coding/filesystem mutation
tools；Product SDK composition 同样不含 source mount、Git、database 或
Engineering Plane capability。
