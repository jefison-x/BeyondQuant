# Preserved keyless runner probe

These are the executed probe scripts and sanitized readback from
`/tmp/byq-acp-product-slot-probe-final-20261005`. The exact image IDs are in
`image-identity.txt`. No environment/credential files were copied.

`run_probe.py` ran one disposable PID1 runner and one UID/GID10002 client in
separate PID namespaces, both with network disabled and read-only rootfs.
The client had control GID10006 and the shared Workspace volume. A synthetic
localhost MCP responder ran as a trusted test process inside the runner.
The runner and client used their baked source; only the probe scripts and
synthetic MCP fixture were mounted read-only. The client did not send a prompt.

`client-probe.stdout` proves private home/tmp creation, official ACP initialize,
session/new, session/close and authenticated EXIT cleanup=proven. Inspect
records the configured container boundary; stop/remove outputs record exact
cleanup. Empty stderr/log files are intentionally preserved.

For an optional reproduction, prepare the hard-coded temporary directory and
its `control`, `state`, `workspace` subdirectories; put the three scripts there.
Generate a fresh synthetic URL-safe base64 control secret of at least 32 bytes.
Use it as `BYQ_ACP_PRODUCT_RUNNER_CONTROL_SECRET` in `runner.env`, together
with `BYQ_ACP_PRODUCT_WORKSPACE_ID=workspace_probe`. In `client.env`, set
`BYQ_ACP_PRODUCT_SLOT_PROBE_SECRET` to the same synthetic value, and set
`BYQ_ACP_PRODUCT_SLOT_BINDINGS` to a JSON object mapping `workspace_probe` to
`socket_path=/run/byq-acp-product-runner/control.sock` and
`control_secret_env=BYQ_ACP_PRODUCT_SLOT_PROBE_SECRET`. Protect the env files
with mode0600. Inspect names and exact image IDs before running; do not borrow
live configuration or provider credentials. The script retains a failed
runner for inspection and only stops/removes its successfully created probe
runner. No automatic rerun is needed for the current preserved evidence.

This is framework/transport evidence. It does not prove BYQ Backend terminal
ACK, Product API, browser behavior, native route selection, model calls,
delegated tools, cancellation recovery, or default ACP qualification.
