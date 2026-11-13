# 常见问题与踩坑记录

本页先说明当前预检和实际案例中的问题，再保留固定版本导入材料的历史排错记录。新的 [CellOracle 原始计数案例](../cases/celloracle-paul2015-gata1/README.md)与 [PRnet 参考评估](../cases/prnet-reference-evaluation/README.md)已在 Linux CPU 实际运行；它们的环境和结果以各自证据为准。“历史安装与分析记录”之后的观察来自 [NOTICE](../NOTICE) 所列版本，不自动适用于当前平台和权重。

## 先检查输入，不启动模型

`scripts/preflight.py` 把能实际检查的字段、文件和表格问题写成 JSON，供用户和 Agent 复查。它不会安装依赖、下载权重、调用模型、执行 `python_executable` 或自动转换输入，也不会创建分析目录。它只写入命令明确指定的预检记录。

在 Skill 根目录运行：

```bash
python scripts/preflight.py --request /path/to/request.json --output /path/to/preflight-001.json
```

**`--output` 必须是新文件。重跑时改用 `preflight-002.json` 等新文件名**；已有记录、请求文件、输入数据、资源文件和链接都不能被覆盖。命令行参数 `--request`、`--output` 按当前工作目录解析；**JSON 内的所有相对路径统一相对 `request.json` 所在目录解析**，包含 `analysis_dir`、`python_executable` 和 `resources` 中的路径。请求文件采用 UTF-8，大小最多 256 KiB；只填写文件路径，不把表达矩阵直接塞进请求。重复 JSON 键、未知字段和非有限数值会被拒绝。

下面是 CellOracle KO 的字段示例，需要换成用户实际选择的文件、目标基因和解释器。它检查 CSV 输入准备情况；当前 CellOracle 执行示例仍需要 `.h5ad`，因此即使表格干净也会返回 `incomplete`，不会自动转换：

```json
{
  "schema_version": 1,
  "task": "ko",
  "backend": "CellOracle",
  "input_file": "data/counts.csv",
  "input_scale": "raw_counts",
  "species": "human",
  "matrix_orientation": "genes_by_cells",
  "targets": ["STAT3"],
  "analysis_dir": "analysis",
  "python_executable": "/absolute/path/to/python",
  "resources": {
    "base_grn": "priors/base_grn.parquet"
  }
}
```

Windows 解释器路径可写成 `D:/envs/celloracle/python.exe`，避免 JSON 反斜杠转义。未指定解释器时，记录 `requested_python_status: unknown` 和检查器自身的 `sys.executable`，供用户选择；不会把检查器环境自动认定为兼容模型的环境。即使给出的文件可读，也只记录 `readable_path_only_not_executed`。

解释器路径保留用户选择的虚拟环境入口，不将 `.venv/bin/python` 的符号链接展开成共享基础 Python；后者可能没有该环境的模型依赖。数据准备生成的请求与预检报告都应保留这一入口，后续运行使用相同路径。普通数据资源可规范解析路径，解释器入口需要保留其环境含义。

### 请求字段（schema_version 1）

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 可省略；指定时必须为整数 `1`。 |
| `task`、`backend`、`analysis_dir` | 必填。任务为 `ko`、`oe` 或 `drug`。模型名须使用 `CellOracle`、`Geneformer`、`GEARS`、`PRnet`、`chemCPA`、`UniPert-G2CP`、`UniCure`、`DrugReflector` 中的精确写法，并匹配任务。目录只检查路径和现有父目录，不做写入探测。 |
| `input_file`、`input_scale`、`species` | 使用表达输入的路线必填；尺度为 `raw_counts`、`normalized` 或 `log1p`。物种和尺度是用户声明，不能通过数值形状证明与模型训练一致。 |
| `targets`、`intervention_mode` | KO/OE 必须给不重复的非空基因 ID 数组。多个目标必须指定 `independent` 或 `joint`；联合路线的模型支持仍需另外核对。 |
| `matrix_orientation` | CSV/TSV 必填：`genes_by_cells` 或 `cells_by_genes`，不猜测方向。两种格式均以首列保存行 ID，其余列只放数值。 |
| `counts_layer` | h5ad 可选，用于指出待检查的表达层；省略时选择 `X`。是否读取数值由 `scan_h5ad_values` 决定。当前 Geneformer 示例要求原始计数位于 `X`，不接受此字段。 |
| `scan_h5ad_values` | h5ad 可选布尔值，省略或 `false` 时只检查元数据与形状；`true` 时按块扫描所选 dense/CSR/CSC 矩阵的全部存储值，不把稀疏矩阵转为 dense。数值检查不认证原始计数来源、稀疏索引结构、`n_counts` 一致性或模型权重。 |
| `raw_full_transcriptome` | 当前 Geneformer 路线必须显式声明为 `true`，同时声明人类和 `raw_counts`。声明不能证明数据未经筛选或归一化。 |
| `oe_value`、`oe_percentile` | 仅 CellOracle OE 使用，必须且只能选一个；前者为有限正数，后者在 `(0, 100]`。预处理后还要检查 `imputed_count` 尺度与实际范围，不能把它解释为实验倍数。 |
| `python_executable` | 可读的解释器文件路径，不能只写命令别名 `python`。未提供时记未完成；此工具不执行它，也不认证其依赖。 |
| `resources` | 可选的资源名到本地文件路径字典，例如 `{"base_grn": "priors/base_grn.parquet"}`。只检查文件存在、非空与可读。CellOracle 缺少 `base_grn` 记未完成；不会下载文件或检查全部权重。 |
| `drug_library`、`disease_signature` | 药筛需要用户指定 `drug_library`；疾病方向比较另给 `disease_signature`。DrugReflector 必须给后者，不能用表达 `input_file` 代替。这里只检查文件和可读取的表格结构，后端列语义、剂量单位、药物编码和签名构造均另列未检查。 |
| `baseline_source`、`cell_context` | UniPert-G2CP 必须填写 `baseline_source: "model_builtin"` 和细胞背景，例如用户选择的 `A549`；该路线拒绝 `input_file`，避免把自带对照误标为患者基线。实际 checkpoint 与细胞背景的匹配仍未认证。 |

