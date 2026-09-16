# H4 跨进程丢回执恢复

2026-09-13。探针：scripts/evidence/h4-recovery-fixture.py 与
services/mcp/tests/research-recovery-live-test.ts，必须显式启用 BYQ_H4_RECOVERY。

内部 Docker 网络、tmpfs PostgreSQL、当前源码 Backend 与编译后 MCP 函数。
四种实际 HTTP POST：ResearchTask、Experiment、Artifact、Factor。Backend 确认201并提交后，
测试 fetcher 丢弃响应并抛出异常，MCP 均返回 outcome_unknown；不是模拟 Backend 响应。
随后真实重启 Backend 容器，原 MCP 测试进程已经退出，新容器进程只执行原键 GET。
四种结果均 confirmed，完整原对象一致；恢复阶段所有请求强制 GET，不允许重发 POST。
数据库最终合成用户只有2个task（含预建parent）、1个experiment、2个artifact（含factor），无重复。

首次服务未就绪导致登记连接失败，无回执行和业务提交；增加显式 healthz 就绪检查后通过。
这是在 MCP fetcher 收到真实 HTTP 响应后、返回调用方之前的故障注入，不声称 TCP 中途截断、
OS kill -9 未提交事务或真实 DSH 模型进程已做同样验收。现有数据库测试另覆盖事务异常回滚。
合成身份与原结果保存在 /tmp/byq-h4-cross-process，不提交原始fixture，未连接生产或模型。

## 六类领域提交补充（`.72`）

2026-09-13，当前MCP代码对实际Backend的股票池、LearningRun、最后一轮Iteration、
EvaluationSignal、Lesson和反馈草稿分别提交一次，服务器201之后、返回MCP之前注入回执丢失。
六项均outcome_unknown；提交探针进程退出，真实重启Backend容器，新MCP容器进程强制GET
并按原键确认六项原始结果，完整对象严格相等。恢复阶段写入数0。

最后只读事务核对专用owner：1task、1source Artifact、2LearningRun（含预置迭代parent）、
1Iteration、1Signal、1Lesson、1Pool、1Feedback、0Hub outbox，符合预期且无重复。
脚本 h4-domain-recovery-fixture.py / h4-domain-recovery-verify.py 和 domain-recovery-live-test.ts
保留，可显式在byq_domain_test及BYQ_H4_RECOVERY=1执行。原回执临时文件不提交仓库。
首次夹具Artifact创建遗漏可信workspace而被既有边界拒绝；补正确测试上下文后通过，未放松产品边界。

与前四项相同，这证明服务和调用进程重启后的持久读取，不冒充TCP截断、kill -9事务中断或真实模型评测。
