# ADR-0025：Personal Workspace Tenancy Boundary

- Status: Accepted
- Date: 2026-08-24
- Accepted: 2026-08-24
- Decision scope: personal workspace identity、resource ownership、trusted request context、
  compatibility migration 与 future team extension
- Related: ADR-0003、ADR-0012、ADR-0014、ADR-0016、ADR-0018、ADR-0019、ADR-0024

## 背景

BeyondQuant 当时已有 durable user 和 exact-owner isolation。Product resource 主要按从
authenticated user 派生的 `owner_principal` authorization。对于当时 two-user Product
journey 这很安全，但混淆了 user account、持有 research asset 的 container 和创建/修改
asset 的 actor 三个概念。未来 Cloud/team deployment 会因此需要大规模 rekey
conversation、Strategy、Backtest、Approval 和 Paper account。

维护者选择 personal-workspace-first product，而不是 team edition。即时需求是每个
durable user 自动 provision 一个 private workspace，不包含 invitation、sharing、
organization administration、billing、quota 或 workspace switcher；但 storage/request
Contract 必须避免未来 ADR 引入 team workspace 时再次进行 ownership migration。

Read-only BeyondQuant-Community repository 提供有用 planning evidence：commercial
feature 前先建立 personal boundary；绝不信任 client/model 声明的 tenant；public market
data 不复制进 user asset；迁移 ownership 时不静默分配 unverifiable row。它没有兼容
当前 BYQ 架构的 implemented tenant system；旧 runtime、ORM、API、Cloud topology 只作
reference 或被替换。

## 决策

1. `workspace` 是 BYQ 当前 tenancy/authorization boundary。每个 durable user 恰有一个
   kind 为 `personal` 的 workspace，user 是唯一 `owner` membership。Initial Product 不
   暴露 workspace create、invitation、sharing、switching 或 team role。
2. PostgreSQL 持有 `workspaces` 和 `workspace_memberships`。Workspace/membership ID 是
   stable opaque ID。Personal workspace 恰有一个 owner membership，且不能通过 Phase
   49-52 Product API transfer/delete。
3. Workspace-owned domain row 在 expand/backfill/verify/contract migration 后获得 non-null
   `workspace_id`。本计划期间 `owner_principal` 继续作为 immutable creator/historical
   audit identity；cutover 后不再是最终 authorization key。
4. User account data 保持 user-scoped：profile、appearance、authentication session、
   encrypted personal model credential/profile/binding 和 personal Agent Policy。相关 action
   可操作 workspace resource，但 membership 不转移 account secret/personal preference。
5. Canonical market data、calendar、provider ingestion state、system Operations、monitoring
   policy、deployment configuration 和 platform audit 保持 platform-scoped。从 workspace
   引用 platform data 不会复制或使其可 export。
6. Gateway 从 authenticated durable user 派生 active personal workspace，strip/ignore
   Browser-supplied workspace/owner identity header，并在 private service call 传播
   normalized trusted context。Backend 对 user/membership validation 具有权威；workspace
   或 membership absent、disabled、mismatched、ambiguous 时 fail closed。
7. Runtime Adapter、DSH-facing orchestration 和 BeyondQuant MCP 只接收 service-derived
   workspace/actor context。Model、tool argument、WorkflowTrace card、imported bundle 或
   Browser body 不能选择 workspace。DSH 不访问 PostgreSQL；所有 Agent-to-Domain call
   继续经过 BeyondQuant MCP。
8. Browser 继续只调用 same-origin Gateway/Product API。Raw DSH event/internal workspace
   header 不成为 Frontend Contract。Product 可为 orientation 暴露有界 personal-workspace
   summary；只有一个 valid workspace 时不要求 selector。
9. 本计划期间 authorization 在 repository/service Contract 中明确执行。PostgreSQL RLS
   可能作为后续 defense-in-depth layer，但不能替代 Product API、Backend、MCP 和 cross-
   resource authorization test，也不属于 Phase 49-52。
