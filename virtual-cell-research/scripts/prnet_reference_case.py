#!/usr/bin/env python3
"""Run a pinned official PRnet checkpoint on its official HT115 reference data.

This is an internal reference evaluation, not independent validation. Heavy
model dependencies are imported only by run; fetch never executes model code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import sys

import numpy as np

CASE_ID = "prnet-reference-evaluation"
COMMIT = "f19174bde3ed2633f54c7831799cc38c4ffc7a0d"
BASE = f"https://raw.githubusercontent.com/Perturbation-Response-Prediction/PRnet/{COMMIT}/"
SCALE = "official_demo_normalize_total_median_then_log1p"
# Source files remain external resources; no PRnet implementation or weights
# are copied into this Skill's source distribution.
_FILES = (
    ("model", "PRnet.py", "models/PRnet.py", 10794, "024f39a07e2887fea45a42f60b07b3ba17dc7501f134285ff72798eacb8bea3e"),
    ("encoding", "_utils.py", "data/_utils.py", 9406, "b72ad61f7e4e1389a62ce50db144627e1d5d5f16fccee4c17f05ab29328d4b5e"),
    ("weights", "lincs_best_epoch_all.pt", "checkpoint/lincs_best_epoch_all.pt", 2210427, "f4b69f6fbcbfab3636b1e0a9eb64c32ccf61ea48431f05ba8433e3678713e8c8"),
    ("demo", "demo.h5ad", "dataset/demo.h5ad", 3136818, "c3bd7c7e3e08fa68062fbf2080ada31f9086359b5ab03f843b7f0efd21389d9b"),
    ("official-demo", "test_demo.py", "test_demo.py", 3244, "7adc897816106a78d5ec357a808a4ee1e14c3c90a04a23a546a0efacdbb3d84d"),
    ("official-trainer", "PRnetTrainer.py", "trainer/PRnetTrainer.py", 27021, "0d0eb2d8e19ce284d56313667fc2ffb532050ede8b93b4a40bc5ffa6329e8038"),
    ("license", "LICENSE", "LICENSE", 11357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
)
RESOURCES = [
    {"id": rid, "file_name": name, "source_path": source, "url": BASE + source,
     "bytes": size, "sha256": sha,
     "format": "h5ad" if rid == "demo" else "pytorch_state_dict" if rid == "weights" else "text",
     "license_status": "not_separately_specified_for_file" if rid in {"demo", "weights"} else "Apache-2.0",
     "license_url": "https://github.com/Perturbation-Response-Prediction/PRnet/blob/" + COMMIT + "/LICENSE"}
    for rid, name, source, size, sha in _FILES
]


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def resource_paths(root):
    """Verify every resource before importing external code or loading weights."""
    root = Path(root)
    paths = {}
    for resource in RESOURCES:
        path = root / resource["id"] / resource["file_name"]
        if not path.is_file() or path.stat().st_size != resource["bytes"]:
            raise ValueError(f"Missing or wrong-size resource: {path}")
        if sha256_file(path) != resource["sha256"]:
            raise ValueError(f"SHA256 mismatch; refusing to load {path}")
        paths[resource["id"]] = path
    return paths


def fetch_resources(output_dir, reuse_dir=None):
    """Explicitly fetch the seven small, pinned files; never run them here."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    catalogue = _module(Path(__file__).with_name("cases.py"), "vcr_case_downloader")
    case = {"id": CASE_ID, "title": "PRnet official reference resources", "task": "drug_reference_evaluation",
            "context": "HT115 official demo; checkpoint training membership unknown",
            "sources": [{"title": "PRnet fixed source", "url": BASE + "README.md"}],
            "stage": "catalogued", "model_status": "not_run", "validation_status": "not_assessed",
            "resources": RESOURCES, "limitations": ["Downloading is not model execution."], "expected_outputs": []}
    record = {"case_id": CASE_ID, "status": "downloading", "model_status": "not_run", "resources": []}
    _json(root / "resources.json", record)
    try:
        for resource in RESOURCES:
            cached = None if reuse_dir is None else Path(reuse_dir) / resource["id"] / resource["file_name"]
            if cached is not None and cached.exists():
                if not cached.is_file() or cached.stat().st_size != resource["bytes"] or sha256_file(cached) != resource["sha256"]:
                    raise ValueError(f"Cached resource identity mismatch: {cached}; nothing was overwritten")
                destination = root / resource["id"] / resource["file_name"]
                destination.parent.mkdir()
                shutil.copyfile(cached, destination)
                result = {"status": "reused_verified", "asset_id": resource["id"], "url": resource["url"],
                          "cached_from": str(cached.resolve()), "bytes": resource["bytes"], "sha256": resource["sha256"],
                          "expected_sha256_verified": True, "model_status": "not_run"}
                _json(destination.parent / "fetch_record.json", result)
            else:
                result = catalogue.fetch_resource(case, resource, root / resource["id"], max_mib=8)
            record["resources"].append(result)
            if result["status"] not in {"downloaded", "reused_verified"}:
                raise ValueError(f"Resource {resource['id']} failed: {result['error']}")
        resource_paths(root)
        record["status"] = "ready"
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        _json(root / "resources.json", record)
        raise
    _json(root / "resources.json", record)
    return record


