# F7 校验边界补修（2026-09-08）

新增 7 项合成反例在修改前全部失败：列表调仓周期、对象型 training_regimes 触发
TypeError；v1/v2 超大合法 JSON 整数在 float 转换时触发 OverflowError；专家嵌套字段
被降为泛化 strategy。不能把这些反例认作历史生产两次 422 的确切原因。

修复先校验类型/范围再做浮点转换，保留允许值语义；封闭 MLValidationError 提供值隔离
的字段及类别。专家路径改成已受 Backend/MCP 双端允许的点分隔索引，不扩大错误内容权限。
Community 只读检查及分类见 migration inventory；不移植旧策略执行器或异常字符串输出。

验证：

- 初始反例 7 failed；只读源码快速回归 25 passed。
- 最终构建的全部 ML 策略、安全校验及响应映射：30 passed，29.07 秒。
  包含 _ml_call/_research_call 返回真实 HTTPException 422 和封闭 detail 的断言，
  不是浏览器或完整 HTTP 网络旅程。
- MCP 构建通过；17 项本地测试脚本通过，包含新增两个专家路径、私有字段不外泄断言。
  需要真实 Backend/MCP 的 contract-test 明确未在本切片重跑，不计全量集成通过。
- 首次运行 npm test 因未配置真实 MCP 合同夹具的 token 停止；首次 Backend 映射测试
  因导入 app.main 需要数据库而收集失败。已改用隔离 byq_domain_test 重跑，不连接生产。
  合成数据库初始化脚本已创建测试角色，重复 CREATE 被拒绝；没有覆盖既有身份。

未修改数据库 schema、前端或 Runtime；未重复数据库全量/浏览器回归，也未调用付费 API。
本切片不实现持久纠错次数账本，F7 仍未关闭。根回合与任务/动作绑定必须先明确，不能仅按
会话或任意新幂等键重置次数，也不能将 SDK generation 当成单个模型回合。
