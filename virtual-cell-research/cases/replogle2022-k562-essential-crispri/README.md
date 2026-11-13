# Replogle K562 essential：pseudobulk 与单细胞输入的区别

Homo sapiens; K562 essential; day 6; PRJNA831566 / Figshare 20029387 v1

**阶段：已收录来源；模型未运行，独立验证未完成。**

## 本例要完成的工作

- pseudobulk metadata/control key inspection
- source-scale observed summary
- model-specific held-out design before inference

## 输入与获取

本页命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先查看完整记录：

```bash
python scripts/cases.py show replogle2022-k562-essential-crispri
```

`cases.py` 的目录查看和资源获取只使用 Python 标准库。后续需要读取 H5AD 或执行数据教学时，按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 使用独立 Python 3.12 环境，并在 Skill 根目录安装 [requirements-data.txt](../../requirements-data.txt)。模型环境与权重另行准备。

按需选择一个资源，使用 `fetch` 下载到 Skill 根目录下新的 `local-runs/` 子目录；默认限额为 64 MiB，不会批量获取整个数据集。`--output-dir` 的相对路径按当前 Skill 根目录解析；缺少的父目录会自动创建，已存在的最终目录仍会被拒绝。

| 资源 ID | 文件 | 大小（bytes） |
| --- | --- | --- |
| `raw_pseudobulk` | `K562_essential_raw_bulk_01.h5ad` | 79766954 |
| `raw_singlecell` | `K562_essential_raw_singlecell_01.h5ad` | 10661879995 |
| `raw_file_manifest` | `KD6_raw_files.csv` | 75702 |

文件 URL、许可状态、已知哈希或发布者校验和记录在 [案例目录](../catalog.json)。数据许可按具体资源记录，不能由本项目代码许可推定。未知 SHA256 的下载只记录本次哈希。

## 准备流程与限制

- 尚未下载矩阵；优先79.8MB raw pseudobulk检查，需显式提高默认64MiB限额。
- pseudobulk不是单细胞；normalized版本是gemgroup Z-normalized，不能当raw counts；raw也已筛过表达基因。
- 同一载体两个sgRNA针对一个目标不等于双基因扰动。
- GSE197744是另一项病毒研究，不是本研究accession；正确原始入口为PRJNA831566。
- 特定checkpoint训练重叠未知；完整single-cell约10.66GB，不自动下载。
- MD5为发布者元数据；当前下载工具核对已知SHA256并记录本次SHA256，SHA256未提供时不会宣称来源哈希已验证。

**本例的矩阵准备脚本和模型复现尚未完成。** 贡献时请补上实际命令、筛选/映射统计、输入输出哈希与报告，再按证据更新阶段；不能只添加一张图就标记为已复现。

## 原始来源

- [Original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC9380471/)
- [Original reads](https://www.ncbi.nlm.nih.gov/bioproject/PRJNA831566)
- [Author processed data API](https://api.figshare.com/v2/articles/20029387)
- [Original file map](https://api.figshare.com/v2/articles/20022944)
