# 两用户任务读取隔离（2026-10-17）

DSH/ACP专项维护，不推进Product Phase。基于工作树HEAD `5ebbdf89dac3b14554c62dbae9adbea6bfc2ab7e`，本项不修改源码、不更新镜像。复用现有A/B账号及此前已验证的host-only Cookie边界。

目标是补齐旧跨任务读取的HTTP证据，不重跑会话读取和模型流程。上限3次只读浏览器GET、1次原生Gateway日志读取、120秒；实际没有提交用户消息、触发Product模型或创建Job。

| 浏览器身份和请求 | 实际响应 |
| --- | --- |
| B，127.0.0.1，自己的任务列表 | HTTP200，`tasks:[]` |
| B，127.0.0.1，读取A指定任务 | HTTP404，`product_domain_rejected / research task not found` |
| A，localhost，读取同一任务 | HTTP200；准确任务、owner=admin、工作区及原会话匹配 |

准确任务为 `task_95563991efea45309f78425488d38839`；A工作区为 `workspace_4c5b803209d549019b7804976f6930c6`，会话为 `conversation_d1970f74cbcb4703b8c182523db4c4f1`。A读取成功证明目标确实存在，B自己的列表200证明正常认证，不把401或不存在目标误作隔离通过。

每次响应通过现有Gateway/Product API在同一浏览器只读页查看并保存AX/截图；HTTP状态由一次准确起止时间窗的Gateway原生plain日志核对，三条目标请求依次为200/404/200，没有从错误正文猜状态或构造测试专用API。当前A/B用户页面的身份AX另行保留；原A会话与用户已转至外观设置的B页面均未导航、未写入，用户页面和草稿保持。仅新增一个独立只读核对标签页并保留。

任务仍为planned/version1；其needs_attention进度来自之前取消的8137接续，不是本次查询造成的变更，也不据此重新执行旧任务。

私有原件：`.ci-artifacts/agent-origin-consumer-20261015-v1/two-user-task-access-20261017-v1/`，包括计划、浏览器身份/响应/截图、单次Gateway日志原生退出码和准确请求行。独立Sol与Root最终结论保存于该目录；本项仅限定任务读取隔离，不代表并发Root、迟到MCP、真实业务unknown、进程异常或完整租户安全资格。15参数写入/执行、Full CI、推送、合并及生产仍NOT_RUN。
