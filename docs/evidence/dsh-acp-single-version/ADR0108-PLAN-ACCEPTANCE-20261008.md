# ADR-0108 foreground plan creation — real acceptance (2026-10-08, byq-acpf6)

Status: **Product plan-creation PASS** (real browser, durable BYQ user, Gateway/Product API).
Not merged/deployed/default-promoted; no Phase advance. All values redacted of secrets.

## Candidate images (old -> new)
| Service | old digest | new digest |
|---|---|---|
| backend | `sha256:8f6b5f31d48097890ead1fb57bece1ca100daab4ceb31b5f06615a2de55e9a5e` | `sha256:9d3bb3c863ee7e8597f5868d5f4a56a9fc6175dcdd69a69e21148a2b3b6987e6` |
| gateway | `sha256:839e964aeea56ce5b1b50e8b36ed4c33e75a2789cd14e38d45cdcf5008059e08` | `sha256:b40114c4aa71f0904726a74873ef672836ecf93ff1ac817cb31d007523e0b043` |
| judgment-consumer | `sha256:5a19c7b284c093f7ca61963d0678118f3ae502928b79ce29db97a55a23d06423` | `sha256:ca221acd5c952c4625ad5b73e9f0a332f8d578cf450e7ed9d21cb7c01dbaf883` |

Built from worktree HEAD `2d5810973240c5d7692569319c2b5ab337ae2082`; deployed only to the
`byq-acpf6` stack (backend + gateway recreated; production and other stacks untouched).

## Real-browser Product flow (Playwright headless Chromium, frontend origin)
Browser requests use the frontend origin only; all API calls are Gateway/Product API
(`/api/product/...`). Evidence: `plan-acceptance-evidence.json`, `plan-readback-evidence.json`.

- Durable user A login: PASS (session cookie).
- Task `task_af01e6ea117d4d1a9497c7afb0a34a80` (owner `acpchain-user`, workspace
  `workspace_475249ca…`): pre-plan read `404`.
- `POST /api/product/research/tasks/{task}/execution-plan {idempotency_key: plan-adr0108-1}`
  -> **201** `{plan_version:1, task_version:1, stage:strategy_draft, next_action:draft_strategy}`.
- `GET …/execution-plan` -> **200** (same projection).
- Exact key+body replay `POST` -> **201**, byte-identical to the first receipt; follow-up `GET`
  -> **200** `plan_version:1` (no second plan).
- Wrong binding (task2 binds task1): `POST` -> **404** `research execution plan reference is not
  bound to this task`.
