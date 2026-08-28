# ADR-0038：DSH Product Plugin Registry 与 Qualification Boundary

- Status: Accepted
- Date: 2026-08-28
- Accepted: 2026-08-28
- Decision scope: Phase 63 Product Agent generic capability governance
- Related: ADR-0001、ADR-0003、ADR-0004、ADR-0009、ADR-0018、ADR-0019、ADR-0025、ADR-0033、ADR-0036、ADR-0037

## 背景

Product DSH composition 已精确固定在 Python `0.1.1rc1` / npm `0.1.1-rc.1`，但新增
generic capability 仍依赖人工修改一个持续增长的 Cordis YAML。上游 package 存在、npm
安装成功和 BYQ 可以安全用于 Product 是三个不同事实。维护者明确授权 Phase 63 建立
受控、可审计、版本锁定、最小权限且可自动验证的插件治理边界。

2026-08-28 重新检查 official GitHub、npm、PyPI 与 rc.1 source。GitHub 最新 release 为
`0.1.2-alpha.1`，npm 样板包可观察到 `0.1.1-rc.2`，但 official Python SDK/runtime-bin
仍最高为 `0.1.1rc1`。因此本 ADR 不升级 DSH baseline，也不混合 prerelease。

## 决策

### 1. Registry 是 BYQ-owned、声明式且 Git-managed

`plugins/dsh-byq/registry/` 持有版本化 registry、JSON Schema、Product profiles 和独立
Agent capability mapping。首版不增加数据库，不接受用户上传、URL/GitHub source 或
第三方 package。每个 descriptor 固定 official publisher、exact package version、npm
integrity、runtime compatibility、qualification evidence、完整 capability bitmap、
credential reference、risk、agent allow/deny 和 Product enabled policy。

Registry 只描述 deployment input。它不持有 BYQ domain authorization，不是 Marketplace，
也不向运行中的 Product 提供安装或自修改 API。

### 2. 状态不可跳级

核心状态语义为：

```text
AVAILABLE → QUALIFIED → ENABLED
```

`AVAILABLE` 只证明上游存在；`QUALIFIED` 证明在当前精确 baseline 完成 package、integrity、
closure、peer、startup、Cordis initialize、capability、credential、secret、lifecycle、Agent、
MCP、contract 和 architecture gate；`ENABLED` 是派生状态，必须同时满足 QUALIFIED、Product
policy enabled 和明确 Agent assignment。附加状态为 `BLOCKED`、`REJECTED`、`DEPRECATED`。
任何 AVAILABLE/BLOCKED/REJECTED package 均不能进入 Product composition。

### 3. 风险与 capability fail closed

风险分为 `LOW`、`MEDIUM`、`HIGH`、`PROHIBITED`。Product composition 永久拒绝 shell、
terminal、unrestricted code execution、Git mutation、application-source write、Docker
socket、runtime mutation、Engineering capability、subprocess 和 unrestricted database。
混合 package 只有在危险 capability 真正隔离时才可使用安全部分。

Web Search 只启用 `web_search`，明确配置 `fetch: false`。Web evidence 只能成为 research
context/provenance，不能直接成为 Factor、Strategy calculation 或 Backtest deterministic
input；权威量化输入仍只来自 BYQ Data Plane。

### 4. Plugin enablement 与 Agent authorization 分离

`agent-capabilities.json` 与 plugin Product enabled policy 独立。生成器验证 descriptor
allow/deny 后才把 model-facing tool 加入既有 DSH `toolFilter.allow`。Phase 63 明确允许
`market_researcher` 使用 `web_search`；Factor、Strategy 和 Backtest 子 Agent 均不可见且
执行也被 scoped restriction 拒绝。rc.1 root Agent 的全局 tool registry 没有独立 root
filter，因此 `quant_orchestrator` 被显式记录为允许，而不是隐式继承。未来若要移除 root
访问，必须使用上游可验证的 root restriction seam，不能创建 BYQ 第二工具运行时。

DSH toolFilter 不是 BYQ authorization ceiling。所有 Agent-to-Domain 动作继续逐项经过
`byq_agent_authorize`、Backend policy 和 audit；DSH interaction/approval 永不替代它们。

### 5. Deterministic Composition Builder

`scripts/dsh/plugin_registry.py` 读取 Registry + Product Profile + Agent Mapping，验证准确
manifest/lock/integrity、状态、风险、版本、assignment 和 capability，然后从受控 template
生成唯一 Product Cordis composition。输出排序稳定，并生成：

- profile identity；
- composition SHA-256；
- enabled plugin IDs；
- qualified package/version set。

生成文件有显式 header；CI 使用 `build --check` 拒绝人工漂移。Runtime Adapter readiness
只投影上述封闭、无密钥 identity，不返回 credential、raw executable config 或内部 token。

### 6. 禁止 online install

Enable 的唯一流程是：

```text
registry change → qualification → exact manifest/lock → generation → CI → image build/deploy
```

Browser、Gateway、Runtime Adapter 和 DSH session 均无 `npm install`、hot install、extensions
或 self-modification path。存在于 image closure 也不等于加载或 enabled。

### 7. 首批 qualification 结果

- Guard：QUALIFIED + ENABLED；advisory reminder 不改 Domain result，timeout 是 cooperative
  safe failure，不伪造成功。
- Compaction：QUALIFIED + ENABLED；summary/pruned result 只属于 Agent context，不是 BYQ
  Artifact、research evidence、StrategyVersion 或 Backtest manifest。
- Web Search：QUALIFIED + ENABLED；keyless initialize，credentialed smoke 可选，fetch 禁用。
- Spill：BLOCKED；rc.1 `spill-local` 无 session/age cleanup，并返回要求 read/grep 的本地
  path；Product DSH 没有 filesystem read/write tool，不能为它扩权。
- Interaction：BLOCKED_BY_RUNTIME_VERSION；rc.1 package 存在，但当前 qualified SDK/JSON-RPC
  path 没有验证完成 Product question request/answer lifecycle。

## 非目标

不建设开放 Marketplace、上传/评分/推荐、runtime install、任意 package source、完整前端
Plugin Center、shell/terminal/filesystem/coding executor、DSH extensions，亦不改变 MCP、
PostgreSQL、Redis、provider、WorkflowTrace、credential、workspace 或 BYQ authorization
边界。

## 验收与回滚

CI 必须覆盖 registry negative cases、exact closure、deterministic hash、enabled/disabled
composition、Agent visibility、secret absence、architecture、keyless initialize、session
lifecycle、MCP path 和 existing Product Agent compatibility。Web credentialed smoke 不进入
required CI。

回滚恢复前一 generated composition、manifest/lock 和 Runtime Adapter image；停止并释放
owned DSH process，再从保留的 Agent Plane session volume 启动新 runtime。BYQ business
database、Artifact、WorkflowTrace 和 credential 不迁移、不删除。单个插件失败时只禁用该
plugin 并重新生成，绝不升级、fork、patch 或绕过 protocol。

## Acceptance record

维护者于 2026-08-28 明确授权 Phase 63。该授权接受本 ADR 的 Registry、Qualification、
Composition Builder 与五类 official sample inspection，不授权 release/tag/production
publication 或下一 Product Phase。
