# 科研插件 SDK：协议 0.1 草案

本模块提供一个可运行的扩展起点：**第三方添加插件目录即可被发现、校验和显式执行，不需要修改工作台主程序或中央注册表。** 它使用 Python 标准库，不依赖 Qt、DSH、MCP、LLM API 或外部网络。

这是工程接口草案，尚不是稳定的科研数据标准。当前覆盖声明式发现、请求结构、一次性子进程执行、失败记录和 CSV/Markdown 产物；没有实现通用工作流编排、模型训练、远程安装、插件市场或模型环境自动部署。桌面预览版尚未自动调用插件 runner。

## 1. 五分钟运行真实示例

从仓库根目录，在 Python 3.10 或更新版本的环境中执行：

```bash
python -m vcw_core plugins list examples/plugins
```

发现过程只读取 `plugin.json` 并检查声明路径，**不会 import 或执行插件 Python 文件**。

生成一份指向随附 CSV 的请求。以下命令可在 PowerShell、cmd 或常见 Unix shell 中运行：

```bash
python -c "import json,pathlib; p=pathlib.Path('examples/plugins/csv_qc/example-input.csv').resolve(); pathlib.Path('qc-request.json').write_text(json.dumps({'input_csv':str(p),'input_scale':'raw_counts'},ensure_ascii=False),encoding='utf-8')"
python -m vcw_core run --plugin examples/plugins/csv_qc --request qc-request.json --output local-runs
```

CLI 返回 UTF-8 JSON，包含 `run_dir`、`status` 和 `error`。成功的退出码为 `0`，执行或产物校验失败为 `1`，配置或请求错误为 `2`。

示例的真实输入有 3 个细胞、3 个基因，表达总量为 12，9 个矩阵元素中有 4 个非零值，另有 1 个全零细胞。可用以下文件核对：

- `tables/qc_metrics.csv`：细胞数、基因数、表达总量和非零比例。
- `tables/gene_detection.csv`：每个基因的非零细胞数及比例。
- `report.md`：输入哈希、用户声明的数据尺度和分析边界。

将 CLI 返回的 `run_dir` 通过桌面客户端“导入运行目录”打开，即可查看真实输出。`load_run(run_dir)` 也可以读取该目录。

**CSV QC 是教学插件，不是基因干预或药物预测。** 它不判断细胞是否合格、不做归一化，也不替代细胞类型、线粒体比例、双细胞、供体与批次层面的专业检查。原始计数、归一化值及 log 变换值必须由使用者明确声明；本例不会根据数据外观自动推断。

## 2. 插件目录与声明

每个插件目录至少包含 `plugin.json` 和一个 Python 入口文件。入口可以使用同目录的辅助模块，或给定 Python 环境中安装的依赖。根目录下放多个这样的插件目录即可共同发现。

最小声明：

```json
{
  "api_version": "0.1",
  "id": "lab.example",
  "version": "0.1.0",
  "kind": "data_qc",
  "description": "明确说明该插件的实际能力和边界",
  "input_schema": {
    "type": "object",
    "properties": {
      "input_csv": {"type": "string", "minLength": 1}
    },
    "required": ["input_csv"],
    "additionalProperties": false
  },
  "output_types": ["table", "report"],
  "entrypoint": "entrypoint.py"
}
```

`id` 使用 1–64 个小写字母、数字、点、连字符或下划线，并以字母开始。同次发现出现重复 ID 会整体报错，不静默覆盖。`version` 使用 `major.minor.patch`，可附预发布后缀；`api_version` 当前必须严格等于 `0.1`。

`kind` 当前接受 `data_qc`、`analysis`、`prediction`、`visualization`。这个字段是插件作者的能力声明，不代表核心已经验证了该能力。

`entrypoint` 必须指向插件目录中的 `.py` 普通文件；路径使用 `/`，不能包含 `..`、绝对路径、符号链接跳转或 Windows 盘符。

### 请求 schema 是有界子集

当前支持：

- `type`：`object`、`array`、`string`、`number`、`integer`、`boolean`、`null`。
- 对象：`properties`、`required`，并要求 `additionalProperties: false`。
- 数组：`items`、`minItems`、`maxItems`。
- 字符串：`minLength`、`maxLength`。
- 数值：`minimum`、`maximum`。
- 通用：`description`、`enum`。

未知关键字、`$ref`、联合类型和未实现的 JSON Schema 功能会被拒绝。不会访问远程 schema，也不自动插入默认参数。默认值若由插件使用，插件作者必须在说明中公开，并在结果或日志中记录实际使用值。

输入 JSON 的重复键、非有限数值、未知参数和错误类型会被拒绝；布尔值不会被当作整数。框架只验证结构，物种、表达尺度、基因对应关系和模型适配必须由科研插件进一步验证。

## 3. 显式执行约定

runner 以参数列表启动子进程，形式为：

```text
python -X utf8 -E -s entrypoint.py --request /absolute/request.json --output /absolute/run/_work
```

没有通过 shell 拼接用户输入。每次执行创建全新 UUID 结果目录；插件应读取请求，在指定 `_work` 中写结果，再生成 `result.json`，最后以 `0` 退出。绝对输入路径由请求提供，不能依赖调用者的当前目录。

可以明确指定已准备好的隔离环境：

```bash
python -m vcw_core run --plugin path/to/plugin --request request.json --output local-runs --python path/to/environment/python --timeout 120
```

不同模型可以使用不同解释器及依赖环境。SDK 不负责创建环境、下载权重或解决依赖冲突。若将来由打包桌面程序调用 API，必须给出独立 Python 解释器，不能把冻结后的应用可执行文件误当作 Python。

