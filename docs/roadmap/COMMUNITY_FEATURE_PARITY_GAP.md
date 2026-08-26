# Community Feature Parity Gap Audit

Status: **已由 Phase 48 对账并关闭**。本文最初写于 Phase 34 之后，现作为历史 gap register 保留。先前的 `PARTIAL` 结论已被 Phases 35–40，以及 Phases 41–48 交付的完整 conversation-first Product experience 取代。

## 对账方法

- 按 surface 检查只读 Community frontend `/home/jefison/projects/BeyondQuant-community/frontend`，从未修改或复制。
- 每项 capability 在对应 Product phase 前，均在 `docs/migration/COMMUNITY_MIGRATION_INVENTORY.md` 中分类。
- Phase 40 V2 matrix 关闭 domain/workbench parity，不留无法解释的 `PARTIAL` 或 `MISSING`。
- Phases 42–47 有意将能力迁移至 conversation-first shell、user center、System Settings dialog 和统一 management workspaces。
- Phase 48 在组合体验上重新执行 no-mock、two-user Product journey，以及 desktop/tablet/mobile Chrome review。

## 最终处置

| Community surface | BYQ 处置 | Final status |
|---|---|---|
| Login 与 durable user identity | 使用 durable username/password Product session；bootstrap token 不是普通 browser login。 | `REDESIGNED_PASS` |
| Dashboard 与 quick entry | Xiaoba 为默认 Product surface；resource summaries/actions 仍可经 Product routes/settings 访问。 | `REDESIGNED_PASS` |
| Agent 与 conversation history | Owner-scoped durable catalog、turn replay、rename、pin、archive/restore 和 normalized WorkflowTrace。 | `REDESIGNED_PASS` |
| Research 与 approvals | BYQ ResearchTask/Artifact/Approval lineage 和有界 approval inbox。 | `REDESIGNED_PASS` |
| Stock Pool | Mutable identity 加 immutable membership snapshots、lifecycle、weights、history 和 frozen references。 | `REDESIGNED_PASS` |
| Strategy | Editable drafts、validation、immutable versions、approval、export、history 和 signal lineage。 | `REDESIGNED_PASS` |
| Backtest | Approved version → isolated signal snapshot → 带全部八个 evidence tabs 的 deterministic result。 | `REDESIGNED_PASS` |
| Paper Trading | Owner-scoped accounts、精确 T+1 ledger、settlement、risk controls 和安全 bundle transfer。 | `REDESIGNED_PASS` |
| Profile 与 appearance | Durable profile 加 versioned system/light/dark 和封闭 accent themes。 | `REDESIGNED_PASS` |
| Models、assets 与 Agent policy | Encrypted write-only credentials、profiles/binding、validated asset transfer 和 effective policy rules。 | `REDESIGNED_PASS` |
| Operations 与 Data Center | Route-backed、admin-only、有界 projections，Tushare sync 和 PostgreSQL coverage；无 raw infrastructure controls。 | `REDESIGNED_PASS` |
| Shared responsive components | 统一 states、pagination、dialogs、charts、focus、unsaved-change 和 semantic theme behavior。 | `REDESIGNED_PASS` |

最终详细比较见 [`COMMUNITY_FEATURE_PARITY_MATRIX_V2.md`](COMMUNITY_FEATURE_PARITY_MATRIX_V2.md)。Phase 48 残余 Product/release 工作另见 [`../evidence/phase-48/PRODUCT_GAP_REGISTER.md`](../evidence/phase-48/PRODUCT_GAP_REGISTER.md)。本文任何历史 gap 都不授权重新引入 Community APIs、runtime、storage、BaoStock、AKShare、VectorBT、PydanticAI 或 Hermes。

## Release 含义

Parity 和 Product-experience implementation 已完成，但这不自动声明 v1.0 release。Phase 48 只重新开放 ADR-0024 要求的 human release-candidate review；maintainer 必须单独评估 release evidence，决定是否接受 RC。