def row_metrics(observed, predicted):
    """Row-wise errors and Pearson; constant vectors have undefined correlation."""
    observed, predicted = np.asarray(observed, dtype=np.float64), np.asarray(predicted, dtype=np.float64)
    if observed.ndim != 2 or observed.shape != predicted.shape or not observed.size:
        raise ValueError("Metric matrices must be nonempty and have identical two-dimensional shapes")
    if not np.isfinite(observed).all() or not np.isfinite(predicted).all():
        raise ValueError("Metric matrices must be finite")
    a = observed - observed.mean(axis=1, keepdims=True)
    b = predicted - predicted.mean(axis=1, keepdims=True)
    denom = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
    corr = np.full(len(observed), np.nan)
    valid = denom > 1e-14
    corr[valid] = np.clip(np.sum(a[valid] * b[valid], axis=1) / denom[valid], -1, 1)
    error = predicted - observed
    return {"rmse": np.sqrt(np.mean(error ** 2, axis=1)),
            "mae": np.mean(np.abs(error), axis=1), "pearson": corr}


def exclusion_groups(pert_ids, names, canonical_smiles):
    """Conservatively link aliases so no drug group contributes to its own mean.

    Equality of any source pert_id, case-folded source name or RDKit canonical
    isomeric SMILES joins a component. This is an exclusion rule, not a claim
    that every member of the component is experimentally interchangeable.
    """
    columns = [list(pert_ids), list(names), list(canonical_smiles)]
    if not columns[0] or len({len(c) for c in columns}) != 1:
        raise ValueError("Exclusion identities need matching nonempty lengths")
    parent, owner = list(range(len(columns[0]))), {}
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, row in enumerate(zip(*columns)):
        for kind, value in enumerate(row):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Drug exclusion identity is missing")
            key = (kind, value.strip().casefold() if kind == 1 else value)
            if key in owner:
                parent[find(i)] = find(owner[key])
            else:
                owner[key] = i
    components = {}
    for i in range(len(parent)):
        components.setdefault(find(i), []).append(i)
    result = np.empty(len(parent), dtype="U24")
    for members in components.values():
        identity = sorted({str(columns[0][i]) + "|" + columns[2][i] for i in members})
        key = "exclude_" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        result[members] = key
    return result


def leave_group_out_mean(observed_delta, groups):
    """Other-demo-group mean; it is a diagnostic reference, not external data."""
    delta = np.asarray(observed_delta, dtype=np.float64)
    groups = np.asarray(groups)
    if delta.ndim != 2 or len(delta) != len(groups) or not np.isfinite(delta).all():
        raise ValueError("Invalid delta/group alignment")
    if len(set(groups)) < 2:
        raise ValueError("Other-group reference requires at least two drug exclusion groups")
    total, result = delta.sum(axis=0), np.zeros_like(delta)
    for group in np.unique(groups):
        mask = groups == group
        result[mask] = (total - delta[mask].sum(axis=0)) / int((~mask).sum())
    return result


