# F7 官方调用观察资格切片（2026-09-08）

状态：部分资格证据，非 F7 完成或制品认证。ADR-0066 已获维护者“批准。”接受。

## 已执行

从本隔离工作树构建 MCP 和官方 DSH 0.1.2rc1 探针镜像；使用 Docker internal 网络，
不发布主机端口、不挂载生产数据，MCP Backend 指向不可用本地端口。Provider 是测试内的
loopback 合成服务，不使用真实模型密钥。测试会话没有业务 owner，领域输入也不满足 schema，
因此这些测试不证明领域写入成功。

`services/runtime-adapter/tests/test_dsh_012_real_process.py` 的
`test_official_registration_notification_has_exact_request_identity` 扩展为 7 项，实际执行 7 passed：

- 原 AgentRun 注册正向观察保持通过。
- 两个领域工具分别发送空对象、含中文/空值/布尔/整数/小数的嵌套对象、大参数对象。
- 大参数脚本包含 50,000 个汉字（脚本 UTF-8 为 150,000 字节）；不是支持无限输入的承诺。
- 官方 `tool/call` 中 arguments 确认为 JSON 字符串，解析后与每项完整合成输入一致。
- 领域工具不误生成 AgentRun 注册 fingerprint 输入。

探针镜像仅供本次测试：`byq-ci-f7-observe-runtime:20260908`、
`byq-ci-f7-observe-mcp:20260908`。Runtime Dockerfile 尚携带历史 .5 清单，
新增测试已造成源码清单漂移；本次明确不把该镜像称为 .5 已认证制品，也不改写历史清单。
待实现和测试稳定后按既有规则生成独立构建身份及完整资格认证。

## 仍须验证，不能从本切片推断

受影响 Runtime 完整测试实际为 132 passed、7 skipped、3 个既有弃用警告（22.15 秒）。
跳过项不计为通过。架构/共享检查执行 214 项但未全绿：1 failure、4 errors；其中构建清单
与资格报告检查明确拒绝新增测试后的 .5 源码漂移，模拟构建失败检查未生成预期调用文件。
该结果保留，不能把上轮 214 PASS 沿用到当前改动；独立构建及整体验证尚待完成。

实际有效请求经过 MCP trace 增补后的规范摘要；非法 JSON、截断、非有限/超安全整数及输入上限；
schema 拒绝的可靠结果归属与持久计数；多根/child/迟到来源的身份绑定；私有凭证投递与公开隔离；
认领、撤销、并发修正及 Artifact/回执崩溃窗口；纠错耗尽后的官方停止路径。

当前没有接入领域调用凭证或纠错台账，没有生产部署、历史研究续跑、付费 API、push 或 merge。

## 后续：真实 HTTP 根身份资格结果

`test_domain_call_wire.py` 对两个工具分别执行同 generation 两个根回合，实际 2 passed。
使用官方保留依赖载体、只读挂载当前源码、Docker `--network none`，仅容器 loopback
Provider/MCP；不是保留镜像的新制品认证。合成 MCP 仅观察传输身份、不代表真实 BYQ schema。

Adapter 通知包含不同 root 绑定及 turn 1/2；MCP 请求 headers、name、arguments 均相同，
仅 MCP 自己的 JSON-RPC id 不同。model callId 可以相同，且不会传入 MCP body。
因此输入观察 PASS 不等于独立 HTTP 请求根归属 PASS；不得以 model AgentRun 引用或
MCP 请求自增序号推算 root。尚未实施的“凭证 hash 匹配后直接执行”路线保持关闭。
现有终态 ACK 屏障是有价值的防线；此处没有宣称生产已发生跨根越权，也未绕过屏障做业务写入。

固定上游提交 `a66e4702047846cdaa10c66c9d3df3951f5ea70d` 只读核查：

- [MCP 配置](https://github.com/deepseek-ai/DeepSeek-Harness/blob/a66e4702047846cdaa10c66c9d3df3951f5ea70d/packages/mcp/mcp-client/src/index.ts)
  的 headers 为静态字典。
- [MCP 工具桥](https://github.com/deepseek-ai/DeepSeek-Harness/blob/a66e4702047846cdaa10c66c9d3df3951f5ea70d/packages/mcp/mcp-client/src/tools.ts)
  的 `callToolUncached` 仅发送 name/arguments；ToolExecution 提供 signal 而非逐调用 HTTP 身份。
- [MCP transport](https://github.com/deepseek-ai/DeepSeek-Harness/blob/a66e4702047846cdaa10c66c9d3df3951f5ea70d/packages/mcp/mcp-client/src/transport.ts)
  在构建时设置静态 requestInit headers。
- [公开工具扩展](https://github.com/deepseek-ai/DeepSeek-Harness/blob/a66e4702047846cdaa10c66c9d3df3951f5ea70d/packages/core/tools/src/index.ts)
  存在 pre/around/post-execute；调用身份只读，around wrapper 仅可换 signal。
  没有把“本次未找到动态 header”泛化为“DSH 不存在任何扩展能力”。

现有 MCP server 2.0.0 的公开 `createMcpHandler().fetch(Request, {parsedBody})` 可用于进一步
schema 拒绝资格测试；私有 `validateToolInput` 不应覆写。该入口不能自行补出 DSH 根身份。

新增私有摘要合同原型及 7 项单元测试，覆盖 trace 增补、键顺序、数字表示、bool 与数字区分、
换 key/child 不算纠正进展、非法 JSON/重复键/超大整数/非有限值/深度/大小拒绝。该模块
尚未接入 Runtime、MCP 或 Backend，不能声称为已生效的权限控制。

后续实现需先决定 [ADR-0067 根回合隔离提案](../../architecture/adr/ADR-0067-root-scoped-runtime-call-identity.md)。
它改变进程复用和上下文恢复频率，须维护者接受，不由 ADR-0066 原审批或“不要停止”隐含授权。

最终复验：新增精确线缆断言后 2 passed（2.88 秒）；私有合同 7 项通过。
当前源码挂载官方依赖载体的 Runtime 全套为 122 passed、19 skipped、3 个弃用警告（3.79 秒）。
此轮没有启动真实 BYQ MCP 栈，相关 opt-in 项明确跳过；与上轮 132/7 的配置不同，不作性能对比。
文档 8 份检查与 diff whitespace 检查通过。没有重写历史构建、重新宣称架构检查全绿或发布认证。
