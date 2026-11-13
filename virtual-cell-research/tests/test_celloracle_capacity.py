"""Regression for an observed real CellOracle import boundary; synthetic arrays."""
import importlib.util
from pathlib import Path
import unittest

import anndata as ad
import numpy as np
from scipy import sparse

SPEC = importlib.util.spec_from_file_location("celloracle_capacity_route", Path(__file__).resolve().parents[1] / "examples/ko_oe/celloracle_run.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CellOracleCapacity(unittest.TestCase):
    def test_real_failure_shape_gets_actionable_error_without_mutating_counts(self):
        values = np.ones((5, 1001), dtype=np.int32)
        values[:, 790:] = 0
        data = ad.AnnData(sparse.csr_matrix(values))
        with self.assertRaisesRegex(ValueError, "only 790.*increase --n-hvg"):
            MODULE.check_celloracle_cv_capacity(data, "0.20.0")
        np.testing.assert_array_equal(data.X.toarray(), values)

    def test_dense_and_sparse_capacity_checks_do_not_certify_model_results(self):
        values = np.tile(np.arange(1, 6, dtype=np.int32), (1001, 1)).T
        for matrix in (values, sparse.csr_matrix(values), sparse.csc_matrix(values)):
            with self.subTest(kind=type(matrix).__name__):
                result = MODULE.check_celloracle_cv_capacity(ad.AnnData(matrix), "0.20.0")
                self.assertEqual(result["status"], "capacity_checked")
                self.assertEqual(result["required_genes"], 1000)

    def test_uninspected_backend_version_is_not_claimed_checked(self):
        result = MODULE.check_celloracle_cv_capacity(ad.AnnData(np.ones((4, 4))), "0.21.0")
        self.assertEqual(result["status"], "not_checked")


if __name__ == "__main__":
    unittest.main()
