# 投研体验维护 — 2026-11-07

## 范围与基线

维护者请求“请研究项目代码解决体验测试问题”，依据会话
`6aeecc9b-c21c-83e8-ad83-b45a36158c66` 的体验记录处理明确缺陷。
本次授权为代码维护和必要验证，不推断 push/PR、合并、发布或部署授权。
不推进 Product Phase，不修改用户模型配置、历史回执或数据卷。

- 起点：fetched `origin/main` / `e7c488d800a2e61f1aae6226d80cfc41a21af77b`。
- 分支：`codex/research-experience-20261107`。
- 隔离工作树：`/home/jefison/.codex/worktrees/research-experience/BeyondQuant`。
- 工作树校验通过，使用专用 `BYQ_ENGINEERING_WORKTREE_ROOT=/home/jefison/.codex/worktrees`。
- 主工作区仅 fast-forward 同步；实现变更只在隔离工作树。

## 原始失败事实

Engineering 只读核对运行环境的持久会话、WorkflowTrace、provider gate journal
和 DSH 原生日志。生产测试镜像标签对应起点提交、Release Images `42334849363`。

原体验会话 `conversation_4d08951130e14140a33a56209949f79f`：

| Root | 时间（UTC） | 事实 |
| --- | --- | --- |
| `c563b48e23ba4156b90f5ced6d8908e4` | 07:04:44–07:05:00 | provider attempt 1，admitted/completed，HTTP 500，forwarded=true |
| `290161774b4c497ea46101d7c1912043` | 07:05:40–07:05:56 | provider attempt 1，admitted/completed，HTTP 500，forwarded=true |

两次 admission reason 均为 `within_request_budget`，Backend Root 均为 failed、
terminal_unknown_claim_count=0。不能据此把实际 token 用量 unknown 改成0。
第一轮原生错误为 `SERVER / Internal Server Error`，上游 request id
`e9c45254-49e8-4908-84a6-eb8e1cf0c60a`。公开失败事件仅有 `AcpRpcError`，
没有 code，因此前端退回“本轮运行未能完成”。未发现支持额度或并发拒绝的证据。
HTTP 500 的服务端内部根因未知，不以错误分类修复冒充模型服务修复。

## 最小修复

Runtime 复用已有请求回执，在精确 generation 的 proxy 已关闭、gate 已封闭且
所有请求已成对结算时，将最后一次 HTTP 错误归类为服务不可用、限流、鉴权或
请求拒绝。公开投影不含上游正文、凭据或原生身份。保留 FAILED、retryable=false、
原有 Backend ACK、未知结果保护和下一轮准入，不重试或重放旧输入。
前端使用固定中文说明和现有 trace/sequence 诊断编号。

- 股票池复用 Product 证券目录按中文名/代码搜索、多选。目录不完整时保留规范代码
  手录；中文查询不生成假候选。按百分比填写权重，空值明确显示“未设置”。创建与
  编辑共用全部留空或全部为正且合计100%的校验；不合法输入保留，不发请求。
  百分比换算规范到合同的12位小数，避免20.01%产生二进制除法尾数而被后端拒绝。
- 原股票池可一键进入比较研究草稿，携带当前 pool/snapshot ID；不从分页成员猜全池，
  不自动创建会话、调用模型或发送消息。策略页亦可先描述投资想法。
- 回测缺已批准策略或可用股票池时提供对应管理入口，去掉 ADR 和内部运行术语。
- 模型训练/验证/预测日期不再预填旧样例，要求填写完整且顺序不重叠的区间；
  不把样例日期或本机时间冒充市场数据覆盖。

未扩展拼音搜索、一键等权、行业/估值/股息筛选、自动推荐数据区间或导航重构。

## 真实验证（运行中的原基线，不是新代码部署验收）

开发测试使用正常账号，通过 Gateway/Product API 登录、创建并读取会话
`conversation_231598efc95d4acea9cf1e572495e946`。

1. 基础对话：一次明确输入、不调用工具或业务操作，Root
   `7fc19cfa38b843fbb8e3998c27cfa21e` completed，回答持久化。**PASS**。
2. 招商银行只读研究：一次输入，要求来源/日期，禁止下载行情、创建策略、任务、
   股票池或订单；Root `892dcc815bb24d56b526d43b87295182` failed。
   gate attempt 1、admitted/completed、HTTP 500、forwarded=true，业务 unknown=0。
   **FAIL**，停止此批，不重发。上一轮成功回答不充当本轮研究结果。

