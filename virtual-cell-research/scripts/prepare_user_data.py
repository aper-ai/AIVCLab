"""Prepare user expression data without changing its values or identity.

This is an input preparation tool, not a model runner or a provenance certificate.
Only the selected expression matrix and obs/var annotations enter the new H5AD.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import html
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

MIB = 1024 * 1024
MAX_AXIS = 1_000_000


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(MIB), b""):
            digest.update(block)
    return digest.hexdigest()


def dump_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def check_ids(values, label):
    values = list(values)
    if not values or len(values) > MAX_AXIS:
        raise ValueError(f"{label}: axis must contain 1..{MAX_AXIS} identifiers")
    if any(not isinstance(x, str) or not x or x != x.strip()
           or any(ord(c) < 32 for c in x) for x in values):
        raise ValueError(f"{label}: identifiers must be nonempty strings without surrounding whitespace/control characters")
    if len(set(values)) != len(values):
        raise ValueError(f"{label}: duplicate identifiers; resolve them explicitly before preparation")
    return values


def table_rows(path, expanded_limit):
    path = Path(path)
    suffix = path.name.lower()
    delimiter = "\t" if suffix.endswith((".tsv", ".tsv.gz")) else ","
    if not suffix.endswith((".csv", ".csv.gz", ".tsv", ".tsv.gz")):
        raise ValueError("Tables must use .csv, .tsv, .csv.gz or .tsv.gz")
    opener = gzip.open if suffix.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        def lines():
            total = 0
            while True:
                line = handle.readline(8 * MIB + 1)
                if not line:
                    break
                length = len(line.encode("utf-8"))
                total += length
                if length > 8 * MIB or total > expanded_limit:
                    raise ValueError("Expanded table or line exceeds the configured preparation limit; use a bounded H5AD workflow")
                yield line
        yield from csv.reader(lines(), delimiter=delimiter, strict=True)


def read_expression_table(path, orientation, scale, matrix_limit, expanded_limit):
    import numpy as np
    import pandas as pd
    if orientation not in ("cells_by_genes", "genes_by_cells"):
        raise ValueError("Table input requires explicit --orientation cells_by_genes or genes_by_cells")
    iterator = table_rows(path, expanded_limit)
    header = next(iterator, [])
    check_ids(header, "table header")
    if len(header) < 2:
        raise ValueError("Expression table needs an identifier column and value columns")
    row_ids, seen = [], set()
    for record, row in enumerate(iterator, 2):
        if len(row) != len(header):
            raise ValueError(f"Expression record {record}: row width differs from header; missing values are not zero")
        check_ids([row[0]], "row ID")
        if row[0] in seen:
            raise ValueError("Expression row IDs contain duplicates")
        seen.add(row[0]); row_ids.append(row[0])
        if len(row_ids) > MAX_AXIS or len(row_ids) * (len(header) - 1) * 8 > matrix_limit:
            raise ValueError("Dense expression matrix exceeds the configured preparation memory limit")
    check_ids(row_ids, "expression rows")
    matrix = np.empty((len(row_ids), len(header) - 1), dtype=np.int64 if scale == "raw_counts" else np.float64)
    rows = table_rows(path, expanded_limit)
    if next(rows, []) != header:
        raise ValueError("Expression file changed during preparation")
    count = 0
    for count, row in enumerate(rows, 1):
        if count > len(row_ids) or len(row) != len(header) or row[0] != row_ids[count - 1]:
            raise ValueError("Expression file changed during preparation")
        for col, value in enumerate(row[1:]):
            try:
                if scale == "raw_counts":
                    number = Decimal(value)
                    if (not number.is_finite() or number < 0 or number != number.to_integral_value()
                            or number > np.iinfo(np.int64).max):
                        raise ValueError("raw_counts must be exact nonnegative int64 values")
                    matrix[count - 1, col] = int(number)
                else:
                    number = float(value)
                    if not math.isfinite(number) or number < 0:
                        raise ValueError("expression must be finite and nonnegative")
                    matrix[count - 1, col] = number
            except (ValueError, InvalidOperation, OverflowError) as exc:
                raise ValueError(f"Expression record {count + 1}, value column {col + 2}: missing/invalid value; no filling, rounding or normalization is performed") from exc
    if count != len(row_ids):
        raise ValueError("Expression file changed during preparation")
    if orientation == "genes_by_cells":
        return matrix.T, pd.DataFrame(index=pd.Index(header[1:], name="cell_id")), pd.DataFrame(index=pd.Index(row_ids, name="gene_id"))
    return matrix, pd.DataFrame(index=pd.Index(row_ids, name="cell_id")), pd.DataFrame(index=pd.Index(header[1:], name="gene_id"))


def read_h5ad_matrix(path, counts_layer, matrix_limit):
    import h5py
    from anndata.io import read_elem
    import numpy as np
    from scipy import sparse
    location = "X" if counts_layer is None else "layers/" + counts_layer
    if counts_layer is not None and (not counts_layer or "/" in counts_layer or counts_layer != counts_layer.strip()):
        raise ValueError("--counts-layer must name one H5AD layer, not a path")
    with h5py.File(path, "r") as handle:
        if location not in handle or "obs" not in handle or "var" not in handle:
            raise ValueError(f"H5AD needs obs, var and the selected expression matrix {location}")
        for selected_path in (location, "obs", "var"):
            parent = handle
            for part in selected_path.split("/"):
                if not isinstance(parent.get(part, getlink=True), h5py.HardLink):
                    raise ValueError("Selected H5AD input cannot follow external or soft links")
                parent = parent[part]
        node = handle[location]
        if isinstance(node, h5py.Dataset):
            shape = node.shape
            estimated = int(node.size) * node.dtype.itemsize
            if node.dtype.kind not in "biuf":
                raise ValueError("H5AD expression must be real numeric data")
        else:
            encoding = node.attrs.get("encoding-type", "")
            if isinstance(encoding, bytes):
                encoding = encoding.decode("ascii")
            if encoding not in ("csr_matrix", "csc_matrix"):
                raise ValueError("H5AD preparation supports only dense, CSR or CSC expression matrices")
            if not all(name in node and isinstance(node[name], h5py.Dataset) for name in ("data", "indices", "indptr")):
                raise ValueError("H5AD sparse matrix is missing numeric storage arrays")
            if any(not isinstance(node.get(name, getlink=True), h5py.HardLink) for name in ("data", "indices", "indptr")):
                raise ValueError("Sparse H5AD storage cannot follow external or soft links")
            if (node["data"].dtype.kind not in "biuf" or node["indices"].dtype.kind not in "iu"
                    or node["indptr"].dtype.kind not in "iu"
                    or any(node[name].ndim != 1 for name in ("data", "indices", "indptr"))):
                raise ValueError("Sparse values must be numeric; sparse indices and pointers must be one-dimensional integer arrays")
            shape = tuple(node.attrs.get("shape", ()))
            estimated = sum(int(node[k].size) * node[k].dtype.itemsize for k in ("data", "indices", "indptr"))
        if len(shape) != 2 or any(int(n) < 1 or int(n) > MAX_AXIS for n in shape):
            raise ValueError("H5AD expression shape is empty, invalid or exceeds axis limits")
        if estimated > matrix_limit:
            raise ValueError("Stored H5AD expression exceeds the configured preparation memory limit")
        if not isinstance(node, h5py.Dataset):
            major = int(shape[0] if encoding == "csr_matrix" else shape[1])
            minor = int(shape[1] if encoding == "csr_matrix" else shape[0])
            if node["indptr"].shape != (major + 1,) or node["data"].shape != node["indices"].shape:
                raise ValueError("Sparse H5AD storage lengths do not match its axes")
            pointers = node["indptr"][:]
            if pointers[0] != 0 or pointers[-1] != node["data"].size or (pointers[1:] < pointers[:-1]).any():
                raise ValueError("Sparse H5AD pointers do not cover all stored values exactly")
            del pointers
            for start in range(0, node["indices"].size, 1_000_000):
                indices = node["indices"][start:start + 1_000_000]
                if (indices < 0).any() or (indices >= minor).any():
                    raise ValueError("Sparse H5AD indices are outside the declared axes")
        def annotation_bytes(item, depth=0):
            if isinstance(item, h5py.Dataset):
                overhead = 64 if item.dtype.kind == "O" else item.dtype.itemsize
                return max(int(item.size) * overhead, item.id.get_storage_size())
            if depth > 8 or len(item) > 4096:
                raise ValueError("H5AD annotations exceed the preparation structure limit")
            total = 0
            for key in item:
                if not isinstance(item.get(key, getlink=True), h5py.HardLink):
                    raise ValueError("H5AD annotations cannot follow external or soft links")
                total += annotation_bytes(item[key], depth + 1)
                if total > matrix_limit:
                    raise ValueError("H5AD annotations exceed the configured preparation memory limit")
            return total
        if annotation_bytes(handle["obs"]) + annotation_bytes(handle["var"]) > matrix_limit:
            raise ValueError("H5AD annotations exceed the configured preparation memory limit")
        # Only these components are loaded: unrelated layers, raw and embeddings
        # may be much larger and are deliberately not copied into this input.
        matrix = read_elem(node)
        obs, var = read_elem(handle["obs"]), read_elem(handle["var"])
        omitted = [name for name in handle if name not in ("X", "obs", "var")]
    if matrix.shape != (len(obs), len(var)):
        raise ValueError("H5AD expression axes do not match obs/var")
    if sparse.issparse(matrix):
        matrix.check_format(full_check=True)
        if not matrix.has_canonical_format:
            raise ValueError("Sparse input must be canonical (sorted indices, no duplicate coordinates); resolve structure explicitly")
    elif not isinstance(matrix, np.ndarray):
        raise ValueError("Unsupported expression matrix representation")
    return matrix, obs, var, omitted, estimated


def join_metadata(frame, path, id_column, expanded_limit):
    import pandas as pd
    rows = table_rows(path, min(expanded_limit, 32 * MIB))
    header = next(rows, [])
    check_ids(header, "metadata header")
    if id_column not in header:
        raise ValueError(f"Metadata needs an exact {id_column} column")
    data = []
    for row in rows:
        if len(row) != len(header):
            raise ValueError("Metadata row width differs from header")
        data.append(row)
        if len(data) > len(frame):
            raise ValueError("Metadata must match all expression IDs exactly, without extra rows")
    metadata = pd.DataFrame(data, columns=header).set_index(id_column)
    check_ids(metadata.index.tolist(), id_column)
    if set(metadata.index) != set(frame.index):
        raise ValueError(f"Metadata {id_column} must match all expression IDs exactly; missing or extra identifiers found")
    overlaps = set(metadata.columns) & set(frame.columns)
    if overlaps:
        raise ValueError(f"Metadata columns already exist: {sorted(overlaps)}; no existing annotation is overwritten")
    result = frame.copy()
    for column in metadata.columns:
        # Preserve literal NA and blank strings as supplied, rather than making
        # them expression zeros or silently turning IDs into integers.
        result[column] = metadata.loc[frame.index, column].to_numpy()
    return result


def matrix_qc(matrix, scale):
    import numpy as np
    from scipy import sparse
    values = matrix.data if sparse.issparse(matrix) else matrix.reshape(-1)
    if values.dtype.kind not in "biuf":
        raise ValueError("Expression must use a real numeric dtype")
    minimum = maximum = None
    nonzero = 0
    for start in range(0, len(values), 1_000_000):
        chunk = values[start:start + 1_000_000]
        if not np.isfinite(chunk).all() or (chunk < 0).any():
            raise ValueError("Expression contains NaN/Inf or negative values")
        if scale == "raw_counts" and (chunk != np.floor(chunk)).any():
            raise ValueError("Declared raw_counts contain noninteger values; they will not be rounded")
        if chunk.size:
            low, high = chunk.min().item(), chunk.max().item()
            minimum = low if minimum is None else min(minimum, low)
            maximum = high if maximum is None else max(maximum, high)
            nonzero += int(np.count_nonzero(chunk))
    if sparse.issparse(matrix):
        detected = matrix.astype(bool).getnnz(axis=1) if not (matrix.data == 0).any() else np.asarray((matrix != 0).sum(axis=1)).ravel()
    else:
        detected = np.count_nonzero(matrix, axis=1)
    return {"shape": list(matrix.shape), "dtype": str(matrix.dtype),
            "storage": matrix.format if sparse.issparse(matrix) else "dense",
            "stored_values_checked": int(values.size), "nonzero_values": nonzero,
            "minimum_stored_value": minimum, "maximum_stored_value": maximum,
            "zero_expression_cells": int((detected == 0).sum()),
            "values_finite_nonnegative": True,
            "raw_count_integer_check": "passed" if scale == "raw_counts" else "not_applicable"}


def prepare(input_file, output_dir, *, input_scale, species, orientation=None, counts_layer=None,
            obs_metadata=None, gene_metadata=None, gene_id_kind="unknown", targets=None,
            max_input_mib=256, max_matrix_mib=256, max_expanded_mib=512,
            celloracle_ko=False, python_executable=None, base_grn=None, source_note=None):
    output = Path(output_dir)
    if os.path.lexists(output):
        raise FileExistsError("Use a new output directory; existing paths are never overwritten")
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    try:
        import anndata as ad
        for name, value in (("max_input_mib", max_input_mib), ("max_matrix_mib", max_matrix_mib), ("max_expanded_mib", max_expanded_mib)):
            if type(value) is not int or not 1 <= value <= 4096:
                raise ValueError(f"{name} must be an integer in 1..4096")
        if input_scale not in ("raw_counts", "normalized", "log1p"):
            raise ValueError("Declare input_scale raw_counts, normalized or log1p")
        check_ids([species], "species declaration")
        if gene_id_kind not in ("unknown", "gene_symbol", "ensembl", "other"):
            raise ValueError("gene_id_kind must be unknown, gene_symbol, ensembl or other")
        targets = [] if targets is None else list(targets)
        if targets:
            check_ids(targets, "requested targets")
        if not celloracle_ko and (python_executable is not None or base_grn is not None):
            raise ValueError("--python-executable and --base-grn are only used with --celloracle-ko")
        sources = {}
        for role, path in (("expression", input_file), ("obs_metadata", obs_metadata), ("gene_metadata", gene_metadata)):
            if path is None:
                continue
            path = Path(path).resolve()
            if not path.is_file() or not 0 < path.stat().st_size <= max_input_mib * MIB:
                raise ValueError(f"{role} must be a nonempty file within --max-input-mib")
            sources[role] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        input_path = Path(sources["expression"]["path"])
        omitted = []
        if input_path.suffix.lower() == ".h5ad":
            if orientation is not None:
                raise ValueError("H5AD already defines cells-by-genes orientation; omit --orientation")
            matrix, obs, var, omitted, estimated = read_h5ad_matrix(input_path, counts_layer, max_matrix_mib * MIB)
            selected = "X" if counts_layer is None else "layers/" + counts_layer
        else:
            if counts_layer is not None:
                raise ValueError("--counts-layer only applies to H5AD input")
            matrix, obs, var = read_expression_table(input_path, orientation, input_scale,
                                                    max_matrix_mib * MIB, max_expanded_mib * MIB)
            estimated, selected = matrix.nbytes, "table"
        check_ids(obs.index.tolist(), "cell IDs")
        check_ids(var.index.tolist(), "gene IDs")
        if not obs.columns.is_unique or not var.columns.is_unique:
            raise ValueError("H5AD obs/var annotation columns must be unique")
        if obs_metadata is not None:
            obs = join_metadata(obs, obs_metadata, "cell_id", max_expanded_mib * MIB)
        if gene_metadata is not None:
            var = join_metadata(var, gene_metadata, "gene_id", max_expanded_mib * MIB)
        missing = sorted(set(targets) - set(var.index))
        if missing:
            raise ValueError(f"Requested target IDs are absent: {missing}; gene symbols are annotations unless explicitly used as the unique gene axis")
        qc = matrix_qc(matrix, input_scale)
        qc.update({"status": "prepared", "model_status": "not_run", "independent_validation": "not_assessed",
                   "targets_present": targets, "source_values_changed": False,
                   "cells_filtered": 0, "genes_filtered": 0,
                   "annotations_added": {"obs": obs_metadata is not None, "var": gene_metadata is not None}})
        pending = output / "prepared_input.pending.h5ad"
        prepared = ad.AnnData(X=matrix, obs=obs, var=var)
        prepared.write_h5ad(pending, compression="gzip", convert_strings_to_categoricals=False)
        for record in sources.values():
            if sha256(record["path"]) != record["sha256"]:
                raise ValueError("An input file changed during preparation; do not use the pending output")
        pending.replace(output / "prepared_input.h5ad")
        request_plan = {"status": "not_requested", "missing": [], "model_compatibility": "not_verified"}
        if celloracle_ko:
            missing_fields = []
            if input_scale != "raw_counts": missing_fields.append("raw_counts input required for this CellOracle route")
            if gene_id_kind != "gene_symbol": missing_fields.append("explicit gene_symbol axis declaration; no implicit Ensembl-to-symbol conversion")
            if len(targets) != 1: missing_fields.append("exactly one target gene ID for this single-gene KO request")
            if qc["zero_expression_cells"]: missing_fields.append("zero-expression cells require an explicit upstream QC decision")
            if min(matrix.shape) < 4: missing_fields.append("CellOracle route requires at least four cells and four genes")
            resources = {}
            for role, value in (("python_executable", python_executable), ("base_grn", base_grn)):
                # The invoked venv entry determines its environment even when
                # bin/python links to a shared binary. Keep that entry intact.
                path = Path(value).expanduser() if value else None
                if path is not None:
                    path = path.absolute() if role == "python_executable" else path.resolve()
                if path is None or not path.is_file() or not path.stat().st_size:
                    missing_fields.append(role + " existing nonempty local file")
                else:
                    resources[role] = {"path": str(path), "sha256": sha256(path), "check": "readable_only_not_executed"}
            request_plan = {"status": "incomplete" if missing_fields else "request_written", "missing": missing_fields,
                            "model_compatibility": "not_verified", "resources": resources}
            if not missing_fields:
                request = {"schema_version": 1, "task": "ko", "backend": "CellOracle",
                           "input_file": "prepared_input.h5ad", "input_scale": "raw_counts",
                           "species": species, "targets": targets, "analysis_dir": "analysis",
                           "scan_h5ad_values": True, "python_executable": resources["python_executable"]["path"],
                           "resources": {"base_grn": resources["base_grn"]["path"]}}
                dump_json(output / "preflight_request.json", request)
        card = {"schema_version": 1, "status": "prepared_not_model_ready", "species": species,
                "input_scale": input_scale, "gene_id_kind": gene_id_kind, "source_note": source_note,
                "declarations_verified": False, "source_expression_location": selected,
                "output_expression_location": "X", "output_orientation": "cells_by_genes",
                "shape": list(matrix.shape), "matrix_storage_bytes": estimated, "targets": targets,
                "obs_columns": list(obs.columns), "var_columns": list(var.columns),
                "omitted_h5ad_components": omitted, "celloracle_ko_request": request_plan,
                "next_step": "Review data origin/scale and biological context, then run the matching preflight and model-specific checks.",
                "limits": {"max_input_mib": max_input_mib, "max_matrix_mib": max_matrix_mib,
                           "max_expanded_mib": max_expanded_mib, "max_axis": MAX_AXIS}}
        dump_json(output / "qc.json", qc); dump_json(output / "data_card.json", card)
        next_text = ("已生成 [preflight_request.json](preflight_request.json)。运行预检后还需核对 GRN、目标 TF 与模型环境。"
                     if request_plan["status"] == "request_written" else
                     "CellOracle KO 请求尚未生成。" + ("需补齐：" + "；".join(request_plan["missing"]) if celloracle_ko else "按所选模型核对输入契约和资源。"))
        report = f"""# 用户表达数据准备结果

