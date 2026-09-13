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