两轮观察分别限制120/180秒，均提前得到终态。没有修改运行栈、模型配置或额度。
该结果证明基础对话本次可用，同时研究链仍受模型上游错误阻塞；不证明研究结论
质量、行情数据覆盖或完整“研究→保存观察池→比较”旅程通过。

## 交付门禁

### 本地源码验证

- Workflow 中文错误分类/诊断引用：18 tests **PASS**。
- Worker 的 StockPool、MLResearchWorkbench、Backtest、Strategy、AgentView 五文件：
  57 tests **PASS**。最后权重校验/精度修正后仅重跑 StockPool：9 tests **PASS**，
  其他未受影响测试保留其证据；前端最终类型检查与生产构建 **PASS**。
- 独立 Tester 的 Runtime 分类8组及预算/未知结果/存储/未关闭proxy保护：12 tests
  **PASS**；补充领域安全停止优先级后，重新执行分类矩阵9组 **PASS**。
  使用现有固定镜像 `sha256:9ac6186f5c5402403cb17b563a74ac95664130d82668d58d9c2f88360b031f5b`，
  单仓库只读挂载、显式 PYTHONPATH、network none，不安装依赖或调用模型。
  两次测试准备失败保留：首次缺 packages import path，第二次只读根下缺嵌套挂载点；
  均未执行测试，最终以单挂载修正，未扩大测试范围。
- `dev-check.py --base e7c488d800a2e61f1aae6226d80cfc41a21af77b`、diff检查 **PASS**。
- 独立 Sol Reviewer：Functional / Tests / Clean Break Architecture **PASS**。
  审查发现的领域停止优先级、权重部分填写/总和问题已修复并定向复验。

### 真实浏览器（候选前端 + 已运行 Gateway/Product API）

使用正常账号登录、Playwright Chromium；所有业务请求经过 Gateway。
本地预览 `http://127.0.0.1:5175` 指向开发测试，`http://127.0.0.1:5176`
指向生产测试 Gateway。只是本地候选前端预览，不替换运行栈镜像或正式入口。

- 开发目录只有两条明确标识 Synthetic Fixture 的证券记录，不当作真实行情证据。
  新建 `体验回归_银行观察_20261107`（`stock_pool_5ea9df5c4b084eb28ab851ec7c6594aa`），
  手录600036.SH、601398.SH，初始权重“未设置”；60%/40%保存、刷新回读 **PASS**。
  无效合计保持表单且零 POST；20.01%/79.99%保存后，Product成员回读
  `0.200100000000` / `0.799900000000` **PASS**。这些是表单/持久化验收，不是行情或投资质量验收。
- 策略想法入口只生成编辑草稿，零 session/turn POST **PASS**。
- 模型六个日期输入为空且有填写说明 **PASS**；回测表单去除ADR术语 **PASS**。
  当前开发环境有前置资产，缺项引导仅单元测试覆盖，不冒称真实空资产流程通过。
- 原生产体验池只读核对：平安银行/招商银行/工商银行中文成员、未设置权重 **PASS**；
  中文搜索最终仅返回真实候选“招商银行（600036.SH）” **PASS**；比较草稿准确携带
  `stock_pool_5dbb5369172f43f88b571938bc3967ae` 和原 current snapshot ID **PASS**。
  生产浏览器唯一 POST 为正常登录，零业务写入、零新模型输入。
- 真实旧失败历史显示诊断编号，390px无横向溢出 **PASS**；旧事件没有新 code，
  继续如实显示泛化说明，不改写历史或声称新 Runtime 已运行。
- 浏览器检查曾因等待开发目录不存在的招商银行候选超时；只读API确认空结果后停止
  原批，改为手录验证与生产目录只读验证。另一表单点击被展开下拉遮挡，保留表单、
  关闭下拉后继续，没有重复提交。开发页面无 pageerror。

截图保存在本机 `~/.local/state/byq-maintenance/research-experience-20261107/stock-pool-desktop.png`。
本地预览、浏览器页面、原会话、测试数据、运行环境和失败证据保留。

**Root：本地限定源码修复 PASS；研究可用性整体仍 FAIL。**
新代码镜像、远端 CI、发布、部署和修复后真实模型验收均 **NOT_RUN**。
模型500的服务端根因仍未知；不切换用户模型、绕过保护或反复重发来制造成功。
本次不推进 Product Phase。
