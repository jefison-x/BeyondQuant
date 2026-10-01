# ADR-0091 — 完整个人工作区重置与七天归档

- Status: **Accepted — 2026-10-01；完整个人重置已实现并通过 scoped actual gate，完整 Golden E / Phase17 仍 OPEN**
- Acceptance: 维护者明确要求“直接从数据库层面重置，完成后就像新增了一个用户一样；被重置的用户数据归档保存7天左右”，在只读可行性评估后明确指示“好的，按照这个完整语义修订并实施”。
- Scope: 当前 Clean Break Phase17，登录用户对自己的个人工作区执行显式重置。
- Supersedes: 本 ADR 原 Proposed 的研究图/永久审计目标归档方案；ADR-004 的研究数据范围；ADR-0090 §4 对已闭合个人历史的无期限保留表述。安全、租户、业务幂等、未知外部结果和 DSH 唯一 Harness 边界继续有效。

## 产品合同

保留同一 user_id、username、email/display_name、密码/账号安全字段、role、个人 workspace_id 和 owner membership。个人 Product 状态回到注册默认：无旧对话、研究/策略/实验/成果、Job 历史、股票池、模拟账户/订单/模拟账本、学习及反馈；个人偏好、默认提示、Agent policy、模型配置/绑定和用户凭据移除，按现有注册的惰性默认规则重新初始化。系统配置、system-scope 凭据、共享标准行情和其他用户数据保持。Engineering 记录不属于 Product 重置。

Backend 执行数据库事务，不能 drop schema、删除账号、使用 dev-seed、清全局目录或把 Product DSH 变成数据库操作员。Product API 只允许 durable-cookie 当前个人 owner；管理员在该路径仍只能重置自己。

## 归档与保留

每次成功重置有一个只读的专用归档，UTC created_at 到 expires_at 精确七天。归档覆盖静态分类的个人数据库记录、账户设置快照及 CAS 引用，保存来源范围、逐类计数和 hash；最大100000行/64MiB，超过时拒绝且不部分清理。用户凭据仅保留加密 envelope 和必要元数据，不解密，不向 Product/模型输出；已闭合反馈的远端 status token 仅留不可逆摘要，不保留可访问远端的明文能力。活凭据及绑定删除，归档不能作为 credential resolver 输入。既有登录身份保留，重置不恢复旧 Agent 会话、授权或执行。

已闭合的用户审计、审批和模拟金融历史同样适用七天，并非所有审计永久保留。旧 strategy_approval_fact_archive 不再写入新的重复权威快照；已有快照在原 reset_at 后七天受控到期，引用仍保护 CAS。少量 reset receipt、计数/hash及历史幂等键摘要作为防重放凭据独立保留，不含用户历史 payload/secret。共享系统安全/真实财务事实不归入可清理个人模拟数据。

归档到期从可读历史中删除；其 CAS 文件在无活对象、未到期归档、其他租户或独立保护事实引用后收集。自动维护使用短锁/有界批次，不能在 Worker 正在产生对象时清理；受竞争/活任务影响的物理清理可延迟并保留准确待清理引用，不能伪称已经删除。归档不是恢复/派发输入，不新增通用归档服务。

## 重置顺序与安全

1. 锁定准确 owner/Workspace，核验账号、成员权限和幂等键。统一覆盖工作区及账户设置写入的数据库栅栏，排空已持锁事务。
2. 预检非终态 Job、调用 claim、未决 reservation、未知外部 outcome、feedback outbox/发布责任及跨租户引用。未解决时有界拒绝；不重放未知调用，不通过删除解除责任。仅 actual usage 未知但结果和责任已闭合的历史可如实归档为 unknown，不能补成0。
3. 撤销该用户后台接续许可，禁用准确工作区；Gateway 释放准确会话列表。DSH 内部 context/checkpoint 不归档、不恢复。远端已发布反馈不会因本地重置撤回。
4. finalize 再次预检，先在同一事务完整保存并核验归档，再按子表优先顺序删除静态归属记录，重置偏好/惰性默认，保存幂等 receipt 后激活原 Workspace。任何归档/删除错误回滚；已释放会话不冒称仍健康。
5. 已删除领域请求的旧幂等身份仅以不可逆摘要留作 reset 专用防重放；新幂等键正常使用，旧键拒绝而不能生成新的副作用。原 reset key 重试返回同一 receipt，不清理重置后新建的数据。

这是 Backend 领域生命周期，不是新通用预算平台、会话恢复协调器或第二 Harness。数据库权限/SQL 仍限于 trusted BYQ；Product DSH 只使用 BYQ MCP。

## 验收

先在单独可丢弃测试库验证全新 DDL、完整静态 ownership/FK、普通用户与跨租户拒绝、并发配置/Worker栅栏、原子归档/失败回滚、默认状态、旧键防重放、七天 UTC 边界、密文与 CAS 共享引用保护。Tester → 独立 Reviewer → Root 接受后，再在已授权专用隔离栈执行受影响 Golden E 和真实浏览器，复用仍有效的 A–D/F6。本 ADR 的接受不是这些测试 PASS，不推进 Phase18，不授权生产数据库、备份、部署、推送或合并。


### ML CAS 文件权限

Backend 保持非 root UID10001，只在 ML 挂载上加入 producer 的补充GID10005。
ML producer 保持UID/GID10005，在自身拥有的 root、ml-features、ml-models 三个目录
设置2770/setgid，拒绝符号链接和不同owner/group；对象沿用已有0640。没有递归chown、
对象内容改写、root Backend 或新清理平台。既有专用测试卷只允许同producer身份执行
精确目录初始化及一次唯一测试文件的写/读/删探针；生产/旧卷没有操作授权。


### 已落实与验收边界（2026-10-02）

本地 `91fc0211`、`3006f031`、`1c1f730c` 实施完整语义、ML CAS group 权限与
watch 栅栏；没有推进下一阶段或部署。隔离 populated Reset 一次归档/清理72类784行，
保留账号/RBAC/shared/system与5 CAS，真实浏览器默认状态通过 Tester → 独立 Reviewer →
Root。原失败、离线合同、构建限制及后续研究保存失败分别保留于
[实际证据](../../clean-break/phase17-personal-reset-actual-evidence.md)。
真实七天后删除尚未观测（离线到期合同通过）；当前源码空栈全重建与 hosted CI 未通过。
不能把本 ADR 接受、合同测试或已通过的 Reset 冒称完整 Golden E / Phase17 PASS。
