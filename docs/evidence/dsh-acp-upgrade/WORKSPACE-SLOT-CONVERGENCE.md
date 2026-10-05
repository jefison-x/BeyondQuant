# Workspace slot convergence — 2026-10-05

The maintainer accepted the simplified resource-group design with
“那就按上面的方法收敛。” ADR-0100 now records that decision. This slice
supersedes the unaccepted concurrent shared-container supervisor proposal;
older failed probes and qualification records remain intact.

## Frozen implementation scope

- One statically configured ordinary ACP execution container per supported
  personal Workspace. Workspace is the resource identity; owner is the actor.
- Saved public sessions occupy no slot. Input starts the ordinary ACP process.
  Busy groups reject input without a queue; independent groups have distinct
  sockets, control secrets, session volumes and replay tombstones.
- Reuse DSH native history only after the existing normal-completion, exact
  Backend ACK and cleanup gates. Cancellation, unknown outcomes and process
  faults retain their separate reconciliation rules; no interrupted replay.
- A slot is released only after its exact scope has both Backend ACK and a
  signed proven cleanup receipt. Backend reads unresolved business roots to
  maintain the fence across Adapter restart. No durable capacity scheduler.
- Reuse existing sequential runner cleanup and byte relay. Unknown cleanup or
  loss of authenticated EXIT retires only that execution container.
- No team membership, dynamic allocation, multi-slot routing, queue, per-root
  supervisor, cgroup delegation or second Agent harness is added.

The candidate overlay statically supports one configured personal Workspace.
Unconfigured groups fail closed. Increasing capacity later requires routing
and storage qualification; adding container count alone is insufficient.
Dedicated research judgment retains ADR-0097/0099 isolation and its disabled
trusted entry; this ordinary slot change does not qualify that entry or F6.

## Evidence ledger

| Gate | Result | Evidence and limits |
| --- | --- | --- |
| Clean retained base | PASS | Retained `d74ac9eb2d0321c6f8bfe16ddf9d558d6ebbb06a`; synchronized `origin/main` remains `5619d6aee53a75ae1d461e7732efa922f89c6e4b`. Earlier commits preserved. |
| Protected tracked inputs | PASS | Compose, ADR-0100 and prior qualification ledger copied to `/tmp/byq-acp-slot-convergence-20261005` before editing; no live secret/config modification. |
| Focused client + completed native reuse regression | PASS | 16/16 in retained Adapter dependency image, read-only source, no network/model calls. Synthetic socket/compatibility evidence. |
| Candidate Compose parse | PASS | Base plus overlay parsed with synthetic required environment values; no services started. |
| Product runner unit slice | PASS | Worker final 8/8; independent Tester prior seven 7/7, then only the new post-consumption deadline case 1/1 with no-new-privileges and no network. |
| Current Adapter integration / Backend admission | PASS, focused | Independent Tester: Adapter 7/7 (lazy/busy/native-reuse retry, ACK and cleanup ordering, HTTP admission fail-closed, interrupted repair ACK); Backend 1/1 on a new tmpfs PostgreSQL 16 with no host port. Backend verifies same-group blocking, exact close, other-group admission and unknown old roots after boot rotation. Temporary DB/network removed. Adapter compatibility remains synthetic. |
| Startup/transport and held-scope negative | PASS, focused | Worker client/transport 13/13. Independent Tester ran five transport cases, then only the new held-scope rejection case 1/1. Safe no-process close requires registry to hold no lease; an unsafe signed rejection never supplies exit proof. |
| Matching baked runner and real keyless ACP startup | PASS, bounded | Matching baked runner and Adapter images ran in separate private PID namespaces, read-only rootfs and no network. UID/GID10002 created mode0700 home/tmp; official ACP initialize/session-new/session-close succeeded; signed EXIT cleanup=proven. The MCP responder is a synthetic localhost fixture. No prompt, tool, model, route-selection or Backend ACK ran. See [preserved probe](workspace-slot-probe/README.md). |
| Candidate missing slot configuration | PASS | In the baked read-only/offline Adapter image, missing bindings raised the expected failure; no local ACP fallback. Image `.git/HEAD` matches fixed official commit. |
| Independent Reviewer / Root slice conclusion | PASS, bounded | Reviewer: Functional, focused Tests and Clean Break Architecture PASS after final readback; Root agrees for this ordinary single-slot implementation and keyless process path. Full default upgrade remains unqualified. |
| Actual Gateway/Product API browser and model flows | NOT_RUN | No paid call or Product integration acceptance in this slice. |
| Judgment wiring, delegate proof, F6, full ACP default qualification | NOT_RUN | Existing blockers remain; do not infer closure from slot convergence. |
| Exact-head CI / push / PR / merge / release / deployment | NOT_RUN | No promotion permission is exercised while qualification is incomplete. |

