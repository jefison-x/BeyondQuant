# Phase 7 — Agent authority cutover contract

Status: candidate design; **no deletion or Phase 7 PASS is authorized by this document**.

## Current live boundary

The Adapter lifecycle journal, Gateway lifecycle delivery, and Backend
`agent_runtime_turns` form one live authorization path. An Adapter process loss
must revoke the exact root's BYQ domain-call authority. A Gateway `409` or a
missing DSH session does not change the Backend row. The present journal and
terminal receipt provide that closure, but also retain generic session/root,
generation, executor, and replay state that ADR-002 assigns to DSH.

The 0.10 scope permits an interrupted Agent turn to end without same-session
attach/resume or child rebind. It does **not** permit an old root to keep
authorizing domain writes, fabricate a completed result, replay an Agent
prompt, or change the outcome of an already claimed external action.

## Root-owned target decision

Replace the cross-service runtime replay chain in one vertical cutover with a
BYQ-owned authority fence. The fence stores only the business permission to
call BYQ tools and the exact outcome of already claimed domain actions. It is
not a DSH session, checkpoint, prompt queue, or Agent recovery service.

The implementation candidate is a **Backend-authoritative runtime epoch** for
the single active Gateway/Adapter stack:

1. Adapter startup creates a new random 256-bit incarnation credential through
   a Backend service request authenticated separately from Product MCP. In one
   transaction, Backend stores only its verifier, rotates the current
   authority epoch, and revokes roots from older incarnations. It returns a
   durable, idempotent receipt for the same startup key. The credential is
   never returned by a Product MCP tool or by a DSH-accessible endpoint.
   Adapter does not become ready or start DSH until this succeeds. Gateway
   must verify the Adapter's current receipt through its own service identity
   before admitting Agent traffic; a Backend outage leaves both unready.
2. The Backend marks affected roots `authority_revoked_unconfirmed`. This
   means BYQ domain calls are denied; it does not assert that DSH completed,
   failed, or cancelled the turn. Old session IDs remain interrupted. A new
   Agent turn uses a new session ID.
3. Adapter keeps the incarnation credential private; DSH receives only the
   existing Product MCP transport credential plus a random, session-scoped
   process capability issued only to that DSH process. Adapter binds that
   capability to one session, process, incarnation and currently active root;
   a child may inherit it only within that root. Before **every** Agent-to-Domain
   tool, MCP obtains a fresh exact-root/call admission proof from the live
   Adapter over an authenticated internal service channel. Adapter issues it
   only after validating the process capability and its bound identity; it
   derives the root from its own live binding and rejects a mismatching
   client-provided root rather than trusting it.
   Client-controlled root/session headers and the shared bearer token are
   never sufficient to select another live root. If Adapter is unreachable,
   MCP fails closed,
   including for reads. The proof binds incarnation, root, session, tool and
   call identity, expires quickly, and cannot authorize a second call.
   Backend checks it against the current incarnation verifier at every
   mutating entry. Root registration and lifecycle binding use the same
   authority. A proof minted before Adapter death is a pre-admitted call;
   no proof can be minted afterward. Direct root/child MCP calls while
   Gateway is down follow this same path. MCP's static transport token and
   client-supplied identity headers alone are insufficient. Rotation revokes
   the old credential, so no old Agent may read workspace data or create a
   fresh business claim. Revocation and domain admission use the same
   transaction/lock order. A claim committed before revocation keeps its exact
   result; a claim admitted afterward is rejected. An in-flight external
   action remains `outcome_unknown` until business reconciliation establishes
   its outcome. Existing claim ID/idempotency key and result remain immutable;
   rotation cannot create a second execution under a new key. Internal BYQ
   reconciliation uses a separate service identity; a revoked Agent credential
   grants no post-revocation receipt lookup. A user may query durable Job and
   Artifact results from a new authorized session. No automatic retry or
   compensation is inferred.
