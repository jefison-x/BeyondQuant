# DSH 0.1.2rc1 规划文档验证

日期：2026-09-05。Scope：documentation only。

工作树：`/tmp/byq-dsh-012rc1-upgrade-plan`。
分支：`docs/dsh-012rc1-upgrade-plan`。
规划基线观察：`610f1d6d356530d8a4fb25754bc771a92a32dad7`；后续执行必须重新 fetch 并派生实际基线。

## 检查结果

- `python3 scripts/ci/check-docs.py --base origin/main`：通过本次 Markdown 链接/编码检查。
- `git diff --check`：通过。
- `python3 -m unittest discover -s tests/architecture -p 'test_*.py'`：75 tests，OK。
- 自审：U0–U8 串行与默认版本边界明确；T01–T40 分层；U6 不要求尚未发生的 T40 生产观察。
- 自审：候选测试入口与正式资格分离；attestation 与镜像构建输入分离，避免两种认证循环。
- 自审：实际新版 SDK 参数移除、旧 demo/spine 包缺新版、minimal 默认 coding 工具、业务 provenance
  字面量及 CI 可变镜像复用风险已在对应阶段列出。
- 自审：每个新路径/CLI 均标为拟新增；没有将未实现工具作为当前执行命令。

官方精确 release/API/npm/PyPI 证据链接收录于[主方案](../../../roadmap/DSH_012RC1_UPGRADE_PLAN.md)。
本次检查的是公开源码/metadata 与当前 BYQ；未下载并运行新版完整 artifact，未进行 U0 载体资格验证。

没有修改 runtime、依赖锁、业务服务或生产配置，没有运行生产模型、迁移数据库或部署服务。
没有将 ADR-0058 标记 Accepted，也没有把维护阶段或任何新版测试标记完成。
文档-only 修改无需重跑业务/浏览器/真实模型 suite；本记录不能用作 U0–U8 的运行验证证据。
