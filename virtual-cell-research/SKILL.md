---
name: virtual-cell-research
description: 为虚拟细胞研究提供真实观测数据教学、输入审计、基因 KO/OE、药物转录响应探索和结果复核。用户希望学习虚拟干预、检查数据、选择模型、运行案例或整理结果时使用。先继承已给信息并检查数据和环境，只合并询问关键科学缺项；区分案例收录、文件获取、数据准备、模型执行与独立验证，按实际后端能力交付完整结果。
---

# Virtual Cell Research：虚拟细胞研究流程

把研究问题、输入适配、实际运行和结果证据连成一条可复查的流程。先阅读必要文件，再选择与数据相符的路线；不要要求新手先学会挑模型和解释器。

## 1. 选择入口并补齐真正的缺项

先从当前请求判断入口；已明确时直接继续：

| 入口 | 实际工作 | 完成依据 |
| --- | --- | --- |
| 真实数据教学 | 默认推荐 HT115 处理与对照的观测阅读；显式获取所选资源后计算差值 | 新的来源、完整观测差值、条件索引和 QC；不是模型推理 |
| 输入审计 | 核实数据是否满足指定路线的输入假设 | 检查记录与具体阻断原因；发现输入问题不等于模型失败 |
| 真实模型分析 | 检查用户/参考数据与模型资源，运行兼容路线 | 本次命令、日志、版本、模型原生输出和检查记录 |
| 已有结果或历史复核 | 读取报告、清单、表格、图与勘误 | 指明读取了哪些已有产物，不声称本次重跑 |

首次使用读 [首次使用](references/first-run.md)，按 [案例目录](cases/README.md) 选择具体案例。`python scripts/cases.py list`、`show <case-id>` 和 `validate` 离线运行；只有明确的 `fetch <case-id> --asset <asset-id> --output-dir <新目录>` 才下载一个资源，默认限额 64 MiB。不要自动下载全部案例。

新手入门可执行 `scripts/observed_prnet_case.py` 的 HT115 教学：约 3.14 MB 的真实来源数据，按指定对照计算 661 条处理表达谱的观测差值，保留 20 条对照和 978 个基因。338 条处理谱跨 RNA plate 配对，必须说明可能的批次影响。该步骤不加载或运行 PRnet。模型分析用户已指定输入和目标时，不改成教学案例。

**先观察，后提问。** 继承用户已给的数据、目标、基线、模型和环境；读取可访问文件的元信息、已有处理记录和可用模型环境。启动阶段最多一轮简短合并提问，只询问会改变研究问题或科学解释、且无法从现有信息核实的缺项，例如目标基因、逐个还是联合扰动、实际细胞背景、对照、药物库或 CellOracle OE 设定。不要重新列出六项必填表。

用户未指定的模型、兼容解释器、工作目录和普通运行参数，可依据研究目标、输入及资源给出可更改默认，简要说明理由并记录；满足条件后直接运行，不再询问“确认开始”。不能默认猜测基因/药物、原始计数来源、疾病参照、OE 生物学设定，或静默替换用户指定的模型、基线、目标与任务。关键科学输入不明确时完成检查并报告阻断项，不启动对应推理。后续新发现实质性输入矛盾时可再次询问该问题，不重复索取已知设置。

## 2. 检查输入与真实可用能力

按 [输入契约](references/input-contracts.md) 检查格式、尺度、物种、基因 ID、细胞背景、目标覆盖、对照及药物/剂量信息。缺失与实测零值分别记录；未知尺度不靠数值外观猜测，缺失的必需基因不静默补零。疾病参照仅在疾病方向比较时必需。

需要文件级检查时，按 [预检与排错](docs/troubleshooting.md) 准备请求并运行 `scripts/preflight.py`。H5AD 默认仅检查元数据；显式设置 `scan_h5ad_values: true` 可按块扫描所选 dense/CSR/CSC 矩阵的全部存储值。数值检查不认证原始 counts 来源、稀疏索引、`n_counts` 一致性或模型兼容。`incomplete` 表示必需检查未完成，`preflight_ready` 只覆盖有限预检范围；读取阻断项与未检查项后继续后端核验。Paul2015 教程文件的 `raw_count` 非整数阻断是输入审计证据，不是模型运行失败。

