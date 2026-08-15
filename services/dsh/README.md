# Product DSH Runtime

Phase 5 uses a thin Node 24 image with the exact
`@deepseek-ai/dsh@0.1.0-rc.6` npm artifact, the `byq` profile, and the
`dsh-byq` bundle. The image selectively copies only that bundle. It does not
mount or contain the BeyondQuant source worktree, Git credentials, Codex
authentication, Docker socket, PostgreSQL access, Redis access, or source-edit
capability.

The container starts the verified rc.6 custom-profile command with the
official container-local default host. In rc.6, `web` is a root command alias
and cannot be passed as an application argument after `--profile byq`:

```text
dsh --profile byq --host 127.0.0.1 --port 3080
```

The Web/bootstrap surface is used only to start the diagnostic runtime, load
the profile, and verify MCP composition. It is not a product API and is not
published to a host port. The actual Product SDK path is the Runtime Adapter;
its composition owns the Phase 13 role skills, official in-process subagents,
and trusted BYQ MCP context. The diagnostic Web profile remains deliberately
free of product role state.

The Product preset roster is also bundle-owned: only `byq-product` is scanned,
it is the default, and the user preset root is disabled. The preset composition
contains no coding or filesystem mutation tools. The Product SDK composition
likewise contains no source mount, Git, database, or Engineering Plane
capability.
