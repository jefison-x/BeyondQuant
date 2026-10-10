# ADR-0106 ordinary Product provider budget — slice evidence summary (2026-10-08)

Bounded, reviewable summary of the ADR-0106 ordinary Product work on the isolated `byq-acpf6` stack.
No secrets, no raw native prompt text; only non-secret hashes/ids are referenced. Historical failures
preserved. No push/merge/deploy/tag, no default promotion, no third compression.

## Accepted decision
- `docs/architecture/adr/ADR-0106-ordinary-acp-product-provider-budget.md` — **Accepted** (2026-10-07):
  independent closed `product-turn.v1` profile; per-call input 262144 / output 8192 / tool-payload 131072;
  cumulative 4194304 / 131072 / 1048576; 16 provider calls/attempts/tools; concurrency 1; deadline 180000.
  The provider proxy proves only the model HTTP budget; the tool-call count is a separate proof.

## Implementation (reuse; no second harness; no fork)
- `packages/contracts/product_turn_request.py` (closed profile; hash covers provider `opencode-go-chat` /
  model `deepseek-v4.1-flash` / upstream `https://opencode.ai/zen/go/v1` / target `/chat/completions` + limits).
- `app/research_request_gate.py` (gate accepts the product-turn profile), `app/continuation_budget.py`
  (`create_acp_product_budget_overlay`: single closed Go chat route pinned to the local proxy, model output
  capped at 8192; no continuation reservation, no tool allowlist, no web-tool change), `app/runtime.py`
  (ordinary ACP Product branch: reject non-authorized model `NOT_QUALIFIED` before any proxy/start; first
  proxy closed on any failure; guard rotation only after the previous generation is cleaned),
  `app/compat/dsh_acp.py` + `services/acp_product_runner/server.py` (accept the route-only overlay; exact
  closed shape; atomic guard rewrite temp+fsync+same-dir `os.replace`, `O_NOFOLLOW`, 0600).

## Free proof (no provider call)
- `test_product_turn_budget.py` + `test_continuation_profile.py` + `test_acp_product_slot_runtime.py` —
  **34 passed** (includes the actual-submit loopback gate proof: over-cap -> 429 + `posts=0` + root journal;
  unknown -> next HTTP blocked; guard-rotation ordering; qualified-fixture; unsupported-model rejection).

## Real ordinary flow (isolated `byq-acpf6`; same-scope authorization)
- Images: runtime-adapter `sha256:dd34862a3cfdbe04acccc470f3ff0f91fd7a34b48e66365e4bd086a9a5be5294`;
  ordinary and chain product runners `sha256:c4acdc5a035eb9d727015f062e10dff86a3933210432258e41fac12356c19963`
  (Root readback, 2026-10-08).
- **Two consecutive turns real PASS** — session `conversation_abc35cf6c59d48999c514dbc86cf6b60` /
  `byq-session-f87802967a684a41b3be9254b092239a`: turn 1 root `5406bd26c5014e0f96d75b37c67514f3`
  completed/closed (seq 7, 0 tools, assistant `ALPHA7`); turn 2 **fresh root**
  `376cacfa8e054cfa86170be626638a3a` completed/closed (seq 13) reusing the same native session
  `661fe598-fdd8-4f85-9942-fc2c29e76894`, assistant recalled `ALPHA7`.
- **Native-session source evidence** (pre-stop snapshot): `session.v4.jsonl.zstd`
  sha256 `3995e9b3d4498e99d94e1247c6bdd9063646be9606389034f2a2152aef6fff91`, 29 lines; each of the two real
  inputs appears once. Scope: two ALPHA7 turns only; later inputs not counted here.
- **Cancel execution + explicit next input — local PASS** (not "stop->continue no-unknown"): soft cancel ->
  root `fc7e36de4d344287a7d240e7635d1f3f` cancelled/closed (seq 17); the subsequent turn
  `6124a821aa694003aa10c0b2af76bb1a` is an **explicit new user input in a separate root** (assistant
  `RESUMED`), not a same-root automatic next request / replay.
- **End -> reject**: hard cancel (root `1f55c51fc407414c94e6209e9e8d3d`, cancelled/closed seq 29) then a new
  input rejected `409` "runtime session is not available for this operation".
- **End UI actually asserted** (`browser-observe/end-ui.json`): banner `该会话已结束` rendered; send refused
  (message count 9 -> 9); the input is not hard-`disabled` (enforced by the terminal guard).
