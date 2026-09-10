# F8 领域输入与信号读取归属修复

日期：2026-09-09。状态：LOCAL_VERIFIED，完整隔离CI与独立清理通过。
工作树继续 `post-u8-interface-audit` / `codex/post-u8-interface-audit`；前一批本地提交
`ccd93ba`，同步主线仍为 `428b05f`。本批为已授权Post-U8维护延续，不推进Product Phase。
Community原实现检查按Accepted ADR-0068长期豁免。未访问生产数据或执行真实研究。

## 已复现问题

真实FastAPI TestClient与独立PostgreSQL上的10项失败证明：

- Factor compute及signal snapshot import的缺身份、其他owner、错配workspace请求原先返回201；
  合成测试确实执行了计算并创建Artifact，不只是根据路由签名推断。
- Signal snapshot按ID读取缺身份/跨owner/错配workspace原先返回200；传入strategy_version
  ID也返回其完整制品，未验证signal_snapshot类型。
- 另1项独立失败证明Product Agent actor可通过原始信号import创建快照，与ADR-0017读而不写的边界不符。

这些是隔离复现，不代表已经证明生产攻击、真实数据泄漏或历史记录受损。

## 最小修复及合同

遵循ADR-0017/0023/0025及ADR-0062，不增加新权限或新运行时：

1. 两写入口在计算/normalization之前要求完整可信context，解析活跃用户与personal workspace，
   核对ResearchTask的owner/workspace。未认证、禁用、工作区错配返回401，外来对象返回404。
2. Signal import同时核对所引用StrategyVersion的owner/workspace，再保留原kind/status/task匹配验证。
   原始fixture/import仅允许human owner actor；Product Agent actor返回403。隔离signal-worker生产路径不改。
3. Artifact事务使用已有trusted_owner/trusted_workspace参数，重新验证任务及引用归属。
   不信任Browser/model提供的owner字段，不让DSH访问数据库。
4. Snapshot GET使用相同可信context和owner/workspace检查，并限定signal_snapshot kind；保持成功返回
   `snapshot`中的原Artifact结构。合法快照的content、hash、输入身份及回测审批语义不改。
5. "keyless"仅表示不需要外部Provider密钥，不表示匿名访问；修正原route docstring以消除误导。

现有private service trusted-header拓扑不变。本批不建设新的服务认证机制，也不声称已关闭所有API鉴权或F2幂等核对缺口。
因子计算仍在现有Artifact幂等检查前运行，非ML原key精确核对、提交先登记及持久核对仍为后续事项。

## 验证与资源

- 修改前首轮：10 FAILED、1 PASS；首个归属修复后相关API19 PASS。
- Product Agent原始import补测：1 FAILED；随后加actor限制和禁用用户矩阵。
- 最终定向：新增15项隔离回归，加完整factor API、backtest API及factor语义文件，共30 PASS，20.09秒。
- 有效owner读取、因子幂等重试、snapshot→backtest正常旅程保留通过；失败路径断言计算未启动、制品集合不变。
- 临时PostgreSQL使用内部网络及tmpfs，不挂载生产/Community卷；源码和测试只读挂载。
  retained镜像仅提供锁定测试依赖，不冒称新源已完成制品资格。
- 日志在本地 `.ci-artifacts/domain-input-ownership/`，均经现有redactor；无付费模型或外部投递。

历史`.18`证据不覆盖本批新源码；本批独立验证如下。


## 最终独立验证

- `.19`基线/候选清单均通过最终check；历史`.18`及更早清单未改写。
- CI scope `post-u8-input-ownership-20260909`：退出0，全部26项PASS。
- 架构228；Backend514通过/1跳过/7subtests，488.12秒；Gateway202。
- Runtime基线149通过/35跳过；候选158通过/26跳过；真实候选进程23通过。
- MCP完整合同、Frontend176、模拟浏览器20及真实Product API浏览器9项通过。
- 重启持久化、两用户隔离和Product coherence通过；Python发布器10、relay2、Cloudflare19亦通过。
- 既有框架弃用/ResizeObserver警告及跳过项如实保留，不计无告警或全场景覆盖。
- 定向探针及全CI结束后均独立核验作用域资源清理PASS；临时数据为可重建合成数据，未备份。
- 本地脱敏CI日志：`.ci-artifacts/domain-input-ownership/LOCAL-CI.log`，SHA-256：
  `0a65dbd415f4bedc168a4d775e8f57c2a775fae9228ad55be6289c703ec9ac4d`。
- 源码与15项新增回归已完成本地验证；文档/diff检查通过，仅本地提交，未push、无PR、无远端CI、未merge或部署。

本切片关闭上述三个入口的具名归属/类型/actor缺陷，不关闭全接口审计或F2/F6/S3。
后续优先推进非ML原key精确核对与持久恢复；Product下一Phase仍未授权。
