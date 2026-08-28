# ADR-0039：Market Research Web Search Evidence Boundary

- Status: Accepted
- Date: 2026-08-28
- Accepted: 2026-08-28
- Decision scope: Phase 64 Market Research Agent Web Search 深化
- Related: ADR-0003、ADR-0004、ADR-0006、ADR-0009、ADR-0018、ADR-0019、ADR-0025、ADR-0032、ADR-0033、ADR-0037、ADR-0038

## 背景

Phase 63 在 Python `0.1.1rc1` / npm `0.1.1-rc.1` baseline qualification 并启用了
search-only DSH Web Search。Package 存在、Agent 能搜索和网页内容可成为 BYQ research
evidence 仍是三个不同事实。互联网来源具有冲突、过期、发布时间缺失和未来信息污染风险；
DSH tool output、conversation context 与 durable BYQ Artifact 也不能混为一体。

维护者授权 Phase 64 将 Web Search 深化为 Market Research Agent 的受控能力，但不授权
`web_fetch`、爬虫、第二 Research Database 或网页数据进入确定性量化输入。

## 决策

### 1. 搜索属于 DSH，证据晋升属于 BYQ

`web_search` 是 DSH generic capability。结果首先是 session-scoped evidence candidate；只有
用户明确要求保存研究时，Market Research Agent 才能逐动作 authorization，经
`byq_web_evidence_create` 将结果晋升为现有 ResearchTask/Experiment 下的
`web_research_evidence` Artifact。Backend 计算 content hash、保存 lineage/trace 并执行严格
contract validation。Plugin 不访问 MCP 之外的 Backend、PostgreSQL、Provider 或 Artifact Store。

不建立新表或第二 Research Database。现有 Artifact lifecycle、owner/workspace、idempotency、
authorization 和 audit 保持权威。

### 2. Versioned evidence contract

Artifact content 使用 `web-research-evidence.v1`，要求：

- research as-of timestamp；
- verified/unknown trading session 与 persisted-data cutoff，二者不得由 Web 或 wall clock 推断；
- 至多四条有 purpose 的中文、英文或 mixed query，完全重复 query 被拒绝；
- 至多 32 条去重 source，保留 URL、title、publisher、source tier、published/retrieved time、
  temporal status、query indexes 和 bounded summary；
- typed claim：`FACT`、`CAUSAL` 或 `CANDIDATE`，状态为 `SUPPORTED`、`CONFLICTED` 或
  `UNESTABLISHED`；
- limitations 与固定 usage policy：`research_only=true`、`deterministic_input=false`、
  `authoritative_market_data=false`。

URL 只作为 inert provenance 保存，不被 Backend fetch；credential-bearing/local URL、duplicate
URL、secret-like fields 和未知 schema fields fail closed。

### 3. 来源和防幻觉规则

来源等级为 `PRIMARY`（监管、政府、交易所、公司法定/官方材料）、`SECONDARY`（可识别专业
财经媒体）、`AUXILIARY`（论坛/自媒体）和显式 `UNKNOWN`。SUPPORTED claim 至少需要一条
在 as-of 内发布的 PRIMARY/SECONDARY；SUPPORTED CAUSAL claim 必须有 PRIMARY。AUXILIARY
只能用于候选发现，未知发布时间、未来发布时间或来源冲突不能被静默变成确定结论。

无结果、证据弱、时点无效或不能建立因果时，Agent 必须回答“现有证据无法建立原因”并说明
缺口。模型记忆不能补充本轮未检索的事件、数字、引用或因果链。过期新闻只能作为明确标注的
历史背景，不能证明当前原因。

### 4. 时间和 Data Plane 边界

`published_at`、`retrieved_at`、research `as_of`、BYQ trading session 和 persisted-data cutoff
是不同字段。Backend 根据 publication/as-of 计算关系并拒绝伪造的 temporal status；未知日历
不能携带 asserted trading session。Web evidence 与 persisted cutoff 不一致时只能记录差异。

未经 BYQ Data Plane 采集、规范化、PIT 校验、provenance 和冻结的网页数据，不得进入 Factor、
Strategy calculation、signal snapshot、Backtest manifest 或其他 deterministic input。Artifact
被 validated 也只表示 evidence contract 通过，不把网页变成 authoritative market data。

### 5. Agent 与公开投影

