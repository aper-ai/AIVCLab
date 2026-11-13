#!/usr/bin/env python3
"""Describe paired drug responses in the original GSE52778 processed FPKM table.

The source has bulk RNA-seq profiles, not single cells or raw UMI counts.
FPKM columns are joined to donor and treatment through original SRA FASTQ
filenames and GEO accessions, never through the order of source columns.
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
import re
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd


CASE_ID = "airway-gse52778-drug-response"
SERIES_URL = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE52778"
PAPER_URL = "https://doi.org/10.1371/journal.pone.0099625"
SRA_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id=" + ",".join(str(i) for i in range(551401, 551385, -1)) + "&rettype=full&retmode=xml"
SOURCES = {
    "fpkm": {"file_name": "GSE52778_All_Sample_FPKM_Matrix.txt.gz", "bytes": 2596435,
             "sha256": "e7e54e8f564d417b47843e82c2a7140b92a783d6b5078816bae15d07fca126f6",
             "url": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE52nnn/GSE52778/suppl/GSE52778_All_Sample_FPKM_Matrix.txt.gz"},
    "metadata": {"file_name": "GSE52778_series_matrix.txt.gz", "bytes": 3396,
                 "sha256": "67db46e962f795b9dd61fa6b4279f2678c6b2b9bf1df035fbc22fcf81b5e879e",
                 "url": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE52nnn/GSE52778/matrix/GSE52778_series_matrix.txt.gz"},
    # SRA eutils serializes SRAFile siblings in changing order. Pin the complete
    # scientific identity projection below, while recording each raw response
    # hash. A raw-byte hash would incorrectly reject an equivalent live response.
    "sra_mapping": {"file_name": "SRP033351_full.xml", "bytes": None,
                    "sha256": None, "url": SRA_URL,
                    "canonical_identity_sha256": "2992f218505bc0d7a20cfa3579685848cd8ade5aea34900e0a52c4e20e58a927"},
}
SRA_IDENTITY_FIELDS = ("experiment", "geo_accession", "library_id", "original_fastq_names",
                       "run_accession", "sra_donor", "sra_title", "sra_treatment")
CONDITIONS = {"Untreated": "Untreated", "Dexamethasone": "Dex", "Albuterol": "Alb", "Albuterol_Dexamethasone": "Alb_Dex"}
TREATMENTS = ["Dex", "Alb", "Alb_Dex"]
LABELS = {"Dex": "Dexamethasone", "Alb": "Albuterol", "Alb_Dex": "Combination"}
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


def resolve_sources(input_dir):
    paths, records = {}, {}
    for key, expected in SOURCES.items():
        candidates = [input_dir / expected["file_name"], input_dir / key / expected["file_name"]]
        found = [path for path in candidates if path.is_file()]
        if len(found) != 1:
            raise ValueError("Exactly one fixed source file is required: " + expected["file_name"])
        path = found[0]
        actual = record(path)
        if ((expected["bytes"] is not None and actual["bytes"] != expected["bytes"])
                or (expected["sha256"] is not None and actual["sha256"] != expected["sha256"])):
            raise ValueError("Fixed official input hash/size mismatch: " + key)
        if key == "sra_mapping" and not 0 < actual["bytes"] <= 2 * 1024 * 1024:
            raise ValueError("SRA metadata response exceeds the bounded snapshot size")
        paths[key] = path
        records[key] = {**expected, **actual, "local_path": str(path), "license_status": "not_separately_specified",
                        "sha256_provenance": "project_computed_full_download_2026-11-13_not_publisher_signed",
                        "hash_policy": "pinned_canonical_identity_and_recorded_raw_hash" if key == "sra_mapping" else "pinned_raw_file_hash"}
    return paths, records


def read_geo_metadata(path):
    fields, characteristics, relations = {}, [], []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if not row:
                continue
            if row[0] == "!Sample_characteristics_ch1":
                characteristics.append(row[1:])
            elif row[0] == "!Sample_relation":
                relations.append(row[1:])
            elif row[0].startswith("!Sample_"):
                fields.setdefault(row[0], row[1:])
    accessions = fields["!Sample_geo_accession"]
    if len(accessions) != 16 or len(set(accessions)) != 16:
        raise ValueError("Expected sixteen unique GEO samples")
    if any(len(values) != 16 for values in [*characteristics, *relations, fields["!Sample_title"]]):
        raise ValueError("Metadata vectors disagree with accession axis")
    rows = []
    for i, accession in enumerate(accessions):
        attributes = {}
        for values in characteristics:
            key, sep, value = values[i].partition(": ")
            if not sep or key in attributes:
                raise ValueError("Ambiguous GEO sample characteristic")
            attributes[key] = value
        condition = attributes.get("treatment")
        if condition not in CONDITIONS or attributes.get("cell type") != "airway smooth muscle cells":
            raise ValueError("Unexpected treatment or cell type")
        experiments = [re.search(r"SRX\d+", values[i]).group() for values in relations if values[i].startswith("SRA:") and re.search(r"SRX\d+", values[i])]
        if len(experiments) != 1:
            raise ValueError("Every sample needs one explicit SRA experiment")
        rows.append({"geo_accession": accession, "geo_title": fields["!Sample_title"][i],
                     "donor": attributes["cell line"], "treatment": CONDITIONS[condition],
                     "source_treatment": condition, "cell_type": attributes["cell type"],
                     "ercc_mix": attributes.get("ercc_mix", ""), "experiment": experiments[0]})
    frame = pd.DataFrame(rows)
    if frame.duplicated(["donor", "treatment"]).any() or frame.donor.nunique() != 4:
        raise ValueError("Need four donors with unique donor-condition combinations")
    if not frame.groupby("donor").treatment.apply(lambda s: set(s) == set(CONDITIONS.values())).all():
        raise ValueError("Each donor must have all four source conditions")
    return frame


def read_sra_mapping(path):
    root = ET.parse(path).getroot()
    if root.tag != "EXPERIMENT_PACKAGE_SET":
        raise ValueError("Unexpected SRA XML root")
    rows = []
    for package in root.findall("EXPERIMENT_PACKAGE"):
        experiment, sample = package.find("EXPERIMENT"), package.find("SAMPLE")
        study = experiment.find("STUDY_REF")
        if study.get("accession") != "SRP033351" or study.get("refname") != "GSE52778":
            raise ValueError("SRA package is outside the declared study")
        geo_id = experiment.get("alias")
        if sample.get("alias") != geo_id or sample.findtext("IDENTIFIERS/EXTERNAL_ID[@namespace='GEO']") != geo_id:
            raise ValueError("SRA experiment and sample GEO identities disagree")
        attrs = {item.findtext("TAG"): item.findtext("VALUE") for item in sample.findall("SAMPLE_ATTRIBUTES/SAMPLE_ATTRIBUTE")}
        if attrs.get("treatment") not in CONDITIONS:
            raise ValueError("Unrecognized SRA treatment")
        runs = package.findall("RUN_SET/RUN")
        if len(runs) != 1:
            raise ValueError("Expected one run per source sample")
        original = [node.get("filename") for node in runs[0].findall("SRAFiles/SRAFile") if node.get("supertype") == "Original"]
        matches = [re.fullmatch(r"(LL\d{2})_R([12])\.fastq", name) for name in original]
        if len(matches) != 2 or any(match is None for match in matches):
            raise ValueError("Need the explicit paired original FASTQ names")
        libraries = {match.group(1) for match in matches}
        if len(libraries) != 1 or {match.group(2) for match in matches} != {"1", "2"}:
            raise ValueError("Original FASTQ records disagree on library identity")
        rows.append({"geo_accession": geo_id, "experiment": experiment.get("accession"),
                     "run_accession": runs[0].get("accession"), "library_id": next(iter(libraries)),
                     "sra_donor": attrs["cell line"], "sra_treatment": CONDITIONS[attrs["treatment"]],
                     "sra_title": sample.findtext("TITLE"), "original_fastq_names": ";".join(sorted(original))})
    frame = pd.DataFrame(rows)
    if len(frame) != 16 or any(not frame[key].is_unique for key in ("geo_accession", "experiment", "run_accession", "library_id")):
        raise ValueError("SRA mappings must be sixteen one-to-one identities")
    if set(frame.library_id) != {f"LL{i:02d}" for i in range(1, 17)}:
        raise ValueError("Unexpected source library identities")
    return frame


def canonical_sra_identity(mapping):
    """Hash all pairing-relevant identities, independent of XML sibling order."""
    selected = mapping.loc[:, list(SRA_IDENTITY_FIELDS)].sort_values("geo_accession")
    if len(selected) != 16 or not selected.geo_accession.is_unique:
        raise ValueError("Canonical SRA identity needs sixteen distinct samples")
    if not all(isinstance(value, str) and value.strip() for value in selected.to_numpy().ravel()):
        raise ValueError("Canonical SRA identity fields must be nonempty strings")
    payload = json.dumps(selected.to_dict("records"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_sra_identity(mapping):
    fingerprint = canonical_sra_identity(mapping)
    if fingerprint != SOURCES["sra_mapping"]["canonical_identity_sha256"]:
        raise ValueError("SRA sample mapping differs from the pinned canonical identity")
    return fingerprint


def align_columns(geo, sra, sample_columns):
    if len(sample_columns) != 16 or len(set(sample_columns)) != 16:
        raise ValueError("Expected sixteen unique expression columns")
    if set(geo.geo_accession) != set(sra.geo_accession):
        raise ValueError("GEO/SRA sample sets differ")
    merged = geo.merge(sra, on=["geo_accession", "experiment"], how="outer", validate="one_to_one", indicator=True)
    if not merged._merge.eq("both").all():
        raise ValueError("GEO/SRA experiment accession mismatch")
    if not merged.donor.eq(merged.sra_donor).all() or not merged.treatment.eq(merged.sra_treatment).all() or not merged.geo_title.eq(merged.sra_title).all():
        raise ValueError("GEO/SRA donor, treatment or title disagrees")
    merged["expression_column"] = merged.treatment + "_" + merged.library_id
    if set(merged.expression_column) != set(sample_columns):
        raise ValueError("Expression column treatment/library identities do not match original source labels")
    merged["source_column_index"] = merged.expression_column.map({name: i for i, name in enumerate(sample_columns)})
    return merged.drop(columns="_merge").sort_values("library_id").reset_index(drop=True)


def paired_responses(fpkm, mapping):
    """Return treatments x donors x genes, pairing through verified identities."""
    donors = sorted(mapping.donor.unique())
    contrasts, pair_rows = [], []
    for treatment in TREATMENTS:
        donor_rows = []
        for donor in donors:
            records = mapping.loc[mapping.donor.eq(donor)].set_index("treatment")
            if len(records) != 4 or not records.index.is_unique or not {"Untreated", treatment}.issubset(records.index):
                raise ValueError("Incomplete or ambiguous donor-condition pairing")
            ctrl, treated = records.loc["Untreated"], records.loc[treatment]
            a = fpkm[ctrl.expression_column].to_numpy(dtype=float)
            b = fpkm[treated.expression_column].to_numpy(dtype=float)
            donor_rows.append(np.log2(1 + b) - np.log2(1 + a))
            pair_rows.append({"donor": donor, "treatment": treatment,
                "control_geo_accession": ctrl.geo_accession, "treated_geo_accession": treated.geo_accession,
                "control_column": ctrl.expression_column, "treated_column": treated.expression_column})
        contrasts.append(donor_rows)
    return np.asarray(contrasts), donors, pd.DataFrame(pair_rows)


def draw_figure(figure_data, selected, donors, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    cmap = LinearSegmentedColormap.from_list("paired_drug_response", [BLUE, "#FFFFFF", ORANGE])
    bound = float(np.ceil(figure_data.observed_response.abs().max()))
    style = {"font.family": "DejaVu Sans", "font.size": 10.5, "text.color": NAVY,
             "axes.labelcolor": NAVY, "xtick.color": NAVY, "ytick.color": NAVY,
             "svg.fonttype": "none", "figure.facecolor": "white", "savefig.facecolor": "white"}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 3, figsize=(14.2, 6.5), sharey=True,
                                 gridspec_kw={"left": .115, "right": .97, "top": .73, "bottom": .29, "wspace": .12})
        for i, (ax, treatment) in enumerate(zip(axes, TREATMENTS)):
            matrix = figure_data.loc[figure_data.treatment.eq(treatment)].pivot(index="gene_id", columns="donor", values="observed_response").loc[selected.gene_id, donors].to_numpy()
            image = ax.imshow(matrix, aspect="auto", cmap=cmap, norm=TwoSlopeNorm(vmin=-bound, vcenter=0, vmax=bound))
            ax.set_yticks(np.arange(len(selected)), selected.gene_symbol)
            ax.set_xticks(np.arange(len(donors)), donors, rotation=35, ha="right")
            ax.tick_params(length=0, pad=6)
            ax.set_title(f"{chr(65 + i)}  {LABELS[treatment]}", loc="left", fontsize=13, weight="bold", pad=14)
            ax.axhline(3.5, color=NAVY, lw=.8)
            ax.set_xlabel("Paired donor-derived cell line", fontsize=9.5, labelpad=10)
            for y in range(matrix.shape[0]):
                for x in range(matrix.shape[1]):
                    ax.text(x, y, f"{matrix[y, x]:+.1f}", ha="center", va="center", fontsize=9.1,
                            color="white" if abs(matrix[y, x]) > bound * .72 else NAVY)
            for spine in ax.spines.values():
                spine.set_visible(False)
        cax = fig.add_axes([.30, .115, .48, .025])
        cb = fig.colorbar(image, cax=cax, orientation="horizontal")
        cb.set_label("Observed response: log₂(1 + FPKMtreated) − log₂(1 + FPKMuntreated)", fontsize=10, labelpad=5)
        cb.ax.tick_params(labelsize=9, length=2)
        cb.outline.set_visible(False)
        fig.text(.045, .935, "Drug responses across four paired airway cell lines", fontsize=20, weight="bold")
        fig.text(.045, .875, "GSE52778  •  Bulk RNA-seq  •  1 µM of each drug  •  18 h treatment", fontsize=12)
        fig.text(.045, .815, "Same eight genes across treatments; selected from dexamethasone donor means", fontsize=11)
        fig.text(.045, .025, "Measured processed FPKM. Descriptive paired differences; no model prediction or drug-interaction test.", fontsize=9.3, color="#52677B")
        for suffix in ("png", "svg"):
            fig.savefig(output / ("drug_response." + suffix), dpi=175)
        plt.close(fig)
    if (output / "drug_response.png").stat().st_size >= 3 * 1024 * 1024:
        raise ValueError("Gallery PNG exceeds 3 MiB")


def run_case(input_dir, output_dir, invocation=None):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    try:
        paths, sources = resolve_sources(Path(input_dir))
        geo, sra = read_geo_metadata(paths["metadata"]), read_sra_mapping(paths["sra_mapping"])
        sra_identity = verify_sra_identity(sra)
        fpkm = pd.read_csv(paths["fpkm"], sep=r"\s+", keep_default_na=False)
        sample_columns = [column for column in fpkm if re.fullmatch(r"(Dex|Alb|Untreated|Alb_Dex)_LL\d{2}", column)]
        if len(fpkm) != 23273 or not fpkm.gene_id.is_unique or fpkm.gene_id.astype(str).str.strip().eq("").any():
            raise ValueError("Source gene IDs must be the complete unique 23,273-row axis")
        sample_values = fpkm[sample_columns].to_numpy(dtype=float)
        if not np.isfinite(sample_values).all() or (sample_values < 0).any():
            raise ValueError("FPKM values must be finite and nonnegative")
        mapping = align_columns(geo, sra, sample_columns)
        responses, donors, pairs = paired_responses(fpkm, mapping)
        if responses.shape != (3, 4, 23273) or not np.isfinite(responses).all():
            raise ValueError("Unexpected paired response shape")
        tables, raw = output / "tables", output / "raw"
        tables.mkdir(); raw.mkdir()
        mapping.to_csv(tables / "sample_mapping.csv", index=False)
        pairs.to_csv(tables / "donor_pairs.csv", index=False)
        annotation = fpkm.drop(columns=sample_columns)
        annotation.to_csv(tables / "source_annotations.csv", index=False)
        np.savez_compressed(raw / "source_fpkm.npz", source_gene_ids=fpkm.gene_id.to_numpy(dtype=str),
                            sample_columns=np.asarray(sample_columns, dtype=str), fpkm=sample_values)
        np.savez_compressed(raw / "paired_responses.npz", source_gene_ids=fpkm.gene_id.to_numpy(dtype=str),
                            donors=np.asarray(donors, dtype=str), treatments=np.asarray(TREATMENTS, dtype=str), observed_delta=responses)
        status_columns = [treatment + "_status" for treatment in ["Untreated", *TREATMENTS]]
        source_status_ok = fpkm[status_columns].eq("OK").all(axis=1).to_numpy()
        expressed = (sample_values >= 1).all(axis=1)
        eligible = source_status_ok & expressed
        summary_tables = []
        for treatment, response in zip(TREATMENTS, responses):
            summary_tables.append(pd.DataFrame({"gene_id": fpkm.gene_id, "gene_symbol": fpkm.gene_short_name,
                "treatment": treatment, "paired_donors": 4, "mean_paired_difference": response.mean(axis=0),
                "median_paired_difference": np.median(response, axis=0), "sample_sd_across_donors": response.std(axis=0, ddof=1),
                "positive_donors": (response > 0).sum(axis=0), "negative_donors": (response < 0).sum(axis=0),
                "all_condition_status_ok": source_status_ok, "all_16_fpkm_at_least_one": expressed,
                "figure_eligible": eligible}))
        summary = pd.concat(summary_tables, ignore_index=True)
        summary.to_csv(tables / "gene_summary.csv", index=False)
        dex = summary.loc[summary.treatment.eq("Dex") & summary.figure_eligible]
        selected = pd.concat([
            dex.loc[dex.mean_paired_difference.gt(0)].sort_values(["mean_paired_difference", "gene_id"], ascending=[False, True]).head(4),
            dex.loc[dex.mean_paired_difference.lt(0)].sort_values(["mean_paired_difference", "gene_id"], ascending=[True, True]).head(4)])
        if len(selected) != 8:
            raise ValueError("Need four eligible genes in each response direction")
        gene_position = {gene: i for i, gene in enumerate(fpkm.gene_id)}
        pairs_lookup = pairs.set_index(["treatment", "donor"])
        figure_rows = []
        for i, treatment in enumerate(TREATMENTS):
            for j, donor in enumerate(donors):
                pair = pairs_lookup.loc[(treatment, donor)]
                for n, gene in enumerate(selected.itertuples()):
                    k = gene_position[gene.gene_id]
                    figure_rows.append({"gene_id": gene.gene_id, "gene_symbol": gene.gene_symbol,
                        "donor": donor, "treatment": treatment, "panel_selection": "top_positive_Dex" if n < 4 else "top_negative_Dex",
                        "control_column": pair.control_column, "treated_column": pair.treated_column,
                        "control_fpkm": float(fpkm.iloc[k][pair.control_column]), "treated_fpkm": float(fpkm.iloc[k][pair.treated_column]),
                        "observed_response": float(responses[i, j, k])})
        figure_data = pd.DataFrame(figure_rows)
        # Read the exported plot table back and verify every plotted response.
        figure_data.to_csv(tables / "figure_data.csv", index=False)
        saved = pd.read_csv(tables / "figure_data.csv")
        reconstructed = np.log2(1 + saved.treated_fpkm.to_numpy()) - np.log2(1 + saved.control_fpkm.to_numpy())
        error = float(np.max(np.abs(saved.observed_response - reconstructed)))
        if error > 1e-12:
            raise ValueError("Exported figure numbers fail paired FPKM reconstruction")
        draw_figure(saved, selected, donors, output)
        qc = {"status": "completed", "source_rows": len(fpkm), "source_profiles": len(sample_columns),
              "biological_units": 4, "contrasts": 3, "paired_responses": len(pairs),
              "source_gene_id_unique": bool(fpkm.gene_id.is_unique), "source_gene_symbols_unique": bool(fpkm.gene_short_name.is_unique),
              "all_zero_fpkm_rows": int(np.all(sample_values == 0, axis=1).sum()),
              "all_condition_status_ok_rows": int(source_status_ok.sum()), "all_16_fpkm_at_least_one_rows": int(expressed.sum()),
              "figure_eligible_rows": int(eligible.sum()), "plotted_genes": selected.gene_id.tolist(),
              "source_status_counts": {column: {str(k): int(v) for k, v in fpkm[column].value_counts().items()} for column in status_columns},
              "plotted_value_reconstruction_max_abs_error": error,
              "sra_canonical_identity_sha256": sra_identity,
              "sra_canonical_identity_fields": list(SRA_IDENTITY_FIELDS),
              "sra_raw_hash_policy": "Actual raw SHA256 retained; scientific identity projection pinned; XML file ordering may vary",
              "mapping_rule": "Original SRA FASTQ filename -> library_id -> experiment/GEO accession -> donor/treatment; treatment labels also checked against SRA attributes",
              "source_column_order_used_for_pairing": False, "model_status": "not_run", "independent_validation": "not_assessed"}
        write_json(output / "qc.json", qc)
        selection = "Among genes with source status OK in every condition and FPKM >= 1 in all 16 source profiles, select 4 highest positive and 4 lowest negative equal-donor Dex response means; source gene_id breaks ties. Reuse the same panel for Alb and combination. All 23,273 rows are retained in full outputs."
        selected_means = summary.loc[summary.gene_id.isin(selected.gene_id)].pivot(index="gene_id", columns="treatment", values="mean_paired_difference").loc[selected.gene_id]
        selected_means.reset_index().to_csv(tables / "selected_gene_means.csv", index=False)
        table_lines = ["| 来源 gene_id | Dex | Alb | Alb + Dex |", "| --- | ---: | ---: | ---: |"]
        table_lines += [f"| {gene} | {row.Dex:.3f} | {row.Alb:.3f} | {row.Alb_Dex:.3f} |" for gene, row in selected_means.iterrows()]
        report = f"""# GSE52778：真实供体配对的药物观测响应

