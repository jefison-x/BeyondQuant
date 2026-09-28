# Phase 10 — pinned DSH transport contract

The Product runtime is pinned to the paired official Python
`deepseek-harness-sdk==0.1.5rc1` and
`deepseek-harness-runtime-bin==0.1.5rc1` artifacts. The release wrapper
`Dsh015Compatibility` inherits the public Python SDK surface used by the
qualified 0.1.2 boundary. Phase 10 does not silently upgrade this pin.

| BYQ translation | Public DSH surface actually used | Boundary |
|---|---|---|
| Start root | `DeepSeekHarnessConfig`, `DeepSeekHarness`, `bundled_runtime_path()`, `harness.start()` | Adapter owns only the transport/process handle for a live root. |
| Send input | `harness.start_session(native_id)` then `Session.run(content, on_notification=...)` | DSH runs the Agent loop and private context inside the owned process. BYQ supplies bounded completed public Product history as ordinary input and tracks only live call/authority state, classified in the [field audit](phase10-adapter-ownership.md). |
| Hard cancel | `harness.close()` | Ends the dedicated process. Old interrupted run cannot publish a late success. |
| Live status/events | Public `Notification` callback on a running call | Adapter normalizes a bounded event projection; there is no independent DSH status-query or attach API in this qualified Python contract. |
| Delegated research | Product composition tools and `subagent.started`/`subagent.finished` notifications | DSH owns delegation. Adapter's in-memory child inactivity guard only bounds a stuck dedicated process. |

The qualified public Python surface has no separately used `cancel`, root
`attach/resume/status`, or child `rebind` method. Soft cancel is an Adapter
request to suppress the in-flight result; hard cancel closes the dedicated
harness. Native DSH session persistence and continuable-subagent capabilities
are not adopted through this SDK boundary. Consequently an Adapter or DSH
process loss is reported as interrupted. A user starts a new Agent session and
uses BYQ `job_id`/Artifact IDs to find durable business work. No old prompt or
unknown external action is replayed automatically.

For healthy multi-turn Product interaction, each admitted root has a fresh DSH
process and a distinct exact BYQ domain-call authority. BYQ may pass bounded,
persisted **completed public Product messages** as ordinary input to that
root. This is not DSH-private session/context restoration. The former
failed-turn `conversation_recovery` envelope, which inferred unanswered work
from trace events, is outside this boundary and was removed in Phase 10.
Completion is checked against the scoped, closed Backend business-root record
and its exact terminal receipt. Trace events correlate persisted Product
answers with roots; they do not decide root status.

This phase removes the old Adapter behavior that built a *new* DSH process
under an interrupted or failed BYQ session ID. The live READY original-harness
reattach path remains for a Gateway reconnect during the same Adapter boot.
An ordinary terminal model/runtime failure is reported as failed; it is not
called an interruption without a recorded interrupted run. Both cases require
a new Agent session instead of same-session reconstruction.
Normal root-turn process replacement for a new, explicitly admitted prompt
remains bounded by the exact Backend root-close/terminal receipt and
domain-call admission fence. The old journal and cross-process repair paths
were removed in Phase 7; Phase 10 must not recreate them.

Contract verification uses the pinned release identity and affected Adapter
and Gateway tests. Real-process hard-cancel and a joined two-turn Product API
flow passed in isolated test images; scripted loopback provider output proves
the transport contract, not live-model answer quality.
