# AIVC 公开历史结果样例

这两个结果包整理自 AIVC-Skill 同一批次的 CellOracle 0.20.0 示例，分别对应 STAT3 敲除与 JUN 敲除。工作台为两项条件分配了不同结果编号，以便并排查看。两项结果共享 GSE198291 数据集、后端和报告出处。原报告未记录独立的条件运行编号与运行时间。

- `aivc-stat3-ko`：STAT3 敲除历史结果视图。
- `aivc-jun-ko`：JUN 敲除历史结果视图。

`tables/projection_metrics.csv` 的三项指标逐行抄录自原报告第 43–50 行，保留三位小数。单位标为 `embedding units`，指原报告嵌入投影的相对单位。`figures` 中的图为原仓库发布的对应条件图。`manifest.json`、`validation.json` 和 `report.md` 由 Aper AI 为本地阅读整理。工作台比较这两个条件时显示的是同一历史批次中两项投影指标的描述性差值。

原报告的勘误明确说明，历史数值和图片未按修正规则重跑。两个条件均无独立实验或留出数据验证。随机化投影是技术对照，向量差长度描述投影差异。两个样例包提供汇总指标和静态图。

数据编号为 GEO GSE198291。样例归属 AIVC-Skill contributors，随附 [`LICENSE-AIVC.txt`](LICENSE-AIVC.txt)。

[AIVC-Skill 固定版本报告](https://github.com/Pengzhi-Gao/aivc-skill/blob/587579e7e004ccfa7079c794d7dd1948caa211f9/examples/lung_cancer/reports/reproduction-report.md)
