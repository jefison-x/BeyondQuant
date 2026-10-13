# DSH / ACP 专项维护当前验收（2026-10-13）

不推进 Product Phase。应用闭包基线为 `55033eb0937665bf1d19f848de1f185353f7dbc0`，基于同步后的 `origin/main=ad5f7df1ad18e54dd0d9860d424241297187eef8`。新增租约观察切片的五文件源码 SHA 单独记录于 ROOT-LEASE-OBSERVER-OFFLINE-FAIL-STOP.json；修正入口后的定向离线验收见ROOT-LEASE-OBSERVER-OFFLINE-PASS.json，真实状态验收仍未完成。

| 项目 | 结果 | 范围 |
| --- | --- | --- |
| 完整应用闭包及定向离线回归 | PASS | 22 路径闭包、typed Artifact fixture 修补、48 MCP 合同及已记录定向检查；见 ROOT-COMBINED-OFFLINE-PASS.json |
| 已有精确 scope 的签名清理回执 | PASS | 替身34例及一次既有回执读取；不等于恢复原子 Agent；见 ROOT-EXISTING-SIGNED-CLEANUP-READ-PASS.json |
| 计数与委派预算机制旧证据 | PASS 限定复用 | 源码哈希与机制边界相同；不重复模型；见 ROOT-TOOL-COUNT-EVIDENCE-REUSE.json |
| 生产 ACP 源码版本对应 | PASS 限定 | digest150b4802通过正式部署/准入/manifest对应源码33152f65；健康不替代真实业务验收；见 ROOT-PRODUCTION-SOURCE-ATTRIBUTION-PASS.json |
| 新 MCP 镜像源码读回 | PASS | `08dcc976...`，构建/源码资格；见 ROOT-COMBINED-MCP-IMAGE-SOURCE-PASS.json |
| 隔离 MCP 服务更新 | PASS | 新容器健康，其余10个隔离服务及17个生产库存未变；见 ROOT-ISOLATED-MCP-UPDATE-PASS.json |
| 浏览器采集入口 V2 替身 | FAIL_STOP | 首例将合法重复读取误判；一次执行后停测，全面重审采集合同；见 ROOT-BROWSER-V2-OFFLINE-FAIL-STOP.json |
| 新候选真实 Product / 浏览器 | PASS 限定单轮 | 手动8次模型、零新Job；刷新后唯一回答、持久化/交付/Root结算一致；独立Sol及Root PASS；自动V3仍NOT_RUN；见 ROOT-MANUAL-BROWSER-ONE-TURN-PASS.json |
| 两用户测试 Compose 合同 | PASS 离线限定 | 实际默认链解析，3项+6子测试，独立Tester/Sol/Root PASS；真实用户/实际挂载仍未验证；见 ROOT-TWO-USER-OFFLINE-CONTRACT-PASS.json |
| 两用户真实预检入口 | FAIL_OBSERVER_STOP | Root猜错表名；只读查询失败，零模型/Job/用户/容器变更；停止后重审查询复用方法；见 ROOT-TWO-USER-LIVE-PREFLIGHT-FAIL-STOP.json |
| 两用户预检完整性源码审计 | PASS 发现缺口 | Sol确认readyfile、无子进程、Backend roots闭合不能证明Adapter lease已释放；当前`slot_available=UNKNOWN`，真实批次保持停止，先完善只读采集合同 |
| 实际Adapter租约匿名只读计数 | PASS 定向离线限定 | 平级挂载修正后Runtime6/Gateway3通过，Tester→独立Sol→Root PASS；模型/Job0、原27容器未变。首个挂载FAIL保留，真实计数/旧进程租约仍未验证；见ROOT-LEASE-OBSERVER-OFFLINE-PASS.json |
| 两用户、自然迟到旧请求、业务结果 unknown、进程丢失 | NOT_RUN 当前补缺批次 | 保留旧限定证据，逐片补缺；不自动重放未知业务结果 |
| 远程 CI / 推送 / 合并 / 生产部署 | NOT_RUN | 不以本地、合成或隔离更新证明生产资格 |

## OC 工程执行事故

只读源码审计 `ses_ecd98ec47ffeX0YS71U5PpA5AP` 超过工具次数且擅自检查环境，将服务认证变量带入工具输出。该批次 FAIL_STOP；含密原日志只留私有目录，不进入Git、不出站、不得续用该 session。已完成准确abort、私有日志0600、原生服务密码轮换（旧认证401、新认证200）、原固定Tester session可读。

原生 OC 服务保留，两个旧自动派发timer可逆暂停。当前7个Agent的关键工具权限配置读回为deny，经Sol核对；实际执行拒绝NOT_RUN。权限不阻止模型请求或清除旧会话上下文，新增OC工具任务仍NOT_ADMITTED。现有必要Luna源码回退继续；固定测试命令经审查后在OC外执行。无新客户端、调度框架或Agent harness。具体范围见ROOT-OC-*回执。

当前仍 NOT_READY。历史部署证据和本次新候选资格分别记录，不因当前未验收而改写旧生产部署成功记录。
