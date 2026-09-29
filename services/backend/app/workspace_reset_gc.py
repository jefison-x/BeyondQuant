"""Offline, retryable garbage collection for the isolated development object stores."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_CAS_ID = re.compile(r"^[a-f0-9]{64}$")
_REFERENCE_KEYS = {"namespace", "object_id", "sha256", "size", "media_type"}
_KNOWN_NAMESPACES = {"backtest-results", "ml-features", "ml-models"}

_LIVE_REFERENCE_SQL = """
    SELECT content->'object_reference' AS reference
      FROM artifacts
     WHERE content ? 'object_reference'
    UNION ALL
    SELECT content->'result_reference' AS reference
      FROM artifacts
     WHERE content ? 'result_reference'
    UNION ALL
    SELECT result_reference_json AS reference
      FROM backtest_jobs
     WHERE result_reference_json IS NOT NULL
"""


class WorkspaceResetGcError(RuntimeError):
    """Garbage collection could not prove that deletion is safe."""


def _validated_reference(value: object) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != _REFERENCE_KEYS:
        raise WorkspaceResetGcError("database contains an unknown or malformed object reference")
    namespace = value.get("namespace")
    object_id = value.get("object_id")
    digest = value.get("sha256")
    size = value.get("size")
    media_type = value.get("media_type")
    if (
        not isinstance(namespace, str) or namespace not in _KNOWN_NAMESPACES
        or not isinstance(object_id, str) or _CAS_ID.fullmatch(object_id) is None
        or digest != object_id
        or isinstance(size, bool) or not isinstance(size, int) or size < 0
        or not isinstance(media_type, str) or not media_type or len(media_type) > 128
    ):
        raise WorkspaceResetGcError("database contains an unknown or malformed object reference")
    return namespace, object_id


def _live_references(connection: Any) -> list[object]:
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    try:
        rows = connection.execute(text(_LIVE_REFERENCE_SQL)).mappings().all()
    except SQLAlchemyError as error:
        raise WorkspaceResetGcError("authoritative object references could not be read") from error
    return [row["reference"] for row in rows]


def _roots_by_namespace(
    backtest_object_root: str | Path, ml_object_root: str | Path,
) -> dict[str, Path]:
    backtest_root = Path(backtest_object_root).expanduser()
    ml_root = Path(ml_object_root).expanduser()
    return {
        "backtest-results": backtest_root,
        "ml-features": ml_root,
        "ml-models": ml_root,
    }


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise WorkspaceResetGcError("object store could not be scanned completely") from error
    return digest.hexdigest()


def collect_unreferenced_objects(
    references: Iterable[object], *,
    backtest_object_root: str | Path,
    ml_object_root: str | Path,
) -> dict[str, int | str]:
    """Delete orphaned direct-child CAS files after validating every live reference.

    The caller must stop all application and worker writers first. Discovery and
    validation finish before the first unlink, so a database or scan failure
    cannot leave a partially collected set. A later invocation safely retries
    any unlinks interrupted by process or filesystem failure.
    """
    live: set[tuple[str, str]] = set()
    for reference in references:
        live.add(_validated_reference(reference))

    roots = _roots_by_namespace(backtest_object_root, ml_object_root)
    candidates: list[tuple[Path, int]] = []
    skipped = 0
    for namespace in sorted(_KNOWN_NAMESPACES):
        root = roots[namespace]
        namespace_dir = root / namespace
        try:
            root_mode = root.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WorkspaceResetGcError("object store could not be scanned completely") from error
        if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
            skipped += 1
            continue

        try:
            namespace_mode = namespace_dir.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WorkspaceResetGcError("object store could not be scanned completely") from error
        if stat.S_ISLNK(namespace_mode) or not stat.S_ISDIR(namespace_mode):
            skipped += 1
            continue

        try:
            with os.scandir(namespace_dir) as iterator:
                entries = list(iterator)
        except OSError as error:
            raise WorkspaceResetGcError("object store could not be scanned completely") from error
        for entry in entries:
            if _CAS_ID.fullmatch(entry.name) is None:
                skipped += 1
                continue
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise WorkspaceResetGcError("object store could not be scanned completely") from error
            if not stat.S_ISREG(entry_stat.st_mode):
                skipped += 1
                continue
            if (namespace, entry.name) in live:
                continue
            path = namespace_dir / entry.name
            if _hash_file(path) != entry.name:
                skipped += 1
                continue
            candidates.append((path, entry_stat.st_size))

    deleted = 0
    deleted_bytes = 0
    for path, size in candidates:
        try:
            # Recheck the entry immediately before unlink. unlink never follows
            # a symlink, and a replacement symlink is retained as unexpected.
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode):
                skipped += 1
                continue
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WorkspaceResetGcError("orphan deletion was interrupted; rerun to retry") from error
        deleted += 1
        deleted_bytes += size

    return {
        "schema_version": "workspace-reset-object-gc.v1",
        "deleted_objects": deleted,
        "deleted_bytes": deleted_bytes,
        "skipped_entries": skipped,
    }


def _assert_isolated_stack() -> Any:
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    scope = os.environ.get("BYQ_DEV_SCOPE", "")
    if re.fullmatch(r"byq-dev-[0-9a-f]{10}", scope) is None:
        raise WorkspaceResetGcError("isolated development scope required")
    if os.environ.get("COMPOSE_PROJECT_NAME") != scope:
        raise WorkspaceResetGcError("development Compose project identity mismatch")
    try:
        database = make_url(os.environ.get("BYQ_DATABASE_URL", ""))
    except (ArgumentError, ValueError) as error:
        raise WorkspaceResetGcError("isolated Compose PostgreSQL connection required") from error
    if database.drivername != "postgresql+psycopg" or database.host != "postgres":
        raise WorkspaceResetGcError("isolated Compose PostgreSQL connection required")
    return database


def run_gc() -> dict[str, int | str]:
    from sqlalchemy import create_engine, text

    database_url = _assert_isolated_stack()
    backtest_root = os.environ.get("BYQ_BACKTEST_OBJECT_ROOT", "/var/lib/byq/domain/backtest-objects")
    ml_root = os.environ.get("BYQ_ML_OBJECT_ROOT", "/var/lib/byq/ml-objects")
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                references = _live_references(connection)
        return collect_unreferenced_objects(
            references,
            backtest_object_root=backtest_root,
            ml_object_root=ml_root,
        )
    finally:
        engine.dispose()


def main() -> int:
    from sqlalchemy.exc import ArgumentError
    from sqlalchemy.exc import SQLAlchemyError

    try:
        print(json.dumps(run_gc(), sort_keys=True))
    except (WorkspaceResetGcError, ArgumentError, SQLAlchemyError) as error:
        print(f"Development object cleanup refused: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
