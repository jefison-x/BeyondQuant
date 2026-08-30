# 用户设置与资产

- `/user/profile`：昵称、研究偏好、默认提示词。
- `/user/appearance`：跨设备明暗模式和主题色。
- `/user/assets`：工作区资产清单和经过验证的导入导出；导入内容不能携带 owner、workspace 或审批权限。
- `/user/models`“模型配置”：写入保密的对话 LLM 凭据、模型档案和 Agent 绑定，不是 LightGBM 量化研究。
- `/user/agent-policy`：个人审批偏好和操作规则；个人设置不能绕过平台审批、风控或领域不变量。
- 小巴可以说明和导航这些页面，但不读取凭据明文，也不代替用户修改账户安全设置。