已实际读取原作者 GEO 处理后 FPKM、原始 GEO 注释和 SRA 文件身份记录；四位供体来源的气道平滑肌细胞系、四个条件，共 16 份 bulk RNA-seq profile。三种处理均相对同一供体的 Untreated，保留全部 23,273 个来源 gene_id、12 个配对响应和全部数值。

![真实药物观测响应](drug_response.png)

三个面板使用同一组 8 个基因，颜色与格内数值都是 `log2(1+FPKM_treated) − log2(1+FPKM_untreated)`。正值表示处理后在此变换尺度上较高，负值表示较低。来源为 FPKM，不能称为 UMI、CPM 或未经伪计数的 log fold change。

选图先要求四个来源 condition status 均为 OK，且所有 16 份 profile 的 FPKM ≥ 1，留下 {int(eligible.sum()):,} 个可展示基因；然后按 Dex 的四供体等权平均差值选最大 4 个正值与最小 4 个负值，稳定 gene_id 打破并列。此筛选只用于图，不删除全量输出，也不构成显著性检验。

{chr(10).join(table_lines)}

## 可核查文件

- `tables/sample_mapping.csv`：16 个 LL 文库、GSM、SRX、SRR、真实供体和处理的逐项映射。
- `tables/donor_pairs.csv`：每个处理和供体实际使用的两个来源列。
- `raw/source_fpkm.npz`、`raw/paired_responses.npz`：全部来源数值、三个处理 × 四供体 × 23,273 个基因响应及全部轴。
- `tables/source_annotations.csv`、`tables/gene_summary.csv`：保留来源状态标签、locus、来源 gene_id 与 gene_short_name，及每个处理全基因的等权汇总。
- `tables/figure_data.csv`：96 个图值、实际对照/处理 FPKM 和来源列名；重新计算的最大误差为 {error:.3g}。
- `provenance.json`、`qc.json`：来源 URL、实际 SHA256、包版本、完整命令和检查。

