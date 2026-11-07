# ACP 空闲会话连续冷启动接续 — 2026-11-07

## 范围与故障证据

维护者接受最小修复并授权独立审查、PR/CI、合并、发布，先开发测试原会话验收，
通过后再部署生产测试环境。保留数据、原会话、页面、历史回执和回退材料，
不推进 Phase 18。合同见 [ADR-0114 窄修订](../architecture/adr/ADR-0114-local-domain-unknown-reconciliation.md)。

此前主线 `f2adebec` 的 Release Images `42325188885` 已成功完成 Full、发布和
manifest/SBOM/签名验证。开发候选服务健康，但原会话 `/resume` 返回 409；开发
应用已回退原配置和旧镜像，生产未部署。历史失败保留，不以发布成功代替产品验收。

原会话最后 Root 已结算、关闭、unknown=0，原生关闭、进程退出和清理均有证明。
第一次恢复留下已 acknowledged 的边界；未发送新输入就再次冷启动时，旧
`_recovery_boundary_authorized` 拒绝已确认关闭的跨 boot 边界。该函数在此前运行
镜像和 `f2adebec` 中相同，因此回退镜像不能消除这个既有 409。

## 最小变更

只在既有 Runtime 恢复授权函数中增加已结算、已 ACK、关闭/清理/排空证明完整，
且当前权威 epoch 严格更新的路径。原身份、事件摘要、回执和准确 trace tail 校验
继续生效；新重附仍须产生连续事件并由 Gateway 持久化、精确 ACK 后才能接收输入。
不重放旧 prompt，不修改历史事件或终态回执，不放宽未结算和未知结果保护。
现有未确认关闭的独立修复路径保持其原约束。

## 验证与交付边界

本文件记录源码交付前的检查点。私有原始证据位于
`~/.local/state/byq-maintenance/acp-idle-cold-recovery-20261107`。
后续 hosted CI、可信主线镜像发布和两环境 Product 验收分别记录，不由本地测试代替。

- Gateway 恢复与业务保护合同：24 PASS，包括未知结果、准确终态、原身份和 trace 边界。
- 架构检查：73 PASS；文档链接与语法检查通过。
- 初次 Gateway 单测容器因只读父挂载缺少嵌套挂载点而未启动，原错误日志保留；
  改为单个只读源码挂载后通过，不接应用网络、卷或凭据。
- Runtime 原生 Root 复用/重启合同：23 PASS；新增连续冷启动、未 ACK 拒绝、
  权威来源/回执/tail 不匹配、无重放及后续新 Root 独立 ACK。
  宿主缺少 `httpx` 未能收集测试后，改用已有固定镜像离线执行，未安装新依赖。
- 独立审查：Functional / Tests / Clean Break Architecture 全部 PASS。
- hosted CI、新提交发布/部署：当前检查点 NOT_RUN。

真实验收顺序：开发备份/部署 → 原会话正常账号登录并无 prompt 接续 → 再冷启动
开发 Gateway/Runtime 并接续同一会话 → 生产备份/部署及原会话接续。每步核对镜像、
健康、原消息/Root 回执/用户参数/研究任务台账哈希。应用失败只回退镜像配置，
不恢复数据库或改写旧绑定。所有运行环境和原页面保留。
