# Phase 7 slice 2 — retire advisory generation history

Status: Phase Gate PASS for this bounded slice. Slice 1 passed separately; Phase 7 overall remains in progress.

## Ownership decision

`services/runtime-adapter/app/generation_ledger.py` persists a best-effort list of BYQ runtime generation IDs and epochs. `runtime.py` catches its write failures and explicitly treats it as advisory. No Product response or domain fact reads the list; only runtime rehydration repopulates `RuntimeSession.generations` for private history, and two tests inspect that list. The live current generation, lifecycle journal, loss containment, terminal fencing, conversation owner/workspace, trace sequence, business receipts and Worker/Job state remain separate. This list is generic Agent execution history under ADR-001/002 and has no business owner in BYQ 0.10.

Delete the file-backed generation ledger and the duplicate in-memory `RuntimeSession.generations` history. Keep `RuntimeGeneration` for the active DSH execution binding until the larger Adapter contract is qualified. Keep current-generation terminal fencing and `LifecycleJournal`; do not change the public Product API, DSH SDK, Backend schema, financial idempotency, approval or active Job behavior. Historical D15 qualification scripts/evidence stay historical, with no claim that they still describe current 0.10 runtime.

## Historical release and current build identity

The promoted `dsh-0.1.5rc1` release descriptor and all 34 declared inputs match the pre-Clean-Break main tree `d4c6a9e34f531d27dd0e94804be6ed0aa6f9fde3`. Pin its historical input verification to that exact Git tree. Current BYQ source integrity is checked separately by the new `.217` build revision. Existing `.215` and `.216` build manifests remain frozen. This preserves release verification without treating historical BYQ runtime files as current architecture constraints.

## Acceptance

- Restart/rehydration tests still prove stable BYQ conversation/session identity and monotonic trace sequence using the lifecycle journal, not the removed advisory list.
- A lost open root is still marked interrupted by authoritative journal/containment evidence. Late terminal writes remain fenced by active generation and epoch.
- No code writes or reads `generation-ledger`; no new state store or compatibility shim is added.
- Current build identity gets a new immutable revision, preserving `.215` and `.216`; Compose default and CI choose it. The H4 interface ledger is reconciled against the actual diff.
- Runtime Adapter affected/full tests, architecture unittest, build/release checks, and `git diff --check` run before independent Sol Reviewer and Root acceptance. No Phase 8 environment/database cleanup is implied.

## Gate evidence

Candidate commit `a2d134ed` passed the full repository unittest suite (918 tests, 11 skipped) after the new runtime source entered Git history. The Runtime Adapter suite passed in an offline, read-only container (283 passed, 52 skipped). H4 audited 572/572 interfaces with zero stale or missing records. Historical DSH release inputs, frozen `.215`/`.216` and current `.217` build manifests, promotion, Compose resolution and diff checks passed. The independent Sol Reviewer examined the actual diff and reported Functional PASS and Clean Break Architecture PASS with no blocking finding. Root accepts this deletion only; broader Adapter/session ownership remains for qualified later slices.