## Failures preserved

The first source compilation attempted to create bytecode on the read-only
worktree mount; a `/tmp` pycache destination passed. Initial runner tests
exposed the judgment-scope tombstone mismatch and a synthetic launcher fixture
error. Independent review additionally found the readiness payload mismatch,
Adapter leaf/mount permissions, ignored unknown cleanup in relay/startup,
repair-harness ACK retention, pre-START failure classification and ACK retry
idempotency. Each requires a focused correction and readback; no full suite
rerun is required by this slice.

The first real runner-container attempt returned `READONLY_RUNNER_READY=NOT_READY`
after about ten seconds. No START/ACP input was sent. Container ID was
`c4602c06123d0b599f82c30411777cf1d33fcb890293ce2e68d12f72a61e9137`.
The worker removed that exact temporary container before capturing logs or
inspect, so its cause is **unknown**, not proven to be a stale-image fault.
This failure remains recorded. A new probe must capture readiness, logs and
container state before exact cleanup; passing units cannot replace it.

## Local image identity

The initial canonical Dockerfile built the fixed official source using cached
source/locked-dependency build steps. Subsequent reviewed server fixes were
baked using `/tmp/byq-acp-slot-convergence-20261005/Dockerfile.final-source`:
`FROM byq-acp-product-runner:qualification-20261005`, COPY the current server
and contract to their fixed paths, then remove their write bits. Both resulting
file hashes were read back from the image and match the workspace. This avoids
rebuilding the unchanged DSH tree; it is not a published release image.

| Input | Identity |
| --- | --- |
| Initial canonical local image | `sha256:fe3dbfe9ec438f9982a649fbf519ac646115dafce00bf3d061a939a057a1a998` |
| Matching local qualification image | `sha256:6722c919993d35201249a0eecf80b5bda3f4be7122a356876e2493dc2f318dca` |
| Product server source/image SHA-256 | `4bf7283291c2952e4688478d83e82508ec5ea8ad93c0a645675d4ec350d3113a` |
| Product slot contract source/image SHA-256 | `d3b888aaf9745e83f18d9e1e9def58dce7c9839f3a9c318aeb275dd874ccebbb` |
| Canonical Product runner Dockerfile SHA-256 | `fa5e86637df50c453239d37a4ff1b6f7cd3c1316b07f0accd3e6cb74f5605638` |
| Image `.byq-source-commit` | `639ed015397290b3745d163aafe02ffee4aa3f84` |

The matching Adapter local image is
`sha256:de094b9c628308744f3544cdebf0bf9c69838864f61c2b345b57a829d09dbe5a`.
It derives from the retained fixed-source/dependency image
`sha256:f600f4eb348542b96d9e0c64243edc47ee37c8f8f509200c8099da9d658aa2ba`
using `/tmp/byq-acp-slot-convergence-20261005/Dockerfile.adapter-final-source`:
COPY current `app` and contracts, remove write bits, return to UID10002, and
set transport `product-slot-v1`. Runtime, API module, ACP compatibility,
slot transport and client file hashes all match readback from the image.
The canonical candidate Adapter Dockerfile also defaults to this transport;
missing static bindings fail startup rather than selecting local DSH.

## Rollback

No business schema/storage migration or live deployment occurs. Keep the exact
`0.1.5rc1` image/config rollback in `BASELINE.md`. New workspace-native volumes
are candidate-only; old candidate global ACP paths are not silently migrated
or reused. Preserve the volumes and business outcome evidence when rolling
back. SDK rollback does not convert unknown business results into “not run”.
