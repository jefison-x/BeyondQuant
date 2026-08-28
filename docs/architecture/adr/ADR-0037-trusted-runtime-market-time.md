# ADR-0037：可信运行时钟与交易会话时间分层

- Status: Accepted
- Date: 2026-08-28
- Accepted: 2026-08-28
- Decision scope: Post-Phase 62 Product Agent 时间认知维护修复
- Related: ADR-0003、ADR-0027、ADR-0032、ADR-0033

## 背景

真实 Product 会话“今天日期是？”正常结束，但模型明确表示无法读取系统时钟。更换模型
没有解决问题，其中一次回答还被公共投影拒绝。根因是 Product DSH composition 既没有在
模型组装时注入可信时间，也没有向 Agent 暴露“当前自然日”和“最新交易日/数据截止日”
之间的明确边界。

DSH `0.1.1-rc.1` 已提供 `ctx.systemPrompt.context()`：动态 provider 在每次 prompt
assembly 时求值，并作为带来源的 runtime-context snapshot 进入 DSH 历史。BYQ 的
ADR-0027 则已经持有 `Asia/Shanghai`、SSE 交易日历和完整市场快照。两者职责不同，
不能用一个自然日字段替代。

维护者于 2026-08-28 明确要求完成双层时间方案。本 ADR 只修复已有 Product Agent 的
时间认知，不定义新 Product Phase，不授权 release、tag、生产发布或其他研究能力。

## Community 检查与分类

只读检查了 `/home/jefison/projects/BeyondQuant-community`：旧 PydanticAI runtime 在
回测工具边界直接调用 `date.today()`，其 Agent runtime 和 prompt coupling 为
`REPLACE`，不得迁移。旧 scheduler 的 `Asia/Shanghai`、timezone-aware schedule 以及
相对日期确定化测试意图为 `PORT_LOGIC`/`PORT_TESTS`，但当前 BYQ 已由 ADR-0027 独立
实现；本修复只复用现有 BYQ persistence，不复制 Community 代码或架构。

## 决策

### 1. DSH 拥有自然日和墙上时钟

增加 BYQ composition-local DSH plugin，通过 `ctx.systemPrompt.context()` 注册唯一动态
上下文。Provider 在每次模型调用前读取服务器时钟，提供：

- RFC 3339 UTC instant；
- deployment-owned IANA timezone，当前固定 `Asia/Shanghai`；
- 带 UTC offset 的当地时间；
- 当地自然日。

时间不在进程启动时冻结，不由 Browser、用户 prompt 或模型 provider 提供。上下文明示
自然日只用于墙上时钟和相对自然日，不能证明交易日、开盘状态、最新完整行情或数据截止。
该插件属于 DSH 通用 Agent capability，不修改 Runtime Adapter 用户消息，不新增第二套
Agent harness，也不 fork DSH。

### 2. BYQ 拥有交易会话和数据截止

增加只读、无参数的 `market-session-context.v1` Domain projection，经
Backend → BeyondQuant MCP 暴露为 `byq_market_session_context`。它只读取 ADR-0027 已有
PostgreSQL 事实：

- 当前 `Asia/Shanghai` 日期是否有已验证 SSE calendar row；
- 已验证时该日为 `open` 或 `closed`，未验证为 `unknown`；
- calendar 已覆盖到的日期；
- 不晚于当前日期的最新完整 persisted market session、row count 和验证时间。

该读取不调用 Provider、不触发同步、不读取 credential，不返回 worker、job、schedule、
error、dataset hash 或内部 ID。`quant_orchestrator` 与 `market_researcher` 升级到 v1.3.0
并获得该只读动作；每次调用仍需准确授权和审计。其他角色不扩权。

### 3. 两层不得互相推断

- “现在几点/今天几号/过去 30 个自然日”使用 DSH trusted runtime clock；
- “今天是否交易/最新完整交易日/行情截止到哪天”使用 BYQ session context；
- calendar 未验证或完整快照不存在时必须回答未知/不可用，不按星期、时钟、模型知识或
  最新一根零散 bar 推断；
- 最终回答保留用户有价值的日期和缺失事实，不暴露 raw tool、DSH/MCP schema 或内部
  control narration。

## 拒绝的替代方案

- 在 Runtime Adapter 前缀修改用户消息：污染 durable conversation 语义与审计来源。
- 依赖模型训练日期或切换 provider：运行时钟不是模型固有事实。
- 由 Browser 传入权威时间：客户端可篡改且时区语义不稳定。
- 用普通 clock MCP 代替 DSH context：把通用能力错误放入 Domain Plane，并要求无意义的
  工具往返。
- 用自然日 `today` 代表数据完整性：周末、节假日、收盘前和同步延迟都会产生错误。

## 验收

- 固定 instant 测试 UTC、`Asia/Shanghai` 和 DST IANA timezone 格式；非法 timezone
  fail closed；
- composition 启动后每次 assembly 均包含具名动态时间 snapshot；
- Backend PostgreSQL test 覆盖 open/closed/unknown、calendar coverage、latest complete
  session 和 no-provider path；
- MCP translation/schema/role tests 覆盖无参数有界读取、安全失败和最小权限；
- Runtime normalization 只显示本地化领域活动，不泄 raw schema；
- 真实 Product 会话能回答当前日期，并能把当前日期、交易日和行情截止日明确区分。

## 回滚

从 composition 移除时间 plugin，并移除 MCP tool、Backend projection 和两项 role
permission。现有 calendar、market completeness、DSH sessions、WorkflowTrace 和审计记录
均不删除、不改写。
