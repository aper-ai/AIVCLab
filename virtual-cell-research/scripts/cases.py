"""Inspect a case catalogue offline, or explicitly fetch one selected resource.

Fetching only transfers a file. It never unpacks it, imports case code, installs
dependencies, prepares data, or runs a model. HTTPS uses urllib's normal proxy
and TLS configuration; redirects may not downgrade to HTTP.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request


DEFAULT_CATALOG = Path(__file__).resolve().parents[1] / "cases" / "catalog.json"
MAX_CATALOG_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
STAGES = {"catalogued", "data_downloaded", "prepared", "model_executed", "validated"}
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _https_url(value):
    if not _text(value) or value != value.strip() or any(ord(c) < 33 for c in value):
        return False
    try:
        parts = urllib.parse.urlsplit(value)
        return (parts.scheme == "https" and bool(parts.hostname) and parts.port != 0
                and parts.username is None and parts.password is None)
    except ValueError:
        return False


def _file_name(value):
    if not _text(value) or value.casefold() in {".", "..", "fetch_record.json", "fetch_record.json.tmp"}:
        return False
    return (not any(c in '/\\:*?"<>|' or ord(c) < 32 for c in value)
            and not value.endswith((".", " "))
            and value.split(".", 1)[0].upper() not in WINDOWS_RESERVED)


def validate_catalog(catalog):
    """Return structural errors without reading resources or accessing a network."""
    errors = []
    if not isinstance(catalog, dict):
        return ["catalog 必须是 JSON 对象"]
    if type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
        errors.append("schema_version 必须为整数 1")
    cases = catalog.get("cases")
    if not isinstance(cases, list):
        return errors + ["cases 必须是数组"]
    ids = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        for key in ("id", "title", "task", "context"):
            if not _text(case.get(key)):
                errors.append(f"{prefix}.{key} 必须是非空字符串")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not ID_PATTERN.fullmatch(case_id):
            errors.append(f"{prefix}.id 只能含小写字母、数字、点、下划线和连字符，且以字母或数字开始")
        elif case_id in ids:
            errors.append(f"重复 case id: {case_id}")
        else:
            ids.add(case_id)
        sources = case.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"{prefix}.sources 必须是非空数组")
        else:
            for n, source in enumerate(sources):
                if not isinstance(source, dict) or not _text(source.get("title")) or not _https_url(source.get("url")):
                    errors.append(f"{prefix}.sources[{n}] 需要 title 和无凭据的 HTTPS URL")
        stage = case.get("stage")
        if not isinstance(stage, str) or stage not in STAGES:
            errors.append(f"{prefix}.stage 必须为 {', '.join(sorted(STAGES))}")
        else:
            model = "executed" if stage in {"model_executed", "validated"} else "not_run"
            validation = "validated" if stage == "validated" else "not_assessed"
            if case.get("model_status") != model or case.get("validation_status") != validation:
                errors.append(f"{prefix} 状态矛盾：stage={stage} 需要 model_status={model}, validation_status={validation}")
        for key in ("limitations", "expected_outputs"):
            if not isinstance(case.get(key), list) or any(not _text(item) for item in case[key]):
                errors.append(f"{prefix}.{key} 必须是字符串数组")
        resources = case.get("resources")
        if not isinstance(resources, list):
            errors.append(f"{prefix}.resources 必须是数组（尚无资源可用时允许空数组）")
            continue
        resource_ids = set()
        for n, resource in enumerate(resources):
            label = f"{prefix}.resources[{n}]"
            if not isinstance(resource, dict):
                errors.append(f"{label} 必须是对象")
                continue
            asset_id = resource.get("id")
            if not isinstance(asset_id, str) or not ID_PATTERN.fullmatch(asset_id):
                errors.append(f"{label}.id 必须是合法的稳定 ID")
            elif asset_id in resource_ids:
                errors.append(f"{prefix} 有重复 resource id: {asset_id}")
            else:
                resource_ids.add(asset_id)
            if not _file_name(resource.get("file_name")):
                errors.append(f"{label}.file_name 必须是跨平台的文件 basename，不能是路径或下载记录名")
            if not _https_url(resource.get("url")):
                errors.append(f"{label}.url 必须为无凭据的 HTTPS URL")
            for key in ("format", "license_status"):
                if not _text(resource.get(key)):
                    errors.append(f"{label}.{key} 必须是非空字符串")
            size = resource.get("bytes")
            if "bytes" not in resource or (size is not None and (type(size) is not int or size < 0)):
                errors.append(f"{label}.bytes 必须是非负整数或 null")
            digest = resource.get("sha256")
            if "sha256" not in resource or (digest is not None and (not isinstance(digest, str) or not HASH_PATTERN.fullmatch(digest))):
                errors.append(f"{label}.sha256 必须是 64 位十六进制字符串或 null")
            license_url = resource.get("license_url")
            if "license_url" not in resource or (license_url is not None and not _https_url(license_url)):
                errors.append(f"{label}.license_url 必须是 HTTPS URL 或 null")
    return errors


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 有重复键: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"JSON 不允许非有限数值: {value}")


def load_catalog(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(MAX_CATALOG_BYTES + 1)
    if len(raw) > MAX_CATALOG_BYTES:
        raise ValueError("catalog 超过 4 MiB；请拆分目录，勿把数据放入 catalog")
    catalog = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object,
                         parse_constant=_reject_constant)
    errors = validate_catalog(catalog)
    if errors:
        raise ValueError("目录校验失败：\n- " + "\n- ".join(errors))
    return catalog


class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _https_url(newurl):
            raise ValueError("拒绝重定向：资源下载只允许 HTTPS，不能降级到 HTTP")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _write_record(directory, record):
    temporary = directory / "fetch_record.json.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, directory / "fetch_record.json")
    finally:
        temporary.unlink(missing_ok=True)


def _check_format(path, resource):
    """Check container magic only; do not decompress or assert biological validity."""
    fmt = resource["format"].lower()
    with path.open("rb") as handle:
        prefix = handle.read(512)
        html = prefix.lstrip(b"\xef\xbb\xbf \r\n\t").lower()
        if html.startswith((b"<!doctype html", b"<html")):
            raise ValueError("收到 HTML 页面而非数据文件；请核对资源直链")
        if fmt in {"gzip", "gz"} or fmt.endswith(".gz") or resource["file_name"].lower().endswith(".gz"):
            if not prefix.startswith(b"\x1f\x8b"):
                raise ValueError("文件不含 gzip 标识；未解压，也未完成数据准备")
            return "gzip_signature_only"
        if fmt in {"h5ad", "hdf5", "h5"}:
            signature = b"\x89HDF\r\n\x1a\n"
            if prefix.startswith(signature):
                return "hdf5_signature_only"
            # HDF5 permits a user block before its signature, at powers of two.
            offset, size = 512, path.stat().st_size
            while offset + len(signature) <= size:
                handle.seek(offset)
                if handle.read(len(signature)) == signature:
                    return "hdf5_signature_only"
                offset *= 2
            raise ValueError("文件不含 HDF5 标识；不能把它视作 H5AD 输入")
    return "not_checked"


def fetch_resource(case, resource, output_dir, *, max_mib=64):
    """Fetch one validated catalogue resource into an exclusively new directory.

    Return the persisted success/failure record. Errors before reserving the new
    directory raise normally, so an existing directory or input is never changed.
    """
    if type(max_mib) is not int or max_mib <= 0:
        raise ValueError("max_mib 必须是正整数")
    errors = validate_catalog({"schema_version": 1, "cases": [case]})
    if errors or resource not in case.get("resources", []):
        raise ValueError("只能下载已经通过目录校验且属于所选案例的资源")
    directory = Path(output_dir).expanduser().absolute()
    # Create missing parents, but reserve the final leaf exclusively.
    directory.mkdir(parents=True, exist_ok=False)
    directory = directory.resolve()
    partial = directory / (resource["file_name"] + ".partial")
    destination = directory / resource["file_name"]
    record = {"schema_version": 1, "case_id": case["id"], "asset_id": resource["id"],
              "status": "downloading", "url": resource["url"], "final_url": None,
              "file_name": resource["file_name"], "format": resource["format"],
              "max_bytes": max_mib * 1024 * 1024, "bytes": 0, "sha256": None,
              "expected_bytes": resource["bytes"], "expected_bytes_verified": None,
              "expected_sha256": resource["sha256"], "expected_sha256_verified": None,
              "format_check": "not_checked", "model_status": "not_run",
              "validation_status": "not_assessed", "started_at": _now(), "finished_at": None,
              "artifact": None, "error": None}
    promoted = False
    try:
        _write_record(directory, record)
        if resource["bytes"] is not None and resource["bytes"] > record["max_bytes"]:
            raise ValueError("目录声明的文件大小超过 --max-mib；可明确提高限额后使用新的输出目录")
        opener = urllib.request.build_opener(HTTPSOnlyRedirectHandler())
        request = urllib.request.Request(resource["url"], headers={
            "User-Agent": "Virtual-Cell-Research-cases/1", "Accept-Encoding": "identity"})
        digest = hashlib.sha256()
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            if not _https_url(final_url):
                raise ValueError("拒绝非 HTTPS 最终地址")
            record["final_url"] = final_url
            if response.getcode() != 200:
                raise ValueError(f"资源服务器返回 HTTP {response.getcode()}，未取得完整文件")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise ValueError("资源地址返回 HTML 页面，请提供文件直链")
            length = response.headers.get("Content-Length")
            length = int(length) if length is not None else None
            if length is not None and (length < 0 or length > record["max_bytes"]):
                raise ValueError("服务器声明的文件大小超出下载限额或不合法")
            with partial.open("xb") as handle:
                while True:
                    chunk = response.read(min(CHUNK_BYTES, record["max_bytes"] - record["bytes"] + 1))
                    if not chunk:
                        break
                    record["bytes"] += len(chunk)
                    if record["bytes"] > record["max_bytes"]:
                        raise ValueError("下载超过 --max-mib 限额，已停止；没有保留成品文件")
                    handle.write(chunk)
                    digest.update(chunk)
            if length is not None and record["bytes"] != length:
                raise ValueError("下载字节数与服务器 Content-Length 不符，文件可能不完整")
        record["sha256"] = digest.hexdigest()
        if resource["bytes"] is not None:
            record["expected_bytes_verified"] = record["bytes"] == resource["bytes"]
            if not record["expected_bytes_verified"]:
                raise ValueError("下载大小与目录声明的 bytes 不符")
        if resource["sha256"] is not None:
            record["expected_sha256_verified"] = digest.hexdigest() == resource["sha256"].lower()
            if not record["expected_sha256_verified"]:
                raise ValueError("SHA256 与目录中的预期值不符；文件未保留为成品")
        record["format_check"] = _check_format(partial, resource)
        os.replace(partial, destination)
        promoted = True
        record.update(status="downloaded", artifact=str(destination), finished_at=_now())
        _write_record(directory, record)
    except (Exception, KeyboardInterrupt) as exc:
        partial.unlink(missing_ok=True)
        if promoted:
            destination.unlink(missing_ok=True)
        record.update(status="failed", artifact=None, finished_at=_now(),
                      error="用户中断下载" if isinstance(exc, KeyboardInterrupt) else str(exc))
        _write_record(directory, record)
    return record


def _positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数 MiB")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线查看案例目录；只在显式 fetch 时下载一个资源，不运行模型。")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="案例 catalog.json 路径")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (("list", "离线列出案例"), ("show", "离线展示一个案例"),
                               ("validate", "离线检查目录字段与状态"), ("fetch", "下载一个明确选择的资源")):
        child = subparsers.add_parser(command, help=help_text)
        child.add_argument("--catalog", default=argparse.SUPPRESS, help="案例 catalog.json 路径")
        if command in {"show", "fetch"}:
            child.add_argument("case_id")
        if command == "fetch":
            child.add_argument("--asset", required=True, help="该案例 resources 中的资源 ID")
            child.add_argument("--output-dir", required=True, help="尚不存在的新目录；缺少的父目录会自动创建")
            child.add_argument("--max-mib", type=_positive_int, default=64, help="下载限额（MiB），默认 64；显式调整才会提高")
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.command == "validate":
            print(f"目录校验通过：{len(catalog['cases'])} 个案例；未下载文件、未执行模型，也未核实科学证据。")
            return 0
        if args.command == "list":
            print("case_id\ttitle\ttask\tstage")
            for case in catalog["cases"]:
                print("\t".join(case[key] for key in ("id", "title", "task", "stage")))
            print("stage 是目录记录的阶段；本命令没有运行模型。")
            return 0
        case = next((case for case in catalog["cases"] if case["id"] == args.case_id), None)
        if case is None:
            raise ValueError(f"没有案例 {args.case_id!r}；请先运行 list")
        if args.command == "show":
            print(json.dumps(case, ensure_ascii=False, indent=2, allow_nan=False))
            return 0
        resource = next((resource for resource in case["resources"] if resource["id"] == args.asset), None)
        if resource is None:
            raise ValueError(f"案例没有资源 {args.asset!r}；请先运行 show {case['id']}")
        record = fetch_resource(case, resource, args.output_dir, max_mib=args.max_mib)
        if record["status"] != "downloaded":
            print(f"下载失败：{record['error']}\n检查记录：{Path(args.output_dir) / 'fetch_record.json'}", file=sys.stderr)
            return 1
        print(f"已下载 {record['bytes']} 字节：{record['artifact']}\n记录：{Path(args.output_dir) / 'fetch_record.json'}")
        if record["expected_sha256_verified"] is None:
            print("来源未提供预期 SHA256；记录的是本次计算值，未认证来源校验和。")
        print("未解压、未准备数据、未执行模型、未做科学验证。")
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        print(f"无法继续：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
