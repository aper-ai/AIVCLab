#!/usr/bin/env python3
"""Read the real PRnet HT115 demo and describe observed, paired differences.

Virtual Cell Research teaching case; no model loading, training, or prediction.
The CLI accepts only the checksum-pinned official demo. The Python-only fixture
override requires an explicit synthetic_fixture=True and is recorded as such.
"""

from __future__ import annotations

import argparse
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

import anndata as ad
import numpy as np
import pandas as pd
from scipy import sparse


CASE_ID = "prnet-ht115-demo"
SOURCE_COMMIT = "f19174bde3ed2633f54c7831799cc38c4ffc7a0d"
SOURCE_URL = (
    "https://raw.githubusercontent.com/Perturbation-Response-Prediction/PRnet/"
    f"{SOURCE_COMMIT}/dataset/demo.h5ad"
)
OFFICIAL_SHA256 = "c3bd7c7e3e08fa68062fbf2080ada31f9086359b5ab03f843b7f0efd21389d9b"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_MATRIX_ELEMENTS = 8_000_000
SCALE = "source_native_processed_scale"
REQUIRED_OBS = (
    "cell_id", "cell_type", "pert_id", "pert_iname", "condition", "pert_dose",
    "pert_dose_unit", "dose", "pert_time", "pert_time_unit", "pert_type",
    "rna_plate", "rna_well", "control", "SMILES", "canonical_smiles",
    "paired_control_index", "demo_split",
)
REQUIRED_VAR = ("pr_gene_title", "pr_is_lm", "pr_is_bing")
NUMERIC_OBS = ("pert_dose", "dose", "pert_time", "control")
CONDITION_FIELDS = (
    "pert_id", "SMILES", "cell_id", "cell_type", "pert_dose",
    "pert_dose_unit", "pert_time", "pert_time_unit", "rna_plate",
)
_INVOCATION_CONTEXT = ContextVar("observed_case_invocation", default=None)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strings(values, label: str) -> pd.Series:
    series = pd.Series(values, copy=False)
    if series.isna().any():
        raise ValueError(f"{label} contains missing values")
    text = series.astype(str)
    if text.str.strip().eq("").any():
        raise ValueError(f"{label} contains empty values")
    return text


