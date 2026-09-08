# F7 迟到 HTTP 与新根回合隔离（2026-09-08）

状态：本切片隔离实测通过；不关闭 F7。

PR #263 合并后，从同步后的主线建立独立 `test/post-u8-late-http` 工作树。
仅增加 Engineering 合成探针，不改变 Product 实现、生产配置或 DSH，不提交伪造的调用凭证。
ADR-0066/0067 两工具限制保持；本切片只验证策略工具，不能推广为 ML 或全动作通过。

## 设计

- 官方 .12 root-turn composition + 本地非转发 Provider + Gateway/MCP/Backend/PostgreSQL。
- 第一根：创建唯一合成原任务，先 schema 拒绝，再不同输入修正失败，根终态。
- 第二根：通过公开 MCP 发现原任务，独立注册，新根首次 schema 失败；保持模型请求等待。
- Engineering 驱动只读合成数据库中实际投递的私有证据，重放第一根的 HTTP 请求；
  不读取生产数据，不把私有身份提交给模型，不插入/修改证据或改写任务状态。
- 验证原回执稳定、换根/换 generation/未观察的新内容均拒绝，claim、bucket、Artifact
  不因负例改变。取消第二根，再核对精确原回执，不能重开业务执行。
- 所有请求经过实际 MCP HTTP handler；数据库只用于只读断言，不代替 Agent-to-Domain。
- 重放按实际证据和固定夹具重建语义相同的请求，不是截获并延迟原 socket；
  因此它补充根身份负例，不冒充原连接在途提交竞争已全部验证。

## 限制

这是脚本 Provider 的确定性传输资格测试，不是真实模型语义评测；没有付费调用。
不声称覆盖 ML、有效 Artifact 提交中的撤销竞争、提交后断网未知回执或全部并发认领。
当前 composition 明确串行，未启用并行 child 来制造通过。
失败记录保留，未执行不计 PASS；仍以整个 ADR-0067 门禁为发布前提。

源绑定使用已合并的 .12 candidate：
`sha256:71e1e6b142d588329c6a1788a129d68c5310ae086d5c8e33f75b9729e5637650`。
新增 evidence 脚本不在应用 build source inventory 内；检查通过不等于探针通过。
隔离 scope `post-u8-late-http-20260908-12`，清理后不保留合成数据库。
复现脚本：[Provider](f7-late-http-provider.py)、[HTTP 探针](f7-late-http-probe.py)，
依赖已归档 `f7-native-provider.py` 的两个纯测试编码辅助函数。

## 实际结果

合成公开会话 `conversation_66fb7815498544cd926b98e120940ff8`：两次根回合确实使用
不同 root 和 generation，第一根 failed，第二根测试中保持 active，随后由 Product API
明确 hard cancel，最终 cancelled。没有 session.result，历史失败事件仍在。

- 旧请求原样重放两次只返回原 schema 拒绝，未增加 claim。
- `old-body-new-root`、`old-body-new-root-generation`、`old-key-unobserved-change`
  三个真实 HTTP 负例均返回 `call_evidence_pending`，前后整个只读状态快照相等。
- 新根原请求独立保存首次拒绝，取消后精确重放仍保持原回执；不重开模型或业务操作。
- 始终只有 3 份实际调用证据、3 份 correctable_failure claim、0 个 Artifact；
  本地 Provider 共 8 次请求（包含被取消的新根等待请求），不是 8 次付费调用。
- Backend/Gateway 独立重启、健康后，重放两个原始失败回执再次通过；两根终态、3 个
  claim、0 个 Artifact 和 8 次 Provider 请求不变，没有自动执行新研究。
- MCP 响应未暴露内部 proof 字段、原 root 或 generation；不扩大为全公开接口泄漏审计结论。

本切片没有实测失败；准备时通过源码核对更正了 MCP 端口和取消请求格式，未以生产试错。
静态语法、源绑定与差异检查通过，1 份新增 Markdown 链接检查通过。
独立清理返回 `CI cleanup verified: post-u8-late-http-20260908-12`，本次合成容器、卷、
网络和镜像标签已清理，数据可用夹具重建；生产、Community 和其他工作树未修改。
有效 Artifact 提交中撤销、ML 对应矩阵、未知结果/回执丢失联合测试仍需后续切片。

本次实际 candidate 镜像 ID：
`sha256:b20ebd1b3e28b78f28c5458d776b4ccac298c70e95d4b8dcb70cd6eb5767c0bb`。
