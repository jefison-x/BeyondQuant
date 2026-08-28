# DSH Upgrade Lane

Status: **QUALIFIED — `0.1.1rc1` / `0.1.1-rc.1` maintenance upgrade**

本任务建立可重复、证据驱动的路径，以跟踪 official DeepSeek Harness releases，同时不把 BYQ product contracts 耦合到 DSH internals。它有意安排在当前 product-depth sequence 之后；重大 DSH security advisory 可通过独立 maintenance worktree 和 ADR-0003 compatibility review 提前触发。

## Qualified stack（2026-08-25）

本 lane 认证的 Product Runtime：

- Python `deepseek-harness-sdk==0.1.1rc1`；
- Python `deepseek-harness-runtime-bin==0.1.1rc1`；
- BYQ JSON-RPC runtime closure 中全部 71 个 `@deepseek-ai/dsh-*` packages 精确固定为 npm `0.1.1-rc.1`；Phase 63 candidate package 仍由 Registry 决定是否加载；
- 七个 supporting `@deepseek-ai/*` Cordis packages 精确固定为当前 official stable versions；
- public `@deepseek-ai/dsh-sdk-jsonrpc-demo` `lib/bin.js` carrier；
- 不变的 BYQ Cordis composition、JSONL persistence，以及作为唯一 Agent-to-Domain path 的 `@deepseek-ai/dsh-mcp-client`。

GitHub/npm `0.1.1-rc.2` 更新，但没有匹配 Python SDK/runtime-bin release，因此拒绝。普通 top-level npm rc.1 install 也 fail closed，因为 upstream caret peer ranges 会选择 rc.2 transitive packages。BYQ 将完整 DSH closure 列为 exact direct pins，阻止混合 prerelease tree；Phase 63 后 clean npm resolution 包含 78 个 `@deepseek-ai/*` packages，其中 71 个 DSH packages 只有 `0.1.1-rc.1`，且不使用 overrides、`--force` 或 `--legacy-peer-deps`。package presence 不等于 Product enabled。

证据与 compatibility results 记录在 [`dsh-compatibility-matrix.md`](../architecture/research/dsh-compatibility-matrix.md)。未来 candidate 在不改变 qualified pin 的情况下运行：

```bash
python3 scripts/dsh/prepare_candidate.py \
  --python-version 0.1.1rc1 \
  --npm-version 0.1.1-rc.1 \
  --output /tmp/byq-dsh-candidate-0.1.1rc1
```

命令下载 platform SDK/runtime wheels、验证 PyPI SHA-256 metadata、创建并验证 clean npm lock、运行 `npm ci`/high-level audit，并输出 CycloneDX SBOM 和 dependency report。它拒绝混合 Python/npm prereleases 和已存在 output directories。

## Rollback baseline（2026-08-22）

BYQ 之前将 Python SDK/runtime 和显式 npm runtime closure 固定为 DSH `0.1.0-rc.6`。Runtime Adapter 启动 npm `@deepseek-ai/dsh-sdk-jsonrpc-demo` closure；只改 Python packages 不会改变为 Product Agent sessions 服务的 runtime。

相关官方变化：

- `0.1.0-rc.7`：max-token truncation 后继续长 session、large-history pagination 稳定性、durable MCP/ACP image attachments；
- `0.1.0-rc.8`：large-history/fork 改进、可靠 subagent result delivery、multimodal support、更广 Python bundled runtime closure；
- `0.1.1-rc.1`：修复 Bubblewrap `/proc/<pid>/root` sandbox escape，并支持 vision model；
- `0.1.1-rc.2`：DeepSeek adapter 的 Files API image reuse/image preprocessing。

Security fix、long-session stability 和 subagent delivery 与 BYQ 相关。Upstream Web UI、Job Panel、shell/PTY、PowerShell 变化不足以扩大 Product DSH privileges。Multimodal features 使用前需要未来 BYQ Product API 和 normalized WorkflowTrace 决策。

Compatibility spike 发现 Python `0.1.1rc1` 可 initialize/close，但 npm top-level `0.1.1-rc.1` 可能解析出混合 rc.1/rc.2 closure 并导致 peer dependency failure。Exact npm `0.1.1-rc.2` closure 可安装，但 official Python packages 仍是 `0.1.1rc1`。无 compatibility evidence 时 BYQ 不得采用该混合 release set。Official release evidence 保留原链接：

- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.0-rc.7>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.0-rc.8>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.1>
- <https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.1.1-rc.2>

## 交付目标与范围

将 ADR-0003 的人工 upgrade review 转为可复现 compatibility lane，使无 protocol、persistence 或 security boundary 变化的常规 DSH release 能在一个工作日内认证。已交付：

1. 精确 BYQ/DSH compatibility matrix，覆盖 Python SDK、runtime-bin、npm closure、hashes、protocol behavior 和 known limitations。
2. Candidate preparation command：下载 artifacts、验证 hashes/metadata、生成 lockfile 和 SBOM/diff，不修改 accepted runtime pin。
3. 保留显式 npm runtime，因为 BYQ custom Cordis composition 需要 MCP client 和有界 Product capability roster；bundled Python runtime 是精确配对 dependency，不是 selected carrier。
4. 自动化 compatibility tests，覆盖 initialization、MCP authorization、subagents、long-session resume/replay、normalized notifications、secret filtering、timeouts、cancellation、process reaping 和 credential resolution。
5. 使用 isolated upgrade worktree/Draft-PR workflow；versions 保持 exact，不允许 `latest`、caret 或 automatic production adoption。
6. 保留两项 policy：security fixes expedited qualification；feature releases normal batching。新 DSH capabilities 保持 disabled，直到 BYQ contract/Accepted ADR 显式采用。

## Acceptance criteria

- 一个命令生成可审查 candidate dependency evidence；
- 完整 DSH compatibility suite 可在无真实 model key 的 local CI 运行；
- 可选 credentialed smoke 有文档且不存储 test secret；
- 混合 npm/Python release sets fail closed，除非显式接受；
- Compatible runtime-only upgrade 不改变 Product API/WorkflowTrace contracts；
- ADR-0003/compatibility matrix 标识 qualified production pin、rollback pin、limitations 和 evidence location。

## 非目标

- 自动 merge runtime upgrades；
- 立即跟随每个 DSH prerelease；
- 启用 shell、source-write、deployment、raw-event 或 database access；
- 在无 BYQ-owned public contract 时采用 multimodal payloads；
- fork 或 patch DeepSeek Harness。
