# 官方 DeepSeek F6 实现与验收检查点 — 2026-11-01

**PASS：真实官方模型的有界 F6 链及单请求只读用量 UI。**
范围是实际官方模型、真实 SignalJob 和原生后台接续；行情继续使用原有明确标注的
合成生命周期夹具，不代表真实 Tushare 行情、策略效果或完整 Phase17 验收。

先前401来自另开的独立 Playwright 浏览器，不能代表原页面未登录。维护者指出后，
已恢复原 IAB 控制并直接复用其持久 admin 登录，不需要密码，没有重置密码或复制
浏览器私有存储。原 NOT_RUN 检查点和失败保留；以下记录随后实际完成的唯一真实批。

## 范围与源码

- 维护者明确接受 [ADR-0116](../architecture/adr/ADR-0116-official-deepseek-f6-qualification.md)，授权隔离实现和一次有界真实验收。
- 分支 `codex/acp-real-f6-qualification-20261101`；应用源码 `771cd22c816f9fac8e32b0883c6a1611b1329002`，测试断言修正 `dd1ae266`；基点 `772570c1`。
- 实测发现的对象选择标识修正 `a4524b55`，只读自动请求投影/UI `83b18aab`。Runtime/Runner 生命周期执行器仍为本次已经实测的 `771cd22c`；后续只读取原收据，没有重跑模型或 Job。
- 用户级执行参数及已完成 Product 设置验收复用 [现有证据](user-agent-execution-options-20261101.md)，没有改回会话级设置或修改原用户参数。
- 新增独立 `task-ready-read.official-deepseek.v1`，只接纳 `deepseek-official/deepseek-flash`、`https://api.deepseek.com/anthropic`、`/v1/messages`。旧 Go profile、hash 和历史收据保留。
- 新 reservation 采用 owner 的持久 `byq-product` 模型绑定；路由解析不读取或解密 key。旧事件先返回原快照，不因当前设置或绑定变化重建。
- Runtime 在 START 前验证 profile 与原生会话实际 provider/model 一致。proxy、native overlay/guard 与 Runner 校验同一有限 profile、工具范围、用户选项和新 Root 身份。
- 复用 Messages 终态及实际 token 用量处理；缺失终态或不可证明用量保持 unknown，不补零、不重发。null 数值选项不生成16次/180秒等隐含上限。

## 实际定向检查

日志根目录：`.ci-artifacts/acp-real-f6-qualification-20261101/`。

| 检查 | 实际结果及证据范围 |
|---|---|
| Contract | Worker 工具会话报告10 passed；文件日志 NOT_CAPTURED |
| 隔离 PostgreSQL Backend | Worker 工具会话报告6 passed；凭据模块及并发/source-fact 回归另一次25 passed；日志 NOT_CAPTURED。临时数据库容器和网络已移除 |
| Runner 新旧路线定向 | Worker 工具会话报告4 passed；日志 NOT_CAPTURED |
| Runtime 五模块 | `runtime-focused-five-modules-20261101.log`：167 passed、1 failed；唯一失败是新增测试误断言 fixture 已准备的 generation 为空 |
| Runtime 失败用例复验 | 修为拒绝前后 generation/harness/active_run 身份保持不变，仅重跑失败 node，`runtime-focused-failed-node-rerun-20261101.log`：1 passed；应用源码未变，不倒写首轮结果 |
| Gateway 接续派发 | `gateway-delivery.log`：104 passed，包含官方 carrier 的精确派发 |
| Native JS guard | `native-js.log`：18 passed，包含官方 profile、工具限制及重算 hash 后的错误配对拒绝 |
| 架构、语法与隔离工作树 | `architecture.log`：73 passed；`dev-check.log`：local syntax PASS、remote CI REQUIRED；worktree 检查和 diff check PASS |
| 独立 Sol Reviewer | Functional PASS（源码）、Tests PASS（受影响定向范围）、Clean Break Architecture PASS；不包含真实 F6/Product 资格 |

原失败不覆盖：新增 JS 测试最初使用了错误方法/ready-row 断言；Gateway 首轮因工作目录
加载旧镜像 contract 而失败；Runtime 首批两次 namespace 导入失败及只读嵌套挂载失败
均未执行功能测试。核对实际布局、源码导入路径及原生入口后恢复测试，没有增加 harness。
相关文件日志保留；未写文件的准备命令输出只在工具会话，标为 NOT_CAPTURED。

