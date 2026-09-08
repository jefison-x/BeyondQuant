# ADR-0067：根回合隔离的 Runtime 调用身份

- Status: Accepted
- Date: 2026-09-08
- Scope: 补齐 ADR-0066 两工具准入在当前官方 DSH 0.1.2rc1 下缺少 HTTP 根归属的问题。
- Related: ADR-0003、ADR-0046、ADR-0062、ADR-0064、ADR-0066。
- Acceptance: 2026-09-08，维护者明确回复“批准”，接受本决策并授权隔离实现及资格验证；不授权 push/merge、生产部署或历史研究续跑。
- Supersedes: 具名修订 ADR-0003 的“同一 active BYQ session 跨根回合复用 process”及
  ADR-0046 的“ready runtime resume 不新建 process”；其他安全、恢复、审批和预算约束不变。

## 已验证的缺口

`test_domain_call_wire.py` 使用官方锁定进程、本地合成 Provider/MCP，分别对两个目标工具
执行同 generation 两根回合、相同参数、相同 model callId 的调用。两项探针通过，确认：

- Adapter 的官方通知能区分 turn 1/2，并绑定两个不同 BYQ root。
- MCP HTTP headers 和工具参数相同。变化的 MCP JSON-RPC id 不在 Adapter 的 tool/call 通知中。
- 官方固定源码 `a66e4702047846cdaa10c66c9d3df3951f5ea70d` 的 MCP client 仅发送
  `name`/`arguments`；headers 为连接配置中的静态字典。不存在已资格验证的逐调用关联字段。

这不是已复现生产越权。现有终态 ACK 屏障仍限制跨回合复用；但它不能代替 ADR-0066 要求的
独立精确请求归属证明，不能对“旧未消费凭证 + 新请求先到”的一般并发准入宣称已验证。
不能猜 MCP 自增 id 与 callId 的关系、信任 model 自报 root，或按最新 active root 查询归属。

## 接受的决策

1. 保留公开 conversation/session/trace identity；每个新根回合使用独立官方 DSH process 和
   generation。只调整既有 Adapter 的 process 所有权粒度，不增加第二 harness、代理或队列，
   不升级、回退、fork 或修改官方 SDK/runtime。
2. Adapter 在启动模型前持久登记 root、generation 和一次性执行身份；通过官方 MCP 静态
   headers 配置注入不可由工具参数覆盖的 BYQ 根身份。MCP 从受信服务 header 转发该身份，
   Backend 同时校验 owner/workspace/session/generation/root、真实调用观察、原任务和 AgentRun。
   根身份本身不是权限，也不是可公开或放进模型上下文的凭证。
3. 同根 child 共享原根的纠错范围；下一个 root 使用新 process，不复用旧调用证明或预算。
   迟到旧 HTTP 请求保留旧 header，因此不能被归入新 root。重复请求仍只返回原持久回执，
   同 key 改内容拒绝。ADR-0066 的执行前扣次、unknown 不返还、一次修正语义不变。
4. 根终态后关闭/reap 原进程；仍以 Backend 精确终态 ACK 为新回合准入屏障。原执行者失效
   只按 ADR-0064 恢复收尾。不能从有界超时推断领域写入未发生。
5. 每轮沿 ADR-0046/0062 的现有公开历史恢复合同提供上下文；保留最近未回答主题和失败事实。
   不复制 DSH 私有日志、推理、缓存或未完成 tool state，不自动续跑历史研究。公开会话连续性
   不等于私有 DSH 状态连续性；需要通过真实跟进研究验收，而不是仅测重新启动成功。
6. 原 MCP schema 保持严格。继续资格验证官方 MCP handler 的公开 Request/parsedBody 入口，
   为两个工具记录可确定的 schema 拒绝；不得覆写 SDK 私有校验函数或降低 schema。
   不可归属/无法完整哈希的输入不得进入领域执行，停止与错误语义必须有独立失败测试。

## 代价与门禁

每次用户根回合增加初始化/清理成本，并更频繁使用有界公开历史，而不是保留进程内完整上下文。
接受只授权实现和资格验证，不预先认定体验可接受。至少验证两用户、同会话连续三轮、child、
相同 body/callId/key、迟到旧请求、并发认领、取消/重启、回执丢失、进程清理和中文研究对象保持；
记录相对现有基线的初始化延迟、RSS、20-cycle 泄漏及实际上下文差异。资格失败不能发布。

新增独立构建/配置身份，保留历史清单和失败报告，不将旧认证套用于新拓扑。
终态 ACK 沿原生命周期日志持久化（v2 首批；追加 ADR-0066 私有调用证据后的当前实现为 v3）；
v1/v2 仅在验证原摘要后显式迁移，未记录的 ACK/调用不作已确认推断。
Gateway 仅按原有有界投递机制重新确认精确终态回执，不续跑任何历史研究。
联合升级须验证日志版本与两服务协议；旧应用不能直接读取 v3 状态，不将混版本运行当作
已验证兼容路径。本次隔离实现不授权生产日志迁移。
本方案不解决 F6 的全路径累计模型费用限制；后台续接仍保持关闭，直至 ADR-0065 门禁通过。

## 未选择的替代方式

- 仅凭 hash/进程 generation/最新 active root：不能补上独立调用归属。
- 修改官方 MCP client 或打补丁传 header：违反不 fork/不 patch 约束。
- 另写通用 MCP bridge、拦截全局 fetch 或偷偷改只读 ToolExecution：不采用。
- 官方 `tools/pre-execute`/`tools/execute` 确实存在；所锁合同限定调用身份只读，execute wrapper
  仅可换 signal。它们不是已证明可为原 MCP HTTP 注入关联 header 的入口。若改用新的受信
  Product 内扩展来承担调用准入，须单独资格评估，不冒充现有 SDK 自动提供了该保证。
- 等待官方提供并资格验证逐调用元数据：可行的延期方向，但当前没有可直接启用的合格接口。

本 ADR 不授权 push/merge、生产部署、release/tag、历史任务续跑、数据扩容或生产付费实验。
