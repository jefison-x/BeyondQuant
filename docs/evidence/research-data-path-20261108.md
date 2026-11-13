# Research data path — bounded optimization (2026-11-08)

## Scope and authority

Maintainer request: “好的，按你的这个思路，看看可否优化一下我们的数据获取路径。”
This is bounded maintenance in the existing isolated
`codex/research-experience-20261107` worktree, based on
`2cf7735117fd8f691465d5273dbb436d4937a7ad`. It does not advance Product Phase,
authorize production deployment, or qualify a new external MCP capability.

## Verified data paths

- `services/mcp/src/market-data.ts` calls Backend persisted research reads.
  `byq_market_session_context`, `byq_market_daily`, `byq_market_valuation` and
  `byq_market_fundamentals` do not refresh a live provider.
- `services/backend/app/data_provider.py:TushareProvider` already implements
  Tushare API access, with bounded normalization, provenance and provider errors.
- `services/backend/app/provider_runtime.py` resolves the active system
  credential first, then the configured environment fallback. Engineering
  inspection inside the running Backend confirmed `environment` for this probe;
  no credential was exported or written to the evidence.
- `byq_data_demand_create` currently needs a frozen stock-pool/date scope or an
  index snapshot request. A lightweight single-stock, missing-fields preparation
  request does not yet exist. This slice does not extend its authority or schema.

The retained [latency evidence](research-experience-20261107.md) measured
557.730 seconds for one research turn: model requests 383.456 seconds, web search
142.362 seconds, web fetch 26.201 seconds. Six BYQ market-data reads totaled
0.382 seconds. This supports reducing unnecessary research work; it does not
establish a database bottleneck or a general response-time baseline.

## Official Tushare comparison

