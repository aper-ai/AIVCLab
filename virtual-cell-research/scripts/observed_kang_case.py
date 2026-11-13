#!/usr/bin/env python3
"""Read fixed Kang PBMC source files and describe donor-paired observations.

No learned model, training, imputation, hypothesis test, or efficacy prediction.
The CLI accepts only six checksum-pinned official GEO files. Test-only checksum
overrides require an explicitly labelled synthetic fixture through the Python API.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np
import pandas as pd
from scipy import io, sparse


CASE_ID = "kang-ifnb-pbmc"
DEFAULT_CELL_TYPE = "CD14+ Monocytes"
SCALE = "log2(1 + 1000000 * pseudobulk_gene_counts / pseudobulk_all_gene_counts)"
FILES = {
    "control_matrix": ("GSM2560248_2.1.mtx.gz", 28545918, "32add28a0b3397d9ef3f220b7a6a55e98e60fe7b66fe48d0986d634df8ca0013"),
    "stimulated_matrix": ("GSM2560249_2.2.mtx.gz", 29050932, "8aecc98a7ac4957bbc2570f87ebe8ce97332a5bcdbf557d40bd5aabfd287bdc5"),
    "genes": ("GSE96583_batch2.genes.tsv.gz", 277054, "93aa4e9b530ef9d6411ca129b416324c5cc1cc5a01a1fa6ed4f4a845480ed3ca"),
    "metadata": ("GSE96583_batch2.total.tsne.df.tsv.gz", 756342, "1d57e72e92ca8695250e88cc0f1c3fa8c0be1175d974f8b427c58f1274dc6c09"),
    "control_barcodes": ("GSM2560248_barcodes.tsv.gz", 52904, "d58d8d55cbe4a12757207784b3bc9227bf200c9100ca15131176e9f8159c955e"),
    "stimulated_barcodes": ("GSM2560249_barcodes.tsv.gz", 52366, "9bb38e080dfae81036fbcd9902c6c6254a4466aa85f70705479be3b2d6679d55"),
}
SAMPLES = (("ctrl", "GSM2560248", "control_matrix", "control_barcodes"),
           ("stim", "GSM2560249", "stimulated_matrix", "stimulated_barcodes"))
SOURCE_HEADER = ["tsne1", "tsne2", "ind", "stim", "cluster", "cell", "multiplets"]


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def source_url(key):
    name = FILES[key][0]
    if key in {"genes", "metadata"}:
        return "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/" + name
    sample = "GSM2560248" if key.startswith("control") else "GSM2560249"
    return f"https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM2560nnn/{sample}/suppl/{name}"


def require_text(series, label, *, unique=False):
    values = pd.Series(series, copy=False)
    if values.isna().any() or values.astype(str).str.strip().eq("").any():
        raise ValueError(f"{label} contains missing or blank identifiers")
    if unique and not values.is_unique:
        raise ValueError(f"{label} must be unique")


def read_labels(paths):
    # The published TSV has a seven-field header but eight-field records: the
    # first field is an unnamed row ID. Read it explicitly, not by position guess.
    with gzip.open(paths["metadata"], "rt", encoding="utf-8") as handle:
        if handle.readline().rstrip("\r\n").split("\t") != SOURCE_HEADER:
            raise ValueError("Unexpected published metadata header")
    metadata = pd.read_csv(paths["metadata"], sep="\t", skiprows=1,
                           names=["metadata_id", *SOURCE_HEADER], dtype=str,
                           keep_default_na=False).set_index("metadata_id")
    require_text(metadata.index, "metadata IDs", unique=True)
    for column in ("ind", "stim", "cell", "multiplets"):
        require_text(metadata[column], "metadata." + column)
    if set(metadata.stim) != {"ctrl", "stim"}:
        raise ValueError("Metadata must contain exactly ctrl and stim")
    if not set(metadata.multiplets).issubset({"singlet", "doublet", "ambs"}):
        raise ValueError("Unrecognized multiplet status; no silent filtering")
    genes = pd.read_csv(paths["genes"], sep="\t", header=None, dtype=str,
                        keep_default_na=False)
    if genes.shape[1] != 2:
        raise ValueError("Gene table must have exactly gene ID and symbol columns")
    genes.columns = ["gene_id", "gene_symbol"]
    require_text(genes.gene_id, "gene IDs", unique=True)
    require_text(genes.gene_symbol, "gene symbols")
    barcodes = {}
    for _, _, _, key in SAMPLES:
        table = pd.read_csv(paths[key], sep="\t", header=None, dtype=str, keep_default_na=False)
        if table.shape[1] != 1:
            raise ValueError("Barcode file must have one column")
        values = table[0]
        require_text(values, key, unique=True)
        if not values.str.fullmatch(r"[ACGT]+-1").all():
            raise ValueError("Unexpected official barcode syntax")
        barcodes[key] = values.tolist()
    return genes, metadata, barcodes


def align_metadata(metadata, barcodes):
    """Reconstruct the verified source-specific collision rule, with a full audit."""
    controls = set(barcodes["control_barcodes"])
    rows, used = [], set()
    for condition, sample, _, barcode_key in SAMPLES:
        names = barcodes[barcode_key]
        # In this fixed published merge, a cross-sample duplicate barcode keeps
        # its ctrl ID; the stim metadata ID has one literal '1' appended (-11).
        expected = [name + "1" if condition == "stim" and name in controls else name for name in names]
        if len(set(expected)) != len(expected) or not set(expected).issubset(metadata.index):
            raise ValueError("Published barcode collision mapping is incomplete or ambiguous")
        selected = metadata.loc[expected].copy()
        if not selected.stim.eq(condition).all() or used.intersection(expected):
            raise ValueError("Barcode mapping crosses conditions or reuses metadata rows")
        used.update(expected)
        selected.insert(0, "source_cell_id", [sample + ":" + name for name in names])
        selected.insert(1, "sample_accession", sample)
        selected.insert(2, "source_barcode", names)
        selected.insert(3, "matrix_column", np.arange(len(names)))
        selected["metadata_id_was_disambiguated"] = np.asarray(expected) != np.asarray(names)
        selected["cell_annotation_status"] = np.where(selected.cell.eq("NA"), "unassigned_source_label", "source_label_present")
        selected["included_singlet"] = selected.multiplets.eq("singlet")
        selected["filter_reason"] = np.where(selected.included_singlet, "included", selected.multiplets)
        rows.append(selected.reset_index())
    if used != set(metadata.index):
        raise ValueError("Some source metadata rows have no matrix barcode")
    aligned = pd.concat(rows, ignore_index=True)
    require_text(aligned.source_cell_id, "sample-prefixed cell IDs", unique=True)
    return aligned


def read_count_matrix(path, expected_shape):
    with gzip.open(path, "rt", encoding="ascii") as handle:
        if handle.readline().strip() not in {"%%MatrixMarket matrix coordinate real general", "%%MatrixMarket matrix coordinate integer general"}:
            raise ValueError("Unsupported Matrix Market header")
        line = handle.readline()
        while line.startswith("%"):
            line = handle.readline()
        dimensions = tuple(map(int, line.split()))
        if len(dimensions) != 3 or dimensions[:2] != expected_shape or not 0 <= dimensions[2] <= 20_000_000:
            raise ValueError("Matrix header does not match genes/barcodes or exceeds case bounds")
    try:
        from threadpoolctl import threadpool_limits
        limit = threadpool_limits(limits=2)
    except ImportError:
        limit = nullcontext()
    with limit, gzip.open(path, "rb") as handle:
        matrix = io.mmread(handle, spmatrix=True)
    if not sparse.issparse(matrix) or matrix.shape != expected_shape:
        raise ValueError("Matrix must be sparse genes by cells")
    values = matrix.data
    if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any():
        raise ValueError("Raw UMI counts must be finite nonnegative integers")
    if values.size and values.max() > 1_000_000:
        raise ValueError("Unexpectedly large single entry for the fixed UMI-count case")
    count = matrix.nnz
    matrix = matrix.astype(np.int64).tocsc()
    if matrix.nnz != count:
        raise ValueError("Duplicate coordinate entries are not accepted")
    return matrix


def stable_group_id(donor, condition, cell_type):
    identity = json.dumps([str(donor), str(condition), str(cell_type)], ensure_ascii=False, separators=(",", ":"))
    return "pb_" + hashlib.sha256(identity.encode()).hexdigest()[:16]


def aggregate_counts(paths, genes, aligned):
    """Aggregate sparse source counts; never densify a cell-by-gene matrix."""
    included = aligned.loc[aligned.included_singlet]
    keys = sorted(set(zip(included.ind, included.stim, included.cell)))
    if not keys:
        raise ValueError("No source singlets remain")
    groups = pd.DataFrame(keys, columns=["donor", "condition", "cell_type"])
    groups.insert(0, "group_id", [stable_group_id(*key) for key in keys])
    if not groups.group_id.is_unique:
        raise ValueError("Group identity hash collision")
    lookup = {key: i for i, key in enumerate(keys)}
    aggregate = sparse.csr_matrix((len(keys), len(genes)), dtype=np.int64)
    n_cells = np.zeros(len(keys), dtype=np.int64)
    aligned = aligned.copy()
    aligned["source_library_umi"] = 0
    aligned["group_id"] = ""
    audits = []
    for condition, sample, matrix_key, _ in SAMPLES:
        sample_rows = aligned.loc[aligned.sample_accession.eq(sample)]
        matrix = read_count_matrix(paths[matrix_key], (len(genes), len(sample_rows)))
        libraries = np.asarray(matrix.sum(axis=0)).ravel().astype(np.int64)
        aligned.loc[sample_rows.index, "source_library_umi"] = libraries
        keep = sample_rows.included_singlet.to_numpy()
        cells = np.flatnonzero(keep)
        retained = sample_rows.iloc[cells]
        positions = np.asarray([lookup[(r.ind, condition, r.cell)] for r in retained.itertuples()], dtype=np.int64)
        assignment = sparse.csr_matrix((np.ones(len(cells), dtype=np.int64), (positions, cells)), shape=(len(groups), matrix.shape[1]))
        partial = (assignment @ matrix.T).tocsr()
        retained_umi = int(libraries[cells].sum())
        if int(partial.sum()) != retained_umi:
            raise ValueError("Pseudobulk aggregation failed exact UMI conservation")
        aggregate = aggregate + partial
        n_cells += np.bincount(positions, minlength=len(groups))
        aligned.loc[retained.index, "group_id"] = groups.iloc[positions].group_id.to_numpy()
        audits.append({"sample": sample, "condition": condition, "shape_genes_by_cells": list(matrix.shape),
                       "stored_entries": int(matrix.nnz), "source_total_umi": int(libraries.sum()),
                       "included_singlets": len(cells), "excluded_cells": int((~keep).sum()),
                       "included_singlet_umi": retained_umi, "aggregated_umi": int(partial.sum()),
                       "zero_library_cells": int((libraries == 0).sum()), "raw_count_values_checked": True})
    groups["n_cells"] = n_cells
    groups["library_umi"] = np.asarray(aggregate.sum(axis=1)).ravel().astype(np.int64)
    if int(n_cells.sum()) != len(included):
        raise ValueError("Group cell totals do not match included source cells")
    return aggregate, groups, aligned, audits


def paired_responses(counts, groups, cell_type, min_cells):
    if not isinstance(cell_type, str) or not cell_type.strip():
        raise ValueError("cell_type must be explicit text")
    if cell_type == "NA":
        raise ValueError("NA is an unassigned source label, not an annotated cell type")
    if type(min_cells) is not int or min_cells < 1:
        raise ValueError("min_cells must be a positive integer")
    selected = groups.loc[groups.cell_type.eq(cell_type)]
    if selected.empty:
        raise ValueError(f"No singlets have cell type {cell_type!r}")
    pairs, differences = [], []
    for donor in sorted(groups.donor.unique()):
        entries = selected.loc[selected.donor.eq(donor)]
        if entries.condition.duplicated().any():
            raise ValueError("Duplicate donor/condition groups")
        record = {"donor": donor, "cell_type": cell_type, "status": "included", "reason": ""}
        positions = {}
        for condition in ("ctrl", "stim"):
            row = entries.loc[entries.condition.eq(condition)]
            record[condition + "_group_id"] = None if row.empty else row.iloc[0].group_id
            record[condition + "_n_cells"] = 0 if row.empty else int(row.iloc[0].n_cells)
            record[condition + "_library_umi"] = 0 if row.empty else int(row.iloc[0].library_umi)
            if not row.empty:
                positions[condition] = row.index[0]
        if len(positions) != 2:
            record.update(status="excluded", reason="missing_condition")
        elif min(record["ctrl_n_cells"], record["stim_n_cells"]) < min_cells:
            record.update(status="excluded", reason="fewer_than_min_cells_in_at_least_one_condition")
        elif min(record["ctrl_library_umi"], record["stim_library_umi"]) <= 0:
            record.update(status="excluded", reason="zero_pseudobulk_library")
        else:
            values = counts[[positions["ctrl"], positions["stim"]]].toarray().astype(np.float64)
            logcpm = np.log2(1.0 + 1_000_000.0 * values / values.sum(axis=1, keepdims=True))
            differences.append(logcpm[1] - logcpm[0])
        pairs.append(record)
    pair_table = pd.DataFrame(pairs)
    if not differences:
        return pair_table, np.empty((0, counts.shape[1]), dtype=np.float64)
    return pair_table, np.stack(differences)


def render_figure(data, output):
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    donors = list(dict.fromkeys(data.donor))
    genes = list(dict.fromkeys(data.gene_id))
    values = data.pivot(index="donor", columns="gene_id", values="paired_logcpm_difference").loc[donors, genes].to_numpy()
    labels = [data.loc[data.gene_id.eq(g), "gene_symbol"].iloc[0] for g in genes]
    limit = float(np.abs(values).max()) or 1.0
    with plt.rc_context({"svg.fonttype": "none", "font.size": 9}):
        figure, axis = plt.subplots(figsize=(10, max(4, len(donors) * 0.4 + 2)))
        try:
            mesh = axis.pcolormesh(values, cmap="coolwarm", vmin=-limit, vmax=limit, edgecolors="white", linewidth=.5)
            axis.set_xticks(np.arange(len(genes)) + .5, labels, rotation=45, ha="right")
            axis.set_yticks(np.arange(len(donors)) + .5, donors)
            axis.invert_yaxis()
            axis.set_ylabel("Donor (paired biological unit)")
            axis.set_title("Virtual Cell Research | observed IFN-beta response\n" + str(data.cell_type.iloc[0]) + "; descriptive donor-paired differences", loc="left", pad=12)
            bar = figure.colorbar(mesh, ax=axis, pad=.02)
            bar.set_label("stim minus ctrl: log2(1 + CPM)\nAll source genes used in library denominator")
            if bar.solids is not None:
                bar.solids.set_rasterized(False)
            figure.tight_layout()
            for suffix in ("png", "svg"):
                figure.savefig(output / f"donor_response.{suffix}", dpi=160, facecolor="white")
        finally:
            plt.close(figure)


def _analyse(input_dir, output, cell_type, min_cells, expected_checksums, synthetic_fixture, invocation):
    if not isinstance(cell_type, str) or not cell_type.strip() or cell_type == "NA":
        raise ValueError("Choose an explicit annotated source cell type; NA is unassigned")
    if type(min_cells) is not int or min_cells < 1:
        raise ValueError("min_cells must be a positive integer")
    expected = {key: item[2] for key, item in FILES.items()}
    if expected_checksums is not None:
        if not synthetic_fixture:
            raise ValueError("Checksum overrides require synthetic_fixture=True through the Python API")
        if set(expected_checksums) != set(expected):
            raise ValueError("Synthetic fixture must provide all six checksums")
        expected = dict(expected_checksums)
    elif synthetic_fixture:
        raise ValueError("Synthetic fixture requires its own six explicit checksums")
    paths, source_records = {}, {}
    for key, (name, official_size, _) in FILES.items():
        path = Path(input_dir) / key / name
        size = path.stat().st_size
        if not 0 < size <= 64 * 1024 * 1024 or (not synthetic_fixture and size != official_size):
            raise ValueError(f"Unexpected size for {key}")
        actual = sha256_file(path)
        if actual != expected[key]:
            raise ValueError(f"SHA256 mismatch for {key}")
        paths[key] = path
        source_records[key] = {"file_name": name, "bytes": size, "sha256": actual,
                               "path": str(path.resolve()), "url": None if synthetic_fixture else source_url(key)}
    genes, metadata, barcodes = read_labels(paths)
    aligned = align_metadata(metadata, barcodes)
    counts, groups, cells, audit = aggregate_counts(paths, genes, aligned)
    pairs, differences = paired_responses(counts, groups, cell_type, min_cells)
    for folder in ("raw", "tables", "figures"):
        (output / folder).mkdir()
    compression = {"method": "gzip", "mtime": 0}
    sparse.save_npz(output / "raw/pseudobulk_counts.npz", counts, compressed=True)
    genes.to_csv(output / "tables/genes.csv", index=False)
    groups.to_csv(output / "tables/pseudobulk_index.csv", index=False)
    cells.to_csv(output / "tables/cell_index.csv.gz", index=False, compression=compression)
    pairs.to_csv(output / "tables/donor_pairs.csv", index=False)
    donors = pairs.loc[pairs.status.eq("included"), "donor"].to_numpy(dtype=str)
    np.savez_compressed(output / "raw/paired_responses.npz", observed_delta=differences,
                        donor_ids=donors, gene_ids=genes.gene_id.to_numpy(dtype=str))
    pd.DataFrame(differences, index=donors, columns=genes.gene_id).to_csv(
        output / "tables/paired_responses.csv.gz", index_label="donor", float_format="%.17g", compression=compression)
    summary = genes.copy()
    summary["n_paired_donors"] = len(donors)
    if len(donors):
        summary["mean_paired_difference"] = differences.mean(axis=0)
        summary["median_paired_difference"] = np.median(differences, axis=0)
        summary["sample_sd_across_donors"] = differences.std(axis=0, ddof=1) if len(donors) > 1 else np.nan
        summary["positive_donors"] = (differences > 0).sum(axis=0)
        summary["negative_donors"] = (differences < 0).sum(axis=0)
    summary.to_csv(output / "tables/gene_summary.csv", index=False)
    figure = {"status": "skipped", "reason": "no_complete_eligible_donor_pairs", "data": None, "paths": [],
              "selection": "top_12_genes_by_absolute_equal_donor_mean_difference; gene_ID_breaks_ties",
              "interpretation": "descriptive_selection_not_significance_or_prediction"}
    if len(donors):
        positions = np.lexsort((genes.gene_id.to_numpy(), -np.abs(differences.mean(axis=0))))[:min(12, len(genes))]
        figure_data = pd.DataFrame([{"donor": donor, "cell_type": cell_type, "gene_id": genes.iloc[j].gene_id,
                                    "gene_symbol": genes.iloc[j].gene_symbol,
                                    "paired_logcpm_difference": differences[i, j]}
                                   for i, donor in enumerate(donors) for j in positions])
        figure_data.to_csv(output / "tables/figure_data.csv", index=False)
        figure["data"] = "tables/figure_data.csv"
        try:
            render_figure(figure_data, output / "figures")
            figure.update(status="generated", reason=None, paths=["figures/donor_response.png", "figures/donor_response.svg"])
        except Exception as exc:
            figure.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
    write_json(output / "figure_manifest.json", figure)
    qc = {"status": "completed" if len(donors) else "completed_without_paired_response",
          "source_cells": len(cells), "source_genes": len(genes), "source_donors": sorted(groups.donor.unique()),
          "included_singlets": int(cells.included_singlet.sum()),
          "excluded_by_status": cells.loc[~cells.included_singlet, "multiplets"].value_counts().to_dict(),
          "metadata_id_disambiguations": int(cells.metadata_id_was_disambiguated.sum()),
          "source_unassigned_cell_labels": int(cells.cell.eq("NA").sum()),
          "included_singlets_with_unassigned_cell_label": int((cells.cell.eq("NA") & cells.included_singlet).sum()),
          "duplicated_gene_symbols": int(genes.gene_symbol.duplicated().sum()),
          "group_count": len(groups), "selected_cell_type": cell_type, "minimum_cells_per_donor_condition": min_cells,
          "paired_donors": len(donors), "pair_exclusions": pairs.loc[pairs.status.ne("included")].to_dict("records"),
          "selected_ctrl_cells": int(pairs.loc[pairs.status.eq("included"), "ctrl_n_cells"].sum()),
          "selected_stim_cells": int(pairs.loc[pairs.status.eq("included"), "stim_n_cells"].sum()),
          "matrix_audit": audit, "all_included_umi_conserved": True,
          "scale": SCALE, "response_operation": "stim_minus_ctrl_within_same_donor_and_cell_type",
          "replicate_unit": "donor", "donor_weighting": "equal", "model_status": "not_run",
          "independent_validation": "not_assessed", "statistics": "descriptive_only_no_pvalues",
          "biological_qc": "source_annotations_and_singlet_filter_only; no_new_mitochondrial_or_doublet_QC",
          "batch_limitation": "two_condition_specific_source_libraries; shared_library_effects_are_not_removed"}
    write_json(output / "qc.json", qc)
    preview = "![实际供体配对观测差值](figures/donor_response.png)" if figure["status"] == "generated" else "本次未生成预览图；原因见[图清单](figure_manifest.json)，数值与来源记录仍保留。"
    report = f"""# Kang PBMC：供体配对观测教学

