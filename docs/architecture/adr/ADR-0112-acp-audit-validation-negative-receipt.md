# ADR-0112 — ACP审计校验的精确负回执

- Status: **Proposed — 等待维护者接受，尚未授权实现本片**。
- Date: 2026-10-16。
- Scope: 仅普通Product ACP的`byq_agent_audit`；不推进Product Phase。
- Related: Accepted ADR-0094、ADR-0109、ADR-0111；不扩大ADR-0109的authorize专用合同。

## 实际问题

原生child记录证明，两次正确身份的audit请求因detail中的公开字段
`authorization_decision`在INSERT前触发422，MCP将入口结算为unknown，Root无法关闭。
字段误判已单独修补并通过19项离线测试，尚未安装。仍需避免其他可证明无写入的校验拒绝
使同类会话永久阻塞。普通HTTP状态、模型描述或后续成功调用不能替代精确证明。

ADR-0109仅接受`byq_agent_authorize`的`role_tool_not_allowed`负回执，
没有授权audit校验负回执或通用4xx放行，因此本片单独记录具体决定。

## 提议决定

1. 仅当Backend在精确pending ingress的事务和身份锁下，证明audit的确定性校验
   在任何audit INSERT或其他业务副作用之前拒绝，才可签发私有负回执。
   绑定owner/workspace/actor/session/trace/root/boot/native AgentRun、tool、
   mcp_request_id、输入摘要和观察事件身份；caller不得自证结果。
2. 复用现有ingress/settlement账本持久保存同一拒绝事实。回执只证明该audit没有写入，
   不证明其他业务动作未执行，也不授予权限。不建设通用调度器、第二套Harness或恢复协调器。
   凭据过滤、合法公开字段的有限枚举、业务授权与用户取消均保留。
3. MCP仅凭这份匹配的Backend证明，将同一入口结算为known denied。
   普通422/其他4xx、5xx、超时、缺失/错配回执或可能已写入的结果仍按unknown保护，
   不重发audit或业务动作来消除不确定性。
4. 区分响应丢失的位置：未证明负结算已提交时仍pending/unknown；若Backend已经提交精确
   denied结算而结算响应丢失，MCP仍向调用方报告unknown、不重放。后续Root仅可依据
   Backend对同一最终ingress游标/摘要的精确终态ACK及已确认runner清理闭合，且其他结果均已解决。
   不宣称此前响应已送达。已持久化的unknown行不可改写。
5. 重复提交同一准确负回执的结算必须幂等；不得重新执行audit handler，不得跨用户、
   跨Root、跨boot或改变输入后复用。旧unknown和现有未闭合Root不因本ADR或软件升级变成PASS。

## 最小验收

- audit校验负例无INSERT，有准确持久负回执；正常audit仍写入并正常结算。
- 错误tenant/root/boot/native/AgentRun/request/event/input摘要、非pending状态、伪造和迟到证明均拒绝。
- 并发/重复结算幂等；未提交前丢响应、提交负结算后丢响应分别记录，旧unknown不可升级。
- 普通422、5xx、超时及不确定写仍受保护；精确终态ACK和runner清理门保留。
- 定向离线测试 → 独立Tester/Sol → Root PASS后，才按已有维护授权和有限批次补必要Product验收。

## 执行边界

维护者接受本ADR后，即可在当前隔离维护分支实施上述窄合同并进行定向离线验证。
接受本ADR不要求用户再申请“接续许可”，不扩大Product DSH权限，不授权重放旧请求、
清理数据库/卷或生产部署。推送、合并、生产和正式版本门禁仍按现有对应授权分别执行。
