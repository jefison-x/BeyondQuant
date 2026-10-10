# Normal completed-session continuation — 2026-10-09

Fresh qualification stack `byq-dev-c89ff732f2`; no production/old-stack startup. Fixed official rc.2 candidate images documented in `../adr0109-revision-20261009/IMAGES.md`. Two authorized normal Gateway turns using the existing user's OpenCode Go / deepseek-v4.1-flash profile; no model switch or automatic turn replay.

## Observed results (bounded qualification complete)

1. After recreating only the Adapter for the default-off judgment configuration, continued public conversation `conversation_3529cbb916b547bf803a6eb48bdf3a1e`. New root `73c669f65881405081b2b5c448ec4d75` created exactly one task through real MCP: `task_bcc6aa6b60ca4380ae31d3928aef4375`. Product API readback confirms the conversation binding; execution-plan POST 201 / GET 200, version 1, stage `strategy_draft`. No Job/data download/compute/delegation requested or observed.
2. Native root changed from prior `9b167d2e-3fb1-4997-b77d-3768fd9f1abd` to `e2d5a24f-1307-432b-91fd-f824aab3bbf5`. Independent Reviewer source investigation confirms intentional accepted ADR-0096 restart fallback: fresh native session plus completed public history. This is NOT same-native recovery across restart.
3. Without another Adapter restart, one read-only next turn created BYQ root `554024c8bc0c46709841c3620c3f830c`, retained native root `e2d5a24f-1307-432b-91fd-f824aab3bbf5`, and used a different AgentRun. Actual tool ingress: authorize/get/audit, all settled under the new root. Exact Backend terminal closure and runner-signed proven cleanup collected for each root. Normal cleanup transport reason `cancelled` is not a user-cancel scenario.

MCP task-create ingress is observed and Product readback proves the task; `agent_acp_domain_call_observations` is empty. Do not claim it contains a mutating-domain-call row. Provider exports contain the earlier delegated-turn journal as well as each current turn's journal; count each current journal separately, not the aggregate file.

## Remaining boundaries

- Tester, independent Reviewer and Root PASS only the normal-path boundaries explicitly below.
- Context nonduplication requires native history/input evidence, not only the public transcript.
- No delayed old-root request, unknown side effect, interrupted-root recovery, user cancellation, second-user concurrency or background completed-Job continuation is proved by these turns.
- Normal background completion remains NOT_RUN: new DB lacks executable market/security/pool resources and completed signal Job. The verified final read-only archive has relevant tables, but its retention contract explicitly prohibits BYQ 0.10 test/migration input. It will NOT be imported. Only its table-of-contents was read; no data restored/imported. A permitted data source/bundle is required and has been requested from the maintainer.
- Judgment consumer/model execution, default switch, hosted CI/release/deployment remain separate gates. No Product Phase advance, push, merge, deployment or release/tag in this slice.

## Budget separation

The next turn appends to the same native-session provider journal. Its first ten rows exactly match the preparation turn's captured journal; exclude that prefix before counting the next turn. Each new turn used five provider attempts, all HTTP 200 and within the enforced request budget. The earlier delegated-turn journal is excluded entirely. `normal-session-budget-summary.json` records both selections and actual per-turn usage. Journal cumulative counts are not repeat-submission evidence.

## Independent Reviewer

Bounded Functional/Tests/Architecture PASS: same-process normally completed roots share the native session while BYQ root and AgentRun change; exact ACK, settled ingress and signed cleanup exist. Native-history input counting is still pending independent Tester; answer correctness with an explicit task ID is not an implicit-memory proof. Restart fresh-native/public-history fallback remains distinct from same-native recovery.

## Independent Tester / Root verdict

Tester independently confirmed task/conversation/workspace binding, plan HTTP 201/200, roots completed/closed with terminal sequences 21 and 30, ingress cursors 3 and unknown counts 0, distinct BYQ roots/AgentRuns sharing native `e2d5a24f-1307-432b-91fd-f824aab3bbf5`, three settled ingress rows each, no repeated task-create in the read-only next root, and both signature-verified proven cleanup receipts. Tester independently verified old delegated journal exclusion and exact previous-prefix subtraction, leaving five HTTP-200 attempts per new turn.

Root PASS: normal task preparation via actual Gateway→DSH ACP→BYQ MCP, normal Product plan creation/readback, and same-process completed-root native reuse with new business identities and exact terminal closure/cleanup. Reviewer and Tester agree on this bounded scope. The Adapter-restart scenario is the accepted fresh-native/public-history fallback, not same-native persistence across reboot.

NOT_RUN: direct native-history user-input counting (compressed history was located but not read), implicit-memory behavior, delayed request/cancel/unknown/fault paths, real completed-background-Job delivery, enabled dedicated judgment on the new startup configuration, default promotion and release/deploy. These limits are not waived by the Root PASS.
