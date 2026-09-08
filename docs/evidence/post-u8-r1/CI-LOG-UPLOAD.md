# CI 脱敏日志附件修复（2026-09-08）

状态：本地验证通过；远端附件实测待授权推送。未推送、未部署，不关闭 Post-U8 业务整改。

## 前一分支交付事实

维护者要求“先同步，合并代码。然后再继续整改”。PR #263 的精确 head
`4b5f82175ec3e891a0ad0118f4c121dc5ec7eb8d` 经贡献及服务器检查 preflight 后，
按 ADR-0015/0059 squash auto-merge，于 2026-09-08 11:29:03 UTC 合并。
主工作区已 fast-forward 到 `0063000a67cc0a3db11062200479fc438f3d01c9`。
未部署生产，未回放历史研究，未修改 Community。

远端 run `34218603419`：local-ci、contribution、ci-gate 均 success；实际 console
记录 26/26 checks passed，独立 cleanup verified。上传步骤为 success，但警告
`No files were found`，没有附件，不能把该步骤绿色描述成证据文件已上传。
历史运行及警告不覆盖、不重写；本缺陷说明原附件门禁不充分，不否定 console 中实际执行的测试。

## 原因和限定修复

工作流将两份脱敏输出保存到隐藏目录 `.ci-artifacts`。所锁定
[upload-artifact 源码版本说明](https://github.com/actions/upload-artifact/blob/043fb46d1a93c77aae656e7c1c64a875d1fc6a0a/README.md)
规定 `include-hidden-files` 默认 false、没有匹配文件默认只 warn。

显式允许隐藏路径，但把上传白名单缩为 `checks.log`、`cleanup.log` 两份脱敏文件，
不递归上传目录，不上传其他临时日志、环境变量或凭据；缺文件设为 error，保留 always
上传和七天保留期。该选项要求至少一个匹配文件，不能冒称逐个文件完整性验证。
不改变测试选取、检查门禁、清理范围或生产配置。

## 验证与身份

- 回归先运行：12 项治理测试中新增上传断言失败；另有一次旧构建源漂移导致测试准备错误。
  补充新身份后 12 项全部通过，未放宽断言。
- 新增不可变 `.13` 清单，不覆盖 `.12` 或历史失败/报告；应用逻辑未改。
- candidate manifest：`sha256:3322a1386a84fc39145f7cfcf5ed2b257e123cb0321853b02075edff666681c3`。
- compatibility manifest：`sha256:ec74c257588a07b5747455c8d6d478645bd7b3399084bf4e1c017f0cd67a87ad`。
- 两份 source binding 检查通过；225 项架构检查通过。
- 隔离完整 CI scope：`post-u8-ci-logs-20260908-13`，25/25 checks passed，退出 0；
  该次执行计划在证据文档新增前确定，文档检查另行运行，1 份通过，不虚报为流水线 26 项。
- Backend 490 passed / 1 skipped / 7 subtests（559.23 秒）；兼容 Runtime 144 passed / 32 skipped；
  candidate Runtime 153 passed / 23 skipped（14.40 秒），真实官方进程旅程 20 passed（31.61 秒）。
- MCP 完整 suite、前端构建和 175 项单测、20 项 mocked UI、9 项真实 Product 浏览器通过；
  重启和双用户持久隔离通过。mocked UI 输出过一次 ResizeObserver 警告，不冒称 console 全空。
- 暂存差异约 151 KB 的 Gitleaks 脱敏扫描通过，无新增豁免。
- CI 退出后的独立清理再次返回 `CI cleanup verified: post-u8-ci-logs-20260908-13`；
  仅移除本次合成测试资源，数据可用夹具重建，未移除生产或其他任务资源。
- 实际附件生成必须在新分支的远端 Actions 上验证；本地静态测试不替代上传实测。

本切片开发遵循继续整改授权；前一分支的单次合并不推定为本分支 push/merge 或部署授权。
DSH 0.1.2rc1、Product Phase 97、U8 提前结束及 F6 后台关闭结论不变；无付费 API。
