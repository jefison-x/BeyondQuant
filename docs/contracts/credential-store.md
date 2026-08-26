# Credential Store Contract

ADR-0019 定义 authority boundary。本文固定初始 storage、public projection、encryption、resolution 和 lifecycle contract。

## Credential identity 与 scope

一个 credential 包含：

- `credential_id`：`cred_` 加 32 个小写十六进制字符；
- `purpose`：`model_api_key` 或 `tushare_token`；
- `provider`：经评审的 BYQ catalogue key；
- `scope`：`user` 或 `system`；
- `owner_user_id`：`user` 时必填，`system` 时为 null；
- `label`：1–120 个显示字符；
- `status`：`active`、`disabled` 或 `revoked`；
- 正数 `version`；
- created/updated timestamps 和 actor identifiers。

`tushare_token` 为 system-scoped。Phase 37 model provider/model values 来自 BYQ runtime catalogue；拒绝任意 base URLs。

## Public projection

Credential 读取和 mutation response 只包含：

```json
{
  "credential_id": "cred_0123456789abcdef0123456789abcdef",
  "purpose": "model_api_key",
  "provider": "deepseek",
  "scope": "user",
  "label": "研究模型",
  "status": "active",
  "configured": true,
  "masked": "sk-…cdef",
  "version": 1,
  "created_at": "2026-08-22T00:00:00+00:00",
  "updated_at": "2026-08-22T00:00:00+00:00"
}
```

其中永不包含 `secret`、`api_key`、`token`、`plaintext`、`ciphertext`、`nonce`、`tag`、`key`、`key_id` 或 `envelope` 字段。创建/替换时空 secret 无效；secret input 上限 16 KiB。Mask 最多暴露经评审的 provider prefix 和末尾四个字符；太短时显示 `configured`。

## Encryption envelope

存储的 envelope 逻辑结构为：

```text
version = credential-envelope.v1
algorithm = AES-256-GCM
key_id = deployment key identifier
nonce = 12 random bytes
ciphertext_and_tag = AESGCM.encrypt(key, nonce, utf8(secret), aad)
```

AAD 是以下内容的 canonical UTF-8 编码：

```text
credential-envelope.v1\n<credential_id>\n<purpose>\n<provider>\n<scope>\n<owner-or-system>
```

Deployment 提供：

- `BYQ_CREDENTIAL_KEYRING`：将有界 key ids 映射到 base64url 编码、无 padding 的 32-byte keys 的 JSON object；
- `BYQ_CREDENTIAL_ACTIVE_KEY_ID`：新写入使用的 member。

Malformed JSON、重复/无效 ids、错误 key length、缺少 active id、未知 envelope version/key id 或 authentication failure 都会使 credential writes/resolution 不可用，绝不回退到 plaintext。

Rotation 添加新 key、设为 active、以 optimistic version checks 分批 rewrap active credentials、验证后才移除未使用旧 key。Rotation 写 audit events，但不写 secret/envelope material。Key-ring values 不写日志，也不由 health APIs 暴露。

## Lifecycle 与 concurrency

- Create 需要 secret 和 idempotency key。
- Metadata update 使用预期 `version`；省略 secret 时保留 envelope。
- Secret replacement 使用预期 `version` 和新 nonce，并递增 version。
- Disable 保留 envelope，但阻止 resolution。
- Revoke 原子禁用 dependent bindings 并清除 envelope。
- Revoked credentials 不能 enable 或 resolve。

Audit entries 仅追加，记录 action、credential id、scope、owner、actor、request/idempotency identity、prior/new version、outcome 和 timestamp；不包含 submitted secret、mask fragments、model prompt、provider response 或 encryption material。

## Model profile 与 binding

Owner-scoped model profile 引用一个 owner 可见且 active 的 `model_api_key`、一对 provider/model catalogue 值及有界 generation options。Binding 以 optimistic versioning 将 `(owner_user_id, agent_preset_id)` 映射到一个 profile。Cross-owner references 和 provider/model/credential mismatches 均 fail closed。

Gateway 可把 owner、Agent preset、selected profile 和 session/turn ids 传给 Runtime Adapter，但永不接收 resolution output。Runtime Adapter 只以 resolver service token 调用专用 internal resolve operation。单一用途 response 包含 provider/model runtime fields 和 plaintext key；adapter 不得在 owned session 之外缓存，也不得写入 durable session record。

`BYQ_CREDENTIAL_RESOLVER_TOKEN` 是仅注入 Backend 和 Runtime Adapter 的独立高熵 service secret；不得复用为 `BYQ_MCP_TOKEN`、`BYQ_PRODUCT_TOKEN`、browser session 或 encryption key。缺失/无效 resolver authentication 返回规范化 denial，不尝试 lookup。

## Environment fallback

`DEEPSEEK_API_KEY` 和 `TUSHARE_TOKEN` 仅为 system bootstrap fallback。Active database system credential 优先。选定 user binding 后，绝不回退到 environment/system credential。Environment values 不自动导入，其 mask 也不用于 public response。

## Failure 与 redaction

包含 secret 的 request bodies 和 internal resolution responses 必须在 HTTP/log/trace instrumentation 前 redact。Provider authentication errors 经过规范化，不含 provider body 或 submitted credential。以下 consumers 永不接收 plaintext/envelope data：

- browser 和 Product API clients；
- Gateway；
- MCP 和 DSH tools/events；
- WorkflowTrace 和 business audit projections；
- exception messages、metrics labels、logs、fixtures 和 exported assets。
