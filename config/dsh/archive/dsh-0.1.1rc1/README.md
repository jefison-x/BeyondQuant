# Retired npm closure

These byte-preserved `.archive` files are historical provenance/license fixtures,
not npm installation manifests. ADR-0069 retires this runtime from daily builds,
CI execution and dependency updates. Do not rename them into active manifests or
refresh their dependencies. The supported runtime uses the exact official
0.1.2rc1 Python wheels and bundled executable.

Historical images, backups, release descriptors and qualification records remain
unchanged. An archived image is not certification of current application source.

旧 Dockerfile、双版本部署准备/恢复演练及其专属测试也已以 `.archive` 保存原始字节，
仅用于历史证据核验，不属于构建或运行入口。当前 CI 的历史来源/许可证检查仍可能读取这些档案。
旧兼容实现已删除，通用生命周期及规范化测试改用受支持的 0.1.2 实现。
