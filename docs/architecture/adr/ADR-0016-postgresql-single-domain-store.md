# ADR-0016：PostgreSQL 作为唯一 BYQ Domain Store（移除 SQLite）

- Status: Accepted
- Date: 2026-08-17
- Decision scope: BeyondQuant Next 的 Data Plane domain persistence
- Related: ADR-0002、ADR-0006、ADR-0013、ADR-0015

## 背景

BYQ domain state 当时位于单文件 SQLite database（`BYQ_DOMAIN_DB_PATH`），由
ResearchStore、AgentResearchStore、LearningLoopStore、EngineeringTaskStore、
PaperTradingStore、UserAuthStore、UserPolicyStore 和 BacktestJobStore 共享。SQLite
简化 development，但不提供 production-grade concurrency、role isolation、point-in-
time backup，也不是 ADR-0013 已要求的 durable market-data target。同时维护两个 SQL
engine（dev/test 使用 SQLite，production 使用 PostgreSQL）会在每个 store 重复
connection 和 dialect code。

## 决策

1. PostgreSQL 成为唯一 BYQ domain-store engine。Migration 后，从 production 和 test
   code path 移除 SQLite。
2. Environment 通过 PostgreSQL database 和 role 隔离：
   - `byq_domain`（application）、`byq_domain_test`（automated test）、
     `byq_bootstrap`（admin/bootstrap migration），各自使用专用 role；
   - 不共享 credential；Backend 使用 application role 连接。
3. Store 迁移到基于 SQLAlchemy Core + `psycopg` 的单一 shared SQL layer
   `services/backend/app/db.py`，使 placeholder、row mapping、transaction 和 migration
   在各 store 间一致。
4. Immutable object store（Backtest result、bundle）继续通过现有 `LocalObjectStore`
   interface 使用 filesystem-backed object store；large blob 绝不存入 PostgreSQL。
5. 现有 SQLite domain data 通过 logical、idempotent 流程迁移：read-only export →
   validation → manifest → PostgreSQL import → verification；conflict policy 为
   `KEEP_NEW`、`VERIFY_EQUAL`、`REPORT_MISMATCH`。
6. Community PostgreSQL 保持 read-only evidence source，绝不 mount、copy 或作为 BYQ
   authoritative storage。
7. Backup/restore 使用 `pg_dump`/`pg_restore`；执行 durable market-data import
   （ADR-0013）前必须完成真实 restore drill。
8. DSH、MCP、Gateway 和 Product boundary 不变：DSH 绝不直接访问 PostgreSQL；domain
   access 继续经过 BYQ Backend 和 BeyondQuant MCP。

## 后果

- Application、test 和 deployment 共用一个 connection/dialect path，未来增加 store
  更快。
- CI 和 local development 通过 Compose provision PostgreSQL service，并使用隔离 test
  database。
- Unit test 在 test database 上使用相同 store code；SQLite 不再是受支持 Backend。
- Production deployment 需要 PostgreSQL service 和经过测试的 backup/restore；Compose
  topology 增加一个 service。

## 拒绝的替代方案

- dev/test 保留 SQLite、production 使用 PostgreSQL：重复 connection/dialect code，且
  dialect-specific bug 可能逃过 CI。
- 将 result object 等全部 state 存入 PostgreSQL：形成 unbounded row，并违反 object-
  integrity boundary。
- 复用 Community PostgreSQL：违反 ADR-0013 和 read-only evidence rule。
