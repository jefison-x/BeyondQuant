# BeyondQuant 版本规划

Status: Accepted planning baseline — 2026-09-11。
依据 [ADR-0071](../architecture/adr/ADR-0071-v1-machine-learning-release-plan.md)。
维护者确认：“1.0版本应该在支持当前市面上常用智能机器学习模块开发运行稳定以后再发布。”
随后接受调研方案：“好的，就按这一份方案进行版本规划。”

本计划冻结交付目标，不把规划接受等同于模型已支持、Phase 已授权、镜像已发布或生产已验证。
当前 Product Phase 97 和 Beta 状态保持不变；下一 Product Phase 仍以 [STATUS](STATUS.md) 为准。

## 产品范围

1.0 定位为 A 股日频为主、支持主流机器学习与深度学习的稳定量化研究平台。
用户通过界面或小巴组合已支持的特征、目标、模型、参数、验证和有限调参，完成训练、
样本外预测、冻结信号、原生回测及结果比较。新增算法实现通过 Engineering 的代码、CI 和发布进入注册表。

必备清单见 [模块支持矩阵](V1_ML_SUPPORT_MATRIX.md)，发布条件见
[稳定性与发布验收](V1_RELEASE_ACCEPTANCE.md)。支持必须精确到模型、任务、运行环境和证据，
安装依赖或单次训练成功不能代替完整研究闭环。

## 版本里程碑

下表均为规划目标，未创建这些 Git tag/Release，也未更改现有 package version 或镜像身份。
一个产品版本可以含多个独立 Phase/维护批次；不要把版本号当作 Phase 编号。

| 版本 | 交付范围 | 完成门槛 |
|---|---|---|
| 0.9.0 | 为现有 Beta 建立统一产品版本和已知限制基线 | 发布清单绑定源码、镜像和实际服务组合，完成独立发布验收 |
| 0.9.x | 完整 F2、剩余全接口审计、复合研究故障回归 | Post-U8 各项有最新结论；不把 F6 完成或健康检查等同整体关闭 |
| 0.10.0 | S3、历史成分准备、可版本化特征与时点数据基础 | 真实数据基准可复现；同时完成 HIST 数据可行性及深度学习环境资格调查 |
| 0.11.0 | 目标/统一评估扩展；Ridge、Lasso、ElasticNet、Logistic、Random Forest、Extra Trees | 传统模型在统一数据与验证合同下完成研究闭环 |
| 0.12.0 | XGBoost、CatBoost，LightGBM 分类/排序扩展 | 提升树在同一条件下公平比较；逐任务验收 |
| 0.13.0 | 独立深度学习 Worker，MLP、LSTM、GRU、TCN | 序列输入、长训练、取消、重启和模型加载稳定 |
| 0.14.0 | 有界小型 Transformer、有限调参、固定融合、实验比较 | 选择过程可追溯，最终测试集不参与调参或融合权重选择 |
| 0.15.0 | HIST 与历史行业/概念关系快照 | 关系来源、历史可见性、资源上限及真实端到端闭环通过 |
| 1.0.0-rc.N | 功能冻结、完整矩阵回归与连续稳定性观察 | 所有必备项符合发布验收，整改后观察有独立证据 |
| 1.0.0 | 首个稳定研究平台版本 | 维护者确认正式发布；执行 ADR-0015 的合并治理切换 |

顺序依赖：现有可靠性 → 数据/特征/环境资格 → 传统模型 → 深度运行基础 → 时序/注意力 → HIST → RC。
HIST 的数据调查在 0.10 提前进行，不能到 0.15 才寻找历史关系；深度环境也须提前确认。
调查不是 Provider 下载、数据迁移、GPU 采购或生产部署授权。

## 首批规划分解与风险

- 0.9.x 沿现有维护台账收尾，不重复实现已完成的 F6、Ridge、walk-forward 或专家路由。
- 0.10 先冻结数据基准：标的、区间、特征、缺失/停牌/退市口径、时点来源、摘要及许可。
  S3 功能闭环与实际数据扩容分别验收；不能以“全市场全历史”代替有限、可测的支持范围。
- HIST 资格报告须明确历史行业/概念 membership 是否可证明、缺口和可用区间。
  无法验证时登记阻塞，由维护者明确修订本计划；禁止静默删除必备项或用当前关系回填历史。
