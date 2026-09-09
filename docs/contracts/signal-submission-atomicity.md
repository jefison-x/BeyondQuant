# Signal submission identity and atomic references

ADR-0062/0025: both signal-producer and derived backtest-task creation use the
existing signal job store. No new queue or Agent harness.

1. Require trusted active owner/workspace and the owned ResearchTask. Validate the
   bounded original key and finite, credential-free command. Hash owner/workspace,
   command and creation purpose; exclude delivery trace and mutable readiness/repair.
2. Claim the existing owner/workspace key under a PostgreSQL transaction advisory
   lock. Same command returns the committed job without repeating preparation.
   Changed command/purpose returns conflict. Missing legacy command hash returns
   explicit conflict: use original-ID/original-key reads, never guess equivalence.
3. First submission validates/fixes domain inputs and approval where required,
   freezes the requirement, and persists waiting_for_data plus the pool reference
   in one transaction. Any reference failure rolls both back. Preparation is
   bounded validation; expensive readiness scans and repair requests do not run
   in the HTTP submission path.
4. Existing signal Worker assesses durable requirements after commit, requests
   missing-data repair with retry_terminal=false, and promotes only ready inputs.
   Disabled owners are not assessed/repaired/promoted by this scan. A failed or
   completed repair is not automatically restarted by polling.
5. The original frozen requirement/preparation and first delivery trace remain
   authoritative on retries. The new nullable command hash is hidden from public
   projections. Existing rows and artifacts are not retroactively rewritten.

Evidence must cover exact retries after reconnect and new trace, conflicts before
preparation, independent concurrent claimants, injected post-reference rollback,
worker repair after durable acceptance, terminal repair preservation, and disabled
identity. Persistent watch budgets/continuation and legacy-row backfill remain
separate tasks. Historical rows without atomic references are not silently healed.
