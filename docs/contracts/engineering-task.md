# EngineeringTask Contract — Phase 15

## Ownership

BYQ owns the EngineeringTask state machine, evidence gates, and human merge
record. Engineering DSH/Codex performs isolated repository work and reports
evidence through the Engineering Plane API. The Product Plane and Product MCP
surface do not expose EngineeringTask tools or capabilities.

## State machine

```text
proposed -> approved -> in_progress -> review_required -> completed
                  |              |             |
                  v              v             v
              rejected/cancelled ...            rejected/cancelled
```

Terminal states are immutable.

## Required evidence

Starting `in_progress` requires an approved task. Entering
`review_required` requires an isolated worktree path and a non-main branch.
Entering `completed` additionally requires:

- a positive draft PR number;
- `ci_status == success`;
- `self_review == true`;
- non-empty architecture evidence;
- `merge_status == not_merged`.

The Backend never pushes, merges, or marks a PR ready. A separate human merge
record (`merged` or `rejected`) may only be written after `completed` and
cannot be written by the initiating actor.

## Security

Engineering endpoints are owner/actor scoped and reject credential fields.
They are Engineering Plane only; the Product quant role catalogue and Product
MCP service must not expose them.
