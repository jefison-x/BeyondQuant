# Terminal Signal-Producer Jobs: Audit and Reversible Record

## Why this exists

`signal_producer_jobs` rows reach a terminal state (`failed`, `completed`,
`cancelled`) and remain in the table forever. Production carries a small set of
historical failures from the ADR-0047 capacity-bound round plus the one completed
signal that fed the round-1 HS300 backtest:

| job | status | error / result | conversation |
| --- | --- | --- | --- |
| `signaljob_53c130e94a8a43928e8ebf7ad994cdac` | `failed` | `market_requirement_exceeded` | `conversation_3cfec242be2e48a3ad414f175ad414bf` |
| `signaljob_7946d38fd0354bc08a2fe096a4b51d10` | `failed` | `market_requirement_exceeded` | `conversation_ea1e1fc5dc9646d0aedaa8761ccc35c6` |
| `signaljob_459bf1459c97497b9e82aa8eaf3aef6f` | `failed` | `signal_execution_failed` | `conversation_01b3a5e573524548b0a3faa9f9a9a6a5` |
| `signaljob_c433216d99434b309d2238657ca4db11` | `failed` | `signal_execution_failed` | `conversation_01b3a5e573524548b0a3faa9f9a9a6a5` |
| `signaljob_fa70e3aa2a8e4517b4a6feac114527f1` | `completed` | `artifact_300b1f7fc30e4fc1813a8148c0c1c829` | `conversation_01b3a5e573524548b0a3faa9f9a9a6a5` |

## No supported domain archive status

BYQ has **no archive status on `signal_producer_jobs` or `research_tasks`**.
The only supported archive lifecycle is the owner/workspace-scoped ML-strategy
lifecycle (`set_ml_study_lifecycle`, ADR-0050), which targets
`ml_strategy_version` artifacts and does not apply to signal/backtest task rows.
There is therefore no domain/agent action that can archive these rows today, and
an ops script must not invent one.

Consequences, stated plainly:

* Terminal-job archival requires a **new domain/agent action** (an Accepted ADR
  plus a Backend/MCP contract). It is not an operations concern.
* Until then, terminal jobs stay visible and immutable. That is intentional:
  they are audit evidence for how the ADR-0047 capacity bounds were reached.
* This tool never deletes, updates, re-statuses or hides a job.

## The tool

`scripts/ops/archive_terminal_signal_jobs.py` is audit-first and non-destructive.

Audit only (default; reads and prints, writes nothing):

```sh
python3 scripts/ops/archive_terminal_signal_jobs.py \
  --database-url "$BYQ_DATABASE_URL"
```

Record the audit manifest without any domain change:

```sh
python3 scripts/ops/archive_terminal_signal_jobs.py \
  --database-url "$BYQ_DATABASE_URL" \
  --manifest-out /var/lib/byq/ops/terminal-signal-jobs-20260919.json
```

Materialise the reversible archive record (explicit; still no domain change):

```sh
python3 scripts/ops/archive_terminal_signal_jobs.py --apply \
  --database-url "$BYQ_DATABASE_URL" \
  --archive-root /var/lib/byq/ops/byq-terminal-signal-jobs \
  --timestamp 20260919T000000Z
```

Each job entry carries: job id, owner, status, task id/title, the linked
`product_conversations` row (id, title, status, message count), strategy-version
artifact id, stock-pool snapshot id, result artifact id, error code, attempt
count and created/started/finished/updated timestamps.

## Safety boundaries

* Database access is read-only (`connection.read_only = True`) and only a single
  parameterised `SELECT` is issued.
* `--apply` writes only `<archive-root>/<timestamp>/manifest.json`. The manifest
  records `database_rows_modified: false`, `production_data_deleted: false`,
  `archive_requires_domain_action: true` and the reversal instruction.
* Reversal: delete the timestamped archive directory. No domain row was changed,
  so nothing else must be restored.
* Fail closed: an archive directory that already exists without a manifest is
  refused; a repeated `--apply` for the same timestamp is an idempotent no-op.
* Unknown/non-terminal statuses are rejected before any query is built.

## Recommended follow-up (domain, not ops)

If maintainers want terminal jobs out of the normal Product view, the correct
path is a named ADR defining a bounded terminal-job lifecycle (for example an
owner/workspace-scoped `archived` marker on the signal-task projection) and the
matching Backend/MCP contract. The ops tool should then be reduced to the
read-only audit it is today; it must not perform the mutation.
