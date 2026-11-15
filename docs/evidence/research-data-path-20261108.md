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

### 2026-11-14 继续验收整改：摘要范围与交接收敛候选

维护者要求“继续验收整改”，继续限定测试部署/原题复测，生产不动。起点af170a43。
复核已保留的真实公开工具参数与结果：前轮child交接8566字符，上一轮4759字符；
委派扩大到EPS、多种资本指标、历史风险及完整分红日历，随后多次检索三季报EPS、
旧息差及未来预约日期。delegate后5次模型请求104.245秒；3次产品帮助结果只有
430/162/1701字符且接口很快，不能把耗时归因为帮助接口慢或仅归因为文本长度。

候选收紧默认摘要的主题范围，额外指标只在用户明确要求或影响重要结论时检索；
交接为一份主题/证据表、去重来源及重要缺口，避免多份报告；不可读必要表格一次
定向权威替代后明确缺口，未来排期定向核实后不循环猜测。来源、同期间分红及
最新实施状态核验保留，字数是软目标，详细请求/必要证据优先。研究后的“下一步”
仅给一两项相关能力，复用已知指南，未决能力才查询。不新增工具、权限、harness。

独立审查指出旧来源清单规则仍要求重复摘录，已统一摘录仅出现在finding行，
来源清单保留每个原始URL、标题和日期；修正后37 tests/20subtests PASS、
diff检查PASS，切片dev-check PASS。真实质量/耗时尚待同题验证。

### 2026-11-14 摘要收敛首轮：速度下降但质量回归（FAIL保留）

源码2c5345fb，派生测试镜像eab8b6f4d58828fc21413e6058f8a770a10f35268f46d7d01a52c331e0e809e5。
镜像4文件实际哈希一致，测试仅四ACP更新/10healthy，生产17未变。正常测试账号
设置不变，原题提交一次：conversation_b7b69141bbf447838fa95e1253aaf646，
root5765aa7ffa1043078fa4610f8016f59b，Backend UTC23:59:54.115485至
次日00:03:39.042810，224.927325秒，completed/closed，unknown=0。
模型44次/131.407秒，搜索8次/85.945秒，读取13次/4.390秒，本地1.320秒，
差额1.865秒；输出tokens21741，child4815字符，最终2729字符；全模型HTTP200，
搜索无timeout。耗时较379.798秒下降，但本轮不能验收为PASS。

**质量与引用FAIL**：root委派主动要求网页PE/PB/股息率填本地缺口，虽标第三方，
仍违反既有数据边界；还把截止日写成“之后公开资料都纳入”（本次实际引用仍在
截止前，不能称已采用未来资料）。child据此检索网页估值/预测，研报的净息差
1.83%、信用成本0.74%被当2026Q3公司指标，实际公司报告为1.82%/0.72%；root照搬。
child去掉同花顺URL末尾#1，root沿用，因此7/8 URL精确保真，原生与持久化文本相同。
分红主数字/观察终点仍正确，但不抵消其他质量失败。

针对性纠正：两角色同时拒绝用标注第三方的报价、PE/PB、预测收益率和目标价
补本地覆盖缺口；公开报表盈利/分红仍可研究。已报告财务指标必须有同期间/
指标/实体/单位/计算口径的公司公告或法定披露转载支撑，研报只作线索，缺原文
不照搬数字。当前与历史均排除截止日后资料，拒绝相反委派；URL scheme/query/
fragment都逐字保留。摘要收敛保留，不改权限、依赖或工具。37 tests/20subtests
PASS，独立审查Functional/Architecture PASS，进入一次限定复测；若再失败，
保留失败并停止本批，不用速度掩盖质量。首次脚本文本定位因折行assert在写入前
停止；核对真实marker后完成，无半写配置。首轮抽取child文本的命令因只读环境
写文件失败，改在已授权证据写入调用中完成；两者均没有重复提交真实研究。
首轮证据保留于summary-scope-*，不覆盖。后续纠正证据使用summary-evidence-*。

### 2026-11-14 摘要证据边界纠正：最终限定验收

源码e5b55b4d，派生测试镜像
`byq-local/research-acp-summary-evidence:e5b55b4d`，
`sha256:1bb3a2cea19d982d0310943a96e3d1a0a8521fb79bef0a7ea32eb265bef4a2ef`。
四份研究规则/身份文件的镜像内哈希逐一匹配源码；Node/DSH/权限及依赖不变，
不是新的Full或发布资格。测试Compose只改四ACP的image，命令exit0后验10healthy；
最终快照确认生产17容器ID/image/StartedAt/mounts与本批开始完全一致，测试其他
6容器和所有挂载未变。前两条已撤权历史root保持原状。

本批首轮失败后，针对已定位边界只进行这一次纠正复测。账号模型/执行配置
逐对象与首轮及之前质量通过轮相同，原题SHA256仍为20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7。
会话`conversation_9a060444316347d3b1dc7677857a4fb4`，root
`1c81e70e76764a149098e11fe109a145`，UTC2026-11-14 00:09:40.428412至
00:13:23.448958，**223.020546秒**，completed/closed，unknown=0。
Gateway/Product API真实验证；本批浏览器NOT_RUN，不冒充浏览器验收。

