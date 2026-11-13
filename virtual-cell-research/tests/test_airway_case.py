"""Identity contracts; numeric fixtures are synthetic, never experimental evidence."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/observed_airway_case.py"
SPEC = importlib.util.spec_from_file_location("observed_airway_case", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def synthetic_identities():
    geo, sra, columns = [], [], []
    fpkm = pd.DataFrame({"gene_id": ["synthetic_1", "synthetic_2", "synthetic_3"]})
    for d in range(4):
        for t, condition in enumerate(["Untreated", *module.TREATMENTS]):
            n = d * 4 + t + 1
            gsm, srx, ll = f"GSM_TEST_{n}", f"SRX_TEST_{n}", f"LL{n:02d}"
            donor, title = f"SYNTHETIC_D{d}", f"SYNTHETIC_D{d}_{condition}"
            geo.append({"geo_accession": gsm, "experiment": srx, "geo_title": title,
                        "donor": donor, "treatment": condition})
            sra.append({"geo_accession": gsm, "experiment": srx, "sra_title": title,
                        "sra_donor": donor, "sra_treatment": condition, "library_id": ll})
            column = condition + "_" + ll
            columns.append(column)
            # Distinct donor backgrounds expose accidental cross-donor pairing.
            fpkm[column] = np.asarray([2 + d, 20 + d * 10, 200 + d * 100]) * (t + 1)
    return pd.DataFrame(geo), pd.DataFrame(sra), columns, fpkm


class AirwayIdentityContracts(unittest.TestCase):
    def test_pinned_source_identity_allows_row_and_field_reordering(self):
        source = SCRIPT.parents[1] / "cases/airway-gse52778-drug-response/sample_mapping.csv"
        mapping = pd.read_csv(source, dtype=str, keep_default_na=False)
        expected = module.SOURCES["sra_mapping"]["canonical_identity_sha256"]
        self.assertEqual(module.verify_sra_identity(mapping), expected)
        shuffled = mapping.iloc[::-1, ::-1]
        self.assertEqual(module.verify_sra_identity(shuffled), expected)

    def test_every_pinned_identity_field_rejects_relabelling(self):
        source = SCRIPT.parents[1] / "cases/airway-gse52778-drug-response/sample_mapping.csv"
        mapping = pd.read_csv(source, dtype=str, keep_default_na=False)
        for field in module.SRA_IDENTITY_FIELDS:
            with self.subTest(field=field):
                bad = mapping.copy()
                bad.loc[0, field] = bad.loc[0, field] + "_WRONG"
                with self.assertRaisesRegex(ValueError, "pinned canonical identity"):
                    module.verify_sra_identity(bad)

    def test_source_row_and_expression_column_order_do_not_define_pairs(self):
        geo, sra, columns, fpkm = synthetic_identities()
        original = module.align_columns(geo, sra, columns)
        permuted = module.align_columns(geo.sample(frac=1, random_state=2),
                                        sra.sample(frac=1, random_state=3), list(reversed(columns)))
        first, donors, pairs = module.paired_responses(fpkm, original)
        second, donors2, pairs2 = module.paired_responses(fpkm[["gene_id", *reversed(columns)]], permuted)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(donors, donors2)
        pd.testing.assert_frame_equal(pairs, pairs2)
        self.assertEqual(first.shape, (3, 4, 3))

    def test_treatment_prefix_cannot_be_reassigned_to_another_library(self):
        geo, sra, columns, _ = synthetic_identities()
        columns[0], columns[1] = "Untreated_LL02", "Dex_LL01"
        with self.assertRaisesRegex(ValueError, "treatment/library identities"):
            module.align_columns(geo, sra, columns)

    def test_conflicting_geo_sra_donor_is_rejected(self):
        geo, sra, columns, _ = synthetic_identities()
        sra.loc[0, "sra_donor"] = "SYNTHETIC_D3"
        with self.assertRaisesRegex(ValueError, "donor, treatment or title disagrees"):
            module.align_columns(geo, sra, columns)

    def test_missing_sample_cannot_silently_reduce_pair_count(self):
        geo, sra, columns, _ = synthetic_identities()
        with self.assertRaisesRegex(ValueError, "sample sets differ"):
            module.align_columns(geo, sra.iloc[1:], columns)

    def test_missing_donor_condition_does_not_reuse_another_control(self):
        geo, sra, columns, fpkm = synthetic_identities()
        mapping = module.align_columns(geo, sra, columns)
        missing = mapping.loc[~((mapping.donor == "SYNTHETIC_D0") & (mapping.treatment == "Untreated"))]
        with self.assertRaisesRegex(ValueError, "Incomplete or ambiguous"):
            module.paired_responses(fpkm, missing)


if __name__ == "__main__":
    unittest.main()
