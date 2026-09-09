# Post-U8 全接口审计：首批反馈发布核对

日期：2026-09-09。状态：IN_PROGRESS。Product Phase 97、DSH 0.1.2rc1 不变。
维护者授权开始剩余整改；本批为独立 `codex/post-u8-interface-audit` 工作树。
Community 检查长期豁免见 [ADR-0068](../../architecture/adr/ADR-0068-post-u8-community-inspection-waiver.md)。
本批没有生产操作、真实 GitHub 投递或付费模型调用。

## 源清单及尚未闭合范围

[SOURCE-INVENTORY.json](SOURCE-INVENTORY.json) 由现有只读枚举器生成，逐项保留源位置，
并人工补入 Product `/api/product` 与 auth `/api/auth` router 前缀。
基线包含 434 个 Python route、81 个 MCP tool、4 个 worker.py 入口，共519项。
Gateway 180、Backend 238、Runtime Adapter 14、Signal Sandbox 2。
每项仍为 NEEDS_EVIDENCE；该数量不是验证通过数量，不包含下表补充 surface。

| 自动枚举遗漏的 surface | 代码定位 | 人工发现范围；审计状态 |
|---|---|---|
| MCP HTTP transport | `services/mcp/src/server.ts` | healthz、MCP_PATH 请求及 session transport；NEEDS_EVIDENCE |
| 本地反馈 relay | `workers/feedback-hub-relay/relay.py` | run、HTTP health；outbox claim/delivery/status；NEEDS_EVIDENCE |
| 本地兼容 publisher | `workers/feedback-publisher/publisher.py` | run、HTTP health、GitHub reconcile/create、Backend complete/retry；分页缺陷见F2-PUB-01 |
| Cloudflare Hub HTTP | `services/feedback-hub-cloudflare/src/index.ts` route | healthz、intake、status/{receipt}、admin/session POST/GET/DELETE、admin/feedback GET、triage/accept/reject/duplicate POST、publisher heartbeat/claim/complete/retry；NEEDS_EVIDENCE |
| 管理控制台静态路径 | `services/feedback-hub-cloudflare/src/admin-console.ts` | /admin、/admin/、app.css、app.js；NEEDS_EVIDENCE |
| Durable Objects | `services/feedback-hub-cloudflare/src/index.ts` | AdminLoginGate fetch/alarm、InstallationGate fetch、FeedbackGate fetch→moderate/claim/complete/retry；NEEDS_EVIDENCE |
| Hub Cron | `services/feedback-hub-cloudflare/src/index.ts` scheduled | dispatchDue/outbox→Queue；NEEDS_EVIDENCE |
| Cloudflare publisher | `workers/feedback-publisher-cloudflare/src/index.ts` | fetch health、queue→claim→reconcile/create→complete/retry/ack；分页缺陷见F2-PUB-01 |

检查到 Gateway 显式 include_router(product_router/auth_router)，未发现 Python mount、
add_api_route 或 api_route 动态注册；不能据此关闭 Gateway handler 到 Backend 的逐项映射。
框架自动 OpenAPI/docs、middleware、通知和内部回调仍需逐项适用性核查。
后续台账须逐项补 owner、读写/同步异步、授权、幂等、超时、错误、重试、权威状态、恢复、
下游及测试证据；本文件不声称已完成全接口审计。

## F2-PUB-01：第一页未匹配就重复发布

状态：CONFIRMED_DEFECT → LOCAL_VERIFIED；完整隔离CI与清理已通过。
两发布器原先仅请求 `state=all&per_page=100&page=1`，没有匹配则直接 POST。
首次 GitHub 创建已成功但回执丢失、原 Issue 移到后续页时，存在再次创建路径。
本轮合成失败测试证明代码路径，不宣称查实了生产重复 Issue。

领域不变量来自 ADR-0049/0053：未知结果先按固定事件 marker 查询，部分列表未匹配不能证明不存在；
保持独立发布器唯一 writer 和固定仓库。修复最多查询5页，每页100条；遇到短页才能判定该次
有界扫描完成。跨页重复 marker 报 reconciliation_conflict；后页失败、畸形结果或5页全满均
沿已有 provider_unavailable/retry 持久记录，不创建替代 Issue，不清空原 outbox。

限制：500条全满会阻止自动发布，进入现有有界重试/人工处理；不会无限分页或默默丢弃反馈。
这是修复不完整分页的最小安全切片，不是外部平台 exactly-once 保证：并发移动分页、搜索/列表
可见性延迟、lease过期后 writer 是否仍可创建等仍为 NEEDS_EVIDENCE，必须另行故障验收。
未新增服务、队列、数据库字段或 GitHub 权限；不启用可选本地 publisher。

