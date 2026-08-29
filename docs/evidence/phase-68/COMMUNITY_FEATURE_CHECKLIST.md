# Phase 68 Community frontend checklist

The corresponding BeyondQuant-Community stock-pool page was inspected read-only
before implementation. It exposes a dynamic count/filter but no dynamic rule
editor, evaluator, scheduler, point-in-time preview, materialization history, or
recovery semantics.

| Community evidence | Classification | BYQ Phase 68 decision |
|---|---|---|
| Dynamic pool count and type filter | `PORT_UX` | Keep a visible Dynamic catalog filter and type label. |
| Empty dynamic pool execution placeholder | `DROP` | Do not preserve placeholder completion or legacy service architecture. |
| Existing stock-pool dialog/list/detail visual language | `PORT_LAYOUT` / `PORT_STYLE` | Extend the current BYQ responsive management workspace. |
| Community provider/service/ORM paths | `REFERENCE_ONLY` / `REPLACE` | Use Gateway Product API, BYQ domain persistence, and trusted Data Worker only. |
| Arbitrary expressions or executable rule content | `DROP` | Use `dynamic-stock-pool-rule.v1` allowlists; reject unknown fields/operators. |

No Community source, API, database, provider adapter, or runtime code was copied
or modified.
