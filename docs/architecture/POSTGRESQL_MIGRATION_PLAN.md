# PostgreSQL Single Domain Store — Migration Plan

Status: Accepted implementation plan（ADR-0016）。本文是将 BYQ domain persistence 从 SQLite 迁移到单一 PostgreSQL engine，并为后续 phases 提速的 engineering blueprint。

## 1. 当前 storage inventory（基于 2026-08-17 `main` 验证）

八个 domain stores 都连接同一 SQLite file（`BYQ_DOMAIN_DB_PATH`，默认 `/tmp/byq-domain.sqlite3`，production `/var/lib/byq/domain/byq.sqlite3`）；各自拥有 schema/query，当时 production code 尚无 shared SQL layer。

| Store | Module | Tables |
|---|---|---|
| ResearchStore | `research.py` | `research_tasks`、`experiments`、`artifacts`、`research_transitions` |
| AgentResearchStore | `agent_research.py` | `agent_runs`、`agent_audit`、`agent_approvals` |
| LearningLoopStore | `learning_loop.py` | `learning_runs`、`learning_iterations`、`evaluation_signals`、`lessons`、`learning_history` |
| EngineeringTaskStore | `engineering.py` | `engineering_tasks`、`engineering_history` |
| PaperTradingStore | `paper_trading.py` | `paper_accounts`、`stock_pools`、`paper_positions`、`paper_orders`、`paper_fills` |
| UserAuthStore | `user_auth.py` | `users`、`auth_sessions` |
| UserPolicyStore | `user_policy.py` | `user_agent_policy` |
| BacktestJobStore | `backtest.py` | `backtest_jobs` |
| LocalObjectStore | `backtest.py` | `BYQ_BACKTEST_OBJECT_ROOT` 下 filesystem（不变） |

当时通用 pattern：`sqlite3.connect(..., check_same_thread=False)`、`sqlite3.Row`、PRAGMA、`CREATE TABLE/INDEX IF NOT EXISTS`；`?` placeholders；`fetchone/fetchall`；用 `ALTER TABLE ADD COLUMN`/PRAGMA 做 back-migration；JSON/timestamps 存 TEXT；每 store 一个 `threading.RLock`；`from_env()` 在 `app/main.py`/worker 构造；API tests monkeypatch module stores。

### 1.1 已 merge foundation（不得重做）

- `compose.yml`：`postgres:16-alpine`、`byq_domain`/`byq_app`、health dependency、`BYQ_DATABASE_URL`。
- `services/backend/app/db.py`：SQLAlchemy Core + psycopg helpers；`SQLAlchemy==2.0.40`、`psycopg[binary]==3.2.6`。
- `services/backend/tests/test_db.py`：设置 `BYQ_DATABASE_URL` 时运行 PG integration。

### 1.2 检查发现的两个 trap

1. `db.py` 的 `RESEARCH_SCHEMA_DDL` 只是 sketch，与 ResearchStore 不符：`research_transitions` 实际 composite PK 为 `(entity_type, entity_id, idempotency_key)` 并含 `request_hash`/`target_status`/`result_json`；`experiments` 有 `input_snapshot`；artifacts/experiments idempotency 按 `(task_id, idempotency_key)`。决策：每 store 自有精确 PG `SCHEMA_DDL`/`bootstrap_schema()`，替换 sketch。
2. Compose backend tests 当时默认写 app DB `byq_domain`；stores 迁移后必须固定 `byq_domain_test`（Stage 1）。

## 2. Target topology

```text
backend -> BYQ_DATABASE_URL (postgresql+psycopg://byq_app:***@postgres:5432/byq_domain)
postgres:
  byq_domain       - application (byq_app)
  byq_domain_test  - automated tests (byq_test)
  byq_bootstrap    - bootstrap/admin/migrations (byq_bootstrap)
object store       - filesystem volume (byq_domain_state/backtest-objects)
```

`BYQ_DATABASE_URL` 取代 `BYQ_DOMAIN_DB_PATH`。Community PostgreSQL 仍是 read-only evidence，不 mount/copy/作为 authoritative storage。

## 3. Shared SQL layer contract（`db.py` v2）

所有 stores 使用单一 entry point：

- 保留 `create_db_engine(url)`（`pool_pre_ping=True`）、`connect`、`execute`、`fetch_one`、`run_ddl`。
- 增加 `transaction(engine)`，以 `engine.begin()` commit/rollback multi-statement writes。
- `execute()` 集中 normalize：`datetime/date → isoformat()`、`Decimal → float`、JSONB dict/list 原样、bool 原样。
- 增加 `ensure_column(...)`，使用 `ADD COLUMN IF NOT EXISTS`。
- 每 store 定义 `SCHEMA_DDL: list[str]` 和 `bootstrap_schema(engine)`；`db.py` 不拥有 store-specific DDL。
- 可用小型 `PgStoreMixin`（engine/lock/execute/fetch/transaction/close/from_env），但不得构建 generic harness；store 保留 validation/transitions/invariants。

