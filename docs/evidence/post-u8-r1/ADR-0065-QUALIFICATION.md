# ADR-0065 预算接口首轮资格核查

日期：2026-09-08。维护者明确批准 ADR-0065；开发工作树为
`post-u8-conversation-recovery`，分支 `fix/post-u8-conversation-recovery`。
本轮仅规范、资格测试；没有实现或启用后台执行，没有修改生产、历史研究或 release 身份。

## 锁定制品实测

官方 PyPI SDK `deepseek-harness-sdk==0.1.2rc1` 与
`deepseek-harness-runtime-bin==0.1.2rc1`，使用现有带 SHA-256 的
`services/runtime-adapter/requirements.candidate.lock` 构建测试镜像。

- 官方 launcher 的 `--help` 公开 `--profile`、`--patch`、`--dump-config`；未安装扩展。
- 对现有 sdk profile 加 BYQ Product patch 执行 `--dump-config`，确认含 token-meter、
  llm-retry、compaction-basic、web-search-deepseek 和 tool-subagent，未加载 agent-budget。
- SDK 配置签名有 max_tokens；已有 loopback 测试再次确认同一回合可发出两次各自带
  max_tokens=8 的请求。合成 usage 不是实际计费，不由此断言所有公开扩展均无能力。
- 所有命令均在 `--network none` 一次性容器运行；脚本 Provider 只监听容器 loopback，
  最多接受两次合成请求，没有有效业务工具、密钥、外部 Provider 或训练。

## 公开资料线索及边界

[官方配置目录](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/config-catalog.md)
区分部署配置与运行时扩展接口；当前 master 文档不能代替锁定 0.1.2rc1 的接口资格证据。
本次目录检索没有得到可直接启用的任务累计预算配置；这不是对全部 runtime-only seam 的否定证明。

另发现 [vibeinging/dsh-agent-budget](https://github.com/vibeinging/dsh-agent-budget)。
作者说明它是外置、单 Host 的 agent-tree 预算包，输入预留基于估算，不能保证精确计费。
仓库所有者不在官方 deepseek-ai 组织下；包名中的 scope 不能单独证明官方发布者身份。
未下载、安装、加载或执行该包，未把它记为 QUALIFIED。其概念不能替代覆盖测试或 ADR-0038
的官方发布者/准确版本/完整依赖资格门禁，也不能据此声称它必然兼容现有 SDK 制品。

## 结果与剩余工作

当前组合仍为 **预算执行资格未通过**，不是“累计预算已实现”。
根/子 Agent/搜索/压缩/重试的全部请求发出前上界拦截，以及重启、并发和结算覆盖尚无合格证据。
后台自动续接保持关闭；不得使用计量器、每请求 max_tokens 或 8 回合限制冒充累计硬上限。
账本合同见 `docs/contracts/task-continuation-budget.md`；持久账本、用户许可入口、
消费者及真实并发/丢回执/浏览器验收仍待实现。其他独立整改不由本资格缺口宣布完成或永久阻塞。

最终验证：Runtime 完整 suite（显式打开两项预算资格测试）120 通过、11 跳过、3 个既有
弃用警告（2.53秒）；架构及共享合同 83 通过、3 subtests 通过（0.99秒）。
新增清单测试第一次误用 import 名称查 distribution metadata 而失败，修正为锁文件中的
`deepseek-harness-sdk` 后通过；该夹具错误不计业务修复红灯。
测试使用锁定构建镜像，只读挂载新增测试文件，不挂载替代应用实现。
本轮不涉及 Backend/UI 实现，不运行无关全量数据库或浏览器测试；无付费调用、远端 CI 或部署。

验证后一次性预算/架构测试容器均已退出删除，预算测试名称查询为空；本轮专用 Runtime
镜像标签已删除，可按锁定依赖重建。没有创建数据卷或修改生产服务、Community 和私有备份。
