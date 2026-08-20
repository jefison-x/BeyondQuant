"""BYQ-owned StrategyDraft/StrategyVersion validation and export contracts.

Strategy source is treated as bounded domain data.  This module performs only
deterministic static validation; execution is deliberately deferred to a
future BYQ-owned worker boundary.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any


STRATEGY_DRAFT_SCHEMA_VERSION = "strategy-draft-v1"
STRATEGY_VERSION_SCHEMA_VERSION = "strategy-version-v1"
STRATEGY_VALIDATOR_VERSION = "byq-strategy-static-v1"
MAX_SCRIPT_BYTES = 48 * 1024
MAX_JSON_BYTES = 48 * 1024
_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{2,63}$")
_CATEGORIES = {
    "trend_following",
    "mean_reversion",
    "momentum",
    "volatility_based",
    "arbitrage",
    "custom",
}
_SOURCE_TYPES = {"python_script"}
_ALLOWED_IMPORT_ROOTS = {
    "collections",
    "math",
    "numpy",
    "pandas",
    "scipy",
    "sklearn",
    "statistics",
    "statsmodels",
    "typing",
    "xgboost",
    "lightgbm",
}
_FORBIDDEN_CALLS = {
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "globals",
    "input",
    "locals",
    "open",
    "vars",
    "__import__",
}
_FORBIDDEN_ATTRIBUTES = {
    "connect",
    "fork",
    "open",
    "popen",
    "read_html",
    "read_pickle",
    "read_sql",
    "request",
    "spawn",
    "system",
    "urlopen",
}
_SECRET_KEY_FRAGMENTS = (
    "token",
    "password",
    "secret",
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "authorization",
)


class StrategyValidationError(ValueError):
    """Raised when a strategy violates the BYQ strategy contract."""


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrategyValidationError(f"{field} must be a non-empty string")
    result = value.strip()
    if len(result) > maximum:
        raise StrategyValidationError(f"{field} exceeds {maximum} characters")
    return result


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StrategyValidationError(f"{field} must be an object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StrategyValidationError(f"{field} has unknown fields: {', '.join(unknown)}")


def _reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = "".join(character for character in str(key).lower() if character.isalnum())
            if any(fragment in normalized for fragment in _SECRET_KEY_FRAGMENTS):
                raise StrategyValidationError("strategy payload must not contain credential fields")
            _reject_secret_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_secret_keys(nested)


def _canonical_json(value: object, field: str) -> tuple[object, str]:
    _reject_secret_keys(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise StrategyValidationError(f"{field} must be finite JSON") from error
    if len(encoded) > MAX_JSON_BYTES:
        raise StrategyValidationError(f"{field} exceeds {MAX_JSON_BYTES} bytes")
    return json.loads(encoded), encoded.decode("utf-8")


class _SourceVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.custom_strategy: ast.ClassDef | None = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.errors.append(f"line {node.lineno}: relative imports are not allowed")
        self._check_import(node.module or "", node.lineno)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == "CustomStrategy":
            if self.custom_strategy is not None:
                self.errors.append(f"line {node.lineno}: duplicate CustomStrategy class")
            self.custom_strategy = node
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
            self.errors.append(f"line {node.lineno}: forbidden call {node.func.id}")
        if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_ATTRIBUTES:
            self.errors.append(f"line {node.lineno}: forbidden attribute {node.func.attr}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            self.errors.append(f"line {node.lineno}: dunder attribute access is not allowed")
        self.generic_visit(node)

    def _check_import(self, module: str, lineno: int) -> None:
        root = module.split(".", 1)[0]
        if root not in _ALLOWED_IMPORT_ROOTS:
            self.errors.append(f"line {lineno}: import {module or '<unknown>'} is not allowed")


class _LoopedModelFitVisitor(ast.NodeVisitor):
    """Reject model training nested in a per-call historical loop."""

    def __init__(self) -> None:
        self.loop_depth = 0
        self.lines: list[int] = []

    def visit_For(self, node: ast.For) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self.loop_depth
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "fit"
        ):
            self.lines.append(node.lineno)
        self.generic_visit(node)


class _PortfolioStateContractVisitor(ast.NodeVisitor):
    """Reject fields that are not part of the BYQ portfolio-state contract."""

    _INVALID_FIELDS = {"current_date", "peak_equity"}

    def __init__(self) -> None:
        self.invalid_fields: list[tuple[str, int]] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "portfolio_state"
            and node.attr in self._INVALID_FIELDS
        ):
            self.invalid_fields.append((node.attr, node.lineno))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "portfolio_state"
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in self._INVALID_FIELDS
        ):
            self.invalid_fields.append((str(node.args[1].value), node.lineno))
        self.generic_visit(node)


def _method_contract(class_node: ast.ClassDef, visitor: _SourceVisitor) -> None:
    methods = {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    signal = methods.get("generate_signals")
    weights = methods.get("generate_target_weights")
    if signal is not None and weights is not None:
        visitor.errors.append("CustomStrategy must implement exactly one strategy output method")
        return
    if signal is None and weights is None:
        visitor.errors.append("CustomStrategy must implement generate_signals or generate_target_weights")
        return
    selected = signal or weights
    assert selected is not None
    if isinstance(selected, ast.AsyncFunctionDef):
        visitor.errors.append(f"line {selected.lineno}: strategy output method must be synchronous")
        return
    arguments = {argument.arg for argument in selected.args.args}
    required = {"data", "parameters"} if signal is not None else {"data", "portfolio_state", "parameters"}
    missing = sorted(required - arguments)
    if missing:
        visitor.errors.append(f"line {selected.lineno}: strategy method is missing {', '.join(missing)}")
    if weights is not None:
        fit_visitor = _LoopedModelFitVisitor()
        fit_visitor.visit(weights)
        if fit_visitor.lines:
            lines = ", ".join(str(line) for line in fit_visitor.lines)
            visitor.errors.append(
                "generate_target_weights must not call model.fit inside a historical loop "
                f"(line {lines})"
            )
        state_visitor = _PortfolioStateContractVisitor()
        state_visitor.visit(weights)
        for field, line in dict.fromkeys(state_visitor.invalid_fields):
            visitor.errors.append(
                f"line {line}: portfolio_state does not contain {field}"
            )


def validate_strategy_source(script: str) -> dict[str, Any]:
    try:
        tree = ast.parse(script)
    except SyntaxError as error:
        return {"success": False, "errors": [f"Python syntax error at line {error.lineno or '?'}: {error.msg}"]}
    visitor = _SourceVisitor()
    visitor.visit(tree)
    if visitor.custom_strategy is None:
        visitor.errors.append("strategy must define class CustomStrategy")
    else:
        _method_contract(visitor.custom_strategy, visitor)
    return {"success": not visitor.errors, "errors": visitor.errors}


def _strategy_snapshot(value: object) -> dict[str, Any]:
    strategy = _object(value, "strategy")
    _reject_unknown(
        strategy,
        {"strategy_id", "name", "category", "description", "parameters", "parameter_schema", "source_type", "script"},
        "strategy",
    )
    strategy_id = _text(strategy.get("strategy_id"), "strategy.strategy_id", 64)
    if _ID_PATTERN.fullmatch(strategy_id) is None:
        raise StrategyValidationError("strategy.strategy_id has invalid format")
    name = _text(strategy.get("name"), "strategy.name", 200)
    category = _text(strategy.get("category"), "strategy.category", 32)
    if category not in _CATEGORIES:
        raise StrategyValidationError("strategy.category is not supported")
    source_type = _text(strategy.get("source_type", "python_script"), "strategy.source_type", 32)
    if source_type not in _SOURCE_TYPES:
        raise StrategyValidationError("strategy.source_type must be python_script")
    description = "" if strategy.get("description") is None else _text(strategy["description"], "strategy.description", 4000)
    parameters, _ = _canonical_json(_object(strategy.get("parameters", {}), "strategy.parameters"), "strategy.parameters")
    parameter_schema, _ = _canonical_json(_object(strategy.get("parameter_schema", {}), "strategy.parameter_schema"), "strategy.parameter_schema")
    script = _text(strategy.get("script"), "strategy.script", MAX_SCRIPT_BYTES)
    if len(script.encode("utf-8")) > MAX_SCRIPT_BYTES:
        raise StrategyValidationError(f"strategy.script exceeds {MAX_SCRIPT_BYTES} bytes")
    return {
        "strategy_id": strategy_id,
        "name": name,
        "category": category,
        "description": description,
        "parameters": parameters,
        "parameter_schema": parameter_schema,
        "source_type": source_type,
        "script": script,
    }


def prepare_strategy(value: object) -> dict[str, Any]:
    snapshot = _strategy_snapshot(value)
    static_check = validate_strategy_source(snapshot["script"])
    validation = {
        "validator": STRATEGY_VALIDATOR_VERSION,
        "success": bool(static_check["success"]),
        "static_check": static_check,
        "execution_check": {
            "status": "deferred",
            "reason": "strategy execution belongs to a future BYQ-owned worker",
        },
    }
    if not validation["success"]:
        raise StrategyValidationError("strategy failed BYQ static validation: " + "; ".join(static_check["errors"]))
    identity = {
        "schema_version": STRATEGY_VERSION_SCHEMA_VERSION,
        "strategy_id": snapshot["strategy_id"],
        "source_type": snapshot["source_type"],
        "snapshot": snapshot,
    }
    _, identity_json = _canonical_json(identity, "strategy identity")
    version_id = hashlib.sha256(identity_json.encode("utf-8")).hexdigest()
    source_fingerprint = hashlib.sha256(snapshot["script"].encode("utf-8")).hexdigest()
    export = {
        "schema_version": STRATEGY_VERSION_SCHEMA_VERSION,
        "version_id": version_id,
        "strategy_id": snapshot["strategy_id"],
        "source_type": snapshot["source_type"],
        "source_fingerprint": source_fingerprint,
        "snapshot": snapshot,
    }
    return {
        "schema_version": STRATEGY_DRAFT_SCHEMA_VERSION,
        "snapshot": snapshot,
        "validation": validation,
        "version_id": version_id,
        "source_fingerprint": source_fingerprint,
        "export": export,
    }


def prepare_strategy_draft(value: object) -> dict[str, Any]:
    """Prepare a strategy draft for durable save (Phase 33).

    Unlike ``prepare_strategy`` (which requires passing static validation and
    raises on failure), this always returns a draft document so intermediate
    edits can be persisted. ``validation.success`` records whether the source
    passed static checks; structural errors (id/category/source_type/script
    size) still raise. Creating a version still requires a validated draft
    via ``prepare_strategy``.
    """
    snapshot = _strategy_snapshot(value)
    static_check = validate_strategy_source(snapshot["script"])
    validation = {
        "validator": STRATEGY_VALIDATOR_VERSION,
        "success": bool(static_check["success"]),
        "static_check": static_check,
        "execution_check": {
            "status": "deferred",
            "reason": "strategy execution belongs to a future BYQ-owned worker",
        },
    }
    return {
        "schema_version": STRATEGY_DRAFT_SCHEMA_VERSION,
        "snapshot": snapshot,
        "validation": validation,
    }


def strategy_draft_content(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STRATEGY_DRAFT_SCHEMA_VERSION,
        "snapshot": prepared["snapshot"],
        "validation": prepared["validation"],
    }


def strategy_version_content(prepared: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STRATEGY_VERSION_SCHEMA_VERSION,
        "version_id": prepared["version_id"],
        "strategy_id": prepared["snapshot"]["strategy_id"],
        "source_type": prepared["snapshot"]["source_type"],
        "source_fingerprint": prepared["source_fingerprint"],
        "snapshot": prepared["snapshot"],
        "validation": prepared["validation"],
        "export": prepared["export"],
    }


def content_sha256(value: object) -> str:
    _, encoded = _canonical_json(value, "artifact content")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_version_content(value: object) -> dict[str, Any]:
    content = _object(value, "strategy version content")
    _reject_unknown(
        content,
        {"schema_version", "version_id", "strategy_id", "source_type", "source_fingerprint", "snapshot", "validation", "export"},
        "strategy version content",
    )
    if content.get("schema_version") != STRATEGY_VERSION_SCHEMA_VERSION:
        raise StrategyValidationError("unsupported strategy version schema")
    prepared = prepare_strategy(content.get("snapshot"))
    if content.get("version_id") != prepared["version_id"]:
        raise StrategyValidationError("strategy version identity does not match its snapshot")
    if content.get("source_fingerprint") != prepared["source_fingerprint"]:
        raise StrategyValidationError("strategy source fingerprint does not match its snapshot")
    if content.get("export") != prepared["export"]:
        raise StrategyValidationError("strategy export does not match its snapshot")
    return content


def export_strategy_version(value: object) -> dict[str, Any]:
    content = validate_version_content(value)
    exported = content["export"]
    _reject_secret_keys(exported)
    return exported
