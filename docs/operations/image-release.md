# 云端镜像发布与 digest 部署

依据 [ADR-0070](../architecture/adr/ADR-0070-hosted-ci-and-image-release.md)。

## 开发

```bash
make dev-check
# 定向测试按改动选择；完整组件与集成套件交给 PR CI。
# 单次读取（不阻塞）。
python3 scripts/ci/watch-ci.py --pr 123 --expected-head <完整PR-head-SHA> --once
# 有界可恢复观察：输出只在状态变化时出现；PENDING(2) 时再次调用，不要长期 sleep。
python3 scripts/ci/watch-ci.py --pr 123 --expected-head <完整PR-head-SHA> --budget-seconds 90
```

watcher 只报告观察到的状态，不是合并授权工具；缺失、过期、403 或未知证据一律
返回 BLOCKED/STALE（退出码 3），绝不返回 PASS。退出码：0 PASS、1 FAIL、
2 PENDING/预算耗尽、3 BLOCKED/STALE。

PR 的完整套件分任务并行执行；主线不因合并再次触发 Full。夜间 Full 用于漂移检查。
每次运行的阶段耗时、pytest 收集/通过/跳过与慢 setup/call/teardown 项由既有入口在
脱敏日志中产出，可用 `python3 scripts/ci/ci-metrics.py --log <redacted log> --sha <sha> --run <id> --attempt <n>`
汇总；不为此新增额外 Full 运行。
`local-ci.sh --all --with-e2e --with-smoke` 保留作本地显式诊断入口。

## 构建发布

### 受测镜像在不同 Docker 存储之间交接

新的内部交接收据使用 `byq-release-images.v2`。`captured_image_id` 保存 qualify
实际捕获的 Docker 存储 ID；`image_id` 保存归档 config 原始字节的 SHA-256。
两者可能不同。归档独立保存并验证 manifest、按顺序排列的层 digest/size/diffID
和平台，不能把本地 ID 当作已发布的 registry digest。外部 `byq-release.v2`
和 DSH identity 的 `image_id` 使用 canonical config digest。

export 校验原受测镜像与归档内容；publish 在 load 前校验收据、完整归档和精确
标签绑定，load 后核对全部服务标签、store ID、RootFS 和平台，再运行 syft/push。
经典存储加载后 ID 必须等于 config hash；containerd ID 必须绑定已验证的归档
manifest 和 Descriptor。纯传统归档不能仅凭 RootFS 相等认定未知 manifest ID。
默认路由（`compose.yml` + `compose.override.yml`，含
`compose.dsh-acp-rc2-candidate.yml`）现按 ADR-0110 声明单镜像：三个 ACP 角色
共用 `services/acp_unified/Dockerfile` 与同一个 run-scoped 项目镜像 tag，运行期由
`BYQ_ACP_ROLE` fail-closed 派发；发布/CI 只构建该 ACP 镜像一次，并把它 alias 到三个
角色的 run-scoped tag，使各 service 的 capture 仍精确。拓扑由唯一 checked-in
Compose 路由（`scripts/release/images.py`）导出，没有 ambient selector。三个角色因此
共享一次 SBOM/push。此为源码采纳，不代表已发布 registry digest、已部署或 hosted CI
已通过；那些仍由发布/部署通道独立验证。

已有 v1 内部收据必须证明记录 ID 等于归档 config 的实际 hash；现代 classic save
即使同时带 OCI layout 也按字节验证，不能只按布局猜测 ID。Docker/OCI 兼容视图
必须逐标签指向相同 config 和有序层。外部层 URL、缺失 descriptor 内容、未知
元数据和不一致身份会拒绝，不会在 publish 中重建或补下载。

