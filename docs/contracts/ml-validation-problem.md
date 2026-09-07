# ML 校验问题：ml-validation-problem.v1

Post-U8 F7 本地切片。类型化 ML 校验异常在 Backend 422 中返回封闭字段路径和类别，
不序列化异常原文、未知输入字段、原值或内部对象。MCP 再次校验字段段名和类别，重建响应。
不受信任的扩展字段、服务端传入的任意提示或 repair_limit 不向模型转发。

字段为 `schema_version`、`field`、`code`、`repair_limit=1`、固定 `next_action`。
类别限 object_required、unknown_fields、text_required、date_format、integer_required、
number_required、boolean_required、out_of_range、unsupported_value。
允许值和范围从既有 `byq_ml_capabilities` 的已认证 registry 查询，不能猜测模型/参数能力。

此切片覆盖 v1/v2 的公共对象、日期和参数校验辅助器；尚未把所有校验路径转换为结构化问题，
也未实现持久的纠正次数台账，因此 F7 不能据此关闭。历史两次 422 的字段原因仍未知。
