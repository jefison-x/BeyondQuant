# ADR-0003：Gateway 与 DSH Runtime Integration

- Status: Accepted
- Date: 2026-08-15
- Decision scope: Phase 6 Product Plane / Agent Plane runtime seam
- Supersedes: Phase 5 的 `NO DECISION YET` Gateway integration placeholder

## 2026-08-25 qualified-pin 修订

正式 DSH Upgrade Lane 将 Product Runtime 验证到 Python
`deepseek-harness-sdk==0.1.1rc1` 与
`deepseek-harness-runtime-bin==0.1.1rc1`；明确 npm runtime closure 中的 54 个 DSH
package 全部固定为 `0.1.1-rc.1`，另有七个 supporting `@deepseek-ai/*` package 固定到
当前 stable version。本修订只改变 dependency version。已选择的 Option B topology、
public JSON-RPC carrier、custom BYQ Cordis composition、process ownership、MCP-only
domain boundary、WorkflowTrace normalization 和 Product capability restriction 均不变。
Python/npm rc.6 保持 rollback baseline。

GitHub/npm `0.1.1-rc.2` 未通过验证，因为不存在对应 official Python SDK/runtime-bin。
只有全部 DSH package 都是准确 direct pin 时，rc.1 npm closure 才完整；普通的部分
top-level set 会通过 upstream range 拉取 rc.2，并导致 peer resolution 失败。Compatibility
matrix 和 artifact evidence 位于
`docs/architecture/research/dsh-compatibility-matrix.md`。

## 2026-08-28 Phase 63 plugin-governance 修订

ADR-0038 在不改变 Python/npm release baseline 的情况下，将 explicit manifest 扩展为
71 个 exact `@deepseek-ai/dsh-* @0.1.1-rc.1` package，以便 qualification framework 对
official samples 做真实 closure/init 验证。只有 Registry 中 QUALIFIED + Product enabled
+ Agent assigned 的 package 才进入 generated Cordis composition；package presence 不等于
enabled。Runtime online install、extensions、自修改和原有 MCP/security/ownership 边界均
不变。

## 背景

Phase 5 有意停在 container-local DSH Web bootstrap。该 Web surface 不是 Product API：
它继续 bind 到 DSH loopback interface，不发布 host port，也不得通过 proxy 或 workaround
暴露。

Phase 6 需要以下 programmatic path：

```text
BYQ Gateway
  ↓ internal BYQ API
DSH Runtime Adapter
  ↓ official SDK over stdio JSON-RPC
explicit exact-pinned DSH runtime composition
  ↓ official MCP client
BeyondQuant MCP
```

该 seam 必须保持现有边界：

- Product DSH 没有 coding、source filesystem、Git mutation 或 Engineering Plane
  capability。
- Agent-to-Domain call 只使用 BeyondQuant MCP。
- Gateway 不 import DSH SDK，也不解析 raw DSH notification type。
- DSH session persistence 保持为 Agent Plane state；Gateway 只保留 BYQ session 与
  trace identity。
- DSH 是准确固定的 external dependency，不被 fork，也不为 BYQ rebuild。

正式检查了 official rc.6 artifact，而不是推断。npm 使用 `0.1.0-rc.6`；Python/PyPI
使用 `0.1.0rc6`。Python SDK 持有 subprocess 和 stdio JSON-RPC client，但 rc.6 没有
prompt cancel 或 per-session close；`session/prompt` 返回 enqueue receipt，而非 completed
result。这些限制使 process ownership 成为架构决策的一部分。

## 评估的方案

### Option A：Python SDK 加 bundled runtime

不用于 Product runtime。Official `deepseek-harness-runtime-bin==0.1.0rc6` closure 包含
coding-capable bash 和 local filesystem capability，且不包含
`@deepseek-ai/dsh-mcp-client`。Custom composition 不能把缺失 package 加入 bundled
closure。为增加 MCP 而 rebuild 或 fork runtime 会违反仓库边界。

### Option B：Python SDK 加 explicit npm DSH runtime

选择此方案。Python SDK 是 application-facing client。它通过 `launch_args_override`
启动准确固定的 npm rc.6 runtime，使用 official public `dsh-jsonrpc-agent` carrier
（`lib/bin.js`）和 BYQ-controlled Cordis composition，composition 包含：

- `@deepseek-ai/dsh-sdk-jsonrpc-server`；
- non-coding `@deepseek-ai/dsh-agent-spine-demo` configuration；
- DSH JSONL persistence/checkpoint policy；
- 连接 BeyondQuant MCP 的 `@deepseek-ai/dsh-mcp-client`。

