# Adamson K562：UPR CRISPRi 与对照标签核查

Homo sapiens; K562; GSE90546 / GSM2406681 UPR subexperiment

**阶段：已收录来源；模型未运行，独立验证未完成。**

## 本例要完成的工作

- UPR-only input manifest
- guide/target/control mapping audit
- perturbation-held-out evaluation plan

## 输入与获取

本页命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先查看完整记录：

```bash
python scripts/cases.py show adamson2016-k562-upr-crispri
```

`cases.py` 的目录查看和资源获取只使用 Python 标准库。后续需要读取 H5AD 或执行数据教学时，按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 使用独立 Python 3.12 环境，并在 Skill 根目录安装 [requirements-data.txt](../../requirements-data.txt)。模型环境与权重另行准备。

按需选择一个资源，使用 `fetch` 下载到 Skill 根目录下新的 `local-runs/` 子目录；默认限额为 64 MiB，不会批量获取整个数据集。`--output-dir` 的相对路径按当前 Skill 根目录解析；缺少的父目录会自动创建，已存在的最终目录仍会被拒绝。

| 资源 ID | 文件 | 大小（bytes） |
| --- | --- | --- |
| `upr_matrix` | `GSM2406681_10X010_matrix.mtx.txt.gz` | 未核实；见来源 |
| `barcodes` | `GSM2406681_10X010_barcodes.tsv.gz` | 未核实；见来源 |
| `genes` | `GSM2406681_10X010_genes.tsv.gz` | 未核实；见来源 |
| `identities` | `GSM2406681_10X010_cell_identities.csv.gz` | 未核实；见来源 |

文件 URL、许可状态、已知哈希或发布者校验和记录在 [案例目录](../catalog.json)。数据许可按具体资源记录，不能由本项目代码许可推定。未知 SHA256 的下载只记录本次哈希。

## 准备流程与限制

- CRISPRi 是抑制/敲低，不应自动写成完全KO。
- 只选UPR子实验，不混合Pilot TF与UPR epistasis；矩阵和完整标签未在本次下载核验。
- 先重建原始guide/control映射；已发表评估指出旧处理包有标签问题，本项目尚未复现其全部数量。
- GEO专用数据许可未核实；模型训练重叠及独立留出条件尚未核对。

**本例的矩阵准备脚本和模型复现尚未完成。** 贡献时请补上实际命令、筛选/映射统计、输入输出哈希与报告，再按证据更新阶段；不能只添加一张图就标记为已复现。

## 原始来源

- [GEO series](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE90546)
- [UPR sample](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM2406681)
- [Original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC5315571/)
- [Published processed-label audit](https://academic.oup.com/bioinformatics/article/41/6/btaf317/8142305)
