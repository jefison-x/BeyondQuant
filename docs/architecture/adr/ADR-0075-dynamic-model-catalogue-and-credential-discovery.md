# ADR-0075：凭据驱动的动态模型目录与后台续接资格

- Status: Accepted
- Date: 2026-09-17
- Relates: ADR-0019（加密凭据）、ADR-0072（长研究检查点）
- Does not supersede any existing decision.

## Context

建模型档案时可选模型来自静态 `MODEL_CATALOG`（`services/backend/app/credentials.py`），
无法反映 provider 新增模型；运行时 `resolve_model()` 也只接受静态目录条目，新模型无法用于
前台对话或后台续接。维护者要求：新建模型档案应基于所选凭据**自动刷新可用模型**，并允许
新发现的可用模型参与后台续接/长研究。

## Decision

1. **凭据驱动发现**：Backend 新增 `GET /v1/users/model-credentials/{credential_id}/models`。
   仅对 owner-active、`purpose=model_api_key` 的凭据，用解密后的密钥调用**封闭 provider**
   的 OpenAI 兼容 `{base}/models`：
   - `deepseek` → `https://api.deepseek.com`
   - `opencode-go` → `https://opencode.ai/zen/go/v1`
   - `opencode-zen` → `https://opencode.ai/zen/v1`
   有界超时（8s）、结果上限 200、去重、失败闭合（503）；**密钥永不回显**，只用于该次出站调用。
2. **档案校验与解析**：档案的 `model` 必须属于该凭据的发现结果；`resolve_model()` 不再仅凭
   静态 `_CATALOG` 接受模型，而是接受“该 provider 已发现且凭据 active”的模型；静态目录保留为
   provider 不可达时的已知安全回退。
3. **后台续接资格**：`runtime.py` 不再硬编码单一 `deepseek-v4-flash`，而是允许**同一已验证
   provider** 下、凭据 active 且发现通过的模型；模型切换仍受既有绑定与 workspace 约束。
4. **边界不变**：Product 仅经 Product API；Backend 不经 Community；不引入新 SDK（复用 stdlib
   HTTP）；不记录或转发明文密钥；未知 provider/失败一律闭合，不静默回退到任意模型。

## Consequences

- 新模型（如 DeepSeek V4.1 Flash）无需改代码即可在建档案时出现并可用于续接（发现接口返回）。
- 需要在 Product API/前端提供“选中凭据→刷新模型”；档案创建在 provider 不可达时使用静态回退子集。
- 移除对单一模型的硬编码后，续接资格依赖 provider+凭据活性，而不是模型白名单；相应测试需覆盖
  拒绝未知 provider、拒绝非 active 凭据与发现失败。

## Migration / rollback

无数据迁移。静态目录与现有已建档案继续有效；发现接口为增量。若需回退，恢复 `resolve_model`
的静态目录校验即可，不影响既有档案与绑定。
