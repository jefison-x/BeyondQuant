# Phase 7 — late domain proof after terminal closure

Status: bounded local evidence; Phase 7 overall remains OPEN.

## Scope and reason

Base: `4018f971` on isolated `clean-break/runtime-simplification` (2026-09-27, Asia/Shanghai). The previous boot-authority cutover added an active-root check to fresh domain-call evidence ingestion. That check prevented an exact existing claim from returning its durable `unknown` receipt after root terminal closure. Existing BYQ contracts allow late, correctly bound proof as inert evidence; they still deny new claims and writes after authority closes.

This slice removes only the added active-root requirement at evidence ingestion. Owner/workspace/session/trace/root/run/role/task/conversation binding, proof sequence and retention checks remain. Claim creation still requires active authority, and execution still checks authority immediately before its domain write. The test now asserts an exact old claim returns `unknown` and a new idempotency key is rejected after terminal closure. This does not replay an Agent turn or DSH session.

The immutable selected build advances from `.229` to `.230`; `.229` remains frozen byte-for-byte. DSH remains `0.1.5rc1`.

## Verification

- Fresh dedicated PostgreSQL in a disposable Compose project: `test_domain_correction_admission.py`, `test_domain_call_evidence.py`, and `test_runtime_authority_rotation.py` — **47 passed**. This includes the previously failing late-proof case and its new-key denial, exact evidence binding, terminal write prevention, and boot authority rotation.
- Current build/architecture focused suite — **86 passed**. Selected `.230` and frozen `.229` build checks passed; `git diff --check` passed before evidence drafting.
- The dedicated project ended with **zero** containers, volumes, networks and images; temporary credentials were removed. No existing database, user data, backup, service, push, merge or deployment was touched.

## Remaining limit

This repairs an inherited proof/receipt regression. The live Adapter journal → Gateway lifecycle delivery → Backend root authority fence remains. The final post-deletion `outcome_unknown` integration proof and generic runtime deletion remain Phase 7 work. Phase 7 overall stays OPEN; Phase 8 stays CLOSED.
