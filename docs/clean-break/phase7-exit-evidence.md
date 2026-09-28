# Phase 7 bounded exit evidence — 2026-09-28

Scope: legacy Agent recovery/compatibility removal on the isolated Clean Break
branch. Full 0.10 architecture, fresh schema, full functionality and Golden
scenarios remain later gates. [Live-state classification](phase7-exit-classification.md)
records the unresolved Phase 10/14/17 work without calling it complete.

The final source slice deletes the old `ResearchTask.continuation_budget`
`recovery_attempts` scan from Backend domain-call admission and the unwired
Gateway `LifecycleDelivery.recover` callback. Two tests whose only input was
discarded old recovery rows were retired. Current admission still checks
evidence, owner/workspace, registered role, current boot/root authority and
unknown claim outcome. Gateway still sends and acknowledges exact business
evidence and terminal receipts. The `.239` selected build pins the changed
source; `.238` remains frozen.

| Check | Result |
|---|---|
| Gateway lifecycle, answer and domain-proof delivery in fresh image | 25/25 PASS |
| Backend on disposable tmpfs PostgreSQL: boot rotation/claim race, normal proof claim, two crash-to-unknown cases, unknown after reconnect | 5/5 PASS |
| Retained continuation-route rejection tests | 3/3 PASS |
| Architecture checks | 198/198 PASS |
| `.239` identity; build/retirement selectors; AST; diff | PASS |
| Test resources | Dedicated PostgreSQL container, private network and two tagged images removed; final exact filters empty |

Independent Sol Reviewer inspected the actual source/build/docs diff and
returned **Functional PASS / Tests PASS / Clean Break Architecture PASS** for
this bounded Phase 7 removal. It verified that boot revocation, exact root
close/ACK, current evidence admission and `outcome_unknown` no-replay remain.
This verdict does not certify the remaining Adapter session/run/generation and
context ownership, Backend mixed lifecycle tables, or all of 0.10.

No existing BYQ database, volume, backup, user data or service was changed;
there was no push, merge or deployment.
