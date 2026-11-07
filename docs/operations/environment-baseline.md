# 生产测试与开发测试环境基线

这是 2026-11-07 对现有环境进行的运行配置整理，不改变 Clean Break 架构或
Phase 17 验收范围。Phase 18 仍未开始。受保护配置属于本机 operator 输入，
不随 Git、镜像、release 制品或证据公开。

## 两套长期环境

| 项目 | 生产测试 | 开发测试 |
| --- | --- | --- |
| Compose project | `beyondquant` | `byq-development-test` |
| 用户入口 | `http://192.168.1.3` | `http://127.0.0.1:32790` |
| 运行服务 | 原有 17 个 | 10 个，含共享数据库和辅助 Runner |
| 配置目录 | `~/.config/beyondquant/environments/production-test` | `~/.config/beyondquant/environments/development-test` |
| 唯一 Compose 入口 | `compose.json` | `compose.json` |
| 受保护参数来源 | `operator.env`，目录 0700、文件 0600 | 同左，独立值 |

每个入口声明本环境的完整运行服务集合、健康依赖、网络、权限和既有卷。
网络和卷使用明确的既有名称及 `external: true`，缺失即失败，不能以新空卷
冒充原数据。两套环境没有共用网络或卷。生产测试未新增 `judgment-consumer`。

开发测试保留的服务为 PostgreSQL、Backend、Frontend、Gateway、Runtime Adapter、
主 Product Runner、辅助 Product Runner、Judgment Runner、MCP、Judgment MCP。
它保留原测试数据及特殊资格实验的会话/控制卷；生产仍保留完整工作服务集合。
两套环境共用组件的镜像基线相同，服务集合、账户、密钥、数据和资格参数分别管理。
开发测试的主链检查不能代替生产全部 Worker 的功能验收。

## 镜像与配置更新

本次基线来自已资格验证的主线 `e8be5d2fcbbf4086db36a13eac24a47197e2be37`，
可信 Release Images run `42233709463`。应用使用发行清单的 registry digest；
ACP Adapter、Product Runner、Judgment Runner 共用已接受的统一镜像，
按 `BYQ_ACP_ROLE` 分派，保留各自权限和存储边界。辅助 Product Runner 使用相同镜像。
PostgreSQL 保持原来两套环境共同使用的固定镜像，不升级数据库版本。

参数值只从各自 `operator.env` 注入，Compose 中为按名引用；明确可空的参数使用
空默认引用。必需凭据须通过现有 `release_secrets.verify_injection` 校验。
生产部分 Worker 过去依赖部署进程的临时变量，按旧标签重放会解析出空凭据；
本次已按运行值建立持久的受保护来源，未轮换任何凭据。

运行中的应用不再挂载工作树 Python 文件、ACP 兼容模块或 Frontend dist。
开发 Backend 接回原有 domain-state、ml-model-state 卷及访问组 10005；
文件对象路径从空的 `/tmp/byq-f6` 目录改为上述持久卷内的路径，验证运行用户可读写。
Judgment MCP 指向健康主 Backend。保留原有健康启动依赖及 Runner 安全配置。

以后沿用 [镜像发布流程](image-release.md) 和 `scripts/release/manifest.py overlay`
验证签名、SBOM、可信运行和 digest。先在开发测试验证，再按任务授权处理生产测试。
每次成功后把已验证的 image 字段收敛回当前单入口，保留原配置作回退记录，
不继续无限叠加日期目录和临时源码补丁。默认 F6 运行开关为 1，用户主动关闭的
设置仍保存在各自数据库中，不由环境同步覆盖。

下面的 `config` 仅作退出状态验证；解析结果可能含秘密，不打印、不保存明文：

```bash
byq_environment_dir="$HOME/.config/beyondquant/environments/development-test"
docker compose --project-directory "$byq_environment_dir" \
  --env-file "$byq_environment_dir/operator.env" \
  -f "$byq_environment_dir/compose.json" config --quiet
```

生产测试使用对应目录。受控启动用同一入口的
`up -d --no-build --pull never --wait`，不能绕过本任务的授权、停入口、未结算执行
检查、备份和验收步骤。不要用此命令自动添加发行清单中尚未部署的服务。

## 备份、回退与清理

本机本轮证据目录为
`~/.local/state/byq-maintenance/environment-convergence-20261107`。
两环境分别保存逻辑数据库和非数据库状态卷的加密备份，完全解密到匿名临时文件后
用原生 `pg_restore --list`、`tar -tf` 校验。数据库卷、状态卷原地保留，不做数据迁移。
容器原规格仅加密留档；日志与容器独有的变更文件同样加密归档。
解密密钥是受保护 operator 材料，不进入 Git 或制品。

两配置目录保留 `rollback.compose.json` 和受保护的 `rollback.env`；其镜像和
源码挂载原件继续保留。开发回退配置同样挂接持久数据卷，避免旧镜像回退后新文件
不可访问；精确的迁移前参数仍在加密快照和旧容器中。开发测试迁移前的十个主链容器改名加后缀
`-retained-env20261107`，停止并关闭自动重启，作为本轮回退材料。
不能同时启动旧、新数据库容器访问同一卷。回退应用须先停当前写入者，使用原镜像
和既有卷；只有独立确认需要恢复数据时才进行数据库恢复。

废弃资源按 `cleanup-plan.json` 的精确 ID 清理。删除前必须核验其仍停止、
不属于当前运行链路、容器独有文件及完整日志已加密归档并校验。
容器删除不带 `-f`、`-v`。未分类对象保留，不依据名字相似或创建时间直接删除。
本轮不删除任何镜像、数据卷、原始挂载文件、工作树、历史回执、release 目录或备份。
禁止全局 prune、volume prune、`down -v`。

本轮已清理 73 个旧容器、16 个无任何保留容器引用的空网络，镜像和卷删除数均为 0。
清理后共有 27 个运行容器（生产测试 17、开发测试 10）、10 个停止的本轮回退容器，
另有 3 个尚未确认归属的无标签停止容器保留。归档索引、逐 ID 删除结果分别位于
`retired-archive-index-complete.json`、`cleanup-result.json` 和
`network-cleanup-result.json`，不把“未删除”误报为“已清理”。

## 验证边界

本轮复用上述可信发行的构建、Full、签名和 SBOM 证据，不重新构建镜像。
配置与注入校验、独立配置审查、先开发后生产启动、正常用户 Product API 原会话
恢复及持久消息/执行回执校验分别记录。原页面保留，不冒称新增浏览器交互验收，
也不以零模型调用的恢复检查代替新的模型回合或真实 F6 链路验收。
这两份 operator 配置绑定保留的数据资源；从空环境创建使用既有
`scripts/dev/environment.py` 的源码/schema/seed 流程，不把外部卷入口当作空环境模板。
实际运行与正常用户原会话恢复结果见证据目录中的
`development-test-acceptance.json`、`production-test-acceptance.json`；整体盘点见
`RESULT.json`。生产有 12 个现成健康探针通过，其余 5 个 Worker 的证据为容器运行，
不据此宣称新增业务 Job 验收。
