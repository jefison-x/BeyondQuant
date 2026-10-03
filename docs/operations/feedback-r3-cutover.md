# R3 旧反馈记录切换预检

状态：ADR-0092 候选发布门槛；此页不授权部署或删除数据。

R3 候选移除本机审核与 GitHub 直发，并将 owner 的发布状态只投影自
Cloudflare Hub。旧本机 `product_feedback_publications`、`product_feedback_outbox`
及审核记录仍留在 PostgreSQL 供归档核对。旧记录不会自动迁入 Hub；直接切换可能
让已提交项无法撤回/继续处理，或让旧 Issue 链接从新的 owner 投影消失。

## 当前只读观察

2026-10-03 10:04:20 UTC 对当前正式 PostgreSQL 容器的 `byq_domain` 数据库执行
只读聚合，没有读取反馈正文、身份、ID 或凭据，得到：

| 表 | 行数 |
|---|---:|
| `product_feedback` | 0 |
| `product_feedback_publications` | 0 |
| `product_feedback_outbox` | 0 |
| `product_feedback_hub_outbox` | 0 |

当时 `submitted_without_hub` 与 `legacy_published_without_hub` 也均为 0。
这是一个时间点的证据，不能代替未来发布前的目标数据库预检。没有修改容器、表或数据。

## 发布前必须重做的分类

在目标数据库上以只读事务执行下列聚合，保存数据库身份、时间和结果到发布证据。
禁止输出 feedback 正文、用户信息、Issue URL、token 或记录 ID。执行者须先证明
连接的是目标数据库；不得把此 SQL 当成数据清理命令。

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT 'legacy_publications' AS category, count(*) AS rows
  FROM product_feedback_publications
UNION ALL
SELECT 'legacy_outbox', count(*) FROM product_feedback_outbox
UNION ALL
SELECT 'submitted_without_hub', count(*)
  FROM product_feedback f
  LEFT JOIN product_feedback_hub_outbox h ON h.feedback_id = f.feedback_id
  WHERE f.status <> 'draft' AND h.feedback_id IS NULL
UNION ALL
SELECT 'legacy_publication_status', count(*)
  FROM product_feedback
  WHERE publication_status <> 'not_queued';
COMMIT;
```

四个门槛计数必须全部为 **0**，并在停止旧入口写入到新版本接管期间保持成立，
才可继续该次 R3 发布评审。任一非零或查询失败都阻止切换；按记录状态、
已尝试外部副作用、Hub receipt 和旧 Issue 映射逐项分类，另行提出经接受的
迁移/归档方案和用户可见处理，不能直接清空表、丢弃 outbox、重发 GitHub Issue
或把未知结果标成已完成。生产旧表、镜像、备份的物理删除另设授权与清单。
