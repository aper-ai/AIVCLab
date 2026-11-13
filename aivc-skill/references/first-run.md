# 第一次使用 AIVC

不必先学会选择模型和配置 Python。先告诉 Agent **你想回答什么问题、有什么数据，以及想干预哪个基因或哪些药物**；文件和环境中能直接查到的内容由 Agent 检查，再解释可用路线。

## 目录

1. [先选一种开始方式](#先选一种开始方式)
2. [准备最少的科学输入](#准备最少的科学输入)
3. [运行 CellOracle 参数化入口](#运行-celloracle-参数化入口)
4. [运行 Geneformer 参数化入口](#运行-geneformer-参数化入口)
5. [开始药筛前先确认什么](#开始药筛前先确认什么)
6. [运行后按什么顺序看](#运行后按什么顺序看)
7. [遇到失败怎么继续](#遇到失败怎么继续)
8. [可直接使用的提示词](#可直接使用的提示词)

## 先选一种开始方式

| 方式 | 适合的情况 | 你会得到什么 |
| --- | --- | --- |
| 查看历史示例 | 还没准备数据，想先理解输出和局限 | 既有图表、历史报告与勘误的解释；不运行模型 |
| 运行真实参考样例 | 想确认本机环境能否完成实际计算 | 新的命令、日志、模型输出和检查记录；需要相应数据及模型资源 |
| 分析自己的数据 | 已有研究目标及表达数据 | 对你指定输入和基线的分析；不替换为历史示例 |

### 只查看历史示例

先读 [历史报告开头的勘误](../examples/lung_cancer/reports/reproduction-report.md)，再读 [修复说明](../docs/audit-remediation.md)。这些是历史记录，不表示修正后的代码已经在当前机器重跑。

历史 CellOracle 的向量差长度不能解释为特异信号。历史 UniPert Top 20 响应表与药物排名的对应曾有错误，三个药筛分支缺少全量历史响应；不能据旧图补全响应或重新证明候选排名。如果本地缺少某张图或源表，说明缺失，不用生成图代替原始证据。

### 真实参考样例与自己的数据

参考样例的公开输入来源见 [肺癌示例说明](../examples/lung_cancer/README.md)。使用新工作目录准备数据、匹配先验/权重，再运行下面的参数化入口。模型权重、原始数据与环境不随 Skill 自动就绪；历史机器的路径和耗时也不是本机保证。

第一次实际执行可围绕一个已明确的目标条件验证完整流程，记录这是小规模试运行；不要自动改成全药物库、多个模型或另一套目标。完整任务仍按用户原来的范围继续。

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

从仓库根目录可先查看参数，不会启动模型计算：

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

目前药筛代码是需要适配的历史示例，不是把任意 `.h5ad` 放进去就可运行的统一命令。先读 [药筛适配步骤](model-setup.md#复用药筛示例的配置步骤)，检查脚本实际依赖的源码、环境、checkpoint、数据、协变量与条件索引。

- PRnet 和 chemCPA 的接口可接受外部基线，但要对齐具体权重的基因轴与预处理；接口能接收矩阵不代表跨背景预测已获验证。
- UniPert-G2CP 当前调用使用模型自带的细胞系对照，无剂量维度；必须明确实际背景，不能将其结果标成用户样本预测。
- GEARS、UniCure、DrugReflector 的文档路线仍需要相应数据/资源和适配验证，不作为当前已完成的一键功能。
- 先在已明确的小范围条件检查输出完整性、响应差异和评分区分度，再按授权任务扩展；必须保存完整响应、基线、基因与条件索引。

缺少可比较疾病参照时可以交付模型原生响应，不编造恢复分数。排名并列或不可区分时停止推荐候选，保留真实预测和诊断。

## 运行后按什么顺序看

| 顺序 | 文件 | 先看什么 |
| --- | --- | --- |
| 1 | `report.md` | 做了什么、本次运行还是历史读取、哪些条件完成、结论边界 |
| 2 | `manifest.json`、`provenance.json` | 是否确实使用指定的数据、基线、模型、目标、版本和参数 |
| 3 | `validation.json`、`errors.jsonl` | 预测合法性、响应差异、排名区分度和独立验证分别怎样 |
| 4 | 主要图、对应 `tables/` 和图形清单 | 坐标/单位/条件是否一致，图与表能否按 ID 对应 |
| 5 | `raw/` 和完整索引 | 能否从完整结果重新计算统计或重画图 |

`result_available` 表示算出了有效输出，不表示经过独立实验验证。`unvalidated` 不会抹掉已完成预测；`partial` 需要看成功与失败的具体条件。CellOracle 模拟表达、Geneformer embedding 变化和药物转录方向评分各有自己的含义，不能合并成同一种“准确率”或疗效。

## 遇到失败怎么继续

| 提示或现象 | 下一步 |
| --- | --- |
| 找不到输入、先验或 checkpoint | 核对本次实际路径与文件完整性；历史路径不能直接当作本机路径 |
| counts 尺度或完整转录组不符 | 回到原始数据和处理记录；不靠逆 log、补零或加确认标志蒙混通过 |
| 目标不在 GRN/tokenizer/覆盖范围 | 看清具体缺失环节，保留 `no_prediction`；不要自动换成另一个基因 |
| 缺模块、版本或 CUDA 不兼容 | 修复选定的隔离环境；`--help` 能跑不代表推理依赖齐全 |
| 输出目录非空 | 新建运行 ID，保留旧结果 |
| 某个条件失败 | 读该条件的错误记录，保留其他条件结果，只重试失败部分 |
| 图没生成但预测存在 | 读图形清单与源表，补齐画图条件或重画，不必重跑预测 |
| 药物响应几乎相同或评分并列 | 检查权重、基线、剂量及评分定义；不把微小数值差放大成可靠排名 |
| 没有疾病评分或独立验证 | 查看跳过原因和已生成的原生结果，按研究问题补对应数据 |

更具体的记录与失败规则见 [执行手册](execution-playbook.md)。

## 可直接使用的提示词

### 先看懂历史结果

> 我刚接触虚拟细胞。请使用 AIVC 只讲解仓库里的 CellOracle 历史示例，先说明哪些是旧结果和勘误，再用一张图和对应源表解释输出；不要启动模型或说已经重跑。

### 实际运行一个参考条件

> 请使用 AIVC 实际运行公开肺癌参考样例的 STAT3 单基因敲除。先检查本机数据和兼容环境；能从文件核实的信息不要再问。模型和目录可以给出有依据的默认，缺少资源时说明具体缺项。为这次运行新建目录，并交付日志、完整响应和检查记录。

### 分析自己的数据

> 这是我的原始单细胞 h5ad 和处理说明。我想分别模拟 STAT3、JUN 的敲除，主要关心表达变化和不同细胞群的状态差异。请先读取数据和现有环境，推荐适配路线；只把无法从文件确定的必要信息一次问清。保持我指定的基线，不要自动改成模型自带细胞系。

### 只做药物响应，不强制逆转排名

> 请使用 AIVC 检查我提供的表达数据和药物库能否进行药物转录响应预测。我目前没有疾病参照，先保留模型原生响应；说明实际基线来源、环境和权重是否可用。若响应或排名无法区分，报告诊断原因，不推荐候选。
