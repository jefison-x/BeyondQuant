# ADR-0084：门禁分级、外部依赖与可降级交付

- Status: Accepted
- Date: 2026-09-21
- Accepted: 2026-09-21（维护者明确接受本文完整决定，并授权同步修订相关 ADR、STATUS 与专项计划）
- Decision source: 维护者要求审查并合理化可能过严、阻塞后续开发的 ADR，并在审阅完整决定后
  明确接受。
- Relates: ADR-0003、ADR-0058、ADR-0059、ADR-0062、ADR-0064、ADR-0070、ADR-0071、
  ADR-0074、ADR-0079、ADR-0081、ADR-0082、ADR-0083
- Scope: 当前与未来 ADR、专项计划、STATUS 和机器门禁的阻塞语义；不授权生产部署、正式
  release/tag、破坏性数据操作、付费资源或绕过 GitHub 门禁。

## 背景

BYQ 已累积大量 Accepted ADR。历史上若干资格计划把以下不同性质的条件聚合为同一个
`GO/NO_GO`：安全不变量、当前功能完成、候选依赖资格、远期完整能力和正式发布验收。结果是
一个尚不存在的上游 DSH 能力也能冻结 0.9 收口、候选升级和后续架构阶段，即使 BYQ 已能如实
报告中断、隔离迟到结果并从持久业务状态恢复。

严格门禁仍然必要，但门禁必须阻塞正确的对象。安全失败不能被降级为成功；外部可选能力缺失
也不能自动变成整个产品路线的永久停止条件。

## 决定

### 1. 四类门禁

每项新门禁必须声明一种类型和明确的阻塞对象：

1. **Safety / Integrity Gate**：权限、租户隔离、凭据、时点正确性、不可逆数据操作、业务幂等、
   重复副作用、制品身份和伪造成功。影响范围内 fail closed；不得用风险接受、标签或降级绕过。
2. **Feature Gate**：只阻塞依赖该能力的功能及其支持声明。功能可以明确 unavailable、
   interrupted 或 limited；不得因此冻结无关功能、版本或维护任务。
3. **Promotion / Release Gate**：只阻塞具名环境、候选晋升或正式版本发布。开发、合并和其他
   已授权阶段可继续，除非它们直接依赖该门禁。
4. **External Qualification Gate**：记录上游、供应商、数据源或平台能力。缺失时保持
   `BLOCKED_EXTERNAL`，但只有在它同时属于已经确认的当前核心产品合同且不存在安全降级时，
   才能成为当前版本的全局阻断项。

任何 aggregate gate 必须保留成员类型；不得把一个 External Qualification Gate 通过聚合
悄然提升为 Safety Gate。

### 2. 可降级交付判据

外部能力缺失时，满足以下全部条件即可把它留作受限能力，而不阻塞无关版本工作：

- 用户和运维界面如实显示 unavailable、interrupted、lost 或需要确认，不显示成功或无缝续接；
- 旧 generation、旧 epoch 和迟到结果被 fence，已终结执行不会被重新打开；
- durable business job、审批、制品和 conversation identity 不依赖临时 runtime/terminal；
- 只自动重试合同声明为幂等且结果可核对的步骤；
- 写入、下单、发布、付费调用或结果未知的副作用先查精确回执/幂等键，无法确认时暂停；
- owner/workspace/authorization、审计、预算和取消语义继续生效；
- 降级范围、用户影响和上游复核触发条件有机器可读记录。

上述判据不恢复 DSH 私有内存、hidden reasoning、工具私有状态或子进程现场，也不授权 BYQ
实现第二套通用 Agent harness、session store、PTY runtime 或上游协议。

### 3. DSH 0.1.5-rc.1 / D15 的具名重分类

`subagent-child-crash` 和 `subagent-byq-adapter-restart` 继续保持真实的
`BLOCKED_EXTERNAL` Feature/External Qualification 状态，直到 DSH 提供并通过进程外
continuable provider 资格验证。历史 D15-4/D15-G verdict 不改写。

本 ADR 生效后，这两项不再是以下事项的全局硬前置：

- 0.9.0/0.9.x 收口；
- DSH 0.1.5-rc.1 候选兼容判断或生产晋升决定；
- R3 thin supervisor 的安全失败、观测、清理和新 generation 恢复范围；
- 与子进程原位续接无关的后续产品/数据/模型阶段。

