"""Read-only input preflight. Never install dependencies or execute a model/interpreter.

Relative request paths are resolved against the request JSON's directory. A ready
result covers only this tool's checks, never backend compatibility or prediction.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import re
import sys

BACKENDS = {"CellOracle": {"ko", "oe"}, "Geneformer": {"ko", "oe"},
            "GEARS": {"ko", "oe"}, "PRnet": {"drug"}, "chemCPA": {"drug"},
            "UniPert-G2CP": {"drug"}, "UniCure": {"drug"}, "DrugReflector": {"drug"}}
FIELDS = set("schema_version task backend input_file input_scale species targets analysis_dir "
             "python_executable resources drug_library disease_signature matrix_orientation "
             "counts_layer intervention_mode oe_value oe_percentile raw_full_transcriptome "
             "baseline_source cell_context scan_h5ad_values".split())
ENSG = re.compile(r"ENSG\d{11}\Z")


def issue(report, group, code, message, required=False):
    entry = {"code": code, "message": message}
    if group == "not_checked":
        entry["required_for_preflight"] = required
    report[group].append(entry)


def local_path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("must be a nonempty local path string")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def readable_file(value, label, base, report):
    try:
        path = local_path(value, base)
        if not path.is_file():
            raise ValueError("must name an existing regular file")
        with path.open("rb") as handle:
            if not handle.read(1):
                raise ValueError("file is empty")
        report["files"][label] = {"path": str(path), "bytes": path.stat().st_size}
        return path
    except (OSError, ValueError, RuntimeError) as exc:
        issue(report, "blockers", "file_unreadable", f"{label}: {exc}")
        return None


def table_metadata(path, request=None):
    """Stream records; retain identifiers only, never the complete value matrix."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle, delimiter="\t" if path.suffix.lower() == ".tsv" else ",", strict=True)
        header = next(rows, [])
        if not header or any(not s.strip() for s in header) or len(header) != len(set(header)):
            raise ValueError("table needs nonempty, unique column headers (including the ID column)")
        if request and len(header) < 2:
            raise ValueError("expression table needs an ID column and at least one value column")
        ids, count = set(), 0
        for count, row in enumerate(rows, 1):
            if len(row) != len(header):
                raise ValueError(f"record {count + 1}: column count differs from header")
            if not request:
                continue
            if not row[0].strip() or row[0] in ids:
                raise ValueError(f"record {count + 1}: blank or duplicate row ID")
            ids.add(row[0])
            for column, value in enumerate(row[1:], 2):
                try:
                    number = float(value)
                    valid = math.isfinite(number)
                    if request["input_scale"] == "raw_counts":
                        exact = Decimal(value)
                        valid = valid and exact >= 0 and exact == exact.to_integral_value()
                except (ValueError, InvalidOperation):
                    valid = False
                if not valid:
                    raise ValueError(f"record {count + 1}, column {column}: missing/nonfinite/nonnumeric value or invalid raw count")
        if count == 0:
            raise ValueError("table has no data records")
    meta = {"rows": count, "columns": header}
    if request:
        genes_rows = request["matrix_orientation"] == "genes_by_cells"
        genes = ids if genes_rows else set(header[1:])
        missing = set(request.get("targets", [])) - genes
        if missing:
            raise ValueError(f"targets absent from declared gene axis: {sorted(missing)}")
        meta = {"n_genes": len(genes), "n_cells_or_samples": len(header) - 1 if genes_rows else count,
                "matrix_orientation": request["matrix_orientation"], "values_checked": "all_streamed",
                "targets_present": request.get("targets", [])}
    return meta


