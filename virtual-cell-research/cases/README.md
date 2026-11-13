# 案例库：按研究任务和真实完成阶段选择

这里维护真实数据的获取、检查和分析方法。案例说明、下载工具、输入审计与观测分析步骤由本项目维护；数据、模型及论文分别引用原始提供方。

当前收录 **11 个工作流案例**：5 项真实数据教学/输入审计/基线评估、2 项真实模型执行、4 项来源与路线整理。HT115 观测教学与 PRnet 参考推理使用同一份 demo，Kang 观测与留一供体评估使用同一项研究数据；Paul2015 输入审计与 Gata1 模拟分别使用该研究的教程对象和原始数据，不把它们计成互不相关的新数据集。**本轮真实模型执行路线为 2 条，独立预测验证仍未完成。**

先看软件实际生成的 [公开案例结果图集](gallery/README.md)，再按下表选择案例。图集包含基因 KO/OE、配对药物观测、PRnet 参考预测和供体留出评价；每张图都有源表、绘图入口和读图说明。

## 从哪里开始

| 案例 | 研究内容 | 当前证据 | 阅读入口 |
| --- | --- | --- | --- |
| HT115 官方演示数据 | 观测药物响应、配对对照和源尺度 | 已下载 3.14 MB 数据，实际完成观测差值与报告；模型未运行 | [入门案例](prnet-ht115-demo/README.md) |
| Airway GSE52778 | 地塞米松、沙丁胺醇及联合处理的供体配对响应 | 已取得 16 条处理后 FPKM 表达谱及来源元数据，完成 4 供体 × 3 对比与结果图；模型未运行 | [药物观测案例](airway-gse52778-drug-response/README.md) |
| Paul2015 造血输入 | 检验 `raw_count` 层是否满足原始计数契约 | 已下载 66.3 MB，扫描后发现非整数，预检正确阻断 | [输入审计案例](celloracle-paul2015-input-audit/README.md) |
| Kang PBMC / IFN-beta | 供者、细胞类型与刺激响应 | 六份数据已取得；完成 129 组计数聚合和 8 个 CD14+ 供体配对分析 | [供者设计案例](kang-ifnb-pbmc/README.md) |
| Kang 留一供体均值基线 | 将每位供体依次留出，检查评价划分与简单基线 | 8 折真实计算、完整成员记录；均值参照优于零响应，仅为同研究交叉验证教学 | [留一供体评估](kang-heldout-baseline/README.md) |
| Paul2015 / CellOracle Gata1 | 原始 UMI、野生型背景、网络拟合与 TF KO/OE | Linux CPU 分别完成 500 细胞 × 1,500 基因的 KO 和 OE 模拟；保存失败修正与完整模型产物 | [实际基因模拟](celloracle-paul2015-gata1/README.md) |
| HT115 / PRnet 固定权重 | 稳定 profile 对应、同尺度预测与简单基线比较 | CPU 实际推理 661 条处理谱；平均误差未优于零响应，训练重叠未知 | [实际模型参考评估](prnet-reference-evaluation/README.md) |
| sci-Plex3 | 细胞系、化合物、剂量和重复孔 | 已核实原始及处理数据入口，未下载矩阵 | [剂量案例](sciplex3-chemical-dose/README.md) |
| Norman K562 | 单基因与组合 CRISPRa | 已核实矩阵和标签来源，小切片待制作 | [基因激活案例](norman2019-k562-crispra/README.md) |
| Adamson K562 UPR | CRISPRi 与 guide/control 映射 | 已核实 UPR 子实验，标签重建与模型评估待完成 | [基因抑制案例](adamson2016-k562-upr-crispri/README.md) |
| Replogle K562 essential | CRISPRi 的 pseudobulk 与单细胞数据 | 已核实作者存档，79.8 MB pseudobulk 未下载 | [聚合与单细胞案例](replogle2022-k562-essential-crispri/README.md) |

## 目录命令

在包含 `SKILL.md` 的目录中执行：

```bash
python scripts/cases.py list
python scripts/cases.py show prnet-ht115-demo
python scripts/cases.py validate
python scripts/cases.py fetch prnet-ht115-demo --asset demo --output-dir local-runs/prnet-input
```

前三个命令完全离线。`fetch` 只获取明确选择的一个资源，创建新的输出目录，默认限额 64 MiB，记录来源、最终 URL、大小和 SHA-256。它不运行模型或解压执行内容。已有目录不会被覆盖；重跑需换目录名。

大文件需明确提高限额，例如 Replogle pseudobulk 可用 `--max-mib 96`；不要在不清楚大小时直接下载全部单细胞矩阵。若目录没有预期 SHA-256，本次下载哈希只表示得到的文件内容，`expected_sha256_verified` 保持未知。发布者的其他校验和另保存在目录中。

## 阶段与验收

| 阶段 | 可以说明什么 |
| --- | --- |
| `catalogued` | 已整理来源、任务和获取方法，不能据此说已取得数据 |
| `data_downloaded` | 需要实际文件与下载记录；仅取得部分元数据时单独注明 |
| `prepared` | 已完成该案例定义的数据准备、观测教学、输入审计或基线评估，有可定位证据；不表示输入一定合格 |
| `model_executed` | 确实运行了指定模型与权重，有命令、日志和原生输出 |
| `validated` | 完成明确设计的独立预测评估，保留数据划分、方法与结果 |

模型运行和独立验证状态单列。留一供体案例的 `baseline_status=executed` 表示实际计算了均值参照与评估；其 `model_status=not_run` 指未调用虚拟细胞后端，不把它增加为一条 CellOracle/PRnet 模型路线。预检通过、mock、历史图、文件下载或脚本正常退出都不能替代模型推理与独立验证。Paul2015 的案例检查可以完成，同时输入契约不通过；这是有用的审计结果。

## 如何补一个案例

在 [catalog.json](catalog.json) 登记稳定 ID、任务、背景、原始来源、资源 URL/大小/哈希/许可、限制和验收产物；为案例添加简短 README。取得真实证据后再提升阶段，未实现的准备步骤明确保留。贡献步骤见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

来源数据按具体资源条款使用，不自动继承本项目的代码许可。源码包包含目录、说明、脚本和少量实际教学证据；原始矩阵与模型权重由用户按需从原始提供方获取。
