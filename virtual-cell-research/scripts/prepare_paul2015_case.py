"""Prepare a fixed wild-type background from original GSE72857 UMI counts.

This prepares input only. It does not run CellOracle or assert predictive validity.
The CLI accepts checksum-pinned official counts, design and GEO SOFT metadata.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import sys

OFFICIAL_HASHES = {
    "counts": "6f45b72b935493181f0f9fdb7343181a5eeca63d0d39ba2a2a8439ac34f08e74",
    "design": "b547a49285a59476e194d77c9a34a9747628ee465736227d840a6aac5f3a5f68",
    "samples": "9dac928a12f462739c0c92f3562acedff4813b2a2acdcf3aa2bee9e62cd6b440",
}
SOURCE_URLS = {
    "counts": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE72nnn/GSE72857/suppl/GSE72857_umitab.txt.gz",
    "design": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE72nnn/GSE72857/suppl/GSE72857_experimental_design.txt.gz",
    "samples": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE72nnn/GSE72857/soft/GSE72857_family.soft.gz",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_design(path):
    import pandas as pd
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.startswith("Well_ID\tSeq_batch_ID\t"):
                rows = list(csv.DictReader(handle, fieldnames=line.rstrip("\r\n").split("\t"), delimiter="\t"))
                break
        else:
            raise ValueError("Experimental design header is missing")
    frame = pd.DataFrame(rows)
    required = {"Well_ID", "Amp_batch_ID", "Mouse_ID", "Batch_desc", "Number_of_cells", "Plate_ID"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ValueError("Experimental design is empty or lacks required fields")
    if frame.Well_ID.isna().any() or frame.Well_ID.eq("").any() or frame.Well_ID.duplicated().any():
        raise ValueError("Design Well_ID must be unique and nonempty")
    return frame.set_index("Well_ID", drop=False)


def read_samples(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        text = handle.read()
    result = {}
    for sample in text.split("^SAMPLE = ")[1:]:
        lines = sample.splitlines()
        record = {"geo_sample": lines[0].strip()}
        for line in lines[1:]:
            if line.startswith("^DATABASE") or line.startswith("^SERIES") or line.startswith("^PLATFORM"):
                break
            for prefix, key in (("!Sample_title = ", "title"),
                                ("!Sample_source_name_ch1 = ", "source")):
                if line.startswith(prefix):
                    record[key] = line[len(prefix):]
            if line.startswith("!Sample_characteristics_ch1 = "):
                value = line.split(" = ", 1)[1]
                if ": " in value:
                    key, val = value.split(": ", 1)
                    record[key] = val
            if line.startswith("!Sample_data_processing = Genome_build: "):
                record["genome_build"] = line.rsplit(": ", 1)[1]
        match = re.fullmatch(r"(AB\d+) \[Sample \d+\]", record.get("title", ""))
        if not match:
            raise ValueError("GEO sample title does not identify an amplification batch")
        batch = match.group(1)
        if batch in result:
            raise ValueError("Duplicate GEO amplification batch")
        result[batch] = record
    if not result:
        raise ValueError("No sample metadata found")
    return result


def prepare(counts, design, samples, output_dir, *, max_cells=500, min_counts=1000,
            min_genes=500, seed=123, expected_hashes=None, synthetic_fixture=False):
    import anndata as ad
    import numpy as np
    import pandas as pd
    from scipy import sparse

    output = Path(output_dir)
    if os.path.lexists(output):
        raise FileExistsError("Use a new output directory; existing paths are not overwritten")
    for name, value in (("max_cells", max_cells), ("min_counts", min_counts), ("min_genes", min_genes)):
        if type(value) is not int or value < 1 or (name == "max_cells" and value > 1000):
            raise ValueError(f"{name} must be positive; the teaching case permits at most 1000 cells")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    expected = OFFICIAL_HASHES if expected_hashes is None else expected_hashes
    if (expected != OFFICIAL_HASHES) != bool(synthetic_fixture):
        raise ValueError("Non-official hashes require explicit synthetic_fixture=True")
    sources = {}
    for name, path in (("counts", counts), ("design", design), ("samples", samples)):
        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= 24 * 1024 * 1024:
            raise ValueError(f"{name} must be a nonempty file no larger than 24 MiB")
        actual = sha256(path)
        if actual != expected.get(name):
            raise ValueError(f"{name} SHA256 mismatch; do not substitute another data version")
        sources[name] = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": actual,
                         "url": None if synthetic_fixture else SOURCE_URLS[name]}
    design_df = read_design(design)
    sample_map = read_samples(samples)
    wanted = (design_df.Batch_desc.eq("Unsorted myeloid") & design_df.Mouse_ID.eq("2")
              & design_df.Number_of_cells.eq("1"))
    candidate = design_df.loc[wanted].copy()
    if candidate.empty:
        raise ValueError("No source-labeled Mouse 2 single-cell Unsorted myeloid wells")
    for batch in candidate.Amp_batch_ID.unique():
        record = sample_map.get(batch, {})
        expected_metadata = {"source": "Unsorted myeloid", "genotype/variation": "wild type",
                             "strain background": "C57BL/6", "tissue": "bone marrow", "genome_build": "mm9"}
        if any(record.get(key) != val for key, val in expected_metadata.items()):
            raise ValueError(f"GEO metadata does not verify the selected wild-type mm9 background: {batch}")
    for field in ("geo_sample", "genotype/variation", "strain background", "tissue", "selection marker", "genome_build"):
        candidate[field.replace("/", "_").replace(" ", "_")] = [sample_map[batch].get(field, "unknown") for batch in candidate.Amp_batch_ID]
    gene_names, vectors, excluded_genes = [], [], []
    source_rows = 0
    ambiguous_total = None
    original_total = None
    with gzip.open(counts, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        cell_ids = next(reader, [])
        if not cell_ids or len(cell_ids) != len(set(cell_ids)) or any(not cell for cell in cell_ids):
            raise ValueError("Matrix cell IDs must be unique and nonempty")
        if set(cell_ids) != set(design_df.index):
            raise ValueError("Matrix and design cell IDs must match exactly")
        candidate_ids = [cell for cell in cell_ids if cell in candidate.index]
        positions = np.asarray([i for i, cell in enumerate(cell_ids) if cell in candidate.index])
        candidate = candidate.loc[candidate_ids]
        ambiguous_total = np.zeros(len(candidate), dtype=np.int64)
        original_total = np.zeros(len(candidate), dtype=np.int64)
        seen = set()
        for row in reader:
            source_rows += 1
            if len(row) != len(cell_ids) + 1 or not row[0] or row[0] in seen:
                raise ValueError("Count row width or gene identity is invalid")
            seen.add(row[0])
            try:
                values = np.asarray([row[int(i) + 1] for i in positions], dtype=np.int64)
            except (ValueError, OverflowError) as exc:
                raise ValueError("Selected-background counts must be exact integers") from exc
            if (values < 0).any() or (values > 1_000_000).any():
                raise ValueError("Selected-background counts are negative or exceed the case limit")
            original_total += values
            if ";" in row[0]:
                ambiguous_total += values
                excluded_genes.append({"source_gene_id": row[0], "reason": "multiple_gene_names_not_resolved", "candidate_count_sum": int(values.sum())})
                continue
            gene_names.append(row[0])
            vectors.append(sparse.csr_matrix(values.reshape(1, -1)))
    matrix = sparse.vstack(vectors, format="csr").T.tocsr()
    totals = np.asarray(matrix.sum(axis=1)).ravel()
    genes_detected = np.asarray((matrix > 0).sum(axis=1)).ravel()
    candidate["counts_before_ambiguous_gene_exclusion"] = original_total
    candidate["counts_in_excluded_multiname_genes"] = ambiguous_total
    candidate["counts_retained_unambiguous"] = totals
    candidate["genes_detected_unambiguous"] = genes_detected
    candidate["qc_passed"] = (totals >= min_counts) & (genes_detected >= min_genes)
    eligible = candidate.index[candidate.qc_passed].tolist()
    if len(eligible) < max_cells:
        raise ValueError(f"Only {len(eligible)} eligible cells; choose an explicit smaller max_cells")
    ordered = sorted(eligible, key=lambda cell: (hashlib.sha256(f"{seed}:{cell}".encode()).hexdigest(), cell))
    selected_ids = set(ordered[:max_cells])
    candidate["selected"] = candidate.index.isin(selected_ids)
    selected = candidate.selected.to_numpy()
    selected_matrix = matrix[selected]
    nonzero_genes = np.asarray(selected_matrix.sum(axis=0)).ravel() > 0
    if "Gata1" not in gene_names or not nonzero_genes[gene_names.index("Gata1")]:
        raise ValueError("Gata1 is absent or unexpressed in the selected cells")
    var = pd.DataFrame(index=pd.Index(np.asarray(gene_names)[nonzero_genes], name="gene_symbol"))
    obs = candidate.loc[candidate.selected].copy()
    obs.index.name = "cell_id"
    data = ad.AnnData(X=selected_matrix[:, nonzero_genes].astype(np.int32), obs=obs, var=var)
    data.uns["input_scale"] = "raw_nonnegative_integer_molecule_counts"
    data.uns["species"] = "Mus musculus"
    data.uns["genome_build"] = "mm9"
    data.uns["source_accession"] = "GSE72857"
    data.uns["selection"] = "Mouse_ID=2; Unsorted myeloid; Number_of_cells=1; QC; smallest SHA256(seed:Well_ID)"
    output.mkdir(parents=True, exist_ok=False)
    data.write_h5ad(output / "paul2015_wt_input.h5ad", compression="gzip")
    candidate.to_csv(output / "candidate_cells.csv", index=False)
    pd.DataFrame(excluded_genes, columns=["source_gene_id", "reason", "candidate_count_sum"]).to_csv(output / "excluded_genes.csv", index=False)
    dump_json(output / "sample_metadata.json", {batch: sample_map[batch] for batch in candidate.Amp_batch_ID.unique()})
    qc = {"case_id": "celloracle-paul2015-gata1", "source_kind": "synthetic_test_fixture" if synthetic_fixture else "GSE72857_original_UMI_and_design",
          "source_cells": len(cell_ids), "source_genes": source_rows, "candidate_cells": len(candidate),
          "eligible_cells": len(eligible), "selected_cells": data.n_obs, "selected_expressed_genes": data.n_vars,
          "excluded_multiname_genes": len(excluded_genes), "candidate_counts_before_exclusion": int(original_total.sum()),
          "candidate_counts_excluded_multiname": int(ambiguous_total.sum()),
          "selected_counts_excluded_multiname": int(ambiguous_total[selected].sum()),
          "selected_counts_before_exclusion": int(original_total[selected].sum()),
          "selected_counts_retained": int(data.X.sum()), "selected_target_positive_cells": int((data[:, "Gata1"].X > 0).sum()),
          "raw_counts_passed": True, "background_verified_in_GEO": True, "model_status": "not_run", "independent_validation": "not_assessed",
          "numeric_check_scope": "all genes and count values in the 3040-well selected background before QC; other experimental backgrounds are not scanned" if not synthetic_fixture else "synthetic candidate counts"}
    dump_json(output / "qc.json", qc)
    provenance = {"created_at": datetime.now(timezone.utc).isoformat(), "sources": sources,
                  "script_sha256": sha256(__file__), "sys_executable": sys.executable,
                  "parameters": {"max_cells": max_cells, "min_counts": min_counts, "min_genes": min_genes, "seed": seed},
                  "versions": {name: importlib.metadata.version(name) for name in ["anndata", "numpy", "pandas", "scipy"]},
                  "model_status": "not_run", "independent_validation": "not_assessed",
                  "artifacts": {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p)} for p in sorted(output.iterdir()) if p.is_file()}}
    dump_json(output / "provenance.json", provenance)
    return qc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("counts", "design", "samples", "output-dir"):
        parser.add_argument("--" + flag, required=True, type=Path)
    parser.add_argument("--max-cells", type=int, default=500)
    parser.add_argument("--min-counts", type=int, default=1000)
    parser.add_argument("--min-genes", type=int, default=500)
    parser.add_argument("--seed", type=int, default=123)
    args = parser.parse_args(argv)
    try:
        result = prepare(args.counts, args.design, args.samples, args.output_dir, max_cells=args.max_cells,
                         min_counts=args.min_counts, min_genes=args.min_genes, seed=args.seed)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Preparation blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
