# ADR-0031：Agent 领域动作完成与策略校验合同

- Status: Accepted
- Date: 2026-08-26
- Accepted: 2026-08-26
- Decision scope: Phase 58 Agent → Stock Pool / Strategy Domain completion
- Related: ADR-0007、ADR-0009、ADR-0012、ADR-0018、ADR-0020、ADR-0024、ADR-0025

## 背景

Phase 57 后的真实用户验收证明，BYQ 的股票池、策略 Artifact 和回测领域能力分别可用，
但生产 Agent 无法自然连接这些能力：

1. 用户从银行板块研究得到五只候选后明确要求“建立一个股票池”，
   `market_researcher` 与 `quant_orchestrator` 对 `byq_pool_create` 的授权均返回 403。
2. 用户继续要求设计简单策略时，Agent 对 `byq_strategy_validate` 连续尝试十余种猜测，
   全部返回 422。Backend 已有通过真实测试的 `CustomStrategy` 合同；失败主要来自 DSH
   skill 没有给出可执行合同、MCP 丢弃 Backend 的安全校验详情，以及 MCP 测试用无效
   策略配合假 201 响应制造了错误信心。
3. Product 现有 Workflow Card 可以表达股票候选，但它是 presentation proposal，不能
   代替用户明确要求的 owner-scoped Domain write，也不能让 model-produced card 获得
   authority。

Read-only Community 审计证明以下语义有价值：研究候选与业务写入分离；Agent 权限必须
最小化；工具、Artifact 与 Backend 使用同一版本化策略合同；校验失败只修失败部分且
同类错误最多重试一次；业务资源必须由权威 Backend 验证，不能以模型声明或 evidence
Artifact 冒充成功。Community 的 PydanticAI/Hermes runtime、Agent Service SQL、旧审批
executor、direct Backend API 和 frontend Agent schema coupling 均不兼容当前架构。

维护者在验收缺陷和后续开发计划评审后明确授权启动 Phase 58。本 ADR 固定 Phase 58 的
最小 capability、安全和验收边界；不授权 Phase 59 的估值/行情 read-path 工作，也不
提前实现 Phase 60 的公开回答投影重构。

## 决策

### 1. 升级而不扩大专业研究角色

BYQ role catalogue 升级到新的明确版本。`market_researcher` 继续只收集市场证据、发布
候选和创建有界 research Artifact，**不得**创建或修改股票池。

`quant_orchestrator` 增加一个闭合的 Stock Pool capability slice：

- `byq_pool_list`
- `byq_pool_get`
- `byq_pool_create`

只允许创建 `custom` pool。`byq_pool_snapshot_replace`、`byq_pool_lifecycle`、删除、
trusted index/dynamic writer 和 provider operation 均不加入 orchestrator role。

创建 custom pool 是 owner-scoped、可审计且不覆盖已有 immutable snapshot 的低风险
Domain Artifact 创建，等价 Product UI 的明确创建动作；当用户在当前 conversation 中
明确要求建立股票池时，不增加第二次人工审批。该决定不授权 Agent 根据后台规则、定时
任务或模糊建议自动建池。未来若支持自主批量创建、修改、停用或删除，必须重新评审
Approval policy。

所有调用仍使用 service-derived owner/workspace/actor context。Backend 继续计算
`pool_id`、snapshot identity、fingerprint 和 custom provenance，并校验 canonical symbol、
weight 与 owner scope。Model、Browser 或 MCP caller 不能提交 authoritative identity、
trusted provenance 或 workspace identity。

### 2. 候选结果与真实股票池必须可区分

`agent.card.stock_candidates` 和 research evidence 仍只是 proposal，不代表股票池已经
创建。只有 `byq_pool_create` 返回真实 owner-scoped `pool`，并在 Agent audit 中记录成功
resource identity 后，Agent 才能声称创建成功或在后续对话中使用该 pool。

Agent 不得在 403 后换角色、换工具或让用户复制内部参数绕过 policy。市场研究结果交回
orchestrator 后，由 orchestrator 在用户明确请求下执行一次有界创建。相同 conversation
中的后续“这个股票池”必须引用真实返回的 pool，而不是原候选列表或 evidence Artifact。

### 3. 唯一策略输入合同

`byq_strategy_validate` 的 MCP schema、DSH skill、规范文档和 Backend 接受字段必须一致。
Phase 58 的策略快照为：

```text
strategy_id, name, category, optional description,
optional parameters, optional parameter_schema,
optional data_requirements, source_type=python_script, script
```

脚本必须定义 `CustomStrategy`，且准确实现一个同步方法：

```python
class CustomStrategy:
    def generate_signals(self, data, parameters):
        return {}
```

或：

```python
class CustomStrategy:
    def generate_target_weights(self, data, portfolio_state, parameters):
        return {}
```

策略校验不要求 ResearchTask/Experiment 先进入 `running`。Agent 不得为了猜测 422 原因
改变无关 task/experiment 状态。`data_requirements` 与 ADR-0030 已接受的 Backend 字段保持
一致；Phase 58 只修复 schema drift，不新增数据能力。

