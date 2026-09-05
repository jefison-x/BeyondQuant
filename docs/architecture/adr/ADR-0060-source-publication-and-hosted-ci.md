# ADR-0060：个人研究源码公开、权属与一次性 CI 发布过渡

- Status: Accepted
- Date: 2026-09-05
- Decision scope: 源码许可、贡献/第三方授权、源码仓库公开和 CI runner 迁移；不改变 Product/DSH runtime、金融领域或业务部署权限
- Acceptance: 维护者明确要求拟定个人非商业许可、禁止机构使用、保留今后商业授权，合并 DSH 升级方案并公开仓库、迁至 GitHub 标准免费 runner；随后明确撤销个人自有资金实盘例外，要求禁止实盘。维护者确认 `jefison-x`/`root` 原创代码版权归其本人、无雇主/客户限制，并指定 GitHub 主页为唯一公开联系入口。维护者另明确回复“批准一次性发布过渡例外”。
- Supersedes: 仅本次私有仓库发布准备 PR 的 ADR-0015/0059 服务器强制检查/auto-merge 可用性前置；不豁免失败检查、审查、精确提交、分支 PR 或禁止直接 push main 的规则。公开后立即恢复通常门禁。

## 决策

1. 根 LICENSE 使用 BYQ 自定义 `LicenseRef-BYQ-Individual-Noncommercial-1.0`，仅个人非商业
   学习、研究和模拟；机构、商业和所有实盘用途均不得依据该公共许可使用。强制性法律和
   平台已获必要权限不被否认；不声称 OSI 开源或绝对免责。
2. 维护者对自有/足够授权部分保留商用与再许可权。CLA 保留贡献者版权，明确向维护者授予
   商业/再许可权；机构成果不自动接收。第三方许可证与数据权利独立，未知来源阻止合入/发行。
3. 本次授权含 develop、push/PR、merge、仓库可见性和 runner/必要 GitHub 安全设置迁移；
   不包含 DSH U0–U8 实施、业务服务部署/重启、数据迁移、Release/tag 或 v1.0 发布。
   DSH 文档归档后 ADR-0058 仍 Proposed，U0–U8 全部 PLANNED。
4. 当前 private 套餐的 branch-protection API 为 403。仅发布准备分支
   `chore/source-publication-license` 可在精确 PR head 的实际 GitHub local-ci/ci-gate 全绿、
   全部其他检查成功、无冲突且完成自审/维护者授权审计记录后，正常 squash 合并一次。
   不使用 --admin、force push、伪造状态或忽略失败/跳过检查；记录例外消耗的 PR/head/结果。
   不为后续 DSH 升级或任意 PR 提供永久绕过开关。
5. 公开前完成最终历史/讨论/日志/截图/附件审计，并使正式机 runner 不再可被该仓库调度。
   不可信代码不得接触正式网络、Docker socket、凭据、数据库或主机用户目录。
6. 公开 CI 使用标准 `ubuntu-24.04` 临时 VM，显式工具链、受控构建并发、无真实密钥/资金，
   scoped 测试资源与清理、不跳过的汇总门禁。CI 不执行大规模生产 ML/回测，也不承担部署。
7. 为在“许可先入 main”与“公开后免费 hosted 验证”之间安全过渡，可拆两 PR：
   A 合并本次许可/DSH 方案/已验证治理；B 事先准备 hosted-only 工作流。
   A 合并且审计通过后暂停 Actions、停用并撤销正式 runner、公开，配置严格保护与外部 PR
   审批，再恢复 Actions 验证 B。B 必须通过托管 CI 后按通常门禁合并；不能对 B 再用第 4 条例外。
   过渡期间队列不可执行正式机代码；CI 暂时待验证不冒充通过，业务服务保持运行。
8. 必需服务器检查为 `local-ci` 与 `ci-gate`，strict/up-to-date、禁止 force push/delete、
   包含管理员，合并经 PR；外部贡献需来源/CLA/维护者审查。设置不能验证时停止进一步发布动作。
   公开前后均保留正常审核，不因免费额度限制自动降级安全边界。

## 回滚与公开不可逆性

公开前可停在 Draft/private；公开后即使恢复 private，也不能收回他人已经获取的副本。
因此审计和权属门禁在可见性改变前完成。GitHub-hosted 失败时修复 B 或保持合并阻断，
不得重新连接正式机 runner。已有源码许可对已获许可版本的合规使用者不追溯撤销。

## 验收

许可/风险/CLA/权属/第三方清单合同测试、原治理完整 CI、DSH 文档一致性、历史脱敏审计，
以及托管环境冷/热启动、完整回归和取消清理证据。平台前后状态与例外消耗记录进入专项
证据，不把临时 PR 或 Git SHA 写入 STATUS。