- **Same-conversation browser** (`browser-observe/network10-pinned.json`): Gateway replay 200, session/trace
  match, 77 requests, 0 foreign.

## Preserved failures (not model success; precisely aligned)
- A `conversation_98d163c74dfc4749b259b6ffd49fcf32`: guard-write rejected the real overlay (writer UUID
  regex v4-only vs runtime UUIDv5) -> no root, no provider attempt.
- B `conversation_1b02aa99069e4ae191bdb4278420945a` root `d37700944db1404289008c578dfe00ec`: DSH
  `max_tokens 32768` > profile 8192 -> `output_tokens_limit` (root failed).
- C `conversation_b8a42b16a66f4ac693050a0b19b287bd` turn 1 root `3265ef46bfa24675a4b1db0bbca9fb10` OK; the
  **normal next input** failed on `O_EXCL` guard-exists.

## Cancelled-turn real gate/cleanup (honest)
- Cancelled turn `fc7e36de...` gate record (`product-turn-generation-2f507a38e6f546318d11772539d62116`):
  `admitted` then `completed` with **`provider_outcome_unknown`** (`forwarded:false`, `status:0`,
  `usage_source: unknown`). So the provider outcome/usage remain **UNKNOWN**; the DB `cancelled` does not
  prove "no provider unknown", and `forwarded:false` does not prove streaming was interrupted.
- Signed cleanup receipt: `byq-acp-product-runner-cleanup.v1`, `cleanup:"proven"`, `code:0`,
  `reason:"cancelled"`, exact `root_run_id`/`session_id`/`generation_id`/`runner_instance_id`.
- Cancel native tool evidence = 0 (`agent_acp_tool_ingress_observations` 0, `agent_acp_domain_call_observations` 0).
- Independent review confirmed that after soft cancellation the explicit new input used a new native
  session (`b373e8de...`) under `root-288e19e1...`; it did not resume the original native instance. The
  same-native proof above applies only to the two normally completed ALPHA7 turns.
- The hard-end root `1f55c51f...` also retains provider-outcome unknown in its own journal. Execution
  cancellation/closure and denied subsequent input do not establish a known model outcome.

## Public projection divergence (decision, not a broad API change)
- `product_conversations.status`/`_public_conversation_status` stays `active` for a live current-boot
  binding, while the **already-implemented** Gateway normalization
  `services/gateway/app/session_containment.py::loss_from_evidence` derives the truthful terminal from the
  trace events (`session.cancelled` -> cancelled, `session.closed` -> closed, `session.result` -> completed,
  `session.failed` -> failed, fenced loss -> interrupted). The durable catalog status is not updated to match,
  so `GET`/list disagree with the event-terminal UI. The current authority is `ARCHITECTURE.md`, the Clean
  Break ADRs 001-006, and ADR-0093/0096/0100/0102 (ADR-0079/0083/0085 are **historical-only, superseded** by
  the Clean Break baseline and are NOT the current terminal-API basis). Left as a specific decision: reuse the
  existing `session_containment` projection (avoid a second lifecycle) and reconcile the durable catalog
  `status` (legal enum + scope) rather than a GET-only override. The UI end is proven by the banner + refused
  send, and the runtime rejects further input; not called a whole user-visible end PASS.

## Remaining gates (specific; not "project complete")
1. Tool-call count 16: **NOT_RUN** (no reliable ordinary MCP/native dispatch counter; the proxy proves only
   the model HTTP budget).
2. Identity-switch business reads: proven only by the **background continuation** #7/#9 (different new
   sessions), **not** by the ordinary same-native cross-root turns.
3. Public-projection clarification (`active` vs event-terminal end).
4. Multi-turn / restart / two-user / late-identity / sub-agent real acceptance: NOT_RUN (see the remaining
   matrix); ordinary **two consecutive turns are now real PASS**, so "multi-turn" is not blanket NOT_RUN.
5. Recovery operator close for a lost runner with no receipt (**Draft A**, ADR revision) — pending decision.
6. Dedicated judgment entry: **Draft B is an implementation/qualification plan for the Accepted ADR-0097/0098**,
   not a new ADR gap; `/acp-root/run` remains 503 until integrated.
7. Single-version default promotion (ADR-0103 gate) and exact-head CI / PR / merge / release / deploy: NOT_RUN.
