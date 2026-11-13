#!/usr/bin/env python3
"""Evaluate imported predictions on explicit axes, scales and biological units.

This entry audits files and declared split membership. It does not run a model,
inspect its training process, or certify independent scientific validation.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys


MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_VALUES = 5_000_000


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def read_settings(path):
    path = Path(path)
    if path.stat().st_size > 256 * 1024:
        raise ValueError("Settings JSON exceeds 256 KiB")
    data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + x)))
    allowed = {"schema_version", "input_kind", "observed", "predicted", "baseline", "unit_definition", "notes"}
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError("Settings must be an object with documented fields only")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if data.get("input_kind") not in {"response", "expression"}:
        raise ValueError("input_kind must be response or expression")
    _text(data.get("unit_definition"), "unit_definition")
    keys = ["observed", "predicted"] + (["baseline"] if data["input_kind"] == "expression" else [])
    if data["input_kind"] == "response" and "baseline" in data:
        raise ValueError("Response input must not declare a second baseline")
    for key in keys:
        info = data.get(key)
        if not isinstance(info, dict) or set(info) != {"scale", "context"}:
            raise ValueError(key + " must declare exactly scale and context")
        for field in ("scale", "context"):
            _text(info[field], key + "." + field)
    if any(data[key] != data["observed"] for key in keys[1:]):
        raise ValueError("Observed, predicted and baseline scale/context declarations must match exactly")
    return data


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError(label + " must be nonblank text without surrounding whitespace/control characters")
    return value


def read_rows(path):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Input exceeds {MAX_FILE_BYTES} bytes; use a deliberately prepared smaller evaluation")
    names = path.name.lower()
    base = names[:-3] if names.endswith(".gz") else names
    if not base.endswith((".csv", ".tsv")):
        raise ValueError("Use CSV/TSV, optionally gzip compressed")
    opener = gzip.open if names.endswith(".gz") else open
    delimiter = "\t" if base.endswith(".tsv") else ","
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError("Empty table: " + path.name)
        if not header or len(header) != len(set(header)):
            raise ValueError("Table header is empty or contains duplicate columns")
        for name in header:
            _text(name, "column name")
        yield header
        count = 0
        for row in reader:
            if len(row) != len(header):
                raise ValueError("Ragged/blank table row in " + path.name)
            count += len(row)
            if count > MAX_VALUES + 2 * 100_000:
                raise ValueError("Decoded input exceeds bounded table size")
            yield row


def read_matrix(path):
    import numpy as np
    rows = iter(read_rows(path))
    header = next(rows)
    if header[0] != "sample_id" or len(header) < 3:
        raise ValueError("Matrix needs sample_id followed by at least two unique gene ID columns")
    samples, values = [], []
    seen = set()
    for row in rows:
        sample = _text(row[0], "sample_id")
        if sample in seen:
            raise ValueError("Duplicate sample_id: " + sample)
        seen.add(sample)
        samples.append(sample)
        if len(samples) * (len(header) - 1) > MAX_VALUES:
            raise ValueError(f"Matrix exceeds {MAX_VALUES} values; evaluate a declared smaller set")
        try:
            values.append([float(x) for x in row[1:]])
        except ValueError as e:
            raise ValueError("Matrix has missing/nonnumeric values") from e
    if not samples:
        raise ValueError("Matrix contains no samples")
    array = np.asarray(values, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError("Matrix contains NaN/Inf")
    return samples, header[1:], array


def align_matrix(reference_samples, reference_genes, matrix):
    samples, genes, array = matrix
    if set(samples) != set(reference_samples) or set(genes) != set(reference_genes):
        raise ValueError("Matrix sample/gene ID sets differ; no implicit intersection or positional matching")
    si, gi = {s: i for i, s in enumerate(samples)}, {g: i for i, g in enumerate(genes)}
    return array[[si[s] for s in reference_samples]][:, [gi[g] for g in reference_genes]]


def read_metadata(path, samples):
    rows = iter(read_rows(path))
    header = next(rows)
    if not {"sample_id", "unit_id"}.issubset(header):
        raise ValueError("Metadata requires sample_id and unit_id")
    records = {}
    for row in rows:
        d = dict(zip(header, row))
        for key in ("sample_id", "unit_id"):
            _text(d[key], key)
        if "fold_id" in d:
            _text(d["fold_id"], "fold_id")
        if d["sample_id"] in records:
            raise ValueError("Duplicate metadata sample_id")
        records[d["sample_id"]] = d
    if set(records) != set(samples):
        raise ValueError("Metadata sample IDs must exactly match evaluated samples")
    return header, [records[s] for s in samples]


def audit_membership(path, metadata):
    if path is None:
        return {"status": "not_supplied", "training_process_verified": False,
                "independent_validation": "not_assessed"}
    if any("fold_id" not in row for row in metadata):
        raise ValueError("Membership audit requires metadata.fold_id")
    rows = iter(read_rows(path))
    header = next(rows)
    if set(header) != {"fold_id", "role", "sample_id", "unit_id"}:
        raise ValueError("Membership requires exactly fold_id,role,sample_id,unit_id")
    folds, seen = {}, set()
    unit_by_sample = {r["sample_id"]: r["unit_id"] for r in metadata}
    for row in rows:
        d = dict(zip(header, row))
        for key in header:
            _text(d[key], key)
        if d["role"] not in {"train", "evaluation"}:
            raise ValueError("Membership role must be train or evaluation")
        if d["sample_id"] in unit_by_sample and unit_by_sample[d["sample_id"]] != d["unit_id"]:
            raise ValueError("A sample has inconsistent biological-unit membership")
        unit_by_sample[d["sample_id"]] = d["unit_id"]
        key = (d["fold_id"], d["role"], d["sample_id"])
        if key in seen:
            raise ValueError("Duplicate split membership record")
        seen.add(key)
        folds.setdefault(d["fold_id"], {"train": [], "evaluation": []})[d["role"]].append(d)
    expected_folds = {r["fold_id"] for r in metadata}
    if set(folds) != expected_folds:
        raise ValueError("Membership folds do not match evaluated metadata")
    summaries = []
    for fold_id, roles in sorted(folds.items()):
        train, test = roles["train"], roles["evaluation"]
        if not train or not test:
            raise ValueError("Each recorded fold requires training and evaluation members")
        if {x["sample_id"] for x in train} & {x["sample_id"] for x in test}:
            raise ValueError("Training/evaluation sample leakage in fold " + fold_id)
        if {x["unit_id"] for x in train} & {x["unit_id"] for x in test}:
            raise ValueError("Training/evaluation biological-unit leakage in fold " + fold_id)
        expected = {(r["sample_id"], r["unit_id"]) for r in metadata if r["fold_id"] == fold_id}
        if {(r["sample_id"], r["unit_id"]) for r in test} != expected:
            raise ValueError("Evaluation membership disagrees with metadata")
        summaries.append({"fold_id": fold_id, "training_samples": len(train),
                          "training_units": len({x["unit_id"] for x in train}),
                          "evaluation_samples": len(test), "evaluation_units": len({x["unit_id"] for x in test})})
    return {"status": "passed_recorded_membership", "folds": summaries,
            "training_process_verified": False, "independent_validation": "not_assessed",
            "scope": "Disjointness of supplied records only; does not inspect actual model training, feature selection or hyperparameter tuning."}


def _rms(values):
    import numpy as np
    scale = float(np.max(np.abs(values)))
    return 0.0 if scale == 0 else scale * float(np.sqrt(np.mean((values / scale) ** 2)))


def metrics(observed, predicted):
    import numpy as np
    observed, predicted = np.asarray(observed, dtype=float), np.asarray(predicted, dtype=float)
    if observed.shape != predicted.shape or observed.ndim != 1 or observed.size < 2:
        raise ValueError("Metric vectors must have matching one-dimensional gene axes")
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise ValueError("Metric vectors must be finite")
    with np.errstate(over="ignore", invalid="ignore"):
        error = predicted - observed
    if not np.isfinite(error).all():
        raise ValueError("Response error exceeds finite numeric range")
    scale_o, scale_p = float(np.max(np.abs(observed))), float(np.max(np.abs(predicted)))
    oo = observed / scale_o if scale_o else observed.copy()
    pp = predicted / scale_p if scale_p else predicted.copy()
    oo, pp = oo - oo.mean(), pp - pp.mean()
    denominator = float(np.linalg.norm(oo) * np.linalg.norm(pp))
    corr = float(np.clip(np.dot(oo, pp) / denominator, -1, 1)) if denominator else None
    nonzero = observed != 0
    direction = float(np.mean(np.sign(observed[nonzero]) == np.sign(predicted[nonzero]))) if nonzero.any() else None
    scale_error = float(np.max(np.abs(error)))
    mae = scale_error * float(np.mean(np.abs(error / scale_error))) if scale_error else 0.0
    return {"rmse": _rms(error), "mae": mae, "pearson": corr,
            "direction_agreement_nonzero_observed": direction, "nonzero_observed_genes": int(nonzero.sum())}


def mean_defined(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def aggregate_metrics(observed, predicted, metadata):
    import numpy as np
    profiles = []
    for i, info in enumerate(metadata):
        for method, row in (("prediction", predicted[i]), ("no_change", np.zeros_like(observed[i]))):
            profiles.append({"sample_id": info["sample_id"], "unit_id": info["unit_id"], "method": method,
                             **metrics(observed[i], row)})
    units = []
    fields = ("rmse", "mae", "pearson", "direction_agreement_nonzero_observed")
    for method in ("prediction", "no_change"):
        for unit in sorted({r["unit_id"] for r in metadata}):
            selected = [r for r in profiles if r["method"] == method and r["unit_id"] == unit]
            units.append({"unit_id": unit, "method": method, "samples": len(selected),
                          **{field: mean_defined([r[field] for r in selected]) for field in fields},
                          "pearson_defined_samples": sum(r["pearson"] is not None for r in selected)})
    summary = {}
    for method in ("prediction", "no_change"):
        selected = [r for r in units if r["method"] == method]
        summary[method] = {field: mean_defined([r[field] for r in selected]) for field in fields}
        summary[method]["units"] = len(selected)
        summary[method]["pearson_defined_units"] = sum(r["pearson"] is not None for r in selected)
    summary["rmse_gain_over_no_change"] = summary["no_change"]["rmse"] - summary["prediction"]["rmse"]
    return profiles, units, summary


def write_rows(path, header, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def run_evaluation(observed_path, predicted_path, metadata_path, settings_path, output_dir, *, baseline_path=None, membership_path=None):
    import numpy as np
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    sources = {"observed": Path(observed_path), "predicted": Path(predicted_path),
               "metadata": Path(metadata_path), "settings": Path(settings_path)}
    if baseline_path is not None:
        sources["baseline"] = Path(baseline_path)
    if membership_path is not None:
        sources["split_membership"] = Path(membership_path)
    try:
        source_records = {key: {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest(path)} for key, path in sources.items()}
        settings = read_settings(settings_path)
        expression = settings["input_kind"] == "expression"
        if expression != (baseline_path is not None):
            raise ValueError("Expression inputs require one aligned baseline; response inputs must omit baseline")
        samples, genes, observed = read_matrix(observed_path)
        predicted = align_matrix(samples, genes, read_matrix(predicted_path))
        baseline = align_matrix(samples, genes, read_matrix(baseline_path)) if expression else np.zeros_like(observed)
        metadata_header, metadata = read_metadata(metadata_path, samples)
        split = audit_membership(membership_path, metadata)
        for key, path in sources.items():
            if path.stat().st_size != source_records[key]["bytes"] or digest(path) != source_records[key]["sha256"]:
                raise ValueError("Input changed while reading: " + key)
        with np.errstate(over="ignore", invalid="ignore"):
            observed_response, predicted_response = observed - baseline, predicted - baseline
        if not np.isfinite(observed_response).all() or not np.isfinite(predicted_response).all():
            raise ValueError("Subtracted responses are not finite")
        profile_rows, unit_rows, summary = aggregate_metrics(observed_response, predicted_response, metadata)
        (output / "raw").mkdir()
        (output / "tables").mkdir()
        np.savez_compressed(output / "raw/aligned_responses.npz", sample_ids=np.asarray(samples), gene_ids=np.asarray(genes),
                            observed_input=observed, predicted_input=predicted, baseline=baseline,
                            observed_response=observed_response, predicted_response=predicted_response)
        write_rows(output / "tables/profile_metrics.csv", list(profile_rows[0]), profile_rows)
        write_rows(output / "tables/unit_metrics.csv", list(unit_rows[0]), unit_rows)
        write_rows(output / "tables/evaluation_metadata.csv", metadata_header, metadata)
        write_rows(output / "tables/gene_index.csv", ["gene_id"], [{"gene_id": g} for g in genes])
        result = {"schema_version": 1, "status": "completed", "task": "imported_prediction_evaluation",
                  "model_status": "not_run", "prediction_status": "imported", "independent_validation": "not_assessed",
                  "samples": len(samples), "genes": len(genes), "biological_units": len({r["unit_id"] for r in metadata}),
                  "settings": settings, "split_audit": split, "metrics": summary,
                  "aggregation": "Compute per-sample metrics, mean within each biological unit, then mean units equally; this is mean RMSE, not pooled RMSE.",
                  "direction_rule": "Exact nonzero observed responses only; a zero prediction is incorrect for a nonzero observed response. No biological significance threshold.",
                  "undefined_correlations": "Constant vectors have undefined Pearson, stored as null/empty; valid-unit denominator is reported.",
                  "limitations": ["Scale/context declarations are checked for consistency, not inferred or biologically certified from values.",
                                  "Split files audit supplied memberships only; actual model training, tuning, feature selection and preprocessing leakage are not certified.",
                                  "Shared donors, batches, experiments or response conditions can remain dependent. No p-values, confidence intervals or efficacy claims."]}
        write_json(output / "evaluation.json", result)
        write_json(output / "qc.json", {"status": "passed_file_checks", "axis_alignment": "exact_ID_sets_reordered",
                                       "all_values_finite": True, "split_audit": split, "independent_validation": "not_assessed"})
        p, z = summary["prediction"], summary["no_change"]
        corr = "未定义" if p["pearson"] is None else f"{p['pearson']:.6f}"
        verdict = "低于零响应参照" if summary["rmse_gain_over_no_change"] > 0 else "未低于零响应参照"
        report = f"""# 预测响应评估\n\n本次评估已提供的预测，未运行模型。共 {len(samples)} 个样本、{len(genes)} 个基因、{result['biological_units']} 个声明的生物学单位。独立科学验证仍为未评估。\n\n## 先看结果\n\n| 方法 | 单位等权平均 RMSE，越低越好 | 单位等权平均 MAE | 单位等权平均响应 Pearson |\n| --- | ---: | ---: | ---: |\n| 导入预测 | {p['rmse']:.6f} | {p['mae']:.6f} | {corr} |\n| 零响应参照 | {z['rmse']:.6f} | {z['mae']:.6f} | 未定义，响应恒为零 |\n\n本次预测的平均 RMSE **{verdict}**。先在每个样本计算指标，再在同一单位内平均，最后对单位等权平均；不能将它写成全部数值合并后的 RMSE。相关系数为正并不保证幅度误差更小。\n\n## 数据与划分\n\n- 输入形式：`{settings['input_kind']}`。表达形式先减去同 ID、同尺度的指定基线；响应形式不再重复减基线。\n- 尺度：{settings['observed']['scale']}。\n- 背景：{settings['observed']['context']}。\n- 生物学单位定义：{settings['unit_definition']}。\n- 成员记录审计：`{split['status']}`。它只核对提交文件中的样本/单位是否跨训练与评估集合，不证明实际训练过程没有泄漏。\n\n## 怎样继续检查\n\n查看[单位指标](tables/unit_metrics.csv)与[逐样本指标](tables/profile_metrics.csv)，检查平均值是否掩盖个别单位的差异。Pearson 空值表示恒定向量，不要补为零；每个单位的有效样本数已记录。方向一致率只在实测非零基因上计算，零预测视为未匹配方向；这不是显著性或疗效判断。\n\n完整 ID 及数值在[数组](raw/aligned_responses.npz)、[样本元信息](tables/evaluation_metadata.csv)和[基因索引](tables/gene_index.csv)。用 `numpy.load(..., allow_pickle=False)` 读取数组。复核[完整评估](evaluation.json)、[QC](qc.json)及[来源记录](provenance.json)。\n\n本入口不执行随机划分、不训练模型、不自动选择效果最好的基因或条件，也不认证用户声明的尺度和来源。正式独立评估还需核实训练、调参、特征选择与全部预处理使用的样本范围；共享实验与批次影响需按研究设计处理。\n"""
        (output / "report.md").write_text(report, encoding="utf-8")
        artifacts = {p.relative_to(output).as_posix(): digest(p) for p in output.rglob("*") if p.is_file()}
        provenance = {"schema_version": 1, "project": "Virtual Cell Research", "started_utc": started,
                      "completed_utc": datetime.now(timezone.utc).isoformat(), "sources": source_records,
                      "script_sha256": digest(__file__), "python": platform.python_version(), "numpy": importlib.metadata.version("numpy"),
                      "python_executable": sys.executable, "argv": sys.argv, "artifacts_sha256": artifacts,
                      "independent_validation": "not_assessed"}
        write_json(output / "provenance.json", provenance)
        (output / "errors.jsonl").write_text("", encoding="utf-8")
        return result
    except Exception as error:
        write_json(output / "error.json", {"status": "failed", "error_type": type(error).__name__, "message": str(error),
                                           "model_status": "not_run", "independent_validation": "not_assessed"})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare imported observed/predicted responses with ID, scale and split checks; never certify independent validation.")
    parser.add_argument("--observed", type=Path, required=True)
    parser.add_argument("--predicted", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True, help="CSV/TSV with sample_id,unit_id; fold_id required for split audit")
    parser.add_argument("--settings", type=Path, required=True, help="JSON with exact scale/context declarations and unit definition")
    parser.add_argument("--baseline", type=Path, help="Required only when input_kind=expression")
    parser.add_argument("--split-membership", type=Path, help="CSV/TSV: fold_id,role,sample_id,unit_id; role train|evaluation")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing paths are not overwritten")
    args = parser.parse_args(argv)
    try:
        result = run_evaluation(args.observed, args.predicted, args.metadata, args.settings, args.output_dir,
                                baseline_path=args.baseline, membership_path=args.split_membership)
    except Exception as error:
        print(f"Evaluation stopped: {error}", file=sys.stderr)
        return 2
    print(f"Evaluated {result['samples']} samples across {result['biological_units']} units; independent validation remains not_assessed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
