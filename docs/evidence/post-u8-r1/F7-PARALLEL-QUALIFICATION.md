# F7 并行子任务探针：保留失败与适用范围

2026-09-08，独立 post-u8.12 scope `post-u8-f7-parallel-20260908-12`，
脚本 Provider、真实 Product/Gateway/官方 Runtime/MCP/Backend/PostgreSQL，无付费请求。
本记录不修改生产配置，不把失败测试改记为 PASS。

## 实际结果

根模型在同一响应发出两个 strategy 委派调用；Provider 在每个 child 的第二次请求
设置双参与者、12 秒有界屏障，要求两个请求实际重叠后才返回无效领域调用。
屏障未满足，首 child 先退出，再开始第二个 child；本地 Provider 最终 12 次请求，
root 5 次、child 1 为 3 次、child 2 为 4 次，根最终 `model-run-failed`。
探针要求的 `domain-correction-stopped` 断言失败，ML 并行场景没有执行。
合成会话：`conversation_79fa2a27b1f742f38b9f09b599a11a6a`。

## 只读原因核查

BYQ 当前根隔离组合 `plugins/dsh-byq/profiles/root-scoped/dsh-0.1.2rc1/byq-product.yml`
明确 `agent-loop.config.maxParallelToolCalls: 1`，不是“官方默认必然串行”。
在实际候选容器运行官方 launcher `--profile sdk --patch ... --dump-config`，
只输出并行字段，退出 0，实际值确为 1。

锁定官方源 `a66e4702047846cdaa10c66c9d3df3951f5ea70d`：
`packages/core/agent-loop/src/index.ts` 文档明确 1 为串行；默认常量为 10。
`packages/subagent/tool-subagent/src/index.ts` 委派本身声明 concurrency-safe，
所以不能把本次失败解释为官方不支持并行。BYQ 当前配置限制了同一步委派的在途数量。

结论：同根原生并行兄弟调用对**当前显式串行组合**不适用；本探针结果保留 FAILED，
不通过修改应用并行设置来制造绿色结果，也不推广为所有并发风险已消失。
此前连续兄弟的真实资格仍有效；Backend 并发认领、网络迟到旧 HTTP 与新根的竞争
是独立矩阵，仍需各自证据。若未来改变并行设置，必须重新执行该资格探针。

保留脚本：[Provider](f7-parallel-provider.py)、[驱动](f7-parallel-probe.py)。
脚本只适用于全新隔离合成栈；无生产写入、外部 Provider、训练或回测。
验证后执行精确 scope 清理，cleanup verified；测试容器、合成卷、网络和镜像标签已移除。
