#!/usr/bin/env python3
"""Read-only source inventory; findings are evidence candidates, not audit PASS."""
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def inventory():
    entries = []
    for base in ("services", "workers", "packages"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if any(part in {"node_modules", ".venv", "__pycache__", "dist"} for part in path.parts):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                        continue
                    method = decorator.func.attr
                    if method not in {"get", "post", "put", "patch", "delete", "options", "head", "api_route", "websocket"}:
                        continue
                    if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                        continue
                    entries.append({"kind": "route", "file": str(path.relative_to(ROOT)),
                                    "line": decorator.lineno, "method": method.upper(),
                                    "path": decorator.args[0].value, "handler": node.name,
                                    "audit_status": "NEEDS_EVIDENCE"})
    for path in sorted((ROOT / "services/mcp/src").glob("*.ts")):
        source = path.read_text()
        for match in re.finditer(r'\.registerTool\(\s*"([^"]+)"', source):
            entries.append({"kind": "mcp_tool", "file": str(path.relative_to(ROOT)),
                            "line": source[:match.start()].count("\n") + 1,
                            "name": match.group(1), "audit_status": "NEEDS_EVIDENCE"})
    for path in sorted((ROOT / "workers").rglob("*.py")):
        if path.name == "worker.py":
            entries.append({"kind": "worker", "file": str(path.relative_to(ROOT)),
                            "audit_status": "NEEDS_EVIDENCE"})
    return entries


if __name__ == "__main__":
    entries = inventory()
    print(json.dumps({"schema_version": "reliability-inventory.v1", "entries": entries,
                      "limitations": ["Python literal route decorators and literal MCP registrations only",
                                      "Manual review required for mounts, dynamic routes and external TypeScript handlers",
                                      "Discovery does not establish correctness"]}, ensure_ascii=False, indent=2))
