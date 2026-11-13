"""Plot matched, completed CellOracle KO/OE runs with checked source tables.

This script reads real runner outputs. It does not fit a model, generate
expression data, change a result, or treat a projection as validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


NAVY = "#17324D"
BLUE = "#276FBF"
TEAL = "#128C87"
ORANGE = "#D87936"
GRAY = "#718595"
SCALE_LABEL = "CellOracle imputed log1p(raw-count) scale"
RUNNER_SCALE_CONTRACT = (
    "log1p(raw counts), then KNN smoothing into imputed_count; native simulated_count "
    "and delta_X retain that internal scale"
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False,
                                    allow_nan=False) + "\n", encoding="utf-8")


def check_axes(frame, label):
    for name, axis in (("cell", frame.index), ("gene", frame.columns)):
        if not axis.is_unique or axis.hasnans or any(not str(x).strip() for x in axis):
            raise ValueError(f"{label}: {name} IDs must be unique and nonempty")
    if frame.empty or not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError(f"{label}: empty or nonfinite expression matrix")


def validate_expression_triplet(baseline, simulated, delta):
    """Reject axis corruption before doing any elementwise arithmetic."""
    for label, frame in (("baseline", baseline), ("simulated", simulated), ("delta_X", delta)):
        check_axes(frame, label)
        if not baseline.index.equals(frame.index) or not baseline.columns.equals(frame.columns):
            raise ValueError(f"{label}: cell/gene axes differ from baseline (including order)")
    residual = delta.to_numpy() - (simulated.to_numpy() - baseline.to_numpy())
    maximum = float(np.abs(residual).max())
    if not np.allclose(residual, 0, rtol=0, atol=1e-12):
        raise ValueError(f"delta_X differs from simulated minus baseline: {maximum}")
    return {"cells": len(baseline), "genes": len(baseline.columns),
            "all_values_finite": True, "cell_gene_axes_exact": True,
            "delta_identity_max_abs_error": maximum,
            "delta_values_checked": int(delta.size)}


def validate_matched_coordinates(ko, oe):
    """A shared UMAP requires both identical ordered IDs and coordinates."""
    required = ["cell", "group", "umap_x", "umap_y", "dx", "dy", "dx_random", "dy_random"]
    for label, table in (("KO", ko), ("OE", oe)):
        if not set(required).issubset(table.columns):
            raise ValueError(f"{label}: incomplete cell-state table")
        if table.cell.isna().any() or table.cell.duplicated().any():
            raise ValueError(f"{label}: missing or duplicate cell IDs")
        if not np.isfinite(table[required[2:]].to_numpy(dtype=float)).all():
            raise ValueError(f"{label}: nonfinite coordinate or vector")
    if not ko.cell.equals(oe.cell):
        raise ValueError("KO/OE cell IDs differ, including order")
    if not np.array_equal(ko[["umap_x", "umap_y"]], oe[["umap_x", "umap_y"]]):
        raise ValueError("KO/OE UMAP coordinates differ; cannot draw a shared embedding")
    if not ko.group.equals(oe.group):
        raise ValueError("KO/OE descriptive group labels differ")
    return {"cell_ids_exact": True, "umap_coordinates_exact": True,
            "descriptive_groups_exact": True, "cells": len(ko)}


def directional_effects(delta, target, per_direction):
    """Rank signed mean changes separately; always exclude the forced target."""
    if target not in delta.columns:
        raise ValueError(f"Target gene is absent: {target}")
    if per_direction < 1:
        raise ValueError("per_direction must be positive")
    effects = pd.DataFrame({"gene": delta.columns,
                            "mean_delta": delta.mean(axis=0).to_numpy(),
                            "mean_abs_delta": delta.abs().mean(axis=0).to_numpy(),
                            "fraction_cells_up": (delta > 0).mean(axis=0).to_numpy(),
                            "fraction_cells_down": (delta < 0).mean(axis=0).to_numpy()})
    candidates = effects.loc[effects.gene != target]
    decreasing = candidates.loc[candidates.mean_delta < 0].sort_values(
        ["mean_delta", "gene"], ascending=[True, True]).head(per_direction).copy()
    increasing = candidates.loc[candidates.mean_delta > 0].sort_values(
        ["mean_delta", "gene"], ascending=[False, True]).head(per_direction).copy()
    decreasing["direction"] = "decrease"
    increasing["direction"] = "increase"
    for frame in (decreasing, increasing):
        frame["direction_rank"] = np.arange(1, len(frame) + 1)
    selected = pd.concat([increasing, decreasing], ignore_index=True)
    return effects, selected


def validate_matched_grn(ko, oe):
    check_axes(ko, "KO GRN")
    check_axes(oe, "OE GRN")
    if not ko.index.equals(oe.index) or not ko.columns.equals(oe.columns):
        raise ValueError("KO/OE fitted GRN gene axes differ")
    difference = float(np.abs(ko.to_numpy() - oe.to_numpy()).max())
    same_support = np.array_equal(ko.to_numpy() != 0, oe.to_numpy() != 0)
    # Independent fits can differ at floating-point roundoff. The original
    # coefficients stay unchanged; report the actual difference explicitly.
    if not same_support or difference > 1e-12:
        raise ValueError(f"KO/OE fitted GRNs differ beyond 1e-12 absolute tolerance: {difference}")
    return {"fitted_grn_gene_axes_exact": True, "fitted_grn_nonzero_pattern_exact": True,
            "fitted_grn_coefficients_exact": ko.equals(oe),
            "fitted_grn_max_abs_difference": difference,
            "fitted_grn_absolute_tolerance": 1e-12,
            "fitted_grn_matches_within_tolerance": True}


def validate_case_input(manifest, cells):
    """Verify the dataset identity used in this case-specific figure heading."""
    import anndata as ad

    path = Path(manifest["inputs"]["h5ad"])
    if not path.is_file() or sha256(path) != manifest["inputs"]["h5ad_sha256"]:
        raise ValueError("Original AnnData is missing or differs from the model input hash")
    data = ad.read_h5ad(path, backed="r")
    try:
        expected = {"source_accession": "GSE72857", "species": "Mus musculus",
                    "genome_build": "mm9", "input_scale": "raw_nonnegative_integer_molecule_counts"}
        if any(data.uns.get(key) != value for key, value in expected.items()):
            raise ValueError("Input metadata does not support this GSE72857 case heading")
        background = {"Batch_desc": "Unsorted myeloid", "Mouse_ID": "2",
                      "Number_of_cells": "1", "genotype_variation": "wild type"}
        if any(key not in data.obs or not data.obs[key].astype(str).eq(value).all()
               for key, value in background.items()):
            raise ValueError("Input metadata does not verify the displayed wild-type myeloid background")
        if list(data.obs_names) != list(cells):
            raise ValueError("Original AnnData cell IDs differ from the result matrices")
        return {"source_accession": "GSE72857", "source_identity_checked": True,
                "wild_type_background_checked": True, "original_input_hash_checked": True}
    finally:
        data.file.close()


def load_run(path, expected_mode, target):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text())
    validation = json.loads((path / "validation.json").read_text())
    provenance = json.loads((path / "provenance.json").read_text())
    if manifest.get("status") != "completed" or manifest.get("task") != expected_mode:
        raise ValueError(f"Expected a completed {expected_mode.upper()} run: {path}")
    if manifest.get("target_gene") != target:
        raise ValueError("Run target gene does not match the requested target")
    if manifest.get("output_type") != "network_simulation":
        raise ValueError("Input is not a CellOracle network simulation")
    if manifest.get("backend") != {"name": "CellOracle", "version": "0.20.0"}:
        raise ValueError("This reviewed gallery contract requires CellOracle 0.20.0")
    if provenance.get("backend") != manifest["backend"]:
        raise ValueError("Manifest and provenance backend versions disagree")
    if manifest.get("celloracle_internal_scale") != RUNNER_SCALE_CONTRACT:
        raise ValueError("Run does not declare the reviewed imputed log1p(raw-count) scale contract")
    matrices = {name: pd.read_csv(path / "raw" / filename, index_col=0,
                                 float_precision="round_trip")
                for name, filename in (("baseline", "baseline_imputed_expression.csv.gz"),
                                       ("simulated", "simulated_expression.csv.gz"),
                                       ("delta", "delta_X.csv.gz"))}
    checks = validate_expression_triplet(**matrices)
    shift = pd.read_csv(path / "tables/cell_state_shift.csv.gz", float_precision="round_trip")
    setting = pd.read_csv(path / "tables/target_expression_setting.csv", float_precision="round_trip")
    baseline = matrices["baseline"]
    if list(shift.cell) != list(baseline.index) or list(setting.cell) != list(baseline.index):
        raise ValueError("State/target table IDs differ from expression rows, including order")
    if not np.array_equal(setting.baseline_imputed.to_numpy(), baseline[target].to_numpy()):
        raise ValueError("Target setting table baseline differs from the expression matrix")
    if setting.fixed_input_setting.nunique() != 1 or not np.isfinite(setting.fixed_input_setting).all():
        raise ValueError("Target input setting must be one finite constant")
    fixed = float(setting.fixed_input_setting.iloc[0])
    if expected_mode == "ko" and fixed != 0:
        raise ValueError("KO target must be set to zero")
    target_error = float(np.abs(matrices["simulated"][target].to_numpy() - fixed).max())
    if target_error > 1e-12:
        raise ValueError("Simulated target does not equal its recorded fixed setting")
    for columns, summary in ((("dx", "dy"), "shift_magnitude"),
                             (("dx_random", "dy_random"), "random_shift_magnitude")):
        if not np.allclose(np.linalg.norm(shift[list(columns)].to_numpy(), axis=1),
                           shift[summary], rtol=1e-12, atol=1e-12):
            raise ValueError(f"Stored {summary} does not match its two vector components")
    effects, _ = directional_effects(matrices["delta"], target, 1)
    saved = pd.read_csv(path / "tables/gene_effects.csv", float_precision="round_trip")
    if saved.gene.duplicated().any() or set(saved.gene) != set(effects.gene):
        raise ValueError("Saved gene-effect gene IDs do not match the full delta matrix")
    metrics = ["mean_delta", "mean_abs_delta", "fraction_cells_up", "fraction_cells_down"]
    if not np.allclose(saved.set_index("gene").loc[effects.gene, metrics].to_numpy(),
                       effects[metrics].to_numpy(), rtol=1e-12, atol=1e-12):
        raise ValueError("Saved gene-effect values disagree with the full delta matrix")
    checks.update(backend_version_verified="0.20.0", internal_expression_scale_contract_verified=True,
                  target_simulated_setting_max_abs_error=target_error,
                  target_table_matches_expression=True, saved_gene_effects_match_full_delta=True,
                  projection_magnitudes_match_vectors=True)
    source_names = ["manifest.json", "validation.json", "provenance.json",
                    "raw/baseline_imputed_expression.csv.gz", "raw/simulated_expression.csv.gz",
                    "raw/delta_X.csv.gz", "raw/simulation_grn_coefficients_000.csv.gz",
                    "tables/cell_state_shift.csv.gz", "tables/gene_effects.csv",
                    "tables/target_expression_setting.csv"]
    sources = {name: {"bytes": (path / name).stat().st_size, "sha256": sha256(path / name)}
               for name in source_names}
    return {"path": str(path), "manifest": manifest, "validation": validation,
            "shift": shift, "setting": setting, "fixed": fixed, "checks": checks,
            "sources": sources, **matrices}


def save_figure(fig, path, dpi):
    fig.savefig(path, dpi=dpi, facecolor="white")
    if Path(path).stat().st_size > 3_000_000:
        raise ValueError(f"PNG exceeds the 3 MB gallery limit: {path}")


def style_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for spine in ax.spines.values():
        spine.set_color("#C3CDD5")
    ax.tick_params(colors=NAVY, labelsize=9, length=3)
    ax.xaxis.label.set_color(NAVY)
    ax.yaxis.label.set_color(NAVY)


def oe_choice_label(run):
    choice = run["validation"].get("target_setting", {}).get("choice", "fixed setting")
    return "P" + choice.removeprefix("percentile_") if choice.startswith("percentile_") else "fixed setting"


def plot_shifts(runs, arrow_ids, output, dpi, target):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    table = runs["ko"]["shift"]
    xy = table[["umap_x", "umap_y"]].to_numpy()
    selected = table.cell.isin(arrow_ids).to_numpy()
    vectors = [runs[mode]["shift"][list(columns)].to_numpy()
               for mode in ("ko", "oe") for columns in (("dx", "dy"), ("dx_random", "dy_random"))]
    extent = max(float(np.ptp(xy, axis=0).max()), 1e-8)
    max_vector = max(float(np.linalg.norm(vec, axis=1).max()) for vec in vectors)
    common_scale = max(max_vector, 1e-8) / (0.085 * extent)
    points = np.concatenate([xy] + [xy + vector / common_scale for vector in vectors])
    lower, upper = points.min(axis=0) - extent * 0.06, points.max(axis=0) + extent * 0.06
    fig, axes = plt.subplots(2, 2, figsize=(12.4, 9.5), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.84, bottom=0.13, hspace=0.34, wspace=0.17)
    titles = [f"A  {target} KO", "B  KO randomized delta_X",
              f"C  {target} OE (fixed {oe_choice_label(runs['oe'])})", "D  OE randomized delta_X"]
    colors = [BLUE, GRAY, TEAL, GRAY]
    for ax, vector, title, color in zip(axes.flat, vectors, titles, colors):
        ax.scatter(xy[:, 0], xy[:, 1], s=9, color="#D5DDE3", alpha=0.75, linewidths=0, zorder=1)
        quiver = ax.quiver(xy[selected, 0], xy[selected, 1], vector[selected, 0], vector[selected, 1],
                           angles="xy", scale_units="xy", scale=common_scale,
                           width=0.0033, headwidth=3.3, headlength=4.4,
                           color=color, alpha=0.88, zorder=2)
        ax.set(xlim=(lower[0], upper[0]), ylim=(lower[1], upper[1]), aspect="equal",
               xlabel="UMAP 1", ylabel="UMAP 2")
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=NAVY, pad=13)
        ax.text(0.02, 0.98, f"Mean |shift| = {np.linalg.norm(vector, axis=1).mean():.3f}",
                transform=ax.transAxes, va="top", fontsize=9, color=NAVY,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9, "pad": 3})
        style_axes(ax)
    reference = 0.5 if max_vector >= 0.5 else round(max_vector / 2, 2)
    axes[1, 1].quiverkey(quiver, 0.72, -0.22, reference,
                         f"{reference:g} projection units", labelpos="E", coordinates="axes",
                         color=NAVY, labelcolor=NAVY, fontproperties={"size": 9})
    fig.text(0.08, 0.965, f"{target} perturbation projects onto a shared cell-state map",
             fontsize=18, fontweight="bold", color=NAVY, va="top")
    version = runs["ko"]["manifest"]["backend"]["version"]
    fig.text(0.08, 0.923, f"CellOracle {version}  |  GSE72857 wild-type myeloid background  |  {len(table):,} cells",
             fontsize=11, color=NAVY, va="top")
    fig.text(0.08, 0.887, f"Same coordinates, {len(arrow_ids)} deterministically selected arrows, and one arrow scale in all panels",
             fontsize=10, color="#52697A", va="top")
    fig.legend(handles=[Line2D([], [], marker="o", linestyle="none", color="#CBD5DC", markersize=5,
                                label=f"All {len(table)} baseline cells"),
                        Line2D([], [], color=BLUE, lw=2, label="KO"),
                        Line2D([], [], color=TEAL, lw=2, label="OE"),
                        Line2D([], [], color=GRAY, lw=2, label="Randomized projection")],
               loc="lower left", bbox_to_anchor=(0.073, 0.046), ncol=4, frameon=False, fontsize=10)
    fig.text(0.08, 0.027, "Randomization permutes/sign-flips delta_X with the fitted GRN held fixed. Descriptive simulation; no biological validation.",
             fontsize=9, color="#52697A")
    path = output / "state_shifts.png"
    save_figure(fig, path, dpi)
    plt.close(fig)
    return {"filename": path.name, "common_quiver_scale": common_scale,
            "arrow_reference_projection_units": reference, "points_per_panel": len(table),
            "arrows_per_panel": len(arrow_ids), "axis_limits": {"lower": lower.tolist(), "upper": upper.tolist()},
            "color_semantics": "background cells gray; KO blue; OE teal; randomized vectors gray; no cell-type labels"}


def plot_effects(runs, selected, target_table, output, dpi, target):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    fig = plt.figure(figsize=(12.4, 9.6))
    grid = fig.add_gridspec(2, 2, height_ratios=[1.2, 0.9], left=0.11, right=0.96,
                            top=0.80, bottom=0.14, hspace=0.55, wspace=0.34)
    axes = [fig.add_subplot(grid[0, 0]), fig.add_subplot(grid[0, 1])]
    xmax = max(float(selected.mean_delta.abs().max()) * 1.21, 1e-8)
    for ax, mode, panel in zip(axes, ("ko", "oe"), ("A", "B")):
        frame = selected.loc[selected["mode"] == mode].sort_values("mean_delta", ascending=True)
        color = np.where(frame.mean_delta < 0, BLUE, ORANGE)
        ax.barh(np.arange(len(frame)), frame.mean_delta, height=0.7, color=color, zorder=3)
        ax.set_yticks(np.arange(len(frame)), frame.gene, fontsize=9)
        ax.axvline(0, color=NAVY, linewidth=0.8, zorder=2)
        ax.set_xlim(-xmax, xmax)
        ax.set_xlabel("Mean simulated delta_X", fontsize=10, labelpad=8)
        ax.set_title(f"{panel}  {target} {mode.upper()}: downstream genes", loc="left",
                     color=NAVY, fontsize=12, fontweight="bold", pad=12)
        ax.grid(axis="x", color="#E8EDF0", linewidth=0.7, zorder=0)
        style_axes(ax)
    ax = fig.add_subplot(grid[1, :])
    ordered = target_table.sort_values(["baseline_imputed", "cell"])
    ranks = np.arange(1, len(ordered) + 1)
    baseline = ordered.baseline_imputed.to_numpy()
    fixed = runs["oe"]["fixed"]
    high = baseline > fixed
    ax.plot(ranks, baseline, color=NAVY, linewidth=1.7, label="Baseline Gata1")
    ax.scatter(ranks[high], baseline[high], s=12, color=ORANGE, zorder=4,
               label=f"{int(high.sum())} cells above OE setting")
    ax.axhline(0, color=BLUE, linewidth=1.6, linestyle="--", label="KO: fixed 0")
    choice = oe_choice_label(runs["oe"])
    ax.axhline(fixed, color=TEAL, linewidth=1.8, linestyle="--", label=f"OE: fixed {choice} = {fixed:.4f}")
    ax.set(xlim=(1, len(ordered)), xlabel=f"Cells ranked by baseline imputed {target} (all {len(ordered)} cells)",
           ylabel=f"{target} expression")
    ax.set_ylim(-0.06 * max(float(baseline.max()), 1), float(baseline.max()) * 1.12)
    ax.set_title("C  The intervention fixes one target value in every cell", loc="left",
                 color=NAVY, fontsize=12, fontweight="bold", pad=12)
    decreased, increased = int((baseline > fixed).sum()), int((baseline < fixed).sum())
    ax.text(0.025, 0.95, f"OE raises {increased} cells and lowers {decreased} cells.\nThe fixed {choice} setting is not a per-cell fold change.",
            transform=ax.transAxes, va="top", fontsize=10, color=NAVY,
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.93, "pad": 5})
    style_axes(ax)
    ax.legend(loc="lower left", bbox_to_anchor=(-0.01, -0.37), ncol=4, frameon=False,
               fontsize=9, handlelength=2.2, columnspacing=1.7)
    fig.text(0.08, 0.965, "Network responses and the imposed target setting",
             fontsize=18, fontweight="bold", color=NAVY, va="top")
    counts = selected.groupby(["mode", "direction"]).size()
    n_each = int(counts.max())
    fig.text(0.08, 0.921, f"Top {n_each} positive and {n_each} negative mean changes per run; forced target {target} excluded from gene ranking",
             fontsize=10.6, color=NAVY, va="top")
    fig.text(0.08, 0.886, f"All panels use the {SCALE_LABEL}; changes are not measured log2 fold changes",
             fontsize=10, color="#52697A", va="top")
    fig.legend(handles=[Line2D([], [], color=BLUE, lw=6, label="Negative mean change"),
                        Line2D([], [], color=ORANGE, lw=6, label="Positive mean change")],
               loc="upper left", bbox_to_anchor=(0.105, 0.866), ncol=2, frameon=False,
               fontsize=9, handlelength=1.3)
    fig.text(0.08, 0.028, "Signed means summarize heterogeneous simulated responses. No error bars, p-values, or claims of experimental validation.",
             fontsize=9, color="#52697A")
    path = output / "intervention_effects.png"
    save_figure(fig, path, dpi)
    plt.close(fig)
    return {"filename": path.name, "effect_x_limits": [-xmax, xmax],
            "selection": f"Up to {n_each} strictly positive and {n_each} strictly negative signed mean delta_X per run; ties by gene symbol",
            "target_excluded_from_ranking": target, "target_cells_shown": len(target_table),
            "unit": SCALE_LABEL}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ko-run", type=Path, required=True)
    parser.add_argument("--oe-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-gene", default="Gata1")
    parser.add_argument("--per-direction", type=int, default=8)
    parser.add_argument("--arrows", type=int, default=240)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args(argv)
    if not 150 <= args.dpi <= 200 or args.arrows < 1:
        parser.error("Use 150–200 dpi and at least one arrow")
    output = args.output_dir.expanduser().absolute()
    if os.path.lexists(output):
        raise FileExistsError("Use a new output directory; existing paths are not overwritten")
    runs = {mode: load_run(path, mode, args.target_gene)
            for mode, path in (("ko", args.ko_run), ("oe", args.oe_run))}
    matched = validate_matched_coordinates(runs["ko"]["shift"], runs["oe"]["shift"])
    for input_name in ("h5ad_sha256", "base_grn_sha256"):
        if runs["ko"]["manifest"]["inputs"][input_name] != runs["oe"]["manifest"]["inputs"][input_name]:
            raise ValueError(f"KO/OE {input_name} differs")
    matched.update(validate_case_input(runs["ko"]["manifest"], runs["ko"]["baseline"].index))
    if not runs["ko"]["baseline"].equals(runs["oe"]["baseline"]):
        raise ValueError("KO/OE baseline matrices differ")
    coeffs = [pd.read_csv(Path(runs[mode]["path"]) / "raw/simulation_grn_coefficients_000.csv.gz",
                          index_col=0, float_precision="round_trip") for mode in ("ko", "oe")]
    matched.update(validate_matched_grn(*coeffs))
    matched.update(input_hashes_match=True, baseline_expression_exact=True,
                   backend_versions_exact=True, expression_scale_contracts_exact=True)
    ordered_ids = sorted(runs["ko"]["shift"].cell,
                         key=lambda cell: (hashlib.sha256(f"{args.seed}:{cell}".encode()).hexdigest(), cell))
    arrow_ids = ordered_ids[:min(args.arrows, len(ordered_ids))]
    selected, complete, shifts = [], [], []
    for mode, run in runs.items():
        effects, top = directional_effects(run["delta"], args.target_gene, args.per_direction)
        complete.append(effects.assign(mode=mode))
        selected.append(top.assign(mode=mode))
        shifts.append(run["shift"].assign(mode=mode, arrow_selected=run["shift"].cell.isin(arrow_ids)))
    selected = pd.concat(selected, ignore_index=True)
    target_table = pd.DataFrame({"cell": runs["ko"]["baseline"].index,
                                 "baseline_imputed": runs["ko"]["baseline"][args.target_gene].to_numpy(),
                                 "ko_fixed_input_setting": runs["ko"]["fixed"],
                                 "oe_fixed_input_setting": runs["oe"]["fixed"],
                                 "ko_simulated_target": runs["ko"]["simulated"][args.target_gene].to_numpy(),
                                 "oe_simulated_target": runs["oe"]["simulated"][args.target_gene].to_numpy()})
    target_table["oe_target_direction"] = np.where(target_table.baseline_imputed < runs["oe"]["fixed"], "increase",
        np.where(target_table.baseline_imputed > runs["oe"]["fixed"], "decrease", "unchanged"))
    output.mkdir(parents=True, exist_ok=False)
    output = output.resolve()
    pd.concat(shifts, ignore_index=True).to_csv(output / "cell_state_shift_source.csv.gz", index=False, compression="gzip")
    pd.concat(complete, ignore_index=True).to_csv(output / "all_gene_effects_source.csv.gz", index=False, compression="gzip")
    selected.to_csv(output / "downstream_effects_source.csv", index=False)
    target_table.to_csv(output / "target_setting_source.csv", index=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "text.color": NAVY, "axes.labelcolor": NAVY, "savefig.dpi": args.dpi})
    figures = [plot_shifts(runs, arrow_ids, output, args.dpi, args.target_gene),
               plot_effects(runs, selected, target_table, output, args.dpi, args.target_gene)]
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "model_status": "executed", "validation_status": "not_assessed",
               "scientific_status": "simulated_unvalidated", "dpi": args.dpi,
               "plot_code_sha256": sha256(__file__), "parameters": vars(args) | {},
               "matched_run_checks": matched,
               "arrow_selection": {"algorithm": "smallest SHA256(seed:cell_ID), tie by cell_ID", "seed": args.seed,
                                    "cell_ids": arrow_ids, "count": len(arrow_ids)},
               "runs": {mode: {"directory": run["path"], "numerical_checks": run["checks"],
                                "input_manifest": run["manifest"], "source_hashes": run["sources"],
                                "fixed_target_setting": run["fixed"],
                                "non_target_genes_with_nonzero_delta": int((run["delta"].drop(columns=args.target_gene) != 0).any(axis=0).sum()),
                                "mean_projection_magnitude": float(run["shift"].shift_magnitude.mean()),
                                "mean_randomized_projection_magnitude": float(run["shift"].random_shift_magnitude.mean())}
                        for mode, run in runs.items()},
               "oe_target_direction_counts": target_table.oe_target_direction.value_counts().to_dict(),
               "figures": figures,
               "artifacts": {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
                             for path in sorted(output.iterdir()) if path.suffix in {".png", ".csv", ".gz"}}}
    summary["parameters"] = {key: str(value) if isinstance(value, Path) else value
                             for key, value in summary["parameters"].items()}
    write_json(output / "plot_summary.json", summary)
    print(json.dumps({"output_dir": str(output), "matched_run_checks": matched,
                      "oe_target_direction_counts": summary["oe_target_direction_counts"],
                      "figures": figures}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