### 表格与 h5ad 分别检查什么

CSV/TSV 必须有非空且不重复的列名。`genes_by_cells` 的形态如下；`cells_by_genes` 则把细胞放在首列、基因 ID 放在表头：

```csv
gene_id,cell_1,cell_2
STAT3,1,0
JUN,2,3
```

表达表格逐行读取，检查行宽、重复或空白行 ID、目标基因覆盖、空值、非数字和 NaN/Inf。声明 `raw_counts` 时，另查非负整数；缺测不会自动填成零。内存只保留当前记录和 ID 集合，不装入完整表达矩阵。CellOracle、Geneformer、GEARS 的 CSV/TSV 输入还需要补成对应路线的 h5ad 格式和元数据，预检不会替用户完成这一步。

h5ad 检查需要**运行检查器的环境**已经有可用的 `anndata.io.read_elem` 和 `h5py`；缺失或无法导入时明确记 `h5ad_dependency`、`incomplete`，不会自动安装。默认只读 `obs`、`var` 和所选表达位置的形状，不载入完整 `X`、`layers`、`raw` 或 embedding。检查 ID、目标覆盖以及相应路线的元数据字段：Geneformer 的无版本人类 `ensembl_id` 与正的有限 `n_counts`；GEARS 的 `condition` 和 `cell_type`。默认将矩阵数值检查记为 `h5ad_values` 未完成，不能把“元数据可读”解释成全矩阵 QC 通过。

显式设置 `"scan_h5ad_values": true` 后，检查器用 NumPy 按块扫描选中位置的所有存储值，支持 dense、CSR 和 CSC；稀疏矩阵只读 `data`，不会为检查而转成 dense，隐式零视作合法计数。任何 NaN/Inf 都会阻断；声明 `raw_counts` 时，负数或非整数也会阻断。数值检查仍不能证明原始计数来源或预处理过程，也不审计稀疏索引结构、不比较 `n_counts` 与表达总和、不验证权重。未发现数值错误时，这些语义缺口仍记在 `h5ad_semantics` 中。

### 官方教程中的 `raw_count` 也需要检查

[Paul2015 输入审计案例](../cases/celloracle-paul2015-input-audit/README.md)对固定版本的官方 CellOracle H5AD 进行了实际下载、哈希复算和完整扫描。`layers/raw_count` 没有负数，但含 **1,327,057 个非整数**。在本 Skill 当前要求原始整数计数的 CellOracle 入口中，预检因此返回 `matrix_invalid`、`blocked` 和退出码 `2`。

这是输入假设被否定，不是模型失败；案例检查已经完成，`input_contract_passed` 仍为 `false`，模型未运行。不能通过四舍五入、关闭扫描或修改尺度声明将处理后的表达值伪装成原始计数。应核查原研究数据和预处理来源，或另行适配并验证官方预处理 Oracle/Links 对象路线。该观察不否定 CellOracle 官方教程本身，也不构成扰动预测的准确性评估。

GRN 的文件可读不代表其物种、gene symbol 覆盖和目标 TF 适用；只有实际拟合后才能检查目标是否在有效网络中。药物库的表头可读也不代表药物可编码、剂量正确或疾病逆转可计算。这些缺口保存在预检记录，执行者须按[输入契约](../references/input-contracts.md)及所选路线继续核实。

