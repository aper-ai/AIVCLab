"""Contract tests with explicit synthetic fixtures, not model validation."""
import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/explain_result.py"
SPEC = importlib.util.spec_from_file_location("explain_result", SCRIPT)
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class ResultReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / "源结果"
        self.run.mkdir()

    def json(self, name, data):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    def csv(self, name, fields, rows):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fields)
            writer.writeheader()
            writer.writerows(rows)

    def artifact(self, name):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SYNTHETIC TEST FIXTURE; not parsed as a scientific matrix")

    def ledger(self):
        p = self.run / "provenance.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["artifacts"] = {str(f.relative_to(self.run).as_posix()): {"sha256": READER.digest(f), "bytes": f.stat().st_size}
                            for f in self.run.rglob("*") if f.is_file() and f != p}
        self.json("provenance.json", doc)

    def kang(self):
        self.json("provenance.json", {"case_id": "kang-ifnb-pbmc", "source_kind": "synthetic_test_fixture",
                                      "model_status": "not_run", "independent_validation": "not_assessed"})
        self.json("qc.json", {"status": "completed", "model_status": "not_run", "independent_validation": "not_assessed",
                             "replicate_unit": "donor", "donor_weighting": "equal", "scale": READER.KANG_SCALE,
                             "response_operation": "stim_minus_ctrl_within_same_donor_and_cell_type", "paired_donors": 2,
                             "source_genes": 3, "selected_cell_type": "细胞群 A", "selected_ctrl_cells": 4,
                             "selected_stim_cells": 4, "source_cells": 10, "included_singlets": 8, "pair_exclusions": []})
        self.csv("tables/donor_pairs.csv", ["donor", "cell_type", "status", "ctrl_n_cells", "stim_n_cells"],
                 [{"donor": d, "cell_type": "细胞群 A", "status": "included", "ctrl_n_cells": 2, "stim_n_cells": 2} for d in ["D1", "D2"]])
        self.genes = [dict(gene_id="ENSG1", gene_symbol="重复符号", n_paired_donors=2, mean_paired_difference=2,
                           positive_donors=2, negative_donors=0, sample_sd_across_donors=.5),
                      dict(gene_id="ENSG2", gene_symbol="重复符号", n_paired_donors=2, mean_paired_difference=-1,
                           positive_donors=0, negative_donors=2, sample_sd_across_donors=.2),
                      dict(gene_id="ENSG3", gene_symbol="零", n_paired_donors=2, mean_paired_difference=0,
                           positive_donors=0, negative_donors=0, sample_sd_across_donors=0)]
        self.csv("tables/gene_summary.csv", list(self.genes[0]), self.genes)
        self.json("figure_manifest.json", {"status": "skipped", "paths": [], "reason": "synthetic_fixture"})
        for name in ["raw/paired_responses.npz", "raw/pseudobulk_counts.npz", "tables/paired_responses.csv.gz", "report.md"]:
            self.artifact(name)
        self.ledger()

    def celloracle(self, mode="ko"):
        backend = {"name": "CellOracle", "version": "0.20.0"}
        chosen = 0 if mode == "ko" else .7
        target_mean = chosen - .5
        self.json("provenance.json", {"status": "completed", "backend": backend, "independent_validation": "none",
                                      "source_kind": "synthetic_test_fixture"})
        self.json("manifest.json", {"status": "completed", "backend": backend, "task": mode,
                                    "output_type": "network_simulation", "scientific_status": "simulated_unvalidated",
                                    "independent_validation": "none", "celloracle_internal_scale": READER.CELLORACLE_SCALE,
                                    "target_gene": "Target", "genes_used": 3,
                                    "parameters": {"oe_percentile": 95 if mode == "oe" else None}})
        self.json("validation.json", {"input_status": "passed", "simulation_status": "result_available", "delta_x_finite": True,
                                      "independent_validation": "none", "cells": 2, "target_gene_mean_delta": target_mean,
                                      "target_setting": {"chosen_value": chosen, "choice": "percentile_95" if mode == "oe" else "ko_zero"},
                                      "projection_status": "result_available", "mean_shift_magnitude": .5, "mean_random_shift_magnitude": .3,
                                      "group_column": "Plate_ID", "grn_scope": "whole"})
        self.csv("tables/gene_effects.csv", ["gene", "mean_delta", "mean_abs_delta", "fraction_cells_up", "fraction_cells_down"],
                 [{"gene": gene, "mean_delta": value, "mean_abs_delta": abs(value),
                   "fraction_cells_up": int(value > 0), "fraction_cells_down": int(value < 0)}
                  for gene, value in [("Target", target_mean), ("Positive", 1), ("Negative", -2)]])
        self.csv("tables/target_expression_setting.csv", ["cell", "baseline_imputed", "fixed_input_setting"],
                 [{"cell": cell, "baseline_imputed": val, "fixed_input_setting": chosen} for cell, val in [("C1", .2), ("C2", .8)]])
        self.csv("figures/figure_manifest.csv", ["status", "plot_path", "reason"], [{"status": "failed", "plot_path": "", "reason": "synthetic_figure_failure"}])
        for name in ["raw/baseline_imputed_expression.csv.gz", "raw/simulated_expression.csv.gz", "raw/delta_X.csv.gz", "tables/cell_state_shift.csv.gz", "report.md"]:
            self.artifact(name)

    def prnet(self):
        self.json("provenance.json", {"case_id": "prnet-reference-evaluation", "model_status": "executed", "independent_validation": "not_assessed",
                                      "source_kind": "synthetic_test_fixture"})
        self.json("manifest.json", {"case_id": "prnet-reference-evaluation", "backend": "PRnet", "status": "completed",
                                    "execution_status": "success", "model_status": "executed", "prediction_status": "success",
                                    "independent_validation": "not_assessed", "scale": READER.PRNET_SCALE, "conditions_completed": 2,
                                    "parameters": {"noise_draws": 16}})
        self.json("qc.json", {"finite_predictions": True, "all_profile_and_gene_ids_preserved": True, "scale": READER.PRNET_SCALE,
                             "profiles": 2, "genes": 3, "cross_rna_plate_profiles": 1})
        self.csv("tables/condition_index.csv", ["source_profile_id", "condition_id"],
                 [{"source_profile_id": "P1", "condition_id": "A"}, {"source_profile_id": "P2", "condition_id": "B"}])
        self.metrics = []
        for method in READER.METHODS:
            for i, profile in enumerate(["P1", "P2"]):
                self.metrics.append({"source_profile_id": profile, "condition_id": "AB"[i], "method": method,
                                     "rmse": [.2, .3][i] if method == "prnet_mean" else [.1, .2][i],
                                     "mae": .1, "pearson": None if method == "no_change" else .4,
                                     "post_expression_pearson": .8, "scale": READER.PRNET_SCALE})
        self.csv("tables/profile_metrics.csv", list(self.metrics[0]), self.metrics)
        summaries = {}
        for method in READER.METHODS:
            rows = [r for r in self.metrics if r["method"] == method]
            summaries[method] = {"mean_profile_" + key: READER.mean([r[key] for r in rows]) for key in ["rmse", "mae", "pearson"]}
            summaries[method].update(mean_profile_post_expression_pearson=.8, profile_pearson_defined=0 if method == "no_change" else 2)
        self.json("validation.json", {"independent_validation": "not_assessed", "training_overlap": "unknown",
                                      "holdout_status": "not_established", "metrics": summaries})
        self.csv("figures/figure_manifest.csv", ["status", "plot_path", "reason"], [{"status": "skipped", "plot_path": "", "reason": "synthetic_fixture"}])
        self.artifact("raw/reference_predictions.npz")
        self.artifact("report.md")
        self.ledger()

    def read(self, name="解读"):
        return READER.explain(self.run, self.root / name)

    def test_kang_both_signs_keep_unique_ids_and_original_bytes(self):
        self.kang()
        before = {str(p): p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        result = self.read()
        self.assertEqual(result["gene_changes"]["positive"][0]["gene_id"], "ENSG1")
        self.assertEqual(result["gene_changes"]["negative"][0]["gene_id"], "ENSG2")
        report = (self.root / "解读/interpretation.md").read_text(encoding="utf-8")
        self.assertIn("没有运行预测模型", report)
        self.assertIn("合成测试夹具", report)
        self.assertIn("细胞数不能代替独立重复数", report)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.run.rglob("*") if p.is_file()})
        self.assertTrue(all(x["matches_recorded_artifact"] for k, x in result["input_artifacts"].items() if k != "provenance.json"))

    def test_changed_source_values_change_report_not_hardcoded(self):
        self.kang()
        first = self.read("first")
        self.genes[0]["mean_paired_difference"] = 7.25
        self.csv("tables/gene_summary.csv", list(self.genes[0]), self.genes)
        self.ledger()
        second = self.read("second")
        self.assertNotEqual(first["gene_changes"], second["gene_changes"])
        self.assertIn("7.25", (self.root / "second/interpretation.md").read_text(encoding="utf-8"))

    def test_kang_duplicate_ids_fail_instead_of_using_symbol(self):
        self.kang()
        self.genes[1]["gene_id"] = "ENSG1"
        self.csv("tables/gene_summary.csv", list(self.genes[0]), self.genes)
        self.ledger()
        with self.assertRaisesRegex(ValueError, "重复"):
            self.read()
        self.assertEqual(json.loads((self.root / "解读/error.json").read_text(encoding="utf-8"))["status"], "failed")

    def test_conflicting_donor_count_is_not_reported_as_success(self):
        self.kang()
        qc = json.loads((self.run / "qc.json").read_text(encoding="utf-8"))
        qc["paired_donors"] = 3
        self.json("qc.json", qc)
        self.ledger()
        with self.assertRaisesRegex(ValueError, "供体数不一致"):
            self.read()

    def test_artifact_hash_mismatch_is_blocked(self):
        self.kang()
        self.genes[0]["mean_paired_difference"] = 8
        self.csv("tables/gene_summary.csv", list(self.genes[0]), self.genes)
        with self.assertRaisesRegex(ValueError, "哈希或大小不一致"):
            self.read()
        self.assertFalse((self.root / "解读/interpretation.md").exists())

    def test_no_eligible_pairs_explained_without_invented_responses(self):
        self.kang()
        qc = json.loads((self.run / "qc.json").read_text(encoding="utf-8"))
        qc.update(status="completed_without_paired_response", paired_donors=0, selected_ctrl_cells=0, selected_stim_cells=0)
        self.json("qc.json", qc)
        self.csv("tables/donor_pairs.csv", ["donor", "cell_type", "status", "ctrl_n_cells", "stim_n_cells"],
                 [{"donor": d, "cell_type": "细胞群 A", "status": "excluded", "ctrl_n_cells": 2, "stim_n_cells": 2} for d in ["D1", "D2"]])
        self.csv("tables/gene_summary.csv", ["gene_id", "gene_symbol", "n_paired_donors"],
                 [{"gene_id": row["gene_id"], "gene_symbol": row["gene_symbol"], "n_paired_donors": 0} for row in self.genes])
        self.ledger()
        result = self.read()
        self.assertIsNone(result["gene_changes"])
        self.assertEqual(result["execution_status"], "completed_without_paired_response")
        self.assertIn("没有有效供体配对", (self.root / "解读/interpretation.md").read_text(encoding="utf-8"))

    def test_celloracle_ko_excludes_target_from_downstream_list(self):
        self.celloracle()
        result = self.read()
        self.assertEqual(result["gene_changes"]["negative"][0]["gene_id"], "Negative")
        self.assertEqual(result["target_mean_delta"], -.5)
        self.assertEqual(result["independent_validation"], "not_assessed")
        report = (self.root / "解读/interpretation.md").read_text(encoding="utf-8")
        self.assertIn("不是实测扰动差异基因", report)
        self.assertIn("图状态：`failed`", report)

    def test_celloracle_oe_reports_cells_decreased_and_setting_basis(self):
        self.celloracle("oe")
        result = self.read()
        self.assertEqual(result["cells_above_target_setting"], 1)
        report = (self.root / "解读/interpretation.md").read_text(encoding="utf-8")
        self.assertIn("percentile_95", report)
        self.assertIn("1 / 2", report)
        self.assertIn("目标输入下调", report)

    def test_incomplete_celloracle_run_is_not_promoted(self):
        self.celloracle()
        manifest = json.loads((self.run / "manifest.json").read_text(encoding="utf-8"))
        manifest["status"] = "failed"
        self.json("manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "未完成"):
            self.read()

    def test_prnet_recomputes_baselines_and_keeps_undefined_correlation(self):
        self.prnet()
        self.metrics.reverse()
        self.csv("tables/profile_metrics.csv", list(self.metrics[0]), self.metrics)
        self.ledger()
        result = self.read()
        self.assertAlmostEqual(result["metrics"]["prnet_mean"]["mean_profile_rmse"], .25)
        self.assertIsNone(result["metrics"]["no_change"]["mean_profile_pearson"])
        self.assertEqual(result["comparison"], "higher_rmse")
        self.assertEqual(result["profiles_higher_rmse"], 2)
        self.assertIn("高于零响应参照", (self.root / "解读/interpretation.md").read_text(encoding="utf-8"))

    def test_prnet_summary_must_match_source_metrics(self):
        self.prnet()
        validation = json.loads((self.run / "validation.json").read_text(encoding="utf-8"))
        validation["metrics"]["prnet_mean"]["mean_profile_rmse"] = .01
        self.json("validation.json", validation)
        self.ledger()
        with self.assertRaisesRegex(ValueError, "重算不一致"):
            self.read()

    def test_zero_response_correlation_cannot_be_filled_with_zero(self):
        self.prnet()
        for row in self.metrics:
            if row["method"] == "no_change":
                row["pearson"] = 0
        self.csv("tables/profile_metrics.csv", list(self.metrics[0]), self.metrics)
        self.ledger()
        with self.assertRaisesRegex(ValueError, "应未定义"):
            self.read()

    def test_prnet_wrong_profile_condition_is_blocked(self):
        self.prnet()
        self.metrics[0]["condition_id"] = "B"
        self.csv("tables/profile_metrics.csv", list(self.metrics[0]), self.metrics)
        self.ledger()
        with self.assertRaisesRegex(ValueError, "条件标识"):
            self.read()

    def test_unknown_contract_and_missing_core_write_failure_record(self):
        self.json("provenance.json", {"project": "some other analysis"})
        with self.assertRaisesRegex(ValueError, "未识别"):
            self.read("unknown")
        self.assertTrue((self.root / "unknown/error.json").is_file())
        (self.run / "provenance.json").unlink()
        with self.assertRaisesRegex(ValueError, "缺少必要文件"):
            self.read("missing")
        self.assertTrue((self.root / "missing/error.json").is_file())

    def test_existing_output_is_never_modified(self):
        self.kang()
        out = self.root / "解读"
        out.mkdir()
        keep = out / "keep"
        keep.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.read()
        self.assertEqual([p.name for p in out.iterdir()], ["keep"])
        self.assertEqual(keep.read_bytes(), b"existing")

    def test_nonfinite_and_duplicate_json_are_rejected(self):
        (self.run / "provenance.json").write_text('{"value": NaN}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "非有限"):
            self.read("nan")
        (self.run / "provenance.json").write_text('{"case_id": "x", "case_id": "y"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "重复"):
            self.read("duplicate")

    def test_json_resource_limit_is_enforced(self):
        self.kang()
        with patch.object(READER, "MAX_JSON_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "限额"):
                self.read()
        self.assertTrue((self.root / "解读/error.json").is_file())

    def test_figure_cannot_point_outside_run_directory(self):
        self.kang()
        outside = self.root / "private.png"
        outside.write_bytes(b"must not be read")
        self.json("figure_manifest.json", {"status": "generated", "paths": ["../private.png"]})
        self.ledger()
        with self.assertRaisesRegex(ValueError, "越界"):
            self.read()
        record = json.loads((self.root / "解读/error.json").read_text(encoding="utf-8"))
        self.assertNotIn("../private.png", record["input_artifacts"])

    def test_help_runs_without_site_packages(self):
        result = subprocess.run([sys.executable, "-S", str(SCRIPT), "--help"], capture_output=True,
                                text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--run-dir", result.stdout)


if __name__ == "__main__":
    unittest.main()
