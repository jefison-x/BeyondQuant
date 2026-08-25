# BeyondQuant / DeepSeek Harness compatibility matrix

Qualification date: 2026-08-25

## Version decision

| Surface | Highest official release observed | BYQ decision | Reason |
| --- | --- | --- | --- |
| GitHub Releases | `dsh-v0.1.1-rc.2` | Not qualified | No matching official Python SDK/runtime-bin |
| PyPI SDK | `0.1.1rc1` | Qualified | Exact dependency on runtime-bin `0.1.1rc1` |
| PyPI runtime-bin | `0.1.1rc1` | Qualified | Same Python prerelease as SDK |
| npm BYQ runtime closure | `0.1.1-rc.2` published | `0.1.1-rc.1` qualified | Matches Python; full exact closure resolves without mixed prereleases |
| Rollback | `0.1.0rc6` / `0.1.0-rc.6` | Retained | Prior qualified BYQ stack and lockfile |

Official release evidence:

- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.1>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.2>
- <https://pypi.org/project/deepseek-harness-sdk/0.1.1rc1/>
- <https://pypi.org/project/deepseek-harness-runtime-bin/0.1.1rc1/>

## Artifact and closure evidence

| Artifact | Qualified version | Integrity |
| --- | --- | --- |
| `deepseek-harness-sdk` universal wheel | `0.1.1rc1` | SHA-256 `2113aec229039da435bc44b275b487216d2b1c308d850521b88cea6ce3c1b762` |
| runtime-bin Linux x86_64 wheel | `0.1.1rc1` | SHA-256 `8eb31e3ab2bc3ff45474fe419eb389e32553391f1a40789ea2cc3dc8d6de137b` |
| runtime-bin Linux arm64 wheel | `0.1.1rc1` | SHA-256 `e73987c6c08d8322bce2b8b2ce75db6a139ecf546417b6015ce7a8de5e5f19b5` |
| runtime-bin macOS arm64 wheel | `0.1.1rc1` | SHA-256 `2707cd666ba49ee0963228873abf7850ca7ec5e782cca61e3603793bace0d1cf` |
| JSON-RPC carrier | `0.1.1-rc.1` | SHA-512 `CTWwd1g5/AKkNvuSu1lVdbfenhvR9UhuELQm7uhYhRGI3d3tnCnOReky0rbc7VW6tzvllMl8ShA2V5tOMQunEQ==` |
| JSON-RPC server | `0.1.1-rc.1` | SHA-512 `C1fHyeVJ4Zc3yJ7mxQfFSO7B2FXcDOTMxkmd2NjC8haSO8j8wOLFf8W58f0fKVbf/bcPhYqbImIjBfNfSPLF3w==` |
| MCP client | `0.1.1-rc.1` | SHA-512 `GXifDFUgiWcm3dr2Cbnpi9mbQgzP3GtIpGSX+7RlXlCHIHuavXCdgvGHSbq/KGPM5vAwrkZS+xcLwTSqpQL47A==` |

The other official `@deepseek-ai/*` closure packages were rechecked against
npm and exact-pinned at their current stable versions: `cordis@4.0.1`,
`cordis-plugin-group@1.0.1`, `cordis-plugin-include@1.0.6`,
`cordis-plugin-loader@1.0.2`, `cordis-plugin-timer@1.1.3`,
`cosmokit@1.8.2`, and `schemastery@3.18.1`.

The checked-in npm manifest lists every package in the DSH closure as an exact
direct pin. The clean lock contains 61 `@deepseek-ai/*` packages: 54
`@deepseek-ai/dsh-*` packages all at `0.1.1-rc.1` plus the seven stable support
packages above. The manifest and lock package sets are equal. The clean install
and `npm audit --audit-level=high` reported zero vulnerabilities. No BYQ
top-level DSH pin uses `latest`, caret, or tilde, and no override, force, or
legacy peer resolution is used. Upstream-declared ranges remain visible as
metadata in the lockfile, but every resolved DSH node is constrained by the
matching exact BYQ direct pin.

A partial rc.1 manifest was deliberately tested and rejected: npm selected
`@deepseek-ai/dsh-tools@0.1.1-rc.2`, which requires rc.2 peers and produces
`ERESOLVE`. This is the fail-closed evidence for full closure pinning.

## Compatibility qualification

| Contract / behavior | Evidence | Result |
| --- | --- | --- |
| Python SDK API | `DeepSeekHarnessConfig`, `start`, `start_session`, `close`, notification/request APIs inspected in built image | PASS |
| JSON-RPC carrier | public `dsh-jsonrpc-agent/lib/bin.js`, keyless initialize and shutdown | PASS |
| custom BYQ Cordis | unchanged composition initializes with coding flags disabled | PASS |
| `dsh-mcp-client` | startup uses authenticated Streamable HTTP and `failOnStartupError: true` | PASS |
| BeyondQuant MCP | MCP contract/auth tests plus real runtime startup | PASS |
| session lifecycle | create, duplicate conflict, prompt ownership, release | PASS |
| persistence/resume | same contained session root, hard-cancel replacement runtime, durable volume restart | PASS |
| subagent delivery | rc.1 SDK session-tree filter and lifecycle ancestry contract; BYQ subagent plugins initialize | PASS (keyless contract) |
| WorkflowTrace normalization | normalized allowlist, secret/raw-event denial, ordering tests | PASS |
| cancellation | retained soft-settle and hard process-close policies; no fabricated DSH cancel | PASS |
| process cleanup | SDK close plus child-process reap smoke | PASS |
| full vertical path | Gateway -> Runtime Adapter -> DSH -> BeyondQuant MCP | PASS |

The subagent delivery result is a keyless protocol/composition qualification.
A live delegated model turn remains optional credentialed smoke and no provider
secret is stored in tests or evidence.

## Security and capability decision

The qualified stack includes upstream's Bubblewrap `/proc/<pid>/root` escape
fix, max-token continuation fix, large-history stability improvements, and
subagent report-delivery fix. BYQ treats the sandbox fix as defense in depth.
The full pins constrain packages already present in the rc.6 transitive
runtime tree; listing a package for resolution does not load it into Cordis.
Product DSH still has no shell, terminal, filesystem mutation, source mount,
Git mutation, database, Redis, or Engineering capability.

Vision, image reuse, broader bundled presets, shell/PTY, filesystem, Web UI,
and other new upstream capabilities are not enabled. They remain future
capabilities until a BYQ public contract and, where required, an Accepted ADR
adopts them.

## Known limitations and rollback

- DSH still exposes no qualified prompt-cancel or per-session close operation;
  BYQ retains soft settle and adapter-owned hard process close.
- `0.1.1-rc.2` remains unqualified until official matching Python artifacts
  exist and the entire stack passes this lane.
- The separately profiled Phase 5 DSH Web diagnostic image remains the exact
  rc.6 bootstrap/rollback baseline and is not a Product request path.
- A real model-keyed subagent turn is optional and was not required for keyless
  CI; provider credentials are never committed.

Rollback restores the prior rc.6 Python pins, npm manifest, lockfile, version
reporting, and image from repository history. Stop/release owned processes
before deployment; preserve the Agent Plane JSONL session volume and start a
new runtime session if cross-version resume cannot be proven. No BYQ business
database rollback or migration is involved.
