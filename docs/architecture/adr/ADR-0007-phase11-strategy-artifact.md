# ADR-0007：Phase 11 Strategy Artifact、Validation 与 Approval Boundary

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 11 Quant Domain strategy artifacts
- Supersedes: 无先前 strategy-artifact 决策

## 背景

Phase 10 生成可复现 research Artifact，但仓库尚无安全的 BYQ-owned strategy
code/configuration 表示。Community 为 content-addressed strategy snapshot、static source
check、export hygiene，以及 approval 与 execution 的区分提供了有用证据；其 SQLAlchemy
model、Pandas runtime、Agent Service workflow 和 optional engine 不兼容当前架构。

Phase 11 必须让生成的 Strategy 成为可审计数据，而不能把它变成 application source，
也不能授予 Product DSH execution 或 filesystem privilege。

## 决策

1. Strategy draft 是 BYQ `Artifact`，包含有界、normalized strategy snapshot 和保留的
   validation evidence。draft 不可变；修订后的 draft 是通过 lineage 关联的新 Artifact。
2. 经过验证的 `StrategyVersion` 表示为 content-addressed BYQ Artifact。其 semantic
   snapshot 排除可变 timestamp 和 Agent runtime state。version identity 是 canonical
   strategy identity 的 SHA-256；source fingerprint 是 strategy source 的另一 SHA-256。
   对同一 task 重复相同 version request，会解析为相同 version Artifact。
3. StrategyVersion materialize 前，BYQ 执行确定性 static validation。Validation 拒绝
   unsafe import/call、无效 Python structure、不支持的 category、过大或 malformed
   parameter，以及无效 strategy method Contract。本 Phase 不执行 arbitrary code；
   execution 属于后续 BYQ-owned worker boundary。
4. Export 是明确的 BYQ operation，只包含 StrategyVersion Contract 和 semantic snapshot。
   credential、runtime setting、DSH/Agent internal、prompt 和 application-source path
   均被拒绝或省略。
5. Approval 是独立、不可变的 `strategy_approval` Artifact，关联已验证
   StrategyVersion，并记录 actor、decision、rationale、trace 和 idempotency evidence。
   approved record 只授权未来尝试，不表示 execution 或 business mutation 已成功。
6. Backend 持有全部 Strategy validation、versioning、export、approval 和 provenance。
   Agent-to-Domain call 使用 normalized BeyondQuant MCP tool。Product DSH 不能写仓库、
   执行 Strategy code 或直接访问 Backend storage。

## 后果

- 复用 Phase 9 Artifact content hashing、lineage、state transition 和 idempotency，而不
  创建第二套 persistence model。
- 即使后续创建新 draft，Strategy history 仍可从保存的 version Artifact replay。
- Static validation evidence 持久且明确；Phase 12 可以增加隔离的 native execution/
  preflight worker，而不改变 version identity。
- Approval 与 execution outcome 保持分离，后续失败不会被表示为成功 business mutation。

## 拒绝的替代方案

- 将 Strategy source 存入 application repository：违反 Strategy data/Artifact 边界和
  Product DSH source protection。
- 复制 Community SQLAlchemy/Pandas/Agent Service Strategy runtime：会把新架构耦合到
  旧仓库 ownership 和 runtime。
- 将可变 current Strategy record 视为历史事实：破坏 reproducibility 和 replay。
- 在 Backend API request 中执行 generated code：创建不安全 execution boundary，应由
  后续 BYQ-owned worker 处理。
- 重新引入 VectorBT、BaoStock 或 AKShare：当前架构和 migration inventory 明确排除。

## 退出证据

Phase 11 必须通过 Backend 与 MCP Contract 测试 invalid source rejection、确定性 version
identity、不可变 historical snapshot、secret-free deterministic export、Approval audit
record、idempotent retry，以及 Approval 与 execution outcome 的分离。
