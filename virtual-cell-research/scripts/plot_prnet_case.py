#!/usr/bin/env python3
"""Plot a completed fixed PRnet reference run, checking IDs and numerical values.

This entry point reads actual inference artifacts; it does not run or simulate a
model. Heatmap selection is descriptive. All treatment profiles enter the paired
RMSE panels, including every profile for which the zero-response baseline wins.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import textwrap

import numpy as np
import pandas as pd

SCALE = "official_demo_normalize_total_median_then_log1p"
NAVY, BLUE, TEAL, ORANGE, GRAY = "#17324D", "#276FBF", "#128C87", "#D87936", "#737F8B"
INPUT_FILES = (
    "manifest.json", "qc.json", "validation.json", "raw/reference_predictions.npz",
    "tables/condition_index.csv", "tables/gene_index.csv", "tables/profile_metrics.csv",
)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _unique_strings(values, name):
    values = np.asarray(values)
    if values.ndim != 1 or values.dtype.kind not in "US" or not len(values):
        raise ValueError(f"{name} must contain nonempty string IDs")
    if len(set(values)) != len(values) or any(not x.strip() for x in values.tolist()):
        raise ValueError(f"{name} contains duplicate or empty IDs")
    return values.astype(str)


def align_and_check(arrays, conditions, genes):
    """Join source tables by ID, then verify the saved treatment/control deltas.

    Table order may differ. Missing IDs, swapped paired controls, and altered
    response values are errors, not reasons to guess a new row alignment.
    """
    profiles = _unique_strings(arrays["profile_ids"], "profile_ids")
    source_ids = _unique_strings(arrays["source_profile_ids"], "source_profile_ids")
    gene_ids = _unique_strings(arrays["gene_ids"], "gene_ids")
    if not conditions.source_profile_id.is_unique or set(conditions.source_profile_id) != set(profiles):
        raise ValueError("condition_index profile IDs differ from NPZ")
    if not genes.gene_id.is_unique or set(genes.gene_id) != set(gene_ids):
        raise ValueError("gene_index gene IDs differ from NPZ")
    conditions = conditions.set_index("source_profile_id").loc[profiles].copy()
    genes = genes.set_index("gene_id").loc[gene_ids].copy()
    for key, column in (("paired_control_ids", "paired_control_index"), ("condition_ids", "condition_id")):
        if not np.array_equal(arrays[key].astype(str), conditions[column].to_numpy(dtype=str)):
            raise ValueError(f"{key} do not match ID-aligned condition_index")
    if "exclusion_groups" in arrays and not np.array_equal(arrays["exclusion_groups"].astype(str), conditions.exclusion_group.to_numpy(dtype=str)):
        raise ValueError("Drug exclusion groups do not match ID-aligned condition_index")
    lookup = {value: i for i, value in enumerate(source_ids)}
    if any(x not in lookup for x in profiles) or any(x not in lookup for x in arrays["paired_control_ids"]):
        raise ValueError("Treatment or paired-control ID is missing from source profiles")
    treatment_positions = [lookup[x] for x in profiles]
    control_positions = [lookup[x] for x in arrays["paired_control_ids"]]
    if set(arrays["paired_control_ids"]) & set(profiles):
        raise ValueError("A treatment profile was used as a paired control")
    expected_shape = (len(profiles), len(gene_ids))
    for key in ("baseline", "observed_post", "observed_delta", "predicted_post_mean", "predicted_delta"):
        if arrays[key].shape != expected_shape or not np.isfinite(arrays[key]).all():
            raise ValueError(f"Invalid shape or nonfinite values in {key}")
    if arrays["processed_X"].shape != (len(source_ids), len(gene_ids)):
        raise ValueError("Processed source axes do not match saved IDs")
    if not np.array_equal(arrays["baseline"], arrays["processed_X"][control_positions]):
        raise ValueError("Saved baseline differs from its paired control")
    if not np.array_equal(arrays["observed_post"], arrays["processed_X"][treatment_positions]):
        raise ValueError("Observed post-treatment rows do not match source profile IDs")
    for delta, post in (("observed_delta", "observed_post"), ("predicted_delta", "predicted_post_mean")):
        expected = arrays[post].astype(np.float64) - arrays["baseline"]
        if not np.allclose(arrays[delta], expected, atol=1e-12, rtol=0):
            raise ValueError(f"{delta} is inconsistent with post-treatment minus paired-control values")
    return conditions, genes


def verify_metrics(arrays, table, summary):
    """Recompute all paired errors; reject scale changes and CSV/NPZ mismatch."""
    if set(table["scale"]) != {SCALE}:
        raise ValueError("Profile metrics use a different response scale")
    if table.duplicated(["source_profile_id", "method"]).any():
        raise ValueError("Duplicate profile/method rows in saved metrics")
    observed = arrays["observed_delta"].astype(np.float64)
    predictions = {
        "prnet_mean": arrays["predicted_delta"],
        "prnet_sample": arrays["gaussian_sample_delta"],
        "no_change": np.zeros_like(observed),
        "other_group_mean": arrays["other_group_mean_delta"],
    }
    if set(table.method) != set(predictions):
        raise ValueError("Saved metrics have missing or unexpected methods")
    result = {}
    for method, prediction in predictions.items():
        if prediction.shape != observed.shape or not np.isfinite(prediction).all():
            raise ValueError(f"{method} prediction axes or values are invalid")
        rows = table.loc[table.method.eq(method)].set_index("source_profile_id")
        if set(rows.index) != set(arrays["profile_ids"]):
            raise ValueError(f"{method} is missing treatment profiles")
        rows = rows.loc[arrays["profile_ids"]]
        if not np.array_equal(rows.condition_id.to_numpy(dtype=str), arrays["condition_ids"]):
            raise ValueError(f"{method} metrics have misaligned condition IDs")
        rmse = np.linalg.norm(prediction.astype(np.float64) - observed, axis=1) / np.sqrt(observed.shape[1])
        mae = np.mean(np.abs(prediction.astype(np.float64) - observed), axis=1)
        for name, values in (("rmse", rmse), ("mae", mae)):
            if not np.allclose(rows[name], values, atol=1e-12, rtol=1e-12):
                raise ValueError(f"{method} {name} does not match the complete NPZ")
        if not np.isclose(rmse.mean(), summary[method]["mean_profile_rmse"], atol=1e-12, rtol=1e-12):
            raise ValueError(f"{method} summary RMSE does not match the complete NPZ")
        if method == "no_change" and not rows.pearson.isna().all():
            raise ValueError("Zero-response Pearson must remain undefined")
        result[method] = rmse
    return result


def select_heatmap(arrays, conditions, gene_count=12, profile_count=10):
    """Select without examining prediction quality or selecting winning profiles.

    Select evenly spaced ranks of alias-exclusion groups sorted by source drug
    name and pert_id. Within a group use the lowest dose, then time, plate and ID.
    Select genes by mean absolute observed response over ALL treatment profiles.
    """
    frame = conditions.reset_index()
    frame["name_key"] = frame.pert_iname.str.strip().str.casefold()
    frame = frame.sort_values(["name_key", "pert_id", "dose", "pert_time", "rna_plate", "source_profile_id"], kind="stable")
    representatives = frame.drop_duplicates("exclusion_group")
    count = min(profile_count, len(representatives))
    ranks = np.linspace(0, len(representatives) - 1, count, dtype=int)
    selected = representatives.iloc[ranks]
    index = {p: i for i, p in enumerate(arrays["profile_ids"])}
    profile_positions = np.array([index[p] for p in selected.source_profile_id], dtype=int)
    amplitudes = np.abs(arrays["observed_delta"]).mean(axis=0)
    gene_positions = np.lexsort((arrays["gene_ids"], -amplitudes))[:min(gene_count, len(amplitudes))]
    return profile_positions, gene_positions, ranks, amplitudes


def load_run(run_dir):
    run_dir = Path(run_dir)
    provenance = json.loads((run_dir / "provenance.json").read_text())
    hashes = {}
    for name in INPUT_FILES:
        path = run_dir / name
        recorded = provenance.get("artifacts", {}).get(name)
        actual = sha256_file(path)
        if not recorded or actual != recorded["sha256"] or path.stat().st_size != recorded["bytes"]:
            raise ValueError(f"Run artifact no longer matches provenance: {name}")
        hashes[name] = {"sha256": actual, "bytes": path.stat().st_size}
    records = {key: json.loads((run_dir / f"{key}.json").read_text()) for key in ("manifest", "qc", "validation")}
    manifest = records["manifest"]
    if manifest.get("case_id") != "prnet-reference-evaluation" or manifest.get("status") != "completed" or manifest.get("model_status") != "executed" or manifest.get("prediction_status") != "success":
        raise ValueError("A completed real PRnet reference inference run is required")
    if manifest.get("scale") != SCALE:
        raise ValueError("Unsupported inference response scale")
    with np.load(run_dir / "raw/reference_predictions.npz", allow_pickle=False) as archive:
        arrays = {key: archive[key].copy() for key in archive.files}
    for key, values in arrays.items():
        if values.dtype.kind in "fciu" and not np.isfinite(values).all():
            raise ValueError(f"Full NPZ contains nonfinite values in {key}")
    if arrays["observed_delta"].shape != (661, 978) or arrays["source_X"].shape != (681, 978):
        raise ValueError("The fixed HT115 reference axes are not 661 treatments / 681 source profiles / 978 genes")
    conditions = pd.read_csv(run_dir / "tables/condition_index.csv", dtype={"source_profile_id": str, "paired_control_index": str, "condition_id": str})
    genes = pd.read_csv(run_dir / "tables/gene_index.csv", dtype={"gene_id": str})
    conditions, genes = align_and_check(arrays, conditions, genes)
    metrics = pd.read_csv(run_dir / "tables/profile_metrics.csv", dtype={"source_profile_id": str, "condition_id": str})
    errors = verify_metrics(arrays, metrics, records["validation"]["metrics"])
    if records["qc"]["profiles"] != len(conditions) or records["qc"]["genes"] != len(genes):
        raise ValueError("QC counts disagree with the checked numerical axes")
    return arrays, conditions, genes, errors, records, provenance, hashes


def make_source(arrays, conditions, genes, errors, records):
    rows, columns, ranks, amplitudes = select_heatmap(arrays, conditions)
    measured = arrays["observed_delta"][np.ix_(rows, columns)]
    predicted = arrays["predicted_delta"][np.ix_(rows, columns)]
    selected = []
    fields = ("pert_id", "pert_iname", "dose", "pert_dose_unit", "pert_time", "pert_time_unit", "rna_plate", "rna_well", "paired_control_index", "condition_id", "exclusion_group", "SMILES", "evaluation_canonical_smiles", "cross_rna_plate")
    for number, position in enumerate(rows):
        row = conditions.iloc[position]
        item = {"display_number": number + 1, "source_profile_id": str(arrays["profile_ids"][position]), "source_npz_row": int(position), "group_sorted_rank_zero_based": int(ranks[number])}
        for field in fields:
            value = row[field]
            item[field] = value.item() if isinstance(value, np.generic) else value
        selected.append(item)
    prnet, baseline = errors["prnet_mean"], errors["no_change"]
    improved = prnet < baseline
    return {
        "schema_version": 1, "case_id": "prnet-reference-evaluation", "run_id": records["manifest"]["run_id"],
        "scale": SCALE, "response_definition": "post-treatment model-scale expression minus its supplied paired-control expression",
        "selection": {
            "profile_rule": "Sort alias-exclusion-group representatives by casefolded source drug name and pert_id; select 10 evenly spaced group ranks. Representative: first name/pert_id, lowest dose, then time, RNA plate and source profile ID.",
            "gene_rule": "Top 12 genes by mean absolute observed response across all 661 treatments; ties by gene ID. Descriptive display selection, not evaluation evidence.",
            "selection_uses_prediction_quality": False, "error_panels_use_all_profiles": True,
        },
        "counts": {"profiles": len(prnet), "genes": len(arrays["gene_ids"]), "exclusion_groups": int(conditions.exclusion_group.nunique()), "source_pert_ids": int(conditions.pert_id.nunique())},
        "heatmap": {
            "profiles": selected,
            "genes": [{"gene_id": str(arrays["gene_ids"][j]), "source_npz_column": int(j), "source_gene_title": str(genes.iloc[j].pr_gene_title), "mean_absolute_observed_response_all_profiles": float(amplitudes[j])} for j in columns],
            "observed_response": measured.tolist(), "predicted_response": predicted.tolist(),
            "shared_symmetric_color_limit": float(max(np.abs(measured).max(), np.abs(predicted).max())),
            "clipping": "none; limit is maximum absolute value across both displayed matrices",
        },
        "paired_errors": {"profile_ids": arrays["profile_ids"].tolist(), "prnet_mean_rmse": prnet.tolist(), "zero_response_rmse": baseline.tolist()},
        "summary": {"prnet_mean_rmse": float(prnet.mean()), "zero_response_mean_rmse": float(baseline.mean()), "mean_paired_rmse_difference": float((prnet - baseline).mean()), "prnet_lower_rmse_count": int(improved.sum()), "zero_response_lower_rmse_count": int((prnet > baseline).sum()), "exact_tie_count": int((prnet == baseline).sum()), "prnet_lower_rmse_fraction": float(improved.mean())},
        "inference_parameters": records["manifest"]["parameters"],
        "scientific_limits": {"training_overlap": records["validation"]["training_overlap"], "independent_validation": records["validation"]["independent_validation"], "preprocessing": records["validation"]["preprocessing_scope"], "cross_rna_plate_profiles": records["qc"]["cross_rna_plate_profiles"], "sampling_is_biological_replication": False, "clinical_or_disease_reversal_ranking": False},
    }


def render(source, output):
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.ticker import MaxNLocator, PercentFormatter

    heatmap = source["heatmap"]
    observed, predicted = np.array(heatmap["observed_response"]), np.array(heatmap["predicted_response"])
    prnet = np.array(source["paired_errors"]["prnet_mean_rmse"])
    baseline = np.array(source["paired_errors"]["zero_response_rmse"])
    n = len(prnet)
    summary = source["summary"]
    cmap = LinearSegmentedColormap.from_list("response", [BLUE, "#FFFFFF", ORANGE])
    style = {"font.family": "DejaVu Sans", "font.size": 11, "text.color": NAVY, "axes.labelcolor": NAVY, "axes.edgecolor": "#CED6DD", "xtick.color": NAVY, "ytick.color": NAVY, "axes.titlesize": 13, "axes.titleweight": "bold", "svg.fonttype": "none"}
    with plt.rc_context(style):
        fig = plt.figure(figsize=(12.5, 10.6), facecolor="white")
        try:
            fig.text(.05, .966, "PRnet | Drug response in the HT115 reference demo", fontsize=20, weight="bold")
            fig.text(.05, .937, "661 treatment profiles × 978 genes  ·  Official fixed checkpoint  ·  CPU inference, 16 noise draws", fontsize=11.5)
            fig.text(.05, .911, "Training overlap unknown; independent validation not assessed", color=ORANGE, fontsize=11.5, weight="bold")
            ax_observed = fig.add_axes([.225, .525, .305, .325])
            ax_predicted = fig.add_axes([.568, .525, .305, .325], sharey=ax_observed)
            cax = fig.add_axes([.899, .525, .014, .325])
            limit = heatmap["shared_symmetric_color_limit"]
            for axis, values, title in ((ax_observed, observed, "A  Measured response"), (ax_predicted, predicted, "B  PRnet predicted response")):
                mesh = axis.pcolormesh(values, cmap=cmap, vmin=-limit, vmax=limit, edgecolors="white", linewidth=.65, rasterized=False)
                axis.set_xticks(np.arange(values.shape[1]) + .5, [x["gene_id"] for x in heatmap["genes"]], rotation=50, ha="right", rotation_mode="anchor", fontsize=10)
                axis.set_yticks(np.arange(values.shape[0]) + .5)
                axis.set_ylim(values.shape[0], 0)
                axis.tick_params(length=0, pad=6)
                axis.set_title(title, loc="left", pad=13)
                for spine in axis.spines.values():
                    spine.set_visible(False)
            labels = []
            for row in heatmap["profiles"]:
                name = str(row["pert_iname"]).strip()
                wrapped = textwrap.fill(name, width=24, break_long_words=False, break_on_hyphens=True)
                labels.append(f"{row['display_number']:02d}  {wrapped}")
            ax_observed.set_yticklabels(labels, fontsize=10.5)
            ax_predicted.tick_params(labelleft=False)
            bar = fig.colorbar(mesh, cax=cax)
            bar.set_label("Response on processed model scale", fontsize=10.5, labelpad=9)
            bar.ax.yaxis.set_major_locator(MaxNLocator(5))
            if bar.solids is not None:
                bar.solids.set_rasterized(False)
            fig.text(.225, .439, "10 fixed representative profiles; 12 genes selected by observed response magnitude.", fontsize=10.4)
            fig.text(.225, .419, "Both panels share the full color range. Gene selection is for display only.", fontsize=10.4, color=GRAY)

            ax_pair = fig.add_axes([.10, .117, .345, .235])
            ax_ecdf = fig.add_axes([.585, .117, .345, .235])
            bound = float(max(prnet.max(), baseline.max()) * 1.055)
            improved = prnet < baseline
            ax_pair.plot([0, bound], [0, bound], color=GRAY, ls="--", lw=1.1, zorder=1)
            for mask, color in ((~improved, ORANGE), (improved, TEAL)):
                ax_pair.scatter(baseline[mask], prnet[mask], s=13, alpha=.57, color=color, edgecolors="none", zorder=2)
            ax_pair.set(xlim=(0, bound), ylim=(0, bound), xlabel="Zero-response RMSE", ylabel="PRnet response RMSE")
            ax_pair.set_title("C  Paired errors · all 661 profiles", loc="left", pad=12)
            ax_pair.text(.05, .94, f"PRnet lower error: {int(improved.sum())}/{n}\nBelow dashed line = PRnet lower", transform=ax_pair.transAxes, va="top", fontsize=10.5, bbox={"facecolor": "white", "edgecolor": "none", "alpha": .88, "pad": 3})
            for values, label, color in ((baseline, "Zero response", GRAY), (prnet, "PRnet", BLUE)):
                sorted_values = np.sort(values)
                ax_ecdf.step(np.r_[0, sorted_values], np.r_[0, np.arange(1, n + 1) / n], where="post", label=label, color=color, lw=2.2)
                ax_ecdf.axvline(values.mean(), color=color, lw=1.1, ls=":", alpha=.85)
            ax_ecdf.set(xlim=(0, bound), ylim=(0, 1.01), xlabel="Response RMSE · lower is better", ylabel="Fraction of treatment profiles")
            ax_ecdf.yaxis.set_major_formatter(PercentFormatter(1))
            ax_ecdf.set_title("D  Complete error distributions", loc="left", pad=12)
            ax_ecdf.legend(loc="lower right", frameon=False, fontsize=10.5)
            ax_ecdf.text(.98, .50, f"Mean RMSE\nPRnet  {summary['prnet_mean_rmse']:.6f}\nZero    {summary['zero_response_mean_rmse']:.6f}", transform=ax_ecdf.transAxes, ha="right", va="center", fontsize=10.5, bbox={"facecolor": "white", "edgecolor": "none", "alpha": .9, "pad": 3})
            for axis in (ax_pair, ax_ecdf):
                axis.spines[["top", "right"]].set_visible(False)
                axis.grid(alpha=.22, color="#A6B3BE", linewidth=.7)
                axis.set_axisbelow(True)
                axis.xaxis.set_major_locator(MaxNLocator(5))
                axis.yaxis.set_major_locator(MaxNLocator(5))
            difference = summary["mean_paired_rmse_difference"]
            fig.text(.05, .050, f"Mean paired RMSE difference (PRnet − zero): {difference:+.6f}.  This run does not improve mean RMSE over zero response." if difference > 0 else f"Mean paired RMSE difference (PRnet − zero): {difference:+.6f}.  Descriptive reference result; no independent validation.", fontsize=11, weight="bold")
            fig.text(.05, .026, "Response = treated expression − supplied control after official normalization + log1p.  No disease-reversal or efficacy ranking.", fontsize=9.7, color=GRAY)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            outside = []
            for artist in fig.findobj(match=matplotlib.text.Text):
                if artist.get_visible() and artist.get_text():
                    box = artist.get_window_extent(renderer)
                    if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width + 1 or box.y1 > fig.bbox.height + 1:
                        outside.append(artist.get_text())
            if outside:
                raise ValueError(f"Figure text extends beyond canvas: {outside}")
            for extension in ("png", "svg"):
                fig.savefig(output / f"predicted_response.{extension}", dpi=180, facecolor="white", metadata={"Creator": "Virtual Cell Research plot_prnet_case.py"} if extension == "svg" else None)
            return {"dpi": 180, "canvas_inches": [12.5, 10.6], "pixel_dimensions": [2250, 1908], "canvas_text_bounds": "passed", "full_shared_color_range": True, "displayed_heatmap_cells": int(observed.size + predicted.size), "paired_error_profiles": n}
        finally:
            plt.close(fig)


def plot_case(run_dir, output_dir):
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError(f"Choose a new output directory; refusing to overwrite {output}")
    arrays, conditions, genes, errors, records, provenance, input_hashes = load_run(run_dir)
    source = make_source(arrays, conditions, genes, errors, records)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "figure_source.json", source)
    checks = render(source, output)
    png = output / "predicted_response.png"
    if png.stat().st_size >= 3_000_000:
        raise ValueError("PNG exceeds the 3 MB gallery budget")
    artifacts = {p.name: {"bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in sorted(output.iterdir()) if p.is_file()}
    evidence = {
        "schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "case_id": "prnet-reference-evaluation", "plotter": "scripts/plot_prnet_case.py", "plotter_sha256": sha256_file(__file__),
        "run_directory": str(Path(run_dir)), "run_manifest": records["manifest"],
        "source_commit": provenance["source_commit"], "inference_script_sha256": provenance["script_sha256"],
        "resources_sha256_verified": provenance["resources_sha256_verified"], "resources": provenance["resources"],
        "run_artifact_hashes": input_hashes, "run_provenance_sha256": sha256_file(Path(run_dir) / "provenance.json"),
        "environment": {"python": platform.python_version(), "packages": provenance["packages"]},
        "summary": source["summary"], "qc": records["qc"], "validation": records["validation"],
        "numerical_checks": {"full_npz_loaded": True, "allow_pickle": False, "npz_arrays_read": sorted(arrays), "all_numeric_arrays_finite": True, "tables_joined_by_ids": True, "paired_control_values_verified": True, "observed_and_predicted_deltas_verified": True, "all_four_methods_profile_rmse_and_mae_recomputed": True, "profile_metrics_and_summary_agree": True, "zero_response_pearson_remains_undefined": True},
        "figure_checks": checks, "visual_review": {"status": "not_performed_by_script"},
        "artifacts": artifacts,
    }
    write_json(output / "evidence.json", evidence)
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True, help="Completed prnet_reference_case.py run directory")
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory for figures and portable evidence")
    args = parser.parse_args(argv)
    try:
        evidence = plot_case(args.run_dir, args.output_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"PRnet plotting error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "generated", "output_dir": str(args.output_dir), "summary": evidence["summary"], "numerical_checks": evidence["numerical_checks"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
