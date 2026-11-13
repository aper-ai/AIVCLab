![Virtual Cell Research：基因扰动、药物响应与可复现工作流](virtual-cell-research/assets/brand/header.svg)

[![Skill：研究预览阶段](virtual-cell-research/assets/brand/badge-skill.svg)](virtual-cell-research/SKILL.md)
[![数据工具环境：Python 3.12](virtual-cell-research/assets/brand/badge-python.svg)](virtual-cell-research/requirements-tests.txt)
[![工程检查配置：Ubuntu 与 Windows](virtual-cell-research/assets/brand/badge-checks.svg)](https://github.com/aper-ai/virtual-cell-workbench/actions/workflows/skill.yml)
[![许可：PolyForm NC 与既有 MIT](virtual-cell-research/assets/brand/badge-license.svg)](virtual-cell-research/docs/licensing.md)

# Virtual Cell Research · 虚拟细胞研究 Skill

**面向虚拟细胞研究的可复现分析与方法协作。**

一句话定义研究任务，发起虚拟基因敲除、过表达与药物筛选；Agent 组织数据检查、模型执行、结果复核和报告生成。

Virtual Cell Research 是面向转录组与单细胞研究的科研 Agent Skill，围绕**虚拟基因敲除、过表达与药物筛选**，衔接数据准备、模型执行、基线比较与结果解释。研究者提供表达数据、目标基因或药物库后，Agent 核对输入与对照、选择兼容模型、执行分析，并交付完整结果、图表和结构化报告。各路线的适用条件、实现程度与验证状态均有明确记录。

项目聚焦**干预前后的转录响应与细胞状态变化**：哪些基因变化、哪些细胞背景响应不同、模型预测相对简单基线表现如何。研究者确定科学问题和干预条件，Agent 组织准备、运行、检查与报告流程，保存方法与结果之间的可追溯记录，为研究假设的比较和后续验证提供依据。

[核心任务](#三项核心研究任务) · [快速开始](#快速开始) · [自有数据](#用自己的数据开展研究) · [真实结果](#四组真实案例从方法到结果) · [案例库](#案例库当前完成到哪一步) · [开放协作](#开放协作与生态共建) · [使用许可](#使用许可与商业授权)

## 三项核心研究任务

| 任务 | 你希望回答的问题 | 必要输入 | 主要输出 |
| --- | --- | --- | --- |
| **虚拟基因敲除（KO）** | 敲除一个目标后，模型中的表达和细胞状态如何变化？ | 表达矩阵、目标基因、未干预细胞背景；多目标需说明逐个还是联合 | 模型支持的表达响应、受影响基因、状态位移或表征变化 |
| **虚拟过表达（OE）** | 按指定方式提高目标，哪些下游响应值得继续研究？ | 表达矩阵、目标、背景及明确的 OE 设定 | 目标实际施加值、对应基线、模拟响应与细胞间差异 |
| **虚拟药物筛选** | 候选药物在指定背景下产生怎样的转录响应，能否进行适用的比较？ | 药物清单或结构、细胞背景、模型要求的基线与剂量/时间；疾病方向比较另需疾病参照 | 逐药逐条件响应、变化基因、适用评分与排序、覆盖情况 |

结果含义随模型而定。CellOracle 输出调控网络模拟与状态投影；Geneformer 示例输出排序编码扰动后的 embedding 影响；药物响应模型按其基因空间、背景和剂量能力解释。选择路线时先确定需要什么结果，再核对输入与资源。[模型能力说明](virtual-cell-research/references/model-capabilities.md)

## 快速开始

### 1. 让 Agent 读取完整 Skill

获取本仓库源码后，保留完整的 `virtual-cell-research/` 目录，其中包含 `SKILL.md`、脚本、案例和参考说明。在能够读取本地文件并运行命令的 Agent 中，按宿主的 Skill 导入方式加载该目录，或直接复制下面的指令：

```text
请读取本仓库的 virtual-cell-research/SKILL.md，使用 Virtual Cell Research
带我完成 prnet-ht115-demo 观测教学。先检查已有环境，按案例获取所需数据，
计算处理与指定对照的响应，最后打开报告、完整源表和图，解释结果。
```

宿主的导入位置各不相同；本项目也提供可直接运行的 Python 入口。已有自己的数据和目标时，可以直接使用下一节的研究指令。

### 2. 手动跑通一个真实数据案例

该参考案例约需下载 **3.14 MB** 的 HT115 官方 demo，包含 **661 条处理表达谱、20 条对照、978 个基因**。它用于核对输入、指定对照和响应差值；此步骤计算真实观测数据，不加载 PRnet 权重。[案例来源与说明](virtual-cell-research/cases/prnet-ht115-demo/README.md)

以下两组命令选择适合自己系统的一组，从**仓库根目录**执行。需要 Python 3.12 和对案例所列数据来源的网络访问；已有独立数据环境可以复用。

**Linux / macOS**

```bash
cd virtual-cell-research
python3.12 -m venv .venv-data
source .venv-data/bin/activate
python -m pip install -r requirements-data.txt
python scripts/cases.py show prnet-ht115-demo
python scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
python scripts/observed_prnet_case.py --input local-runs/prnet-input/demo.h5ad --output-dir local-runs/prnet-observed
```

**Windows PowerShell**

```powershell
cd virtual-cell-research
py -3.12 -m venv .venv-data
.\.venv-data\Scripts\python.exe -m pip install -r requirements-data.txt
.\.venv-data\Scripts\python.exe scripts/cases.py show prnet-ht115-demo
.\.venv-data\Scripts\python.exe scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
.\.venv-data\Scripts\python.exe scripts/observed_prnet_case.py --input local-runs/prnet-input/demo.h5ad --output-dir local-runs/prnet-observed
```

完成后在当前 Skill 目录打开 `local-runs/prnet-observed/report.md`，再查看同一运行目录中的 `tables/condition_index.csv`、完整的 `tables/observed_responses.csv.gz` 和 `figures/observed_response.svg`。计算保留来源处理尺度与指定配对；其中 **338 条处理谱跨 RNA plate 配对**，报告会提示可能的批次影响。

重跑时换一个新的输出目录。`requirements-data.txt` 用于数据教学与准备，模型分析按路线建立独立环境；想直接体验模型，可从下方 CellOracle 或 PRnet 案例开始。更完整的上手步骤见 [首次使用](virtual-cell-research/references/first-run.md)。

## 用自己的数据开展研究

### 准备哪些信息

| 内容 | 需要明确什么 |
| --- | --- |
| 表达文件 | CSV、TSV 或 H5AD；表格行列方向，H5AD 使用 `X` 还是指定 layer |
| 数值与基因 | 原始计数、归一化或 log 处理的真实记录；物种、基因 ID 类型与唯一标识 |
| 样本背景 | 细胞类型、供体、批次、处理条件及可用对照；元数据按稳定 ID 对齐 |
| 干预设定 | 目标基因或药物清单，逐个/联合，OE 定义，以及所需剂量和时间 |
| 评价目标 | 需要原生响应、细胞状态变化，还是与实测比较；疾病方向评分需提供可比较的疾病参照 |

Agent 先读取你已经提供的文件和处理记录，只补问会改变科学解释的缺项。模型、解释器和普通运行参数可依据环境给出有理由的默认。数据准备工具保留原始数值和完整标识，生成新的 H5AD、数据说明和检查报告；具体参数见 [数据准备](virtual-cell-research/references/user-data.md)。

### 三类任务的可复制指令

**虚拟敲除**

```text
使用 Virtual Cell Research，对我提供的单细胞数据分别模拟 STAT3 和 JUN 敲除。
先检查表达尺度、基因覆盖和细胞背景，选择兼容模型；分别运行两个目标，
输出完整模型结果、变化基因、适用的细胞状态图和结果解释，并比较主要差异。
```

**虚拟过表达**

```text
使用 Virtual Cell Research，分析我提供的数据中 Gata1 过表达的模拟影响。
先解释适用模型如何定义过表达，结合我给出的设定核对输入；若设定缺失，
先指出需要明确的条件。运行后交付基线、实际目标设定、完整响应和状态变化图。
```

**虚拟药筛**

```text
使用 Virtual Cell Research，结合我提供的表达数据、药物库和疾病参照开展虚拟药筛。
按输入选择兼容模型，核对基因空间、实际基线、剂量与时间，输出逐药逐条件响应、
适用的疾病方向评分、变化基因图和结果解释；保留未覆盖或无法评分的条件及原因。
```

### 分析交付物

| 交付内容 | 用途 |
| --- | --- |
| 结构化报告 `report.md` | 研究问题、本次完成范围、主要数值、读图说明和下一步 |
| 完整矩阵与索引 | 基线、观测或预测、响应，以及对应的细胞/样本、基因、条件 ID |
| 汇总表和图 | 变化基因、状态位移、模型原生分数或适用的评价图；附展示选择规则 |
| 参数与运行记录 | 输入来源、模型与资源版本、实际命令、环境、随机种子及输出位置 |
| 质量检查与失败记录 | 覆盖、异常、未完成条件、基线比较和验证范围，便于继续处理 |

不同路线按实际结果生成文件。已有结果可交给 [结果解释工具](virtual-cell-research/references/result-reading.md)；已有实测与预测可按 [预测评估](virtual-cell-research/references/prediction-evaluation.md)对齐并比较。

## 一次分析怎样完成

1. **确定研究问题。** 明确目标、细胞背景、干预含义和需要的结果类型。
2. **检查并准备输入。** 核对尺度、基因/样本身份、目标覆盖和对照，生成可解释的模型输入。
3. **匹配模型并执行。** 准备该路线的环境、权重或先验，先检查小范围运行，再完成约定任务。
4. **保存完整结果并比较。** 保留基线、响应和索引，计算适用的摘要；评价预测时加入简单基线。
5. **画图、解读与交付。** 按完整结果生成图表，解释主要变化，记录参数和复现方法。

执行规则由 [SKILL.md](virtual-cell-research/SKILL.md)维护。输入定义、模型资源和失败后的下一步分别见 [输入契约](virtual-cell-research/references/input-contracts.md)、[模型配置](virtual-cell-research/references/model-setup.md)与 [排错指南](virtual-cell-research/docs/troubleshooting.md)。

## 模型能力与当前入口

| 路线 | 当前实现 | 适用条件与结果 |
| --- | --- | --- |
| **CellOracle** | 参数化 KO/OE，500 细胞 Gata1 KO 与 OE 已在 Linux CPU 实跑 | 原始单细胞计数、匹配 GRN 先验及可模拟 TF；输出内部表达差值和状态位移 |
| **PRnet** | 固定官方代码、权重与 HT115 demo 的 CPU 推理和基线比较 | 输出药物转录响应；自有矩阵需另行核对权重基因轴、预处理和背景适配 |
| **Geneformer** | 参数化 delete/overexpress、输入检查和表征导出入口 | 人类完整原始转录组与匹配 tokenizer/权重；输出 embedding 影响，真实模型执行待完成 |
| **chemCPA / UniPert-G2CP** | 已有药筛适配脚本与结果契约 | 按任务配置资源并验收；前者有特定细胞系协变量，后者使用模型自带背景且无剂量维度 |
| **GEARS / UniCure / DrugReflector** | 研究流程、资源说明和代码示例 | 需完成具体适配与运行验证；GEARS 还需匹配的扰动训练数据 |

路线的详细能力和资源要求见 [模型能力表](virtual-cell-research/references/model-capabilities.md)。已实跑的参考案例是选择起点，新数据仍按其物种、尺度、背景和目标重新检查。

## 四组真实案例：从方法到结果

以下 **5 张图**由仓库脚本读取公开数据与本次计算结果生成。四组案例分别展示基因网络模拟、药物观测、药物模型预测和供体留出评价；每组均有源表、实际命令与结果记录。[全部图集](virtual-cell-research/cases/gallery/README.md)

### 01 · CellOracle：Gata1 敲除与过表达怎样改变模型状态？

> 使用 Virtual Cell Research，从 GSE72857 野生型造血细胞原始计数出发，比较 Gata1 KO 和固定内部 P95 的 OE，生成状态位移、下游表达变化和实际目标设定图。

**方法。** 从 GEO 实验标签核实野生型小鼠骨髓背景，固定选择 500 个细胞；CellOracle 0.20.0 使用 1,500 个模型基因与全体细胞共同拟合的调控网络，分别执行 KO 和 OE。KO 将 Gata1 设为 0；OE 将其固定为基线内部表达的第 95 百分位 **1.556675**。

![CellOracle Gata1 KO、OE 与随机化响应在同一 UMAP 上的状态位移](virtual-cell-research/cases/gallery/celloracle/state_shifts.png)

**读状态图。** 散点显示全部 500 个基线细胞；A、C 是 KO/OE 投影，B、D 是固定网络下随机化表达变化的投影。四个面板使用同一坐标、同一组 240 个确定性选取的箭头和统一比例尺，便于直接比较方向。箭头幅度是 UMAP 投影单位，随机化结果提供描述性参照。

| 全部细胞的结果 | Gata1 KO | Gata1 OE |
| --- | ---: | ---: |
| 平均投影位移幅度 | 0.513265 | 0.620486 |
| 单次随机化平均位移幅度 | 0.311007 | 0.330776 |
| 有非零模拟响应的非目标基因 | 1,311 | 1,311 |

![CellOracle Gata1 KO/OE 的下游平均表达变化与所有细胞的实际目标设定](virtual-cell-research/cases/gallery/celloracle/intervention_effects.png)

**读表达图。** A、B 排除被强制设定的 Gata1，各展示正、负平均变化最大的 8 个基因；横轴使用 CellOracle 内部的 **imputed log1p(raw-count)** 尺度。KO 中 Elane 为 +0.580168、Car1 为 −0.925505；OE 中 Car1 为 +1.823699、Ctsg 为 −0.926096。C 将所有细胞按基线排序：固定 P95 使 **475 个细胞提高、25 个细胞降低**，因此这里的 OE 并不等于每个细胞都增加相同倍数。

**解释范围。** 这是单只小鼠、固定子集的网络模拟；多名基因映射排除损失了所选细胞约 13.23% 的分子计数，且没有独立 Gata1 扰动真值。状态箭头和基因变化用于提出后续问题。[完整方法、源表与复现命令](virtual-cell-research/cases/gallery/celloracle/README.md) · [运行记录](virtual-cell-research/cases/gallery/celloracle/evidence.json)

### 02 · Airway：同一供体中，单药与联合处理有什么不同？

> 使用 Virtual Cell Research，分析 GSE52778，核对样本与供体身份，比较地塞米松、沙丁胺醇和联合处理相对未处理对照的表达响应，生成图表和结果解释。

**方法。** 输入为人气道平滑肌的 bulk RNA-seq 来源 FPKM：**4 位供体、16 份表达谱、23,273 个来源基因**；每药 1 µM，处理 18 小时。通过 GEO/SRA 样本记录核实身份，为每位供体分别计算三个处理对比：`log2(1 + FPKM处理) − log2(1 + FPKM对照)`。

![GSE52778 四供体在地塞米松、沙丁胺醇和联合处理下的真实配对响应](virtual-cell-research/cases/airway-gse52778-drug-response/drug_response.png)

**读图。** 每列是一位供体，格内数值是该供体的配对差值。三个面板共享色标和八个基因；候选要求来源状态均为 OK 且所有表达谱 FPKM ≥ 1，再按地塞米松供体平均响应选取四个正向、四个负向基因。下表给出其中四个基因的供体等权平均值：

| 基因 | 地塞米松 | 沙丁胺醇 | 联合处理 |
| --- | ---: | ---: | ---: |
| SPARCL1 | +3.884 | +1.966 | +2.887 |
| FKBP5 | +3.701 | +1.591 | +2.631 |
| KCTD12 | −2.357 | −0.865 | −1.161 |
| TNFAIP6 | −2.292 | −0.881 | −1.006 |

**解释范围。** 本例完成的是实测表达的描述性分析，统计单位为四位供体；伪计数后的差值需按上述尺度阅读，联合处理的图形差异不能直接判为协同或拮抗。[全部结果、配对与复现命令](virtual-cell-research/cases/airway-gse52778-drug-response/README.md) · [运行记录](virtual-cell-research/cases/airway-gse52778-drug-response/evidence.json)

### 03 · PRnet：模型预测是否优于零响应基线？

> 使用 Virtual Cell Research，获取固定 PRnet 官方 HT115 demo 与权重，运行药物响应预测，画出实测和预测热图，并在全部处理表达谱上与零响应基线比较。

**方法。** 固定官方权重在 CPU 上推理 **661 条处理谱 × 978 个基因**，保留来源指定对照。沿官方 demo 执行总量归一化与 `log1p`，在该尺度计算处理表达减对照；主预测对 16 个 decoder-noise 向量下的条件均值取平均，本次没有重新训练权重。

![PRnet HT115 实测与预测响应、全部 661 条处理谱的配对误差和误差分布](virtual-cell-research/cases/gallery/prnet/predicted_response.png)

**读图。** A、B 使用共同色标，展示 10 个按固定规则选择的处理条件和 12 个按实测响应幅度选择的基因。C 的每一点是一条处理谱，虚线下方表示 PRnet 误差较低；D 展示全部处理谱的误差分布。评价使用完整 978 基因，RMSE 越低越好。

| 全部处理谱的结果 | 数值 |
| --- | ---: |
| PRnet 平均逐谱响应 RMSE | 0.140141 |
| 零响应平均逐谱响应 RMSE | 0.132420 |
| PRnet − 零响应的平均 RMSE 差值 | +0.007721 |
| PRnet 误差更低的处理谱 | 185 / 661（27.99%） |

**解释范围。** 本次模型成功执行，但平均误差未优于零响应。checkpoint 训练重叠未知，全部 demo 参与归一化，且 338 条谱的指定对照跨 RNA plate；因此这是一项固定参考推理，结果不外推为疾病逆转或疗效排名。[方法、源表与复现命令](virtual-cell-research/cases/gallery/prnet/README.md) · [运行记录](virtual-cell-research/cases/gallery/prnet/evidence.json)

### 04 · Kang：其他供体的平均响应能预测留出的供体吗？

> 使用 Virtual Cell Research，下载 Kang IFN-β PBMC 数据，按供体配对分析 CD14+ 单核细胞；每次用另外七位供体的响应均值预测第八位，生成响应热图和逐供体误差。

**方法。** GSE96583 的八位供体各有对照与 IFN-β 刺激条件，刺激 6 小时。将 **2,785 个对照细胞、2,600 个刺激细胞**的原始 UMI 按供体/条件聚合，使用全部 **35,635 个来源基因**计算 CPM，再求 `log2(1 + CPM刺激) − log2(1 + CPM对照)`。每一折只用其余七位供体的完整响应均值预测留出者。

![Kang 八位供体的配对响应，以及留一供体均值基线与零响应的全基因误差](virtual-cell-research/cases/gallery/kang/donor_response_and_holdout.png)

**读图。** 左侧每列是一位供体，展示供体平均变化最大的六个正向和六个负向基因；右侧连线比较同一位留出供体的两种全基因误差。八位供体的均值预测误差都较低，供体等权平均 RMSE 为 **0.620647**，零响应为 **0.837714**。

**解释范围。** 这是同一研究内的均值基线交叉验证；八折共享训练供体，条件特异文库影响仍在。完整基因轴包含 20,815 个共同零响应基因，汇总误差不能代表每个响应基因都预测准确。[完整方法、逐供体结果与复现命令](virtual-cell-research/cases/gallery/kang/README.md) · [运行记录](virtual-cell-research/cases/gallery/kang/evidence.json)

## 案例库：当前完成到哪一步

当前收录 **11 个工作流：5 项数据教学/输入检查/基线评估，2 条真实模型路线，4 项来源与路线整理；独立预测验证为 0 项。** 同一数据可承担多个工作流：HT115 用于观测教学与 PRnet 推理，Kang 用于观测配对与供体留出，Paul2015 分别提供教程对象检查与原始计数模拟。四组图集按研究问题组织。[案例目录与阶段记录](virtual-cell-research/cases/README.md)

| 工作流 | 当前阶段与可获得内容 |
| --- | --- |
| [HT115 观测教学](virtual-cell-research/cases/prnet-ht115-demo/README.md) | 已计算完整观测响应，学习指定对照与处理尺度 |
| [Airway 药物观测](virtual-cell-research/cases/airway-gse52778-drug-response/README.md) | 已完成 4 供体 × 3 处理的配对比较与绘图 |
| [Paul2015 输入检查](virtual-cell-research/cases/celloracle-paul2015-input-audit/README.md) | 已发现教程 `raw_count` 层非整数，按本入口原始计数要求阻断 |
| [Kang 供体配对](virtual-cell-research/cases/kang-ifnb-pbmc/README.md) | 已完成计数聚合与八个 CD14+ 供体配对 |
| [Kang 留一供体评估](virtual-cell-research/cases/kang-heldout-baseline/README.md) | 已完成八折均值基线与零响应比较 |
| [CellOracle Gata1 KO/OE](virtual-cell-research/cases/celloracle-paul2015-gata1/README.md) | 已分别执行 KO 和 OE，保存完整模型输出 |
| [PRnet 参考推理](virtual-cell-research/cases/prnet-reference-evaluation/README.md) | 已执行固定权重 CPU 推理与全量基线比较 |
| [sci-Plex3 剂量响应](virtual-cell-research/cases/sciplex3-chemical-dose/README.md) | 已整理来源、细胞系、药物和剂量条件；矩阵待获取 |
| [Norman2019 CRISPRa](virtual-cell-research/cases/norman2019-k562-crispra/README.md) | 已整理单基因/组合激活路线；数据准备待完成 |
| [Adamson2016 UPR CRISPRi](virtual-cell-research/cases/adamson2016-k562-upr-crispri/README.md) | 已整理 UPR 子实验；标签重建与模型评估待完成 |
| [Replogle2022 K562 CRISPRi](virtual-cell-research/cases/replogle2022-k562-essential-crispri/README.md) | 已整理作者存档与 pseudobulk 路线；矩阵待获取 |

在 Skill 目录执行 `python scripts/cases.py list` 查看全部工作流，`python scripts/cases.py show <case-id>` 查看一个案例；两者离线运行。资源按指定案例逐项获取，阶段以 [catalog.json](virtual-cell-research/cases/catalog.json)和对应运行记录为准。

## 结果质量与复现

**先看基线与尺度，再看变化大小。** 读报告时确认实际背景、干预、单位和完成范围；图中的 Top 基因用于展示，完整结果支持重新汇总。评价预测时同时看误差与简单基线，相关性、执行成功和独立验证各有不同含义。

**每张图都能回到源表。** 本项目保留稳定 ID、完整响应、展示筛选规则和绘图入口；并列图尽量共用坐标或色标。四组案例的数值与图形核对范围见 [复核记录](virtual-cell-research/cases/gallery/review-notes.md)。

**每次运行都能找到方法。** 输入来源、资源身份、软件版本、参数、命令和失败条件随结果保存；重新执行使用新目录。源码包含流程、脚本、案例和轻量图源，原始矩阵、模型权重与完整本地运行包按案例单独准备。需要继续判断预测价值时，使用匹配的实测数据设计留出与基线比较。

## 开放协作与生态共建

本项目希望将分散的扰动模型、公开数据与分析经验，逐步沉淀为可运行、可比较、可复核的研究工作流。开放协作围绕具体科学问题展开：明确方法的适用范围，完善数据与评价依据，使模型接入能够进一步支持研究复用与独立验证。

| 共建方向 | 可贡献内容 | 协作目标 |
| --- | --- | --- |
| **模型与方法** | 模型适配、扰动语义、输入输出定义、适用背景与真实运行案例 | 使方法在各自科学定义下可复现执行，明确能力边界与失败条件 |
| **数据与基准** | 有来源与许可记录的扰动数据、稳定标识、条件与对照映射、参考任务与数据划分 | 为方法比较和跨数据集研究提供可追溯、可核对的数据基础 |
| **评测与验证** | 同尺度基线、留出设计、评价指标、独立数据或实验对照 | 评估预测相对简单基线的增益及适用范围，逐步补充独立验证证据 |
| **可复现工作流** | 数据准备、模型执行、结果汇总、结构化报告、结果解释与使用指南 | 保留资源、参数、完整产物和失败记录，支持研究者复用方法并复核结论 |

上述方向是后续协作目标。当前已完成 CellOracle 与 PRnet 两条真实模型执行路线，其他路线按各自适配进度记录；独立预测验证仍待完成。贡献可从现有案例或明确的新研究问题出发，随实际证据推进实现与验证阶段。模型、数据和论文保留原始归属，复用条件按具体资源记录。

### 贡献规范与工程验证

请按 [贡献指南](virtual-cell-research/CONTRIBUTING.md) 说明研究目的、输入与输出、来源与版本、最小运行步骤、完整结果位置及实际验证范围。使用指南和结果解释与代码、案例一起维护，使其他研究者能够从同一份记录重建分析过程。

在独立 Python 3.12 环境、Skill 根目录进行工程检查与打包：

```bash
python -m pip install -r requirements-tests.txt
python -m unittest discover -s tests -v
python scripts/cases.py validate
python scripts/package_skill.py
```

打包产物为 Skill 目录下的 `dist/virtual-cell-research.zip`。工程检查验证代码和记录的一致性，真实模型执行与独立科学评价按各自案例补充。

## 仓库结构与阅读导航

| 位置 | 作用 |
| --- | --- |
| [virtual-cell-research/README.md](virtual-cell-research/README.md) | Skill 使用说明与任务入口 |
| [virtual-cell-research/SKILL.md](virtual-cell-research/SKILL.md) | Agent 执行规则 |
| [virtual-cell-research/references/](virtual-cell-research/references/) | 首次使用、输入准备、能力表、资源配置、结果解读与评价 |
| [virtual-cell-research/scripts/](virtual-cell-research/scripts/) | 数据准备、案例获取、观测分析、绘图、评价与打包工具 |
| [virtual-cell-research/examples/](virtual-cell-research/examples/) | KO/OE 参数化入口与药筛适配示例 |
| [virtual-cell-research/cases/](virtual-cell-research/cases/) | 11 个工作流的来源、命令、实际阶段与结果 |
| [virtual-cell-research/cases/gallery/](virtual-cell-research/cases/gallery/) | 实际结果图、图源与读图说明 |
| [virtual-cell-research/tests/](virtual-cell-research/tests/) | 输入、适配、计算与输出的工程检查 |
| [docs/desktop-viewer.md](docs/desktop-viewer.md) | 附带的 Windows 结果查看器说明：用于打开已有模型运行包 |

Skill 的使用与模型运行按本页的目录和环境准备；附带查看器的安装包提供结果阅读功能，不包含新 Skill 的模型环境与权重。

## 使用许可与商业授权

**个人非商业使用免费，超出免费许可范围的商业使用须取得书面授权。** 新贡献采用 [PolyForm Noncommercial 1.0.0](LICENSE)，支持源码阅读、许可范围内的修改与分享；教育、公共研究及协议列明的其他机构按协议条款免费使用，不因资金来源而缩小该许可。

| 内容 | 适用许可 |
| --- | --- |
| 本次起有权授权的项目新贡献与品牌资产 | PolyForm Noncommercial 1.0.0；超出其许可范围的用途另行商议商业授权 |
| 既有 MIT 版本及带入新版的相同旧内容 | 原 MIT 权利继续有效，包括商业使用权；新条款不溯及既往 |
| 第三方代码、模型、权重、数据与历史材料 | 分别按原许可和资源条款处理，项目商业授权不替代这些权利 |

当前分析代码的大部分已经载有 MIT 许可，不能仅更换 LICENSE 就将这些旧内容改成必须商业授权。原许可、固定版本文件清单、贡献者权利及申请途径在 [完整许可说明](virtual-cell-research/docs/licensing.md) 中明确登记。该政策属于**源码开放的非商业许可**，不宣称为 OSI 批准的开源许可。

[代码许可](LICENSE) · [归属说明](virtual-cell-research/NOTICE) · [第三方资源与来源](virtual-cell-research/THIRD_PARTY_NOTICES.md) · [方法说明](virtual-cell-research/docs/methodology-and-scope.md)