Runner 额外广检不是全套 PASS：Host 报10 passed/10 failed（缺少 no_new_privs）；
容器报18 passed/2 failed。两例是 `test_workspace_mismatch_is_signed_and_never_creates_a_cwd`
和 `test_forbidden_authority_environment_is_rejected_before_consumption`：拒绝及不创建 cwd
已成立，随后未改的 state-dir bootstrap 文件与旧空目录断言冲突。Root 认定与本次
profile 路线扩展无关，保留 FAIL；这些输出文件日志亦为 NOT_CAPTURED。

## 测试前的保留环境检查点

- 5个局部 overlay 镜像构建成功；`candidate-source-readback.json` 核对16个必要源码文件匹配。
- 只更新测试 Backend/Gateway/Runtime/Runner，镜像固定为核对过的 image ID；4角色 healthy，Frontend/MCP 原容器和镜像保留且 healthy。
- 原4角色停止并保留为回退材料，所有原挂载完全一致，未清理数据、卷、备份或历史实验。
- Frontend 仅重载 nginx 以刷新 Gateway 地址；未导航或关闭原测试页面。
- `environment-verification.json`、`before-environment.json`、`after-environment.json` 证明17个 `beyondquant-*` 运行栈容器 ID/镜像未变。
- 新 Runtime 活动会话、输入、held/awaiting ACK/cleanup 均0。队列最近只读核对为7个 completed；真实提交/Worker启动前仍需刷新队列。
- 新 Signal Worker 仅构建、源码核对及离线 import PASS，未启动；旧 sandbox 的 server/runner/bars_frame/依赖声明与仓库匹配，仍停止。
- 私有配置和回退材料位于工作区外 `~/.local/state/byq-maintenance/acp-official-f6-20261101/`，没有把凭据写入 Git 或测试输出。

原页面保留：`http://127.0.0.1:32790/agent?session=conversation_f3c32849e1ba48a9ab7e19348e232cfd`。
单独打开的 Playwright 正常登录窗口停在 `/login`，没有读取个人浏览器存储、重置密码
或复制其他用户凭据。

## 实际真实批

观察开始 `2026-11-01T14:32:29.876614Z`，三个 Root 全部结束于
`14:40:14.643962Z`，在原15分钟观察边界内。后续只读对账、UI 修正与刷新发生在
观察窗口之后；没有借此追加模型输入、后台派发或 Job。

| 身份 | 精确记录 |
|---|---|
| Conversation | `conversation_5ce3f462ed5a40b59adf75dc633ec12e` |
| Runtime session | `byq-session-28c88c9929244057aa2c45f04fd690dd` |
| ResearchTask | `task_1b7d5113093b49df874f2bb12e37af9d` |
| 策略版本 | `artifact_5127ce2a38ac44268b54d7b3b444e814` |
| 精确业务审批 | `approval_request_5cfbe4a6dafa45e78ac53b5660176c06`，批准者为当前正常登录的 admin |
| 唯一 SignalJob | `signaljob_a7d1a09e89174fedb46daae14b0b5d4f`，completed，attempt_count=1 |
| 新信号 Artifact | `artifact_5802dc2753304c4fb4971c21299ee5ac`，validated，SHA256 `597bc3224fb8619d901132ece499b5dbb29cd7ec30981151d2b8ff243e75b61f` |
| Reservation | `continuation_2de90172128993b031d90b600114eade`，dispatch_attempts=1、settled、outcome=completed |
| 原生会话 UUID | `8d9b4571-2230-47d6-8ffc-d0fd0e69db35` |

前台1创建唯一新研究任务、草稿和不可变策略版本，然后结束。其 terminal ACK/槽位释放
确认后，由正常 Product UI 批准精确版本并提交唯一 SignalJob。Worker 开始前队列为
7 completed、未决0；只消费本次 Job，完成后精确停止该 Worker，exit0。总完成数8。
Job 的 `submission_origin` 是 `authenticated_human`，绑定同一持久 user/workspace/
conversation/task，不使用 Product Token 或伪造登录。

Job 完成自动触发一次后台输入。后台只读 ResearchTask 与派生 BacktestTask 的状态，
没有执行回测。随后第二次前台输入不调用工具，准确回答未在该输入重述的口令、任务、
Job 和 Artifact 完整标识。刷新对话后，三段回复仍存在。

