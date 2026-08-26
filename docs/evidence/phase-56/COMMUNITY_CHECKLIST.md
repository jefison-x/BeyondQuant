# Phase 56 Community feature checklist

> 本文记录该 Phase 的验收与审计证据。中文负责说明和结论；文件名、路径、命令、字段、状态码、测试计数及原始观察值保持英文原样。

| Community behavior inspected read-only | BYQ disposition | Evidence |
|---|---|---|
| Adjustment-factor-backed research prices | `PORT_LOGIC` / `REFACTOR` | Closed exact-date factor contract and content-addressed forward-adjusted research view. |
| Raw prices remain the execution tape | `PORT_TESTS` / `REFACTOR` | Immutable signal snapshots retain raw bars separately from sandbox research bars. |
| Dividend and bonus-share handling | `PORT_LOGIC` / `REPLACE` | Implemented-only actions use explicit entitlement, payment and listing dates in the native engine. |
| Avoid false ex-right trading signals | `PORT_TESTS` | Regression coverage separates the adjusted research view from raw-price execution. |
| Community provider SDK, ORM and mutable cache | `REPLACE` | BYQ closed provider contracts, PostgreSQL Data Plane and immutable artifacts are authoritative. |
| VectorBT, BaoStock and AKShare | `DROP` | No dependency, adapter, fallback or compatibility path exists. |

Every reusable Phase 56 invariant is implemented or explicitly replaced;
excluded Community architecture and technologies remain dropped.
