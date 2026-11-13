#!/usr/bin/env python3
"""Create an audited gallery figure from freshly computed Kang case outputs.

This only visualizes observed responses and the leave-one-donor-out mean
baseline. It neither runs nor validates a virtual-cell model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd


NAVY, BLUE, TEAL, ORANGE = "#17324D", "#276FBF", "#128C87", "#D87936"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def record(path):
    path = Path(path)
    return {"bytes": path.stat().st_size, "sha256": digest(path)}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def load_verified(observed, heldout):
    """Reject mismatched genes, donors, values, or baseline scores before plotting."""
    provenance = json.loads((observed / "provenance.json").read_text())
    qc = json.loads((observed / "qc.json").read_text())
    if provenance.get("source_kind") != "official_GEO_GSE96583_batch2":
        raise ValueError("The gallery requires the real fixed GEO source, not a fixture")
    if qc.get("selected_cell_type") != "CD14+ Monocytes" or qc.get("paired_donors") != 8:
        raise ValueError("Expected the completed eight-donor CD14+ case")
    expected = json.loads((Path(__file__).resolve().parents[1] / "cases/kang-ifnb-pbmc/evidence.json").read_text())["sources"]
    if set(expected) != set(provenance["sources"]):
        raise ValueError("The six fixed GEO source identities are required")
    for key, value in expected.items():
        if provenance["sources"][key]["sha256"] != value["sha256"]:
            raise ValueError("Fixed GEO source hash mismatch: " + key)
    artifacts = {key.replace("\\", "/"): value for key, value in provenance["artifacts"].items()}
    required = ["raw/paired_responses.npz", "tables/genes.csv", "tables/donor_pairs.csv", "tables/gene_summary.csv", "qc.json"]
    for relative in required:
        if record(observed / relative) != artifacts[relative]:
            raise ValueError("Observed artifact changed: " + relative)
    with np.load(observed / "raw/paired_responses.npz", allow_pickle=False) as data:
        observed_delta = data["observed_delta"]
        genes, donors = data["gene_ids"].astype(str), data["donor_ids"].astype(str)
    if observed_delta.shape != (8, 35635) or not np.isfinite(observed_delta).all():
        raise ValueError("Unexpected response dimensions or values")
    gene_table = pd.read_csv(observed / "tables/genes.csv", dtype=str, keep_default_na=False)
    summary = pd.read_csv(observed / "tables/gene_summary.csv", keep_default_na=False)
    pairs = pd.read_csv(observed / "tables/donor_pairs.csv", dtype={"donor": str}, keep_default_na=False)
    if not np.array_equal(gene_table.gene_id, genes) or not np.array_equal(summary.gene_id, genes):
        raise ValueError("Gene axis mismatch")
    if not np.allclose(summary.mean_paired_difference, observed_delta.mean(axis=0), rtol=0, atol=1e-12):
        raise ValueError("Saved gene means disagree with full response array")
    with np.load(heldout / "evaluation/raw/aligned_responses.npz", allow_pickle=False) as data:
        if not np.array_equal(data["gene_ids"].astype(str), genes):
            raise ValueError("Baseline gene axis mismatch")
        if not np.array_equal(data["sample_ids"].astype(str), ["CD14:" + donor for donor in donors]):
            raise ValueError("Baseline donor axis mismatch")
        if not np.allclose(data["observed_response"], observed_delta, rtol=0, atol=1e-12):
            raise ValueError("Baseline observation mismatch")
        prediction = data["predicted_response"]
    expected_prediction = np.array([np.delete(observed_delta, i, axis=0).mean(axis=0) for i in range(len(donors))])
    max_prediction_error = float(np.max(np.abs(prediction - expected_prediction)))
    if max_prediction_error > 1e-12:
        raise ValueError("Prediction uses values other than the other seven donor means")
    metrics = pd.read_csv(heldout / "evaluation/tables/unit_metrics.csv", dtype={"unit_id": str})
    pred = metrics.loc[metrics.method.eq("prediction")].set_index("unit_id").loc[donors]
    zero = metrics.loc[metrics.method.eq("no_change")].set_index("unit_id").loc[donors]
    expected_rmse = np.sqrt(np.mean((prediction - observed_delta) ** 2, axis=1))
    expected_zero = np.sqrt(np.mean(observed_delta ** 2, axis=1))
    if not np.allclose(pred.rmse, expected_rmse, rtol=0, atol=1e-12) or not np.allclose(zero.rmse, expected_zero, rtol=0, atol=1e-12):
        raise ValueError("Metric table disagrees with full-array RMSE")
    return provenance, qc, gene_table, summary, pairs, observed_delta, donors, pred, zero, metrics, max_prediction_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-run", type=Path, required=True)
    parser.add_argument("--heldout-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New figure/evidence directory")
    args = parser.parse_args(argv)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    try:
        values = load_verified(args.observed_run, args.heldout_run)
        provenance, qc, genes, summary, pairs, delta, donors, pred, zero, metrics, prediction_error = values
        # Choose six positive and six negative source gene IDs, with stable ID
        # tie breaking. The panel is descriptive; all genes enter the RMSE.
        positive = summary.loc[summary.mean_paired_difference.gt(0)].sort_values(
            ["mean_paired_difference", "gene_id"], ascending=[False, True]).head(6)
        negative = summary.loc[summary.mean_paired_difference.lt(0)].sort_values(
            ["mean_paired_difference", "gene_id"], ascending=[True, True]).head(6)
        chosen = pd.concat([positive, negative])
        if len(chosen) != 12:
            raise ValueError("Expected at least six nonzero genes in each direction")
        positions = [genes.gene_id.tolist().index(gene) for gene in chosen.gene_id]
        heat = delta[:, positions].T
        plot_rows = []
        for i, gene in enumerate(chosen.itertuples()):
            for j, donor in enumerate(donors):
                plot_rows.append({"gene_id": gene.gene_id, "gene_symbol": gene.gene_symbol,
                    "donor": donor, "selection": "top_positive" if i < 6 else "top_negative",
                    "mean_paired_difference": gene.mean_paired_difference,
                    "observed_response": float(heat[i, j])})
        pd.DataFrame(plot_rows).to_csv(output / "figure_data.csv", index=False)
        metrics.to_csv(output / "unit_metrics.csv", index=False)
        pairs.to_csv(output / "donor_pairs.csv", index=False)

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
        cmap = LinearSegmentedColormap.from_list("observed_response", [BLUE, "#FFFFFF", ORANGE])
        style = {"font.family": "DejaVu Sans", "font.size": 10, "text.color": NAVY,
                 "axes.labelcolor": NAVY, "axes.edgecolor": "#C7D1DB", "xtick.color": NAVY,
                 "ytick.color": NAVY, "svg.fonttype": "none", "figure.facecolor": "white",
                 "axes.facecolor": "white", "savefig.facecolor": "white"}
        with plt.rc_context(style):
            fig = plt.figure(figsize=(14.2, 7.2))
            grid = fig.add_gridspec(1, 2, width_ratios=[1.28, 1], left=.095, right=.97,
                                   top=.77, bottom=.24, wspace=.42)
            ax = fig.add_subplot(grid[0, 0])
            bound = float(np.ceil(np.abs(heat).max()))
            mappable = ax.imshow(heat, cmap=cmap, norm=TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound), aspect="auto")
            ax.set_xticks(np.arange(len(donors)), donors, rotation=40, ha="right")
            ax.set_yticks(np.arange(len(chosen)), chosen.gene_symbol)
            ax.tick_params(length=0, pad=5)
            ax.set_xlabel("Paired donor", labelpad=8)
            ax.set_title("A  Paired observed responses", loc="left", fontweight="bold", fontsize=13, pad=38)
            ax.text(0, 1.035, "Six largest increases + six largest decreases by donor mean", transform=ax.transAxes, fontsize=9.2)
            ax.axhline(5.5, color=NAVY, lw=.8)
            for y in range(heat.shape[0]):
                for x in range(heat.shape[1]):
                    ax.text(x, y, f"{heat[y, x]:.1f}", ha="center", va="center", fontsize=8,
                            color="white" if abs(heat[y, x]) > bound * .62 else NAVY)
            for spine in ax.spines.values():
                spine.set_visible(False)
            cax = fig.add_axes([.095, .087, .405, .018])
            cb = fig.colorbar(mappable, cax=cax, orientation="horizontal")
            cb.set_label("Observed response: log₂(1 + CPMstim) − log₂(1 + CPMctrl)", fontsize=9.1, labelpad=4)
            cb.ax.tick_params(labelsize=8, length=2)
            cb.outline.set_visible(False)

            ax2 = fig.add_subplot(grid[0, 1])
            y = np.arange(len(donors))
            ax2.hlines(y, pred.rmse, zero.rmse, color="#C7D1DB", lw=2, zorder=1)
            ax2.scatter(pred.rmse, y, s=65, color=TEAL, label="Mean of other seven donors", zorder=3)
            ax2.scatter(zero.rmse, y, s=65, color=ORANGE, label="Zero-response reference", zorder=3)
            ax2.set_yticks(y, donors)
            ax2.invert_yaxis()
            ax2.set_ylim(len(donors) - .45, -.55)
            ax2.set_xlim(.35, 1.02)
            ax2.set_xlabel("Response RMSE across all 35,635 genes", labelpad=10)
            ax2.set_ylabel("Held-out donor", labelpad=12)
            ax2.set_title("B  Leave-one-donor-out baseline", loc="left", fontweight="bold", fontsize=13, pad=38)
            ax2.text(0, 1.035, f"Donor mean RMSE: {pred.rmse.mean():.3f} versus {zero.rmse.mean():.3f}",
                     transform=ax2.transAxes, fontsize=10)
            ax2.grid(axis="x", color="#E9EEF2", lw=.8)
            ax2.set_axisbelow(True)
            ax2.spines[["top", "right", "left"]].set_visible(False)
            ax2.tick_params(axis="y", length=0)
            ax2.legend(loc="upper left", bbox_to_anchor=(-.02, -.24), frameon=False, fontsize=9.1,
                       handletextpad=.6, borderaxespad=0)
            fig.text(.04, .94, "Observed IFN-β response and a donor holdout baseline", fontsize=20, weight="bold")
            fig.text(.04, .885, "Kang GSE96583  •  CD14+ monocytes  •  8 paired donors  •  6 h stimulation", fontsize=12)
            fig.text(.04, .018, "Observed data + in-experiment mean baseline. Independent model validation was not assessed.", fontsize=9, color="#52677B")
            for suffix in ("png", "svg"):
                fig.savefig(output / ("donor_response_and_holdout." + suffix), dpi=175)
            plt.close(fig)
        png = output / "donor_response_and_holdout.png"
        if png.stat().st_size >= 3 * 1024 * 1024:
            raise ValueError("Gallery PNG must stay below 3 MiB")
        evidence = {"schema_version": 1, "case_id": "kang-gallery", "created_at": datetime.now(timezone.utc).isoformat(),
            "observed_run": str(args.observed_run), "heldout_run": str(args.heldout_run),
            "source_kind": "official_GEO_GSE96583_batch2", "sources": provenance["sources"],
            "run_status": "completed", "model_status": "not_run", "baseline_status": "executed",
            "independent_validation": "not_assessed", "source_cells": qc["source_cells"],
            "singlets": qc["included_singlets"], "paired_donors": 8, "all_genes": len(genes),
            "all_zero_response_genes": int(np.all(delta == 0, axis=0).sum()),
            "control_cells": int(pairs.ctrl_n_cells.sum()), "stimulated_cells": int(pairs.stim_n_cells.sum()),
            "mean_rmse_baseline": float(pred.rmse.mean()), "mean_rmse_zero": float(zero.rmse.mean()),
            "mean_pearson_baseline": float(pred.pearson.mean()),
            "max_abs_prediction_error_against_other_seven_donors": prediction_error,
            "full_gene_metrics_recomputed": True, "gene_axis_checked": True, "donor_axis_checked": True,
            "gene_selection": "6 largest positive donor means and 6 most negative donor means; gene_id breaks ties; selection affects heatmap only",
            "response_scale": "log2(1 + CPM_stim) - log2(1 + CPM_ctrl); CPM uses all source genes per donor-condition library",
            "script": record(__file__), "python": platform.python_version(), "interpreter": sys.executable,
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "matplotlib")},
            "invocation": sys.argv if argv is None else argv,
            "inputs": {str(path): record(path) for path in [args.observed_run / "provenance.json", args.observed_run / "raw/paired_responses.npz",
                args.heldout_run / "fitting.json", args.heldout_run / "evaluation/raw/aligned_responses.npz", args.heldout_run / "evaluation/tables/unit_metrics.csv"]},
            "outputs": {path.name: record(path) for path in sorted(output.iterdir()) if path.is_file()}}
        write_json(output / "evidence.json", evidence)
        print(json.dumps({"output": str(output), "mean_rmse": evidence["mean_rmse_baseline"],
              "mean_zero_rmse": evidence["mean_rmse_zero"], "png_bytes": png.stat().st_size}, indent=2))
    except Exception as error:
        write_json(output / "error.json", {"status": "failed", "error": str(error)})
        raise


if __name__ == "__main__":
    main()
