# Phase 17 — 完整个人重置的实际证据（2026-10-02）

## 当前结论

**完整个人重置：Tester → 独立 Reviewer → Root scoped actual PASS。**
重置后 E1 新研究、真实委派/搜索、后续独立新会话的纠正材料保存和只读浏览器已分别取证。
最新 **实际保存 + 独立只读 UI：三方 scoped PASS**；原 E2 的422、旧超时外部 UNKNOWN、
新保存观察器的原失败均保留，不重放、不称原 E2 整链成功或自主来源分类已修复。
**Golden E 分段组合 / 最终 A–F/F6 映射：本地限定三方 PASS；Phase17：OPEN。**
[最终 Golden 映射](phase17-final-golden-acceptance.md)保留适用 A–D/F6/F、源码/构建边界及 CI 门禁。

## 已实现的产品语义

[Accepted ADR-0091](../architecture/adr/ADR-0091-workspace-reset-fact-retention.md)
按用户接受的完整语义实施。保留同一账号、登录安全字段、role/RBAC、个人 Workspace
及 membership；个人 Product 数据、设置、模型配置/绑定和用户凭据归零到注册/惰性
默认。共享标准行情、系统设置/凭据、其他用户和 Engineering 记录保持。

Backend 按静态 72 类 ownership 分类执行事务归档、count/hash 校验、子表优先删除和
默认状态恢复；账号/Workspace writer fence 防止并发绕过。闭合个人审计、审批及模拟
金融历史适用七天，而非永久保留。少量 reset/旧请求摘要证明独立保留防重放。
真实未决 Job、调用/结算、未知外部结果及发布责任先对账，不因重置删除责任。
归档只保留加密用户 credential envelope；Hub status token 只保留不可逆摘要。

每小时有界清理到期 payload，CAS 仅在无活引用、未到期归档及受保护事实时收集；
缺挂载、symlink、size/hash 不符、活 producer 或 I/O 失败保留准确重试记录。
Backend 保持非 root；ML 三个精确目录采用 producer group/setgid，未递归 chown
或改写既有对象。Job 独立于 Agent、Artifact 持久化与 DSH 唯一 Harness 边界保持。

本地未推送提交：`91fc0211`（完整语义）、`3006f031`（ML CAS 权限与清理）、
`1c1f730c`（ML watch 重置栅栏）。Root 是唯一源码 writer。

## 离线、构建与真实重置分层

