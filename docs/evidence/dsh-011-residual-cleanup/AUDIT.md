# DSH 0.1.1 残留清理

维护者授权：“好的，清理残留。”范围依据 Accepted ADR-0069 修订，不推进 Product Phase。

- 移除旧 SDK 兼容实现及专属测试；仍适用的规范化、取消和进程清理测试使用 0.1.2。
- 四份旧 Dockerfile、双版本部署准备及演练脚本和专属测试转为 `.archive`，保留原始字节。
- 当前 profile 和隔离栈只接受 0.1.2；旧 composition/provenance CLI 仅允许核验；不再生成旧 release identity 或 rollback policy。
- 生产 runtime 镜像不包含 `/app/tests` 或 runtime helper 的 `.test.js`；CI 在同一镜像上只读挂载测试，并在未挂载时检查实际镜像内容。
- 保留历史 release/build manifest、许可档案、历史 profile/registry/policy 及校验函数。当前来源策略仍识别历史 evidence；这是读取已保存证据，不是运行旧 SDK。

`.39` 初次架构检查暴露历史测试对已移除入口的假设；`.40` 文档和223项架构测试通过后，继续清理脚本中不可达的旧分支。完整资格结果以本任务 PR 为准，不能把中间构建视为部署制品。

现有 `.38` 生产制品没有在本地源代码编辑时发生变化；本任务的合并与部署状态须另行记录。
