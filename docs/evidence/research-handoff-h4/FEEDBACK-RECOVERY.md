# H4 反馈命令恢复

2026-09-13，`.71`，遵循Accepted ADR-0049/0053，仅本地恢复能力，不发布反馈。

三个独立连接同键创建原先会触发commands唯一键冲突，失败测试先于修复。
既有命令回放读取前增加精确scope/actor/operation/key事务锁，等待最多2秒；
保持原有revision、审核、outbox与命令结果同事务。封闭create/update/submit/withdraw回执GET
按原工作区和执行者读取，校验feedback_id及实际对象归属；返回原命令结果，不能冒充当前版本。
MCP复用byq_feedback_get原键分支，未知写提供只读核对参数，错对象回执拒绝。

Product页面写前保存当前用户工作区内原命令与固定输入；丢回执、刷新后只读核对或明确原请求重试。
新输入不能替换未确认命令；原提交的披露确认与版本条件不变。核对只恢复事实，不触发新提交。

## 证据

- Backend反馈领域与独立连接恢复8项通过，验证原始版本、跨actor/workspace拒绝、1个草稿、0个Hub事件。
- MCP编译和反馈测试通过，包括错对象、原创建键读取参数。
- Frontend类型/Vite构建通过，持久提交与API6项通过。
- 实际Chromium→Frontend→Gateway/Product API→Backend→专用PostgreSQL：草稿真实提交后丢弃浏览器
  回执，刷新后GET恢复原feedback_id且仍draft，1项通过（2.7秒），全程仅一次创建POST。
- 无真实模型、Hub/GitHub外部投递或生产写入。

本批不关闭中央发布器其他待审计路径或完整H4/H5。管理员moderation仍单独核对；不会自动重放审核动作。
