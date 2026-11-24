# 管理员功能

- `/settings/system/overview`：系统、数据源、缓存、数据库、模型、Agent、预算、运行时、Workflow、访问和审计的安全投影。
- `/settings/system/data`：数据源保密凭据、证券目录、全量手动/每日同步任务、数据覆盖和可用性均由管理员管理。小巴可在用户自己的活动研究会话中提交有界研究补数，也可读取管理员范围内的结果；补数由系统后台执行。
- `/settings/system/plugins`：插件资格、期望启用策略、部署请求和实际 runtime identity；不支持在线安装或热修改。
- 这些管理入口仅管理员可用。普通用户的会话补数不授予管理员、Docker、Git、部署、Provider 或数据库权限。
