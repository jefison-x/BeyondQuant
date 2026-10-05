# DSH ACP single-version phase — audit and gap list (2026-10-05)

Baseline only. No capability is claimed complete here.

## Baseline and authorization

- New isolated worktree: `/home/jefison/projects/.byq-worktrees/dsh-acp-single-version`
  on branch `codex/dsh-acp-single-version`, created from clean `origin/main`
  `f753eb27157228e8d3d594203878f55ab2c7a53e` (PR #386 squash-merge; old worktree
  `dsh-acp-upgrade` and its evidence retained, not deleted). `verify-worktree.py`
  PASS.
- Fixed official DSH for the single-version target: `dsh-v0.2.0-rc.2` @
  `639ed015397290b3745d163aafe02ffee4aa3f84` (read back from the runner image).
- Old version: `0.1.5rc1` (SDK). Retained only as offline rollback assets.
- Protected inputs backed up before any edit (compose files, `.env.example`, the
  two Adapter Dockerfiles, relevant ADRs) to
  `/tmp/byq-acp-single-version-backup-202610051959` (19 files). No live secret
  or protected deployment config was opened.
- This turn: isolated development, local verification, branch push, PR creation
  are authorized; merge/deploy remain conditionally gated (ADR-0015/0059,
  server rules, exact-head CI, qualification). ADR-0101 same-model
  Tester/Reviewer exception applies. No destructive data operation, no deletion
  of rollback assets, no release/tag. New paid tests require a prior minimal
  plan and budget confirmation.

## Current implementation and reusable evidence

- Ordinary ACP Product path (ADR-0100 slot) merged and qualified to a bounded
  extent: normal answer, second-turn native root reuse, soft stop/continue,
  hard-cancel containment, end rejection, two-group isolation, forged/old-root
  ingress denial, read-only tool ingress, bounded delegation, browser
  real-model answer, ADR-0100 boundary/cleanup. Evidence:
  `docs/evidence/dsh-acp-upgrade/PRODUCT-INTEGRATION-20261005.md`.
- ACP compatibility boundary `services/runtime-adapter/app/compat/__init__.py`
  selects `dsh-v0.2.0-rc.2-acp`; SDK `dsh-0.1.5rc1` and rollback
  `dsh-0.1.2rc1` remain selectable.
- Judgment staging exists and is partially qualified: Backend
  `/internal/research-judgment/{task}/acp-root/{begin,register-agent,result,settle}`
  (`services/backend/app/main.py:881-943`), Adapter helpers
  `research_judgment_acp_control.py` (result/settle), isolated judgment MCP and
  runner. Entry `services/runtime-adapter/app/research_judgment_api.py:135` is an
  unconditional `503 research_judgment_acp_lifecycle_unqualified`.
- F6 machinery: Gateway `task_continuation.py` + `_consume_admitted_task_continuation`,
  Backend continuation permission/budget (`research_continuation.py`), Adapter
  continuation gate. The Adapter gate `RuntimeAdapter.continuation_qualified`
  (`runtime.py:2234`) requires `deepseek-harness-sdk == runtime-bin == 0.1.5rc1`
  and `family == 'dsh-0.1.5'`, so ACP disables the existing Product continuation
  path.
- Atomic Agent (original child/subagent) recovery: no implementation. ADR-0096
  covers only the completed **root** native session reuse.

## Fixed official rc.2 capability (source facts)

- `session/resume` refuses any subagent/parented session:
  `packages/acp/acp/lib/index.js:1216` —
  `if (persisted === void 0 || persisted.origin === "subagent" || persisted.parentSession !== void 0) throw invalidParams("session is not resumable: ...")`.
  → **Atomic original-child Agent recovery is not supported by the pinned
  official version.**
- `session/resume` returns only `{configOptions}` (no `sessionId`); root
  sessions resume by exact id/cwd. Root `session/close`/`session/cancel` exist.
- Per-prompt MCP/header mutation is not supported (prior ADR-0096 probe).
- Child creation exposes `parentSession`/`origin`/`delegationDepth`, but no
  trustworthy invoking-role attribution was identified (ADR-0097 note).

## BYQ wiring required (no new generic harness)

