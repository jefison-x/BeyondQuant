# Runtime online single-version retirement — 2026-10-09

Tester / independent Reviewer / Root bounded PASS for the current source increment. No default deployment or current-source baked image qualification is claimed.

- Only the ACP compatibility factory is selectable online. Default ACP is used when the environment selector is absent; explicit 0.1.2/0.1.5 selectors reject rather than falling back. Explicit synthetic compatibility injection remains for isolation tests.
- Readiness and operations keep their existing field shape, with SDK distributions marked `not-applicable`. The actual fixed ACP source/lock/CLI and deployment identity checks remain.
- Background continuation retains opt-in, root scope, credential and qualified provider/model gates. Old SDK distribution qualification was removed.
- Dedicated judgment fixes its ACP family. The historical internal `/run` validates service token, trusted context, attempt and task identity, then returns explicit503 without SDK/Backend/model dispatch. Existing `/acp-root/run` activation/authority/budget/unknown/ACK gates remain.
- Reviewer found an intermediate security regression: absent selector chose ACP but skipped the environment-dependent private-process guard. This was corrected before acceptance. The guard now unconditionally invokes the unchanged Linux non-dumpable check, whose failure aborts startup. A real same-UID child test with selector absent proves the unguarded readable baseline and protected `/proc` access refusal.

Independent Tester ran30 frozen nodes, then3 focused guard/legacy-selector nodes: **33 executions,31 unique nodes, all PASS**. The two legacy-selector cases repeat from the first30. Source mounts were read-only in retained ACP dependency image42525, no network, no session volume, all capabilities dropped and no-new-privileges. No application service, DSH/model or real API was started. Only the process-privacy proof uses a synthetic child. Three existing deprecation warnings are retained.

Worker's host collection failure (missing httpx) and initial container observer attempts are preserved in private logs. Executed candidate tests, not host collection, are the PASS evidence. Changes were compared against backups containing the pre-existing OC dirty worktree; unrelated work was preserved.

Independent Reviewer inspected actual incremental backup diffs, assertions and hashes. Functional, Tests, Clean Break Architecture bounded PASS. Root accepts this current-source slice. Existing old SDK source files/images/configuration are classified historical/offline rollback; they are not reachable through the live selector.

**NOT_RUN:** all-component/exact-head CI, current Runtime source baked-image qualification, additional real Product/model trial, trusted-main Release/Promote/deployment. The independently inspected complete official image9112 contains pre-retirement runtime34c43, not current972f0. The distinction is intentional and recorded. No Product Phase advance, push, PR, merge or deployment in this slice.
