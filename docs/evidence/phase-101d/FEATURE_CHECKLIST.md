# Phase 101 Feature Checklist

| Feature / invariant | Decision | Phase 101 result |
|---|---|---|
| Backend discovery endpoint `GET /v1/users/model-credentials/{id}/models` (decrypt → closed provider `{base}/models` → bounded/dedup) | `IMPLEMENT` | 完成（#287） |
| Discovery sends a bounded client identity; unmappable models marked `supported=false` | `IMPLEMENT` | 完成（#288），实测 opencode 默认 UA 403 → 带标识 200 |
| Supported discovery results persist per credential (`credential_discovered_models`) | `IMPLEMENT` | 完成（#289） |
| Profile creation accepts discovered models; unknown/unsupported fail closed | `IMPLEMENT` | 完成（#289），测试覆盖 |
| Model resolution uses catalogue or discovered runtime provider | `IMPLEMENT` | 完成（#289） |
| Continuation qualification is a closed provider route (deepseek + opencode), not one model | `IMPLEMENT` | 完成（#290），测试覆盖 |
| Gateway forwards discovery with trusted owner context | `IMPLEMENT` | 完成（#291），测试覆盖 |
| Frontend refreshes models on credential selection and via `刷新模型`, filters to supported | `IMPLEMENT` | 完成（#291） |
| Secrets never returned to the browser; browser path is Gateway/Product API only | `VERIFY` | 真实浏览器验证：无跨源、无 5xx、无密钥回显 |

No Community source, PostgreSQL data, cache, credential or Git history was written, copied or adopted.
