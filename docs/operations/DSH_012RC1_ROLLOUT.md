# DSH 0.1.2rc1 发布、观察与回滚方案

状态：PLANNED。仅在[主方案](../roadmap/DSH_012RC1_UPGRADE_PLAN.md) U6/U7 前置条件满足后执行。
本文没有部署任何版本，不包含可直接复制的生产容器删除/卷替换命令。

执行身份：ADR-0059 下另行授权的 trusted operator；U0–U6 开发/合并不自动授予生产权限。
部署前确认本任务授权、平台合并门禁、实际 merged revision 与本次服务白名单，不能沿用失效的历史授权。

## 1. 发布对象和兼容矩阵

U6 必须根据实际代码把以下组合逐项测试，填入 exact image/release/policy hash：

| 组合 | Backend/MCP | Runtime | 用途 |
|---|---|---|---|
| B0 | 升级前生产版本 | 旧 DSH | 只读基线 |
| B1 | U2 后兼容准备版本 | 旧 DSH | 默认、准备部署；必须完整可用 |
| C1 | 兼容准备版本 + 已认证候选 policy | 新 DSH | 隔离认证 |
| P1 | 兼容准备版本 + 正式晋升 policy | 新 DSH | 生产目标 |
| R1 | 与新旧已存证据兼容的准备版本 | 旧 DSH | 生产回滚目标，不一定等于 B0 的全部镜像 |

Backend 镜像包含 Plugin Registry，MCP 可能包含 provenance projection，Runtime 还包含 profile/identity。
因此 U7 的实际部署服务清单由这些变化推导，不预设永远只重启 runtime-adapter。
纯 DSH 后续升级如果无需改变业务服务生成投影，则只更新对应运行服务。
生产 PostgreSQL、行情/ML/信号 Worker 不因 DSH 版本切换而重启或改变数据。

## 2. 必须先解决的部署细节

### 镜像身份

- ADR-0059 的 local-ci 已采用 run-scoped build/test 镜像；U1 复用隔离机制并新增 candidate release/attestation 选择。
- 候选不能覆盖当前/回滚的唯一可用 tag。按 Git revision/release ID 标记构建，记录实际 image ID/digest。
- 单机尚无远端镜像仓库时，允许受控本地 immutable tag + image ID + 导出校验；不要假称已有 registry digest。
- 多服务切换保存每服务的旧/新 image reference；部署恢复用保留制品，不在事故中重新解析 npm/PyPI。
- Dockerfile 中 Node/Python 基镜像必须记录实际解析 digest，防止相同代码重建时基底漂移。

### 生产配置

- 用只读检查核实 compose project、service、network、volume、bind port 与部署目录；不依赖历史猜测。
- 输出只含版本、布尔健康、资源 identity、数量；不打印 `.env`、完整 `docker compose config` 或容器 Env。
- U6 输出一份去密的部署 manifest，列出将修改的服务、镜像、配置 hash、会话 namespace 和回滚目标。
- secrets 通过现有安全途径注入；不写进镜像、Git、证据或 PR。
- SDK 默认继承环境；必须验证 candidate 实际看到的环境只含所需凭据和上下文，不能因新 home/profile 扩大凭据来源。

### 会话存储

- 每个 DSH release/private generation 使用独立、可验证的 home，保持在已分配 Agent volume 内。
- BYQ skills/profile 和本地 runtime plugin root-owned/read-only；会话数据目录才由 runtime UID 写入。
- 不用旧目录冒充新 `dsh_home`；不共享可写 settings、plugin discovery 或 session journal。
- 新版运行不需要原地读取旧日志；Gateway 提供 ADR-0046 的有界公开对话上下文。
- 回滚时新建旧版 private generation，不读取新版独有日志；新日志保留作受控诊断。

## 3. 发布前备份与恢复证据

U6 在隔离栈演练，U7 对已核实的正式资源执行：

