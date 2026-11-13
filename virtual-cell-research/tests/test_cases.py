"""Offline catalogue and bounded-download tests; all urllib responses are mocked."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "cases", Path(__file__).resolve().parents[1] / "scripts" / "cases.py")
cases = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cases)


class Response(io.BytesIO):
    def __init__(self, data, *, headers=None, url="https://data.example.org/counts.csv", code=200):
        super().__init__(data)
        self.headers = headers or {}
        self.url = url
        self.code = code

    def geturl(self):
        return self.url

    def getcode(self):
        return self.code


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.body = b"gene_id,cell_1\nSTAT3,1\nJUN,2\n"
        self.resource = {"id": "counts", "file_name": "计数.csv", "url": "https://data.example.org/counts.csv",
                         "format": "csv", "bytes": len(self.body), "sha256": hashlib.sha256(self.body).hexdigest(),
                         "license_status": "unknown", "license_url": None}
        self.case = {"id": "test-ko", "title": "离线教学案例", "task": "ko", "context": "合成数据，无生物学验证",
                     "sources": [{"title": "Test fixture", "url": "https://data.example.org/"}],
                     "stage": "catalogued", "model_status": "not_run", "validation_status": "not_assessed",
                     "resources": [self.resource], "limitations": ["Synthetic fixture"],
                     "expected_outputs": ["fetch_record.json"], "custom_metadata": {"author": "test"}}
        self.catalog = {"schema_version": 1, "cases": [self.case]}
        self.path = self.base / "目录.json"
        self.path.write_text(json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8")

    def cli(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cases.main(argv)
        return result, stdout.getvalue(), stderr.getvalue()

    def fetch(self, *, response=None, name="下载结果", max_mib=64):
        opener = Mock()
        opener.open.return_value = response if response is not None else Response(self.body)
        with patch.object(cases.urllib.request, "build_opener", return_value=opener):
            result = cases.fetch_resource(self.case, self.resource, self.base / name, max_mib=max_mib)
        record = json.loads((self.base / name / "fetch_record.json").read_text(encoding="utf-8"))
        self.assertEqual(result, record)
        return result, opener

    def assert_failed_without_artifact(self, record, name="下载结果"):
        self.assertEqual(record["status"], "failed")
        self.assertIsNone(record["artifact"])
        self.assertEqual(record["model_status"], "not_run")
        self.assertEqual([p.name for p in (self.base / name).iterdir()], ["fetch_record.json"])

    def test_offline_list_show_validate_and_catalog_argument_positions(self):
        with patch.object(cases.urllib.request, "build_opener", side_effect=AssertionError("offline only")):
            for argv in (["--catalog", str(self.path), "list"], ["show", "test-ko", "--catalog", str(self.path)],
                         ["validate", "--catalog", str(self.path)]):
                result, stdout, stderr = self.cli(argv)
                self.assertEqual(result, 0, stderr)
                self.assertTrue(stdout)
            result, stdout, _ = self.cli(["show", "test-ko", "--catalog", str(self.path)])
            self.assertEqual(json.loads(stdout), self.case)
        self.assertEqual(list(self.base.iterdir()), [self.path])

    def test_missing_fields_duplicate_ids_and_invalid_schema(self):
        broken = [None, {}, {"schema_version": True, "cases": []}]
        for field in self.case.keys() - {"custom_metadata"}:
            item = copy.deepcopy(self.catalog)
            del item["cases"][0][field]
            broken.append(item)
        duplicate_case = copy.deepcopy(self.catalog)
        duplicate_case["cases"].append(copy.deepcopy(self.case))
        broken.append(duplicate_case)
        duplicate_asset = copy.deepcopy(self.catalog)
        duplicate_asset["cases"][0]["resources"].append(copy.deepcopy(self.resource))
        broken.append(duplicate_asset)
        for item in broken:
            with self.subTest(item=item):
                self.assertTrue(cases.validate_catalog(item))
        self.assertEqual(cases.validate_catalog(self.catalog), [])

    def test_stage_and_execution_validation_status_are_consistent(self):
        for stage in cases.STAGES:
            item = copy.deepcopy(self.catalog)
            case = item["cases"][0]
            case.update(stage=stage, model_status="executed" if stage in {"model_executed", "validated"} else "not_run",
                        validation_status="validated" if stage == "validated" else "not_assessed")
            self.assertEqual(cases.validate_catalog(item), [])
            case["model_status"] = "not_run" if case["model_status"] == "executed" else "executed"
            self.assertTrue(cases.validate_catalog(item))
        for key, value in (("stage", "passed"), ("model_status", "executed"), ("validation_status", "validated")):
            item = copy.deepcopy(self.catalog)
            item["cases"][0][key] = value
            self.assertTrue(cases.validate_catalog(item))

    def test_bad_resource_urls_paths_sizes_hashes_and_license_urls(self):
        changes = [("url", value) for value in ("http://example.org/a", "file:///x", "https:///x", "https://u:p@example.org/x", "https://example.org/\nx")]
        changes += [("file_name", value) for value in ("../x", "a/b", "a\\b", "C:x", "NUL", "con.txt", "data.", "fetch_record.json", "FETCH_RECORD.JSON")]
        changes += [("bytes", value) for value in (-1, True, 1.5, "100")]
        changes += [("sha256", value) for value in ("", "a" * 63, "g" * 64, 42)]
        changes += [("license_url", "http://example.org/license")]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                item = copy.deepcopy(self.catalog)
                item["cases"][0]["resources"][0][key] = value
                self.assertTrue(cases.validate_catalog(item))

    def test_json_duplicate_keys_nonfinite_and_catalog_limit(self):
        for payload in ('{"schema_version":1,"schema_version":1,"cases":[]}',
                        '{"schema_version":1,"cases":[],"extra":NaN}', '{"schema_version":1,"cases":[],"extra":Infinity}'):
            self.path.write_text(payload, encoding="utf-8")
            self.assertEqual(self.cli(["validate", "--catalog", str(self.path)])[0], 2)
        with patch.object(cases, "MAX_CATALOG_BYTES", 8):
            self.assertEqual(self.cli(["validate", "--catalog", str(self.path)])[0], 2)

    def test_known_hash_download_in_chinese_path(self):
        result, opener = self.fetch(response=Response(self.body, headers={"Content-Length": str(len(self.body))}))
        self.assertEqual(result["status"], "downloaded")
        self.assertTrue(result["expected_bytes_verified"])
        self.assertTrue(result["expected_sha256_verified"])
        self.assertEqual(result["validation_status"], "not_assessed")
        self.assertEqual(result["model_status"], "not_run")
        self.assertEqual(Path(result["artifact"]).read_bytes(), self.body)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)
        self.assertFalse(list((self.base / "下载结果").glob("*.partial")))
        # Fetching never mutates the catalogue's scientific/execution stage.
        self.assertEqual(self.case["stage"], "catalogued")

    def test_unknown_checksum_is_not_claimed_as_verified(self):
        self.resource.update(bytes=None, sha256=None)
        result, _ = self.fetch()
        self.assertEqual(result["status"], "downloaded")
        self.assertIsNone(result["expected_sha256_verified"])
        self.assertIsNone(result["expected_bytes_verified"])
        self.assertEqual(result["sha256"], hashlib.sha256(self.body).hexdigest())

    def test_missing_parents_are_created_for_new_nested_output(self):
        name = "local-runs/prnet-input"
        self.assertFalse((self.base / "local-runs").exists())
        result, _ = self.fetch(name=name)
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(Path(result["artifact"]).read_bytes(), self.body)
        self.assertEqual(Path(result["artifact"]).parent, self.base / name)
        with self.assertRaises(FileExistsError):
            cases.fetch_resource(self.case, self.resource, self.base / name)
        self.assertEqual(Path(result["artifact"]).read_bytes(), self.body)

    def test_existing_directory_or_input_file_is_never_modified(self):
        output = self.base / "existing"
        output.mkdir()
        marker = output / "untouched.txt"
        marker.write_text("keep", encoding="utf-8")
        with patch.object(cases.urllib.request, "build_opener", side_effect=AssertionError("no network")):
            for existing in (output, self.path):
                with self.assertRaises(FileExistsError):
                    cases.fetch_resource(self.case, self.resource, existing)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.catalog)

    def test_byte_limit_is_checked_before_and_during_download(self):
        self.resource["bytes"] = 1024 * 1024 + 1
        result, opener = self.fetch(max_mib=1)
        self.assert_failed_without_artifact(result)
        opener.open.assert_not_called()
        self.resource.update(bytes=None, sha256=None)
        result, _ = self.fetch(name="streamed", max_mib=1, response=Response(b"x" * (1024 * 1024 + 1)))
        self.assert_failed_without_artifact(result, "streamed")
        result, _ = self.fetch(name="header", max_mib=1, response=Response(self.body, headers={"Content-Length": str(1024 * 1024 + 1)}))
        self.assert_failed_without_artifact(result, "header")

    def test_hash_size_and_truncated_body_fail_without_finished_file(self):
        self.resource["sha256"] = "0" * 64
        result, _ = self.fetch()
        self.assert_failed_without_artifact(result)
        self.assertFalse(result["expected_sha256_verified"])
        self.resource.update(sha256=None, bytes=len(self.body) + 1)
        result, _ = self.fetch(name="wrong-size")
        self.assert_failed_without_artifact(result, "wrong-size")
        self.resource["bytes"] = None
        result, _ = self.fetch(name="truncated", response=Response(self.body, headers={"Content-Length": str(len(self.body) + 1)}))
        self.assert_failed_without_artifact(result, "truncated")

    def test_network_error_and_interruption_leave_failure_record(self):
        for name, error in (("network", OSError("connection failed")), ("interrupted", KeyboardInterrupt())):
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(cases.urllib.request, "build_opener", return_value=opener):
                result = cases.fetch_resource(self.case, self.resource, self.base / name)
            self.assert_failed_without_artifact(result, name)
            self.assertTrue(result["error"])

    def test_timeout_after_partial_body_removes_partial_file(self):
        class InterruptedResponse(Response):
            def read(self, size=-1):
                if self.tell():
                    raise TimeoutError("read timed out")
                return super().read(8)

        result, _ = self.fetch(response=InterruptedResponse(self.body))
        self.assert_failed_without_artifact(result)
        self.assertEqual(result["bytes"], 8)
        self.assertIsNone(result["sha256"])
        self.assertIn("timed out", result["error"])

    def test_html_and_bad_container_magic_are_rejected(self):
        self.resource.update(bytes=None, sha256=None)
        examples = (("html-header", "csv", Response(self.body, headers={"Content-Type": "text/html; charset=utf-8"})),
                    ("html-body", "csv", Response(b"  <!DOCTYPE html><html>Not data</html>")),
                    ("bad-h5ad", "h5ad", Response(b"this is not hdf5")),
                    ("bad-gzip", "csv.gz", Response(b"this is not gzip")))
        for name, fmt, response in examples:
            self.resource["format"] = fmt
            result, _ = self.fetch(name=name, response=response)
            self.assert_failed_without_artifact(result, name)

    def test_magic_check_does_not_claim_complete_data_validation(self):
        self.resource.update(bytes=None, sha256=None, format="h5ad")
        result, _ = self.fetch(response=Response(b"\x89HDF\r\n\x1a\nonly-a-header"))
        self.assertEqual(result["format_check"], "hdf5_signature_only")
        self.assertEqual(result["validation_status"], "not_assessed")
        self.resource["format"] = "gzip"
        result, _ = self.fetch(name="gzip", response=Response(b"\x1f\x8bonly-a-header"))
        self.assertEqual(result["format_check"], "gzip_signature_only")
        self.assertEqual(result["model_status"], "not_run")

    def test_redirect_cannot_downgrade_to_http(self):
        handler = cases.HTTPSOnlyRedirectHandler()
        request = cases.urllib.request.Request(self.resource["url"])
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            handler.redirect_request(request, None, 302, "Found", {}, "http://example.org/file")
        result, _ = self.fetch(response=Response(self.body, url="http://example.org/file"))
        self.assert_failed_without_artifact(result)

    def test_fetch_cli_requires_explicit_asset_and_reports_no_model_run(self):
        self.resource.update(bytes=None, sha256=None)
        self.path.write_text(json.dumps(self.catalog), encoding="utf-8")
        opener = Mock()
        opener.open.return_value = Response(self.body)
        with patch.object(cases.urllib.request, "build_opener", return_value=opener):
            result, stdout, stderr = self.cli(["fetch", "test-ko", "--asset", "counts", "--output-dir", str(self.base / "cli"),
                                               "--catalog", str(self.path)])
        self.assertEqual(result, 0, stderr)
        self.assertIn("未执行模型", stdout)
        self.assertIn("未认证来源校验和", stdout)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(self.cli(["fetch", "test-ko", "--asset", "not-found", "--output-dir", str(self.base / "unused"),
                                  "--catalog", str(self.path)])[0], 2)
        self.assertFalse((self.base / "unused").exists())


if __name__ == "__main__":
    unittest.main()