案例 `{CASE_ID}`；数据身份 `{('synthetic_test_fixture' if synthetic_fixture else 'official_GEO_GSE96583_batch2')}`。

## 实际完成内容

读取 {len(cells)} 个来源细胞、{len(genes)} 个基因。按来源 `multiplets=singlet` 保留 {qc['included_singlets']} 个细胞，聚合成 {len(groups)} 个供体 × 条件 × 细胞类型 pseudobulk。选定 **{cell_type}**，在每个条件至少 {min_cells} 个细胞且文库总量大于零时纳入供体，实际得到 **{len(donors)} 个完整配对供体**。该阈值是显式教学设置，不证明样本质量或统计功效。

每个 pseudobulk 先对全部 {len(genes)} 个来源基因的原始 UMI 求和，再计算 `log2(1 + CPM)`；每位供体的差值为 stim 减 ctrl。`+1` 是 CPM 尺度伪计数。它不是原始 counts 的差、真实 fold change 或模型预测。摘要对供体等权平均，细胞不被当作独立生物学重复。

## 结果与复查入口

- [逐细胞来源、barcode 映射与筛选](tables/cell_index.csv.gz)；[基因 ID 与符号](tables/genes.csv)。
- [pseudobulk 行索引与文库总量](tables/pseudobulk_index.csv)；[全部细胞类型的整数聚合矩阵](raw/pseudobulk_counts.npz)，使用 `scipy.sparse.load_npz` 读取。
- [供体配对、细胞数、文库大小与排除原因](tables/donor_pairs.csv)。
- [全基因配对差值 CSV](tables/paired_responses.csv.gz)／[NPZ 与轴 ID](raw/paired_responses.npz)；[供体等权描述性摘要](tables/gene_summary.csv)。
- [QC](qc.json)、[图清单](figure_manifest.json)、[输入输出哈希、运行参数与环境](provenance.json)。

