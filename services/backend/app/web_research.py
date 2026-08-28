"""Versioned validation for persisted Web Research Evidence.

DSH search results are session context until this contract accepts an explicit
promotion request.  The validator stores provenance only; it never fetches a
URL and never turns web content into a deterministic quantitative input.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlsplit


SCHEMA_VERSION = "web-research-evidence.v1"
MAX_QUERIES = 4
MAX_SOURCES = 32
MAX_CLAIMS = 32
SOURCE_TIERS = frozenset({"PRIMARY", "SECONDARY", "AUXILIARY", "UNKNOWN"})
CLAIM_TYPES = frozenset({"FACT", "CAUSAL", "CANDIDATE"})
CLAIM_STATES = frozenset({"SUPPORTED", "CONFLICTED", "UNESTABLISHED"})
TEMPORAL_STATES = frozenset({"WITHIN_AS_OF", "AFTER_AS_OF", "PUBLISHED_AT_UNKNOWN"})
_DATE = re.compile(r"^[0-9]{8}$")
_SOURCE_ID = re.compile(r"^source_[a-z0-9]{1,32}$")
_LANGUAGES = frozenset({"zh", "en", "mixed"})


def validate_web_research_evidence(value: object) -> dict[str, object]:
    """Validate one immutable web-evidence artifact body and return it unchanged."""

    content = _object(value, "content")
    _exact(
        content,
        {
            "schema_version",
            "research_as_of",
            "market_context",
            "search",
            "sources",
            "claims",
            "limitations",
            "usage_policy",
        },
    )
    if content["schema_version"] != SCHEMA_VERSION:
        raise ValueError("web evidence schema_version is not supported")

    research_as_of = _timestamp(content["research_as_of"], "research_as_of")
    _market_context(content["market_context"])
    queries = _queries(content["search"])
    sources = _sources(content["sources"], research_as_of, len(queries))
    _claims(content["claims"], sources)
    _limitations(content["limitations"])
    _usage_policy(content["usage_policy"])
    return content


def _market_context(value: object) -> None:
    context = _object(value, "market_context")
    _exact(
        context,
        {"as_of_date", "trading_session", "persisted_data_cutoff", "calendar_verified"},
    )
    _date(context["as_of_date"], "market_context.as_of_date")
    for field in ("trading_session", "persisted_data_cutoff"):
        candidate = context[field]
        if candidate is not None:
            _date(candidate, f"market_context.{field}")
    if not isinstance(context["calendar_verified"], bool):
        raise ValueError("market_context.calendar_verified must be a boolean")
    if not context["calendar_verified"] and context["trading_session"] is not None:
        raise ValueError("unverified market context cannot claim a trading session")


def _queries(value: object) -> list[dict[str, object]]:
    search = _object(value, "search")
    _exact(search, {"plugin_id", "plugin_version", "queries", "stopped_reason"})
    if search["plugin_id"] != "web-search" or search["plugin_version"] != "0.1.1-rc.1":
        raise ValueError("web evidence must use the qualified search plugin version")
    queries = search["queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise ValueError(f"search.queries must contain 1 to {MAX_QUERIES} entries")
    seen: set[tuple[str, str]] = set()
    for index, query in enumerate(queries):
        item = _object(query, f"search.queries[{index}]")
        _exact(item, {"text", "language", "purpose"})
        text = _text(item["text"], f"search.queries[{index}].text", 300)
        language = item["language"]
        if language not in _LANGUAGES:
            raise ValueError("search query language is not supported")
        _text(item["purpose"], f"search.queries[{index}].purpose", 240)
        fingerprint = (text.casefold(), str(language))
        if fingerprint in seen:
            raise ValueError("duplicate web search query is not allowed")
        seen.add(fingerprint)
    if search["stopped_reason"] not in {
        "EVIDENCE_SUFFICIENT",
        "NO_RESULTS",
        "BUDGET_EXHAUSTED",
        "CONFLICT_UNRESOLVED",
        "PROVIDER_ERROR",
    }:
        raise ValueError("search.stopped_reason is invalid")
    return queries


def _sources(
    value: object,
    research_as_of: datetime,
    query_count: int,
) -> dict[str, dict[str, object]]:
    if not isinstance(value, list) or len(value) > MAX_SOURCES:
        raise ValueError(f"sources must contain at most {MAX_SOURCES} entries")
    by_id: dict[str, dict[str, object]] = {}
    urls: set[str] = set()
    for index, raw in enumerate(value):
        source = _object(raw, f"sources[{index}]")
        _exact(
            source,
            {
                "source_id",
                "url",
                "title",
                "publisher",
                "source_tier",
                "published_at",
                "retrieved_at",
                "temporal_status",
                "query_indexes",
                "summary",
            },
        )
        source_id = source["source_id"]
        if not isinstance(source_id, str) or _SOURCE_ID.fullmatch(source_id) is None:
            raise ValueError("source_id is invalid")
        if source_id in by_id:
            raise ValueError("duplicate source_id is not allowed")
        url = _url(source["url"])
        if url in urls:
            raise ValueError("duplicate source URL is not allowed")
        urls.add(url)
        _text(source["title"], f"sources[{index}].title", 500)
        _text(source["publisher"], f"sources[{index}].publisher", 200)
        if source["source_tier"] not in SOURCE_TIERS:
            raise ValueError("source_tier is invalid")
        retrieved_at = _timestamp(source["retrieved_at"], f"sources[{index}].retrieved_at")
        published_raw = source["published_at"]
        published_at = None if published_raw is None else _timestamp(
            published_raw, f"sources[{index}].published_at"
        )
        temporal_status = source["temporal_status"]
        if temporal_status not in TEMPORAL_STATES:
            raise ValueError("temporal_status is invalid")
        expected = (
            "PUBLISHED_AT_UNKNOWN"
            if published_at is None
            else "WITHIN_AS_OF"
            if published_at <= research_as_of
            else "AFTER_AS_OF"
        )
        if temporal_status != expected:
            raise ValueError("temporal_status does not match published_at and research_as_of")
        if published_at is not None and retrieved_at < published_at:
            raise ValueError("retrieved_at cannot precede published_at")
        query_indexes = source["query_indexes"]
        if (
            not isinstance(query_indexes, list)
            or not query_indexes
            or len(query_indexes) != len(set(query_indexes))
            or any(
                not isinstance(item, int)
                or isinstance(item, bool)
                or item < 0
                or item >= query_count
                for item in query_indexes
            )
        ):
            raise ValueError("source query_indexes are invalid")
        _text(source["summary"], f"sources[{index}].summary", 2_000)
        by_id[source_id] = source
    return by_id


def _claims(value: object, sources: dict[str, dict[str, object]]) -> None:
    if not isinstance(value, list) or len(value) > MAX_CLAIMS:
        raise ValueError(f"claims must contain at most {MAX_CLAIMS} entries")
    for index, raw in enumerate(value):
        claim = _object(raw, f"claims[{index}]")
        _exact(claim, {"statement", "claim_type", "state", "source_ids"})
        _text(claim["statement"], f"claims[{index}].statement", 2_000)
        claim_type = claim["claim_type"]
        state = claim["state"]
        if claim_type not in CLAIM_TYPES or state not in CLAIM_STATES:
            raise ValueError("claim type or state is invalid")
        source_ids = claim["source_ids"]
        if (
            not isinstance(source_ids, list)
            or len(source_ids) != len(set(source_ids))
            or any(item not in sources for item in source_ids)
        ):
            raise ValueError("claim source_ids are invalid")
        referenced = [sources[item] for item in source_ids]
        reliable = [item for item in referenced if item["source_tier"] in {"PRIMARY", "SECONDARY"}]
        time_safe = [item for item in reliable if item["temporal_status"] == "WITHIN_AS_OF"]
        if state == "SUPPORTED" and not time_safe:
            raise ValueError("supported claim requires a reliable source visible within as-of")
        if state == "SUPPORTED" and claim_type == "CAUSAL" and not any(
            item["source_tier"] == "PRIMARY" for item in time_safe
        ):
            raise ValueError("supported causal claim requires a primary source")
        if state == "CONFLICTED" and len(source_ids) < 2:
            raise ValueError("conflicted claim requires at least two sources")
        if state == "UNESTABLISHED" and claim_type == "CAUSAL" and reliable:
            # Reliable sources may document the observations while still failing
            # to establish causation; this is intentionally allowed.
            continue


def _limitations(value: object) -> None:
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("limitations must contain at most 16 entries")
    for index, item in enumerate(value):
        _text(item, f"limitations[{index}]", 500)


def _usage_policy(value: object) -> None:
    policy = _object(value, "usage_policy")
    _exact(policy, {"research_only", "deterministic_input", "authoritative_market_data"})
    if policy != {
        "research_only": True,
        "deterministic_input": False,
        "authoritative_market_data": False,
    }:
        raise ValueError("web evidence usage policy must remain research-only")


def _url(value: object) -> str:
    url = _text(value, "source.url", 2_048)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source URL must be an absolute public HTTP(S) URL without credentials")
    if parsed.fragment:
        raise ValueError("source URL must not contain a fragment")
    host = parsed.hostname.casefold()
    if host in {"localhost", "0.0.0.0", "::1"} or host.endswith((".local", ".internal")):
        raise ValueError("source URL must not reference a local host")
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("source URL must not reference a local host")
    return url


def _timestamp(value: object, field: str) -> datetime:
    text = _text(value, field, 64)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _date(value: object, field: str) -> str:
    text = _text(value, field, 8)
    if _DATE.fullmatch(text) is None:
        raise ValueError(f"{field} must use YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid date") from exc
    return text


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _exact(value: dict[str, object], required: set[str]) -> None:
    if set(value) != required:
        raise ValueError("web evidence contains missing or unknown fields")


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} must be a non-empty string of at most {maximum} characters")
    return value.strip()
