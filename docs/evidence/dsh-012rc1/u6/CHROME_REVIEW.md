# U6 final-artifact Chrome review

Date: 2026-09-06. Actual Chrome MCP context `byq-u6-final-build-review`, page 5,
loopback frontend `http://127.0.0.1:18210`, synthetic account `u5-admin`.
Scope: `byq-u5-u6-mr5ccwtq`; images came from the validated retained CI archive,
not a browser mock or an older diagnostic build. See [artifact identities](retained-artifacts.json).

## Old-release maintenance window

The real G6 conversation `conversation_90356e51cb96459cb30319c0a0bbbcac` had one
pending approval, `agent_approval_17f3ea9ffa7a41b787267eb3f6976872`, for draft
`feedback_64abd6f3b1d9465b84fba4ad90940312`. The global approval center showed the
same feedback/conversation; its approve/reject buttons were not clicked by Chrome.

Two actual Send clicks with the exact fixed G5 prompt, during the closed gate,
returned HTTP 503. The UI displayed the maintenance/input-retained message.

| Actual DOM check | Desktop 1440×1000 | Mobile 390×844 |
|---|---|---|
| Input equals the retained fixed G5 prompt | PASS | PASS |
| Maintenance message visible | PASS | PASS |
| Rejected G5 absent from transcript | PASS | PASS |
| No processing indicator | PASS | PASS |
| Document width equals viewport width | 1440 | 390 |

Chrome network evidence: requests 42/45 were the two rejected Product turns.
Auth initial 401 was expected; login, history, global approvals and existing
normalized WorkflowTrace SSE returned 200. All 17 observed application requests
used the same loopback origin and Gateway auth/Product/Agent/WorkflowTrace routes.
No Backend, MCP, DSH, database or external Hub request originated in the browser.

## Candidate completion and Plugin Center

After queued continuation and the accepted candidate G5 follow-up, a real reload
of the same conversation showed the original feedback, approved result, completed
submission and contextual follow-up. The mobile DOM had no processing indicator,
the global approval button reported no pending work, and document width remained
390. The earlier rejected browser input was not represented as an accepted turn.

The plugin page `/settings/system/plugins` was inspected at both viewport sizes:

- SDK: `deepseek-harness-sdk==0.1.2rc1`.
- Runtime: `deepseek-harness-runtime-bin==0.1.2rc1`.
- Active profile: `byq-product-candidate`.
- Composition: `sha256:e584cee23c7e39ffaaf7d4c583d4762556032b4d4d173285c14c038d98ec6f98`.
- Desired/Active matched; three qualified/active plugins, two blocked plugins.
- Ask-user and Spill remained blocked. No governance/qualification request was
  created. No deployment or gate-write action was taken through the browser.
- Document widths were exactly 390 and 1440. All seven observed application
  requests were same-origin GETs; Plugin Center and bounded session list returned 200.

This is actual DOM/network review; no saved screenshot is claimed. Real model
outputs were synthetic public answers, not private reasoning or production chats.
The separate live runner verifies fake-Hub counts and domain state; the UI's
generic central-Hub wording alone is not proof of external isolation.

## Additional G1 semantic inspection

Through the same Gateway-only browser context, the public G1 answer in
`conversation_50846cff90d349a490cd2e8276d65e29` correctly reported natural date
2026-09-06 (Asia/Shanghai, Sunday). It explicitly declined to infer a prior trading
day because the synthetic BYQ calendar/complete-session coverage was unavailable.
The probe independently verified unchanged Product object counts. No calendar or
market-data write was requested to make this scenario pass.