| Capability | BYQ must add | Existing reusable pieces |
| --- | --- | --- |
| F6 ACP background continuation | Adapter ACP continuation path that starts a **new root** (new process/generation, new root MCP identity), resumes the correct native session per ADR-0096, sends only the new input, and enforces budget/revoke/unknown-result + exact terminal ACK. Gateway/Backend delivery, idempotency, claim/settle largely framework-neutral. Provider egress must be bounded (present continuation request gate/proxy is SDK-shaped). | Gateway `task_continuation.py`, Backend continuation admission/budget, ADR-0096 root reuse, ACP provider-proxy/usage contracts (ADR-0099) |
| Judgment ACP lifecycle | Wire `/acp-root/run` to begin → dedicated root create/native register → five read-only tool calls → result persistence → close → exact Backend terminal ACK, with success / never-dispatched-fail / user-cancel / dispatched-unknown settlement; keep the dedicated socket/secret/tools isolated from ordinary DSH. | ADR-0097/0098/0099 accepted; Backend begin/register/result/settle; Adapter control helpers; isolated judgment MCP + runner |
| Atomic child Agent recovery | **Not possible on rc.2** (official refusal). Alternatives change the contract and need maintainer acceptance. | — |
| Single DSH version | Make default Compose, dev env, Adapter, ordinary/judgment runners, CI, Release Images, Promote and ops config all resolve to `dsh-v0.2.0-rc.2` from one authoritative version/artifact manifest; remove SDK imports/version conditionals/model-profile branches/auto-fallback from the normal path; keep old files only as classified offline rollback. | build-revision manifest pattern, profile/identity hashes, `compose.dsh-acp-rc2-candidate.yml` overlay |
| Release chain | Extend Release Images/Promote to cover the ACP Adapter, ordinary runner, judgment runner and required config/topology. | `release-images.yml`, `scripts/release/images.py` |

## Contracts / ADRs to revise (need accepted decisions)

1. **F6 on ACP**: extend ADR-0090 (continuation request limits) to the rc.2 ACP
   family, defining the ACP continuation egress/budget/unknown-result contract.
   Removing the SDK-only `continuation_qualified` restriction without this is
   not acceptance.
2. **Atomic child Agent recovery**: rc.2 cannot resume a child. The minimal
   options (below) change the contract and require a maintainer decision.
3. **Single-version default switch**: a new ADR establishing the authoritative
   version/artifact manifest and the removal of the SDK default/fallback.
4. **Storage cutover**: the SDK session store (`dsh-0.1.5rc1`) is not an ACP
   native format. Mounting it directly is prohibited; a cutover needs an
   explicit accepted storage/会话 contract (completed public history only, no
   pending/unknown replay).
5. **Release/topology coverage** for the ACP containers.

## Decision points (maintainer acceptance required — contract changes)

- **D1 Atomic Agent recovery.** Fixed rc.2 refuses subagent resume (exact
  source line above). Options: (a) resume the parent context and create a new
  child to process the existing business Job result (contract change);
  (b) change official version after separate acceptance; (c) do not offer
  atomic child recovery. None may be labelled "atomic Agent recovery PASS".
- **D2 Single-version default switch.** Requires the ordinary ACP path to reach
  production-grade qualification (the live/injection scenarios below) BEFORE
  the default runtime changes; otherwise the switch would put unqualified ACP on
  the Product path.
- **D3 Storage cutover contract** for existing SDK sessions.
- **D4 Release chain coverage/addition** for ACP containers.

## Minimal verification and completion criteria

- F6 ACP: repeated event, revocation, insufficient budget, lost model
  call/receipt, restart, unknown-result protection; a background-Job-triggered
  **new turn**, not a surviving atomic Agent.
- Judgment: five read-only tools' authorization/argument admission/call
  evidence and forbidden-call denial; success / never-dispatched / cancel /
  dispatched-unknown settlement; `/acp-root/run` stays 503 until the full
  lifecycle and isolation gates pass.
- Single-version: one authoritative manifest; every consumer resolves the same
  tag/commit; removed SDK-only conditionals from the normal path; Release
  Images/Promote identity match; rollback path executable.
- Independent Tester/Reviewer (ADR-0101) on the exact final head; exact-head CI;
  merge gate.

## Live/injection scenarios still NOT_RUN (block default promotion)

Truly delayed old-root request while a new root is active; exact ACK/cleanup
loss blocking the next turn; in-flight process fault, connection loss and
unknown result; concurrent two-user real-model and reboot recovery; ADR-0100
live permission/old-process cleanup. These block default promotion, not
necessarily the candidate merge.
