# F7 私有证据与纠错台账实现切片（2026-09-08）

状态：首批两工具实现、无密钥全 CI、Chrome 及跨服务 schema-stop 通过；**不是全部 F7
场景矩阵完成或生产上线认证**。Product Phase 97 不变，
U8 仍为 `CLOSED_EARLY_REMEDIATION_REQUIRED`。未部署、未 push/merge、未付费调用。

## 本切片已实现

- ADR-0067 root-turn 模式：每根独立 generation/private session/官方进程，可信根 header
  与三轮真实 loopback HTTP 对应；保留公开会话，Gateway 在保存新输入前取得有界公开上下文。
  原回答尚未持久化时拒绝下一根，避免“继续”遗漏上一轮方案。
- 原生命周期日志当前实现为 **v3**，追加私有身份/摘要观察；v1/v2 必须先验证原摘要，
  再显式迁移，不虚构旧调用证据。不修改历史报告及生产日志。
- Adapter 私有分页接口 → 复用 Gateway LifecycleDelivery 私有模式 → Backend 专用表。
  不写入 TraceStore/SSE/回答/模型上下文；每页 256、每会话 1024 条，精确回执、8 次/24 小时
  失败预算，先落盘再发送，重启不清零。证据到达不执行领域请求。
- Backend 校验 owner/workspace/session/trace/root/generation、原任务会话和 AgentRun 角色。
  首批仅两个工具；正常用户直接操作保持现有身份路径，不伪造 AgentRun 或扣 Agent 额度。
- 根/任务/动作纠错桶：首次可修复失败后只允许一次不同输入修正；相同失败输入换 key 不执行，
  并发修正只认领一个。认领及执行资格先提交，未知结果不返还额度、不自动重跑。
  Artifact/transition 与成功回执共用事务；领域校验失败使用专门异常分类，不把普通存储错误
  误当可修复失败。历史失败、额度和回执不删除。
- 两个 MCP schema 共用原领域限制，并增加 AgentRun 引用；通过公开 Fetch adapter seam 观察
  schema 拒绝。SDK 仍执行原校验；停止状态仍为 tool error，并保留 SDK 原错误，不执行领域回调。
  仅精确的“尚未认领、缺证据”425 可以在同一次工具请求内有界等待/重送；409、5xx、超时不重试。
- 并发测试发现 Store 重复启动 DDL 可能锁升级死锁；基础 bootstrap 已增加事务级启动锁，
  不串行化正常领域操作。扩展 bootstrap 的并发覆盖仍需补充。

## 已执行验证与失败记录

全部使用保留镜像作为依赖载体、当前源码只读挂载；**不是这些历史镜像的新构建认证**。

- Gateway：200 passed，含私有投递、坏页/缺序号拒绝、重启预算和公开轨迹隔离。
- Runtime 前一子切片：140 passed / 19 skipped，含四个真实官方进程 wire 探针；
  这是 native stop 接入前的结果，不代替最终回归。
  native stop 接入后完整 Runtime 源级回归：142 passed / 19 skipped；新增两 owner 等测试尚需重跑。
- Backend 最初证据 + 生命周期：19 passed；台账 + 研究事务：34 passed。
- Backend API 接入初次回归：2 failed / 40 passed。失败分别为并发 bootstrap 死锁、
  旧审批测试未提供新调用证据。保留并发测试，修复启动锁；审批测试的前置 Artifact 由人类路径
  创建，另新增两个工具的真实 Agent 证据/Artifact 原子成功测试，不放宽 Agent 入口。
  后续回归：45 passed。
- MCP 编译及官方 schema 观察、策略/ML 翻译测试通过。初次编译暴露容器 dist 只读和测试泛型
  联合类型问题；临时编译目录与测试注册类型修正后通过，未改 SDK/生产依赖。
- native stop 首次真实进程测试为 2 failed / 8 passed：官方 MCP 错误在 DSH 中包装成
  `Error: {…}`，不是裸 JSON，不能把该失败当通过。仅针对封闭 BYQ admission 标记增加
  首行有界解析，原始错误保持不变。后续两工具真实停止 + 多根测试 **10 passed**；
  合成 Provider 故意继续请求工具，当前进程确实关闭并记录 `domain-correction-stopped`。
  这不代表两 owner/child/完整跨服务 schema-stop 已全部认证。
