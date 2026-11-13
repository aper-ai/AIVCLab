# CellOracle Paul2015：输入尺度陷阱审计

本案例使用 CellOracle 官方 Paul2015 小鼠造血教程文件，检查一个常见假设：名为 `raw_count` 的层是否符合当前 CellOracle 示例入口要求的原始整数计数。

**预期结果是 `blocked`，退出码为 `2`。** 实际文件中的 `raw_count` 层含非整数值，不能通过此输入契约。这代表输入审计发现了问题；模型尚未执行，不是一次模型运行失败，也不能说明 CellOracle 官方预处理对象教程不能运行。

本案例新增的是固定来源、完整数值检查和阻断解释。数据来自 Paul 等人的原研究与 CellOracle 作者提供的教程工件，算法与数据的原始贡献归相应作者。

## 复现步骤

以下命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 创建或复用独立 Python 3.12 环境；下文 `python` 指向该环境，Windows 可使用 `.\.venv-data\Scripts\python.exe`。

安装的是根目录 [requirements-data.txt](../../requirements-data.txt) 中读取 H5AD 和预检所需的依赖；这里不指定模型环境，不安装模型或下载权重。

```bash
python -m pip install -r requirements-data.txt
python scripts/cases.py show celloracle-paul2015-input-audit
python scripts/cases.py fetch celloracle-paul2015-input-audit --asset tutorial --output-dir local-runs/paul2015-input
python scripts/preflight.py --request cases/celloracle-paul2015-input-audit/request.json --output local-runs/paul2015-preflight-001.json
```

下载文件约 66.3 MB（63.2 MiB），固定到官方仓库中的一个提交，并校验文件大小及 SHA-256。下载器需要新的输出目录；重复操作时应选择新的目录并同步修改请求中的文件路径。预检也不覆盖已有报告，重复预检请使用新的报告名，例如 `paul2015-preflight-002.json`。

**两类相对路径的起点不同。** 命令中的 `--output-dir local-runs/paul2015-input` 和 `--output local-runs/paul2015-preflight-001.json` 相对于当前 Skill 根目录；JSON 内的 `input_file`、`analysis_dir` 相对于 `cases/celloracle-paul2015-input-audit/request.json` 所在目录。

因此，请求里的 `../../local-runs/paul2015-input/Paul_etal_v202204.h5ad` 正好指向 Skill 根目录下的下载文件。不要把 JSON 中这条路径直接改成 `local-runs/...`，否则会去案例子目录中找文件。重跑若换了下载目录，只修改对应的目录名并保留正确相对关系，或给出实际绝对路径。示例使用 `/`，可用于 Linux、macOS 和 Windows Python。

`request.json` 故意声明 `input_scale="raw_counts"`，并选中 `counts_layer="raw_count"`、`scan_h5ad_values=true`，以检验这一假设。它没有配置 `python_executable` 或 `resources.base_grn`：解释器选择、先验网络与模型环境均未验收，也没有为演示构造假的 base GRN。

正常复现后应在 JSON 报告中看到：

```json
{
  "status": "blocked",
  "prediction_status": "not_run",
  "model_compatibility": "not_verified",
  "blockers": [
    {
      "code": "matrix_invalid",
      "message": "raw_counts requires nonnegative integer values; found 0 negative and 1327057 noninteger stored values; a layer name does not establish the data scale"
    }
  ]
}
```

上述为报告中的关键字段节选。报告另有 `python_unknown`、`base_grn` 等未检查项。若报告只有下载失败、文件不存在或依赖缺失，还没有复现本案例的数值阻断。不要为了获得退出码 `0` 而删除扫描选项、改变尺度声明，或将表达值四舍五入成整数。无法从这些处理后的数值可靠地恢复原始 UMI 计数。

## 实测证据

本次实际读取固定文件、复算 SHA-256、执行预检，并用同一个 `scan_h5ad_values` 函数额外扫描 `X` 与 `layers/raw_count` 的所有数值。结果保存在 [evidence.json](evidence.json)。预检请求只选择 `raw_count`；`X` 的统计是额外只读审计，不是该预检 CLI 自动输出的字段。

| 项目 | 实测结果 |
|---|---|
| 文件大小 | 66,291,080 bytes |
| SHA-256 | `518e62dc7207fe4ccae29c6cfeffada3f77bd58bd12effc8144abe1aadb28867` |
| 维度 | 2671 个细胞 × 1999 个基因；细胞和基因 ID 唯一 |
| 目标基因 | `Gata1` 存在 |
| 每个矩阵扫描范围 | 全部 5,339,329 个值；dense float32 |
| `X` | 4,152,571 个负数；5,339,329 个非整数；无非有限值 |
| `layers/raw_count` | 0 个负数；1,327,057 个非整数；无非有限值；最大值 306.5843811035156 |
| 案例检查 | `case_check_status=completed` |
| 输入契约 | `input_contract_passed=false`；预检 `blocked`，退出码 `2` |
| 模型与验证 | `model_status=not_run`；`independent_validation=not_assessed` |

本文件只包含 1999 个基因，不能凭其来自官方教程就声明它是完整转录组。数值检查也不能独立证明原始处理流程、物种、计数来源或生物学有效性。当前 Geneformer 示例要求的人类完整原始计数输入同样不能由这个小鼠教程文件替代。

## 这次审计之后怎么做

若要继续当前从原始计数开始的 CellOracle 流程，应获取并核查原研究的计数矩阵及元数据，再按所选版本的官方方法准备表达数据、匹配的小鼠调控先验与网络拟合。另一条路线是单独适配 CellOracle 官方预处理 Oracle/Links 对象教程，并固定对象、包和依赖版本；它需要不同的输入契约，不能因文件名相似就混用。

本案例未运行以上任一路线，没有输出 Gata1 KO 预测，也没有用真实 Gata1 扰动标签做准确性评估。观察性造血数据上的模拟教程不能直接当作独立干预验证。

## 来源、引用与许可

- [官方 Gata1 模拟教程](https://morris-lab.github.io/CellOracle.documentation/notebooks/05_simulation/Gata1_KO_simulation_with_Paul_etal_2015_data.html)：在 Paul2015 造血数据的预处理 Oracle 对象上拟合网络并模拟 Gata1。
- [固定版本数据文件](https://raw.githubusercontent.com/morris-lab/CellOracle/7948870a3b70f7d228e54734e1fa9ed3291fc23b/celloracle/data/anndata/Paul_etal_v202204.h5ad)与[加载函数](https://github.com/morris-lab/CellOracle/blob/7948870a3b70f7d228e54734e1fa9ed3291fc23b/celloracle/data/load_data.py)：本案例核验的提交为 `7948870a3b70f7d228e54734e1fa9ed3291fc23b`。
- 原研究：Paul F 等，*Transcriptional Heterogeneity and Lineage Commitment in Myeloid Progenitors*，Cell 163, 1663–1677 (2015)。[PubMed PMID 26627738](https://pubmed.ncbi.nlm.nih.gov/26627738/)；[GEO GSE72857](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE72857)。
- [CellOracle 软件许可](https://github.com/morris-lab/CellOracle/blob/7948870a3b70f7d228e54734e1fa9ed3291fc23b/LICENSE)是带附加限制的 Apache 2.0，仅限非商业学术用途；其他用途需联系作者。不能将其标为无限制 Apache-2.0。
- Paul 原始矩阵和打包教程数据的单独再分发许可未核实，记为 **unknown**。本案例保留官方下载指针，不在仓库中打包数据文件，也不以本项目的许可替代上游许可。
