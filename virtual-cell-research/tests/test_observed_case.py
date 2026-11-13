"""Observed-response contracts with clearly labelled synthetic H5AD fixtures.

These tests check data handling, never simulate or claim model inference.
"""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import anndata as ad
import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/observed_prnet_case.py"
spec = importlib.util.spec_from_file_location("observed_prnet_case", SCRIPT)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def fixture():
    obs = pd.DataFrame({
        "cell_id": ["TEST_CELL"] * 4, "cell_type": ["TEST_CELL"] * 4,
        "pert_id": ["DMSO", "DMSO", "TEST_A", "TEST_B"],
        "pert_iname": ["DMSO", "DMSO", "test-a", "test-b"],
        "condition": ["DMSO", "DMSO", "test-a", "test-b"],
        "pert_dose": [-666., -666., 1., 2.], "pert_dose_unit": ["-666", "-666", "um", "um"],
        "dose": [0., 0., 1., 2.], "pert_time": [6.] * 4, "pert_time_unit": ["h"] * 4,
        "pert_type": ["ctl_vehicle", "ctl_vehicle", "trt_cp", "trt_cp"],
        "rna_plate": ["P1", "P2", "P1", "P2"], "rna_well": ["A1", "A2", "B1", "B2"],
        "control": [1, 1, 0, 0], "SMILES": ["CS(=O)C", "CS(=O)C", "CC", "CCC"],
        "canonical_smiles": ["CS(=O)C", "CS(=O)C", "CC", "CCC"],
        "paired_control_index": ["ctrl-1", "ctrl-2", "ctrl-1", "ctrl-2"],
        "demo_split": [None, None, "test", "test"],
    }, index=["ctrl-1", "ctrl-2", "treat-a", "treat-b"])
    var = pd.DataFrame({"pr_gene_title": ["Test gene 1", "Test gene 2", "Test gene 3"],
                        "pr_is_lm": [1] * 3, "pr_is_bing": [1] * 3}, index=["G1", "G2", "G3"])
    return ad.AnnData(X=np.array([[1., 2., 3.], [10., 20., 30.], [4., 1., 6.], [8., 24., 30.]], dtype=np.float32), obs=obs, var=var)


class ObservedCaseContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "synthetic.h5ad"
        self.output = self.root / "results"

    def write(self, data=None):
        (fixture() if data is None else data).write_h5ad(self.source)
        return route.sha256_file(self.source)

    def run_fixture(self, data=None):
        digest = self.write(data)
        return route.run_case(self.source, self.output, expected_sha=digest, synthetic_fixture=True)

    def test_exact_matched_differences_and_stable_traceable_artifacts(self):
        result = self.run_fixture()
        with np.load(self.output / "raw/observed_responses.npz", allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved["observed_delta"], [[3, -1, 3], [-2, 4, 0]])
            self.assertEqual(saved["profile_ids"].tolist(), ["treat-a", "treat-b"])
            self.assertEqual(saved["paired_control_ids"].tolist(), ["ctrl-1", "ctrl-2"])
            self.assertEqual(saved["gene_ids"].tolist(), ["G1", "G2", "G3"])
        csv = pd.read_csv(self.output / "tables/observed_responses.csv.gz", index_col=0)
        np.testing.assert_array_equal(csv.to_numpy(), [[3, -1, 3], [-2, 4, 0]])
        provenance = result["provenance"]
        self.assertEqual(provenance["source_kind"], "synthetic_test_fixture")
        self.assertIsNone(provenance["source_url"])
        self.assertEqual(provenance["source_sha256"], route.sha256_file(self.source))
        self.assertEqual(provenance["model_status"], "not_run")
        self.assertEqual(provenance["independent_validation"], "not_assessed")
        self.assertEqual(provenance["scale"], "source_native_processed_scale")
        self.assertFalse(provenance["normalization_applied"])
        self.assertEqual(result["figure"]["status"], "generated")
        svg = (self.output / "figures/observed_response.svg").read_text()
        self.assertNotIn("<image", svg)
        self.assertTrue((self.output / "figures/observed_response.png").is_file())
        self.assertEqual(route.condition_id(fixture().obs.iloc[2]), route.condition_id(fixture().obs.iloc[2].copy()))

    def test_sha_is_required_and_cli_has_no_override(self):
        digest = self.write()
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            route.run_case(self.source, self.output)
        with self.assertRaisesRegex(ValueError, "synthetic_fixture=True"):
            route.run_case(self.source, self.output, expected_sha=digest)
        self.assertFalse(self.output.exists())
        actions = {action.dest for action in route.parser()._actions}
        self.assertNotIn("expected_sha", actions)
        self.assertNotIn("synthetic_fixture", actions)

    def test_missing_and_noncontrol_pairing_are_rejected(self):
        for pair, expected in (("absent", "Missing paired"), ("treat-b", "non-control")):
            with self.subTest(pair=pair):
                data = fixture()
                data.obs.loc["treat-a", "paired_control_index"] = pair
                digest = self.write(data)
                with self.assertRaisesRegex(ValueError, expected):
                    route.run_case(self.source, self.output, expected_sha=digest, synthetic_fixture=True)
                self.assertFalse(self.output.exists())

    def test_pairing_requires_both_cell_and_time_fields(self):
        for field, value in (("cell_id", "OTHER"), ("cell_type", "OTHER"), ("pert_time", 24.), ("pert_time_unit", "day")):
            with self.subTest(field=field):
                data = fixture()
                data.obs.loc["treat-a", field] = value
                digest = self.write(data)
                with self.assertRaisesRegex(ValueError, f"mismatched {field}"):
                    route.run_case(self.source, self.output, expected_sha=digest, synthetic_fixture=True)
                self.assertFalse(self.output.exists())

    def test_cross_plate_pair_is_preserved_and_flagged(self):
        data = fixture()
        data.obs.loc["treat-a", "paired_control_index"] = "ctrl-2"
        result = self.run_fixture(data)
        with np.load(self.output / "raw/observed_responses.npz", allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved["observed_delta"][0], [-6, -19, -24])
            self.assertEqual(saved["paired_control_ids"][0], "ctrl-2")
        index = pd.read_csv(self.output / "tables/condition_index.csv", index_col=0)
        self.assertTrue(index.loc["treat-a", "cross_rna_plate"])
        self.assertEqual(result["qc"]["cross_rna_plate_treated_profiles"], 1)
        self.assertFalse(result["provenance"]["pairing_reassigned"])

    def test_ambiguous_name_never_merges_different_smiles(self):
        data = fixture()
        data.obs.loc["treat-b", ["pert_iname", "condition"]] = "test-a"
        # Keep every other condition identity field equal to isolate the SMILES guard.
        for field in route.CONDITION_FIELDS:
            if field != "SMILES":
                data.obs.loc["treat-b", field] = data.obs.loc["treat-a", field]
        data.obs.loc["treat-b", "dose"] = 1.
        result = self.run_fixture(data)
        self.assertEqual(result["qc"]["condition_count"], 2)
        self.assertEqual(result["qc"]["ambiguous_names"][0]["pert_iname"], "test-a")
        self.assertEqual(result["qc"]["ambiguous_names"][0]["source_smiles"], ["CC", "CCC"])
        summary = pd.read_csv(self.output / "tables/condition_summary.csv")
        self.assertEqual(summary["n_profiles"].tolist(), [1, 1])

    def test_nonfinite_matrix_and_required_metadata_fail_before_output(self):
        for mutate, expected in (
            (lambda data: data.X.__setitem__((2, 0), np.nan), "non-finite"),
            (lambda data: data.X.__setitem__((2, 0), np.inf), "non-finite"),
            (lambda data: data.obs.__delitem__("paired_control_index"), "Missing required obs"),
            (lambda data: data.var.__delitem__("pr_gene_title"), "Missing required var"),
            (lambda data: data.obs.__setitem__("control", [1, 1, 2, 0]), "only 0 and 1"),
            (lambda data: data.obs.__setitem__("pert_time", [6., 6., np.nan, 6.]), "non-finite"),
        ):
            with self.subTest(expected=expected):
                data = fixture()
                mutate(data)
                digest = self.write(data)
                with self.assertRaisesRegex(ValueError, expected):
                    route.run_case(self.source, self.output, expected_sha=digest, synthetic_fixture=True)
                self.assertFalse(self.output.exists())

    def test_existing_output_is_never_overwritten(self):
        digest = self.write()
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("unchanged")
        with self.assertRaises(FileExistsError):
            route.run_case(self.source, self.output, expected_sha=digest, synthetic_fixture=True)
        self.assertEqual(marker.read_text(), "unchanged")
        self.assertEqual(list(self.output.iterdir()), [marker])

    def test_oversized_input_is_rejected_without_parsing(self):
        with self.source.open("wb") as handle:
            handle.truncate(route.MAX_INPUT_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "8 MiB"):
            route.run_case(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_plot_failure_keeps_complete_data_and_records_reason(self):
        with mock.patch.object(route, "render_figure", side_effect=RuntimeError("test plot failure")):
            result = self.run_fixture()
        self.assertEqual(result["figure"]["status"], "failed")
        self.assertIn("test plot failure", result["figure"]["reason"])
        with np.load(self.output / "raw/observed_responses.npz", allow_pickle=False) as saved:
            np.testing.assert_array_equal(saved["observed_delta"], [[3, -1, 3], [-2, 4, 0]])
        self.assertTrue((self.output / "report.md").is_file())
        self.assertTrue((self.output / "tables/observed_responses.csv.gz").is_file())
        self.assertEqual(json.loads((self.output / "qc.json").read_text())["warnings"][-1]["code"], "figure_failed")


if __name__ == "__main__":
    unittest.main()