在已安装 rc.6 artifact、BYQ composition 和健康 MCP 上，public `lib/bin.js` 与 exported
`packaged-bin.js` 均已实际运行，并通过 keyless initialize/idle/close。选择 public
`dsh-jsonrpc-agent`，因为它是 package 声明的 public bin，且无需 packaged-runtime base
override 即可加载 BYQ composition。这是由 compatibility smoke 保护的准确 rc.6 决策，
不承诺未来 DSH version 的稳定性。

### Option C：TypeScript SDK 加 explicit npm DSH runtime

未选择。`@deepseek-ai/dsh-sdk-client@0.1.0-rc.6` 使用相同 stdio JSON-RPC protocol，
具有相同 cancellation 和 process limitation。Python Gateway 将需要 Node adapter/sidecar
或 Node Gateway，增加 language/process boundary，却不能改善本 Phase 的 lifecycle、
event 或 observability behavior。

## 决策

BYQ 采用 Option B，并以专用 Python Runtime Adapter 作为唯一面向 Gateway 的 DSH
runtime owner。Adapter 使用 FastAPI 提供 internal HTTP/SSE prototype API，并使用
`deepseek-harness-sdk==0.1.1rc1`，为每个 active BYQ session 启动一个明确的
`@deepseek-ai/dsh-sdk-jsonrpc-demo@0.1.1-rc.1` public `dsh-jsonrpc-agent` process。

Adapter 是 Agent Plane runtime boundary；它不是 Engineering DSH，不是第二套通用
Agent Harness，也不是 public chat API。

## Runtime topology

```text
Gateway (Python)
  ├─ internal HTTP: health/session lifecycle
  └─ internal SSE: BYQ WorkflowTraceEvent only
       ↓
Runtime Adapter (Python/FastAPI)
  ├─ one DeepSeekHarness per active BYQ session
  ├─ official stdio JSON-RPC client
  └─ one owned node dsh-jsonrpc-agent/lib/bin.js process per session
       ↓
byq-product-sdk.cordis.yml
  ├─ @deepseek-ai/dsh-sdk-jsonrpc-server
  ├─ @deepseek-ai/dsh-agent-spine-demo (coding flags disabled)
  ├─ DSH JSONL persistence/checkpoint policy
  └─ @deepseek-ai/dsh-mcp-client
       ↓
BeyondQuant MCP (`/mcp/v1`)
```

Base Compose 包含 Gateway、Runtime Adapter、MCP 和 Backend。旧 Phase 5 DSH Web service
只通过带 `dsh-web` diagnostic profile 的 `compose.dsh-web.yml` 提供，不在 Product
request path 中。

## Process ownership

保留的 lifecycle model 是每个 active BYQ session 一个 DSH runtime process。Adapter
通过 official SDK 持有 startup、stdin/stdout/stderr pipe、shutdown、termination 和
cleanup；Gateway web worker 不持有 subprocess。

曾评估多个 `sessionId` 共用单一 runtime。它能降低 cold-start 和 idle overhead，但已
验证 runtime 无法在不影响其他 session 的情况下可靠 hard-cancel 单个 session，且 queued
work 共用 whole-agent result interval。因此，在 DSH 提供可靠 prompt cancellation 和
per-session close 前不采用。

2026-08-15 prototype baseline 测得 fresh Gateway-to-Adapter initialize 为
`0.355827s`，hard cancel 为 `0.039565s`。Initialize 后 idle 时，`docker stats` 报告
Runtime Adapter container `101.3MiB`，`docker top` 报告 owned Node child `121112KiB`
RSS。这些只是 baseline measurement，不是 capacity guarantee；Phase 7 必须在目标
CI/production limit 下复测。

## Session lifecycle

Adapter state vocabulary：

```text
starting → ready → idle → running → idle
                         ├→ cancelling → idle
                         ├→ failed
                         └→ interrupted → closed
```

实现还允许从 `ready`、`idle`、`failed` 或 `interrupted` 正常 release 到 `closed`。

1. Create 验证 BYQ `session_id` 和 `trace_id`，创建 DSH-owned session root，启动明确
   runtime 并完成 JSON-RPC `initialize`；state 变为 `ready`。
