# 新会话读取旧结果：限定通过与历史格式缺陷

维护切片，不推进 Product Phase。源码起点 `a6d20958c6804a8eeb8e012d97b4b702ab4a8890`，沿用隔离环境 `byq-dev-e8b02b5475`，未操作生产。

## 实际执行

通过当前浏览器新建会话 `conversation_6f5598bfe81945fdaadee1130f4590c5`，只读取同一工作区旧 ResearchTask 与 BacktestTask。精确 SignalJob `signaljob_e6958c6d072b4955a296dd7cd1243c32` 已完成；信号快照可读，回测未执行。没有新 Job，不表示恢复旧 Agent。

独立 Sol → Root **PASS_SCOPED_READ_AND_SETTLEMENT**：新 native/root/AgentRun 身份独立，两项 authorize allowed、两项读取 settled、两项成功审计；Root completed/closed、unknown0，精确 Gateway ACK13 与 Product 签名清理证明一致。实际6次 provider 请求全部 HTTP200；旧58条消息、21个Root、6个Job、6条接续账本全行不变。工程观察上限20次请求/600秒；未注入产品参数限制。

## 保留失败，暂停扩大批次

浏览器刷新前后原始 articles 比较失败，整批保持 **FAIL_OBSERVER_STOP**。离线逐字符核对确认助手回答完全相同；用户消息有6个换行被持久化为空格。`AgentView` 当轮显示原输入；Backend `conversation_catalog._text` 使用 `" ".join(value.split())`，落库摘要与该规范化结果精确一致；刷新直接回放落库正文。此为真实用户消息格式不一致，不得通过观察器归一化翻成通过。

正在最小修复正文保存；标题/列表预览继续单行，旧消息不改写。另有模型回答提及旧任务许可过期，当前两项读取均获准；原始 MCP ToolResult 尚待从既有记录核对，不把模型文字作为原返回证明，也不重放请求。

## 边界

双用户验证 **NOT_RUN**（尚无第二账号），进程异常后新 child 继续业务、迟到请求与未知业务结果等后续范围仍未完成。参数保持15项空值，保存与限额验证按维护者要求延期。完整CI、推送、合并、生产部署 **NOT_RUN**。

私有原始命令、日志、SQL、截图与审查记录位于 `.ci-artifacts/agent-origin-consumer-20261015-v1/new-conversation-existing-result-20261016-v1/`，包括 `RELOAD-COMPARISON-STOP.json`、`SOL-ACTUAL-REVIEW.json`、`ROOT-SCOPED-READ-PASS.json`。环境和页面保持打开。

## 独立后续修复：浏览器格式切片 PASS

只修改用户正文保存：首尾裁剪后保留内部空白，实际字符数校验保持12000；标题/列表预览仍单行。旧数据不改写。源码 SHA `6e43fbbd087e08dcfd1de9fe327cc6354463c5c63b54bc3e03a2190ca8964703`。候选 Backend 镜像 `sha256:a165162f41a2b890987bf6d55fd0f357dcf73ed7630e0625a0baf9977b73c06a`，由原基底一次 COPY构建；相较当前镜像增加5125字节，层数仍42。七文件/权限读回精确，只有隔离backend-f6更新，其他15容器及全部挂载保持。

当前浏览器正常发送一次多行消息，实际1次模型HTTP200（input36341含cache35200，output75），没有BYQ MCP调用或新Job。新用户消息的3个换行、4空格缩进及双空格在持久化后精确一致；全部4篇文章刷新前后逐字相同，原有2篇未改。新Root completed/closed、unknown0，精确ACK19和真实Product清理MAC一致，slot held0。独立Sol→Root **PASS_SCOPED_BROWSER_FORMAT**；不覆盖旧整批FAIL、handoff问题或生产资格。详见 `user-message-format-fix-v1/ROOT-BROWSER-PASS.json`。
