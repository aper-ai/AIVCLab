"""Small real input fixtures; no model dependencies, network, or subprocesses."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "preflight", Path(__file__).resolve().parents[1] / "scripts" / "preflight.py")
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.write("counts.csv", "gene_id,cell_1,cell_2\nSTAT3,1,0\nJUN,2,3\n")
        # This is deliberately only a readable file, not a certified GRN.
        self.write("prior.txt", "This fixture does not contain a fitted GRN.\n")
        self.request = {"schema_version": 1, "task": "ko", "backend": "CellOracle",
                        "input_file": "counts.csv", "input_scale": "raw_counts",
                        "matrix_orientation": "genes_by_cells", "species": "human",
                        "targets": ["STAT3"], "analysis_dir": "analysis",
                        "python_executable": sys.executable,
                        "resources": {"base_grn": "prior.txt"}}

    def write(self, name, text):
        path = self.base / name
        path.write_text(text, encoding="utf-8")
        return path

    def inspect(self, **changes):
        return preflight.run_preflight(dict(self.request, **changes), self.base)

    @staticmethod
    def codes(report, section):
        return {item["code"] for item in report[section]}

    def cli(self, output, request=None):
        source = self.write("request.json", json.dumps(self.request if request is None else request))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = preflight.main(["--request", str(source), "--output", str(output)])
        return code

    def test_good_csv_checks_all_values_but_does_not_certify_celloracle(self):
        report = self.inspect()
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["blockers"])
        self.assertEqual(report["matrix"]["values_checked"], "all_streamed")
        self.assertEqual(report["matrix"]["n_genes"], 2)
        self.assertEqual(report["matrix"]["targets_present"], ["STAT3"])
        self.assertIn("h5ad_conversion", self.codes(report, "not_checked"))
        self.assertIn("grn_compatibility", self.codes(report, "not_checked"))
        self.assertEqual(report["prediction_status"], "not_run")
        self.assertEqual(report["model_compatibility"], "not_verified")

    def test_cells_by_genes_tsv_uses_explicit_gene_axis(self):
        self.write("cells.tsv", "cell_id\tSTAT3\tJUN\ncell_1\t1\t2\ncell_2\t0\t3\n")
        report = self.inspect(input_file="cells.tsv", matrix_orientation="cells_by_genes")
        self.assertFalse(report["blockers"])
        self.assertEqual(report["matrix"]["n_cells_or_samples"], 2)
        self.assertEqual(self.inspect(matrix_orientation="unspecified")["status"], "blocked")

    def test_invalid_matrix_values_are_hard_blockers(self):
        for value in ("NaN", "Inf", "-1", "0.5", "", "text", "1e-999", "1e999"):
            with self.subTest(value=value):
                self.write("counts.csv", f"gene_id,cell_1\nSTAT3,{value}\n")
                report = self.inspect()
                self.assertEqual(report["status"], "blocked")
                self.assertIn("matrix_invalid", self.codes(report, "blockers"))

    def test_bad_table_structure_and_missing_target(self):
        cases = ["gene_id,cell_1,cell_1\nSTAT3,1,2\n",
                 "gene_id,cell_1\nSTAT3,1\nSTAT3,2\n",
                 "gene_id,cell_1\nSTAT3,1,2\n",
                 "gene_id,cell_1\nJUN,1\n",
                 "gene_id,cell_1\n,1\n",
                 "gene_id,cell_1\n",
                 ",cell_1\nSTAT3,1\n"]
        for content in cases:
            with self.subTest(content=content):
                self.write("counts.csv", content)
                self.assertEqual(self.inspect()["status"], "blocked")

    def test_required_choices_and_unknown_fields_are_rejected(self):
        self.assertEqual(preflight.run_preflight({}, self.base)["status"], "blocked")
        for changes in ({"task": "drug"}, {"backend": "unknown"}, {"download": True},
                        {"input_scale": "log1p"}, {"targets": []}, {"targets": ["STAT3", "STAT3"]},
                        {"species": []}, {"backend": {}}, {"task": []}, {"targets": [{}]},
                        {"resources": []}, {"schema_version": True}, {"intervention_mode": "maybe"},
                        {"scan_h5ad_values": "yes"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.inspect(**changes)["status"], "blocked")

    def test_missing_interpreter_is_unknown_and_nothing_is_executed(self):
        request = dict(self.request)
        del request["python_executable"]
        report = preflight.run_preflight(request, self.base)
        self.assertEqual(report["requested_python_status"], "unknown")
        self.assertIn("python_unknown", self.codes(report, "not_checked"))
        self.write("untrusted.py", f"from pathlib import Path\nPath({str(self.base / 'should_never_exist')!r}).touch()\n")
        report = self.inspect(python_executable="untrusted.py")
        self.assertEqual(report["requested_python_status"], "readable_path_only_not_executed")
        self.assertFalse((self.base / "should_never_exist").exists())

    def test_interpreter_symlink_preserves_absolute_and_relative_venv_launchers(self):
        launcher = self.base / "selected-env" / "bin" / "python"
        launcher.parent.mkdir(parents=True)
        try:
            launcher.symlink_to(Path(sys.executable).resolve())
        except (OSError, NotImplementedError):
            self.skipTest("This platform/account cannot create interpreter symlinks")
        for value in (str(launcher), "selected-env/bin/python"):
            with self.subTest(value=value):
                report = self.inspect(python_executable=value)
                recorded = report["files"]["python_executable"]
                self.assertEqual(recorded["path"], str(launcher.absolute()))
                self.assertNotEqual(recorded["path"], str(launcher.resolve()))
                self.assertEqual(recorded["path_semantics"], "invocation_path_preserved_not_executed")
                self.assertEqual(report["requested_python_status"], "readable_path_only_not_executed")

    def test_missing_and_empty_files_are_not_accepted(self):
        self.assertEqual(self.inspect(input_file="missing.csv")["status"], "blocked")
        self.write("empty.txt", "")
        self.assertEqual(self.inspect(resources={"base_grn": "empty.txt"})["status"], "blocked")
        report = self.inspect(resources={})
        self.assertIn("base_grn", self.codes(report, "not_checked"))
        self.assertEqual(report["status"], "incomplete")

    def test_multiple_targets_and_oe_need_explicit_choices(self):
        self.assertEqual(self.inspect(targets=["STAT3", "JUN"])["status"], "blocked")
        report = self.inspect(targets=["STAT3", "JUN"], intervention_mode="independent")
        self.assertFalse(report["blockers"])
        self.assertIn("joint_route", self.codes(self.inspect(intervention_mode="joint"), "not_checked"))
        for changes in ({}, {"oe_value": 0}, {"oe_percentile": 101},
                        {"oe_value": True}, {"oe_value": 10 ** 400},
                        {"oe_value": 2, "oe_percentile": 95}):
            with self.subTest(changes=changes):
                self.assertEqual(self.inspect(task="oe", **changes)["status"], "blocked")
        report = self.inspect(task="oe", oe_percentile=95)
        self.assertFalse(report["blockers"])
        self.assertIn("oe_range", self.codes(report, "not_checked"))

    def test_geneformer_does_not_accept_mouse_normalized_or_symbol_targets(self):
        self.write("counts.csv", "gene_id,cell_1\nENSG00000168610,1\n")
        request = dict(self.request, backend="Geneformer", targets=["ENSG00000168610"],
                       raw_full_transcriptome=True)
        good = preflight.run_preflight(request, self.base)
        self.assertFalse(good["blockers"])
        self.assertEqual(good["status"], "incomplete")
        for changes in ({"species": "mouse"}, {"input_scale": "normalized"},
                        {"raw_full_transcriptome": False}, {"targets": ["STAT3"]},
                        {"targets": ["ENSG00000168610.1"]}, {"counts_layer": "counts"}):
            with self.subTest(changes=changes):
                self.assertEqual(preflight.run_preflight(dict(request, **changes), self.base)["status"], "blocked")

    def test_missing_anndata_is_incomplete_not_compatible(self):
        self.write("cells.h5ad", "nonempty placeholder; no parser is available in this test")
        with patch.dict(sys.modules, {"anndata": None, "anndata.io": None}):
            report = self.inspect(input_file="cells.h5ad")
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("h5ad_dependency", self.codes(report, "not_checked"))
        self.assertNotIn("matrix", report)
        self.assertEqual(report["model_compatibility"], "not_verified")

    def test_real_h5ad_metadata_does_not_read_expression_values(self):
        try:
            import anndata
            from anndata.io import read_elem  # noqa: F401
            import h5py
            import numpy as np
        except ImportError:
            self.skipTest("optional anndata.io/h5py not installed; no dependency is installed by tests")
        data = anndata.AnnData(np.array([[1., 0.], [2., 3.]]))
        data.var_names = ["STAT3", "JUN"]
        data.layers["counts"] = data.X.copy()
        data.write_h5ad(self.base / "cells.h5ad")
        original = h5py.Dataset.__getitem__

        def guard(dataset, key):
            if dataset.name in ("/X", "/layers/counts"):
                raise AssertionError("metadata preflight must not load expression data")
            return original(dataset, key)

        with patch.object(h5py.Dataset, "__getitem__", guard):
            report = self.inspect(input_file="cells.h5ad", counts_layer="counts")
        self.assertFalse(report["blockers"])
        self.assertEqual(report["matrix"]["n_genes"], 2)
        self.assertEqual(report["matrix"]["values_checked"], "not_checked")
        self.assertEqual(report["status"], "incomplete")

    def test_unipert_rejects_user_baseline_and_keeps_drug_contract_unchecked(self):
        self.write("drugs.csv", "drug,smiles\ncompound_a,C\n")
        request = {"task": "drug", "backend": "UniPert-G2CP", "analysis_dir": "analysis",
                   "python_executable": sys.executable, "drug_library": "drugs.csv",
                   "baseline_source": "model_builtin", "cell_context": "A549"}
        report = preflight.run_preflight(request, self.base)
        self.assertFalse(report["blockers"])
        self.assertIn("drug_library_semantics", self.codes(report, "not_checked"))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(preflight.run_preflight(dict(request, input_file="counts.csv"), self.base)["status"], "blocked")

    def test_h5ad_numeric_scan_preserves_unverified_semantics(self):
        import anndata
        import numpy as np
        data = anndata.AnnData(np.array([[1., 0.], [2., 3.]]))
        data.var_names = ["STAT3", "JUN"]
        data.write_h5ad(self.base / "counts.h5ad")
        report = self.inspect(input_file="counts.h5ad", scan_h5ad_values=True)
        self.assertFalse(report["blockers"])
        self.assertEqual(report["matrix"]["values_checked"], "all_stored_values")
        self.assertEqual(report["matrix"]["numeric_check"]["noninteger_values"], 0)
        self.assertIn("h5ad_semantics", self.codes(report, "not_checked"))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["model_compatibility"], "not_verified")

    def test_layer_named_raw_count_does_not_override_fractional_values(self):
        import anndata
        import numpy as np
        data = anndata.AnnData(np.array([[1., 0.], [2., 3.]]))
        data.var_names = ["STAT3", "JUN"]
        data.layers["raw_count"] = np.array([[1.25, 0.], [2., 3.5]])
        data.write_h5ad(self.base / "processed.h5ad")
        report = self.inspect(input_file="processed.h5ad", counts_layer="raw_count", scan_h5ad_values=True)
        self.assertEqual(report["status"], "blocked")
        reason = next(item["message"] for item in report["blockers"] if item["code"] == "matrix_invalid")
        self.assertIn("2 noninteger", reason)
        self.assertEqual(report["prediction_status"], "not_run")

    def test_sparse_h5ad_scan_handles_implicit_zeros_and_nonfinite_values(self):
        import anndata
        import numpy as np
        from scipy import sparse
        for format_ in (sparse.csr_matrix, sparse.csc_matrix):
            with self.subTest(format=format_.__name__):
                data = anndata.AnnData(format_(np.array([[1., 0.], [0., 3.]])))
                data.var_names = ["STAT3", "JUN"]
                data.write_h5ad(self.base / "sparse.h5ad")
                report = self.inspect(input_file="sparse.h5ad", scan_h5ad_values=True)
                self.assertFalse(report["blockers"])
                self.assertEqual(report["matrix"]["numeric_check"]["stored_values_scanned"], 2)
                data.X.data[0] = np.nan
                data.write_h5ad(self.base / "sparse.h5ad")
                report = self.inspect(input_file="sparse.h5ad", scan_h5ad_values=True)
                self.assertEqual(report["status"], "blocked")
                self.assertIn("matrix_invalid", self.codes(report, "blockers"))

    def test_cli_paths_use_request_directory_and_do_not_create_analysis(self):
        output = self.base / "records" / "preflight.json"
        self.assertEqual(self.cli(output), 1)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["files"]["input_file"]["path"], str((self.base / "counts.csv").resolve()))
        self.assertEqual(report["analysis_dir"], str((self.base / "analysis").resolve()))
        self.assertFalse((self.base / "analysis").exists())
        self.assertEqual(report["prediction_status"], "not_run")

    def test_cli_cannot_overwrite_any_source_or_existing_report(self):
        self.write("drugs.csv", "drug\ncompound_a\n")
        self.write("signature.csv", "gene,delta\nSTAT3,1\n")
        request = dict(self.request, drug_library="drugs.csv", disease_signature="signature.csv")
        for name in ("request.json", "counts.csv", "prior.txt", "drugs.csv", "signature.csv"):
            with self.subTest(source=name):
                self.write("request.json", json.dumps(request))
                source = self.base / name
                before = source.read_bytes()
                self.assertEqual(self.cli(source, request), 2)
                self.assertEqual(source.read_bytes(), before)
        previous = self.write("previous.json", "previous run evidence")
        self.assertEqual(self.cli(previous), 2)
        self.assertEqual(previous.read_text(encoding="utf-8"), "previous run evidence")

    def test_output_links_cannot_overwrite_source(self):
        for hard in (False, True):
            linked = self.base / ("hardlink.json" if hard else "symlink.json")
            try:
                if hard:
                    linked.hardlink_to(self.base / "counts.csv")
                else:
                    linked.symlink_to(self.base / "counts.csv")
            except OSError:
                continue  # Some Windows accounts cannot create symlinks.
            before = (self.base / "counts.csv").read_bytes()
            self.assertEqual(self.cli(linked), 2)
            self.assertEqual((self.base / "counts.csv").read_bytes(), before)

    def test_malformed_and_nonfinite_json_emit_blocked_record(self):
        for index, content in enumerate(("{bad", "[]", '{"oe_value": NaN}', '{"oe_value": 1e999}',
                                         '{"task":"ko","task":"oe"}',
                                         '{"resources":{"base_grn":"a","base_grn":"b"}}',
                                         json.dumps(dict(self.request, task="oe", oe_value=10 ** 400)))):
            with self.subTest(content=content):
                source = self.write("request.json", content)
                output = self.base / f"bad_{index}.json"
                with contextlib.redirect_stdout(io.StringIO()):
                    code = preflight.main(["--request", str(source), "--output", str(output)])
                self.assertEqual(code, 2)
                report = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(report["status"], "blocked")

    def test_oversized_request_is_rejected_before_parsing(self):
        source = self.write("large_request.json", " " * (256 * 1024) + "{}")
        output = self.base / "large_record.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = preflight.main(["--request", str(source), "--output", str(output)])
        self.assertEqual(code, 2)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["blockers"][0]["code"], "request_invalid")
        self.assertIn("256 KiB", report["blockers"][0]["message"])


if __name__ == "__main__":
    unittest.main()
