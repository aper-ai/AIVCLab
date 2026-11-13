"""Read supported completed run contracts and explain their actual results in Chinese.

This entry never executes models or turns technical checks into scientific validation.
Only the Python standard library is required.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import sys
from urllib.parse import quote


MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_TABLE_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_ROWS = 100000
KANG_SCALE = "log2(1 + 1000000 * pseudobulk_gene_counts / pseudobulk_all_gene_counts)"
PRNET_SCALE = "official_demo_normalize_total_median_then_log1p"
CELLORACLE_SCALE = "log1p(raw counts), then KNN smoothing into imputed_count; native simulated_count and delta_X retain that internal scale"
METHODS = ("prnet_mean", "prnet_sample", "no_change", "other_group_mean")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, label, *, optional=False, lower=None, upper=None):
    if optional and (value is None or value == ""):
        return None
    require(not isinstance(value, bool), f"{label} 不能是布尔值")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label} 必须是有限数值") from None
    require(math.isfinite(result), f"{label} 含非有限数值")
    require(lower is None or result >= lower, f"{label} 小于允许范围")
    require(upper is None or result <= upper, f"{label} 大于允许范围")
    return result


def count(value, label, minimum=0):
    result = number(value, label, lower=minimum)
    require(result.is_integer(), f"{label} 必须为整数")
    return int(result)


def equal_number(actual, declared, label):
    if actual is None:
        require(declared is None, f"{label}：源表未定义，但记录给出了数值")
    else:
        require(math.isclose(actual, number(declared, label), rel_tol=1e-8, abs_tol=1e-10),
                f"{label}：记录与源表重算不一致")


def mean(values):
    values = [v for v in values if v is not None]
    return math.fsum(values) / len(values) if values else None


def unique(rows, field):
    result = {}
    for row in rows:
        key = row[field]
        require(isinstance(key, str) and key.strip() and key == key.strip(), f"{field} 为空或含首尾空格")
        require(key not in result, f"{field} 重复：{key}")
        result[key] = row
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"JSON 重复字段：{key}")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"JSON 含非有限常量：{value}")


def digest(path):
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            total += len(block)
            require(total <= MAX_ARTIFACT_BYTES, f"文件读取超过 256 MiB 限额：{path.name}")
            h.update(block)
    return h.hexdigest()


class Source:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        require(self.root.is_dir(), "--run-dir 必须是已有分析目录")
        self.inputs = {}
        self.provenance = self.json("provenance.json")
        records = self.provenance.get("artifacts", {})
        require(isinstance(records, dict), "provenance.artifacts 必须是对象")
        self.artifacts = records

    def file(self, relative):
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, f"不接受越界文件路径：{relative}")
        candidate = self.root / path
        require(candidate.is_file(), f"缺少必要文件：{relative}；请提供完整且已完成的分析目录")
        resolved = candidate.resolve(strict=True)
        require(resolved.is_relative_to(self.root), f"文件链接越过分析目录：{relative}")
        require(resolved.stat().st_size <= MAX_ARTIFACT_BYTES, f"文件超过解读入口的 256 MiB 限额：{relative}")
        key = path.as_posix()
        if key not in self.inputs:
            self.inputs[key] = {"bytes": resolved.stat().st_size, "sha256": digest(resolved)}
        return resolved

    def json(self, relative):
        path = self.file(relative)
        require(path.stat().st_size <= MAX_JSON_BYTES, f"JSON 超过 4 MiB 限额：{relative}")
        with path.open("rb") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        require(len(raw) <= MAX_JSON_BYTES, f"JSON 读取超过 4 MiB 限额：{relative}")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=_invalid_constant)
        require(isinstance(data, dict), f"JSON 顶层必须是对象：{relative}")
        return data

    def table(self, relative, required):
        path = self.file(relative)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as handle:
            raw = handle.read(MAX_TABLE_BYTES + 1)
        require(len(raw) <= MAX_TABLE_BYTES, f"源表解压后超过 32 MiB 限额：{relative}")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
        fields = reader.fieldnames or []
        require(len(fields) == len(set(fields)) and all(fields), f"源表有重复或空表头：{relative}")
        require(set(required) <= set(fields), f"源表缺少必要列：{relative}；需要 {', '.join(required)}")
        rows = []
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()), f"源表行宽不一致：{relative}")
            rows.append(row)
            require(len(rows) <= MAX_ROWS, f"源表超过 {MAX_ROWS} 行限额：{relative}")
        return rows

    def verify(self):
        for name, record in self.inputs.items():
            require(digest(self.root / name) == record["sha256"], f"读取过程中源文件改变：{name}")
            declared = self.artifacts.get(name)
            if declared is not None:
                require(isinstance(declared, dict), f"产物哈希记录格式错误：{name}")
                require(declared.get("sha256") == record["sha256"] and declared.get("bytes") == record["bytes"],
                        f"产物与 provenance 中的哈希或大小不一致：{name}")
            record["matches_recorded_artifact"] = True if declared is not None else None


def ranked(rows, id_key, value_key, symbol_key=None, exclude=None):
    result = []
    for row in rows:
        if row[id_key] == exclude:
            continue
        item = {"gene_id": row[id_key], "value": row[value_key]}
        if symbol_key:
            item["gene_symbol"] = row[symbol_key]
        result.append(item)
    positive = sorted((r for r in result if r["value"] > 0), key=lambda x: (-x["value"], x["gene_id"]))[:5]
    negative = sorted((r for r in result if r["value"] < 0), key=lambda x: (x["value"], x["gene_id"]))[:5]
    return {"positive": positive, "negative": negative,
            "positive_genes": sum(r["value"] > 0 for r in result),
            "negative_genes": sum(r["value"] < 0 for r in result),
            "zero_genes": sum(r["value"] == 0 for r in result)}


def figures(source, *, kang=False):
    if kang:
        item = source.json("figure_manifest.json")
        rows = [{"status": item.get("status"), "paths": item.get("paths", []), "reason": item.get("reason")}]
    else:
        rows = [{"status": r["status"], "paths": [p for p in r["plot_path"].split(";") if p], "reason": r["reason"]}
                for r in source.table("figures/figure_manifest.csv", ["status", "plot_path", "reason"])]
    for row in rows:
        require(row["status"] in {"generated", "skipped", "failed"}, "图清单含未知状态")
        require(isinstance(row["paths"], list), "图清单 paths 必须为列表")
        if row["status"] == "generated":
            require(row["paths"], "图清单标记生成但没有图路径")
            for path in row["paths"]:
                require(isinstance(path, str), "图路径必须为字符串")
                source.file(path)
    return rows


def kang_result(source):
    qc = source.json("qc.json")
    require(qc.get("status") in {"completed", "completed_without_paired_response"}, "Kang 分析尚未完成")
    require(qc.get("model_status") == source.provenance.get("model_status") == "not_run", "观测分析的模型状态矛盾")
    require(qc.get("independent_validation") == source.provenance.get("independent_validation") == "not_assessed",
            "此观测结果契约不支持独立预测验证声明")
    require(qc.get("replicate_unit") == "donor" and qc.get("donor_weighting") == "equal", "不支持此供体单位或加权方式")
    require(qc.get("scale") == KANG_SCALE and qc.get("response_operation") == "stim_minus_ctrl_within_same_donor_and_cell_type",
            "Kang 响应尺度或比较方向与已支持契约不同")
    n = count(qc.get("paired_donors"), "paired_donors")
    genes = count(qc.get("source_genes"), "source_genes", 1)
    pairs = source.table("tables/donor_pairs.csv", ["donor", "cell_type", "status", "ctrl_n_cells", "stim_n_cells"])
    unique(pairs, "donor")
    require(all(p["cell_type"] == qc.get("selected_cell_type") for p in pairs), "配对表与所选细胞类型不一致")
    require(all(p["status"] in {"included", "excluded"} for p in pairs), "配对表含未知状态")
    included = [p for p in pairs if p["status"] == "included"]
    require(len(included) == n, "配对表与 QC 的供体数不一致")
    for condition in ("ctrl", "stim"):
        observed = sum(count(p[f"{condition}_n_cells"], f"{condition}_n_cells", 1) for p in included)
        require(observed == count(qc.get(f"selected_{condition}_cells"), f"selected_{condition}_cells"), "配对表与 QC 的细胞数不一致")
    rows = source.table("tables/gene_summary.csv", ["gene_id", "gene_symbol", "n_paired_donors"])
    unique(rows, "gene_id")
    require(len(rows) == genes, "基因摘要行数与 QC 不一致")
    require((n > 0) == (qc["status"] == "completed"), "完成状态与有效供体数量矛盾")
    for row in rows:
        require(count(row["n_paired_donors"], "n_paired_donors") == n, "基因摘要供体数不一致")
        if not n:
            continue  # The producer omits response columns when no donor pair is eligible.
        require({"mean_paired_difference", "sample_sd_across_donors", "positive_donors", "negative_donors"} <= row.keys(),
                "有有效供体配对，但基因摘要缺少响应或方向统计")
        row["mean_paired_difference"] = number(row["mean_paired_difference"], "mean_paired_difference")
        number(row["sample_sd_across_donors"], "sample_sd_across_donors", optional=n < 2, lower=0)
        pos, neg = count(row["positive_donors"], "positive_donors"), count(row["negative_donors"], "negative_donors")
        require(pos + neg <= n, "正负方向供体数超过配对供体数")
    for name in ("raw/paired_responses.npz", "raw/pseudobulk_counts.npz"):
        source.file(name)
    return {"kind": "kang_observed", "task": "按供体配对的观测转录响应", "execution_status": qc["status"],
            "model_status": "not_run", "independent_validation": "not_assessed", "scale": KANG_SCALE,
            "baseline": "同一供体、同一细胞类型的 ctrl pseudobulk", "replicate_unit": "donor",
            "paired_donors": n, "genes": genes, "cell_type": qc["selected_cell_type"],
            "source_cells": count(qc.get("source_cells"), "source_cells", 1),
            "included_singlets": count(qc.get("included_singlets"), "included_singlets", 1),
            "control_cells": count(qc.get("selected_ctrl_cells"), "selected_ctrl_cells"),
            "stimulated_cells": count(qc.get("selected_stim_cells"), "selected_stim_cells"),
            "pair_exclusions": qc.get("pair_exclusions", []),
            "gene_changes": ranked(rows, "gene_id", "mean_paired_difference", "gene_symbol") if n else None,
            "figures": figures(source, kang=True),
            "links": ["qc.json", "tables/donor_pairs.csv", "tables/gene_summary.csv", "tables/paired_responses.csv.gz", "report.md"]}


def celloracle_result(source, manifest):
    validation = source.json("validation.json")
    require(manifest.get("status") == source.provenance.get("status") == "completed", "CellOracle 运行未完成或状态矛盾")
    require(manifest.get("output_type") == "network_simulation" and manifest.get("task") in {"ko", "oe"}, "不是受支持的 CellOracle KO/OE 结果")
    require(manifest.get("celloracle_internal_scale") == CELLORACLE_SCALE, "CellOracle 内部尺度与已支持契约不同")
    require(manifest.get("scientific_status") == "simulated_unvalidated", "此 CellOracle 结果契约只支持未独立验证的模拟")
    require(manifest.get("independent_validation") == validation.get("independent_validation") == source.provenance.get("independent_validation") == "none",
            "CellOracle 独立验证状态矛盾或不受支持")
    require(validation.get("input_status") == "passed" and validation.get("simulation_status") == "result_available"
            and validation.get("delta_x_finite") is True, "CellOracle 核心输入或模拟检查未通过")
    require(source.provenance.get("backend") == manifest.get("backend"), "CellOracle 后端版本记录不一致")
    cells, genes = count(validation.get("cells"), "cells", 1), count(manifest.get("genes_used"), "genes_used", 1)
    target = manifest.get("target_gene")
    require(isinstance(target, str) and target.strip(), "缺少目标基因")
    rows = source.table("tables/gene_effects.csv", ["gene", "mean_delta", "mean_abs_delta", "fraction_cells_up", "fraction_cells_down"])
    by_gene = unique(rows, "gene")
    require(len(rows) == genes and target in by_gene, "基因效应表维度或目标基因与运行记录不一致")
    for row in rows:
        row["mean_delta"] = number(row["mean_delta"], "mean_delta")
        absolute = number(row["mean_abs_delta"], "mean_abs_delta", lower=0)
        require(absolute + 1e-10 >= abs(row["mean_delta"]), "平均绝对变化小于平均变化的绝对值")
        up = number(row["fraction_cells_up"], "fraction_cells_up", lower=0, upper=1)
        down = number(row["fraction_cells_down"], "fraction_cells_down", lower=0, upper=1)
        require(up + down <= 1 + 1e-10, "细胞正负变化比例之和超过 1")
    equal_number(by_gene[target]["mean_delta"], validation.get("target_gene_mean_delta"), "目标基因平均变化")
    settings = source.table("tables/target_expression_setting.csv", ["cell", "baseline_imputed", "fixed_input_setting"])
    unique(settings, "cell")
    require(len(settings) == cells, "目标表达设定表的细胞数不一致")
    chosen = number(validation.get("target_setting", {}).get("chosen_value"), "target_setting.chosen_value", lower=0)
    baselines = []
    for row in settings:
        baselines.append(number(row["baseline_imputed"], "baseline_imputed", lower=0))
        equal_number(chosen, row["fixed_input_setting"], "固定目标表达设定")
    if manifest["task"] == "ko":
        require(chosen == 0, "KO 记录的设定值不是零")
    else:
        require(chosen > 0, "OE 记录的设定值必须为正")
    for name in ("raw/baseline_imputed_expression.csv.gz", "raw/simulated_expression.csv.gz", "raw/delta_X.csv.gz"):
        source.file(name)
    projection = validation.get("projection_status")
    require(projection == "result_available", "当前解读入口需要完整的 CellOracle 投影结果；请先查看失败记录")
    source.file("tables/cell_state_shift.csv.gz")
    return {"kind": "celloracle_simulation", "task": f"{target} {'敲除' if manifest['task'] == 'ko' else '过表达'}模拟",
            "execution_status": "completed", "model_status": "executed", "independent_validation": "not_assessed",
            "scale": manifest.get("celloracle_internal_scale"), "baseline": "CellOracle 内部 imputed_count",
            "replicate_unit": "not_established_from_run_metadata", "cells": cells, "genes": genes,
            "target_gene": target, "mode": manifest["task"], "target_setting": chosen,
            "target_setting_choice": validation.get("target_setting", {}).get("choice"),
            "requested_oe_percentile": manifest.get("parameters", {}).get("oe_percentile"),
            "target_mean_delta": by_gene[target]["mean_delta"],
            "cells_above_target_setting": sum(v > chosen for v in baselines),
            "gene_changes": ranked(rows, "gene", "mean_delta", exclude=target),
            "mean_shift_magnitude": number(validation.get("mean_shift_magnitude"), "mean_shift_magnitude", lower=0),
            "mean_random_shift_magnitude": number(validation.get("mean_random_shift_magnitude"), "mean_random_shift_magnitude", lower=0),
            "group_column": validation.get("group_column"), "grn_scope": validation.get("grn_scope"),
            "figures": figures(source),
            "links": ["manifest.json", "validation.json", "tables/gene_effects.csv", "tables/target_expression_setting.csv", "tables/cell_state_shift.csv.gz", "report.md"]}


def prnet_result(source, manifest):
    qc, validation = source.json("qc.json"), source.json("validation.json")
    require(manifest.get("status") == "completed" and manifest.get("execution_status") == "success"
            and manifest.get("model_status") == source.provenance.get("model_status") == "executed"
            and manifest.get("prediction_status") == "success", "PRnet 运行未完成或执行状态矛盾")
    require(manifest.get("independent_validation") == source.provenance.get("independent_validation") == validation.get("independent_validation") == "not_assessed"
            and validation.get("training_overlap") == "unknown" and validation.get("holdout_status") == "not_established",
            "PRnet 参考入口的训练/验证状态矛盾或不受支持")
    require(manifest.get("scale") == qc.get("scale") == PRNET_SCALE, "PRnet 参考尺度不匹配")
    require(qc.get("finite_predictions") is True and qc.get("all_profile_and_gene_ids_preserved") is True, "PRnet 核心数值/标识检查未通过")
    n = count(qc.get("profiles"), "profiles", 1)
    require(count(manifest.get("conditions_completed"), "conditions_completed") == n, "PRnet 完成数量与 QC 不一致")
    conditions = unique(source.table("tables/condition_index.csv", ["source_profile_id", "condition_id"]), "source_profile_id")
    require(len(conditions) == n, "条件表处理表达谱数量不一致")
    rows = source.table("tables/profile_metrics.csv", ["source_profile_id", "condition_id", "method", "rmse", "mae", "pearson", "post_expression_pearson", "scale"])
    grouped = {method: {} for method in METHODS}
    for row in rows:
        method, profile = row["method"], row["source_profile_id"]
        require(method in grouped and profile in conditions and profile not in grouped[method], "指标表含未知方法、缺失身份或重复记录")
        require(row["condition_id"] == conditions[profile]["condition_id"] and row["scale"] == PRNET_SCALE, "指标表条件标识或尺度不一致")
        for key in ("rmse", "mae"):
            row[key] = number(row[key], key, lower=0)
        for key in ("pearson", "post_expression_pearson"):
            row[key] = number(row[key], key, optional=True, lower=-1, upper=1)
        require(method != "no_change" or row["pearson"] is None, "零响应的 Pearson 应未定义，不能填写零或其他数值")
        grouped[method][profile] = row
    metrics = {}
    for method, records in grouped.items():
        require(set(records) == set(conditions), f"{method} 的表达谱集合与条件表不一致")
        summary = {"mean_profile_" + key: mean([r[key] for r in records.values()]) for key in ("rmse", "mae", "pearson")}
        summary["mean_profile_post_expression_pearson"] = mean([r["post_expression_pearson"] for r in records.values()])
        summary["profile_pearson_defined"] = sum(r["pearson"] is not None for r in records.values())
        declared = validation.get("metrics", {}).get(method, {})
        for key, value in summary.items():
            equal_number(value, declared.get(key), f"{method}.{key}")
        metrics[method] = summary
    model_rmse, zero_rmse = metrics["prnet_mean"]["mean_profile_rmse"], metrics["no_change"]["mean_profile_rmse"]
    differences = [grouped["prnet_mean"][p]["rmse"] - grouped["no_change"][p]["rmse"] for p in conditions]
    ties = sum(math.isclose(v, 0, abs_tol=1e-12) for v in differences)
    source.file("raw/reference_predictions.npz")
    return {"kind": "prnet_reference", "task": "PRnet 固定参考数据的转录响应评估", "execution_status": "completed",
            "model_status": "executed", "independent_validation": "not_assessed", "scale": PRNET_SCALE,
            "baseline": "来源表达谱指定的 paired control", "replicate_unit": "biological_independence_not_established",
            "profiles": n, "genes": count(qc.get("genes"), "genes", 1), "metrics": metrics,
            "comparison": "tied" if math.isclose(model_rmse, zero_rmse, rel_tol=0, abs_tol=1e-12) else ("lower_rmse" if model_rmse < zero_rmse else "higher_rmse"),
            "rmse_difference_model_minus_no_change": model_rmse - zero_rmse,
            "relative_rmse_improvement_percent": (zero_rmse - model_rmse) / zero_rmse * 100 if zero_rmse > 0 else None,
            "profiles_lower_rmse": sum(v < -1e-12 for v in differences), "profiles_higher_rmse": sum(v > 1e-12 for v in differences), "profiles_tied": ties,
            "cross_plate_profiles": count(qc.get("cross_rna_plate_profiles"), "cross_rna_plate_profiles"),
            "noise_draws": count(manifest.get("parameters", {}).get("noise_draws"), "noise_draws", 1),
            "figures": figures(source),
            "links": ["manifest.json", "qc.json", "validation.json", "tables/profile_metrics.csv", "tables/condition_index.csv", "report.md"]}


def md(value):
    return html.escape(str(value), quote=False).replace("|", "\\|").replace("`", "\\`").replace("\r", " ").replace("\n", " ")


def fmt(value):
    return "未定义" if value is None else f"{value:.6g}"


def link(source, output, relative):
    path = source.file(relative)
    try:
        target = quote(Path(os.path.relpath(path, output)).as_posix(), safe="/")
        return f"[{md(relative)}]({target})"
    except ValueError:  # Windows drives may differ; do not emit a broken relative link.
        return f"{md(relative)}：`{md(path)}`（位于另一磁盘，请按路径打开）"


def gene_sections(changes):
    lines = ["## 哪些基因变化较大", "", "分别列出有符号平均变化最大的正向与负向基因；这是描述性排序，没有 P 值或 FDR。", ""]
    for label, key in (("正向", "positive"), ("负向", "negative")):
        lines.extend([f"### {label}变化", ""])
        if not changes[key]:
            lines.extend([f"本次源表没有平均变化为{label}的基因。", ""])
            continue
        lines.extend(["| 唯一基因 ID | 符号 | 平均变化 |", "| --- | --- | ---: |"])
        for item in changes[key]:
            lines.append(f"| {md(item['gene_id'])} | {md(item.get('gene_symbol', item['gene_id']))} | {fmt(item['value'])} |")
        lines.append("")
    lines.extend([f"上述统计范围内的方向计数：正向 {changes['positive_genes']}、负向 {changes['negative_genes']}、零变化 {changes['zero_genes']}。符号可能重复，连接结果时使用唯一 ID。", ""])
    return lines


def render(summary, source, output):
    s = summary
    lines = [f"# {md(s['task'])}：结果解读", "", "## 这次完成了什么", ""]
    if source.provenance.get("source_kind") == "synthetic_test_fixture":
        lines.extend(["**本目录使用合成测试夹具，以下数值不是真实研究结果。**", ""])
    if s["kind"] == "kang_observed":
        lines.extend([f"已读取 {s['source_cells']:,} 个来源细胞，按来源注释保留 {s['included_singlets']:,} 个 singlet。选择 **{md(s['cell_type'])}**，对照 {s['control_cells']:,} 个细胞、刺激 {s['stimulated_cells']:,} 个细胞，形成 **{s['paired_donors']} 位供体配对**，基因轴保留 {s['genes']:,} 个唯一 ID。", "",
                      "这里计算的是观测表达响应，**没有运行预测模型**。先在每位供体、每个条件内汇总原始 UMI，以全部来源基因计算 CPM，再计算 log2(1 + CPM) 的刺激减对照差值；供体等权汇总。", "",
                      "正值表示刺激组的归一化相对表达更高，负值表示更低。伪计数加在 CPM 尺度上，数值不能直接解释成每细胞绝对表达倍数。", ""])
        if s["gene_changes"]:
            lines.extend(gene_sections(s["gene_changes"]))
        else:
            lines.extend(["**没有有效供体配对，未形成可解释的配对响应。** 查看配对排除原因，再决定是否补齐数据或调整有依据的细胞数阈值。", ""])
        lines.extend(["## 怎样判断这些变化", "", f"生物学配对单位是 **{s['paired_donors']} 位供体**，细胞数不能代替独立重复数。跨供体 SD 描述个体间差异，不是标准误或置信区间；方向一致也不自动代表统计显著。", "",
                      "图按绝对平均变化选取少量基因；如果只出现正向基因，不代表没有负向结果。完整正负结果以上述源表为准。", "",
                      "对照与刺激来自条件特异文库，供体配对不能单独消除批次混杂。本流程沿用来源细胞注释与 singlet 标记，没有新增完整生物学 QC，也没有建立因果效应或预测准确性证据。", ""])
    elif s["kind"] == "celloracle_simulation":
        lines.extend([f"已实际完成 **{md(s['target_gene'])} {'KO' if s['mode']=='ko' else 'OE'}** 的网络模拟，使用 **{s['cells']:,} 个细胞 × {s['genes']:,} 个建模基因**。基线是模型内部 imputed_count，完整模拟表达与 delta_X 已保留。", "",
                      f"目标表达固定设为 **{fmt(s['target_setting'])}**，目标基因平均模拟变化为 **{fmt(s['target_mean_delta'])}**。这些数值处于 CellOracle 内部 log1p 原始计数再平滑的尺度，不是实验 fold change。", ""])
        if s["mode"] == "oe":
            lines.extend([f"设定依据记录为 `{md(s['target_setting_choice'])}`；请求的内部表达分位数为 `{md(s['requested_oe_percentile'])}`（空值表示未按分位数指定）。有 **{s['cells_above_target_setting']} / {s['cells']}** 个细胞的内部基线高于 OE 设定值，固定设定会使这些细胞的目标输入下调。因此不能把全部细胞都称为表达增加，也不能把该设定解释成实验可实现的倍数。", ""])
        lines.extend(["下面的基因排序排除了被直接设定的目标基因，显示其他基因的平均模拟变化；不是实测扰动差异基因。", ""])
        lines.extend(gene_sections(s["gene_changes"]))
        lines.extend(["## 位移图怎样读", "", f"平均投影位移幅度为 **{fmt(s['mean_shift_magnitude'])}**，单次随机化表达变化投影为 **{fmt(s['mean_random_shift_magnitude'])}**。随机化保持 GRN 固定，是技术对照；较大的位移不等于已证明准确性、显著性或生物学特异性。", "",
                      f"图的分组字段是 `{md(s['group_column'])}`；当前 GRN 范围记录为 `{md(s['grn_scope'])}`。字段名本身不证明细胞类型，技术板号也不是生物学重复。运行记录未建立可用于统计推断的独立生物学重复单位。", "",
                      "UMAP 箭头是模拟表达变化的投影，不是实验追踪轨迹。没有独立真实扰动数据的匹配评估，本结果不能用于靶点确证、机制结论或疗效判断。", ""])
    else:
        labels = {"prnet_mean": "PRnet 条件均值", "prnet_sample": "PRnet 单次高斯采样", "no_change": "零响应参照", "other_group_mean": "其他药物组的 demo 均值"}
        lines.extend([f"已加载模型完成 **{s['profiles']:,} 条处理表达谱 × {s['genes']:,} 个基因**的参考推理。每条处理谱沿用来源指定的配对对照。预测与实测响应均在同一官方 demo 预处理尺度上计算。", "",
                      "## 是否比简单参照更好", "", "RMSE 越低表示当前尺度上的响应误差越小；Pearson 描述变化方向的线性一致性，不能代替幅度误差。", "",
                      "| 方法 | 平均逐表达谱响应 RMSE | 平均响应 Pearson |", "| --- | ---: | ---: |"])
        for method in METHODS:
            metrics = s["metrics"][method]
            lines.append(f"| {labels[method]} | {fmt(metrics['mean_profile_rmse'])} | {fmt(metrics['mean_profile_pearson'])} |")
        verdict = {"lower_rmse": "低于零响应参照", "higher_rmse": "高于零响应参照", "tied": "与零响应参照接近"}[s["comparison"]]
        lines.extend(["", f"**PRnet 条件均值的平均 RMSE {verdict}**；模型减零响应的 RMSE 差为 **{fmt(s['rmse_difference_model_minus_no_change'])}**。逐表达谱比较：模型误差更低 {s['profiles_lower_rmse']} 条、更高 {s['profiles_higher_rmse']} 条、相同 {s['profiles_tied']} 条。这是描述性比较，不是显著性检验或药效排名。", "",
                      "正相关可以与较大的幅度误差同时出现；只有在相同数据、相同尺度和相同条件集合上比较，才能判断相对参照的增益。零响应向量为常量，Pearson 正确结果是未定义，不能把空值填成零。", "",
                      f"本次 {s['noise_draws']} 次 decoder 噪声抽样不是生物学重复；{s['profiles']} 条表达谱也未被证实为同等独立的生物学重复。", "",
                      "## 解释范围", "", "训练成员未知，demo 的 test 标签不证明独立留出。官方预处理的归一化目标来自全部 demo 表达谱，包含实测处理谱，具有明确的内部参考性质。其他药物组均值也来自当前 demo，只能作为已说明构造方式的描述性参照。", "",
                      f"有 **{s['cross_plate_profiles']} 条**来源配对跨 RNA plate，可能受批次影响。该结果不直接外推到其他样本、剂量、临床药敏或疗效；不能据此判断整个 PRnet 方法的普遍表现。", ""])
    lines.extend(["## 状态与下一步", "", f"计算状态：`{s['execution_status']}`；模型状态：`{s['model_status']}`；独立预测验证：**未评估**。这份解读不会把技术运行成功提升为科学验证通过。", "",
                  "先核对研究背景、基线和数值尺度，再查看正负变化或与简单参照的比较。需要科学结论时，另准备与训练过程关系明确的留出数据或真实扰动实验，按预先说明的方法评估。", "",
                  "## 原始记录与图表", ""])
    for relative in [*s["links"], "provenance.json"]:
        lines.append("- " + link(source, output, relative))
    for fig in s["figures"]:
        if fig["status"] == "generated":
            lines.extend("- 图：" + link(source, output, path) for path in fig["paths"])
        else:
            lines.append(f"- 图状态：`{md(fig['status'])}`；原因：{md(fig.get('reason') or '请查看源图清单')}。数值结果仍按源记录解释。")
    lines.extend(["", "本解读登记所读文件的 SHA256，并核对运行包已提供的逐产物哈希；未提供原哈希的文件仅登记本次读取值。它没有重新运行模型、重算所有原始矩阵或开展独立科学验证。相对链接依赖原分析目录与解读目录的相对位置，分享时请保留两者。", ""])
    return "\n".join(lines)


def explain(run_dir, output_dir):
    output = Path(output_dir).absolute()
    require(output.parent.is_dir(), "--output-dir 的父目录必须存在；请先创建父目录")
    output.mkdir(exist_ok=False)
    source = None
    try:
        source = Source(run_dir)
        case = source.provenance.get("case_id")
        manifest = source.json("manifest.json") if (source.root / "manifest.json").is_file() else None
        if case == "kang-ifnb-pbmc" and manifest is None:
            summary = kang_result(source)
        elif case == "prnet-reference-evaluation" and manifest and manifest.get("case_id") == case and manifest.get("backend") == "PRnet":
            summary = prnet_result(source, manifest)
        elif manifest and isinstance(manifest.get("backend"), dict) and manifest["backend"].get("name") == "CellOracle":
            summary = celloracle_result(source, manifest)
        else:
            raise ValueError("未识别受支持的完成结果：当前仅支持 Kang 供体配对、CellOracle KO/OE 和 PRnet 固定参考评估；请先查看原始运行状态")
        require(isinstance(summary.get("scale"), str) and summary["scale"].strip(), "缺少可解释的数值尺度")
        report = render(summary, source, output)
        source.verify()
        summary.update(schema_version=1, interpretation_status="completed", source_kind=source.provenance.get("source_kind"),
                       created_utc=datetime.now(timezone.utc).isoformat(), input_artifacts=source.inputs,
                       input_verification_scope="record_and_table_consistency_and_available_hashes; not_full_matrix_recalculation_or_scientific_validation",
                       script_sha256=digest(Path(__file__)), run_directory=str(source.root))
        (output / "interpretation.md").write_text(report, encoding="utf-8")
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return summary
    except Exception as exc:
        error = {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "input_artifacts": source.inputs if source else {},
                 "source_result_modified": False, "model_executed_by_reader": False}
        (output / "error.json").write_text(json.dumps(error, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="读取已完成的分析目录，生成中文结果解读；不运行模型，不改写原结果。")
    parser.add_argument("--run-dir", required=True, type=Path, help="已有完整分析目录")
    parser.add_argument("--output-dir", required=True, type=Path, help="新的解读目录；父目录必须存在")
    args = parser.parse_args(argv)
    try:
        result = explain(args.run_dir, args.output_dir)
        print(json.dumps({"status": result["interpretation_status"], "kind": result["kind"], "independent_validation": result["independent_validation"],
                          "report": str(args.output_dir / "interpretation.md")}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        print(f"结果解读失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