def _mean_or_none(values):
    values = np.asarray(values)
    finite = values[np.isfinite(values)]
    return None if not finite.size else float(finite.mean())


def preprocess_reference_data(adata, scanpy_module):
    """Preserve source bytes before the official preprocessing mutates X."""
    source = np.asarray(adata.X).copy()
    row_totals = source.sum(axis=1)
    target_sum = float(np.median(row_totals[row_totals > 0]))
    scanpy_module.pp.normalize_total(adata)
    scanpy_module.pp.log1p(adata)
    processed = np.asarray(adata.X, dtype=np.float32)
    if not np.isfinite(processed).all():
        raise ValueError("Official preprocessing produced nonfinite values")
    return source, processed, target_sum


def render_figure(table, summary, output):
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    labels = {"prnet_mean": "PRnet: mean of noise draws", "prnet_sample": "PRnet: one Gaussian sample",
              "no_change": "No-change reference", "other_group_mean": "Other demo groups (descriptive)"}
    with plt.rc_context({"svg.fonttype": "none", "font.size": 9}):
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
        try:
            for method in ("prnet_mean", "prnet_sample", "other_group_mean"):
                values = table.loc[table.method.eq(method), "pearson"].dropna()
                axes[0].hist(values, bins=np.linspace(-1, 1, 26), histtype="step", linewidth=1.8, label=labels[method])
            axes[0].set(xlabel="Pearson across 978 genes (response delta)", ylabel="Treatment profiles")
            axes[0].legend(fontsize=8)
            methods = list(labels)
            axes[1].barh(range(len(methods)), [summary[m]["mean_profile_rmse"] for m in methods], color=["#24577A", "#6B94AD", "#888888", "#B48256"])
            axes[1].set_yticks(range(len(methods)), [labels[m] for m in methods])
            axes[1].invert_yaxis()
            axes[1].set_xlabel("Mean profile RMSE (same processed log scale)")
            fig.suptitle("PRnet official HT115 reference evaluation\nTraining overlap unknown; this is not independent validation", fontsize=12)
            fig.tight_layout()
            paths = []
            for suffix in ("svg", "png"):
                path = output / "figures" / f"reference_metrics.{suffix}"
                fig.savefig(path, dpi=150, facecolor="white")
                paths.append(path.relative_to(output).as_posix())
            return paths
        finally:
            plt.close(fig)


