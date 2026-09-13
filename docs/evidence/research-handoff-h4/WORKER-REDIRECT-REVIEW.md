# 后台 HTTP 重定向审查（进行中）

## 已复现与修复

Python feedback-hub-relay 和 feedback-publisher 的固定端点 JSON 请求使用 urllib 默认重定向处理。
在无外网容器内设置两个不同端口的回环服务，原地址返回 302 到第二服务；携带合成 Authorization/服务头的请求原先成功返回，未拒绝重定向。
测试先失败（DID NOT RAISE），不能据此推定生产实际发生凭据泄漏。

候选在两个 worker 禁止自动 HTTP 重定向；返回原有 hub_unavailable/发布未知错误分类。没有新增重试、变更原请求身份或放宽发布单次创建许可。
新增验收要求重定向目标没有收到任何请求（含凭据）。完整 worker 测试 relay 7 passed（1.69 秒）、publisher 12 passed（2.30 秒）。

## 剩余

Cloudflare publisher 的 GitHub fetch 及 Hub service-binding 仍需独立检查；HTTP 响应有界性与错误分类、其他人工入口、构建身份和 CI 尚待完成。
不将两个 Python 修复推广成所有工作进程完成；不将合成回环测试说成生产安全事故；本候选未提交、推送或部署。

## Cloudflare 候选补齐

GitHub fetch 与 Hub service-binding 请求显式 redirect=error；错误沿原未知结果路径进入原事件 retry，不获得第二次创建许可。
畸形 GitHub 201 回执改为 transport_ambiguous，要求 issue number/id 均为正安全整数且 URL 精确匹配固定仓库；此前 validation_rejected 会把无法证明结果的回执误作确定失败。
实际 workerd 测试 22 passed（1.77 秒），包含新增 redirect_error/malformed_success、原许可拒绝及有界目录核对；类型检查、部署计划4项和两个 Worker dry-run 打包通过。无 Cloudflare/GitHub 生产写入。
Cloudflare 测试使用合成 fetch 与 binding 响应，不能替代生产网络重定向实测；Python 两回环服务已验证目标零请求。
剩余响应读取总时限/大小边界与完整人工入口审计继续；本次不标记这些入口全部 VERIFIED。

独立 .97 清单 sha256:75059dc3dbf2b9adf67ef1036efc6f9c11a6326cfff643bf770700832f149f18；124 架构、make dev-check、台账一致性检查通过。台账仍114/560，人工入口仍8项待审。未推送本候选，等待既有 .96 CI 完成后再更新 Draft PR。

## Cloudflare 响应边界

新增 boundedResponse 接缝，GitHub 与 Hub 请求在响应头/正文合计12秒内读取；分别限制8MiB和512KiB实际字节，不信任 Content-Length。
通过 AbortController 取消请求，同时以 Promise.race 保证不依赖对端响应 abort 才结束；退出时取消未完成正文流，不新增请求或许可。
实际 workerd 26 项通过（1.92秒），四项新增覆盖正常回执、伪造长度下超限、永不返回响应头、正文停滞和流取消；定向时限用50ms，生产默认12秒。
类型检查与两个 Worker dry-run 通过，尚未部署。Python worker 的12秒 socket timeout 仍不代表总正文期限，此剩余事项未关闭。
