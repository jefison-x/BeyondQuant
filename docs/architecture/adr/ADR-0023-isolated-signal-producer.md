# ADR-0023：Isolated Strategy Signal Producer

- Status: Accepted
- Date: 2026-08-22
- Accepted: 2026-08-22
- Decision scope: Phase 40 StrategyVersion 到 signal snapshot production
- Related: ADR-0007、ADR-0008、ADR-0013、ADR-0016、ADR-0017

## 背景

ADR-0017 将 immutable `signal_snapshot` 规定为 native Backtest engine 唯一 Strategy
signal input，但有意不决定如何执行 StrategyVersion Python source。因此只有在 keyless
fixture/import 已创建 matching snapshot 时，Product flow 才能 submit Backtest。D-0002
要求 BYQ-owned producer，使新编写 Strategy 可以端到端进入 Backtest。

Community 在 Backtest service process 中使用 Python `exec()` 和 restricted builtins/
import dictionary 执行 `CustomStrategy`。其中有用证据是 synchronous
`generate_signals(data, parameters)` Contract 和稳定 `-1/0/1` signal semantics。Static
AST check/restricted builtins 不是 security boundary；Community process、Pandas runtime、
provider access、ORM 和 Backtest coupling 均不能复制。

## 决策

1. BYQ 引入由 Quant Domain Plane 持有的 dedicated durable signal-production job。Product
   request 引用一个 validated、owner-matching StrategyVersion、immutable Stock Pool
   snapshot、有界 date range、finite JSON parameter、execution profile 和 idempotency
   key。Backend 在 job runnable 前 resolve/freeze canonical PostgreSQL daily bar。
   Producer 不下载数据，也不调用 Tushare。
2. Production 有两个 privilege tier：
   - trusted `signal-worker` coordinator 可以 claim PostgreSQL job、读取 frozen input 并
     persistence normalized result，但绝不执行 Strategy source；
   - dedicated `signal-sandbox` runner 执行 source。它只接收有界 secret-free input
     document，只暴露固定 BYQ Strategy protocol；没有 BYQ database、Provider、model、
     DSH、MCP、repository 或 Docker credential，也没有 application-source mount。
3. Sandbox 不是 generic Agent/code Harness。每次 invocation 在 fresh child process 中以
   non-root user 运行，使用 read-only filesystem、empty writable temp directory、dropped
   Linux capability、`no-new-privileges`、有界 process count/memory/CPU/wall time、
   sanitized environment 和无 external network route。Coordinator 将 timeout、crash、
   invalid output、resource exhaustion 记录为稳定 failed outcome。
4. Phase 40 execution profile 是 `byq-signal-python-v1`，只支持一个 synchronous
   `CustomStrategy.generate_signals(data, parameters)` entry point，输入为 frozen Pandas-
   compatible canonical bar。Import 只允许 Sandbox 内 deterministic data/math helper。
   Filesystem、subprocess、socket、reflection/dunder、dynamic compilation、clock、entropy
   和 randomness access 被拒绝。`generate_target_weights` 和 arbitrary ML training 不在
   profile 中；validation 可描述，但 producer 以 `execution_profile_unsupported` fail
   closed。
5. Output 是 canonical symbol 到 date-indexed series 的 mapping，value 只能为 `-1`、`0`
   或 `1`。Coordinator 使用 job request 中明确 positive、lot-aligned `order_quantity`，
   将 non-zero row 转为稳定 `sell`/`buy` signal row。Unknown symbol/date、duplicate row、
   non-finite value 或其他 output shape 均拒绝；empty signal 有效且保持明确。
6. Reproducibility 是 Contract：input bar、universe、parameter、execution profile/version、
   interpreter/dependency lock identity 和 Strategy source fingerprint 均 content-addressed；
   input/output ordering canonical，固定 deterministic environment/thread setting。重放
   identical request 得到相同 validated `signal_snapshot` content identity。
7. Backend 在 create/reuse immutable `signal_snapshot` Artifact 前，使用 ADR-0017 snapshot
   normalizer 重新验证 Sandbox output。Artifact ownership、task lineage、Approval 和后续
   Backtest authorization 仍由 ADR-0007/0008/0017 负责。Producer success 本身不 approve
   或运行 Backtest。
8. Product API 暴露 owner-scoped job create/status 和 composed produce-and-submit flow。
   MCP 可暴露有界 job orchestration，但 DSH 不获得 source-execution authority、raw bar、
   credential 或 storage access。Browser 只使用 Product API，绝不直接向 Sandbox submit
   executable code。

## 后果

- Product 可以完成 StrategyVersion → frozen signal snapshot → native Backtest，而不把
  Strategy execution 移入 DSH 或 HTTP request。
- Sandbox image/protocol 成为 security-sensitive exact dependency surface，需要 isolation
  和 escape-regression test。
- Phase 40 不承诺兼容所有 Community Python/ML Strategy；unsupported profile 明确失败，
  不静默放宽 privilege。
- Coordinator/Sandbox split 增加一个 internal service boundary，但使 PostgreSQL 和
  service credential 不进入 untrusted execution tier。

## 拒绝的替代方案

- 在 Backend/Backtest worker 中使用 Community-style `exec()`：static filtering 不是
  isolation，会暴露 process credential 和 storage connectivity。
- Product DSH execution：违反 Agent-to-Domain/source-protection boundary，并将 DSH 变成
  quantitative runtime。
- Browser signal generation/raw CSV upload：失去 trusted provenance、ownership 和
  reproducibility。
- 给 Sandbox PostgreSQL/Tushare access：允许 Strategy code 绕过 frozen input 并
  exfiltrate credential。
- 第二套 generic code/Agent Harness：被禁止；Runner 只实现 closed
  `byq-signal-python-v1` protocol。

## Acceptance review

维护者于 2026-08-22 确认 produced signal 是 historical、reproducible buy/sell/hold intent
snapshot，而不是 Agent event 或 live broker order 后，接受 recommended boundary。
Acceptance 要求 owner isolation、input freezing、idempotency、determinism、unsupported
profile、time/resource limit、secret absence、network/storage denial、output normalization
和完整 Product API Strategy-to-Backtest journey test。

## 回滚

禁用新 producer job create，并移除 coordinator/Sandbox service。Existing immutable
`signal_snapshot` Artifact 在 ADR-0017 下保持 readable/valid；Product 恢复明确 keyless
import path。
