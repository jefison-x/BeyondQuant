# EngineeringTask Contract — Phase 15

## 所有权

BYQ 负责 EngineeringTask state machine、evidence gates 和 human merge record。Engineering DSH/Codex 在隔离 repository 中工作，并通过 Engineering Plane API 报告 evidence。Product Plane 和 Product MCP surface 不暴露 EngineeringTask tools/capabilities。

## State machine

```text
proposed -> approved -> in_progress -> review_required -> completed
                  |              |             |
                  v              v             v
              rejected/cancelled ...            rejected/cancelled
```

Terminal states 不可变。

## 必需证据

进入 `in_progress` 需要 approved task。进入 `review_required` 需要 isolated worktree path 和 non-main branch。进入 `completed` 还需要：

- 正数 draft PR number；
- `ci_status == success`；
- `self_review == true`；
- 非空 architecture evidence；
- `merge_status == not_merged`。

Backend 永不 push、merge 或 mark PR ready。独立 human merge record（`merged` 或 `rejected`）只能在 `completed` 后写入，且不能由 initiating actor 写入。

## 安全

Engineering endpoints 按 owner/actor scoped，并拒绝 credential fields。它们仅属于 Engineering Plane；Product quant role catalogue 和 Product MCP service 不得暴露。
