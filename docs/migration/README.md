# Migration Policy

## Legacy references

- Community reference: `/home/jefison/projects/BeyondQuant-community`
- Community GitHub repository: `jefison-x/BeyondQuant-Community`
- Historical GitHub repository: `jefison-x/BeyondQuant-Legacy`

新项目工作中，Community repository 是 **READ-ONLY** reference。Community
和 Legacy repository 都不是本项目 Git history。

## Migration policy

Legacy code 是 source material，不是 architectural authority。新架构优先于旧
implementation structure、runtime choices 和 service boundaries。

实现 legacy capability 前：

1. 将旧 implementation 作为 reference 检查。
2. 识别 domain invariant 和必需 contract。
3. 分类 legacy module。
4. 在新架构中干净实现 capability。
5. 广泛采用前先增加 tests/contracts。

Legacy modules 最终必须在 `legacy-inventory.md` 分类为：

- `MIGRATE`
- `REFACTOR`
- `CONTRACT-ONLY`
- `DROP`

没有显式 inventory decision 和 architecture review，不得复制 legacy module。

## Productization references

- [Productization Gap Audit](../roadmap/PRODUCTIZATION_GAP_AUDIT.md)
- [Community Frontend Migration](COMMUNITY_FRONTEND_MIGRATION.md)
- [Community Market Data Migration](COMMUNITY_MARKET_DATA_MIGRATION.md)
- [Permanent Community Migration Inventory](COMMUNITY_MIGRATION_INVENTORY.md)

Frontend/market-data 文档是 Phases 16–23 planning records，不授权未来 phase
implementation，也不授权写入 Community repository/database。