- 20-cycle 相对对照：4 passed / 6 deselected，两工具各对比 20 轮。复用模式单轮中位数
  0.066/0.044 秒；逐根模式 1.177/1.094 秒，最大 1.608/1.600 秒。初始化实测 0.648–1.178 秒。
  逐根模式每轮后子进程数均为 0，活跃进程家族采样 RSS 最大约 297–301 MiB；轮后测试进程
  RSS 约 59–64 MiB，20 轮增长约 2.3–2.5 MiB，包含测试保留的请求/事件/指标，不能声称零增长。
  复用模式保留 1 个子进程，轮后家族 RSS 约 270–299 MiB。此为本机无付费合成 Provider
  的控制开销，不是生产模型端到端延迟或正式容量压测。
- 安全审查未允许将证据接收的重复授权检查合并到 helper；保留原检查，并增加重放时原会话
  检查。未以绕过安全审查的方式删除权限校验。

## 独立构建验证与剩余边界

2026-09-08 补充验证：Gateway 202 passed；Runtime 源级回归 147 passed / 23 skipped；
Backend 并发 bootstrap、私有证据和台账组合 26 passed；独立 `.7` 构建架构 224 passed。
MCP 实际 server wire 的私有根引用、425 原请求重送和 SDK schema 拒绝保留测试通过。
上述结果不替代完整跨服务资格。

`.7` 全栈 CI 在镜像构建阶段失败：新增前端测试给单参数 `workflowRunState` 多传了
session ID，TypeScript TS2554；未进入业务测试。仅修正测试调用，保留失败日志和 `.7`
清单；新 `.8` 两个清单通过 source binding 校验，前端镜像构建与 224 项架构通过。
Backend 全量进行到 32% 时，独立并发探针确认创建/恢复处于 STARTING 仍可被 release，
两项均失败；中断 `.8` 剩余 CI 优先补修，退出 130，精确 scope 清理验证通过，不记全量 PASS。
release 现拒绝 STARTING，进程初始化所有权不会被释放接口提前移除。
相邻回归首次 84 passed / 1 failed：双 owner 测试共用 FakeHarness 的 class Event，
关闭 Alice 也会释放 Bob；该测试改为每进程独立事件，不放宽 owner 隔离断言。
随后 85 passed，包含两项启动竞争、取消/恢复和双 owner 根停止。
`.9` 构建及架构通过，Backend 到 64% 时因补充探针确认整体 shutdown/初始化竞争而中断
（退出 130、scope 清理验证通过）。两条路径会把 CLOSED 重新写为 READY，探针 2 failed。
创建/恢复现在只允许 STARTING 初始化提交；迟到进程关闭，创建失败只移除自己的记录，
恢复构建/启动异常恢复 FAILED 而不复活 CLOSED。四项新回归正式进入 Runtime suite。
最终源级完整 Runtime：153 passed / 23 skipped（含六项开启的官方本地 wire 探针）；
新 `.10` 独立构建全栈验证进行中，尚非完整资格 PASS。已完成：架构 224 项通过；
Backend 446 passed / 1 skipped / 7 subtests（516.07 秒）；Gateway 202 passed；
兼容 Runtime 144 passed / 32 skipped；实际 candidate 镜像完整 Runtime
153 passed / 23 skipped（14.52 秒），真实官方进程/子 Agent 旅程 20 passed（29.71 秒）。
随后生命周期基准、MCP、前端构建和依赖审计通过；前端 54 files / 175 tests，
mocked UI 20 passed，真实 Product 浏览器 9 passed，领域重启/双用户核对通过。
`.10` 完整本地 CI 最终 **26/26 checks passed**，进程退出 0。
人工 Chrome 核查未赶在 CI 自动清理前完成，因此仍单独开放；按同一 `.10` 源清单重建
独立浏览器栈，不能将新镜像 ID 冒称为原 CI 镜像。未调用付费模型或修改生产。

### 补充的真实页面与跨服务旅程