## 其他非ML检查发现及下一批

| 路径 | 当前结论 | 下一步 |
|---|---|---|
| ResearchTask/Experiment/Artifact创建 | MCP未知分类存在，读取要求最终ID；未见原key的通用只读核对入口 | F2：按各自owner/task语义设计精确读取与持久核对；禁止列表推断或重放写入 |
| Backtest提交 | 原key持久化于Backend，MCP get仍要求job ID | F2：原key/task只读核对、迟到提交/并发/重启证据 |
| Factor compute | 计算在Artifact幂等检查之前，路由未显式接收Request/调用可信上下文校验 | NEEDS_EVIDENCE：先核对middleware/角色/owner全链与失败回归，不能仅凭路由签名断言生产越权 |
| Signal snapshot导入 | 路由未接收可信Request；直接调用可选trusted_owner的Artifact写入 | NEEDS_EVIDENCE：补缺身份/跨owner的真实API失败回归，核对既有keyless fixture与生产入口边界 |
| ML训练 | 已有持久watch和既有Worker核对 | 保留历史已通过切片，完整研究目标闭环仍待验收 |

## 本地组件证据

修复前：Python 4项失败；Cloudflare 4项失败、1项正例通过（其余14项未选）。
修复后：Python完整10项通过；Cloudflare workerd完整19项通过，类型检查、4项部署脚本测试、
部署合同及两个Worker dry-run通过。测试仅假GitHub/本地服务；没有部署。
一次npm命令误在仓库根运行，ENOENT后改为正确package目录，不计产品缺陷或测试通过。


## 继续执行顺序

1. 先完成本批完整隔离CI与清理，保留精确构建身份；未获push/merge/deploy授权时本地交付。
2. 下一批优先验证Factor/Signal导入身份缺口，再补非ML原key只读核对和持久恢复，避免在缺少
   可信owner约束的入口上扩大恢复能力。按既有ADR收紧鉴权不授予新权限。
3. F6继续官方累计预算资格与账本；无合格全调用拦截证据时后台仍关闭。
4. S3可继续封闭data-demand/Worker实现；实际缓存迁移仍需真实只读数据来源。
5. 汇总完整复合研究故障旅程、全接口逐项结论与历史AgentRun处置；不以本批组件绿色关闭总需求。


## 最终本地交付验证

- 独立 `.18` 源身份：兼容基线与候选均通过 check；历史 `.17` 及更早清单未改写。
- CI scope：`post-u8-interface-audit-20260909`；退出0，全部26项PASS。
- 架构228；Backend499通过/1跳过/7subtests；Gateway202；Python publisher10；relay2；
  Cloudflare19及4项部署脚本测试/类型检查/双Worker dry-run。
- Runtime兼容基线149通过/35跳过；候选158通过/26跳过；真实候选进程23通过。
- Frontend176；模拟浏览器20；真实Product API浏览器9；重启持久化、两用户隔离、完整Product coherence通过。
- 既有ResizeObserver、框架弃用警告保留；跳过项不计PASS。
- CI结束后独立 `cleanup-resources.sh --scope=post-u8-interface-audit-20260909 --verify-only` PASS。
- 最终文档校验、diff hygiene和两版构建身份复核PASS；没有修改main应用源码或Community。
- 脱敏本地日志位于 `.ci-artifacts/post-u8-interface-audit-20260909/LOCAL-CI.log`（不提交仓库），SHA-256：
  `1098f6b2cb20cc09cf725c80b08eb95bddac3b6d61048b29a512997b87a88c6f`。
- 本批仅本地提交；未push、无Draft PR、未验证远端CI、未merge或部署。完整本地CI不等于生产修复或所有F2闭合。

Product下一Phase仍未授权；剩余维护开发按上文顺序继续，不因本批通过自动扩大交付/部署授权。


## 下一切片（2026-09-09）

Factor/Signal归属缺口已隔离复现并完成定向修复；见
[领域输入与信号读取归属](DOMAIN-INPUT-OWNERSHIP.md)。本页`.18`验收保持历史记录，
不覆盖后续新源或宣称F2/全接口审计已闭合。

后续具名切片：[Research 创建回执原键核对](RESEARCH-RECEIPTS.md)。
补充前三类实体精确只读入口；持久 watch 和其他提交仍待完成，初始发现表保留历史语境。

后续具名切片：[Backtest 原键核对](BACKTEST-RECEIPTS.md)。提供原 task/key 只读摘要，
高层 backtest-task 提交、持久等待和自动续接仍未覆盖。
