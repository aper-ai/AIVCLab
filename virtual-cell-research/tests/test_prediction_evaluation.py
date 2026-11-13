"""Synthetic metric/split contracts, not scientific model validation."""
import csv
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/evaluate_predictions.py"
SPEC = importlib.util.spec_from_file_location("evaluate_predictions", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
HOLDOUT_SCRIPT = SCRIPT.with_name("kang_holdout_baseline.py")
HOLDOUT_SPEC = importlib.util.spec_from_file_location("kang_holdout_baseline", HOLDOUT_SCRIPT)
holdout = importlib.util.module_from_spec(HOLDOUT_SPEC)
HOLDOUT_SPEC.loader.exec_module(holdout)


class PredictionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.observed = self.table("observed.csv", [["sample_id", "g1", "g2", "g3"], ["s1", 1, 2, -1], ["s2", 2, 0, -2]])
        self.predicted = self.table("predicted.csv", [["sample_id", "g3", "g1", "g2"], ["s2", -2, 2, 0], ["s1", -1, 1, 2]])
        self.meta = self.table("metadata.tsv", [["sample_id", "unit_id", "fold_id"], ["s2", "供体乙", "f2"], ["s1", "供体甲", "f1"]])
        self.settings = self.root / "settings.json"
        self.config = {"schema_version": 1, "input_kind": "response",
                       "observed": {"scale": "log2(1+CPM) 差值", "context": "教学背景"},
                       "predicted": {"scale": "log2(1+CPM) 差值", "context": "教学背景"},
                       "unit_definition": "供体；合成测试夹具"}
        self.save_settings()

    def tearDown(self):
        self.temp.cleanup()

    def save_settings(self):
        self.settings.write_text(json.dumps(self.config, ensure_ascii=False), encoding="utf-8")

    def table(self, name, rows):
        p = self.root / name
        opener = gzip.open if name.endswith(".gz") else open
        with opener(p, "wt", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter="\t" if ".tsv" in name else ",")
            writer.writerows(rows)
        return p

    def run_case(self, **kwargs):
        return module.run_evaluation(self.observed, self.predicted, self.meta, self.settings, self.root / "out", **kwargs)

    def membership(self):
        return self.table("membership.csv", [["fold_id", "role", "sample_id", "unit_id"],
                    ["f1", "train", "s2", "供体乙"], ["f1", "evaluation", "s1", "供体甲"],
                    ["f2", "train", "s1", "供体甲"], ["f2", "evaluation", "s2", "供体乙"]])

    def test_shuffled_axes_and_metadata_are_exactly_reconstructed(self):
        result = self.run_case()
        self.assertEqual(result["metrics"]["prediction"]["rmse"], 0)
        self.assertAlmostEqual(result["metrics"]["prediction"]["pearson"], 1)
        with np.load(self.root / "out/raw/aligned_responses.npz", allow_pickle=False) as data:
            np.testing.assert_array_equal(data["observed_response"], data["predicted_response"])
            self.assertEqual(data["sample_ids"].tolist(), ["s1", "s2"])
            self.assertEqual(data["gene_ids"].tolist(), ["g1", "g2", "g3"])
        self.assertIn("供体", (self.root / "out/report.md").read_text(encoding="utf-8"))

    def test_expression_mode_uses_aligned_baseline(self):
        self.config["input_kind"] = "expression"
        self.config["baseline"] = dict(self.config["observed"])
        self.save_settings()
        baseline = self.table("baseline.csv.gz", [["sample_id", "g2", "g3", "g1"], ["s2", 0, 1, 2], ["s1", 1, 1, 1]])
        self.run_case(baseline_path=baseline)
        with np.load(self.root / "out/raw/aligned_responses.npz") as data:
            np.testing.assert_array_equal(data["observed_response"], [[0, 1, -2], [0, 0, -3]])

    def test_expression_mode_without_baseline_fails_with_record(self):
        self.config["input_kind"] = "expression"
        self.config["baseline"] = dict(self.config["observed"])
        self.save_settings()
        with self.assertRaisesRegex(ValueError, "require one aligned baseline"):
            self.run_case()
        record = json.loads((self.root / "out/error.json").read_text(encoding="utf-8"))
        self.assertEqual(record["model_status"], "not_run")

    def test_response_cannot_subtract_a_second_baseline(self):
        with self.assertRaisesRegex(ValueError, "response inputs must omit"):
            self.run_case(baseline_path=self.observed)

    def test_gzip_matrix_reader_and_duplicate_header(self):
        good = self.table("ok.tsv.gz", [["sample_id", "g1", "g2"], ["s", 1, 2]])
        self.assertEqual(module.read_matrix(good)[0], ["s"])
        bad = self.table("bad.csv", [["sample_id", "g1", "g1"], ["s", 1, 2]])
        with self.assertRaisesRegex(ValueError, "duplicate columns"):
            module.read_matrix(bad)

    def test_missing_extra_gene_sets_are_never_intersected(self):
        self.predicted = self.table("missing.csv", [["sample_id", "g1", "other"], ["s1", 1, 2], ["s2", 1, 2]])
        with self.assertRaisesRegex(ValueError, "ID sets differ"):
            self.run_case()

    def test_missing_duplicate_and_nonfinite_values_fail(self):
        for i, row in enumerate((["s", "", 1], ["s", "nan", 1], ["s", "inf", 1])):
            with self.subTest(row=row):
                p = self.table(f"bad{i}.csv", [["sample_id", "g1", "g2"], row])
                with self.assertRaises(ValueError):
                    module.read_matrix(p)
        p = self.table("dupe.csv", [["sample_id", "g1", "g2"], ["s", 1, 2], ["s", 2, 3]])
        with self.assertRaisesRegex(ValueError, "Duplicate sample_id"):
            module.read_matrix(p)

    def test_scale_or_background_mismatch_is_blocked(self):
        for key in ("scale", "context"):
            self.config["predicted"] = dict(self.config["observed"])
            self.config["predicted"][key] = "different"
            self.save_settings()
            with self.assertRaisesRegex(ValueError, "must match exactly"):
                module.read_settings(self.settings)

    def test_constant_correlations_and_direction_denominator(self):
        m = module.metrics([1, 0, -1], [0, 0, 0])
        self.assertIsNone(m["pearson"])
        self.assertEqual(m["direction_agreement_nonzero_observed"], 0)
        self.assertEqual(m["nonzero_observed_genes"], 2)
        self.assertIsNone(module.metrics([0, 0], [1, 2])["direction_agreement_nonzero_observed"])

    def test_units_are_equally_weighted_without_cell_pseudoreplication(self):
        truth = np.array([[3., 3.], [0., 0.], [0., 0.]])
        meta = [{"sample_id": f"s{i}", "unit_id": u} for i, u in enumerate(["a", "b", "b"])]
        _, units, summary = module.aggregate_metrics(truth, np.zeros_like(truth), meta)
        self.assertEqual(summary["prediction"]["rmse"], 1.5)
        self.assertEqual(summary["prediction"]["pearson_defined_units"], 0)
        self.assertEqual(len(units), 4)

    def test_recorded_disjointness_never_certifies_actual_training(self):
        result = self.run_case(membership_path=self.membership())
        self.assertEqual(result["split_audit"]["status"], "passed_recorded_membership")
        self.assertFalse(result["split_audit"]["training_process_verified"])
        self.assertEqual(result["independent_validation"], "not_assessed")

    def test_same_sample_leakage_fails(self):
        p = self.membership()
        text = p.read_text(encoding="utf-8").replace("f1,train,s2,供体乙", "f1,train,s1,供体甲")
        p.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sample leakage"):
            self.run_case(membership_path=p)

    def test_same_unit_leakage_and_inconsistent_unit_identity_fail(self):
        _, meta = module.read_metadata(self.meta, ["s1", "s2"])
        p = self.membership()
        text = p.read_text(encoding="utf-8").replace("f1,train,s2,供体乙", "f1,train,extra,供体甲")
        p.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "biological-unit leakage"):
            module.audit_membership(p, meta)
        p = self.membership()
        p.write_text(p.read_text(encoding="utf-8").replace("f1,train,s2,供体乙", "f1,train,s2,other"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.audit_membership(p, meta)

    def test_evaluation_membership_must_match_actual_metadata(self):
        p = self.membership()
        p.write_text(p.read_text(encoding="utf-8").replace("f1,evaluation,s1,供体甲", "f1,evaluation,s3,供体甲"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.run_case(membership_path=p)

    def test_existing_output_and_sources_unchanged(self):
        out = self.root / "out"
        out.mkdir()
        keep = out / "keep.txt"
        keep.write_text("不要覆盖", encoding="utf-8")
        source_hash = module.digest(self.observed)
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertEqual(keep.read_text(encoding="utf-8"), "不要覆盖")
        self.assertEqual(module.digest(self.observed), source_hash)
        self.assertEqual(list(out.iterdir()), [keep])

    def test_file_size_and_matrix_value_limits(self):
        with patch.object(module, "MAX_FILE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "Input exceeds"):
                module.read_matrix(self.observed)
        with patch.object(module, "MAX_VALUES", 3):
            with self.assertRaisesRegex(ValueError, "Matrix exceeds"):
                module.read_matrix(self.observed)

    def test_metadata_missing_sample_is_not_silently_dropped(self):
        self.meta = self.table("short.csv", [["sample_id", "unit_id"], ["s1", "one"]])
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.run_case()

    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, "-S", str(SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_held_out_response_does_not_affect_its_prediction(self):
        values = np.array([[1., 2.], [3., 4.], [5., 6.]])
        first, membership = holdout.leave_one_unit_out_mean(values)
        changed = values.copy()
        changed[0] = [1000, -999]
        second, _ = holdout.leave_one_unit_out_mean(changed)
        np.testing.assert_array_equal(first[0], second[0])
        np.testing.assert_array_equal(first[0], [4, 5])
        self.assertEqual(membership, [[1, 2], [0, 2], [0, 1]])
        self.assertFalse(np.array_equal(first[1], second[1]))

    def test_holdout_input_and_lightweight_help(self):
        with self.assertRaises(ValueError):
            holdout.leave_one_unit_out_mean([[1, 2], [3, 4]])
        with self.assertRaises(ValueError):
            holdout.leave_one_unit_out_mean([[1, 2], [3, 4], [float('nan'), 2]])
        result = subprocess.run([sys.executable, "-S", str(HOLDOUT_SCRIPT), "--help"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_windows_artifact_paths_and_ambiguous_aliases(self):
        record = {"sha256": "example"}
        self.assertEqual(holdout.normalize_artifact_records({"raw\\paired_responses.npz": record}),
                         {"raw/paired_responses.npz": record})
        with self.assertRaisesRegex(ValueError, "Ambiguous"):
            holdout.normalize_artifact_records({"raw\\a.npz": record, "raw/a.npz": record})


if __name__ == "__main__":
    unittest.main()