## 4. 产物契约

示例 `result.json`：

```json
{
  "api_version": "0.1",
  "summary": "仅说明实际完成的工作",
  "artifacts": [
    {"type": "table", "path": "tables/qc_metrics.csv"},
    {"type": "report", "path": "report.md"}
  ]
}
```

当前版本只接受：

- `table`：位于 `tables/` 下的 UTF-8 `.csv`，有非空表头，各行列数一致。
- `report`：UTF-8 `report.md`。

所有路径相对于本次 `_work` 目录，必须是声明范围内的普通文件。绝对路径、父目录逃逸、符号链接、重复路径或未声明的类型会导致运行失败。`result.json` 内文本不会作为代码执行。

核心在进程正常退出后继续验证产物结构和大小；全部通过才复制到正式结果目录。核心生成查看器兼容的 `manifest.json`、`validation.json`、`provenance.json`、`events.jsonl` 和日志，并记录已接受文件的 SHA-256。

这套结构证明通用扩展机制可以工作；将来处理 `.h5ad`、稀疏矩阵、基因轴和扰动条件 ID，需要另外定义并评审科学产物契约，不能把任意 CSV 都宣称为标准预测输出。

## 5. 状态、证据与失败

运行事件为 `before → running → succeeded` 或 `before → running → failed`。每次状态更新都原子替换清单，并追加事件记录。

`succeeded` 仅表示进程正常退出且产物通过结构检查。兼容查看器的 `execution_status` 会标记为 `result_available`，独立验证始终为 `independent_validation: unvalidated`。CSV QC 示例的响应与排名状态为 `not_applicable`，其他插件默认 `unknown`；核心不会替插件臆造模型质量或实验验证。

非零退出、超时、日志超限、缺失 `result.json`、无效 CSV 或越界产物均会标记 `failed`。即使插件已经写出部分文件，也不会因此标记成功。诊断内容保留在 `_work/`、`logs/` 和 `errors.jsonl`；失败报告会说明部分输出仅供排查。

溯源记录当前包含插件声明、入口脚本和请求的哈希，以及所选解释器路径。**它尚不能完整锁定全部辅助源码、依赖包、模型权重或硬件环境。** 科研模型插件应进一步保存这些内容及随机种子；不要把最小 SDK 的追踪字段当成已经实现完整可重复性。

## 6. 资源范围与执行权限

| 项目 | 当前上限 |
|---|---|
| 插件声明与请求 | 各 64 KiB |
| 入口脚本、`result.json` | 各 1 MiB |
| 同次发现 | 64 个插件；目录枚举最多 1,024 项 |
| 请求 schema | 最深 8 层；对象最多 64 个属性 |
| 日志 | stdout、stderr 各 1 MiB，超限失败 |
| 执行时间 | 默认 60 秒；调用者可设至 3,600 秒 |
| 产物 | 1–32 个；CSV 至多 16 MiB，Markdown 至多 1 MiB，总计至多 64 MiB，与查看器读取范围对齐 |
| CSV 产物结构检查 | 至多 1,000,000 行和 16,384 列，并受文件大小限制 |
| CSV QC 示例输入 | 64 MiB、100,000 个细胞、20,000 个基因、2,000,000 个表达数值 |

CSV QC 对表达数值使用有界十进制计算，避免大整数计数被二进制浮点静默舍入。单值最多 50 位有效数位、十进制指数在 −100 到 100 之间，超过范围会明确失败；比例以有限小数输出。当前是数值检查示例的资源范围，不是生物学有效性判据。

**插件与当前用户具有相同权限，这不是安全沙箱。** 只显式运行你信任的插件。资源检查控制 SDK 接受的产物和日志，不是文件系统、内存、CPU 或网络隔离；恶意插件仍可能访问其他文件、运行进程或发起网络请求。核心本身和随附 CSV 示例不使用网络。

插件必须在返回前结束自己的后台进程并关闭 stdout/stderr；本草案只支持遵守这一约定的合作插件。检测到后代持续占用日志管道时，运行会失败。

超时清理：POSIX 使用进程组终止；Windows 在主进程仍运行时使用本次 PID 的 `taskkill /T /F`，必要时终止主进程。**Windows 上主进程已经退出而后代仍持有日志管道时，本实现不能保证清理后代进程**；尚未实现 Windows Job Object 生命周期管理。不要把 daemon 日志线程或超时机制理解为完整的进程树隔离。Windows 行为需要由对应平台 CI 持续验证。

## 7. 共建与未来 DSH/MCP 接口

第三方贡献一个插件时，至少提交声明、入口、一个小型输入示例、可核算的期望输出、错误样例和方法适用范围。模型作者还应提供环境锁定、权重来源与许可、基因/细胞/扰动适配规则和独立验证方案。

未来 DSH、MCP、GUI 或其他 agent 可以共同调用：

```python
from vcw_core import discover_plugins, run_plugin

available = discover_plugins("examples/plugins")
result = run_plugin(
    "examples/plugins/csv_qc",
    {"input_csv": "/absolute/expression.csv", "input_scale": "raw_counts"},
    "local-runs",
    python_executable="/absolute/venv/bin/python",
    timeout=120,
)
```

这些入口复用同一套请求校验和执行记录；不需要 DSH 才能运行科学插件。**当前提交没有实现 DSH 的专用桥接，也没有接入真实干预模型。** 先用这套可执行最小契约开展社区评审，再决定稳定的版本管理、能力元数据与科研结果协议。

运行独立回归：

```bash
python -m unittest -v test_plugin_sdk
```
