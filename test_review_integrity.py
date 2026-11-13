"""Regression cases for scientific status, context and complete source export.

These test local result review only; they do not run or validate any model.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_data import compare_runs, export_report, load_run, read_table, review_status, status_label


class ReviewIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def bundle(self, name, *, manifest=None, validation=None, provenance=None, metrics=True):
        root = self.root / name
        (root / "tables").mkdir(parents=True)
        data = {"run_id": name, "backend": "Model", "task": "drug", "dataset": "GSE-example",
                "source_batch": "controlled-batch", **(manifest or {})}
        (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        for filename, record in (("validation.json", validation), ("provenance.json", provenance)):
            if record is not None:
                (root / filename).write_text(json.dumps(record), encoding="utf-8")
        if metrics:
            (root / "tables" / "metrics.csv").write_text("metric,value,unit\nresponse,0.25,model units\n", encoding="utf-8")
        return root

    def test_technical_pass_is_not_independent_validation(self):
        root = self.bundle("technical", manifest={"status": "completed"}, validation={"status": "passed"})
        run = load_run(root)
        status = review_status(run)
        self.assertEqual(status.execution_status, "result_available")
        self.assertEqual(status.independent_validation, "unknown")
        self.assertEqual(run.validation, {"status": "passed"})
        self.assertTrue(any("不能替代独立验证" in note for note in status.notes))
        report = export_report(self.root / "technical.html", run).read_text(encoding="utf-8")
        self.assertIn("运行执行", report)
        self.assertIn("候选排名", report)
        self.assertIn("未记录 / 未知", report)
        self.assertNotIn("上游声明已验证", report)

    def test_validation_status_passed_remains_unknown_without_independent_semantics(self):
        status = review_status(load_run(self.bundle("ambiguous", validation={"validation_status": "passed"})))
        self.assertEqual(status.independent_validation, "unknown")

    def test_generic_validated_can_describe_schema_checks_and_is_not_independent_evidence(self):
        run = load_run(self.bundle("schema-validated", validation={
            "status": "validated", "checks": [{"name": "CSV schema", "status": "passed"}]}))
        self.assertEqual(review_status(run).independent_validation, "unknown")
        report = export_report(self.root / "schema.html", run).read_text(encoding="utf-8")
        self.assertNotIn("上游声明已验证", report)

    def test_generic_status_object_is_not_independent_validation(self):
        run = load_run(self.bundle("schema-object", validation={
            "status": {"status": "validated", "kind": "CSV schema"}}))
        self.assertEqual(review_status(run).independent_validation, "unknown")
        report = export_report(self.root / "schema-object.html", run).read_text(encoding="utf-8")
        self.assertNotIn("上游声明已验证", report)

    def test_explicit_independent_validation_is_a_declaration_and_conflicts_are_visible(self):
        run = load_run(self.bundle("declared", validation={"independent_validation": {"status": "passed", "data": "heldout"}}))
        self.assertEqual(review_status(run).independent_validation, "declared_validated")
        self.assertIn("未复核证据", status_label(review_status(run).independent_validation))
        run = load_run(self.bundle("conflict", manifest={"validation_status": "validated"},
                                   validation={"independent_validation": "none"}))
        self.assertEqual(review_status(run).independent_validation, "conflicting")
        self.assertEqual(status_label("unvalidated"), "未经独立验证")

    def test_response_and_ranking_stay_separate_from_run_and_validation(self):
        run = load_run(self.bundle("separate", manifest={"status": "completed"}, validation={
            "validation_status": "unvalidated", "degeneracy_check": {
                "response_status": "varying", "ranking_status": "unresolved"}}))
        status = review_status(run)
        self.assertEqual((status.execution_status, status.response_status, status.ranking_status,
                          status.independent_validation),
                         ("result_available", "varying", "unresolved", "unvalidated"))
        self.assertIn(("ranking_status", "validation.json.degeneracy_check.ranking_status"), status.sources)

    def test_same_labels_cannot_hide_different_baseline_or_cell_background(self):
        left = load_run(self.bundle("left", validation={"cell_background": "patient", "baseline_source": "user"}))
        right = load_run(self.bundle("right", provenance={"cell_background": "A549", "baseline_source": "model_builtin"}))
        result = compare_runs(left, right)
        self.assertFalse(result.compatible)
        self.assertFalse(result.metrics)
        self.assertTrue(any("基线来源不一致" in reason for reason in result.reasons))
        self.assertTrue(any("细胞背景不一致" in reason for reason in result.reasons))

    def test_unknown_and_empty_context_are_not_equivalent_verified_context(self):
        for value in ("unknown", "", None):
            with self.subTest(value=value):
                a = self.bundle(f"a-{str(value)}", validation={"response_scale": value})
                b = self.bundle(f"b-{str(value)}", validation={"response_scale": value})
                result = compare_runs(load_run(a), load_run(b))
                self.assertFalse(result.compatible)
                self.assertTrue(any("响应尺度缺失或未知" in reason for reason in result.reasons))
        left = load_run(self.bundle("null", validation={"baseline_source": None}))
        right = load_run(self.bundle("empty", validation={"baseline_source": ""}))
        row = next(row for row in compare_runs(left, right).rows if row.field == "基线来源")
        self.assertEqual((row.left, row.right), ("null", '""'))

    def test_internal_context_conflicts_cannot_be_hidden_by_identical_runs(self):
        root = self.bundle("internally-conflicting", manifest={"response_scale": "log1p"},
                           validation={"response_scale": "linear"})
        result = compare_runs(load_run(root), load_run(root))
        self.assertFalse(result.compatible)
        self.assertTrue(any("上游记录中冲突" in reason for reason in result.reasons))

    def test_numeric_comparison_requires_a_shared_source_anchor(self):
        left = load_run(self.bundle("no-anchor-left", manifest={"source_batch": None}))
        right = load_run(self.bundle("no-anchor-right", manifest={"source_batch": None}))
        self.assertFalse(compare_runs(left, right).compatible)
        for run in (left, right):
            data = dict(run.manifest)
            data.pop("source_batch")
            (run.root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        result = compare_runs(load_run(left.root), load_run(right.root))
        self.assertFalse(result.compatible)
        self.assertFalse(result.metrics)
        self.assertTrue(any("数据指纹" in reason for reason in result.reasons))

    def test_explicit_comparison_contract_is_extensible(self):
        context = {"context_id": "same-input-and-measurement", "response_scale": "log1p",
                   "gene_order_sha256": "stable-gene-order", "custom_metric_definition": "mean delta"}
        a = self.bundle("contract-a", manifest={"comparison_context": context})
        b = self.bundle("contract-b", manifest={"comparison_context": context})
        for root in (a, b):
            data = json.loads((root / "manifest.json").read_text())
            data.pop("source_batch")
            (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(compare_runs(load_run(a), load_run(b)).metrics)
        data = json.loads((b / "manifest.json").read_text())
        data["comparison_context"]["custom_metric_definition"] = "median delta"
        (b / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(compare_runs(load_run(a), load_run(b)).metrics)

    def test_comparison_contract_cannot_override_existing_scientific_or_core_metadata(self):
        cases = (("cell_background", "patient", "A549"),
                 ("source_batch", "original-batch", "different-batch"),
                 ("backend", "PRnet", "chemCPA"))
        for key, actual, conflicting in cases:
            with self.subTest(key=key):
                manifest = {key: actual, "comparison_context": {key: conflicting, "context_id": "same"}}
                a = load_run(self.bundle(f"conflict-a-{key}", manifest=manifest))
                b = load_run(self.bundle(f"conflict-b-{key}", manifest=manifest))
                result = compare_runs(a, b)
                self.assertFalse(result.compatible)
                self.assertFalse(result.metrics)
                self.assertTrue(any("上游记录中冲突" in reason for reason in result.reasons))
        common = {"cell_background": "A549", "comparison_context": {"cell_background": "A549"}}
        self.assertTrue(compare_runs(load_run(self.bundle("consistent-a", manifest=common)),
                                     load_run(self.bundle("consistent-b", manifest=common))).metrics)

    def test_upstream_checkpoint_prefix_hash_is_checked_without_equating_it_to_a_full_hash(self):
        a = load_run(self.bundle("hash-a", validation={"checkpoint_sha256_16": "a" * 16}))
        b = load_run(self.bundle("hash-b", validation={"checkpoint_sha256_16": "b" * 16}))
        self.assertFalse(compare_runs(a, b).metrics)
        full = load_run(self.bundle("hash-full", validation={"checkpoint_sha256": "a" * 64}))
        result = compare_runs(a, full)
        self.assertFalse(result.compatible)
        self.assertFalse(result.metrics)
        self.assertTrue(any("权重" in reason for reason in result.reasons))

    def test_skipped_runs_and_failed_quality_checks_cannot_compare_untyped_metric_tables(self):
        a = load_run(self.bundle("quality-complete"))
        cases = (({"status": "skipped"}, {}, "运行状态"),
                 ({"status": "not_applicable"}, {}, "运行状态"),
                 ({"status": "completed"}, {"response_status": "failed"}, "响应检查"),
                 ({"status": "completed"}, {"ranking_status": "failed"}, "排名检查"))
        for number, (manifest, validation, expected) in enumerate(cases):
            with self.subTest(case=number):
                b = load_run(self.bundle(f"quality-invalid-{number}", manifest=manifest, validation=validation))
                result = compare_runs(a, b)
                self.assertFalse(result.compatible)
                self.assertFalse(result.metrics)
                self.assertTrue(any(expected in reason for reason in result.reasons))
        unresolved = load_run(self.bundle("quality-unresolved", manifest={"status": "completed"},
                                           validation={"response_status": "varying", "ranking_status": "unresolved"}))
        self.assertTrue(compare_runs(a, unresolved).metrics)

    def test_failed_execution_and_unknown_units_do_not_produce_deltas(self):
        a = self.bundle("valid")
        b = self.bundle("failed", manifest={"status": "failed"})
        self.assertFalse(compare_runs(load_run(a), load_run(b)).metrics)
        c = self.bundle("unknown-unit")
        for root in (a, c):
            (root / "tables" / "metrics.csv").write_text("metric,value,unit\nresponse,1,unknown\n", encoding="utf-8")
        result = compare_runs(load_run(a), load_run(c))
        self.assertFalse(result.metrics)
        self.assertTrue(any("单位缺失" in note for note in result.metric_notes))

    def test_wide_gene_tables_remain_readable_without_losing_the_source(self):
        root = self.bundle("wide", metrics=False)
        path = root / "tables" / "all_conditions_gene_response.csv"
        headers = ["drug"] + [f"gene_{i}" for i in range(978)]
        values = ["drug-a"] + [str(i) for i in range(978)]
        raw = (",".join(headers) + "\n" + ",".join(values) + "\n").encode()
        path.write_bytes(raw)
        preview = read_table(path, root=root)
        self.assertEqual(preview.total_columns, 979)
        self.assertEqual(len(preview.headers), 512)
        self.assertTrue(preview.columns_truncated)
        self.assertFalse(preview.truncated)
        report = export_report(self.root / "wide.html", load_run(root)).read_text(encoding="utf-8")
        encoded = re.search(r'href="data:text/csv;charset=utf-8;base64,([A-Za-z0-9+/=]+)"', report).group(1)
        self.assertEqual(base64.b64decode(encoded), raw)
        self.assertIn("源表共 979 列", report)

    def test_export_preserves_complete_csv_gzip_order_and_hashes(self):
        root = self.bundle("full", metrics=False)
        source = b"condition_id,drug,dose,score\n" + b"".join(
            f"c{i},drug-{19-i},{i % 3},\n".encode() for i in range(20))
        compressed = gzip.compress(source, mtime=0)
        (root / "tables" / "conditions.csv.gz").write_bytes(compressed)
        report = export_report(self.root / "full.html", load_run(root)).read_text(encoding="utf-8")
        encoded = re.search(r'href="data:application/gzip;base64,([A-Za-z0-9+/=]+)"', report).group(1)
        self.assertEqual(base64.b64decode(encoded), compressed)
        self.assertEqual(gzip.decompress(base64.b64decode(encoded)), source)
        self.assertIn(hashlib.sha256(compressed).hexdigest(), report)
        self.assertIn("仅展示前 12 行", report)
        self.assertEqual((root / "tables" / "conditions.csv.gz").read_bytes(), compressed)

    def test_export_budget_is_shared_and_omissions_are_explicit(self):
        a = self.bundle("budget-a")
        b = self.bundle("budget-b")
        one_size = (a / "tables" / "metrics.csv").stat().st_size
        with patch("run_data.MAX_REPORT_TABLE_BYTES", one_size):
            report = export_report(self.root / "bounded.html", load_run(a), load_run(b)).read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'href="data:text/csv;', report)), 1)
        self.assertIn("未内嵌源表", report)
        self.assertIn("剩余源表附件预算", report)


if __name__ == "__main__":
    unittest.main()
