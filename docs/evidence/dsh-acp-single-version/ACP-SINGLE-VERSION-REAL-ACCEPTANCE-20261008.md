# ACP single-version real acceptance — Agent→MCP task_create → plan → judgment (2026-10-08, byq-acpf6)

Status: **bounded real-acceptance PASS for the single fresh Agent-created chain.**
Not merged/deployed/default-promoted/tagged; no Phase advance. Production untouched.
The judgment result is `no_durable_progress` / `proposal=null` (bounded closure, not a plan advance);
this is recorded honestly and not over-claimed.

## 0. Adapter candidate (this slice)

| item | value |
|---|---|
| old runtime-adapter image | `sha256:3ac2410bc7103ad322bdf1a7c956532958fdd7a37eca5edeecb2e1d896d5ef8b` (backed up as `byq-acpf6-runtime-adapter:pre-diag-20261008`) |
| new runtime-adapter image | `sha256:c324ef803409c0a38e9c34b68bcc847942614eb1e907d13ac2b0a30952b1b0b9` |
| unchanged | backend `9d3bb3c8…`, gateway `b40114c4…`, consumer `ca221acd…` |
| source | HEAD `2d5810973240c5d7692569319c2b5ab337ae2082`, dirty tree (preserved) |
| compose | `compose.yml` + `compose.dsh-acp-rc2-candidate.yml` + `/tmp/opencode/byq-acpf6-override.yml`, env `/tmp/opencode/byq-acpf6.env`, project `byq-acpf6` |
| build | only `runtime-adapter`; `--no-deps --force-recreate`; readiness `/readyz` 200 (health=healthy) |

Evidence: `/tmp/opencode/diag-hardening-20261008/adapter-build.log`, `NEW-ADAPTER-IMAGE.txt`,
`READINESS.txt`, `PRE-BUILD-MANIFEST.txt` (tracked-diff sha256 `b6097e91…`, status sha256 `f00feeec…`).

## 1. Blocker on the previously-used durable user (recorded, not worked around by forgery)

The prior acceptance user `acpchain-user` (workspace `workspace_475249ca69af42a28f03567ab32b6768`)
is **fenced**: the Backend workspace Agent admission returns `can_start:false`
(`GET /internal/runtime-authority/workspaces/…/agent-admission`, boot `4c9e180e30c3e17100afc2955ea06124`).
Cause (read-only DB): three pre-existing Agent turns with `status='active'` and
`authority_status='authority_revoked_unconfirmed'`:

```
75432d37a15c4900bf65e295250026ae  active  authority_revoked_unconfirmed  2026-10-08 00:22
aa13514233354e03837255bbf85df81c  active  authority_revoked_unconfirmed  2026-10-08 00:19
497e63ee13674273b855b7383b885c64  active  authority_revoked_unconfirmed  2026-10-08 00:11
```

The Gateway Agent turn for that user returned `409` with **zero model calls** (adapter
`_require_group_admission` -> `SessionConflict("workspace has an unsettled Agent turn")`).
No cleanup / force-close / fake ACK was performed. The acceptance therefore used the other
clean durable user.

## 2. New task source and identity (explicit)

- durable user: **`admin`** (user `user_b0083bc2a57c459b93d3daf63841d902`), personal workspace
  `workspace_c1b071171522479ca18b25b153e43ab8` (0 pre-existing unsettled turns).
- new conversation: `conversation_39c48495876b46e4923373713310c5a7`, trace
  `byq-trace-dbc871d0a8a74c51980ffc98bbcd0b25`.
- The forbidden unknown `task_af01e6ea117d4d1a9497c7afb0a34a80` / root
  `41d49242599040ac904859405d9558e7` was **not** replayed and received no new call (its rows are
  unchanged, timestamped 09:30Z, before this run).

## 3. Real chain (all values raw)

### 3a. Gateway Agent entry -> MCP `byq_research_task_create`
- `POST /v1/agent/sessions/{conversation}/turns` -> **202** accepted, run
  `746a5b5b48bc4264b64917aee4831913`, runtime session `byq-session-3b74d83994054e259499c2e2e4c4143e`.
- `agent_acp_tool_ingress_observations` for the **agent root** (exactly 3 rows):
  | seq | tool | status |
  |---|---|---|
  | 1 | `byq_agent_authorize` | settled |
  | 2 | `byq_research_task_create` | settled |
  | 3 | `byq_agent_audit` | settled |
  all `root_run_id=746a5b5b…`, `agent_run_id=agent_run_ce9883f90b7b4ebab7bbc6ae4a4a4056`,
  `native_root_session_id=2bce930a-ccfb-497e-9c78-3b7237708e4d`, origin `root`, depth 0.
  Exactly **one** `byq_research_task_create` row.
- agent root closure: `agent_runtime_turns` root `746a5b5b…` `completed`/`closed`,
  `terminal_sequence=10`, `terminal_event_sha256=e17c21d95d0ff6139b03a5aa4b725854ff7bcd68a6a9f94c7a405e70d9d94ad5`,
  `terminal_acp_ingress_sequence=3`, `terminal_unknown_claim_count=0`.
