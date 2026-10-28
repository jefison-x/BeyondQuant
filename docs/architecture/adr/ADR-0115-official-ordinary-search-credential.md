# ADR-0115 — Official ordinary Product search credential delivery

- Status: **Accepted** (2026-10-29; maintainer: “复用当前Key，补齐并验证搜索”).
- Scope: ordinary Product ACP roots using qualified official DeepSeek or OpenCode Go routes. This is maintenance, not Product Phase advancement.

## Context

The user configured an owner-scoped `web_search_api_key` credential through Product Settings. A fresh official DeepSeek ordinary conversation still reached the search plugin without `DEEPSEEK_SEARCH_API_KEY`. The Runtime resolver could resolve that exact owner's search record, but official roots skipped its lookup and child environment delivery. A separate older conversation's recovery failure remains independent.

## Decision

For each fresh ordinary Product root, resolve the current owner's independent `web_search_api_key` record before starting its DSH child for both qualified OpenCode Go and official DeepSeek routes. Deliver the resolved value only as `DEEPSEEK_SEARCH_API_KEY` to that child. Keep the existing owner/session/trace checks, resolver authentication, ordinary execution overlay, and closed environment validation. No model-key or ambient-environment fallback is permitted. F6, delegated, task-ready and continuation roots do not gain search lookup or injection.

The official DeepSeek model key and separately configured search key **may have the same value**, as the maintainer explicitly authorized reuse. They remain separate purpose-scoped records and are resolved independently. This exception applies only to the `DEEPSEEK_API_KEY`/`DEEPSEEK_SEARCH_API_KEY` pair; OpenCode Go model and search values, MCP discovery/signing keys, resolver and other internal credentials remain distinct. It does not establish that the upstream search provider accepts the reused key; a real Product search is a separate verification gate.

## Gates

Narrow source and contract tests, independent review, CI/release, deployment and real browser search verification remain distinct. The previously failed conversation recovery is not repaired or reclassified by this decision.
