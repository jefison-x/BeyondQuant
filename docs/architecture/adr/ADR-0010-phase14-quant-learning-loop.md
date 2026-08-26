# ADR-0010：Phase 14 Quant Learning Loop

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 14 Quant Domain learning 与 evidence promotion

## 背景

Phase 9-13 建立了持久化 BYQ ResearchTask、Experiment、Artifact、Factor、
StrategyVersion、Approval、确定性 Backtest 和 quant Agent role state。仓库仍缺少将
evaluated evidence 转化为可信量化知识的受控路径。Community implementation 提供
evidence compaction、有界 Agent execution profile、可重试 error classification 和确定性
trajectory eval fixture，但没有 BYQ Learning Loop 或 Lesson promotion state machine。

Learning Loop 必须有界且可审计：普通 chat output 不能直接成为可信量化知识，Agent
iteration 也不能变得无界或由 prompt 驱动。

## 决策

1. BYQ 持有 `LearningRun` state machine。Run 按 owner/task 隔离，保存明确的
   `max_iterations`、`max_repairs` budget 和可选 deterministic stopping rule，并按
   `active -> awaiting_review -> completed|failed|cancelled` transition。
2. 每次 run iteration 是 append-only、ordered、idempotent BYQ event。Failed iteration
   可在 repair budget 内重试。当 iteration budget、repair budget 用尽或命中 stopping
   rule 时，run 进入 `awaiting_review`；只有 trusted human reviewer 可以 approve/reject。
   terminal run 不可变，并可通过 ordered iteration history replay。
3. BYQ 持有 `EvaluationSignal` record。每个 signal 引用一个 validated Artifact、命名
   一个有限 metric，并保留 task/experiment lineage 和 provenance。
   `compare_experiments` 对两个 experiment 返回确定性 metric comparison，绝不编造
   missing value。
4. BYQ 持有 `Lesson` evidence promotion。Proposed Lesson 必须引用至少一个 validated
   Artifact 或 EvaluationSignal；plain chat content 不能单独 promotion。Lesson state 为
   `proposed -> approved|rejected|superseded`，每次 promotion decision 都以 ordered
   history record 保留 reviewer、decision、rationale 和 timestamp。
5. Backend 持有全部 Learning Loop persistence 和 invariant。Agent-to-Domain call 使用
   normalized BeyondQuant MCP tool。DSH generic orchestration 可以提出 iteration 或
   Lesson，但不能绕过 budget、stopping rule、human review、provenance 或 BYQ storage
   boundary。

## 后果

- Agent iteration 有界，并具备明确 Human gate 和 stopping rule。
- Promoted Lesson 保留 evidence、validation、review、provenance 和 promotion history。
- CI 无需 model credential 即可测试 budget、idempotency、deterministic comparison、
  promotion gate 和 secret rejection。
- 不引入新的通用 Agent Harness、DSH runtime fork 或 direct business-storage access。
