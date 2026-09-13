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

## 本地发布器重定向分类补正

复核发现 `.97` 仅拒绝跳转，但 urllib HTTPError 的3xx仍走旧默认 validation_rejected；此前仅检查目标零请求的测试未覆盖该分类。新增断言先失败，保留此遗漏事实。
现在3xx明确 transport_ambiguous。五种301/302/303/307/308回环测试均要求目标零请求且错误为未知；全部发布器16项通过（6.31秒）。未部署旧错误候选。

## Relay失效拦截修正与慢响应证据

发现旧坏JSON测试仍patch urllib.request.urlopen，而实现已使用build_opener.open。修正为拦截实际Opener，并断言5次请求与5次实际read；四个畸形/超限响应拒绝，正常JSON成功对照通过。完整Relay7项通过（1.12秒），无外部网络。旧测试的通过不能证明曾读取过坏响应。

独立无网络容器的回环HTTP慢响应实测：publisher._json_request(timeout=0.08)，每0.03秒发送一个字节，实际0.320秒后返回正常成功。确认socket timeout不是整次header/body deadline；本轮仅复现，尚未修复，Python发布器/Relay人工入口审计仍不关闭。没有外部服务或真实认证。

## Python整次请求期限候选

两个Worker确认在Linux主线程串行调用HTTP，只有健康服务在后台线程。新增共享feedback_http_deadline.request_deadline，以POSIX实时时钟覆盖连接/响应头/正文；finally清除本次timer并恢复原SIGALRM处理器。拒绝非主线程及已有timer，不覆盖其他定时器、不启动遗留网络线程、不自动重发。默认仍12秒，Relay与Publisher保留各自hub_unavailable/transport_ambiguous映射。此辅助函数不适用于通用多线程HTTP客户端，也不改变Agent会话时限。Docker与CI显式加入同一模块。

真实无网络容器回环测试覆盖慢响应头和慢正文：每30毫秒持续发送字节，120毫秒期限触发未知结果，耗时小于800毫秒；后续快速请求成功，timer归零、原handler恢复；嵌套timer与非主线程调用在网络前拒绝。Publisher完整19项通过（7.62秒），加强线程异常传播后定向复核另行执行。Relay新增测试初次因缺threading导入未执行到请求，已修正并重跑，原失败不作为运行缺陷。新候选尚需构建、架构检查及远端CI，人工入口整体审计仍未关闭。

修正后Relay完整8项通过（2.14秒），共享期限增强测试3项通过（1.34秒）；124项架构、dev-check语法、CI脚本语法及`.109`构建身份通过。尚未新镜像运行或远端CI验证，不标记整个人工入口完成。

两个Worker当前源码与共享模块按Docker同目录布局只读挂载，清空额外PYTHONPATH后均成功import；依赖仍由保留镜像提供，此探针不是新镜像构建证明。

## Provider回执内部ID资格

Python _complete 原来仅检查id非空，六个反例True/-1/浮点/数字字符串/对象/数组均复现可进入Backend complete请求。URL使用原配置仓库合法地址，避免URL拒绝掩盖ID缺陷。现在仅接受非bool正整数，畸形回执保持transport_ambiguous且Backend调用为零；完整Publisher25项通过（7.18秒）。这是边界反例，不是生产收到畸形GitHub回执的证据。

CI影响分类已核对workers/*触发Backend、架构及集成，共享期限模块不会漏出组件选择。`.108`目前只有已修正的前端模拟用例失败，Backend尚在运行；不提前取消剩余作业。

部署权限探针：实际uid/gid10006与10007分别在network=none、read-only、cap-drop ALL、no-new-privileges容器内触发40毫秒deadline并中断300毫秒等待；原SIGALRM处理器恢复、timer归零且下一期限正常。两个容器--rm退出，不需要root或额外capability。仍是保留依赖镜像加当前共享源码的权限验证，不冒充完整新镜像资格。
