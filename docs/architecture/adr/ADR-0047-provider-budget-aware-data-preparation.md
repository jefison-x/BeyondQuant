# ADR-0047: Provider-budget-aware Data Preparation and Observable Tasks

- Status: Accepted
- Date: 2026-08-31
- Decision owners: BeyondQuant Product, Data and ML Planes
- Phase: 82

## Context

A production ML preparation requested 300 symbols over 1,128 open sessions, or
338,400 symbol/session cells. The request failed before useful work because the
50,000-cell bound of one `market-data-requirement.v3` was also treated as the
maximum size of the whole ML preparation. The uncaught validation error then
restarted the ML Worker, hiding the actual data task behind a generic runtime
failure.

Tushare's official 2,000-point permission table, obtained by a RMB 200 annual
donation at the documented 1:10 ratio, permits 200 calls per minute and 100,000
calls per API per day. The official A-share daily contract returns at most
6,000 rows per call. These are Provider request budgets, not BYQ completeness,
memory, transaction or retry bounds. A theoretical quota product is not a
throughput guarantee.

BYQ already partitions Xiaoba data demands and already persists repair,
per-session synchronization and automation jobs. The Product Data Center lists
several of these records, but has no unified stage/unit projection and ML
waiting runs do not expose their data preparation progress.

The read-only Community Data Sync page contains hardcoded pools, a TODO API and
fake 50% progress. Its durable sync task model nevertheless confirms the useful
UX invariant: a task should expose queued/running/terminal state, completed and
total units, rows, heartbeat, retry and a safe failure. Its ORM, thread runner,
direct Provider paths and fake page are not reusable.

## Decision

### 1. Separate aggregate requests from atomic readiness partitions

The 50,000-cell and 250-session bounds remain invariants of one independently
assessable and retryable readiness partition. They are not Provider quotas and
must not cap an aggregate data demand or ML preparation.

Backend creates a deterministic list of non-overlapping date partitions for an
aggregate frozen universe and date window. Every partition receives its own
existing repair request. Aggregate readiness is derived only from current
partition assessments; enqueue or download completion alone never means ready.

ML training persists the partition plan and uses the same preparation facade.
The worker assesses failures per run, so one malformed or oversized run cannot
restart the worker or block unrelated runs.

### 2. Treat Provider permissions as a configurable operational budget

The Data Worker remains the only Tushare caller. The default personal
2,000-point profile records the official 200 requests/minute, 100,000 requests
per API/day and 6,000 daily rows/request ceilings. BYQ applies a conservative
request-rate budget with headroom and retries provider rate-limit responses.

The profile does not claim to discover the credential's actual tier and does
not predict completion time from the theoretical maximum. Daily call counts,
rows and durable work units are observable; credentials and raw Provider
responses are not.

### 3. Project one truthful task view without a second workflow

Add `data-task.v1` as a read-only Product projection over existing data demand,
repair/session, security-master, manual synchronization and automation records.
It has stable task/reference identities, purpose, stage, status, completed and
total units, percentage, row counts, safe error, timestamps and bounded detail.

The Data Center leads with this task view and polls the existing Product API.
ML waiting runs expose their linked preparation stage and progress. Browser
continues to call Gateway/Product API only.

### 4. Keep large ML material bounded and auditable

The ML contract may process an aggregate partition plan up to its documented
universe/session/usable-row limits. Feature material must still pass a bounded
serialized-size check before persistence and training. Exceeding that separate
resource limit fails only the affected run with an actionable safe error; it
does not relabel Provider quota or crash the worker.

## Consequences

- A 338,400-cell request becomes several <=50,000-cell repairable partitions.
- Task progress is durable work completed over total work, never simulated
  time or a percentage inferred from Tushare's theoretical quota.
- Provider throttling may extend elapsed time but protects the shared personal
  quota and keeps retries observable.
- Existing bounded repair/session state remains authoritative; no generic
  harness or second synchronization engine is introduced.

## Rejected alternatives

- Raise `MAX_REQUIRED_CELLS` globally: removes transaction/retry protection and
  confuses a domain work bound with a Provider permission.
- Treat 600 million theoretical rows/day as an SLA: ignores endpoint mix,
  latency, retries, trading-calendar work and account-specific restrictions.
- Show frontend-only progress: cannot survive restart or prove completion.
- Copy Community sync code: violates current Product, Data and Provider
  boundaries and would reintroduce fake/incompatible behavior.
