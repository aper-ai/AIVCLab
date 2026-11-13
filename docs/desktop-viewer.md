# Windows 结果查看器

本页记录已有 0.1.0 查看器的使用与构建。当前科研分析主入口见 [Virtual Cell Research](../virtual-cell-research/README.md)。


**0.1.0 · Windows x64 预览版**

已有「Aper AI 虚拟细胞工作台」用于读取带 `manifest.json` 的模型运行包，把图、表、参数和来源整理为复核记录。它在本机运行，无需登录或上传数据。观测教学的输出是独立的数据报告，当前没有模型运行包的 `manifest.json`，请直接阅读生成的 `report.md`、表格和图。Skill 的使用不依赖此查看器。

### 使用查看器

1. 安装后打开「Aper AI 虚拟细胞工作台」，点击「打开 AIVC 公开样例」开始体验；也可导入带有 `manifest.json` 的现有运行目录。
2. 查看「运行概览」「图表」「源表」和「参数与验证」。图表页可跳转到运行包中已有的图件来源清单；源表页可选择数值列绘图。
3. 在「运行对比」选左右两个结果。先查看上下文是否一致，再核对参数、状态和汇总指标。汇总差值仅针对声明一致的上下文及同表、同名、同单位的合规指标，计算方向为右减左。
4. 点击右上角导出单次或对比 HTML 报告。报告自带预览图及来源链接，可以离线打开或从浏览器打印。表格和图件预览有大小及数量限制，完整原件以导入目录为准。

内置样例取自 [AIVC-Skill 固定版本的历史测试报告](https://github.com/Pengzhi-Gao/aivc-skill/blob/587579e7e004ccfa7079c794d7dd1948caa211f9/examples/lung_cancer/reports/reproduction-report.md#L33-L56)。它们是 CellOracle 同一批次的两个历史条件，未经独立实验或留出数据验证。样例出处、限制与上游许可见 [samples/README.md](../samples/README.md)。

### 模型运行包与查看器的衔接

| 已有环节 | 工作台 0.1.0 |
| --- | --- |
| 运行清单、模型参数、验证与来源记录 | 导入原记录，独立显示运行和验证状态；缺失信息保留为未知 |
| 标准化结果与已生成的图 | 预览 CSV、CSV.GZ 与常见位图；按表选择数值列绘图；读取图件来源清单 |
| 失败记录、原始输出、上游报告 | 读取错误和报告文本，列出原始文件名称，保留原目录 |
| 单次结果交付 | 新增参数差异、受条件约束的汇总差值及离线复核报告 |
| 建环境、提交任务、运行模型、生成预测与验证 | 继续由独立运行环境承担；这个安装包不包含模型权重和推理引擎 |

直接选择运行目录（例如 `results/<run_id>/`），而非它的父目录。可选内容包括 `validation.json`、`provenance.json`、`errors.jsonl`、`raw/`、`tables/`、`figures/` 和 `report.md`。运行包不会被执行或改写。定量汇总表使用表头 `metric,value,unit`，不能拿预览数值当作独立实验结论。需要直接访问未预览的格式，可从「报告与文件」打开原目录。

### 构建与验证查看器

使用 Windows x64 Python 3.12、[requirements-build.txt](../requirements-build.txt) 中的依赖及 Inno Setup 6，运行 `build.ps1`。脚本生成 `dist/AperAI-VirtualCell-Workbench-Setup-0.1.0-x64.exe`，仅安装到当前用户，无需管理员权限。

从安装目录启动 `AperVirtualCellWorkbench.exe --smoke-test <证据目录>`，可重跑公开样例验收并保存截图、HTML 报告和检查结果。
