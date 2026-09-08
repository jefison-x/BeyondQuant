# 迟到回答与未回答主题恢复（2026-09-08）

本批为 ADR-0062/0046 范围内的 Gateway 恢复投影修复，不改变 Product Phase。
基于已合并的 #261，在独立 `fix/post-u8-correction-order` 工作树实施。

## 失败与修复

旧实现按目录中最后一条 assistant 的位置截断未回答问题。合成序列
“旧问题 → 新问题 → 旧回答迟到入库 → 新回合失败”使新问题丢失；首轮六项
回归为四通过、一断言失败、一空恢复对象错误。修复后另增两项失败反例，证明
未回答问题还会混入标称已完成的恢复历史，以及无关联证据的回答会伪造已完成历史。

现在使用同 session/trace 内的精确回答序号、正文、原 session.started 与成功终态
界定已回答范围，而不使用 assistant 入库位置/入库时间。原回合开始之后提交的新问题
不被旧回答关闭。失败回合的部分回答不关闭主题；缺证据/正文不匹配/主题不唯一时要求确认。
未回答请求仅进入独立恢复分区，不再同时被标为已完成。没有改写或删除持久消息。

完整 Gateway 测试首次为 190 passed / 1 failed：既有重启测试仅提供无日期、无回答序号的
合成旧回答，却期望作为已完成历史。补充旧回合的规范化 start/answer/result 与消息日期，
保留原有重启、序号连续、旧问答恢复、缺身份需确认和 collector 断言；缺证据拒绝由新增反例覆盖。

## 边界

本批不是 UI 时间线重新排序，不提供持久 user-message/root-turn 外键，不宣称无 trace 时
能够找回回答关联或完整多轮语义已验收。F7 持久纠错台账、S3 历史准备、F6 预算续接仍未完成。
MCP 的进程级 generation 不能充当纠错根回合；后续应核验既有可信 AgentRun 的 root_run_id
绑定与动作上下文，不另建通用 harness。

源码变化使旧 post-u8.3 当前树 hash 检查按设计失败；保留旧 manifest、历史 release 和
失败测试，按 ADR-0061 独立创建 post-u8.4，不继承 .3 的资格结论。
首次架构运行被只读沙箱阻止临时目录创建；适当权限重跑后剩余失败为当前构建身份漂移，
均不计作通过。最终验证结果另行追加。未调用付费 API、未部署、未续跑历史研究。

后续重跑保留两次夹具错误（回答合同缺 channel/truncated、trace 序号不连续）。
补全后再暴露真实缺陷：失败前没有新的 session.started 时，误借用了上一个成功回合的
run_id，且排除了其有效历史回答。现在只在上一终态之后查找本轮起点；缺失即保持未知。
最终 Gateway 全套：191 passed / 1 个既有 Starlette 弃用警告，1.78 秒；通过无网络镜像和
只读最终源码执行，尚不是完整构建认证。.4 保留为未完成资格的中间身份；最终源码使用新的
.5 清单，不能用 .4 曾通过的 214 项架构检查冒充最终源码结果。

## 最终本地验证

源码提交：`90aa463e024938b109dd58253859d042e8b73e8b`；隔离 scope：
`post-u8-order-20260908-5`。CI 开始时源码尚未提交，随后按相同内容提交；两份最终
清单在提交后再次核验通过。此为本地验证，不冒充远端 exact-head CI。

- 影响选择的完整本地 CI：退出 0，26/26 检查通过。
- 架构/共享合同：214；Backend：421 passed、1 skipped、7 subtests；Gateway：191。
- Runtime：119 passed、14 skipped；实际候选进程/委派：12 passed。
- 两个 runtime 各 20 次生命周期循环，lingering_threads=0、retained_sessions=0。
- MCP 全套通过；前端 build、172 单元测试、20 模拟浏览器测试、9 真实 Product API 浏览器测试通过。
- 全栈 smoke、ML/反馈重启持久化和双用户隔离、无 mock 双用户 Product coherence 通过。
- Gitleaks 检查源码提交：无泄漏。保留既有弃用/工具链警告及模拟页面 ResizeObserver 警告，
  不声称零告警，不将未执行的真实模型语义算作通过。

脱敏日志：本工作树 `.ci-artifacts/post-u8-order-20260908-5.log`，SHA256
`500046c1a8e288f3e6d35df9caf43db43139b6dc8ee21044f9843d30b0a77acc`。
日志记录全部 12 个构建镜像 ID 与测试结果。

| 身份 | SHA256 |
|---|---|
| .5 baseline manifest | `8be7f79374ea0cb19bbd244bfff2fca4a72ecbda350722d037796f3b8056f015` |
| .5 candidate manifest | `c81b9fc9b3095e811e39f661472b844c616fc97a53ff2e9ee9d41ddb0d1f301d` |
| Gateway image | `5b30bc43ccabca0aea8ac3517560a3a9767f7ce9f87156b2963da37d188a5b37` |
| baseline runtime image | `bba3937cf707a71613fa2c030a06652f377a7b861ea1eefb20bd075a348d9376` |
| candidate runtime image | `90530e28cc157bb03ae820d941508cbc735685ac9bb57c18be322e2d2d7747b7` |

CI 自动清理后再次执行独立 scoped cleanup，专属容器、镜像、卷、网络为零。
早期独立 Gateway 镜像也已清理，可重建；日志及历史失败记录保留。没有触碰生产、
Community 或私有备份。付费 API 调用为零，未推送、未合并、未部署。
