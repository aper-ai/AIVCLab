"""Record build inputs and verified outputs without requiring third-party packages.

The manifest is provenance, not a claim of reproducible binary builds or a
signature. A source archive must declare its revision explicitly; it is never
reported as a verified, clean Git checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import VERSION

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", "verification", "local-runs"}
EXCLUDED_FILES = {"qc-request.json"}
SOURCE_SUFFIXES = {".py", ".ps1", ".iss", ".txt", ".md", ".json", ".jsonl", ".csv", ".gz", ".png", ".ico", ".isl", ".yml", ".yaml", ".toml", ".cfg", ".ini"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def source_inventory(root: Path) -> dict:
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED_DIRS and (not name.startswith(".") or name == ".github"))
        for name in sorted(names):
            if name in EXCLUDED_FILES:
                continue
            path = Path(directory) / name
            if path.suffix.lower() not in SOURCE_SUFFIXES and name not in {"LICENSE", ".gitignore"}:
                continue
            if path.is_symlink():
                raise ValueError(f"Build inputs must not be symbolic links: {path.relative_to(root)}")
            files.append(file_record(path, root))
    files.sort(key=lambda item: item["path"])
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"tree_sha256": hashlib.sha256(encoded).hexdigest(), "files": files}


def git_source(root: Path, declared_commit: str | None = None) -> dict:
    if declared_commit is not None and not re.fullmatch(r"[0-9a-fA-F]{40}", declared_commit):
        raise ValueError("Source revision must be a full 40-character Git commit SHA.")
    try:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=normal"], check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        if declared_commit is None:
            raise ValueError("No Git checkout found. Provide --source-commit for an exported source archive; it will be marked as declared, not verified.") from None
        return {"commit": declared_commit.lower(), "revision_source": "declared_archive", "dirty": None, "changes": []}
    if declared_commit is not None and commit.lower() != declared_commit.lower():
        raise ValueError("Declared source commit differs from the checked-out Git HEAD.")
    return {"commit": commit, "revision_source": "git", "dirty": bool(status.strip()), "changes": status.splitlines()}


def dependency_pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if not match:
            raise ValueError(f"Build dependencies must use exact pins: {line}")
        name, expected = match.groups()
        pins[name] = expected
    return pins


def check_dependencies(path: Path) -> None:
    for name, expected in dependency_pins(path).items():
        try:
            actual = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError(f"Missing build dependency: {name}=={expected}") from None
        if actual != expected:
            raise ValueError(f"{name}: expected {expected}, installed {actual}. Install requirements-build.txt without changing its pins.")


def write_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def smoke_result(path: Path, *, packaged: bool | None = None) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("passed") is not True or result.get("error") or not result.get("checks"):
        raise ValueError(f"Smoke test did not pass: {path}")
    if packaged is not None and result.get("packaged") is not packaged:
        raise ValueError(f"Smoke test packaged flag does not match the tested executable: {path}")
    return result


def snapshot(root: Path, declared_commit: str | None = None, compiler: Path | None = None) -> dict:
    result = {
        "schema_version": 1,
        "application": {"name": "AperVirtualCellWorkbench", "version": VERSION},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {**git_source(root, declared_commit), **source_inventory(root)},
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "packages": dict(sorted((dist.metadata["Name"], dist.version) for dist in importlib.metadata.distributions() if dist.metadata["Name"])),
        },
        "build_dependency_pins": dependency_pins(root / "requirements-build.txt"),
        "ci": {key: os.environ[key] for key in ("GITHUB_REPOSITORY", "GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "RUNNER_OS", "ImageOS", "ImageVersion") if key in os.environ},
    }
    if compiler:
        result["installer_compiler"] = {"name": compiler.name, "sha256": sha256(compiler), "size_bytes": compiler.stat().st_size}
    return result


def release_manifest(root: Path, captured: dict, artifact: Path, evidence_paths: list[Path]) -> dict:
    current = source_inventory(root)
    if current["tree_sha256"] != captured["source"]["tree_sha256"]:
        raise ValueError("Source inputs changed during the build. Rebuild before publishing this artifact.")
    evidence = []
    for path in evidence_paths:
        content = json.loads(path.read_text(encoding="utf-8"))
        if content.get("passed") is not True:
            raise ValueError(f"Build verification failed or has no success status: {path}")
        evidence.append({**file_record(path, root), "result": content})
    if not evidence:
        raise ValueError("A build manifest requires verification evidence.")
    return {**captured, "completed_at": datetime.now(timezone.utc).isoformat(), "artifact": file_record(artifact, root), "verification": evidence}


def run_tests(output: Path, modules: list[str]) -> int:
    os.chdir(ROOT)
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(modules) if modules else loader.discover(str(ROOT), pattern="test_*.py")

    def test_ids(node):
        if isinstance(node, unittest.TestSuite):
            for child in node:
                yield from test_ids(child)
        else:
            yield node.id()

    # TestSuite removes completed children while running, so capture selection first.
    discovered_ids = list(test_ids(suite))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    executed = result.testsRun - len(result.skipped)
    passed = result.wasSuccessful() and executed > 0
    write_json(output, {
        "passed": passed,
        "tests_run": result.testsRun,
        "tests_executed": executed,
        "requested_modules": list(modules),
        "discovered_test_ids": discovered_ids,
        "discovery": {
            "method": "explicit_modules" if modules else "unittest.discover",
            "pattern": None if modules else "test_*.py",
            "note": "Python 3.12 unittest discovery recurses into package directories; non-package subdirectories are not searched recursively.",
        },
        "skipped": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
        "failures": [{"test": str(test), "traceback": detail} for test, detail in result.failures],
        "errors": [{"test": str(test), "traceback": detail} for test, detail in result.errors],
        "python": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-dependencies")
    test = commands.add_parser("test")
    test.add_argument("--output", type=Path, required=True)
    test.add_argument("--module", action="append", default=[])
    capture = commands.add_parser("snapshot")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--source-commit")
    capture.add_argument("--compiler", type=Path)
    verify = commands.add_parser("verify-smoke")
    verify.add_argument("path", type=Path)
    verify.add_argument("--packaged", choices=("yes", "no"), required=True)
    finish = commands.add_parser("release")
    finish.add_argument("--snapshot", type=Path, required=True)
    finish.add_argument("--artifact", type=Path, required=True)
    finish.add_argument("--output", type=Path, required=True)
    finish.add_argument("--evidence", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check-dependencies":
            check_dependencies(ROOT / "requirements-build.txt")
        elif args.command == "test":
            return run_tests(args.output, args.module)
        elif args.command == "snapshot":
            write_json(args.output, snapshot(ROOT, args.source_commit, args.compiler))
        elif args.command == "verify-smoke":
            smoke_result(args.path, packaged=args.packaged == "yes")
        elif args.command == "release":
            captured = json.loads(args.snapshot.read_text(encoding="utf-8"))
            write_json(args.output, release_manifest(ROOT, captured, args.artifact, args.evidence))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Build evidence error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
