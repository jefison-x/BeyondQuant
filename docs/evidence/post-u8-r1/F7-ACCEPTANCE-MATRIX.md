# F7 最终验收核对（2026-09-08）

范围：ADR-0066/0067 首批 `byq_strategy_validate`、`byq_ml_strategy_create` 的可修正错误、
持久一次修正、无进展停止及根回合调用归属。不是所有领域工具都接入同一纠错账本。
不将 F6 主动续接、S3 数据准备或全研究流程自然语言验收混作 F7 完成。

当前：本范围 F7 整改与资格验证完成。最终 `.15` 本地整栈 26/26 通过，
独立 cleanup verify-only 通过；进入已授权 push/PR、远端 CI 与合并门禁，不包含生产部署。

| 门禁 | 证据与边界 |
|---|---|
| 安全字段错误、无原异常/源码 | `.15` [安全诊断](F7-SAFE-DIAGNOSTICS.md)：两工具实际模型请求收到白名单提示；Backend/MCP 恶意诊断过滤测试 |
| 一次修正成功/二次失败停止 | `.15` 正反实际官方进程：成功各五次本地请求、唯一成果；失败各四次、原生停止、零成果 |
| 换 key/child 不重置，同输入不重跑 | [兄弟子 Agent](F7-NATIVE-SIBLINGS.md) 两工具实际串行 child；当前 Backend 持久预算/并发认领测试 |
| 根、generation、owner/workspace/task 归属 | [台账](F7-CORRECTION-LEDGER.md)、[普通迟到 HTTP](F7-LATE-HTTP.md)、[ML 迟到 HTTP](F7-CROSS-SERVICE-LOSS.md) 与 current 私有证据合同负例 |
| 缺证据不执行，晚到不自动执行，有限 425 重送 | Backend 请求/证据顺序测试；MCP actual server wire、schema observation、admission；unknown/409/5xx 不自动重送 |
| 认领/执行异常、撤销/提交竞争、未知回执 | [原子回执](F7-ATOMIC-RECEIPT.md) 真实数据库锁竞争；[真实 MCP 断连](F7-CROSS-SERVICE-LOSS.md) 两工具唯一提交/回执；当前 Backend 全项回归 |
| 用户禁用阻止新领域写入 | `.15` 严格合法两工具请求在禁用后拒绝，新回合 401/403；历史普通夹具缺字段问题已具名更正 |
| 私有凭证不进入公开响应/事件 | `.15` 实际停止事件与模型错误提示断言，`.14` 迟到/断连 MCP 响应断言，Runtime private observation 源级负例 |
| 进程/root 终态、ACK、取消/重启 | current 生命周期测试；`.15` 诊断回执及 AgentRun/root 重启只读复核；`.14` ML 迟到取消后重放 |
| 中文同会话三轮、原目标及显式新目标 | [三根恢复](ORIGINAL-TASK-DISCOVERY.md) 官方进程 + 脚本 Provider，原任务唯一且未误建；不是付费模型自主研究成功率 |
| 初始化/RSS/20-cycle | [台账性能记录](F7-CORRECTION-LEDGER.md)：两工具20轮相对基线、轮后子进程零，明确记录RSS增长；本批不改 Runtime/组合进程机制 |
| 最终源及完整 CI | `.15` immutable 源身份通过；最终 CI `post-u8-f7-final-20260908-15` 26/26 PASS、退出0、独立清理核验PASS |

原并行兄弟探针保留 FAILED；当前显式 maxParallelToolCalls=1，未修改配置以制造通过。
并发认领及数据库提交/取消竞争另有实际测试，不以串行配置宣称不存在并发风险。
若未来改变并行设置，须重新验证原生并行 child，见[适用范围](F7-PARALLEL-QUALIFICATION.md)。

历史失败、U8 提前关闭结论、旧 release、生产拓扑不改。全部实验为合成数据与本地 Provider，
没有付费 API 或生产操作。脚本确定性资格不等同于完整金融研究结果质量认证。

## 条件性交付授权

维护者在确认本批只待 F7 完成后推送合并的顺序时明确指令：
“对，完全整改完F7以后，再推送合并。现在继续。”
范围为本工作树 F7 补测/修复，目标既有 `jefison-x/BeyondQuant`，以 main 为 PR base。
只有上表与本地最终回归完成后才 push/Draft PR；远端 CI 全绿并通过 ADR-0059 精确 head
preflight 后按 ADR-0015 squash auto-merge。不推 main、不绕过 required checks、
不包含生产部署、release/tag、F6/S3 交付或历史研究续跑。
