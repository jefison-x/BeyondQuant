# Phase 40 acceptance evidence

Phase 40 closes the final Community parity and real Product journey gate.

- ADR-0023 records the isolated signal-producer decision.
- `GOLDEN_JOURNEY.json` records the no-mock two-user Product API journey.
- `CHROME_MCP_REVIEW.md` records desktop/mobile browser, network, console and
  Lighthouse review.
- `COMMUNITY_FEATURE_CHECKLIST.md` records feature-by-feature Community
  classification and closure.
- `scripts/evidence/phase40-product-golden.py` is the reusable secret-free
  Product API verifier. Users and canonical bars are explicit environment
  setup; all product actions in the script cross Gateway Product API.

The isolated sandbox was also exercised with valid Pandas output, forbidden
`socket` import, forbidden file open, and an infinite-loop timeout. D-0003's
production-like object-root audit observed 0 referenced objects, 0 object
files, 0 orphans and 0 missing objects, so its observation trigger was false.

Final local CI (`scripts/ci/local-ci.sh --all --with-smoke`) passed all 12
checks: architecture boundaries, Backend, Gateway, Runtime Adapter, MCP,
locked frontend install/build/53 unit tests/dependency audit, full isolated
Compose smoke, and three real Product API browser journeys. The smoke also
asserted the signal sandbox's non-root user, credential-free environment and
exclusive internal-network membership.