已保存 **{matrix.shape[0]:,} 个细胞/样本 × {matrix.shape[1]:,} 个基因**到 [prepared_input.h5ad](prepared_input.h5ad)。本步骤没有运行模型。

| 项目 | 本次记录 |
| --- | --- |
| 物种声明 | {html.escape(species).replace('|', '&#124;')} |
| 表达尺度声明 | {input_scale} |
| 基因 ID 类型声明 | {gene_id_kind} |
| 选用的表达位置 | {html.escape(selected).replace('|', '&#124;')} |
| 保存格式 | {qc['storage']}，{qc['dtype']}；X 为 cells × genes |
| 全零细胞/样本 | {qc['zero_expression_cells']}，原样保留 |
| 已核对目标 ID | {html.escape(', '.join(targets)).replace('|', '&#124;') if targets else '未指定'} |

## 下一步

{next_text}

查看 [数据卡](data_card.json)、[数值与身份检查](qc.json)和[来源记录](provenance.json)。提供供体、细胞类型、条件、对照和药物/剂量信息，按研究问题选择模型。使用稳定 ID 连接结果；gene_symbol 注释不会自动替换唯一 gene ID。

## 如何解释这次完成

程序保留选定矩阵的全部细胞、基因和数值，没有归一化、填缺失值、过滤、取整或基因别名合并。CSV/TSV 转换为 int64（raw_counts）或 float64（其他尺度）；H5AD 保留所选矩阵的 dtype 和稀疏格式。

