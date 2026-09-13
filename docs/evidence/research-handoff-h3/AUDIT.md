# H3：有限授权交接验收

2026-09-13。维护者在 H2 本地交付后明确“继续”，本批实施 H3；不授权生产任务续跑。
独立分支 `codex/research-handoff-dispatch-0913` 基于 H2，本批不推进 Product Phase。
本地开发、验证与提交；未推送、合并、部署。独立构建身份 `.55`，历史清单保留。

## 实现范围

- 新确认许可允许一次原任务交接；之后新策略审批领域制品可触发新的交接。
- 复用 F6 原队列消费、单个任务预算账本、精确回执与 Runtime qualification，不增加 Harness。
- 旧许可重放不补新标记；普通模型回合结束不会自发产生下一轮。
- 前台回合、待审批、非终态作业和已登记未知业务回执阻止新交接。
  尚未发送的交接等待时不消耗发送尝试或模型回执核对次数。
- 初次并发认领只产生一个 reservation；未知结果不重新发送、不返还额度；取消/撤销/到期等原门禁保留。
- Backend/MCP/DSH 的权限边界、后台工具白名单与期限不变，训练创建等原限制仍执行。
- 修复真实 HTTP 环境下许可面板调用 `crypto.randomUUID()` 崩溃，复用已有 `createRequestId()`。

详见 [H3 合同](../../contracts/research-domain.md)。完整三轮模型研究、选优与模拟账户闭环仍属 H5。
缺少检查点、精确制品、许可或明确阻塞的任务不会因此自动恢复；历史生产研究未处理。

## 验证证据

| 检查 | 结果 |
|---|---|
| Backend H3/F6 许可、通知、预算、工具范围和 H2 回归 | 64 passed |
| 最终等待不消耗核对次数修正：H3+通知回归 | 13 passed（上项子集重跑） |
| Gateway 续接投递、许可和回合准入 | 32 passed |
| 许可面板与请求 ID 兼容性 | 10 passed |
| 前端类型检查及构建 | 通过 |
| 架构 unittest discovery | 124 passed；不冒称所有 pytest 架构测试 |
| 桌面1440/手机390真实浏览器 | 2 passed |
| dev-check、隔离工作树、`.55` 清单 | 通过 |

浏览器功能检查：真实身份登录；看到新许可范围；选择本任务已验证资产；明确填入额度并确认；
Product API 持久保存许可；测试侧可信消费者通过 Backend 的 peek/claim 创建真实 reservation；
Product 页面显示后台续接已排队；用户撤销后 Backend dispatch 返回 false；刷新仍显示已撤销。
浏览器请求只到同源 Gateway/Product API，测试侧内部消费者不属于浏览器；无 pageerror 或跨源浏览器请求。
排队截图经查看，桌面和手机文字正常换行：[桌面](h3-queued-1440.png)、[手机](h3-queued-390.png)。

此验收未启动 DSH/模型：Gateway 自动消费者明确关闭，Backend 启用 F6 后仅由测试侧内部请求认领，
在真正发送前撤销。真实模型资格、实际模型执行及完整业务闭环不在本次浏览器证明范围内；
复用发送链的精确回执/丢回执行为由上述 Gateway 回归覆盖。

## 环境、失败记录与重跑

Backend/Gateway 测试用已有 `.42` 镜像提供依赖，当前工作树源码只读挂载，数据使用独立内网及 tmpfs PostgreSQL。
前端为本工作树构建物；没有调用生产数据库、生产会话、真实模型或付费 Provider。
`.55` 应用镜像未构建，远端完整组件 CI 未执行；这些验证不冒充发布资格。

可重复夹具：`scripts/evidence/h3-handoff-fixture.py` 要求 `BYQ_H3_FIXTURE=1` 且数据库名为
`byq_domain_test`；每轮用新的 `BYQ_H3_BROWSER_USER=h3-browser-<suffix>`，不重置或替换旧许可。
浏览器文件为 `apps/frontend/tests/e2e/handoff-continuation.spec.ts`，须明确设置 `BYQ_H3_E2E=1`、
隔离 Product origin 与测试 Backend origin；普通 E2E 默认跳过，不能把跳过当成通过。

首次真实 HTTP 验收暴露 `crypto.randomUUID is not a function`，已修复并在同样 HTTP origin 重跑通过。
测试选择框/复选框原先点击被样式遮挡的原生 input，后改为点击用户可见文字，不使用强制点击或接口 mock。
原失败 trace 保留在本机 `/tmp/byq-h3-browser-http-failure`、`/tmp/byq-h3-browser-selector-failure`、
`/tmp/byq-h3-browser-checkbox-selector-failure`。

清理已验证：本批4个服务/数据库容器及内部网络均已删除，tmpfs 数据库没有持久卷遗留；临时依赖链接已移除。生产栈未改动。
