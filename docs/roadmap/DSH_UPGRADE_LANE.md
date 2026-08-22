# DSH Upgrade Lane

Status: **SCHEDULED — post-Phase 40 maintenance initiative**

This task establishes a repeatable, evidence-driven path for following
official DeepSeek Harness releases without coupling BYQ product contracts to
DSH internals. It is intentionally scheduled after the current product-depth
sequence. A critical DSH security advisory may trigger it earlier through a
dedicated maintenance worktree and ADR-0003 compatibility review.

## Research baseline (2026-08-22)

BYQ currently pins the Python SDK/runtime and the explicit npm runtime closure
to DSH `0.1.0-rc.6`. The Runtime Adapter launches the npm
`@deepseek-ai/dsh-sdk-jsonrpc-demo` closure; changing only the Python packages
does not change the runtime that serves Product Agent sessions.

Recent official releases provide these relevant changes:

- `0.1.0-rc.7`: long-session continuation after max-token truncation,
  large-history pagination stability, and durable MCP/ACP image attachments;
- `0.1.0-rc.8`: large-history/fork improvements, reliable subagent result
  delivery, multimodal support, and a broader Python bundled runtime closure;
- `0.1.1-rc.1`: a security fix for a Bubblewrap `/proc/<pid>/root` sandbox
  escape, plus vision-model support;
- `0.1.1-rc.2`: Files API image reuse and image preprocessing in the DeepSeek
  adapter.

The security fix, long-session stability, and subagent delivery are relevant
to BYQ. Upstream Web UI, Job Panel, shell/PTY, and PowerShell changes do not
justify widening Product DSH privileges. Multimodal features require a future
BYQ Product API and normalized WorkflowTrace decision before use.

The compatibility spike found that Python `0.1.1rc1` initializes and closes,
but an npm top-level `0.1.1-rc.1` set can resolve a mixed rc.1/rc.2 transitive
closure and fail peer dependency resolution. An exact npm `0.1.1-rc.2` closure
installs, while the official Python packages were still at `0.1.1rc1`. BYQ
must not adopt that mixed release set without compatibility evidence.

Official release evidence:

- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.0-rc.7>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.0-rc.8>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.1>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.2>

## Delivery objective

Turn ADR-0003's manual upgrade review into a reproducible compatibility lane
that can qualify routine DSH releases within one working day when no protocol,
persistence, or security boundary changes.

## Planned scope

1. Produce an exact BYQ/DSH compatibility matrix covering Python SDK,
   runtime-bin, npm closure, hashes, protocol behavior, and known limitations.
2. Add a candidate-version preparation command that downloads artifacts,
   verifies hashes/metadata, materializes a lockfile, and emits an SBOM/diff
   without modifying the accepted runtime pin.
3. Prefer one coherent runtime source. Evaluate whether the paired Python
   runtime executable can replace the duplicate npm closure while preserving
   the custom Cordis composition, MCP configuration, and lifecycle ownership.
4. Automate compatibility tests for initialization, MCP authorization,
   subagents, long-session resume/replay, normalized notifications, secret
   filtering, timeouts, cancellation, process reaping, and credential
   resolution.
5. Add an isolated upgrade worktree/Draft-PR workflow. Versions remain exact;
   no `latest`, caret, or automatic production adoption is allowed.
6. Define two policies: expedited qualification for security fixes and normal
   batching for feature releases. New DSH capabilities stay disabled until a
   BYQ contract or Accepted ADR explicitly adopts them.

## Acceptance criteria

- one command prepares a candidate and produces reviewable dependency evidence;
- the full DSH compatibility suite runs in local CI without a real model key;
- an optional credentialed smoke is documented and never stores a test secret;
- mixed npm/Python release sets fail closed unless explicitly accepted;
- Product API and WorkflowTrace contracts remain unchanged by a compatible
  runtime-only upgrade;
- ADR-0003 and the compatibility matrix identify the qualified production pin,
  rollback pin, limitations, and evidence location.

## Non-goals

- automatically merging runtime upgrades;
- following every DSH prerelease immediately;
- enabling shell, source-write, deployment, raw-event, or database access;
- adopting multimodal payloads without a BYQ-owned public contract;
- forking or patching DeepSeek Harness.
