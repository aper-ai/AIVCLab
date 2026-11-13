"""Small CLI shared by humans and future MCP/DSH integration layers."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .sdk import PluginError, discover_plugins, read_json, run_plugin


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Virtual Cell Workbench plugin protocol 0.1 draft")
    commands = parser.add_subparsers(dest="command", required=True)
    plugins = commands.add_parser("plugins", help="Inspect plugin descriptors without executing plugin code")
    actions = plugins.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list")
    listing.add_argument("folder", type=Path)
    run = commands.add_parser("run", help="Explicitly execute a trusted plugin with user permissions")
    run.add_argument("--plugin", type=Path, required=True)
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--python", dest="python_executable")
    run.add_argument("--timeout", type=float, default=60)
    options = parser.parse_args(argv)
    try:
        if options.command == "plugins":
            result = [{"id": item.id, "version": item.version, "kind": item.kind,
                       "root": str(item.root), "description": item.description,
                       "input_schema": item.input_schema, "output_types": item.output_types}
                      for item in discover_plugins(options.folder)]
            print(json.dumps({"api_version": "0.1", "plugins": result}, ensure_ascii=False, indent=2))
            return 0
        result = run_plugin(options.plugin, read_json(options.request), options.output,
                            python_executable=options.python_executable, timeout=options.timeout)
        print(json.dumps({"run_dir": str(result.run_dir), "status": result.status, "error": result.error},
                         ensure_ascii=False, indent=2))
        return 0 if result.status == "succeeded" else 1
    except (PluginError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
