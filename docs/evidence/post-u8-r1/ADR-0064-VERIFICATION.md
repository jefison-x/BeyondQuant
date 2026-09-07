# ADR-0064 首版隔离验证

日期：2026-09-07。维护者明确批准 ADR-0064 后，在独立修复 worktree 实施。
不推进 Product Phase，不变更生产服务、历史报告或冻结构建身份，不恢复历史研究。

## 结果

- Runtime：118 passed，11 skipped；跳过项为显式 opt-in 集成/付费测试，不计通过。
- Gateway：153 passed。
- 架构及 WorkflowTrace/AgentRun 合同：83 passed，3 subtests passed。
- 真实 DSH 0.1.2rc1、Adapter HTTP/SSE、Gateway、MCP、Backend 隔离链路：4 passed，1 paid deselected。
  其中新增两项真实进程组 SIGKILL→原卷新 Adapter→独立 Gateway 重扫：普通用户和禁用用户。
  每个崩溃场景恰好两次本地合成 Provider 请求；恢复没有增加模型调用，原 prompt 摘要返回
  原 run，重复核查不产生第二终态。普通用户直接验证 AgentRun interrupted；禁用用户通过
  精确内部回执确认，同时普通查询仍返回 401。
- 单测覆盖锁竞争、真实持锁进程死亡、复制卷/缺失锁拒绝、损坏日志/跨身份拒绝、
  首终态不改写、序号高水位、原提示幂等冲突、存储失败不启动模型且关闭资源、
  Gateway 重启及请求中死亡不重置恢复预算。

首轮新增测试在实现前因缺少 lifecycle_journal 模块而收集失败；这只是缺实现基线，
不是行为断言失败的完整红绿证据。已有 FastAPI/Starlette/WebSocket 弃用警告未在本次扩大处理。

## 限制

同次 Linux 启动、原本地卷及原锁身份是自动恢复前提。主机重启、复制/恢复卷、日志缺失、
身份不明、网络文件系统一律拒绝自动收尾。8 MiB 上限及每事件 fsync 尚未做长会话性能认证。
不增加通用恢复队列、不恢复业务任务/审批、不调用外部付费 API。未验证生产或完成独立发布认证。
其他 Post-U8 需求仍按原清单推进，本报告不宣称全部整改完成。

## 清理

按已批准的受限清理例外，移除本轮 `byq-ci-r2-recovery-20260907` 隔离项目的三项服务、
两个合成数据卷、测试镜像和网络。合成数据未备份，可重新构造；生产及私有备份未改动。
终态仅保存 run_id 的最终版本再次通过 Runtime 118 项及真实链路 4 项。