H5AD 只复制选定表达矩阵及 obs/var 注释；其他层、raw、embedding、图和 uns 不进入这个最小模型输入，原文件保持不变。输入的物种、尺度、gene ID 类型和来源说明仍是使用者声明；整数检查不能证明数据未经归一化，准备成功也不证明模型兼容、训练域匹配或独立验证成立。
"""
        (output / "report.md").write_text(report, encoding="utf-8")
        artifacts = {p.name: sha256(p) for p in output.iterdir() if p.is_file()}
        versions = {name: importlib.metadata.version(name) for name in ("anndata", "h5py", "numpy", "pandas", "scipy")}
        provenance = {"schema_version": 1, "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat(),
                      "python_executable": sys.executable, "argv": sys.argv, "packages": versions,
                      "sources": sources, "script_sha256": sha256(__file__), "outputs_sha256": artifacts,
                      "model_status": "not_run", "independent_validation": "not_assessed"}
        dump_json(output / "provenance.json", provenance)
        return card
    except Exception as exc:
        dump_json(output / "error.json", {"status": "failed", "model_status": "not_run",
                  "exception_type": type(exc).__name__, "message": str(exc), "started_utc": started,
                  "failed_utc": datetime.now(timezone.utc).isoformat(),
                  "note": "This new output directory may contain incomplete artifacts; source files were not modified."})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare CSV/TSV/H5AD expression with explicit scale and stable IDs; never run a model.")
    parser.add_argument("--input", required=True, dest="input_file")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scale", required=True, dest="input_scale", choices=("raw_counts", "normalized", "log1p"))
    parser.add_argument("--species", required=True)
    parser.add_argument("--orientation", choices=("cells_by_genes", "genes_by_cells"))
    parser.add_argument("--counts-layer")
    parser.add_argument("--obs-metadata", help="CSV/TSV with exact cell_id column, all input cells once")
    parser.add_argument("--gene-metadata", help="CSV/TSV with exact gene_id column, optional gene_symbol annotation")
    parser.add_argument("--gene-id-kind", choices=("unknown", "gene_symbol", "ensembl", "other"), default="unknown")
    parser.add_argument("--target", dest="targets", action="append", help="Exact unique gene ID; repeat to check several targets")
    parser.add_argument("--source-note", help="User-supplied data origin/preprocessing statement; recorded, not certified")
    parser.add_argument("--max-input-mib", type=int, default=256)
    parser.add_argument("--max-matrix-mib", type=int, default=256)
    parser.add_argument("--max-expanded-mib", type=int, default=512)
    parser.add_argument("--celloracle-ko", action="store_true", help="Write a KO preflight request only if all explicit fields are present")
    parser.add_argument("--python-executable")
    parser.add_argument("--base-grn")
    args = parser.parse_args(argv)
    try:
        card = prepare(**vars(args))
        print(f"Prepared {card['shape'][0]} cells/samples × {card['shape'][1]} genes; model not run. Read {Path(args.output_dir) / 'report.md'}")
        return 0
    except Exception as exc:
        print(f"Input preparation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
