# 租约观察切片：离线入口合同重审

本文件是执行前的固定合同，不是新测试框架。首次 Docker 125 失败保留在
`ROOT-LEASE-OBSERVER-OFFLINE-FAIL-STOP.json`。本批已停止，没有重跑。

## 已定位的入口缺陷

原命令把服务源码只读挂载到 `/app`，随后把共享合同挂载到 `/app/packages`。
宿主服务目录没有 `packages` 子目录，Docker 必须在已只读的父挂载中创建它，
因此在 Python 启动前失败。源码和测试断言均未执行。这不是产品行为失败。

此前采用了 CI 的子挂载位置，却把 CI 的父挂载改为只读，未同时核对挂载树。
只检查源码、测试函数和镜像 ID，不能证明容器入口有效。

## 最小修正

保持全部源码只读，改为两个平级挂载，避免在任何只读父挂载内创建目标：

| 来源 | 目标 | 模式 |
| --- | --- | --- |
| 本切片对应服务目录 | `/byq-test/service` | `ro` |
| 本工作树 `packages` | `/byq-test/packages` | `ro` |
| Runtime plugin runtime | `/opt/byq/runtime` | `ro` |
| Runtime plugin skills | `/opt/dsh/bundles/dsh-byq/skills` | `ro` |

工作目录固定 `/byq-test/service`，`PYTHONPATH=/byq-test/service:/byq-test`，
`PYTHONDONTWRITEBYTECODE=1`，pytest `-p no:cacheprovider`。
服务目录内的 `app` 和 `tests` 及按 `__file__` 读取的相邻 fixture 保持同一结构。
临时根文件系统和 `/tmp` 可写；不挂业务卷，不写宿主源码，不改变正式 CI。
Runtime 使用既有 `/opt/byq-venv/bin/python3`，Gateway 使用既有 `python`。

## 整个入口一起核对

1. **源码和依赖。** 使用已保存的五文件 SHA；依赖环境使用已核对的两个
   immutable image ID，`--pull=never`，不以宿主 Python 或可变 tag 替代。
2. **完整挂载树。** 所有源目录必须存在。任一目标不能等于或位于另一只读
   挂载目标之下；同时检查 workdir、Python import 路径、相邻 fixture、plugin
   路径和临时可写目录，不能只检查出错的一个路径。
3. **固定合同。** Runtime 六个节点和 Gateway 三个节点分两个进程，保持原
   已审查节点名单；不增加全组件 suite。未启动、未收集或依赖不明均不能算 PASS。
4. **资源边界。** 全新准确名称和 slice label，`--network=none`、只读源码；
   不传私有环境、凭据、Docker socket、旧会话卷或数据库；最多两个专用测试容器。
5. **先保存再判断。** 库存、命令和 SHA 在执行前保存，每步原始 stdout、stderr、
   rc、timeout 先保存再解析。第一故障不被后续错误覆盖；Runtime 失败不启动 Gateway。
6. **时间和退出。** 每进程最多60秒、总120秒，模型和 Job 上限均0。只处理本批
   精确名字且 label 匹配的临时容器；结束核对原27容器及源 SHA 不变。任何错误
   停止该批，不自动重试、不扩大范围。

源码重审不替代实际执行。用户后续要求修正后继续；独立Tester按新批次offline-v2固定执行一次，
Runtime6/Gateway3全部通过，独立Sol复核及Root限定离线PASS；原失败证据仍保留。
原两用户真实批次仍停止；`held=0` 只表示某个存活 Adapter 进程的瞬时租约计数，
不能证明 Runner 就绪，不能通过重启旧 Adapter 来冒称旧租约已释放。
