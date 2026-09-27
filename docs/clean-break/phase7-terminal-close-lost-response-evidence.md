# Phase 7 — normal terminal close after a lost Backend response

Status: **bounded live PASS; overall Phase 7 OPEN**.

## Scope and isolation

- Source base: `9161df03` on the isolated `clean-break/runtime-simplification` worktree. Test date: 2026-09-27 (Asia/Shanghai). No Product runtime code, schema, deployment, push, or merge changed.
- Disposable Compose project: `byq-p7-term-54ea99f722`, with six services: Postgres, Backend, Product MCP, pinned `dsh-0.1.5rc1-post-u8.226` Adapter, test-only Backend-close proxy, and Gateway. Gateway and proxy had no host port; all project volumes and networks were private and project-prefixed. Backend used only the new project-local `byq_domain` database. Generated credentials lived in mode-0600 files under `/tmp` during the run.
- The test-only Adapter PID 1 ran the normal application with a loopback scripted model provider. The provider called real Product MCP `byq_agent_run_start`, then waited for SIGUSR1 to emit a valid final completion. The host created a durable test user, conversation and turn through Gateway Product API; it did not create an Adapter session directly.

## Live result

Before releasing the provider, the disposable Backend held one active root and one fingerprint-bound active `quant_orchestrator` AgentRun under the current Adapter boot. There were exactly two authenticated model requests. SIGUSR1 released the provider, and real DSH produced a `completed` terminal event. Gateway fetched exact Adapter evidence and sent the root close to Backend through the private test proxy.

The proxy forwarded the **first** exact close to Backend and received its 200 receipt after Backend committed. It then closed the Gateway-side connection without sending a status line or response bytes. Before host release, identical close retries received a test-only 503 without being forwarded. The host verified the Backend root and AgentRun were already `completed/closed`, with terminal sequence and SHA-256 matching the captured first receipt; Adapter terminal evidence matched it; the Adapter journal had no terminal ACK; Gateway delivery still had one pending event; and a same-session Adapter prompt returned 409 for pending domain cleanup without adding a model request.

After the host armed only that root in the proxy, the next byte-identical close reached Backend. Backend returned the **same** receipt. Gateway then acknowledged it to Adapter; the durable journal contained that exact ACK, Gateway delivery became `up_to_date` with no pending/exhausted/rejected events, and the root and AgentRun rows stayed unchanged. The proxy observed three Gateway close requests: one Backend-forwarded close with a genuinely lost 200 response, one test-gated 503, and one Backend-forwarded idempotent retry. Only two requests reached Backend. Provider request count stayed at two.

The row below preserves the live observation with corrected counter labels. The
first runner version printed `backend_close_requests=3` for all Gateway-to-proxy
attempts; static review identified the mislabel after the live run. The checked-in
runner now reports `gateway_close_requests=3` and derives
`backend_forwarded_close_requests=2` from the proxy's two forward counters.
Docker was not rerun for this output-only correction.

```json
{"adapter_terminal_ack_exact":true,"backend_forwarded_close_requests":2,"gateway_close_requests":3,"backend_retry_receipt_exact":true,"conversation_id":"conversation_cebc2bb25b904323b6daf5c4a8ee87c0","pending_prompt_status":409,"project":"byq-p7-term-54ea99f722","provider_requests":2,"result":"PASS","root_id":"4f8d624962b04027a3324afdd509b280","terminal_event_sha256":"5098aadb1bcab099aa40b8832eb04cf5cd25d337f66d750e46bc3cf8c78c6f20","terminal_outcome":"completed","terminal_sequence":10}
```

The exact project was taken down with `--volumes --remove-orphans`; its four project-tagged BYQ images and the temporary credential directory were removed. Filtered Docker checks found **zero** remaining project containers, volumes, networks and images. No existing database, user data or backup was touched.

## Reproduction and limit

The checked-in [Compose overlay](../../scripts/evidence/phase7-terminal-close.compose.yml), [Adapter provider fixture](../../services/runtime-adapter/tests/phase7_compose_terminal_probe.py), [close proxy](../../services/runtime-adapter/tests/phase7_backend_close_proxy.py), and [fail-able host check](../../scripts/evidence/phase7-terminal-close-lost-response.py) require newly generated disposable credentials and a project matching `byq-p7-term-<10 hex>`. The host check preflights the resolved Compose project, private ports, local database, locked DSH build, private PID topology, and scoped resources before touching a container.

This proves normal `completed` terminal closure and exact lost-response retry in the qualified Product API → Gateway → Adapter → Backend topology. It does not prove `outcome_unknown` behavior, remote DSH process reattachment, or every terminal outcome. Phase 7 remains open for its remaining deletion and final gate; Phase 8 remains closed.
