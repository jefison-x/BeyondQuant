# Stale root identity fence — 2026-10-09

**PASS, bounded synthetic isolated protocol slice.** This uses synthetic seeded roots/HMAC identity against real MCP HTTP and Backend/PostgreSQL. It does not start DSH, use a model key, or prove naturally late DSH requests or Product acceptance.

Old root is completed/closed; new root is active, with the same native session and a different AgentRun. The old token yields MCP rejection and Backend observe/abort HTTP 409. Ingress counts remain old 1→1 / new 0→0. No business handler or new root authorization is admitted. The disposable internal network and tmpfs database publish no host port and create no volume; independent label inventory found no remaining probe resources.

Retained failures: v1 lost setup stage diagnostics; v2 accurately isolated `seed_product_context` failure because only Agent schema existed while Workspace trigger installation requires the registered test schema. The corrected seed reuses existing registered schema DDL without dropping any schema. The next run passed all protocol assertions.

Independent Reviewer then found cleanup Unknown could falsely pass if Docker inspect/list failed. Root changed exact not-found classification and requires successful final listings; six narrow fake-command cases and static list checks passed, with no Docker/model execution. Reviewer rechecked the correction. Existing real protocol evidence was reused rather than rerun. Tester/Reviewer/Root bounded PASS; exact current-head hosted qualification remains NOT_RUN.

The original JSON omits exact execution scope/image/source hashes. `manifest.json` records known invocation/configuration and current hashes, with this audit-binding limitation explicitly retained. It is not a retroactive exact-source execution receipt.
