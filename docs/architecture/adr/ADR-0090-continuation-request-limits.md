# ADR-0090 — 后台接续授权与单次请求限额分离

- Status: **Accepted — 预算合同实现与真实资格仍待验证**
- Acceptance evidence: 2026-10-01，维护者在审阅本 ADR 的精确方案和验收边界后明确回复“明确接受”。接受范围为持久授权与单次请求限额分离、保留责任账本、不恢复旧余额/DSH 状态；不授权推送、远程合并、部署或现有数据库操作。
- Date: 2026-10-01
- Decision owner: BeyondQuant maintainer
- Current authority: ADR-0088、Clean Break ADR-001/002/003/005/006。
- Scope: 一次获授权、原健康 Product 会话中的后台接续请求。不是通用预算平台、会话恢复协调器或第二套 Harness。
- Audit: [Phase 17 预算与观察器审计](../../clean-break/phase17-continuation-budget-audit.md)。

## 背景

现有 Backend 将 Task 授权 `token_limit` 作为持久累计余额；每次 reservation
占用剩余额度，Adapter guard 每个 `llm/stream` 调用按 `1048576 + maxTokens`
记入保守上限，终态回执将上限合计命名为 `charged_tokens`。这不是实际模型消耗。
400 万最多容纳 3 次 8192-output guard 调用；1600 万最多容纳 15 次。
调大测试数值没有消除授权、执行资源限额与记账的耦合。

当前 Adapter **不恢复旧预算**：guard journal 使用独占创建，失去原会话或回执
无法证明时返回 `outcome_unknown`。Backend 持久保存累计上限和未决责任；
不能将其描述为已经实现的 DSH 跨进程余额恢复。历史 ADR-0086 不构成当前规范，
其单次请求代码中的前置限额与真实 usage 分离方法可按现行合同复用。

## 决策

### 1. 业务授权保持持久，资源限额属于一次请求

Backend 保留 Workspace/用户/actor、准确 Task、原 Product 会话、确认的
StrategyVersion ID/hash、grant version、期限、撤销、`max_turns`、幂等及
事件/输入摘要关联。授权绑定一个由 BYQ 配置提供、模型无法抬高的具名
execution profile ID/version/hash；本切片只实现 `max_turns=1` 的当前验收路径。
授权不再是模型 token 的历史余额。批准策略不等于批准所有领域写操作。

一次业务事件原子创建一个持久 request/reservation 身份（可沿用现有 reservation ID
和存储，不新增账本服务），绑定 grant、事件、输入 hash 和 profile hash。
相同输入返回原回执；冲突拒绝；同一请求已提交、已终态或未知时不得生成第二次提交。
请求自己的限额从零开始且绝不重新打开旧请求。`max_turns>1` 的一般化切片及
任何换会话重发策略不在本决策实施范围，仍须保持 fail-closed。

### 2. 一次后台请求的明确候选限额

以下是拟实现及离线资格验证的 **安全上限**，不是实际消耗、成本预测或已通过实测的参数。
profile 名称为 `task-ready-read.v1`，仅绑定当前 task-ready 读取/回答目标，首批 route
仅允许已记录的 official DeepSeek Flash；其他已配置 route 不冒充已完成此 profile 资格。

| 维度 | 候选硬上限 | 计量边界 |
|---|---:|---|
| 实际 provider HTTP attempts（含 retry/compaction） | 16 | 每次外发前计数；拒绝调用另记，不算已外发成功 |
| 并发 provider 请求 | 1 | 请求开始/终态 |
| 单次 provider 请求输入 | 262144 bytes | 序列化完整 body，含 system/history/tool definitions/results |
| 累计 provider 输入 | 4194304 bytes | 每次重发完整上下文均累计，不以 token 估算替代 |
| 单次声明输出 | 8192 tokens | 外发前确认声明；支持的 provider 必须遵守限额 |
| 累计声明输出 | 131072 tokens | 安全计数，与 provider 实际 usage 分开 |
| 单次 provider body 中工具数据 | 65536 bytes | 工具结果载荷，含重复携带的结果 |
| 累计工具数据 | 1048576 bytes | 各 body 重复携带也累计；不等同于工具调用数 |
| 工具调用 | 16 | 使用 DSH 公开 hook，在 dispatch 前拒绝第 17 次 |
| 请求总耗时 | 180 seconds | admission 至 DSH 请求关闭；Root 测试步骤另受测试总时限约束 |

