"""Synthetic fixtures for preparation contracts; never model execution evidence."""
from pathlib import Path
import gzip
import importlib.util
import json
import tempfile
import unittest

import anndata as ad
import numpy as np
import pandas as pd

SPEC = importlib.util.spec_from_file_location("prepare_paul2015_case", Path(__file__).resolve().parents[1] / "scripts/prepare_paul2015_case.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Paul2015Preparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = {name: self.root / (name + ".gz") for name in ("counts", "design", "samples")}
        self.counts = '"W1"\t"W2"\t"W3"\t"W4"\t"W5"\t"W6"\n' + '\n'.join([
            '"Gata1"\t1\t0\t3\t4\t50\t0', '"GeneA"\t2\t3\t4\t5\t20\t0',
            '"GeneB"\t3\t4\t5\t6\t10\t0', '"AliasA;AliasB"\t7\t8\t9\t10\t10\t0']) + '\n'
        self.design = 'Fixture notes\nWell_ID\tSeq_batch_ID\tAmp_batch_ID\tMouse_ID\tBatch_desc\tNumber_of_cells\tPlate_ID\n' + '\n'.join([
            f'W{i}\tS1\tAB173\t2\tUnsorted myeloid\t1\t1' for i in range(1, 5)]) + '\n' + \
            'W5\tS2\tAB239\t4\tCebpa KO\t1\t2\nW6\tS1\tAB173\t2\tUnsorted myeloid\t0\t1\n'
        self.samples = '\n'.join([
            '^SAMPLE = GSM_fixture', '!Sample_title = AB173 [Sample 3]', '!Sample_source_name_ch1 = Unsorted myeloid',
            '!Sample_characteristics_ch1 = genotype/variation: wild type', '!Sample_characteristics_ch1 = strain background: C57BL/6',
            '!Sample_characteristics_ch1 = tissue: bone marrow', '!Sample_characteristics_ch1 = selection marker: Lin- cKit+ Sca1-',
            '!Sample_data_processing = Genome_build: mm9', ''])
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        for name in self.paths:
            with gzip.open(self.paths[name], "wt", encoding="utf-8") as handle:
                handle.write(getattr(self, name))

    def run_case(self, output="output", **kwargs):
        options = {"max_cells": 4, "min_counts": 5, "min_genes": 2, "seed": 123,
                   "synthetic_fixture": True, "expected_hashes": {name: MODULE.sha256(path) for name, path in self.paths.items()}}
        options.update(kwargs)
        return MODULE.prepare(self.paths["counts"], self.paths["design"], self.paths["samples"], self.root / output, **options)

    def test_raw_input_exact_axis_and_mixed_experiments_are_separated(self):
        qc = self.run_case()
        data = ad.read_h5ad(self.root / "output/paul2015_wt_input.h5ad")
        self.assertEqual(list(data.obs_names), ["W1", "W2", "W3", "W4"])
        self.assertEqual(list(data.var_names), ["Gata1", "GeneA", "GeneB"])
        np.testing.assert_array_equal(data.X.toarray(), [[1, 2, 3], [0, 3, 4], [3, 4, 5], [4, 5, 6]])
        self.assertTrue(data.obs.genotype_variation.eq("wild type").all())
        self.assertEqual(qc["model_status"], "not_run")
        self.assertEqual(qc["source_kind"], "synthetic_test_fixture")

    def test_multiname_gene_exclusion_preserves_count_accounting(self):
        qc = self.run_case()
        self.assertEqual(qc["candidate_counts_excluded_multiname"], 34)
        self.assertEqual(qc["candidate_counts_before_exclusion"] - qc["candidate_counts_excluded_multiname"], qc["selected_counts_retained"])
        excluded = pd.read_csv(self.root / "output/excluded_genes.csv")
        self.assertEqual(excluded.iloc[0].source_gene_id, "AliasA;AliasB")
        self.assertEqual(int(excluded.iloc[0].candidate_count_sum), 34)

    def test_sample_genotype_and_build_require_primary_metadata(self):
        for replacement in ("mutant", ""):
            with self.subTest(replacement=replacement):
                original = self.samples
                self.samples = self.samples.replace("wild type", replacement)
                self.write()
                with self.assertRaisesRegex(ValueError, "wild-type mm9"):
                    self.run_case()
                self.samples = original
        self.samples = self.samples.replace("Genome_build: mm9", "Genome_build: mm10")
        self.write()
        with self.assertRaisesRegex(ValueError, "wild-type mm9"):
            self.run_case()

    def test_axis_disagreement_and_duplicate_genes_fail_before_output(self):
        original = self.counts
        self.counts = self.counts.replace('"W6"', '"unknown"')
        self.write()
        with self.assertRaisesRegex(ValueError, "match exactly"):
            self.run_case()
        self.counts = original.replace('"GeneB"', '"GeneA"')
        self.write()
        with self.assertRaisesRegex(ValueError, "gene identity"):
            self.run_case()
        self.assertFalse((self.root / "output").exists())

    def test_fractional_and_negative_candidate_counts_are_not_rounded(self):
        original = self.counts
        for value in ("1.5", "-1"):
            with self.subTest(value=value):
                self.counts = original.replace('"Gata1"\t1\t', '"Gata1"\t' + value + '\t')
                self.write()
                with self.assertRaisesRegex(ValueError, "counts"):
                    self.run_case()
        self.assertFalse((self.root / "output").exists())

    def test_deterministic_selection_and_existing_output_are_preserved(self):
        self.run_case(max_cells=2)
        self.run_case(output="again", max_cells=2)
        a = ad.read_h5ad(self.root / "output/paul2015_wt_input.h5ad")
        b = ad.read_h5ad(self.root / "again/paul2015_wt_input.h5ad")
        self.assertEqual(list(a.obs_names), list(b.obs_names))
        before = MODULE.sha256(self.root / "output/paul2015_wt_input.h5ad")
        with self.assertRaises(FileExistsError):
            self.run_case()
        self.assertEqual(before, MODULE.sha256(self.root / "output/paul2015_wt_input.h5ad"))

    def test_qc_shortfall_and_missing_target_block(self):
        with self.assertRaisesRegex(ValueError, "eligible"):
            self.run_case(min_counts=100)
        self.counts = self.counts.replace('"Gata1"', '"OtherGene"')
        self.write()
        with self.assertRaisesRegex(ValueError, "Gata1"):
            self.run_case()

    def test_nonofficial_hashes_require_explicit_synthetic_flag(self):
        with self.assertRaisesRegex(ValueError, "synthetic_fixture"):
            self.run_case(synthetic_fixture=False)
        hashes = {name: MODULE.sha256(path) for name, path in self.paths.items()}
        hashes["counts"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.run_case(expected_hashes=hashes)


if __name__ == "__main__":
    unittest.main()
