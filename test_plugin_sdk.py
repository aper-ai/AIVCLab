"""Executable plugin contract checks; no Qt, models, LLMs or network required."""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from run_data import load_run, review_status
from vcw_core import PluginError, discover_plugins, load_plugin, run_plugin
from vcw_core.sdk import validate_request

PROJECT = Path(__file__).resolve().parent
EXAMPLE = PROJECT / "examples" / "plugins" / "csv_qc"
EMPTY_SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
OUTPUT_SCRIPT = '''import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--request')
p.add_argument('--output')
a = p.parse_args()
out = Path(a.output)
(out / 'tables').mkdir()
(out / 'tables' / 'values.csv').write_text('metric,value,unit\\nA,2,count\\n', encoding='utf-8')
(out / 'result.json').write_text(json.dumps({'api_version':'0.1', 'summary':'test result',
    'artifacts':[{'type':'table', 'path':'tables/values.csv'}]}), encoding='utf-8')
'''


class PluginSdkTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def plugin(self, name="third-party", script=OUTPUT_SCRIPT, **changes):
        directory = self.root / name
        directory.mkdir()
        descriptor = {"api_version": "0.1", "id": name, "version": "0.1.0", "kind": "data_qc",
                      "input_schema": EMPTY_SCHEMA, "output_types": ["table"], "entrypoint": "run.py", **changes}
        (directory / "plugin.json").write_text(json.dumps(descriptor), encoding="utf-8")
        (directory / "run.py").write_text(script, encoding="utf-8")
        return directory

    def run_fixture(self, directory, **kwargs):
        return run_plugin(directory, {}, self.root / "results", python_executable=sys.executable, **kwargs)

    def test_discovery_has_no_python_execution_side_effect(self):
        marker = self.root / "must-not-exist"
        directory = self.plugin(script=f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise RuntimeError('do not run')")
        self.assertEqual(discover_plugins(self.root)[0].id, "third-party")
        self.assertFalse(marker.exists())
        self.assertEqual(load_plugin(directory).entrypoint.name, "run.py")

    def test_duplicate_ids_and_incompatible_api_are_rejected(self):
        self.plugin("one", id="same")
        self.plugin("two", id="same")
        with self.assertRaisesRegex(PluginError, "Duplicate plugin id"):
            discover_plugins(self.root)
        incompatible = self.plugin("future", api_version="9.9")
        with self.assertRaisesRegex(PluginError, "api_version"):
            load_plugin(incompatible)

    def test_unsafe_entrypoint_and_unsupported_schema_are_rejected(self):
        directory = self.plugin(entrypoint="../outside.py")
        (self.root / "outside.py").write_text("pass", encoding="utf-8")
        with self.assertRaisesRegex(PluginError, "escapes"):
            load_plugin(directory)
        bad = self.plugin("schema", input_schema={"type": "object", "$ref": "https://example.org/schema"})
        with self.assertRaisesRegex(PluginError, "Unsupported"):
            load_plugin(bad)

    def test_request_schema_rejects_wrong_types_unknown_keys_and_nonfinite_values(self):
        schema = {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 8}},
                  "required": ["count"], "additionalProperties": False}
        for request in ({}, {"count": True}, {"count": 0}, {"count": 9}, {"count": 2, "extra": 1},
                        {"count": float("inf")}, {"count": 10 ** 400}):
            with self.subTest(request=str(request)[:80]), self.assertRaises(PluginError):
                validate_request(request, schema)
        validate_request({"count": 2}, schema)

    def test_third_party_plugin_runs_without_core_registration(self):
        result = self.run_fixture(self.plugin())
        self.assertEqual(result.status, "succeeded", result.error)
        run = load_run(result.run_dir)
        self.assertEqual(run.backend, "third-party")
        self.assertEqual([path.name for path in run.tables], ["values.csv"])
        review = review_status(run)
        self.assertEqual(review.execution_status, "result_available")
        self.assertEqual(review.independent_validation, "unvalidated")
        states = [json.loads(line)["state"] for line in (result.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual(states, ["before", "running", "succeeded"])
        self.assertTrue((result.run_dir / "logs" / "stdout.log").is_file())
        self.assertEqual(len(run.manifest["artifacts"][0]["sha256"]), 64)

    def test_real_csv_qc_in_chinese_paths_has_correct_metrics_and_preserves_input(self):
        directory = self.root / "中文插件"
        shutil.copytree(EXAMPLE, directory)
        source = directory / "example-input.csv"
        original = source.read_bytes()
        request = {"input_csv": str(source), "input_scale": "raw_counts"}
        result = run_plugin(directory, request, self.root / "中文结果", python_executable=sys.executable)
        self.assertEqual(result.status, "succeeded", result.error)
        with (result.run_dir / "tables" / "qc_metrics.csv").open(encoding="utf-8", newline="") as stream:
            metrics = {row["metric"]: float(row["value"]) for row in csv.DictReader(stream)}
        self.assertEqual(metrics["cell_count"], 3)
        self.assertEqual(metrics["gene_count"], 3)
        self.assertEqual(metrics["expression_total"], 12)
        self.assertEqual(metrics["nonzero_entries"], 4)
        self.assertAlmostEqual(metrics["nonzero_fraction"], 4 / 9)
        self.assertEqual(metrics["zero_expression_cells"], 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertIn("没有执行", load_run(result.run_dir).report)

    def test_invalid_csv_is_failed_and_never_published_as_success(self):
        source = self.root / "invalid.csv"
        source.write_text("cell_id,G1\na,NaN\n", encoding="utf-8")
        result = run_plugin(EXAMPLE, {"input_csv": str(source)}, self.root / "results")
        self.assertEqual(result.status, "failed")
        self.assertFalse((result.run_dir / "tables").exists())
        self.assertIn("非有限", (result.run_dir / "logs" / "stderr.log").read_text(encoding="utf-8"))

    def test_large_raw_counts_are_not_silently_rounded_to_binary_float(self):
        source = self.root / "counts.csv"
        source.write_text("cell_id,G1\na,9007199254740993\nb,1\n", encoding="utf-8")
        result = run_plugin(EXAMPLE, {"input_csv": str(source), "input_scale": "raw_counts"}, self.root / "results")
        self.assertEqual(result.status, "succeeded", result.error)
        with (result.run_dir / "tables" / "qc_metrics.csv").open(encoding="utf-8", newline="") as stream:
            metrics = {row["metric"]: row["value"] for row in csv.DictReader(stream)}
        self.assertEqual(metrics["expression_total"], "9007199254740994")

    def test_nonzero_exit_does_not_promote_existing_partial_outputs(self):
        result = self.run_fixture(self.plugin(script=OUTPUT_SCRIPT + "\nraise SystemExit(7)\n"))
        self.assertEqual(result.status, "failed")
        self.assertIn("code 7", result.error)
        self.assertTrue((result.run_dir / "_work" / "tables" / "values.csv").exists())
        self.assertFalse((result.run_dir / "tables").exists())
        self.assertEqual(review_status(load_run(result.run_dir)).execution_status, "failed")

    def test_timeout_retains_diagnostics_and_stops_the_job(self):
        started = time.monotonic()
        result = self.run_fixture(self.plugin(script=OUTPUT_SCRIPT + "\nimport time\ntime.sleep(10)\n"), timeout=0.3)
        self.assertEqual(result.status, "failed")
        self.assertIn("timed out", result.error)
        self.assertLess(time.monotonic() - started, 5)
        self.assertFalse((result.run_dir / "tables").exists())
        self.assertEqual(json.loads((result.run_dir / "manifest.json").read_text())["status"], "failed")

    def test_artifact_escape_and_invalid_csv_are_rejected(self):
        escape = OUTPUT_SCRIPT + "\n(out.parent / 'outside.csv').write_text('a\\n1\\n')\n" + \
            "(out / 'result.json').write_text(json.dumps({'api_version':'0.1','summary':'bad','artifacts':[{'type':'table','path':'../outside.csv'}]}))\n"
        result = self.run_fixture(self.plugin("escape", escape))
        self.assertEqual(result.status, "failed")
        self.assertIn("escapes", result.error)
        malformed = OUTPUT_SCRIPT + "\n(out / 'tables' / 'values.csv').write_text('a,b\\n1\\n')\n"
        other = self.run_fixture(self.plugin("badcsv", malformed))
        self.assertEqual(other.status, "failed")
        self.assertIn("CSV row", other.error)

    def test_log_limit_is_bounded_and_marks_job_failed(self):
        with patch("vcw_core.sdk.MAX_LOG_BYTES", 1024):
            result = self.run_fixture(self.plugin(script=OUTPUT_SCRIPT + "\nprint('x' * 10000)\n"))
        self.assertEqual(result.status, "failed")
        self.assertIn("log limit", result.error)
        self.assertLessEqual((result.run_dir / "logs" / "stdout.log").stat().st_size, 1024)

    def test_cli_lists_then_executes_an_unregistered_plugin(self):
        directory = self.plugin("community")
        result = subprocess.run([sys.executable, "-m", "vcw_core", "plugins", "list", str(directory)],
                                cwd=PROJECT, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["plugins"][0]["id"], "community")
        request = self.root / "request.json"
        request.write_text("{}", encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "vcw_core", "run", "--plugin", str(directory),
            "--request", str(request), "--output", str(self.root / "CLI 结果")],
            cwd=PROJECT, capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(load_run(payload["run_dir"]).backend, "community")


if __name__ == "__main__":
    unittest.main()
