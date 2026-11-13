"""Read local result bundles and export static reports without executing bundle files."""

from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import html
import io
import json
import math
import os
import re
import tempfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


MAX_METADATA_BYTES = 1024 * 1024
MAX_TABLE_BYTES = 16 * 1024 * 1024
MAX_FIGURE_BYTES = 8 * 1024 * 1024
MAX_COLUMNS = 512
MAX_SOURCE_COLUMNS = 100_000
MAX_ASSETS = 1000
MAX_ASSET_DEPTH = 8
MAX_PREVIEW_ROWS = 10_000
MAX_METRIC_BYTES = 256 * 1024
MAX_METRIC_TABLES = 12
MAX_METRIC_ROWS = 1000
MAX_REPORT_TABLE_BYTES = 32 * 1024 * 1024
FIGURE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}
MISSING = object()


class RunDataError(ValueError):
    """An invalid, unsafe, or unreadable result bundle or output path."""


@dataclass(frozen=True)
class RunData:
    root: Path
    run_id: str
    backend: str
    task: str
    dataset: str
    source_url: str
    notes: str
    manifest: dict[str, Any]
    validation: dict[str, Any]
    provenance: dict[str, Any]
    parameters: dict[str, Any]
    tables: tuple[Path, ...]
    figures: tuple[Path, ...]
    report: str
    errors_text: str
    raw_files: tuple[Path, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TablePreview:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    truncated: bool
    total_columns: int = 0
    columns_truncated: bool = False


@dataclass(frozen=True)
class ReviewStatus:
    """Separate upstream declarations; reading a bundle never validates its science."""

    execution_status: str
    response_status: str
    ranking_status: str
    independent_validation: str
    notes: tuple[str, ...]
    sources: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ComparisonRow:
    field: str
    left: str
    right: str
    changed: bool


@dataclass(frozen=True)
class MetricComparison:
    name: str
    left: Decimal
    right: Decimal
    delta: Decimal
    unit: str
    table: str


@dataclass(frozen=True)
class RunComparison:
    compatible: bool
    reasons: tuple[str, ...]
    rows: tuple[ComparisonRow, ...]
    metrics: tuple[MetricComparison, ...]
    metric_notes: tuple[str, ...]


def resolve_asset(root: Path | str, path: Path | str) -> Path:
    """Resolve a regular file, requiring it to stay within the imported directory."""
    base = Path(root).absolute()
    path = Path(path)
    if not path.is_absolute():
        path = base / path
    try:
        resolved = path.resolve(strict=True)
        contained = base.resolve(strict=True) == base and resolved.is_relative_to(base)
        if not contained or not resolved.is_file():
            raise RunDataError(f"无法访问运行目录内的文件 {path.name}。")
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, RunDataError):
            raise
        raise RunDataError(f"无法读取运行文件 {path.name}。") from exc
    return resolved


def _read_bounded(path: Path, maximum: int, *, compressed: bool = False) -> bytes:
    try:
        if not path.is_file():
            raise RunDataError(f"{path.name} 不是可读取的普通文件。")
        if path.stat().st_size > maximum:
            raise RunDataError(f"{path.name} 超过 {maximum // 1024} KiB 大小限制。")
        with path.open("rb") as source:
            if compressed:
                with gzip.GzipFile(fileobj=source) as archive:
                    data = archive.read(maximum + 1)
            else:
                data = source.read(maximum + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise RunDataError(f"无法读取 {path.name}，请检查文件权限及格式。") from exc
    if len(data) > maximum:
        detail = "解压后" if compressed else ""
        raise RunDataError(f"{path.name} {detail}超过 {maximum // 1024} KiB 大小限制。")
    return data


def _read_text(path: Path, maximum: int = MAX_METADATA_BYTES, *, compressed: bool = False) -> str:
    try:
        return _read_bounded(path, maximum, compressed=compressed).decode("utf-8-sig")
    except UnicodeError as exc:
        raise RunDataError(f"{path.name} 无法按 UTF-8 读取。") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"重复字段 {key!r}")
        obj[key] = value
    return obj


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("数值超出可读取范围")
    return number


