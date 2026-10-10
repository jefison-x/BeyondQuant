# ADR-0109 accepted loss revision — 2026-10-09

HEAD: `2d5810973240c5d7692569319c2b5ab337ae2082`; worktree/branch unchanged.
Maintainer accepted the exact loss revision with "接受". Prior strict-contract FAIL,
old real failed root and all unknown rows remain preserved.
Before-files backup: `/tmp/byq-adr0109-revision-20261009/before.tar.gz`.
Revision changes only ADR/contract/acceptance record and two Backend tests; runtime
implementation from the preceding slice is unchanged.

## Verified gates

- Backend exact root+child durable denied settlements -> private terminal ACK -> final
  ingress cursor/hash readback: PASS (2 selected tests, includes unknown fence).
- Authorization response unknown stays immutable and blocks close/new root: PASS.
- Adapter exact ACK and cleanup proof both required, either order, wrong ACK/slot-busy
  blocked: PASS (2 selected tests; synthetic harness).
- Fixed official version/composition identity architecture test: PASS (5 tests).
- Previous actual Backend HTTP + MCP bridge fault probe: reused; no repeat/model call.
- Syntax and diff-check: PASS.
- Independent Reviewer: Functional/Tests/Architecture PASS for the bounded revised contract.
- Root: local revised control-contract PASS; not complete Product qualification.

## Limits

A lost settlement response is modeled in the new Backend tests by discarding the committed
Store return. Prior actual HTTP/bridge fault injection proves MCP reports unknown while the
Backend denial settlement remains durable. The exact terminal cursor is atomically persisted
with the Backend root and checked on authenticated readback; lifecycle ACK JSON itself carries
root/event identity, not cursor fields. Synthetic interrupted outcome is not user cancellation.
Adapter cleanup is a fake-harness contract, not proof of real process cleanup.

Old real root `0a00179537f54edab8cd92a9fc37af03` remains fenced. This accepted revision gives
it no historical denial receipt and no reconciliation permission. New real Gateway/DSH/Product
qualification and actual cleanup for the revised branch remain NOT_RUN. No default promotion,
push, PR, merge, production deploy or Product Phase advance.

## Subsequent actual normal-completion integration

See [REAL-PRODUCT.md](REAL-PRODUCT.md): new isolated exact-matched candidate
8-service readiness PASS; one real Gateway/DSH ACP/MCP/Backend child read PASS
through Tester → independent Reviewer → Root. It obtained exact terminal ACK
snapshot and verified signed actual cleanup (UID10002 remaining 0). Nine provider
calls, all HTTP200 and within ADR-0106. Old failed roots unchanged.
This supersedes the earlier NOT_RUN statement only for this single normal completed
read-only delegation and actual cleanup; lost ACK, user cancel and process-fault
Product recovery remain NOT_RUN in this slice. Whole ACP/default/release remains open.
