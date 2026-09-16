# H4 人工审查面（反馈 Hub / 发布者 / DSH 运行时回调）

2026-09-16，本地维护；Product Phase 97 不变。
审计检查器要求的 8 个人工面：Cloudflare 与本地反馈发布者、反馈中继、Central Hub 的
HTTP/cron/静态管理台/Durable Objects，以及 DSH 插件运行时回调。

## 面与源

| 面 | 代表源文件 | 说明 |
|---|---|---|
| cloudflare_publisher | `workers/feedback-publisher-cloudflare/src/index.ts` | Cloudflare 发布者；向 Hub D1 申请 `begin-create` 持久许可后最多一次 POST |
| local_publisher | `workers/feedback-publisher/publisher.py` | 本地高级发布者；向 Backend 申请持久许可 |
| feedback_relay | `workers/feedback-hub-relay/relay.py` | 反馈中继；原事件/租约与回执语义 |
| hub_http | `services/feedback-hub-cloudflare/src/index.ts` | Hub fetch 处理器；服务认证、来源校验、JSON 边界 |
| hub_cron | `services/feedback-hub-cloudflare/src/index.ts` | Hub 定时处理；cron 触发的发布/对账 |
| durable_objects | `services/feedback-hub-cloudflare/src/index.ts` | Installation/Feedback/AdminLogin Gate DO；原子once消费 |
| hub_admin_static | `services/feedback-hub-cloudflare/src/admin-console.ts` | 内联管理台静态资源；同源与 CSP 约束 |
| framework_middleware_callbacks | `plugins/dsh-byq/runtime/byq-continuation-budget.js` | DSH 插件运行时回调（预算）；配套 `byq-runtime-time-context.js` |

## 合同要点

- 两个发布者均为**最多一次自动创建**：先原子消费持久许可（Backend/Hub D1），租约失效不可开始创建；
  重复/丢失许可回复不再授予；目录恢复可完成原 Issue。这是 at-most-once，不是 exactly-once。
- Hub DO 以 sourceHash 命名做来源限流/登录门；管理台要求同源请求。
- DSH 运行时回调仅施加延续预算/时间上下文，通用执行与停止仍由 DSH 负责，领域事实归 Backend。
- 未注册在 Product API/MCP 的写路径一律不暴露给浏览器。

## 证据

- [PUBLISHER-CREATE-PERMIT](./PUBLISHER-CREATE-PERMIT.md)、`docs/operations/product-feedback-publisher.md`。
- `workers/feedback-publisher/tests/test_publisher.py`、`test_http_deadline.py`；
  `workers/feedback-hub-relay/tests/test_relay.py`；
  `deploy/feedback-hub-cloudflare/tests/hub.test.ts`、`publisher-http.test.ts`；
  `plugins/dsh-byq/runtime/byq-continuation-budget.test.js`。

## 限制

- `framework_middleware_callbacks` 的代表文件为解释性选择（DSH 插件运行时回调）；如需按其他文件聚合
  请维护者确认。
- 生产 Cloudflare 部署未执行；本批为源/测试/本地 workerd 证据。
- H5 完整研究仍待做；台账 `product_assets_import` 仍 `NEEDS_EVIDENCE`。
