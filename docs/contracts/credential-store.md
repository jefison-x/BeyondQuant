# Credential Store Contract

当前权限边界以 ADR-0088 Clean Break baseline 及适用的 Accepted Clean Break ADR 为准；ADR-0019 仅作历史来源，并在与当前架构冲突时不适用。本文固定 CredentialStore 的 storage、public projection、encryption、resolution 和 lifecycle contract。

## Credential identity 与 scope

一个 credential 包含：

- `credential_id`：`cred_` 加 32 个小写十六进制字符；
- `purpose`：`model_api_key`、`web_search_api_key` 或 `tushare_token`；
- `provider`：经评审的 BYQ catalogue key；
- `scope`：`user` 或 `system`；
- `owner_user_id`：`user` 时必填，`system` 时为 null；
- `label`：1–120 个显示字符；
- `status`：`active`、`disabled` 或 `revoked`；
- 正数 `version`；
- created/updated timestamps 和 actor identifiers。

`tushare_token` 为 system-scoped。`web_search_api_key` 是独立的 user-scoped 搜索凭据，目前只允许 `deepseek` provider；同一 owner 最多有一条未撤销记录（active 或 disabled）。撤销记录保留为历史，不再是当前候选。Model provider/model values 来自 BYQ runtime catalogue；拒绝任意 base URLs。受审核的 user-scoped model credential providers 为 `deepseek`、`opencode-go` 和 `opencode-zen`。

搜索凭据与模型凭据用途分离：它不参与模型发现、profile、binding 或模型 `configured` 计数。Product `/user/models` 设置面可单独查看和提交搜索凭据；公共读取与写入回执只返回脱敏 metadata。搜索服务没有配置时，普通对话可继续，但不会从模型凭据、系统凭据、Engineering 配置或环境变量回退取得搜索 Key。多个未撤销搜索记录属于状态冲突，必须失败关闭，不能按时间选择其中一条。

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

OpenCode Go/Zen 的 provider family 只用于 credential/profile ownership。Backend 从固定 catalogue 解析为六个 DSH runtime routes：每个 gateway 分别使用 `openai-responses`、`openai-completions` 和 `anthropic-messages`。固定根端点为 `https://opencode.ai/zen/go/v1` 与 `https://opencode.ai/zen/v1`；浏览器、profile payload 和 credential payload 均不能覆盖端点、协议或 runtime route。同一 provider family 的 credential 可用于其三个受审核 route，并只以 `OPENCODE_API_KEY` 注入当前 owned SDK child environment。

`BYQ_CREDENTIAL_RESOLVER_TOKEN` 是仅注入 Backend 和 Runtime Adapter 的独立高熵 service secret；不得复用为 `BYQ_MCP_TOKEN`、`BYQ_PRODUCT_TOKEN`、browser session 或 encryption key。缺失/无效 resolver authentication 返回规范化 denial，不尝试 lookup。

## Resolver 与环境配置边界

普通模型 credential resolver 仅处理 `model_api_key`。搜索凭据使用独立的私有 resolver operation，并固定解析当前 owner 的 `web_search_api_key`、`deepseek`、`user` 记录；其 service authentication 和 owner/session/trace 校验不得弱化。明文只送给可信 Runtime Adapter，不能进入 Gateway、浏览器、MCP/DSH payload、持久 session、receipt、日志或异常。

普通 ACP Go 或官方 DeepSeek root 在真正创建每个新 DSH 子进程前重新解析当前 owner 独立存储的搜索凭据。旧进程必须先经过已有关闭/退出确认门；同一 native session 可复用历史和 cwd，但下一 root 使用新进程和最新 credential snapshot。正在执行的 root 仍可能持有启动时的旧 snapshot，因此修改 BYQ 配置不等同于立即撤销正在进行的 provider 请求；需要立即失效时，应在 provider 侧撤销旧 Key。F6 不执行搜索凭据 lookup 或注入。当前 root 的取消/轮换与原生搜索调用的即时撤销仍是开放边界，本文不据此声称已证明立即撤销。

ADR-0111 的 native web-search 配额仍是 OPEN：上游要求每个请求的 `maxTokens` 与 `maxUses` 为正整数。移除 BYQ 对上游默认值的覆盖只会恢复上游 defaults，不能证明这些默认值无限，也不能证明会话累计使用不受限。此凭据切片不修改 SDK、不引入大整数，也不据此声称搜索配额或使用结算已经完成。

`DEEPSEEK_API_KEY`、`OPENCODE_API_KEY` 及 `TUSHARE_TOKEN` 的既有环境/bootstrap 配置路径仍存在。特别是普通 ACP Go 模型路由当前仍从其模型配置路径构造 `OPENCODE_API_KEY` 子进程环境；旧的“OpenCode 不提供 environment fallback”表述不代表此现实路径已经迁移。选定 user model binding 后，仍不得回退到环境/system model credential。搜索 Key 不得从模型或 system 值回退，也不得复制 Go 模型 Key 到搜索变量。按 Accepted ADR-0115，仅分别解析的官方 DeepSeek 模型凭据与搜索凭据允许值相同；Go 模型、MCP discovery/signing、resolver 及其他内部凭据仍须与搜索凭据区分。

维护者已明确：未来应废除仅针对“模型 API Key”的系统 `.env` 配置，改由前端和加密 CredentialStore 管理模型凭据。该模型 Key 迁移尚未完成；本搜索凭据切片不删除当前 Go 模型配置路径，也不等同于完成该迁移。其他启动和业务环境设置不在这项 future requirement 范围内。Environment values 不自动导入，其 mask 也不用于 public response。

## Failure 与 redaction

包含 secret 的 request bodies 和 internal resolution responses 必须在 HTTP/log/trace instrumentation 前 redact。Provider authentication errors 经过规范化，不含 provider body 或 submitted credential。以下 consumers 永不接收 plaintext/envelope data：

- browser 和 Product API clients；
- Gateway；
- MCP 和 DSH tools/events；
- WorkflowTrace 和 business audit projections；
- exception messages、metrics labels、logs、fixtures 和 exported assets。

## 模型配置原命令回执

模型绑定及档案删除在业务事务内追加 `model_command_receipts`，以 owner、闭合 operation、
资源 ID 和原 expected_version 为唯一命令身份，记录目标 profile、actor、提交版本与删除触发的解绑版本。
只读核对还必须匹配目标 profile。保留版本冲突规则，不因重试自动采用新版本。回执失败必须回滚
业务写入及解绑；过去没有此记录的操作不从当前状态补造回执。Product 页面写前保存无密钥的原命令，
按原身份只读恢复；MCP/DSH 不增加模型配置写权限。