## 4. 八个 stores 的统一 migration contract

保持 public method names/signatures/return shapes，仅替换 SQL backend：

1. `__init__(database_url=None)`；`from_env()` 读 `BYQ_DATABASE_URL`；`close()` dispose engine。
2. `?` 改 named `:param`，tuple 改 dict。
3. DDL mapping：

   | SQLite | PostgreSQL |
   |---|---|
   | `TEXT PRIMARY KEY` IDs | `TEXT PRIMARY KEY` |
   | TEXT timestamps | `TIMESTAMPTZ`，API 仍 ISO strings |
   | `*_json TEXT` | `JSONB`，默认 `'{}'::jsonb` |
   | money/price/cash/fees `REAL` | `NUMERIC(18,4)`，读取 normalize float |
   | metrics/limits `REAL` | `DOUBLE PRECISION` |
   | counters/version/sequence | `INTEGER` |
   | 0/1 flags | `BOOLEAN` |
   | unique indexes | 同 columns 的 `CREATE UNIQUE INDEX IF NOT EXISTS` |
   | FK | 保持 `REFERENCES`，按既有 parent-first insert |

4. JSONB write 直接传 Python object，不 `json.dumps`；read 不 `json.loads`（可留 tolerant helper）。
5. Timestamps 继续写 UTC ISO text，PG cast 后集中 normalize，保持 API/string comparisons。
6. Back-migrations 用 `ensure_column`。
7. Single statement auto-commit；atomic flows（如 `disable_user`、order submit）用 transaction。

## 5. Test 与 CI strategy（Stage 1 先完成）

新增 `services/backend/tests/conftest.py`：必须有 `BYQ_DATABASE_URL` 且 database name 必须为 `byq_domain_test`，否则明确 skip/refuse；每 test 以 AUTOCOMMIT `DROP SCHEMA public CASCADE`、`CREATE SCHEMA public`，再运行已迁移 stores 的 `SCHEMA_DDL`。API tests 继续 monkeypatch stores；store tests 改为 `Store()`，LearningLoop 保留 ResearchStore dependency。

Compose init `infra/postgres/init/10-byq-databases.sql` 幂等创建 `byq_test`、`byq_bootstrap` roles 和 `byq_domain_test`、`byq_bootstrap` databases；`CREATE DATABASE` 在 transaction 外以 `\gexec` 执行。Compose 自身已创建 `byq_domain`/`byq_app`。

CI backend test 必须使用：

```yaml
docker compose exec -T
  -e BYQ_DATABASE_URL=postgresql+psycopg://byq_test:byq-test-dev@postgres:5432/byq_domain_test
  backend python -m pytest -q -p no:cacheprovider
```

## 6. Stage checklist（每 stage 一个 PR/human gate）

### Stage 0 — Foundation（`MERGED`）

Postgres service、`BYQ_DATABASE_URL`、`db.py` v1、`test_db.py`；无 store migration。

### Stage 1 — Harness + UserAuthStore + UserPolicyStore

先做最小 stores、JSON-adjacent column、BOOLEAN upsert、session→user FK 和 column migration pattern。修改 `db.py` v2、user stores/tests/conftest、init SQL、Compose、CI。验收 users/sessions/policy 全在 PG，API tests 使用 test DB，guard 拒绝非 test URL。`BYQ_DOMAIN_DB_PATH` 暂保留到 Stage 6。

### Stage 2 — PaperTradingStore + BacktestJobStore

迁移 NUMERIC、JSONB、upserts、FK-free tables 和对应 tests/API tests。`LocalObjectStore` 保持 filesystem；worker `from_env()` 使用 DB URL。

### Stage 3 — AgentResearchStore + LearningLoopStore + EngineeringTaskStore

迁移中型 FK/JSONB/BOOLEAN stores 及 tests。LearningLoopStore 仍接收 ResearchStore；Stage 4 前二者可暂用不同 SQL。

### Stage 4 — ResearchStore + DDL contract fix

最后迁移最大/最常用 store；用 section 1.2 的精确 schema 替换 sketch，验证 `input_snapshot`、content-addressed artifacts、composite transition PK 和 cross-store tests。

### Stage 5 — Logical SQLite → PostgreSQL data migration

新增 `sqlite_export.py`、`pg_import.py`、`migrate_sqlite_to_pg.py`、tests 和 `docs/operations/postgres-migration-runbook.md`。Pipeline：

