# Docker image-store 身份核验修复

主流程 PR #276 已合并；主线镜像发布 run `34544965649` 的 Full、归档、GHCR publisher、
SPDX SBOM 和 GitHub attestation 全部通过。来源为 `8fd72bb7dad5f0db431482a80b0364163d020512`。
发布清单 SHA256 为 `2abde0cedaa731ff6900fb180d41d0df010fc7f772bced502d76621c2f706f81`。

独立验证已确认：来源签名、main ref、source SHA、成功 workflow、11份 SBOM 哈希通过；
GHCR 匿名读回的11个 manifest 内容摘要及其 config digest 均与清单一致。
这些是本次具名发布证据，不是 STATUS 中的固定 main 基线。

本机 Docker 29.1.3 containerd store 的 image inspect `Id` 是 manifest digest；
云端 classic store 的 `Id` 是 config digest。原配置生成直接比较二者导致误拒绝。
前端实测原失败保留；没有执行 Compose up 或切换生产服务。

修复同时核验：注册表 manifest 的 config digest、拉取后的精确 RepoDigest、linux/amd64，
以及 store 对应的 config ID 或 manifest ID/Descriptor。未绑定的 ID、错误 config、
错误 RepoDigest/Descriptor 和错误平台均拒绝，未放宽为“任意 SHA 即通过”。

本地237项架构/脚本测试通过；同一个真实 GHCR 前端镜像重测后，digest overlay 生成通过。
本机用户目录 GitHub CLI 已更新到官方校验过的 2.100.0，以支持 attestation/source 校验。
远端最终结果补记于修复 PR；不重新发布未改变的应用，不创建正式 Git tag/Release。
