# DSH Plugin Qualification

## Lifecycle

```text
discover → register AVAILABLE → inspect official source → verify exact package/integrity
→ dependency/peer closure → capability/risk/credential audit → keyless initialize
→ contract/security/Agent/MCP tests → QUALIFIED → policy + assignment → ENABLED
```

`scripts/dsh/plugin_registry.py` fail closed 检查 duplicate/unknown state、semver range、未知
publisher/package、integrity/lock mismatch、rc mixing、缺失 risk/capability、unqualified enable、
prohibited capability 和 invalid Agent assignment。正常 deployment 只使用 `npm ci`；禁止
`latest`、caret、tilde、override、`--force` 和 `--legacy-peer-deps`。

## Plugin onboarding

1. Discover official package；
2. 以 AVAILABLE 登记；
3. 检查 official source/README/package exports；
4. 固定 exact version 与 integrity；
5. 分类 capability；
6. 分类 risk；
7. 验证完整 dependency/peer closure；
8. 运行 qualification tests；
9. 全部通过后改为 QUALIFIED；
10. 明确 Agent assignment；
11. Product policy 设为 enabled；
12. 重新生成 composition/identity；
13. CI；
14. 正常 build/deploy。

禁止 `npm install latest → production`。若插件要求比当前 baseline 更新的 runtime，登记为
`BLOCKED_BY_RUNTIME_VERSION`，并转入既有 DSH Upgrade Lane；不得自动升级。

## Secrets 与 smoke

CI 运行 keyless package/init/tool-registration/permission tests。真实 Web Search smoke 只在
operator 提供 credential 时运行，结果不作为 golden fixture，secret 不进入 composition、
identity、readiness、WorkflowTrace、error 或 log。

## Rollback

将 profile 移除目标 plugin、重新生成并通过 CI，随后用正常 image lifecycle 部署。停止/
释放旧 owned session process；不删除 Agent Plane log 或 BYQ business data。若 cross-version
resume 未证明，保留旧 log 作为 audit 并创建新 runtime session。
