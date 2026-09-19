# ADR-0080：发布制品 secret 边界

- Status: Proposed
- Date: 2026-09-19
- Scope: release/rollback overlay、resolved private config、retained-artifact copy、release manifest 与备份中的 secret 值；部署期 secret 注入来源与校验。不推进 Product Phase。
- Relates: [ADR-0059](ADR-0059-development-governance-and-ci-integrity.md)（隔离工作树、合并/部署门禁、轻量升级流程）、[ADR-0062](ADR-0062-post-u8-reliability-boundaries.md)（Post-U8 维护边界）、[ADR-0070](ADR-0070-hosted-ci-and-image-release.md)（可信镜像发布与 digest 部署输入）。

## 背景

一次经核实的只读盘点确认，发布准备把 secret 的**字面值**写入 release 制品：

- `release-*/target.compose.json` 与 `release-*/target.resolved.private.json` 含真实
  `TUSHARE_TOKEN`、`DEEPSEEK_API_KEY`、`BYQ_MCP_TOKEN`、`BYQ_PRODUCT_TOKEN`、
  `BYQ_FEEDBACK_HUB_RELAY_TOKEN`、`BYQ_CREDENTIAL_RESOLVER_TOKEN`、
  `BYQ_CREDENTIAL_KEYRING`、`BYQ_CREDENTIAL_ACTIVE_KEY_ID`、
  `BYQ_FEEDBACK_PUBLISHER_TOKEN`、`BYQ_PLUGIN_DEPLOYMENT_TOKEN`、
  `BYQ_BOOTSTRAP_ADMIN_PASSWORD` 以及 `BYQ_DATABASE_URL`（含数据库口令）等。
- 成因有两处：release 目录的 operator `prepare.py` 把 live 容器的 `Config.Env`
  逐键复制进 overlay 的 `environment`；`docker compose config --format json` 又把
  插值后的完整配置落盘为 `target.resolved.private.json`。
- `compose.yml` 本已用 `${VAR:-default}` / `${VAR:?message}` 从宿主 `.env`
  在部署时注入，但 overlay 的字面 `environment` 覆盖了该来源，使 `.env` 修改对
  这些服务失效，并把明文扩散到主机文件、备份与保留制品。

问题不是“存在某个配置文件”，而是**明文 secret 会随备份/发布制品长期增殖，且轮换
对已落盘副本无效**。一个被轮换的 token 仍会留在历史 release 目录和备份里。

## 决策

### 1. 不变式

Release 制品（attested manifest、target/rollback overlay、resolved private config、
retained-artifact copy、备份）MUST NOT 含任何明文 secret 值。生成的 overlay 对 secret
键 MUST 只保存**按名称引用**（`${ENV_NAME}`）或占位形式；真实值只在部署时注入。

### 2. 受保护的非仓库来源

部署期真实值来自受保护、非仓库来源：宿主 `.env`（MUST 为 `0600`，且 gitignored、
永不提交），或等价受保护的 secrets 文件 / Docker secrets。secret MUST NOT 进入
镜像、Git、release 制品、证据或 PR。宿主 `.env` 自身不是发布制品，不进入任何制品。

### 3. 部署期注入

Operator 通过带 `--project-directory <main>`（Docker Compose 自动加载该目录 `.env`）
或显式 `--env-file <受保护文件>` 执行 compose。overlay 中的 `${ENV_NAME}` 在
`up`/`config` 时由受保护来源解析并注入运行容器，因此修改受保护来源即可生效，无需
重新生成或重新哈希制品。

### 4. Guard 与工具

新增 `scripts/dsh/release_secrets.py`：

- `sanitize_overlay` 把 secret 键的字面值替换为 `${ENV_NAME}`；
- `redact_resolved` 生成去密的 resolved 证据（secret 键为引用，secret-like 字面值为
  `<redacted>`）；
- `assert_no_plaintext_secrets` 对制品做 fail-closed 扫描：secret 键的字面值、
  `sk-*`/PEM/Bearer 模式、内嵌凭据的 DB URL、以及显式已知值集合均拒绝；
- `parse_protected_env` 拒绝 group/world 可读的受保护来源；
- `verify_injection` 在部署前用受保护来源解析全部引用，缺失/空值的必需 secret
  fail closed，且只在内存中解析、绝不落盘或打印。

发布准备 MUST 在写盘前对 `target.compose.json`、`target.resolved.private.json` 及
retained-artifact copy 调用上述净化/去密与 guard；`scripts/release/manifest.py` 的
overlay 生成也在写出前运行 guard。

### 5. Attestation 与验证

镜像 attestation 绑定的是 manifest（源 SHA、run、digest-pinned image、SBOM 哈希），
从不包含 env 值，因此不受影响。`scripts/release/manifest.py` 的 registry/digest 验证
与 `gh attestation verify` 不变；resolved config 仅为证据，现以去密形式保存。
若未来任何 manifest 字段需要覆盖 secret，必须改为哈希“引用”而非值，并在本 ADR
具名记录。

### 6. 迁移与向后兼容

- 既有 release 目录与备份 MUST NOT 被修改、重写或删除；其历史明文暴露如实保留并
  记录，不作为可复用模板。
- 旧 overlay 含字面值仍可被 Compose 接受并用于回滚；但它们是非合规的历史制品，
  operator MUST NOT 把它们继续向前复制到新 release。
- 使用引用形式的新 release 在部署前，受保护来源 MUST 已包含全部被引用的 secret。
  `verify_injection` fail closed 会阻止缺失来源的部署，而不是静默注入空值。
- 本 ADR 不迁移、不打印、不轮换任何现有 secret 值。

### 7. 明确不在范围

- 不轮换任何外部 provider token 或内部 secret；不改 token 内容。
- 不把 secret 迁移进 Docker secrets / 外部 vault；`.env`（0600）是当前受保护来源。
- 不改变 compose topology、服务集合、网络/卷或 Product/DSH 边界。
- 不修改、删除或重写既有 release 目录、retained artifacts 或备份。
- 不把 secret 值读取、打印或序列化进任何证据。

## 后果

- 备份、release 目录与 retained artifacts 不再因发布而累积明文 secret；轮换后旧
  副本不再包含新值。
- `.env`（0600）成为这些服务部署期 secret 的权威注入来源。
- 发布准备多一步净化与 guard；缺失受保护来源的引用会 fail closed，需 operator 在
  不打印值的前提下补齐来源。
- 历史制品保持原样，暴露面被承认且不再扩大。

## 备选方案

1. 仅 `chmod` 与文档约束、不改生成器：不解决制品内明文与轮换失效，拒绝。
2. 把 `target.resolved.private.json` 直接删除：失去 key 集合与可审计性；改为去密证据。
3. 在 overlay 中完全省略 secret 键、依赖 base `compose.yml` 插值：也能去密，但对
   “引用可审计”与缺失即 fail-closed 的表达较弱；本 ADR 选择显式引用 + 部署前校验。

## 回滚

本决策无运行时状态迁移。若需回退，operators 可继续使用历史含字面值的 overlay 部署
（Compose 接受）；工具与 guard 的移除需要新的 ADR，不得以兼容层绕过不变式。
