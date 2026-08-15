# BeyondQuant MCP Boundary Contract Placeholder

## Purpose

Define the stable capability boundary between Agent Plane and Quant Domain Plane.

## Ownership

BYQ owns domain capabilities, invariants, authorization, validation, and business idempotency exposed through BeyondQuant MCP. DSH owns generic MCP client infrastructure.

## Non-goals

- This document does not define a complete tool schema.
- It does not permit direct DSH access to BYQ PostgreSQL, Redis business state, or backend internals.
- It does not define a generic second agent harness.

## Stability guarantee

Agent-to-domain calls MUST use this boundary. Storage and backend implementation changes SHOULD remain invisible to DSH clients when the domain contract remains compatible.