2. `submit_prompt` 只在 `ready` 或 `idle` 接受。它在 session lock 下 claim 一个
   `active_run`，原子地将 state 改为 `running`，然后才启动一个 `Session.run()` worker。
   第二个 prompt 收到 409，不能创建 concurrent active run。
3. Normal completion 只清除该 active run，并将 state 改为 `idle`；非 cancel failure 将
   state 改为 `failed`。
4. `release` 只在没有 active run 时允许。它将 state 改为 `closed`，close/reap owned
   Harness，发出 close trace，发送 SSE termination，并移除 live record。Release 后用
   相同 BYQ session 重建时，在未来 resume policy 下创建新 owned runtime。
5. Live record 存在时 duplicate create 明确返回 409 conflict。

## Streaming

Internal prototype 选择 Runtime Adapter 到 Gateway 的 SSE。SSE 映射到 Adapter ordered
notification queue，足以承载 one-way internal event stream。如果 backpressure 或
bidirectional control 有需要，internal streaming HTTP 仍是未来选项。

SSE 只承载 serialized BYQ `WorkflowTraceEvent` envelope。Gateway code 不解析 DSH
notification method、event type 或 payload schema。

## Event normalization 与 ordering

`packages/contracts/workflow_trace.py` 中 framework-neutral minimum envelope 为：

```text
trace_id, session_id, sequence, timestamp, kind, source, payload
```

Adapter 将 `session.status` 和选定 `session.event` value 转换为 BYQ-owned event。
Unknown DSH event type 变为有界 `session.progress` event。Raw DSH payload 不越过
Gateway boundary。

每个 RuntimeSession 有一个 ordering lock。Sequence allocation 和 queue publication 均
在该 lock 内完成，因此即使 notification、cancel、result 和 failure path 并发，sequence
仍唯一、严格递增，并按相同顺序发布。

## Cancellation

### Soft cancel

只对当前 active run 有效。它将 session transition 到 `cancelling`，发出 BYQ
cancellation event，并因已验证 runtime 无 prompt-cancel operation 而等待 DSH work
settle。最终 result 被丢弃，state 回到 `idle`。Cancel request 只作用于 active run，不能
永久污染后续 prompt。

### Hard cancel

只对当前 active run 有效。它将 session transition 到 `interrupted`，detach 该 run，发出
BYQ cancellation event，并对 Adapter-owned DSH runtime 调用 official SDK `close()`。
SDK 执行已文档化的 shutdown/terminate/kill ladder。Adapter 不 patch protocol，也不伪造
successful cancellation response。

Hard cancel 后 prompt 收到 409，closed Harness 永不复用。Durable log 可能含有
interrupted/incomplete turn。未来 resume 必须依据明确 policy 创建新 owned runtime；
Phase 7 持有完整 Product resume flow。

## Failure isolation

每个 active session 一个 owned runtime，将 runtime crash 限制到该 session，并使 cleanup
确定。Adapter process failure 仍可能影响分配给该 instance 的所有 session；horizontal
scale 时 deployment 必须 restart Adapter，并保留 ownership/affinity。

## MCP composition

选择的 SDK composition 是
`plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml`。它是唯一 Product capability
source，包含 SDK JSON-RPC server 和使用 `failOnStartupError: true` 的 BYQ MCP client。
Coding tool 为 `NONE`：未安装或启用 bash、terminal、write、edit、str-replace、Codex、
Git mutation 和 source filesystem write。DSH 只通过 BeyondQuant MCP 访问 business
data，绝不直接访问 PostgreSQL 或 Redis。

## Model configuration

Adapter 通过 SDK initialize configuration 传入 official `deepseek-official` provider route
和 `deepseek-v4-flash` model。Phase 6 不 mount/invoke model provider、不发真实 model
request，也不要求 `DEEPSEEK_API_KEY`。Phase 7 必须验证真实 Product Agent model
routing 和 credential；不引入 fake production model abstraction。

## Persistence

Named Compose volume `byq_dsh_sessions` 只 mount 到
`/var/lib/byq/dsh-sessions`。Runtime user 可以写 Agent Plane volume 和必要 temp storage；
application、config 和 runtime installation path 保持 root-owned/read-only。Adapter 解析
每个 session path，并证明它保持在 `DSH_SESSION_ROOT` 下。

Gateway 只保存/传输 BYQ session identity 和 BYQ trace identity。DSH durable session log
属于 Agent Plane runtime owner；未来 BYQ business Artifact 保持为 Backend/Domain Plane
state。

## Security boundary 与 internal trust