`market_researcher` 持有 `web_search` 和 `byq_web_evidence_create`。Factor、Strategy、Backtest
Agent 的 DSH toolFilter 与 BYQ role catalogue 都没有这两个能力。Coordinator 在 rc.1 的 root
registry 中仍可见 `web_search`，但 Product role contract 要求委派专业搜索，不得把 Web result
传成 deterministic input；若无法可靠保持该规则，进入 DSH Upgrade Lane，不能创建第二 harness。

公开回答可展示用户需要的来源 URL/title/date；WorkflowTrace 仍只投影 normalized answer/activity，
不持久化 raw DSH tool arguments/results、provider credential、hidden reasoning 或内部 schema。

Backend validation 失败时，MCP 只返回固定枚举的 `validation_issue`（例如
`TEMPORAL_STATUS`、`SOURCE_URL`），不回显原始 payload 或 Backend detail。Agent 最多按该码修正
一次；再次失败即停止并审计 failure，不能盲目重复提交。

### 6. 搜索预算与停止

每个 run 最多四条 query；official plugin 继续限制每 query 的 bounded results、timeout 和 uses。
相同 query/language、相同 URL 去重。`EVIDENCE_SUFFICIENT`、`NO_RESULTS`、`BUDGET_EXHAUSTED`、
`CONFLICT_UNRESOLVED` 或 `PROVIDER_ERROR` 是显式停止原因。Guard reminder 是 advisory，不替代
角色预算和 Backend evidence contract。

## 非目标

不启用 `web_fetch`、任意 URL 下载、browser automation、爬虫/新闻仓库、第二数据库、全文
索引、runtime install、DSH upgrade/fork/patch、shell/filesystem/code runtime、direct Provider/DB、
网页量化输入、Phase 65 Plugin Center 或新的 frontend surface。

## 验收与回滚

Contract tests 覆盖 valid promotion、no result、conflict、duplicate query/URL、future/unknown time、
AUXILIARY-only、causal source、stale context、calendar mismatch、local/credential URL 和固定 usage
policy。Agent/MCP/composition tests 证明 Market Research 可保存，而 Factor/Strategy/Backtest
不可见。Keyless DSH initialize/session/MCP、secret/raw schema negative tests 和 existing Product
Agent regressions 必须通过；credentialed smoke 从 deployment secret 读取并且不进入 deterministic
golden fixture。

回滚删除本 Phase 新 tool registration/role assignment/validator 并恢复前一 generated composition。
已保存 Artifact 保持 immutable domain data，可继续通过 generic Artifact read；不得删除数据库
或 session。Web provider failure只停止搜索并保留 BYQ structured-data path。

## STOP CONDITIONS

需要 `web_fetch`、runtime upgrade/fork/patch、MCP bypass、direct DB/provider、source write、危险
capability、模型记忆补证、Agent 串权、网页 deterministic input、无法证明 provenance/time、secret
或 raw DSH schema 泄漏时停止。缺 credential 只阻止 credentialed smoke，不得伪造实网结果；
keyless contract、Product boundary 和实现仍可独立验证。

## 2026-08-29 maintenance clarification：保存命令与公共状态

真实 Product journey 发现，让模型生成内部 `source_id` 会把一次成功搜索退化为难以理解的
“入库校验失败”，并且分开的 task/evidence mutation 会留下孤立 ResearchTask。现接受以下不改变
Artifact v1 持久格式和安全边界的收紧：

1. Agent-facing command 只用零基 `source_indexes` 关联 claim 与本次来源数组；Backend 对已校验
   public URL 计算稳定 `source_id`。Browser、模型和 DSH plugin 均不拥有该 identifier contract。
2. 显式保存使用一个 BYQ MCP command；Backend 在同一 PostgreSQL transaction 内创建最小
   ResearchTask 与 `web_research_evidence` Artifact。validation、idempotency conflict 或写入失败
   整体回滚。
3. normalized validation issue 仍最多定向修复一次。公共回答只投影保存成功与来源数，或说明
   “结果可阅读但研究记录暂未保存，且未用于量化计算”；不得暴露 schema/source ID/tool/enum，
   也不得在无关后续 turn 主动重播历史保存故障。

旧 `/v1/research/web-evidence` 的 existing-task Backend route 暂保留为兼容内部 Contract；Product
Agent 使用新的 atomic record route。二者都只能经 trusted MCP/Backend boundary，均不能使 Web
evidence 成为确定性量化输入。
