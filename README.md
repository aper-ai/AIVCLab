# Virtual Cell Research · 虚拟细胞研究 Skill

**从表达数据出发，开展虚拟基因敲除、过表达与药物筛选。**

**Virtual Cell Research** 是面向转录组和单细胞研究的科研 Agent Skill。提供表达矩阵、目标基因或药物库后，Agent 按研究目标检查数据与对照、匹配模型、运行虚拟干预，生成预测响应、变化基因、状态位移或药物评分，并交付图表、质量检查与可追溯的运行记录。

## 三项核心能力

| 研究任务 | 提供什么 | 得到什么 |
| --- | --- | --- |
| **虚拟基因敲除** | 表达数据、目标基因、细胞背景 | 模型支持的表达变化、受影响基因与细胞状态变化 |
| **虚拟过表达** | 表达数据、目标基因、明确的过表达设定 | 设定条件下的模拟响应，以及对应基线和实际作用范围 |
| **虚拟药物筛选** | 药物库、细胞背景和模型所需基线；疾病方向比较另需疾病参照 | 逐药转录响应、适用的评分与排序；支持剂量的模型可比较浓度 |

结果类型随模型能力而定。具体入口、所需资源及真实运行范围见 [模型能力表](virtual-cell-research/references/model-capabilities.md)。

## 直接从你的任务开始

- **已有自己的数据**：按 [数据准备](virtual-cell-research/references/user-data.md) 检查 CSV、TSV 或 H5AD，保留完整标识与原始数值，再进入模型分析。
- **第一次接触虚拟细胞**：从 [首次使用](virtual-cell-research/references/first-run.md) 选择一个小型真实案例，学习输入、对照、预测与图表。
- **已经得到结果**：用 [结果解读](virtual-cell-research/references/result-reading.md) 生成中文说明，先看关键变化和基线，再回到完整源表。
- **想评价预测是否有用**：按 [预测评估](virtual-cell-research/references/prediction-evaluation.md) 对齐实测与预测、检查数据划分，并与简单基线比较。

对 Agent 说明你的问题即可，例如：

> 使用 Virtual Cell Research，对我提供的单细胞数据模拟 STAT3 敲除。请检查输入、选择适用模型，输出完整模拟结果、变化基因和状态图，并解释主要发现与限制。

完整使用方式、三类任务的提示词和执行入口见 [Skill 使用说明](virtual-cell-research/README.md)。

## 为什么适合研究与共建

**让 Agent 处理流程，让研究者掌握判断。** 已提供的信息会直接沿用；需要选择的科学条件会清楚说明。每次分析记录模型版本、输入来源、参数、对照和完成状态，便于复查、重跑及协作。

**用完整结果支撑图表。** 先保存预测、基线、响应和稳定 ID，再生成摘要与图。运行成功、技术质量和独立科学验证分别呈现。

**从一个具体贡献开始。** 新增数据案例、模型适配、输入检查或结果图表，都可以沿现有约定逐步加入。无需先理解或搭建一个庞大的平台，见 [贡献指南](virtual-cell-research/CONTRIBUTING.md)。

## 真实案例与资源

[案例目录](virtual-cell-research/cases/README.md) 提供来源、数据获取、运行命令、结果图和实际完成阶段。已执行的路线包括 HT115 药物观测、Kang 供体配对、CellOracle 基因扰动和 PRnet 参考推理；各自的证据与解释范围保存在案例中。

模型环境按路线独立准备，数据和权重从所列来源获取。项目提供的 [Windows 结果查看器](docs/desktop-viewer.md) 可用于已有模型运行包的本地复核，Skill 本身可以直接使用。

[代码许可](virtual-cell-research/LICENSE) · [资源与来源记录](virtual-cell-research/THIRD_PARTY_NOTICES.md)
