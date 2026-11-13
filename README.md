# Aper AI 虚拟细胞工作台

**开发中的虚拟细胞研究框架 · Windows 结果查看器 · Python 插件协议 0.1 草案**

目标是让新手方便完成研究流程，让专业用户复查全部参数与证据，让社区通过独立插件贡献方法。第一阶段围绕转录组数据检查、基因干预、药物响应与验证建立基础。

当前可用的是离线结果查看器，以及新加入的本地 Python 插件 SDK 草案和真实 CSV 基础质控示例。**尚未接入 DSH、持久任务服务或虚拟细胞模型推理。** 科学核心独立运行；结合 DeepSeek Harness 的分层方案和完成条件见 [架构与路线](docs/architecture.md)。

| 当前能力 | 状态 |
| --- | --- |
| 导入 AIVC 运行目录、图表与源表、条件受限的比较、离线报告 | 已实现 |
| 分别显示执行、响应、排名与独立验证状态 | 已实现；上游声明保留来源，不代替独立复核 |
| 本地插件发现、请求校验、显式子进程执行、失败记录 | 协议 0.1 草案；CLI/Python 调用 |
| 细胞 × 基因 CSV 的基础数值检查 | 真实教学插件；不是扰动预测或完整单细胞质控 |
| 新手研究向导、DSH/MCP 桥接、真实模型与远程 GPU | 规划中 |

## 查看和复核已有结果

1. 安装后打开「Aper AI 虚拟细胞工作台」，点击「打开 AIVC 公开样例」开始体验；也可导入带有 `manifest.json` 的现有运行目录。
2. 查看「运行概览」「图表」「源表」和「参数与验证」。图表页可跳转到运行包中已有的图件来源清单；源表页可选择数值列绘图。
3. 在「运行对比」选左右两个结果。先核对细胞背景、基线、基因空间、尺度等上下文。满足来源和质量条件时才计算同表、同名、同单位指标的右减左差值；缺少或冲突的信息会显示原因。
4. 导出单次或对比 HTML 报告。报告包括状态、来源、预览图和可下载的 CSV/CSV.GZ 原件；附件每文件最多 16 MiB、整份报告最多 32 MiB，超限会列明未嵌入的文件。完整产物以运行目录为准。
5. 使用「刷新当前」重读更新后的目录；「关闭当前」移除当前视图；「最近打开」快速重开目录。界面会说明宽表或长表的预览截断，不改变源文件。

查看器在本机读取结果，无需登录或联网，不执行导入目录中的代码。运行插件是独立、显式的开发入口，权限与结果查看器不同。

内置样例取自 [AIVC-Skill 固定版本的历史测试报告](https://github.com/Pengzhi-Gao/aivc-skill/blob/587579e7e004ccfa7079c794d7dd1948caa211f9/examples/lung_cancer/reports/reproduction-report.md#L33-L56)。它们是 CellOracle 同一批次的两个历史条件，未经独立实验或留出数据验证。样例出处、限制与上游许可见 [samples/README.md](samples/README.md)。

## 与 AIVC-Skill 的衔接

| 已有环节 | 当前工作台 |
| --- | --- |
| 运行清单、模型参数、验证与来源记录 | 保留原记录，分别解释各类状态；缺失信息保留为未知 |
| 标准化结果与已生成的图 | 预览 CSV、CSV.GZ 与常见位图；按表选择数值列绘图；读取图件来源清单 |
| 失败记录、原始输出、上游报告 | 读取错误和报告文本，列出原始文件名称，保留原目录 |
| 单次结果交付 | 新增参数差异、受条件约束的汇总差值及离线复核报告 |
| 建环境、运行模型、生成预测与验证 | 模型尚未集成；当前安装包不包含模型权重和推理引擎 |

直接选择运行目录（例如 `results/<run_id>/`），而非它的父目录。可选内容包括 `validation.json`、`provenance.json`、`errors.jsonl`、`raw/`、`tables/`、`figures/` 和 `report.md`。运行包不会被执行或改写。定量汇总表使用表头 `metric,value,unit`，不能拿预览数值当作独立实验结论。需要直接访问未预览的格式，可从「报告与文件」打开原目录。

## 运行源码与第一个插件

推荐 Python 3.12。结果查看器需要 PySide6；构建依赖已固定在 `requirements-build.txt`：

```bash
python -m pip install -r requirements-build.txt
python app.py
```

插件 SDK 和 CSV 示例仅使用 Python 标准库，无需 Qt、GPU、模型权重或大语言模型：

```bash
python -m vcw_core plugins list examples/plugins
```

插件发现只读取声明。显式执行插件的请求示例、命令、输出和边界见 [插件 SDK](docs/plugin-sdk.md)。生成的运行目录可以直接导入当前查看器。

当前执行器使用本机用户权限执行选定插件，不构成安全沙箱；暂不提供第三方插件自动安装、环境管理、断点恢复和长期后台服务。

## 社区如何扩展

科学贡献者主要编写 Python 适配器、能力声明和参考样例。DSH 研究插件负责对话、向导及工具卡片，两者通过同一科学核心衔接。数据检查、模型、评分、质量规则、基准样例和新手教程都可以成为贡献入口。

先阅读 [贡献指南](CONTRIBUTING.md)、[插件 SDK](docs/plugin-sdk.md) 和 [DSH 架构决策](docs/architecture.md)。目前协议仍为草案，欢迎用真实第二个方法检验接口。开源发布前还需由维护者确认项目许可与各类数据、权重的分发范围。

## 构建与验证

使用 Windows x64 Python 3.12、[requirements-build.txt](requirements-build.txt) 中的精确依赖及 Inno Setup 6，运行 `build.ps1`。版本由 `version.py` 统一提供，安装包输出到 `dist/`，安装到当前用户。

构建脚本先执行单元测试和源码 smoke，再验证冻结后的 EXE，记录源码状态、输入文件哈希、环境、安装包校验值和验证结果。CI 另在干净 Windows runner 上验证安装、启动与卸载。这些是构建来源证据，不是二进制可复现性或数字签名声明。

```bash
python -m unittest discover -v
python app.py --smoke-test verification/source-smoke
```

无显示器的 Linux 需设置 `QT_QPA_PLATFORM=offscreen`。未安装 Qt 时 UI 单测会跳过，不能视为 GUI 验证通过。Windows 特有检查需要 Windows 环境。

从安装目录启动 `AperVirtualCellWorkbench.exe --smoke-test <证据目录>`，可重跑公开样例验收并保存截图、HTML 报告和检查结果。
