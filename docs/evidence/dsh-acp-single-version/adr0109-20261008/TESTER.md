# Independent Tester — ADR-0109, 2026-10-08

## Results

Two focused Backend tests independently PASS in the new internal-network PostgreSQL tmpfs
`byq_domain_test`: durable/idempotent denial and terminal cursor; changed input, sibling
AgentRun and existing unknown refusal.

Actual Backend HTTP plus the frozen MCP acp-bridge.ts ran three synthetic requests without
DSH/Gateway or model credentials:

| Case | MCP result | Backend ledger | Read-only terminal predicate | Result |
| --- | --- | --- | --- | --- |
| normal role denial | denied, exact denied settlement ACK | settled / denied | allows | PASS (normal path) |
| authorization response dropped | no proof, unknown settlement ACK | unknown / unknown | blocks | PASS (fence) |
| negative settlement response dropped | no settlement ACK | settled / denied | allows | FAIL against current ADR lost-receipt fence |

Each case had exactly one durable denial audit. All three synthetic roots remained active;
no root close, new root admission or cleanup/terminal ACK was exercised. The predicate was
called read-only. This proves the Backend/MCP response-loss difference, not actual terminal
ACK delivery or Product acceptance.

## Environment and limitations

Only the newly created tmpfs DB and test internal network were used. No candidate/production
storage, failed real root, model call or business source edit. One fixture write-permission
problem was fixed without product effects. Initial bridge readiness failed because the
harness used an absent network alias. A single URL-only correction to the existing container
DNS name enabled the first executed three-case tool probe. No automatic business replay.

Logs: tester-backend.log, tester-bridge.log, tester-ledger.json. Root handles disposal of only
the named temporary Backend HTTP container, PostgreSQL container and test network.
