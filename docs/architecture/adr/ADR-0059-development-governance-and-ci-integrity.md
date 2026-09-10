# ADR-0059：开发治理与 CI 证据一致性

- Status: Accepted
- Date: 2026-09-05
- Decision scope: maintenance workflow、Engineering/operator 权限说明与 CI integrity；不改变 Product 权限或 DSH baseline
- Acceptance: 维护者在治理审查后明确要求“按照你的建议……治理与 ci 整改，最后修正……DSH 升级方案”。本记录只接受该整改范围，不授权本次推送、合并、部署或 DSH 升级。
- Supersedes: ADR-0015/开发流程中未区分 Engineering 与授权 operator 的部署措辞；DSH_UPGRADE_LANE 的自动合并非目标仅指未经授权的升级机器人；其余边界不变。

## 决策

1. 规范按职责唯一归属：AGENTS 是入口；ARCHITECTURE 是持久边界；Accepted ADR 是具名例外；
   DEVELOPMENT_WORKFLOW 是执行/权限门禁；STATUS 是当前 Product Phase；专项计划是任务步骤；
   ci-policy 与其受测脚本是风险验证政策。历史 Phase 验收不是当前通用流程。
   只有显式声明范围和 supersedes 的 Accepted ADR 覆盖原规则，不能用“较新文件”自动扩权。
2. 区分 Product Phase、maintenance/bugfix、dependency upgrade、docs/review、operations。
   “继续开发”只选 STATUS Next phase；明确指定维护可独立执行，不修改完成 Phase、不提前实现下一阶段。
3. 开发、push/PR、merge、production deploy 是独立授权范围，可由维护者一次性明确覆盖。
   未覆盖的外部写动作不能推定授权。默认 Draft/human gate；v1.0 前只有明确合并授权且
   GitHub auto-merge、服务器 required checks 可验证时才使用 ADR-0015 squash auto-merge。
   设置关闭、API 403、检查缺失/跳过/过期时停在 Draft，不使用 admin bypass 或立即手动 merge 代替。
   本 ADR 不修改 GitHub 设置，不以本地检查冒充平台强制门禁。
4. Engineering code agent 本身没有生产部署权限。维护者可另行授权其在 Product 之外作为
   trusted operator 执行既有 deployment lane；记录授权、目标 commit/image、服务白名单、
   readiness/业务 smoke、rollback 和必要 backup。不得把该权限传给 Product DSH、Backend 或浏览器。
   自动 destructive migration、数据删除、release/tag 不包含在普通部署授权中。
5. STOP 暂停受影响的越界实现/发布，允许继续只读调查、隔离复现、测试和 Proposed ADR。
   ADR 必须有维护者对精确决策的接受记录才能 Accepted；泛化“继续”不等于接受新边界。
6. 隔离 worktree 默认根为 `/home/jefison/projects/.byq-worktrees`，运维可通过
   `BYQ_ENGINEERING_WORKTREE_ROOT` 指定专用根。不得使用仓库根、主工作区、Community、系统根或整个 home/tmp。
   Backend 仅校验申报路径合同，不挂载主机源码、不调用 Git；宿主工程工具验证真实路径与 worktree 登记。
7. CI 按影响选择完整组件 suite，依赖/契约/迁移/运行时组合触发 integration。
   本次源码构建的 run-scoped 镜像必须同时用于测试与 Compose；构建失败不得回退旧镜像。
   日志脱敏后保留；cleanup 必须独立运行且失败使 gate 失败。
8. fork PR 只在无生产网络/凭据的 GitHub-hosted 临时 runner 执行，不转入 self-hosted，
   不使用 pull_request_target 执行贡献者代码。汇总 gate 明确要求正确 lane 真正 success。
   平台不允许执行时保持未验证，不以 skipped 代替通过。

## 完成与兼容

EngineeringTask `completed` 沿用 ADR-0011，仅表示 tested Draft PR 交付完成，不表示 merged/deployed。
合并、部署和观察结果另行记录证据；不在本次重写其持久状态机。
DSH ADR-0058 保持 Proposed；治理整改不接受候选运行时。DSH 升级仍先 U0 资格审查。

