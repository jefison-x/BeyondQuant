# ADR-0053：Cloudflare 原生中央 Feedback Hub

- Status: Accepted
- Date: 2026-09-05
- Accepted: 2026-09-05
- Decision scope: Phase 93 中央 Feedback Hub 的无服务器部署、持久化、调度和 GitHub publisher 隔离
- Related: ADR-0015、ADR-0049、ADR-0051、ADR-0052

## 背景

Phase 92 交付的中央 Hub 使用常驻 FastAPI、独立 PostgreSQL 和 publisher 容器。其协议和安全边界满足匿名开源反馈，
但要求维护者长期运行主机、数据库、TLS 代理和三个容器。维护者明确选择 Cloudflare Workers 免费计划作为官方中央入口，
以降低一次性安装和持续运维成本。官方中央容器尚未配置或承载生产反馈，因此本阶段没有中央业务数据迁移；正式 BYQ 中正在
运行的 `feedback-hub-relay` 是本地出站 relay，不是要移除的中央服务。

2026-09-05 核验的 Cloudflare 官方能力包括 Workers、D1、SQLite Durable Objects、Queues/DLQ、Service Bindings、Cron、
WebCrypto、Workers Secrets 和本地 workerd/Vitest。Workers Free 当前足以承载早期反馈量，但免费额度是故障边界而不是 SLO；
本地 BYQ outbox 和中央 D1 outbox 必须保证超限或平台故障时不丢记录。

Community 只读检查结论与 Phase 92 相同：它只有 Issue template、敏感信息提示、全局审批 UX 和离开产品到 GitHub 的路径，
没有中央匿名 intake、Cloudflare、D1、Queue 或 publisher 实现。模板语义继续为 `PORT_TESTS`/`PORT_UX`，中央实现为
`REPLACE`；未复制 Community 源码、运行时、数据库或 Git history。

## 决策

1. ADR-0052 的公开合同保持不变：local relay 继续调用 `POST /v1/intake` 和 capability-token `GET /v1/status/{receipt}`；
   request/receipt/status schema、双层隐私校验、每 installation 每小时五次、中央审核和固定仓库语义不变。普通用户和小巴
   不感知 Cloudflare，也不新增配置。
2. 官方 Hub 改为 TypeScript module Worker。D1 持有中央 feedback、audit、publication mapping 和 transactional outbox；
   不使用 KV 作为权威状态。每个匿名 installation hash 路由到独立 SQLite Durable Object，串行限流与 event reservation；
   每个 receipt 路由到独立 Durable Object，串行审核和 publisher lease/result mutation。不得使用单一全局 Durable Object。
3. `accept` 在同一个 D1 batch 中更新审核状态并写 outbox。Cron dispatcher 只以 compare-and-set claim 到期 outbox，再向
   Queue 写稳定 event ID；Queue 不是权威记录。发送与 D1 更新之间崩溃可以产生重复 queue delivery，但不能丢失 outbox。
   `dispatching`/`enqueued` 超时记录会重新投递，以覆盖免费 Queue 的短保留期。
4. GitHub writer 是第二个、不可公开访问的 Queue Consumer Worker。它不绑定 D1、Durable Object、Product Backend、源码、
   Git、Docker、DSH 或任意 repository；只持有固定 `jefison-x/BeyondQuant` GitHub App secret，并通过 Service Binding 加共享
   publisher token 向 Hub claim/complete/retry。Hub Worker 不持有 GitHub App ID、installation ID 或 private key。
5. Publisher 在每次 create 前按稳定 marker 有界 reconciliation；GitHub App JWT 使用 Workers WebCrypto。只允许
   `api.github.com/app/installations/{fixed-id}/access_tokens` 和固定仓库 Issues list/create；不实现 Contents、Pull requests、
   Actions、comment、close、label、assignee、milestone、任意 origin 或任意 repository。
