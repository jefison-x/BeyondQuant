# F6：公开模型调用拦截接口复核

日期：2026-09-10。范围是 ADR-0065 的接口资格调查，未实现预算执行器或开启后台续接。
工作区为 `post-u8-interface-audit`，沿用已有隔离维护分支；本轮不更新主工作区。

## 本轮新增结论

找到了可继续验证的公开接口：`@deepseek-ai/dsh-llm@0.1.2-rc.1`
发布包的 `lib/types/index.d.ts` 声明 `llm/stream` waterfall，接受完整请求及 `next`。
`lib/index.js` 的 `streamWithRegistration` 将 waterfall 放在 `adapterStream` 之前。
因此不能把“Python SDK 没有预算参数”扩大为“官方不存在公开拦截接口”。
这只是接口存在与静态位置证据，不是全调用预算执行资格通过。

Python SDK 的 `HarnessClient` 则将通知入队，由 `NotificationSubscription.drain`
消费；`on_notification` 不构成 Runtime 每次 Provider 请求前必须等待的批准回执。
仅在通知回调里累计用量或发取消，不能据此证明超额请求尚未发出。
通用 `request/respond` 的存在也不能证明 Runtime 暴露了预算准入协议。

## 精确制品与取证方法

未安装或执行新 npm 包。通过 npm registry 读取准确版本 metadata，下载 tarball 到
内存，逐包核对 registry 声明的 SHA-512 integrity，仅读取归档内 JS 和类型声明；
不提取到应用、不运行安装脚本、不改变锁文件。registry integrity 校验不是独立发布者
签名验签，也不证明 npm 包与 bundled executable 的依赖逐项相同。

| npm 包（均为 0.1.2-rc.1） | tarball SHA-256 |
|---|---|
| `@deepseek-ai/dsh-llm` | `1132f9402c23b275345728a3d209ef2fc9286ebb7604276ce725f73fd77382e1` |
| `@deepseek-ai/dsh-llm-retry` | `2587234f8f1c8ff808239eb87c6edb2ae7c344efed176575fba1a321773a1d52` |
| `@deepseek-ai/dsh-token-meter` | `c7eefd9e7013ce7925101d61c298640c28c768c070579090089d43247f0504d2` |

registry metadata 可由 `https://registry.npmjs.org/@deepseek-ai/dsh-llm/0.1.2-rc.1`
取得，另外两包替换包名即可。首轮误按 `dist/index.js` 查找没有命中；随后按实际
`lib/index.js`、`lib/types/index.d.ts` 读取，不能把路径未命中算作接口不存在。

官方上游源码另固定在 `b2e3b2a0125854567a4a5fcba75782e42fe84901`，只作解释性参考：

- [LLM 公开接口](https://github.com/deepseek-ai/deepseek-harness/blob/b2e3b2a0125854567a4a5fcba75782e42fe84901/packages/llm/llm/src/index.ts)
- [重试实现](https://github.com/deepseek-ai/deepseek-harness/blob/b2e3b2a0125854567a4a5fcba75782e42fe84901/packages/llm/llm-retry/src/index.ts)
- [计量器](https://github.com/deepseek-ai/deepseek-harness/blob/b2e3b2a0125854567a4a5fcba75782e42fe84901/packages/llm/token-meter/src/index.ts)

上游 master 与发布包不同层次的证据不能混用。猜测的 `v0.1.2-rc.1` Git tag 查询返回
404，未据此推定 release commit；没有升级 DSH。

## 覆盖判定

| 资格项 | 本轮证据 | 判定 |
|---|---|---|
| 公开调用前接口 | 精确 npm 包的类型声明及 adapter 调用前 waterfall | 候选接口存在 |
| 当前 Python SDK 直接准入回调 | 签名与通知队列实现只读检查 | 未证明具备 |
| 当前 bundled executable 可加载同一接口 | 二进制含接口名，但未加载验证 | 未通过；字符串不能作为资格 |
| 根请求超额前拒绝 | 既有 max_tokens 多步反例再次通过 | 现有参数不满足累计上限 |
| 子 Agent、搜索、压缩 | 尚无该接口逐路径实际阻断证据 | 未验证 |
| 重试 | 精确 retry 包使用 `agent/request-error` 返回 retry 决定 | 不能据静态位置推定所有重试受控 |
| Provider 内部重试、并发 | 尚无每次 HTTP 发出前唯一预留证据 | 未验证 |
| 输入上界、输出上界与可信唯一结算 | 尚无覆盖所有模型/调用的执行器 | 未验证 |
| PostgreSQL 预留、重启、撤销竞争 | 本轮未实现执行账本 | 未验证 |

下一资格切片应在锁定 bundled runtime 的隔离环境验证受支持的加载方式，随后以
loopback Provider 记录实际请求，证明拒绝发生在 HTTP 之前。根请求先通过，再分别扩展
子调用、搜索、压缩、两类重试及并发；任何不经过拦截点的请求都使全覆盖资格失败。
还须证明输入的保守上界，不能用 token-meter 的估计值直接充当硬保证。
全过程保持现有 ADR-0038/0065 边界，不借此授权新包安装、Provider 代理、私有 hook 或 fork。

## 已运行验证与限制

使用既有 retained candidate 依赖镜像，以 `--network none`、只读挂载当前
`test_dsh_budget_semantics.py` 运行原有两项资格测试：**2 passed，2.34 秒**。
脚本 Provider 仅容器 loopback、合成凭据，无外部模型或业务工具调用。
测试证明当前 Product composition 有计量器但未加载 agent-budget，以及同一回合
可发出两次 `max_tokens=8` 请求；绿色表示反例成立，不表示 F6 合格。

只读镜像内检查所得 bundled executable SHA-256：
`8ae368a6c2bfbe46a1f11e4f80926c27f2bfe342bff1e370157d0a5240744302`；
SDK `client.py` SHA-256：
`78193d6b88d49b87dc0057ec92cbc512426e7712f75c3e700f0fc7e0046d28fc`。
SDK/runtime distribution 均为 `0.1.2rc1`。retained 镜像只用于依赖资格探针，
不是对本分支应用实现的重新认证。

日志位于忽略目录 `.ci-artifacts/f6-budget-interface/QUALIFICATION.log`。
日志 SHA-256：`a19a2aaa76816419c2eb1dd7ca97a86a3c1b7bd57a7c1d6a01ea9521e61269ba`。
架构/共享合同 228 项通过；文档检查通过；`f6-budget-inspection` scoped 资源核验为零。
本轮只更新证据与状态文档，不改 bound source，因此不创建新 build revision。
F6 仍未完成，后台执行保持关闭；执行预留/结算、消费者和完整业务验收继续待办。
