# ADR-0070：本地轻检查、云端并行 CI 与镜像发布

- Status: Accepted
- Date: 2026-09-11
- Acceptance: 维护者要求低本地资源、高开发速度、低 Codex token 消耗且便于 release 的 CI 方案，并回复“好的将你的建议实施落地”。
- Scope: Engineering CI、缓存、可信主线镜像构建/发布、制品来源验证及 digest 部署输入；不推进 Product Phase。
- Supersedes: ADR-0059/0060 和 DEVELOPMENT_WORKFLOW 中被解释为合并前必须本地及 GitHub 各跑一遍完整 CI、所有作业均不得具有镜像发布权限的要求。测试作业继续只读；仅下述独立发布作业有最小写权限。

## 决策

1. 本地默认 `make dev-check`，做差异、Python/Bash/JSON 语法检查，并根据修复运行必要的定向测试。
   完整受影响组件、架构、集成和浏览器验收以 GitHub 结果为合并证据；不能把轻检查称为完整 CI。
2. PR 按既有风险图拆分并行组件及独立 integration lane，保留全部套件和真实浏览器要求。
   `local-ci` 汇总所有已规划任务（含独立 cleanup 和日志上传）；`ci-gate` 仍要求 contribution。
   任何计划失败、任务失败/跳过/取消都不能通过。main 合并不自动重复 Full。
3. PR 旧提交取消；发布和 promotion 串行、不取消进行中作业。所有执行使用标准临时 ubuntu runner。
   npm 按 lock 缓存，Buildx 使用按服务划分的 GHA v2 min 缓存、amd64 和受控并发；缓存不是测试证据。
4. Release Images 只接受官方仓库 main 的手动 dispatch。无发布权限的 qualify 作业执行完整 CI，
   导出同一次验证的全部应用镜像。明确允许该作业上传非敏感镜像归档/哈希 receipt，保留一天。
   这是对 PR 只上传脱敏日志规则的具名例外；禁止上传 Env、数据库、卷、生产日志和浏览器身份文件。
5. 独立 publish 作业仅对上述成功作业交付的精确源码/run/archive/image ID 核验后发布 GHCR，
   不重编译、不运行应用代码。最小权限为 packages 写入及来源证明所需 OIDC/attestations 写入。
   生成 source SHA、Full CI URL、migration 分类、各服务 digest/image ID 和 SPDX SBOM 哈希清单。
   GitHub attestation 绑定清单。验证者同时核对官方 signer workflow、main ref 和成功 run 的 source SHA。
6. Promotion 只给已经验证的相同 digest 添加显式版本标签，不重建，不覆盖其他镜像的版本标签。
   正式 Git tag/Release/v1.0 发布仍需具名授权，本维护不自动创建。保留清单和 SBOM 到正式 release 资产。
7. 生产 operator 验证证明及镜像身份后生成按服务选择的 digest overlay，使用 `--no-build --no-deps`。
   仍执行 ADR-0059 的轻量备份、排空、健康/业务验证和旧镜像回退；不把生产权限交给 GitHub 测试或 Product。
8. Codex 使用结构化精确 head watcher，只在状态变化及结束输出摘要，失败时读取有界脱敏日志。
   缺失、过期、超时和平台不可用如实报告，不能伪造 PASS。性能目标须以实际执行测量。

## 验证

风险图、分支权限、缺失检查、损坏制品、未验证主线、镜像引用逃逸、版本覆盖和失败清理均须拒绝。
本地运行必要脚本/架构合同测试；远端验证并行任务及缓存。实际发布/提升执行结果另记，配置存在不等于发布成功。
