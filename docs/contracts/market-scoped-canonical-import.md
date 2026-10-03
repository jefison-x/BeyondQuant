# Scoped canonical market import

Status: Phase 17 bounded implementation; actual target bootstrap remains pending.

## Owner and entry points

BYQ Data Plane owns canonical facts and readiness. Engineering may perform the
reviewed once-only bootstrap of a fresh disposable target from a validated logical
bundle. Ordinary Product imports continue through domain Jobs and Data Worker.
These store methods add no HTTP/MCP endpoint or Product DSH database privilege:

- `MarketReadinessStore.import_scoped_market_supplements`: one canonical symbol,
  at most 401 calendar days, original factor/action rows and source completeness
  attestations, plus the validated source bundle SHA-256.
- `MarketAutomationStore.import_verified_logical_calendar`: a complete ordered
  SSE calendar interval, original row hashes and TuShare response provenance,
  plus the validated source bundle SHA-256; no Provider invocation.

## Scope and proof

`market_symbol_supplement_completeness` proves only its `(symbol, trade_date)`.
Its content digest binds the symbol/date, original source attestation, bundle
hash and actual imported factor/action row hashes and counts. Canonical row
hashes are checked at import and rechecked when consuming a scoped proof.
Absent actions mean absence for the selected symbol only. An unrepresented
symbol does not inherit the proof.

Original source daily completeness is an attestation from the trusted source
Data Plane. A subset does not contain enough rows to recompute its global
aggregate hash. Store its provenance in the scoped proof; never copy its counts
or completeness flag into target global completeness.

Readiness may use a complete global proof or a valid exact scoped proof for
required supplements. Chosen proof identities participate in the ready-input
digest. Native full-session supplement replacement deletes that date's scoped
proofs in the same transaction.

## Conflicts and calendar

Imports verify original canonical values and provenance. Exact replay is
idempotent; a conflicting row or proof aborts its transaction without overwriting
existing data. Scoped import does not delete other symbols or assert full-market
completeness. Calendar import requires every calendar day, typed open flags,
valid previous-open linkage and one TuShare response provenance. It inserts or
verifies equal rows and cannot overwrite differing existing calendar content.

A bundle digest is an integrity binding, not proof of an arbitrary caller's
source authority. The Engineering wrapper must separately verify the exact
reviewed export identity, completed offline qualification, empty target and
pinned target containers/images. An ambiguous import result permits read-only
reconciliation, never an automatic replacement operation.

## Evidence boundaries

Focused isolated database tests qualify the contract and negative controls.
Source offline validation, actual target import/readback and final Golden A–F
are separate evidence. None grants new external model/provider calls or closes
Phase 17 by itself.
