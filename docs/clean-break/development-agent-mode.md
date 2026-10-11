# Clean Break development agent mode (Phase 0)

Status: active on `clean-break/runtime-simplification` under ADR-0088. It does not grant Product DSH Engineering privileges.

## Inventory and merge decision

The repository had `AGENTS.md`, `ARCHITECTURE.md`, `docs/DEVELOPMENT_WORKFLOW.md`, CI policy, and product-side `plugins/dsh-byq/skills`, but no tracked `.codex/` or `.agents/` project configuration. Machine-local Codex settings had Sol/medium, on-request approval and Engineering MCP servers `chrome-devtools` and `openaiDeveloperDocs`. The session uses workspace-write with managed approval, restricted network and a repository write root; an external engineering worktree therefore needs an authorized write path. Local secrets and MCP credentials stay outside Git. Product MCP remains the sole Agent-to-Domain boundary; Engineering MCP is never added to Product Compose or DSH configuration.

Reference studied: [GPT6-SolMedium-LunaMax profile](https://github.com/donvito/codex-astra-luna-orchestrator/tree/main/profiles/GPT6-SolMedium-LunaMax), especially its [config](https://github.com/donvito/codex-astra-luna-orchestrator/blob/main/profiles/GPT6-SolMedium-LunaMax/codex/config.toml). BYQ adapts the role split, not the upstream installer, broad instructions, MCP settings, or permissions. [OpenAI Codex configuration](https://developers.openai.com/codex/config-reference) documents trusted project configuration and role files. Local `codex-cli` at inventory time: 0.157.0.

## Roles and routing

| Role | Model / effort | Work | Output |
|---|---|---|---|
| Root | `gpt-6-sol` / `medium` | Architecture owner; scope, risks, boundaries, phase acceptance | Explicit PASS/FAIL and next gate |
| Explorer | OpenCode service | Read-only bounded code/ownership investigation | Findings, evidence, paths, duplication, risks |
| Worker | OpenCode service | One assigned subsystem and writer | Diff, tests, risks |
| Researcher | OpenCode service | Necessary DSH/API/dependency facts | Primary sources, versions, implications |
| Tester | OpenCode service | Focused test execution | PASS/FAIL, commands, failures |
| Reviewer | `gpt-6-sol` / `medium` | Independently inspect actual diff, interfaces, schema and tests | Functional, Tests, Architecture PASS/FAIL |

Engineering tasks use native `opencode serve` plus `opencode run --attach`
with an explicit `--dir` and `--session`. Reuse the same session for the same
task, and separate unrelated tasks. Luna is a fallback on explicit user request
or after an explained OpenCode failure. See the default in [AGENTS.md](../../AGENTS.md).
The local service is managed with `systemctl --user start byq-opencode.service`;
credentials remain in the private user environment file, outside Git.

The configured ceiling is four *subagents* (Root is separate). Normal use is one or two agents; independent read-only investigations can fill the ceiling. This particular hosted session exposes only four total concurrency slots, so it can run Root plus three subagents. A small task stays with Root. One subsystem has one writer, and concurrent writers must have nonoverlapping ownership or isolated worktrees. Reviewer must not rely on Worker summaries. Root issues the final phase acceptance.

Every delegation states files/subsystem, task, forbidden interfaces, acceptance criteria and tests. Every phase follows investigation or implementation → Tester → independent Sol Reviewer → Root PASS. The reviewer checks security, correctness, regressions and Clean Break violations: duplicate owner, thick adapter, compatibility shim, DSH capability duplication, event as state, Agent-owned long compute, Job/Artifact bypass, old migration burden and development tooling in product code.

Keep current BYQ worktree, security, test, CI and human merge rules. The user-requested Clean Break is a scoped architecture program; superseding old product ADRs requires a new accepted architecture decision before destructive implementation. Do not mechanically install the external profile or copy product DSH skills into Codex. Project TOML is a default for future trusted sessions; an already running hosted session or explicit launch override may take precedence. Role routing must be verified in a fresh trusted Codex session before claiming end-to-end configuration activation.

## Validation

- Parse every project TOML; assert root/role models, effort and four-subagent ceiling.
- Verify `scripts/ci/verify-worktree.py` and `git diff --check`.
- In a fresh trusted session, dispatch bounded Explorer, Worker, Tester and Reviewer probes and inspect actual model/effort and permissions. An agent's instruction to be read-only is behavioral guidance, not a filesystem security boundary.