1. 以 SQLite URI `mode=ro` 导出每 table 为 canonical JSONL + schema/version metadata。
2. 校验 ids、symbols、dates、finite numbers、JSON、owner/actor。
3. Manifest 记录 per-table counts/fingerprints/source hashes。
4. PG import 幂等，policy `KEEP_NEW`/`VERIFY_EQUAL`/`REPORT_MISMATCH`，绝不 last-write-wins。
5. 以 counts/sample fingerprints 验证。

必须在 Stage 6 cleanup 前对原 `byq_domain_state` volume 执行 export。

### Stage 6 — SQLite removal/cleanup

从 Compose 移除 `BYQ_DOMAIN_DB_PATH`，保留 DB URL 和 object-store volume；更新 worker/docs/tests。Gate：

```bash
rg -n "BYQ_DOMAIN_DB_PATH|sqlite3|import sqlite" services compose.yml workers docs/roadmap docs/architecture docs/DEVELOPMENT_WORKFLOW.md
```

只允许 migration runbook/Community inventory 等 historical mentions。

### Stage 7 — Backup/restore drill + ADR-0013 import

新增 `scripts/pg-backup-restore.sh`：`pg_dump -Fc byq_domain`，恢复到 scratch、验证 counts/checksums、drop scratch。真实 restore 是 ADR-0013 bulk import 的 hard gate。随后按 read-only export→validate→manifest→BYQ import→verify 执行 Community market migration，复用 conflict policy；BaoStock/AKShare/VectorBT 保持 DROP。

## 7. Store-by-store DDL checklist

- `users`：`username UNIQUE`；`preferences`/`default_prompt` 可幂等 add。
- `auth_sessions`：FK user；index `(user_id, expires_at)`。
- `user_agent_policy`：PK owner；BOOLEAN；owner conflict upsert。
- `paper_accounts`：unique owner/name；cash NUMERIC。
- `stock_pools`：symbols/weights/provenance JSONB；可 add type/description/weights。
- `paper_positions`：PK account/symbol，conflict upsert。
- `paper_orders`：unique account/idempotency；money NUMERIC。
- `paper_fills`：money NUMERIC；index account/created。
- `backtest_jobs`：unique task/idempotency；request/manifest/reference/summary JSONB。
- `agent_runs`：unique owner/idempotency。
- `agent_audit`：FK run；detail JSONB；index run/created/audit。
- `agent_approvals`：FK run；unique run/idempotency。
- `learning_runs`：unique owner/idempotency；三 JSONB。
- `learning_iterations`：FK；unique run/idempotency 和 run/sequence；三 JSONB。
- `evaluation_signals`：unique task/idempotency；value DOUBLE PRECISION。
- `lessons`：unique task/idempotency；三 JSONB。
- `learning_history`：index entity/created/history。
- `engineering_tasks`：unique owner/idempotency；self_review BOOLEAN；architecture evidence JSONB。
- `engineering_history`：FK；index task/created/history。
- `research_tasks`：unique owner/idempotency。
- `experiments`：FK task；unique task/idempotency；input_snapshot JSONB。
- `artifacts`：FK task/nullable experiment；unique task/idempotency；content/lineage JSONB；kind index。
- `research_transitions`：composite PK entity/id/idempotency；`request_hash`、`target_status`、`result_json JSONB DEFAULT '{}'::jsonb`。

## 8. Known traps 与 gates

- 不可原样复用旧 `RESEARCH_SCHEMA_DDL`。
- `BYQ_DOMAIN_DB_PATH` 保留到 Stage 6，并在同一 PR 更新 architecture test。
- CI 只写 `byq_domain_test`，guard 阻止 app DB。
- JSONB 不 double encode/decode；timestamps/money 集中 normalize。
- PG 强制 FK，保持 parent-first insert，并检查依赖 SQLite lax behavior 的 delete。
- `CREATE DATABASE` 必须 transaction 外执行。
- Community PG 只读；backup/restore/ADR-0013 不触碰它。
- Large blobs 留 LocalObjectStore；PG 只存 references。
- BeyondQuant Next v1.0 时按 ADR-0015 禁用 auto-merge，恢复 human gate。

## 9. Phase 31 definition of done

- 全部 backend tests 使用 `byq_domain_test`，guard 生效。
- 无 SQLite code path，`BYQ_DOMAIN_DB_PATH` 仅可在 migration references。
- 八 stores 全经 `db.py` 使用 PG，public method shapes 不变。
- 对真实 dev volume 执行 logical SQLite→PG migration，幂等并按 manifest 验证。
- `pg_dump`/`pg_restore` drill 通过并验证 scratch。
- Architecture tests、CI、Compose 更新；Phase PR 记录 ADR-0016 acceptance evidence。
