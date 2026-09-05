# ADR-0058：DSH 版本制品、兼容适配与可重复升级

- Status: Proposed
- Date: 2026-09-05
- Decision scope: 拟议 DSH maintenance U0–U8；不改变 Product Phase 97 的完成状态
- Related: ADR-0003、0009、0019、0033、0037、0038、0039、0040、0046、0051

## 背景

BYQ 使用独立 Runtime Adapter、MCP 和 WorkflowTrace 隔离 DSH，但精确版本和原始接口仍散落在
运行代码、依赖、注册表、技能、业务证据 validator 和测试中。0.1.2rc1 删除/替换旧 SDK 配置与 demo
载体，现有 candidate 脚本不能覆盖包拆分、支撑包升级及新版默认 profile 的权限差异。

维护者要求一份详细升级规划；目前尚未实施、未确认新版可用于生产。本 ADR 是待 U0 验证的提案。
具体事实、官方链接、实施阶段和停止条件见[升级方案](../../roadmap/DSH_012RC1_UPGRADE_PLAN.md)。

## 拟议决策

### 1. 一个 release 描述，一个部署选择

工程端用不可变 release descriptor 固定 SDK/runtime、carrier、完整锁、profile/patch、compatibility family
与证据身份；部署指针选择已认证 release。生成物由 check 校验，运行状态核对实际 installed metadata。
现有 Plugin Registry 继续是资格/capability ceiling，PostgreSQL desired policy 和 Runtime active identity
继续遵守 ADR-0040；清单不产生新的授权/插件政策权威。

描述文件为受控构建输入，不由 Product 用户提交。image digest 在构建后 receipt 关联，避免自引用 hash。
认证结果使用独立 attestation 绑定构建输入/镜像，不回写 descriptor 形成依赖循环。
CI/candidate 与正式环境使用独立镜像、卷、网络及会话 home；候选合并不会隐式改变默认版本。

### 2. 使用官方公开启动接口，载体由证据选择

优先验证 matching Python runtime-bin 的 bundled CLI 能否通过公开 profile/patch 承载完整安全 BYQ 组合。
若本地插件加载、依赖身份或能力约束不可证明，使用 exact npm official CLI + 显式安全 profile。
两者均不可行则继续旧版，不用私有入口、fork、第二 harness 或默认 coding profile 规避。

不得将 sdk-minimal 的名称解释为安全认证；实际工具能力和执行权限是判据。
只选一个生产 carrier，不保留两套同时运行/隐式 fallback 的 SDK 安装。
具体 carrier、完整启动参数、插件组合、包映射和资格结果必须在 U0 附录定稿后才可接受本决策。

### 3. Adapter 内部兼容模块

SDK 配置、raw event 解码、root/child lineage、结束原因及必要私有 API 风险集中在 Adapter 内。
内部 Observation 只提供有界、经过归属验证的活动/答案候选/用量/终态；public projection 和私有 liveness
保持独立使用政策，不向 Gateway/Frontend 暴露新的 DSH 协议。
Adapter 继续管理 owned process、传输幂等和已有 900/180/120 生命周期政策。
DSH 继续管理 Agent loop、子 Agent、工具、压缩等通用运行能力；不得在 BYQ 重建通用调度或工具引擎。

### 4. 业务证据协议与上游版本解耦

保留 `web-research-evidence.v1` 的业务格式与 immutable identity。
将来源版本视为 provenance，与当前 runtime enablement 分离；由可信部署/MCP 上下文和已认证政策核验，
不由模型任意声明。MCP/Backend 只接收安全生成投影，不读取 raw Cordis 或启动 DSH。
历史合法 artifact 继续可读，不因撤销新写入资格而改写旧 hash。
过渡需证明旧/新 runtime 与兼容准备版 Backend/MCP 的有效组合及未知来源拒绝。

### 5. 保留已有对话恢复和审批语义

遵循 ADR-0046：切换版本后新建 private generation，从 BYQ durable conversation 获取有界已完成公开消息。
不采用新版原生历史续跑/hidden-state migration 作为本次前置，不直接迁移或重写生产 DSH JSONL。
按 release/generation 隔离 Agent home；旧会话日志保留，现有 BYQ 公开 ID、对象和审批保持权威。
未完成动作不因重启自动重放；approval continuation 必须复查精确资源、会话、幂等状态。
本 ADR 不新增 BYQ 审批引擎、持久任务状态机或常驻后台 Agent。

### 6. 认证、晋升与回滚分开

每次认证对应 exact artifact/image/profile/policy，不复制历史 qualified 标志。
工程 runner 可在固定清单/完整性和同等 capability ceiling 下隔离测试未认证候选；正式 builder/activation
仍只接受对应 attestation 完整的制品，不提供通用跳过资格/安全的生产开关。
required CI 使用真实 runtime + scripted provider 和完整隔离 Product 栈；本次生产晋升还需要 live-model
关键场景、Chrome review、old→new→old 恢复演练及授权发布。
只有 promotion 阶段改变生产默认指针。部署前排空 active turn，保留 pending continuation；仅更新必要服务。
回滚是旧 runtime image + 已验证兼容准备版本 + private generation/public context，不回滚业务数据库。
预发布合并遵循 ADR-0015 和实际用户授权，不因 qualification 自动扩展生产部署权限。

## 不在范围

新 Agent capability、Spill/Interaction、Shell/editor、外部 Agent provider、native cancel/resume 采用、
自主模型选择、自动升级所有 prerelease、在线安装、Product 部署按钮、DSH Web/ACP transport 切换、
多租户共享运行进程、DSH fork、Redis/数据库或 ML 算法改造。

## 后果与代价

首次需集中版本权威、适配两版接口并补齐旧故障测试；后续普通升级的人工工作主要是差异与证据审查。
上游破坏性变化仍需适配和实测，不能承诺任意版本零修改。
保留上一已认证镜像和有限 compatibility family，避免无限多版本负担。

## U0 接受前必须填写的决策记录

- 所选 carrier 及公开启动接口：**待验证**。
- bundled/local-plugin/module resolution 和 SDK 参数映射证据：**待验证**。
- 新旧实际 tool roster 差异及权限验证：**待验证**。
- profile/settings/home/数据路径与凭据继承控制：**待验证**。
- provenance producer identity 的可信来源及滚动部署矩阵：**待定稿**。
- 不可避免的 SDK 私有 API 依赖及替代方案：**待审查**。
- 接受的工程实施授权、日期、证据引用：**尚未记录**。

以上关键项不完整时保持 Proposed。后续维护者授权实施且 U0 满足这些约束后，可记录证据并接受；
无需仅因文档原本是 Proposed 就重复询问已覆盖的常规选择。实际边界超出本提案时应明确修订并取得方向。
