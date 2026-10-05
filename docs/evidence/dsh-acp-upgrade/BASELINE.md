# Product DSH ACP upgrade: audit and gate ledger

Date: 2026-10-04. Standalone maintenance; no Product Phase change.

## Baseline and rollback

| Item | Observed identity |
| --- | --- |
| Fetched `origin/main` and isolated branch base | `5619d6aee53a75ae1d461e7732efa922f89c6e4b` |
| R1–R4 | Merged PR #385 is in that base; affected contracts need qualification. |
| Running Runtime Adapter image | `sha256:968aef621c15fee97457ecd72962f91aaabba65cee350a05075c6420d6351bd0` (read-only Docker inspection); in-container SDK and runtime-bin both report `0.1.5rc1`. |
| Preliminary local ACP candidate image | `sha256:16b5238ddded2c04ae9ac66812b391e4991122ceb1ef94b7ba8fbd90dd3e3437`, 1,430,939,146 bytes. Built from exact official commit and lock; it predates the final Adapter binding and identity-file edits, so it is not a release candidate or final tested image. |
| Existing Dockerfile | `services/runtime-adapter/Dockerfile.post-u8-304-candidate`, SHA-256 `93b2b2646f0b1f7c1209af81c5e97d4e6f0e638df7036c7ff2e66ebb444ae636` |
| Existing Python lock | `services/runtime-adapter/requirements.candidate.lock`, SHA-256 `3040ac39eb1ead938b87a59b743ca6b7aa28c61cc880a7ce74451ea1de7e541a`; DSH SDK and runtime wheels are `0.1.5rc1`. |
| Existing Product composition | `plugins/dsh-byq/profiles/root-scoped/dsh-0.1.2rc1/byq-product.yml`, SHA-256 `68dc022bd520feff8559835e7853190a8bf325d475b10d2ac5362d57f233923b` |
| Existing composition identity | `plugins/dsh-byq/profiles/root-scoped/dsh-0.1.2rc1/byq-product.identity.json`, SHA-256 `fc0685239ae4c55d616a605b62c3f0c6f168415844e1e618d187ffe3efd75475` |
| Existing release identity | `config/dsh/generated/deployment.identity.json`, SHA-256 `430366d49fe1974e5db7e053b5b9f57038eceaa186b60b91a0a69b402090a7a0` |

The tracked configuration remains intact at the clean base. The running image is retained. The Runtime Adapter volume is mounted at `/var/lib/byq/dsh-sessions`; no volume data was read or changed. Protected deployment secrets were not opened, copied or printed. Before deployment, the trusted operator must verify and back up live protected configuration under ADR-0080, then read back its identity without exposing values.

## Fixed source and contract finding

The official `deepseek-ai/deepseek-harness` release `dsh-v0.2.0-rc.2` points to `639ed015397290b3745d163aafe02ffee4aa3f84`. An isolated checkout at `/tmp/byq-dsh-acp-rc2-source` resolved that tag and commit. Its ACP package declares version `0.2.0-rc.2` and `@agentclientprotocol/sdk` `1.4.0`. This proves source identity, not a built image or BYQ compatibility.

The current Adapter puts `BYQ_ROOT_RUN_ID` and other MCP identity inputs in each root-scoped DSH process environment. It starts a new process for the next root and supplies only completed public history to that fresh root. Prompt admission blocks while exact prior terminal receipts are pending. See `services/runtime-adapter/app/runtime.py` and Clean Break ADR-002.

At the pinned ACP source, `session/new` and `session/resume` receive `mcpServers`; `session/prompt` has no documented MCP header update. HTTP MCP headers are mounted into that session's client configuration. Reusing one native ACP session for another BYQ root would retain the previous authority. Supplying BYQ public history on native resume would risk duplicate context. Official ACP resume restores a persistent native log without replaying an interrupted prompt and can remount MCP, but that does not restore BYQ Backend authority. Its interrupted-tool repair marks missing results unknown, not safe to retry. ACP close flushes and disposes the active scope but leaves native persistence resumable; BYQ must separately reject an ended Product session. Backend revokes old active roots when the Adapter boot identity changes (`authority_revoked_unconfirmed`); a new boot cannot re-register the same root or close it with the old exact terminal ACK. ADR-0093 records the resulting restart decision. No ACP adapter implementation was admitted.

## Qualification status