1. 保存旧 runtime 及本次会修改服务的镜像 identity、可恢复镜像、release/profile/policy 文件与 hash。
2. 识别正式 BYQ PostgreSQL 和 Agent/WorkflowTrace 卷的真实资源 ID；Community 数据不在范围。
3. PostgreSQL 使用逻辑备份；DSH 会话/WorkflowTrace 在停止新 turn、活动回合收口后进行一致性备份。
   不物理复制 PostgreSQL data directory，不把不同时间的备份伪称为原子快照。
4. 备份放在管理员选定的持久安全路径，限制访问；路径不能只依赖可能自动清理的 `/tmp`。
5. 记录字节数、SHA-256、创建时间、备份对象、可读验证与权限；`pg_restore --list` 只算可读，
   恢复成功需在隔离数据库实际 restore 并验证持久对象数量/关键关系。
6. 已有近期可验证备份可复用其恢复演练证据，但发布前变化必须有明确覆盖；不宣称旧备份含新数据。
7. 本次回滚不恢复生产业务数据库。新训练/回测/审批/证据在升级期间产生的合法记录必须保留。

备份/回滚保留建议：至少覆盖 7 天及维护者确认升级稳定，以两者较晚为准；空间不足先报告实际占用和方案。
到期不自动删除镜像或备份，清理需明确目标和权限。严禁 `docker system prune`、`volume prune`、`down -v` 操作生产栈。

## 4. 排空与短时维护

单机 Compose 没有天然逐会话蓝绿路由。不要为本次升级临时引入双 Adapter 共享会话的架构。

U6 选定并实测以下一种方式：

1. 如已有可用的运维 admission gate，阻止新建 turn/continuation 提交，保持现有 SSE 和活跃回合完成；
2. 如没有，增加最小、工程端配置的聊天维护 gate，或使用已验证的聊天维护窗口。

gate 的必要语义：

- 门禁状态能跨所需 Gateway 实例生效；单实例内存开关不冒充持久全局控制。
- 拒绝新输入使用现有安全错误结构；浏览器保留输入并允许之后重试，不能显示已开始。
- continuation 保持 durable queued/retryable；响应丢失用既有 idempotency，不创建新的审批或领域任务。
- 与正在进入的 prompt 做竞态测试；不能只读取一次 `active_prompts=0` 就开始切换。
- pending approval 可以跨版本继续存在，不要求用户为了发布全部批准。
- 对正在运行的大型 ML/data job，只观察 Domain state，允许独立 Worker 继续运行。

等待时长最多采用已配置 whole-run ceiling 加 shutdown 宽限。超出后先定位任务，不静默 kill 活跃用户回合。
只有已有授权明确覆盖中断，才按现有取消机制终止并保留可见失败/恢复说明；否则暂缓切换，继续独立检查。

## 5. U7 操作顺序

每步记录开始/结束/结果；失败进入下一节回滚判断。

1. 确认发布授权、U6 全部结果、目标 exact artifact/image/hash、旧 R1 制品和备份可用。
2. 确认当前 PR/主分支状态与部署源码；禁止从脏工作树、未审查候选或 floating tag 部署。
3. 先准备并验证新旧兼容的 Backend/MCP 配置/镜像（若涉及），仍使用旧 DSH 完成最小 smoke。
4. 打开已验证的 admission gate，检查 active turn、owned child、待续接审批和 Worker 状态，等待回合收口。
5. 执行会话一致性备份；保存新的部署 receipt 和旧 image references。
6. 在无模型回合状态下切换 registry/provenance policy、Runtime release/profile/home 命名空间及必要服务。
7. 对实际变更服务使用已验证 compose/image 操作，保持 `--no-deps`，不重启数据库/Worker 链。
8. 核对启动日志安全摘要、SDK/runtime/carrier、installed metadata、profile/hash、MCP 连接和 readiness。
9. 门禁期间做 operator 允许的验证；验证请求走测试专用路径/用户并保持原授权，不能为 smoke 打开临时公开绕过。
10. 解除门禁后执行已有授权的无副作用小巴 smoke，确认正常输入、最终回答、失败可见性及旧公开对话恢复。
11. 确认 Plugin Center active 与目标一致，而不是只看 desired/generated；没有资格的插件仍不能启用。
12. 记录公开服务状态、PostgreSQL/Worker uptime、备份/回滚位置；进入观察窗口。

