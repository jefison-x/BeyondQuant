"""Fresh child implementing only the closed byq-signal-python-v1 protocol."""

from __future__ import annotations

import ast
import builtins
import json
import sys
from typing import Any

import numpy as np
import pandas as pd


MAX_SIGNALS = 50_000
ALLOWED_IMPORTS = {"collections", "math", "numpy", "pandas", "statistics", "typing"}
FORBIDDEN_CALLS = {
    "breakpoint", "compile", "eval", "exec", "getattr", "globals", "input", "locals",
    "open", "setattr", "vars", "__import__",
}
FORBIDDEN_ATTRIBUTES = {
    "compile", "connect", "eval", "ExcelFile", "fork", "fromfile", "genfromtxt",
    "get_handle", "HDFStore", "listdir", "load", "load_library", "loadtxt", "memmap",
    "open", "popen", "read_csv", "read_excel", "read_feather", "read_fwf", "read_gbq",
    "read_hdf", "read_html", "read_json", "read_orc", "read_parquet", "read_pickle",
    "read_sas", "read_spss", "read_sql", "read_stata", "read_table", "read_xml",
    "request", "save", "savetxt", "savez", "savez_compressed", "spawn", "system",
    "to_clipboard", "to_csv", "to_excel", "to_feather", "to_hdf", "to_html", "to_json",
    "to_latex", "to_markdown", "to_orc", "to_parquet", "to_pickle", "to_sql",
    "to_stata", "to_xml", "urlopen",
}
SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int",
        "isinstance", "len", "list", "map", "max", "min", "range", "reversed", "round",
        "set", "slice", "sorted", "str", "sum", "tuple", "zip", "Exception", "ValueError",
        "object", "classmethod", "staticmethod", "property", "super",
        "__build_class__",
    )
}


class ProtocolError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class Guard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.strategy_classes = 0
        self.signal_methods = 0
        self.weight_methods = 0

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".", 1)[0] not in ALLOWED_IMPORTS:
                self.errors.append(f"line {node.lineno}: import is not allowed")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level or (node.module or "").split(".", 1)[0] not in ALLOWED_IMPORTS:
            self.errors.append(f"line {node.lineno}: import is not allowed")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == "CustomStrategy":
            self.strategy_classes += 1
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == "generate_signals":
                    self.signal_methods += 1
                if isinstance(member, ast.FunctionDef) and member.name == "generate_target_weights":
                    self.weight_methods += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            self.errors.append(f"line {node.lineno}: forbidden call")
        if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTES:
            self.errors.append(f"line {node.lineno}: forbidden attribute")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self.errors.append(f"line {node.lineno}: dunder access is not allowed")
        self.generic_visit(node)


def guarded_import(name: str, globals: object = None, locals: object = None, fromlist: object = (), level: int = 0) -> object:
    if level or name.split(".", 1)[0] not in ALLOWED_IMPORTS:
        raise ImportError("module is not available in byq-signal-python-v1")
    return builtins.__import__(name, globals, locals, fromlist, level)


def validate_source(source: object) -> str:
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > 48 * 1024:
        raise ProtocolError("invalid_source", "strategy source is invalid")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        raise ProtocolError("invalid_source", f"strategy syntax error at line {error.lineno or '?'}") from error
    guard = Guard()
    guard.visit(tree)
    if guard.strategy_classes != 1 or guard.signal_methods != 1 or guard.weight_methods:
        guard.errors.append("exactly one CustomStrategy.generate_signals method is required")
    if guard.errors:
        raise ProtocolError("source_rejected", guard.errors[0])
    return source


def build_data(bars: object) -> pd.DataFrame:
    if not isinstance(bars, list) or not bars or len(bars) > 50_000:
        raise ProtocolError("invalid_input", "bars must be a bounded non-empty list")
    frame = pd.DataFrame(bars)
    required = {"symbol", "trade_date", "open", "high", "low", "close", "volume"}
    if set(frame.columns) - (required | {"prev_close", "is_suspended", "up_limit", "down_limit"}) or not required.issubset(frame.columns):
        raise ProtocolError("invalid_input", "bar columns do not match the signal profile")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y-%m-%d", errors="raise")
    frame = frame.sort_values(["symbol", "trade_date"], kind="stable")
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ProtocolError("invalid_input", "bars contain duplicate symbol/date rows")
    return frame.set_index(["symbol", "trade_date"], drop=True)


