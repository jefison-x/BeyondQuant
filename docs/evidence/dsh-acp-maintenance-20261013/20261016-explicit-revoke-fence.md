# 显式撤销围栏：源码门（2026-10-16）

专项维护，不推进 Product Phase。起点为 `6519deff9fa902a0242954aeb7f373a6dafb93ba`。

## 必要修改

- Backend 在原 Task 锁内保存用户显式撤销，并围栏准确同 owner、Workspace、conversation、Task 的合法 v3 记录。尚未派发的预留取消；已接受或结果未知的记录保留原身份和责任，记录停止意图；终态不改写。
- 原有 reserve、claim、dispatch 和意图投影复查撤销。重复撤销可补围栏。损坏历史行原样保留，不能因旧视图投影失败而回滚已经提交的停止意图。自然过期与参数关闭仍分别处理。
- Gateway 复用原有持久取消记录和精确 Root 取消路径。控制取消 ACK 不代表终态；准确终态先经现有生命周期 close/ACK，再核对结算、游标排空和清理，证据齐全后释放。待取消期间继续核对回执，不派发新提示。
- `cancelled / dispatch_attempts=0` 使用准确 Backend 准入事实和 Runtime 无反证组合核对，不要求旧记录具备取消时间戳，也不把 Runtime 缺失单独当作未执行证明。

撤销与跨服务派发不是分布式原子操作：dispatch 先赢 Task 锁时，旧响应仍可能跨过启动边界；该执行保留未知责任并按同一身份取消、核对，不承诺撤销响应后物理上零启动或零副作用，不重放、不退款、不换 Root。

## 静态验收

仅三文件变更，源码冻结 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `services/backend/app/research_continuation.py` | `b7b90f04f8bb6a2bf3b80636e3bfff82ae0cc7564e93650ecb9325e70efc2509` |
| `services/gateway/app/main.py` | `1bc68932a4ff0ab2131d8379f755c455aef8745de3650f4a942d00b6644b5fbb` |
| `services/gateway/app/task_continuation.py` | `99e7363806ffc8954eedbbf5dedfcc69b3e344983756599b1d2e91f6f66cb1cf` |

Python 语法编译与三文件 `git diff --check` 均原生退出0、输出为空。独立 Sol v4 静态复审 PASS，收据 SHA-256 `c5eecf302464029099a8787387a834220eae8e09e9952313700606516114b932`；Root 仅验收源码门，不冒充功能通过。

v1、v2 的 HOLD 对象、差异和收据原样保留。v3 因冻结后源码漂移被哈希守卫拦截，没有最终 PASS/HOLD；v4 重新冻结检查。私有原件位于 `.ci-artifacts/agent-origin-consumer-20261015-v1/explicit-revoke-fence-20261016-v1/`。

## 未完成边界

本片功能测试、镜像更新、浏览器、真实模型、Job、生产、完整 CI 与推送合并均 **NOT_RUN**。无效的历史非空撤销时间继续阻止新派发，但不声称已有 accepted/unknown Root 已自动取消；这类历史歧义仍需核对，不伪造时间戳。

后续只在镜像与隔离更新门通过后，按已修正的[浏览器后验清单](20261016-browser-post-observation.md)另行声明有限真实批次。15项执行参数保存和执行验证仍按维护者要求延期。保留环境、页面、身份与原始失败证据。

## 后续隔离更新与取消核对（同日）

`ccaf122538598ee3b30f6498e0b29b9fc15eb5e6` 已安装到隔离 Backend/Gateway，镜像为 `7159000a…` / `ed5e8601…`。相对前版仅增加24279/4593字节，层数仍42/26；其他14容器和全部16挂载图不变，运行12文件读回一致。安装及原页面刷新前后6篇文章全文相同均经独立 Sol→Root 限定PASS。

随后在原任务会话中仅新建1个合成 SignalJob `signaljob_b42e34fb5467485bbeebe9316fe7ed2e`，确认准确 v3 接续正在运行后，通过浏览器点击1次软停止。源 Root `ae3da4ae4827447a8f9758e07a45b0f5` 完成并关闭；后台 Root `1e2cf8819710419cb51b633db3dede65` 取消并关闭，准确ACK225/240、结算摘要、签名清理和槽位释放吻合。源轮5次模型请求均HTTP200；后台官方结算报告5次请求及已知用量，未声称取得5条后台原始HTTP回执。原批因为Root把带前缀日志当作整行JSON解析而保留 **FAIL_OBSERVER_STOP**；保存原件的生命周期另经独立限定验收，第二条输入 **NOT_RUN**。

有限只读补证发现取消标记仍存在，停止后续测试。准确标记为397字节、`soft`、reservation `continuation_8137b08dc0e2b0d88eeb15e1c478644d`，身份匹配。实际通用 `/peek` 返回同一身份范围的旧终态 `continuation_37c78c7b983f7b23c2893b35563843cf`；Gateway准确ID校验拒绝替换，因此无法用该查询完成新标记的退休。此查询选择缺口已经独立审查确认，不推断每次历史tick或未观察的内存状态。

修复计划仅增加受既有 trusted consumer 保护的按会话和 reservation 精确读取，并替换Gateway三个取消核对读取点；普通 `/peek` 的候选顺序不变，未知结果和完整终态证明不放松。三个源码文件已完成实现、语法编译与差异检查，并经独立Sol→Root限定静态PASS（审查SHA-256 `3c013ac7c1edaab52b4fb536e3d5bb36f53c6ade9d2312a33aace62a7899fcd5`）；尚未安装或验证退休与新输入。保留原标记让正常流程在修复后核对，不人工删除、不重放Job。
