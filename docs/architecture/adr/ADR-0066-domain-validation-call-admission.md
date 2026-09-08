# ADR-0066：领域校验调用归属与持久纠错准入

- Status: Proposed
- Date: 2026-09-08
- Scope: Post-U8 F7；首批限定 `byq_strategy_validate`、`byq_ml_strategy_create`。
- Related: ADR-0003、ADR-0031、ADR-0062、ADR-0064。
- Acceptance: 尚未取得维护者对本决策的接受。只允许只读核查、文档和隔离资格验证，不授权新准入路径上线。
- Supersedes: 不撤销既有安全边界；补充 ADR-0031 的“一次修正”和 ADR-0062 的根回合绑定。

## 已确认事实与证据边界

1. Runtime `_build_harness` 把 `BYQ_DSH_RUN_ID` 设置为进程 generation；它不是当前根回合。
   MCP `trustedBackendFetcher` 传递该进程身份，没有每次调用的可信根回合凭证。
2. Backend 已有 `agent_runtime_turns`、可信注册 fingerprint 和 `agent_runs.root_run_id`。
   这些证明某 AgentRun 注册属于某根回合，不能单独证明任意后续 HTTP 写请求属于该注册。
   `AgentResearchStore.authorize` 不接收完整领域请求或当前调用观察身份。
3. 现有 `test_agent_run_lifecycle.py` 明确测试相同可信进程上下文中的不同根回合可以独立注册、
   收尾。该不变量是必要隔离能力，不是应删除的测试；不能把数据库中“最新 active run”当调用来源。
   这是源码和既有测试合同证据，不声称本次又做了真实模型攻击复现。
4. Adapter `_on_notification` 已通过 source_run/private session 检查，把实际观察到的注册
   关联到当前 ActiveRun。这是可复用的已有 seam；尚未资格验证两个领域工具的完整调用输入、
   SDK schema 拒绝、并发和取消窗口，不能把注册能力直接宣称为调用凭证能力。
5. 现有 `repair_limit: 1` 为提示。仅在 Backend 计数还可能漏掉 MCP schema 提前拒绝的请求。
   这不证明官方 SDK 没有合格接口；必须检查所锁版本并做失败测试。

## 拟接受的决策

### 1. 最小内部调用凭证

Adapter 只针对首批两个工具，从官方受支持通知/接口中观察真实调用，绑定可信 owner、workspace、
session、trace、generation、root-run、工具动作、原任务、幂等请求身份和规范输入摘要。
Model 提交的 AgentRun/task/key 只是待校验引用，不是可信根身份；凭证必须与 Backend 的原始请求、
既有注册和任务会话关联精确一致。跨根复用、同 key 改输入、换 child/角色或伪造引用不能重新准入。

凭证经已有 Gateway 持久投递设施进入 Backend，不增加另一套通用队列或 Agent loop。
凭证是专用内部控制合同，不是 Browser WorkflowTrace：默认不得进入公开 events、SSE、
conversation replay 或模型上下文。只传必要身份、序号和摘要，不传策略正文、原始参数、
提示、工具结果、隐藏推理或密钥；摘要同样按私有数据处理，不公开发布。
Backend 是唯一持久领域写入及纠错预算权威；DSH 不访问数据库。

### 2. 先持久认领，再执行

请求先做可信身份与基本封闭输入验证，再保存固定请求 identity/hash。没有精确凭证时可以
保留有限的待确认回执，但不得运行领域校验、创建 Artifact 或谎报成功。
凭证晚到不自动执行原请求：只能查询，或在仍获授权的原请求重试时重新核查后准入。
待确认注册有数量/大小/期限上限，缺证据失败不能变成新的无限存储入口。

同请求只查询/重放原回执；不同内容复用 key 拒绝。所有次数在执行前持久化；崩溃、断连、
结果写入失败保持 unknown 和已占预算，不通过超时、重启或新 key 自动恢复额度。
原结果确认与领域 Artifact 幂等/事务边界必须共同验证，不能把一次校验成功计作 Artifact 已落地。

### 3. 一次修正与无进展停止

纠错预算绑定 owner/workspace + 可信根回合 + 原任务 + 动作，不按进程、子 Agent、模型自报
回合或每个新 key 分桶。正常首次成功的不同领域操作不消耗“修正”额度；发生首次可修复失败后，
该范围最多准入一次不同输入的修正。修正额度不因换 key/child、重复通知、成功回执重放或重启归零。
同一失败输入不得再次执行；修正仍失败或额度耗尽时持久阻断并给出封闭原因。
新根回合仍需新的可信证据，不为历史任务追溯创建许可。

该准入只限制 BYQ 领域调用，不宣称能终止所有模型思考。通用模型重试、工具循环停止仍优先
使用 DSH 受支持能力；需要把耗尽状态反馈为可验证的停止/等待，不只追加一条建议文本。
必须单独验证 MCP schema 层失败能否被安全计入和停止；未覆盖前不得宣称 F7 整体完成。
不得放宽工具 schema、隐藏错误、篡改 SDK 或构建第二 Agent harness 来消除这个缺口。

### 4. 用户操作与撤销

正常 Product 用户直接操作保留现有身份/审批路径，不伪造 AgentRun，不扣 Agent 纠错预算。
身份禁用、根回合终态、任务取消或会话不匹配阻止新准入。已认领操作与撤销之间定义明确的
事务顺序；迟到回执可以收尾，但不因此重新获得业务执行或模型续接权限。

## 必须先通过的资格和失败测试

- 两个工具的真实官方调用观察，含嵌套/多语种输入、数值、缺字段、过大或截断参数；摘要
  不能被 MCP 增补 trace 字段、键顺序或序列化差异改变。无法完整证明的输入不得准入。
- 同 generation 两根回合、同根多 child、伪造另一 active AgentRun、同 key 不同输入、
  跨 owner/workspace/task/action、迟到旧进程通知和重复投递均不能串账。
- 请求先到/凭证先到、进程退出、认领前后崩溃、领域写入成功但回执丢失、并发修正和重启。
- 相同失败输入不执行、一次合法修正成功、第二次失败后持久停止、换 key/child 不重置额度。
- MCP schema 提前拒绝、无精确 run/task 引用和 native stop seam 的独立覆盖证据。
- Browser/公开 trace 无内部凭证、摘要、参数或密钥；普通用户 UI 路径不误扣额度。

## 备选与回滚

不选择仅按 generation/session 计数、按模型自报 root 或最新 active run 归属、只补提示词、
每个幂等 key 新建预算、清空失败记录、直接读 DSH 私有日志或 fork runtime。
接受后仍先资格验证，再实现两工具的最小合同/台账/接入；逐项扩展其他领域动作需独立审计，
不能把两工具的通过推广为所有接口完成。关闭新准入路径时保留回执/预算/失败记录，并明确
能力受阻，不静默退回无约束执行。

本 ADR 不授权升级或回退 DSH、Provider 代理、新插件在线安装、生产部署、历史研究续跑、
数据扩容、release/tag、push 或 merge。Product Phase 97 与 U8 提前结束结论不变。
