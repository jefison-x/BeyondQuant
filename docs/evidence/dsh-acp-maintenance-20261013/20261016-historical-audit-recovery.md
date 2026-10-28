# 历史普通审计核对与浏览器恢复（2026-10-16）

专项维护，不推进 Product Phase。隔离工作树分支 `codex/dsh-acp-maintenance-candidate`，功能源码 `a6d20958c6804a8eeb8e012d97b4b702ab4a8890`。依据已接受的 [ADR-0113](../../architecture/adr/ADR-0113-historical-audit-unknown-reconciliation.md)。

## 本片结果

| 层次 | 结果 | 边界 |
| --- | --- | --- |
| 历史核对 | PASS | 真实 Product 签名清理回执通过 MAC 核验；binding 仅追加退出证明；Backend 单次原子事务关闭旧 Root 和两个 AgentRun |
| 原始审计 | 保留 UNKNOWN | 原 8 条 ingress 全行不变，序号 5、6 仍 unknown；没有转写为成功或拒绝，没有重放业务 |
| 隔离环境 | PASS | Backend `9b2c11f6…`；Product/Adapter 同一 `ff1390d1…`，逐服务更新并健康；其他服务和完整挂载保持不变 |
| 正常恢复 | PASS（限定） | Gateway 获取并核对原终态 completed/167，再由 Adapter 接受和持久化同一回执，不重放旧输入 |
| 浏览器普通输入 | PASS | 原会话一次输入，实际模型一次 HTTP 200，0 新 Job；预期回复可见，刷新前后 33 个页面文章全文相同 |
| 新回合关闭 | PASS | 新 Root completed/closed，Gateway 精确 ACK173；新 native ID、原生关闭和进程退出证明、签名清理均已核对，当前槽位 held0 |
| 原进程异常测试批 | FAIL 保留 | 旧观察器失败没有改写为 PASS；本片是独立的工程核对及随后浏览器验证 |
| 新镜像只读委派 | PASS | 一父一子独立身份、两项精确读取均有授权和成功审计；10次provider均HTTP200，0新Job，精确ACK184及清理通过，35个页面文章刷新一致 |
| 新镜像后台已发生结果 | PASS（独立补查） | 原浏览器批次观察器失败保留；单个新合成 SignalJob、一次接续 dispatch、两个 Root 关闭和精确 ACK197/212，回答持久化通过 |
| 两用户/迟到/业务 unknown | NOT_RUN 本片 | 后续按缺口补验，不由普通审计恢复或本次单用户后台证据代替 |
| 推送、合并、生产 | NOT_RUN | 不代表发布或生产资格 |

旧 Root 为 `753727634c8641a0add1597d6a304bae`，原终态摘要 `8231e9db5068757c1238e9ad2c6daf70f251a8994a1190a1fd01725cd970a87a`。新 Root 为 `5cee25d082be4e178970a437a10c86bb`，终态173摘要 `4dcfb6f51960eb7d7b142a4bb9a0e44919ef8be723c2d83ce86674b45a51053d`。不声称旧 Adapter 发送过 terminal endpoint ACK，不声称恢复了原子 Agent。

真实模型提供者收据：1 attempt、HTTP200、2781ms；input35252（含cache-read14336）、output15。Adapter 通用 usage 快照为0，该值没有用作模型调用或费用依据。

## 镜像和操作范围

Runtime候选相对原基础增加14317字节、Backend增加129513字节，各一个复制层；没有递归 chown 或重复复制整镜像。仅更新隔离环境 `byq-dev-e8b02b5475` 的相关服务，未改账号、密码、数据库卷或生产服务。MCP 的59910字节单层候选随后仅更新隔离 mcp-f6；6个变更文件与候选读回完全相同，其余15个容器和全16完整挂载不变。其真实负回执路径仍 NOT_RUN。

复用原 Compose 图，单服务执行 `up --no-deps --no-build --pull never --wait`；具体 argv、原始 stdout/stderr、native exit、文件哈希和独立审查位于私有 `.ci-artifacts/agent-origin-consumer-20261015-v1/historical-audit-reconciliation-v1/` 的 `backend-finalize-v1`、`acp-pair-update-v1`、`browser-ordinary-recovery-v1`。这不是新通用测试框架。

## 失败和审查保留

两个早期 helper 失败（工作目录、未定义名）均在 CAS 前停止；后续修复才分别验收。Product 更新后，Root 的完整对象比较再次引入无序 mount 数组顺序，误报失败；该批立即停止。独立审查已保存原件，确认其他15个服务非挂载字段及全16完整挂载对象相等，然后只补缺失的健康和密钥摘要，没有重复部署。

普通输入先按 Sol 已发 GO 执行；审查随后曾对旧 endpoint ACK 提出临时 HOLD，最终根据正常 settled 恢复合同更正。原 GO、临时判断、更正和实际输入时序均保留，没有倒置为事前终审。最终浏览器独立审查摘要为 `e11b0021c630d9c7d49dd3b5f596c138ecfaa58f9cc01c54c2bf7b94ae41f4c2`，Root 限定 PASS。

环境和原浏览器页面保持打开。没有新增或运行功能测试代码。

## 后台新批采集停止

当前镜像的后台自动接续已从原页面提交一次输入，最多允许一个新合成 SignalJob。Root 随后离线读取一份旧回执，把三行 JSONL 误作单个 JSON 对象而失败；外层 shell 因后续只读命令退出0，不能当作内部解析成功。该批保留 FAIL_OBSERVER_STOP，已停止新增测试输入、模型和Job操作；已提交流程不重发。先对数据生产格式和原生命令退出传播作离线复核，再单独核对已发生的结果，不把补查改写为原批通过。

## 已发生后台结果的独立只读验收

离线先核对 JSON/JSONL 合同后，独立只读补查已发生的执行；没有新增输入、模型调用、Job、重启或业务写入。新 Job `signaljob_e6958c6d072b4955a296dd7cd1243c32` completed，接续 `continuation_53e03fbbebc1441476bd8930d781d5d5` 单次 dispatch 并 settled/completed。Source/consumer Root 均 completed/closed，Gateway 精确 ACK197/212、两份真实 Product MAC 清理、预算结算摘要一致。源请求5次模型 HTTP200；后台5次已知 usage，逐次 HTTP 状态未观察，不作声明。全部执行上限 null、自动接续 true。

原47条消息、19条 Root、5个 Job 和5条旧 ledger记录保持不变；浏览器原35个文章作为精确前缀，新增1用户和2独立回答后38个文章刷新完全一致。独立 Sol 验收 SHA256 `e90e501eac5498790022420877f27076a0ee781613a71b6ba1ba5a52a107a04e`；Root 收据为 `browser-background-after-recovery-v1/ROOT-POSTSTOP-PASS.json`。原批仍为 FAIL_OBSERVER_STOP，不改写为通过。
