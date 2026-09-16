# H4：研究对象精确回读

2026-09-13，依据 Accepted ADR-0062 的原身份恢复合同，Product Phase 97 不变。

统一 fetchByqResearchGet 原先将任意对象形状的 HTTP 成功响应视为读取成功。
现对 ResearchTask、Experiment、Artifact 强制返回 ID 与请求 ID 一致；缺失、null、数值、
其他 ID 均返回 invalid_response，不把错误对象内容交给模型，也不调用写接口。
已确认 submission-watch 的恢复读取复用这一校验。Backend 权限和数据过滤保持原合同；
本次为响应合同防御，不宣称生产发生过数据串读或解决所有恢复风险。

测试先复现缺失 ID 被接受，再验证三类对象的15个输入组合和1个已确认回执错对象恢复场景。
MCP TypeScript build、research-watch、research、write-outcome、research-context 四个测试脚本通过。
既有错误/未知结果处理和正确读取路径继续通过。未执行完整远端 CI、真实服务集成或模型研究。
无 UI、数据库结构或权限变更，无生产操作。最终独立构建 .59，历史清单保留。
完整 H4/F2/F7 和 H5 尚未关闭；本地交付，不自动推送、合并或部署。
