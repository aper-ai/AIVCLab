# Norman K562：单基因和双基因 CRISPRa

Homo sapiens; K562; GSE133344; SunTag CRISPRa

**阶段：已收录来源；模型未运行，独立验证未完成。**

## 本例要完成的工作

- cell/guide/target/control mapping with exclusions
- separate single and joint activation conditions
- held-out perturbation split manifest

## 输入与获取

本页命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先查看完整记录：

```bash
python scripts/cases.py show norman2019-k562-crispra
```

`cases.py` 的目录查看和资源获取只使用 Python 标准库。后续需要读取 H5AD 或执行数据教学时，按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 使用独立 Python 3.12 环境，并在 Skill 根目录安装 [requirements-data.txt](../../requirements-data.txt)。模型环境与权重另行准备。

按需选择一个资源，使用 `fetch` 下载到 Skill 根目录下新的 `local-runs/` 子目录；默认限额为 64 MiB，不会批量获取整个数据集。`--output-dir` 的相对路径按当前 Skill 根目录解析；缺少的父目录会自动创建，已存在的最终目录仍会被拒绝。

| 资源 ID | 文件 | 大小（bytes） |
| --- | --- | --- |
| `filtered_matrix` | `GSE133344_filtered_matrix.mtx.gz` | 未核实；见来源 |
| `barcodes` | `GSE133344_filtered_barcodes.tsv.gz` | 未核实；见来源 |
| `genes` | `GSE133344_filtered_genes.tsv.gz` | 未核实；见来源 |
| `identities` | `GSE133344_filtered_cell_identities.csv.gz` | 1956905 |

文件 URL、许可状态、已知哈希或发布者校验和记录在 [案例目录](../catalog.json)。数据许可按具体资源记录，不能由本项目代码许可推定。未知 SHA256 的下载只记录本次哈希。

## 准备流程与限制

- 真实过表达/激活实验，不是完全基因敲除；尚未下载表达矩阵或制作小切片。
- guide 字符串出现 NegCtrl 不保证是纯对照，必须使用完整 guide→target 映射。
- 样本协议字段含与论文不一致的 dCas9-KRAB 描述，保留来源冲突并按原论文/作者流程核实 CRISPRa。
- 按目标/组合预先留出，不能只随机划分细胞；lane/gemgroup 不自动等于独立生物学重复。
- 数据是常见模型训练/评估材料，checkpoint 训练重叠未知；GEO 数据专用许可未核实。

**本例的矩阵准备脚本和模型复现尚未完成。** 贡献时请补上实际命令、筛选/映射统计、输入输出哈希与报告，再按证据更新阶段；不能只添加一张图就标记为已复现。

## 原始来源

- [GEO series](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE133344)
- [Original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6746554/)
- [Author analysis](https://github.com/thomasmaxwellnorman/Perturbseq_GI)
