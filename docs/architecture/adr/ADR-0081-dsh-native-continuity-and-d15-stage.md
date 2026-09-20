# ADR-0081：DSH 0.1.5-rc.1 native continuity adoption and the D15 stage

- Status: Proposed
- Date: 2026-09-19
- Relates: ADR-0079（Runtime Continuity 与 Session Recovery）、ADR-0058（DSH release bundles 与
  compatibility）、ADR-0069（退役 0.1.1 build lane）、ADR-0003（runtime compatibility review）、
  ADR-0023（执行者身份）、ADR-0062（Post-U8 可靠性边界）
- Supersedes: 无（不改写任何 Accepted ADR 文本）。本 ADR 只在获维护者接受后取代 R3 的实施顺序，
  不改变 R0/R1/R2 的已落地语义。
- Decision scope: Runtime Continuity 阶段顺序（R3 冻结与重定义、D15 新增、R4/R6 重定义）；
  D15-0/D15-1 的候选隔离边界。不含生产默认 DSH 版本切换、不含数据库/Worker 变更。
- Qualification target decision: `docs/evidence/d15/target-decision.v1.json`
  （维护者决定目标为 coherent 配对 `dsh-v0.1.5-rc.1`；`0.1.5-rc.2` 无 Python 配对）。

## Context

ADR-0079 定义了 R0–R2 并预告 R3（Supervisor）与 R4（Terminal）为后续独立阶段。实际状态是：

- R3 分支 `codex/phase-r3-supervisor` 相对 `main` **没有任何提交**，未实现；
- DSH `0.1.5` 已原生提供此前计划由 R3/R4 自建的连续性能力：Session V2/V3 迁移、
  `SessionHandle` 持久化、跨进程写租约、continuable subagent/fork、persistent terminal。

在这些能力之上继续自建第二套连续性运行时，会复制状态并与「不重复建设通用 agent harness」
冲突，也无法验证原生语义。因此先冻结 R3，增加 DSH 原生连续性资格阶段 D15。

D15-0 审计确认请求的 `0.1.5-rc.2` 缺少匹配的 Python runtime（仅 `0.1.5rc1`，其 bundled
npm 为 `0.1.5-rc.1`）。维护者据此决定 D15 的资格目标为 coherent 配对 `dsh-v0.1.5-rc.1`；
rc.2 保留为 not-a-coherent-pairing。证据见 `docs/evidence/d15/`。

## Decision

### 1. R3 冻结（非回滚）

R3 状态为 `PAUSED_PENDING_DSH_015_NATIVE_CONTINUITY_QUALIFICATION`。保留既有 R3
代码/测试/文档与框架中立合同；不回滚 R1/R2。暂停自建 DSH 进程重启编排、会话重建、
原生会话持久化替代、subagent 持久化、持久 PTY/shell 运行时，直至 D15-G。

### 2. 新增阶段 D15

`D15-0 Upgrade Recon → D15-1 Candidate Runtime Upgrade → D15-2 Session V3 Migration →
D15-3 Native Session Resume → D15-4 Subagent/Fork Continuity → D15-5 Persistent Terminal →
D15-G Architecture Go/No-Go`。不重编号 R0–R6，不改变其既有语义。

### 3. 原生能力优先，禁止第二连续性实现

凡 DSH 0.1.5 原生覆盖的能力（会话格式迁移、会话句柄持久化、写租约、continuable
subagent、persistent terminal），BYQ 只做**适配、观测与失败降级**，MUST NOT 另建同等
持久化。`LifecycleJournal`（ADR-0079 §4）仍是 BYQ-owned 执行证据日志，不演化为 DSH
session/tool/subagent 的第二持久化。

### 4. 候选隔离边界

未完成 D15-G 前：生产默认选择器不变；0.1.2 制品与历史资格证据不变；候选通过独立声明
（`config/dsh/candidates/`）、独立 compat 模块与显式 selector（`BYQ_DSH_COMPATIBILITY_RELEASE`）
隔离；不写入不可变的 `config/dsh/releases` 注册表（其每 release 绑定归档 Git tree）。
回滚目标为 `dsh-0.1.2rc1`。

### 5. R3/R4/R6 重定义与顺序

- **R3 Thin Runtime Supervisor**：仅 RuntimeGeneration 健康、executor epoch/fencing、
  DSH 原生会话 attach/resume、原生 resume 失败降级、生命周期观测/上报、资源清理。
  明确不含：对话 canonical history、DSH session-store 替代、subagent 持久化、terminal PTY runtime。
- **R4 TerminalAttachment**：attachment 生命周期，非 terminal runtime。
- **R5 DurableJob independence**：不依赖 Browser/Frontend/AgentSession/RuntimeGeneration/
  DSH process/TerminalAttachment。
- **R6 Full Runtime Continuity Qualification**：完整连续性资格。

顺序：`R0 → R1 → R2 → D15 → R3 → R4 → R5 → R6 → independent Production Go/No-Go`。

### 6. 决策相互独立

“BYQ 兼容 DSH 0.1.5-rc.1”与“生产默认 = DSH 0.1.5-rc.1”是独立决策；D15-G Go 或 R6
完成都不隐含生产切换。

## Consequences

- 连续性能力以 DSH 原生为准，BYQ 减少自建状态与故障面。
- R3 推迟到 D15-G 之后，避免在未验证原生语义时重复实现。
- 候选与生产严格隔离。D15-1 已构建/启动/探测 coherent rc.1 候选（隔离、无生产流量）；D15-2
  已完成 Session V3 迁移资格（PASS，证据 `docs/evidence/d15/d15-2/`）；D15-3..D15-G
  的 native 资格仍待执行。
- 由于 D15 改变 runtime build inputs，生产构建修订由 `post-u8.145` 推进到 `post-u8.146`，
  并在 D15-1 新增候选 Dockerfile/锁/探测后推进到 `post-u8.147`，在 D15-2 新增
  `scripts/`/`tests/` 下的迁移 harness 与 fixtures 后推进到 `post-u8.148`（历史清单与证据保留）。

## 接受后验收要求（D15）

- D15-0 台账（machine-readable）与 recon 提交，覆盖 BYQ 依赖接口；
- D15-1 候选隔离声明、selector、compat 边界与测试通过，生产默认不变；
- D15-2..D15-G 测试计划、fixtures、acceptance criteria 提交；
- `R3_RESUME` 仅在 D15-G 完成且存在原生连续性证据时为 YES。

## Migration / rollback

- 本 ADR 只改阶段顺序与文档/隔离代码；回滚即丢弃候选声明并保持默认选择器。
- 不改数据库、不改 domain row、不重启 Worker、不删除任何历史制品或证据。

## Review note（2026-09-20，未改变状态）

状态仍为 **Proposed**。记录的授权缺口：本 ADR 文本写明路线重排须在获维护者接受之后发生，但专项
[D15 计划](../../roadmap/DSH_015RC1_UPGRADE_PLAN.md) 已实际实现该重排（D15 插在 R2 之后、R3 之前）。
该差异必须由维护者具名解决（接受为 Accepted，或以具名记录追认当前重排）；D15-2/D15-3 的 `PASS`
是隔离资格证据，不构成 R3 解冻、生产切换或对本 ADR 的接受。详见
[STATUS.md](../../roadmap/STATUS.md) 顶部“权威当前状态”。