| Gate | Result | Boundary |
| --- | --- | --- |
| Main synchronization and isolated worktree | PASS | Exact base above; no main edits. |
| Official fixed tag/source identity | PASS | Official release and exact local checkout. |
| Independent keyless ACP source review | PASS | Tester verified MCP mount, no per-prompt header change, no automatic resume replay, unknown tool repair, cancel and close distinctions. |
| Tracked rollback artifacts and running image identity | PASS | Exact hashes and image ID recorded above. |
| Protected live configuration backup and full rollback readiness | NOT_RUN | Trusted operator predeployment gate; no secret values were opened or copied. |
| Per-root MCP identity in one reused ACP session | FAIL | No supported per-prompt MCP/header mutation. |
| Same-root Product recovery across Adapter boot rotation | FAIL | Native ACP resume works at protocol level, but current Backend authority cannot transfer to the new boot. |
| ACP mapping and restart design acceptance | PASS | Maintainer accepted ADR-0093's same-root Backend transfer on 2026-10-04; implementation and qualification remain gated. |
| ACP session MCP identity across two root sessions | PASS | Independent keyless mock MCP probe observed separate A/B bearer headers at root session setup. No business/model call was made. |
| Product in-process delegate MCP access | FAIL | At pinned official source, independent Tester observed child model tool catalog empty for both sessions; an exact `toolFilter` on `mcp__byq__ping` failed as an unknown global tool. Root-local ACP MCP clients do not reach spawned child scopes. ADR-0094 records the tested process-scoped alternative and remaining evidence failure. |
| Process-scoped per-root MCP alternative | PASS | Independent keyless two-process probe: root and child saw exact mock BYQ tool; child allowlist and persona held; each process sent only its own synthetic bearer. This does not qualify the current ACP per-session implementation or child event evidence. |
| ACP child domain-call evidence projection | FAIL | Child native log had exact tool call/result, but parent ACP `session/update` omitted both. BYQ Adapter cannot currently prove child business-call evidence from ACP. ADR-0094 remains Proposed. |
| Product model route and credential parity | NOT_RUN | Existing OpenCode routes are absent from the ACP overlay. Automatic approval review rejected adding the existing provider configuration, citing the prohibition on external paid-model calls; no such call was made. Do not treat DeepSeek-only static composition as parity. |
| ACP continuation guard integration | NOT_RUN | The process-specific guard patch and exact ACP reservation header are implemented, but no fixed-container pre-dispatch/unknown-outcome test has qualified them. An earlier proposed relaxation of the old header check was rejected by automatic review and abandoned. |
| Fixed upstream ACP source build and keyless focused tests | PASS | `corepack pnpm install --frozen-lockfile`, native system addon, `build:lib:host`; 4 ACP test files and 97 tests passed. Local source only, no BYQ acceptance. |
| Backend same-root transfer focused tests | PASS | Three exact tests passed in the branch Backend image against a new tmpfs-only `byq_domain_test` PostgreSQL instance. An initial fixture actor mismatch failed, was corrected, and the exact trio passed; isolated container/network were removed. |
| Gateway recovery focused tests | PASS | Seven tests passed in the branch Gateway test image, network disabled. They cover exact transfer ordering, settled receipt check, missing binding fail-closed, stale cache and no duplicate public history. |
| ACP transport mock tests in candidate image | PASS | Four focused tests passed with current isolated Adapter files mounted read-only in the preliminary image; this is a mocked ACP peer, not a Product flow. |
| Complete matching BYQ ACP container | NOT_RUN | A preliminary fixed-source local image built and its profile dump passed, but the image predates current BYQ code/identity files and has no full integration qualification. |
| BYQ Adapter/Gateway/Backend integration qualification | NOT_RUN | Isolated implementation slices exist but are not yet qualified. Product promotion held at delegate MCP failure. |
| Browser and runtime Tester/Reviewer/Root qualification | NOT_RUN | Required after implementation; current independent source Tester and design Reviewer do not substitute. |
| Push, PR, exact-head CI, merge, Release Images, Promote, deploy | NOT_RUN | Downstream gates closed. |

No model, MCP business, Job, market-data, migration, CI, merge or deployment operation was run in this track. The upstream source build and tests used no model credential.

## Primary references

- [Official fixed release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.0-rc.2) and [exact commit](https://github.com/deepseek-ai/deepseek-harness/commit/639ed015397290b3745d163aafe02ffee4aa3f84).
- [ACP protocol contract](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/README.md), [session admission and resume](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/src/index.ts), [MCP header mapping](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/src/mcp.ts).
- BYQ authority implementation: `services/backend/app/agent_research.py` boot rotation, exact terminal closure and re-registration checks; `services/runtime-adapter/app/runtime.py` root-scoped process, prompt and terminal-ACK gates.
