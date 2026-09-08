# F7 部署后模型接入修复（验证进行中）

维护者授权：修复 F7 部署后问题，验证后推送/合并并重新部署生产；关键验收可经 BYQ
调用付费模型。2026-09-09 补充明确允许向 OpenCode Go 发送不含用户身份的独立
会话标识及客户端名称。不得自动重跑真实历史研究、启用 F6 或扩容 Tushare 数据。

已确认失败发生在模型请求阶段：官方返回 `INVALID_REQUEST` / `MissingSessionID`，
约 0.9 秒，无领域工具执行；不是 180 秒研究超时。原始错误正文属于私有证据，不进入公开 trace。

官方要求参见 https://opencode.ai/docs/go/#where-can-i-use-it 。锁定 DSH 源码
`a66e4702047846cdaa10c66c9d3df3951f5ea70d` 的 `llm-pi-ai/config.ts` 支持 provider
headers；`adapter.ts` 保留 Harness 自身 attribution 优先级。使用既有官方配置入口，
不 fork、升级、回退或拦截 DSH 请求。会话标识派生于随机 BYQ session ID，跨 root
进程保持一致；不包含 owner/workspace 或公开 session 文本。所有三条 Go 协议路由配置。

Community 只读参考：`frontend/src/components/agent/XiaobaAssistantDrawer.vue`
错误展示直接回显 `error.response?.data?.detail || error.message`，分类 REFERENCE_ONLY。
新实现继续沿 BYQ 规范化 WorkflowTrace 的闭合错误码映射，不复制原始异常回显。

当前状态：配置测试 3 项通过；候选运行时兼容和进程测试 94 项通过。
最初隔离测试包挂载路径错误导致收集失败，修正后通过；不算产品失败或资格通过。
真实协议 wire、完整 CI、付费验收、远端合并和生产部署尚未完成，不能引用旧构建认证。

## 后续验证进度

真实官方 0.1.2rc1 进程 + 派生 Product profile + loopback Provider/MCP：三种 Go 协议
全部通过，HTTP 400 每种仅一次请求，稳定标识到达 HTTP wire，错误码归一且原始正文不泄漏。
跨 generation 保持相同标识、不同 session 使用不同标识由额外环境合同断言覆盖。
这些是无密钥协议验证，不声称真实 OpenCode Go 付费回答已通过。

完整 CI 首轮 scope 未满足既有制品保留命名要求，主动 SIGTERM（143）停止，独立清理
确认通过；缓存保留。替代 scope 为 `local-u7-f7-provider-repair-20260909`，运行中。

生产应用私有备份 `application-20260908T222954Z` 完成；逻辑备份
`baseline-20260908T223400Z` 为同一只读快照，113 表，2,289,118,986 bytes，SHA-256
`addf0892074f76c9832fba1db65451caad08b8e5079ee6e3e5ae1cbd5332ae91`，目录读取校验通过。
本次未做实际恢复，不以旧恢复结果代替新备份的实际恢复验证。无数据库 schema 修改或回滚。

浏览器门禁尚缺：Chrome MCP 未找到 `DevToolsActivePort`，Ubuntu Chrome 未运行，
当前执行环境无图形 DISPLAY。已请维护者恢复之前的 Chrome 调试连接；不绕过浏览器门禁。
当前没有推送、合并或部署新镜像，没有调用真实付费模型。

部署准备脚本尚未执行：只允许主线已同步且 `.17` 清单匹配后生成新私有 release。
运行时、Gateway 数据卷保留，同一 DSH 版本继续使用当前 namespace，避免遗失持久终态回执。
排空后停下两个日志 writer 并备份，再以 `--no-deps --no-build --pull never` 替换五个
应用服务；其余六个服务的容器 ID、启动时间和镜像必须保持不变。失败保持关闭准入，
不回退数据库、重放研究或执行删除。镜像使用保留制品的可读标签，同时核对不可变 image ID。

## 本地完整验证结果

替代 CI scope **26/26 PASS**，独立测试资源清理验证通过。Architecture 228；
Backend 499 pass / 1 skip / 7 subtests；Gateway 202；兼容基线 Runtime 149 pass / 35 skip；
候选 Runtime 158 pass / 26 skip；真实候选进程 23 pass；Frontend 176；模拟浏览器 20；
真实 Product API 浏览器 9。重启持久化、两用户隔离和完整 Product coherence 通过。
两版 20-cycle 无残留线程/会话，候选峰值 RSS 284.039 MiB、中位耗时 0.837197 秒。
模拟浏览器仍出现既有非致命 ResizeObserver 警告，不掩盖为零告警。

独立 `.17` 清单：候选 SHA-256
`0d07dc38d133bbfbed04b7bb8f371bbc51a717a86c9ca935406606d03c60c461`；
兼容基线 `76e19a950704dbd9dea6e675652cdb18dcd1e8552e7958ac1ecd6025e8c8b67d`。
保留 7 个受测镜像，归档 462,365,184 bytes，SHA-256
`6c69f4b63ca0b8e3dad5a306b6468d4f05552c69d2f4613ac467c63d2ff55081`。

这些结果取代上文相应的“运行中/待 wire”状态，但 **Chrome MCP 复核仍 BLOCKED**。
Playwright 通过不是 Chrome MCP 审查。维护者恢复 Ubuntu Chrome 调试连接后继续；
此前不推送合并或部署。真实付费模型调用为零；不得声称付费 OpenCode Go 回答验收通过。

## 维护者取消工具专属门禁 — 2026-09-09

维护者明确取消 Chrome MCP 测试要求；ADR-0059、AGENTS、开发流程及 CI 政策已同步修订。
上文 Chrome 连接失败仍是历史事实，但不再构成独立发布阻塞。已通过的真实 Product API
Playwright 浏览器证据按其实际覆盖采纳；不会声称执行过 Chrome MCP 或付费模型验收。
本次仅规范文档变更，不改变 `.17` 制品输入；远端 CI、合并和生产部署仍需实际执行和核验，
不得因取消工具限定而宣称新镜像已经上线。未卸载系统 Chrome 或修改插件配置。
