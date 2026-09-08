# 原会话任务发现与三轮恢复（2026-09-08）

R1/F4/F7 的独立实现切片；不是全部整改完成或生产部署认证。

## 确认的缺口与修复

任务创建成功后若根回合在公开回答前失败，原任务 ID 只在私有工具结果中。
新根只能恢复公开上下文，既有 `byq_research_get` 又要求精确 ID，原 MCP context 无任务摘要。
不能靠工作区最新对象补齐，也不能把私有 DSH 会话重新注入公开恢复。

新增 Backend 原会话只读投影和 `byq_agent_context.research_context`：精确核对可信
owner/workspace/session/trace/Product actor、活动用户/个人工作区/成员关系/会话，
最多 20 个原会话候选、400 code point 目标摘录。无自动选择、自动创建、续接或授权。
MCP 严格封闭校验、128 KiB/8 秒上限；不可用与没有绑定任务分离，错误正文不外泄。
旧无绑定任务不猜测补绑，最新明确用户目标优先。详见
[合同](../../contracts/agent-research-context.md)；Community 研究合同已检查并分类。

## 测试与保留失败

- 新接口初始 4 failed / 3 passed（接口缺失，负例通过不计作实现完成）；实现后 7 passed。
- 增补检查初次 2 failed / 8 passed：测试把实体类型写成 `task` 而非 `research_task`，
  且漏列既有身份层的 401。仅修正夹具，保持真实跨 owner 拒绝与数据不外泄断言。
- 最终 Backend 完整 **490 passed / 1 skipped / 7 subtests passed**，395.26 秒；
  隔离临时 PostgreSQL，保留镜像仅作依赖载体、源码只读挂载。自动 cleanup verified。
- 初始 MCP 单容器遇到临时 dist 权限；修正后新摘要、真实 server wire 等通过，但完整脚本
  缺配套 Backend/token 而失败，不计全套通过。随后正式 CI 被旧 `.11` 源漂移门禁拒绝。
- 新 `.12` 独立清单后，正式 `--only=architecture,mcp` **3/3 checks passed**：
  架构 224 项、MCP 编译和全部测试脚本，包括真实隔离 Backend/HTTP 合同；scope
  `post-u8-research-context-20260908-12` 自动清理后另行 verify-only 通过。

候选 `.12` 清单 SHA-256：`71e1e6b142d588329c6a1788a129d68c5310ae086d5c8e33f75b9729e5637650`。
兼容清单：`206f5fb2f1791bb146b3c77ef7da027dcc10cf696ab0c46e193c406fd0e1b588`。
历史 `.11` 及其认证不覆盖新源码，未修改历史清单。

## 真实三根回合

全新内网 scope `post-u8-recovery-wire-20260908-12`；Backend/Gateway/MCP/官方 DSH
Runtime/PostgreSQL 和不转发请求的脚本 Provider。无 Data/ML/Signal Worker、生产凭据或付费请求。
合成会话 `conversation_5ee565d5fa9f4dd5a5cd9a6400918b6d`：

1. 沪深300、近三年、普通动量双均线、每周调仓、先研究凯利仓位：注册→创建原任务→
   两个不同无效输入，真实 `domain-correction-stopped`，4 次本地请求，无公开任务 ID。
2. 原会话“继续”：新进程首请求含原未回答目标，但不含任何具体 task ID；通过 MCP context
   发现唯一原 ID，再经 research_get 读取完整原目标。3 次本地请求，不重新创建任务。
3. 明确改为中证500只讨论方案：新指令完整送达独立新进程，脚本仅回答不执行。1 次本地请求。

共 8 次本地请求。最终一条 planned 原任务、一个 failed AgentRun、零 Artifact。
历史失败和两个后来成功回合并存；后两轮回答均经持久消息核对。

首次驱动漏掉前端已有的 `/resume`，第二轮 409；补齐后沿用原会话，并未重跑首轮。
第三轮紧接 session.result 时被回答持久化屏障 503 拒绝；只读确认随后 answer-delivery
为 up_to_date、回答已落库，再继续原第三轮。驱动现等待持久回答，不降低屏障或盲重试。
首次 409 前保存的那条未执行“继续”消息保留，未删除测试失败历史。

可复现脚本：[Provider](f7-recovery-provider.py)、[Product 驱动](f7-recovery-probe.py)。
Provider 依赖本目录 `f7-native-provider.py` 只读挂载为 `native_provider.py`，仅复用 SSE/字段解析。
此为 scripted transport/evidence 验证，不宣称真实模型自主对象选择、完整研究或全部 F7 已验收。

未 push、merge、部署、续跑历史研究或扩容 Tushare。验收后上述独立 scope 的容器、合成卷、
网络及镜像标签已由既有清理器移除，cleanup verified。合成数据可由夹具重建，未保留数据库备份。
