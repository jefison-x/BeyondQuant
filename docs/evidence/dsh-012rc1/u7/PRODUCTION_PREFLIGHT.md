# U7 production read-only preflight — NOT DEPLOYED

Observed 2026-09-07 Asia/Shanghai. Actual project `beyondquant`, network
`beyondquant-product`; proposed U7 Compose resolved with the existing main `.env`.
Secret/environment values were compared in host memory only, never printed.

| Service | Existing persistent volume / target | Changed Compose environment keys |
|---|---|---|
| Gateway | `byq_workflow_traces` / `/var/lib/byq/workflow-traces` | none |
| Runtime | `byq_dsh_sessions` / `/var/lib/byq/dsh-sessions` | `BYQ_DSH_COMPATIBILITY_RELEASE`, `BYQ_DSH_COMPOSITION`, `DSH_SESSION_ROOT` |
| Backend | `byq_domain_state` / `/var/lib/byq/domain` | `BYQ_PLUGIN_REGISTRY_PATH`, `BYQ_WEB_EVIDENCE_PROVENANCE_POLICY` |
| MCP | none | `BYQ_WEB_EVIDENCE_PROVENANCE_POLICY` |
| Frontend | none | none |

Resolved data volumes match the existing mount identities above. PostgreSQL
resolves to `byq-postgres-clean-20260904`; it is not in the application deployment
service allowlist. PostgreSQL, ML/data/signal Workers and relay must not be
recreated by the release switch. Existing core healthchecks are healthy; workers
are running and backup storage has approximately 72 GiB free.

This comparison is not a complete deployment manifest or deployment authority:
immutable image overlay, explicit private generation namespaces, shared read-only
admission gate, final drained session/trace backup, current logical-backup coverage,
merged clean source, complete qualification and post-switch smoke are still gates.
The running B0 Gateway/Runtime have no newly installed shared admission mount.
Do not assume closing a host file currently protects the serving old stack.
Qualified R1 compatibility is distinct from restoring the original B0 images.

Draft PR #258 exists with G3 qualification failure explicitly recorded. Neither
ready/merge nor production switch has occurred. U8 observation has not started.