| 路线 | 本仓库提供的入口 | 使用边界 |
| --- | --- | --- |
| CellOracle | `examples/ko_oe/celloracle_run.py` 参数化脚本 | 单细胞原始计数、匹配 GRN 先验和可模拟 TF；输出模型表达差值与状态位移 |
| Geneformer | `examples/ko_oe/geneformer_route.py` 参数化脚本 | 本示例限人类完整原始转录组、匹配 tokenizer/权重和所需环境；输出 embedding 影响 |
| PRnet、chemCPA、UniPert-G2CP | `examples/lung_cancer/` 下的历史适配脚本 | 需核对并适配路径、输入、环境和权重；不能把历史脚本存在当成本机已可运行 |
| GEARS、UniCure、DrugReflector | 相应 workflow 参考文档与代码片段 | 按任务准备数据、资源并实现/验证适配；尚非统一的一键入口 |

模型选择读取 [能力登记](references/model-capabilities.md)，选定路线再读 [资源与执行入口](references/model-setup.md)。环境说明中的历史路径只作排查参考，不视为当前机器的安装事实。不同后端隔离环境，不把旧依赖强装进主环境。

## 3. 计算并保留结果原始含义

- **观测教学**：差值是来源处理谱减其指定对照谱，保留原始处理后尺度与跨板标记；不称为预测、单细胞前后追踪或模型验证。
- **CellOracle**：KO 设为 0；OE 必须给出内部 `imputed_count` 尺度内的固定值或分位数及依据，并报告基线高于设定值、因而被下调的细胞。随机化表达变化的投影是技术对照；原始与随机投影的向量差不能解释为特异信号。
- **Geneformer**：`delete` 删除目标 token，`overexpress` 改变排序编码；当前示例不支持 `inhibit`/`activate`。embedding 变化不转写成表达倍数、差异表达或药效。只在原始完整转录组来源核实后设置脚本的确认参数。
- **GEARS**：需要与目标背景及扰动类型匹配的训练数据；KO/CRISPRi 训练不能直接声称支持任意 OE。
- **药筛**：PRnet/chemCPA 外部基线须匹配权重的基因顺序、尺度、协变量与训练域，患者样本按 OOD 探索记录。UniPert-G2CP 使用模型自带对照，不支持在本调用中随意替换成用户基线或增加剂量。DrugReflector 保留原生排名/类别定义。
- 未列入实际入口的模型先按未适配处理，补齐来源、输入契约与运行证据后再接入；历史资料中出现模型名不构成当前能力。分子对接仅在用户已选药物和蛋白、且任务明确包含它时开展。

执行前记录有效设置、选择依据、实际解释器、代码/模型版本、权重/先验、输入哈希、参数、随机性与训练域。每个条件单独登记；失败条件保留错误，已完成条件保留产物，不覆盖历史结果。

## 4. 保存完整结果，再检查和筛选

观测教学先保存完整来源与观测差值；模型分析先保存全量预测、对应基线、响应、基因轴与条件索引，再做 Top 表、评分和绘图。按稳定药物/条件 ID 连接排名与响应，不能靠排序后的行号取另一张表。历史全量数据缺失时标明不可恢复项，不从图片或 Top 表补造。

保留后端实际支持的 `expression`、`network`、`state_embedding`、`ranking` 或 `docking` 输出；记录条件、单位、背景、来源、覆盖与 OOD 状态。

案例目录的 `catalogued`、`data_downloaded`、`prepared`、`model_executed`、`validated` 不可混用；阶段来自证据，不因脚本存在、下载成功或预检通过自动晋升。观测教学的 `model_status` 保持 `not_run`，`independent_validation` 保持 `not_assessed`。模型运行则分别记录：

