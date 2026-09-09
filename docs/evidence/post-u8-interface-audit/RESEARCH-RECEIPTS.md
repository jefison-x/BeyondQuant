# Research 创建回执原键核对

维护切片，Product Phase 97 不变。依据 ADR-0062，使用现有持久幂等映射。

## 实现范围

Backend 新增只读 `/v1/research/submissions/reconcile`，覆盖 ResearchTask、Experiment、Artifact 创建结果。
MCP 扩展现有 `byq_research_get`，兼容最终 ID 读取，新增原 idempotency_key 核对；子实体必须提供原 task_id。
验证可信 active owner/workspace，子实体核对原任务归属；仅返回精确匹配的公开实体。
无记录为 outcome_unknown，不代表创建失败；不重放写入、不扫描列表、不猜最新对象。

本批仅交付原键读取能力，不包含提交前持久登记、持久 watch、自动轮询预算或下游自动续接。
Backtest 等其他非 ML 提交仍待整改，F2 不关闭。

## 定向验证

- 原接口缺失的初始回归：三类实体均 404，3 FAILED（本地 RED.log）。
- 实验输入最初缺少必需来源字段；补齐真实领域契约。工作区和禁用身份断言按既有 401 契约校准。
- 新增 9 项 Backend 回归，覆盖未提交→迟到提交、精确父任务/key、异主、错工作区、禁用/匿名身份、非法 selector。
- 关闭并重新实例化 ResearchStore 后仍找回同一完整公开实体；这是连接/store 重建证据，不冒称独立进程重启。
- 核对时把全部 create/list 方法替换为失败断言，确认无创建或列表回退。
- MCP 覆盖三类状态、Unicode key 编码、互斥 selector、异常响应/传输、旧 ID 兼容。
- 单独完整 npm test 因缺少测试服务令牌停止；完整合同交由隔离 CI 启动依赖后验证。
- 探针只使用内部临时网络、tmpfs PostgreSQL、合成用户，源码只读挂载；无生产、Community 或付费调用。

## 完整验证

- 最终定向 Backend 26 PASS（新增 9 项），18.08 秒；MCP 编译及 research 契约测试通过。
- 独立 `.20` 基线/候选构建清单最终 check 均 PASS；历史 `.19` 及以前证据不改写。
- CI scope `post-u8-research-receipts-20260909`：退出 0，26/26 检查通过。
- 架构 228；Backend 523 PASS、1 SKIP、7 subtests PASS，494.65 秒；Gateway 202 PASS。
- Runtime 基线 149 PASS/35 SKIP；候选 158 PASS/26 SKIP；真实候选进程 23 PASS。
- 完整 MCP 合同通过；Frontend 176、模拟浏览器 20、真实 Product API 浏览器 9 项通过。
- 全栈 smoke、重启持久化、双用户隔离与 Product coherence 均通过。
  全栈既有重启场景不等于本接口进程崩溃后端到端核对专测。
- 框架弃用及既有浏览器警告按原日志保留，跳过不计通过。
- 探针与全 CI 的作用域资源均独立核验清理 PASS；未读取或修改生产/Community 数据。
- 本地脱敏日志 `.ci-artifacts/research-receipts/LOCAL-CI.log`（忽略、不提交），SHA-256：
  `703e16b3d43f0a0575b3ae50d2860acd3b1464e8f0bfee16b0e6f96c76d67d34`。
- 本地验证与提交范围；未 push、无 PR/远端 CI、未 merge 或部署。

本切片关闭三类创建回执缺少原键只读入口的问题。后续优先覆盖 Backtest 原键核对，
再完成具名提交的持久登记、预算约束下的持久等待及续接证据；F2 仍未完成。