- product-runner signed cleanup receipt: `cleanup:"proven"`, `code:0`, root `746a5b5b…`.

### 3b. Created task (conversation-bound)
`research_tasks`: task_id **`task_bf9e9a042ff241b19b7266cbf3d6def2`**, owner `admin`,
workspace `workspace_c1b071171522479ca18b25b153e43ab8`, conversation
`conversation_39c48495876b46e4923373713310c5a7`, trace matching, status `planned`.
(Version at creation was 1; it is now 2 after the judgment advanced the plan — see 3d.)

### 3c. Product plan create/readback (ADR-0108, no references)
- `POST /api/product/research/tasks/{task}/execution-plan {idempotency_key: acp-diag-plan-bf9e9a-1}` -> **201**
  `{plan_version:1, task_version:1, stage:strategy_draft, status:active, next_action:draft_strategy}`.
- `GET` -> **200** identical projection.
- Final `GET` after judgment -> **200** `{plan_version:2, task_version:2, stage:needs_attention, status:blocked, next_action:resolve_blockers}`.

### 3d. ADR-0107 consumer -> dedicated judgment (single target, one run)
Consumer run **once** with `BYQ_JUDGMENT_TARGET_TASK=task_bf9e9a…` (no other task selected):
`stages` 200 -> `dispatch` 200 -> `stage-claim` 200 -> `stage-dispatch-intent` 200 ->
adapter `acp-root/run` 200 -> `acp-root/status` 200.
- call_identity `byq-judgment-bcd9644be3b42f9cd42c5bfe3281cc35`, attempt `1:strategy_draft:1`.
- judgment root `7be7f0b20b474b468a9a632ad6cf0237`; binding `agent_bound`, native
  `ad70ed42-ece3-4d68-9428-613b859e43d9`, AgentRun `agent_run_7aab081baf314f4f83e7d9fa44fade8a`.
- committed result (`research_judgment_stage_calls.result_json`): `completed`/`needs_attention`,
  `progress.reason=no_durable_progress`, `proposal=null`, `model_calls_used=1`.
- **exact terminal ACK**: `root_status=completed`, `root_authority_status=closed`,
  `terminal_sequence=2`,
  `terminal_event_sha256=d2a3e218a895dc25f59abef15599bcd9294a1e4cc9cc772d542e6fb7f8d97bc6`,
  `terminal_acp_ingress_sequence=2`, `terminal_unknown_claim_count=0`.
- adapter judgment journal `phase=terminal_closed`, 3 provider attempts all `opencode-go-chat` 200
  (real usage), bounded `turn_diagnostic` (`finish=completed`, `error_class=null`, `error_code=null`,
  `dsh_stop_reason=unknown`) — **no secret/prompt persisted**.
- judgment-runner signed cleanup receipt `cleanup:"proven"`, `code:0`, root `7be7f0b2…`.
- second consumer pass not performed (single `--once` run).

### 3e. Browser readback
Playwright headless Chromium, frontend origin `http://127.0.0.1:18081`, durable `admin` login:
`GET /api/product/research/tasks/{task}/execution-plan` -> **200** `plan_version:2,
stage:needs_attention, status:blocked`; `logged_in:true`; **foreign origins: []**; 42 requests, no errors.

## 4. Independent Tester (raw) — result

Verdict: **all substantive checks PASS**, with three clarifications and one mount observation:

1. Trace ingress total is **5**, not 3: the agent root contributes exactly 3
   (authorize/task_create/audit) and the judgment root contributes 2
   (`byq_research_stage_input_get`, `byq_research_get`) sharing the same trace_id. The
   `byq_research_task_create` row is exactly one.
2. `research_tasks.version` observed as **2** (created 1, advanced to 2 by the needs_attention result).
3. No `plan_version=1` row is retained (`research_execution_plans` is updated in place to v2); v1 is
   evidenced only by the Product create/readback artifact JSON.
4. The judgment journal path under `workspace_475249ca…` and `workspace_c1b07117…` is the **same
   inode** (dev 2050, inode 10112863, nlink 1, sha256 `6d5be465…`): both workspace paths are bind
   mounts of the **same product-sessions volume** (pre-existing override config). This is a mount
   alias, not duplicated data; the journal content is bound to `workspace_c1b0…` and the accepted
   begin receipt. No replay/duplicate plan/root; forbidden task untouched.

## 5. Boundaries
- Bounded PASS for this single chain only; `no_durable_progress`/`proposal=null` = bounded closure,
  not an effective research/plan advance.
- No new public binding contract, no UI change; ADR-0106/0107/0108 contracts only.
- Child actual-tool coverage handled separately (not mixed in here).
- No push/merge/deploy/default/tag/Phase; model-connection failure would have stopped without retry
  (none occurred; every provider attempt returned HTTP 200).