- 运行：`result_available`、`partial`、`no_prediction`、`failed`、`not_applicable`。
- 响应：`response_status`，描述不同条件是否有可辨别变化及检查依据。
- 排名：分别记录 `condition_ranking_status` 与 `drug_ranking_status`；药物聚合后重新判断区分度，药筛 `ranking_status` 保留药物级兼容别名。不可区分时记 `unresolved` 并停止候选推荐，保留有效预测和合法的逐条件描述性方向。
- 独立验证：缺少匹配实验或独立留出验证时记 `validation_status: unvalidated`，不覆盖运行状态。

输入无法解释、无输出、非有限结果或关键索引缺失时阻断对应条件。高相关、排名并列和缺少独立验证不自动等于计算失败；通过技术检查也不等于药敏或疗效成立。

## 5. 生成适用的图和说明

出图前读 [下游结果规范](references/downstream-results.md)。按实际输出生成互补图组：表达响应、状态位移、embedding 影响或原生排名；图旁标注单位、基线和源表。只有提供适配疾病参照、且基因空间、表达平台与实验条件可比时才计算疾病方向分数；否则跳过该评分并保留原生输出。

药筛逐条件结果及全量响应先落盘；有表达输出时交付每药每条件的 Top 30 变化基因，并保留方向和稳定 ID。恢复方向分类只描述预测转录响应；无效或未评分条件保留“无法判定”及原因。

模型路线逐图登记 `figures/figure_manifest.csv` 的生成、跳过或失败状态；HT115 观测教学使用其实际输出的根目录 `figure_manifest.json`，不要求补造模型图清单。缺可选图不改写成功预测状态；图形失败只重画相关图，不重跑已完成模型。真实扰动验证图与模拟图分开，p 值、误差条、存活率和 IC50 只在有对应数据和方法时提供。

## 6. 交付可复查的运行包

输出目录必须新建。观测教学保留脚本实际生成的 `report.md`、`provenance.json`、`qc.json`、`figure_manifest.json`、完整表和原始数组，不补造模型推理记录。模型分析使用新的 `<analysis_dir>/results/<run_id>/`，保存 `manifest.json`、`provenance.json`、`raw/`、`tables/`、`figures/`、`validation.json`、`errors.jsonl` 和 `report.md`。脚本未自动记录的字段由执行者补充，保留原始记录。

报告先回答做了什么、哪些条件完成、用了什么基线、结果能说明什么，再给主要数值、源表/图、异常与下一步。明确区分历史读取、本次重跑、技术检查和独立验证。临床疗效、疾病机制、因果关系及靶点确证不由预测分数直接推出。

## 按需参考

- [首次使用](references/first-run.md)：HT115 入门、数据环境、KO/OE 命令、报告阅读和失败下一步。
- [案例目录](cases/README.md)、[catalog.json](cases/catalog.json)：七个案例的来源、资源、实际阶段及限制。
- [执行手册](references/execution-playbook.md)：默认设置、一次合并提问、运行记录和失败处理。
- [输入契约](references/input-contracts.md)、[能力登记](references/model-capabilities.md)：输入和模型适用范围。
- [资源与执行入口](references/model-setup.md)、[环境说明](references/backend-environments.md)：选定后端后核对资源和依赖。
- [KO/OE 参数化示例](examples/ko_oe/README.md)：CellOracle/Geneformer 的实际 CLI 与输出。
- [GEARS](references/gears-workflow.md)、[UniCure](references/unicure-workflow.md)、[DrugReflector](references/drugreflector-workflow.md)：按需适配的研究路线。
- [下游结果规范](references/downstream-results.md)：绘图、评分、条件索引和科学解释边界。
- [历史归档](archive/aivc-587579e7/reproduction-report.md)、[勘误](docs/audit-remediation.md)：仅在复核旧研究时读取，不充当新案例执行证据。
- [贡献指南](CONTRIBUTING.md)、[来源说明](THIRD_PARTY_NOTICES.md)：以单个案例或适配维护，保留原作者与资源许可。
- [预检与排错](docs/troubleshooting.md)：轻量预检请求、状态与常见问题的下一步。

维护现有仓库时做定点修改，不重新初始化 Skill。分发前检查文档链接、相关行为测试与 `scripts/package_skill.py` 的文件清单；不把模型权重、用户数据或临时运行产物加入分发包。