6. Queue delivery 使用显式 ack/retry、最多六次 platform retry 和 DLQ；领域 retry/terminal 状态继续由 D1 outbox 决定。
   GitHub 或 Hub callback 不确定时绝不盲目创建第二个 Issue。DLQ 过期不能删除 D1 outbox；dispatcher/reconciliation 可恢复。
7. Hub secret 为 status HMAC、admin bearer 和 publisher service token；Publisher secret 为同一 service token、GitHub App ID、
   installation ID 和 private key。secret 只通过 `wrangler secret put` 配置，不进入 JSON、D1、日志、test fixture 或 Git。
   `/v1/admin/*` 仍验证 admin bearer，并要求 operator 在自定义域名上叠加 Cloudflare Access；`/internal/*` 不作为产品 API。
8. Cloudflare Workers 是唯一官方中央实现。删除未启用的 FastAPI/PostgreSQL 中央容器包，避免维护两套状态机。Phase 89 的
   local direct publisher 保留为高级 self-hosted 兼容出口；它不得与官方 Hub 同时指向相同反馈事件。
9. Wrangler、Workers types、Vitest 和 Cloudflare 测试插件精确锁版本。CI 必须在真实 workerd/D1/Durable Object/Queue 模拟器
   中执行 migration/contract tests并对两个 Worker 做 `wrangler deploy --dry-run`；required CI 不登录 Cloudflare、不上传、
   不创建真实 GitHub Issue。

## 验收

- 现有 Python relay 测试和同一 intake/status wire contract 继续通过；
- workerd 测试覆盖 envelope/hash/secret/PII 拒绝、HMAC receipt、幂等、每 installation 限流、admin auth、审核、D1 outbox、
  Queue dispatch、lease/fence、固定 Issue mapping 和本地 fake GitHub；
- architecture test 证明 Hub bundle 无 GitHub private key，Publisher 无 D1/PostgreSQL/Product/DSH/Git/source/Docker 权限和
  arbitrary GitHub route；
- 两个 Wrangler bundle 均可 dry-run，D1 migration 可在本地应用，部署文档可从全新 Cloudflare account 顺序执行；
- 正式 BYQ Compose、PostgreSQL 卷、Frontend/Gateway/MCP/DSH 和小巴流程不因中央实现替换而重建或变更。

## 拒绝的替代方案

- Pages Functions：Cloudflare 对新 full-stack 项目推荐 Workers，Pages 不改善状态/Queue/DO 部署边界。
- 原样运行 FastAPI：Python Workers 支持 FastAPI，但现有 SQLAlchemy/psycopg/PostgreSQL 锁语义无法原样连接 D1，并会保留
  两套 persistence abstraction。
- 一个 Worker 同时 intake 和持有 GitHub private key：扩大公开入口的 credential blast radius，违反 ADR-0049。
- D1 update 后直接 Queue send：两个系统间没有原子提交，崩溃会丢失已接受任务。
- 只用 Queue、KV 或内存保存反馈：免费额度、保留期、eventual consistency 或 isolate eviction 会丢失权威状态。
- 单一 Durable Object 串行全部安装：形成全局吞吐瓶颈。

## 回滚与迁移

未切换正式 Hub URL 前，回滚只需不部署 Cloudflare Worker；本地 outbox 保持等待。切换后应先清空发行配置中的 Hub URL 停止
新 intake，再停止 Queue Consumer，导出 D1 并保留 Worker secret，不能删除 receipt、outbox 或已创建 Issue。若确需恢复旧
容器实现，必须先制定 D1 到 PostgreSQL 的逻辑导出/校验/导入方案并保证单一 writer；不得同时运行两套中央审核或 publisher。

## 官方参考

- [Workers pricing and Free limits](https://developers.cloudflare.com/workers/platform/pricing/)
- [D1 pricing and limits](https://developers.cloudflare.com/d1/platform/pricing/)
- [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/)
- [Queues pricing and Free plan](https://developers.cloudflare.com/queues/platform/pricing/)
- [Pages Functions migration to Workers](https://developers.cloudflare.com/pages/functions/migrate-to-workers/)