离线合同及原失败见[预算/接续审计第20节](phase17-continuation-budget-audit.md#20-adr-0091-完整个人重置实现离线门禁2026-10-01)。
另有 ML watch 17 个定向 PostgreSQL 正反例通过。实际 fresh-volume producer/consumer
两种启动顺序均通过，专用探针已删除；既有对象 inode/content 未改写。

标准 networkless Backend fresh build 因缺 setuptools83 离线依赖/DNS **FAIL**，原日志
保留。随后仅以固定旧依赖镜像覆盖受影响当前源码，Backend/Gateway/frontend 的
离线 overlay/build 通过，Backend 当前 70 个 app 文件逐 hash 相符。该资格不是当前
源码从空环境重建整栈，也不是 hosted CI。该次 Reset 时 Runtime 仍为已接受 `.280` 镜像；后续限定 Runtime/MCP 源码加载见下文。

专用隔离栈 `byq-dev-dd33416d94` 仅执行 **一次 bodyless Reset POST**：

| 实际断言 | 结果 |
|---|---|
| 原个人记录 72 类 / 784 行 | 事务归档784行；清理后0行 |
| 七天 UTC 归档 | 精确604800秒；闭合ledger2份 |
| CAS | 5对象/引用完整，内容hash匹配 |
| 账号、membership、RBAC、共享和system凭据 | 保持 |
| 用户默认 | 偏好/提示/模型与凭据按注册默认；真实浏览器成功 |
| 新模型输入 / Engineering seed | 0 / 0 |
| 真实经过七天后的定时删除 | NOT_RUN；离线到期/引用/失败合同PASS |

原47件 Reset 证据封存；没有第二次 Reset。

| 独立实际门禁 | SHA256 |
|---|---|
| `/tmp/byq-phase17-personal-reset-actual-tester-20261002/actual-reset-result.json` | `9957edbe1411f575ec2d9fb85341ebcb3f9e6d35907d29449aef64495cd5d418` |
| `/tmp/byq-phase17-ml-permission-review-20261001/actual-populated-reset-independent-review.json` | `e8d2080d8d8c8926fb554262fb2a578d585802cde956658b358410edf5c1122e` |
| `/tmp/byq-phase17-personal-reset-root-actual-acceptance-20261002.json` | `2687dd5998bbfb55aa2834c1104e61950c8f4bb1550cccc583173f8224010225` |
| `/tmp/byq-phase17-personal-reset-actual-seal-20261002.json` | `8fad24fb522b97ae262d7d8a880c682ffbdff659ad8a11726b39ea44426db89a` |

## 重置后的真实研究与已确认失败

整条观察器先经离线 Tester/Reviewer/Root 冻结；一次正常 Product 新 conversation、
两次前台输入、一次真实委派、一次真实 Web query。没有 seed、Job、再次下载行情或
恢复旧 DSH。已验证的 000001.SZ / 20240102–20240531 /98交易日缓存复用。

E1 创建/读回唯一新主 Task，回答及投递完成；E2 父/子 run 完成且回答持久化，
实际搜索得到8来源，但全部 `published_at=null/PUBLISHED_AT_UNKNOWN`，子 Agent
将8条说法标为 SUPPORTED（其中一条因果还缺PRIMARY）。Backend 两次明确422
`SUPPORTED_SOURCE`；校验在 Task/Artifact 写入事务之前完成，没有副作用。
父 Agent 如实报告没有保存；原 E2 不改为 PASS。

证据先保存，再有界只读保留原 SSE 对账，随后关闭浏览器/连接。3个 run completed/
closed，7类 Job 均0，当前 Reset preflight 无未知/未决责任。14 normalized model calls
为该真实尝试的新增用量；raw provider HTTP NOT_OBSERVED，不与用户回合数混同。
再次只读核对 identity/membership/shared8表/归档/5CAS 完整。实际调用及私有会话目录
有精确结构化身份关联，不从公开“系统能力”文字推断权限。

原尝试47件证据封存于
`/tmp/byq-phase17-post-reset-research-failure-20261002/original-attempt-seal.json`；
失败分类及真实 native/Backend 对账位于同目录。未知调用没有重放。

## 受影响保存修复与剩余门禁

仅加强既有 MCP state 描述与市场研究 skill：未知/超研究时点的来源不能建立
SUPPORTED；可保留真实引用和局限，以 UNESTABLISHED 保存研究线索。因果支持仍需
PRIMARY。Backend validator 保持原强校验，加入未知时间正/反合同；不编造发表时间，
不改 source tier、不增加网页或量化用途。

限定后缀先通过离线 Tester → 独立 Reviewer → Root，随后实际创建1正常新会话、
提交1前台输入，计划复用真实8来源并委派1子 Agent。Runtime在任何BYQ工具/委派/保存
之前发生无进展超时：实际child0/search0/新Task0/Artifact0，保存FAIL。原失败和原2轮
结构不改写；没有行情读、Job、Reset或seed。共享/归档保护只读通过。Artifact hash/
lineage、成功回答投递及其真实浏览器验收尚缺，不能用离线候选替代，不能重放未知模型
调用。最终失败及未知用量边界见下面实际记录。
该失败实测时，Runtime/MCP 未加载新 skill/schema，源码提示当时只能称离线资格；实测
后缀依靠显式校正用户输入，不能冒称原提示自动修复通过。

Phase17 最终 Golden 汇总、受影响 source/build currency、必需 hosted CI 与仓库
门禁保持 OPEN；当前源码空栈重建 NOT_RUN。无推送、合并、部署或 Phase18 授权。


### 保存后缀的零输入停止与限定修正

原会话已释放，durable Product GET 可读不代表健康 SSE。第一次后缀在 SSE 接入时
停止：0新会话/0turn/0child/0search，保存证据后有界只读对账并关闭连接。
第二次后缀成功创建一个正常新会话；初始 `answer-delivery=pending` 且三计数均0，
被观察器误要求 `up_to_date`，在输入前停止。其0turn/0child/0search原记录同样保存，
四次只读对账后关闭；Gateway随后正常空闲释放该空会话，不能恢复旧DSH来迁就测试。

Gateway合同允许空会话初始pending。最终候选只在精确session/trace、active、messages0、
投递三计数0且事件为空或仅session.ready时允许pending/up_to_date。出现未知事件、
起始turn、回答或终态均在输入前拒绝；提交后仍有界等待逐片持久化及up_to_date。
只资格化受影响观察器，不重复有效A–D/F6、Reset或Web query。

两次前置停止没有改变Runtime累计14次normalized model calls。原55件和新37件
零输入证据分别封存；原E2仍FAIL。观察器最终25项离线正反例通过并经独立Reviewer/Root
门禁，实际保存结果如下一节；离线资格不等于真实保存通过。

仅删除已不需要的tmpfs合同测试容器 `byq-p17-reset-pg-20261001-a1` 与其唯一内部网络。
首次清理因Docker Mounts数组顺序不同在删除前停止；规范化顺序后逐属性/身份重验并
精确清理成功，Product13容器/5卷/2网络保持。无持久数据删除，结果为
`/tmp/byq-phase17-reset-fixture-cleanup-v3-20261002/fixture-cleanup-result.json`。


### 最终限定保存实测：Runtime超时FAIL

最终一次正常新会话/一次前台输入获202，root
`0a875c4f734c4402a230cc0d9646e78d`，conversation
`conversation_46ede53c565948be8b3eb9510996db91`。原健康SSE收到
`session.failed/runtime-no-progress-timeout`（120秒无进展），没有公开回答。
先保存原记录，四次有界只读对账后关闭连接；没有重放或延长安全限额来获得PASS。

权威Backend root为failed/closed；新agent_runs/audits0，仍只有原主Task、Artifact0、
七类Job0、domain claims0。准确新native仅1个parent，turn start/end各1，BYQ工具、
委派和Web调用0，未观测到assistant usage。Runtime随后active/prompts0，normalized
计数仍14（本次delta0），**不能据此说实际模型调用/费用为0**：provider返回及真实
消耗UNKNOWN，raw HTTP NOT_OBSERVED。当前domain reset guard通过只证明领域责任
无未决，不解除外部模型未知状态，也不允许自动重放。

原会话/原主Task绑定保持；账号、membership、shared8表、七天归档及5 CAS逐项
只读复核保持。没有新增领域写、seed、搜索、行情拉取、Job、Reset或DSH恢复。
实际保存/后缀FAIL；完整个人Reset的原scoped actual PASS保持。

最终失败原尝试及19件只读取证封存：
`/tmp/byq-phase17-web-save-final-failure-seal-20261002.json`，SHA256
`7f4fb65e8898295da12799e0b17492e38a96db20ba00a457e0dc5b2c0fd2a898`。
该失败实测时，精确候选归一化、8来源及发布时点合同只获得离线资格；MCP/skill未更新。
本切片也不对通用lineage解析的任意跨租户输入作安全验收：本场景仅精确绑定已确认
同owner/Workspace的原主Task。Golden E、最终Golden与Phase17仍OPEN。


### 超时只读审计与提示源码加载（2026-10-02）

**只读审计、两服务源码加载：限定 PASS；真实保存仍 FAIL，完整 Golden E / Phase17 OPEN。**

先确认专用隔离栈没有遗留测试 runner、DSH 进程、活动 session/prompt。
120秒无进展保护关闭本地 turn；native 空 stream 和 aborted/disposed、Adapter
normalized计数14→14，均不能证明 provider 未收到请求、成功取消或实际消耗为0。
固定SDK只提供本地JSON-RPC身份/通用通知，本次上游请求ID、返回、取消及用量仍UNKNOWN。
一次只读GET `/models` 返回200仅证明当时连通/认证；没有新模型输入。
旧模型名仍为官方暂时兼容别名，不能因不在模型列表中就归因于配置失效。
[官方说明](https://api-docs.deepseek.com/updates/)。

所核对的Runtime/MCP运行源码差异仅市场研究SKILL.md与MCP server.ts中的保存描述；Adapter代码、
固定DSH SDK/bin 0.1.5rc1、profile/build/contract身份及120秒配置保持。
使用原依赖缓存、network none/pull false构建两份候选；首次legacy builder不支持
COPY --chmod的失败保留，v2只修正构建权限语法。精确镜像源码树及官方MCP
tools/list88项/未知时间→UNESTABLISHED描述离线通过，领域工具与模型调用0。

Tester→独立Reviewer→Root准入后，只以no-deps/no-build/pull never加载
`byq-dev-dd33416d94`的Runtime/MCP两服务。首次后置观察器raw资源比较
失败保留；当时原始快照未保存，不能证明具体字段或顺序原因，没有重复apply。
随后一次只读对账保存完整raw/规范化快照，非目标11服务所有字段均与before相等；
只证明对账时资源完整，不反推首次失败原因。v2对Mounts顺序的过强归因单独更正，
原sealed文件保持，v3在`/tmp/byq-phase17-guidance-load-correction-20261002/`。
其余11容器、5卷、2网络完全保持；实际skill/MCP源码与编译文件hash读回相符。
账号、shared、七天归档及5CAS完整，原root failed/closed，Task1、Artifact/Job/claim0。
新Runtime boot `b36a9049edefe7a6e1a1e07eda797ac5`的normalized计数0只属新进程，
旧进程14及更早历史/未知外部结果仍保留。没有第二次Reset、seed、Web查询、行情下载、
模型输入、旧DSH会话恢复或超时放宽。

审计27文件seal：`/tmp/byq-phase17-reset-timeout-audit-20261002/seal.json`，
SHA256 `1cf3adae52e67d30bfd94255dbdb6434bc921239358325f2683a7a589b1dcd32`。
候选构建28文件seal：`/tmp/byq-phase17-guidance-build-v2-20261002/seal.json`，
SHA256 `0333ce0dbbd55cbfbfebcb4e2f2c3646d86d9a3fd17bf67edad67341f3c1780f`。
加载/只读对账12文件seal：`/tmp/byq-phase17-guidance-load-20261002/seal.json`，
SHA256 `7c980d648be8d058b815ac055ea41700e10cee21d0adb3b48cba6752bfe19e72`。
最终Root限定验收：`/tmp/byq-phase17-reset-timeout-final-root-acceptance-20261002.json`。

这次加载只补运行镜像的提示源码差异，不修复或覆盖历史保存超时，不能冒称真实保存、
模型可用性整链或当前源码空栈重建PASS。保留有效A–D/F6；剩余为受影响保存的独立
实测、最终Golden/source-build汇总及必需hosted CI/仓库门禁。原未知调用不重放。
无推送、合并、部署或Phase18授权。


### 独立模型HTTP协议诊断（2026-10-02）

为区分当前推理接口可用性与原DSH超时，先用10项离线样本检查缺失/非法usage、
输出超限、错误终态、工具项及空回答，再发起一次全新Engineering协议请求。
POST `https://api.deepseek.com/responses`，固定非业务短文本，188-byte body、
max_output_tokens128（包含推理tokens）、reasoning none、tools空/tool_choice none、
socket15秒/总体20秒，无redirect/retry。参数与用量字段按
[官方合同](https://api-docs.deepseek.com/api/create-response/)核对。

真实返回HTTP200、completed、1.509秒；请求`deepseek-v4-flash`，响应报告
`deepseek-flash`，response ID `691fd5e5-63c6-4a5a-ba4f-fdcc63dc7554`。
固定诊断回答匹配、没有工具项，接口报告input21/output13/total34，均在声明输出限额内。
这条直接外部attempt1单独记录：Adapter新boot normalized仍0/active0，并不表示
本次外部请求为0；原DSH请求的返回、取消和实际用量仍UNKNOWN。
没有Product Agent输入、任务/Artifact/Job/Reset/Web/行情动作，也没有改SDK、
provider/default profile、Harness、产品预算或领域授权。

六文件seal：`/tmp/byq-phase17-model-http-diagnostic-20261002/seal.json`，SHA256
`642e8549647f5d2c117de2059e2423e48f99d42051914aaeb554bb7fbfa9b902`。
Root限定验收：`/tmp/byq-phase17-model-http-final-root-acceptance-20261002.json`。
**仅当前这次独立HTTP协议诊断PASS**，不替代DSH/Agent、真实保存/浏览器或完整Golden E。
原失败不重放，Golden E/Phase17 OPEN、有效A–D/F6复用及最终阶段门禁保持。


## 当前源码独立保存与只读浏览器（2026-10-02）

应用源码基础 `a2fa32d89d8c7611861b86ed40474d42c8d149a7`；验收前工程 HEAD
`be279a0af2958a0a7b763177a774777df4d35a30` 仅有两份证据文档差异。
现行 Runtime/MCP skill/schema 及 Backend/Gateway/frontend 精确源码读回均有独立限定资格。
新增正常 Product conversation `conversation_b53d824787f84bb78f3eef72c2579d76`，
sole foreground root `9cd7e6d4939b4e6d999e432ba1ccdb92`；不是恢复旧 DSH 或重放未知请求。

输入显式提供原实际 Web query 的8条结果及纠正为 UNESTABLISHED 的材料。
它证明重置后的研究保存能力，不证明模型无需提示即可自行纠正原来源分类。
沿用已确认422/无写入的 business key `phase17-personal-reset-e2-web-20261002-01`，
新 parent/child registration keys 分别为 `phase17-current-source-save-parent-20261002-01`
及 `phase17-current-source-save-child-20261002-01`；原主 Task 全13字段不变。

| 实际事实 | 结果 |
|---|---|
| Parent / child runs | `agent_run_d38655b1240d465bbefee11b70533cae` / `agent_run_e84b29db5d5f4f03a757177bd43f9e7d`，均 completed/closed |
| 新 child Task | `task_a1624d24a2c44f4bb618a26d5ce11f63` |
| 保存的 draft Artifact | `artifact_e8e10b3fbdca443d98ae67ac88beeefd` |
| Canonical content SHA256 | `aa02283eb8faf0350b11cb54a45c945b506492fc61baeeb53e21d9a79e1cb4dd` |
| 内容/lineage | 8真实来源、8 UNESTABLISHED claims、全部发表日期 UNKNOWN；child/main Task lineage 精确相符 |
| 审计/持久化 | 10条权威结构化 audit；SSE22事件、completed；回答 fragments 持久化、delivery up_to_date |
| 新 Web/行情/Job/Reset/seed | 0 / 0 / 0 / 0 / 0 |
| 真实只读浏览器 | 同一新会话回答及同一 Artifact；135 GET/1 login POST，其他写入/模型输入0 |
| 保全 | 13容器/5卷/2网络、账号/shared8表、784归档行、5 CAS、98行情日保持 |
| 结束状态 | 浏览器/SSE关闭、Runtime active sessions/prompts0；Workers停止、F6 flags0 |

原模型 Runner 在已完成 REPAIR 后因隐式 Playwright context 第二 page 报错，仍是
`STOPPED_NO_REPLAY`，原60文件 seal保留。后续只读 collector 原观察器把合法
`runtime_turn_binding=active` 误判为 running；该失败转录注明来自 Root tool observation，
原 collector stderr 未另存，不冒充原始 stderr 完整证据。

独立新 `actual-contracts-v2.py` 仅修正两处合法状态集合，11离线正反例通过；显式
`browser.newContext()` 以无网络 offline browser样本验证后，只做一次 UI-only 真实检查。
没有重复模型输入。截图证明回答和 JSON detail 页面可见；完整 JSON 由实际 DOM 解析
匹配，不声称单张截图同时显示所有来源或具备专用比较图表 UI。
4MiB body接受上限在完整读取后检查，不冒充流式内存硬上限。

当前 boot normalized delta11、native usage记录17，不等于原始 HTTP请求次数。
raw provider HTTP NOT_OBSERVED；旧超时返回/取消/actual usage仍 UNKNOWN。
独立只读 UI模型增量0 不抹掉此前调用。

| 最新实际门禁/不可变证据 | SHA256 |
|---|---|
| `/tmp/byq-phase17-current-source-save-final-seal-20261002.json`（102文件） | `373515430b0658b2d79960620a014593e3a69eaeb331340bd5b9f75f18de2194` |
| `/tmp/byq-phase17-current-source-save-tester-20261002/actual-save-and-readonly-ui-review.json` | `179e5f66b456420aefe96fd57b2165379e9c33e101904be44bb71ef74d1004d0` |
| `/tmp/byq-phase17-current-source-save-independent-review-20261002/actual-save-and-readonly-ui-review.json` | `48f31fc664ef14221e27163079882ab89827eb6c00cf49365695e8846f93d992` |
| `/tmp/byq-phase17-current-source-save-root-actual-acceptance-20261002.json` | `ef0f58db6df1266154aad371f54385242f51a6bfd211dc1b7d95760fa6162696` |
| `/tmp/byq-phase17-current-source-save-independent-review-20261002/source-build-currency-review.json` | `29b3defd728354a8a1cf59af518d7c2b56c1ba8f89f5aa9e5fec5a73a4ec2f68` |

这份 Root 门禁在真实只读 UI 后签署；旧 pre-run gate 的 NOT_RUN 字段不覆盖改写。
最新限定保存/UI PASS 可以进入分段 Golden E 映射；完整最终门禁另行记录，
hosted CI/仓库验收与 Phase17整体仍 OPEN。


## 最终映射签收

Tester → 独立 Reviewer → Root 已接受当前 Golden E 分段组合，并完成最终 A–F/F6
限定本地映射；[完整门禁](phase17-final-golden-acceptance.md)记录26项绑定、五份原审查
文档快照、ML两启动顺序首次当前限定三方签收及全部证据复用边界。
这不将原E2、旧超时、原观察器或自主来源分类改判成功，不声称新的完整A–F执行。
阶段本地映射完成；当前提交 hosted CI/仓库门禁未完成，Phase17整体仍OPEN。
