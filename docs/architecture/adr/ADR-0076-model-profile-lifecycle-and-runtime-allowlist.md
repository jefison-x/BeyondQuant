# ADR-0076：模型档案生命周期与运行时模型白名单

- Status: Accepted
- Date: 2026-09-17
- Relates: ADR-0019（加密凭据）、ADR-0075（凭据驱动动态模型目录）
- Amends: ADR-0075 的运行时候选边界；不改变其凭据发现与静态回退结论。

## Context

Phase 101 引入凭据驱动发现后，`discover_models` 仅凭前缀启发式
`_runtime_provider_for` 判定 `supported=true`：任何 `deepseek-*` 都被映射到
`opencode-go-chat`。但 DSH/pi-ai 运行时只接受
`plugins/dsh-byq/compositions/byq-product-sdk.cordis.yml`（以及
`plugins/dsh-byq/profiles/` 下版本化 profile）中显式的 per-provider 模型白名单。
用户选择未在白名单中的 `deepseek-v4.1-flash`（`opencode-go-chat`）后，
`create_session` 被运行时拒绝并返回 503，前端显示“product model is unavailable”。

同时，档案删除为软删除（`status='deleted'`），但 `list_profiles` 返回全部状态、
前端仍显示删除按钮，导致“已删除”档案看似残留。维护者要求档案生命周期采用
`active ⇄ disabled`，并保持既有 `deleted` 终态完全兼容。

## Decision

1. **运行时白名单是权威边界**：Backend 维护 `RUNTIME_MODEL_ALLOWLIST`（模块级常量，
   `services/backend/app/credentials.py`），逐条镜像 DSH composition 的
   `providers.<runtime>.models`。`deepseek-official` 无显式 composition 模型列表，
   其白名单为静态 `MODEL_CATALOG` 中 `provider=deepseek` 的模型。
   - `discover_models` 仅在模型 id 属于该 runtime provider 白名单时置
     `supported=true`；前缀仍用于选择 runtime 路由，但不再单独决定支持与否。
   - `create_profile` 对“已发现但不在白名单”的模型**失败闭合**；静态目录行为不变。
   - 白名单漂移由 `services/backend/tests/test_credentials.py` 的 drift 测试解析
     composition 与版本化 profile 并断言逐项相等，任何 composition 变更都会使 CI 失败。
2. **档案生命周期 `active ⇄ disabled`，`deleted` 为 legacy 终态**：
   - 新增 `disable_profile`：`active → disabled`，自动解绑指向它的
     `agent_model_bindings`，版本 +1。
   - 新增 `enable_profile`：`disabled → active`，版本 +1，**不自动重新绑定**。
   - 不引入硬删除；`deleted` 行继续可见且有效，旧删除操作/路由/回执保持兼容，
     `deleted` 档案不可被启用或停用。
   - 两个转换均幂等（同一 `expected_version` 经回执核对）、owner-scoped、
     使用 `expected_version` 乐观并发，并写入审计 + 幂等回执。
3. **绑定仅接受 `active` 档案**：`bind` 严格要求档案与凭据均为 `active`。
4. **新增 additive 回执表**：新建 `model_profile_status_receipts`，
   `CHECK(operation IN ('disable_profile','enable_profile'))`，
   PK `(owner_principal, operation, resource_id, expected_version)`，
   并加入 `SCHEMA_DDL`。**不修改**既有 `model_command_receipts` 的 CHECK 约束，
   避免 DB 约束迁移。
5. **边界不变**：浏览器仅经 Gateway/Product API；Backend 不回显密钥；
   `list_profiles` 继续返回全部状态并在 `_public_profile` 暴露 `status`。

## Consequences

- 选择运行时未配置的模型在发现/建档案阶段即被拒绝，不再产生 503 会话失败。
- 组合文件新增/移除模型时，若 Backend 白名单未同步，drift 测试失败，避免静默漂移。
- 档案停用会自动解除 Agent 绑定；重新启用不会隐式恢复绑定，需用户显式操作。
- 追加回执表是纯 additive 变更，无需迁移既有 `model_command_receipts` 约束或历史行。

## Migration / rollback

无数据迁移。`deleted` 行、旧删除路由与既有回执继续有效；`disabled` 为新增中间态。
回滚可移除新路由/前端动作与新回执表，并将发现白名单校验回退为前缀启发式，
不影响既有档案与绑定。
