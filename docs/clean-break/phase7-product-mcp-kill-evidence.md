# Phase 7 — independent Product MCP observation

Status: **bounded local PASS; overall Phase 7 OPEN**. This follows the earlier
[PID 1 evidence](phase7-live-compose-evidence.md), which used an MCP endpoint
inside the Adapter container and could not observe requests after its death.

## Boundary and test setup

- Source base: `ac9a8b9d` on `clean-break/runtime-simplification`. Test date:
  2026-09-27 (Asia/Shanghai). No push, merge or deployment occurred.
- Disposable Compose project: `byq-p7-mcp-400f8ac3a1`. Generated throwaway
  credentials and explicit configuration lived only under
  `/tmp/byq-p7-product-mcp-j4dyzcxs`; no existing database, user data or
  backup was connected. The resolved configuration used project-prefixed,
  non-external volumes/networks; Gateway had no published host port; Adapter
  restart policy was `no` in a private/default PID namespace.
- Services: Postgres, Backend, actual Product MCP, independent test-only MCP
  observer, Adapter with pinned `dsh-0.1.5rc1-post-u8.226`, and Gateway. The
  observer ran in a separate container and forwarded MCP requests and headers
  to the actual Product MCP. It stored only JSON-RPC method, tool name, HTTP
  status and MCP error flag; it stored no tokens, request payloads or results.
- The scripted provider first asked the real DSH root to call the read-only
  `byq_agent_roles` Product MCP tool, then requested a real foreground
  delegate and blocked the child's provider response. The model response was
  synthetic; the DSH runtime and Product MCP call were real.

## Result

The independent observer recorded exactly one successful `byq_agent_roles`
`tools/call` through Product MCP (`HTTP 200`, JSON-RPC `isError=false`) before
the Adapter's `BLOCKED_CHILD_LIVE` marker. `docker top` showed PID 1 and the
pinned DSH runtime process. The fail-able host check then SIGKILLed only this
project's Adapter while MCP, observer, Backend and Gateway stayed running.

```json
{"adapter_exit_code":137,"gateway_after_kill":503,"observer_after":4,"observer_before":4,"old_processes_gone":3,"project":"byq-p7-mcp-400f8ac3a1","quiet_seconds":3,"result":"PASS","role_successes":1,"tools_call_count":1}
```

The observer's total request and `tools/call` counts stayed unchanged for the
three-second post-kill window while the independent observer and Product MCP
remained alive. All three recorded Adapter/DSH host PIDs had disappeared;
Gateway Agent readiness returned 503. This is an observed boundary for the
qualified Compose PID-namespace topology, not an assertion of DSH process
continuity across restart or of external financial-action rollback.

An exploratory version attempted a child-side market tool call, but its
observer-success condition was not met and no live-child marker was accepted.
That run was **not** counted as PASS. The final bounded test uses the single
successful root read above, followed by the actual child-live marker.

The exact project was taken down with `--volumes --remove-orphans`; filtered
Docker checks found **zero** remaining project containers, volumes, networks
and unique images. The four project-tagged images and temporary credentials
directory were removed. Shared base images and unrelated resources remained.

## Reproduction and gate limit

The repository contains the test-only [Compose overlay](../../scripts/evidence/phase7-product-mcp.compose.yml),
[observer](../../services/runtime-adapter/tests/phase7_product_mcp_observer.py),
[child probe](../../services/runtime-adapter/tests/phase7_compose_child_probe.py),
and [fail-able host check](../../scripts/evidence/phase7-product-mcp-kill.py).
Use generated disposable credentials, project-prefixed non-external resources,
the base `compose.yml` + `compose.override.yml` + test overlay, and run only the
six services listed above. The host check requires explicit `--project`,
`--env-file` and `--override`; it kills only a labeled disposable Adapter and
must be followed by scoped Compose cleanup.

This closes the independent Product MCP post-death observation item in the
[Phase 7 authority contract](phase7-authority-cutover.md). **Phase 7 remains
OPEN** pending an active/unknown Product root across Gateway-only restart,
integrated exact terminal-close/lost-response retry, and deletion of the old
Adapter journal and Gateway lifecycle replay/delivery after their replacement
vertical path passes Tester, independent Sol Reviewer and Root acceptance.