4. On a normal terminal, Adapter uses its service identity to send trusted
   terminal proof directly to a Backend exact-root authority-close
   transaction. Backend returns an idempotent receipt keyed to that root;
   Adapter waits for it before admitting another turn in the same live
   session. Gateway consumes only the resulting Product projection and owns
   no lifecycle replay or terminal delivery queue. A lost close response is
   retried for the same root; it cannot reopen or close another root. Backend
   persists authority status and business claim facts only, not a generic
   `agent_runtime_turns` lifecycle history. The cutover can remove generic
   Gateway replay only after direct close and startup rotation both work.
5. ResearchTask, Job, and Artifact lifecycles remain driven by their own
   business state. An interrupted Agent does not cancel a long Job or mark a
   ResearchTask complete. Business handoff uses those stable IDs and facts.

This candidate assumes one active Adapter writer. Multi-Adapter operation
requires an explicit per-incarnation authority scope; a global startup revoke
would otherwise close another live instance's roots. The implementation must
prove that a surviving old DSH process cannot use its previous Product MCP
credentials or identity fields to bypass the epoch fence during Adapter or
Gateway downtime. A Gateway-only restart does not rotate the epoch while its
Adapter is live: it adopts the Adapter's Backend-verified receipt. Gateway
must continue to present that root as active or outcome unknown and block a
conflicting new turn. It may report `interrupted` only after Backend has
revoked that root or acknowledged its exact terminal. If Gateway cannot
establish the live Adapter identity, it remains unready for Agent traffic;
it must not mint a competing incarnation while the old Adapter can still run.
An Adapter restart rotates the epoch and invalidates old call proofs. The
current MCP call context has no such live proof, so a startup revoke without
this path is **NO-GO**. A surviving old DSH process may still consume model
resources until closed, but must not make new BYQ reads or writes. The current
exact-root close path stays until the entire fence passes.

## One-cutover acceptance contract

- Startup revokes multiple old roots without reporting Agent completion; old
  sessions remain interrupted and a new session can start after the receipt.
- A late registration, active event, or MCP/domain write cannot reopen a
  revoked root. Check all Agent-to-Domain MCP tools, including reads, and all
  Backend mutating entries, not only the central claim method. Include a
  direct call from an old DSH child after Adapter restart and a Gateway-only
  restart with the live Adapter unchanged. An old shared Product MCP bearer
  token, a guessed epoch, or client-controlled root header cannot pass.
- An old child holding the shared bearer and its old process capability
  cannot obtain proof for a different live root by forging root/session
  headers. A live root's capability is never exposed via Product API or MCP.
- Kill Adapter while leaving an old DSH child and MCP/Backend alive, without
  starting a replacement Adapter. The child cannot obtain a fresh proof or
  perform any Agent-to-Domain read/write. A proof minted before death remains
  bound to its exact call and settles once or remains unknown.
- Gateway-only restart with a live Adapter preserves an active/unknown root
  and blocks conflicting new turns; it cannot show `interrupted` while that
  root may still write. Backend revocation or exact terminal ACK precedes
  an interrupted/closed projection.
- Startup revocation racing a domain claim has one serial order. Pre-commit
  results remain exact; post-revocation writes fail closed.
- Lost startup-fence response retries to the same result; Backend outage keeps
  Adapter unready.
- An unresolved claim stays `outcome_unknown`, with zero automatic second
  execution. Existing Jobs/Artifacts survive and are queryable by ID.
- Normal terminal close is acknowledged before a same-session next turn.
- Adapter/Gateway/Backend diff removes the generic replay/recovery owner in
  the same change. No compatibility bridge or old journal format reader stays.
- Focused contracts, one real process-loss path, Tester, independent Sol
  Reviewer, and Root acceptance pass before marking Phase 7 complete.

Phase 10 may qualify the broader thin DSH API contract; Phase 14 may create
the fresh schema baseline. Neither is a reason to defer a live Phase 7
authorization replacement or to delete its current fence early.
