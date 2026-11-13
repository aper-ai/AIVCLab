# Virtual Cell Research · 虚拟细胞研究 Skill

让刚接触虚拟细胞的研究者从真实数据入手，逐步完成输入检查、干预分析和结果复核。这里提供科研 Agent 可读取的工作流程、案例目录、数据检查与教学脚本，以及按实际能力接入模型的路线。

**先完成一个小而真实的观测数据案例，再决定要运行哪个模型。** 当前可以直接学习如何核对处理与对照、计算观测表达差值、读取质量记录；CellOracle、Geneformer 等模型分析仍需要各自的数据、环境和模型资源。

## 第一次使用：读懂真实的药物处理与对照

推荐从 `prnet-ht115-demo` 开始。它使用 PRnet 官方发布的约 **3.14 MB** HT115 示例数据，包含 **661 条处理表达谱、20 条对照表达谱和 978 个基因**。本项目的教学脚本按来源文件指定的对照计算：

> 观测表达差值 = 处理后的 X − 指定对照的 X

这一步读取真实观测数据，**不加载 PRnet 权重，也不执行 PRnet 预测**。一条表达谱不是一个单细胞；差值保留来源文件的处理后尺度，不是原始计数或表达倍数。

在包含 `SKILL.md` 的 `virtual-cell-research/` 目录、使用独立 Python 3.12 环境执行。环境准备与 Windows 命令见 [首次使用](references/first-run.md#建立数据教学环境)。

```bash
python -m pip install -r requirements-data.txt
python scripts/cases.py list
python scripts/cases.py show prnet-ht115-demo
python scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
python scripts/observed_prnet_case.py --input local-runs/prnet-input/demo.h5ad --output-dir local-runs/prnet-observed
```

`list`、`show` 只读本地目录。`fetch` 才下载明确选择的一个资源，并记录大小、来源和哈希；不下载全库、不解压、不安装模型。下载和分析均使用新的输出目录，重复执行时换一个目录名并同步修改输入路径。

完成后打开 `local-runs/prnet-observed/report.md`，对照 `qc.json`、`tables/condition_index.csv` 和完整观测差值表阅读，再看图。**其中 338 条处理表达谱的指定对照来自不同 RNA plate**：脚本保留来源配对并逐条标记，差值可能包含批次影响。图与 Top 基因是描述性展示，不构成药效排名、显著性检验或模型验证。产物清单和完整解释见 [案例目录](cases/README.md)。

如果让 Agent 操作，可以直接说：

> 请读取「这个 Skill 的绝对路径/SKILL.md」，使用 Virtual Cell Research 完成 prnet-ht115-demo 观测教学。先查看案例来源和资源大小，使用独立数据环境，下载明确列出的 demo 资源，计算指定对照下的观测差值。带我阅读跨板配对、完整结果和图；不要把它表述为 PRnet 模型复现。

## 七个案例，各自完成到了哪一步

目录记录与实际执行证据分开保存。**本版没有执行这些案例的模型推理，也没有完成独立科学验证。** 下表中的教学完成、输入阻断和元信息读取都是具体工作范围。

| 案例 ID | 学习或研究问题 | 本版已完成范围 |
| --- | --- | --- |
| `prnet-ht115-demo` | 药物处理表达谱怎样与指定对照对应，如何保留完整观测差值 | 已读取真实数据并完成观测教学；未运行 PRnet |
| `celloracle-paul2015-input-audit` | 名为 `raw_count` 的层是否真满足原始整数计数要求 | 已检查约 66.3 MB 的真实教程文件；发现非整数值，预检按预期阻断；未运行 CellOracle |
| `kang-ifnb-pbmc` | IFN-β 刺激、供体与细胞背景如何组织 | 已读取来源元信息，尚未取得表达矩阵 |
| `sciplex3-chemical-dose` | 化合物、剂量和细胞背景如何共同定义条件 | 已收录来源与路线；数据未下载 |
| `norman2019-k562-crispra` | K562 单基因与组合 CRISPRa 的任务如何定义 | 已收录来源与路线；数据未下载 |
| `adamson2016-k562-upr-crispri` | K562 CRISPRi 与未折叠蛋白反应的输入如何组织 | 已收录来源与路线；数据未下载 |
| `replogle2022-k562-essential-crispri` | 必需基因 CRISPRi 的汇总响应如何阅读 | 已收录约 79.8 MB pseudobulk 资源；尚未下载，不把汇总矩阵当作原始单细胞数据 |

用 `python scripts/cases.py show <case-id>` 查看来源、许可记录、资源、限制与预期产物；完整索引见 [cases/README.md](cases/README.md) 和 [catalog.json](cases/catalog.json)。`catalogued`、`data_downloaded`、`prepared`、`model_executed`、`validated` 表示不同阶段，不能把“已收录”或“文件已下载”算成模型复现。

Paul2015 输入审计的预期结果是 `blocked`、退出码 `2`。这说明检查找到了真实输入问题；它不表示 CellOracle 模型失败，也不表示官方处理后对象的教程无法运行。复现步骤及证据见 [输入尺度审计案例](cases/celloracle-paul2015-input-audit/README.md)。

## 用自己的数据，按研究问题继续

1. **说明问题与目标。** KO、OE、药物响应或已有结果复核；多个基因分别还是联合扰动。
2. **检查输入和资源。** 读取矩阵层、尺度、基因 ID、物种、背景与对照，核对实际环境和必需资源。
3. **确定兼容路线。** Agent 给出有依据的模型、解释器与目录设置；只合并询问无法核实的关键科学缺项，不静默替换指定模型、基线或目标。
4. **按约定范围计算。** 新环境或新数据先检查小范围产物，再继续已授权的完整范围。
5. **保存完整结果与证据。** 先保留原生输出、基线和条件索引，再做摘要、适用评分与图；分别记录运行、响应、排名和独立验证状态。

Agent 主流程见 [SKILL.md](SKILL.md)，具体输入见 [输入契约](references/input-contracts.md)，执行与失败处理见 [执行手册](references/execution-playbook.md)。

### 数据预检能检查什么

```bash
python scripts/preflight.py --request /absolute/request.json --output /absolute/preflight-001.json
```

CSV/TSV 可以流式检查结构、数值和目标覆盖。H5AD 默认读取元数据与矩阵形状；在请求 JSON 中显式设置 `"scan_h5ad_values": true`，可按块扫描所选 dense、CSR 或 CSC 矩阵的全部存储值，检查非有限数值及声明为 raw counts 时的非负整数条件。

数值扫描不会证明原始计数来源，也不核实稀疏索引完整性、`n_counts` 与矩阵的一致性或模型兼容性。**当前实际路线通常仍返回 `incomplete`。** `preflight_ready` 只覆盖预检声明的有限检查范围；输入问题记 `blocked`。请求、输出路径和失败下一步见 [预检与排错](docs/troubleshooting.md)。

### 模型路线的实际实现程度

| 路线 | 已有入口 | 尚需满足的条件 |
| --- | --- | --- |
| CellOracle | 参数化 KO/OE 脚本、输入检查、模拟结果导出及适配测试 | 匹配的单细胞原始计数、GRN 先验与独立环境；OE 需明确内部尺度设定 |
| Geneformer | 参数化 delete/overexpress 脚本及 embedding 结果导出 | 人类完整原始转录组、匹配 tokenizer/权重与环境；输出不是表达倍数 |
| PRnet、chemCPA、UniPert-G2CP | 复用并维护的肺癌药筛适配脚本及结果契约 | 仍需修改历史资源路径，核对预处理、权重、协变量和基线；完成 HT115 观测教学不等于这些模型可运行 |
| GEARS、UniCure、DrugReflector | 参考流程、资源说明和代码片段 | 需要具体适配、匹配数据及实际运行验收，尚无通用一键入口 |

真实模型资源不随 Skill 分发。各后端隔离环境；测试与 `--help` 成功都不能替代真实模型执行。详见 [模型能力](references/model-capabilities.md) 和 [模型配置](references/model-setup.md)。

## 结果先看证据，再看排序

观测教学先看 `report.md`、`provenance.json`、`qc.json`、完整差值和条件索引。模型分析还需检查执行/预测状态、响应差异、条件级与药物级排名，以及独立验证。具体阅读顺序见 [首次使用](references/first-run.md#运行后按什么顺序看)。

药物聚合后重新检查区分度；同分保留并列，无法区分时停止候选推荐。高相关和缺少独立验证不自动等于计算失败。预测转录方向、CellOracle 模拟位移、Geneformer embedding 影响各有自己的含义，不能直接推出药敏、临床疗效或靶点机制。

图应有对应源表与生成状态；绘图失败保留已完成的数值结果。历史数据缺失时不从旧图补造全量响应。需要复核旧研究时，再读 [历史肺癌报告归档](archive/aivc-587579e7/reproduction-report.md) 与 [勘误](docs/audit-remediation.md)；它们不属于本版新案例的执行证据。

## 一起维护

欢迎从一个案例、一条模型适配或一个可复现问题开始。贡献要求、状态证据和测试命令见 [CONTRIBUTING.md](CONTRIBUTING.md)。快速工程测试使用独立 Python 3.12 环境：

```bash
python -m pip install -r requirements-tests.txt
python -m unittest discover -s tests -v
python scripts/cases.py validate
python scripts/package_skill.py
```

打包产物为 `dist/virtual-cell-research.zip`，解压根目录同名；包含工作流、必要源码、案例说明、来源和许可，不包含真实数据、环境、权重或本地运行结果。测试中的 mock 与合成输入会明确标注，不作为科学证据。

本项目维护工作流、案例和工具，并复用部分开源适配实现。代码、历史材料、模型和数据的归属分别说明，见 [NOTICE](NOTICE)、[LICENSE](LICENSE) 和 [第三方来源](THIRD_PARTY_NOTICES.md)。
