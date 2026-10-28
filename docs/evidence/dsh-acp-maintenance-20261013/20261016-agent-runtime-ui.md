# Agent 运行参数与提交回执 UI 维护

本次是 ADR-0111 的 DSH/ACP 维护界面调整，不推进 Product Phase。维护者要求把会话自动接续选项移出聊天输入区，放入系统设置；confirmed 提交回执不再常驻，待核对状态不得被显示成业务任务进度。

普通用户从账户菜单进入“系统设置 → Agent运行参数”。该设置页只列出当前登录用户通过现有会话列表读取到的会话，参数读取和更新仍使用现有 owner/workspace/conversation scoped Product API。新会话默认开启以服务端真实返回值为准；已有明确关闭值保留。界面仅编辑 `auto_continue`，按 API revision 更新，写入结果不明时只重读，不重放；其他运行参数原样保留。

原 `/settings/system/**` 路由及 `requiresAdmin` 未放宽。共享设置布局按身份只显示有权访问的导航项。会话上下文通过 `returnTo` 保留 conversation ID；没有上下文时要求用户选择本人会话，不自动猜测或创建会话。

聊天中的提交回执面板仅显示 `awaiting_receipt`、`conflict`、`needs_attention` 等未确认行；隐藏 confirmed 行和 attempts/deadline 内部字段。API 不可用或登录失效仍显示提示。说明限定在“提交回执”，不代表研究或计算任务完成。

静态验证：`npm --prefix apps/frontend run build`，native exit 0（`vue-tsc --noEmit` 与 Vite build）；`git diff --check -- apps/frontend/src`，native exit 0。最终文案调整后的原始 stdout/stderr/exit receipts 位于 `.ci-artifacts/agent-runtime-ui-v2/`。未运行功能测试或浏览器，也未测试保存写分支；当前保留环境与页面由 Root 按既定范围验收，用户现存参数不做往返改写。

## Root 隔离更新与原浏览器验收

功能源码仍为 `a6d20958` 加九个冻结前端文件，源码清单摘要 `06c351577be0273532f0e5d8751df8bc54e279c9e9b31e0ca1a6980c85aa27f6`。本节为 Root 在终审后追加的证据说明，不属于构建前源码冻结原件。

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 类型/构建及源码审查 | PASS | vue-tsc + Vite build退出0，独立Sol复核九文件SHA和权限边界 |
| 镜像与隔离更新 | PASS | `6cf80c51…`，21769587字节，比旧版+1761字节，层数9→9；干净nginx基础+单COPY；97文件哈希/95 assets精确相同 |
| 资源保留 | PASS | 仅frontend-f6替换并healthy；其他15容器显式字段、全16完整挂载对象不变，账号/数据库卷未调整 |
| 原页面验证 | PASS | 聊天底部开关和已确认卡片消失；账户菜单→系统设置→Agent运行参数选中原CID、真实值开启；关闭设置返回原会话，38个文章前后全文一致 |
| 保存写分支/非管理员浏览器/真实异常回执 | NOT_RUN | 本轮只读查看与导航，不为验证而往返改写用户参数，不制造未知提交 |
| 模型/Job/新标签/功能测试代码 | NOT_RUN | 本轮均未新增或运行；复用当前环境与页面 |
| Full CI/推送/合并/生产 | NOT_RUN | 本地UI维护不替代发布或生产资格 |

实际前端容器 `a84ec4380df1a7da45b19be71489f5bc06b28d881f0270bd11991a47aeb8fbfb`；独立终审摘要 `8fd223f21a48685c4d6b2e4a81dcec8ceb860b2443b6f6e3f880612fa0f891b9`，Root限定PASS。完整命令、native输出、清单、截图与收据位于私有 `.ci-artifacts/agent-origin-consumer-20261015-v1/ui-continuation-receipts-20261016-v1/`，最终浏览器截图 `returned.jpg`。环境和原会话页面继续保持打开。