## 验收与回滚

必须验证风险分类负例、镜像构建失败禁止继续、fork lane/gate、日志脱敏、资源清理和 worktree 逃逸。
不依赖真实模型 key、GitHub 写权限或生产数据库。治理/CI 回滚通过新 PR，不恢复漏测为临时部署捷径。

## Accepted amendment — 2026-09-09：浏览器验证不绑定 Chrome MCP

- Acceptance：维护者明确要求“直接去除掉chrome MCP 测试要求，后续我都准备将系统中安装的chrome 删除掉。”
- Scope：当前及后续 Product、维护修复和发布中的浏览器工具选择；不改变产品架构、测试覆盖或发布授权。
- Supersedes：AGENTS 第36条、DEVELOPMENT_WORKFLOW Product Completion 门禁，以及
  ADR-0018/0019/0022/0044 和历史 Phase、DSH 升级、Post-U8 计划中对 Chrome MCP 的
  专属工具要求。仅替代工具限定，不取消各项验收的业务断言和证据要求。

真实浏览器验证可以使用 Playwright 管理的 Chromium 或其他适合目标环境的测试浏览器。
不再要求 Chrome MCP、系统安装的 Google Chrome、个人登录浏览器或人工开启调试端口。
工具缺失本身不阻塞交付；缺失真实 Product API、持久化、两用户隔离或受影响页面的
桌面/移动端、网络/Console、视觉证据仍须补验。Mock-only、静态页和单纯 HTTP 200 不算完成。

历史报告保留原工具和失败事实；不得将旧 Chrome MCP 失败改写为成功。已有且覆盖当前
修改的真实浏览器证据可按内容采纳，不为补工具名称而重复整套测试。记录工具、受测版本、
范围、结果和限制。此修订不卸载软件、不修改个人浏览器或插件配置，也不绕过远端 CI、
合并 preflight、部署和付费评测的独立授权门禁。

## Accepted amendment — 2026-09-10：常规升级采用轻量部署流程

- Acceptance：维护者认可“升级前备份数据、保存旧镜像和配置、部署通过 CI 的新镜像、验证，失败切回旧镜像；普通应用回退不恢复数据库”，并明确要求“好的，记住了，以后升级就按这个新流程执行。”
- Scope：当前及后续常规应用升级的部署与恢复验证；不改变应用架构、CI 或每次部署的授权范围。
- Supersedes：DSH_012RC1_ROLLOUT 第3节及历史发布步骤中被解释为每次常规升级都须重新执行完整数据库恢复演练、重建回滚方案的要求。历史升级验收事实保持不变。

常规升级按以下顺序执行：

1. 升级前完成数据备份，保留当前配置和实际旧镜像身份；检查备份成功、可读及校验和。
2. 核对目标是已通过所需 CI 的精确镜像；复用适用的既有部署与回退配置，不重新设计回滚方案。
3. 必要时关闭新会话入口并排空活动回合，完成会话一致性备份；仅更新受影响服务。
4. 核对实际镜像、服务健康和基本业务功能，恢复入口并记录结果。
5. 应用异常时优先切回保存的旧镜像及配置，保留当前业务数据库。

普通应用升级不以重新进行完整数据库隔离恢复演练为发布前置条件。只有数据库结构、
存储格式、不兼容或不可逆数据变更，或已有恢复证据失效时，才针对受影响部分补充恢复验证；
不自动扩大为全部数据库重演。既有备份恢复证据可以复用，但不得声称已验证本次新备份的完整恢复。

保留精确旧镜像作为首选回退制品，不依赖现场重编译；必要重建必须重新核验依赖和制品身份。
应用回退不默认恢复数据库；恢复备份可能丢失备份之后的新数据，实际生产数据恢复须另行明确授权。
本修订不授权自动删数据、清理历史制品、付费模型测试、正式 release/tag，或省略实际健康与基本业务验证。
