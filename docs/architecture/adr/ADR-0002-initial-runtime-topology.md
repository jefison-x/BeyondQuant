# ADR-0002: Initial Runnable Service Topology

## Status

Accepted for Phase 5.

## Context

Phase 5 establishes the smallest runnable physical spine for BeyondQuant. It is
an architecture bootstrap, not a migration of product or legacy business
features. The spine must prove service reachability and the Agent Plane to
Quant Domain Plane MCP boundary while keeping Product and Engineering Plane
privileges separate.

## Decision

Phase 5 establishes this initial physical runtime topology:

```text
gateway        (independent service skeleton)

dsh runtime
  ↓ outbound MCP Streamable HTTP
beyondquant-mcp
  ↓ HTTP
byq-backend
```

The runnable services are `gateway`, `dsh`, `mcp`, and `backend`.

The following are intentionally not implemented in Phase 5:

- frontend
- PostgreSQL
- Redis
- backtest-worker
- data-worker
- engineering-dsh

Directories for these components may be reserved only where a meaningful
ownership README is useful. No placeholder implementation is created merely
to make the repository look complete.

Initial technical choices:

| Component | Choice |
| --- | --- |
| Gateway | Python + FastAPI |
| Backend | Python + FastAPI |
| MCP | Node.js / TypeScript with the current official MCP TypeScript SDK |
| DSH runtime | Node.js 24 + `@deepseek-ai/dsh@0.1.0-rc.6` |
| dsh-byq | DSH configuration bundle/plugin |

The Gateway exposes only its own health and bootstrap readiness. It does not
probe, depend on, or expose a DSH Web URL. Gateway-to-DSH application-facing
transport is not implemented and is not defined in this ADR.

The `dsh` service depends on healthy `mcp`; `mcp` depends on healthy
`backend`. Gateway starts independently because its runtime integration with
DSH is deliberately deferred.

## DSH Runtime Baseline

The Phase 5 deployment baseline is the exact npm artifact:

```text
@deepseek-ai/dsh@0.1.0-rc.6
```

The package source is the official npm package published from:

```text
https://github.com/deepseek-ai/deepseek-harness
```

The npm metadata identifies the `apps/cli` package. The published artifact
reported version `0.1.0-rc.6` and integrity
`sha512-brpZfED7ieRa2PQ5tUxMhHrM1pb2CmKFVM/f6yMULBDMicahk+Z2OsHgTwTDnoiZm23Ftu9rQz0NN4pflaoJcg==`.
The registry did not provide `gitHead` or `engines` for this artifact; those
fields are therefore recorded as unavailable rather than inferred.

The related MCP client is installed by the dsh-byq bundle as the exact
dependency `@deepseek-ai/dsh-mcp-client@0.1.0-rc.6`. Its official package
metadata points to `packages/mcp/mcp-client` in the same upstream repository.

The official GitHub `master` package metadata and a published npm artifact may
temporarily differ during Developer Preview publication. BYQ deployment uses
the verified and locked npm artifact, never `latest`, `^`, `~`, or an
unreviewed follow of `master`.

## DSH Web Trust Boundary

DeepSeek Harness `0.1.0-rc.6` intentionally rejects binding the Web
application to `0.0.0.0` because the Web/API surface includes capabilities that
must not be network-exposed without an appropriate application trust boundary.

BeyondQuant therefore SHALL NOT use DSH Web as its Gateway-to-Runtime
production interface. Phase 5 uses DSH Web bound only to container-local
`127.0.0.1` as a bootstrap and runtime verification surface. The DSH
container publishes no host port, and no proxy, redirect, host network, or
other security bypass is permitted.

## Consequences

- BYQ has independently runnable Gateway, Backend, and MCP service skeletons
  before domain feature implementation.
- DSH remains a thin runtime and receives no BeyondQuant source mount, Docker
  socket, Git credentials, or Codex authentication.
- `byq_health` is the first MCP contract and proves MCP-to-Backend routing.
- DSH verifies the outbound DSH-to-MCP boundary without making its Web surface
  a product API.
- The DSH baseline is upgradeable only after a compatibility gate and contract
  test pass.
- PostgreSQL, Redis, strategy, factor, backtest, Tushare, user, and agent
  session behavior remain out of scope.

## Alternatives considered

- Keeping `0.1.0-rc.5`: rejected because the requested npm artifact is no
  longer installable.
- Using `latest` or a semver range: rejected because DSH is a fast-moving
  preview dependency and exact pinning is an architecture requirement.
- Reimplementing the MCP protocol or forking DSH: rejected by the repository
  architecture rules.

## Rollback and follow-up

Rollback is a branch/release rollback to the prior repository revision. A DSH
upgrade requires a new compatibility validation and an explicit dependency
change. Gateway-to-DSH application-facing transport remains undecided and is
deferred to Phase 6. Phase 6 must establish a new ADR before introducing a
session, chat, or runtime adapter.
