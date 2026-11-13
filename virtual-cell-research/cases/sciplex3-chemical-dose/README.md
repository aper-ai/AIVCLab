# sci-Plex3：细胞背景、剂量和重复孔的化学响应

Homo sapiens; A549/K562/MCF7; GSE139944 GSM4150378; 188 compounds; 24 h

**阶段：已收录来源；模型未运行，独立验证未完成。**

## 本例要完成的工作

- cell-line x compound x dose x replicate condition table
- coverage and matched-vehicle QC
- dose response plots on documented source scale

## 输入与获取

本页命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先查看完整记录：

```bash
python scripts/cases.py show sciplex3-chemical-dose
```

`cases.py` 的目录查看和资源获取只使用 Python 标准库。后续需要读取 H5AD 或执行数据教学时，按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 使用独立 Python 3.12 环境，并在 Skill 根目录安装 [requirements-data.txt](../../requirements-data.txt)。模型环境与权重另行准备。

按需选择一个资源，使用 `fetch` 下载到 Skill 根目录下新的 `local-runs/` 子目录；默认限额为 64 MiB，不会批量获取整个数据集。`--output-dir` 的相对路径按当前 Skill 根目录解析；缺少的父目录会自动创建，已存在的最终目录仍会被拒绝。

| 资源 ID | 文件 | 大小（bytes） |
| --- | --- | --- |
| `umi_matrix` | `GSM4150378_sciPlex3_A549_MCF7_K562_screen_UMI.count.matrix.gz` | 3096224606 |
| `genes` | `GSM4150378_sciPlex3_A549_MCF7_K562_screen_gene.annotations.txt.gz` | 806168 |
| `metadata` | `GSM4150378_sciPlex3_pData.txt.gz` | 84673357 |
| `processed_h5ad` | `Sci_Plex.h5ad` | 333082088 |

文件 URL、许可状态、已知哈希或发布者校验和记录在 [案例目录](../catalog.json)。数据许可按具体资源记录，不能由本项目代码许可推定。未知 SHA256 的下载只记录本次哈希。

## 准备流程与限制

- 来源与资源元数据已核实，矩阵尚未下载或切片。
- 原矩阵约3.10GB，元数据约84.7MB；处理后H5AD约333MB，需显式提高下载限额。
- 剂量10/100/1000/10000 nM、24h、重复孔须保留，不当成临床剂量；先核对对照标识。
- PRnet/chemCPA常用相关数据，使用固定权重前排查训练重叠，不能自动称独立验证。
- 原始GEO文件和Zenodo处理文件的尺度、行列轴与许可分别核对。

**本例的矩阵准备脚本和模型复现尚未完成。** 贡献时请补上实际命令、筛选/映射统计、输入输出哈希与报告，再按证据更新阶段；不能只添加一张图就标记为已复现。

## 原始来源

- [GEO series](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE139944)
- [Author repository](https://github.com/cole-trapnell-lab/sci-plex)
- [Original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC7289078/)
- [Processed PRnet archive](https://zenodo.org/records/14230870)
