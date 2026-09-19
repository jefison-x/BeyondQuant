# D15-1 — isolated 0.1.5-rc.1 candidate build / start / probe

Status: **candidate built, started and probed keylessly in isolation. No
qualification (D15-2..D15-G) pass is claimed; not production-wired.**

Target decision: [`../target-decision.v1.json`](../target-decision.v1.json)
(`dsh-v0.1.5-rc.1` / Python `0.1.5rc1` / bundled npm `0.1.5-rc.1`).

- Build identity: [`candidate-build.v1.json`](candidate-build.v1.json)
- Start/probe result: [`candidate-start-probe.v1.json`](candidate-start-probe.v1.json)

## Isolation boundary

- Image `byq-d15-1-0.1.5rc1-candidate:local`
  (`sha256:96bf63272b988c049656d20e2390e60e21711d2c498e8c9ccf8ccd2af849371f`)
  is built but never pushed and never referenced by `compose.yml`,
  `config/dsh/deployment.json` or the immutable `config/dsh/releases` registry.
- The probe runs with `--network none`; the synthetic BYQ MCP and the scripted
  SSE provider are loopback-only. No real model credential is used.
- `DSH_SESSION_ROOT=/var/lib/byq/dsh-sessions/dsh-0.1.5rc1` is a candidate-only
  path inside the image. No production volume is mounted; no DB/worker touched.
- Production default remains `dsh-0.1.2rc1`; rollback is `dsh-0.1.2rc1`.

## Result

| check | observed |
| --- | --- |
| bundled runtime version | `0.1.5-rc.1` |
| Python SDK / runtime-bin | `0.1.5rc1` / `0.1.5rc1` |
| keyless `create_session` | `ready` |
| scripted turn settle | `idle` |
| tool roster | 5 `byq_delegate_*` + `skill` + `web_search` + `mcp__byq__byq_agent_run_start` |
| shell/editor/filesystem/workflow/generic-agent tools | absent |
| notifications | `session.event`, `session.status` |
| event sequence | contiguous `3..22` |
| `tool/call` data keys | `arguments`, `callId`, `name`, `step`, `turn` |
| `tool/result` data keys | `message`, `step`, `turn` |
| BYQ profile patch load | succeeded (0.1.2 patch loaded against the 0.1.5 closure) |

`tool_event_schema` and `profile_schema` move out of `unknown-needs-probe` in the
compatibility ledger on this evidence. D15-2..D15-G still own migration, resume,
subagent/fork and persistent-terminal behavior.
