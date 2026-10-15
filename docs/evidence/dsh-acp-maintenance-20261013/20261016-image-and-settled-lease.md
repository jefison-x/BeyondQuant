# 2026-10-16 隔离镜像、旧接续租约与已有 Job 结果核对

本轮为 DSH / ACP 维护，不推进 Product Phase。应用提交：`6975bd18a3df48fa372def36f8fb64935978aea9`。
工作树：`/home/jefison/.codex/worktrees/dsh-acp-maintenance-candidate/BeyondQuant`。
复用原测试账号、数据库卷和浏览器会话，没有生产更新。

## 镜像与体积

以已有冻结清单核对 483 个源码映射文件和独立 SDK lock；Backend 复用原读回，Gateway/MCP/ACP 修复后原生读回通过。
权限修补只修改目录权限，没有递归复制或 chown 运行时文件。以下是 Docker 报告的存储体积增量，不是全镜像解压体积：

| 修改 | 存储增量 | 新增 RootFS 数据层 |
|---|---:|---:|
| Gateway 目录权限 | 833 字节 | 1，history 16.4 kB |
| MCP 目录权限 | 374 字节（配置） | 0 |
| 统一 ACP 目录权限 | 1,123 字节 | 1，history 73.7 kB |
| Gateway 本次租约修复 | 52,555 字节 | 1，单次 COPY，history 295 kB |

本次 Gateway 仅 COPY 已冻结的 `app/main.py` 和一个测试文件，文件 0444、目录 0555；
65 个映射文件的哈希、原始权限/属主及完整目录清单均匹配。
继承 USER/CMD 不变，revision label 指向上述提交。
新 Gateway 镜像：`sha256:67045fd75b3f9be955574fad48a38c4b4190c18f3092e7951ce769769b6cfc3c`。

先完成四份加密备份和完整认证解密/清单检查，再更新隔离环境：
先前五服务聚合更新通过；本次只替换 `gateway-f6`。
其他 15 个容器 ID、镜像和端口不变，全部 16 个容器挂载保留；15 个健康，Worker 无健康检查。
备份清单检查不等于恢复演练，也不宣称跨卷原子快照。

## 旧结算记录占用接续租约

实采发现新 SignalJob 已完成，但新预留仍 reserved/dispatch 0。
Gateway 日志先对账旧 settled 预留，随后未读取新预留的 Runtime 收据。
定向回归证明：旧 Backend settled、Runtime 明确缺失且精确 prompt reconciliation 为 unknown 时，旧本地租约仍会挡住后续不同事件。

修复仅在精确 Runtime missing-record 和官方 `prompt-receipt.v1/outcome_unknown` 形状下，
验证 Backend 已结算记录的身份、一次派发、run、typed usage、profile/limits、outcome 与 canonical 摘要，
再在锁内释放同一且无任何取消标记的租约。旧 prompt 不重放；未结算、冲突、网络错误和其他未知形状保持原保护。

补丁前单用例出现目标断言失败；原 RED 替身少 schema_version，但旧代码只读取 state，该差异不改变旧分支因果。
GREEN 替身已按官方形状修正，红绿不是相同测试字节。完整 delivery 模块 **103 PASS**；
原生退出 0、无 OOM、准确清理，局部 dev-check 通过。Tester、独立 Sol、Root 离线门通过。

## 真实结果与失败边界

原浏览器只提交一次新 Job：`signaljob_f35d7e1ff26e4ed2a2470124af041012`。
首次未自动接续的批次保留 **FAIL_STOP_REAL_BACKGROUND_NOT_DISPATCHED**。
更新 Gateway 后，原页面无需新输入便自动读取同一任务和同一 BacktestTask，并显示信号生产完成、回测尚未执行。

预留 `continuation_67ab8b63d28cbed9bba2321288648982` 只派发一次并结算；
consumer root `20f58512a06745448c0266b3625d4ce3` 完成、授权关闭、unknown 0。
Runtime terminal、Backend 和 Gateway ACK 的序号 109、boot、root 和事件摘要相同。
消息 22→23、Root 10→11，新增一条 assistant 回答；旧消息/Root/4 个 Job 行不变，Job 与预留总数均保持 4。

最后采集误用了普通回合的 provider journal 文件名，原生命令在 terminal GET 200 后断言失败。
此批单独保留 **FAIL_OBSERVER_STOP**，没有重跑模型。
静态审计后，另批只读一次官方 Runtime continuation receipt：0 新模型/Job/输入，原生 0，
其 exact run、known usage（7 次 provider attempts）、profile/limits 和 canonical 结算摘要与已存 Backend 记录一致。
限定已有 Job 恢复的组合证据经 Tester → 独立 Sol → Root 通过，原失败批次不改标。
不为逐次 HTTP 状态额外追日志：该项 **NOT_RUN**。后台读取有准确授权和成功审计，不冒充独立 native domain-result 读取。

Gateway 重启会清除本地内存占用，因此上述组合仅证明**已有 Job 的限定恢复完成**；
连续运行时“旧 Runtime 终态缺失→下一个事件”的真实回归仍 **NOT_RUN**，软件因果由定向回归证明。
不宣称恢复原子 Agent。真实新版本取消/委派/进程异常/两用户与迟到请求等未覆盖项目仍分别保留。
推送、远程 CI、合并和生产部署 **NOT_RUN**；当前环境与原页面保持打开。

## 准确私有证据入口

证据根：`.ci-artifacts/agent-origin-consumer-20261015-v1/`。

- `native-image-readback-v1/ROOT-LOCAL-IMAGE-PASS.json`：原生哈希/权限/目录与体积；首轮权限及观察器失败均保留。
- `aggregate-local-apply-v1/ROOT-LOCAL-APPLY-PASS.json`：先前五服务更新及备份。
- `current-image-browser-ordinary-v1/ROOT-ACTUAL-PASS.json`：新聚合镜像普通对话、持久化和 ACK 通过。
- `current-image-browser-background-v1/ACTUAL-RESULT.json`：首次后台停滞。
- `settled-continuation-lease-v1/ROOT-OFFLINE-PASS.json`、`GREEN-ENTRY.json`：准确源码哈希、命令、原生红绿日志与独立审查。未采集的 RED/GREEN UTC 起止明示 NOT_RECORDED。
- `settled-continuation-lease-v1/image-v1/ACTUAL-RESULT.json`：精确镜像、原生命令、65 文件核对与体积。
- `settled-continuation-lease-v1/local-gateway-update-v1/`：完整 preflight/rollback、备份、容器前后快照、失败原件、单次后置只读收据、浏览器截图和独立审查。
