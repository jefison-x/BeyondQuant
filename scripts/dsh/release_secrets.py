#!/usr/bin/env python3
"""ADR-0080 release-artifact secret boundary.

Release artifacts (manifest, target/rollback overlays, resolved private
configuration, retained-artifact copies and backups) MUST NOT contain plaintext
secret values. Generated overlays carry secret *references* (``${ENV_NAME}``)
and the literal values are injected at deploy time from a protected, non-repo
source such as the host ``.env`` (mode 0600) or Docker secrets.

This module never prints or persists resolved secret values. ``resolve`` and
``verify_injection`` return values only in memory for verification and must not
be serialized into release artifacts.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


class SecretBoundaryError(ValueError):
    """A release artifact crossed the ADR-0080 secret boundary."""


# Exact names that do not match the generic secret-name pattern.
EXACT_SECRET_ENV = frozenset({
    "BYQ_CREDENTIAL_ACTIVE_KEY_ID",
    "BYQ_CREDENTIAL_KEYRING",
    "BYQ_DATABASE_URL",
    "BYQ_FEEDBACK_GITHUB_APP_PRIVATE_KEY",
})

# Generic secret-bearing environment names. Matches whole underscore-delimited
# segments so ordinary keys (paths, roots, identities, counts) stay classified
# as non-secret.
SECRET_ENV_PATTERN = re.compile(
    r"(?i)(?:^|_)(?:TOKEN|PASSWORD|PASSWD|SECRET|SECRETS|CREDENTIAL|"
    r"CREDENTIALS|API_?KEY|KEYRING|PRIVATE_?KEY|DATABASE_URL|CONNECTION_STRING|DSN)(?:$|_)"
)

# High-confidence secret material that must never appear as a literal.
SECRET_LIKE = re.compile(
    r"(?i)(?:bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY|sk-[a-z0-9_-]{8,})"
)
CREDENTIAL_URL = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|mysql|redis|amqp)[a-z0-9+._-]*://[^/\s:@]+:[^/\s@]+@"
)

# A Docker Compose reference: ${NAME}, ${NAME:-default} or ${NAME:?message}.
REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([-?])([^}]*))?\}$")
REDACTED = "<redacted>"


def is_secret_key(name: object) -> bool:
    text = str(name)
    return text in EXACT_SECRET_ENV or SECRET_ENV_PATTERN.search(text) is not None


def is_reference(value: object) -> bool:
    return isinstance(value, str) and REFERENCE.fullmatch(value) is not None


def reference(name: str) -> str:
    return "${" + name + "}"


def sanitize_value(name: str, value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if is_reference(value):
        return value
    if is_secret_key(name):
        return reference(name)
    _assert_clean_string(value, name)
    return value


def sanitize_overlay(overlay: dict[str, Any]) -> dict[str, Any]:
    """Replace literal secret environment values with named references."""
    clean = copy.deepcopy(overlay)
    for service in clean.get("services", {}).values():
        if not isinstance(service, dict):
            continue
        environment = service.get("environment")
        if isinstance(environment, dict):
            service["environment"] = {
                name: sanitize_value(name, value) for name, value in environment.items()
            }
        elif isinstance(environment, list):
            service["environment"] = [
                _sanitize_entry(entry) for entry in environment
            ]
    _assert_no_plaintext_secrets(clean)
    return clean


def redact_resolved(resolved: dict[str, Any]) -> dict[str, Any]:
    """Redact a resolved Compose configuration into reference-form evidence."""
    clean = redact_strings(copy.deepcopy(resolved))
    for service in clean.get("services", {}).values():
        if not isinstance(service, dict):
            continue
        environment = service.get("environment")
        if isinstance(environment, dict):
            service["environment"] = {
                name: sanitize_value(name, value) for name, value in environment.items()
            }
    _assert_no_plaintext_secrets(clean)
    return clean


def redact_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_strings(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [redact_strings(nested) for nested in value]
    if isinstance(value, str) and _is_secret_literal(value):
        return REDACTED
    return value


def assert_no_plaintext_secrets(artifact: Any, *, secret_values: Any = ()) -> None:
    """Fail closed if an artifact contains a literal secret value."""
    _assert_no_plaintext_secrets(artifact, secret_values=frozenset(secret_values))


def parse_protected_env(path: Path, *, require_private: bool = True) -> dict[str, str]:
    """Parse a ``.env``-style protected source. Values never leave memory."""
    path = Path(path)
    if require_private:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise SecretBoundaryError(
                f"protected secret source {path} must not be group/world accessible "
                f"(mode {mode:04o}); chmod 600 first"
            )
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        name, _, raw = line.partition("=")
        name = name.strip()
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[name] = raw
    return values


def resolve_environment(
    environment: dict[str, Any], source: dict[str, str], *, require_secrets: bool = True
) -> dict[str, Any]:
    """Resolve reference-form values in memory against a protected source."""
    resolved: dict[str, Any] = {}
    for name, value in environment.items():
        if not isinstance(value, str):
            resolved[name] = value
            continue
        match = REFERENCE.fullmatch(value)
        if match is None:
            resolved[name] = value
            continue
        referenced, operator, argument = match.groups()
        if referenced in source and source[referenced] != "":
            resolved[name] = source[referenced]
        elif operator == "-":
            resolved[name] = argument
        elif operator == "?":
            raise SecretBoundaryError(
                f"required reference {referenced} is not provided by the protected source"
            )
        elif require_secrets and is_secret_key(name):
            raise SecretBoundaryError(
                f"required secret reference {referenced} is not provided; deploy would be empty"
            )
        else:
            resolved[name] = ""
    return resolved


def verify_injection(
    overlay: dict[str, Any], source: dict[str, str], *, require_secrets: bool = True
) -> dict[str, dict[str, Any]]:
    """Resolve every service environment in memory; never serialize the result."""
    resolved: dict[str, dict[str, Any]] = {}
    for name, service in overlay.get("services", {}).items():
        if not isinstance(service, dict):
            continue
        environment = service.get("environment")
        if isinstance(environment, dict):
            resolved[name] = resolve_environment(
                environment, source, require_secrets=require_secrets
            )
    return resolved


def write_private_json(path: Path, value: Any) -> None:
    path = Path(path)
    with path.open("x", encoding="utf-8") as output:
        os.chmod(path, 0o600)
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")


def _sanitize_entry(entry: Any) -> Any:
    if not isinstance(entry, str) or "=" not in entry:
        return entry
    name, _, value = entry.partition("=")
    return f"{name}={sanitize_value(name, value)}"


def _is_secret_literal(value: str) -> bool:
    return SECRET_LIKE.search(value) is not None or CREDENTIAL_URL.search(value) is not None


def _assert_clean_string(value: str, name: object) -> None:
    if _is_secret_literal(value):
        raise SecretBoundaryError(
            f"refusing to bake secret-like value under {name!r} into a release artifact"
        )


def _assert_no_plaintext_secrets(value: Any, *, secret_values: frozenset[str] = frozenset()) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if is_secret_key(key) and isinstance(nested, str) and nested:
                if nested != REDACTED and not is_reference(nested):
                    raise SecretBoundaryError(
                        f"release artifact contains a plaintext value for secret key {key!r}"
                    )
            _assert_no_plaintext_secrets(nested, secret_values=secret_values)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_plaintext_secrets(nested, secret_values=secret_values)
    elif isinstance(value, str):
        if value and secret_values and value in secret_values:
            raise SecretBoundaryError("release artifact contains a known secret value")
        _assert_clean_string(value, "value")


def inspect_artifact(path: Path, *, secret_values: Any = ()) -> dict[str, Any]:
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    assert_no_plaintext_secrets(artifact, secret_values=secret_values)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    sanitize = commands.add_parser("sanitize", help="replace secret literals with ${NAME} references")
    sanitize.add_argument("--input", type=Path, required=True)
    sanitize.add_argument("--output", type=Path, required=True)

    redact = commands.add_parser("redact", help="redact a resolved Compose configuration")
    redact.add_argument("--input", type=Path, required=True)
    redact.add_argument("--output", type=Path, required=True)

    check = commands.add_parser("check", help="fail if an artifact contains a literal secret")
    check.add_argument("artifacts", nargs="+", type=Path)

    verify = commands.add_parser("verify", help="resolve references against a protected source")
    verify.add_argument("--input", type=Path, required=True)
    verify.add_argument("--env-file", type=Path, required=True)
    verify.add_argument("--allow-public-source", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "sanitize":
            overlay = json.loads(args.input.read_text(encoding="utf-8"))
            write_private_json(args.output, sanitize_overlay(overlay))
        elif args.command == "redact":
            resolved = json.loads(args.input.read_text(encoding="utf-8"))
            write_private_json(args.output, redact_resolved(resolved))
        elif args.command == "check":
            for artifact in args.artifacts:
                inspect_artifact(artifact)
        else:
            overlay = json.loads(args.input.read_text(encoding="utf-8"))
            source = parse_protected_env(args.env_file, require_private=not args.allow_public_source)
            verify_injection(overlay, source)
    except (SecretBoundaryError, OSError) as error:
        print(json.dumps({"status": "FAIL", "command": args.command, "reason": str(error)}))
        return 1
    print(json.dumps({"status": "PASS", "command": args.command}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
