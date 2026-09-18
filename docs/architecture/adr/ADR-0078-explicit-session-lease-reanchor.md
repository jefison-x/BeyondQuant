# ADR-0078：Explicit Reversible Session-Lease Re-anchor

- Status: Proposed
- Date: 2026-09-19
- Relates: ADR-0064（Runtime 崩溃恢复的受限持久证据）、ADR-0062（Post-U8 可靠性边界）、ADR-0023（隔离信号生产者的执行者身份约束）、ADR-0059（开发权限与 CI 证据门禁）
- Supersedes: 无。待接受后仅替代 ADR-0064「首版实现边界」中「主机重启…拒绝自动判定」的恢复操作层，不改变其自动恢复的 fail-closed 语义。
- Decision scope: runtime-adapter lifecycle journal 的 lease 身份恢复；`scripts/ops` 运维工具；不含 domain/DB 变更。

## Context

`LifecycleJournal` 将每个 durable session 绑定到写入它的主机（ADR-0064 首版实现边界）：

```
lease_identity = sha256(boot_id : st_dev : st_ino : token)
```

其中 `boot_id` 是 `/proc/sys/kernel/random/boot_id`，**每次主机重启都会改变**。于是任何
reboot 前写入的 journal，其 stored `lease_identity` 永远无法再被复现，`LifecycleJournal.claim`
抛出 `JournalIdentityMismatch`，adapter 显式映射为 HTTP `409` + `stale_session_lease`
（区别于未知会话 404 与真实存储故障 503）。

2026-09-19 host reboot 后，17 个既有 session（含活跃会话）全部变为 stale；原有
`scripts/ops/archive_stale_sessions.py` 只能把证据**只读归档**，会话本身不可恢复。这个
问题**每次 reboot 都会复现**。需要一条显式、可审计、可逆的恢复路径，同时不削弱
ADR-0064 的 fail-closed 与跨执行者 fencing。

## Decision

### 1. 显式 re-lease 作为当前受支持的 reboot 后恢复

在 runtime-adapter 增加 `LifecycleJournal.reanchor_lease(root, session_id, *, expected_stored_lease)`。
在持有该 session 的**排他 owner lock** 时，原子地只重写 stored `lease_identity` 为当前
boot 派生的身份；`context`、`sequence`、`open_root`、`events`、`prompts`、`terminal_acks`、
`calls` 全部保持不变（canonical JSON 逐字节以外仅 lease 改变）。它：

- stored lease 已等于当前身份时是**幂等 no-op**，不写审计、不改文件；
- `expected_stored_lease` 与 stored 不一致时**fail closed**（不盲写、不猜测）；
- 未知/无效 session、symlink、live owner（lock 被持有）、非法 lock token 均拒绝；
- 在 journal 旁原子写入 per-session 审计（timestamp、session、old/new lease、prior/new
  journal sha256、preserved 字段列表、reversible=true）；审计提交晚于 journal 原子替换；
- 不触碰任何 domain/数据库状态。

`409 stale_session_lease` 分类与 `archive_stale_sessions.py` 归档工具保持不变；re-lease 是
归档的替代路径，不替代其只读审计能力。

### 2. 运维入口

`scripts/ops/reanchor_session_lease.py`：默认 audit-only；`--apply` 才改写；**必须显式**
`--session-id`（可重复）或 `--session-file` 选择，不做隐式全量 re-lease；写
`audit.json` + `manifest.json`（old/new lease、sha256、reversible、无 DB 写入、无删除）；
同 timestamp 重跑幂等返回 `already_reanchored`；只处理 `stale`，`active`/`current`/
`unprovable`/`archived` 在变更前整体 fail closed。

### 3. Gateway 无 lease-bound 状态

核验 `services/gateway/app/trace_store.py` 与 `agent_lifecycle_delivery.py`：TraceStore 以
`session_id` 为键、以 `sequence` 排序；lifecycle delivery ledger 只保存该序列上的 cursor
与 pending/terminal 记录。re-lease 保持 `sequence` 不变，因此 **Gateway 没有任何 cursor、
ledger 或 trace 文件需要刷新**。工具在 audit/manifest 中记录 `gateway_lease_binding: "none"`
及原因，不得猜测性刷新 Gateway 状态。

### 4. 提议的持久设计修复（待后续 ADR 接受后实现）

当前缺陷的根因是 **lease 身份绑定到 `boot_id`**——一个与业务无关的宿主生命周期事实。
提议将 lease 身份改为与 boot 无关的稳定执行者身份：

- `deployment_identity`：稳定部署/进程身份（release identity + volume identity + lock
  inode/token），不随 reboot 改变；
- `executor_epoch`：单调递增的接管 epoch，仅在**显式 takeover**（operator/协调者授权）时
  递增，用于 fencing 旧执行者与并发恢复者；
- `lease_identity = sha256(deployment_identity : executor_epoch : token)`；
- 保留 ADR-0064 的排他 flock、只读证据重放、终态不可覆盖与「不按 PID/超时猜测」边界；
  跨主机时以 epoch + 显式 takeover 而非 boot_id 证明唯一写者。

该修复会改变 ADR-0064 的「首版实现边界」，因此**必须以独立 ADR 显式接受**后才可实现；
在此之前，本文第 1 节的显式 re-lease 是唯一受支持的 reboot 后恢复。

## Consequences

- reboot 后 operator 可对精确选择的 stale session 恢复可用性，且保留完整证据与可逆审计；
- 恢复动作是显式、有界、可审计的，不引入自动接管，不削弱 ADR-0064 的 fail-closed 语义；
- re-lease 只在没有 live owner 时发生，不产生双写者；
- 在持久设计修复被接受前，每次 reboot 仍需一次人工 re-lease，这是已知的运维成本；
- 若 boot 之外的执行者身份（volume/inode/token）也改变，或存在并发写者，re-lease 仍
  fail closed 并要求人工调查。

## Migration / rollback

无数据迁移、无 schema 变更。新工具仅重写 lease 字段；manifest 记录 old lease 与 prior
sha256，可审计。回退时停止使用工具并保持旧 journal 即可；已 re-lease 的会话在新 boot
前保持 current，reboot 后再次 stale，按同一流程处理。持久设计修复必须另立 Accepted ADR
方可实现。
