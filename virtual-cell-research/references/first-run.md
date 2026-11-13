# 第一次使用 Virtual Cell Research

先选择与你当前目标相符的入口：已有数据和干预目标就直接准备输入并运行兼容模型；希望先了解虚拟细胞时，可从小型真实案例开始。你不必先学会挑模型和解释器；Agent 读取已提供的信息与可用环境，只询问会改变研究问题的缺项。

**已有自己的数据**先读 [数据准备](user-data.md)，**已有运行结果**先读 [中文解读](result-reading.md)，**已有实测与预测**先读 [预测评估](prediction-evaluation.md)。下面的 HT115 教学是可选入门，不是所有任务的必经步骤。

## 目录

1. [让 Agent 读取完整 Skill](#让-agent-读取完整-skill)
2. [建立数据教学环境](#建立数据教学环境)
3. [完成 HT115 观测教学](#完成-ht115-观测教学)
4. [理解其他案例的实际阶段](#理解其他案例的实际阶段)
5. [准备最少的科学输入](#准备最少的科学输入)
6. [运行 CellOracle 参数化入口](#运行-celloracle-参数化入口)
7. [运行 Geneformer 参数化入口](#运行-geneformer-参数化入口)
8. [开始药筛前先确认什么](#开始药筛前先确认什么)
9. [运行后按什么顺序看](#运行后按什么顺序看)
10. [遇到失败怎么继续](#遇到失败怎么继续)
11. [可直接使用的提示词](#可直接使用的提示词)

## 让 Agent 读取完整 Skill

源码中的 Skill 根目录和分发包解压后的根目录均为 `virtual-cell-research/`。保留 `SKILL.md`、`references/`、`scripts/`、`cases/`、`examples/`、文档与许可文件；仅复制一段提示词会缺少真实执行入口和来源记录。

在能访问这些文件并运行命令的科研 Agent 环境中，按宿主的 Skill 导入方式加载完整目录，或明确告诉 Agent：

> 请读取「这个 Skill 的绝对路径/SKILL.md」，使用 Virtual Cell Research 带我完成 prnet-ht115-demo 观测教学。先读取案例声明和本机环境，明确每一步是下载、数据计算还是模型推理，并带我查看完整结果。

具体导入位置由宿主决定，本项目没有适用于所有 Agent 的统一安装命令。也可以不使用 Agent，直接执行下面的命令。

**下文命令均在包含 `SKILL.md` 的目录运行。** 若从工作台仓库获取源码，先进入 `virtual-cell-research/` 子目录；不要在外层仓库根目录直接运行 `scripts/...`。

## 建立数据教学环境

读取案例目录的 `list`、`show`、`validate` 与单资源 `fetch` 只使用 Python 标准库。HT115 观测计算和 H5AD 检查使用 [requirements-data.txt](../requirements-data.txt) 中的数据处理依赖；这些依赖不安装 PRnet、CellOracle 等模型，也不包含权重。

已有可用的独立 Python 3.12 数据环境时直接复用。手动创建可用下面的方式，选择自己系统对应的一种。

### Windows PowerShell

```powershell
py -3.12 -m venv .venv-data
.\.venv-data\Scripts\python.exe -m pip install -r requirements-data.txt
```

后续命令中的 `python` 使用 `.\.venv-data\Scripts\python.exe` 代替。无需为了本教程改变 PowerShell 脚本执行策略。

### Linux 或 macOS

```bash
python3.12 -m venv .venv-data
source .venv-data/bin/activate
python -m pip install -r requirements-data.txt
```

如果没有 Python 3.12，先准备该解释器；不要把模型旧依赖直接装进已有主环境。真实模型分析使用自己的兼容环境，不能把这个数据环境视为模型环境认证。

## 完成 HT115 观测教学

### 1. 看清来源和要下载的内容

```bash
python scripts/cases.py list
python scripts/cases.py show prnet-ht115-demo
```

这两条命令只读本地 [catalog.json](../cases/catalog.json)。该案例使用 PRnet 作者提供的约 3.14 MB `demo.h5ad`，包含 HT115 的 681 条表达谱：661 条处理、20 条 vehicle 对照，978 个基因。处理与对照通过来源 `paired_control_index` 对应。

它是已处理的 L1000 来源表达数据，一条 profile 是一条表达谱，不是一个单细胞。数据、软件和案例说明的许可分别记录；不要用本 Skill 的许可替代数据提供方的条款。

### 2. 明确获取一个资源

```bash
python scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
```

下载器只获取 `demo`，自动创建缺失父目录，但拒绝已经存在的最终目录。默认最大 64 MiB；不会解压或启动模型。来源固定、已知大小和 SHA256 会被核对，下载记录保存在 `local-runs/prnet-input/fetch_record.json`。

对于没有预期哈希的其他资源，记录本次计算的 SHA256，`expected_sha256_verified` 为 `null`；这不等于来源完整性已经获认证。案例只是收录了地址时，`show` 不会顺便下载。

### 3. 计算真实观测差值

```bash
python scripts/observed_prnet_case.py --input local-runs/prnet-input/demo.h5ad --output-dir local-runs/prnet-observed
```

Windows 用户可直接复制对应命令：

```powershell
.\.venv-data\Scripts\python.exe scripts/cases.py list
.\.venv-data\Scripts\python.exe scripts/cases.py show prnet-ht115-demo
.\.venv-data\Scripts\python.exe scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
.\.venv-data\Scripts\python.exe scripts/observed_prnet_case.py --input local-runs/prnet-input/demo.h5ad --output-dir local-runs/prnet-observed
```

脚本接受固定 SHA256 的官方 demo，在来源文件的处理后尺度计算 **处理 X − 来源指定对照 X**，不重新归一化、不重分配对照、不加载 PRnet 权重。它不是任意用户 H5AD 的通用分析入口；自己的数据先走输入与路线检查。

**338 条处理谱的指定对照跨 RNA plate。** 查看 `tables/condition_index.csv` 中的 `paired_rna_plate` 和 `cross_rna_plate`；脚本保留这项来源事实，差值可能混入批次影响。指定对照也不表示同一个细胞干预前后的追踪测量。

### 4. 看完整产物，不只看热图

先打开 `local-runs/prnet-observed/report.md`，再依次核对：

| 文件 | 回答的问题 |
| --- | --- |
| `provenance.json`、`qc.json` | 来源和输入哈希是否匹配，实际检查了什么，有哪些配对或命名警告？ |
| `tables/condition_index.csv` | 每条处理谱用了哪个对照，条件 ID 如何区分药物、剂量、时间、细胞背景和 plate？ |
| `tables/observed_responses.csv.gz`、`raw/observed_responses.npz` | 完整 661 × 978 观测差值是否保留，能否对应原始行列 ID？ |
| `tables/condition_mean_responses.csv.gz`、`tables/top_observed_genes.csv` | 条件内平均变化与绝对变化较大的基因是什么？ |
| `tables/figure_data.csv`、`figure_manifest.json`、`figures/observed_response.svg` | 图选择了哪些条件/基因，是否成功生成，如何回到源表？ |

热图按稳定条件 ID 选择小部分条件，再选其中变化较大的基因；它不是药效排名。Top 基因没有 P 值，不称为统计显著差异基因。profile 数也不能直接当作独立生物学重复数。

本教学的完成依据是本次来源记录、完整观测表与检查结果；`model_status` 始终为 `not_run`，`independent_validation` 为 `not_assessed`。来源里的 `demo_split=test` 本身不能证明相对某个模型的独立验证。重新执行时新建输出目录，例如 `prnet-observed-002`。

## 理解其他案例的实际阶段

[案例目录](../cases/README.md) 收录十一项具体问题。[公开案例结果](../cases/gallery/README.md) 提供本次实际生成的图、读图说明和重跑入口。先用 `show <case-id>` 看限制，不必一次下载全部数据。

- **Paul2015 输入尺度审计已经实做。** 约 66.3 MB 的教程对象，其 `raw_count` 层含非整数值；按当前原始整数计数契约，预检应返回 `blocked`、退出码 `2`。这是检查找到了问题，不是模型计算失败。按 [案例步骤](../cases/celloracle-paul2015-input-audit/README.md) 阅读或复现，不要靠四舍五入伪装原始计数。
- **Kang IFN-β PBMC 已完成真实供体配对教学。** 六份来源文件合计约 58.7 MB；按 [案例步骤](../cases/kang-ifnb-pbmc/README.md) 获取并运行，学习样本与 barcode 对齐、原始计数聚合、缺失配对和供体内差值。默认 CD14+ 分析有 8 个供体配对，未执行预测模型。
- **Airway GSE52778 已完成真实药物观测分析。** [药物响应案例](../cases/airway-gse52778-drug-response/README.md) 用 GEO 与 SRA 核实 16 个样本的身份，对 4 位供体分别比较地塞米松、沙丁胺醇及联合处理与未处理对照。输入是作者处理后的 bulk RNA-seq FPKM；它帮助学习配对与读图，不是单细胞原始计数或模型预测。
- **Kang 留一供体基线评估已完成。** [真实评估教学](../cases/kang-heldout-baseline/README.md) 每次只用另外 7 位供体构建均值参照，预测被留出的 1 位，再与零响应比较；保存全部成员和 8 折结果。它帮助理解数据划分与评价，不是 CellOracle/PRnet 的独立验证。
- **CellOracle Gata1 KO 和 OE 已完成真实模型执行。** [完整案例](../cases/celloracle-paul2015-gata1/README.md) 从 GSE72857 原始整数 UMI 和 GEO 实验标签核实野生型背景，固定选择 500 个细胞，实际拟合网络并分别模拟 KO 和内部 95 分位固定值的 OE，记录实际被提高与降低的细胞数量。数据准备与模型环境分开，Linux CPU 路线已实测；这不等于独立生物学验证或 Windows 安装验收。
- **PRnet 已完成固定权重的 CPU 参考推理。** [参考评估案例](../cases/prnet-reference-evaluation/README.md) 明确获取一组固定官方代码、权重与 demo，保留稳定 profile ID、随机种子和同尺度结果，并与零响应基线比较。本次正相关没有转化成更低的平均误差；训练重叠未知，不能标为独立验证，也不能将此固定 demo 入口直接用于任意用户矩阵。
- **sci-Plex3、Norman2019、Adamson2016 和 Replogle2022 目前是已收录路线。** 数据尚未下载。Replogle 案例列出的是约 79.8 MB pseudobulk，不是原始单细胞矩阵；更大的资源需要明确提高下载限额。

目录阶段 `catalogued`、`data_downloaded`、`prepared`、`model_executed`、`validated` 含义不同。当前有五项数据教学/审计/基线评估、两条真实模型路线（CellOracle 已分别运行 KO 与 OE），独立验证仍未完成。一个教学脚本完成、输入审计正确阻断、真正执行模型，分别说明，不合并为“已复现论文结论”。

对自己的 H5AD，预检默认只读元数据与形状。在请求 JSON 中显式加入 `"scan_h5ad_values": true` 后，可按块扫描所选 dense/CSR/CSC 的全部存储值。数值合格仍不能证明原始计数来源、稀疏索引完整性、`n_counts` 与矩阵一致或模型环境兼容；通常仍有 `incomplete` 项。具体请求字段见 [预检与排错](../docs/troubleshooting.md)。

## 准备最少的科学输入

| 任务 | 需要告诉 Agent 或能从文件核实的内容 |
| --- | --- |
| 基因 KO | 表达文件、目标基因、未干预背景；多个基因是逐个还是联合 |
| 基因 OE | 上述内容；CellOracle 另需目标固定值或分位数及设定依据 |
| 药物响应 | 药物库/候选清单、细胞背景、模型需要的基线与剂量/时间 |
| 疾病方向比较 | 另需疾病参照/差异方向及可比较的基因、平台和实验条件 |

数据层、基因 ID、物种、样本/供体/细胞类型字段和处理记录由 Agent 先检查。只在这些信息无法核实时合并询问缺项。单独计算干预响应不强制准备疾病参照。

模型、可用解释器和保存目录可以由 Agent 给出有依据、可更改的默认。用户已指定的模型、输入、基线和目标会保留；遇到不适配先说明原因，不静默换路线。

## 运行 CellOracle 参数化入口

### 使用前提

这条路线用于单细胞调控网络模拟。需要：

- `.h5ad` 中的原始非负整数计数，放在 `.X` 或明确的 counts layer。
- 与物种、基因组版本和 gene symbol 匹配的 CellOracle base GRN `.parquet`。
- 目标在表达数据、先验 TF 范围和实际拟合网络中可用。
- 已核实兼容的 CellOracle 独立 Python 环境。

这不是对任意基因、任意矩阵都适用的模型。资源准备见 [CellOracle 设置](model-setup.md#celloracle)，所有实际参数见 [KO/OE 示例说明](../examples/ko_oe/README.md#celloracle)。

### 命令

从上面的 Skill 根目录可先查看参数，不会启动模型计算：

```bash
python examples/ko_oe/celloracle_run.py --help
```

下面是 **PowerShell 示例**。解释器、文件、目标与输出路径必须替换成当前任务已核实的内容；`STAT3` 仅为示例，不替代用户目标。结果目录必须不存在或为空。

```powershell
& 'D:\envs\celloracle\Scripts\python.exe' .\examples\ko_oe\celloracle_run.py --h5ad 'D:\data\cells.h5ad' --base-grn 'D:\models\base_grn.parquet' --target-gene STAT3 --mode ko --output-dir 'D:\analysis\results\stat3-ko-001'
```

如果原始计数确实在 `adata.layers['counts']`，追加 `--counts-layer counts`。不能因为层名叫 counts 就跳过其来源和尺度检查。

只有已经确定采用内部表达 95 分位作为 OE 设定时，才使用下面的 OE 示例；也可换成有依据的 `--oe-value`：

```powershell
& 'D:\envs\celloracle\Scripts\python.exe' .\examples\ko_oe\celloracle_run.py --h5ad 'D:\data\cells.h5ad' --base-grn 'D:\models\base_grn.parquet' --target-gene STAT3 --mode oe --oe-percentile 95 --output-dir 'D:\analysis\results\stat3-oe-001'
```

95 分位不是通用默认。CellOracle 设置的是 log1p(raw-count) 经 KNN 平滑后的内部表达值，不是“实验过表达 95 倍”。固定值会使原本高于该值的细胞下调，报告必须单列这种情况。

`--group-col` 只控制分组描述；`--grn-unit-col` 指定分别拟合 GRN 的细胞分组。没有后者时拟合全体输入细胞共用的 GRN，不能据此声称得到每类细胞的特异网络。当前入口一次执行一个目标/模式；多个目标需分别调用并使用不同输出目录，不能把逐个扰动当作联合扰动。

### 先核对这些输出

- `raw/baseline_imputed_expression.csv.gz`、`raw/simulated_expression.csv.gz`、`raw/delta_X.csv.gz`：完整基线、模拟表达与差值。
- `tables/gene_effects.csv`：有方向的表达效应及绝对变化统计。
- `tables/cell_state_shift.csv.gz`、`tables/simulation_grn_index.csv`：状态位移及实际模拟网络索引。
- OE 的 `tables/target_expression_setting.csv`：目标设定与实际基线。
- `figures/figure_manifest.csv`：哪些图已生成、跳过或失败，以及源表。

## 运行 Geneformer 参数化入口

### 使用前提

当前示例要求人类完整转录组原始 scRNA 计数：`.X` 尚未做 HVG 选择、归一化或 log 转换；`.var['ensembl_id']` 为无版本号的 ENSG ID，`.obs['n_counts']` 为每细胞完整原始计数总量。tokenizer、词典和 checkpoint 必须匹配 V1/V2；还需满足该示例的独立环境和 CUDA 要求。

`--confirm-raw-full-transcriptome` 是对数据来源的明确声明。只有已从处理记录或用户信息核实原始完整转录组时才设置，不能为了通过检查直接添加。数值看起来像整数，不能证明没有做过基因筛选。

### 命令

```bash
python examples/ko_oe/geneformer_route.py --help
```

在上述前提已经核实后，PowerShell 的单条件 KO 示例为：

```powershell
& 'D:\envs\geneformer\Scripts\python.exe' .\examples\ko_oe\geneformer_route.py --input-h5ad 'D:\data\human_raw_counts.h5ad' --model-dir 'D:\models\Geneformer-V2' --model-version V2 --target-ensembl ENSG00000168610 --perturbation KO --confirm-raw-full-transcriptome --output-dir 'D:\analysis\results\geneformer-ko-001'
```

目标 ID 必须来自本次数据和目标的已核实映射。`--perturbation OE` 运行过表达编码扰动，`both` 分别运行 KO 与 OE；它们不是两个基因的联合扰动。按细胞类型限制分析时，成对提供 `--cell-type-column` 与 `--cell-type`。`--max-ncells` 可用于已明确的小规模试运行，必须记录子集，不能把其结果冒充全部细胞。

本路线的 KO 是删除目标 token，OE 是将目标 token 移到排序编码前端，交付的是 **embedding 影响**。它不会自动产生基因表达倍数、差异表达、药物浓度或实验疗效。当前官方操作路径仅执行 `delete`/`overexpress`，不使用 `inhibit`/`activate`。

### 先核对这些输出

`tokenized/` 保存编码数据；`raw/KO|OE/` 保存官方原始输出；`tables/KO|OE/` 保存官方统计和余弦影响表；根目录保存清单、溯源、验证、错误与报告。`KO|OE` 表示实际执行的条件子目录，不是一个字面目录名。

V1 的 cell 汇总与 V2 的 CLS 表征指标分开展示。现有 `observation_index` 是结果行索引，未提供原始细胞 ID 的完整映射，不应自行断言某行对应某个细胞。只有经核实来自本次运行的可信原始 pickle 才用于相应后续处理，不加载来源不明的 pickle。

## 开始药筛前先确认什么

HT115 教学只读真实观测数据；完成教学不表示 PRnet 已安装或权重已经通过验收。

想先运行真实药物响应模型，可直接使用 [PRnet 固定参考案例](../cases/prnet-reference-evaluation/README.md)。对自己的矩阵与药物库，先读 [药筛适配步骤](model-setup.md#复用药筛示例的配置步骤)，核对源码、环境、checkpoint、基因轴、预处理、协变量与条件索引；参考入口不自动接收任意 `.h5ad`。

- PRnet 和 chemCPA 的接口可接受外部基线，但要对齐具体权重的基因轴与预处理；接口能接收矩阵不代表跨背景预测已获验证。
- UniPert-G2CP 当前调用使用模型自带的细胞系对照，无剂量维度；必须明确实际背景，不能将其结果标成用户样本预测。
- GEARS、UniCure、DrugReflector 的文档路线仍需要相应数据/资源和适配验证，不作为当前已完成的一键功能。
- 先在已明确的小范围条件检查输出完整性、响应差异和评分区分度，再按授权任务扩展；必须保存完整响应、基线、基因与条件索引。

缺少可比较疾病参照时可以交付模型原生响应，不编造恢复分数。排名并列或不可区分时停止推荐候选，保留真实预测和诊断。

## 运行后按什么顺序看

HT115 观测教学使用上面的 `qc.json` 与 `provenance.json` 阅读顺序。真正运行模型后，再核对对应路线实际生成的运行包：

| 顺序 | 文件 | 先看什么 |
| --- | --- | --- |
| 1 | `report.md` | 做了什么，是观测计算、本次模型运行还是历史读取，哪些条件完成？ |
| 2 | `manifest.json`、`provenance.json` | 是否使用指定的数据、基线、目标、模型及版本？ |
| 3 | `validation.json`、`errors.jsonl` | 执行、响应差异、条件/药物排名与独立验证分别怎样？ |
| 4 | 主要图、`tables/` 和图形清单 | 单位、条件和来源是否一致，能否按稳定 ID 回到源表？ |
| 5 | `raw/` 和完整索引 | 能否从完整结果重算统计或重画图？ |

教学与模型路线的产物名称不同，不补造脚本没有生成的模型记录。`result_available` 表示有有效计算输出，不等于经过独立实验验证；`unvalidated` 不抹掉已完成预测，`partial` 需查看具体成功与失败条件。目录中的 `validation_status: not_assessed` 也不能被解读为已验证。

CellOracle 模拟表达、Geneformer embedding 变化、药物转录方向评分和真实观测差值各有自己的含义，不能合并成同一种“准确率”或疗效。

## 遇到失败怎么继续

| 提示或现象 | 下一步 |
| --- | --- |
| 下载超过 64 MiB | 先核对 `show` 的资源大小和用途；确定要该资源后显式设置合适的 `--max-mib`，换新目录重试 |
| 下载错误、SHA256 或大小不符 | 阅读 `fetch_record.json`；核对来源和下载内容，不删去预期哈希来绕过校验 |
| HT115 教学输入 SHA256 不符 | 此脚本只接受固定官方 demo；核对获取的资源，不把自己的矩阵冒充 demo |
| 下载/分析目录已存在 | 保留旧目录，选择新名字；不要为重跑清空原结果 |
| H5AD 依赖无法导入 | 在数据环境安装 `requirements-data.txt`，不能由 `incomplete` 推断矩阵本身有问题 |
| `raw_count` 层含非整数，或原始完整转录组不符 | 查处理记录和真实原始数据；不靠逆 log、补零、取整或确认标志蒙混通过 |
| 目标不在 GRN/tokenizer/覆盖范围 | 说明具体缺失环节，保留 `no_prediction`，不自动换目标 |
| 缺模型模块、权重、先验或 CUDA 不兼容 | 修复选定路线的隔离环境与资源；`--help` 成功不代表推理依赖齐全 |
| 某个条件失败 | 保存该条件错误，保留其他条件的产物，只重试失败部分 |
| 表格完成但图失败 | 看图形清单和源表，补齐绘图条件后重画；无需重做已完成数值计算 |
| 药物响应几乎相同或评分并列 | 检查基线、权重、剂量和评分口径，不把微小差异放大成候选推荐 |
| 缺疾病评分或独立验证 | 阅读未检查/跳过原因，保留原生结果，按研究问题补对应数据 |

具体记录与恢复规则见 [执行手册](execution-playbook.md)。

## 可直接使用的提示词

### 从真实观测数据入门

> 请使用 Virtual Cell Research 带我完成 prnet-ht115-demo。先看来源、资源大小和当前环境，只下载 demo 资源，生成完整观测差值与报告。解释指定对照、338 条跨 RNA plate 配对及图的选择方式，明确没有运行 PRnet 模型或完成独立验证。

### 学会识别输入尺度问题

> 请使用 Virtual Cell Research 阅读或复现 celloracle-paul2015-input-audit。核对固定来源文件及 raw_count 层的数值，说明为什么预期结果是 blocked。不要为了让检查通过而改尺度声明、取整数据或替换我的目标。

### 分析自己的数据

> 这是我的原始单细胞 h5ad 和处理说明。我想分别模拟 STAT3、JUN 的敲除，关心表达变化和不同细胞群的状态差异。请先读取数据和现有环境，推荐适配路线；只把无法核实的必要信息一次问清，保持指定基线，记录完整输出与独立验证状态。

### 做药物响应，疾病评分按条件决定

> 请检查我提供的表达数据和药物库能否做药物转录响应预测。我目前没有疾病参照，先保留模型原生响应；说明实际基线、环境和权重是否可用。响应或排名无法区分时报告诊断原因，不推荐候选。

## 需要历史材料时

[历史肺癌报告](../archive/aivc-587579e7/reproduction-report.md) 和 [勘误](../docs/audit-remediation.md) 用于复核旧研究，不是本版入门案例的执行证据。历史 CellOracle 向量差长度不能解释为特异信号；历史 UniPert Top 20 对应曾有错误，三个药筛分支缺少完整历史响应，不能从旧图恢复全量结果。读取这些材料时注明来源、已有产物和缺失项，不声称本次重跑。
