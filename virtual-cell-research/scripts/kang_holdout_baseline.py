#!/usr/bin/env python3
"""Demonstrate leave-one-donor-out response prediction on fixed Kang observations.

Only a training-donor mean is fitted. This does not evaluate a pretrained virtual
cell model and does not establish external or independent biological validation.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_predictions", Path(__file__).with_name("evaluate_predictions.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def leave_one_unit_out_mean(responses):
    import numpy as np
    values = np.asarray(responses, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 3 or not np.isfinite(values).all():
        raise ValueError("Need finite response rows from at least three biological units")
    predicted = np.empty_like(values)
    memberships = []
    for test_index in range(values.shape[0]):
        train = [i for i in range(values.shape[0]) if i != test_index]
        predicted[test_index] = values[train].mean(axis=0)
        memberships.append(train)
    return predicted, memberships


def normalize_artifact_records(records):
    """Source runs can record Windows separators; never guess between aliases."""
    result = {}
    for path, record in records.items():
        normalized = path.replace("\\", "/")
        if normalized in result:
            raise ValueError("Ambiguous artifact paths after separator normalization")
        result[normalized] = record
    return result


def run_case(observed_run, output_dir):
    import numpy as np
    import pandas as pd
    from scipy import sparse
    evaluator = load_evaluator()
    root, output = Path(observed_run), Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    try:
        provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
        if provenance.get("case_id") != "kang-ifnb-pbmc" or provenance.get("source_kind") != "official_GEO_GSE96583_batch2":
            raise ValueError("Use a completed official Kang observed case, not a synthetic or arbitrary response file")
        # Check the six original resource identities against the shipped case.
        expected = json.loads((Path(__file__).resolve().parents[1] / "cases/kang-ifnb-pbmc/evidence.json").read_text(encoding="utf-8"))["sources"]
        if set(provenance.get("sources", {})) != set(expected):
            raise ValueError("Source resource set differs from the fixed Kang case")
        for key, record in expected.items():
            if provenance["sources"][key]["sha256"] != record["sha256"]:
                raise ValueError("Fixed original source hash differs: " + key)
        required = ["qc.json", "raw/paired_responses.npz", "raw/pseudobulk_counts.npz",
                    "tables/donor_pairs.csv", "tables/pseudobulk_index.csv", "tables/genes.csv"]
        checked = {}
        artifact_records = normalize_artifact_records(provenance.get("artifacts", {}))
        for rel in required:
            path = root / rel
            record = artifact_records.get(rel)
            if not record or path.stat().st_size != record["bytes"] or evaluator.digest(path) != record["sha256"]:
                raise ValueError("Observed-case artifact hash mismatch: " + rel)
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("Observed-case input unexpectedly large: " + rel)
            checked[rel] = {"sha256": record["sha256"], "bytes": record["bytes"]}
        qc = json.loads((root / "qc.json").read_text(encoding="utf-8"))
        if qc.get("status") != "completed" or qc.get("selected_cell_type") != "CD14+ Monocytes" or qc.get("paired_donors") != 8:
            raise ValueError("This tutorial requires the completed 8-donor CD14+ Monocytes case")
        with np.load(root / "raw/paired_responses.npz", allow_pickle=False) as archive:
            delta = archive["observed_delta"]
            donors, genes = archive["donor_ids"].astype(str), archive["gene_ids"].astype(str)
        if delta.shape != (8, 35635) or not np.isfinite(delta).all() or len(set(donors)) != 8 or len(set(genes)) != len(genes):
            raise ValueError("Unexpected fixed-case dimensions, duplicate IDs or invalid response")
        gene_table = pd.read_csv(root / "tables/genes.csv", dtype=str, keep_default_na=False)
        if not np.array_equal(gene_table.gene_id.to_numpy(), genes):
            raise ValueError("Gene axis disagrees with saved gene table")
        groups = pd.read_csv(root / "tables/pseudobulk_index.csv", dtype=str, keep_default_na=False)
        pairs = pd.read_csv(root / "tables/donor_pairs.csv", dtype=str, keep_default_na=False)
        if not groups.group_id.is_unique or not pairs.donor.is_unique:
            raise ValueError("Duplicated pseudobulk or donor pair identifiers")
        counts = sparse.load_npz(root / "raw/pseudobulk_counts.npz").tocsr()
        if counts.shape != (len(groups), len(genes)) or (counts.data < 0).any() or not np.isfinite(counts.data).all() or not np.equal(counts.data, np.rint(counts.data)).all():
            raise ValueError("Saved pseudobulk must be finite nonnegative integer counts on the declared axes")
        group_index = {s: i for i, s in enumerate(groups.group_id)}
        reconstructed = []
        for donor in donors:
            pair = pairs.loc[pairs.donor == donor]
            if len(pair) != 1 or pair.iloc[0].status != "included":
                raise ValueError("Every evaluated donor needs one included paired observation")
            pair = pair.iloc[0]
            vectors = []
            for condition in ("ctrl", "stim"):
                i = group_index[pair[condition + "_group_id"]]
                info = groups.iloc[i]
                if info.donor != donor or info.condition != condition or info.cell_type != "CD14+ Monocytes":
                    raise ValueError("Pseudobulk index crosses donor/condition/cell type")
                row = counts.getrow(i).toarray().ravel().astype(float)
                if row.sum() <= 0:
                    raise ValueError("Zero pseudobulk library")
                vectors.append(np.log2(1 + 1e6 * row / row.sum()))
            reconstructed.append(vectors[1] - vectors[0])
        reconstructed = np.asarray(reconstructed)
        if not np.array_equal(reconstructed, delta):
            raise ValueError("Saved responses differ from donor-paired log2(1+CPM) reconstructed from counts")
        predicted, training = leave_one_unit_out_mean(delta)
        inputs = output / "evaluation-input"
        inputs.mkdir()
        sample_ids = ["CD14:" + donor for donor in donors]
        for name, values in (("observed.csv.gz", delta), ("predicted.csv.gz", predicted)):
            with gzip.open(inputs / name, "wt", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sample_id", *genes])
                writer.writerows([[sample_ids[i], *[format(v, ".17g") for v in row]] for i, row in enumerate(values)])
        metadata = [{"sample_id": sample_ids[i], "unit_id": donor, "fold_id": "leave_out_" + donor} for i, donor in enumerate(donors)]
        evaluator.write_rows(inputs / "metadata.csv", ["sample_id", "unit_id", "fold_id"], metadata)
        members, fits = [], []
        for i, train in enumerate(training):
            fold = metadata[i]["fold_id"]
            for j in train:
                members.append({"fold_id": fold, "role": "train", "sample_id": sample_ids[j], "unit_id": donors[j]})
            members.append({"fold_id": fold, "role": "evaluation", "sample_id": sample_ids[i], "unit_id": donors[i]})
            fits.append({"fold_id": fold, "held_out_donor": donors[i], "training_donors": donors[train].tolist(),
                         "training_response_float64_le_sha256": hashlib.sha256(np.ascontiguousarray(delta[train], dtype="<f8").tobytes()).hexdigest()})
        evaluator.write_rows(inputs / "split_membership.csv", ["fold_id", "role", "sample_id", "unit_id"], members)
        declared = {"scale": "log2(1 + CPM_stim) - log2(1 + CPM_ctrl), full-source-gene library denominator",
                    "context": "GSE96583 batch2; CD14+ Monocytes; 8 lupus donors; 6h IFN-beta versus control"}
        settings = {"schema_version": 1, "input_kind": "response", "observed": declared, "predicted": declared,
                    "unit_definition": "One donor with a paired ctrl/stim pseudobulk response; cells are not independent units.",
                    "notes": "Leave-one-donor-out mean of the other seven responses. Folds overlap in training donors; not eight independent experiments or external validation."}
        evaluator.write_json(inputs / "settings.json", settings)
        evaluator.write_json(output / "fitting.json", {"estimator": "leave_one_donor_out_training_mean", "hyperparameters_tuned": False,
            "gene_selection": "All 35635 source gene IDs retained, including shared zeros; no gene selection uses held-out responses.",
            "preprocessing": "Each donor-condition library is normalized using its own full-source gene sum. No population-fitted normalization or response fitting uses held-out donor.",
            "folds": fits, "script_sha256": evaluator.digest(__file__), "observed_artifacts_verified": checked,
            "response_reconstruction_max_abs_error": float(np.max(np.abs(reconstructed - delta))),
            "source_record_claim": "Original source identities verified against case records; output hashes and all donor deltas recomputed from saved pseudobulk. Raw single-cell files are not re-read here.",
            "independent_validation": "not_assessed"})
        result = evaluator.run_evaluation(inputs / "observed.csv.gz", inputs / "predicted.csv.gz", inputs / "metadata.csv",
            inputs / "settings.json", output / "evaluation", membership_path=inputs / "split_membership.csv")
        figure = {"status": "not_generated"}
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            table = pd.read_csv(output / "evaluation/tables/unit_metrics.csv", dtype={"unit_id": str})
            predicted_rows = table[table.method == "prediction"].set_index("unit_id").loc[donors]
            zero_rows = table[table.method == "no_change"].set_index("unit_id").loc[donors]
            x = np.arange(len(donors))
            with plt.rc_context({"svg.fonttype": "none"}):
                fig, ax = plt.subplots(figsize=(10, 4.8))
                ax.bar(x - .19, predicted_rows.rmse, width=.38, color="#24577A", label="Mean of other seven donors")
                ax.bar(x + .19, zero_rows.rmse, width=.38, color="#A0A5AB", label="No-change reference")
                ax.set_xticks(x, donors)
                ax.set_xlabel("Held-out donor (paired biological unit)")
                ax.set_ylabel("Response RMSE across all 35,635 genes")
                ax.set_title("Kang CD14+ leave-one-donor-out baseline\nShared experiment; not external model validation")
                ax.legend(frameon=False)
                fig.tight_layout()
                fig.savefig(output / "holdout_metrics.svg")
                fig.savefig(output / "holdout_metrics.png", dpi=150)
                plt.close(fig)
            figure = {"status": "generated", "svg": "holdout_metrics.svg", "png": "holdout_metrics.png",
                      "source": "evaluation/tables/unit_metrics.csv"}
        except Exception as error:
            figure = {"status": "failed", "reason": str(error)}
        evaluator.write_json(output / "figure_manifest.json", figure)
        p, z = result["metrics"]["prediction"], result["metrics"]["no_change"]
        image = "![留出供体误差比较](holdout_metrics.png)\n\n" if figure["status"] == "generated" else "绘图未完成；完整数值仍保留。\n\n"
        report = f"""# Kang 留一供体基线教学\n\n每次留出一位供体，仅用另外七位的观测响应均值预测该供体。共八折，全部 35,635 个来源基因保留。\n\n{image}平均响应 RMSE：训练供体均值 **{p['rmse']:.6f}**，零响应 **{z['rmse']:.6f}**；预测响应平均 Pearson **{p['pearson']:.6f}**。数值是八位供体等权平均，不含显著性检验。全基因中包含共零和无响应基因，不能把全基因较低误差写成每个响应基因都预测准确。\n\n查看[完整评估](evaluation/report.md)、[每折训练成员](evaluation-input/split_membership.csv)、[实际拟合记录](fitting.json)和[单位指标](evaluation/tables/unit_metrics.csv)。本例只拟合一个简单均值基线，没有运行 CellOracle 或 PRnet。\n\n八折共享训练供体，不能作为八次独立实验。本例沿用同一实验的八位狼疮患者与条件特异文库，供体留出不能消除文库/条件混杂，也不代表跨队列或跨实验泛化。未使用外部独立实验验证模型，独立科学验证状态仍为未评估。\n"""
        (output / "report.md").write_text(report, encoding="utf-8")
        return result
    except Exception as error:
        evaluator.write_json(output / "error.json", {"status": "failed", "message": str(error), "independent_validation": "not_assessed"})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Use the other seven Kang donors to predict each held-out donor; baseline teaching only.")
    parser.add_argument("--observed-run", type=Path, required=True, help="Completed official Kang CD14+ observed-run directory")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output directory")
    args = parser.parse_args(argv)
    try:
        result = run_case(args.observed_run, args.output_dir)
    except Exception as error:
        print(f"Holdout tutorial stopped: {error}", file=sys.stderr)
        return 2
    print(f"Completed {result['biological_units']} held-out donors; independent validation remains not_assessed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
