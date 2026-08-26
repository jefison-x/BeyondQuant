# Data Worker

ADR-0027 的 trusted Data Plane worker。它负责 durable schedule loop、
trading-calendar refresh、full-market daily snapshots、retries 和 restart
recovery。它可访问 PostgreSQL/Tushare credential，但没有 DSH、MCP、
Gateway、browser、model、repository-write 或 Docker authority。