### 如何看结果和退出码

| `status` | 退出码 | 含义 |
| --- | --- | --- |
| `preflight_ready` | `0` | 此工具所声明的检查范围完成，仍不代表 backend 就绪或预测成功。 |
| `incomplete` | `1` | 未发现已知硬错误，但仍有 `required_for_preflight: true` 的未完成项，需要补充信息、依赖或路线检查。未启用的 h5ad 数值扫描、原始计数来源等 h5ad 语义、CSV→h5ad 转换和药物语义等检查均可能保留未完成，因此正常文件也可能返回该状态。 |
| `blocked` | `2` | 字段、文件或数值存在确定问题。无法读取请求、写入新输出或输出会覆盖源文件时也返回 `2`；写入失败会在终端说明原因。 |

记录中的 `blockers` 是已确认问题，`warnings` 是解释边界，`not_checked` 是尚未核实的事项。所有记录都保持 `prediction_status: "not_run"`、`model_compatibility: "not_verified"`。解释器执行、依赖组合、GPU/CUDA、权重/tokenizer 版本、模型基因顺序和科学验证均不在本次预检的完成范围内。不要把退出码或单一状态当作启动模型的兼容性认证。

## 当前真实案例中的问题

### CellOracle 0.20.0 的 CV 检查索引越界

基因总数足够不代表内部 CV 计算可用的基因足够。本例首次选入 1,001 个基因，但只有 790 个满足该版本的条件，原导入器访问第 1,000 个分数时失败。当前适配入口提前检查：至少 `min(入选基因数, 1000)` 个基因在大于 2 个细胞中表达，且平均原始计数位于 `(0, 35)`。不足时返回具体数量和操作建议。

本例显式改用 `--n-hvg 1500` 后有 1,211 个合格基因，运行成功；不能据此给所有数据统一增加 HVG，也不能通过填数或改尺度绕过检查。此规则只核实过 0.20.0，其他版本保留未检查状态。详见[实际失败与重跑记录](../cases/celloracle-paul2015-gata1/README.md)。

### PRnet 相关系数为正，为什么仍不能说优于简单基线

固定参考案例中，预测响应的平均 Pearson 为 0.4151，但平均逐表达谱 RMSE 为 0.140141，高于零响应参照的 0.132420。相关衡量方向一致性，RMSE 还受幅度误差影响；两者必须同时查看。零响应向量恒定，相关系数应标为未定义，不填成零。

参考入口还在 Scanpy 就地预处理前复制原始矩阵，防止导出的 `source_X` 实际变成处理后数值；完整基线、观测和预测响应均用保存的 ID 对齐复核。训练重叠未知与全部 demo 样本共同决定归一化目标的限制见[案例说明](../cases/prnet-reference-evaluation/README.md)。

### Kang 条码相同或 gene symbol 重复

对照和刺激文库有 313 个相同条码，不能直接按裸 barcode 合并。当前入口只接受固定来源文件，显式核对来源合并注释的后缀规则，并保留样本 accession 与原条码。9 个字面 `NA` 细胞标签按未分配处理；它们不构成第九种细胞类型。基因轴使用唯一 Ensembl ID，重复 symbol 保留为注释，不能用第一次匹配替代唯一标识。

观测响应的生物学配对单位是供体；CD14+ 示例的 8 位供体不能被数千个细胞替代。图中的绝对变化 Top 12 本次全部为正，不代表没有负向响应。完整正负结果与来源计数差异见 [Kang 案例](../cases/kang-ifnb-pbmc/README.md)。

## 历史安装与分析记录

以下保留原固定版本的安装与排错经验。新手先使用上述实际案例环境；涉及旧 Windows 环境、A549 和肺癌药筛的观察均不计入本项目新案例的模型执行或独立验证。

## 安装

### CellOracle 在 Windows 上装不下来

`pip install celloracle` 会拉进 `velocyto` 和 `gimmemotifs` 两个只有源码包的依赖，conda-forge 与 bioconda 都没有 win-64 构建。`velocyto` 唯一的 Cython 模块 `speedboosted` 提供 CellOracle 计算路径要用的 `colDeltaCor` 系列函数，必须真的编译。

处理方式见 [`environment-celloracle-windows.md`](environment-celloracle-windows.md)。要点：用 pip 包 `ziglang` 自带的 zig 当 C 编译器，并且必须用 Cython 3 从官方 `.pyx` 重新生成 C——sdist 里自带的 `speedboosted.c` 太旧，Python 3.10 下会报 `expression is not assignable` 和 `no member named 'tp_print'`。

### CellOracle 装完导入时报 `which: no R` 和 jupyter 版本告警

