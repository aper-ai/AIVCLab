"""Synthetic source-format fixtures: never experimental or model evidence."""
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import sparse


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/observed_kang_case.py"
SPEC = importlib.util.spec_from_file_location("observed_kang_case", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture(root):
    """Two donors, a cross-sample barcode collision, a doublet, duplicate symbols."""
    ctrl = np.array([[2, 1, 10, 9], [0, 1, 0, 9], [2, 2, 0, 9]], dtype=np.int64)
    stim = np.array([[4, 0, 0], [0, 4, 10], [4, 4, 0]], dtype=np.int64)
    texts = {
        "genes": "ENSG1\tSAME\nENSG2\tSAME\nENSG3\tOTHER\n",
        "control_barcodes": "AAAA-1\nCCCC-1\nGGGG-1\nTTTT-1\n",
        "stimulated_barcodes": "AAAA-1\nACAC-1\nCACA-1\n",
        "metadata": "\t".join(module.SOURCE_HEADER) + "\n" + "\n".join([
            "AAAA-1\t0\t0\tD1\tctrl\t1\tCD14+ Monocytes\tsinglet",
            "CCCC-1\t0\t0\tD1\tctrl\t1\tCD14+ Monocytes\tsinglet",
            "GGGG-1\t0\t0\tD2\tctrl\t1\tCD14+ Monocytes\tsinglet",
            "TTTT-1\t0\t0\tD2\tctrl\t1\tCD14+ Monocytes\tdoublet",
            "AAAA-11\t0\t0\tD1\tstim\t1\tCD14+ Monocytes\tsinglet",
            "ACAC-1\t0\t0\tD1\tstim\t1\tCD14+ Monocytes\tsinglet",
            "CACA-1\t0\t0\tD2\tstim\t1\tCD14+ Monocytes\tsinglet",
        ]) + "\n",
    }
    for key, matrix in (("control_matrix", ctrl), ("stimulated_matrix", stim)):
        r, c = np.nonzero(matrix)
        texts[key] = "%%MatrixMarket matrix coordinate real general\n%\n" + f"{matrix.shape[0]} {matrix.shape[1]} {len(r)}\n"
        texts[key] += "".join(f"{i+1} {j+1} {matrix[i,j]}\n" for i, j in zip(r, c))
    paths = {}
    for key, text in texts.items():
        path = root / key / module.FILES[key][0]
        path.parent.mkdir(parents=True)
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write(text)
        paths[key] = path
    return paths, {k: module.sha256_file(p) for k, p in paths.items()}


class KangCaseContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input = self.root / "input"
        self.paths, self.hashes = fixture(self.input)

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, **kwargs):
        return module.run_case(self.input, self.root / "out", min_cells=1,
                               expected_checksums=self.hashes, synthetic_fixture=True, **kwargs)

    def test_source_collision_rule_has_no_cross_condition_join(self):
        genes, meta, codes = module.read_labels(self.paths)
        aligned = module.align_metadata(meta, codes)
        self.assertEqual(int(aligned.metadata_id_was_disambiguated.sum()), 1)
        rows = aligned.loc[aligned.source_barcode.eq("AAAA-1")]
        self.assertEqual(rows.metadata_id.tolist(), ["AAAA-1", "AAAA-11"])
        self.assertEqual(rows.stim.tolist(), ["ctrl", "stim"])
        self.assertTrue(aligned.source_cell_id.is_unique)

    def test_metadata_order_is_not_used_to_align(self):
        _, meta, codes = module.read_labels(self.paths)
        first = module.align_metadata(meta, codes)
        shuffled = module.align_metadata(meta.sample(frac=1, random_state=9), codes)
        pd.testing.assert_frame_equal(first, shuffled)

    def test_unmatched_or_wrong_condition_metadata_is_rejected(self):
        _, meta, codes = module.read_labels(self.paths)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            module.align_metadata(meta.drop(index="AAAA-11"), codes)
        bad = meta.copy()
        bad.loc["AAAA-11", "stim"] = "ctrl"
        with self.assertRaisesRegex(ValueError, "crosses conditions"):
            module.align_metadata(bad, codes)

    def test_full_aggregation_and_equal_donor_differences(self):
        with patch.object(module, "render_figure", return_value=None):
            result = self.execute()
        self.assertEqual(result["qc"]["included_singlets"], 6)
        self.assertEqual(result["qc"]["paired_donors"], 2)
        self.assertEqual(result["qc"]["duplicated_gene_symbols"], 1)
        output = self.root / "out"
        counts = sparse.load_npz(output / "raw/pseudobulk_counts.npz").toarray()
        np.testing.assert_array_equal(counts, [[3, 1, 4], [4, 4, 8], [10, 0, 0], [0, 10, 0]])
        expected = np.log2(1 + 1e6 * np.array([[4, 4, 8], [0, 10, 0]]) / np.array([[16], [10]])) - np.log2(1 + 1e6 * np.array([[3, 1, 4], [10, 0, 0]]) / np.array([[8], [10]]))
        with np.load(output / "raw/paired_responses.npz", allow_pickle=False) as arrays:
            np.testing.assert_allclose(arrays["observed_delta"], expected, rtol=0, atol=0)
            self.assertEqual(arrays["donor_ids"].tolist(), ["D1", "D2"])
        summary = pd.read_csv(output / "tables/gene_summary.csv")
        np.testing.assert_allclose(summary.mean_paired_difference, expected.mean(axis=0))
        self.assertEqual(result["provenance"]["source_kind"], "synthetic_test_fixture")
        self.assertIn("SYNTHETIC TEST FIXTURE", (output / "report.md").read_text(encoding="utf-8"))

    def test_missing_low_cell_and_zero_library_pairs_stay_explicit(self):
        groups = pd.DataFrame([
            ["a", "D1", "ctrl", "X", 3, 2], ["b", "D1", "stim", "X", 1, 2],
            ["c", "D2", "ctrl", "X", 3, 2],
            ["d", "D3", "ctrl", "X", 3, 0], ["e", "D3", "stim", "X", 3, 2],
        ], columns=["group_id", "donor", "condition", "cell_type", "n_cells", "library_umi"])
        counts = sparse.csr_matrix([[2, 0], [0, 2], [2, 0], [0, 0], [0, 2]])
        pairs, delta = module.paired_responses(counts, groups, "X", 2)
        self.assertEqual(delta.shape, (0, 2))
        self.assertEqual(pairs.reason.tolist(), ["fewer_than_min_cells_in_at_least_one_condition", "missing_condition", "zero_pseudobulk_library"])

    def test_bad_counts_and_duplicate_coordinates_are_rejected(self):
        path = self.paths["control_matrix"]
        for entries, count, message in (("1 1 -1\n", 1, "nonnegative"), ("1 1 0.5\n", 1, "integers"), ("1 1 nan\n", 1, "finite"), ("1 1 2\n1 1 3\n", 2, "Duplicate coordinate")):
            with gzip.open(path, "wt") as handle:
                handle.write(f"%%MatrixMarket matrix coordinate real general\n%\n3 4 {count}\n" + entries)
            with self.assertRaisesRegex(ValueError, message):
                module.read_count_matrix(path, (3, 4))

    def test_dimensions_and_repeated_gene_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            module.read_count_matrix(self.paths["control_matrix"], (4, 3))
        with gzip.open(self.paths["genes"], "wt") as handle:
            handle.write("ENSG1\tA\nENSG1\tB\n")
        with self.assertRaisesRegex(ValueError, "unique"):
            module.read_labels(self.paths)

    def test_fixed_hashes_and_fixture_override_cannot_be_silent(self):
        with self.assertRaisesRegex(ValueError, "size"):
            module.run_case(self.input, self.root / "wrong-real")
        self.assertEqual(json.loads((self.root / "wrong-real/error.json").read_text(encoding="utf-8"))["model_status"], "not_run")
        with self.assertRaisesRegex(ValueError, "require synthetic"):
            module.run_case(self.input, self.root / "unlabelled", expected_checksums=self.hashes)
        corrupted = dict(self.hashes, genes="0" * 64)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            module.run_case(self.input, self.root / "mismatch", expected_checksums=corrupted, synthetic_fixture=True)

    def test_plot_failure_preserves_numeric_data_and_no_broken_image(self):
        with patch.object(module, "render_figure", side_effect=ImportError("no plotting backend")):
            result = self.execute()
        self.assertEqual(result["figure"]["status"], "failed")
        output = self.root / "out"
        self.assertTrue((output / "raw/paired_responses.npz").is_file())
        self.assertTrue((output / "provenance.json").is_file())
        self.assertNotIn("![", (output / "report.md").read_text(encoding="utf-8"))

    def test_existing_output_is_not_modified(self):
        output = self.root / "out"
        output.mkdir()
        (output / "keep").write_text("existing", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.execute()
        self.assertEqual((output / "keep").read_text(encoding="utf-8"), "existing")
        self.assertEqual(len(list(output.iterdir())), 1)

    def test_source_na_annotation_is_retained_without_becoming_a_cell_type(self):
        path = self.paths["metadata"]
        with gzip.open(path, "rt") as handle:
            text = handle.read()
        text = text.replace("GGGG-1\t0\t0\tD2\tctrl\t1\tCD14+ Monocytes", "GGGG-1\t0\t0\tD2\tctrl\t1\tNA")
        with gzip.open(path, "wt") as handle:
            handle.write(text)
        self.hashes["metadata"] = module.sha256_file(path)
        with patch.object(module, "render_figure", side_effect=ImportError("plot omitted in synthetic test")):
            result = self.execute()
        self.assertEqual(result["qc"]["source_unassigned_cell_labels"], 1)
        self.assertEqual(result["qc"]["included_singlets_with_unassigned_cell_label"], 1)
        self.assertEqual(result["qc"]["paired_donors"], 1)
        self.assertEqual(result["qc"]["pair_exclusions"][0]["reason"], "missing_condition")
        groups = pd.read_csv(self.root / "out/tables/pseudobulk_index.csv", keep_default_na=False)
        self.assertEqual(int(groups.loc[groups.cell_type.eq("NA"), "library_umi"].iloc[0]), 10)
        with self.assertRaisesRegex(ValueError, "unassigned"):
            module.run_case(self.input, self.root / "na-request", cell_type="NA")


if __name__ == "__main__":
    unittest.main()
