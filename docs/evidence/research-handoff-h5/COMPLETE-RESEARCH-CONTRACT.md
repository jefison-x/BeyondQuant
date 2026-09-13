# H5 三轮研究验收合同（未执行真实模型）

固定场景见 `tests/dsh_upgrade/h5_research_contract.py`，仅接受 h5-research-user、
独立工作区、原任务、冻结股票池及两只明确标记为合成行情的标的。
当前只是验收门禁，不能作为H5完成证据。

模型须在同一原任务内实际完成三轮不同策略版本的回测，逐轮读取前轮事实，再保存validated报告。
报告逐项对应原job ID、策略版本和实际总收益率，按约定规则选优；人工经Product API/页面创建
模拟账户并绑定原池和原快照，再核对完成证据。BYQ MCP当前不提供模拟账户写能力，不为测试扩权。

独立校验器拒绝未完成/缺轮次/错任务/错池/错策略版本/虚报收益/错选优/错账户工作区/缺报告引用。
两项单元测试（含10种反例）通过，测试中对象为明确的内部夹具，不是实际研究结果。
工作区ID形式已与当前WorkspaceTenancyStore核对。

仍需完成：封闭数据及服务栈、固定提示和预算的真实模型测试资格、实际Product API/浏览器流程、
原始工具读写次序与重启/交接证据、持久结果回读和资源清理。未读取模型密钥、未付费调用。
旧U5/U7固定场景资格不冒充新H5场景资格。三年历史指数缺月仍按已有readiness证据明确不可用。

## 原对象只读采集准备

新增 collect_completion：仅按操作者保存的原task、三个job、report、account ID读取六个明确Backend路径；核对响应对象ID再交给完成校验器。
路径与当前Backend真实task/artifact直接响应、job/account封装响应逐项核对。只读回调由后续隔离执行器提供，本函数不读取密钥、联网、搜索目录、重试或写入。
4项合同测试通过，新增路径/次序、重复或非法ID在调用前拒绝、被替换报告拒绝。夹具仅验证采集合同，不是实际研究执行证据。
仍缺真实隔离服务栈、已授权模型执行器、逐轮工具时序及实际对象回读；H5仍未完成。

补充六个读取位置分别缺失/超时的12个反例，要求停止在原位置、无重复路径、无替代对象；当前5项合同测试通过。仍为内部夹具测试，没有实际三轮研究或模型执行。

## 独立 H5 栈候选

新增 h5_stack.manifest 复用旧验收栈生成器的封闭服务定义，使用独立 byq-h5 资源命名/标签；不读取部署Compose或.env，不继承模型密钥。
补 signal-worker 与 signal-sandbox 后共10服务。沙箱仅在内部signal网络，不带数据库/模型环境或持久卷；原model网络设internal，Runtime模型key为空，配置明确execution-authorized=false。
实际高层回测由Backend run_backtest_job/BacktestWorker.run_once执行，未加入不必要的常驻回测worker。
两项配置测试和 docker compose --env-file /dev/null ... config --quiet通过；未构建、启动或访问真实Provider。
仍需镜像当前源码/依赖可用性核查、完整栈只读preflight及cleanup、合成行情准备、真实模型与审批/许可/三轮工具链验收。配置存在不算运行资格。

## 信号组件实际启动探针

当前signal-worker源码在无网络容器成功import；临时屏蔽packages目录后仍通过，未发现猜测的缺失模块问题。
当前signal-sandbox server.py/runner.py只读挂载到保留依赖镜像 sha256:f30b6907408456886521e419dfd6fe1affcdc4c04a398a2c4a67ee43c5ddbefc；这是当前源码组件探针，不是新镜像构建验收。
容器network=none、只读根、32MiB noexec tmpfs、全部cap移除、896MiB/1CPU/32pid限制；无DB或Provider密钥。
h5_signal_probe.py 经真实回环HTTP触发子进程，对两标的合成单日输入产出精确两个信号，禁止import os被source_rejected拒绝。
探针容器自动删除后docker ps -a精确名称查询为零。未使用模型、未创建回测、未写研究完成结果，不替代H5三轮研究验收。

候选原始配置增加 validate_candidate 完整匹配生成定义；七类变更（模型网络、密钥、沙箱数据库网络、主机挂载、特权、伪造授权标记、额外服务）均拒绝。H5栈与采集合同共8项通过。它只验证原始配置，不能证明实际容器状态或授予模型运行权限；运行态preflight和cleanup仍待接入。

## 实际网络 preflight 切片

inspect_networks 对Docker实际inspect结果核对精确4网络集合、bridge驱动、scope标签、Internal属性并拒绝Ingress。4项栈合同测试通过，包含6种实际网络结果变更反例。
已实际创建独立随机byq-h5-netcheck作用域的4个空Docker网络并读取inspect通过；无容器、无数据连接。finally按本次创建的精确ID删除，按scope标签复查剩余零。
此证据只覆盖网络，实际容器镜像/进程/环境/挂载/健康和整栈清理检查仍待实现，H5未完成。