Prototype endpoint 信任 private Compose network，并使用 MCP token 进行 Adapter-to-MCP
call；它们不是 external user authentication。Product DSH 无 source mount、Docker
socket、host network、host-published DSH Web port、engineering credential 或宽泛 writable
application path。Production cross-host deployment 在将 Adapter 暴露到 private network
之外前，必须增加 service identity 和 authorization，优先使用 mTLS 或等效 authenticated
internal mesh。

## Observability

Readiness 报告准确 SDK/runtime-bin version、explicit carrier path、composition path、
persistence owner 和 process ownership。SDK stdout 保留给 JSON-RPC frame；diagnostic
保留在 stderr。Adapter log 和 normalized WorkflowTrace event 是面向 Gateway 的
observability surface。Raw DSH payload 和 secret 不记录到 log。

## Horizontal scaling

Adapter 可独立于 Gateway deployment。Replicated deployment 必须增加 ownership registry
或 affinity rule，防止第一 Adapter 仍持有 DSH process 时第二 Adapter resume 同一
session。在 horizontal session migration 前，必须替换 named DSH volume，或按 Adapter
provision 并明确 shared-storage semantics。

## DSH upgrade compatibility

已验证 Product Runtime baseline 为准确 rc.1：

- 54 个 DSH npm runtime package 全部为 `0.1.1-rc.1`，另加七个准确固定的 supporting
  `@deepseek-ai/*` package；
- Python `deepseek-harness-sdk==0.1.1rc1`；
- `deepseek-harness-runtime-bin==0.1.1rc1`。

任何 DSH upgrade 都是独立 compatibility decision，需要新的 npm/PyPI metadata、
artifact hash/closure inspection、carrier validation、composition/initialization/MCP test、
notification Contract review、cancellation review 和 ADR update。较新 npm release 不会
自动改变该 baseline。

## 运行时会话资源维护说明（2026-08-29）

“每个 active BYQ session 一个 DSH process”中的 active 指正在执行、被 Product SSE
消费，或仍处于短暂重连宽限期的运行时会话，不等同于 durable conversation catalog 中
所有 active lifecycle conversation。浏览器离开且无消费者后，Gateway 可以在有界宽限期
后经 Runtime Adapter release 该临时进程；再次打开会话时，仍按本 ADR 的 create seam，
以 BYQ WorkflowTrace 的最后 sequence 恢复运行时投影。Durable conversation、消息和
WorkflowTrace 不因此删除或归档。

Runtime Adapter 的长连接通知等待不得占用共享 web executor。每个 owned session 的
blocking notification queue 可通过 Adapter-owned 有界桥接线程转入 async SSE queue，
仍由 Adapter 独占 raw DSH notification normalization，且不改变 Browser Contract。

## 已验证 runtime 的已知限制

- 无 prompt cancel；
- 无 per-session close；
- 无 protocol version negotiation；
- prompt 只返回 MessageId enqueue receipt；
- whole-agent idle interval 持有 high-level run result；
- request timeout 不停止已经运行的 work；
- stdout 只用于 JSON-RPC protocol；
- 面向未来 Approval flow 的 server/client request capability 不完整。

### 2026-09-01 maintenance clarification：有界运行看门狗

Adapter 的 dedicated-process ownership 也承担有界 lifecycle safety：每个 prompt、观察到的
`byq_delegate_*` 子 Agent 调用以及无公开 WorkflowTrace 进度区间都有 monotonic wall-clock
上限。超限时 Adapter 原子 detach active run、发出 BYQ-owned 安全失败码并只关闭该 session
持有的 DSH process；late result 丢弃，既有 failed-session resume 使用新的 private generation。
这不是第二套 Agent loop，不解析 child hidden state，也不改变 DSH 通用 subagent ownership。

分页类 Agent-to-Domain read 的次数预算由 BeyondQuant MCP Contract 强制，DSH persona 只负责
选择必要页，并在剩余次数归零或收到非错误的有界结束信号后立即使用已有证据作答。预算耗尽
不访问 Backend，也不作为会令子 Agent 失败的工具异常。具体默认值、稳定控制码与恢复语义见
`docs/contracts/product-agent-run-guards.md`。

这些是当前限制，不是可用 future feature。Adapter hard-cancel process close 是 BYQ
ownership policy，并不表示已验证 DSH release 支持 prompt cancellation。

### 2026-09-03 maintenance correction：内部活性与公共进度分离

