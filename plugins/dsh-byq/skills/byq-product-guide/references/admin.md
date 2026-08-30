# 管理员功能

- `/settings/system/overview`：系统、数据源、缓存、数据库、模型、Agent、预算、运行时、Workflow、访问和审计的安全投影。
- `/settings/system/data`：Tushare 写入保密凭据、证券目录、手动/每日/小巴按需同步任务、数据覆盖和 readiness。小巴只提交有界需求并读取结果，Provider 调用仍由可信数据 Worker 执行。
- `/settings/system/plugins`：插件资格、期望启用策略、部署请求和实际 runtime identity；不支持在线安装或热修改。
- 这些入口仅管理员可用。管理员工作区中的小巴可提交有界数据需求，但不能获得管理员、Docker、Git、部署、Provider 或数据库权限。
