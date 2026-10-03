# 个人工作区菜单沿用 Bootstrap Admin 名称

状态：**OPEN — 已记录，修复暂缓。**

记录日期：2026-10-03。维护者要求与
[Agent 停止后会话问题](runtime-stop-session-issue.md)一并安排后续修复。
本记录不表示源码修正、浏览器验收、部署或阶段收口。

## 用户报告与验收要求

用户在前端把昵称修改为“大大”，菜单仍显示“Bootstrap Admin的个人工作区”。
维护者明确接受以下两种显示方式：

- `Admin的个人工作区`
- `大大（Admin）的个人工作区`

不得继续显示当前的 `Bootstrap Admin的个人工作区`。本次请求只授权记录问题；
具体显示方案与实现留待后续修复。

## 已确认的源码原因

记录分支基线：`adca19bae7bee1db28e33633f30c3f45bc432d27`。

- [`UserSettingsMenu.vue`](../../apps/frontend/src/components/layout/UserSettingsMenu.vue)
  的 `workspaceName` 直接使用 `auth.user.workspace.display_name`（基线行 27），
  侧边菜单和下拉菜单都使用这一值（行 60、68）。
- 同组件昵称展示使用独立的 `auth.user.display_name`（行 25）。
- [`ProfileView.vue`](../../apps/frontend/src/views/ProfileView.vue) 保存昵称成功后
  只更新 auth 中的用户 `display_name`（行 48），未更新工作区名称。
- [`user_auth.py`](../../services/backend/app/user_auth.py) 的 bootstrap 账号创建
  默认昵称为 `Bootstrap Admin`。

因此，菜单的工作区名称与当前昵称是两个独立字段；修改昵称后，菜单仍可沿用
初始化名称。本次只核对源码并保留用户报告，未对用户当前记录作新的数据库
查询或真实浏览器复现，不能把源码确认称为真实页面验收。

## 后续限定修复与验收（NOT_RUN）

1. 按维护者允许的形式投影个人工作区显示名，消除 bootstrap 初始化措辞；
   普通用户使用其自己的账号/昵称，不把所有账号硬编码为 Admin。
2. 核对侧边菜单、下拉菜单及移动端的相同展示来源；如选择昵称形式，保存昵称
   后即时更新，并在刷新/重新登录后保持一致。
3. 保留账号、Workspace ID、所有权和权限语义；显示名修复不要求重置用户数据
   或批量修改现有数据库。
4. 用定向组件/合同验证及真实 Gateway/Product API 浏览器证据验收受影响页面，
   经 Tester → 独立 Reviewer → Root 门禁；不默认重跑行情、模型或 A–D/F6。

## 本次操作边界

中断前只同步 main 并创建隔离分支，未修改实现，未启动测试或服务。
本次仅集中保存两项问题文档及索引；未推送、合并或部署。
