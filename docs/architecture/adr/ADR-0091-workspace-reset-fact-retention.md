# ADR-0091 — Workspace Reset 保留接续责任与审计目标事实

- Status: **Proposed — 等待维护者明确接受，尚未实施**
- Date: 2026-10-01
- Decision owner: BeyondQuant maintainer
- Scope: Clean Break Phase17，单个 Workspace 的显式 Reset；Backend 同事务安全与持久事实。不是预算平台、会话恢复器或第二套 Harness。
- Authority: ADR-0088、Clean Break ADR-003/004、Accepted ADR-0090 §3–4。
- Evidence: [Phase17 审计 §19](../../clean-break/phase17-continuation-budget-audit.md#19-golden-e-重置边界审查与尚未接受的方案2026-10-01)。

## 现状与具体阻塞

ADR-0090 已要求保留 grant、reservation、结算、幂等及未知外部责任，不能删除整个
`continuation_budget`。目前这些数据只保存在 `research_tasks` 的两个 JSONB 列。
`WorkspaceResetStore._preflight` 未检查它们，随后 `_DELETE_PLAN` 会删除 Task。
私有测试文件封存不能代替 BYQ 内的持久责任。这是现行合同缺口；真实 E 未运行。

当前精确隔离栈有21 Task、60 Artifacts、12 Product conversations，真实 F6 的
`byq_research_task_create`/strategy draft/validate 审计保留精确 Task/Artifact 引用。
现有 `retained_task_audit`/`retained_audit` 会阻止重置这些对象；其他 approval/action
引用也须一次性分类。只给账本加 archive 仍不足以完成 E，不能删审计或跳过守卫。
既有 strategy_approval_fact_archive 仅覆盖其已定义的审批事实，不覆盖全部上述责任。

## 最小提议

### 1. 产品事实保留边界

由 Backend 增加一个**仅供 Workspace Reset 使用**的不可变事实归档表，候选名
`workspace_reset_fact_archive`。它不是活 Task/Job/Artifact，不进入普通资源目录，
也不能生成许可、执行 Job 或派发 Agent。已有 strategy_approval_fact_archive 继续
唯一拥有其审批及版本快照；新表仅补足尚未保留的事实或以精确ID/hash引用现有归档，
不复制同一权威事实到两份可分别演进的快照。保存范围仅是：

- 被删除 Task 内非空 grant/旧预算责任/request reservation、原 profile、输入/事件摘要、
  幂等与准确结算/未知字段；保持原 schema version，不转换为新可消费余额。
- 现存权威 audit/approval/research_task_actions 精确引用的待删领域对象及必要目标事实。
  首批显式类型限于 ResearchTask、Artifact，以及本轮实际受引用的 terminal BYQ Job；
  未分类种类阻止 reset，不开放任意对象的通用归档注册。
- 原 owner/Workspace/source kind/source ID、完整源事实摘要、必要不可变快照、reset ID、
  authority reference IDs。引用链所需的 Artifact content/hash/CAS reference 仍须可核验。
  不保存可重启的 DSH session、Agent checkpoint、历史余额运行状态或数据库备份。

使用明确唯一键和原始事实 hash，重复相同事实可验证，内容冲突拒绝；同一源 ID
不能被不同 owner/workspace、版本或 snapshot 覆盖。保留当前审计/审批/action 行。
归档无活对象 FK，不会随活图删除而消失；归档所引用 CAS 对象须计入既有引用保护，
不能被 reset GC 当作孤儿删除。不增加通用存储或账本服务。

### 2. 重置事务与未知责任

在既有 Workspace writer fence/advisory lock 下，begin/finalize 都检查精确当前状态：

- 非终态 Job、未确认的 Agent authority/外部结果、未决 reservation 或无法分类的许可
  责任阻止 reset。未知调用先对账，不能靠 reset 清除或重发。
- 实际 usage unknown 不伪装为0。若外部结果/dispatch/结算仍无法证明，继续阻止；
  本轮 E 对任何已外发请求的 usage completeness 或 limit-compliance unknown 也
  fail closed；留在原账本对账，不以归档/重置补出0或已知值。未发生请求而 usage
  为null须由无reservation/无dispatch的精确事实证明，不能把null猜成外部结果已知。
  更宽的“仅用量未知可重置”语义不在此提议实施范围。
- 非空许可必须先证明已撤销/失效且不可派发。所有需保留事实先在同一事务归档并
  精确核验 source count、identity、hash 与 authority references，再删除 disposable 图。
- 归档失败/缺失/冲突、跨 Workspace 引用、未分类 authority 类型都回滚并 fail closed。
  现有审计引用守卫仅在其精确目标已持久保留后允许通过，不能无条件解除。

不复制整个旧图作为可恢复状态。普通 Task/Job/Artifact/conversation API 对删除对象
仍404，reset 后 seed/研究必须使用新身份。用户/Workspace/RBAC、共享配置及市场
canonical data 保持原有保护。旧请求/事件不能因为对象归档重新提交。

### 3. 可核验只读入口

新增一个有限的 Product 只读事实查询：当前 Workspace 的精确 `source_kind/source_id`
lookup，返回 source identity/hash、reset identity、authority refs，以及必要的 closed
责任投影。Gateway/Backend 都使用当前真实用户、membership/owner 与 Workspace 校验，
不依赖旧会话仍存在。不提供重放、恢复、授予、修改或批量跨用户能力。Product DSH
仍只经现有 BYQ MCP 访问领域，不获得此入口的 Engineering 权限或直接 PostgreSQL。
本切片将查询与响应边界固定如下，实施前先写封闭合同及反例：

- 仅正常 durable user cookie；必须仍是当前 active personal Workspace 的 owner，
  当前 membership/user均active。Bootstrap Product Token、已禁用用户及越权lookup拒绝。
- `source_kind` 为明确的上述已分类枚举，`source_id` 为该类型精确ID（不超过128字符）；
  单个事实 lookup，不提供跨用户列表、通配符、分页式账本导出或执行操作。
- 响应限于 schema version、owner/workspace/source kind/ID、source snapshot/hash、reset ID/time、
  最多100条精确authority ID/run/action/outcome引用、已关闭grant/profile/reservation/settlement
  与usage的封闭投影。新v2投影采用现行责任字段及真实unknown标记；旧v1只读投影保持
  原schema与估算量标签，不转换为actual用量或新grant。完整内部快照不直接公开。
- UTF-8 JSON最大65536 bytes；超限拒绝并保留源事实，不截断身份/责任后称核验成功。
  不公开原始模型/provider payload、secret、任意Artifact正文或DSH私有状态。
- 未分类的audit action/resource或跨Workspace引用先阻止reset；不能在落archive后放宽
  校验。来源hash与引用的规范化算法/响应字段必须通过合同测试后才冻结实测。
此入口让验收通过 Product API 对账持久事实，私有测试文件不是唯一证据。

## KEEP / DELETE / REWRITE

| 分类 | 精确范围 |
| --- | --- |
| KEEP | Workspace/用户权限、授权/撤销/幂等、grant/profile/reservation/usage/unknown 原事实、Agent audit/approval/action、已有 strategy approval archive、必要 CAS 引用 |
| DELETE | 通过现有 reset 清单删除 disposable 活对象；删除架构中的历史余额续花/跨进程预算恢复语义，不删除对应责任记录 |
| REWRITE | reset begin/finalize 同锁责任预检；原子归档与验证后删除；审计/审批引用检查使用保留事实；有界只读 Product 对账合同；E 观察器 |

## 验证顺序与一次性修正

先冻结全部剩余 E 断言与当前源合同，使用现有样本/定向新鲜测试库验证：未知/未决、
未撤销许可、半完整 settlement、跨 Workspace、hash/authority 冲突、归档回滚、
重复 reset、普通资源404与只读保留事实、schema/bootstrap/CAS 引用保护。
E 观察器同步修正 snapshot type/null、精确资源 owner/workspace/ID、许可状态、完整
目录边界及 response-before-assert；保存错误后有界只读对账，无自动重放。

Tester → 独立 Reviewer → Root 后，仅运行受影响 E：当前 populated exact scope
Runtime/Workspace reset → 一次 seed → 最多两次新的研究输入/一个委派 child，
复用98交易日缓存、有效 A–D 与已经通过的 F6/UI，不重新下载行情。新增 schema/reset
源修正须补其具体 fresh-schema/build 资格，不能据此默认全仓回归或整栈重建。
最后仍保留 final Golden 与当前 head hosted CI/仓库门禁。

## 接受与授权边界

这是**新的 reset 后持久事实存储/只读边界**，不是模型调用许可。按 AGENTS.md
规则15及维护者“架构边界改变先提出 ADR 并等待明确接受”的指令，接受前不新增
DDL/archive/API 实现、不运行真实 E reset/seed。当前事实封存与候选观察器保持。
接受本提议才允许在隔离分支实施上述窄合同；仍不授权操作现有真实数据库、用户
数据、备份、市场下载、部署、推送或远端合并，也不推进 Phase18。
