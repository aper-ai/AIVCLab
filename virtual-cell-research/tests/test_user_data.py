"""User-input contracts with synthetic data; not scientific validation."""
from pathlib import Path
import gzip
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest

import anndata as ad
import h5py
import numpy as np
import pandas as pd
from scipy import sparse

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_user_data", ROOT / "scripts/prepare_user_data.py")
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)
PREFLIGHT_SPEC = importlib.util.spec_from_file_location("user_preflight", ROOT / "scripts/preflight.py")
PREFLIGHT = importlib.util.module_from_spec(PREFLIGHT_SPEC); PREFLIGHT_SPEC.loader.exec_module(PREFLIGHT)


class UserDataContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "counts.csv"
        self.source.write_text("cell_id,G1,G2\n001,1,0\n002,2,3\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, name="output", source=None, **kwargs):
        options = {"input_scale": "raw_counts", "species": "human", "orientation": "cells_by_genes"}
        options.update(kwargs)
        return MODULE.prepare(source or self.source, self.root / name, **options)

    def read(self, name="output"):
        return ad.read_h5ad(self.root / name / "prepared_input.h5ad")

    def test_cells_by_genes_and_metadata_reorder_keep_identity_and_values(self):
        obs = self.root / "cells.tsv"
        obs.write_text("cell_id\tdonor\tcell_type\n002\tD2\tNA\n001\tD1\t单核细胞\n", encoding="utf-8")
        genes = self.root / "genes.csv"
        genes.write_text("gene_id,gene_symbol\nG2,Shared\nG1,Shared\n", encoding="utf-8")
        card = self.prepare(obs_metadata=obs, gene_metadata=genes, targets=["G1"])
        data = self.read()
        np.testing.assert_array_equal(data.X, [[1, 0], [2, 3]])
        self.assertEqual(data.obs_names.tolist(), ["001", "002"])
        self.assertEqual(data.obs.donor.tolist(), ["D1", "D2"])
        self.assertEqual(data.obs.cell_type.tolist(), ["单核细胞", "NA"])
        self.assertEqual(data.var.gene_symbol.tolist(), ["Shared", "Shared"])
        self.assertEqual(card["status"], "prepared_not_model_ready")
        self.assertFalse(card["declarations_verified"])
        self.assertIn("没有运行模型", (self.root / "output/report.md").read_text(encoding="utf-8"))

    def test_gzip_genes_by_cells_transpose_and_float_scale(self):
        source = self.root / "expression.tsv.gz"
        with gzip.open(source, "wt", encoding="utf-8") as handle:
            handle.write("gene_id\tc02\tc01\nG2\t1.25\t0\nG1\t2.5\t3.125\n")
        self.prepare(source=source, orientation="genes_by_cells", input_scale="log1p")
        data = self.read()
        self.assertEqual(data.obs_names.tolist(), ["c02", "c01"])
        self.assertEqual(data.var_names.tolist(), ["G2", "G1"])
        np.testing.assert_array_equal(data.X, [[1.25, 2.5], [0, 3.125]])
        self.assertEqual(data.X.dtype, np.dtype("float64"))

    def test_raw_table_keeps_large_exact_int64_and_rejects_decimal_rounding(self):
        self.source.write_text("cell_id,G1\nc,9007199254740993\n", encoding="utf-8")
        self.prepare()
        self.assertEqual(int(self.read().X[0, 0]), 9007199254740993)
        self.source.write_text("cell_id,G1\nc,1.00000000000000000001\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "invalid value"):
            self.prepare("fractional")

    def test_h5ad_selected_sparse_layer_and_annotations_are_exact(self):
        source = self.root / "layer.h5ad"
        counts = sparse.csc_matrix(np.array([[1, 0, 2], [0, 3, 0]], dtype=np.int32))
        data = ad.AnnData(X=np.full((2, 3), 0.5, dtype=np.float32),
                          obs=pd.DataFrame({"donor": ["A", "B"]}, index=["cell2", "cell1"]),
                          var=pd.DataFrame({"symbol": ["A", "B", "C"]}, index=["g3", "g2", "g1"]))
        data.layers["counts"] = counts
        data.obsm["X_umap"] = np.ones((2, 2)); data.uns["note"] = "source-only metadata"
        data.write_h5ad(source)
        source_hash = MODULE.sha256(source)
        card = self.prepare(source=source, orientation=None, counts_layer="counts")
        actual = self.read()
        self.assertTrue(sparse.isspmatrix_csc(actual.X))
        self.assertEqual(actual.X.dtype, counts.dtype)
        np.testing.assert_array_equal(actual.X.data, counts.data)
        np.testing.assert_array_equal(actual.X.indices, counts.indices)
        np.testing.assert_array_equal(actual.X.indptr, counts.indptr)
        self.assertEqual(actual.obs_names.tolist(), data.obs_names.tolist())
        self.assertEqual(actual.var_names.tolist(), data.var_names.tolist())
        pd.testing.assert_frame_equal(actual.obs, ad.read_h5ad(source).obs)
        pd.testing.assert_frame_equal(actual.var, ad.read_h5ad(source).var)
        # AnnData releases that expose X as layers[None] may include that alias;
        # no additional source layer is copied.
        self.assertEqual([key for key in actual.layers if key is not None], [])
        self.assertIn("obsm", card["omitted_h5ad_components"])
        self.assertEqual(MODULE.sha256(source), source_hash)

    def test_sparse_noncanonical_coordinates_are_not_summed_silently(self):
        source = self.root / "duplicate.h5ad"
        matrix = sparse.csr_matrix((np.array([1, 2]), np.array([0, 0]), np.array([0, 2])), shape=(1, 2))
        ad.AnnData(matrix, obs=pd.DataFrame(index=["c"]), var=pd.DataFrame(index=["a", "b"])).write_h5ad(source)
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.prepare(source=source, orientation=None)

    def test_h5ad_external_links_and_fractional_sparse_indices_fail(self):
        external = self.root / "outside.h5"
        with h5py.File(external, "w") as handle:
            handle.create_dataset("matrix", data=np.ones((2, 2)))
        source = self.root / "linked.h5ad"
        ad.AnnData(np.ones((2, 2))).write_h5ad(source)
        with h5py.File(source, "a") as handle:
            del handle["X"]
            handle["X"] = h5py.ExternalLink(str(external), "matrix")
        with self.assertRaisesRegex(ValueError, "external or soft"):
            self.prepare("linked", source=source, orientation=None)
        source = self.root / "indices.h5ad"
        ad.AnnData(sparse.csr_matrix([[1, 0], [0, 2]])).write_h5ad(source)
        with h5py.File(source, "a") as handle:
            del handle["X/indices"]
            handle["X"].create_dataset("indices", data=[0.25, 1.0])
        with self.assertRaisesRegex(ValueError, "integer arrays"):
            self.prepare("indices", source=source, orientation=None)
        source = self.root / "unused-data.h5ad"
        ad.AnnData(sparse.csr_matrix([[1, 0], [0, 2]])).write_h5ad(source)
        with h5py.File(source, "a") as handle:
            handle["X/indptr"][-1] = 1
        with self.assertRaisesRegex(ValueError, "cover all stored values"):
            self.prepare("unused-data", source=source, orientation=None)

    def test_invalid_values_are_not_filled_or_rounded(self):
        for index, value in enumerate(("", "NA", "NaN", "inf", "-1", "0.2", "9223372036854775808")):
            with self.subTest(value=value):
                self.source.write_text(f"cell_id,G1,G2\nc,1,{value}\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.prepare(str(index))
                error = json.loads((self.root / str(index) / "error.json").read_text(encoding="utf-8"))
                self.assertEqual(error["model_status"], "not_run")
                self.assertFalse((self.root / str(index) / "prepared_input.h5ad").exists())

    def test_duplicate_blank_and_whitespace_ids_fail(self):
        bad = ["cell_id,G1,G1\nc,1,2\n", "cell_id,G1\nc,1\nc,2\n",
               "cell_id,G1\n,1\n", "cell_id,G1\n c,1\n", "cell_id, G1\nc,1\n"]
        for index, text in enumerate(bad):
            self.source.write_text(text, encoding="utf-8")
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.prepare(str(index))

    def test_metadata_id_sets_and_existing_columns_are_not_overwritten(self):
        obs = self.root / "obs.csv"
        for index, rows in enumerate(("001,A\nunknown,B\n", "001,A\n001,B\n", "001,A\n", "001,A\n002,B\nextra,C\n")):
            obs.write_text("cell_id,donor\n" + rows, encoding="utf-8")
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.prepare(str(index), obs_metadata=obs)
        source = self.root / "existing.h5ad"
        ad.AnnData(np.ones((2, 2)), obs=pd.DataFrame({"donor": ["X", "Y"]}, index=["001", "002"]), var=pd.DataFrame(index=["G1", "G2"])).write_h5ad(source)
        obs.write_text("cell_id,donor\n001,A\n002,B\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.prepare("collision", source=source, orientation=None, obs_metadata=obs)

    def test_gene_symbols_never_replace_unique_target_ids(self):
        genes = self.root / "genes.csv"
        genes.write_text("gene_id,gene_symbol\nG1,Shared\nG2,Shared\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "absent"):
            self.prepare(gene_metadata=genes, targets=["Shared"])

    def test_h5ad_axis_and_layer_declarations_are_explicit(self):
        source = self.root / "dense.h5ad"
        ad.AnnData(np.array([[1.5, 0], [0, 2.5]], dtype=np.float32), obs=pd.DataFrame(index=["c1", "c2"]), var=pd.DataFrame(index=["g1", "g2"])).write_h5ad(source)
        with self.assertRaisesRegex(ValueError, "omit --orientation"):
            self.prepare("orientation", source=source)
        with self.assertRaisesRegex(ValueError, "selected expression"):
            self.prepare("layer", source=source, orientation=None, counts_layer="missing")
        with self.assertRaisesRegex(ValueError, "noninteger"):
            self.prepare("raw", source=source, orientation=None)
        self.prepare("normalized", source=source, orientation=None, input_scale="normalized")
        np.testing.assert_array_equal(self.read("normalized").X, [[1.5, 0], [0, 2.5]])
        self.assertEqual(self.read("normalized").X.dtype, np.dtype("float32"))

    def test_matrix_limit_applies_before_loading_compressed_dense_h5ad(self):
        source = self.root / "large.h5ad"
        ad.AnnData(np.zeros((500, 500), dtype=np.float64)).write_h5ad(source, compression="gzip")
        self.assertLess(source.stat().st_size, MODULE.MIB)
        with self.assertRaisesRegex(ValueError, "memory limit"):
            self.prepare(source=source, orientation=None, max_matrix_mib=1)

    def test_table_dense_and_expansion_limits_fail_without_partial_matrix(self):
        source = self.root / "dense.csv"
        source.write_text("cell_id," + ",".join(f"g{i}" for i in range(400)) + "\n" +
                          "".join(f"c{row}," + ",".join(["0"] * 400) + "\n" for row in range(400)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "memory limit"):
            self.prepare("dense", source=source, max_matrix_mib=1)
        source = self.root / "expanded.tsv.gz"
        with gzip.open(source, "wt", encoding="utf-8") as handle:
            handle.write("cell_id\tG1\n")
            for i in range(70000):
                handle.write(f"long_cell_{i:08d}\t1\n")
        with self.assertRaisesRegex(ValueError, "Expanded table"):
            self.prepare("expanded", source=source, max_expanded_mib=1)

    def test_existing_output_and_sources_survive_success_and_failure(self):
        before = MODULE.sha256(self.source)
        self.prepare()
        prepared_hash = MODULE.sha256(self.root / "output/prepared_input.h5ad")
        with self.assertRaises(FileExistsError):
            self.prepare()
        self.assertEqual(MODULE.sha256(self.root / "output/prepared_input.h5ad"), prepared_hash)
        self.assertEqual(MODULE.sha256(self.source), before)
        with self.assertRaisesRegex(ValueError, "orientation"):
            self.prepare("failure", orientation=None)
        self.assertEqual(MODULE.sha256(self.source), before)

    def test_complete_celloracle_request_is_compatible_but_not_model_ready(self):
        self.source.write_text("cell_id,G1,G2,G3,G4\n" + "".join(f"c{i},1,2,3,4\n" for i in range(4)), encoding="utf-8")
        prior = self.root / "prior.parquet"
        prior.write_bytes(b"Synthetic readable prior placeholder; not a real model resource")
        card = self.prepare(celloracle_ko=True, gene_id_kind="gene_symbol", targets=["G1"], python_executable=sys.executable, base_grn=prior)
        self.assertEqual(card["celloracle_ko_request"]["status"], "request_written")
        request = json.loads((self.root / "output/preflight_request.json").read_text(encoding="utf-8"))
        checked = PREFLIGHT.run_preflight(request, self.root / "output")
        self.assertEqual(checked["blockers"], [])
        self.assertEqual(checked["prediction_status"], "not_run")
        self.assertEqual(checked["model_compatibility"], "not_verified")
        self.assertFalse((self.root / "output/analysis").exists())

    def test_incomplete_ko_request_preserves_data_and_explains_missing_fields(self):
        card = self.prepare(celloracle_ko=True)
        self.assertEqual(card["celloracle_ko_request"]["status"], "incomplete")
        self.assertIn("python_executable", " ".join(card["celloracle_ko_request"]["missing"]))
        self.assertFalse((self.root / "output/preflight_request.json").exists())
        self.assertTrue((self.root / "output/prepared_input.h5ad").is_file())

    def test_virtual_environment_interpreter_entry_is_not_dereferenced(self):
        self.source.write_text("cell_id,G1,G2,G3,G4\n" + "".join(f"c{i},1,2,3,4\n" for i in range(4)), encoding="utf-8")
        entry = self.root / "venv" / "bin" / "python"
        entry.parent.mkdir(parents=True)
        try:
            entry.symlink_to(Path(sys.executable).resolve())
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Creating an interpreter symlink is unavailable: {exc}")
        self.assertNotEqual(str(entry.absolute()), str(entry.resolve()))
        prior = self.root / "prior.parquet"
        prior.write_bytes(b"Readable fixture only; not a scientific prior")
        card = self.prepare(celloracle_ko=True, gene_id_kind="gene_symbol", targets=["G1"], python_executable=entry, base_grn=prior)
        request = json.loads((self.root / "output/preflight_request.json").read_text(encoding="utf-8"))
        self.assertEqual(request["python_executable"], str(entry.absolute()))
        interpreter = card["celloracle_ko_request"]["resources"]["python_executable"]
        self.assertEqual(interpreter["path"], str(entry.absolute()))
        self.assertEqual(interpreter["sha256"], MODULE.sha256(entry.resolve()))

    def test_source_and_output_hashes_match_actual_bytes(self):
        self.prepare()
        record = json.loads((self.root / "output/provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(record["sources"]["expression"]["sha256"], MODULE.sha256(self.source))
        for path, digest in record["outputs_sha256"].items():
            self.assertEqual(MODULE.sha256(self.root / "output" / path), digest)

    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts/prepare_user_data.py"), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--counts-layer", result.stdout)


if __name__ == "__main__":
    unittest.main()
