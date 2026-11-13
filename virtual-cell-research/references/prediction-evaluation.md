# 预测结果怎样评估

用 `scripts/evaluate_predictions.py` 比较已有预测与实测响应，检查基因和样本对应关系、输入尺度、简单参照与生物学重复。它读取文件并生成评估报告，不启动模型或改写已有结果。

## 先分清三件事

1. **模型是否运行成功**：由原运行记录说明。
2. **当前预测表现如何**：在同一组样本、基因和尺度上，与零响应等参照比较误差和相关。
3. **评估是否独立**：需要核实实际训练、调参、特征选择、预处理与评估数据之间的关系。仅凭一个 `test` 标签或用户填写的训练成员表不能证明科学独立性。

本工具始终保留 `independent_validation: not_assessed`。成员表通过只记为 `passed_recorded_membership`，表示所提供的记录中没有检测到样本或生物学单位跨训练/评估集合。它没有审计实际模型训练，也不能排除未记录的预训练重叠。

## 准备三个表与一份设置

在[数据教学环境](first-run.md#建立数据教学环境)执行。观测和预测矩阵使用 CSV/TSV，均可 gzip 压缩。**第一列必须叫 `sample_id`，其余列必须为唯一基因 ID。** 允许行列顺序不同；程序按 ID 重排。两表的样本和基因集合必须完全相同，不默默求交集、删缺失项或补零。

例如 `observed.csv`：

```csv
sample_id,ENSG_A,ENSG_B,ENSG_C
donor1,1.2,0,-0.5
donor2,0.8,0.2,-0.3
```

`predicted.csv` 使用同样的 ID 和声明尺度。所有数值必须有限，空白、缺失、NaN/Inf 和重复 ID 均会停止计算；`NA` 等字符串不会被当作可自动填补的数值。

`metadata.csv` 至少包含 `sample_id,unit_id`：

```csv
sample_id,unit_id,fold_id
donor1,donor1,fold1
donor2,donor2,fold2
```

`unit_id` 是研究设计中的生物学单位，例如供体。多细胞或多次条件记录来自同一供体时，应使用相同的单位 ID。不要把细胞或模型随机抽样各自写成独立供体。程序先计算逐样本指标、在单位内平均，最后对单位等权汇总。不同条件在单位内的平均权重相等，用户仍须判断该汇总是否符合研究问题；可按预先确定的条件分别评估。

`settings.json`：

```json
{
  "schema_version": 1,
  "input_kind": "response",
  "observed": {
    "scale": "log2(1+CPM)_stim_minus_control",
    "context": "human PBMC; CD14+; IFN-beta 6h"
  },
  "predicted": {
    "scale": "log2(1+CPM)_stim_minus_control",
    "context": "human PBMC; CD14+; IFN-beta 6h"
  },
  "unit_definition": "donor with a paired stimulated/control response"
}
```

观测、预测声明的 `scale` 和 `context` 必须完全一致。程序核对声明的一致性，不根据数值外观推断真实预处理或认证背景。

运行。下面使用 Bash 多行写法；Windows PowerShell 中可合并为一行执行，去掉行末反斜杠：

```bash
python scripts/evaluate_predictions.py \
  --observed observed.csv --predicted predicted.csv \
  --metadata metadata.csv --settings settings.json \
  --output-dir local-runs/evaluation-001
```

输出目录必须新建。命令失败时退出码为 2；若已创建本次目录，会保留 `error.json`。既有目录不会被覆盖。单个输入文件限 256 MiB，单个矩阵限 5,000,000 个数值；更大的分析需预先按研究问题准备有明确记录的子集，本入口不自动抽样。

### 输入的是处理后表达，而不是响应差值

把 `input_kind` 改为 `expression`，在设置中增加与 `observed` 相同尺度和背景的 `baseline` 对象，再提供 `--baseline baseline.csv`。基线矩阵使用同样的 `sample_id` 和基因 ID；每行是该样本明确对应的对照。程序分别计算：

`observed_response = observed_expression - baseline`

`predicted_response = predicted_expression - baseline`

已是差值的 `response` 输入禁止再次传基线，防止重复相减。表达形式缺少基线、基线 ID 不匹配或尺度声明不匹配时停止。这里不自动构造对照、做批次校正或换算尺度。

## 加入训练/评估成员记录

可增加 `--split-membership split_membership.csv`。这时元信息还必须提供 `fold_id`，成员表必须且只能有下列四列：

```csv
fold_id,role,sample_id,unit_id
fold1,train,donor2,donor2
fold1,evaluation,donor1,donor1
fold2,train,donor1,donor1
fold2,evaluation,donor2,donor2
```

`role` 只允许 `train` 和 `evaluation`。每折必须有两种成员，评估成员必须与实际评估样本相符，同一样本的单位身份不能变化。同一折出现相同样本或生物学单位跨训练/评估集合时阻断计算。

多折之间共用训练样本是交叉验证的一般情况，但不能因此把折当作独立实验。药物、细胞系、供体、批次等其他潜在泄漏维度，需要根据研究问题另外核实；当前 `unit_id` 只审计显式选择的一个分组维度。与训练关系未知的预训练权重组合时，仍保留未知状态。

可先运行[真实 Kang 留一供体基线教学](../cases/kang-heldout-baseline/README.md)，查看程序实际保存的成员、拟合记录与完整评估。

## 结果应该怎么看

首先打开 `report.md`，然后查看：

| 产物 | 用途 |
| --- | --- |
| `evaluation.json` | 完整方法、单位等权指标、成员审计和解释边界 |
| `tables/profile_metrics.csv` | 每个样本的预测与零响应 RMSE、MAE、Pearson、方向一致率 |
| `tables/unit_metrics.csv` | 单位内平均值、样本数量和可计算相关系数的数量 |
| `raw/aligned_responses.npz` | 已对齐的输入、基线、响应及全部轴 ID；以 `allow_pickle=False` 读取 |
| `tables/evaluation_metadata.csv`、`gene_index.csv` | 本次实际评估的样本、单位、折和基因 |
| `qc.json`、`provenance.json` | 检查范围、输入/源码/结果哈希、解释器与命令 |

RMSE 与 MAE 越低越好；响应相关描述方向和形状的一致性，不替代幅度误差。零响应参照预测“处理后维持对照”，其响应恒为零，所以 Pearson 未定义，CSV 中为空、JSON 中为 `null`，不能填成 0。

**单位等权平均 RMSE 与把所有数值合并后计算的 RMSE 不同。** 报告使用前者，避免细胞或条件数多的供体自动主导汇总。方向一致率只在实测非零的基因上计算，预测为零时判为方向未匹配；这里的零是数值零，不是生物学显著性阈值。

低表达、共零基因及条件构成会影响全基因指标。预先确定的响应基因集可以另做评估，但不能看完测试答案再选择“最好预测”的基因，并把筛选后的分数当作无偏结果。本入口不计算显著性、置信区间或临床疗效结论。
