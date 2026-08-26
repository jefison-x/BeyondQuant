# ADR-0019：Encrypted Credential Store 与 Runtime Resolution Boundary

- Status: Accepted
- Date: 2026-08-22
- Decision scope: Phase 37 model credential 与 Phase 39 Tushare credential
- Related: ADR-0003、ADR-0004、ADR-0005、ADR-0012、ADR-0014、ADR-0016
- Contract: `docs/contracts/credential-store.md`

## 背景

Community 通过 `UserModelSettingsPanel` 暴露 provider/model credential CRUD、model
profile 和 Agent binding，并通过 `DataSourceConfig` 暴露 data-source configuration。
这些 workflow 是有用的 Product evidence，但旧 credential API、provider catalogue、
Agent runtime 和 persistence model 不是安全 migration boundary。

BYQ 当时从 process environment 接收 `DEEPSEEK_API_KEY` 和 `TUSHARE_TOKEN`。Gateway
model-settings response 只有 status，用户无法创建 personal model credential 或使 Agent
binding 生效；environment-only configuration 也无法提供经过审计的 Tushare credential
administrator CRUD。因此需要 database-backed store，但将可恢复 secret 放入 PostgreSQL
会引入 encryption、key rotation、authorization、runtime delivery、deletion 和
observability 决策，必须在 Phase 37 前闭合。

Browser、Gateway、MCP、DSH event stream、WorkflowTrace、audit record 和 application
log 绝不能收到 stored plaintext secret；同时 Adapter-owned model client 和 Backend-
owned Tushare provider 需要短暂使用 plaintext 认证 outbound provider call。

## 决策

### 1. Backend 持有单一 typed credential store

Backend 持有 PostgreSQL credential metadata 和 encrypted secret envelope record。初始
purpose 为：

- `model_api_key`，scope 为 `user` 或 `system`；
- `tushare_token`，scope 只能为 `system`。

每条 record 有稳定 BYQ identifier、purpose、provider key、scope、user-scoped owner
identity、display label、status、version、masked descriptor、encrypted envelope 和
created/updated/revoked audit metadata。准确 limit 和 public projection 定义于
`docs/contracts/credential-store.md`。

User-scoped credential 只对其 durable BYQ user owner 可见、可修改。System-scoped
credential 要求 authenticated `admin` role。Browser 只能通过 Gateway Product API route
访问。MCP 和 DSH 不获得 credential CRUD 或 resolution capability。

### 2. 使用 versioned AES-256-GCM envelope

Secret value 在 Backend application layer 使用 AES-256-GCM 加密。每次 write 使用新的
96-bit random nonce 和 active 256-bit deployment key。Authenticated additional data 将
ciphertext 绑定到 envelope version、credential id、purpose、provider、scope 和 owner，
防止 ciphertext 被移动到其他 record 或语义。

Deployment key 由 versioned environment key ring 提供，绝不存入 PostgreSQL，也不由
readiness endpoint 返回。Key ring 标识新 write 使用的 active key，并可保留 previous
key 进行 decrypt-and-rewrap rotation。Unknown key id、invalid tag、malformed envelope 或
unavailable key 均 fail closed。Plaintext 绝不 persistence、cache 到 disk、进入 exception
或 queue。

Normative envelope、key-ring variable、rotation procedure 和 startup behavior 属于
Credential Store Contract。有效 active key 可用前，production credential write 不可用；
env-only bootstrap 仍可运行，但不能静默降低 encryption。

### 3. Public read 只含 metadata，write 不回显 secret

Public Product API read 只返回准确 allow-listed metadata、`configured` 和有界 masked
descriptor，例如 `sk-…abcd`。绝不返回 ciphertext、nonce、tag、key id、plaintext、
environment value 或可逆 derivative。Descriptor 在 write 时计算，不能用于重建值。

Create/replacement request 只在 request body 接受 secret。Response 使用相同 metadata-
only projection。Secret omitted 的 metadata update 保留现有 encrypted value；替换 secret
会增加 credential version 并写新 nonce/envelope。相同 idempotency key 可 replay 先前
metadata response，但绝不 replay submitted request body。

Delete 是可审计 revoke：原子 disable active binding 并移除 encrypted envelope。Revoked
secret 不可读取或恢复。Create、replace、enable/disable、bind/unbind 和 revoke 均 append
audit event，包含 actor、owner/scope、credential id、action、request identity 和
timestamp，但不含 secret 或 credential-shaped payload。

### 4. Model profile、Agent binding 与 secret 分离

Model credential 用于认证 provider，本身不是 executable Agent configuration。BYQ 保存
owner-scoped model profile，引用 active credential，并只包含 allow-listed provider/model
catalogue key 和有界 generation option。Phase 37 不接受任意 user-supplied provider URL，
避免 runtime 变成 SSRF proxy。

Owner-scoped Agent binding 将 BYQ Agent preset id 映射到 model profile。只有 catalogue-
compatible active profile 可绑定。Revoke/disable credential 会使 dependent profile
unavailable、binding ineffective，不能 fallback 到其他 user 或 system credential。
Product API 可报告 effective source 和 availability，但绝不报告 secret。

### 5. 通过 private Backend-to-Adapter seam resolve model secret

