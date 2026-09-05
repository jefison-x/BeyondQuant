# ADR-0054：Cloudflare GitHub 自动部署

- Status: Accepted
- Date: 2026-09-05
- Accepted: 2026-09-05
- Decision scope: Phase 94 中央 Feedback Hub 的 Git source、自动资源配置、migration 和生产部署门禁
- Related: ADR-0015、ADR-0049、ADR-0052、ADR-0053

## 背景

Phase 93 已把官方中央 Feedback Hub 实现为两个隔离 Cloudflare Worker，但首次安装仍要求维护者在本机安装依赖、登录
Wrangler、创建 D1/Queue、回填 account-specific D1 id、执行 migration 并依次部署。维护者要求由 Cloudflare 直接引入
`jefison-x/BeyondQuant` GitHub 仓库，减少命令行配置，并让后续 `main` 更新自动部署。

Cloudflare Workers Builds 原生支持 GitHub、monorepo、custom root/deploy command、build watch paths 和每个 Worker 的独立
check。Wrangler 4.129 支持无 resource id 的 D1 自动配置，Cloudflare 部署也能根据 Wrangler config 配置 D1、Durable
Objects 和 Queues。Cloudflare 官方同时明确：一个 Deploy to Cloudflare 按钮不能一起部署 monorepo 中的多个 Worker。

Community 只读检查没有 Cloudflare、Wrangler、Workers Builds 或等价自动部署实现；其 GitHub Actions 只作为普通 CI
`REFERENCE_ONLY`。本阶段部署控制面为 `REPLACE`，不复制 Community workflow、runtime、credential 或 Git history。

## 决策

1. Cloudflare 连接同一个官方 GitHub 仓库两次，分别创建 `byq-feedback-hub` 和 `byq-feedback-publisher` project。两个 project
   使用相同 root directory `deploy/feedback-hub-cloudflare`，但使用独立 deploy command。不得合并为一个 Worker。
2. Production branch 仅为 `main`。非生产分支不上传或激活 Worker，只执行现有 type/workerd/contract/bundle dry-run；GitHub
   required CI 仍是 merge gate。Cloudflare Git connection 不成为 Issue writer，也不得绕过受保护 `main` 的 PR/CI 流程。
3. Hub build 使用 `npm run cloudflare:build`，deploy 使用 `npm run cloudflare:deploy:hub`；deploy 先按 D1 binding `DB` 应用
   versioned migration，再部署 Worker。Publisher 使用相同 build command 和 `npm run cloudflare:deploy:publisher`。
4. D1 config 不提交 account-specific `database_id`。Wrangler/Cloudflare 按固定 binding/name 自动创建并保持绑定；Queue、DLQ
   和 Durable Object 同理由 Wrangler config 声明。首次必须先完成 Hub，再连接 Publisher，使 Service Binding 目标存在。
5. 每个 config 声明自己的 `secrets.required`。Hub 只要求 status/admin/publisher service secret；Publisher 只要求同一 service
   secret和 GitHub App ID/installation/private key。缺失 secret 时 fail closed，不允许以明文 var、build secret、`.env`、
   `.dev.vars`、GitHub Actions secret 或仓库文件绕过。Dashboard runtime secrets 在后续 code deploy 中保持。
6. Cloudflare 的 GitHub source App 与创建官方 Issue 的 BYQ GitHub App 是两个不同主体。前者只限定到所选仓库并用于 source
   build/check；后者仍只在 Publisher runtime 中拥有固定仓库 Issues read/write，不获得 Contents、Pull requests 或 Actions 权限。
7. 仓库提供可机器验证的固定 project/resource/secret/command contract、精确 Dashboard 参数和 CLI fallback。不得声称一个
   按钮可原子部署两个 Worker；自动资源配置或 Git build 失败必须可见并可重试，D1 outbox 仍是发布事实来源。

## 验收

- 无 account id/D1 id 的 Hub config 可由 Wrangler dry-run 打包，并保留固定 D1/DO/Queue identity；
- 自动部署合同测试检查两个 project 名、required secrets、migration-first command、Service Binding、Queue/DLQ 和固定仓库；
- workerd/D1/DO/Queue/fake-GitHub 测试与两个 bundle dry-run 继续通过，且使用的 fake secrets 只存在于运行时临时目录；
- runbook 从 GitHub import 开始，明确两个 project 的 root/build/deploy/watch-path/branch 设置、首次 fail-closed secret 配置、
  验收、回滚和 CLI fallback；
- Frontend、Gateway、Backend、MCP、DSH、本地 relay、正式 PostgreSQL/Compose 和反馈 wire contract 均不变。

## 拒绝的替代方案

- 一个 Worker/一个按钮：会让公网 intake Worker 持有 GitHub private key，并违反 ADR-0049/0053。
- 把 Cloudflare API token 放进 GitHub Actions：增加 GitHub secret 和第三个部署控制面，不符合由 Cloudflare 拉取 Git 的目标。
- 提交 D1 id/account id：使开源仓库与维护者账号耦合，也破坏自动配置和可移植性。
- 把 runtime secret 作为 Workers build variable：扩大 build log/process 暴露面；runtime secret 只配置到目标 Worker。
- 自动部署所有 PR branch：Durable Object Worker 无可用 preview URL，且会创建不必要的 account state。

## 回滚

在 Cloudflare Worker 的 Settings → Builds 禁用 production build 即可停止自动部署，现有 Worker/D1/Queue 继续运行。代码回滚
必须通过新的 Git PR 合并到 `main`；不得 force push。若 migration 已应用，只允许兼容的 forward repair，不自动回滚或删除
D1 表/outbox。断开 GitHub source App 不影响现有部署；撤销 Issue publisher App 会停止新 Issue，但不删除反馈或既有 Issue。

## 官方参考

- [Workers Builds Git integration](https://developers.cloudflare.com/workers/ci-cd/builds/git-integration/)
- [Workers Builds monorepo setup](https://developers.cloudflare.com/workers/ci-cd/builds/advanced-setups/)
- [Workers Builds configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/)
- [Build watch paths](https://developers.cloudflare.com/workers/ci-cd/builds/build-watch-paths/)
- [Deploy buttons and automatic resource provisioning](https://developers.cloudflare.com/workers/platform/deploy-buttons/)
- [Required Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
