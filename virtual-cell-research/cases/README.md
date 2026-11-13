# 案例库：按研究任务和真实完成阶段选择

这里维护真实数据的获取、检查和分析方法。案例说明、下载工具、输入审计与观测分析步骤由本项目维护；数据、模型及论文分别引用原始提供方。

当前收录 **7 个案例**。其中 **2 个数据教学流程已实际完成**：一个完成观测响应分析，一个完成输入契约审计并正确阻断。其余案例已核实来源、整理获取方法和待完成步骤。**本轮真实模型运行数为 0，独立预测验证数为 0。**

## 从哪里开始

| 案例 | 研究内容 | 当前证据 | 阅读入口 |
| --- | --- | --- | --- |
| HT115 官方演示数据 | 观测药物响应、配对对照和源尺度 | 已下载 3.14 MB 数据，实际完成观测差值与报告；模型未运行 | [入门案例](prnet-ht115-demo/README.md) |
| Paul2015 造血输入 | 检验 `raw_count` 层是否满足原始计数契约 | 已下载 66.3 MB，扫描后发现非整数，预检正确阻断 | [输入审计案例](celloracle-paul2015-input-audit/README.md) |
| Kang PBMC / IFN-beta | 供者、细胞类型与刺激响应 | 基因和细胞元数据已读取，表达矩阵未下载 | [供者设计案例](kang-ifnb-pbmc/README.md) |
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
| `prepared` | 已完成该案例定义的数据准备、观测教学或输入审计，有可定位证据；不表示输入一定合格 |
| `model_executed` | 确实运行了指定模型与权重，有命令、日志和原生输出 |
| `validated` | 完成明确设计的独立预测评估，保留数据划分、方法与结果 |

模型运行和独立验证状态单列。预检通过、mock、历史图、文件下载或脚本正常退出都不能替代模型推理与独立验证。Paul2015 的案例检查可以完成，同时输入契约不通过；这是有用的审计结果。

## 如何补一个案例

在 [catalog.json](catalog.json) 登记稳定 ID、任务、背景、原始来源、资源 URL/大小/哈希/许可、限制和验收产物；为案例添加简短 README。取得真实证据后再提升阶段，未实现的准备步骤明确保留。贡献步骤见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

来源数据按具体资源条款使用，不自动继承本项目代码的 MIT 许可。源码包包含目录、说明、脚本和少量实际教学证据；原始矩阵与模型权重由用户按需从原始提供方获取。
