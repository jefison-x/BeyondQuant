# Personal Workspace Tenancy Plan

- Status: Phases 49-52 complete
- Decision: [ADR-0025](../architecture/adr/ADR-0025-personal-workspace-tenancy.md)
- Contract: [`personal-workspace.v1`](../contracts/personal-workspace.md)

## 结果

在不增加 team-product complexity 的前提下，将 BYQ 从 principal-keyed personal data 迁移到显式 personal workspace boundary。完成后，每个 durable user 都有一个 private workspace；每个已分类 domain asset 都由 trusted workspace context 授权；现有 Product journeys 在 restart、import/export、Agent actions 和 browser navigation 中保持可用、隔离。

每个 phase 使用独立 worktree、branch、PR，并停在自己的 acceptance gate。Pre-release ADR-0015 exception 下可启用 CI-green auto-merge；merge 后必须从最新 `main` 启动 services/frontend 于 `0.0.0.0:80` 供 maintainer 验证。

## 固定 scope 与非目标

包含：每用户自动 provision 一个 personal workspace；workspace membership/trusted request context；additive schema、deterministic backfill、quarantine/report、verification、contract migration/rollback evidence；Product、Backend、MCP、Agent orchestration、object references、bundles、lineage、approvals 和 idempotency 的 workspace authorization；Product shell 中有界 personal-workspace identity；two-user no-crossover/recovery evidence。

不包含：organizations、invitations、sharing、member administration、role editor；multiple workspace create/switch；billing、subscriptions、entitlements、quotas、commercial data products；canonical market data 的 tenant copies；PostgreSQL RLS/service-role redesign；修改 DSH generic runtime 或允许 DSH direct database access。

## Phase 49 — Boundary decision 与 migration classification（`COMPLETE`）

交付：接受 ADR-0025/`personal-workspace.v1`；将全部资源分类为 user/workspace/platform/Engineering；按强制 sequence 检查 Community tenancy evidence；固定 expand/backfill/verify/contract 顺序、ambiguous-row quarantine、compatibility window、rollback rules 和 future team seam。

Acceptance：不声称 runtime/schema behavior 已改变；区分 actor identity/authorization boundary；显式排除 team features/platform data；Phase 50 具有精确 prerequisites/fail-closed migration rules。

## Phase 50 — Workspace foundation 与 verified backfill（`COMPLETE`）

Scope：

- 通过 idempotent PostgreSQL bootstrap/migration pattern 添加 `workspaces`/`workspace_memberships`。
- 在一个 transaction 中为每个 durable user（含新用户）provision 恰好一个 personal workspace/owner membership。
- 为 workspace-resource roots 和必需 child/audit tables 添加 nullable workspace keys/indexes。
- 实现 idempotent owner→user→workspace backfill command，输出 versioned manifest、table counts、mismatch details、quarantine/report。
- 验证 parent-child workspace equality、references、uniqueness、restart idempotency；未验证 table 不强制 non-null。

Acceptance：重复 provisioning/backfill 不创建 duplicate，也不改变已验证 mapping；只填充精确 unique owner mappings，ambiguous/orphan/service identities 报告并保持 unassigned；backup/rollback drill 证明 additive changes 不破坏 Phase 48 Product path；API 暂不将 nullable `workspace_id` 当新 authorization。

Stop：resource 无可证明 owner、parent/child 解析为不同 workspaces，或 counts/references 与 manifest 不符时，不得 contract。

## Phase 51 — Trusted context 与 domain authorization cutover（`COMPLETE`）

Scope：durable session resolution 加 authoritative workspace/membership；Gateway 构造/传播 normalized trusted context 并剥离 browser identity/workspace headers；Backend/Product routes 按 `workspace_id` 授权，actor/creator 只用于 audit；context 经 Runtime Adapter/MCP 传播但不改 raw DSH schemas，不允许 model-selected scope；idempotency、lineage、approval、object retrieval、signal、backtest、paper trading、bundle 全部 workspace-aware；验证后强制 FK/non-null/uniqueness。

Acceptance：public headers/body 不能 impersonate workspace；两用户无法 list/get/mutate/approve/replay/import-over/dereference 对方 assets；platform admin 不自动访问他人 workspace；browser 仍只用 Gateway/Product API，DSH 无 database access，Agent domain calls 仍走 MCP；Phase 48 golden behavior 通过。

Stop：任何 root 仍只按 `owner_principal` 授权、child/reference 可跨 workspace，或 runtime/MCP 接受 model/client-selected scope 时停止。

Delivered：durable sessions 解析一个 active personal workspace；Gateway 忽略 browser identity/workspace headers，经 Runtime Adapter、Product DSH、MCP、Backend 传播 trusted context。Backend membership validation 在 domain selector 前强制执行。Database triggers 标记 root/child ownership 并拒绝 mismatch。Development migration 将 31 个 classified columns contract 为 `NOT NULL`，22 个 relationship checks 为零且无 quarantine。证据在 `docs/evidence/phase-51/`。

## Phase 52 — Product orientation、recovery 与 isolation closure（`COMPLETE`）

Scope：在 user shell/session bootstrap 暴露有界 current personal-workspace projection，不加 switcher/membership management；更新 asset export/import language/diagnostics 但不暴露 trust data；运行 fresh provisioning、legacy-compatible migration、backup/restore、restart、downgrade/forward-repair drills；扩展 no-mock journey 至两个 workspace，覆盖 conversation、pool、strategy、approval、signal、backtest、paper、models、preferences、bundle、admin settings；执行 Chrome desktop/mobile review 并记录 Community checklist/network evidence。

Acceptance：新用户自动获得一个可用 workspace；identity 在 logout/login、restart、backup/restore、bundle round-trip 后保持；cross-workspace API/browser 尝试 fail closed 且不泄漏 metadata；正常 personal workflows 完整；UI 明确 personal scope 但无 fake team affordance；最终报告列出 quarantined legacy rows，并确认无 compatibility read fallback 作为 authorization path。

Delivered：browser bootstrap 在 login/session restoration 暴露同一有界 workspace summary。Shell/bundle UI 标识 current scope，无 selector/member controls；bundle source identity 只作 evidence，durable session 仍是 destination authority。Two-workspace journey 覆盖全部 surface 并忽略 forged browser workspace header。Cross-workspace Paper-account 使用 metadata-safe not-found。Fresh provisioning、backup/restore、PostgreSQL restart 和 Phase 51 pre-contract repair 保持 identity、强制 31 tables、零 relationship failures/zero quarantine。证据在 `docs/evidence/phase-52/`。

## 后续 team extension

未来 Accepted ADR 可引入 team workspaces、multiple memberships、roles、invitations、active-workspace selector 和 commercial control-plane policy；必须保留 workspace-keyed domain assets，并单独评估 credential sharing、Agent policy precedence、market-data entitlements、audit impersonation 和 RLS。本计划不隐含任何这些决策。
