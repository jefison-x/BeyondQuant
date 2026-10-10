# ACP 专项：2026-10-09 新会话交接

## 人的最新指令与授权

本主会话过长：完成当前默认配置、CI/Release 清理保护的小段收尾后，提醒迁移新会话。保留原工作树、提交、未提交修改和失败证据。当前收尾不进入下一轮构建/Full/付费验收/推送/PR/合并/部署。

原专项允许隔离开发、验证、工作分支推送/PR；合并只能通过有效的 pre-v1 ADR-0015/0059 精确 head/preflight/required checks/服务器规则门禁。禁止直接推 main、即时合并、release/tag、破坏性数据操作。模型验收已有后续授权，但必须先复用有效证据，不为美化结果重试。OpenCode Go / deepseek-v4.1-flash 为已验证路由；凭据只能读取私有配置，不能输出。测试可使用已授权的生产 Tushare 凭据。

最近明确授权仅隔离分支默认配置：固定 ACP rc.2、默认已验证模型、解除旧 SDK 会话卷挂载但保留数据/镜像/回滚配置、缺可信 Workspace 时拒绝启动。不要再索要同一授权。用户已关闭本机生产：本机只测试，未来其他机器部署，由 Product 外 trusted operator 执行；不得报告本机生产验收。

## 工作位置与规则

- 工作树 `/home/jefison/projects/.byq-worktrees/dsh-acp-single-version`，分支 `codex/dsh-acp-single-version`。
- HEAD `2d5810973240c5d7692569319c2b5ab337ae2082` + 保留的大量 OC/当前修改，绝不可 reset/clean/覆盖。
- 实际 origin/main / merge-base `f753eb27157228e8d3d594203878f55ab2c7a53e`；2026-10-09 核验 upstream-only 0、branch commits 29。旧5619基线为历史。
- 此次没有 commit、push、PR、merge、部署；新会话重新核验实际状态。
- 先读 AGENTS.md、ARCHITECTURE.md、STATUS.md、IMPLEMENTATION_PLAN.md、DEVELOPMENT_WORKFLOW.md、相关 Accepted ADR 和 CURRENT-QUALIFICATION.md。不得推进 Product Phase（Phase17仍OPEN）。一子系统一写者，独立 Tester/Reviewer 后 Root 给出有限结论。
- 固定官方 `dsh-v0.2.0-rc.2@639ed015397290b3745d163aafe02ffee4aa3f84`，pnpm lock `80fe05eae33582ae26839afd05f1965f9b0e4be11034ddf9797af6085d5ba9b1`。不自动换新标签、不fork、不加第二harness。
- ADR0093/94/96(native reuse)/97专用研究root/0102新子助手业务接续/0103后台完成新root/0105–0109及已接受修订有效。ADR0104丢失进程且无可信清理回执的恢复方案仍未接受：暂停该冲突部分，不能猜测业务未发生或重放回合。

## 已有可复用证据

1. `continuous-native-acceptance-20261009/RESULT.md`：实际 normal→后台完成自动推进→normal，3root/同原生会话、新身份、精确BackendACK、signedcleanup、上下文不重复；真实桌面/移动只读浏览器 bounded PASS。原失败保留。
2. `cancel-new-child-acceptance-20261009/RESULT.md`：取消后通过新root/新子助手接续已提交业务的核心 bounded PASS；旧子实例恢复没有资格证明。旧cancelroot ACK41，新root ACK56；原Job attempt1/幂等key/artifact不变，无写执行重放。严格“整个root只读一次”试验 FAIL：子助手一次+父助手一次共2只读，助手描述一次不准确，不能改成PASS。旧provider有一次outcome/usage unknown，不能重试。新的准确取消历史提示已构建frontend并真实只读桌面/移动验证PASS。
3. `late-root-isolation-20261009/RESULT.md`：合成旧root令牌通过实际MCP→隔离BackendPG拒绝409/noingress bounded PASS；不是自然DSH迟到请求/Product集成验收。
4. `data-preparation-20261009/RESULT.md`：真实Tushare3标准日期与单股票数据、小范围Job/Worker/readiness有限PASS，历史DB归档未导入。
5. 专用研究判断入口已接通实际请求/consumer/专用ACP结果/精确ACK/cleanup/browser（20261008证据）；结果 needs_attention/no_durable_progress/proposal=null，是调用路径资格，不是有效推进研究计划。
6. `runtime-single-version-retirement-20261009/RESULT.md`：只ACP selector/默认ACP/旧SDK明确拒绝、readiness合同保留、旧judgment入口503无dispatch、无条件Linux进程secret保护。独立33次执行/31 unique focused tests PASS，Reviewer/Root bounded PASS。不是当前源baked镜像资格。
7. `authoritative-build-wiring-20261009/`：权威manifest+resolver/helper/profile/完整固定官方source构建；Adapter image `sha256:9112eb955ff4bb0465bf9b98e70d0b107a74ad36541d16f7ee4330d869db6d4f` 和 Product runner `sha256:693c7bfd2f0dd64c45fc84d7f950886ddfe6294783e62977afb2eb5ed666b0dd` 构建退出0、独立readonly源/lock/profile/hash/无SDK检查PASS。Adapter镜像中runtime hash34c43...早于当前972f0...，不能当最新Runtime代码资格。Product runner controller检查UID0，账号定义byq10002，无DSH子进程实际launch。

## 本次配置/CI/Release小段

