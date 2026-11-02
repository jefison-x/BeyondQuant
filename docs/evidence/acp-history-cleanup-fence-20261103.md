# Historical ACP recovery cursor blocking new conversations — 2026-11-03

## Scope and authority

The maintainer authorized the minimal repair and necessary verification while
preserving historical receipts, data, retained environments and the current
browser page. This is maintenance under ADR-0093/ADR-0100; Phase 18 remains
NOT_STARTED. Push/PR, merge, release and deployment are outside this task.

Clean base: `b45e21c28588a041f045d7c0c1ed082f62f1c461`.
Branch: `codex/acp-history-cleanup-fence-20261103`, reusing the clean isolated
`oc-service-default` worktree. The retained Backend operations binding and
Frontend assets in that worktree were not changed.

## Confirmed failure and repair

The operating browser showed the conflict while creating a new conversation.
Gateway and Runtime logs recorded six failed session-creation requests between
2026-11-02 22:43:19 and 22:48:16 UTC, before a prompt or model call. Runtime had
zero active sessions and zero held slots. Its workspace admission scan read ten
historical ACP bindings; four acknowledged recovery boundaries retained the
pre-reattachment cursor, failing the strict recovery sequence contract.

The workspace cleanup scan now reads the same bindings without validating the
unrelated conversation's recovery boundary. It retains schema, identity,
resource-group/cwd, qualified scope/receipt and existing V2 cleanup checks.
Every recovery read remains strict by default. No receipt is repaired, removed,
replayed or reclassified as resumable. Backend business admission, exact terminal
ACK, domain-call drain, slot ownership and unknown-outcome protection are unchanged.

## Verification

| Check | Result and boundary |
| --- | --- |
| Regression before repair | FAIL as expected: four selected cases reproduced the stale recovery-boundary rejection |
| Product-slot and completed-root reuse files | PASS: 76 tests, offline synthetic execution, no model calls |
| Additional binding safety checks | PASS: 4 selected cases (3 new and 1 updated/repeated); cross-group placement, invalid schema, reversed domain drain and outside cwd still fail closed |
| Original operating receipt volume | PASS: read-only mount, network disabled; all 10 bindings pass the repaired workspace cleanup scan; the 4 original strict recovery failures remain failures |
| Receipt preservation | PASS: SHA-256 of all 10 historical files unchanged, including comparison with the pre-test operating snapshot |
| Local syntax/diff/worktree checks | PASS |
| Independent Sol review | Functional and Architecture PASS; test coverage reviewed without duplicating execution; Root confirmed all selected executions PASS |
| Hosted PR CI / image / deployed browser verification | NOT_RUN; not authorized by this maintenance request |

The two focused test files plus the additional cases cover 79 distinct tests.
Existing tests include Backend unsettled-root denial, failed/unavailable admission,
unknown provider outcomes, exact terminal ACK and cleanup sequencing. The new
regressions also prove that a fresh saved session launches no DSH process or slot,
strict recovery still rejects the old cursor, and V2 unconfirmed cleanup still
blocks both session creation and prompt submission without changing its receipt.

Tests reuse the installed operating ACP image
`sha256:a4ab8bfdd92091ac7fac9e26c5c2ac60791a5e8eb4bc0805c83d5c15701f31bb`
as the interpreter/dependency environment, with changed source mounted read-only.
No image was built or promoted. Initial disposable-container mount/import setup
errors were resolved by using the repository's actual directory layout; they are
not Product evidence. The retained environments were not restarted or patched.

Private raw evidence is retained under
`~/.local/state/byq-maintenance/acp-history-fence-20261103/`:
`regression-red.log`, `runtime-focused.log`, `binding-safety.log`,
`historical-receipts-readonly.json`, and the before/after binding hash snapshots.
The operating Runtime, Product Runner and Gateway retain their original container
IDs and start times. The existing production-test page has not been operated on.

## Remaining gate

This is a locally verified code repair. The running operating image still contains
the original code, so production-test recovery is not claimed. The next delivery
gate is authorized push/Draft PR and affected CI, followed by the separate merge,
trusted-image release and deployment gates.
