# ADR-0011：Phase 15 Engineering Plane Task Boundary

- Status: Accepted
- Date: 2026-08-16
- Decision scope: Phase 15 Engineering Plane task 与 evidence Contract

## 背景

Product Plane 绝不能获得 source-editing、Git 或 merge authority。Phase 15 需要受控
EngineeringTask record，使 Engineering DSH/Codex subagent 可以在隔离 worktree 中工作，
并产出经过测试的 Draft PR，同时不削弱该边界。Community repository 没有等价
EngineeringTask 实现，因此这是新的 BYQ-owned Contract，不是迁移。

## 决策

1. BYQ 在 Backend 持有 `EngineeringTask` state machine：
   `proposed -> approved -> in_progress -> review_required ->
   completed|rejected|cancelled`。Terminal state 不可变。
2. Task 记录 owner、initiating actor、trace、description、scope、worktree path、branch
   name、Draft PR number、CI status、self-review boolean、有界 architecture evidence 和
   Human merge status。
3. `in_progress` 要求 approved task；`review_required` 要求 isolated worktree path 和
   non-main branch；`completed` 要求 Draft PR number、`ci_status == success`、
   `self_review == true`、非空 architecture evidence 和
   `merge_status == not_merged`。
4. Backend 从不 push、merge 或将 PR 标记为 ready。独立的 `record_human_merge`
   operation 只在 task completed 后记录明确 Human decision（`merged` 或 `rejected`），
   不执行 Git/GitHub mutation。
5. EngineeringTask endpoint 只属于 Engineering Plane，不通过 Product BeyondQuant MCP
   surface 暴露，也不存在于任何 Product quant role allowlist。

## 后果

- Engineering work 具有可审计、有界、由 evidence gate 约束的 Contract。
- Product DSH 仍不能访问 EngineeringTask endpoint 或修改 source。
- CI 无需 GitHub 或 Git credential 即可测试 state transition、evidence gate、Human
  merge record 以及 Product/MCP separation。
