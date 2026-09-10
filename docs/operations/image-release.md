# 云端镜像发布与 digest 部署

依据 [ADR-0070](../architecture/adr/ADR-0070-hosted-ci-and-image-release.md)。

## 开发

```bash
make dev-check
# 定向测试按改动选择；完整组件与集成套件交给 PR CI。
python3 scripts/ci/watch-ci.py --pr 123 --expected-head <完整PR-head-SHA>
```

PR 的完整套件分任务并行执行；主线不因合并再次触发 Full。夜间 Full 用于漂移检查。
`local-ci.sh --all --with-e2e --with-smoke` 保留作本地显式诊断入口。

## 构建发布

对已合并 main 发起一次显式镜像发布，migration 必须按本次变更填写：

```bash
gh workflow run release-images.yml --ref main -f migration=none
```

工作流在无生产凭据的云端执行 Full，保留本次实测镜像，独立发布到 GHCR。
PR 与 release 可能各构建一次，依靠缓存降低成本；publish 与部署都不重编译。
镜像标签包含源码和 run/attempt；生产引用 `ghcr.io/...@sha256:...`。
发布失败不产生可用的成功 run 清单，即使部分 candidate 镜像已上传也不能部署。
镜像归档保留一天，脱敏日志七天，发布清单/SBOM 九十天；正式 release 时把清单、SBOM
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

常规发布按已接受的轻量流程：完成数据备份并校验可读/摘要，保存当前配置和实际旧镜像，必要时
关闭入口排空并备份会话，然后仅对选定服务执行 `up -d --no-deps --no-build --pull never --wait`。
核对实际 digest/image ID、健康、普通用户登录与既有会话后恢复入口；失败用保存的旧镜像/配置恢复。
不自动恢复业务数据库，不重复整库恢复演练，不清理历史镜像或备份。

缓存采用服务级 GHA v2 `mode=min`，通过平台配额与逐出限制总占用，不提高付费额度。
缓存失效仅导致重建；测试范围和制品验证不可省略。时间以 Actions 实测为准，首轮冷缓存会更慢。
