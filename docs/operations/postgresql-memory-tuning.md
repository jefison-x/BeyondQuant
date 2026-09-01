# PostgreSQL 内存调优运行手册

BeyondQuant 的 PostgreSQL 是 ADR-0016 定义的唯一权威 Domain Store。本调优只改变
PostgreSQL 启动时内存参数，不改变数据库、角色、schema、持久卷、备份或应用访问边界。

## 当前基线

当前单机约有 11 GB 内存，BYQ 数据库约 17 GB。此前 PostgreSQL 使用镜像默认值：
`shared_buffers=128MB`、`effective_cache_size=4GB`、
`maintenance_work_mem=64MB`、`work_mem=4MB`。首轮调优采用：

| 参数 | 默认值 | 用途 |
| --- | ---: | --- |
| `BYQ_POSTGRES_SHARED_BUFFERS` | `1GB` | 提高 PostgreSQL 共享数据页缓存，但为 Worker 和 OS page cache 保留内存。 |
| `BYQ_POSTGRES_EFFECTIVE_CACHE_SIZE` | `4GB` | 只向 planner 描述预计可用缓存，不会预分配内存。 |
| `BYQ_POSTGRES_MAINTENANCE_WORK_MEM` | `256MB` | 加快 VACUUM、CREATE INDEX 等维护工作；仍需考虑并发维护 Worker。 |
| `BYQ_POSTGRES_WORK_MEM` | `4MB` | 保持保守；它可能按连接和执行计划中的多个排序/哈希节点重复分配。 |

生产环境可在受控 `.env` 中覆盖这些参数。值必须使用 PostgreSQL 接受的内存单位，修改后
需要重启 PostgreSQL。不要仅为提高吞吐量而提高 `max_connections`；优先限制连接池并观察
实际并发。

## 部署前检查

1. 确认逻辑备份和最近一次 restore drill 有效。
2. 使用 `docker stats --no-stream` 确认主机有至少 2 GB 可用内存余量。
3. 确认没有运行中的大规模数据导入、索引创建、训练或回测任务。
4. 执行 `docker compose config --quiet` 验证 Compose 插值。

只重建 PostgreSQL 容器不会删除命名持久卷。不得运行 `docker compose down -v`，也不得改变
`BYQ_POSTGRES_VOLUME_NAME` 或把 Community PostgreSQL 挂载为 BYQ 数据卷。

## 应用与验证

应用配置：

```bash
docker compose up -d postgres
docker compose exec -T postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW shared_buffers" -c "SHOW effective_cache_size" -c "SHOW maintenance_work_mem" -c "SHOW work_mem"'
```

等待 Backend、Data Worker、Signal Worker 和 ML Worker 恢复健康，然后观察至少一个代表性业务
窗口。`pg_stat_database` 是累计统计；评估前记录起始快照，不能把历史批量导入产生的读盘直接
归因于新配置。

```sql
SELECT datname, numbackends, xact_commit, blks_read, blks_hit,
       round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS buffer_hit_pct,
       temp_files, temp_bytes
FROM pg_stat_database
WHERE datname = current_database();
```

同时记录：

- 主机及 PostgreSQL 的内存、swap、OOM/restart；
- Gateway/Product API 的 P50/P95/P99；
- Data/Signal/ML Worker 队列长度和任务耗时；
- `pg_stat_statements` 中 total execution time、mean execution time、shared block reads 和
  temp blocks 最高的查询（启用该扩展应另行评审并验证重启配置）。

## 继续调整的门槛

- 如果主机长期保持足够余量、没有 swap/OOM，并且热点读取仍明显受磁盘 I/O 限制，可在独立
  变更中把 `shared_buffers` 小步提高；单次调整后重新观察完整业务窗口。
- `effective_cache_size` 应根据 PostgreSQL 与 OS 实际可用缓存估计，不等于内存限制。
- 只有确认排序或哈希频繁落临时文件且并发上界明确，才考虑小幅提高 `work_mem`。
- 大 JSON 行、无界 `SELECT *`、缺少索引或重复计算必须在查询/存储层修复，不能靠扩大缓存掩盖。

## 回滚

若出现 OOM、swap 持续增长、容器反复重启或整体 P95 恶化，将 `.env` 中参数恢复为上一组值，
然后执行：

```bash
docker compose up -d postgres
```

确认 PostgreSQL 和依赖服务恢复健康，并再次查询 `pg_settings`。回滚只改变启动参数，不回退、
删除或重建数据库卷。