- 深度环境资格报告须给出候选 Python/PyTorch、模型格式、CPU/GPU profile、镜像大小、
  代表性训练/推理耗时和峰值内存。未知项保持待测，不根据包可安装推定支持。
- 后续每个版本在开工前拆为合同、实现、Product/MCP/UI、故障/性能验收等具体 Phase；
  新的 Accepted ADR 和 STATUS 下一阶段授权就绪后才实施，不在这里预授权全部 Phase。

粗估 80–140 工程人日，加至少两周 RC 观察；是规划估算而非排期承诺，也不等同 AI 运行时间。
依赖兼容、历史数据和资源资格调查完成后再分批重估，不以压缩测试兑现日期。

## 运行与开发边界

- 复用 BYQ capability registry、领域任务和模型/预测/信号合同，不引入第二任务引擎或 Agent harness。
- 传统模型优先 CPU；深度模型依赖和资源隔离。GPU 是独立资格验证的可选 profile，基础安装不强依赖 GPU。
- GitHub CI 构建镜像并执行合同和小规模真实训练；大数据训练、持续负载和 GPU 资格在明确配置的
  研究 Worker 上验证，不把生产数据/凭据送入公开 CI，不假定免费 runner 能完成 GPU 验收。
- Product 仅经 Product API，Agent-to-Domain 仅经 BYQ MCP；DSH 不训练、不推理、不读业务库或模型对象。
- 框架版本在各批资格验证时精确锁定。模型格式逐 profile 验证；保持 pickle/joblib 和任意对象加载禁令。
- GPU、有限调参、HIST、新 Worker 拓扑等须有具名实施 ADR；本规划不解除 ADR-0043/0048 的现行限制。
- 任意 Python/模型上传、无限 AutoML、在线学习、强化学习、实盘券商不在 1.0 必备范围。
  Chronos/TimesFM 为后续实验候选，需评估预训练数据重叠、适配、资源和实证价值。

## 版本与制品规则

- 产品版本、Product Phase、DSH 依赖版本、内部 build ID 分开管理；历史 post-u8 构建不重命名。
- 0.x 按里程碑递增次版本，兼容修复递增修订号；RC 从 rc.1 递增。
  1.0 起兼容修复用 patch、兼容功能用 minor、公开接口不兼容修改用 major。
- 单个提交不必发布版本；发布后的版本不能覆盖，变更必须使用新版本。
- RC 到正式版复用相同已验证镜像 digest，不重编译；若需修改镜像内版本字符串等内容，必须产生新候选并重新验证。
- 发布记录包含产品版本、source SHA、CI run、全部服务的精确 digest、内部构建身份、迁移分类、
  实际部署范围、备份、回退版本和验收证据。部分服务更新时记录完整组合，不能声称所有服务均为新构建。
- 生产固定 digest；部署沿 ADR-0059/0070 的备份、旧镜像保留、排空、健康/业务验收轻量流程。
- 本次不自动创建版本 tag、GitHub Release、不改 promotion 工作流、不设置自动镜像删除。
  镜像保留自动化作为独立维护；任何规则均须保护当前生产、回退及正式发布引用的 digest 和清单。

## 规划来源

调研日期：2026-09-11。以下支持技术选型，不是市场占有率统计或 BYQ 已通过兼容资格的证明。

- [Qlib 模型库](https://github.com/microsoft/qlib)：提供树、时序和图模型的量化研究参考；不将 Qlib 整个平台引入 BYQ。
- [scikit-learn 算法体系](https://scikit-learn.org/stable/supervised_learning.html)。
- [HIST 原项目](https://github.com/Wentao-Xu/HIST)：关系数据与模型研究参考；复用须先核对许可及来源。
- [XGBoost 模型 IO](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html)、[CatBoost 模型保存](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_save_model)。
- [scikit-learn 持久化](https://scikit-learn.org/stable/model_persistence.html)、[PyTorch 可复现性](https://docs.pytorch.org/docs/stable/notes/randomness.html)。
- [Chronos](https://github.com/amazon-science/chronos-forecasting)、[TimesFM](https://github.com/google-research/timesfm)。
- [SemVer](https://semver.org/lang/zh-CN/)、[现有 ML 扩展计划](MACHINE_LEARNING_EXTENSIBILITY_PLAN.md)。
