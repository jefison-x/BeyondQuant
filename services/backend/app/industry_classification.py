"""BYQ Data Plane storage, incremental sync and point-in-time readiness for
Shenwan (申万) industry classification and membership.

Phase 100-C owns two authoritative datasets:

- ``market_index_classify`` — the versioned ``index_classify`` industry tree
  (SW2014/SW2021). It exposes no dates, so it is reference data keyed by source.
- ``market_index_member_all`` — ``index_member_all`` membership intervals with
  explicit ``in_date``/``out_date``. The provider offers no as-of date parameter
  and silently ignores date-like parameters, so point-in-time membership is
  reconstructed locally from these persisted intervals and never from the
  current constituent set.

The module never connects to Community storage and never exposes raw Tushare
envelopes or credentials outside Backend.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .data_provider import (
    INDEX_CLASSIFY_LEVELS,
    INDEX_CLASSIFY_SOURCES,
    INDEX_MEMBER_ALL_FIELDS,
    IndexClassifyRequest,
    IndexMemberAllRequest,
    ProviderAuthorizationError,
    ProviderCredentialsMissing,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderUnavailable,
    TushareProvider,
    _SW_INDUSTRY_PATTERN,
    _TUSHARE_HISTORICAL_ALIAS_PATTERN,
)
from .db import PgStoreMixin, execute, fetch_one
from .pg_import import CONFLICT_POLICIES, KEEP_NEW, REPORT_MISMATCH, VERIFY_EQUAL


SCHEMA_VERSION = "shenwan-industry.v1"
CLASSIFY_SCHEMA_VERSION = "shenwan-classify.v1"
MEMBER_SCHEMA_VERSION = "shenwan-member.v1"
MAX_READINESS_SYMBOLS = 2_000
_MAX_COVERAGE_ROWS = 200_000
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_KINDS = {"classify", "member"}
_MODES = {"incremental", "refresh"}
_TERMINAL = {"completed", "failed"}
_SYMBOL = re.compile(r"^[0-9]{6}\.(?:SH|SZ|BJ)$")
_SW_PARENT = re.compile(r"^[0-9]{6}$")
_MEMBER_VALUE_FIELDS = tuple(
    field for field in INDEX_MEMBER_ALL_FIELDS
    if field not in {"ts_code", "l3_code", "in_date"}
)


class IndustryClassificationError(RuntimeError):
    pass


class IndustryClassificationNotFound(IndustryClassificationError):
    pass


class IndustryClassificationConflict(IndustryClassificationError):
    pass


class IndustryClassificationPersistenceError(IndustryClassificationError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _date(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        raise ValueError(f"{field} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{field} must be a calendar date in YYYYMMDD") from error
    return value


def _level(value: object) -> str:
    level = str(value).strip().upper()
    if level not in INDEX_CLASSIFY_LEVELS:
        raise ValueError("industry level must be L1, L2 or L3")
    return level


def _industry_code(value: object, *, field: str) -> str:
    code = str(value).strip().upper()
    if not _SW_INDUSTRY_PATTERN.fullmatch(code):
        raise ValueError(f"{field} must match NNNNNN.SI")
    return code


def _symbol(value: object) -> str:
    symbol = str(value).strip().upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError("symbol must match NNNNNN.SH, NNNNNN.SZ or NNNNNN.BJ")
    return symbol


def _provider_error(error: Exception) -> tuple[str, str]:
    if isinstance(error, ProviderCredentialsMissing):
        return "credentials_missing", "Tushare credentials are not configured"
    if isinstance(error, ProviderAuthorizationError):
        return "authorization_failed", "Tushare rejected the configured credentials"
    if isinstance(error, ProviderRateLimited):
        return "rate_limited", "Tushare request was rate limited"
    if isinstance(error, ProviderProtocolError):
        return "provider_protocol_error", "Tushare returned invalid Shenwan industry data"
    if isinstance(error, ProviderUnavailable):
        return "provider_unavailable", "Tushare is unavailable"
    return "sync_failed", "Shenwan industry synchronization failed"


def _classify_sha256(row: dict[str, Any]) -> str:
    return _canonical_hash({
        key: row[key] for key in sorted(row)
        if key not in {"content_sha256", "imported_at", "provenance", "provenance_json"}
    })


def _member_sha256(row: dict[str, Any]) -> str:
    return _canonical_hash({
        key: row[key] for key in sorted(row)
        if key not in {"content_sha256", "imported_at", "provenance", "provenance_json"}
    })


class IndustryClassificationStore(PgStoreMixin):
    """Authoritative Shenwan industry store with interval point-in-time semantics."""

    SCHEMA_DDL: list[str] = [
        """
        CREATE TABLE IF NOT EXISTS market_index_classify (
            src TEXT NOT NULL,
            index_code TEXT NOT NULL,
            industry_name TEXT NOT NULL,
            parent_code TEXT NOT NULL,
            level TEXT NOT NULL,
            industry_code TEXT NOT NULL,
            is_pub TEXT,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (src, index_code)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_classify_level_idx
            ON market_index_classify(level, index_code)
        """,
        """
        CREATE TABLE IF NOT EXISTS market_index_member_all (
            ts_code TEXT NOT NULL,
            l3_code TEXT NOT NULL,
            in_date TEXT NOT NULL,
            out_date TEXT,
            l1_code TEXT NOT NULL,
            l1_name TEXT NOT NULL,
            l2_code TEXT NOT NULL,
            l2_name TEXT NOT NULL,
            l3_name TEXT NOT NULL,
            name TEXT NOT NULL,
            is_new TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            provenance_json JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (ts_code, l3_code, in_date)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_member_all_l3_idx
            ON market_index_member_all(l3_code, in_date, out_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_member_all_l1_idx
            ON market_index_member_all(l1_code, in_date, out_date)
        """,
        """
        CREATE INDEX IF NOT EXISTS market_index_member_all_symbol_idx
            ON market_index_member_all(ts_code)
        """,
        """
        CREATE TABLE IF NOT EXISTS industry_classification_sync_jobs (
            job_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            kind TEXT NOT NULL,
            mode TEXT NOT NULL,
            src TEXT,
            level TEXT,
            selector TEXT,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL,
            rows_received BIGINT NOT NULL DEFAULT 0,
            rows_inserted BIGINT NOT NULL DEFAULT 0,
            rows_updated BIGINT NOT NULL DEFAULT 0,
            rows_kept BIGINT NOT NULL DEFAULT 0,
            rows_quarantined BIGINT NOT NULL DEFAULT 0,
            error_code TEXT,
            error_message TEXT,
            requested_by TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS industry_classification_sync_jobs_created_idx
            ON industry_classification_sync_jobs(created_at DESC, job_id DESC)
        """,
        """
        CREATE TABLE IF NOT EXISTS industry_classification_sync_audit (
            audit_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES industry_classification_sync_jobs(job_id),
            actor_principal TEXT NOT NULL,
            action TEXT NOT NULL,
            outcome TEXT NOT NULL,
            detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS industry_classification_sync_audit_created_idx
            ON industry_classification_sync_audit(created_at DESC, audit_id DESC)
        """,
    ]

    def __init__(self, database_url: str | None = None) -> None:
        try:
            super().__init__(database_url)
        except SQLAlchemyError as error:
            raise IndustryClassificationPersistenceError("industry classification storage is unavailable") from error

    @classmethod
    def from_env(cls) -> "IndustryClassificationStore":
        return cls()

    # -- normalization ----------------------------------------------------

    @staticmethod
    def _normalize_classify(rows: list[object], provenance: dict[str, object]) -> list[dict[str, Any]]:
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in rows:
            src = str(getattr(item, "src", "")).strip().upper()
            if src not in INDEX_CLASSIFY_SOURCES:
                raise ProviderProtocolError("provider returned an invalid index-classify source")
            index_code = str(getattr(item, "index_code", "")).strip().upper()
            if not _SW_INDUSTRY_PATTERN.fullmatch(index_code):
                raise ProviderProtocolError("provider returned an invalid index-classify code")
            level = str(getattr(item, "level", "")).strip().upper()
            if level not in INDEX_CLASSIFY_LEVELS:
                raise ProviderProtocolError("provider returned an invalid index-classify level")
            parent_code = str(getattr(item, "parent_code", "")).strip()
            if not parent_code or (parent_code != "0" and not _SW_PARENT.fullmatch(parent_code)):
                raise ProviderProtocolError("provider returned an invalid index-classify parent code")
            key = (src, index_code)
            if key in seen:
                raise ProviderProtocolError("provider returned duplicate index-classify rows")
            seen.add(key)
            is_pub_value = getattr(item, "is_pub", None)
            is_pub = None if is_pub_value is None or str(is_pub_value).strip() == "" else str(is_pub_value).strip()
            row: dict[str, Any] = {
                "src": src,
                "index_code": index_code,
                "industry_name": str(getattr(item, "industry_name", "")),
                "parent_code": parent_code,
                "level": level,
                "industry_code": str(getattr(item, "industry_code", "")),
                "is_pub": is_pub,
                "provenance": provenance,
            }
            row["content_sha256"] = _classify_sha256(row)
            normalized.append(row)
        return sorted(normalized, key=lambda row: (row["src"], row["index_code"]))

    @staticmethod
    def _normalize_members(rows: list[object], provenance: dict[str, object]) -> list[dict[str, Any]]:
        if not isinstance(provenance, dict):
            raise ValueError("provenance must be an object")
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in rows:
            ts_code = str(getattr(item, "ts_code", "")).strip().upper()
            if not (_SYMBOL.fullmatch(ts_code) or _TUSHARE_HISTORICAL_ALIAS_PATTERN.fullmatch(ts_code)):
                raise ProviderProtocolError("provider returned an invalid index-member ts_code")
            l3_code = str(getattr(item, "l3_code", "")).strip().upper()
            if not _SW_INDUSTRY_PATTERN.fullmatch(l3_code):
                raise ProviderProtocolError("provider returned an invalid index-member l3_code")
            in_date = _date(str(getattr(item, "in_date", "")), field="in_date")
            out_date_value = getattr(item, "out_date", None)
            out_date = None if out_date_value in (None, "") else _date(str(out_date_value), field="out_date")
            if out_date is not None and out_date < in_date:
                raise ProviderProtocolError("provider returned an index-member interval with out_date before in_date")
            is_new = str(getattr(item, "is_new", "")).strip().upper()
            if is_new not in {"Y", "N"}:
                raise ProviderProtocolError("provider returned an invalid index-member is_new flag")
            if is_new == "Y" and out_date is not None:
                raise ProviderProtocolError("provider returned a current index-member with an out_date")
            key = (ts_code, l3_code, in_date)
            if key in seen:
                raise ProviderProtocolError("provider returned duplicate index-member intervals")
            seen.add(key)
            row: dict[str, Any] = {
                "ts_code": ts_code, "l3_code": l3_code, "in_date": in_date, "out_date": out_date,
                "is_new": is_new, "provenance": provenance,
            }
            for field in _MEMBER_VALUE_FIELDS:
                if field in {"out_date", "is_new"}:
                    continue
                if field in {"l1_code", "l2_code"}:
                    code = str(getattr(item, field, "")).strip().upper()
                    if not _SW_INDUSTRY_PATTERN.fullmatch(code):
                        raise ProviderProtocolError(f"provider returned an invalid index-member {field}")
                    row[field] = code
                else:
                    row[field] = str(getattr(item, field, ""))
            row["content_sha256"] = _member_sha256(row)
            normalized.append(row)
        return sorted(normalized, key=lambda row: (row["ts_code"], row["l3_code"], row["in_date"]))

    # -- imports ----------------------------------------------------------

    def import_classify_rows(
        self,
        rows: list[object],
        *,
        provenance: dict[str, object],
        conflict_policy: str = KEEP_NEW,
    ) -> dict[str, Any]:
        """Idempotent import of ``index_classify`` reference rows."""
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict_policy must be one of {sorted(CONFLICT_POLICIES)}")
        normalized = self._normalize_classify(rows, provenance)
        inserted = kept = 0
        mismatches: list[dict[str, Any]] = []
        with self._transaction() as connection:
            for row in normalized:
                existing = fetch_one(
                    connection,
                    """SELECT content_sha256 FROM market_index_classify
                       WHERE src=:src AND index_code=:index_code FOR UPDATE""",
                    {"src": row["src"], "index_code": row["index_code"]},
                )
                if existing is not None:
                    if conflict_policy in {VERIFY_EQUAL, REPORT_MISMATCH} and existing["content_sha256"] != row["content_sha256"]:
                        mismatches.append({
                            "src": row["src"], "index_code": row["index_code"],
                            "reason": "verify_equal_mismatch" if conflict_policy == VERIFY_EQUAL else "conflict_reported",
                        })
                    kept += 1
                    continue
                execute(connection, """INSERT INTO market_index_classify
                    (src, index_code, industry_name, parent_code, level, industry_code, is_pub,
                     content_sha256, provenance_json, imported_at)
                    VALUES (:src, :index_code, :industry_name, :parent_code, :level, :industry_code,
                            :is_pub, :content_sha256, :provenance, now())""", row)
                inserted += 1
        return {"inserted": inserted, "updated": 0, "kept": kept, "reported": len(mismatches), "mismatches": mismatches}

    def import_member_rows(
        self,
        rows: list[object],
        *,
        provenance: dict[str, object],
        conflict_policy: str = KEEP_NEW,
    ) -> dict[str, Any]:
        """Idempotent import/reconcile of ``index_member_all`` intervals.

        An open interval (``out_date`` null, ``is_new='Y'``) may be refreshed by
        a later current snapshot; a settled interval (``out_date`` set) is
        historical and is never rewritten. A settled interval whose incoming
        content differs is reported as a mismatch instead.
        """
        if conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(f"conflict_policy must be one of {sorted(CONFLICT_POLICIES)}")
        normalized = self._normalize_members(rows, provenance)
        inserted = updated = kept = 0
        mismatches: list[dict[str, Any]] = []
        with self._transaction() as connection:
            for row in normalized:
                existing = fetch_one(
                    connection,
                    """SELECT out_date, content_sha256 FROM market_index_member_all
                       WHERE ts_code=:ts_code AND l3_code=:l3_code AND in_date=:in_date FOR UPDATE""",
                    {"ts_code": row["ts_code"], "l3_code": row["l3_code"], "in_date": row["in_date"]},
                )
                if existing is None:
                    execute(connection, """INSERT INTO market_index_member_all
                        (ts_code, l3_code, in_date, out_date, l1_code, l1_name, l2_code, l2_name,
                         l3_name, name, is_new, content_sha256, provenance_json, imported_at)
                        VALUES (:ts_code, :l3_code, :in_date, :out_date, :l1_code, :l1_name,
                                :l2_code, :l2_name, :l3_name, :name, :is_new, :content_sha256,
                                :provenance, now())""", row)
                    inserted += 1
                    continue
                if existing["content_sha256"] == row["content_sha256"]:
                    kept += 1
                    continue
                if existing["out_date"] is None:
                    execute(connection, """UPDATE market_index_member_all SET
                        out_date=:out_date, l1_code=:l1_code, l1_name=:l1_name, l2_code=:l2_code,
                        l2_name=:l2_name, l3_name=:l3_name, name=:name, is_new=:is_new,
                        content_sha256=:content_sha256, provenance_json=:provenance, imported_at=now()
                        WHERE ts_code=:ts_code AND l3_code=:l3_code AND in_date=:in_date""", row)
                    updated += 1
                    continue
                mismatches.append({
                    "ts_code": row["ts_code"], "l3_code": row["l3_code"], "in_date": row["in_date"],
                    "reason": "settled_interval_rewrite_rejected",
                })
        return {"inserted": inserted, "updated": updated, "kept": kept, "reported": len(mismatches), "mismatches": mismatches}

    # -- point-in-time reconstruction ------------------------------------

    def membership_asof(
        self, *, level: object = "L1", code: object, as_of_date: object, limit: int = MAX_READINESS_SYMBOLS,
    ) -> dict[str, Any]:
        """Reconstruct membership active at ``as_of_date`` from persisted intervals.

        Active means ``in_date <= as_of_date`` and (``out_date`` is null or
        ``out_date > as_of_date``). This is the only correct point-in-time path:
        the provider has no as-of query and current constituents are never
        backfilled into history.
        """
        normalized_level = _level(level)
        normalized_code = _industry_code(code, field="code")
        as_of = _date(as_of_date, field="as_of_date")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_READINESS_SYMBOLS:
            raise ValueError(f"limit must be between 1 and {MAX_READINESS_SYMBOLS}")
        column = {"L1": "l1_code", "L2": "l2_code", "L3": "l3_code"}[normalized_level]
        rows = self._execute(
            f"""SELECT ts_code, l1_code, l1_name, l2_code, l2_name, l3_code, l3_name, name,
                       in_date, out_date, content_sha256
                FROM market_index_member_all
                WHERE {column}=:code AND in_date<=:as_of
                  AND (out_date IS NULL OR out_date>:as_of)
                ORDER BY ts_code, l3_code LIMIT :limit""",
            {"code": normalized_code, "as_of": as_of, "limit": limit + 1},
        )
        if len(rows) > limit:
            raise ValueError("membership_asof exceeded its bounded member limit")
        return {
            "schema_version": SCHEMA_VERSION,
            "level": normalized_level,
            "code": normalized_code,
            "as_of_date": as_of,
            "member_count": len(rows),
            "members": rows,
            "source": "persisted_intervals",
            "current_snapshot_used": False,
        }

    def readiness(
        self, *, symbols: object, as_of_date: object, level: object = "L1",
    ) -> dict[str, Any]:
        """Fail-closed membership readiness for a symbol set at one as-of date.

        Each symbol must have exactly one active membership interval at the
        requested level; missing or ambiguous membership is never inferred from
        the current constituent snapshot.
        """
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("symbols must be a non-empty list")
        normalized_symbols = sorted({_symbol(symbol) for symbol in symbols})
        if len(normalized_symbols) != len(symbols):
            raise ValueError("symbols must be unique canonical codes")
        if len(normalized_symbols) > MAX_READINESS_SYMBOLS:
            raise ValueError(f"symbols exceeds {MAX_READINESS_SYMBOLS} entries")
        normalized_level = _level(level)
        as_of = _date(as_of_date, field="as_of_date")
        column = {"L1": "l1_code", "L2": "l2_code", "L3": "l3_code"}[normalized_level]
        rows = self._execute(
            f"""SELECT ts_code, l1_code, l2_code, l3_code, in_date, out_date, content_sha256
                FROM market_index_member_all
                WHERE ts_code IN (SELECT jsonb_array_elements_text(:symbols))
                  AND in_date<=:as_of AND (out_date IS NULL OR out_date>:as_of)
                  AND {column} IS NOT NULL
                ORDER BY ts_code, l3_code""",
            {"symbols": normalized_symbols, "as_of": as_of},
        )
        active: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in normalized_symbols}
        for row in rows:
            active[str(row["ts_code"])].append(row)
        missing: list[dict[str, str]] = []
        ambiguous: list[dict[str, str]] = []
        evidence: list[dict[str, Any]] = []
        for symbol in normalized_symbols:
            intervals = active[symbol]
            if not intervals:
                missing.append({"symbol": symbol, "as_of_date": as_of, "reason": "industry_membership_unavailable"})
                continue
            if len(intervals) > 1:
                ambiguous.append({"symbol": symbol, "as_of_date": as_of, "reason": "industry_membership_ambiguous"})
                continue
            row = intervals[0]
            evidence.append({
                "symbol": symbol,
                "industry_code": row[column],
                "l1_code": row["l1_code"], "l2_code": row["l2_code"], "l3_code": row["l3_code"],
                "in_date": row["in_date"], "out_date": row["out_date"],
                "content_sha256": row["content_sha256"],
            })
        classify_present = bool(self._fetch_one(
            "SELECT 1 AS present FROM market_index_classify WHERE level=:level LIMIT 1",
            {"level": normalized_level},
        ))
        return {
            "schema_version": MEMBER_SCHEMA_VERSION + "-readiness",
            "level": normalized_level,
            "as_of_date": as_of,
            "symbols": normalized_symbols,
            "memberships": evidence,
            "coverage": {
                "usable": bool(normalized_symbols) and not missing and not ambiguous and classify_present,
                "classify_present": classify_present,
                "requested_symbols": len(normalized_symbols),
                "resolved_symbols": len(evidence),
                "missing": missing[:200],
                "ambiguous": ambiguous[:200],
            },
        }

    # -- coverage / fingerprints -----------------------------------------

    def persisted_fingerprint(self) -> dict[str, Any]:
        classify = self._execute(
            """SELECT src, index_code, content_sha256 FROM market_index_classify
               ORDER BY src, index_code"""
        )
        members = self._execute(
            """SELECT ts_code, l3_code, in_date, content_sha256 FROM market_index_member_all
               ORDER BY ts_code, l3_code, in_date"""
        )
        classify_rows = [[str(r["src"]), str(r["index_code"]), str(r["content_sha256"])] for r in classify]
        member_rows = [[str(r["ts_code"]), str(r["l3_code"]), str(r["in_date"]), str(r["content_sha256"])] for r in members]
        return {
            "classify_row_count": len(classify_rows),
            "member_row_count": len(member_rows),
            "content_sha256": _canonical_hash({"classify": classify_rows, "members": member_rows}),
        }

    def coverage(self) -> dict[str, Any]:
        """Coverage and quality derived from persisted rows, never from a pull."""
        classify_totals = self._fetch_one(
            """SELECT COUNT(*)::bigint AS row_count, COUNT(DISTINCT src)::bigint AS source_count,
                      COUNT(DISTINCT index_code)::bigint AS code_count
               FROM market_index_classify"""
        ) or {}
        classify_groups = self._execute(
            """SELECT src, level, COUNT(*)::bigint AS row_count
               FROM market_index_classify GROUP BY src, level ORDER BY src, level"""
        )
        member_totals = self._fetch_one(
            """SELECT COUNT(*)::bigint AS row_count,
                      COUNT(*) FILTER (WHERE out_date IS NULL)::bigint AS open_count,
                      COUNT(*) FILTER (WHERE out_date IS NOT NULL)::bigint AS settled_count,
                      COUNT(*) FILTER (WHERE ts_code LIKE 'T%')::bigint AS alias_count,
                      COUNT(*) FILTER (WHERE in_date IS NULL OR in_date='')::bigint AS missing_in_date,
                      MIN(in_date) AS in_date_min, MAX(in_date) AS in_date_max,
                      MIN(out_date) AS out_date_min, MAX(out_date) AS out_date_max
               FROM market_index_member_all"""
        ) or {}
        intervals = self._execute(
            """SELECT ts_code, l3_code, in_date, out_date FROM market_index_member_all
               ORDER BY ts_code, in_date, l3_code LIMIT :limit""",
            {"limit": _MAX_COVERAGE_ROWS + 1},
        )
        truncated = len(intervals) > _MAX_COVERAGE_ROWS
        overlap_count = 0
        by_symbol: dict[str, list[tuple[str, str | None, str]]] = {}
        for row in intervals[:_MAX_COVERAGE_ROWS]:
            by_symbol.setdefault(str(row["ts_code"]), []).append(
                (str(row["in_date"]), row["out_date"], str(row["l3_code"])),
            )
        for symbol_intervals in by_symbol.values():
            ordered = sorted(symbol_intervals, key=lambda item: (item[0], item[1] or "99999999"))
            for index in range(len(ordered) - 1):
                current_end = ordered[index][1] or "99999999"
                next_start = ordered[index + 1][0]
                if next_start < current_end:
                    overlap_count += 1
        orphan = self._fetch_one(
            """SELECT COUNT(*)::bigint AS orphan_count FROM (
                   SELECT DISTINCT l3_code FROM market_index_member_all
               ) AS members
               WHERE NOT EXISTS (
                   SELECT 1 FROM market_index_classify AS classify
                   WHERE classify.index_code=members.l3_code
               )"""
        ) or {}
        member_row_count = int(member_totals.get("row_count") or 0)
        classify_row_count = int(classify_totals.get("row_count") or 0)
        issue_count = overlap_count + int(orphan.get("orphan_count") or 0) + int(member_totals.get("missing_in_date") or 0)
        if not member_row_count and not classify_row_count:
            quality = "empty"
        elif issue_count:
            quality = "issues"
        else:
            quality = "observed"
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": "tushare",
            "endpoint": "index_classify/index_member_all",
            "scope": "persisted_observations",
            "completeness_claimed": False,
            "quality": quality,
            "issue_count": issue_count,
            "classify": {
                "schema_version": CLASSIFY_SCHEMA_VERSION,
                "row_count": classify_row_count,
                "source_count": int(classify_totals.get("source_count") or 0),
                "code_count": int(classify_totals.get("code_count") or 0),
                "groups": classify_groups,
            },
            "member": {
                "schema_version": MEMBER_SCHEMA_VERSION,
                "row_count": member_row_count,
                "open_count": int(member_totals.get("open_count") or 0),
                "settled_count": int(member_totals.get("settled_count") or 0),
                "alias_count": int(member_totals.get("alias_count") or 0),
                "missing_in_date": int(member_totals.get("missing_in_date") or 0),
                "in_date_min": member_totals.get("in_date_min"),
                "in_date_max": member_totals.get("in_date_max"),
                "out_date_min": member_totals.get("out_date_min"),
                "out_date_max": member_totals.get("out_date_max"),
                "overlap_pairs": overlap_count,
                "orphan_l3_codes": int(orphan.get("orphan_count") or 0),
                "scan_truncated": truncated,
            },
        }

    # -- sync jobs --------------------------------------------------------

    def create_sync_job(self, payload: object, *, actor: object) -> tuple[dict[str, Any], bool]:
        if not isinstance(payload, dict):
            raise ValueError("industry sync request must be an object")
        allowed = {"kind", "mode", "src", "level", "selector", "selector_level", "idempotency_key"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(f"industry sync request has unknown fields: {', '.join(unknown)}")
        actor_text = str(actor).strip()
        if not actor_text or len(actor_text) > 128:
            raise ValueError("actor principal is invalid")
        kind = str(payload.get("kind", "")).strip()
        if kind not in _KINDS:
            raise ValueError("industry sync kind must be classify or member")
        mode = payload.get("mode", "incremental")
        if mode not in _MODES:
            raise ValueError("industry sync mode must be incremental or refresh")
        src: str | None = None
        level: str | None = None
        selector: str | None = None
        if kind == "classify":
            src = str(payload.get("src", "")).strip().upper()
            if src not in INDEX_CLASSIFY_SOURCES:
                raise ValueError("classify sync requires src SW2014 or SW2021")
            if payload.get("selector") not in (None, "") or payload.get("selector_level") not in (None, ""):
                raise ValueError("classify sync does not accept a selector")
            if payload.get("level") not in (None, ""):
                level = _level(payload.get("level"))
        else:
            if payload.get("src") not in (None, "") or payload.get("level") not in (None, ""):
                raise ValueError("member sync does not accept src or level")
            selector_value = payload.get("selector")
            selector_level = payload.get("selector_level")
            if selector_value in (None, "", "all"):
                if selector_level not in (None, ""):
                    raise ValueError("member sync selector_level requires an industry selector")
                selector = "all"
            else:
                text = str(selector_value).strip().upper()
                if _SYMBOL.fullmatch(text):
                    if selector_level not in (None, ""):
                        raise ValueError("member sync selector_level is only valid for industry selectors")
                    selector = f"ts_code:{text}"
                elif _SW_INDUSTRY_PATTERN.fullmatch(text):
                    resolved = _level(selector_level) if selector_level not in (None, "") else None
                    if resolved is None:
                        raise ValueError("member sync industry selector requires selector_level L1, L2 or L3")
                    selector = f"{resolved.lower()}_code:{text}"
                else:
                    raise ValueError("member sync selector must be a Shenwan code, a stock code or all")
        idempotency_key = payload.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY.fullmatch(idempotency_key):
            raise ValueError("idempotency_key is invalid")
        request = {
            "provider": "tushare", "kind": kind, "mode": mode,
            "src": src, "level": level, "selector": selector,
        }
        request_sha256 = _canonical_hash(request)
        job_id = f"industrysync_{uuid.uuid4().hex}"
        now = _now()
        try:
            with self._transaction() as connection:
                existing = fetch_one(
                    connection,
                    "SELECT * FROM industry_classification_sync_jobs WHERE idempotency_key=:key",
                    {"key": idempotency_key},
                )
                if existing is not None:
                    if existing["request_sha256"] != request_sha256:
                        raise IndustryClassificationConflict("industry idempotency key was reused")
                    return self._public_job(existing), False
                execute(connection, """INSERT INTO industry_classification_sync_jobs
                    (job_id, provider, kind, mode, src, level, selector, status, progress,
                     requested_by, idempotency_key, request_sha256, created_at, updated_at)
                    VALUES (:job_id, 'tushare', :kind, :mode, :src, :level, :selector, 'queued', 0,
                            :actor, :idempotency_key, :request_sha256, :now, :now)""", {
                    "job_id": job_id, "kind": kind, "mode": mode, "src": src, "level": level,
                    "selector": selector, "actor": actor_text,
                    "idempotency_key": idempotency_key, "request_sha256": request_sha256, "now": now,
                })
                self._audit(connection, job_id, actor_text, "created", "queued", {
                    "kind": kind, "mode": mode, "src": src, "level": level, "selector": selector,
                })
        except IntegrityError as error:
            raise IndustryClassificationConflict("industry sync conflicts with existing state") from error
        return self.get_sync_job(job_id), True

    def run_sync_job(
        self, job_id: object, *, provider_factory: Callable[[], TushareProvider],
    ) -> dict[str, Any]:
        job_id = str(job_id)
        with self._transaction() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM industry_classification_sync_jobs WHERE job_id=:job_id FOR UPDATE",
                {"job_id": job_id},
            )
            if row is None:
                raise IndustryClassificationNotFound("industry sync job not found")
            if row["status"] in _TERMINAL:
                return self._public_job(row)
            if row["status"] != "queued":
                raise IndustryClassificationConflict("industry sync job is already running")
            execute(connection, """UPDATE industry_classification_sync_jobs
                SET status='running', progress=10, started_at=:now, updated_at=:now
                WHERE job_id=:job_id""", {"job_id": job_id, "now": _now()})
        try:
            provider = provider_factory()
        except (ProviderError, ValueError) as error:
            code, message = _provider_error(error)
            return self._finish_job(job_id, status="failed", received=0, inserted=0, updated=0, kept=0,
                                   error_code=code, error_message=message)
        try:
            if row["kind"] == "classify":
                received, inserted, updated, kept = self._run_classify(provider, row)
                quarantined = 0
            else:
                received, inserted, updated, kept, quarantined = self._run_member(
                    provider, str(row["selector"] or "all"),
                )
        except (ProviderError, ValueError, SQLAlchemyError) as error:
            code, message = _provider_error(error)
            return self._finish_job(job_id, status="failed", received=0, inserted=0, updated=0, kept=0,
                                   error_code=code, error_message=message)
        return self._finish_job(
            job_id, status="completed", received=received, inserted=inserted, updated=updated,
            kept=kept, quarantined=quarantined,
        )

    def _run_classify(self, provider: TushareProvider, row: dict[str, Any]) -> tuple[int, int, int, int]:
        level = str(row["level"]) if row["level"] else None
        result = provider.fetch_index_classify(IndexClassifyRequest(src=str(row["src"]), level=level))
        report = self.import_classify_rows(list(result.rows), provenance=result.provenance.as_dict())
        return len(result.rows), int(report["inserted"]), int(report["updated"]), int(report["kept"])

    def _run_member(self, provider: TushareProvider, selector: str) -> tuple[int, int, int, int, int]:
        received = inserted = updated = kept = quarantined = 0
        selector_params: dict[str, str] = {}
        if selector != "all":
            field, _, code = selector.partition(":")
            if field not in {"ts_code", "l1_code", "l2_code", "l3_code"} or not code:
                raise IndustryClassificationConflict("industry sync selector is invalid")
            selector_params = {field: code}
        for flag in ("Y", "N"):
            result = provider.fetch_index_member_all(IndexMemberAllRequest(is_new=flag, **selector_params))
            report = self.import_member_rows(list(result.rows), provenance=result.provenance.as_dict())
            received += len(result.rows)
            inserted += int(report["inserted"])
            updated += int(report["updated"])
            kept += int(report["kept"])
            quarantined += len(getattr(result, "quarantined", ()) or ())
        return received, inserted, updated, kept, quarantined

    def list_sync_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return [self._public_job(row) for row in self._execute(
            """SELECT * FROM industry_classification_sync_jobs
               ORDER BY created_at DESC, job_id DESC LIMIT :limit""",
            {"limit": limit},
        )]

    def get_sync_job(self, job_id: object) -> dict[str, Any]:
        row = self._fetch_one(
            "SELECT * FROM industry_classification_sync_jobs WHERE job_id=:job_id",
            {"job_id": str(job_id)},
        )
        if row is None:
            raise IndustryClassificationNotFound("industry sync job not found")
        return self._public_job(row)

    def _finish_job(
        self, job_id: str, *, status: str, received: int, inserted: int, updated: int, kept: int,
        quarantined: int = 0, error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as connection:
            row = fetch_one(connection, "SELECT * FROM industry_classification_sync_jobs WHERE job_id=:job_id", {"job_id": job_id})
            if row is None:
                raise IndustryClassificationNotFound("industry sync job not found")
            execute(connection, """UPDATE industry_classification_sync_jobs SET
                status=:status, progress=100, rows_received=:received, rows_inserted=:inserted,
                rows_updated=:updated, rows_kept=:kept, rows_quarantined=:quarantined,
                error_code=:error_code, error_message=:error_message, completed_at=:now, updated_at=:now
                WHERE job_id=:job_id""", {
                "job_id": job_id, "status": status, "received": received, "inserted": inserted,
                "updated": updated, "kept": kept, "quarantined": quarantined, "error_code": error_code,
                "error_message": error_message, "now": now,
            })
            self._audit(connection, job_id, str(row["requested_by"]), "finished", status, {
                "kind": str(row["kind"]), "rows_received": received, "rows_inserted": inserted,
                "rows_updated": updated, "rows_kept": kept, "rows_quarantined": quarantined,
            })
        return self.get_sync_job(job_id)

    @staticmethod
    def _audit(connection, job_id: str, actor: str, action: str, outcome: str, detail: dict[str, object]) -> None:
        execute(connection, """INSERT INTO industry_classification_sync_audit
            (audit_id, job_id, actor_principal, action, outcome, detail_json, created_at)
            VALUES (:audit_id, :job_id, :actor, :action, :outcome, :detail, :now)""", {
            "audit_id": f"industryaudit_{uuid.uuid4().hex}",
            "job_id": job_id, "actor": actor, "action": action, "outcome": outcome,
            "detail": detail, "now": _now(),
        })

    @staticmethod
    def _public_job(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "provider": row["provider"],
            "kind": row["kind"],
            "mode": row["mode"],
            "src": row["src"],
            "level": row["level"],
            "selector": row["selector"],
            "status": row["status"],
            "progress": row["progress"],
            "rows_received": row["rows_received"],
            "rows_inserted": row["rows_inserted"],
            "rows_updated": row["rows_updated"],
            "rows_kept": row["rows_kept"],
            "rows_quarantined": row["rows_quarantined"],
            "error_code": row["error_code"],
            "error_message": row["error_message"],
            "requested_by": row["requested_by"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }
