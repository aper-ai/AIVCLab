"""Protocol 0.1 draft: inspect plugins, validate requests, execute explicit jobs.

Plugins execute with the user's permissions. This module is not a sandbox.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

API_VERSION = "0.1"
MAX_JSON_BYTES = 64 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_LOG_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_TABLE_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_REPORT_ARTIFACT_BYTES = 1024 * 1024
MAX_TOTAL_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_PLUGINS = 64


class PluginError(ValueError):
    """An unsupported descriptor, invalid request or failed output contract."""


@dataclass(frozen=True)
class Plugin:
    root: Path
    id: str
    version: str
    kind: str
    input_schema: dict[str, Any]
    output_types: tuple[str, ...]
    entrypoint: Path
    description: str


@dataclass(frozen=True)
class RunResult:
    run_dir: Path
    status: str
    error: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PluginError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path | str, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise PluginError(f"JSON must be a regular file of at most {maximum} bytes: {path.name}")
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise PluginError(f"JSON size limit exceeded: {path.name}")
        obj = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs,
                         parse_constant=lambda value: (_ for _ in ()).throw(PluginError(f"Non-finite JSON: {value}")))
        encoded = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > maximum:
            raise PluginError(f"JSON size limit exceeded: {path.name}")
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, PluginError):
            raise
        raise PluginError(f"Cannot read valid UTF-8 JSON from {path.name}: {exc}") from exc
    if not isinstance(obj, dict):
        raise PluginError(f"JSON root must be an object: {path.name}")
    return obj


def _relative_file(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or len(value) > 1024 or "\0" in value or "\\" in value:
        raise PluginError("File paths must be nonempty relative paths using '/' separators")
    path = Path(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts or path.as_posix() != value:
        raise PluginError(f"File path escapes its directory: {value}")
    candidate = root / path
    try:
        resolved = candidate.resolve(strict=True)
        if resolved != candidate or not resolved.is_relative_to(root) or not resolved.is_file():
            raise PluginError(f"File must remain within its directory without symlinks: {value}")
    except (OSError, RuntimeError) as exc:
        raise PluginError(f"Cannot access declared file: {value}") from exc
    return resolved


_SCHEMA_KEYS = {"type", "description", "properties", "required", "additionalProperties", "items",
                "enum", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
_SCHEMA_TYPES = {"object", "array", "string", "number", "integer", "boolean", "null"}


def _finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _schema(schema: Any, depth: int = 0) -> None:
    if depth > 8 or not isinstance(schema, dict) or set(schema) - _SCHEMA_KEYS:
        raise PluginError("Unsupported input_schema keyword or nesting depth (maximum 8)")
    kind = schema.get("type")
    if not isinstance(kind, str) or kind not in _SCHEMA_TYPES:
        raise PluginError("Every input_schema node must declare one supported type")
    if "description" in schema and (not isinstance(schema["description"], str) or len(schema["description"]) > 4000):
        raise PluginError("Schema description must be a short string")
    relevant = {"type", "description", "enum"}
    if kind == "object":
        relevant |= {"properties", "required", "additionalProperties"}
        props, required = schema.get("properties", {}), schema.get("required", [])
        if (not isinstance(props, dict) or len(props) > 64 or not isinstance(required, list)
                or any(not isinstance(key, str) for key in required) or len(set(required)) != len(required)
                or set(required) - props.keys() or schema.get("additionalProperties") is not False):
            raise PluginError("Objects need at most 64 properties, valid required names and additionalProperties=false")
        for child in props.values():
            _schema(child, depth + 1)
    elif kind == "array":
        relevant |= {"items", "minItems", "maxItems"}
        _schema(schema.get("items"), depth + 1)
    elif kind == "string":
        relevant |= {"minLength", "maxLength"}
    elif kind in {"integer", "number"}:
        relevant |= {"minimum", "maximum"}
    if set(schema) - relevant:
        raise PluginError(f"Schema keyword is not supported for {kind}")
    for low, high, ceiling in (("minLength", "maxLength", 16384), ("minItems", "maxItems", 1024)):
        for key in (low, high):
            if key in schema and (type(schema[key]) is not int or not 0 <= schema[key] <= ceiling):
                raise PluginError(f"{key} must be an integer between 0 and {ceiling}")
        if schema.get(low, 0) > schema.get(high, ceiling):
            raise PluginError(f"{low} exceeds {high}")
    for key in ("minimum", "maximum"):
        if key in schema and not _finite(schema[key]):
            raise PluginError(f"{key} must be finite")
    if "minimum" in schema and "maximum" in schema and schema["minimum"] > schema["maximum"]:
        raise PluginError("minimum exceeds maximum")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not 1 <= len(schema["enum"]) <= 50):
        raise PluginError("enum must contain 1 to 50 values")


def validate_request(request: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        if len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_JSON_BYTES:
            raise PluginError("Request exceeds 64 KiB")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, PluginError):
            raise
        raise PluginError("Request must contain finite, UTF-8 JSON values") from exc

    def check(value, node, path):
        kind = node["type"]
        matches = {"object": type(value) is dict, "array": type(value) is list,
                   "string": type(value) is str, "integer": type(value) is int,
                   "number": type(value) in (int, float), "boolean": type(value) is bool, "null": value is None}
        if not matches[kind]:
            raise PluginError(f"{path} must have type {kind}")
        if "enum" in node and not any(type(value) is type(item) and value == item for item in node["enum"]):
            raise PluginError(f"{path} is not an allowed enum value")
        if kind == "object":
            props = node.get("properties", {})
            if set(node.get("required", [])) - value.keys() or value.keys() - props.keys():
                raise PluginError(f"{path} has missing required or undeclared fields")
            for key, item in value.items():
                check(item, props[key], f"{path}.{key}")
        elif kind in {"string", "array"}:
            lower, upper, default = ("minLength", "maxLength", 16384) if kind == "string" else ("minItems", "maxItems", 1024)
            if not node.get(lower, 0) <= len(value) <= node.get(upper, default):
                raise PluginError(f"{path} length is outside its declared limits")
            if kind == "array":
                for index, item in enumerate(value):
                    check(item, node["items"], f"{path}[{index}]")
        elif kind in {"number", "integer"}:
            if (not _finite(value) or "minimum" in node and value < node["minimum"]
                    or "maximum" in node and value > node["maximum"]):
                raise PluginError(f"{path} is outside its finite numeric limits")
    check(request, schema, "request")


def load_plugin(directory: Path | str) -> Plugin:
    root = Path(directory).resolve(strict=True)
    data = read_json(root / "plugin.json")
    required = {"api_version", "id", "version", "kind", "input_schema", "output_types", "entrypoint"}
    if required - data.keys() or data.keys() - (required | {"description"}):
        raise PluginError("Plugin descriptor has missing or unsupported fields")
    if data["api_version"] != API_VERSION:
        raise PluginError(f"Incompatible api_version: expected {API_VERSION}")
    if not isinstance(data["id"], str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", data["id"]):
        raise PluginError("Plugin id must be 1 to 64 lowercase identifier characters")
    if not isinstance(data["version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", data["version"]):
        raise PluginError("Plugin version must use major.minor.patch")
    if not isinstance(data["kind"], str) or data["kind"] not in {"data_qc", "analysis", "prediction", "visualization"}:
        raise PluginError("Unsupported plugin kind")
    _schema(data["input_schema"])
    if data["input_schema"]["type"] != "object":
        raise PluginError("The request schema root must be an object")
    outputs = data["output_types"]
    if (not isinstance(outputs, list) or not outputs or any(not isinstance(item, str) or item not in {"table", "report"} for item in outputs)
            or len(set(outputs)) != len(outputs)):
        raise PluginError("Protocol 0.1 output_types supports unique table/report values")
    entrypoint = _relative_file(root, data["entrypoint"])
    if entrypoint.suffix != ".py" or entrypoint.stat().st_size > MAX_RESULT_BYTES:
        raise PluginError("entrypoint must be a Python .py file of at most 1 MiB")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 4000:
        raise PluginError("description must be a short string")
    return Plugin(root, data["id"], data["version"], data["kind"], data["input_schema"],
                  tuple(outputs), entrypoint, description)


def discover_plugins(directory: Path | str) -> tuple[Plugin, ...]:
    """Read descriptors and paths only. No plugin Python code is imported or run."""
    root = Path(directory).resolve(strict=True)
    candidates = [root] if (root / "plugin.json").exists() else []
    if not candidates:
        with os.scandir(root) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 1024:
                    raise PluginError("Plugin directory inventory exceeds 1024 entries")
                if entry.is_dir(follow_symlinks=False) and (Path(entry.path) / "plugin.json").exists():
                    candidates.append(Path(entry.path))
                if len(candidates) > MAX_PLUGINS:
                    raise PluginError(f"At most {MAX_PLUGINS} plugins may be discovered at once")
    plugins = tuple(load_plugin(path) for path in sorted(candidates))
    seen = set()
    for plugin in plugins:
        if plugin.id in seen:
            raise PluginError(f"Duplicate plugin id: {plugin.id}")
        seen.add(plugin.id)
    return plugins


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stop(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        # Kill the process tree created for this job, not unrelated Python jobs.
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def _execute(command: list[str], work: Path, logs: Path, timeout: float) -> int:
    exceeded = threading.Event()
    errors = []

    def drain(stream, destination):
        total = 0
        try:
            with destination.open("wb") as output:
                while chunk := stream.read(8192):
                    available = MAX_LOG_BYTES - total
                    if available > 0:
                        output.write(chunk[:available])
                    total += len(chunk)
                    if total > MAX_LOG_BYTES:
                        exceeded.set()
        except OSError as exc:
            errors.append(str(exc))
            exceeded.set()
        finally:
            stream.close()

    process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
    threads = [threading.Thread(target=drain, args=(stream, logs / name), daemon=True)
               for stream, name in ((process.stdout, "stdout.log"), (process.stderr, "stderr.log"))]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            if exceeded.is_set():
                raise PluginError("Plugin exceeded the log limit or its log could not be saved")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PluginError(f"Plugin timed out after {timeout:g} seconds")
            try:
                process.wait(timeout=min(remaining, 0.1))
            except subprocess.TimeoutExpired:
                pass
        for thread in threads:
            thread.join(timeout=1)
        if any(thread.is_alive() for thread in threads):
            raise PluginError("Plugin left background processes holding log pipes open")
        if exceeded.is_set() or errors:
            raise PluginError("Plugin exceeded the log limit or its log could not be saved")
        return process.returncode
    except BaseException:
        _stop(process)
        for thread in threads:
            thread.join(timeout=1)
        raise


def _artifacts(work: Path, plugin: Plugin) -> tuple[list[tuple[str, Path, str]], str]:
    result = read_json(work / "result.json", MAX_RESULT_BYTES)
    if set(result) != {"api_version", "summary", "artifacts"} or result["api_version"] != API_VERSION:
        raise PluginError("result.json needs api_version, summary and artifacts for protocol 0.1")
    if not isinstance(result["summary"], str) or len(result["summary"]) > 4000:
        raise PluginError("Result summary must be a string of at most 4000 characters")
    entries = result["artifacts"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise PluginError("A result must declare 1 to 32 artifacts")
    accepted, seen, total = [], set(), 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"type", "path"}:
            raise PluginError("Each artifact needs exactly type and path")
        kind, relative = entry["type"], entry["path"]
        if kind not in plugin.output_types:
            raise PluginError("Artifact type was not declared by the plugin")
        source = _relative_file(work, relative)
        if relative.casefold() in seen:
            raise PluginError("Duplicate artifact path")
        seen.add(relative.casefold())
        if (kind == "table" and (Path(relative).parts[0] != "tables" or source.suffix.lower() != ".csv")) or (
                kind == "report" and relative != "report.md"):
            raise PluginError("Tables must be tables/*.csv; a report must be report.md")
        size = source.stat().st_size
        total += size
        readable_limit = MAX_TABLE_ARTIFACT_BYTES if kind == "table" else MAX_REPORT_ARTIFACT_BYTES
        if not 0 < size <= min(MAX_ARTIFACT_BYTES, readable_limit) or total > MAX_TOTAL_ARTIFACT_BYTES:
            raise PluginError("Artifact size limit exceeded or artifact is empty")
        try:
            with source.open(encoding="utf-8-sig", newline="") as stream:
                if kind == "table":
                    rows = csv.reader(stream, strict=True)
                    headers = next(rows, [])
                    if (not headers or not any(item.strip() for item in headers) or len(headers) > 16384
                            or any("\0" in item for item in headers)):
                        raise PluginError("Output CSV needs a nonempty header with at most 16384 columns")
                    for count, row in enumerate(rows, 1):
                        if count > 1_000_000 or len(row) != len(headers) or any("\0" in cell for cell in row):
                            raise PluginError("Output CSV row shape, count or content is invalid")
                else:
                    for chunk in iter(lambda: stream.read(65536), ""):
                        if "\0" in chunk:
                            raise PluginError("Output report contains NUL characters")
        except (UnicodeError, csv.Error) as exc:
            raise PluginError(f"Output is not valid UTF-8 {kind}: {source.name}") from exc
        accepted.append((kind, source, relative))
    return accepted, result["summary"]


def run_plugin(plugin_directory: Path | str, request: dict[str, Any], output_parent: Path | str, *,
               python_executable: str | None = None, timeout: float = 60) -> RunResult:
    """Explicitly execute one trusted plugin. A successful process still needs valid artifacts."""
    plugin = load_plugin(plugin_directory)
    validate_request(request, plugin.input_schema)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise PluginError("timeout must be finite and between 0 and 3600 seconds")
    if python_executable is None and getattr(sys, "frozen", False):
        raise PluginError("A packaged application must supply a separate Python interpreter")
    interpreter = shutil.which(python_executable or sys.executable)
    if interpreter is None:
        raise PluginError("The requested Python interpreter was not found")
    parent = Path(output_parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    run_id = f"{plugin.id}-{uuid.uuid4().hex}"
    root = parent / run_id
    root.mkdir()
    work, logs = root / "_work", root / "logs"
    work.mkdir()
    logs.mkdir()
    request_path = root / "request.json"
    _write_json(request_path, request)
    manifest = {"run_id": run_id, "backend": plugin.id, "backend_version": plugin.version,
                "task": plugin.kind, "source_kind": "explicit-plugin-execution",
                "parameters": request, "api_version": API_VERSION, "created_at": _now(),
                "independent_validation": "unvalidated",
                "notes": "插件执行与产物结构检查不代表独立科学验证；本运行不自动评价预测效力。"}
    validation = {"independent_validation": "unvalidated",
                  "response_status": "not_applicable" if plugin.kind == "data_qc" else "unknown",
                  "ranking_status": "not_applicable" if plugin.kind == "data_qc" else "unknown"}
    _write_json(root / "provenance.json", {"plugin_root": str(plugin.root),
        "plugin_manifest_sha256": _sha256(plugin.root / "plugin.json"),
        "entrypoint_sha256": _sha256(plugin.entrypoint), "request_sha256": _sha256(request_path),
        "python_executable": interpreter, "protocol": API_VERSION})
    _write_json(root / "validation.json", validation)

    def state(status, **extra):
        manifest.update(status=status, execution_status={"before": "pending", "running": "running",
                        "succeeded": "result_available", "failed": "failed"}[status], **extra)
        _write_json(root / "manifest.json", manifest)
        with (root / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps({"timestamp": _now(), "state": status}, ensure_ascii=False) + "\n")

    state("before")
    error = ""
    try:
        state("running", started_at=_now())
        exit_code = _execute([interpreter, "-X", "utf8", "-E", "-s", str(plugin.entrypoint), "--request", str(request_path),
                              "--output", str(work)], work, logs, timeout)
        manifest["exit_code"] = exit_code
        if exit_code:
            raise PluginError(f"Plugin exited with code {exit_code}; see logs/stderr.log")
        artifacts, summary = _artifacts(work, plugin)
        files = []
        for kind, source, relative in artifacts:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.resolve() != destination or not destination.resolve().is_relative_to(root):
                raise PluginError("Output destination was redirected outside the run directory")
            shutil.copyfile(source, destination)
            files.append({"type": kind, "path": relative, "sha256": _sha256(destination),
                          "bytes": destination.stat().st_size})
        manifest["artifacts"] = files
        manifest["summary"] = summary
        shutil.copyfile(work / "result.json", root / "result.json")
        if not (root / "report.md").exists():
            (root / "report.md").write_text("# 插件执行记录\n\n运行产物已生成。未进行独立科学验证。\n", encoding="utf-8")
        state("succeeded", completed_at=_now())
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
        error = error[:4000]
        (root / "errors.jsonl").write_text(json.dumps({"error": error, "stage": "plugin_execution_or_artifact_check"},
                                                     ensure_ascii=False) + "\n", encoding="utf-8")
        (root / "report.md").write_text(f"# 插件运行未完成\n\n{error}\n\n部分输出仅供诊断，不是成功的科研结果。\n", encoding="utf-8")
        state("failed", completed_at=_now(), error=error)
    return RunResult(root, manifest["status"], error)
