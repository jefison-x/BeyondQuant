# 活动进程丢失：故障注入前的恢复合同核对

## 维护者接受（2026-10-17）

维护者在本会话明确回复“接受 ADR-0104，继续实现并验证”，接受已审修订及其限定的隔离 A Product runner 单次故障/替换验证授权。ADR-0104 已标 Accepted，ADR-0100/0113 的对应引用同步。现有静态架构/Compose 合同 5 项通过，0 模型/Job/容器变更。实施首先限定 runner 的持久身份、事前 START 归属及状态卷排他锁；未完成源码审查和无模型资格核验前，不做故障注入。生产、推送、合并均未授权。

以下保留接受之前的设计审计与当时状态，不覆盖本节接受记录。

前一项双用户普通对话及持久请求区间已限定 PASS。此片只审计与修订 Proposed ADR，没有新增模型、Job、容器操作或故障注入，不推进 Product Phase。

已通过的空闲重启、同公开会话新建子助手读取旧 SignalJob 结果继续有效。它没有证明：活动 runner 丢失、且来不及写 signed cleanup receipt 时，如何安全释放旧 Root。现有普通 Product 路径在缺证明时保留 fence；原 ADR-0104 尚为 Proposed，且“新 instance 不同”不足以证明旧进程已停止。不能先杀掉保留环境中的 runner 再猜测恢复方式。

本片将 [ADR-0104](../../architecture/adr/ADR-0104-acp-operator-process-fence-proof.md) 草案收敛到 ordinary Product：执行前固化 instance/准确容器与 scope 绑定、同一 state volume 排他锁及 consumed/tombstone；Engineering 以准确 native Docker 证据证明旧执行停止，复用私有一次性 CLI/受保护 audit seam。Backend 独立锁内重验 authority、完整 ingress/registration/claims；真正业务 unknown 仍阻塞。单独 operator interrupted 事实不能冒充旧 DSH EXIT、cleanup 或 native-close RPC；精确 ACK/proof/drain 闭合后，只能新建 native/子助手并只读已有结果，不重放旧任务。没有新增服务、HTTP/MCP 入口、调度框架或数据库表。

独立 Sol 设计 PASS：私有原件 `.ci-artifacts/agent-origin-consumer-20261015-v1/process-loss-admission-20261017-v1/SOL-ADR-0104-DESIGN-REVIEW.json`，SHA256 `e595f5207ca85805d46ff7685a00cdde90b0a2f35c7d8d9f29604c4cb2ce9b5d`；被审 ADR SHA256 `04357de411c4e42e761a6036090114d3faaaac24fd1aeb51d3c6f7a9455a9265`。Root 接受此限定设计审查，**不等于实现或故障操作授权**。

AGENTS.md 第15条及 Accepted ADR-0100/0113 要求维护者先接受这个具体例外合同。ADR 仍为 Proposed；实现、实际活动故障验证、进程丢失后的新子助手读取均 NOT_RUN。当前双用户隔离环境及三个页面继续保留。
