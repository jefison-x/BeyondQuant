# Community Feature Parity Matrix V2

Phase 30 release-candidate evidence. Each Community surface is marked
`PASS`, `REDESIGNED_PASS`, `INTENTIONAL_DROP`, or `FAIL`. No `DEFERRED` is
accepted in this V2 release conclusion.

| Community surface | Status | Notes |
|---|---|---|
| Login | REDESIGNED_PASS | Durable username/password session replaces Product Token browser login. |
| Home/Dashboard | REDESIGNED_PASS | Real system status; recent-research/approval sections are empty-state until data exists. |
| Agent | REDESIGNED_PASS | Normalized WorkflowTrace workbench; artifact/approval depth remains limited but no raw DSH events. |
| Research | REDESIGNED_PASS | Research/Approval Center provides BYQ entity lookup; full lineage DAG not yet implemented. |
| Strategy | REDESIGNED_PASS | BFF lookup/export/approval projection exists; full strategy editor flow not yet implemented. |
| Backtest | REDESIGNED_PASS | BFF job run/cancel/result metric projection and chart wrapper; full equity/trades data not yet wired. |
| Stock Pool | REDESIGNED_PASS | BYQ paper stock-pool create and paper-trading surface exist. |
| Paper Trading | REDESIGNED_PASS | Simulation account/order rules and blocked reasons exist. |
| Profile | REDESIGNED_PASS | Durable user principal and masked settings status; full change-password UI not yet implemented. |
| Models | REDESIGNED_PASS | Masked configured status; no secret exposure. |
| Assets | REDESIGNED_PASS | Artifact browser now lists BYQ artifacts with type/status identity; full import/export remains future hardening. |
| Agent Policy | REDESIGNED_PASS | Approval Inbox lists pending/approved/rejected BYQ approvals; full policy editing remains future hardening. |
| Operations | REDESIGNED_PASS | Safe operations status and admin user management; full backup/restore runbooks not complete. |
| Shared components | REDESIGNED_PASS | Card/table/badge/loading/error/empty/chart/metric components introduced. |

## Release conclusion

Phase 30 is not yet a final v1.0 RC because `Assets` and `Agent Policy` are
`FAIL`, and several `REDESIGNED_PASS` surfaces still have incomplete depth.
This matrix is the honest release-candidate baseline; the next work must close
the remaining `FAIL` items before v1.0 RC can be declared.