三个独立 BYQ Root 分别为 `ed864ac80ddc401eb9c1d80b99bab341`、
`44bfceb77f654fcd89d123e40b92bf5e`、`61b40917bf4f4574919555dec4ffd601`，
Backend 均 completed/authority closed；Runtime exact terminal evidence 均HTTP200，
sequence17/28/34与各自 receipt 一致。前台1与后台 MCP 注册具有不同 Agent-run 和
generation，但同一 native UUID；第二个前台没有 MCP 操作，最终持久 binding 的 UUID
相同，native close/process exit 均true、cleanup_unconfirmed=false，held/await ACK/
await cleanup均0。`binding.closed=false` 表示 `conversation_ended=false`，符合保留公开
会话的要求，不表示 Root authority 未关闭。

前两 Root 的逐项 native close 布尔值没有独立逐 Root 留档；其清理成立依赖于源码
`_acp_native_reuse_is_proven` 的 ACK/close/drain 严门与后续实际成功复用，是机制推断，
不写成逐项直接 readback。后台 guard 记录7次工具调用（包括 bootstrap run_start）；
admitted MCP ingress为另一个层次的6条，均settled，只含授权、两类只读获取和审计。
最初把两层数量强等同的采集断言失败已纠正，没有额外模型调用。

## 实际用量与 UI

后台 profile 为 `task-ready-read.official-deepseek.v1`，用户参数 revision0，
auto_continue=true，数值全部null。没有创建旧式 continuation grant，没有改用户参数。
`continuation-request-usage.v2` 与16条 provider admission/completion journal 支持
8次真实 provider attempt：输入47,589、缓存读取319,232、输出1,539 token，
usage_source=provider_response、completeness=known、limit_violations=[]。
这些计数各自按 provider 字段保存，不估算费用。

实测同时修正两个直接阻塞：Backtest 三个对象 select 用真实资源 ID 作 value-key，
避免多版本被同时标选或显示旧标签（定向2 tests/build与独审PASS）；现有 owner-scoped
读接口附加最新 validated v3 `automatic_request`，前端只读显示原参数与用量，隐藏旧
grant操作（Backend纯合同3 tests、Frontend两模块16 tests/build、独审PASS）。
不存在 v3 时旧响应不变；最新 v3 无效则读取失败，不回退旧无请求状态或早期收据。

局部更新 Backend/Frontend 后，用原 IAB 登录在审批中心精确读取本 Task。页面显示
已结算、已完成、派发1次、官方模型、用户参数版本0、null上限为不限及上述真实用量；
刷新同一只读记录仍一致，没有生成新 Root/Job/派发。截图与 DOM 存在
`real-f6-usage-ui.jpg`、`real-f6-usage-ui.dom.txt`、`real-f6-usage-refreshed.dom.txt`。
旧系统级汇总监测仍显示0，未接入本次官方请求的实际统计，明确不作为本次用量或费用
依据；本次 PASS 以单请求原收据和其只读 UI 为范围，不宣称全局汇总监测已修复。

## 最终状态与证据边界

新增证据包括 `real-batch.json`、`real-job-and-ledger.json`、`real-bg-journals.json`、
`real-root-mcp-lineage.json`、`real-terminal-evidence.json`、`real-final-runtime.json`、
`real-browser-proof.json`、`real-final-readback.json`、`real-final-environment.json`。
六个必要服务 healthy，原容器/数据/卷/备份保留，17个 `beyondquant-*` 运行栈容器
ID/镜像未变。原页URL和旧回复均直接读回；本轮结果页保留供共同验证。

ResearchTask 仍 planned，派生回测只到 ready_to_execute，没有提交回测 Job；信号夹具
覆盖19个交易日/38个数据单元、缺失0，不构成研究任务完成、策略质量或真实行情证明。
原 Runner 广检及采集失败、部分旧日志 NOT_CAPTURED 保留，不覆盖为全套PASS。
当前没有 push/PR/hosted CI、merge、release 或运行栈部署；Phase17保持 OPEN，未启动
Phase18。

最终门禁：Tester `real-f6-evidence-review.md` → 独立 Sol Reviewer
`real-f6-independent-review.md` → Root，均为本次有界真实 F6 与单请求 UI 收据 PASS。
这些结论保留上述合成数据、planned任务状态、逐 Root native flag直接留档缺口及
原始 FAIL/NOT_CAPTURED 边界，不扩展为整体 Product、全局监测或发布资格。