def _run_model(paths, output, seed, noise_draws, threads, manifest):
    # These libraries are intentionally absent from fast-test requirements.
    import anndata as ad
    import pandas as pd
    import scanpy as sc
    import torch
    from rdkit import Chem
    from rdkit import rdBase

    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)
    validator = _module(Path(__file__).with_name("observed_prnet_case.py"), "vcr_observed_validator")
    adata = ad.read_h5ad(paths["demo"])
    source_matrix, obs, paired_positions = validator.validate_data(adata)
    if adata.shape != (681, 978) or not np.isfinite(source_matrix).all() or (source_matrix < 0).any():
        raise ValueError("Official demo identity/shape/nonnegative-scale contract failed")
    # Preserve the exact official demo preprocessing, including its use of the
    # median sum of ALL demo profiles. This transductive reference choice is
    # disclosed and is not presented as a deployment/held-out preprocessing fit.
    source_matrix, matrix, target_sum = preprocess_reference_data(adata, sc)
    treated_pos = np.flatnonzero(obs.control.eq(0).to_numpy())
    treated = obs.iloc[treated_pos].copy()
    treated.index.name = "source_profile_id"
    baseline = matrix[paired_positions[treated_pos]]
    observed = matrix[treated_pos]
    observed_delta = observed.astype(np.float64) - baseline
    treated["condition_id"] = treated.apply(validator.condition_id, axis=1)
    treated["paired_rna_plate"] = obs.iloc[paired_positions[treated_pos]].rna_plate.to_numpy()
    treated["cross_rna_plate"] = treated.rna_plate.to_numpy() != treated.paired_rna_plate.to_numpy()
    canonical = []
    for smiles in treated.SMILES:
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise ValueError("Source SMILES cannot be parsed; no condition is silently dropped")
        canonical.append(Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True))
    treated["evaluation_canonical_smiles"] = canonical
    groups = exclusion_groups(treated.pert_id, treated.pert_iname, canonical)
    treated["exclusion_group"] = groups

    model_module = _module(paths["model"], "vcr_pinned_prnet_model")
    encoding_module = _module(paths["encoding"], "vcr_pinned_prnet_encoding")
    # The official implementation provides both the architecture and FCFP4 +
    # log10(dose+1) encoder. Do not substitute a new neural architecture here.
    model = model_module.PGM(978, 64, 10, hidden_layer_sizes=[128], z_dimension=64,
                             adaptor_layer_sizes=[128], comb_adapt_dim=1024, dr_rate=0.05)
    state = torch.load(paths["weights"], map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    # RDKit's deprecation messages are repetitive; parsing errors remain visible.
    with rdBase.BlockLogs():
        encoded = encoding_module.Drug_dose_encoder(treated.SMILES.to_list(), treated.dose.to_list(), num_Bits=1024, comb_num=1)
    encoded = np.asarray(encoded, dtype=np.float32)
    if encoded.shape != (len(treated), 1024) or not np.isfinite(encoded).all():
        raise ValueError("Official compound/dose encoding is invalid")
    generator = torch.Generator(device="cpu").manual_seed(seed)
    x, c = torch.from_numpy(baseline), torch.from_numpy(encoded)
    means, variances, noise_values = [], [], []
    sampled = None
    with torch.inference_mode():
        for draw in range(noise_draws):
            noise = torch.randn((len(treated), 10), generator=generator)
            raw = model(x, c, noise)
            mean = torch.clamp(raw[:, :978], min=1e-3, max=1e3)
            variance = torch.nn.functional.softplus(raw[:, 978:])
            sd = torch.clamp(torch.sqrt(variance), min=1e-3, max=1e3)
            if not torch.isfinite(mean).all() or not torch.isfinite(sd).all():
                raise ValueError("Model output contains nonfinite values")
            means.append(mean.numpy().copy())
            variances.append((sd ** 2).numpy().copy())
            noise_values.append(noise.numpy().copy())
            if draw == 0:
                sampled = (mean + sd * torch.randn(mean.shape, generator=generator)).numpy().copy()
        # A shared control and noise isolate chemical/dose sensitivity from
        # profile baseline differences and random draws. The reference control
        # is the mean of the 20 PROCESSED controls, not the mean source profile.
        fixed_baseline = matrix[obs.control.eq(1).to_numpy()].mean(axis=0)
        fixed_x = torch.from_numpy(np.repeat(fixed_baseline[None], len(treated), axis=0))
        fixed_n = torch.zeros((len(treated), 10), dtype=torch.float32)
        fixed_prediction = torch.clamp(model(fixed_x, c, fixed_n)[:, :978], min=1e-3, max=1e3).numpy().copy()
    manifest.update(model_status="executed", prediction_status="success")
    mean_stack, var_stack = np.stack(means), np.stack(variances)
    predicted = mean_stack.astype(np.float64).mean(axis=0)
    predicted_delta = predicted - baseline
    sample_delta = sampled.astype(np.float64) - baseline
    other_delta = leave_group_out_mean(observed_delta, groups)
    deltas = {"prnet_mean": predicted_delta, "prnet_sample": sample_delta,
              "no_change": np.zeros_like(observed_delta), "other_group_mean": other_delta}
    rows, gene_rows, summary = [], [], {}
    for method, delta in deltas.items():
        metrics = row_metrics(observed_delta, delta)
        gene_metrics = row_metrics(observed_delta.T, delta.T)
        expression = row_metrics(observed, delta + baseline)
        summary[method] = {"mean_profile_rmse": float(metrics["rmse"].mean()),
                           "mean_profile_mae": float(metrics["mae"].mean()),
                           "mean_profile_pearson": _mean_or_none(metrics["pearson"]),
                           "profile_pearson_defined": int(np.isfinite(metrics["pearson"]).sum()),
                           "mean_gene_pearson": _mean_or_none(gene_metrics["pearson"]),
                           "gene_pearson_defined": int(np.isfinite(gene_metrics["pearson"]).sum()),
                           "mean_profile_post_expression_pearson": _mean_or_none(expression["pearson"])}
        for i, profile in enumerate(treated.index):
            rows.append({"source_profile_id": profile, "condition_id": treated.condition_id.iloc[i], "method": method,
                         **{key: float(value[i]) for key, value in metrics.items()},
                         "post_expression_pearson": float(expression["pearson"][i]), "scale": SCALE})
        for i, gene in enumerate(adata.var_names):
            gene_rows.append({"gene_id": gene, "method": method, **{key: float(value[i]) for key, value in gene_metrics.items()}, "scale": SCALE})
    table = pd.DataFrame(rows)
    table.to_csv(output / "tables/profile_metrics.csv", index=False)
    pd.DataFrame(gene_rows).to_csv(output / "tables/gene_metrics.csv", index=False)
    treated.to_csv(output / "tables/condition_index.csv", index_label="source_profile_id")
    adata.var.to_csv(output / "tables/gene_index.csv", index_label="gene_id")
    np.savez_compressed(output / "raw/reference_predictions.npz",
        source_X=source_matrix, source_profile_ids=np.asarray(adata.obs_names, dtype=str),
        profile_ids=np.asarray(treated.index, dtype=str), gene_ids=np.asarray(adata.var_names, dtype=str),
        paired_control_ids=np.asarray(treated.paired_control_index, dtype=str),
        condition_ids=np.asarray(treated.condition_id, dtype=str), exclusion_groups=groups,
        processed_X=matrix, baseline=baseline, observed_post=observed, observed_delta=observed_delta,
        predicted_post_mean=predicted, predicted_delta=predicted_delta, gaussian_sample_post=sampled,
        gaussian_sample_delta=sample_delta, mean_aleatoric_variance=var_stack.astype(np.float64).mean(axis=0),
        noise_induced_mean_variance=mean_stack.astype(np.float64).var(axis=0),
        sampled_noise=np.stack(noise_values), other_group_mean_delta=other_delta,
        fixed_baseline=fixed_baseline, fixed_prediction=fixed_prediction)
    for name, values in {"observed_delta": observed_delta, "predicted_delta": predicted_delta,
                         "other_group_mean_delta": other_delta}.items():
        pd.DataFrame(values, index=treated.index, columns=adata.var_names).to_csv(
            output / "tables" / f"{name}.csv.gz", index_label="source_profile_id",
            compression={"method": "gzip", "mtime": 0}, float_format="%.17g")
    fixed_delta = fixed_prediction.astype(np.float64) - fixed_baseline
    energy = float(np.mean(fixed_delta ** 2))
    variation = float(np.mean(np.var(fixed_delta, axis=0)))
    sensitivity = {"background": "mean_of_20_processed_controls", "noise": "same_zero_vector_for_all_conditions",
                   "mean_squared_response": energy, "mean_gene_variance_across_conditions": variation,
                   "chemical_variation_to_total_rms_ratio": float(np.sqrt(variation / energy)) if energy else None,
                   "nearly_constant_at_absolute_tolerance_1e_8": bool(np.max(np.std(fixed_delta, axis=0)) < 1e-8),
                   "interpretation": "Input sensitivity diagnostic; does not establish drug accuracy or efficacy."}
    validation = {"status": "unvalidated", "independent_validation": "not_assessed", "training_overlap": "unknown",
                  "holdout_status": "not_established", "dataset_role": "official_checkpoint_reference_demo",
                  "source_split": "demo_split=test for 661 treatments; not a training-membership certificate",
                  "checkpoint_split_binding": "Published all checkpoint has no verified sample/compound membership manifest.",
                  "mean_reference": "Leave connected drug group out of THIS demo. Excludes shared pert_id/name/canonical isomeric SMILES; descriptive, not external or deployable.",
                  "preprocessing_scope": "Official default median normalization uses all 681 demo profiles including observed treatments; transductive reference evaluation.",
                  "inference_adaptation": "Official PGM and dose encoder, fixed CPU order/seed; 16 by default decoder-noise draws averaged, plus one Gaussian sample. Not byte-for-byte original shuffled Trainer output.",
                  "metrics": summary}
    qc = {"status": "passed_with_warnings", "profiles": len(treated), "genes": adata.n_vars,
          "source_profiles": adata.n_obs, "controls": int(obs.control.eq(1).sum()),
          "all_profile_and_gene_ids_preserved": True, "finite_predictions": True,
          "cross_rna_plate_profiles": int(treated.cross_rna_plate.sum()),
          "drug_exclusion_groups": len(np.unique(groups)), "scale": SCALE,
          "normalization_target_sum": target_sum, "chemical_sensitivity": sensitivity,
          "warnings": ["training_overlap_unknown", "transductive_demo_normalization", "source_cross_plate_pairs_preserved",
                       "no_clinical_efficacy_or_independent_validation", "other_group_mean_is_demo_derived_reference"]}
    _json(output / "validation.json", validation)
    _json(output / "qc.json", qc)
    figure = {"status": "generated", "data": "tables/profile_metrics.csv", "paths": []}
    try:
        figure["paths"] = render_figure(table, summary, output)
    except Exception as exc:
        figure.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    pd.DataFrame([{"figure_id": "reference_metrics", "task": "drug", "condition": "all_source_demo_treatments",
                   "backend": "PRnet", "output_type": "expression", "question": "Reference response errors and correlations",
                   "plot_path": ";".join(figure["paths"]), "source_table": figure["data"], "metric": "RMSE/Pearson",
                   "unit": SCALE, "baseline_source": "source_paired_control", "status": figure["status"],
                   "reason": figure.get("reason", "")}]).to_csv(output / "figures/figure_manifest.csv", index=False)
    preview = "![真实模型参照评估](figures/reference_metrics.png)" if figure["status"] == "generated" else "绘图失败；请查看[图清单](figures/figure_manifest.csv)，数值结果已保留。"
    numbers = "\n".join(f"| {method} | {v['mean_profile_rmse']:.6f} | {v['mean_profile_pearson'] if v['mean_profile_pearson'] is not None else '未定义（常数响应）'} |" for method, v in summary.items())
    report = f"""# PRnet 官方 HT115 参照评估

**实际加载官方 2.21 MB checkpoint 并在 CPU 运行了 {len(treated)} 条处理表达谱。训练重叠未知，独立验证未评估。**

## 本次结果

| 方法 | 平均逐 profile 响应 RMSE | 平均逐 profile 响应 Pearson |
| --- | ---: | ---: |
{numbers}

{preview}

同一尺度下，响应 = 处理后表达 − 原始指定对照。主要比较响应差值；绝对表达相关往往会保留较强的基因间基线结构，不能用高绝对表达相关替代响应预测准确性。零响应基线的响应 Pearson 未定义，不补成 0。

## 这次怎样调用模型

固定官方提交 `{COMMIT}`、原始 PGM 架构、FCFP4 1024-bit 剂量编码和严格匹配权重。输入固定为官方 demo，完整 978 基因顺序不改动。沿官方 `test_demo.py` 先 `normalize_total()`，再 `log1p()`；归一化目标和为 {target_sum:.9g}。它由全部 681 条 demo 表达谱的行和中位数得到，包括实测处理谱，因此是有明确局限的参照路径。

实际 CPU 线程 {threads}，随机种子 {seed}，每条 profile 使用 {noise_draws} 个标准正态 decoder-noise 向量。主预测是这些向量下高斯条件均值的平均，同时保存一个与官方定义相同的高斯采样输出。这些数值抽样不代表生物学重复。它没有原 Trainer 的 shuffle/追加输出行为，不能称为官方脚本逐字节复现。没有重新训练或调参；该 demo 的预处理不能自动外推为任意用户数据都与权重匹配。

## 基线、对照与解释边界

- `no_change`：预测处理后表达等于该 profile 指定对照，即零响应。
- `other_group_mean`：用本 demo 中其他药物组的实测响应均值。每个待评估组的所有条件都排除；共享来源 pert_id、名称或 RDKit 规范异构 SMILES 的记录通过连通分组一起排除。这是 demo 内的描述性参照，不能称为外部可部署基线，不能据此断言模型一般优劣。
- 排除当前组后，其他组均值与当前组实测值在数学上相互依赖；其逐基因相关可出现构造导致的负相关，不能解释为真实的反向生物学作用。完整指标照实保留，并明确这个参照的用途。
- 保留 {int(treated.cross_rna_plate.sum())} 条跨 RNA plate 配对，差值可能包含批次因素。没有偷偷更换对照或做批次校正。
- checkpoint 名称为 `lincs_best_epoch_all.pt`。分发资料未提供可核实的训练成员清单与该 demo 的排除证明；论文中的交叉验证结果不能直接套用到这个权重。`demo_split=test` 只作为来源字段保存。
- [QC](qc.json) 额外固定同一对照和同一噪声，测量输入化学结构/剂量引起的变化；这是敏感性诊断，不是药效排名。没有输出临床候选或治疗建议。

## 产物与复查

- [完整 NPZ](raw/reference_predictions.npz)：来源 X、预处理 X、基线、实测、预测、采样、方差、噪声和全部行列 ID；使用 `numpy.load(..., allow_pickle=False)`。
- [条件索引](tables/condition_index.csv)、[基因轴](tables/gene_index.csv)、[逐 profile 指标](tables/profile_metrics.csv)、[逐基因指标](tables/gene_metrics.csv)。指标空值表示相关系数未定义。
- 完整压缩表：[实测响应](tables/observed_delta.csv.gz)、[预测响应](tables/predicted_delta.csv.gz)、[其他组响应均值](tables/other_group_mean_delta.csv.gz)。
- [验证边界与指标](validation.json)、[图清单](figures/figure_manifest.csv)、[来源与环境](provenance.json)、[运行状态](manifest.json)。

模型原作者与许可：[PRnet](https://github.com/Perturbation-Response-Prediction/PRnet)，[原论文](https://doi.org/10.1038/s41467-024-53457-1)。本项目提供调用与评估流程，未发明或重新训练 PRnet；公开 demo 和权重的独立许可未单独核实，代码 Apache-2.0 不自动覆盖所有数据。
"""
    (output / "report.md").write_text(report, encoding="utf-8")
    versions = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "anndata", "scanpy", "torch", "rdkit", "scipy", "h5py")}
    try:
        versions["matplotlib"] = importlib.metadata.version("matplotlib")
    except importlib.metadata.PackageNotFoundError:
        versions["matplotlib"] = None
    return {"qc": qc, "validation": validation, "figure": figure, "packages": versions}


