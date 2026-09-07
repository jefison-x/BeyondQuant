# 首版任务许可持久化验证

2026-09-08，隔离分支 `fix/post-u8-conversation-recovery`，依据 Accepted ADR-0062/0065。
原 ResearchTask 新增可空 continuation_permission；历史任务保持 NULL，不追溯授权。
首版允许明确 token 额度和 validated 同任务制品确认、个人登录查询、精确版本撤销。
用户/工作区/成员关系、会话和任务数据库锁保护许可创建；同键重放不刷新时间或额度，
并发连接返回同一许可，不允许替换/增额，撤销不能复活。普通 task 返回不含内部许可内容。

当前只保存许可，不存在模型启动、预留/结算或通知消费者。can_start 始终 false；
金额请求被拒绝，token_limit 不是已经验证的执行器硬限额。首版每任务只有 version 1，
没有续期/增额功能，UI 控件及浏览器功能验收仍待完成。

## 验证

- 初始新增数据库测试 13 通过（17.42秒）：重启、相同请求、额度冲突、撤销、身份隔离、
  非法数值、未知字段、错误制品及两个独立连接并发。不把线程测试声称为真实进程崩溃验证。
- 最终 Backend 全量 413 通过、1 跳过、7 subtests 通过（480.70秒），包含后补到期/错误版本和 API 测试。
- 许可 API 版本 Gateway 全量 154 通过（2.18秒），新增个人 cookie、确认 header、
  跨站拒绝、模型/部署身份不能授权及 owner header 覆盖测试。
- OpenAPI 新路由最初缺失，架构门禁 1 失败；补齐路径、个人登录及封闭请求 schema 后
  83 通过、3 subtests 通过（4.35秒）。未降低架构门禁。
- 真实 HTTP：隔离 Gateway 登录 → Backend 原任务/制品合成准备 → 明确确认 → 重复提交
  与查询 → 撤销 → 禁止增额/复活 → 退出后拒绝，全部通过。脚本为同目录 permission-http.py。
  首次脚本用错 Gateway 端口而连接失败，未发生写入；改为实际 8100 后通过。
  此轮退出断言只覆盖 Gateway 可见结果；后续进程丢失演练发现 Backend 注销响应 500
  被 Gateway 吞掉，已另行修复并以真实浏览器及完整回归验证，见 ANSWER-DELIVERY-AND-LOGOUT.md。

全量测试使用构建镜像，不挂载替代应用代码。测试数据库严格为 byq_domain_test；HTTP 场景
使用同一专用 CI PostgreSQL 的合成 byq_domain，与全量夹具数据库分离。没有生产访问、
外部 Provider、付费 API、训练、Runtime 进程、远端 CI、合并或部署。