The [official MCP configuration page](https://tushare.pro/document/1?doc_id=463)
documents a remote endpoint with a token in its path and configuration obtained
from the account's MCP Server page. No third-party MCP package was installed.

Two bounded initialization probes used the documented endpoint shape: first the
local existing `.env` credential, then the actual Backend credential resolution.
Both returned HTTP 401. The Backend probe completed in 129 ms with the fixed
response `{"error":"missing_token"}`. Redirect following was disabled and no
secret-bearing URL was printed. Initialization did not succeed: tools/list,
MCP data calls, tool coverage and transport/session compatibility are **NOT_RUN**.
No repeated credential guessing or alternate authentication probe was attempted.
This response does not establish an invalid token or insufficient data rights;
the current account-generated MCP configuration still needs confirmation.

Three read-only HTTPS API probes used that Backend-resolved token, without
model calls, synchronization, persistence, configuration changes or jobs:

| API | Bounded request | Result | Elapsed |
| --- | --- | --- | --- |
| daily_basic | 600036.SH, trade_date 20261106, five selected fields | HTTP 200, code 0, one row | 236 ms |
| fina_indicator | 600036.SH, period 20251231, five selected fields | HTTP 200, code 0, one row | 140 ms |
| dividend | 600036.SH, end_date 20251231, five selected fields | HTTP 200, code 0, two rows | 133 ms |

The dividend response included proposal and implementation records; these are
not two additive payouts. The probes establish access to these exact samples,
not full API entitlement, financial-report correctness or general latency.
API versus MCP data-speed comparison remains **NOT_RUN** because MCP did not
initialize. The upstream data was not imported into BYQ research or backtests.

## Candidate behavior change

Only the current ACP Product profile, its matching hashes and the two Product
research skills change:

1. For stock research summaries/comparisons, preserve an explicit historical
   as-of; check session context when a current/latest cutoff or exchange-session
   determination is needed. Obtain needed durable BYQ fields before delegating
   public-background research.
2. Reuse applicable evidence only for matching symbols, fields and as-of scope;
   updated-data requests check the cutoff again. Each new read retains its own
   authorization and audit.
3. Delegate the remaining public questions with compact values, dates,
   provenance and explicit coverage gaps. Evidence does not transfer authority;
   child AgentRun binding is unchanged.
4. Request a compact sourced handoff for a brief summary, avoid duplicate reads
   and a second full report, and stop when requested topics are supported or
   explicitly unresolved. Conflicts and missing provenance still need checking.
5. Missing persisted metrics remain gaps. No implicit refresh, automatic data
   demand, provider credential access or webpage substitution is introduced.

No tools, privileges, model settings, generic runtime mechanisms, historical
profiles, database schema, provider implementation or running containers change.
The profile instructions guide model behavior; they are not a deterministic
scheduler or a measured guarantee of faster research.

## Validation

- PASS: existing ACP profile/version/build and plugin-registry contracts:
  `python3 -m pytest -q tests/architecture/test_acp_authoritative_version.py
  tests/architecture/test_dsh_authoritative_version.py
  tests/architecture/test_dsh_authoritative_build.py
  tests/test_dsh_plugin_registry.py` — 37 passed, 20 subtests passed.
- PASS: scoped `python3 scripts/ci/dev-check.py --base
  2cf7735117fd8f691465d5273dbb436d4937a7ad` syntax checks; component tests and
  remote CI remain separate gates. `git diff --check` passed.
- Independent source review found no blocker. Its suggestion to avoid an
  unnecessary current-cutoff lookup for fixed historical queries was applied
  consistently to both personas and skills; the 37 tests and 20 subtests passed
  again after that adjustment.
- NOT_RUN: candidate image build, candidate Product/browser research,
  end-to-end latency comparison, MCP tool/data qualification, hosted PR CI.
- No push, PR, merge, release or deployment. Existing test/production
  environments, pages, credentials and data are retained.

## Retained test deployment and paired result (2026-11-09)

After ADR-0117 exact historical recovery, the same question was submitted once
per profile through the existing test Gateway with unchanged user/model/search
credential version and execution options. Baseline 316.582s versus candidate
264.778s (16.36% shorter); model calls 33→29 and model time 235.156→141.937s.
Search calls remained 10 and their time increased 68.433→114.029s. This supports
less generation work in this pair, not faster database reads or a production SLA.

Quality is not accepted: the candidate changed a source URL during the child
handoff and left the official dividend denominator unresolved (33.9% calculated
using total attributable profit versus official 35.34% using ordinary-shareholder
profit). Local market data is absent in both runs; public-source coverage differs.
Keep the candidate in test only. Exact IDs, timing method, primary-source checks
and remaining issues are in [the experience evidence](research-experience-20261107.md).

## Source fidelity and dividend basis repair (2026-11-09)

Maintainer explicitly authorized fixing the two retained quality defects, updating
only the retained test environment, and rerunning the identical question;
production must not change. Starting head: `cd9f97f6`.

The current Product coordinator/market-research personas and their skills now
require a compact source list copied from actual web results, with exact URLs,
report periods and supporting excerpts. The coordinator preserves those URLs
and checks claim support against the handoff. Dividend research must distinguish
cash dividend, payout ratio and yield; period, units, distribution status and
ordinary-shareholder profit must agree. A ratio conflict triggers a focused
primary dividend-table/notes check. Failed retrieval remains a verification gap;
third-party summaries are attributed to their actual source, never silently
promoted to company disclosure. No company-specific values are hardcoded.

This is a research-instruction repair, not a deterministic URL validator or a
new runtime harness. Tool privileges, provider/model settings and persisted
market data are unchanged. The independent reviewer accepted the boundary and
requested the source-attribution clarification, which was applied. Existing
profile/version/build/plugin contracts passed: 37 tests, 20 subtests. Actual
same-question quality/latency remains NOT_RUN until the candidate run below.


### Candidate deployment and first quality run

Source commit `624c8829`, unified ACP candidate
`sha256:0d87206caf37eb0a849c1444e7bb56ed5db5b0b91c4039b635a14ee5c3b73249`.
The four changed image files were read back and hashed against source. Only
`runtime-adapter`, `acp-product-runner`, `acp-product-runner-secondary`, and
`acp-judgment-runner` changed image in the retained operator Compose; all became
healthy. No current authorized root or running domain job was present before
deployment; two October 21 revoked/unconfirmed records were preserved. Production
17 container IDs, image IDs and start times matched the saved pre-update inventory.

The original question SHA256 remains
`20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7`;
model/search settings and execution options matched the retained baseline exactly.
First run: `conversation_70dec1ce04dc47acaa09dba020619a9c`, root
`1274bf9d61c24dbe914768a8b1584eb6`. It was soft-cancelled via the Product API
at 861.189s of Backend root lifetime (cancelled/closed, unknown business claims 0).
This is **not a completed-answer latency**. The final generation was interrupted;
no research answer reached the conversation. Its one cancelled provider request
has unknown usage; 29 other model requests returned HTTP 200.

The child handoff did complete shortly before cancellation: all 7 handoff URLs
occur verbatim in actual web_search/web_fetch results (delegate outputs excluded
from the provenance corpus). Its dividend section correctly identifies CNY 50.843 billion / CNY 143.874 billion = 35.34%, using
ordinary-shareholder profit. The source table is in CNY millions:
50,843 / 143,874 = 35.34%. This agrees with the official 2025 annual
report, printed pages 100 and 248. The model used a full announcement reproduction
and labelled the publisher; original-host retrieval was not universally available.
Child-handoff checks PASS; final-answer quality remains NOT_RUN for this sample.

Latency **FAIL**: one two-query risk-section search lasted **604.706s** before
returning `tool call timed out after 60000ms`. All searches totalled 687.481s;
model-request intervals 165.810s (includes the cancelled request), web fetch
3.410s, other tools 2.434s. The DSH base composition enables timeout-policy and
the search provider receives a cancellation signal. Source inspection shows
cooperative cancellation waits for the downstream promise; batch search waits
for all requests. No BYQ configuration omission was found. Which downstream
operation delayed settling is unproven; do not label the cause simply network,
a missing plugin, or the new research instructions. No DSH fork or new timeout
harness was added.

After confirmed cancellation/closure, one fresh same-version, identical-question
retest was started to finish final-answer acceptance. It does not erase this
failure or establish a latency SLA. No further blind retries are authorized by
this evidence record.

### Completed same-question retest and acceptance limits

Retest conversation `conversation_68c587f8655a419887bb7a8909acdc56`, root
`72168b1413e6415e92ab82e8f659bc83`: completed/closed with zero unknown business
claims. Backend UTC 2026-11-09 02:15:34.013951 → 02:19:51.928129,
**257.914178s**. All 30 model calls returned HTTP 200; model-request interval
union 185.801s, 6 searches 58.341s, 8 fetches 5.719s, local tools 4.468s,
unattributed gaps 3.585s, no cross-category overlap. Output tokens 24,783.
This is a single completed sample, not a stable latency guarantee. The previous
264.778s candidate and 316.582s baseline remain separate samples; research
coverage differs, so neither a same-quality speedup nor an SLA is established.

Targeted checks **PASS in this completed sample**:

- All four final citation URLs occur verbatim in actual web_search/web_fetch
  results; child handoffs are not used to establish web provenance.
- Concatenating the two saved assistant segments without separators reproduces
  the native final text exactly (4,581 characters). An initial inspection joined
  them with a newline and falsely suggested a broken URL. That inspection
  artefact is corrected, not attributed to Product transport. AgentView's live
  and replay paths concatenate same-run text without separators.
- The final answer identifies annual dividend 508.43亿元, ordinary-shareholder
  profit 1,438.74亿元 and 35.34%; it distinguishes payout ratio from price-based
  dividend yield, annual/interim amounts and total attributable profit. The
  dividend denominator agrees with the [official 2025 annual report](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20260327/e1efc81f-7ad9-41b7-9b02-5db202026930.pdf),
  pages 100 and 248. The report explicitly lists preferred-share and perpetual
  distributions; the answer's statement that its retrieved text lacked that
  separate list describes its limited retrieval, not absence from the report.

Overall quality **FAIL / not accepted**: before delegation, the coordinator
set research as-of to 2026-03-30 even though the user asked for current research
and never requested that historical cutoff. It conflated the test market-data
calendar cutoff with the public research as-of. The child followed that wrong
instruction, excluded later material, and the final answer used FY2025 instead
of available 2026Q3 financials and described the annual dividend as still
proposed. Thus correct arithmetic and faithful URLs do not make this an adequate
current research conclusion. No fixed date or company-specific figure was added
to product instructions to game the benchmark. This date-selection defect and
the native search cancellation delay remain open, alongside absent local CMB
market data and unverified data-center navigation. No further model reruns were
performed in this repair slice.

Validation scope: real test Gateway/Product API with durable user login; no
fresh browser-rendering acceptance is claimed. The current user page was left
untouched. Four ACP services remain on the candidate; all ten test containers
are healthy. Final production inventory again matched all 17 pre-update
container IDs/images/start times. No production change, push, PR, merge or
remote CI. Private raw evidence and both cancelled/completed test conversations
remain retained under the existing research-candidate-20261109 evidence folder.


### 2026-11-13 日期边界修复与搜索超时调查（未部署）

本轮只修复已经由 native delegate 参数证明的日期混淆：父级把本地交易日历
覆盖终点 2026-03-30 强制当作公开研究截止日，用户并未要求历史研究。
父子角色、研究技能和可信时钟说明现在区分用户显式历史研究日、当前研究日、
各数据集覆盖日；年报期间和“观察3至6个月”不构成历史研究请求。当前研究
需检查最新已披露定期报告和后续分红批准/实施状态；明确历史研究仍排除未来披露。
没有将系统时间当作交易日或最新行情证据，也未改动业务授权或数据。

验证与审查：
- `node --test plugins/dsh-byq/runtime/byq-runtime-time-context.test.js`：4 PASS，
  包含上海当地午夜切换和历史研究/覆盖边界。
- `pytest` 定向 authoritative version/build 与 plugin registry：37 PASS、
  20 subtests PASS；profile、identity 和 authoritative manifest 哈希一致。
- 独立 Reviewer：日期 Functional PASS、上述本地 Tests PASS、Clean Break
  Architecture PASS。Product 质量/耗时、镜像与部署验收均 NOT_RUN。

搜索超时仍 OPEN，不属于本次已修复项：
- 保留先前 root 1274bf9d61c24dbe914768a8b1584eb6、native child
  dd999d3f-94ff-4b82-8628-c3ca41f94085 seq104→107 的604.706秒失败。
  最终错误为60000ms工具超时，但记录没有取消信号实际触发时间或HTTP结束时间；
  不能仅凭该错误断言信号在第60秒已送达HTTP层。
- 核对实际部署镜像 0d87206caf37eb0a849c1444e7bb56ed5db5b0b91c4039b635a14ee5c3b73249
  内 timeout-policy、deadline、tool signal融合、批量搜索及DeepSeek fetch路径。
  guard等待下游退出；信号逐层传递。deadline使用自建AbortController和setTimeout，
  不是AbortSignal.timeout。未发现足以解释该历史等待的确定代码缺陷。
- 同镜像、无外网、无真实凭据的原生provider+deadline测试，等待响应头、
  等待正文、双查询分别约102/102/101ms终止，命令exit0。仅证明这些本地场景。
- 原生registry链夹具首次因测试依赖解析失败未运行；核对实际导出后，工具链
  109ms返回TOOL_TIMEOUT且断言通过，但清理调用不存在的ctx.dispose导致exit1。
  整项不得记为PASS，已停止该夹具批，不继续扩展替代harness。
- 查询同一历史时段系统journal，没有取得支持休眠解释的记录；不据此排除所有
  调度、网络或运行时因素，也不将上游类似问题直接当成本次根因。

未添加丢弃在途调用的Promise.race或修改通用DSH超时语义。遵循用户“两项修好
后再更新测试环境”的顺序，本轮没有构建/部署候选，没有新真实研究调用，
没有生产变更；保留现有测试容器、数据、账号和用户页面。下一验收仍使用原题
SHA256 20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7，
不得将后续单次未超时运行当作历史超时根因或修复证据。


### 2026-11-13 继续定位：复现并修复 GC 后 HTTP 取消失效

后续调查取得了前一阶段缺失的可证伪结果。当前镜像 Node22.23.3 / Undici6.28.1
中，原生 DeepSeekSearchProvider 使用 `redirect: error`，HTTP 已返回响应头但
正文未结束时，垃圾回收可使 Request/AbortController 提前失去保活引用。
外部 deadline 已触发，正文读取却仍在等待。原生 provider 的成功正文和错误正文、
单/双查询四个场景均复现；不强制 GC 的前置对照能正常取消。
官方 [Undici #4627](https://github.com/nodejs/undici/issues/4627) 和
[合入修复 #4750](https://github.com/nodejs/undici/pull/4750) 对应同一机制。
当前 Node22 内置 fetch 没有保活 requestObject；Node24.21.0 / Undici7.29.1
已将其保留至 fetchParams。没有修改 DSH 源码、取消语义或跳过重定向保护。

新增 `tests/dsh_upgrade/search_abort_gc.test.mjs`，使用同一原生 provider/deadline，
仅访问隔离容器内 HTTP fixture，不使用真实 Key/模型：
- 旧镜像：等待响应头2 PASS；成功/错误正文4 FAIL。信号约300ms触发，正文
  直至fixture约1500ms强制断开连接才退出。
- 临时Node24二进制派生候选：6 PASS，约300–308ms退出，请求连接正常关闭。
- 第一版连接断言把Undici额外建立的闲置连接也计入，导致headers额外失败；
  修正为只跟踪实际req.socket后重跑，原输出保留，最终使用v2红/绿证据。

这证明当前版本存在可导致搜索超时不收敛的缺陷，并验证上游修复覆盖该条件。
历史604.706秒记录没有GC/响应头/取消时点，故不声称当时确实发生GC或全部
604秒已被逐秒解释。不能把缺陷复现升级为未采集到的历史事实。

源码修法只在当前正式使用的 `services/acp_unified/Dockerfile` 将builder和runtime
固定到同一Node24镜像digest，并在builder内运行上述回归。DSH release/commit/lock
不变。独立审查Functional/Architecture PASS；依赖/配置37项及20subtests PASS。
仅替换Node二进制的派生镜像用于红绿定位，不部署；从修改后的统一Dockerfile
完整重建和最终镜像验证仍为准入门槛，完成后才更新四个测试ACP容器及同题复测。
生产不在本轮部署范围内。


### 2026-11-13 完整镜像、测试部署与同题最终复测

本节更新前两节的阶段状态：源码修复153282e6已完成，完整统一镜像已构建，
已部署测试环境并完成一次同题Product API复测；研究质量仍有明确FAIL项。
未部署临时仅换Node的派生镜像，未更新生产。

最终完整镜像 `byq-local/research-acp-date-timeout-full:20261113`：
`sha256:ec90cb94ff0b050d5cec9270360f98ae18c3e14a2925eee492b709f559d1d2bc`。
从修改后的统一Dockerfile构建，DSH官方source/lock不变，native system在Node24下
重建。构建内6项取消回归PASS；最终镜像重验6项PASS（约300–311ms结束且连接关闭），
可信时钟4项PASS、CLI版本rc2、system.node及pty.node加载PASS。
三角色/恢复合同首批51 PASS、15 FAIL，失败均因测试启动命令漏了现有环境要求的
no-new-privileges；核对fixture并加回该参数后，两份受影响runner测试28 PASS。
未改产品安全配置，未抹掉首批失败。另有统一镜像合同15 PASS/5subtests和切片
`dev-check --base dcf22dbd` PASS；远端CI/发布资格NOT_RUN。

只修改正式development-test Compose四个ACP服务的image字段。生产17个容器
ID/image/StartedAt未变；测试其余6个容器未变，四个ACP容器均使用上述完整镜像。
测试10个容器健康，卷/挂载语义未变。初次直接比较Mounts数组因Docker返回顺序
变化失败；核实差异只有顺序，随后统一按Destination比较，保留此观察器错误说明。
两条既有authority_revoked_unconfirmed历史root保留，没有新未决业务操作。

原题SHA256仍为20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7。
测试账号的模型与执行选项与上一轮逐对象相同。新会话
`conversation_ae2911b44ec34af8bddb3db9ceade62b`，root
`794e0b0c78904db0be540d82de2d38ad`，Backend UTC13:16:52.831514至
13:20:36.086083，completed/closed，terminal_unknown_claim_count=0。

| 指标 | 上次完成轮（11月9日） | 本轮（11月13日） |
| --- | ---: | ---: |
| Backend全程 | 257.914秒 | 223.255秒 |
| 模型请求次数 / 区间并集 | 30 / 185.801秒 | 33 / 139.069秒 |
| 搜索工具次数 / 区间并集 | 6 / 58.341秒 | 8 / 71.208秒 |
| 页面抓取次数 / 区间并集 | 8 / 5.719秒 | 13 / 8.092秒 |
| 本地工具区间 | 4.468秒 | 2.291秒 |
| 区间外差额 | 3.585秒 | 2.595秒 |
| 上游输出tokens | 24783 | 23797 |
| 公开答案字符数 | 4581 | 5657 |

本轮33个模型请求均HTTP200；8次搜索为5.043–15.364秒，无工具超时。
搜索区间包括搜索侧模型工作，不是纯网络或数据库时延。各类别没有交叠；父级
delegate等待不重复计入。本轮比上一完成轮少34.660秒（13.44%），主要对应模型
阶段缩短，搜索总耗时反而增加。日期已变化、公开资料和随机输出不能锁定，故只
描述两次观察，不将差异归因于Node修复，不宣称稳定提速或SLA。

质量核验：
- 日期目标PASS：delegate明确用户未指定历史日，公开研究截止2026-11-13
  21:16（Asia/Shanghai），本地日历03-30另列为覆盖缺口。答案纳入2026三季报，
  2025年度末期分红状态正确改为2026年7月已实施。未编造本站行情/估值。
- 引用保真PASS：7/7完整URL精确存在于实际web_search/web_fetch结果URL集合中；
  原生最终公开文本与持久化分段无分隔拼接完全一致。首次比较误读data.content，
  核实原生结构为data.message.content后，仅比较text块；未输出reasoning内容。
- 核心财务抽检：营收2648.52亿元、归母1164.76亿元、同比5.34%/2.38%、ROE13.49%
  与[公司三季报第2页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20261030/ba4dc24b-e84a-4228-bbf6-a1b52e638eca.pdf#page=2)相符。
- **整体质量FAIL**：派息率35.34%、分母普通股股东利润1438.74亿元主数字正确，
  但解释仍附了不适用的33.85%算术对照，反向表述利润扣除关系，还称差额构成
  “未逐项披露”。[2025官方年报第248页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20260327/e1efc81f-7ad9-41b7-9b02-5db202026930.pdf#page=249)
  明确列示1501.81−9.96−53.11=1438.74亿元，第100页列示508.43/1438.74=35.34%。
  引用真实不等于解释正确，原先分红口径整改不能整体关闭。
- 另有未经核实的未来时间判断：观察窗写2027年2月至5月，却把2027一季报
  “大概率”归在窗外，没有取得具体披露排期依据；此项保留待整改，不作为事实。
- 只做研究，实际工具列表没有策略、股票池、研究保存、交易信号或订单创建。
  浏览器本轮NOT_RUN（Chrome连接不可用）；正常测试用户Gateway/Product API已验收。

独立Reviewer与Root：日期修复、GC类搜索取消回归、限定部署和本轮运行结算PASS；
研究结论整体FAIL，历史604.706秒的确切GC时点仍UNPROVEN。正常新样本不能替代
受控取消回归或反向证明历史成因。测试环境与原页面保留供用户共同检查。
原始证据在既有私有目录：date-timeout-full-*.txt、date-timeout-gc-*-v2.txt、
date-timeout-retest-*、date-timeout-environments-{before,deployed,final}.json，
包含首次失败；未推送、合并或修改生产。

### 2026-11-14 分红解释与观察期判断：候选修复

维护者接受上一轮建议，继续修复这两个已复现的质量错误、更新测试并同题复测；
生产不动。Git起点6b08dae5，复用当前隔离工作树，不推进Product Phase。
核对上一轮root/child最终公开text（不读取reasoning）后，确认不适用的33.85%对照、
跨期扣除解释和“未逐项披露”断言已在child交接出现，root照搬；child未来排期
判断也缺少边界依据，root另添加未核实的一季报窗外判断。

本次仅调整两角色persona及对应skill：交接保留同期间/股类/状态的分子、分母
原标签、单位、原表行和来源；只有同期间主报告调节表才可解释利润扣除，
不兼容算术对照直接省略，未取得依据不等于公司未披露。主角色独立核对交接。
观察期从明确起点计算各日历月终点，分别判断三个月/六个月；按披露或实施日
而非报告期判断，区分确认排期与预计，跨终点区间保持不确定。不增加工具、
权限、硬编码股票数字或第二套harness。身份及manifest哈希同步。

37项版本/构建/插件合同与20subtests PASS，切片dev-check及diff检查PASS。
独立Reviewer：候选Functional/Architecture PASS；真实质量尚待Product复测。
复用前轮完整Node24镜像ec90cb94…作为限定派生基础，仅覆盖研究profile/identity/skills；
不声称重新完成Full或远端CI。部署前生产17容器运行（12 healthy），测试10 healthy；
仅两条既有authority_revoked_unconfirmed root，未发现正在获授权执行的新研究。

### 2026-11-14 分红与观察期：测试部署和同题复测结果

源码4c7f20d2；测试派生镜像
`byq-local/research-acp-dividend-window:4c7f20d2`，
`sha256:d769e96fadb8b41b4fa38a58f1164d61c79ee89b355e49213c4b7dc21c441c5b`。
基础为前轮完整ec90cb94…镜像，Node/DSH及依赖未变。镜像中profile、identity、
两份skill的实际SHA256与源码一致；只COPY这四份只读文件及候选标签。首次构建
将image ID直接写作FROM sha256:…，被BuildKit解释为远端仓库而失败；保留日志，
核对本地tag的精确ID后修正引用，一次重建成功。无第二次同类错误、无额外模型调用。

正式测试Compose仅四个ACP服务image字段改变，配置校验PASS，更新命令exit0并
等待四服务healthy。前后及复测后快照证明：生产17个容器ID/image/StartedAt/挂载
未变（12 healthy、5无healthcheck的worker running），测试10 healthy，其他6个
测试容器未变，所有挂载按Destination归一后语义相同。测试数据和页面保留。

本次只提交一次未改动的原题，SHA256仍为
20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7；测试账号
模型与执行设置逐对象等于上一轮。会话
`conversation_08f501818b69420abcacfd8066c52343`，root
`fccf169091f34bd99d170fcdf9738f77`，Backend UTC2026-11-13 22:44:49.049848
至22:51:08.848149，**379.798301秒**；北京时间为11月14日。
completed/closed，terminal_unknown_claim_count=0，无重放、取消或业务写入。
正常Gateway/Product API已验证；浏览器本轮NOT_RUN，不冒充浏览器验收。

| 质量项 | 本次结论 |
| --- | --- |
| 年度分红口径与解释 | PASS（单次样本）：508.43亿元/普通股股东利润1438.74亿元=35.34%，每股2.016元；不再给不兼容33.85%、跨期扣除解释或“未逐项披露”断言 |
| 2026中期分红状态 | PASS：计划已批准；金额/每股/登记日未检索到实施公告并标未核验，保留已披露2027年1–2月派发窗口 |
| 观察期判断 | PASS：起点2026-11-14，三个月2027-02-14、六个月2027-05-14；1–2月窗口跨三个月终点，三个月归属不确定、六个月内；年报/一季报预约日期未取得，不再断言在窗外 |
| 日期和本地覆盖 | PASS：可信当前研究日与03-30未验证日历分开，纳入2026三季报；本站无行情/估值不编PE/PB/股息率 |
| 引用及持久化 | PASS：7/7完整URL（包括原工具返回的fragment）精确属于web工具结果集合，原生最终text与持久化分段无分隔拼接完全相等 |

分红数字另与[官方2025年报第100页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20260327/e1efc81f-7ad9-41b7-9b02-5db202026930.pdf#page=101)核对；
营收/归母净利润/同比/年化ROAE与[官方三季报第2页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20261030/ba4dc24b-e84a-4228-bbf6-a1b52e638eca.pdf#page=2)相符。
产品本轮仍主要使用法定披露报纸版和公告转载文本，不能把工程侧PDF核验算作
Product已具备PDF表格解析能力。主回答明确保留该来源限制。未验证所有未来
排期的不存在性；“未检索到”只表示此次检索结果。

| 指标 | 前轮11月13日 | 本轮11月14日 |
| --- | ---: | ---: |
| Backend全程 | 223.255秒 | 379.798秒 |
| 模型请求数 / 区间并集 | 33 / 139.069秒 | 38 / 263.740秒 |
| 搜索次数 / 区间并集 | 8 / 71.208秒 | 11 / 108.506秒 |
| 页面读取次数 / 区间并集 | 13 / 8.092秒 | 19 / 4.529秒 |
| 本地工具区间 | 2.291秒 | 1.098秒 |
| 区间外差额 | 2.595秒 | 1.925秒 |
| 上游输出tokens | 23797 | 50540 |
| 最终公开答案字符数 | 5657 | 3915 |

**耗时退化/FAIL**：比前轮增加156.544秒（约70.1%）；模型阶段增加124.671秒，
搜索增加37.298秒。38个模型请求均HTTP200；11次搜索单次4.783–15.201秒，
没有超时。模型区间含请求等待和输出，搜索区间含搜索侧模型工作；父delegate
等待241.189秒不重复累计，各类别无交叠。delegate结束后仍有5次模型请求，
合计104.245秒。实际工具参数可见多次围绕三季报EPS与未来年报预约日期检索、
3次产品帮助查询；不能将全部重复主题都判无效，后续应按新增证据与问题必要性
收敛。最终答案更短不代表模型工作更少。单样本不建立稳定SLA或证明规则修改
单独导致变慢，亦不把未超时说成历史所有超时均已解释。

独立Reviewer与Root：**两项研究质量限定PASS**，运行结算及限定测试部署PASS；
**耗时优化未通过，全体验尚未关闭**。数据缺口续研、失败恢复提示及其他原有
体验遗留项不在本切片内，没有宣称完成。优先后续收敛重复检索/主子任务重复整理，
保留来源核验要求。远端CI/生产发布NOT_RUN，未推送、合并或更新生产。
私有证据：dividend-window-{build,build-v2,deploy}.txt、acp-dividend-window.Dockerfile、
dividend-window-compose-preflight.json、dividend-window-environments-{before,deployed,final}.json、
dividend-window-retest-*（含原始公开回答、原生记录、请求日志、指标及交接）。