生产会话证明，固定 DSH `0.1.1-rc.1` 在长推理和子 Agent 工作期间持续产生合法的
turn/step、reasoning chunk 与 tool lifecycle event，但 ADR-0033 要求其中多数不得公开。
若无进度看门狗只观察公共 WorkflowTrace，Adapter 会把仍在运行的 DSH 误判为静默并关闭。

因此 `no_progress_timeout_seconds` 观察 Adapter-owned 的私有运行活性，而不是要求产生公共
进度。只有限定的合法 DSH execution event 可以刷新该 monotonic clock；raw payload、hidden
reasoning、子会话 identity 与工具参数/结果仍被 normalization 丢弃，不越过 Gateway。活动中的
delegated child 使用其专用 180 秒边界，不能被更短的 root quiet interval 抢先误标；整个 prompt
仍受有限的绝对上限约束。此修正不新增 heartbeat、不解析推理语义、不实现第二 Agent loop，也
不改变 DSH pin、MCP、WorkflowTrace 或 Browser Contract。

### 2026-09-03 maintenance correction：复杂任务绝对上限与失败可见性

真实机器学习编排在持续产生合法私有活性、完成多轮工具调用后，可能超过原 300 秒绝对
上限。默认 whole-run ceiling 调整为 900 秒；120 秒无活动上限与 180 秒 delegated-child
上限保持不变，因此真实停滞仍会及时终止。该调整只改变 Adapter-owned lifecycle policy，
不改变 DSH、MCP 或 WorkflowTrace schema。

Runtime 自动重建产生的 `session.ready`/`session.resumed` 只证明新 private generation 可用，
不证明失败的用户回合已经重试。Frontend 必须保留最后一次 `session.failed`，直到后续
`session.started` 证明新回合实际开始，避免将真实超时显示为静默空闲。

## Base Web DSH 决策

旧 Phase 5 Web DSH 从 base production Compose 移除，并保留在
`compose.dsh-web.yml` 的明确 `dsh-web` diagnostic profile 中。它没有 host port、source
mount、socket、proxy 或 host networking。Product request 只使用 Gateway → Runtime
Adapter → owned JSON-RPC DSH → MCP。Diagnostic profile 仅用于 bootstrap/configuration
inspection，不是第二条 Product request path。

## 拒绝的替代方案

- 将 DSH Web 用作 Gateway API：违反 Web boundary，并要求禁止的 proxy/network
  workaround。
- 在 base production Compose 放置 DSH Web：创建第二条非 request DSH path，并模糊已
  选择的 JSON-RPC ownership boundary。
- 由 Gateway 持有 DSH subprocess：将 web-worker lifecycle 与 Agent process lifecycle
  耦合，并削弱 failure isolation。
- Option A bundled zero-config runtime：closure 含 coding capability，且缺少 MCP client。
- Option C TypeScript SDK：对当前 Python Gateway 增加不必要 language/process seam。
- Fork 或 rebuild DSH：仓库架构规则禁止。
- Gateway 解析 raw DSH notification：使 Product Contract 耦合 DSH。

## 回滚

Dependency rollback baseline 是 Python `0.1.0rc6` 与 npm `0.1.0-rc.6`，使用仓库历史
中的 prior runtime manifest 和 lockfile。停止并 release owned Runtime Adapter session，
deployment prior image/revision，并让 Adapter 使用相同 Agent Plane JSONL session volume
restart。无需 BYQ business-data migration。若无法确定 interrupted rc.1 session 的
runtime-level resume，保留 durable log 作为 audit evidence，并启动新 owned runtime
session，不转换或 patch DSH persistence。Rollback 必须保留 MCP-only domain path、
no-proxy/no-host-network Web boundary 和全部 Product capability restriction。

## 退出标准

只有满足以下条件，Phase 6 才完成：

- 记录 official rc.6 Python/npm metadata 和 bundled closure evidence；
- Option A/B/C evidence 和本 ADR 完成 review；
- lifecycle、duplicate-create、hard/soft cancellation、release、identifier、ordering、
  filesystem 和 persistence test 通过；
- keyless JSON-RPC initialize、MCP startup、normalization、Gateway Contract 和 process
  cleanup smoke 通过；
- base Compose 与 diagnostic Web profile check 通过；
- CI 运行 Phase 5 与 Phase 6 test，并保持 Human Merge Gate。

如果 compatibility evidence 不足或新 DSH behavior 打破该 seam，必须将本 ADR 改为
Proposed，Phase 6 必须停在已文档化 architecture blocker。