- Wrong binding (task2 binds task1's conversation): `POST` -> **404** same message.
- `GET` for task2 -> **404** (no plan created).
- Forged body owner: `POST {owner_principal: <user-B>}` -> **422** `invalid research execution plan
  create request` (closed create request refuses identity fields; the trusted identity never comes
  from the body).
- Cross-user: user B (`admin`, personal workspace `workspace_c1b07117…`) `GET` -> **404**;
  `POST` -> **404** `research task not found`. User B login PASS.

## ADR-0107 consumer -> dedicated ACP judgment (scoped to this task only)
Consumer run once with `BYQ_JUDGMENT_TARGET_TASK=task_af01e6ea117d4d1a9497c7afb0a34a80`
(no other task selected). Outcome:

- claim `byq-judgment-ef254112a3921095b7e6551e82d177e6`, attempt binding `1:strategy_draft:1`;
- adapter ACP root `41d49242599040ac904859405d9558e7`, bound `agent_run_dde93f53e60f45ff823b2b5b9bd10798`;
- the model ran (3 provider attempts `opencode-go-chat`, all HTTP 200, real token usage);
- settlement `outcome_unknown` / terminal `interrupted` (no committed result);
- exact terminal ACK: `terminal_event_sha256=008eec7ee0736e4226ef9b00df06ad37cff211e87cf31beb57680fbde034f2ad`,
  `settlement_digest=sha256:74fbd85d358d72dc9df23d5d26b676f8c3a43577da2b03de8e76933996c3167b`,
  `terminal_acp_ingress_sha256=1fad1825666ed7a4dd3dc7859befa0042409e72e914d8809852aabee38ff89f2`,
  `root_authority_status=closed`.
- **Boundary:** this is a bounded closure, NOT an effective plan advance (per the rule that a
  non-committed/null proposal only counts as closure). The plan advanced to `needs_attention`
  (plan_version 2, status `blocked`, next_action `resolve_blockers`).

## Page read-back
Browser `GET /api/product/research/tasks/{task}/execution-plan` -> **200**
`{plan_version:2, task_version:2, stage:needs_attention, status:blocked,
next_action:resolve_blockers}`.

## Forensic addendum — judgment root actual fields (read-only)
Distinguishing each item, none over-claimed:

| Item | Actual value |
|---|---|
| Provider HTTP (3 attempts) | `completed`, HTTP **200**, `error=None` (no provider/network error) |
| Provider tokens | in 2157/424/497, out 106/114/779 |
| Durable journal phase | `prompt_may_have_dispatched` (NOT `result_prepared` / `result_committed` / `terminal_closed`) |
| Journal result keys | **absent**: no `result` / `result_prepared` / `terminal` / `cleanup` / `committed` |
| `research_judgment_stage_calls.result_json` | **NULL** (no result committed) |
| Run path | `run_judgment_acp_root`: commits only when `finish == "completed"` AND `output.result()` returns a result; otherwise `_settle` -> `outcome_unknown`/`interrupted`. Here the ACP prompt did not reach a committable completed result. |
| Exact ACK | `terminal_event_sha256=008eec7e…`, `settlement_digest=sha256:74fbd85d…`, `terminal_acp_ingress_sha256=1fad1825…`, `terminal_sequence=2`, `root_authority_status=closed`, `process_fence=stopped` |
| Plan after | `plan_version=2, stage=needs_attention, status=blocked` (bounded closure) |

Concrete fault: the ACP judgment turn ran 3 successful provider calls but ended before preparing/committing
a result, so the adapter settled `outcome_unknown`/`interrupted` and closed the root with a proven
process fence. It is **not** a valid judgment/proposal result and **not** an effective plan advance.
No provider network error occurred, so the stop-the-new-real-call convention is not triggered by this
run; the unknown business outcome is preserved and **not** replayed (no new call/attempt was made).

Minimal-fix candidate (for maintainer decision, NOT applied): make the judgment ACP turn's non-completed
outcome diagnosable from the persisted journal — record the ACP `finish` status and the DSH-side stop
reason in the journal — so `outcome_unknown` is distinguishable from a truncated-but-valid turn. This
does not alter the paused recovery ADR or add a retry path.

## Provenance findings (recorded, not over-claimed)
1. **Task provenance is NOT a proven Agent `byq_research_task_create` chain.** The task's
   conversation is bound to runtime session `byq-session-7ef865e2907d492485547eea6ed1268f` (trace
   `byq-trace-639a3e36…`), and a completed `agent_run_aef0aaeb…` exists on that trace, but
   `agent_acp_tool_ingress_observations` for that session contains only `byq_agent_authorize`,
   `byq_research_get`, `byq_backtest_task_get`, `byq_agent_audit` — **no** `byq_research_task_create`.
   So this task was a diagnostic/prior-acceptance-created bound task (idempotency key
   `acp9-readonly-20261007`, never planned before this run). It is a lawful, never-executed,
   provenance-provable bound task; it is **not** counted as a complete Product/Agent new-creation
   chain.
2. **Product `create_task` conversation-binding gap (independent, real).** A task created via
   `POST /api/product/research/tasks` has **no** bound conversation, so a subsequent foreground plan
   create fails `422 research execution plan requires the bound conversation`. The Product task-create
   route forwards no session id, so `ResearchStore._trusted_conversation_id` finds no conversation.
   Preserved as FAIL evidence; a precise small proposal for a conversation-binding contract is a
   separate maintainer decision (no recovery-architecture expansion here).
