#!/bin/sh
# BYQ ACP single-image role dispatcher (candidate).
#
# One image can serve the three ACP container roles. The role is selected ONLY
# by the explicit BYQ_ACP_ROLE startup parameter and is fail-closed: any unset
# or unknown value refuses to start. Every role keeps its own PID 1 contract,
# interpreter, and process entrypoint; this dispatcher never merges the roles.
#
#   adapter   trusted Runtime Adapter (FastAPI/uvicorn), runs as the byq user
#   product   ordinary ACP process owner (acp_product_runner/server.py), root PID 1
#   judgment  isolated ACP judgment process owner (acp_judgment_runner/server.py), root PID 1
#
# Exit codes: 64 = bad/unknown role, 77 = adapter identity guard refused.
set -eu

role="${BYQ_ACP_ROLE:-}"
case "$role" in
  adapter)
    # Fail-closed identity guard. `id -u`/`id -g` report the EFFECTIVE uid/gid
    # (GNU coreutils and busybox both default to effective; `-r` would be real).
    # The entrypoint is PID 1 with no setuid transition, so this refuses to start
    # uvicorn whenever a misconfigured Compose service launches the adapter as
    # root (or any identity other than the unprivileged byq 10002:10002).
    adapter_uid="$(id -u)"
    adapter_gid="$(id -g)"
    if [ "$adapter_uid" != "10002" ] || [ "$adapter_gid" != "10002" ]; then
      echo "adapter role must run as byq (effective uid/gid 10002:10002), got ${adapter_uid}:${adapter_gid}" >&2
      exit 77
    fi
    cd /app
    exec /opt/byq-venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8400
    ;;
  product)
    exec /usr/bin/python3 /opt/byq/acp_product_runner/server.py
    ;;
  judgment)
    exec /usr/bin/python3 /opt/byq/acp_judgment_runner/server.py
    ;;
  *)
    echo "BYQ_ACP_ROLE must be one of: adapter product judgment (got '${role}')" >&2
    exit 64
    ;;
esac