默认base+唯一ACP overlay，Makefile/dev/local-ci通过 `scripts/dsh/acp_build.py`；两runner同可信Workspace leaf；缺配置failclosed；旧SDK卷解除挂载但声明/数据保留。首次新账号/Workspace onboarding NOT_RUN。

Release canonical 17自建镜像/18Compose服务（PG外部）统一 images.py；build/test/export/manifest/Promote一致。captured immutable ID完整集验证后按ID归档，DSH三角色额外identity，其他14BYQsource/run/image/SBOM；trustedmain+Full+samebatch规则未放松。

旧SDK后台完成fixture不能称ACP：Release Full在新ACP Product/Worker fixture缺失时明确失败并禁止导出，当前Full NOT_RUN/推广门禁仍关闭。清理只对应scope准确名称/标签/17capturedID，ACP专用网络及6卷必须纳入；foreign标签或digest引用保守保留；KEEP_POSTGRES保留独立测试PG资源。此次只模拟测试，没有实际清理资源。

本小段最终测试/审查/secret-scan与快照哈希见 `default-release-source-checkpoint-20261009/RESULT.md`。

## 私有测试环境与保护

- 私有目录 `/tmp/byq-adr0109-qual-20261009-c89ff732f2` 0700，env0600，测试scope `byq-dev-c89ff732f2`；Workspace `workspace_f6196f43175243fb870649f457a94dcf`。不输出provider key、cookie、token或完整环境。
- 最后观察9healthy测试容器（核心8+frontend），worker已停止；网关127.0.0.1:32783，frontend127.0.0.1:32784。新会话先核验端口/资源；默认源码修改未重建此live stack。
- live Adapter旧资格image42525c14...，frontend准确提示image da1dd098...。精确旧镜像/配置/volume备份保留；不得大范围prune。
- `compose-acp-safe.py` 使用权威resolver与显式文件/私有镜像覆盖；不要直接加载或打印私有env。
- 构建记录 `/tmp/byq-acp-authoritative-real-build-20261009`；两个build已结束无运行build。
- 备份 `/tmp/byq-acp-default-implementation-20261009/prechange.tar.gz` SHA4dccb51e0fc0e0adc3e28604ea51a212fad73c0c6ff9a5fb8c87bb461825d7f1；`/tmp/byq-acp-release-batch-preedit-20261009/`；`/tmp/byq-runtime-only-single-version-20261009-prechange/`；Makefile旧版本 `/tmp/byq-acp-default-entry-finish-20261009/Makefile.before`。

## 新会话下一步（不重复完整已验证套件）

1. 优先补 canonical17batch 的 ACP 后台完成 Product/Worker fixture，保持授权/幂等/unknown/精确ACK/cleanup保护；把旧SDK测试fixture迁到ACP当前默认，不能删安全门禁或静默skip。
2. 当前runtime selector/privacy变更完整烘焙ACPimage、judgmentrunner完整sourcebuild/identity；17同批镜像真实Full/readback/SBOM/export资格。此次旧镜像source-identity PASS不能代替。
3. 必要的首次账号/可信Workspace dev-bootstrap/readiness窄验证；静态Compose PASS不是全新环境验收。
4. 对保留OC的全量实际diff做最终审查/secret扫描；reuse有效业务证据，补具体剩余two-user/自然late-request等资格缺口。未知active故障ADR0104保持暂停。旧SDK native数据不物理复制/不自动迁移，先分类目录及回滚影响。
5. 满足资格后才工作分支push/DraftPR（创建后attach artifact），exact head CI/required checks/rules/审查/RootPASS；只在原授权有效且pre-v1 ADR0015/0059全部门禁满足时启用squash auto-merge。
6. trustedmain ReleaseImages最终Full后同批受测digest发布/Promote；未来另一台机器可信operator部署，部署前备份/旧镜像配置/readiness/停止后继续/rollback核验。不得称本地合成或测试为生产验收。

Root要明确当前小段PASS与整个专项尚未完成的边界，不再用功能代码编号向用户解释“后台任务完成后自动继续”。

## 收尾安全扫描：FAIL / 待分类

gitleaks 8.30.1 校验工具tar SHA `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`。扫描 origin/main→当前工作树 changed regular files + nonignored untracked files 快照407文件，退出1，35 findings。集中在 runtime source-hashes/independent summary、ADR0109 image-source-readback 的哈希字段，以及5个测试文件的测试token夹具。尚未逐项确认真假，**不得称secret gate PASS**，不得打印匹配值或粗放加入全局ignore。下一会话先安全分类，若纯fixture更改为明确synthetic低熵标记，证据hash保留可验证语义并使用最窄有依据规则；真实凭据若有需单独安全处理。Git history扫描此次 NOT_RUN。

私有日志/脱敏报告/source snapshot位于 `/tmp/byq-acp-frozen-scan-20261009/`；共享交接仅收录 rule/path/line 元数据，不含匹配内容。

## 最终冻结结果

独立Tester最终28选定方法+9子断言全部PASS，冻结前后源哈希一致；独立Reviewer源码/架构有限PASS，Root本小段PASS。整体Release NOT_READY：secret扫描35候选未分类，Full/当前Runtime完整镜像资格仍NOT_RUN。测试节点/log/receipt在本目录。各写者已冻结；新会话从此交接记录继续，先分类安全扫描和补ACP后台完成发布fixture，不要重复已完成真实验收。
