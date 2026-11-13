from __future__ import annotations

import gzip
import json
import os
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from run_data import (
    MAX_TABLE_BYTES,
    RunDataError,
    compare_runs,
    export_report,
    load_run,
    read_table,
    resolve_asset,
)


PROJECT = Path(__file__).resolve().parent


class RunDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=PROJECT)
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)

    def run_folder(self, name, **overrides):
        root = self.temporary / name
        root.mkdir()
        (root / "tables").mkdir()
        (root / "figures").mkdir()
        data = {"run_id": name, "backend": "test backend", "task": "public sample",
                "dataset": "test dataset", "parameters": {}, **overrides}
        (root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        return root

    def test_load_indexes_supported_assets_and_preserves_metadata(self):
        root = self.run_folder("样例", parameters={"nested": {"seed": None}})
        (root / "validation.json").write_text('{"status":"unvalidated"}', encoding="utf-8")
        (root / "provenance.json").write_text('{"source_url":"https://example.org/test"}', encoding="utf-8")
        (root / "report.md").write_text("报告文本", encoding="utf-8")
        (root / "tables" / "readme.exe").touch()
        (root / "tables" / "saved.pkl").touch()
        (root / "tables" / "table.CSV").write_text("label,value\n一,1\n", encoding="utf-8-sig")
        (root / "figures" / "active.svg").touch()
        (root / "figures" / "plot.png").touch()
        run = load_run(root)
        self.assertEqual(run.run_id, "样例")
        self.assertEqual(run.validation["status"], "unvalidated")
        self.assertEqual(run.parameters, {"nested": {"seed": None}})
        self.assertEqual(run.source_url, "https://example.org/test")
        self.assertEqual(run.report, "报告文本")
        self.assertEqual(tuple(path.name for path in run.tables), ("table.CSV",))
        self.assertEqual(tuple(path.name for path in run.figures), ("plot.png",))
        self.assertEqual(read_table(run.tables[0], root=run.root).rows, (("一", "1"),))

    def test_indexes_upstream_figure_manifest_and_raw_names_without_opening_raw(self):
        root = self.run_folder("upstream")
        (root / "figures" / "figure_manifest.csv").write_text("file,description\nsample.png,Example\n", encoding="utf-8")
        (root / "errors.jsonl").write_text('{"text":"<sample error>"}\n', encoding="utf-8")
        (root / "raw").mkdir()
        (root / "raw" / "neutral.bin").write_bytes(b"DO NOT READ RAW PAYLOAD CONTENTS")
        run = load_run(root)
        self.assertEqual([path.name for path in run.tables], ["figure_manifest.csv"])
        self.assertEqual([path.name for path in run.raw_files], ["neutral.bin"])
        self.assertIn("<sample error>", run.errors_text)
        self.assertIn("未找到", compare_runs(run, run).metric_notes[0])
        report = export_report(self.temporary / "upstream.html", run).read_text(encoding="utf-8")
        self.assertIn("neutral.bin", report)
        self.assertIn("&lt;sample error&gt;", report)
        self.assertNotIn("DO NOT READ RAW PAYLOAD CONTENTS", report)

    def test_rejects_bad_required_manifest_but_warns_for_optional_document(self):
        root = self.run_folder("bad")
        for invalid_json in ('{"name":1,"name":2}', '{"value":1e999}', '[]', r'{"name":"\ud800"}'):
            with self.subTest(invalid_json=invalid_json):
                (root / "manifest.json").write_text(invalid_json, encoding="utf-8")
                with self.assertRaises(RunDataError):
                    load_run(root)
        (root / "manifest.json").unlink()
        with self.assertRaisesRegex(RunDataError, "manifest.json"):
            load_run(root)
        root = self.run_folder("optional")
        (root / "validation.json").write_text("[]", encoding="utf-8")
        result = load_run(root)
        self.assertEqual(result.validation, {})
        self.assertIn("validation.json", result.warnings[0])

    def test_reads_gzip_and_stops_preview_at_row_limit(self):
        root = self.run_folder("gzip")
        path = root / "tables" / "a.csv.gz"
        path.write_bytes(gzip.compress('label,value\n"first, item",1\nsecond,2\n'.encode()))
        preview = read_table(path, limit=1, root=root)
        self.assertEqual(preview.headers, ("label", "value"))
        self.assertEqual(preview.rows, (("first, item", "1"),))
        self.assertTrue(preview.truncated)
        self.assertFalse(read_table(path, limit=2, root=root).truncated)
        path.write_bytes(gzip.compress(b"a" * (MAX_TABLE_BYTES + 1)))
        with self.assertRaisesRegex(RunDataError, "解压后"):
            read_table(path, root=root)
        path.write_bytes(b"not a gzip archive")
        with self.assertRaises(RunDataError):
            read_table(path, root=root)

    def test_rejects_table_with_inconsistent_rows_and_outside_paths(self):
        root = self.run_folder("safe")
        path = root / "tables" / "bad.csv"
        path.write_text("first,second\nmissing column\n", encoding="utf-8")
        with self.assertRaisesRegex(RunDataError, "列数不一致"):
            read_table(path, root=root)
        outside = self.temporary / "outside.csv"
        outside.write_text("a,b\n1,2\n", encoding="utf-8")
        with self.assertRaises(RunDataError):
            resolve_asset(root, "../outside.csv")
        with self.assertRaises(RunDataError):
            read_table(outside, root=root)

    def test_skips_symlink_to_file_outside_result_root(self):
        root = self.run_folder("safe")
        outside = self.temporary / "outside.csv"
        outside.write_text("a,b\n1,2\n", encoding="utf-8")
        path = root / "tables" / "redirect.csv"
        try:
            path.symlink_to(outside)
        except OSError:
            self.skipTest("当前 Windows 用户缺少创建符号链接的权限")
        self.assertEqual(load_run(root).tables, ())
        with self.assertRaises(RunDataError):
            read_table(path, root=root)

    @unittest.skipUnless(os.name == "nt", "Windows directory junction test")
    def test_skips_windows_junction_to_directory_outside_result_root(self):
        root = self.run_folder("safe")
        outside = self.temporary / "outside"
        outside.mkdir()
        (outside / "outside.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        junction = root / "tables" / "redirect"
        creation = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True)
        if creation.returncode != 0:
            self.skipTest("无法创建 Windows 目录联接")
        self.addCleanup(junction.rmdir)
        self.assertEqual(load_run(root).tables, ())
        with self.assertRaises(RunDataError):
            read_table(junction / "outside.csv", root=root)

    def test_comparison_distinguishes_missing_null_and_boolean_number(self):
        left = load_run(self.run_folder("left", parameters={"one": 1, "none": None}))
        right = load_run(self.run_folder("right", parameters={"one": True, "extra": None}))
        comparison = compare_runs(left, right)
        self.assertTrue(comparison.compatible)
        rows = {row.field: row for row in comparison.rows}
        self.assertEqual((rows['参数["none"]'].left, rows['参数["none"]'].right), ("null", "（缺失）"))
        self.assertEqual((rows['参数["extra"]'].left, rows['参数["extra"]'].right), ("（缺失）", "null"))
        self.assertTrue(rows['参数["one"]'].changed)

    def test_comparison_skips_changed_context_and_metrics_with_different_units(self):
        left = self.run_folder("left", source_batch="same batch")
        right = self.run_folder("right", source_batch="same batch")
        outside = self.run_folder("outside", source_batch="other batch")
        for folder, lines in ((left, "A,0.10,u\nB,7,u\nC,5,u\n"), (right, "A,0.22,u\nB,8,v\nC,NaN,u\nD,1,u\n"), (outside, "A,0.30,u\n")):
            (folder / "tables" / "metrics.csv").write_text("metric,value,unit\n" + lines, encoding="utf-8")
        result = compare_runs(load_run(left), load_run(right))
        self.assertEqual([(row.name, row.delta, row.unit) for row in result.metrics], [("A", Decimal("0.12"), "u")])
        self.assertEqual(len(result.metric_notes), 3)
        result = compare_runs(load_run(left), load_run(outside))
        self.assertFalse(result.compatible)
        self.assertFalse(result.metrics)
        self.assertIn("来源批次", result.reasons[0])

    def test_report_escapes_input_disables_active_links_and_leaves_source_intact(self):
        left = self.run_folder("left", run_id="<script>sample</script>", source_url="javascript:evil()")
        right = self.run_folder("right", source_url="https://example.org/sample?a=1&b=2")
        (left / "report.md").write_text('<img src="https://example.org/tracker">', encoding="utf-8")
        (left / "tables" / "t.csv").write_text("name,value\n<b>,1\n", encoding="utf-8")
        original = (left / "manifest.json").read_bytes()
        left_run, right_run = load_run(left), load_run(right)
        with self.assertRaises(RunDataError):
            export_report(left / "report.html", left_run, right_run)
        output = self.temporary / "report.html"
        self.assertEqual(export_report(output, left_run, right_run), output)
        report = output.read_text(encoding="utf-8")
        self.assertNotIn("<script>", report)
        self.assertNotIn('href="javascript:', report)
        self.assertNotIn('<img src="https:', report)
        self.assertIn("&lt;script&gt;sample&lt;/script&gt;", report)
        self.assertIn("&lt;b&gt;", report)
        self.assertIn('href="https://example.org/sample?a=1&amp;b=2"', report)
        self.assertEqual((left / "manifest.json").read_bytes(), original)

    def test_public_sample_runs_and_report_match_historical_records(self):
        samples = PROJECT / "samples"
        first = load_run(samples / "aivc-stat3-ko")
        second = load_run(samples / "aivc-jun-ko")
        self.assertEqual(first.validation["status"], "unvalidated")
        self.assertEqual(first.manifest["source_batch"], second.manifest["source_batch"])
        result = compare_runs(first, second)
        self.assertTrue(result.compatible, result.reasons)
        expected = {"位移幅度": Decimal("0.035"), "随机对照": Decimal("0.013"), "向量差长度": Decimal("0.024")}
        self.assertEqual({row.name: row.delta for row in result.metrics}, expected)
        report = export_report(self.temporary / "samples.html", first, second).read_text(encoding="utf-8")
        self.assertIn("公开历史批次中的条件结果", report)
        self.assertEqual(report.count("data:image/png;base64,"), 2)
        for value in expected.values():
            self.assertIn(str(value), report)


if __name__ == "__main__":
    unittest.main()