def run_reference(resources_dir, output_dir, *, seed=2024, noise_draws=16, threads=1, invocation=None):
    if type(seed) is not int or not 0 <= seed < 2 ** 32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(noise_draws) is not int or not 1 <= noise_draws <= 64:
        raise ValueError("noise_draws must be an integer in [1, 64]")
    if type(threads) is not int or not 1 <= threads <= 4:
        raise ValueError("threads must be an integer in [1, 4]")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("raw", "tables", "figures"):
        (output / folder).mkdir()
    (output / "errors.jsonl").write_text("", encoding="utf-8")
    manifest = {"schema_version": 1, "run_id": output.name, "case_id": CASE_ID, "task": "drug", "backend": "PRnet",
                "status": "running", "model_status": "not_run", "prediction_status": "not_run", "validation_status": "unvalidated",
                "independent_validation": "not_assessed", "started_at": datetime.now(timezone.utc).isoformat(),
                "parameters": {"seed": seed, "noise_draws": noise_draws, "torch_threads": threads, "device": "cpu"},
                "baseline_source": "official_demo_paired_controls", "scale": SCALE}
    _json(output / "manifest.json", manifest)
    provenance = {"project": "Virtual Cell Research", "case_id": CASE_ID, "script_sha256": sha256_file(__file__),
                  "python": platform.python_version(), "sys_executable": sys.executable, "working_directory": str(Path.cwd()),
                  "invocation": invocation or {"kind": "python_api", "entrypoint": "run_reference", "argv": None},
                  "source_commit": COMMIT, "resources": RESOURCES, "resource_directory": str(Path(resources_dir).resolve()),
                  "model_status": "not_run", "independent_validation": "not_assessed"}
    try:
        paths = resource_paths(resources_dir)
        provenance["resources_sha256_verified"] = True
        result = _run_model(paths, output, seed, noise_draws, threads, manifest)
        manifest.update(status="completed", execution_status="success", model_status="executed", prediction_status="success",
                        conditions_completed=result["qc"]["profiles"], figure_status=result["figure"]["status"])
        provenance.update(packages=result["packages"], model_status="executed", preprocessing=result["validation"]["preprocessing_scope"])
    except Exception as exc:
        manifest.update(status="failed", execution_status="failed", error=f"{type(exc).__name__}: {exc}")
        provenance["model_status"] = manifest["model_status"]
        (output / "errors.jsonl").write_text(json.dumps({"stage": "reference_run", "error": manifest["error"]}) + "\n", encoding="utf-8")
        if not (output / "validation.json").exists():
            _json(output / "validation.json", {"status": "unvalidated", "independent_validation": "not_assessed", "reason": manifest["error"]})
        if not (output / "report.md").exists():
            (output / "report.md").write_text("# PRnet reference run failed\n\n" + manifest["error"] + "\n\nSee manifest.json, errors.jsonl and provenance.json. No independent validation was performed.\n", encoding="utf-8")
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    _json(output / "manifest.json", manifest)
    provenance["artifacts"] = {path.relative_to(output).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
                               for path in sorted(output.rglob("*")) if path.is_file() and path.name != "provenance.json"}
    _json(output / "provenance.json", provenance)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pinned PRnet CPU reference inference; training overlap unknown, no independent validation.")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="Download seven pinned resources (~5.41 MB), without executing them")
    fetch.add_argument("--output-dir", required=True, type=Path)
    fetch.add_argument("--reuse-dir", type=Path, help="Optional earlier resource directory; copy only hash-verified files into the new directory")
    run = sub.add_parser("run", help="Load official model and evaluate its official reference demo on CPU")
    run.add_argument("--resources-dir", required=True, type=Path)
    run.add_argument("--output-dir", required=True, type=Path)
    run.add_argument("--seed", type=int, default=2024)
    run.add_argument("--noise-draws", type=int, default=16)
    run.add_argument("--threads", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            result = fetch_resources(args.output_dir, args.reuse_dir)
            print(json.dumps({"status": result["status"], "resources": len(result["resources"]), "model_status": "not_run"}))
            return 0
        invocation = {"kind": "cli" if argv is None and __name__ == "__main__" else "python_main",
                      "argv_source": "sys.argv" if argv is None else "main(argv)",
                      "argv": list(sys.argv) if argv is None else list(argv)}
        result = run_reference(args.resources_dir, args.output_dir, seed=args.seed, noise_draws=args.noise_draws,
                               threads=args.threads, invocation=invocation)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "completed" else 2
    except (OSError, ValueError) as exc:
        print(f"PRnet reference error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
