"""Regression checks for source provenance and failed-build publication gates."""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts.build_evidence import (
    check_dependencies,
    git_source,
    release_manifest,
    run_tests,
    smoke_result,
    source_inventory,
    write_json,
)


class BuildEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "app.py").write_text("print('sample')\n", encoding="utf-8")
        (self.root / "samples").mkdir()
        (self.root / "samples" / "figure.png").write_bytes(b"source fixture")

    def test_source_and_sample_changes_invalidate_snapshot_but_outputs_do_not(self):
        before = source_inventory(self.root)
        (self.root / "build").mkdir()
        (self.root / "build" / "generated.json").write_text("{}", encoding="utf-8")
        self.assertEqual(source_inventory(self.root), before)
        (self.root / "samples" / "figure.png").write_bytes(b"changed fixture")
        self.assertNotEqual(source_inventory(self.root)["tree_sha256"], before["tree_sha256"])

    def test_archive_revision_is_explicit_and_never_claims_clean_git(self):
        with patch("scripts.build_evidence.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, "No Git checkout"):
                git_source(self.root)
            declared = git_source(self.root, "a" * 40)
        self.assertEqual(declared["revision_source"], "declared_archive")
        self.assertIsNone(declared["dirty"])
        with self.assertRaisesRegex(ValueError, "40-character"):
            git_source(self.root, "main")

    def test_git_revision_checks_dirty_state_and_rejects_false_commit(self):
        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout.strip()

        git("init", "--quiet")
        git("add", ".")
        git("-c", "user.name=Build test", "-c", "user.email=build-test@example.invalid", "commit", "--quiet", "-m", "fixture")
        actual = git("rev-parse", "HEAD")
        self.assertEqual(git_source(self.root), {"commit": actual, "revision_source": "git", "dirty": False, "changes": []})
        (self.root / "app.py").write_text("print('changed')\n", encoding="utf-8")
        self.assertTrue(git_source(self.root)["dirty"])
        with self.assertRaisesRegex(ValueError, "differs"):
            git_source(self.root, "0" * 40)

    def test_dependency_mismatch_and_missing_package_block_build(self):
        requirements = self.root / "requirements-build.txt"
        requirements.write_text("PySide6==6.11.1\n", encoding="utf-8")
        with patch("scripts.build_evidence.importlib.metadata.version", return_value="6.10.0"):
            with self.assertRaisesRegex(ValueError, "expected 6.11.1"):
                check_dependencies(requirements)
        with patch("scripts.build_evidence.importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(ValueError, "Missing build dependency"):
                check_dependencies(requirements)

    def test_release_hashes_actual_installer_and_records_verification(self):
        captured = {"source": source_inventory(self.root), "application": {"version": "fixture"}}
        (self.root / "dist").mkdir()
        installer = self.root / "dist" / "setup.exe"
        installer.write_bytes(b"installer bytes")
        evidence = self.root / "verification" / "tests.json"
        write_json(evidence, {"passed": True, "tests_run": 3})
        result = release_manifest(self.root, captured, installer, [evidence])
        self.assertEqual(result["artifact"]["sha256"], hashlib.sha256(b"installer bytes").hexdigest())
        self.assertEqual(result["verification"][0]["result"]["tests_run"], 3)
        self.assertEqual(result["verification"][0]["path"], "verification/tests.json")

    def test_changed_source_and_failed_or_missing_evidence_block_release(self):
        captured = {"source": source_inventory(self.root)}
        installer = self.root / "setup.exe"
        installer.write_bytes(b"installer bytes")
        evidence = self.root / "verification" / "tests.json"
        write_json(evidence, {"passed": False})
        with self.assertRaisesRegex(ValueError, "verification failed"):
            release_manifest(self.root, captured, installer, [evidence])
        with self.assertRaisesRegex(ValueError, "requires verification"):
            release_manifest(self.root, captured, installer, [])
        write_json(evidence, {"passed": True})
        (self.root / "app.py").write_text("print('changed during build')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed during"):
            release_manifest(self.root, captured, installer, [evidence])

    def test_smoke_requires_real_checks_and_correct_executable_kind(self):
        evidence = self.root / "verification" / "smoke-result.json"
        write_json(evidence, {"passed": True, "checks": ["opened"], "packaged": False, "error": ""})
        self.assertTrue(smoke_result(evidence, packaged=False)["passed"])
        with self.assertRaisesRegex(ValueError, "packaged flag"):
            smoke_result(evidence, packaged=True)
        write_json(evidence, {"passed": True, "checks": [], "packaged": True})
        with self.assertRaisesRegex(ValueError, "did not pass"):
            smoke_result(evidence, packaged=True)

    def test_all_skipped_suite_fails_and_records_selected_test_ids(self):
        class MissingRuntime(unittest.TestCase):
            @unittest.skip("fixture dependency is unavailable")
            def test_runtime(self):
                self.fail("A skipped test must not execute")

        case = MissingRuntime("test_runtime")
        expected_ids = [case.id()]
        suite = unittest.TestSuite([unittest.TestSuite([case])])
        output = self.root / "verification" / "all-skipped.json"
        previous_cwd = Path.cwd()
        try:
            with patch("scripts.build_evidence.unittest.defaultTestLoader.loadTestsFromNames", return_value=suite), redirect_stderr(io.StringIO()):
                exit_code = run_tests(output, ["test_ui"])
        finally:
            os.chdir(previous_cwd)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 1)
        self.assertFalse(result["passed"])
        self.assertEqual((result["tests_run"], result["tests_executed"]), (1, 0))
        self.assertEqual(result["requested_modules"], ["test_ui"])
        self.assertEqual(result["discovered_test_ids"], expected_ids)

    def test_mixed_executed_and_skipped_suite_passes_with_honest_counts(self):
        class MixedRuntime(unittest.TestCase):
            def test_available(self):
                self.assertTrue(True)

            @unittest.skip("fixture platform is unavailable")
            def test_optional(self):
                self.fail("A skipped test must not execute")

        cases = [MixedRuntime("test_available"), MixedRuntime("test_optional")]
        expected_ids = [case.id() for case in cases]
        suite = unittest.TestSuite([unittest.TestSuite(cases)])
        output = self.root / "verification" / "mixed.json"
        previous_cwd = Path.cwd()
        try:
            with patch("scripts.build_evidence.unittest.defaultTestLoader.loadTestsFromNames", return_value=suite), redirect_stderr(io.StringIO()):
                exit_code = run_tests(output, ["platform_tests"])
        finally:
            os.chdir(previous_cwd)
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["passed"])
        self.assertEqual((result["tests_run"], result["tests_executed"]), (2, 1))
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["discovered_test_ids"], expected_ids)


if __name__ == "__main__":
    unittest.main()