保留现有公开历史投影 20 条/每条 6000 字符/总 24000 字符限额；它不是 provider
输入 bytes 的证明。工具数据、输出和时间都在实际边界执行，不能只写在 prompt。
当前原健康逻辑会话可以按现有 root-scoped DSH 合同发起新 root；不恢复旧 DSH 私有状态。
禁止该 profile 的 Web、委派、下载、其他 Task、创建额外 Job 和 execute。
领域能力仍经 BYQ MCP 逐动作授权和审计，不能靠预算放行。

复用现有 `research_request_gate.py` 的 request 计量和 usage 解析，并为具名 profile
收窄接线；不直接复制历史 3-call/stage/persona 协议。DSH 保有 Agent loop、工具循环、
压缩和取消；Adapter 只安装一次请求的计量/guard，并按已有 DSH API 关闭所拥有的进程。
若公开 hook 不能在实际外发/工具 dispatch 前实施某一维度，该 profile 保持未资格，
不得另建 Harness、悄悄忽略该维度或以调高 token 总额代替。

### 3. 实际消耗、业务结果和未知状态独立记录

`limits`、admitted attempts/bytes、provider 实际 input/cache/output usage、
usage source/completeness、request outcome、Job/Artifact/审计关联分别记录。
无法证明的值写 `unknown`，不写 0，不把保守上限写成 actual usage。
未知用量不自动判定业务 Job 失败；业务结果由精确 Job/Artifact/审计事实证明。
但无法证明外发结果或资源限额是否被遵守时，此请求需对账并关闭自动接续资格，
不得重发来补 usage，也不得将未知字段抹掉后报完整结算。

持久记录保留准确授权、at-most-once 提交和未知副作用责任，不保存可恢复的
Agent 计数器或可继续消费的旧余额。Adapter/DSH loss 后仅对账准确回执和
Job/Artifact；没有原健康会话就停止该自动接续场景。另行获授权的新会话可查询
同一 Job ID，其查询不是旧请求的预算续跑或旧 DSH 会话恢复。

### 4. 数据与切换边界

不删除整个 `continuation_budget`、旧 grant、未决 reservation、财务或审计事实。
先按 schema version 区分责任记录与计数器语义，保留原记录可读、只用于对账且
不可重新 dispatch；旧 `token_limit` 不得自动转换为新业务许可。
未来实现仅调整新建 0.10 schema/新记录及准确调用链，未授权操作现有库或用户数据。
授权合同切换前没有兼容派发桥，也不通过数据迁移伪造新的 grant。

## 已接受的边界

接受本 ADR 即接受：**去掉授权历史 token 余额，改由明确 profile 约束每次请求；
持久账本保留业务责任、幂等和未知结果，取消旧预算恢复/续花语义。**
这改变 Backend/Product/MCP/Adapter 的当前许可与回执合同，不能仅当测试参数调整。
维护者已接受上述许可/计量切换的精确边界；实现及 profile 资格仍须经过定向测试、独立 Reviewer 和 Root，随后才执行受影响 F6。

## 验证与后果

先用旧记录、离线 HTTP/tool 样本证明每维度在调用前拦截；真实 usage 无效/缺失仍 unknown；
撤销与并发 admission、同事件重入、同键冲突、lost receipt 和未知外部结果必须保留反例。
单次研究请求 guard 有效不证明后台接续接线已有效。
Tester → 独立 Reviewer → Root 验收后，仅跑受影响 F6；
复用仍适用的 A–D，阶段最后的必需 Golden/Full CI 门禁保留。

增加 token 总额、删除全部账本、恢复旧 DSH 会话以及新增通用预算平台均为拒绝方案。
未部署的实现可通过隔离分支回退源码；不自动回退业务数据，不从旧请求重新提交。
