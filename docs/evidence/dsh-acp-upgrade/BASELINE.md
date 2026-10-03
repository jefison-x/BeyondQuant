# Product DSH ACP upgrade: audit and gate ledger

Date: 2026-10-04. Standalone maintenance; no Product Phase change.

## Baseline and rollback

| Item | Observed identity |
| --- | --- |
| Fetched `origin/main` and isolated branch base | `5619d6aee53a75ae1d461e7732efa922f89c6e4b` |
| R1–R4 | Merged PR #385 is in that base; affected contracts need qualification. |
| Running Runtime Adapter image | `sha256:968aef621c15fee97457ecd72962f91aaabba65cee350a05075c6420d6351bd0` (read-only Docker inspection); in-container SDK and runtime-bin both report `0.1.5rc1`. |
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
| ACP mapping and restart design acceptance | NOT_RUN | ADR-0093 is Proposed; maintainer must decide the recovery contract. |
| ACP executable keyless tests and complete matching container | NOT_RUN | No dependencies installed or BYQ candidate image built in this track; prior isolated upstream report is not BYQ acceptance. |
| Adapter implementation and BYQ targeted integration | NOT_RUN | Held at design gate. |
| Browser and runtime Tester/Reviewer/Root qualification | NOT_RUN | Required after implementation; current independent source Tester and design Reviewer do not substitute. |
| Push, PR, exact-head CI, merge, Release Images, Promote, deploy | NOT_RUN | Downstream gates closed. |

No model, MCP business, Job, market-data, migration, CI, merge or deployment operation was run in this track.

## Primary references

- [Official fixed release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.0-rc.2) and [exact commit](https://github.com/deepseek-ai/deepseek-harness/commit/639ed015397290b3745d163aafe02ffee4aa3f84).
- [ACP protocol contract](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/README.md), [session admission and resume](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/src/index.ts), [MCP header mapping](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/acp/acp/src/mcp.ts).
- BYQ authority implementation: `services/backend/app/agent_research.py` boot rotation, exact terminal closure and re-registration checks; `services/runtime-adapter/app/runtime.py` root-scoped process, prompt and terminal-ACK gates.
