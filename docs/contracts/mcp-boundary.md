# BeyondQuant MCP Boundary Contract

## Purpose

Define the stable capability boundary between Agent Plane and Quant Domain Plane.

## Ownership

BYQ owns domain capabilities, invariants, authorization, validation, and business idempotency exposed through BeyondQuant MCP. DSH owns generic MCP client infrastructure.

## Phase 8 data capability

The `byq_market_daily` tool is the Agent-to-Domain entry point for the Phase 8
daily market-data contract. It accepts the normalized request fields described
in [the data-provider contract](data-provider.md) and returns BYQ daily bars
plus provenance metadata.

The MCP service may call the Backend Domain/Data endpoint to fulfill this
capability. It must not receive or forward `TUSHARE_TOKEN`, and it must not
pass through arbitrary Tushare endpoint names, raw parameters, or raw provider
response envelopes.

## Non-goals

- This document does not define a complete tool schema.
- It does not permit direct DSH access to BYQ PostgreSQL, Redis business state, or backend internals.
- It does not define a generic second agent harness.

## Stability guarantee

Agent-to-domain calls MUST use this boundary. Storage and backend implementation changes SHOULD remain invisible to DSH clients when the domain contract remains compatible.