`strategy_researcher` 为完成这条闭合链路增加且只增加
`byq_research_task_create` 前置能力；role version 升至 `1.2.0`，DSH child toolFilter 与
Backend catalogue 同步。该能力只创建当前 owner/workspace 的 planned ResearchTask，
不包含 `byq_research_transition`、Stock Pool 写入、approval、backtest 或 execution。
当 task 不存在时，固定执行并分别审计 task create → strategy validate → version create；
不得用后一动作的 authorization 覆盖前一 prerequisite。

校验成功后，Agent 使用返回的真实 validated draft Artifact 创建 StrategyVersion。
普通 evidence Artifact、模型生成代码块或“设计完成”文本不能冒充 validated draft 或
version。Approval 与 execution 继续保持分离。

### 4. 安全、结构化、可修复的错误

Backend 继续持有策略 invariant。MCP 不再把全部 422 压缩为只有 HTTP 状态的
`strategy_request_invalid`；它可以投影由 BYQ Backend 产生的有界 validation message，
但必须：

- 只接受 JSON object 中的字符串 `detail`；
- 限制长度并拒绝 control characters；
- 不返回 stack trace、storage path、request body、script、credential、header 或 raw
  Backend envelope；
- 同时保留稳定 `status` code，供 Agent 决定是否可修复。

MCP 未识别的响应继续 fail closed 为通用安全错误。Browser 仍只看到 normalized
WorkflowTrace；本 ADR 不授权 raw MCP result 或错误详情进入公开回答。

### 5. 有界修复与停止规则

对于一次策略校验：

1. Agent 首次必须使用规范最小合同，而不是探测字段。
2. 收到明确可修复的结构化 validation message 后，只允许针对失败规则修正一次。
3. 第二次仍失败、错误不可修复、403/401、owner/workspace mismatch 或 service unavailable
   时立即停止，保留已成功读取的证据，不换角色绕过，不重复创建 task/experiment。
4. 同一 Domain write 使用稳定 idempotency context；调用成功后不得因继续对话重复创建。

通用模型重试由 DSH 持有；BYQ skill/contract 定义 Domain action 的预算和停止条件，不
创建第二个 Agent loop 或 workflow engine。

### 6. 测试与证据

Phase 58 必须包含：

- role policy：orchestrator pool list/get/create allowed；market researcher create denied；
  snapshot/lifecycle 仍 denied；catalog version 明确升级；
- owner/workspace isolation 与 Agent audit evidence；
- MCP strategy translation 使用 Backend 真正有效的最小策略，不再用无效 fixture 假装
  成功；
- 422 安全详情、无详情/异常响应降级、长度和 secret/path rejection；
- MCP schema 与 Backend 的 `data_requirements` 一致；
- planned ResearchTask 直接 validate 201 → StrategyVersion 201；
- 真实 Product Agent：候选 → 创建真实 pool → 基于真实 pool 生成 validated strategy
  version；不得出现 pool 403 或同类 422 重试风暴；
- Chrome DevTools/Playwright evidence，确认 Browser 仍只访问 same-origin Gateway/Product
  surface，且没有 raw Backend/MCP/DSH schema 或 secret 泄漏。

## 非目标

- 不接入 daily_basic、估值、fundamental 或新的市场数据工具；它们属于 Phase 59。
- 不重构 public answer/activity/hidden reasoning projection；它们属于 Phase 60，但 Phase 58
  不得扩大现有泄漏。
- 不增加 pool snapshot replace、lifecycle/delete、index/dynamic writer 或 Paper Trading
  mutation capability。
- 不改变 StrategyVersion identity、Approval semantics、signal sandbox 或 Backtest engine。
- 不复制 Community executor、Agent Service persistence、PydanticAI、Hermes、VectorBT、
  BaoStock 或 AKShare。

## 停止条件

- 实现需要让 Product DSH 直接访问 PostgreSQL、Backend internal 或 application source；
- 需要信任 model/browser 提交 owner/workspace/trusted provenance；
- 无法在不暴露 secret/path/raw Backend body 的情况下提供可修复错误；
- pool mutation 需要扩展到 snapshot/lifecycle/delete 或自动后台执行；
- 真实有效最小策略仍无法通过现有 Backend contract，说明 domain invariant 并非仅为
  translation/skill drift；
- 需要新增第二个 Agent harness、fork DSH 或绕过 MCP。

## 后果

- 普通用户可从研究候选自然创建真实 custom pool，并在后续策略请求中引用真实资源。
- 专业 market researcher 仍保持 least privilege；写能力只增加到 orchestrator 的最小
  read/create slice。
- 策略 Agent 获得可执行的唯一合同和有限修复信息，不再通过十余次猜测定位 422。
- Backend 仍是全部 pool/strategy invariant 和 identity 的权威；DSH 只负责编排。
- Phase 59/60 可分别处理数据能力与公开交互，不被 Phase 58 偷跑。

## 回滚

回滚 role catalogue 版本并移除 orchestrator 的三个 pool capability；保留已经创建的
owner-scoped pool 与 immutable snapshot，不删除或改写业务数据。回滚 MCP 策略错误投影
时恢复 generic safe status；已创建的 validated draft/version identity 不受影响。

## Acceptance record

维护者在审阅真实用户验收缺陷和分阶段开发计划后，于 2026-08-26 明确要求启动
Phase 58。Acceptance 仅授权本 ADR 的 Agent Stock Pool read/create、策略合同对齐、有界
错误和回归证据，不授权 Phase 59、Phase 60、release、tag 或 production publication。
