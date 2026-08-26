# Quant Learning Loop Contract — Phase 14

## 所有权

BYQ 负责 bounded learning runs、ordered iteration history、evaluation signals、experiment comparison 和 lesson evidence promotion。DSH 可提出 generic agent iterations、subagent work 或 lesson candidates，但每个 budget、stopping rule、human gate、validation check 和 promotion decision 都是 BYQ domain contract。

## Learning runs

`byq_learning_run_start` request 声明 owner/task-scoped run，包含显式 `max_iterations`、`max_repairs` budget 及可选 deterministic stopping rules。Run 按 `active -> awaiting_review -> completed|failed|cancelled` 转换。

Iterations 仅追加、有序且幂等。Failed iteration 仅可在 repair budget 内重试。达到 iteration budget、repair budget 或匹配 stopping rule 时转为 `awaiting_review`；只有 trusted human reviewer 可批准或拒绝。Initiating actor 不能 review 自己的 run。

## Evaluation signals 与 comparison

Evaluation signal 指定一个有限 metric，并引用 validated BYQ Artifact；保留 task/experiment lineage 和 provenance。Experiment comparison 是确定性的，要求两个 experiments 均有 signals，且不虚构缺失值。

## Lesson promotion

Lesson proposal 必须引用至少一个 validated Artifact 或 EvaluationSignal 作为 evidence。普通 chat content 本身不是可信 quantitative knowledge。Lesson state 为 `proposed -> approved|rejected|superseded`；每个 promotion decision 作为带 reviewer、decision、rationale 和 timestamp 的有序 history record 保留。Initiating actor 不能 promotion 自己的 lesson。

## 稳定性

Backend storage 是实现细节。Agent-to-domain 调用使用 normalized BeyondQuant MCP tools；DSH 永不获得直接 business-storage access 或绕过这些 invariants 的权限。
