# H4 集成验证与未决范围

2026-09-13；当前分支承接 H1–H3 和 H4 三个修复切片，共六个前序本地提交。
维护者接受“整理逐接口结论、统一推送近期修改、运行远端 CI”的下一步后回复“好的，继续”。
据此本批授权 develop、push/pr；不据此执行 merge、deploy 或推进 Product Phase 97。

## 本地已执行

- 当前源码 MCP build + 完整 npm test 通过；包含真实 HTTP MCP 与 Backend 合同、合成身份的持久写入。
- Backend test_research_receipt_watches.py：17项通过，真实临时 PostgreSQL；迟到提交、Store 重建、
  原键核对、并发计次、错误退避、过期/禁用和归属拒绝。Store 重建不是 OS 进程崩溃注入。
- 新增真实 Chromium HTTP 创建旅程通过：确认 randomUUID 不可用，真实用户登录，经 Product API
  创建、刷新、按原 task_id 回读同一标题；无接口 mock。前端构建通过。
- 测试依赖镜像仅提供依赖；应用源码来自当前工作树。内部网络、tmpfs 数据库、无生产或模型调用。
- 初次 Backend 启动缺注册表、嵌套只读挂载失败；改为完整工作树只读挂载后测试通过。
- 沙箱内 GitHub 登录查询失败；获网络权限后 keyring 登录及 fetch 正常，不需要用户重新登录。

## 接口族状态（不是逐接口全部通过）

| 接口族 | 已有具名证据 | 尚需补齐 |
|---|---|---|
| ResearchTask/Experiment/Artifact | RESEARCH-RECEIPTS、原键父任务绑定、EXACT-READ、本次17项恢复测试 | MCP→Backend丢响应与独立服务重启组合；首次写响应与confirmed watch父任务一致性审计 |
| Backtest/BacktestTask/SignalProducer | BACKTEST-RECEIPTS、BACKTEST-TASK-RECEIPTS、SIGNAL-SUBMISSION | 最终版本的跨服务未知回执故障旅程 |
| ML训练/预测 | 已有持久watch与MCP组件证据 | 逐写接口绑定与迟到取消集成覆盖 |
| 策略/因子/信号导入 | DOMAIN-INPUT-OWNERSHIP、组件翻译测试 | 按原键恢复及写前认领逐接口审计，不能用通用unknown分类代替 |
| 股票池/学习记录/反馈 | 已有专用状态入口及历史组件证据 | 各写接口恢复适用性、持久有界重试与最终证据映射 |
| F7纠错 | 已交付的两工具资格 | 其余工具逐项资格及无进展停止证据 |

CURRENT-INVENTORY.json 重新按当前源码枚举，保持 NEEDS_EVIDENCE，不能把枚举当作验证。
旧完整清单中的人工补充 surface 仍适用，见 post-u8-interface-audit/AUDIT.md。
上述为集成初检时的待办。后续按下方切片推进；H4/F2/F7仍未关闭，H5已进行历史单次快照准备，不能将合成流程验收当作真实研究完成。

## 首轮远端 CI

运行34729680726的集成项：13个真实浏览器测试中11通过，2个F6桌面/手机用例因仍定位旧许可确认文案超时。
同步当前H3确认文案，保留保存、持久化、撤销业务断言；不扩大超时或跳过用例。原失败保留，修订后重新验证。

## 第二轮远端 CI 与详情合同修订

运行34730210521：集成及其他组件通过，Backend为618通过、1失败、1跳过、7subtests通过。
唯一失败为旧研究API测试将详情与创建响应整体比较，未涵盖H2新增handoff字段。
修订保留原实体全部字段严格相等，并显式验证handoff版本、原task_id、目标、状态和无会话绑定时的阻塞原因。
修订后隔离 PostgreSQL 的完整 test_research_api.py 共17项通过；远端须对新提交重新验证。

## 远端门禁完成

提交e0bbc69的运行34731527630全部通过（包含Backend、真实集成与最终ci-gate）。
后续因子/内容去重回执/故障探针为新源码，不能沿用这一成功结果。

2026-09-13：提交 `6bbd2d8` 的远端完整受影响 CI 已通过，运行 `34732957839`。
该结果覆盖因子原键恢复、三类内容去重回执和跨进程探针；随后 `.65` 缓存与 `.66` 因子纠错仍需新CI。
