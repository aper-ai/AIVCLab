# Kang PBMC：按供者和细胞类型比较 IFN-beta 响应

Homo sapiens; PBMC; GSE96583 batch 2; 8 donors; 6 h IFN-beta versus control

**阶段：已收录来源；模型未运行，独立验证未完成。**

## 本例要完成的工作

- matrix/barcode/metadata alignment record
- donor x cell-type x condition summary
- observed response report with donor-aware design

## 输入与获取

本页命令统一在包含 `SKILL.md` 的 `virtual-cell-research/` **Skill 根目录**运行，不在外层工作台仓库根目录或本案例子目录运行。先查看完整记录：

```bash
python scripts/cases.py show kang-ifnb-pbmc
```

`cases.py` 的目录查看和资源获取只使用 Python 标准库。后续需要读取 H5AD 或执行数据教学时，按 [数据环境说明](../../references/first-run.md#建立数据教学环境) 使用独立 Python 3.12 环境，并在 Skill 根目录安装 [requirements-data.txt](../../requirements-data.txt)。模型环境与权重另行准备。

按需选择一个资源，使用 `fetch` 下载到 Skill 根目录下新的 `local-runs/` 子目录；默认限额为 64 MiB，不会批量获取整个数据集。`--output-dir` 的相对路径按当前 Skill 根目录解析；缺少的父目录会自动创建，已存在的最终目录仍会被拒绝。

| 资源 ID | 文件 | 大小（bytes） |
| --- | --- | --- |
| `control_matrix` | `GSM2560248_2.1.mtx.gz` | 28545918 |
| `stimulated_matrix` | `GSM2560249_2.2.mtx.gz` | 29050932 |
| `genes` | `GSE96583_batch2.genes.tsv.gz` | 277054 |
| `metadata` | `GSE96583_batch2.total.tsne.df.tsv.gz` | 756342 |
| `control_barcodes` | `GSM2560248_barcodes.tsv.gz` | 未核实；见来源 |
| `stimulated_barcodes` | `GSM2560249_barcodes.tsv.gz` | 未核实；见来源 |

文件 URL、许可状态、已知哈希或发布者校验和记录在 [案例目录](../catalog.json)。数据许可按具体资源记录，不能由本项目代码许可推定。未知 SHA256 的下载只记录本次哈希。

## 准备流程与限制

- 只下载并读取基因和细胞元数据；两份表达矩阵尚未下载。
- 元数据 29065 条，其中 24679 singlet；预处理不能把双细胞或未分配供者当独立重复。
- 这是 cytokine 刺激，不是基因 KO/OE 或药物敏感性实验；按供者保留配对，细胞不等于独立生物学重复。
- 矩阵、barcode、metadata 需按完整稳定标识对齐；批次/供者拆分与任何模型训练重叠尚未核对。
- GEO 文件未核实独立数据许可；其他存档的 CC-BY 不自动覆盖所有衍生文件。

**本例的矩阵准备脚本和模型复现尚未完成。** 贡献时请补上实际命令、筛选/映射统计、输入输出哈希与报告，再按证据更新阶段；不能只添加一张图就标记为已复现。

## 原始来源

- [GEO GSE96583](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583)
- [Original paper](https://www.nature.com/articles/nbt.4042)
- [CC-BY derivative (different file)](https://zenodo.org/records/10069528)