| 指标 | 前次质量通过样本 | 本批首轮失败 | 最终纠正样本 |
| --- | ---: | ---: | ---: |
| 完整耗时 | 379.798秒 | 224.927秒 | 223.021秒 |
| 模型请求数 / 区间并集 | 38 / 263.740秒 | 44 / 131.407秒 | 27 / 139.634秒 |
| 搜索数 / 区间并集 | 11 / 108.506秒 | 8 / 85.945秒 | 9 / 77.836秒 |
| 页面读取数 / 区间并集 | 19 / 4.529秒 | 13 / 4.390秒 | 11 / 2.248秒 |
| 本地工具区间 | 1.098秒 | 1.320秒 | 1.450秒 |
| 区间外差额 | 1.925秒 | 1.865秒 | 1.853秒 |
| 上游输出tokens | 50540 | 21741 | 27194 |
| 子任务交接字符 | 8566 | 4815 | 3682 |
| 最终公开答案字符 | 3915 | 2729 | 3698 |

最终较前次质量通过样本减少156.778秒（41.28%）；模型区间减少124.106秒、
搜索区间减少30.670秒。交接后仍有5次模型请求，但累计104.245→27.820秒；
不是简单把请求次数降为零。搜索含搜索侧模型工作，不是纯网络时间；父delegate
等待不重复计入，各类别无交叠（浮点末位误差归零）。27个模型请求全HTTP200，
9次搜索6.254–10.759秒，无timeout。单次对比不能证明稳定SLA或排除模型/资料波动，
本批不再盲测。

**独立Reviewer与Root：本轮纠正目标限定PASS**：
- root委派正确限定cutoff之前资料，明确拒绝网页报价/PE/PB/预测股息率/目标价
  补本地覆盖缺口；child及最终答案均未再提供此类替代值。