[Moby save](https://github.com/moby/moby/blob/v28.5.2/image/tarexport/save.go)
可能保留 pulled layer 压缩 descriptor 而导出原始 DiffID 层；此类缺失 descriptor
payload 的归档目前不支持。真实 hosted Docker store/export 仍须验证。
[Docker CLI manifest 类型](https://github.com/docker/cli/blob/v29.0.0/cli/manifest/types/types.go)
使用 `Descriptor.digest` / `Descriptor.platform`；registry readback 必须核对
config/platform，存在 Raw 时同时核对原始 manifest hash。

本地证明与限制见 [2026-10-10 交接身份证据](../evidence/dsh-acp-single-version/acp-release-store-identity-20261010/RESULT.md)。
源码测试、真实本地归档、跨 daemon load 与 hosted registry 验收分别记录；任一项
尚未执行不能由另一项替代。

### 外部发布清单版本

当前 17 服务发布清单使用 **`byq-release.v2`**，明确包含
`acp_image_topology` 和 `dsh_identity`；per-role 和 single-image 拓扑均用 v2。
它与内部镜像归档收据 `byq-release-images.v2` 是两个独立合同，DSH identity
的版本不变。发布脚本生成 v2，验证、digest overlay 和推广使用同一严格校验器。

旧 13 服务 `byq-release.v1` 及误标为 v1 的新清单，在读取 SBOM、验证签名、
访问 GitHub、拉取/推广镜像或生成操作输出之前拒绝。未知版本同样拒绝。
不要手改已签清单的版本名或补写 ACP 字段；这样不能证明旧制品具备新身份。
实际历史签名制品的操作兼容性仍 **OPEN / NOT_RUN**，本次不引入迁移路径。

`scripts/v090/final_closeout/observer.py` 的 v1 检查属于冻结的 0.9 历史证据，
不作为当前发布检测或准入工具。当前准入由 `scripts/release/manifest.py`
核对完整 v2 清单、SBOM、签名工作流和成功的 trusted-main 发布运行。

本地源码验证见 [外部清单 v2 证据](../evidence/dsh-acp-single-version/acp-public-manifest-v2-20261010/RESULT.md)。

### 一次最终 Full 的调度规则

默认只执行：**PR 按影响检查 → 合并 → Release Images（最终 Full + 发布受测镜像）
→ Promote 相同 digest → 部署健康/基本业务验证**。Release 的 qualify 已承担发布候选的
最终 Full；不要再先调度 `ci-selfhosted.yml profile=full` 作为普通发布的前置步骤。
本规则从合并后的下一次新发布候选生效，不取消进行中的测试或改写历史失败。

阶段明确要求的合并前 Full/Golden、夜间漂移检查和必要故障诊断仍各有独立目的，不能
用 release 尚未执行的未来结果宣称阶段通过。PR CI 必须通过；发布候选 Full 也未减少。
普通 CI 只有测试证据，没有可信 release 归档，不可据此跳过镜像 qualify。

对已合并 main 发起一次显式镜像发布，migration 必须按本次变更填写：

```bash
gh workflow run release-images.yml --ref main -f migration=none
```

工作流在无生产凭据的云端执行 Full，保留本次实测镜像，独立发布到 GHCR。
PR 与 release 可能各构建一次，依靠缓存降低成本；publish 与部署都不重编译。
镜像标签包含源码和 run/attempt；生产引用 `ghcr.io/...@sha256:...`。
发布失败不产生可用的成功 run 清单，即使部分 candidate 镜像已上传也不能部署。
清单必须覆盖当前 Compose 的全部应用镜像，包括独立的 backtest-worker、factor-worker
和 optimization-worker。这三个服务使用各自经测试的 Worker 镜像，不得替换成缺少
相应入口的 Backend 镜像；缺少任何镜像、SBOM 或交接绑定都不能产生可用的成功
发布清单或用于部署。失败前可能已上传部分 candidate 镜像，这些不构成成功发布。
publish 作业失败时，只重跑失败作业，复用同一 run 中已成功验证且未过期的归档；无需
重跑 Full。qualify 的测试失败必须修复，不得直接发布；修改源码/构建输入或受测归档
已不可用时，重新资格验证。成功 run 后的 RC、正式版标签和部署均复用其镜像 digest，
不因版本标签或部署动作再执行完整 CI。
镜像归档压缩上传并保留一天，脱敏日志七天，发布清单/SBOM 九十天；正式 release 时把清单、SBOM
及 attestation bundle 保存为长期 release 资产，不依赖 Actions 临时保留期。

## RC 提升

同一成功构建先标记 RC，再明确授权最终版本时使用同一个 run ID：

```bash
gh workflow run promote-images.yml --ref main -f run_id=<成功镜像发布run> -f tag=v0.2.0-rc.1
# 正式版本须具名授权；替换为已授权版本，复用相同 run。
gh workflow run promote-images.yml --ref main -f run_id=<同一run> -f tag=v0.2.0
```

此动作仅提升镜像标签，不创建 Git tag 或 GitHub Release。已有其他 digest 的标签拒绝覆盖。
源码已变更时必须重新构建和验证，不能把旧清单标为新源码。

## 部署输入

operator 需要支持 `gh attestation verify --source-ref` 的当前 GitHub CLI、Docker 和 GHCR 拉取权限。
默认 GHCR 包可能是 private；公开源码不自动公开镜像，包可见性按维护者配置，不隐式修改。

```bash
gh run download <成功镜像发布run> --name release-manifest --dir <私有release目录>/manifest
python3 scripts/release/manifest.py overlay \
  --manifest <私有release目录>/manifest/manifest.json \
  --services backend,gateway,runtime-adapter,mcp,frontend \
  --output <私有release目录>/images.compose.json
```

脚本先校验 GitHub 来源证明及成功 Full run，拉取 digest，核对实际镜像 ID，再写新的 overlay；
不能覆盖现有配置，未知 migration 分类阻止生成。该命令不重启服务。
将生成的文件作为既有 operator target Compose 最后一层输入，保留现有 Env、卷和 admission 配置。

### 发布制品 secret 边界（ADR-0080）

Release 制品（attested manifest、`target.compose.json`、`target.resolved.private.json`、
retained-artifact copy 与备份）MUST NOT 含明文 secret 值。operator 生成 overlay 时：

1. 不要从 live 容器复制 secret 的 `Config.Env` 字面值；secret 键只保存 `${ENV_NAME}` 引用。
2. 写出前对制品运行 guard，失败即停止：

```bash
python3 scripts/dsh/release_secrets.py check <release目录>/target.compose.json \
  <release目录>/target.resolved.private.json
```

3. 若已有含字面值的制品，用净化/去密生成新文件（不覆盖旧制品）：

```bash
python3 scripts/dsh/release_secrets.py sanitize \
  --input <旧>/target.compose.json --output <新>/target.compose.json
python3 scripts/dsh/release_secrets.py redact \
  --input <旧>/target.resolved.private.json --output <新>/target.resolved.private.json
```

4. 部署前用受保护来源（`0600` 宿主 `.env` 或 `--env-file`）验证每个引用都可解析；
   缺失或为空即 fail closed，不得静默注入空值：

```bash
python3 scripts/dsh/release_secrets.py verify \
  --input <release目录>/target.compose.json --env-file /home/jefison/projects/BeyondQuant/.env
```

5. 实际值由 Docker Compose 在 `compose up`/`config` 时从 `--project-directory` 下的
   `.env`（或显式 `--env-file`）注入。既有含字面值的 release 目录/备份不改写，仅作
   历史回滚；不得向前复制到新 release。`scripts/release/manifest.py` 的 attestation 与
   digest 验证不变，因为它从不校验 env 值。

常规发布按已接受的轻量流程：完成数据备份并校验可读/摘要，保存当前配置和实际旧镜像，必要时
关闭入口排空并备份会话，然后仅对选定服务执行 `up -d --no-deps --no-build --pull never --wait`。
核对实际 digest/image ID、健康、普通用户登录与既有会话后恢复入口；失败用保存的旧镜像/配置恢复。
不自动恢复业务数据库，不重复整库恢复演练，不清理历史镜像或备份。

缓存采用服务级 GHA v2 `mode=min`，通过平台配额与逐出限制总占用，不提高付费额度。
缓存失效仅导致重建；测试范围和制品验证不可省略。时间以 Actions 实测为准，首轮冷缓存会更慢。

Docker classic store 的 `Id` 是 config digest，containerd store 的 `Id` 是 manifest digest。
配置生成同时检查注册表 config、拉取后的精确 RepoDigest、平台及 store 对应的 ID/Descriptor；
不因 Docker 29 的默认 store 改变而误报，也不能仅接受任意一种 SHA 字符串。