def normalize_output(value: object, data: pd.DataFrame) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        raise ProtocolError("invalid_output", "generate_signals must return a mapping")
    allowed_symbols = set(str(item) for item in data.index.get_level_values("symbol").unique())
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for raw_symbol, series in value.items():
        symbol = str(raw_symbol)
        if symbol not in allowed_symbols:
            raise ProtocolError("invalid_output", "signal output contains an unknown symbol")
        if not isinstance(series, pd.Series):
            raise ProtocolError("invalid_output", "each signal output must be a pandas Series")
        valid_dates = set(data.xs(symbol, level="symbol").index)
        for raw_date, raw_signal in series.items():
            try:
                date = pd.Timestamp(raw_date).normalize()
            except (TypeError, ValueError) as error:
                raise ProtocolError("invalid_output", "signal index contains an invalid date") from error
            if date not in valid_dates:
                raise ProtocolError("invalid_output", "signal output contains a date outside frozen bars")
            if isinstance(raw_signal, (bool, np.bool_)) or not isinstance(raw_signal, (int, float, np.integer, np.floating)):
                raise ProtocolError("invalid_output", "signal value must be -1, 0, or 1")
            numeric = float(raw_signal)
            if not np.isfinite(numeric) or numeric not in {-1.0, 0.0, 1.0}:
                raise ProtocolError("invalid_output", "signal value must be -1, 0, or 1")
            key = (symbol, date.strftime("%Y-%m-%d"))
            if key in seen:
                raise ProtocolError("invalid_output", "signal output contains duplicate rows")
            seen.add(key)
            rows.append({"symbol": symbol, "trade_date": key[1], "signal": int(numeric)})
            if len(rows) > MAX_SIGNALS:
                raise ProtocolError("invalid_output", "signal output exceeds 50000 rows")
    return sorted(rows, key=lambda row: (str(row["trade_date"]), str(row["symbol"])))


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict) or request.get("schema_version") != "byq-signal-sandbox-request-v1":
            raise ProtocolError("invalid_input", "unsupported sandbox request")
        if request.get("profile") != "byq-signal-python-v1":
            raise ProtocolError("execution_profile_unsupported", "execution profile is unsupported")
        strategy = request.get("strategy")
        if not isinstance(strategy, dict):
            raise ProtocolError("invalid_input", "strategy input is invalid")
        source = validate_source(strategy.get("script"))
        parameters = request.get("parameters", {})
        if not isinstance(parameters, dict):
            raise ProtocolError("invalid_input", "parameters must be an object")
        namespace: dict[str, Any] = {
            "__builtins__": {**SAFE_BUILTINS, "__import__": guarded_import},
            "__name__": "byq_strategy",
            "np": np,
            "pd": pd,
        }
        compiled = compile(source, "<byq-strategy>", "exec", dont_inherit=True, optimize=2)
        exec(compiled, namespace, namespace)
        strategy_class = namespace.get("CustomStrategy")
        if not isinstance(strategy_class, type):
            raise ProtocolError("invalid_source", "CustomStrategy is unavailable")
        data = build_data(request.get("bars"))
        result = strategy_class().generate_signals(data.copy(deep=True), json.loads(json.dumps(parameters)))
        response = {
            "ok": True,
            "schema_version": "byq-signal-sandbox-response-v1",
            "signals": normalize_output(result, data),
        }
    except ProtocolError as error:
        response = {"ok": False, "error_code": error.code, "error_detail": str(error)[:300]}
    except Exception:
        response = {"ok": False, "error_code": "execution_failed", "error_detail": "strategy execution failed"}
    sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