10. Future Accepted ADR 可增加 workspace kind/membership role，或在 workspace 上增加
    organization。Existing domain row 继续以 `workspace_id` 为 key，因此扩展只增加
    membership/active-workspace selection，无需重新分配全部 asset。

Normative context shape/resource classification 记录在
[`personal-workspace.v1`](../../contracts/personal-workspace.md)。

## Security 与 domain invariant

- Authenticated user 是 actor；workspace 是 resource boundary。
- Platform administrator status 不隐含授予另一个 user workspace 的 membership 或普通
  Product access。
- Workspace-owned parent/child record 必须具有相同 `workspace_id`。
- Workspace resource 的 idempotency/uniqueness key 包含 workspace boundary。
- Cross-workspace lookup、mutation、Approval、import、replay、object retrieval 和 lineage
  traversal fail closed，且不泄漏 target resource。
- Object storage path 绝不作为 ownership evidence；object retrieval 前由 authoritative
  PostgreSQL metadata 授权。
- Imported asset 从 trusted request context 获取 destination workspace。Manifest-supplied
  workspace/owner 仅为 evidence，不能授予 access。
- Actor/workspace context 在 audit 和 WorkflowTrace correlation 中分别记录；public
  projection 保持有界且 secret-free。

## Migration 与 compatibility

Migration 明确分阶段：

1. Expand workspace table，并为每个 durable user idempotently provision 一个 personal
   workspace 和 owner membership。
2. 为 classified domain table 增加 nullable `workspace_id` column 和 workspace-aware
   index，不改变 current read。
3. 只在能从 historical owner principal 证明 exact unique durable-user mapping 时 backfill。
   生成 count/manifest；orphaned、ambiguous、service-token 或其他 unverifiable row 被
   quarantine/report。
4. 在 column mandatory 前验证 row count、parent-child equality、reference integrity、
   uniqueness 和 owner-to-workspace mapping。
5. 将 read/write cutover 到 trusted `WorkspaceContext`，保留 `owner_principal` 用于
   creator/audit compatibility；之后才对 verified table 增加 non-null、foreign-key 和
   uniqueness constraint。
6. 只有 two-user Browser/Product API golden journey 证明 restart persistence、import/
   export、Approval、lineage 和 cross-workspace denial 后，才移除 compatibility read path。

Migration 不把所有 legacy row 分给 first user 或 administrator。Contract step 前 rollback
会 disable workspace-aware read/write，并保留 additive table/column。Constraint enforced
后，rollback 是 forward repair 或从 Phase backup restore，绝不静默回到 mixed owner/
workspace authorization。Phase 49-52 不删除 `owner_principal`。

## 后果

- Personal Product 获得明确、auditable tenancy boundary，UI 不增加 team-management
  complexity。
- 即使 visible Product change 很小，大部分 domain table/service method 仍需要受控 migration。
- User secret/preference 正确绑定 human account；shareable research Artifact 在结构上为
  future team model 做好准备。
- Existing owner isolation 是安全 compatibility source，但在 Phase 52 完成 migration 和
  golden journey 前，不能误认为 workspace isolation 已完成。

## 拒绝的替代方案

- 永久以 `user_id` 作为 tenant key：现在简单，但 team workspace 到来时需要大规模 asset
  rekey，并持续混淆 actor/owner semantics。
- 立即实现完整 organization/team：在 personal Product 需要前增加 invitation、role
  policy、switching、sharing、billing 和 operator support。
- 信任 client-supplied workspace ID：允许 confused-deputy 和 horizontal privilege
  escalation。
- 复用 Community tenant design/runtime code：它是与 obsolete runtime/storage assumption
  耦合的 planning draft，不是 compatible implementation。
- 让全部 data workspace-owned：复制 canonical market data，并混淆 shared platform
  dataset access 与 user Artifact ownership。
- 先启用 RLS 并单独依赖它：service、MCP、object、lineage、import、audit boundary 未定义，
  且增加 migration risk。

## Acceptance record

维护者于 2026-08-24 选择 personal-workspace tenancy option。Acceptance 授权 Phase
49-52，但不授权 team feature、raw DSH Browser Contract、DSH database access、Community
code copying 或 silent ownership assignment。
