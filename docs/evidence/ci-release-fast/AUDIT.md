# CI 与镜像发布维护

维护者要求落实已讨论的低本地资源、云端并行、镜像复用及低 token 方案；按
[ADR-0070](../../architecture/adr/ADR-0070-hosted-ci-and-image-release.md) 执行独立维护，不推进 Phase 97。

## 实现

- `make dev-check` 做本地轻检查，完整受影响 suite 在 GitHub 验证。
- 同一风险图规划 docs/architecture/backend/gateway/runtime/mcp/frontend/integration 并行任务。
- 保留 local-ci/ci-gate 必需状态、contribution、按任务 scope 的独立清理及脱敏日志。
- Buildx 服务级 GHA v2 min 缓存、amd64、并发二；npm lock 缓存；按需安装浏览器依赖。
- Backend/Gateway 依赖层置于源码前；候选 runtime 复用当次镜像，不重复构建。
- 可信 main Full → 测试镜像归档 → 独立 GHCR publisher → SPDX SBOM/attested manifest。
- 来源核验及 digest overlay；RC/正式镜像标签复用 digest，不创建 Git tag/Release。
- 精确 head watcher 输出状态变化及失败时有界脱敏日志。

## 本地验证

- actionlint 1.7.12：三个 workflow 语法通过。
- 架构/脚本 unittest：236 项通过（包括 GHA cache 环境下运行）。
- changed-document links 与 git diff --check 通过。
- Compose build --print 输出验证：目标标签绑定本次 scope，Dockerfile/context 来自当前隔离工作树。
- 不重复本地 Full；远端结果与实际发布验证追加在 PR 描述，未执行前不得称为已发布。

构建 `.43` 的旧 CI 结构断言失败保留；`.44` 本地测试通过，随后修正远端缓存环境下的
fake-Docker 测试隔离；`.45` 远端已有组件通过后，新增发布失败重试及归档压缩；`.46` 为最终候选身份，
本地 236 项通过。旧提交未完成任务由新提交自动取消，历史 manifest 不改写。

生产应用不因 CI 配置合入而重启。正式 release/tag 和具体生产部署结果独立记录。