不阻断。前者是 `test_R_libraries_installation()` 找不到 R，本流程不用 R；后者只是版本提示。

### CellOracle 使用隔离环境

`celloracle 0.20.0` 锁定 `numpy==1.26.4` 和 `pandas<=1.5.3`，和带新版 scanpy 的主环境冲突。两个解释器分开装，靠 `manifest` 记录各自路径。

## 输入

### PRnet 的输入契约

PRnet 的 LINCS 适配器使用自带 AnnData（978 landmark 基因），需要 `SMILES`、`dose`、`cov_drug_name`、`paired_control_index`，按 `cell_type` 取子集。模型前向接口也能接外部基线，适用性由预处理、权重与训练域共同决定。

取子集时必须连同 `paired_control_index` 指向的对照一起保留，否则数据集构建直接报错。A549（人肺腺癌）有 4060 个 profile、458 种药物。

### chemCPA 查不到药物表征会静默填零向量

chemCPA 按 SMILES 从 parquet 查药物表征，查不到时会静默填零向量，适配器需先检查覆盖。2333 个 FDA 药物中，训练表征覆盖 768 个，剩余 1565 个需按兼容流程补充表征或标为无预测。

补表征的做法是照它的生成流程重算：descriptastorus 的 RDKit2D 描述符 → NaN/Inf 置 0 → 丢低方差列 → 用训练集统计量做 z 标准化。标准化用的 mean/std 没存在 parquet 里，要用训练集 SMILES 重算原始描述符反解，再拿 parquet 自身校验。实测 194 列里 180 列逐值一致。

### chemCPA 的 config 缺字段

`load_config` 读出来的 config 里没有 `config_hash`，要手动补，否则 `load_model` 报 KeyError。另外 `load_model` 里是 `from chemCPA.paths import CHECKPOINT_DIR`，要改 `utils` 命名空间里的那份，改 `chemCPA.paths` 无效。

## 结果

### CellOracle 的空扰动与随机化对照

`simulate_shift` 传播的是"输入 − 实测"这个差值。扰动条件为空时差值恒为 0，位移也是 0。扰动位移使用下述随机化投影作技术对照。

`estimate_transition_prob(calculate_randomized=True)` 会打乱 `delta_X` 并随机翻转符号，计算随机化表达变化的投影对照 `delta_embedding_random`，GRN 保持固定。原始与对照并排展示，两者向量差长度按描述量解读。

### 药筛排名看起来有数，实际不随药物变化

历史外部基线测试中，模型输出由共同成分主导，药物间响应差异较小。

按 `../references/downstream-results.md` 分开检查预测有限性、逐基因响应范围和评分区分度。NaN/Inf 按条件失败；评分相同或余弦接近 1 不足以判预测失败。响应同方向但幅度不同可以是有效输出。评分无法区分时保留预测，将排名标 `unresolved`；数值容差用于分辨数值差异，生物学显著性另需适用检验。

上游历史记录：同一批 FDA 药物库上，chemCPA 极差 3.4e-06、相关中位数 1.00000；PRnet 0.0084、0.99994；UniPert-G2CP 0.307、0.958。这些历史数值使用旧版判据，新的运行需分别核对预测、响应和排名。

### chemCPA 药物效应接近 0

上游历史排查记录了剂量响应模块贡献较小的现象：该次带 BatchNorm 的 MLP 输出经 sigmoid 后约为 5e-4，按 `combo_embedding = transformed × sigmoid` 计算后，药物对隐变量的贡献约为 0.01。这些中间量不能单独证明权重本身有缺陷，也不能排除加载、运行环境或输入适配问题。

上游还记录了使用模型自带 A549 对照、沿 `chemCPA.train.compute_prediction` 路径复算时，5 个药物响应两两相关达到 1.000000。这个现象仅限于该次历史输入、权重与环境；原因仍需核查权重加载、环境和官方参考条件，本次没有重跑或确证该归因。

### 单细胞矩阵投到 landmark 基因空间会掉基因

chemCPA 是 977 个 landmark 基因，PRnet 和 UniPert-G2CP 是 978 个。单细胞矩阵投过去覆盖率约 96%，缺失基因与实测零值分开。当前示例没有经过验证的插补流程，缺模型必需基因时停止该路推理；评分使用共同有效基因并保存掩码。

SciPlex 与 LINCS 各自按对应权重的训练预处理核对归一化口径。记录归一化所用基因范围、目标总量及 log 变换。

## 交付

### 缺失候选的保存方式

无覆盖候选标 `no_prediction`，预测值留缺失；有效预测中的零效应正常保留。

### 运行与验证状态分别记录

缺少独立实验或留出数据时标 `unvalidated`，并保存原始模型结果。预测与实测相关系数需注明来源属于训练内比较、留出测试还是外部验证。
