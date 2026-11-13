"""Small numerical guards for plotting; these fixtures are never model results."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd


spec = importlib.util.spec_from_file_location(
    "plot_celloracle_case", Path(__file__).resolve().parents[1] / "scripts/plot_celloracle_case.py")
plot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plot)


class PlotCellOracleIntegrityTests(unittest.TestCase):
    def test_existing_output_is_rejected_without_reading_runs_or_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("original output")
            with self.assertRaisesRegex(FileExistsError, "not overwritten"):
                plot.main(["--ko-run", "missing-ko", "--oe-run", "missing-oe",
                           "--output-dir", str(output)])
            self.assertEqual(sentinel.read_text(), "original output")

    def test_rejects_permuted_expression_axis_even_when_values_look_valid(self):
        base = pd.DataFrame([[1., 2.], [3., 4.]], index=["c1", "c2"], columns=["g1", "g2"])
        delta = pd.DataFrame(0., index=base.index, columns=base.columns)
        with self.assertRaisesRegex(ValueError, "axes differ"):
            plot.validate_expression_triplet(base, base.iloc[::-1], delta)

    def test_rejects_nonfinite_or_inconsistent_delta(self):
        base = pd.DataFrame([[1., 2.]], index=["c1"], columns=["g1", "g2"])
        with self.assertRaisesRegex(ValueError, "differs from"):
            plot.validate_expression_triplet(base, base, base)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            plot.validate_expression_triplet(base, base, base * np.nan)

    def test_shared_map_rejects_cell_or_coordinate_mismatch(self):
        table = pd.DataFrame({"cell": ["c1", "c2"], "group": ["plate1", "plate2"],
                              "umap_x": [0., 1.], "umap_y": [0., 2.],
                              "dx": [0.1, 0.2], "dy": [0.1, 0.2],
                              "dx_random": [0.2, 0.1], "dy_random": [0.2, 0.1]})
        changed = table.copy()
        changed.loc[1, "umap_x"] += 0.00001
        with self.assertRaisesRegex(ValueError, "coordinates differ"):
            plot.validate_matched_coordinates(table, changed)
        with self.assertRaisesRegex(ValueError, "cell IDs differ"):
            plot.validate_matched_coordinates(table, table.iloc[::-1].reset_index(drop=True))

    def test_ranks_signed_changes_and_excludes_forced_target(self):
        delta = pd.DataFrame({"Gata1": [100., 100.], "up": [3., 1.], "down": [-4., -2.],
                              "mixed": [-100., 100.], "less_up": [0.5, 0.5], "zero": [0., 0.]})
        _, selected = plot.directional_effects(delta, "Gata1", 1)
        self.assertEqual(set(selected.gene), {"up", "down"})
        self.assertEqual(selected.set_index("gene").loc["down", "mean_delta"], -3.)
        self.assertEqual(selected.set_index("gene").loc["up", "mean_delta"], 2.)

    def test_grn_roundoff_is_reported_but_material_difference_is_rejected(self):
        ko = pd.DataFrame([[0., 0.25], [-0.5, 0.]], index=["g1", "g2"], columns=["g1", "g2"])
        roundoff = ko.copy()
        roundoff.loc["g1", "g2"] += 2e-15
        result = plot.validate_matched_grn(ko, roundoff)
        self.assertFalse(result["fitted_grn_coefficients_exact"])
        self.assertGreater(result["fitted_grn_max_abs_difference"], 0.)
        changed = ko.copy()
        changed.loc["g1", "g2"] += 0.01
        with self.assertRaisesRegex(ValueError, "beyond"):
            plot.validate_matched_grn(ko, changed)


if __name__ == "__main__":
    unittest.main()
