"""Synthetic ID/numerical-integrity regressions; not model validation evidence."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/plot_prnet_case.py"
spec = importlib.util.spec_from_file_location("plot_prnet_under_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    # Nonalphabetical profile and gene IDs make accidental positional joins
    # observable. The two controls have deliberately different values.
    processed = np.array([[1., 2.], [4., 8.], [2., 0.], [5., 6.], [0., 3.]])
    baseline = processed[[0, 1, 0]].copy()
    observed = processed[[2, 3, 4]].copy()
    prediction = np.array([[1.5, 1.], [4.5, 9.], [1., 2.]])
    arrays = {
        "source_profile_ids": np.array(["control-B", "control-A", "treatment-C", "treatment-A", "treatment-B"]),
        "profile_ids": np.array(["treatment-C", "treatment-A", "treatment-B"]),
        "gene_ids": np.array(["GENE-Z", "GENE-A"]),
        "paired_control_ids": np.array(["control-B", "control-A", "control-B"]),
        "condition_ids": np.array(["condition-C", "condition-A", "condition-B"]),
        "processed_X": processed, "baseline": baseline,
        "observed_post": observed, "observed_delta": observed - baseline,
        "predicted_post_mean": prediction, "predicted_delta": prediction - baseline,
    }
    conditions = pd.DataFrame({
        "source_profile_id": arrays["profile_ids"], "paired_control_index": arrays["paired_control_ids"],
        "condition_id": arrays["condition_ids"], "pert_iname": ["Zulu", "Alpha", "Middle"],
        "pert_id": ["ID-Z", "ID-A", "ID-M"], "dose": [10., 1., 5.], "pert_time": [6., 6., 6.],
        "rna_plate": ["plate-Z", "plate-A", "plate-M"], "exclusion_group": ["group-Z", "group-A", "group-M"],
    })
    genes = pd.DataFrame({"gene_id": arrays["gene_ids"], "pr_gene_title": ["Gene Z", "Gene A"]})
    return arrays, conditions, genes


class PRnetPlotIntegrity(unittest.TestCase):
    def test_reordered_tables_keep_exact_source_id_and_gene_alignment(self):
        arrays, conditions, genes = fixture()
        aligned, aligned_genes = module.align_and_check(arrays, conditions.iloc[[1, 2, 0]], genes.iloc[::-1])
        self.assertEqual(aligned.index.tolist(), ["treatment-C", "treatment-A", "treatment-B"])
        self.assertEqual(aligned.paired_control_index.tolist(), ["control-B", "control-A", "control-B"])
        self.assertEqual(aligned_genes.pr_gene_title.tolist(), ["Gene Z", "Gene A"])

    def test_matching_lengths_cannot_hide_duplicate_or_missing_profile_id(self):
        arrays, conditions, genes = fixture()
        conditions.loc[1, "source_profile_id"] = "treatment-C"
        with self.assertRaisesRegex(ValueError, "profile IDs"):
            module.align_and_check(arrays, conditions, genes)

    def test_consistently_relabelled_control_still_must_match_actual_values(self):
        arrays, conditions, genes = fixture()
        arrays["paired_control_ids"][0] = "control-A"
        conditions.loc[0, "paired_control_index"] = "control-A"
        with self.assertRaisesRegex(ValueError, "baseline differs"):
            module.align_and_check(arrays, conditions, genes)

    def test_response_cannot_silently_drift_from_saved_prediction(self):
        arrays, conditions, genes = fixture()
        arrays["predicted_delta"][0, 1] += .01
        with self.assertRaisesRegex(ValueError, "predicted_delta is inconsistent"):
            module.align_and_check(arrays, conditions, genes)

    def test_heatmap_choice_ignores_prediction_success_and_table_order(self):
        arrays, conditions, genes = fixture()
        aligned, _ = module.align_and_check(arrays, conditions, genes)
        first = module.select_heatmap(arrays, aligned, gene_count=1, profile_count=2)
        # Endpoint drug groups are Alpha and Zulu, despite the source order.
        self.assertEqual(first[0].tolist(), [1, 0])
        # Mean absolute observed response is larger in GENE-A.
        self.assertEqual(first[1].tolist(), [1])
        arrays["predicted_delta"][:] = [[1000., -1000.], [0., 0.], [-999., 999.]]
        second = module.select_heatmap(arrays, aligned.iloc[::-1], gene_count=1, profile_count=2)
        np.testing.assert_array_equal(first[0], second[0])
        np.testing.assert_array_equal(first[1], second[1])

    def test_wrong_saved_rmse_and_nonzero_baseline_correlation_are_rejected(self):
        arrays, _, _ = fixture()
        # Hand-computed three-profile errors avoid asserting the implementation
        # against a second call to itself.
        arrays["gaussian_sample_delta"] = arrays["observed_delta"].copy()
        arrays["other_group_mean_delta"] = np.zeros((3, 2))
        expected = {
            "prnet_mean": ([np.sqrt(.625), np.sqrt(4.625), 1.], [.75, 1.75, 1.]),
            "prnet_sample": ([0., 0., 0.], [0., 0., 0.]),
            "no_change": ([np.sqrt(2.5), np.sqrt(2.5), 1.], [1.5, 1.5, 1.]),
            "other_group_mean": ([np.sqrt(2.5), np.sqrt(2.5), 1.], [1.5, 1.5, 1.]),
        }
        rows, summary = [], {}
        for method, (rmse, mae) in expected.items():
            summary[method] = {"mean_profile_rmse": float(np.mean(rmse))}
            for i in range(3):
                rows.append({"source_profile_id": arrays["profile_ids"][i], "condition_id": arrays["condition_ids"][i], "method": method, "rmse": rmse[i], "mae": mae[i], "pearson": np.nan if method == "no_change" else .5, "scale": module.SCALE})
        table = pd.DataFrame(rows)
        checked = module.verify_metrics(arrays, table.iloc[::-1], summary)
        self.assertEqual(len(checked["prnet_mean"]), 3)
        np.testing.assert_allclose(checked["prnet_mean"], expected["prnet_mean"][0])
        changed = table.copy()
        changed.loc[0, "rmse"] = 0.
        with self.assertRaisesRegex(ValueError, "rmse does not match"):
            module.verify_metrics(arrays, changed, summary)
        changed = table.copy()
        changed.loc[changed.method.eq("no_change"), "pearson"] = 0.
        with self.assertRaisesRegex(ValueError, "Pearson must remain undefined"):
            module.verify_metrics(arrays, changed, summary)


if __name__ == "__main__":
    unittest.main()
