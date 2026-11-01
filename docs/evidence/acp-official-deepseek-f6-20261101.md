# 官方 DeepSeek F6 实现与验收检查点 — 2026-11-01

**实现定向门禁 PASS；真实官方 F6 NOT_RUN。** 原账号正常登录尚未完成，
`/api/auth/me` 返回401；没有为本轮提交新模型输入、新 SignalJob 或业务审批。
15分钟真实批观察窗口尚未开始，不能记为 outcome_unknown 或真实 F6 PASS。

## 范围与源码

- 维护者明确接受 [ADR-0116](../architecture/adr/ADR-0116-official-deepseek-f6-qualification.md)，授权隔离实现和一次有界真实验收。
- 分支 `codex/acp-real-f6-qualification-20261101`；应用源码 `771cd22c816f9fac8e32b0883c6a1611b1329002`，测试断言修正 `dd1ae266`；基点 `772570c1`。
- 用户级执行参数及已完成 Product 设置验收复用 [现有证据](user-agent-execution-options-20261101.md)，没有改回会话级设置或修改原用户参数。
- 新增独立 `task-ready-read.official-deepseek.v1`，只接纳 `deepseek-official/deepseek-flash`、`https://api.deepseek.com/anthropic`、`/v1/messages`。旧 Go profile、hash 和历史收据保留。
- 新 reservation 采用 owner 的持久 `byq-product` 模型绑定；路由解析不读取或解密 key。旧事件先返回原快照，不因当前设置或绑定变化重建。
- Runtime 在 START 前验证 profile 与原生会话实际 provider/model 一致。proxy、native overlay/guard 与 Runner 校验同一有限 profile、工具范围、用户选项和新 Root 身份。
- 复用 Messages 终态及实际 token 用量处理；缺失终态或不可证明用量保持 unknown，不补零、不重发。null 数值选项不生成16次/180秒等隐含上限。

## 实际定向检查

日志根目录：`.ci-artifacts/acp-real-f6-qualification-20261101/`。

| 检查 | 实际结果及证据范围 |
|---|---|
| Contract | Worker 工具会话报告10 passed；文件日志 NOT_CAPTURED |
| 隔离 PostgreSQL Backend | Worker 工具会话报告6 passed；凭据模块及并发/source-fact 回归另一次25 passed；日志 NOT_CAPTURED。临时数据库容器和网络已移除 |
| Runner 新旧路线定向 | Worker 工具会话报告4 passed；日志 NOT_CAPTURED |
| Runtime 五模块 | `runtime-focused-five-modules-20261101.log`：167 passed、1 failed；唯一失败是新增测试误断言 fixture 已准备的 generation 为空 |
| Runtime 失败用例复验 | 修为拒绝前后 generation/harness/active_run 身份保持不变，仅重跑失败 node，`runtime-focused-failed-node-rerun-20261101.log`：1 passed；应用源码未变，不倒写首轮结果 |
| Gateway 接续派发 | `gateway-delivery.log`：104 passed，包含官方 carrier 的精确派发 |
| Native JS guard | `native-js.log`：18 passed，包含官方 profile、工具限制及重算 hash 后的错误配对拒绝 |
| 架构、语法与隔离工作树 | `architecture.log`：73 passed；`dev-check.log`：local syntax PASS、remote CI REQUIRED；worktree 检查和 diff check PASS |
| 独立 Sol Reviewer | Functional PASS（源码）、Tests PASS（受影响定向范围）、Clean Break Architecture PASS；不包含真实 F6/Product 资格 |

原失败不覆盖：新增 JS 测试最初使用了错误方法/ready-row 断言；Gateway 首轮因工作目录
加载旧镜像 contract 而失败；Runtime 首批两次 namespace 导入失败及只读嵌套挂载失败
均未执行功能测试。核对实际布局、源码导入路径及原生入口后恢复测试，没有增加 harness。
相关文件日志保留；未写文件的准备命令输出只在工具会话，标为 NOT_CAPTURED。

Runner 额外广检不是全套 PASS：Host 报10 passed/10 failed（缺少 no_new_privs）；
容器报18 passed/2 failed。两例是 `test_workspace_mismatch_is_signed_and_never_creates_a_cwd`
和 `test_forbidden_authority_environment_is_rejected_before_consumption`：拒绝及不创建 cwd
已成立，随后未改的 state-dir bootstrap 文件与旧空目录断言冲突。Root 认定与本次
profile 路线扩展无关，保留 FAIL；这些输出文件日志亦为 NOT_CAPTURED。

## 保留测试环境

- 5个局部 overlay 镜像构建成功；`candidate-source-readback.json` 核对16个必要源码文件匹配。
- 只更新测试 Backend/Gateway/Runtime/Runner，镜像固定为核对过的 image ID；4角色 healthy，Frontend/MCP 原容器和镜像保留且 healthy。
- 原4角色停止并保留为回退材料，所有原挂载完全一致，未清理数据、卷、备份或历史实验。
- Frontend 仅重载 nginx 以刷新 Gateway 地址；未导航或关闭原测试页面。
- `environment-verification.json`、`before-environment.json`、`after-environment.json` 证明17个 `beyondquant-*` 运行栈容器 ID/镜像未变。
- 新 Runtime 活动会话、输入、held/awaiting ACK/cleanup 均0。队列最近只读核对为7个 completed；真实提交/Worker启动前仍需刷新队列。
- 新 Signal Worker 仅构建、源码核对及离线 import PASS，未启动；旧 sandbox 的 server/runner/bars_frame/依赖声明与仓库匹配，仍停止。
- 私有配置和回退材料位于工作区外 `~/.local/state/byq-maintenance/acp-official-f6-20261101/`，没有把凭据写入 Git 或测试输出。

原页面保留：`http://127.0.0.1:32790/agent?session=conversation_f3c32849e1ba48a9ab7e19348e232cfd`。
单独打开的 Playwright 正常登录窗口停在 `/login`，没有读取个人浏览器存储、重置密码
或复制其他用户凭据。

## 下一项未闭合门禁

原账号在独立窗口正常登录后，按 ADR-0116 只执行一次有界真实链：新 conversation/task、
准确业务审批、最多一个 SignalJob、两个前台输入和一次自动后台输入。只使用已验证的
现有市场数据，核对 Job/Artifact、只派发一次、新 Root/MCP、正确 native session、
实际用量/结算、terminal ACK/cleanup 和持久化结果刷新。通过前真实 F6 保持 NOT_RUN。

Root PASS 仅覆盖实现、定向证据和保留环境准入。当前没有 push/PR/hosted CI、merge、
release 或运行栈部署；Phase17 保持 OPEN，未启动 Phase18。