{preview}

图按绝对供体均值差选择最多 12 个基因，保留每位供体的符号与数值；这是描述性选择，没有 P 值、显著性或模型性能含义。图成功时对应源表为 `tables/figure_data.csv`。

## 对齐和解释限制

- 两个样本的原始 barcode 都以 `-1` 结尾。来源合并元数据给 stim 中跨样本同名的 {qc['metadata_id_disambiguations']} 项追加了一个 `1`（成为 `-11`）。脚本只对本次固定来源应用这个经核对的规则，并逐条验证条件和全量覆盖；稳定 ID 使用 sample accession 加原 barcode，原始 metadata ID 单独保留。
- 基因按唯一 Ensembl ID 保留；{qc['duplicated_gene_symbols']} 条重复符号不合并，不因符号相同丢弃或重复计数。
- 来源 cell 字段中的字面量 `NA` 表示未注释：共 {qc['source_unassigned_cell_labels']} 个细胞，其中 {qc['included_singlets_with_unassigned_cell_label']} 个 singlet。它们的原始标签和聚合计数另保留，不能把这个标签当真实细胞类型选择；本次所选 {cell_type} 不包含这些细胞。
- 本案例使用来源细胞类型和 singlet 注释，没有重新做细胞注释、线粒体比例过滤或 doublet 判定。供体、低细胞数和缺失配对均可在源表检查。
- 两个条件来自条件特异的来源文库；供体配对不消除共享的文库/批次影响。描述性差值不能单独建立刺激的纯因果效应，也不是健康人群的一般结论。
- `model_status: not_run`；`independent_validation: not_assessed`。未训练或运行虚拟细胞模型，没有将该数据相对任何已有模型的训练重叠核实为独立验证。
- GEO 文件未单独核实数据许可，不能自动套用本项目代码许可或其他衍生存档许可。

