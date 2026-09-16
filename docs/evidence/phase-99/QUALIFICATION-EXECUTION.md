# Phase 99 — 0.10 资格调查执行证据

2026-09-17，隔离工作树；依据 ADR-0074。仅调查与只读核对，不实现数据扩容、不引入 HIST、
不授权 GPU、不改运行能力或生产状态。

## 1. 深度学习环境 CPU profile（实测）

隔离容器 `python:3.11-slim-bookworm`，仅安装 PyTorch CPU wheel；合成输入
`x=[1024,20,10]`、`y=[1024,1]`，2 线程，固定种子。命令：

```bash
docker run --rm --network bridge -v /tmp/dl_measure.py:/tmp/dl_measure.py:ro python:3.11-slim-bookworm \
  sh -lc "pip install --no-cache-dir --quiet torch --index-url https://download.pytorch.org/whl/cpu && python /tmp/dl_measure.py"
```

实测结果：

| 项 | 值 |
|---|---|
| Python | 3.11（宿主另有 3.14，未安装 torch，作为不兼容候选记录） |
| torch | `2.14.0+cpu` |
| 线程 | 2 |
| MLP 训练（1024×200，20 步） | 0.1296 s |
| MLP 推理 | 0.0003 s |
| LSTM(seq20,hid32) 训练（20 步） | 0.8824 s |
| LSTM 推理 | 0.0067 s |
| 峰值 RSS（含 torch 导入） | 352.8 MB |
| 安装体积 | `site-packages/torch` 773 MB；`site-packages` 合计 908 MB |

未测（保持 `not_measured`）：GPU profile、真实数据规模训练、取消/重启/迟到结果的故障矩阵、
数值容差（确定性路径可比对，但本批未建立容差基线）、镜像 digest 与 SBOM。
这些属于 0.13 实施前的补充资格，不因本批通过而推定。

## 2. HIST 历史关系数据（只读核对，结论：blocked）

只读核对本机可用来源：

- `/home/jefison/projects/BeyondQuant-community` 不存在；`/home/jefison/projects` 仅含
  `BeyondQuant` 与 `BeyondQuant-Cloud`。
- `docker ps` 无 Community/Legacy 容器，`docker volume ls` 无 Community/Legacy 卷。
- 与 [S3 历史指数成分准备记录](../post-u8-r1/S3-HISTORICAL-PREPARATION.md)（2026-09-08 未收到只读导出）一致。

结论：当前**无法取得**历史行业/概念 membership 的只读样本，`V1_HIST_DATA_QUALIFICATION`
维持 `blocked`（来源、可见日期、覆盖区间、许可均 `not_proven`）。不做下载替代、不迁移、
不用当前关系回填历史。解除阻塞需维护者提供只读逻辑导出或可用只读连接。

## 限制

- 本证据为隔离合成测量，不是 1.0 release-verified；不宣称任何模型已支持。
- 不读取或披露任何凭据；不访问生产数据或 Community 原始实现。
