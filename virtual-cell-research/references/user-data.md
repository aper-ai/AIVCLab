# 使用自己的表达数据

把 CSV、TSV 或 H5AD 整理成带明确细胞、基因和尺度记录的模型输入。入口为 `scripts/prepare_user_data.py`，输出新的 `prepared_input.h5ad` 和中文检查报告。此步骤只准备输入，不安装模型或启动推理。

## 1. 先明确三件事

| 需要的信息 | 怎样提供 |
| --- | --- |
| 表达尺度 | `raw_counts` 为未归一化原始计数；`normalized` 或 `log1p` 必须对应真实处理记录。名称和数值外观不足以证明来源。 |
| 物种 | 用 `--species human`、`--species mouse` 或准确的其他物种声明。 |
| 矩阵方向 | 表格必须显式指定 `cells_by_genes` 或 `genes_by_cells`；H5AD 已定义 cells × genes，不再填写方向。 |

如果不清楚尺度，先查生成这个文件的流程。不要为通过某个模型的检查，把归一化数值改称原始计数。已完成的模型分析也不必重新做输入准备。

先按[首次使用说明](first-run.md#建立数据教学环境)建立独立 Python 3.12 数据环境。下文 `python` 指该环境的解释器；Windows 可直接写 `.venv-data\Scripts\python.exe`，Linux/macOS 可写 `.venv-data/bin/python`。所有命令均从包含 `SKILL.md` 的目录运行，输出目录必须尚不存在。

## 2. CSV/TSV：直接保留数据和唯一 ID

表格第一列是行 ID，其余列全部为表达值。下面仅说明文件形状，不是可评价模型的小型生物学数据集：

```csv
gene_id,cell_001,cell_002
STAT3,8,5
JUN,3,0
```

读取 genes × cells 的原始计数：

```bash
python scripts/prepare_user_data.py --input data/counts.csv --orientation genes_by_cells --scale raw_counts --species human --gene-id-kind gene_symbol --target STAT3 --output-dir local-runs/my-data-prepared
```

同样支持 `.tsv`、`.csv.gz` 和 `.tsv.gz`。细胞在行时改为 `--orientation cells_by_genes`。程序保留数字样式的 ID，例如 `001` 不会变成 `1`；ID 前后空格、空 ID、重复 ID 和缺失数值会明确阻断，不静默清理。

`raw_counts` 表格转成精确 int64；不接受非整数、超出 int64 的值，也不会把高精度小数取整。其他声明尺度转成 float64，要求有限且非负。所有尺度都保留零值；缺失值不补成零。

### 细胞与基因注释

可同时传 `--obs-metadata data/cells.tsv`。文件必须有唯一的 `cell_id` 列，并包含全部输入细胞各一次；行顺序可以不同，程序按 ID 重排。供体、细胞类型、条件和 batch 等字段原样进入 `obs`：

```tsv
cell_id	donor_id	cell_type	condition
cell_002	D02	Monocyte	control
cell_001	D01	Monocyte	control
```

基因注释使用 `--gene-metadata data/genes.tsv`，必须有唯一的 `gene_id` 列；可包含 `gene_symbol` 等字段。基因集必须精确匹配输入，注释不会替换基因轴。重复的 symbol 可以保留为注释，但任何目标查询和结果连接仍使用唯一 gene ID。

元数据中的字面 `NA` 和空字符串原样保留，不自动解释为细胞类型、不推断为缺失值或零值。已有 H5AD 注释列与外部同名列冲突时停止，不覆盖原注释。细胞子集选择和基因别名映射应由明确的研究步骤完成，再重新提供一致文件。

## 3. H5AD：明确选用 X 还是一个 layer

如果原始计数在 `layers['counts']`：

```bash
python scripts/prepare_user_data.py --input data/sample.h5ad --counts-layer counts --scale raw_counts --species human --target STAT3 --output-dir local-runs/my-data-from-h5ad
```

若要读取 `X`，省略 `--counts-layer`。`--target` 接受实际唯一基因 ID，可以重复提供以检查多个目标；不会根据 gene symbol 的第一次匹配猜测目标。

输出的 `X` 保存选定矩阵，并保留全部细胞和基因、相同顺序、数值、dtype，以及 CSR/CSC 稀疏格式。`obs` 和 `var` 注释也保留。准备器不会把稀疏表达转成 dense。

这是一个最小模型输入：原文件的其他 layer、`raw`、embedding、邻接图和 `uns` 不复制，省略项记录在数据卡中，原文件保持不变。不能把该输出当作原 H5AD 的完整备份。

## 4. 生成 CellOracle KO 预检请求

当前 CellOracle 执行入口要求原始计数和匹配先验的 gene symbol 轴。针对**单个明确目标**，可以在准备数据时同时生成请求：

```bash
python scripts/prepare_user_data.py --input data/counts.csv --orientation genes_by_cells --scale raw_counts --species human --gene-id-kind gene_symbol --target STAT3 --celloracle-ko --python-executable /absolute/path/to/celloracle/python --base-grn priors/human_base_grn.parquet --output-dir local-runs/stat3-input
python scripts/preflight.py --request local-runs/stat3-input/preflight_request.json --output local-runs/stat3-preflight.json
```

Windows 将解释器路径换成实际路径，例如 `D:/envs/celloracle/python.exe`。以上资源路径只是格式示例，需要换成真实存在的文件。准备器只核验可读性和哈希，不执行解释器、加载 GRN 或验证物种匹配。

解释器保留用户指定的虚拟环境启动入口，例如 `.venv-celloracle/bin/python`；即使它是符号链接，也不改写为共享基础 Python。文件哈希识别实际二进制内容，不能替代入口路径或认证该环境中的依赖。

只有 raw_counts、gene_symbol 声明、一个目标、至少 4 个细胞与 4 个基因、没有全零细胞，以及解释器/GRN 文件齐全时，才写 `preflight_request.json`。这些只是该入口的必要条件，不是足够的科学质量标准。缺少条件时仍保存合法的输入与报告，数据卡列出具体缺项，不生成貌似完整的请求。

预检返回 `incomplete` 时阅读未检查事项，而不是反复改状态。确认来源尺度、GRN 物种和基因覆盖、目标 TF、细胞背景及环境后，按 [CellOracle 实际案例](../cases/celloracle-paul2015-gata1/README.md)或 [KO/OE 执行入口](../examples/ko_oe/README.md)继续。数据准备不会把过表达、联合扰动或药筛自动转成单基因 KO；这些任务仍按[输入契约](input-contracts.md)设置。

## 5. 结果与错误怎样处理

| 文件 | 用途 |
| --- | --- |
| `prepared_input.h5ad` | 选定表达矩阵和 obs/var；X 方向统一为 cells × genes |
| `data_card.json` | 用户声明、输入位置、输出尺度、保留/省略内容和下一步缺项 |
| `qc.json` | 完整数值与身份检查、全零细胞数和目标覆盖；没有过滤或运行模型 |
| `provenance.json` | 输入、脚本和产物哈希，命令、时间、环境；不改写为来源认证 |
| `report.md` | 中文结果摘要与下一步 |
| `preflight_request.json` | 仅在显式请求且字段齐全时生成 |
| `error.json` | 本次准备失败的原因；失败目录可能保留未完成文件，不视为成功输出 |

默认每个输入文件最多 **256 MiB**、矩阵存储最多 **256 MiB**、解压表格文本最多 **512 MiB**；单个 ID 轴上限 100 万。H5AD 注释有单独的结构/估算容量检查；这些不是整个 Python 进程的精确 RSS 上限。超出范围时停止，改用适合该数据规模的分块准备流程，或在确认资源后显式调整三个 `--max-*-mib` 参数（各上限 4096 MiB）。不要为了避开限制而随意截断表达矩阵。

退出码 `0` 表示输入准备完成，**不表示模型就绪**；`2` 表示输入、依赖或写入等步骤失败。已有目录不会覆盖，重跑使用新目录。若只缺 CellOracle 请求字段，输入准备仍返回 `0`，但数据卡的请求状态为 `incomplete`。

## 已执行的输入一致性检查

本入口已实际读取 [GSE72857 原始计数准备案例](../cases/celloracle-paul2015-gata1/README.md)产生的 **500 × 10,757** 输入，输出保留了稀疏矩阵的数值、索引、dtype 和全部 obs/var 身份。该输入原本来自一个经过明确筛选的小鼠背景；这里仅检查导入保持一致，不将其称为新的独立数据集、模型执行或科学验证。

模型与数据仍需按具体案例引用原研究。输入格式及语义要求见[输入契约](input-contracts.md)，真实数据来源与限制见各案例说明。
