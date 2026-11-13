"""Synthetic contract tests; these tests do not load or validate PRnet weights."""
import importlib.util
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prnet_reference_case.py"
spec = importlib.util.spec_from_file_location("prnet_reference_under_test", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PRnetReferenceContracts(unittest.TestCase):
    def test_source_array_survives_inplace_model_preprocessing(self):
        # Synthetic preprocessing deliberately mutates the exact same X buffer.
        # The saved source must retain its original values, not a shared view.
        original = np.array([[1., 2.], [3., 4.]], dtype=np.float32)
        data = SimpleNamespace(X=original.copy())
        def normalize(obj):
            obj.X *= 2
        def log1p(obj):
            np.log1p(obj.X, out=obj.X)
        preprocessor = SimpleNamespace(pp=SimpleNamespace(normalize_total=normalize, log1p=log1p))
        source, processed, target = module.preprocess_reference_data(data, preprocessor)
        np.testing.assert_array_equal(source, original)
        np.testing.assert_allclose(processed, np.log1p(original * 2))
        self.assertEqual(target, 5.)
        self.assertFalse(np.shares_memory(source, data.X))

    def test_exact_error_and_constant_response_correlation_is_undefined(self):
        truth = np.array([[1., -2., 3.], [3., 1., -1.]])
        same = module.row_metrics(truth, truth)
        np.testing.assert_array_equal(same["rmse"], [0., 0.])
        np.testing.assert_allclose(same["pearson"], [1., 1.])
        zero = module.row_metrics(truth, np.zeros_like(truth))
        self.assertTrue(np.isnan(zero["pearson"]).all())
        np.testing.assert_allclose(zero["rmse"], np.sqrt(np.mean(truth ** 2, axis=1)))
        self.assertIsNone(module._mean_or_none(zero["pearson"]))

    def test_metrics_refuse_nonfinite_or_misaligned_arrays(self):
        for target in (np.array([[1, np.inf]]), np.array([[1, np.nan]]), np.ones((2, 2)), np.ones(2)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                module.row_metrics(np.array([[1., 2.]]), target)

    def test_alias_exclusion_is_transitive_and_stable_under_reordering(self):
        ids = ["id_a", "id_b", "id_c", "id_d"]
        names = ["Drug A", "drug a", "Other name", "Unrelated"]
        smiles = ["CCC", "CCO", "CCO", "COC"]
        groups = module.exclusion_groups(ids, names, smiles)
        self.assertEqual(len(set(groups[:3])), 1)
        self.assertNotEqual(groups[0], groups[3])
        order = [3, 1, 0, 2]
        reordered = module.exclusion_groups([ids[i] for i in order], [names[i] for i in order], [smiles[i] for i in order])
        np.testing.assert_array_equal(groups[order], reordered)

    def test_mean_reference_excludes_all_target_group_conditions(self):
        values = np.array([[1., 2.], [3., 4.], [10., 20.], [14., 30.]])
        groups = ["A", "A", "B", "B"]
        result = module.leave_group_out_mean(values, groups)
        np.testing.assert_allclose(result, [[12, 25], [12, 25], [2, 3], [2, 3]])
        changed = values.copy()
        changed[:2] += 10000
        # Neither of A's observed outcomes is available to its own reference.
        np.testing.assert_array_equal(module.leave_group_out_mean(changed, groups)[:2], result[:2])

    def test_reference_does_not_invent_an_empty_comparison_group(self):
        with self.assertRaises(ValueError):
            module.leave_group_out_mean(np.ones((2, 3)), ["same", "same"])
        with self.assertRaises(ValueError):
            module.exclusion_groups(["a"], [""], ["CC"])
        with self.assertRaises(ValueError):
            module.exclusion_groups(["a"], ["b", "c"], ["CC"])

    def test_resource_hashes_are_checked_before_loading_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for resource in module.RESOURCES:
                path = root / resource["id"] / resource["file_name"]
                path.parent.mkdir()
                path.write_bytes(b"x" * resource["bytes"])
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                module.resource_paths(root)

    def test_missing_resources_leave_honest_failure_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(module, "_run_model") as inference:
                result = module.run_reference(root / "missing", root / "out")
            inference.assert_not_called()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["model_status"], "not_run")
            self.assertEqual(result["independent_validation"], "not_assessed")
            prov = json.loads((root / "out/provenance.json").read_text())
            self.assertEqual(prov["invocation"]["kind"], "python_api")
            self.assertIsNone(prov["invocation"]["argv"])
            self.assertTrue((root / "out/errors.jsonl").read_text().strip())

    def test_existing_outputs_and_invalid_parameters_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "exists"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("original")
            with self.assertRaises(FileExistsError):
                module.run_reference(root, output)
            self.assertEqual(marker.read_text(), "original")
            for settings in ({"noise_draws": 0}, {"noise_draws": 65}, {"seed": -1}, {"threads": 5}, {"threads": True}):
                with self.subTest(settings=settings), self.assertRaises(ValueError):
                    module.run_reference(root, root / "invalid", **settings)
                self.assertFalse((root / "invalid").exists())

    def test_cli_help_needs_no_model_dependencies(self):
        code = "import sys,runpy; sys.modules.update({n:None for n in ['torch','scanpy','rdkit']}); sys.argv=[sys.argv[1],'--help']; runpy.run_path(sys.argv[0],run_name='__main__')"
        completed = subprocess.run([sys.executable, "-c", code, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("independent validation", " ".join(completed.stdout.split()))

    def test_verified_cache_reuse_is_explicit_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b"synthetic cache fixture; not an official model"
            resource = dict(module.RESOURCES[0], bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            cache = root / "previous/model/PRnet.py"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(raw)
            with patch.object(module, "RESOURCES", [resource]):
                record = module.fetch_resources(root / "new", root / "previous")
            self.assertEqual(record["status"], "ready")
            self.assertEqual(record["resources"][0]["status"], "reused_verified")
            self.assertEqual((root / "new/model/PRnet.py").read_bytes(), raw)
            self.assertEqual(cache.read_bytes(), raw)

    def test_corrupt_cache_is_not_executed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / "previous/model/PRnet.py"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"invalid fixture")
            with self.assertRaisesRegex(ValueError, "Cached resource identity mismatch"):
                module.fetch_resources(root / "new", root / "previous")
            self.assertEqual(cache.read_bytes(), b"invalid fixture")
            record = json.loads((root / "new/resources.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertFalse((root / "new/model/PRnet.py").exists())


if __name__ == "__main__":
    unittest.main()
