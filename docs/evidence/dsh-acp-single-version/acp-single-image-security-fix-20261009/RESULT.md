# ACP single-image candidate — adapter root-regression security fix (2026-10-09)

Subsystem: BYQ ACP single-image candidate (`services/acp_unified/`). Sole writer.
No PR / push / merge / deploy. No ADR, no 17-image batch, no F6. No image rebuild
(prior RAM/disk exhaustion); a controlled rebuild is required before any runtime
claim for the fix.

## Finding (Reviewer, blocking)

- The accepted per-role adapter Dockerfile defaults to `USER byq` (uid/gid 10002).
- The new `services/acp_unified/Dockerfile` **omitted** that default, so the built
  candidate image defaulted to **root** (`docker image inspect` `User = none`).
- Only the candidate Compose pinned `user: "10002:10002"` for the adapter; a
  service that omitted `user:` would have launched `BYQ_ACP_ROLE=adapter` as root.
- The adapter entrypoint had no identity guard.

## Fix (minimal source)

- `services/acp_unified/Dockerfile`: final stage now ends with `USER byq`
  (matches the accepted adapter image default).
- `services/acp_unified/entrypoint.sh`: adapter branch fail-closes (exit 77) unless
  **effective** uid and gid are both 10002; uvicorn is never started otherwise.
  (`id -u`/`id -g` report effective ids in GNU coreutils and busybox.)
- `compose.dsh-acp-single-image-candidate.yml`: unchanged — product/judgment stay
  explicitly `user: "0:0"`; adapter stays `user: "10002:10002"`.
- `services/acp_product_runner/server.py`, `services/acp_judgment_runner/server.py`:
  unchanged — original root PID-1 guards preserved.

## Targeted test (no Docker, no real secret)

`services/acp_unified/tests/test_entrypoint.sh` drives the real entrypoint with a
stubbed effective-id `id`:

```
== role dispatcher ==
[PASS] unset BYQ_ACP_ROLE refused (exit=64)
[PASS] unknown BYQ_ACP_ROLE refused (exit=64)

== adapter identity guard ==
[PASS] adapter as root refused (exit=77)
[PASS] adapter wrong gid refused (exit=77)
[PASS] adapter wrong uid refused (exit=77)
[PASS] adapter unknown identity refused (exit=77)
[PASS] adapter 10002:10002 clears the identity guard

== SUMMARY ==
PASS=7 FAIL=0
```

Commands run: the test above; `sh -n` on both shell files; `git diff --check`.
Nothing else.

## Boundary integrity

- Accepted per-role Dockerfiles (`Dockerfile.acp-0.2.0-rc.2-candidate`,
  `acp_product_runner/Dockerfile`, `acp_judgment_runner/Dockerfile`) and the
  accepted `compose.dsh-acp-rc2-candidate.yml` were not modified by this fix.
  Their existing dirty-tree modifications are pre-existing and preserved.
- The unified Dockerfile builder (`official-dsh`) stage and the final-stage
  permission/ownership block are untouched; `USER byq` is appended after them.

## Candidate status

Old candidate `byq-acp-unified:candidate` = `sha256:b4fd707bd4e0…` is **STALE**
(conflicts with the fixed source). All runtime PASS evidence for that image
(role tests, per-role negatives, image inspect, boundary matrix) does **not**
transfer to the fixed source. Rebuild under Root control before any runtime PASS.
