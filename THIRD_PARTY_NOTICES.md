# 第三方许可与发行边界

根 LICENSE **仅覆盖有权按该许可授权的 BYQ 原创部分**。它不改变任何第三方许可证，
不禁止他人依法单独商用 MIT/Apache/LGPL 等第三方组件，也不规避 copyleft 义务。

## 已识别的主要组件

| 来源 | 已核实的许可证/范围 |
| --- | --- |
| DeepSeek Harness 与当前 `@deepseek-ai/*` closure | MIT；保留包内 LICENSE 和 DeepSeek 等原作者声明 |
| FastAPI、SQLAlchemy、Vue 等 | 按精确版本随包提供的 MIT 等原许可 |
| psycopg / psycopg-binary 3.2.6 | LGPLv3；发布包含它们的镜像/二进制时须核对源码、替换及告知义务 |
| cryptography 50.0.1 | Apache-2.0 OR BSD-3-Clause，按所选择分支履行义务 |
| DOMPurify | MPL-2.0 OR Apache-2.0，按所选择分支履行义务 |
| Lightning CSS | MPL-2.0；当前为构建依赖，不据此推断它进入前端 bundle |
| Cloudflare 构建链 sharp/libvips | 含 LGPL；多项为 dev/optional，不等于 Worker 实际包含全部平台二进制 |
| Python、Node、PostgreSQL 与容器基础系统 | 各自许可证；BYQ 的根许可不覆盖基础镜像和系统包 |

精确 npm 依赖声明见 [npm inventory](docs/legal/npm-license-inventory.json)，Python 直接依赖
见 [Python inventory](docs/legal/python-dependency-inventory.json)。清单按锁文件/构建声明生成，
**不是所有二进制发行物的合规证明**，也不替代包内完整许可证。更新依赖须重新生成并审核。

## 源码公开与二进制交付分开验收

本次发布为源码仓库公开，不发布新的预构建发行镜像或 Release 二进制。依赖锁文件记录
包版本，不表示复制了依赖源码。使用者按构建脚本下载的第三方包仍按其原许可使用。

后续每个实际发行物（前端静态包、容器、离线安装包、模型文件）发布前，必须：

1. 生成包含实际运行依赖、内嵌文件和系统包的 SBOM，区分构建工具与运行时。
2. 收集随包许可证和版权/NOTICE，并随发行物提供；前端 bundle 包含的组件也不能遗漏。
3. 核验选用的双许可分支、copyleft 源码提供、修改告知和用户替换等适用义务。
4. 发现未知来源/缺少许可/不兼容内容则停止发行，不把“安装成功”当成许可已解决。
5. 不随包分发正式数据库、凭据、受限行情缓存、用户对话、私有策略和无授权模型/数据。

## Community 与贡献

Community 的第三方 AGPL 内容不能改标 BYQ 许可；维护者本人原创的另行授权边界见
[OWNERSHIP.md](docs/legal/OWNERSHIP.md)。引入第三方片段须记录原始 URL、精确版本/提交、
文件/片段、许可证、修改与发行义务。CLA 不会使原第三方限制失效。

仅引用上游文档或研究其行为，不表示获得复制全部原文/源码/素材的许可。本文件不能
视为任何第三方权利人的额外授权。疑问请经 [维护者主页](https://github.com/jefison-x) 联系。
