# 策略版本创建纠错资格（进行中）

2026-09-13，维护者明确“接受方案”，ADR-0073 已记录为 Accepted。

## 已执行

仅隔离工作树候选：增加 byq_strategy_version_create 私有调用摘要合同，必需原 task、AgentRun、draft artifact 和 idempotency key。
运行时停止识别改为引用公共 ACTIONS，避免与摘要合同重复维护动作清单；未接入 Backend 版本写入或正式 MCP 工具注册。候选 schema 已加入观察合同，用于真实 SDK 拒绝资格。

官方 SDK 0.1.2rc1 保留镜像，无外网容器，Provider/MCP 均为回环合成服务，无真实模型密钥或领域写入。
首次运行因 tmpfs 权限在启动阶段失败；修正临时目录权限后，新动作两项身份探针通过，原生停止探针失败。
原因是运行时停止识别单独列举旧动作；统一合同后，四动作全部非 20-cycle 探针 **12 passed，8 deselected，24.32 秒**。
这仅证明完整输入观察、根隔离及停止路径，不代表 SDK schema/领域准入/并发/重启资格全部完成。

架构测试 124 项中一项 test_image_build_failure_never_runs_old_image 报错（临时 calls 文件不存在）；普通及提升执行均复现，尚待诊断。不得声称架构全绿。
上一批 .93 远端 CI run 34747915202 已 completed/success；该结果不覆盖本候选。

## 剩余

SDK schema 拒绝及 owner/workspace/task/action 隔离；Backend 原子写入/准入回执；最多一次修正、未知保留、同键异输入、取消/并发/重启、人类路径；构建身份、完整受影响测试与 CI。
H4/H5 均未完成，本候选未推送、合并或部署。

## 后续资格证据

- 私有摘要合同 9 项通过，新增版本原键/AgentRun 替换不能改变输入摘要、草稿改变必须改变摘要、缺引用及伪造根/owner 字段拒绝。
- MCP 编译及真实 SDK HTTP schema 拒绝/请求体边界测试通过；版本 draft_artifact_id 数字错误被 SDK 拒绝，领域回调保持零执行。
- Runtime 完整单元回归 164 passed、52 skipped（显式资格环境未开启），1.31 秒；12 项官方进程探针保留独立结果，不将跳过计为通过。
  初次单元回归被保留镜像的 root-turn 默认环境干扰；显式使用测试夹具要求的 session 模式后通过，未改产品实现消除该环境失败。
- 隔离 PostgreSQL 两动作证据测试 20 passed，19.19 秒：持久重启、原回执、根/task/run/generation 拒绝、跨 owner/workspace/session/trace 隔离及私有端点权限。
- MCP 全套执行到实时 contract-test 因未配置合成 BYQ_MCP_TOKEN 而停止；需按 CI 的隔离 Backend/MCP 服务夹具完整执行，不能声称全套通过。
- 架构失败已定位到 build_test_images 的构建清单前置检查：候选源码尚未生成新构建身份，旧清单明确报告 build revision drift，导致假镜像命令未执行。
  需候选定稿后生成新身份再重跑，不修改测试断言或覆盖历史清单。

仍未证明跨 action 准入、领域事务/并发/取消/未知预算闭环；不启用或发布该候选。

## 领域接入候选（尚未完成发布资格）

候选已将 Backend 版本生成、validated 转换、成功回执接入原有准入事务；MCP 注册改用已测 schema，传入可信 trace/root 并复用原凭证等待机制。
前文“未接入”为此前资格阶段历史状态，当前以本段为准。原 draft 类型、任务、来源验证证据检查保留；来源损坏和身份错误不转换成可修正参数错误。

新真实 HTTP 用例先以 422 而非预期 425 失败，证明旧版本入口未接入凭证等待；接入后通过。
四动作并发取消用例 4 passed：版本先准备一份人类草稿，只有新版本与回执进入 Agent 事务；数据库实际 advisory 锁竞争可见，取消等待提交，取消后原结果可回放。
新增版本转换前崩溃场景要求插入回滚，原调用保留 unknown，原键重试不能再次写入。
共享 evidence 夹具保留原签名，版本参数化仅用于本文件局部包装，避免影响其他纠错测试的原动作语义；修正后相关 45 项通过。
MCP 编译和官方 SDK schema/请求体边界复测通过。

仍需完成该动作的精确跨 action、并发修正、完整 MCP 服务合同与发布构建/审计清单/远端 CI；不能根据本段局部证据宣布 H4 或 H5 完成。

最终本轮组合回归：test_strategy_version_correction、test_strategy_artifact、test_domain_call_evidence、test_domain_correction_admission、test_factor_correction_admission 共 **60 passed，52.86 秒**；包含版本插入后失败的回滚与 unknown 保留。未执行新候选远端 CI。

本轮新增跨 action/并发资格与两项版本 HTTP 用例共 3 passed，4.34 秒。二次失败按原合同为 correctable_failure/correction_failed，后续新调用因耗尽被拒绝；原测试误把该失败回执期待为 blocked，已按合同纠正。
实际 MCP 工厂版本转发及停止验收通过；带真实隔离 Backend 的完整 MCP 26 个测试程序通过，临时 Backend 自动清理。首次完整运行误将 DSH 版本作为 Web 插件版本期望导致断言失败，恢复仓库插件默认值后通过，产品版本未更改。
复核本次 diff 仅改变 create_strategy_version 的 Backend handler 和 MCP 版本注册/转发、候选 schema 与公共运行时动作识别；既有台账其余 handler 未改，更新其整文件/相关依赖哈希，共涉及 67 个已有条目，不新增全接口完成声明。

独立 .96 构建清单通过，manifest sha256:a8ccac4c51dd57017c4ca1c6788b14954d50f0a8414f6efc663dd63ad550ab77。124 项架构测试全绿，make dev-check 通过；台账 112/560，448 未核对，8 人工入口待审。远端 CI 待新提交执行。