- 关键财务指标来自法定披露原文/可识别转载，分红508.43/1438.74=35.34%，
  每股2.016元同口径；净息差回到2026年1–9月1.82%，未再误引信用成本0.74。
  工程抽检[公司2025年报第100页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20260327/e1efc81f-7ad9-41b7-9b02-5db202026930.pdf#page=101)
  及[三季报第5页](https://s3gw.cmbimg.com/lb5001-cmbweb-prd-1255000097/cmbir/20261030/ba4dc24b-e84a-4228-bbf6-a1b52e638eca.pdf#page=5)支持相应主数字；集团权重法核心一级12.08%在第11页有据。
- 观察起点11-14、三个月02-14/六个月05-14保持正确；1–2月现金派发区间跨
  三个月终点，未来年报预约日期未取得不猜。
- 7/7 URL与真实web工具结果集合精确一致，包括fragment及长query；原生最终
  text与持久化分段拼接完全一致。没有策略/股票池/研究保存/交易订单创建调用。

**整体体验仍未关闭，以下保留整改项**：
1. 不允许外部数据替代本站口径，并不意味着外部有出处报价或可审计推算就是
   “编造”；本轮对此文案过强。
2. “唯一有官方时间窗”没有公告全集穷尽证明；中期具体金额/登记等应写
   “本轮未检索或未核验到”，不能绝对说“均未公告”。
3. 现金派发窗口不自动覆盖股权登记日；观察表应只标派发窗口，登记日单列
   未确认。
4. “先补齐数据”的建议尚无清晰的当前用户可用权限路径，缺数据→准备→续研
   体验仍需后续功能整改。本轮没有新增自动任务/提醒或解决该流程。

限定核心验收通过不代表所有句子均已验证、所有体验完成或具备正式发布资格。
本批开发/定向合同/审查/测试候选部署有证据，远端CI/生产发布NOT_RUN；未推送
或合并。测试环境与当前页面保留。证据为summary-evidence-{build,deploy}.txt、
acp-summary-evidence.Dockerfile、summary-evidence-compose-preflight.json、
summary-evidence-environments-{before,deployed,final}.json及summary-evidence-retest-*。
首轮summary-scope-*完整保留，未用最终通过覆盖失败。


## 2026-11-15 研究措辞与缺数据接续流程整改

本次维护使用原隔离工作树。研究规则提交 bcdcc08f，Product 准备流程
907d5da2，空交易范围后端校验 78b8c2b2，指引与实际上限一致性修正 f8f1625e，
重试回归 db63a7e6。更新范围为 byq-development-test，生产保持原部署。
远端 CI、推送和生产发布均 NOT_RUN。

### 功能与恢复

原会话增加准备研究数据入口，显式确认规范代码、日期及所需字段。普通用户通过
Gateway/Product readiness 查看覆盖，缺口生成仅携带范围的管理员链接。管理员
复核后通过新增 Product preparation API 复用 MarketAutomationStore 持久化准备
请求，原会话必须重新检查同一范围后才能带入续研草稿，发送仍由用户确认。

范围限 1–20 个标的、180 个自然日。估值与财务字段使用现有允许列表，准备沿用
按交易日获取的既有 Data Plane。普通用户无准备写权限。任务完成回执只描述执行
状态，字段值、分红口径与来源仍需续研核实。零交易日、零有效记录范围阻止准备。

独审发现最初实现的 retry_terminal=False 使终态任务无法恢复。现已加显式管理员
重试，按 request_id、requirement hash、status、completed_at、error 生成终态版本，
在行锁事务内对当前版本做单次状态变更。同一范围重提只返回原请求；失败/已完成
但覆盖仍缺需要重新确认重试。响应中断先只读刷新原任务，旧版本不能重新排队
下一代失败。新 API 不暴露其它领域准备任务。

范围草稿按用户和会话保存在 sessionStorage，页面刷新后恢复，覆盖结果必须重查。
关闭标签或换设备需要重新填写范围。现有输入框草稿追加续研前需确认。

### 定向验证

- Backend data API 初批 13 项、CAS 真实 PostgreSQL 回归 1 项通过，后续零范围 2 项、
  retry API 权限及当前覆盖再核对 1 项通过。既有 readiness/repair 4 项通过。
- Gateway preparation admin-only 转发回归 1 项通过。
- Frontend API/范围校验/组件初批 12 项通过，补充重试中断恢复 1 项通过。
  首次新增组件测试定位器错误已修正，失败未混作通过。
- 前端 vue-tsc 和 Vite 构建通过。profile/identity architecture 25 项通过。
  首次 unittest 模块路径错误已纠正，临时文件受只读沙箱限制后使用获批执行完成。
- git diff --check、dev-check local_syntax PASS。定向测试使用隔离、无外部网络、
  无持久卷的 PostgreSQL byq_domain_test，未对保留测试业务库执行测试 DDL。
- Independent Reviewer 对终态恢复限定 PASS。其零交易日 API 意见已落实且两个
  回归通过。Product 全链路仍受以下实际数据源缺口约束。

### 测试部署与浏览器

七个既有服务替换为基于当前已验证镜像的限定派生候选，新增既有 data worker。
预检时保留测试栈的八类待执行队列表均为零、自动调度关闭，获授权 active root
为零。worker 使用测试密钥环，独立非特权 UID、只读文件系统，无主机数据挂载。
心跳正常，last_error 空，自动调度仍关闭。

Compose 等待部署通过，测试 11 个容器运行，10 个具有 healthcheck 的服务健康。
新 worker 用数据库心跳验证。17 个生产容器 id/image/started/health/mounts
逐对象匹配基线，原 10 个测试容器的挂载全部保留。快照验证曾因未序列化 tuple
与 JSON list 比较误报，按同格式持久化快照复核一致，未发现实际挂载差异。

真实 Chromium 使用 C 普通账号和 A 管理员、Gateway/Product API 验证。
原会话 conversation_2fa02883797e4febbec58e3997e9646e，准备范围
600036.SH / 20261113 / pb。普通用户 readiness 200、verdict unavailable，
准备写 403。管理员链接只含范围，不含会话/身份；显式复核前提交按钮禁用。
管理员确认后返回 409，明确提示无法解析唯一有效 Tushare 数据源。原会话刷新
保留范围，复查仍缺失且无续研按钮。

已现场核实该测试栈 Tushare 配置为空，环境无 TUSHARE_TOKEN。
没有借用生产凭据，真实补数至 ready 的 Product 正向链路 NOT_RUN，阻塞为待配置
测试 Tushare 数据源。已向用户请求在测试页配置专用 Key。
ready 后填草稿分支目前只有定向组件证据，不能替代真实数据补齐验收。

### 原题真实研究第一轮

沿用 benchmark-question.txt，SHA256
20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7。
账号模型与执行配置与上轮逐对象相同。会话
conversation_d865c34c4d0b441191619b2cedac8a5a，root
71e139c44148401d94817b062789de26，completed/closed，unknown=0。
持久化结算 178.700910 秒。25 个模型请求全 200，5 次搜索、9 次页面读取，
没有工具错误。模型区间并集 115.608 秒、搜索 56.145 秒、网页 2.320 秒、
本地工具 2.606 秒，区间可能重叠，不能简单相加等同总耗时。

7/7 URL 与真实工具来源完全匹配，原生最终文本与持久化拼接完全一致。
未创建策略、股票池、回测或交易。无行情/估值/财务覆盖仍明确披露，未检索到
与尚未核实用语替代原穷尽式断言。

质量第一轮保留 FAIL。下一步建议给出全年跨度，超过实际 180 天上限，使用了
不存在的接续研究按钮，且普通用户检查/管理员提交的表述不准确。f8f1625e
明确规范代码、范围上限、近端最小范围、管理员写权限和实际带入续研草稿按钮。
只有四个测试 ACP 服务再更新，第一轮结果完整保留。

本批私有原件目录为
/home/jefison/.local/state/byq-maintenance/research-candidate-20261109/preparation-20261114。
包括各镜像 Dockerfile、build log、image id、Compose 前后版本、deploy log、
environments-before/after/final.json、browser.json、submission/product/terminal、
answer.txt、metrics.json。guidance-corrected 子目录保存针对具体指引失败的纠正
复测，未覆盖第一轮结果。


### 指引纠正复测与公告状态纠正

第二轮会话 conversation_042c3f70291b474687846bec77473487，
root ff7a8a2261df42edb92836007c8ae188，结算 175.462513 秒，
completed/closed，unknown=0。25 个模型请求全 200，5 次搜索、13 次页面读取，
其中一次 web_fetch 错误；来源链接 3/3 精确匹配。原生文本与持久化差异仅为
既有 Product 术语投影 coverage_unverified → 覆盖完整性尚未验证，使用源码
project_public_answer_text 后完全一致。此核验曾在容器替换中途读取失败，
等待 Compose healthy 后完成，没有重发研究。

指引目标 PASS，规范代码 600036.SH、180 自然日上限、近期范围、管理员交接与
带入续研草稿均准确。整体措辞目标继续 FAIL，每股金额/总额仍被写成尚未公告，
检索缺口不能建立当前公告状态，三月计划写另行公告只证明当时计划。
bc382b25 进一步限定逐句审查公告/披露/支付状态，明确历史公告的时间边界、
本轮未检索到和本轮尚未核实，状态须各有相应日期的证据。25 项 profile/
identity architecture 再验证通过。四个测试 ACP 服务更新后针对同一问题再次
验证，前两轮失败不覆盖。

测试 worker 的 Provider 环境已与 Backend 对齐，使用相同默认端点与测试密钥环。
未引入独立端点配置；现场心跳正常、last_error 空、准备记录仍为零。


### 第三轮、真实数据源与完整浏览器补数

第三轮同题会话 conversation_561b9e773d414c7e829bc0b29e75aaa0，
root e1ef48d228564e8a9c950e7355c318f7，completed/closed，unknown=0，
结算 310.334831 秒。31 次模型请求全 200，13 次搜索、22 次网页读取，
一次 web_fetch 错误，6/6 引用 URL 来自实际工具结果；Product 术语投影后最终文本
与持久化完全一致。模型区间 175.528 秒、搜索 124.773 秒、网页读取 5.600 秒。
这次多检索了分红批准决议及同口径分母，耗时高于上次 223.020546 秒，不能宣称
稳定提速。前两次 178.700910 / 175.462513 秒同样不能证明稳定 SLA。

金额改为本轮未检索到，批准状态有决议来源，准备入口与上限正确。仍保留两处
措辞问题，具体日期尚未确定和地方融资平台敞口无量化披露，本轮检索缺口不足以
证明这两个当前状态。d29b3d2c 对这些结尾缺口与日期句再限定，不把第三轮记录
改为全面质量 PASS。最终测试候选应用这一修正，后续在同一会话验证真实续研。

用户随后明确授权直接找生产 Key 配置测试。只读事务检查生产 credentials，
生产有效来源为环境 TUSHARE_TOKEN。密钥经内存由生产容器传入测试管理员
Product credential API，并由测试自身密钥环加密存储，未输出、写入证据或提交。
生产无写操作。credential-copy-receipt.json 仅记录来源类型与测试目的地。

首次真实准备 datarepair_2ab2e9c91d594ceca3981933d071ad6f 返回 failed /
readiness_not_satisfied。Product readiness 精确定位证券目录缺少 600036.SH
上市状态，非 Provider 猜测。管理员通过现有 security-master sync Product API
提交 securitysync_2d6f1ed148fa42bea20a16ca31e3e871，completed，收到 5923，
导入 5922，隔离 1 条，保留其现有验证/隔离规则。新目录快照
securitysnapshot_11881223becf8c5508278a4d5b4146a2。

相同 symbol/date/field 范围重新确认后按新目录快照形成准备
datarepair_ec90f80062fe45fcab701bd343838f1e，queued → waiting_for_sessions →
completed。20261113 市场任务 completed，持久化规范日线 5571 条、
估值 5571 条。均由既有按交易日 Data Plane 路径取得，未伪造成逐股票 Provider 请求。

真实普通用户浏览器持续复查同一范围达到 usable，仍在原会话、带入续研草稿
成功且未自动发送。with-source/browser.json 记录该过程，初始回执为第一次
失败任务，后续实际成功任务由 after-directory-submit.json 及数据库结算互证。
首次失败保留。with-source/resumed-draft.png 为真实页面。

d29b3d2c 同时修复此前暴露的目录前置死路。准备前遇到缺少证券状态时，返回
可操作 409，指向证券目录，避免排入必然失败的准备。管理员审核卡可直接切换
数据中心现有证券目录页，完成目录同步后重新确认相同范围。新增 backend
回归通过，审批卡 3 项再次通过，vue-tsc/Vite 构建通过。

最终 Backend、frontend、四个 ACP 测试服务更新，Gateway 和 Data Worker 保留
此前已验证版本。真实浏览器在第三轮招商银行原会话打开目录按钮验证可达，
复查 600036.SH/20261113/pb 为 usable，带入草稿并由用户已授权的测试动作点击
发送。续研 root e34e4899667845129dab8ba6e4d86f91，原会话身份保持不变。
这次覆盖就绪后的续研使用新数据，不能与先前无本地数据的同题样本做等条件
耗时比较。continuation/ 保存原会话、草稿、截图、提交和结算原件。


### 最终结算与验收范围

续研 completed/closed，unknown=0。结算时间 2026-11-14T20:57:22.445371Z 至
20:57:52.699156Z，**30.253785 秒**。8 次模型请求全部 200，本轮只执行持久化
估值与交易日上下文读取，无新搜索或网页读取，无工具错误。模型区间并集
28.255 秒、本地工具 0.892 秒。没有股票池、策略、回测或交易创建。
公开最终文本按既有 Product 术语投影后与持久化完全一致，沿用的 3 个 URL
逐项包含于同一会话上一轮已验证的 6 个来源中。metrics 的本轮 unmatched
只表示没有在本轮重新抓取，unmatched_after_verified_history 为空。

续研读取 600036.SH / 20261113 / pb=0.916，完整性 usable=true、complete=true，
来源 Tushare 持久化数据集。工程只读 SQL 复核该行 PB=0.916，与公开回答一致。
本轮对未读取的价格/PE/股息率明确列为缺口，具体分红日期写本轮未检索到，
没有继续使用前轮无量化披露的推断。引用旧研究时保持日期和分红分母口径。

最终裁定为**本次限定范围的缺数据→管理员准备→原会话复查→实际续研 PASS**。
真实范围是一个交易日、一个 PB 字段。长区间、更多估值与财务字段没有再次做
真实 Provider 补数测试，不扩展认定其已全量验收。跨设备范围恢复仍需重填。
措辞规则及本轮续研缺口表述目标限定 PASS，三轮完整摘要中已发现的失败样本
均保留，模型输出仍须按具体运行验收，不能认定未来所有句子均不再出现误断。

最终独立 Reviewer 补查发现缺项列表最多 200 条，目录缺口可能被截断。
f6328c7d 已改读未截断 missing_by_dataset，并以未截断/截断两个回归验证。
Reviewer 确认阻断解除。最终只更新测试 Backend 至对应镜像，Product readiness
现场再核为 usable；测试 worker 心跳新鲜、last_error 空，临时无持久卷测试 PG
已停止，保留测试环境及数据。

最终 environments-final-verified.json 与更新前生产 17 容器逐对象一致，测试原
10 容器挂载一致。测试当前 11 容器（新增必要 data worker），现有环境、数据库、
测试身份与原会话保留。生产只读获取用户已授权的 Key，未修改生产配置或容器。
最终源码 f6328c7d，文档提交单独记录；未推送、合并或生产发布。

完整原题耗时为三次 178.700910、175.462513、310.334831 秒，上轮基准
223.020546 秒。模型/搜索次数与范围随实际检索变化，不能声明稳定提速。
30.253785 秒属于单日 PB 就绪后的同会话续研，与完整联网研究分别列示。


## 2026-11-15 多字段完整研究验收

用户确认继续扩大当前研究验收。本批复用原工作树与测试环境，起点 5a0a5feb，
生产权限仍仅为此前明确授权的凭据只读复用，不新增生产写操作。
测试原有估值记录已含 20261113 的 PE/PB/股息率/总市值，财务记录原为零。
确认范围为 600036.SH、20261113，一个交易日，估值字段 pe_ttm/pb/dv_ttm/total_mv，
盈利字段 eps/roe/or_yoy/netprofit_yoy。这里只验收当前研究的多字段数据，未声称
获得更长历史日线或完成所有财务修订的历史回测资格。

### 精确失败与窄修复

真实普通用户→管理员浏览器提交 datarepair_bbd02fe3c9b74c3eb8b614841076b254。
首次准备失败 ProviderProtocolError，原失败回执和浏览器结果保留。
一次相同范围的只读诊断定位到 provider returned duplicate financial-indicator rows：
fina_indicator 请求报告期 20250512–20261113，原始返回 8 条；20260630/20260829
和 20250630/20250830 两组分别包含 update_flag 1 与 0。
这是 Provider 版本记录，不是权限失败或搜索超时。

[Tushare 官方 FAQ](https://tushare.pro/document/2?doc_id=122) 第7问解释
1 为修正后的数据、0 为初始数据。688a8235/4207d1d1 只修改财务适配器和原有
持久化逻辑：同报告期、同公告日的重复组，必须只有一个1且其余全0才选择1；
多个1、只有0、未知标记均报协议错误，不同公告日分别保留。
原始来源行数仍为8，规范导入6条，未将过滤后的数量伪装成原始响应数量。

独审指出修正版缺少实际修正发布日期。本次新增重复组通过可信取得时间记录
revision_observed_date，仅从该观察日或公告次日两者较晚日生效，不倒填原公告日。
观察凭证保存在既有 provenance_json；相同内容再次获取保留首次观察日与生效日，
内容变化使用新观察边界。旧无凭证单行切换到已观察修正版时不能继承旧日；
后续再次只返回同值单行也继承已建立的观察凭证。
单条 flag1 从未出现重复时的既有历史 PIT 局限保持未资格化，不以本次当前研究
PASS 覆盖它。不存在修正发布日期证明的旧财报历史回测需要单独核验。

Provider 模块36项通过，隔离 PostgreSQL 5项通过，覆盖顺序无关、歧义拒绝、
不同公告日、原始来源行数、公告/观察日可见性、重取稳定性及旧数据切换。
Independent Reviewer 接受本次重复组当前补数路径的限定 Functional/Clean Break PASS，
历史 singleton1 限制明确保留。dev-check local_syntax PASS；无架构例外、新依赖、
新 Worker 或表结构改动。远端 CI/正式发布 NOT_RUN。

### 测试更新与真实恢复

从当前已验 Backend 固定镜像派生，仅覆盖 data_provider.py 与 market_readiness.py；
测试 Backend 与既有 data worker 更新，前端、Gateway、ACP 保持本轮起始镜像。
镜像文件哈希逐项匹配工作树，Compose 等待部署成功。
原管理员页面读到原失败回执，明确勾选重试并提交，返回同一 request_id。
同一普通用户会话持续复查到 usable，覆盖8个字段，带入续研草稿成功。
recovered-browser.json、preparation-recovered-terminal.json、ready-fields.png
与最初失败 browser.json/preparation-terminal.json 分别保留。

真实规范数据抽检，20261113：收盘价42.93元、PE TTM 7.0817倍、PB 0.916倍、
股息率TTM 4.696%、总市值108268797.1608万元（约10826.88亿元）。
20260930报告期，Tushare公告日20261031、生效20261101：
EPS4.57、ROE8.7745%、营收同比5.3425%、净利同比2.3767%。
这组ROE不等同于公告年化ROAE，不能混为同一口径。
[估值单位](https://tushare.pro/document/2?doc_id=32)及
[财务字段定义](https://tushare.pro/document/2?doc_id=79)已按官方文档核对。

另用实际 Store 读取检验 ROA/grossprofit_margin，值为null，返回
field_values_missing 和 usable=false，未转成0。此项是持久化读取证据，
不冒充该两字段的浏览器/原题 Agent 结果；本次浏览器确认的盈利字段为上述四项。
私有 persisted-daily/valuation/financials.json 保存规范数值与来源，未包含密钥。

### 同题研究与耗时

原题SHA256保持20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7，
测试账号models与execution-options对象和此前基准逐对象相等。
补数全部完成后才提交一次原题，隔离数据准备时间与研究运行时间。
会话 conversation_a99b52b9231242c3bdaf60c3131a086f，root
815ee30119a94cf49c21b224e8839d96。结果与分解由本批终态原件续记。
私有原件为 research-candidate-20261109/full-research-20261115。


### 本批完整研究结算与裁定

本次原题运行 2026-11-15T00:21:02.210255Z 至 00:27:12.412557Z，
**370.202302秒**，completed/closed、unknown=0。28次模型请求全部HTTP200，
8次搜索、20次网页读取。各类区间并集：模型263.895秒、搜索93.522秒、
网页6.493秒、本地工具2.553秒。各类别分别统计，不能推成纯网络与纯推理时长。

两次最慢模型请求分别105.393秒/21168输出tokens、43.906秒/9505输出tokens，
仅使用提供方用量元数据，没有输出内部推理内容。原生delegate完成后的3次模型
请求分别4.102、16.115、105.393秒，共125.610秒，显示父级收尾仍有明显开销。
数据准备已经在原题开始前完成，故其时间不混入这370.202秒。未声明稳定提速，
耗时优化目标**FAIL/仍开放**，后续优先针对交接后模型收尾。

5/5公开URL与本轮真实检索结果逐字一致，原生最终文本与持久化文本完全相等。
最终回答正确将42.93元/7.0817倍/.916倍/4.696%展示为42.93/7.08/.92/4.70%，
日期20261113，未把单日估值断言成历史分位。公开年化ROAE13.49%引用三季报，
未冒充本地fina_indicator的8.7745%。未展示总市值换算或EPS值，因此不把这些
值的持久化检查冒充最终文字输出已展示验收。

分红508.43/1438.74=35.34%，普通股股东分母与全年分子口径一致。中期金额、
总额、分母金额用本轮未检索到，派发窗口与登记日分开。观察起点11/15、
三/六个月端点02/15、05/15及窗口跨三个月端点判断正确。
Independent Reviewer 对当前研究数字/口径/日期/引用给限定质量PASS，
运行完成PASS，耗时仍FAIL。不代表所有未来输出或整体体验已通过。

保留运行中的异常：3次byq_agent_run_start分别409 agent_conflict、404
agent_not_found、409 agent_conflict，均后续恢复；一次web_fetch因
application/pdf不受支持失败。它们是后续需定位的运行/能力问题，不改记为
本轮工具零错误。本轮无股票池、策略、回测、订单创建。
latency-detail.json保存具体错误和请求元数据。

真实浏览器打开会话核对关键估值显示及5个引用href，原样匹配，截图和
research-browser.json保存。最终两套环境快照对比生产17容器id/image/
started/health/mounts一致，测试保留11容器及原挂载。临时无持久卷测试PG
已停止，保留测试业务数据、页面与身份。未更新生产、推送、合并或启动远端CI。
本批源代码4207d1d1（含688a8235修复），文档提交另记。


## 2026-11-15 文字型 PDF 阅读能力

用户批准先接入公开文字型 PDF，再在测试环境验证。起点3602fee1，复用原隔离
工作树。源码0bdf909f，已读页判断约束8d0bde68。没有修改DSH源代码或增加
第二套Agent harness，未新增Backend/MCP/数据库接口、宿主命令或凭据输入。

### 实现和边界

通过DSH的Cordis插件与defineTool公开接口注册pdf_read，产品根会话和市场研究
角色可调用。复用锁定DSH镜像的公开URL校验、DNS公网验证、地址固定连接、
代理路由，同源重定向最多5跳，每跳重新验证。只发送固定匿名请求头，不接受
模型传入headers或credentials。下载含流式计数上限15MiB，最多5个1-based页码，
文档最多2000页，每页最多12000字符，空文本和截断均显式返回。

PDF.js6.3.289在可终止Worker内提取指定页文字，禁eval、XFA、WASM、字体渲染与
外部资源获取，Worker V8 old-generation上限256MiB，完整下载/解析预算30秒。
返回原始source_url、final_url、取得时间、总页数和逐页文字，内容标记为不可信
研究证据，不用于确定性行情输入。没有OCR或保证表格结构重建。

网络helpers经@deepseek-ai/dsh-web-fetch-http/src/*导出加载，已在实际Node24
镜像验证。该源码子路径在当前固定DSH完整源码镜像中存在，其npm发布files清单
未包含src，不能声称工具适配任意packed DSH。PDF.js从现有预览依赖图加载；
没有另行安装依赖。后续DSH版本升级仍需验证这两个镜像耦合点。

统一正式入口services/acp_unified/Dockerfile与独立product Dockerfile均复制
两个运行文件，配置identity/authoritative哈希同步。Judgment profile保持原配置，
插件字节在该角色未被注册为可调用能力。

### 定向验证和修正

16项PDF/边界用例通过，包括有效页码、空页、损坏文件、12000字符截断、
参数边界、匿名头、凭据URL/非HTTP拒绝、真实DSH公网地址拒绝、每跳pin、
同源/次数限制、Content-Length与实际流大小限制、预取消、Worker取消、
实际DSH schema编译/注册，以及完整截止期间的真实HTTP慢流关闭。
慢流运行于network-none隔离容器，测试resolver仅pin本地fixture，生产resolver
仍为DSH公网检查；requestPinned、fetch body与关闭均是实际SDK实现。
30秒截止实测30067.99毫秒，server response close=true。
另25项架构/配置/构建合同通过，dev-check local_syntax和diff检查通过。

保留初次失败及修正：长文本测试fixture超出页面宽度，PDF.js只返回49字符，
扩大合法MediaBox后验证截断；实际defineTool要求显式additionalProperties，
补齐后注册成功；独审发现统一Dockerfile最初漏COPY，正式入口已补且加合同断言。
没有将这些失败覆盖成初次通过。

Independent Reviewer关闭构建入口与活动流取消两项阻断，给予测试候选的
Functional/Tests/Clean Break限定PASS。候选无宿主挂载、user10006、read_only下
实际tool.execute读原失败文件成功，文档共3页，选第1/2页，1.728秒。
该候选预检不替代后续Product证据。

### 原文件真实Product与浏览器

原web_fetch失败URL原样使用：
http://dataclouds.cninfo.com.cn/shgonggao/hsomarket/2026/20260327/3ca17483514b40a79b971a0705569b05.PDF#1#1#1

测试仅替换四个ACP镜像，Backend/Gateway/前端/Data Worker不动，Compose
等待健康通过。首轮Product会话conversation_9961b643f7a24f7897f1011e3a3eb09b，
root b595e709e0404a39af9f30cb9a85be54，completed/closed、unknown=0，
17.701115秒，仅pdf_read一次（0.768秒），2次模型请求均200，无工具错误、
搜索、web_fetch或业务MCP操作。链接、原生最终文本和持久化逐字匹配。
Independent Reviewer确认主要数字、页码、当时待股东会审议状态和限制声明正确，
给Product限定PASS，指出一句全篇缺失判断应只限定已读页。

8d0bde68把范围约束同步到根/子研究指引及工具结果说明，测试四ACP更新后
使用完全相同PDF问题复测，原首轮保留。最终会话
conversation_189c04c71cb7446b8b899f7eab4ec5db，root
7af2c1b5c4434223847bfa8f55daca86，completed/closed、unknown=0，
2026-11-15T02:39:52.065149Z至02:40:10.813980Z，18.748831秒。
同样仅一次pdf_read（0.632秒）、2次模型请求均200，无搜索或业务对象创建。
最终明确第3页未读，不对其内容下判断，具体日期缺失只说第1/2页未出现。

实际提取并核对：公告2026-011、2025年度利润分配方案，文件当时尚需股东会
审议；全年/本次每股2.016/1.003元，全年/本次508.43/252.96亿元；
普通股股东净利润分母1438.74亿元，比例35.34%，与原页文字一致。
1,361.84亿元明确为提取盈余公积的另一口径，不替代分红比例分母。
原URL含全部fragment保留，native与persisted完全一致，URL unmatched为空。
真实Chromium中金额、页码和原链接可见，href精确一致，可点击。

本次是文字型PDF专项验收，不能把18.75秒与完整联网个股研究耗时直接比较。
扫描页OCR、复杂表格结构/视觉对齐尚未验收。完整原题370.20秒的性能整改、
run_start恢复与其它体验项继续保留原状态。

最终生产17容器id/image/started/health/mounts逐对象等同基线，测试原有挂载保留。
测试环境及原会话保留；未推送、合并、执行远端CI或生产发布。
私有证据为research-candidate-20261109/pdf-read-20261115，包括镜像构建/部署/
环境快照、candidate-pdf-read.json、首轮Product原件及scope-corrected最终
product/answer/metrics/browser/result.png。正式完整清洁重建与Release Images
资格NOT_RUN，当前证据只覆盖固定已验证基础上的限定测试派生镜像。


## 2026-11-15 完整原题、父会话处理与登记键整改

用户继续授权在原隔离工作树修复、仅更新测试并用同一问题验收；生产不动。
起点1d25abce，源码切片5c5a313d、646a09fb、66e101fa，未推进Product Phase。
原题SHA256仍为20bd2af90641878114ada3b32213cd79630cc9ebd5b4e70ac65961adde317be7。
每轮提交前核对同一A测试账号的模型与执行设置完整对象等同原基准；
没有替换模型、自动准备数据或创建股票池、策略、回测和订单。

### 旧登记错误的具体原因

full-research-20261115的root 815ee30119a94cf49c21b224e8839d96，子研究三次
run_start结果为409、receipt_only 404、409。原生调用的同一登记键
mr-cmb-600036-20261115-public-research-v1已于2026-11-14T20:37:34.606475Z
用于同账号旧root 71e139c44148401d94817b062789de26。测试库范围对照证实
owner相同而session和trace不同，既有AgentRun为agent_run_af61eeceae284bd497d5e6c6b7150d6f。

Backend start_run按owner/key取得旧登记，再比较包含session等范围的request_hash，
冲突必须409；registration_receipt只返回当前精确workspace/actor/session/trace/
generation的记录，所以查询旧键为404。之前文中“均后续恢复”只可理解为
研究根运行最终完成，不证明这些失败的子登记本身后来成功。
本次补强每个新turn/native agent的fresh attempt suffix；同次重试/未知仍保留
原键核对，不修改Backend校验、不重开旧运行，也未改写两条撤权历史未决记录。
白名单原生调用及SQL范围对照保存在historical-registration-diagnosis.json。

### 最小实现

- 产品帮助目录补充research-data-preparation，普通用户只获EXPLAIN/NAVIGATE，
  agent_tools仅byq_product_help_query，不授予准备数据执行权限。短功能词查询，
  不猜capability_id，不把本地skill参考路径当成MCP resource URI。
- 最新期财务响应只证明已返回的期间与字段；未读取历史不等于本地不存在。
  不从NULL推原因，不猜ROE/ROAE公式或年化关系。简短摘要省略口径未核实、
  用户未询问的provider ROE，不增加无比较依据的“低估”“缓冲厚”等评价。
- 父会话用子研究已取到的原文、表行和精确URL核对。具体冲突/缺段仍可定向
  复查；完整交接不要求重读整份文件。分红缺口不靠猜金额/币种/将来日期补齐，
  同义词不是新来源，保留最新报告及截止前后续公告核实要求。
- 公开只给最终研究摘要，不播报登记/授权/审计/委派步骤。日程限本轮已核实
  范围；未来最新进展不承诺沿用旧cutoff，明确历史研究仍尊重用户指定日期。
  后一点为规则与本轮措辞证据，不声称已完成真实跨日续研验收。

### 同题逐轮结果，失败不覆盖

| 轮次 | 原生root耗时 | 模型请求 | 验收结果 |
|---|---:|---:|---|
| 旧完整基准815ee… | 370.202302秒 | 28 | 保留3登记错误、1次PDF不支持；本次未重判旧结论 |
| PDF完整首轮e42596516bb1415095595d0728770730 | 228.996769秒 | 30 | LIMITED FAIL：误称本地无逐季财务，帮助误读file资源 |
| 5c5a313d，da145130273747b5b4531841e71175e7 | 295.112519秒 | 29 | FAIL：板块低估/ROE年化/NULL原因/因果/仅有日程无依据，且公开内部播报 |
| 646a09fb，ccedee82d0ae48a6975e7421d2e64b8c | 211.780569秒 | 18 | FAIL：仍猜ROE未年化、资本厚、承诺旧截止日继续最新查询 |
| 66e101fa，8fed0e864eb740329662b825028c7b84 | 266.295190秒 | 27 | 原题质量限定PASS，真实浏览器PASS；不宣称稳定SLA |

最终会话conversation_3546ba911c3749eebcdb9f593f7133c5，root completed/closed、
terminal_unknown_claim_count=0，27次模型请求均200，工具错误0，登记2次均成功。
运行时间2026-11-15T03:53:01.804732Z至03:57:28.099922Z；
提交到采集观察约269.17秒，与上述root耗时不是同一口径。

最终13次搜索的时间并集118.251秒，模型137.476秒，web_fetch 4.644秒，
pdf_read 0.615秒，本地工具2.531秒；分类可有重叠，不作简单相加的排他归因。
父会话交接后的4次模型共24.993秒，墙钟26.754秒，包含补记已读操作的审计、
一次HTML读取与帮助查询。旧基准对应父模型125.610秒，减少80.10%。
总耗时比旧370.20秒减少28.07%，但中间轮次211.78与228.99秒更快。
搜索仍有明显波动，不能用本轮或最快轮次证明稳定性能，也不能声称搜索整改已全部闭环。

独立Reviewer终审确认：本轮未再猜本地ROE公式或评价资本厚度，没有无证同业排序、
无证因果或穷尽日程；2025年度2.016元/股、508.43亿元、普通股股东利润分母
1438.74亿元和35.34%，实施日期及2026年中期比例型计划/金额未核实/支付窗口
保持区分。观察端点2027-02-15与2027-05-15，区间跨越三个月端点的不确定性保留。
实际PDF读取第1–3页，引用含原#1#1#1；7/7最终URL与实际取得结果原样匹配，
最终原生公开文本与持久化文本逐字一致，无需术语投影后才能相等。
上述为原题、这些来源和当前数据的限定验收，不是任意研究问题准确性保证。

### 首次“空答”采集判断修正

本轮首次终态快照messages仅含用户，旧采集只拼messages，得到0字符。
该同一快照的agent.output.delta已包含完整3190字终答，原生也有相同公开文本。
未调用新模型、未补写答案；重读同会话后持久化assistant为3190字。
Gateway get_product_session保留尚未持久化的answer delta，AgentView.replayMessages
合并messages与未入库delta并按workflow_sequence去重，符合当前公开回放路径。
因此不能把这次采集时序误判为产品永久丢失答案。
原始product.json、answer.txt空快照、initial-snapshot-metrics.json保留，
另存product-reread.json和final-answer.txt，最终比较使用最后一条持久化终答。
此前一轮把所有公开进度拼接对比单条原生终答的误差亦已单独纠正。

### 检查、浏览器与部署范围

5c5a313d切片12项authoritative/profile/帮助权限架构测试及17项现有ACP拓扑/
构建合同通过；后两次profile修改各重新通过12项相关测试、dev-check
local_syntax与diff检查。实际MCP挂载新catalog执行既有product-help-test通过，
新feature真实query返回USER/导航且不含EXECUTE。独立规则审查通过后才更新测试。
这些是定向本地证据；远端CI、正式清洁重建、Release Images均NOT_RUN。

最终真实Chromium以测试A账号打开原会话，数值与7个原始href可见，
内部登记播报和英文注册说明均不再显示，截图及browser.json保存。
前轮内部播报实际可见的失败截图亦保留。测试身份、用户原页面和数据未清理。

测试仅更新4个ACP及2个MCP，Backend/Gateway/前端/Data Worker不变；
每次逐文件核对上版基础与当前源哈希，Compose等待健康，保留旧镜像/配置回退。
最终ACP sha256:3942db5a0afd577bc6e9a1e5ad95199f66359db8d1816d145ace8fe10f9e77d2，
MCP sha256:2b39eafd4c2ec3c30d18e43066b3b2f8f3306fd56d4a21413bdb11a97bccff76。
这是固定已验基础上的限定测试派生镜像，不替代正式完整构建资格。

全批更新后两套库存对照：生产17容器id/image/started/health/mounts逐对象一致；
测试11容器、原挂载全部保留，仅目标6个服务容器发生替换，定义健康检查者均健康。
私有证据根目录research-candidate-20261109/pdf-full-research-20261115，
首轮在根目录，其后corrected、claim-corrected、basis-corrected分别保存独立会话。
没有推送、合并、修改生产或发起正式发布。待续项包括稳定搜索耗时、跨日续研、
扫描PDF/OCR/复杂表格以及正式候选CI；既有其他体验项不因本轮原题通过而自动关闭。