def _read_object(root: Path, name: str) -> dict[str, Any]:
    path = resolve_asset(root, name)
    try:
        data = json.loads(
            _read_text(path),
            object_pairs_hook=_unique_object,
            parse_float=_finite_float,
            parse_constant=_finite_float,
        )
        # JSON escape sequences can represent lone surrogates despite UTF-8 input.
        json.dumps(data, ensure_ascii=False).encode("utf-8")
        pending = [(data, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 48:
                raise ValueError("JSON 结构超过 48 层")
            if isinstance(item, dict):
                pending.extend((value, depth + 1) for value in item.values())
            elif isinstance(item, list):
                pending.extend((value, depth + 1) for value in item)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, RunDataError):
            raise
        raise RunDataError(f"{name} 包含无效的 JSON 数据（{exc}）。") from exc
    if not isinstance(data, dict):
        raise RunDataError(f"{name} 的顶层必须是 JSON 对象。")
    return data


def _optional_object(root: Path, name: str, warnings: list[str]) -> dict[str, Any]:
    path = root / name
    if path.exists() or path.is_symlink():
        try:
            return _read_object(root, name)
        except RunDataError as exc:
            warnings.append(str(exc))
    return {}


def _asset_paths(root: Path, name: str, warnings: list[str]) -> tuple[Path, ...]:
    directory = root / name
    if not directory.exists() and not directory.is_symlink():
        return ()
    try:
        if directory.is_symlink() or not directory.resolve(strict=True).is_relative_to(root):
            raise RunDataError(f"已跳过运行目录之外的 {name} 资源目录。")
        if not directory.is_dir():
            raise RunDataError(f"{name} 应为目录。")
    except (OSError, RuntimeError, ValueError) as exc:
        warnings.append(str(exc))
        return ()

    assets = []
    pending = [(directory, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_ASSETS:
                        warnings.append(f"{name} 超过 {MAX_ASSETS} 个文件或目录，已跳过该资源目录。")
                        return ()
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        if depth < MAX_ASSET_DEPTH and path.resolve(strict=True) == path:
                            pending.append((path, depth + 1))
                        else:
                            warnings.append(f"已跳过 {name} 中的深层或重定向目录 {entry.name}。")
                        continue
                    is_table = (name == "tables" and entry.name.lower().endswith((".csv", ".csv.gz"))) or (
                        name == "figures" and depth == 0 and entry.name.lower() == "figure_manifest.csv"
                    )
                    is_figure = name == "figures" and path.suffix.lower() in FIGURE_MIME
                    if is_table or is_figure or name == "raw":
                        try:
                            resolve_asset(root, path)
                            assets.append(path)
                        except RunDataError as exc:
                            warnings.append(str(exc))
        except (OSError, RuntimeError) as exc:
            warnings.append(f"无法读取 {current.name} 目录（{exc}）。")
    return tuple(sorted(assets, key=lambda path: (path.as_posix().casefold(), path.as_posix())))


def _label(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("id", "name", "type"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return ""


_UNKNOWN_LABELS = {"", "unknown", "unspecified", "not_recorded", "null", "none", "n/a", "na",
                   "未记录", "未声明", "未知", "不详", "缺失"}


def _known(value: Any) -> bool:
    if value is MISSING or value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in _UNKNOWN_LABELS
    if isinstance(value, (list, dict)):
        return bool(value) and all(_known(item) for item in (value.values() if isinstance(value, dict) else value))
    return True


def status_label(value: str) -> str:
    """Human-readable status without upgrading a declaration to verified evidence."""
    return {
        "unknown": "未记录 / 未知", "unvalidated": "未经独立验证",
        "declared_validated": "上游声明已验证（未复核证据）", "conflicting": "上游记录互相冲突",
        "result_available": "上游已生成结果", "partial": "部分完成", "failed": "失败",
        "running": "运行中", "pending": "待运行", "cancelled": "已取消",
        "no_prediction": "无预测结果", "not_applicable": "不适用", "skipped": "已跳过",
        "varying": "响应有变化", "indistinguishable": "响应不可区分",
        "available": "上游记录为可用", "unresolved": "尚不能区分候选优先级",
        "insufficient_conditions": "条件数不足", "not_available": "不可用",
        "passed": "上游技术检查通过", "not_performed": "未进行",
    }.get(value, f"上游状态：{value}" if value else "未记录 / 未知")


def review_status(run: RunData) -> ReviewStatus:
    """Normalize known status fields while retaining their JSON source locations.

    A generic validation.status=passed/validated may describe a schema check,
    not independent validation. Original metadata remains untouched.
    """
    notes: list[str] = []
    sources: list[tuple[str, str]] = []
    execution_aliases = {"completed": "result_available", "complete": "result_available",
                         "success": "result_available", "succeeded": "result_available"}
    execution_values = {"result_available", "partial", "failed", "running", "pending",
                        "cancelled", "no_prediction", "not_applicable", "skipped"}
    independent_aliases = {"none": "unvalidated", "not_performed": "unvalidated",
                           "not_tested": "unvalidated", "unvalidated": "unvalidated",
                           "validated": "declared_validated", "independently_validated": "declared_validated",
                           "failed": "failed", "unknown": "unknown"}

    def read(document: dict[str, Any], path: str) -> Any:
        value: Any = document
        for key in path.split("."):
            if not isinstance(value, dict) or key not in value:
                return MISSING
            value = value[key]
        return value

    def collect(field: str, entries: tuple[tuple[str, dict[str, Any], str], ...],
                kind: str) -> str:
        found = []
        for filename, document, path in entries:
            declared_path = path
            raw = read(document, path)
            if isinstance(raw, dict):
                raw = raw.get("status", MISSING)
                path += ".status"
            if raw is MISSING or raw is None:
                continue
            if not isinstance(raw, str) or not raw.strip():
                notes.append(f"{filename}.{path} 未提供可识别的状态字符串。")
                continue
            value = raw.strip().casefold()
            if kind == "execution":
                value = execution_aliases.get(value, value)
                if value not in execution_values:
                    continue
            elif kind == "independent":
                # Legacy negative declarations remain useful. A generic positive
                # status can describe technical/schema validation, so it cannot
                # assert independent experimental or held-out validation.
                if declared_path == "status" and value not in {"unvalidated", "not_performed", "not_tested"}:
                    continue
                if path.startswith("independent_validation") and value in {"passed", "success"}:
                    value = "declared_validated"
                else:
                    value = independent_aliases.get(value, "unknown")
            elif value in _UNKNOWN_LABELS:
                value = "unknown"
            sources.append((field, f"{filename}.{path}"))
            found.append(value)
        known = set(found) - {"unknown"}
        if len(known) > 1:
            notes.append(f"{field} 的上游记录不一致，不能自动选择其中一项。")
            return "conflicting"
        return next(iter(known)) if known else "unknown"

    documents = (("manifest.json", run.manifest), ("validation.json", run.validation))
    execution = collect("execution_status", tuple(
        (name, doc, key) for name, doc in documents
        for key in ("execution_status", "prediction_status", "status")), "execution")
    response = collect("response_status", tuple(
        (name, doc, key) for name, doc in documents
        for key in ("response_status", "degeneracy_check.response_status")), "technical")
    ranking = collect("ranking_status", tuple(
        (name, doc, key) for name, doc in documents
        for key in ("ranking_status", "degeneracy_check.ranking_status")), "technical")
    independent = collect("independent_validation", tuple(
        (name, doc, key) for name, doc in documents
        for key in ("independent_validation", "validation_status")) +
        (("validation.json", run.validation, "status"),), "independent")
    if independent == "unknown":
        notes.append("未记录独立实验或留出验证状态；运行完成及技术检查通过不能替代独立验证。")
    elif independent == "declared_validated":
        notes.append("独立验证状态来自上游声明；本查看器未复核验证数据、划分或实验结果。")
    return ReviewStatus(execution, response, ranking, independent, tuple(notes), tuple(sources))


def _optional_text(root: Path, name: str, warnings: list[str]) -> str:
    path = root / name
    if path.exists() or path.is_symlink():
        try:
            return _read_text(resolve_asset(root, name))
        except RunDataError as exc:
            warnings.append(str(exc))
    return ""


def load_run(root: Path | str) -> RunData:
    """Read a bundle manifest and index its safe, supported result assets."""
    try:
        root = Path(root).resolve(strict=True)
        if not root.is_dir():
            raise RunDataError("请选择包含 manifest.json 的运行结果文件夹。")
    except (OSError, RuntimeError, ValueError) as exc:
        raise RunDataError("请选择可访问且包含 manifest.json 的运行结果文件夹。") from exc

    manifest = _read_object(root, "manifest.json")
    warnings = []
    validation = _optional_object(root, "validation.json", warnings)
    provenance = _optional_object(root, "provenance.json", warnings)
    parameters = manifest.get("parameters", manifest.get("params", {}))
    if not isinstance(parameters, dict):
        warnings.append("运行参数字段应为 JSON 对象。原始内容保留在清单中。")
        parameters = {}
    report = _optional_text(root, "report.md", warnings)
    errors_text = _optional_text(root, "errors.jsonl", warnings)
    tables = _asset_paths(root, "tables", warnings)
    figure_files = _asset_paths(root, "figures", warnings)
    raw_files = _asset_paths(root, "raw", warnings)

    return RunData(
        root=root,
        run_id=_label(manifest.get("run_id")) or root.name,
        backend=_label(manifest.get("backend")),
        task=_label(manifest.get("task")),
        dataset=_label(manifest.get("dataset")),
        source_url=_label(manifest.get("source_url")) or _label(provenance.get("source_url")),
        notes=_label(manifest.get("notes")),
        manifest=manifest,
        validation=validation,
        provenance=provenance,
        parameters=parameters,
        tables=tables + tuple(path for path in figure_files if path.suffix.lower() == ".csv"),
        figures=tuple(path for path in figure_files if path.suffix.lower() in FIGURE_MIME),
        report=report,
        errors_text=errors_text,
        raw_files=raw_files,
        warnings=tuple(warnings),
    )


def read_table(path: Path | str, limit: int = 2000, *, root: Path | str | None = None) -> TablePreview:
    """Read bounded UTF-8 CSV or gzip-compressed CSV while preserving original values."""
    return _read_table(path, limit=limit, maximum=MAX_TABLE_BYTES, root=root)


def _read_table(path: Path | str, *, limit: int, maximum: int, root: Path | str | None) -> TablePreview:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PREVIEW_ROWS:
        raise RunDataError(f"预览行数应在 1 到 {MAX_PREVIEW_ROWS} 之间。")
    path = Path(path)
    filename = path.name
    if not filename.lower().endswith((".csv", ".csv.gz")):
        raise RunDataError("请选择 .csv 或 .csv.gz 表格。")
    if root is not None:
        path = resolve_asset(root, path)
    table = _read_text(path, maximum, compressed=filename.lower().endswith(".gz"))
    if "\0" in table:
        raise RunDataError(f"{filename} 包含 CSV 文本不支持的空字符。")
    reader = csv.reader(io.StringIO(table, newline=""), strict=True)
    rows = []
    truncated = False
    try:
        headers = next((row for row in reader if row), None)
        if not headers or not any(header.strip() for header in headers):
            raise RunDataError(f"{filename} 缺少表头。")
        total_columns = len(headers)
        if total_columns > MAX_SOURCE_COLUMNS:
            raise RunDataError(f"{filename} 超过 {MAX_SOURCE_COLUMNS} 列源表读取限制。")
        for row in reader:
            if not row:
                continue
            if len(row) != len(headers):
                raise RunDataError(f"{filename} 第 {reader.line_num} 行与表头列数不一致。")
            if len(rows) == limit:
                truncated = True
                break
            rows.append(tuple(row[:MAX_COLUMNS]))
    except csv.Error as exc:
        raise RunDataError(f"{filename} 第 {reader.line_num} 行无法按 CSV 读取（{exc}）。") from exc
    return TablePreview(tuple(headers[:MAX_COLUMNS]), tuple(rows), truncated,
                        total_columns, total_columns > MAX_COLUMNS)


def _json(value: Any, *, formatted: bool = False) -> str:
    if value is MISSING:
        return "（缺失）"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2 if formatted else None)


def _comparison_rows(field: str, left: Any, right: Any) -> list[ComparisonRow]:
    if isinstance(left, dict) and isinstance(right, dict):
        rows = []
        for key in sorted(left.keys() | right.keys()):
            rows.extend(_comparison_rows(f"{field}[{_json(key)}]", left.get(key, MISSING), right.get(key, MISSING)))
        return rows
    left_text, right_text = _json(left), _json(right)
    return [ComparisonRow(field, left_text, right_text, left_text != right_text)]


def _metric_paths(run: RunData) -> dict[str, list[Path]]:
    paths: dict[str, list[Path]] = {}
    for path in run.tables:
        if not path.is_relative_to(run.root / "tables"):
            continue
        name = path.relative_to(run.root / "tables").as_posix().casefold().removesuffix(".gz")
        paths.setdefault(name, []).append(path)
    return paths


def _metric_rows(preview: TablePreview) -> dict[str, tuple[str, str]]:
    if preview.truncated:
        raise RunDataError(f"超过 {MAX_METRIC_ROWS} 行差值比较限制。")
    metrics = {}
    for raw_name, raw_value, raw_unit in preview.rows:
        name = raw_name.strip()
        if not _known(name) or name in metrics:
            raise RunDataError("存在空白或重复指标名称。")
        metrics[name] = (raw_value.strip(), raw_unit.strip())
    return metrics


def _metric_number(raw: str) -> Decimal | None:
    if len(raw) > 60 or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,2})?", raw):
        return None
    number = Decimal(raw)
    parts = number.as_tuple()
    if len(parts.digits) > 40 or abs(parts.exponent) > 30:
        return None
    return number


def _compare_metrics(left: RunData, right: RunData) -> tuple[tuple[MetricComparison, ...], tuple[str, ...]]:
    left_tables, right_tables = _metric_paths(left), _metric_paths(right)
    matching = sorted(left_tables.keys() & right_tables.keys())
    differences = []
    notes = []
    for table in matching[:MAX_METRIC_TABLES]:
        left_paths, right_paths = left_tables[table], right_tables[table]
        if len(left_paths) != 1 or len(right_paths) != 1:
            notes.append(f"{table} 存在多个同名表格，已跳过差值计算。")
            continue
        try:
            left_table = _read_table(left_paths[0], limit=MAX_METRIC_ROWS, maximum=MAX_METRIC_BYTES, root=left.root)
            right_table = _read_table(right_paths[0], limit=MAX_METRIC_ROWS, maximum=MAX_METRIC_BYTES, root=right.root)
            schema = ("metric", "value", "unit")
            if left_table.headers != schema and right_table.headers != schema:
                continue
            if left_table.headers != schema or right_table.headers != schema:
                raise RunDataError("两侧指标表列结构不一致。")
            left_metrics, right_metrics = _metric_rows(left_table), _metric_rows(right_table)
        except RunDataError as exc:
            notes.append(f"{table} · {exc}")
            continue
        for name in sorted(left_metrics.keys() | right_metrics.keys()):
            if name not in left_metrics or name not in right_metrics:
                notes.append(f"{table} · {name} 只出现在一侧。")
                continue
            left_raw, left_unit = left_metrics[name]
            right_raw, right_unit = right_metrics[name]
            if not _known(left_unit) or not _known(right_unit) or left_unit != right_unit:
                notes.append(f"{table} · {name} 的单位缺失或不一致。")
                continue
            left_number, right_number = _metric_number(left_raw), _metric_number(right_raw)
            if left_number is None or right_number is None:
                notes.append(f"{table} · {name} 的数值格式或精度超出支持范围。")
                continue
            with localcontext() as context:
                # The supported coefficient and exponent bounds permit exact subtraction.
                context.prec = 120
                delta = right_number - left_number
            differences.append(MetricComparison(name, left_number, right_number, delta, left_unit, table))
    if len(matching) > MAX_METRIC_TABLES:
        notes.append(f"仅检查前 {MAX_METRIC_TABLES} 张同名表格的指标差值。")
    if not differences and not notes:
        notes.append("未找到可计算差值的同名指标表（metric,value,unit）。")
    return tuple(differences), tuple(notes)


# Fields describing the measurement context, not the intervention being compared.
# A new producer can declare additional invariants in comparison_context without
# requiring a backend-specific reader or changing the original result files.
_CONTEXT_FIELDS = {
    "species": "物种", "cell_background": "细胞背景", "cell_type": "细胞类型",
    "baseline_source": "基线来源", "baseline_kind": "基线类型",
    "accepts_user_baseline": "用户基线能力", "gene_space": "基因空间",
    "gene_id_type": "基因标识体系", "gene_order_sha256": "基因顺序哈希",
    "response_scale": "响应尺度", "expression_scale": "表达尺度",
    "normalization": "归一化方法", "preprocessing": "预处理",
    "dose_unit": "剂量单位", "time_unit": "时间单位",
    "checkpoint_sha256": "权重哈希", "weights_sha256": "权重哈希",
    "checkpoint_sha256_16": "权重 SHA256 前16位",
    "input_sha256": "输入数据哈希", "dataset_sha256": "数据集哈希",
    "baseline_sha256": "基线哈希", "output_type": "输出类型",
}

_CORE_CONTEXT_FIELDS = {
    "backend": "后端", "task": "任务", "dataset": "数据集", "backend_version": "后端版本",
    "model": "模型", "model_version": "模型版本", "dataset_version": "数据集版本",
    "metrics": "指标定义", "units": "单位", "source_kind": "结果类型",
    "source_batch": "来源批次", "source_commit": "来源版本",
}


def _context_entries(run: RunData) -> dict[str, list[tuple[str, Any]]]:
    entries: dict[str, list[tuple[str, Any]]] = {}
    documents = (("manifest.json", run.manifest), ("validation.json", run.validation),
                 ("provenance.json", run.provenance), ("parameters", run.parameters))
    for filename, document in documents:
        for key in _CONTEXT_FIELDS:
            if key in document:
                entries.setdefault(key, []).append((f"{filename}.{key}", document[key]))
        if "comparison_context" in document:
            context = document["comparison_context"]
            if isinstance(context, dict) and context:
                for key, value in context.items():
                    # A context contract adds invariants; it never overrides
                    # contradictory declarations elsewhere in the same bundle.
                    canonical = key if key in _CONTEXT_FIELDS or key in _CORE_CONTEXT_FIELDS else f"comparison_context.{key}"
                    entries.setdefault(canonical, []).append(
                        (f"{filename}.comparison_context.{key}", value))
            else:
                entries.setdefault("comparison_context", []).append((f"{filename}.comparison_context", context))
    # Core metadata already appears in compare_runs. Collect it again only when
    # a context contract repeats that key, to detect contradictions rather than
    # silently preferring the contract.
    for key in entries.keys() & _CORE_CONTEXT_FIELDS.keys():
        for filename, document in documents:
            if key in document:
                entries[key].append((f"{filename}.{key}", document[key]))
    return entries


def _compare_context(left: RunData, right: RunData) -> tuple[list[ComparisonRow], list[str], bool]:
    left_entries, right_entries = _context_entries(left), _context_entries(right)
    rows: list[ComparisonRow] = []
    reasons: list[str] = []
    anchored = (_known(left.manifest.get("source_batch")) and
                left.manifest.get("source_batch") == right.manifest.get("source_batch"))
    for key in sorted(left_entries.keys() | right_entries.keys()):
        label = _CONTEXT_FIELDS.get(key, _CORE_CONTEXT_FIELDS.get(key, key))
        a, b = left_entries.get(key, []), right_entries.get(key, [])
        values = []
        for side, declared in (("左侧", a), ("右侧", b)):
            unique = {_json(value) for _, value in declared}
            if not declared or any(not _known(value) for _, value in declared):
                reasons.append(f"{side}{label}缺失或未知。")
                values.append(MISSING if not declared else declared[0][1])
            elif len(unique) != 1:
                reasons.append(f"{side}{label}在上游记录中冲突。")
                values.append({source: value for source, value in declared})
            else:
                values.append(declared[0][1])
        fields = _comparison_rows(label, *values)
        if all(_known(value) for value in values) and any(row.changed for row in fields):
            reasons.append(f"{label}不一致。")
        rows.extend(fields)
        if key in {"input_sha256", "dataset_sha256", "source_batch", "comparison_context.context_id"}:
            anchored = anchored or (all(_known(value) for value in values) and
                                    _json(values[0]) == _json(values[1]))
    return rows, list(dict.fromkeys(reasons)), anchored


def compare_runs(left: RunData, right: RunData) -> RunComparison:
    """Compare run context and parameters, then subtract matching declared metrics."""
    reasons = []
    rows = []
    for key, label in (("backend", "后端"), ("task", "任务"), ("dataset", "数据集")):
        left_label, right_label = getattr(left, key), getattr(right, key)
        if not _known(left_label) or not _known(right_label):
            reasons.append(f"{label}信息不完整。")
        elif left_label != right_label:
            reasons.append(f"{label}不一致。")
        fields = _comparison_rows(label, left.manifest.get(key, MISSING), right.manifest.get(key, MISSING))
        if left_label and left_label == right_label and any(row.changed for row in fields):
            reasons.append(f"{label}附加信息不一致。")
        rows.extend(fields)
    for key, label in (("run_id", "运行编号"), ("backend_version", "后端版本"), ("model", "模型"),
                       ("model_version", "模型版本"), ("dataset_version", "数据集版本"),
                       ("metrics", "指标定义"), ("units", "单位"), ("source_kind", "结果类型"),
                       ("source_batch", "来源批次"), ("source_commit", "来源版本")):
        left_value, right_value = left.manifest.get(key, MISSING), right.manifest.get(key, MISSING)
        if left_value is MISSING and right_value is MISSING:
            continue
        fields = _comparison_rows(label, left_value, right_value)
        if key != "run_id":
            if not _known(left_value) or not _known(right_value):
                reasons.append(f"{label}缺失或未知。")
            elif any(row.changed for row in fields):
                reasons.append(f"{label}不一致。")
        rows.extend(fields)
    left_parameters = left.manifest.get("parameters", left.manifest.get("params", MISSING))
    right_parameters = right.manifest.get("parameters", right.manifest.get("params", MISSING))
    if left_parameters is not MISSING or right_parameters is not MISSING:
        rows.extend(_comparison_rows("参数", left_parameters, right_parameters))
    context_rows, context_reasons, anchored = _compare_context(left, right)
    rows.extend(context_rows)
    reasons.extend(context_reasons)
    for side, run in (("左侧", left), ("右侧", right)):
        review = review_status(run)
        status = review.execution_status
        if status in {"failed", "no_prediction", "cancelled", "running", "pending", "conflicting",
                      "skipped", "not_applicable"}:
            reasons.append(f"{side}运行状态为{status_label(status)}，不能将源表视为完整有效结果。")
        for label, technical in (("响应检查", review.response_status), ("排名检查", review.ranking_status)):
            if technical in {"failed", "conflicting"}:
                reasons.append(f"{side}{label}为{status_label(technical)}；源表未声明指标角色，已暂停数值差值，保留原始数据供诊断。")
    if reasons:
        return RunComparison(False, tuple(reasons), tuple(rows), (), ("运行上下文无法确认可比，已跳过数值差值。",))
    metrics, metric_notes = _compare_metrics(left, right)
    if metrics and not anchored and left.root != right.root:
        return RunComparison(False, ("缺少共同来源批次、数据指纹或明确的比较上下文标识。",), tuple(rows), (),
                             metric_notes + ("同名数据集及同单位不能确认数据来源和处理尺度一致，已跳过数值差值。",))
    return RunComparison(True, (), tuple(rows), metrics, metric_notes)


def _http_url(value: str) -> str:
    if not value or any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme in ("http", "https") and parts.hostname and parts.username is None:
            _ = parts.port
            return value
    except ValueError:
        pass
    return ""


def _table_html(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> str:
    heading = "".join(f'<th scope="col">{html.escape(cell)}</th>' for cell in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f'<div class="table"><table><thead><tr>{heading}</tr></thead><tbody>{body}</tbody></table></div>'


def _figure_uri(run: RunData, figure: Path) -> str:
    data = _read_bounded(resolve_asset(run.root, figure), MAX_FIGURE_BYTES)
    suffix = figure.suffix.lower()
    valid = {
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".gif": data.startswith((b"GIF87a", b"GIF89a")),
        ".webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
        ".bmp": data.startswith(b"BM"),
    }
    if not valid[suffix]:
        raise RunDataError("图片内容与扩展名不匹配。")
    return f"data:{FIGURE_MIME[suffix]};base64,{base64.b64encode(data).decode('ascii')}"


def _table_downloads_html(run: RunData, budget: list[int]) -> str:
    """Embed exact source bytes, sharing one bounded budget across the report."""
    attached: list[str] = []
    omitted: list[str] = []
    for table in run.tables:
        relative = table.relative_to(run.root).as_posix()
        try:
            path = resolve_asset(run.root, table)
            if path.stat().st_size > budget[0]:
                raise RunDataError("超过本报告剩余源表附件预算")
            data = _read_bounded(path, min(MAX_TABLE_BYTES, budget[0]))
            budget[0] -= len(data)
            mime = "application/gzip" if table.name.lower().endswith(".gz") else "text/csv;charset=utf-8"
            encoded = base64.b64encode(data).decode("ascii")
            name = relative.replace("/", "__")
            digest = hashlib.sha256(data).hexdigest()
            attached.append(f'<li><a download="{html.escape(name)}" href="data:{mime};base64,{encoded}">'
                            f'{html.escape(relative)}</a> · {len(data)} bytes · SHA256 <code>{digest}</code></li>')
        except (RunDataError, OSError) as exc:
            omitted.append(f"<li>{html.escape(relative)} · {html.escape(str(exc))}</li>")
    sections = ["<h3>完整源表附件</h3>",
                "<p>以下下载包含导出时的原始文件字节，保留全部行列、顺序和缺失值；SHA256 用于核对附件内容。"
                "表格预览不代表完整数据，也不代表已验证其科学有效性。</p>"]
    if attached:
        sections.append("<ul>" + "".join(attached) + "</ul>")
    else:
        sections.append("<p>本报告没有内嵌源表附件。</p>")
    if omitted:
        sections.append("<h4>未内嵌源表（仍在原运行目录）</h4><ul>" + "".join(omitted) + "</ul>")
    sections.append(f"<p>每张源表最多 {MAX_TABLE_BYTES // (1024 * 1024)} MiB；"
                    f"整份报告的源表原字节合计最多 {MAX_REPORT_TABLE_BYTES // (1024 * 1024)} MiB。"
                    "原始模型文件仅列出名称，未作为附件导出。</p>")
    return "\n".join(sections)


def _run_html(run: RunData, index: int, *, table_budget: list[int] | None = None) -> str:
    escape = html.escape
    heading = ("后端", "任务", "数据集")
    context = tuple(value or "未声明" for value in (run.backend, run.task, run.dataset))
    sections = [f'<section><h2>结果 {index} · {escape(run.run_id)}</h2>', _table_html(heading, (context,))]
    review = review_status(run)
    sections.append("<h3>结果状态</h3>")
    sections.append(_table_html(("运行执行", "响应检查", "候选排名", "独立验证"), ((
        status_label(review.execution_status), status_label(review.response_status),
        status_label(review.ranking_status), status_label(review.independent_validation)),)))
    sections.append(f"<p>导入目录：<code>{escape(str(run.root))}</code></p>")
    if review.notes:
        sections.append("<ul>" + "".join(f"<li>{escape(note)}</li>" for note in review.notes) + "</ul>")
    if review.sources:
        sections.append("<p>状态记录来源：" + escape("；".join(f"{field}: {source}" for field, source in review.sources)) + "</p>")
    if run.manifest.get("source_kind") == "public-historical-condition-view":
        sections.append("<p>公开历史批次中的条件结果。</p>")
    if run.notes:
        sections.append(f"<p>{escape(run.notes)}</p>")
    if link := _http_url(run.source_url):
        sections.append(f'<p>来源 <a href="{escape(link)}" rel="noreferrer">{escape(link)}</a></p>')
    for title, data in (("运行参数", run.parameters), ("运行清单", run.manifest),
                        ("上游校验记录", run.validation), ("来源记录", run.provenance)):
        content = escape(_json(data, formatted=True)) if data else "<em>无记录</em>"
        sections.append(f"<h3>{title}</h3><pre>{content}</pre>")
    if run.warnings:
        sections.append("<h3>导入提示</h3><ul>" + "".join(f"<li>{escape(note)}</li>" for note in run.warnings) + "</ul>")
    if run.tables:
        sections.append("<h3>结果表格</h3><ul>" + "".join(f"<li>{escape(path.relative_to(run.root).as_posix())}</li>" for path in run.tables) + "</ul>")
        for table in run.tables[:4]:
            sections.append(f"<h4>{escape(table.relative_to(run.root).as_posix())}</h4>")
            try:
                preview = read_table(table, limit=12, root=run.root)
                sections.append(_table_html(preview.headers, preview.rows))
                if preview.truncated:
                    sections.append("<p>仅展示前 12 行。</p>")
                if preview.columns_truncated:
                    sections.append(f"<p>源表共 {preview.total_columns} 列，仅预览前 {len(preview.headers)} 列；完整列见源表附件。</p>")
            except RunDataError as exc:
                sections.append(f"<p>{escape(str(exc))}</p>")
        if len(run.tables) > 4:
            sections.append("<p>报告内预览前 4 张表格。</p>")
        sections.append(_table_downloads_html(run, table_budget if table_budget is not None else [MAX_REPORT_TABLE_BYTES]))
    if run.figures:
        sections.append("<h3>上游图件</h3><ul>" + "".join(f"<li>{escape(path.relative_to(run.root).as_posix())}</li>" for path in run.figures) + "</ul>")
        for figure in run.figures[:4]:
            try:
                image = _figure_uri(run, figure)
                sections.append(f'<figure><img src="{image}" alt="{escape(figure.name)}"><figcaption>{escape(figure.name)}</figcaption></figure>')
            except RunDataError as exc:
                sections.append(f"<p>{escape(figure.name)} · {escape(str(exc))}</p>")
        if len(run.figures) > 4:
            sections.append("<p>报告内嵌前 4 张图件。</p>")
    if run.report:
        sections.append(f"<h3>上游报告原文</h3><pre>{escape(run.report)}</pre>")
    if run.errors_text:
        sections.append(f"<h3>上游错误记录</h3><pre>{escape(run.errors_text)}</pre>")
    if run.raw_files:
        names = "".join(f"<li>{escape(path.relative_to(run.root).as_posix())}</li>" for path in run.raw_files)
        sections.append(f"<h3>原始附件文件名</h3><ul>{names}</ul>")
    sections.append("</section>")
    return "\n".join(sections)


REPORT_STYLE = """
body{max-width:1100px;margin:3rem auto;padding:0 1.5rem;color:#172e2c;background:#f4f8f7;font:16px/1.6 system-ui,sans-serif}
h1,h2,h3,h4{line-height:1.3}section{background:white;border:1px solid #d4e2de;border-radius:12px;padding:1.5rem;margin:1.5rem 0}
table{border-collapse:collapse;width:100%;text-align:left}th,td{border-bottom:1px solid #e2ebe8;padding:.45rem .6rem;vertical-align:top}
th,pre{background:#edf5f2}.table{overflow:auto;max-width:100%;overflow-wrap:anywhere}pre{padding:.75rem;white-space:pre-wrap;overflow-wrap:anywhere}
figure{margin:1rem 0}img{display:block;max-width:100%;max-height:36rem;object-fit:contain}a{color:#075d50;overflow-wrap:anywhere}
@media print{body{background:white;margin:0;padding:0}section{border:0;padding:0}figure{break-inside:avoid}}
"""


def _comparison_html(left: RunData, right: RunData) -> str:
    comparison = compare_runs(left, right)
    status = "已核对两侧结果的声明信息。" if comparison.compatible else "两侧结果的声明不足以确认可比性。"
    reasons = " ".join(comparison.reasons)
    rows = tuple((row.field, row.left, row.right, "有变化" if row.changed else "一致") for row in comparison.rows)
    table = _table_html(("字段", left.run_id, right.run_id, "比较"), rows)
    sections = [f"<section><h2>结果对比</h2><p>{status} {html.escape(reasons)}</p>{table}"]
    if comparison.metrics:
        metric_rows = tuple((row.table, row.name, format(row.left, "f"), format(row.right, "f"),
                             format(row.delta, "f"), row.unit) for row in comparison.metrics)
        sections.append("<h3>同名同单位指标</h3><p>差值为右侧减左侧，描述所导入的数值。</p>")
        sections.append(_table_html(("源表", "指标", left.run_id, right.run_id, "差值", "单位"), metric_rows))
    if comparison.metric_notes:
        notes = "".join(f"<li>{html.escape(note)}</li>" for note in comparison.metric_notes)
        sections.append(f"<ul>{notes}</ul>")
    sections.append("</section>")
    return "\n".join(sections)


def export_report(destination: Path | str, left: RunData, right: RunData | None = None) -> Path:
    """Export a self-contained, printable report to a local .html file."""
    destination = Path(destination)
    temporary_path = None
    if destination.suffix.lower() not in (".html", ".htm"):
        raise RunDataError("请选择扩展名为 .html 的报告路径。")
    try:
        parent = destination.parent.resolve(strict=True)
        destination = parent / destination.name
        resolved = destination.resolve()
        runs = (left, right) if right is not None else (left,)
        table_budget = [MAX_REPORT_TABLE_BYTES]
        if any(destination.is_relative_to(run.root) or resolved.is_relative_to(run.root) for run in runs):
            raise RunDataError("请选择运行结果文件夹之外的报告保存位置。")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, prefix=".aper-report-", delete=False) as output:
            temporary_path = Path(output.name)
            output.write('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                         '<meta name="viewport" content="width=device-width, initial-scale=1">'
                         '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">'
                         f'<title>Aper AI · 虚拟细胞运行报告</title><style>{REPORT_STYLE}</style></head>'
                         '<body><h1>Aper AI · 虚拟细胞运行报告</h1><main>')
            output.write(f'<p>导出时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec="seconds")}</p>'
                         '<p>本报告是已导入结果的离线复核快照。工作台未执行模型或独立实验验证；'
                         '运行、技术检查、候选排名与独立验证分别列示。</p>')
            if right is not None:
                output.write(_comparison_html(left, right))
            for index, run in enumerate(runs, start=1):
                output.write(_run_html(run, index, table_budget=table_budget))
            output.write("</main></body></html>")
        os.replace(temporary_path, destination)
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, RunDataError):
            raise
        raise RunDataError(f"无法保存报告 {destination.name}，请检查目录权限或文件占用。") from exc
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return destination