取代其全局阻塞作用的当前必需门禁是 **BYQ session failure containment and business recovery**：
检测执行者失联；把未完成 run 标记为 `interrupted`；拒绝旧 generation/epoch 与迟到终态；保留
conversation、公开历史、durable job 和回执；按上节规则重新调度安全步骤；未知副作用暂停并向
用户说明。该门禁通过后，可以产生一个新的、具名的 D15 superseding assessment；它不得改写
历史 `NO_GO` 文件，也不得把未实现的原生子进程续接标成 PASS。

本重分类不自动切换 DSH 默认 selector、不自动解冻 R3、不构成部署授权。候选仍须通过与实际
采用范围相关的版本闭包、carrier、composition、权限、会话、取消、MCP、WorkflowTrace、故障
降级、回滚和 Product smoke 门禁。

### 4. 风险选择与证据复用

CI 和资格证据按变更影响选择。安全边界、协议、持久格式、权限或副作用语义变化运行完整相关
矩阵；文档、探针或接口不变的补丁只运行定向和架构检查。计划器必须证明所选 lane 覆盖影响，
但不得为了统一标签把无关 lane 全部纳入。

精确绑定到未变化源码、依赖、合同、镜像和环境的既有证据可以复用。复用必须记录身份和适用
范围；不能把旧 PASS 复制给已变化的边界。平台卡死或网络故障是 CI infrastructure failure，
允许对同一精确 head 有界重试，不产生新的业务资格结论。

### 5. DSH 升级风险分级

- **A（制品/文档/补丁，无运行合同变化）**：验证闭包、完整性、生成物和受影响定向检查；
- **B（SDK、carrier、composition 或观察合同变化）**：增加真实 runtime、MCP、权限、会话、取消、
  WorkflowTrace、故障降级和回滚验证；
- **C（持久格式、信任边界、权限、生产拓扑或副作用语义变化）**：运行完整相关矩阵，并在生产晋升前
  补 live-model、真实 Product API、old→new→old 和必要恢复演练。

等级由 diff 和合同影响决定，不能由版本号或发布渠道单独决定。上游未提供、且 BYQ 能安全降级的
可选能力只阻塞该能力声明。所有等级的生产 selector 切换仍是独立授权。

### 6. ADR 与版本范围治理

- 同一版本、同一信任边界、同一数据/执行拓扑下的一组模型、profile 或接口扩展可以由一个
  实施 ADR 覆盖；普通实现细节不要求逐项新增 ADR。
- 只有新增信任主体、持久化权威、跨 Plane 调用、外部写权限、不可逆迁移、新付费资源或生产
  拓扑时，才强制新建具名 ADR。
- 当前 1.0 模型矩阵继续作为规划目标。0.10 数据、HIST 来源和深度环境资格完成后，必须通过
  具名范围复核把项目分为 `core`、`extended`、`deferred`；接受后的 core 才是正式 1.0 全局
  发布门禁。不得静默删除、伪造通过或用不可证明数据替代。
- STATUS 只表达当前权威状态和下一可执行任务；历史事实留在 ADR/证据，不在顶部重复形成门禁。

## 明确保留的严格边界

本 ADR 不放宽 Product/Engineering 权限隔离、MCP-only Agent-to-Domain、租户隔离、凭据和源码
保护、数据时点与许可、业务幂等、真实浏览器/Product API 验收、精确制品身份、不可逆数据操作、
生产部署和正式发布授权。它只修正门禁的作用域和聚合方式。

## 迁移顺序

1. 将本 ADR 标为 Accepted，并在 ADR-0081/0082、0058、0074、0071 增加精确 superseding 修订。
2. 修订 STATUS、IMPLEMENTATION_PLAN 和 D15 计划：B1/B2 保持外部阻塞，但不再是全局停止点。
3. 建立 BYQ session failure containment and business recovery 的独立实现/验收切片。
4. 该切片通过后生成新的 D15 superseding assessment；历史 verdict 保持不可变。
5. 再按实际采用范围判断 DSH 0.1.5-rc.1 晋升；selector 切换仍需独立部署决定。
6. 0.10 资格调查后执行 1.0 core/extended/deferred 范围复核。

回滚需新的 Accepted ADR，并说明为何外部能力必须重新成为全局硬阻断。回滚不得改写历史证据。
