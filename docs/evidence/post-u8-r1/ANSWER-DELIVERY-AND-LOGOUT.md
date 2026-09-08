# 持久回答投递与注销回执验证（2026-09-08）

仅独立 maintenance worktree、本地合成用户及隔离 PostgreSQL；未部署、未调用付费 API。

## 回答投递

Gateway 复用既有 LifecycleDelivery 的固定 answer 模式，独立文件、锁及游标；
先持久计次再发送，最多 8 次/24 小时，退避与未知结果跨重启保留。
SSE/trace collector 不等待目录 HTTP。只接受精确 session/trace、runtime-adapter
来源的公开 workflow-answer.v1；Backend 的消息身份、角色、正文及工作流序号必须一致。
先前回答待确认或耗尽时不允许后续回答越过它；状态查询不能重置预算。

`answer-delivery-http.py` 在真实子进程写入 Backend 成功后、保存投递 ACK 前
调用 os._exit(17)。父进程重新加载磁盘账本，确认第一次尝试已计次、后续消息未发送；
重复提交后 Backend 仅存在两条消息，workflow_sequence 为 9、10，目录序号为 1、2。
最终运行 PASS；使用加速的合成时钟，不调用模型。首次运行的回答断言通过，但注销
步骤暴露下述真实 500，因此不计整条脚本通过；修复后完整重跑通过。

此验证不证明迟到回答相对后续用户消息的完整锚定，也不证明损坏/缺失 trace 元数据可恢复。
任务自动续接、模型累计预算准入及全部研究语义旅程仍未完成。

## 注销

Backend 原先删除会话后返回 None，违反 dict 响应合同，产生 500；Gateway 吞错，
前端忽略结果。新增测试在旧镜像中真实失败（期待 200、实际 500）。现在 Backend
返回明确成功回执；Gateway 对未知回执返回 503，保留 cookie 供同一身份幂等重试；
前端仅在明确成功后清理身份并跳转。不得将未知结果提示成成功。

Chrome MCP 使用独立合成浏览器上下文及 localhost:18261：

- 桌面 1365×900：注入一次前端 fetch 503（这是 UI 故障注入，不是实际网络故障），
  点击退出后仍保留用户及页面，显示“注销结果尚未确认，请重试退出登录。”；
  再次点击通过真实 Gateway/Backend HTTP 200 后返回登录页。
- 手机 390×844：登录后打开产品导航、用户菜单并真实注销，返回 /login。
- 两种尺寸无横向溢出；浏览器 console 无 error/warn。已检查的请求走同源 Auth/Product API。
- Community 用户菜单及会话实现已只读检查并分类，见 migration inventory；不移植旧认证路径。

## 最终回归

- Backend：414 passed、1 skipped、7 subtests passed，538.63 秒。
- Gateway：175 passed，2.39 秒。
- Frontend：53 files / 170 tests passed；类型检查及生产构建通过。
- 架构及共享合同：83 passed、3 subtests passed。
- Backend/Gateway 各有既有 Starlette 弃用警告；前端单测有组件 stub 警告，实际浏览器无警告。

这些是本地证据，不替代远端 CI、发布认证或生产观察，不修改历史 U8 失败结论。
