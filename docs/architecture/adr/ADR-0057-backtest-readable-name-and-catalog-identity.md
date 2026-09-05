# ADR-0057：回测可读名称与目录身份分离

- Status: Accepted
- Date: 2026-09-05
- Accepted: 2026-09-05
- Decision scope: Phase 97 Backtest catalog metadata and Product presentation
- Related: ADR-0008、ADR-0016、ADR-0017、ADR-0035、GitHub Issue #240

## 背景

当前 `backtest_jobs` 只有稳定的 `backtest_*` 技术身份。Product 回测目录把该身份作为
主标题，用户无法通过策略意图快速区分任务，搜索也只能匹配 ID。只读 Community 审查
证明其持久化 `name`、创建时自定义名称和名称/ID 分层展示具有可迁移的产品语义；其 ORM、
旧 Agent API、VectorBT 和执行架构仍不兼容当前 BYQ。

回测 ID、输入 manifest 和结果 object identity 均承担审计与可复现职责，不能用用户名称
替代。反过来，名称也不能参与 immutable input hash，否则只修改目录标签就会改变计算身份。

## 决策

1. `backtest_jobs.name` 是 owner-scoped、持久化的目录元数据，规范化为 1–120 个字符；
   `job_id` 继续是唯一稳定身份。名称不要求唯一。
2. 创建请求 MAY 提供 `name`。缺省时 Backend 根据已验证策略名称和精确到秒的创建时刻
   生成可读默认值；历史回填另附短 ID 避免同分钟旧任务难以区分。Browser、DSH 和 MCP
   不自行伪造持久名称。
3. 名称不进入 signal snapshot、Backtest input manifest、request content hash、result hash、
   Artifact identity 或执行规则。相同 idempotency key 的重放返回首次创建任务及其原名称。
4. PostgreSQL 以向前兼容 DDL 增加字段。历史行使用创建时间和短 ID 生成稳定、非空的
   “历史回测”名称；不得修改历史输入、结果、状态或 lineage。
5. bounded catalog/summary/Product API/MCP projection 同时返回 `name` 与 `job_id`；搜索匹配
   名称或完整 ID，仍保持服务端分页和 owner/workspace 授权。
6. Product UI 以名称作为主要信息，将“回测 ID”独立展示；创建向导允许自定义名称，移动端
   以名称为标题、短 ID 为辅助信息，技术详情保留完整 ID。
7. 本阶段不增加重命名状态机，不改变 Backtest worker、审批、signal producer、ML Worker、
   DSH runtime 或 immutable execution boundary。

## 后果

- 普通用户可以用可读名称识别和搜索回测，同时仍能复制精确 ID 进行审计、对话引用和排障。
- 前端不需要从 ID 或非权威本地状态推断名称；小巴创建的任务即使未显式命名也会由领域层
  获得可读默认名称。
- PostgreSQL forward repair 可原位升级生产数据，不删除或重算已有任务。

## Community 分类

- `BacktestView.vue` 名称输入、名称主标题和独立 ID：`PORT_UX` / `PORT_LAYOUT` / `REFACTOR`。
- `BacktestRequest.name`、`BacktestRun.name`、轻量列表名称字段：`PORT_LOGIC` / `PORT_TESTS` /
  `REFACTOR`。
- Community ORM、direct internal API、PydanticAI/Hermes、VectorBT/BaoStock/AKShare：`DROP`。

## 验收

- fresh PostgreSQL 和 Phase 96 schema forward repair 均产生非空名称，且历史 job/result identity
  不变。
- Backend create/list/get、名称与 ID 搜索、idempotency、owner isolation 和 Backtest task/MCP
  projection tests 通过。
- Product 创建向导、桌面目录、移动目录、技术详情和分页搜索通过 frontend test 与真实 Chrome
  desktop/mobile review；Network 仅访问 Gateway/Product API。
- architecture、unit、contract、Compose smoke、`git diff --check` 和 secret-negative review 通过。

## 回滚

代码可通过正常 PR 回滚为忽略 `name`，但 PostgreSQL 字段保持兼容保留，不自动删除。历史
manifest、result 和 Artifact 无需迁移或重算。