Gateway 使用 authenticated owner 和 Agent/profile reference 启动 turn，绝不 fetch secret。
Runtime Adapter 从 Backend internal endpoint resolve effective binding；该 endpoint 由仅
Backend 与 Runtime Adapter 持有的 dedicated resolver service token 保护。Request 绑定
owner、Agent preset 和 session/turn identity。Backend authorizes binding，并将单一有界
resolution document 直接返回 Adapter。

该 internal response 是唯一允许包含 plaintext 的 API response。它不属于 Product API
或 OpenAPI，Browser、Gateway、MCP、DSH tool 均无法访问，且没有 generic credential-
list/read endpoint。Runtime Adapter 只在 memory 持有，并只把 model key 放入该 session
的 Adapter-owned SDK child environment。Session description、WorkflowTrace、error、
command argument、log 和 durable DSH session metadata 均排除它。Resolution failure 对
requested turn fail closed，不能静默使用其他 user key。

Phase 37 必须用 secret-boundary、owner-isolation、redaction 和 child-process-environment
test 证明该 seam。未来 external secret broker/KMS 可替换 internal resolution，而不改变
Product API。

### 6. Tushare resolution 留在 Backend 内

Backend-owned Tushare Adapter 在 provider call 时直接从 credential store resolve active
system `tushare_token`，不向 Gateway、MCP、DSH 或 Runtime Adapter 暴露 resolver route。
Data-source configuration 保持 Tushare-only；BaoStock、AKShare、Yahoo 和其他 Community
provider 保持 `DROP`。

### 7. Environment credential 是明确 bootstrap fallback

`DEEPSEEK_API_KEY` 和 `TUSHARE_TOKEN` 仅为 bootstrap/system compatibility fallback。
同一 purpose/provider 的有效 active database credential 优先。Environment value 不自动
import PostgreSQL，在 public projection 中只表示为不泄漏内容的 source/status flag。

Missing、disabled、revoked、corrupt 或 cross-owner user credential 没有 environment
fallback，防止 personal binding failure 意外消耗 system key。Bootstrap fallback usage
可在 secret-free audit/health metadata 中观察。

### 8. Phase ownership 消除 Phase 37/40 循环

Phase 37 持有 exit criteria 所需 model credential/profile/binding UI component 和 API
flow，以及 asset re-import 和 Agent Policy depth。Phase 40 可在后续 extract/generalize
已验证 shared component，但不是 Phase 37 prerequisite。Phase 39 复用该 Accepted store
处理 Tushare-only data-source workflow，不增加 provider。

## 后果

- Model/Tushare credential 持久、scoped、masked、auditable、rotatable，且不向 browser-
  facing Contract 暴露 secret。
- Backend 增加 credential/profile/binding record 和 narrow internal resolver；Runtime
  Adapter 增加 per-session resolution 和 in-memory child environment injection。
- Deployment 必须独立于 PostgreSQL provision/backup encryption key ring；仅有 database
  backup 无法 decrypt credential。
- Key loss 会按设计使受影响 credential 不可恢复，operator 必须替换。Invalid encryption
  state 只降低 credential-backed operation，不影响无关 Product read。
- Phase 37 无需等待 Phase 40，同时保持 one-phase-per-worktree gate。

## 必需实现证据

- encryption known-answer/round-trip 与 tamper/AAD/key-id failure test；
- key rotation/rewrap test，证明 old/active key behavior；
- owner/admin authorization、idempotency、optimistic-version、revoke、cascade 和
  append-only audit test；
- 证明 plaintext/envelope field 绝不出现的 Product API/OpenAPI test；
- 证明准确 binding resolution、无 cross-owner/fallback substitution、in-memory-only
  handling 和完整 redaction 的 Runtime Adapter test；
- 不含 live secret fixture 的 Tushare precedence/fallback test；
- Phase 37 Community feature checklist 和真实 Product API desktop/mobile Chrome MCP
  evidence。

## 拒绝的替代方案

- Environment-only credential 加 status UI：无法满足 durable CRUD、personal binding、
  rotation 或 audit。
- Plaintext 或 database-extension-only storage：向 database reader/backup 暴露 secret，
  或把 domain store 耦合到隐式 decryption role。
- Hash provider credential：outbound provider authentication 需要 original secret。
- 将 secret 返回 Gateway 再转发 Runtime Adapter：扩大 browser-facing process trust
  boundary，并产生 logging/error hazard。
- 为 MCP/DSH 提供 generic secret-read endpoint：违反 Agent-to-Domain boundary，并授予
  不必要 secret authority。
- 任意 user provider URL：产生 SSRF/exfiltration surface。
- Broken personal binding 自动 fallback 到 system key：隐藏 authorization/configuration
  failure，且可能使用错误 credential 计费。
- 复制 Community credential table、provider 或 Agent runtime：保留不兼容 trust 和
  provider assumption。

## 回滚

禁用 database-backed resolution 和 personal binding，revoke resolver service token，并
让受支持 system provider 恢复明确 environment bootstrap configuration。Revoked record
保留为 audit evidence；encrypted record 可保留一个有界 rollback window，或经 operator
确认后安全 purge。Product metadata endpoint 继续省略 secret。
