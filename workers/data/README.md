# Data Worker

Trusted Data Plane worker for ADR-0027. It owns the durable schedule loop,
trading-calendar refresh, full-market daily snapshots, retries and restart
recovery. It has PostgreSQL and Tushare credential access but no DSH, MCP,
Gateway, browser, model, repository-write or Docker authority.