独立 scope `post-u8-f7-browser-20260908-10`，同一 `.10` 源清单，六服务健康；未启动
Data/ML/Signal Worker。Chrome 独立上下文、合成 `ci-f7-browser`，真实登录和 Product
持久会话，三个规范化停止事件为明确测试夹具，不是实际业务失败或模型评测。
1365×900 和 390×844（刷新后）均保留三个中文停止原因、历史记录和“新一轮不表示原任务
完成”说明；无横向溢出、无直接重试引导、无私有凭证字段。刷新后的 10 条请求均为同源
Auth/Product/规范 WorkflowTrace 且 200；console error/warn 为空。仅关闭本次 Chrome 页。

随后仅将该测试 Runtime 接到不转发外部请求的本地脚本 Provider，保持官方进程、真实
Gateway/MCP/Backend/数据库。分别以两个独立合成用户执行策略与 ML schema-stop：
每项恰好 4 次本地合成响应（注册 AgentRun → 创建任务 → 首次无效输入 → 一次不同输入修正），
随后真实进程以 `domain-correction-stopped` 收尾，无 session.result、无第五次模型请求。
数据库核对：每用户 2 份私有证据、2 份 correctable_failure 回执、repair_used=true，
两个 AgentRun 均 failed；两个研究任务仍 planned，未把模型停止伪造为研究完成。
Artifact、训练运行、预测运行均为 0。没有真实 DeepSeek 或其他付费调用。

Backend/Gateway 重启后再次核对：两桶仍 repair_used=true，4 份 claim、2 个 failed
AgentRun 保留；Product 恢复两份停止记录，本地 Provider 仍为 4 次请求，没有新增模型请求。
可复现夹具保存为 [页面夹具](f7-browser-seed.py)、[本地 Provider](f7-joined-provider.py) 和
[Product 旅程](f7-joined-probe.py)，仅适用于全新独立合成栈，不可对生产执行。
验证后精确清理 scope：7 个容器、4 个合成卷、对应网络和镜像标签已移除，cleanup
verify 通过。合成数据未备份，可用夹具重建；CI 原作用域也单独验证为零。
生产、Community、历史报告和私有备份未修改。

目录级 Gitleaks 报告 12 处匹配，已逐项检查：反馈 Hub 的固定假凭据、四字节伪 PEM
及测试运行时生成的临时 RSA key 模板，凭据存储测试的合成 token，其他测试的幂等键，
以及迁移文档的 API/架构文字误匹配。未发现真实凭据；未增加豁免或关闭任何扫描规则。
原始脱敏扫描报告保留在隔离工作树 `.ci-artifacts/f7-gitleaks-redacted.json`。
随后暂存改动的 stdin 扫描约 865 KB，通过且未新增任何豁免；最后 shutdown 补修及合同
文档入暂存后再次扫描约 1.02 MB，也通过。12 份变更文档与差异格式检查通过。

构建 `.6` 清单已独立保留但未认证：完整架构发现 224 项中 2 failed / 4 errors，
包括测试中使用默认 SDK 构造器和冻结后补充保留上限保护导致的真实源漂移。
测试改为明确配置官方 SDK，不降低架构断言；后续用新 `.7` 身份重新认证，不覆盖 `.6`。
只有 candidate 的新 Post-U8 Dockerfile 启用 root-turn；0.1.1 比较载体保留 session 模式，
不将其生命周期测试当作 F7 领域准入资格，也不授权部署回退。生产选择器及 U6/U7 Dockerfile 未改。

首批两工具的 schema-stop、私有投递/持久回执、无密钥全 CI 和本切片 Chrome 已有上述证据。
仍需逐项收口完整自然语言研究语义旅程，以及多 child/迟到 HTTP/撤销竞争矩阵中当前仅有
组件测试的跨服务场景；不能把本地脚本 Provider 当作真实模型遵循证据。历史 `.5` 清单
不匹配当前源，不得覆盖其已发布身份或使用其旧 PASS 为本切片背书。

F6 全调用累计 token/cost qualification、S3 既有指数需求/cache 流程仍未完成；后台主动续接
保持关闭，数据扩容暂缓。当前无生产部署及本分支 push/merge 授权。
