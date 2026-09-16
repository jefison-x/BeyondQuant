# H4：原键核对回执的原任务绑定

2026-09-13，本地维护，依据 Accepted ADR-0062；Product Phase 97 不变。

Backend 原键核对已有 owner/workspace/task 过滤。MCP 原先只校验回执类型、原键及对象 ID，
未校验 confirmed Experiment/Artifact 的 task_id。现要求与查询的原任务严格一致；
缺失或不一致返回 invalid_response，不尝试重放写入。这是跨层合同防御，未证实生产串任务。
ResearchTask 无父任务语义，未知回执不携带 entity，二者保持现有行为。

修复前新增失败测试在缺失父任务时复现；修复后两类对象共8个缺失/错误/null/数值任务身份回归通过。
原有正确回执、未知结果、单次 GET 和无写入断言继续通过。
MCP TypeScript build 通过。research、research-watch、write-outcome、ml-research、backtest
五个定向测试脚本全部通过。npm test 的前7个脚本通过，随后 contract-test 因缺少
独立服务配置 BYQ_MCP_TOKEN 停止；不声称完整 MCP/远端 CI 通过。

无 UI、Backend 数据结构或 DSH 权限修改；无生产、真实模型调用、push/merge/deploy。
隔离工作树承接前三批与 H4 首切片；完整 F2/F7/H4 及 H5 保留。
最终独立构建 .58，历史清单不改写。
