# Phase 101 Verification Evidence

Phase 101（Credential-driven dynamic model catalogue and continuation qualification）实现并验收完成：
建档案按凭据自动刷新 provider 可用模型，新发现模型可用于后台续接，浏览器只经 Gateway/Product API。

依据 [ADR-0075](../../architecture/adr/ADR-0075-dynamic-model-catalogue-and-credential-discovery.md) 与
[IMPLEMENTATION_PLAN Phase 101](../../roadmap/IMPLEMENTATION_PLAN.md)。切片 PR：#287、#288（P101-A）、#289（P101-B）、
#290（P101-C）、#291（P101-D）。

从合并后的 `origin/main` 工作树验证：

- Backend 凭据/发现测试通过：`services/backend/tests/test_credentials.py`（12 passed，真实隔离 PostgreSQL）。
- Gateway Product API 测试通过：路由转发、无密钥回显、路由一致性（`tests/architecture` 路由对齐通过）。
- 前端生产构建通过；Vitest 211 passed（含发现客户端用例）。
- 真实浏览器（Playwright 管理 Chromium）经 真实前端 → Gateway → Backend → 独立 PostgreSQL，
  无任何路由 mock：真实 DeepSeek 凭据发现返回 200 且列出 `deepseek-flash`、`deepseek-v4-pro`；
  不可用凭据发现闭合失败并保留已审阅静态目录。见 [browser review](BROWSER_REVIEW.md) 与
  [feature checklist](FEATURE_CHECKLIST.md)。
- 验证未改动 Community、生产库或生产凭据；验证凭据写入隔离 `byq_domain_test`。

## 特性检查与剩余

- [x] 选择凭据后自动按该凭据刷新 provider 模型列表（经 Product API）。
- [x] `刷新模型` 按钮可手动重新拉取并提示结果。
- [x] 只有 `supported`（可映射传输族）模型进入可选列表；未映射模型不出现。
- [x] 凭据不可用时发现闭合失败，已审阅静态目录保留为回退。
- [x] 响应不返回密钥或密文；浏览器只经 Gateway/Product API，无跨源请求、无 5xx。
- [x] 后台续接资格放宽为封闭 provider 路由（deepseek-official 与六个 opencode 路由）。
- [ ] 真实覆盖度量（Phase 100）与 HIST 概念时点可见性仍另行跟踪。
