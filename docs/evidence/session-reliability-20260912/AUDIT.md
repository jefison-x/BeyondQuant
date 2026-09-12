# 2026-09-12 会话故障修复

## 授权与范围

维护者在近期生产会话只读诊断后回复“好的修复。”。本任务为独立 bugfix，Product Phase 97 不变。
仅开发和隔离验证；本记录不授予生产数据库修写、历史研究续跑、部署或正式发布权限。
遵循 ADR-0062/0065/0066/0067 的既有边界，不扩大首批两工具的 F7 持久准入范围。

## 已确认现象

一条审批续接在 900 秒根回合上限收尾，AgentRun 已正确失败，无 stale active 复现。
错误审批将普通策略版本标为 generic artifact；人工批准并不满足执行端 strategy_version 精确绑定。
同时观察到研究状态误用 active/in_progress/blocked、按 ID 查询混入 task_id，以及重复后台 404。
404 来自另外两个旧会话，不作为本次超时根因。原始会话、对象标识及模型私有内容不发布。
三个早期 experiment/backtest 422 的确切字段未确认，不把常见错误提示测试当作这些原请求的复现。

## 修改

- Backend 和 MCP 在创建审批时要求动作对应的准确资源类型和 ID。执行端精确校验保留。
- 已有错误审批在 queued/failed → submitting 认领前进入 needs_attention，不启动模型，次数不增加。
  已 submitted/outcome_unknown 的回执及人工决定保持原语义，不伪造执行失败或成功。
- 同一事务仅将审批明确关联、同 owner/workspace/conversation/session/trace、仍在 approval 阶段的
  planned/running 任务进度改为 blocked。保留任务状态及对象链接，不选最近任务、不自动重跑。
- 非法研究状态在 MCP 拒绝并返回合法状态；blocked 是 progress.stage。按 ID 查询明确要求省略 task_id。
- 常见研究/回测 422 返回封闭字段/审批指导，不透传任意 Backend detail、输入值或内部路径。
  repair_limit=1 仍是指导，不冒充这些新工具已经获得持久纠错额度执法。
- 研究回执核对失败持久退避 30/60/120/240/300 秒，保留待核对状态；独立 F6 消费继续。
  成功重置退避；上下文变更、损坏状态及进程重建有测试。

## 验证

构建身份：`dsh-0.1.2rc1-post-u8.49`；manifest SHA-256：
`9cca0f3b4db7f88fc78dc0f8f5d362a0d968ca96ebfda2aefcd5cbc701e09967`。

| 检查 | 结果 |
| --- | --- |
| 隔离工作树检查、dev-check、diff whitespace | PASS |
| Backend 完整套件，真实 PostgreSQL 16 | 591 passed、1 skipped、7 subtests passed |
| Gateway 完整套件 | 224 passed |
| MCP 编译及 package test 全部 24 个入口 | PASS，含实际 MCP → Backend HTTP 合同 |
| 架构测试 | 237 passed |
| 最终不可变构建清单校验 | PASS |
| 测试容器及网络清理 | 本次 scope 残留为零 |

先执行的审批入口与退避回归测试在未修复时失败；修复后通过。
过程中修正了测试挂载路径、独立工作区准备和 Node 测试环境；失败不计为通过。
Backend 的一项 skipped 不冒称已执行。没有真实模型或真实浏览器全旅程认证。
数据库验证使用专用内部网络、临时 PostgreSQL 16 和 byq_domain_test/byq_mcp_test，
无宿主端口、无生产挂载；结束后容器及网络均清理。没有构建新应用镜像。

## 交付状态

本地修复已验证并保存在独立分支；未推送、未合并、未部署。
远端 required CI、合并门禁及生产健康/业务验证仍属于后续交付步骤；本地结果不替代它们。
主工作区保持干净，独立版本规划工作树未改动。

## 限制与后续

不延长 900 秒超时，不宣称全面消除模型无进展或所有工具重试。
F7 其他工具、S3 全旅程和历史故障任务处理仍是剩余事项。
本次不批量改写旧审批，不续跑已有生产研究。错误审批须按准确版本重新走授权流程。
