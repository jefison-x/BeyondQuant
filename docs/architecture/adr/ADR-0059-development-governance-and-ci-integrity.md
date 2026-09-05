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
