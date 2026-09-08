# F7 后续实现入口核查（2026-09-08）

状态：隔离实现中，不得据此关闭 F7。后续 root-turn、日志 v3、私有投递和持久准入进展见
[纠错台账切片](F7-CORRECTION-LEDGER.md)。下列首批记录保留其当时证据边界，不作为最新通过结论。

当前安全接入门禁：同 generation 两根回合的真实 HTTP 探针确认缺少可独立关联的根身份。
[ADR-0067](../../architecture/adr/ADR-0067-root-scoped-runtime-call-identity.md) 根回合隔离方案
已于 2026-09-08 获维护者批准。已有摘要合同仍为未接入原型，不是可信执行许可；不能跳过
真实请求归属资格验证直接部署 Backend 计数器。

## ADR-0067 首批实现（2026-09-08）

- 新进程恢复不再清除旧根的待确认终态屏障；只接受 Backend 精确回执释放。
- 取消/watchdog 的旧进程关闭进行中禁止恢复或释放；捕获实际待关闭 harness，不读取已替换对象。
- 现有生命周期日志升级为 v2，持久保存精确终态 ACK；落盘失败不解除屏障，释放/重建不丢失
  待确认状态。无活跃 Runtime 时也可只认领原日志确认回执，不创建进程。v1 先校验原始摘要再
  显式迁移，缺少 ACK 证据保留未确认，不推断已关闭。
- Gateway 不再把 Adapter ACK 404 当成功；原有有限投递账本按最多 256 条扫描/16 次发送一轮，
  一次性重新确认旧已投递终态。不投递提示、不重跑研究、不清零已有 pending/exhausted 次数。
  缺少历史证据显示 unavailable，不伪造 up_to_date。
- 在准入锁内捕获工作线程的 harness/private session 身份；延迟旧线程不得读取新进程执行。
- 官方 SDK 的 `start_session()` 隐式调用 `start()`，而 `close()` 会重置初始化状态。
  因此兼容层将官方 Session 准备与执行分开，准备在取消锁内，执行仍使用官方 `Session.run()`；
  不修改 SDK 私有方法。0.1.2 的实际发送路径在 transport 关闭后拒绝，不自动启动进程。
- `scripts/dsh/root_profile.py` 为两基线生成独立 `profiles/root-scoped/` 配置和身份，
  仅增加受信根 header。原历史配置及其身份未修改；新配置尚未用于部署或视为已认证。
  生成器分别验证 Registry 元数据 + YAML 算法与 candidate 原文件 SHA-256，不能混用。
- Prompt 内部合同增加可选公开上下文投影，原子替换待用上下文；显式空数组清除旧对象，
  省略保留 create/resume 投影。非法角色在认领前拒绝；原始幂等回执不被重试上下文改变。
  Gateway 尚未逐轮发送，不能据此声称完整会话连续性通过。
- 源挂载保留依赖镜像的无网络回归：Gateway 193 passed；0.1.1 Runtime 131 passed / 22 skipped。
  0.1.2 Runtime 134 passed / 19 skipped（开启两个官方进程 loopback wire 探针，无付费调用）。
  独立配置单元测试 3 passed，生成一致性通过；新增官方 Session 关闭路径测试
  在两套 SDK 分别 1 passed（公开 start 替身，无实际进程，不冒充真实进程 qualification）。
  这些是源级回归，不是新构建认证；真实进程/付费 API 跳过不算通过。

日志 v2 必须随独立构建做联合升级/恢复资格验证：旧 Adapter 不能读取新 v2 日志，不能把
混版本 Gateway/Adapter 或旧应用直接读取新状态视为兼容回退。当前只在隔离临时数据上测试，
未迁移生产日志。历史源绑定清单仍不匹配当前源码，未运行/宣称新的全栈构建验收通过。

尚未完成：每根实际进程切换、每轮公开上下文恢复、可信调用持久投递与 Backend 纠错准入，
以及 ADR-0067 的真实多轮/迟到请求/20-cycle 资格验证。F7 保持开放。

接受后的首轮实测见 [官方调用观察资格切片](F7-CALL-OBSERVATION.md)：7 项观察探针通过，
Runtime 132 passed/7 skipped；构建身份漂移导致架构检查未全绿，仍未完成持久准入。

后续核查：仅传入 AgentRun 引用不足以证明当前调用的根归属。下述实现计划必须结合
[ADR-0066](../../architecture/adr/ADR-0066-domain-validation-call-admission.md)
的逐调用可信证明；维护者于 2026-09-08 批准该决策，先隔离资格验证再实施。
接受不代表工具观察、schema 拒绝覆盖或持久准入已通过，不将 AgentRun 引用本身当作调用凭证。

## 已有能力与缺口

- `services/backend/app/agent_research.py` 已有 `agent_runtime_turns`、
  `agent_runtime_registrations` 和 `agent_runs.root_run_id`。可信注册观察可将 AgentRun
  绑定到 Adapter 所见根回合；应复用，不能按 SDK generation 新建第二回合账本。
- `services/mcp/src/server.ts` 的 `trustedBackendFetcher` 传播 owner/workspace/actor/
  session/trace/process generation，但策略校验/ML 创建参数尚未要求精确 AgentRun。
  不能把同进程中“最新 active run”或 model 自报 root_run_id 当作该调用的可信归属。
- `AgentResearchStore.authorize` 校验 run 的 owner/actor、session/generation 和角色，
  但独立授权调用不等于下一 HTTP mutation 的已绑定一次性请求身份。
- `ml-research.ts` 的 `repair_limit: 1`、`strategy.ts` 的安全错误反馈只是提示；
  不能代替 Backend 对并发、重启、换幂等键和换子 Agent 的持久限制。

## 下一批测试先行范围

1. 沿现有 MCP → Backend 策略/ML 请求传入可核查 AgentRun 引用，Backend 校验既有
   trusted registration、root、owner/workspace/session、task 与精确动作。缺绑定时拒绝
   Agent mutation；普通用户 Product 操作不能被错误计入 Agent 纠错预算。
2. 在 BYQ 领域侧以根回合 + 原任务 + 动作作为不可通过换 idempotency_key/child 重置的
   修正范围，记录规范输入 hash、请求身份及封闭结果，不保存 raw 异常或凭据。
3. 先持久认领再校验；相同请求只重放原结果，相同 key 不同输入拒绝。首次失败允许一次
   明确修正，重复无进展或预算耗尽明确阻断。未知结果先查原回执，不能视为可再提交。
4. 并发重复、事务回滚、结果写入前后崩溃、重启、旧终态 run、跨 owner/任务、同根换
   child、下一用户回合及正常 UI 请求分别给失败反例；safe error 和界面状态不能说成成功。

实施保持 ADR-0031/0062、MCP-only 与 Product/Engineering 隔离。若发现现有可信注册无法
证明请求归属，应先记录具体 seam 缺口与决策，不以“实现了计数器”冒充 F7 完成。
本核查未调用模型、未改 Backend/MCP 或生产数据，不授权历史研究续跑。