来源：[GSE96583](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583)；[原始研究](https://doi.org/10.1038/nbt.4042)。
"""
    if synthetic_fixture:
        report = "# SYNTHETIC TEST FIXTURE — not experimental evidence\n\n" + report
    (output / "report.md").write_text(report, encoding="utf-8")
    packages = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "scipy")}
    try:
        packages["matplotlib"] = importlib.metadata.version("matplotlib")
    except importlib.metadata.PackageNotFoundError:
        packages["matplotlib"] = None
    provenance = {"schema_version": 1, "project": "Virtual Cell Research", "case_id": CASE_ID,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "source_kind": "synthetic_test_fixture" if synthetic_fixture else "official_GEO_GSE96583_batch2",
                  "sources": source_records, "script_sha256": sha256_file(__file__),
                  "parameters": {"cell_type": cell_type, "min_cells": min_cells, "normalization": SCALE},
                  "sys_executable": sys.executable, "python": platform.python_version(), "packages": packages,
                  "invocation": invocation or {"kind": "python_api", "argv": None},
                  "model_status": "not_run", "independent_validation": "not_assessed",
                  "artifacts": {str(p.relative_to(output)): {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
                                for p in sorted(output.rglob("*")) if p.is_file()}}
    write_json(output / "provenance.json", provenance)
    return {"output_dir": str(output.resolve()), "qc": qc, "figure": figure, "provenance": provenance}


def run_case(input_dir, output_dir, *, cell_type=DEFAULT_CELL_TYPE, min_cells=20,
             expected_checksums=None, synthetic_fixture=False, invocation=None):
    output = Path(output_dir)
    if os.path.lexists(output):
        raise FileExistsError(f"Output exists; choose a new directory: {output}")
    output.mkdir(parents=True, exist_ok=False)
    try:
        return _analyse(input_dir, output, cell_type, min_cells, expected_checksums, synthetic_fixture, invocation)
    except Exception as exc:
        write_json(output / "error.json", {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                                          "model_status": "not_run", "independent_validation": "not_assessed"})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compute donor-paired observed responses from six fixed Kang GEO files; no model inference.")
    parser.add_argument("--input-dir", type=Path, required=True, help="Parent containing the six cases.py fetch asset directories")
    parser.add_argument("--output-dir", type=Path, required=True, help="A new output directory")
    parser.add_argument("--cell-type", default=DEFAULT_CELL_TYPE, help="Exact source cell label; default CD14+ Monocytes")
    parser.add_argument("--min-cells", type=int, default=20, help="Minimum source singlets per donor and condition; default 20")
    arguments = None if argv is None else list(argv)
    args = parser.parse_args(arguments)
    invocation = {"kind": "cli" if arguments is None and __name__ == "__main__" else "python_main",
                  "argv_source": "sys.argv" if arguments is None else "main(argv)",
                  "argv": list(sys.argv) if arguments is None else arguments, "cwd": str(Path.cwd())}
    try:
        result = run_case(args.input_dir, args.output_dir, cell_type=args.cell_type, min_cells=args.min_cells, invocation=invocation)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Kang observed-case error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output_dir": result["output_dir"], "source_cells": result["qc"]["source_cells"],
                      "included_singlets": result["qc"]["included_singlets"], "paired_donors": result["qc"]["paired_donors"],
                      "model_status": "not_run", "independent_validation": "not_assessed",
                      "figure_status": result["figure"]["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