def scan_h5ad_values(node):
    """Scan stored values in bounded blocks; do not densify sparse matrices."""
    import h5py
    import numpy as np
    if isinstance(node, h5py.Dataset):
        if node.ndim != 2:
            raise ValueError("expression dataset must have two dimensions")
        values, shape = node, tuple(node.shape)
        block = max(1, 1_000_000 // max(1, shape[1]))
    else:
        encoding = node.attrs.get("encoding-type", "")
        if isinstance(encoding, bytes):
            encoding = encoding.decode("ascii")
        if encoding not in ("csr_matrix", "csc_matrix") or "data" not in node:
            raise ValueError("numeric scan supports dense, CSR and CSC expression encodings")
        values, shape = node["data"], tuple(node.attrs.get("shape", ()))
        if values.ndim != 1 or len(shape) != 2:
            raise ValueError("invalid sparse expression value shape")
        block = 1_000_000
    if values.dtype.kind not in "biuf":
        raise ValueError("expression values must be real numeric values")
    count = nonfinite = negative = fractional = 0
    minimum = maximum = None
    for start in range(0, values.shape[0], block):
        chunk = np.asarray(values[start:start + block])
        finite = np.isfinite(chunk)
        count += int(chunk.size)
        nonfinite += int((~finite).sum())
        valid = chunk[finite]
        if valid.size:
            negative += int((valid < 0).sum())
            fractional += int((valid != np.floor(valid)).sum())
            low, high = float(valid.min()), float(valid.max())
            minimum = low if minimum is None else min(minimum, low)
            maximum = high if maximum is None else max(maximum, high)
    return {"stored_values_scanned": count, "nonfinite_values": nonfinite,
            "negative_values": negative, "noninteger_values": fractional,
            "minimum_stored_value": minimum, "maximum_stored_value": maximum,
            "scope": "all stored numeric values; implicit sparse zeros are valid counts; sparse indices are not structurally audited"}


def h5ad_metadata(path, request):
    # Read only obs/var and matrix shape. read_h5ad(backed='r') can still load
    # layers eagerly; read_elem avoids loading X, layers, raw, or embeddings.
    try:
        from anndata.io import read_elem
        import h5py
    except Exception as exc:
        raise ImportError(f"optional metadata reader unavailable: {exc}") from exc

    with h5py.File(path, "r") as handle:
        obs, var = read_elem(handle["obs"]), read_elem(handle["var"])
        node = handle["layers"][request["counts_layer"]] if request.get("counts_layer") else handle["X"]
        shape = node.shape if isinstance(node, h5py.Dataset) else node.attrs.get("shape", ())
        if tuple(shape) != (len(obs), len(var)) or not len(obs) or not len(var):
            raise ValueError("expression shape must match nonempty obs/var metadata")
        for axis in (obs.index, var.index):
            if not axis.is_unique or axis.hasnans or any(not str(x).strip() for x in axis):
                raise ValueError("obs/var IDs must be nonempty and unique")
        genes = list(var.index)
        if request["backend"] == "Geneformer":
            if "ensembl_id" not in var or "n_counts" not in obs:
                raise ValueError("Geneformer requires var.ensembl_id and obs.n_counts")
            genes = list(var["ensembl_id"])
            if any(not isinstance(g, str) or not ENSG.fullmatch(g) for g in genes) or len(set(genes)) != len(genes):
                raise ValueError("Geneformer needs unique, versionless human ENSG IDs")
            if any(not math.isfinite(float(n)) or float(n) <= 0 for n in obs["n_counts"]):
                raise ValueError("Geneformer obs.n_counts must contain positive finite totals")
        if request["backend"] == "GEARS" and not {"condition", "cell_type"}.issubset(obs.columns):
            raise ValueError("GEARS needs obs.condition and obs.cell_type")
        missing = set(request.get("targets", [])) - set(genes)
        if missing:
            raise ValueError(f"targets absent from gene metadata: {sorted(missing)}")
        metadata = {"n_genes": len(var), "n_cells_or_samples": len(obs), "values_checked": "not_checked",
                    "expression_location": f"layers/{request['counts_layer']}" if request.get("counts_layer") else "X",
                    "targets_present": request.get("targets", [])}
        if request.get("scan_h5ad_values"):
            qc = scan_h5ad_values(node)
            metadata.update(values_checked="all_stored_values", numeric_check=qc)
            if qc["nonfinite_values"]:
                raise ValueError(f"expression contains {qc['nonfinite_values']} nonfinite stored values")
            if request["input_scale"] == "raw_counts" and (qc["negative_values"] or qc["noninteger_values"]):
                raise ValueError("raw_counts requires nonnegative integer values; "
                                 f"found {qc['negative_values']} negative and {qc['noninteger_values']} noninteger stored values; "
                                 "a layer name does not establish the data scale")
        return metadata


def run_preflight(request, base_dir):
    report = {"schema_version": 1, "status": "blocked", "prediction_status": "not_run",
              "model_compatibility": "not_verified", "blockers": [], "warnings": [],
              "not_checked": [], "files": {}, "checker_python": sys.executable,
              "requested_python_status": "unknown"}
    add = lambda group, code, message, required=False: issue(report, group, code, message, required)
    if not isinstance(request, dict):
        add("blockers", "request_type", "request must be a JSON object")
        return report
    report["request"] = request
    if set(request) - FIELDS:
        add("blockers", "unknown_fields", f"unsupported fields: {sorted(set(request) - FIELDS)}")
    if type(request.get("schema_version", 1)) is not int or request.get("schema_version", 1) != 1:
        add("blockers", "schema_version", "schema_version must be 1")
    task, backend = request.get("task"), request.get("backend")
    if not isinstance(backend, str) or backend not in BACKENDS or task not in ("ko", "oe", "drug") or task not in BACKENDS[backend]:
        add("blockers", "route", "choose an exact supported backend name and a compatible ko/oe/drug task")
    for name in ("input_scale", "species", "matrix_orientation", "counts_layer", "intervention_mode", "baseline_source", "cell_context"):
        if name in request and (not isinstance(request[name], str) or not request[name].strip()):
            add("blockers", "field_type", f"{name} must be a nonempty string")
    if "raw_full_transcriptome" in request and type(request["raw_full_transcriptome"]) is not bool:
        add("blockers", "field_type", "raw_full_transcriptome must be a boolean")
    if "scan_h5ad_values" in request and type(request["scan_h5ad_values"]) is not bool:
        add("blockers", "field_type", "scan_h5ad_values must be a boolean")
    if "intervention_mode" in request and request["intervention_mode"] not in ("independent", "joint"):
        add("blockers", "intervention_mode", "intervention_mode must be independent or joint")
    targets = request.get("targets", [])
    if not isinstance(targets, list) or any(not isinstance(t, str) or not t.strip() for t in targets):
        add("blockers", "targets", "targets must be an array of nonempty gene IDs")
    elif len(targets) != len(set(targets)) or (task in ("ko", "oe") and not targets):
        add("blockers", "targets", "KO/OE needs nonempty, unique targets")
    elif len(targets) > 1 and request.get("intervention_mode") not in ("independent", "joint"):
        add("blockers", "intervention_mode", "multiple targets require independent or joint")
    if request.get("intervention_mode") == "joint":
        add("not_checked", "joint_route", "joint perturbation support/training and the execution entry point remain unverified", True)
    resources = request.get("resources", {})
    if not isinstance(resources, dict):
        add("blockers", "resources", "resources must map resource names to explicit local file paths")
        resources = {}
    for name, value in resources.items():
        readable_file(value, f"resources.{name}", base_dir, report)
    try:
        directory = local_path(request.get("analysis_dir"), base_dir)
        parent = next((p for p in [directory, *directory.parents] if p.exists()), directory)
        if not parent.is_dir():
            raise ValueError("analysis_dir or its existing parent is not a directory")
        report["analysis_dir"] = str(directory)
        if not os.access(parent, os.W_OK):
            add("warnings", "directory_access", "parent is not reported writable; no write probe was performed")
    except (OSError, ValueError, RuntimeError) as exc:
        add("blockers", "analysis_dir", str(exc))
    if "python_executable" not in request:
        add("not_checked", "python_unknown", f"select an interpreter; checker uses {sys.executable}, which is not a compatibility recommendation", True)
    elif readable_file(request["python_executable"], "python_executable", base_dir, report):
        report["requested_python_status"] = "readable_path_only_not_executed"
    if backend == "UniPert-G2CP":
        if "input_file" in request or request.get("baseline_source") != "model_builtin" or not request.get("cell_context"):
            add("blockers", "fixed_baseline", "UniPert-G2CP needs baseline_source=model_builtin and cell_context; input_file is unsupported")
    elif backend == "DrugReflector":
        if "input_file" in request or "disease_signature" not in request:
            add("blockers", "signature_route", "DrugReflector uses disease_signature, not an expression input_file")
        add("not_checked", "v_score", "directed v-score construction and checkpoint native compound classes need route-specific validation", True)
    else:
        if request.get("input_scale") not in ("raw_counts", "normalized", "log1p") or not request.get("species"):
            add("blockers", "expression_declarations", "declare input_scale=raw_counts|normalized|log1p and species")
        readable_file(request.get("input_file"), "input_file", base_dir, report)
    if backend in ("CellOracle", "Geneformer") and request.get("input_scale") != "raw_counts":
        add("blockers", "raw_counts_required", f"the {backend} example requires raw_counts")
    if backend == "CellOracle":
        if "base_grn" not in resources:
            add("not_checked", "base_grn", "configure resources.base_grn before the CellOracle route; nothing is downloaded", True)
        add("not_checked", "grn_compatibility", "GRN species/symbol overlap, target TF inclusion and fitting are not checked")
    if backend == "Geneformer":
        if str(request.get("species", "")).lower() not in ("human", "homo sapiens", "homo_sapiens", "9606") or request.get("raw_full_transcriptome") is not True:
            add("blockers", "geneformer_counts", "declare human species and raw_full_transcriptome=true for the current Geneformer example")
        if request.get("counts_layer"):
            add("blockers", "geneformer_layer", "the current Geneformer example reads raw counts from X, not counts_layer")
        if isinstance(targets, list) and any(not isinstance(t, str) or not ENSG.fullmatch(t) for t in targets):
            add("blockers", "geneformer_targets", "Geneformer targets must be versionless human ENSG IDs")
    settings = [k for k in ("oe_value", "oe_percentile") if k in request]
    if settings or (backend == "CellOracle" and task == "oe"):
        if backend != "CellOracle" or task != "oe" or len(settings) != 1:
            add("blockers", "oe_setting", "CellOracle OE requires exactly one of oe_value and oe_percentile; other routes do not use these settings")
        for key in settings:
            value = request[key]
            if type(value) not in (int, float) or not 0 < value <= sys.float_info.max or (key == "oe_percentile" and value > 100):
                add("blockers", "oe_setting", f"{key} must be finite and >0; percentile must also be <=100")
        add("not_checked", "oe_range", "the selected value's imputed_count scale and data range must be checked after preprocessing")
    if backend in ("GEARS", "UniCure"):
        add("not_checked", "backend_contract", "matched training data/perturbation semantics or checkpoint-specific embeddings require route-specific validation", True)
    if task == "drug" and "drug_library" not in request:
        add("blockers", "drug_library", "drug task requires an explicitly selected drug_library file")
    for name in ("drug_library", "disease_signature"):
        if name in request:
            path = readable_file(request[name], name, base_dir, report)
            if path and path.suffix.lower() in (".csv", ".tsv"):
                try:
                    report[name] = table_metadata(path)
                except (OSError, UnicodeError, csv.Error, ValueError) as exc:
                    add("blockers", "table_invalid", f"{name}: {exc}")
            add("not_checked", f"{name}_semantics", "column meanings, biological IDs, encoding coverage, units and gene/scale alignment are not validated", True)
    path_info = report["files"].get("input_file")
    if path_info and not report["blockers"]:
        path = Path(path_info["path"])
        try:
            if path.suffix.lower() in (".csv", ".tsv"):
                if request.get("matrix_orientation") not in ("genes_by_cells", "cells_by_genes"):
                    raise ValueError("CSV/TSV requires matrix_orientation=genes_by_cells|cells_by_genes; first column is the row ID")
                if request.get("counts_layer"):
                    raise ValueError("counts_layer is only applicable to h5ad")
                report["matrix"] = table_metadata(path, request)
                if backend in ("CellOracle", "Geneformer", "GEARS"):
                    add("not_checked", "h5ad_conversion", "current route needs h5ad metadata; this tool has not converted the table", True)
            elif path.suffix.lower() == ".h5ad":
                report["matrix"] = h5ad_metadata(path, request)
                if request.get("scan_h5ad_values"):
                    add("not_checked", "h5ad_semantics", "numeric values were scanned; sparse-index integrity, original-count provenance and n_counts agreement remain unverified", True)
                else:
                    add("not_checked", "h5ad_values", "only metadata and shape were read; set scan_h5ad_values=true for bounded numeric scanning; n_counts agreement remains unverified", True)
            else:
                add("not_checked", "input_format", "only CSV/TSV and h5ad metadata inspection are implemented", True)
        except ImportError as exc:
            add("not_checked", "h5ad_dependency", f"metadata inspection needs working anndata.io.read_elem and h5py in the checker environment: {exc}", True)
        except (OSError, UnicodeError, csv.Error, ValueError, KeyError, TypeError) as exc:
            add("blockers", "matrix_invalid", str(exc))
    add("warnings", "declared_scale", "species, input_scale and full-transcriptome status are declarations; numeric checks cannot prove preprocessing or biological context")
    add("not_checked", "model_execution", "interpreter execution, dependencies, CUDA, weights/tokenizer versions, model gene order, prediction and scientific validation were not checked")
    report["status"] = "blocked" if report["blockers"] else ("incomplete" if any(i["required_for_preflight"] for i in report["not_checked"]) else "preflight_ready")
    return report


def json_number(text):
    number = float(text)
    if not math.isfinite(number):
        raise ValueError("request JSON must not contain NaN, Infinity, or overflowing numbers")
    return number


def json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    request_path = args.request.expanduser().absolute()
    try:
        request_path = request_path.resolve()
        with request_path.open("rb") as handle:
            raw = handle.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("request JSON exceeds 256 KiB; reference matrix paths instead of embedding data")
        request = json.loads(raw.decode("utf-8-sig"), parse_constant=json_number,
                             parse_float=json_number, object_pairs_hook=json_object)
        report = run_preflight(request, request_path.parent)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        request = {}
        report = run_preflight({}, request_path.parent)
        report["blockers"] = []
        issue(report, "blockers", "request_invalid", str(exc))
    # Protect every source even when its content failed preflight. Exclusive
    # creation also refuses existing reports, symlinks, and hard-linked inputs.
    protected = [request_path]
    if isinstance(request, dict):
        resources = request.get("resources", {})
        values = [request.get(k) for k in ("input_file", "drug_library", "disease_signature", "python_executable")]
        values += list(resources.values()) if isinstance(resources, dict) else []
        for value in values:
            try:
                protected.append(local_path(value, request_path.parent))
            except (OSError, ValueError, RuntimeError):
                pass
    try:
        if args.output.expanduser().is_symlink():
            raise ValueError("--output cannot be a symbolic link")
        output = args.output.expanduser().resolve()
        if output in protected:
            raise ValueError("--output cannot overwrite a request, input, interpreter, or resource file")
        content = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Cannot write preflight record: {exc}", file=sys.stderr)
        return 2
    print(f"{report['status']}: {output} (prediction not run; backend compatibility not verified)")
    return {"preflight_ready": 0, "incomplete": 1, "blocked": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