U6 应生成具体实例的发布/回滚命令，并用这些命令完成演练。不得从本文占位名称直接组装生产命令。
不把审批、创建 ML 或发布 Issue 当作只读生产 smoke；这些流程已在隔离环境验证。

## 6. 回滚触发与执行

以下任一项属于立即停止晋升/回滚的红线：

- 身份不匹配、MCP 无法认证、required role/tool 缺失、新增危险工具或跨用户可见。
- 长推理再次被误杀、child 不能交付、root 无终态、超时被显示为普通空闲。
- 同一意图产生重复 ML/回测/反馈、审批续接越权或丢失。
- secret/raw reasoning 泄漏、未批准日志上传、会话目录串写。
- 生产必须功能不可用，或资源持续增长接近已定容量边界。

普通 provider 临时 429/网络失败先按错误类别识别，不把所有模型错误都归因于升级；但不得无限等待掩盖故障。

回滚步骤：

1. 保持或重新开启 admission gate，保存去密诊断与 exact image/release identity。
2. 停止分配新 turn；按既有政策收口 owned DSH process，避免旧新运行实例同时处理同一会话。
3. 恢复 R1 的 runtime 镜像、release/profile 和命名空间选择；如需协调服务，恢复已验证的新旧兼容准备版本。
4. 不恢复 B0 的严格旧 evidence validator，除非已经证明它能读取/处理升级期间产生的新来源证据。
5. 保留现有 PostgreSQL/Artifact/审批/Worker 状态。恢复 Product conversation 时创建新私有 generation，
   从 BYQ 已完成公开消息恢复上下文；不将新版 DSH JSONL 转换给旧 SDK。
6. 对未确定是否执行的动作，先读取 BYQ 权威状态和幂等记录，不能自动再次提交。
7. 验证旧 runtime ready、只读回合、pending approval 的继续处理、后台 Worker 正常，然后解除门禁。
8. 记录 U7 ROLLED_BACK、用户可见影响、故障类别、保留证据和下一步；不能写“升级完成”。

若 R1 也无法恢复，保持最小聊天维护状态，保留可用的业务页面/Worker，报告具体阻碍；禁止扩大数据库恢复范围自救。

## 7. U8 观察与完成标准

发布后目标观察 24 小时、首 30 分钟完成密集初检。观察使用现有运维指标/有界查询，不定时下载全部日志或会话。
如果没有获得连续监控授权/工具，保存阶段状态并明确尚待观察；不能结束 turn 就声称完成 24 小时观察。

| 指标 | 重点 |
|---|---|
| 会话终态 | failed/timeout 原因、没有终态的 active run、取消后复活 |
| 子 Agent | active child 数和年龄、结果已到但 root 未结束、跨回合晚到事件 |
| 审批续接 | queued/submitting 年龄、failed 类别、重复 submitted/executed |
| ML/回测 | 同意图对象数量、重复动作、既有 job 的状态/lineage 连续性 |
| 身份与资格 | 实际 release/profile 与目标一致、desired≠active 时诚实显示 |
| 资源 | owned process 收口、CPU/RSS、session 磁盘增量、Worker/数据库运行状态 |
| 用户体验 | 最终答案、明确失败原因、旧对话追问、列表加载行为 |

缺少业务流量时不能用零错误声称场景全覆盖；补授权的隔离样本，并在报告中说明生产样本范围。
U8 完成需记录观察起止、样本数、异常处置、当前/回滚制品和后续升级 dry-run 结果。

## 8. 发布证据模板

```text
Release decision: READY / BLOCKED / DEPLOYED_OBSERVING / COMPLETE / ROLLED_BACK
Authorization reference:
Target release / Git / image references / composition / policy hashes:
Previous compatible rollback references:
Affected services:
Baseline and candidate test reports:
Live-model report and browser review:
Backup identities / integrity / restore rehearsal:
Admission gate and drain results:
Production installed identity and smoke results:
PostgreSQL / Worker status:
Observation start / end / sample counts / limitations:
Rollback triggers or actual rollback record:
Retained resources and retention owner:
Next authorized action:
```
