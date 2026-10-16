# 两用户普通对话与持久请求区间核对

专项维护，不推进 Product Phase。源码检查点 `4e0476c4`；本片未改应用源码或重建镜像，不能将文档 HEAD 当作所有镜像的构建来源。

## 环境准备

复用现有双用户 qualification fixture，仅将 Adapter 服务名准确接到当前浏览器使用的 `runtime-adapter-f6`。v1 误指通用 Adapter 的计划保留 HOLD，未应用。v2 经独立 Sol 审查后，空闲门确认原 24 Root 全关闭、准确 ACK/绑定/签名清理一致，再仅更新 F6 Adapter、增加 B runner 及独立 sessions/state/control 三卷。

原生 Compose 更新退出 0。17 个隔离容器中其余 15 个完整选中字段及按 Destination 规范化的挂载对象均保持，A 原挂载保持；新 Adapter 与 B runner 均健康，仍用 `sha256:ff1390d1f7bfa23e2533eb91e5c9700e48aa9f8b77a44f201bc43ae610b47eb2`，没有新镜像层、构建或下载。

新 Adapter 为 `ae6d19473570ffd919f76e6e34ad17f5232506102935f66648c7374e32dbd057`，B runner 为 `5ae86ad865b0a331c7e9e6222184cc06e3b1b66f542bbca566d49365da582d26`；boot `cc88cee728545b9846eb3174d8cd45a1`，两槽位。控制密钥仅在本机私有 0600 文件，不入 Git/日志。生产未操作。

## 浏览器实际结果

冻结两条普通消息，各发送一次，预期至多两次 provider attempt、0 Job、热执行观察 120 秒，无重试。A 原会话输出 001–080 编号，B 新会话输出独立单行标记；两轮在约 11.3 秒内终结，首次浏览器结果保存于首发后约 47.5 秒。

| 项目 | 结果 |
| --- | --- |
| A/B 普通回复与刷新持久化 | 限定 PASS；A 47/B 2 篇文章，输入均可用，标记不串用 |
| A 旧历史 | 24 Root 和 71 条消息内容元数据不变，旧指定回复仍仅一处 |
| 两次 provider 请求 | 各一个 admitted/completed 配对、HTTP 200，实际 usage 已报告 |
| 身份和终态 | 两个新 Root 的 owner/Workspace/session/trace/generation/cwd/native ID 分离，均 completed/authority closed/unknown0 |
| ACK 与清理 | 各自准确 ACK、settlement hash/sequence、签名清理、process/native close、drain 对应，最终槽位空闲 |
| 业务动作 | 两 Root ingress 均 0，0 新业务 Job，原七个 SignalJob 未重放 |
| 瞬时 active2/held2 采样 | **NOT_PROVEN**；采样在两轮结束后到达，不改写原判据结果，不重发模型 |

停止新增热测后，仅核对同两次请求已有持久日志。A 区间 `[1792194183931,1792194190468]`、B 区间 `[1792194185645,1792194187363]`（epoch ms）交叉 **1718 ms**。该补充证据经独立 Sol → Root **限定 PASS：两个普通 Product 请求在 Adapter 同时在途**，不声称 provider 内部并行计算，也不替代原瞬时采样门。

B 无个人模型档案时，实际使用系统默认的合格 OpenCode Go 路由成功；未要求用户新增 Key。Adapter operations 的 normalized model_calls 仍为 0，不能替代原生 provider journal 的两次实际请求及 usage。

## 证据与未覆盖项

本机原件目录：`.ci-artifacts/agent-origin-consumer-20261015-v1/two-user-concurrent-dialogue-20261017-v1/`。保留固定输入、准确 argv/退出码、配置源 SHA、安装前后 inventory、双流原日志、provider JSONL、完整 scope 的 MAC 验证、Backend READ ONLY 元数据、浏览器 AX/截图及全部 HOLD/NOT_PROVEN。

最终独立审查 `SOL-ACTUAL-REVIEW.json` SHA256：`03e4bcd339a9143f74c4c6983e637408d028a7efe3892b4d15b909890bbe1feb`。Root 收据为同目录 `ROOT-PASS.json`。

active parent/child 进程丢失、迟到旧 MCP、真正业务 unknown、其他 Job 类型等仍未由本片验收。15 参数执行验证延期；运行 guard `900/900/0/180/120` 原样保留，declared max output 32768 的来源未由本片解决，不能宣称限制已全部移除。Full CI、推送、合并、生产均 NOT_RUN。环境、三张浏览器页面及用户原草稿保持。
