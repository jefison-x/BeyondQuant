# U7 Community reference and review checklist

Status: reference inspection and final U7 artifact Chrome review PASS.
No Community file or BYQ frontend source is changed in U7.

Read-only reference inspected: Community `frontend/src/views/AgentView.vue`
composer 335–380 and submit handling 862–922; global approval drawer in
`frontend/src/components/agent/GlobalApprovalCenter.vue` 1–125. Existing U6
classification remains applicable, but its browser evidence does not certify
new U7 image/policy/registry identities.

| Feature | Classification | U7 acceptance requirement |
|---|---|---|
| Multiline composer, Ctrl+Enter | PORT_UX | Existing interaction works at desktop/mobile widths. |
| Clear input before transport acceptance | REPLACE | Closed admission returns maintenance and retains rejected input; no accepted-looking transcript bubble. |
| Raw Agent stream/context coupling | DROP | Browser uses Gateway Product API and normalized WorkflowTrace only. |
| Global approval drawer | PORT_UX | Pending record remains visible; queued continuation survives upgrade exactly once. |
| Immediate execution wording during maintenance | REPLACE | Durable decision/queued status must not falsely claim execution. |
| Product deployment/gate controls | DROP | No browser writer, installation or operator privilege. |
| Plugin desired/active identity | REFERENCE_ONLY | Verify actual 0.1.2rc1 SDK/carrier and new qualified registry together; blocked plugins remain blocked. |

Historical profile name `byq-product-candidate` is immutable build identity, not
the current qualification state. U7 reports must distinguish that name from the
separate QUALIFIED carrier/projection attestation. No mock or screenshot-only
inspection will be counted as final Product acceptance.

Actual desktop/mobile results are recorded in [Chrome review](CHROME_REVIEW.md).
The exact-image live runner independently verifies durable continuation and
new/old policy bindings; its completed result remains a separate acceptance gate.
