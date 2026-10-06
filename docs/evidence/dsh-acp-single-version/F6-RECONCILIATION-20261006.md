# F6 / recovery reconciliation (2026-10-06)

Isolated projects only. Production (`beyondquant-*`) was not touched.

## byq-acpcand: unsettled-root reconciliation

- Identity: DB `byq_domain`; owner `admin`, workspace
  `workspace_73c15da91bad4b77adf3ce0a81548f4d`; adapter boot `392ca536...` (epoch 19).
- Backup: `/tmp/byq-acpcand-reconcile-backup-20261006/state.sql`.
- 13 unsettled judgment roots (`active`/`authority_revoked_unconfirmed`) from
  revoked diagnostic boots. **0 closable**: 3 have `outcome_unknown` with
  `process_fence=unproven`; 10 have no settlement. No runner cleanup receipt
  exists for any of their exact scopes (only 2 receipts exist, for other turns).
- No record deleted, no SQL state changed, no forced close, no replay.

### Corrected conclusion

Closing these roots does **not** require relaxing the Backend fence. The
existing trusted fence-proof entry is the runner-persisted signed cleanup
receipt; for these executions the runner produced **no** receipt, so no trusted
fence proof exists and the operator cannot close them. This is a **contract
gap**: there is no operator path to safely close a root whose runner/DSH was
lost without a receipt. "No current process" is not a proof and a historical
EXIT must not be forged. Proposed minimal decision point: a trusted operator
entry (owned by the runner process-fence) that can prove an exact old execution
is gone without a cleanup receipt — e.g. a runner-instance-replacement proof —
or an explicit operator `abandoned` terminal outcome that records the unresolved
fence honestly. This must be an ADR decision before any default promotion; a
production recovery story and the needs_attention cases must be defined, and
rebuilding the database is not an acceptable recovery.

## byq-acpf6: fresh isolated project for F6

- New project `byq-acpf6` (new volumes/DB/secrets, reused built images), pinned
  judgment network `172.30.0.0/16`. Stack healthy; judgment entry authenticated;
  F6 executor flag on.
- F6 gate: `continuation-qualification` returned `qualified:true`.

### F6 execution defects found (fixed)

1. `submit_prompt` started the Product slot for a non-used process even when a
   continuation budget was present, holding the workspace lease so the
   continuation's own availability check reported busy. Fixed by skipping that
   start when `budget is not None`.
2. The continuation's early fail-closed binding persist ran before the new root
   id and authority epoch were set, failing "no exact root authority". Fixed by
   binding `record.process_root_id`/`authority_epoch` first.
3. `_prepare_private_product_home` rejected a pre-existing Adapter-owned home
   created with a looser mode; it now enforces 0700 when the directory is ours.

### Remaining F6 blocker (decision point)

`DshAcpCompatibility.start` in product-slot mode requires the fixed Product
composition, but the continuation supplies the ACP guard patch as the
composition (`create_acp_guard_patch`), so the slot start fails with "ACP slot
requires its fixed Product composition". F6 ACP continuation in the Product slot
is therefore **not wired**: the guard patch must be applied through the product
runner (as an additional patch) or the continuation must run on a local ACP
process. This needs a minimal design decision before F6 execution can be
verified; it is not a route/model issue.

## NOT_RUN

- F6 ACP execution end to end (blocked by the guard-patch/product-slot gap).
- Real Gateway/Product API browser verification; single-version switch and
  release-chain ACP coverage.