## 解释边界

这是处理后 bulk RNA-seq 的描述性复读，不是 raw-read 比对、单细胞分析或虚拟细胞模型推断。四个供体才是生物学单位；同一对照在三个对比中复用，不能把 12 个配对响应视为 12 个独立供体。保留所有来源基因时也保留 LOWDATA、FAIL、HIDATA 等原状态，这些状态不自动获得可靠表达解释。图的筛选是公开的展示规则，不是预注册基因面板或无偏全基因性能。

供体与处理差异不能直接解释为临床疗效、药物协同或拮抗；本例没有为交互作用建立统计模型，没有 P 值、FDR、置信区间或模型预测。原作者的显著性结果也不作为本脚本重新获得的结论。`model_status: not_run`；`independent_validation: not_assessed`。

来源：[GEO GSE52778]({SERIES_URL})、[原始研究 Himes 等，2014]({PAPER_URL})、[NCBI SRA SRP033351](https://www.ncbi.nlm.nih.gov/sra?term=SRP033351)。原论文为 CC BY；本次 GEO/SRA 源文件未核实单独数据许可，不能自动套用项目代码 MIT 许可。
"""
        (output / "report.md").write_text(report, encoding="utf-8")
        provenance = {"schema_version": 1, "case_id": CASE_ID, "created_at": datetime.now(timezone.utc).isoformat(),
            "source_kind": "official_GEO_GSE52778_processed_FPKM_and_GEO_SRA_metadata", "sources": sources,
            "source_paper": PAPER_URL, "parameters": {"scale": "log2(1 + source_FPKM_treated) - log2(1 + source_FPKM_untreated)", "gene_selection": selection},
            "run_status": "completed", "model_status": "not_run", "independent_validation": "not_assessed",
            "script_sha256": digest(__file__), "python": platform.python_version(), "interpreter": sys.executable,
            "packages": {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "matplotlib")},
            "invocation": invocation or {"kind": "python_api"},
            "artifacts": {str(path.relative_to(output)): record(path) for path in sorted(output.rglob("*")) if path.is_file()}}
        write_json(output / "provenance.json", provenance)
        return {"output_dir": str(output), "qc": qc, "provenance": provenance}
    except Exception as error:
        write_json(output / "error.json", {"status": "failed", "error": str(error), "model_status": "not_run"})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory; existing outputs are never overwritten")
    args = parser.parse_args(argv)
    result = run_case(args.input_dir, args.output_dir,
                      invocation={"argv": sys.argv if argv is None else argv, "cwd": str(Path.cwd())})
    print(json.dumps({"output_dir": result["output_dir"], "qc": result["qc"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
