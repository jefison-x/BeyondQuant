# ADR-0036：OpenCode Go/Zen 模型 Provider

- Status: Accepted
- Date: 2026-08-28
- Accepted: 2026-08-28
- Decision scope: personal model provider extension
- Related: ADR-0003、ADR-0019

## 背景

个人模型设置当前只允许 DeepSeek。用户需要使用已有 OpenCode Go key，并希望同时具备
OpenCode Zen 适配。OpenCode 官方 Go/Zen catalogue 混合使用 OpenAI Responses、
OpenAI-compatible Chat Completions 和 Anthropic Messages，不能通过修改 DeepSeek Base URL
获得正确且可审计的语义。

只读检查 Community `UserModelSettingsPanel.vue` 后，保留 provider-first 选择以及
credential/profile/binding 分层 UX；任意 Base URL、自由模型 ID、local provider、Community
API/数据库/runtime 均不迁移。DSH 官方 `@deepseek-ai/dsh-llm-pi-ai@0.1.1-rc.1` 与项目
当前 DSH contract 精确匹配，并正式支持上述三类可完整声明的协议。

## 决策

1. 新增 `opencode-go` 和 `opencode-zen` credential provider family。密钥仍使用现有
   AES-256-GCM write-only store、owner scope、profile 和 Agent binding；不新增 secret store。
2. Backend catalogue 把 provider/model 解析为六条固定 DSH route：Go/Zen 各自拆分
   Responses、Chat Completions、Messages。runtime route、protocol 和 endpoint 永不由浏览器
   输入。
3. 固定使用 OpenCode 官方根端点 `https://opencode.ai/zen/go/v1` 与
   `https://opencode.ai/zen/v1`。首版只开放经评审的常用 text/tool 模型；同协议扩容仍需
   catalogue review。Gemini 专用 Google protocol 不在本次范围。
4. Runtime Adapter 只对六条受审核 route 将当前 session resolution 的 key 注入 owned DSH
   child 的 `OPENCODE_API_KEY`。未知 runtime provider fail closed；key 不进入 Gateway、MCP、
   WorkflowTrace、readiness、durable session、日志或异常。
5. Provider 执行复用官方 DSH pi-ai plugin，不修改或 fork DSH，不建立第二 generic harness，
   Agent-to-Domain 调用仍全部经过 BeyondQuant MCP。

## 验收

- Backend 拒绝未评审 provider、跨 provider credential/profile 组合和自由 model ID；catalogue
  public projection 不暴露 DSH runtime route 或 endpoint。
- 六条 route 均由精确锁定的 DSH plugin 加载，并共享 provider family 的当前用户 key。
- Runtime tests 证明 key 只进入 `OPENCODE_API_KEY`，未知 route 无法接收 secret。
- Product API 与前端可选择 DeepSeek、OpenCode Go、OpenCode Zen，模型列表随 credential
  provider 收敛；浏览器网络只访问 same-origin Product API。
- Backend、Gateway、Runtime、Frontend tests/build 和 Chrome browser review 通过。

## 非目标

- 任意 OpenAI-compatible Base URL、OpenRouter、自托管或 local provider；
- OpenCode 模型自动发现后直接加入可执行 catalogue；
- Gemini Google protocol、OAuth、模型计费/配额管理或对 provider 隐私政策作 BYQ 保证；
- 把 OpenCode key 写入部署环境或作为 system fallback。

## Acceptance record

用户于 2026-08-28 明确要求先实现 OpenCode Go/Zen 适配并使用其个人 Go key；该授权接受
本 ADR 的固定端点、个人 write-only credential 和官方 DSH provider 方案。