def _numeric(values, label: str) -> np.ndarray:
    try:
        numbers = pd.to_numeric(values, errors="raise").to_numpy(dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not np.isfinite(numbers).all():
        raise ValueError(f"{label} contains non-finite values")
    return numbers


def validate_data(data: ad.AnnData) -> tuple[np.ndarray, pd.DataFrame, np.ndarray]:
    """Validate the source fields actually used; never invent a missing pairing."""
    if data.n_obs < 2 or data.n_vars < 1:
        raise ValueError("X needs at least one treatment, one control, and one gene")
    if data.n_obs * data.n_vars > MAX_MATRIX_ELEMENTS:
        raise ValueError("X exceeds the small teaching-case matrix limit")
    for frame, columns, name in (
        (data.obs, REQUIRED_OBS, "obs"), (data.var, REQUIRED_VAR, "var")
    ):
        if not frame.columns.is_unique:
            raise ValueError(f"{name} column names must be unique")
        missing = sorted(set(columns) - set(frame.columns))
        if missing:
            raise ValueError(f"Missing required {name} fields: {', '.join(missing)}")
        if not frame.index.is_unique:
            raise ValueError(f"{name} identifiers must be unique")
        _strings(frame.index, f"{name} identifiers")
    if not all(isinstance(value, str) for value in data.obs_names):
        raise ValueError("obs identifiers must be strings")
    if not all(isinstance(value, str) for value in data.var_names):
        raise ValueError("var identifiers must be strings")
    if {"source_profile_id", "condition_id", "cross_rna_plate"} & set(data.obs.columns):
        raise ValueError("obs uses a reserved tutorial output column")
    obs = data.obs.copy()
    for name in REQUIRED_OBS:
        if name not in NUMERIC_OBS and name != "demo_split":
            obs[name] = _strings(obs[name], f"obs.{name}").to_numpy()
    for name in NUMERIC_OBS:
        obs[name] = _numeric(obs[name], f"obs.{name}")
    _strings(data.var["pr_gene_title"], "var.pr_gene_title")
    for name in ("pr_is_lm", "pr_is_bing"):
        if not np.isin(_numeric(data.var[name], f"var.{name}"), [0, 1]).all():
            raise ValueError(f"var.{name} must contain binary flags")
    if not np.isin(obs["control"], [0, 1]).all():
        raise ValueError("obs.control must contain only 0 and 1")
    treated = obs["control"].eq(0).to_numpy()
    if not treated.any() or treated.all():
        raise ValueError("Both treatment and control profiles are required")
    if not obs.loc[treated, "pert_type"].eq("trt_cp").all():
        raise ValueError("Treatment profiles must have pert_type=trt_cp")
    if not obs.loc[~treated, "pert_type"].eq("ctl_vehicle").all():
        raise ValueError("Control profiles must have pert_type=ctl_vehicle")
    if not obs.loc[treated, "demo_split"].eq("test").all():
        raise ValueError("Treated demo_split values must be the source label test")
    if not obs["condition"].eq(obs["pert_iname"]).all():
        raise ValueError("condition and pert_iname disagree; do not guess the name")
    if not obs["SMILES"].eq(obs["canonical_smiles"]).all():
        raise ValueError("SMILES and canonical_smiles disagree; do not choose silently")
    if (obs.loc[treated, "pert_dose"] <= 0).any():
        raise ValueError("Treated pert_dose must be positive")
    if not obs.loc[treated, "dose"].eq(obs.loc[treated, "pert_dose"]).all():
        raise ValueError("Treated dose and pert_dose disagree")
    if not obs.loc[~treated, "dose"].eq(0).all():
        raise ValueError("Derived control dose must be zero; retain raw sentinels separately")
    if (obs["pert_time"] <= 0).any():
        raise ValueError("pert_time must be positive")
    pair_positions = obs.index.get_indexer(obs["paired_control_index"])
    if (pair_positions < 0).any():
        bad = obs.loc[pair_positions < 0, "paired_control_index"].iloc[0]
        raise ValueError(f"Missing paired control profile: {bad}")
    paired = obs.iloc[pair_positions]
    if not paired["control"].eq(1).all():
        raise ValueError("paired_control_index references a non-control profile")
    for name in ("cell_id", "cell_type", "pert_time", "pert_time_unit"):
        if not np.array_equal(obs[name].to_numpy(), paired[name].to_numpy()):
            raise ValueError(f"Paired control has mismatched {name}")
    if data.X is None:
        raise ValueError("X is missing; the tutorial reads source X only")
    matrix = data.X.toarray() if sparse.issparse(data.X) else np.asarray(data.X)
    if matrix.shape != data.shape or matrix.dtype.kind not in "fiu":
        raise ValueError("X must be a numeric profile-by-gene matrix")
    if not np.isfinite(matrix).all():
        raise ValueError("X contains non-finite values; no profiles are silently dropped")
    return matrix, obs, pair_positions


def condition_id(row: pd.Series) -> str:
    identity = {
        key: float(row[key]) if key in ("pert_dose", "pert_time") else str(row[key])
        for key in CONDITION_FIELDS
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "cond_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def render_figure(figure_data: pd.DataFrame, figure_dir: Path) -> list[str]:
    """Draw paths/text in SVG (no raster heatmap embedded in the SVG)."""
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    conditions = list(dict.fromkeys(figure_data["condition_id"]))
    genes = list(dict.fromkeys(figure_data["gene_id"]))
    values = figure_data.pivot(index="condition_id", columns="gene_id", values="observed_delta").loc[conditions, genes].to_numpy()
    labels = [figure_data.loc[figure_data.condition_id.eq(cid), "display_label"].iloc[0] for cid in conditions]
    limit = float(np.abs(values).max()) or 1.0
    with plt.rc_context({"svg.fonttype": "none", "font.size": 9}):
        fig, axis = plt.subplots(figsize=(11, max(4, len(conditions) * 0.48 + 2)))
        try:
            mesh = axis.pcolormesh(values, cmap="coolwarm", vmin=-limit, vmax=limit, rasterized=False, edgecolors="white", linewidth=0.6)
            axis.set_xticks(np.arange(len(genes)) + 0.5, genes, rotation=45, ha="right")
            axis.set_yticks(np.arange(len(conditions)) + 0.5, labels)
            axis.invert_yaxis()
            axis.set_title("Virtual Cell Research | observed HT115 response\nStable-ID selection; not a prediction or efficacy ranking", loc="left", pad=15)
            axis.set_xlabel("Genes selected by mean absolute observed difference in this displayed subset")
            colorbar = fig.colorbar(mesh, ax=axis, pad=0.025)
            colorbar.set_label("Treatment minus supplied paired control\n(source-native processed scale)")
            # Matplotlib can rasterize long colorbar gradients automatically.
            if colorbar.solids is not None:
                colorbar.solids.set_rasterized(False)
            fig.tight_layout()
            paths = []
            for suffix in ("svg", "png"):
                path = figure_dir / f"observed_response.{suffix}"
                fig.savefig(path, dpi=160, facecolor="white")
                paths.append(str(path.relative_to(figure_dir.parent)))
            return paths
        finally:
            plt.close(fig)


def run_case(input_path, output_dir, *, expected_sha=OFFICIAL_SHA256, synthetic_fixture=False) -> dict:
    """Write a new result directory; only tests may explicitly supply a fixture SHA."""
    source = Path(input_path)
    output = Path(output_dir)
    invocation = dict(_INVOCATION_CONTEXT.get() or {
        "kind": "python_api", "entrypoint": "run_case", "argv": None,
        "argv_source": "not_applicable_to_direct_python_api",
        "working_directory": str(Path.cwd()),
    })
    invocation["parameters"] = {
        "input_path": str(source), "output_dir": str(output),
        "expected_sha": expected_sha, "synthetic_fixture": synthetic_fixture,
    }
    if os.path.lexists(output):
        raise FileExistsError(f"Output directory already exists; choose a new directory: {output}")
    if expected_sha != OFFICIAL_SHA256 and not synthetic_fixture:
        raise ValueError("A non-official expected_sha requires synthetic_fixture=True")
    if synthetic_fixture and expected_sha == OFFICIAL_SHA256:
        raise ValueError("A synthetic fixture must have its own explicit expected_sha")
    if not source.is_file():
        raise ValueError(f"Input is not a regular file: {source}")
    size = source.stat().st_size
    if size <= 0 or size > MAX_INPUT_BYTES:
        raise ValueError("Input must be nonempty and no larger than 8 MiB")
    actual_sha = sha256_file(source)
    if actual_sha != expected_sha:
        raise ValueError(f"Input SHA256 mismatch: expected {expected_sha}, got {actual_sha}")
    # Read only the matrix shape before allocating the full AnnData object.
    import h5py
    with h5py.File(source, "r") as handle:
        node = handle.get("X")
        shape = node.shape if isinstance(node, h5py.Dataset) else (node.attrs.get("shape") if node is not None else None)
        if shape is None or len(shape) != 2 or int(shape[0]) * int(shape[1]) > MAX_MATRIX_ELEMENTS:
            raise ValueError("Missing, invalid, or oversized X shape")
    data = ad.read_h5ad(source)
    matrix, obs, pair_positions = validate_data(data)
    treated_positions = np.flatnonzero(obs["control"].eq(0).to_numpy())
    treated = obs.iloc[treated_positions].copy()
    treated.index.name = "source_profile_id"
    paired = obs.iloc[pair_positions[treated_positions]]
    delta = matrix[treated_positions].astype(np.float64) - matrix[pair_positions[treated_positions]].astype(np.float64)
    if not np.isfinite(delta).all():
        raise ValueError("Observed subtraction produced non-finite values")
    treated["condition_id"] = treated.apply(condition_id, axis=1)
    treated["paired_rna_plate"] = paired["rna_plate"].to_numpy()
    treated["cross_rna_plate"] = treated["rna_plate"].to_numpy() != paired["rna_plate"].to_numpy()
    genes = np.asarray(data.var_names, dtype=str)
    profiles = np.asarray(data.obs_names, dtype=str)
    treatment_ids = np.asarray(treated.index, dtype=str)
    unique_conditions = sorted(treated["condition_id"].unique())
    mean_deltas, summaries, top_genes = [], [], []
    for cid in unique_conditions:
        positions = np.flatnonzero(treated["condition_id"].eq(cid).to_numpy())
        group = treated.iloc[positions]
        if len(group[list(CONDITION_FIELDS)].drop_duplicates()) != 1:
            raise ValueError("Condition identity hash collision")
        row = group.iloc[0]
        mean_delta = delta[positions].mean(axis=0)
        mean_deltas.append(mean_delta)
        item = {"condition_id": cid, **{key: row[key] for key in CONDITION_FIELDS}}
        item.update({
            "pert_iname": row["pert_iname"], "n_profiles": len(group),
            "n_supplied_controls": group["paired_control_index"].nunique(),
            "cross_rna_plate_profiles": int(group["cross_rna_plate"].sum()),
            "mean_absolute_observed_delta": float(np.abs(mean_delta).mean()),
            "l2_of_mean_observed_delta": float(np.linalg.norm(mean_delta)),
            "scale": SCALE,
        })
        summaries.append(item)
        order = np.lexsort((genes, -np.abs(mean_delta)))[:min(10, len(genes))]
        for rank, gene_pos in enumerate(order, start=1):
            top_genes.append({"condition_id": cid, "rank_by_absolute_observed_delta": rank,
                              "gene_id": genes[gene_pos], "mean_observed_delta": float(mean_delta[gene_pos]),
                              "n_profiles": len(group), "scale": SCALE})
    means = np.stack(mean_deltas)
    ambiguities = []
    for name, group in treated.groupby("pert_iname", sort=True, observed=True):
        if group["SMILES"].nunique() > 1:
            ambiguities.append({"pert_iname": str(name), "source_smiles": sorted(group["SMILES"].unique()),
                                "pert_ids": sorted(group["pert_id"].unique()),
                                "profile_count": len(group)})
    warnings = []
    cross_count = int(treated["cross_rna_plate"].sum())
    if cross_count:
        warnings.append({"code": "cross_rna_plate_pairing", "profiles": cross_count,
                         "action": "kept_source_pairing_without_reassignment"})
    if ambiguities:
        warnings.append({"code": "name_has_multiple_source_smiles", "names": len(ambiguities),
                         "action": "conditions_use_pert_id_smiles_dose_time_cell_and_plate"})
    qc = {
        "status": "passed_with_warnings" if warnings else "passed",
        "profiles": data.n_obs, "genes": data.n_vars,
        "treated_profiles": len(treated), "control_profiles": data.n_obs - len(treated),
        "condition_count": len(unique_conditions), "treated_pert_ids": int(treated["pert_id"].nunique()),
        "treated_names": int(treated["pert_iname"].nunique()),
        "all_required_fields_present": True, "finite_X": True, "finite_observed_delta": True,
        "unique_profile_and_gene_ids": True, "all_supplied_pairs_exist": True,
        "all_supplied_pairs_reference_controls": True, "paired_cell_and_time_match": True,
        "cross_rna_plate_treated_profiles": cross_count, "warnings": warnings,
        "ambiguous_names": ambiguities, "chemical_equivalence_assessment": "not_performed",
        "scale": SCALE, "model_status": "not_run", "independent_validation": "not_assessed",
    }
    # Stable-ID selection avoids presenting the figure as a drug efficacy ranking.
    display_count = min(8, len(unique_conditions))
    gene_order = np.lexsort((genes, -np.abs(means[:display_count]).mean(axis=0)))[:min(12, len(genes))]
    figure_rows = []
    for position, cid in enumerate(unique_conditions[:display_count]):
        info = summaries[position]
        label = f"{info['pert_iname'][:19]} | {info['pert_dose']:g} {info['pert_dose_unit']} | {cid[-6:]}"
        for gene_pos in gene_order:
            figure_rows.append({"condition_id": cid, "display_label": label, "gene_id": genes[gene_pos],
                                "observed_delta": float(means[position, gene_pos]), "scale": SCALE})
    figure_data = pd.DataFrame(figure_rows)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("raw", "tables", "figures"):
        (output / folder).mkdir()
    np.savez_compressed(output / "raw/source_profiles.npz", X=matrix, profile_ids=profiles, gene_ids=genes)
    np.savez_compressed(output / "raw/observed_responses.npz", observed_delta=delta, profile_ids=treatment_ids,
                        paired_control_ids=np.asarray(treated["paired_control_index"], dtype=str), gene_ids=genes,
                        condition_ids=np.asarray(treated["condition_id"], dtype=str))
    # Preserve original metadata, including raw control dose sentinels and test labels.
    data.obs.to_csv(output / "tables/source_profiles.csv", index_label="source_profile_id")
    data.var.to_csv(output / "tables/source_genes.csv", index_label="gene_id")
    treated.to_csv(output / "tables/condition_index.csv", index_label="source_profile_id")
    compression = {"method": "gzip", "mtime": 0}
    pd.DataFrame(delta, index=treatment_ids, columns=genes).to_csv(
        output / "tables/observed_responses.csv.gz", index_label="source_profile_id", float_format="%.17g", compression=compression)
    pd.DataFrame(means, index=unique_conditions, columns=genes).to_csv(
        output / "tables/condition_mean_responses.csv.gz", index_label="condition_id", float_format="%.17g", compression=compression)
    pd.DataFrame(summaries).to_csv(output / "tables/condition_summary.csv", index=False)
    pd.DataFrame(top_genes).to_csv(output / "tables/top_observed_genes.csv", index=False)
    figure_data.to_csv(output / "tables/figure_data.csv", index=False)
    figure_status = {"selection": "first_8_condition_ids_sorted_then_top_12_genes_by_mean_absolute_observed_delta",
                     "data": "tables/figure_data.csv", "interpretation": "descriptive_only"}
    try:
        figure_status.update({"status": "generated", "paths": render_figure(figure_data, output / "figures")})
    except Exception as exc:  # Plotting cannot erase already computed observation tables.
        figure_status.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}",
                              "paths": [str(p.relative_to(output)) for p in sorted((output / "figures").glob("observed_response.*"))]})
        qc["warnings"].append({"code": "figure_failed", "reason": figure_status["reason"]})
        qc["status"] = "passed_with_warnings"
    _write_json(output / "figure_manifest.json", figure_status)
    _write_json(output / "qc.json", qc)
    source_kind = "synthetic_test_fixture" if synthetic_fixture else "official_PRnet_HT115_demo"
    if figure_status["status"] == "generated" and (output / "figures/observed_response.png").is_file():
        figure_preview = (
            "![本次实际生成的观测响应子集；仅作描述性展示](figures/observed_response.png)\n\n"
            "[矢量 SVG](figures/observed_response.svg) · [图中完整数值](tables/figure_data.csv) · "
            "[图清单](figure_manifest.json)"
        )
    else:
        figure_preview = (
            "本次未生成可用预览图；完整观测矩阵、源表和 QC 已保留。"
            "请先查看[图清单及失败原因](figure_manifest.json)，再读取[图中数值](tables/figure_data.csv)。\n\n"
            f"绘图信息：{figure_status.get('reason', 'PNG preview is unavailable')}"
        )
    report = f"""# Virtual Cell Research — HT115 实测响应入门案例

案例：`{CASE_ID}`；数据身份：`{source_kind}`。

## 这次做了什么

读取 {data.n_obs} 个真实来源 profile、{data.n_vars} 个基因；其中 {len(treated)} 个处理 profile、{data.n_obs - len(treated)} 个 vehicle 对照。按原始 `paired_control_index` 计算每个处理 profile 的 **观测表达差值 = 处理后 X − 其指定对照 X**，未重分配对照，未再归一化或变换 X。按稳定扰动 ID、原始 SMILES、剂量及单位、时间及单位、细胞背景和 RNA plate 生成 {len(unique_conditions)} 个条件 ID。

表达尺度是 `{SCALE}`。它不是原始计数、表达倍数或预测。一个 profile 是这份 L1000 来源数据的一条表达谱；不要将它当成单细胞，也不要把指定对照理解为同一个细胞干预前后的追踪测量。

## 如何阅读产物

1. [profile 元数据](tables/source_profiles.csv)和[基因元数据](tables/source_genes.csv)保留原始字段；[来源 X 与行列 ID](raw/source_profiles.npz)保留读取的原始数值。
2. [逐 profile 对照与条件索引](tables/condition_index.csv)显示原始对照、条件 ID、对照 plate 和跨板标记。[完整观测响应 NPZ](raw/observed_responses.npz) 与[完整观测响应 CSV](tables/observed_responses.csv.gz)保存全部 {len(treated)} × {data.n_vars} 个观测差值。NPZ 可用 `numpy.load(path, allow_pickle=False)` 读取。
3. [条件平均响应](tables/condition_mean_responses.csv.gz)是条件内 profile 差值的均值。[条件汇总](tables/condition_summary.csv)的幅度仅是描述性统计；profile 数不能直接当作独立生物学重复数。
4. [Top 观测变化基因](tables/top_observed_genes.csv)按每条件绝对观测差值选最多 10 个基因，保留正负号；没有 P 值，不称为统计显著差异基因。
5. 图先按条件稳定 ID 取最多 8 个条件，再取该子集平均绝对差值最大的最多 12 个基因；这是示意选择，不是药效排名。可查看[完整图数据](tables/figure_data.csv)和[图清单](figure_manifest.json)（本次 `{figure_status['status']}`）。SVG 为矢量路径/文字，PNG 供预览。

## 观测响应预览

{figure_preview}

## 必须连同结果阅读的限制

- {cross_count} 个处理 profile 的指定对照跨 RNA plate。保留来源配对并标记，差值可能包含批次差异。
- {len(ambiguities)} 个药物名对应多条来源 SMILES，详见 [QC 记录](qc.json)。没有进行化学等价性判断，未仅按名称合并。
- 原始对照 `pert_dose=-666` / `pert_dose_unit=-666` 是来源占位值，不能解释成浓度；派生 `dose=0` 另行保留。
- 这是已处理表达尺度上的实测数据阅读案例，不能据此确定药敏、疗效或临床候选药物；不输出临床用药建议。
- `model_status: not_run`；没有加载权重或执行 PRnet 推理。`independent_validation: not_assessed`；来源 `demo_split=test` 标签不足以证明相对任何预训练模型的独立验证。这不是 PRnet 模型复现。

## 来源与复查

官方来源：{SOURCE_URL if not synthetic_fixture else 'Synthetic fixture generated by tests; not experimental evidence.'}

SHA256：`{actual_sha}`。来源提交：`{SOURCE_COMMIT if not synthetic_fixture else 'not_applicable'}`。

官方仓库代码标为 Apache-2.0；此 demo 文件未单独标识数据许可，不能把本 Skill 的许可自动套用到数据。PRnet 论文：https://doi.org/10.1038/s41467-024-53457-1 。完整来源、解释器、调用参数、版本和产物校验和见 [provenance.json](provenance.json)；数据检查结果见 [qc.json](qc.json)。本脚本只引用来源，不内嵌数据，不下载或调用模型。
"""
    if synthetic_fixture:
        report = "# SYNTHETIC TEST FIXTURE — not real experimental evidence\n\n" + report
    (output / "report.md").write_text(report, encoding="utf-8")
    packages = {name: importlib.metadata.version(name) for name in ("anndata", "numpy", "pandas", "scipy", "h5py")}
    try:
        packages["matplotlib"] = importlib.metadata.version("matplotlib")
    except importlib.metadata.PackageNotFoundError:
        # Matplotlib is optional: its absence must not discard the numeric run.
        packages["matplotlib"] = None
    provenance = {
        "schema_version": 1, "project": "Virtual Cell Research", "case_id": CASE_ID,
        "created_at": datetime.now(timezone.utc).isoformat(), "source_kind": source_kind,
        "source_path": str(source.resolve()), "source_bytes": size, "source_sha256": actual_sha,
        "source_url": None if synthetic_fixture else SOURCE_URL,
        "source_commit": None if synthetic_fixture else SOURCE_COMMIT,
        "data_license": "not_applicable_synthetic_fixture" if synthetic_fixture else "not_separately_specified_for_demo_file",
        "source_repository_code_license": None if synthetic_fixture else "Apache-2.0",
        "script_sha256": sha256_file(Path(__file__)), "scale": SCALE,
        "operation": "source_X_treatment_minus_source_X_supplied_paired_control",
        "normalization_applied": False, "pairing_reassigned": False,
        "condition_identity_fields": list(CONDITION_FIELDS),
        "model_status": "not_run", "independent_validation": "not_assessed",
        "statistics": "descriptive_only_no_pvalues_no_efficacy_ranking",
        "python": platform.python_version(),
        "sys_executable": sys.executable, "invocation": invocation,
        "packages": packages,
        "artifacts": {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
                      for path in sorted(output.rglob("*")) if path.is_file()},
    }
    _write_json(output / "provenance.json", provenance)
    return {"output_dir": str(output.resolve()), "qc": qc, "figure": figure_status, "provenance": provenance}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Virtual Cell Research: inspect the checksum-pinned real HT115 demo; no model inference.")
    result.add_argument("--input", required=True, type=Path, help="Official PRnet dataset/demo.h5ad (at most 8 MiB)")
    result.add_argument("--output-dir", required=True, type=Path, help="New result directory; existing paths are never overwritten")
    return result


def main(argv=None) -> int:
    explicit_argv = None if argv is None else list(argv)
    args = parser().parse_args(explicit_argv)
    invocation = {
        "kind": "cli" if __name__ == "__main__" and explicit_argv is None else "python_main",
        "entrypoint": "main",
        "argv": list(sys.argv) if explicit_argv is None else explicit_argv,
        "argv_source": "sys.argv" if explicit_argv is None else "main(argv)",
        "working_directory": str(Path.cwd()),
    }
    token = _INVOCATION_CONTEXT.set(invocation)
    try:
        result = run_case(args.input, args.output_dir)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Observed-case error: {exc}", file=sys.stderr)
        return 2
    finally:
        _INVOCATION_CONTEXT.reset(token)
    print(json.dumps({"output_dir": result["output_dir"], "profiles": result["qc"]["profiles"],
                      "treated_profiles": result["qc"]["treated_profiles"], "genes": result["qc"]["genes"],
                      "model_status": "not_run", "independent_validation": "not_assessed",
                      "figure_status": result["figure"]["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
