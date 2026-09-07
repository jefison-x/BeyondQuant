# Post-U8 可靠性审计执行记录

状态：IN_PROGRESS，2026-09-07。DSH保持0.1.2rc1；Tushare数据扩容不在开发范围。
本记录是实施审计，不代表已完成所有接口检查。范围为既有R/S/F需求。

## 发现方式与覆盖

`python3 scripts/ci/inventory-reliability.py` 从源码枚举Python routes、MCP tools、Worker入口，
所有项目默认NEEDS_EVIDENCE。挂载路由、动态路由、Gateway catch-all实际映射和Cloudflare
TypeScript handlers需人工补齐后才能声明全量。不得将发现数量当作验证数量。

初始基线枚举结果：413个路由（Backend 227、Gateway 174、Runtime Adapter 10、Signal Sandbox 2），
78个MCP工具、4个Worker入口。全量接口的正确性结论仍为NEEDS_EVIDENCE。

首轮测试审查发现 `services/mcp/tests/ml-research-test.ts` 明确断言unknownTraining.isError=false，
并只覆盖“提交超时后立即查到”与“立即404”两种结果，未覆盖晚于回合结束才落库和训练完成后的续接。
因此旧测试绿色并不能证明本次链路正确；新增回归必须覆盖迟到commit → 原identity核对 → 下游推进。

## 已确认及修复优先级

| 顺序 | 缺陷 | 代码证据 | 计划 |
|---|---|---|---|
| 1 | 未回答主题丢弃 | Gateway `_conversation_context`；ADR-0046 原 §2 | R2；ADR-0062已接受，待合同优先修复 |
| 1 | 活动失败/未知误标 | AgentActivityPanel、ml-research outcome_unknown isError=false | R1/F3；合同与UI联测 |
| 1 | 固定child截止、领域active不收尾 | Runtime `_enforce_run_guards`、生产盘点 | R3/R4/F10 |
| 2 | ML准备先执行、提交后落库 | Backend `create_ml_training_run` | F1；异步化并先登记identity |
| 2 | 仅一次核对，迟到结果丢链 | MCP `createTrainingWithReconciliation` | F2/F6；持久核对 |
| 2 | 审批submitted不代表完成 | Gateway `_continue`相关入口、Agent审批状态 | F4/F5/F6 |
| 2 | ML错误反馈过于粗略 | MCP `requestMl` 422处理 | F7；封闭字段错误 |
| 3 | index创建未接Agent，导入不触发刷新 | MCP `byq_pool_create`、stock_pool_producer | S1/S2 |
| 3 | 历史成分缺口 | 中证500仅2026年三份verified样本 | S3；不扩展新数据集 |

所有其他接口的8秒等待只是审计线索，尚未断言存在同样缺陷。读写授权、幂等、超时、
业务状态、通知及恢复逐项检查；后续批次在此记录VERIFIED_OK或CONFIRMED_DEFECT的证据。

第二轮源码审查新增两项CONFIRMED_DEFECT（代码路径证据，尚无本次生产重复写入证明）：

- Gateway `product_create_research_task` 每次POST新建UUID并用作幂等键，忽略调用者稳定请求身份。
  同一用户请求在响应丢失后重试会变成新的后端身份，需补稳定客户端请求键及scope/冲突测试。
- Gateway `_backend_request` 把所有transport errors合并为503 backend_unavailable，不区分读请求失败
  与写请求结果未知；且成功响应的JSON解码不在异常处理范围内。需闭合unknown与invalid-response投影，
  不能向用户暗示写入未发生。Factor MCP也有无结果核对的写超时路径，领域副作用需继续检查。

## Community检查与分类

只读检查 `BeyondQuant-community/agent-service/app/harness/workflow.py`：
保留“阶段从持久artifact/approval派生”语义为REFERENCE_ONLY；不复用旧repository/runtime。
其失败后 `retry_with_new_idempotency_key` 不适合unknown outcome，分类DROP；
其捕获所有异常返回空数组不能用作数据不存在证据，分类DROP。
后续涉及具体领域或UI前继续检查对应实现并更新正式migration inventory。

## 架构门禁

2026-09-07，维护者明确确认ADR-0062，并要求同步修订ADR-0046和ADR-0045。
ADR-0062现为Accepted：ADR-0046原先的未回答消息丢弃规则已被保留、分区恢复与去重规则替代；
ADR-0045仅增加有任务绑定许可、24小时/8次回合预算和逐动作授权的后台续接例外。
其余MCP、Provider、身份与审批边界不变，不追溯授权既有生产研究，不授权部署或数据扩容。
架构接受门禁已解除；下一步为失败合同测试与分批实现，尚未宣称代码修复或验收完成。
