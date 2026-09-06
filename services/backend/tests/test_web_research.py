from __future__ import annotations

import copy
import hashlib
import json
import os
import unittest
from unittest.mock import patch

from app.research import ResearchStore
from app.web_evidence_provenance import default_policy_path
from app.web_research import (
    SCHEMA_VERSION,
    normalize_web_research_evidence,
    validate_web_research_evidence,
)


def evidence_fixture() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "research_as_of": "2026-08-28T12:00:00+08:00",
        "market_context": {
            "as_of_date": "20260828",
            "trading_session": "20260828",
            "persisted_data_cutoff": "20260827",
            "calendar_verified": True,
        },
        "search": {
            "plugin_id": "web-search",
            "plugin_version": "0.1.1-rc.1",
            "queries": [
                {"text": "site:csrc.gov.cn 上市公司 监管 公告", "language": "zh", "purpose": "查找监管原文"},
                {"text": "listed company announcement regulator", "language": "en", "purpose": "交叉验证英文公开材料"},
            ],
            "stopped_reason": "EVIDENCE_SUFFICIENT",
        },
        "sources": [
            {
                "source_id": "source_csrc",
                "url": "https://www.csrc.gov.cn/example",
                "title": "监管公告",
                "publisher": "中国证监会",
                "source_tier": "PRIMARY",
                "published_at": "2026-08-27T09:00:00+08:00",
                "retrieved_at": "2026-08-28T11:30:00+08:00",
                "temporal_status": "WITHIN_AS_OF",
                "query_indexes": [0],
                "summary": "监管机构发布的有界事实摘要。",
            },
            {
                "source_id": "source_media",
                "url": "https://finance.example.com/report",
                "title": "财经媒体报道",
                "publisher": "Example Finance",
                "source_tier": "SECONDARY",
                "published_at": "2026-08-27T10:00:00+08:00",
                "retrieved_at": "2026-08-28T11:31:00+08:00",
                "temporal_status": "WITHIN_AS_OF",
                "query_indexes": [1],
                "summary": "对官方公告的次级报道。",
            },
        ],
        "claims": [
            {
                "statement": "监管公告已在研究时点前发布。",
                "claim_type": "FACT",
                "state": "SUPPORTED",
                "source_ids": ["source_csrc"],
            }
        ],
        "limitations": ["网页证据不代表 BYQ persisted market data 已同步。"],
        "usage_policy": {
            "research_only": True,
            "deterministic_input": False,
            "authoritative_market_data": False,
        },
    }


class WebResearchEvidenceTests(unittest.TestCase):
    def test_historical_evidence_bytes_and_hash_remain_unchanged(self) -> None:
        fixture = evidence_fixture()
        before = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        expected_hash = hashlib.sha256(before).hexdigest()

        self.assertIs(validate_web_research_evidence(fixture), fixture)

        after = json.dumps(fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(after, before)
        self.assertEqual(hashlib.sha256(after).hexdigest(), expected_hash)

    def test_default_rejects_unknown_but_candidate_policy_allows_rolling_versions(self) -> None:
        unknown = evidence_fixture()
        unknown["search"]["plugin_version"] = "9.9.9"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "producer is not recognized"):
            validate_web_research_evidence(unknown)

        candidate_policy = default_policy_path().with_name(
            "dsh-0.1.2rc1.web-evidence-provenance.json"
        )
        with patch.dict(os.environ, {"BYQ_WEB_EVIDENCE_PROVENANCE_POLICY": str(candidate_policy)}):
            old = evidence_fixture()
            candidate = evidence_fixture()
            candidate["search"]["plugin_version"] = "0.1.2-rc.1"  # type: ignore[index]
            validate_web_research_evidence(old)
            validate_web_research_evidence(candidate)

    def test_system_generates_stable_source_ids_and_resolves_claim_indexes(self) -> None:
        fixture = evidence_fixture()
        for source in fixture["sources"]:  # type: ignore[index]
            source.pop("source_id")
        fixture["claims"][0]["source_indexes"] = [0]  # type: ignore[index]
        fixture["claims"][0].pop("source_ids")  # type: ignore[index]

        normalized = normalize_web_research_evidence(fixture)

        source_ids = [source["source_id"] for source in normalized["sources"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertTrue(all(str(source_id).startswith("source_") for source_id in source_ids))
        self.assertEqual(normalized["claims"][0]["source_ids"], [source_ids[0]])
        self.assertEqual(normalize_web_research_evidence(fixture), normalized)
        validate_web_research_evidence(normalized)

    def test_system_rejects_invalid_claim_source_index(self) -> None:
        fixture = evidence_fixture()
        for source in fixture["sources"]:  # type: ignore[index]
            source.pop("source_id")
        fixture["claims"][0]["source_indexes"] = [99]  # type: ignore[index]
        fixture["claims"][0].pop("source_ids")  # type: ignore[index]

        with self.assertRaisesRegex(ValueError, "claim source_indexes"):
            normalize_web_research_evidence(fixture)

    def test_valid_evidence_and_artifact_promotion_contract(self) -> None:
        fixture = evidence_fixture()
        self.assertIs(validate_web_research_evidence(fixture), fixture)
        payload = ResearchStore._artifact_payload(
            {
                "task_id": "task_0123456789abcdef0123456789abcdef",
                "kind": "web_research_evidence",
                "content": fixture,
                "lineage": [],
                "trace_id": "trace-web-1",
                "idempotency_key": "web-evidence-1",
            }
        )
        self.assertEqual(payload["kind"], "web_research_evidence")
        self.assertRegex(str(payload["content_sha256"]), r"^[0-9a-f]{64}$")

    def test_no_results_is_explicit_and_does_not_invent_support(self) -> None:
        fixture = evidence_fixture()
        fixture["search"]["stopped_reason"] = "NO_RESULTS"  # type: ignore[index]
        fixture["sources"] = []
        fixture["claims"] = [
            {
                "statement": "现有证据无法建立原因",
                "claim_type": "CAUSAL",
                "state": "UNESTABLISHED",
                "source_ids": [],
            }
        ]
        validate_web_research_evidence(fixture)

    def test_conflicting_sources_are_preserved(self) -> None:
        fixture = evidence_fixture()
        fixture["claims"] = [
            {
                "statement": "官方材料与媒体对事件范围表述不一致。",
                "claim_type": "FACT",
                "state": "CONFLICTED",
                "source_ids": ["source_csrc", "source_media"],
            }
        ]
        validate_web_research_evidence(fixture)

    def test_duplicate_query_and_source_are_rejected(self) -> None:
        fixture = evidence_fixture()
        duplicate_query = copy.deepcopy(fixture)
        duplicate_query["search"]["queries"].append(  # type: ignore[index,union-attr]
            copy.deepcopy(duplicate_query["search"]["queries"][0])  # type: ignore[index]
        )
        with self.assertRaisesRegex(ValueError, "duplicate web search query"):
            validate_web_research_evidence(duplicate_query)

        duplicate_source = copy.deepcopy(fixture)
        second = duplicate_source["sources"][1]  # type: ignore[index]
        second["url"] = duplicate_source["sources"][0]["url"]  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "duplicate source URL"):
            validate_web_research_evidence(duplicate_source)

    def test_future_unknown_and_auxiliary_sources_cannot_support_claim(self) -> None:
        for mutation in ("future", "unknown", "auxiliary"):
            fixture = evidence_fixture()
            source = fixture["sources"][0]  # type: ignore[index]
            if mutation == "future":
                source["published_at"] = "2026-08-29T09:00:00+08:00"
                source["retrieved_at"] = "2026-08-29T10:00:00+08:00"
                source["temporal_status"] = "AFTER_AS_OF"
            elif mutation == "unknown":
                source["published_at"] = None
                source["temporal_status"] = "PUBLISHED_AT_UNKNOWN"
            else:
                source["source_tier"] = "AUXILIARY"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "supported claim"):
                validate_web_research_evidence(fixture)

    def test_causal_claim_requires_primary_source(self) -> None:
        fixture = evidence_fixture()
        fixture["claims"] = [
            {
                "statement": "媒体报道的事件造成了市场变化。",
                "claim_type": "CAUSAL",
                "state": "SUPPORTED",
                "source_ids": ["source_media"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "causal claim requires a primary source"):
            validate_web_research_evidence(fixture)

    def test_stale_news_can_only_be_context_or_unestablished(self) -> None:
        fixture = evidence_fixture()
        source = fixture["sources"][0]  # type: ignore[index]
        source["published_at"] = "2020-01-01T00:00:00+08:00"
        fixture["claims"] = [
            {
                "statement": "旧公告只能作为历史背景，不能证明当前原因。",
                "claim_type": "CAUSAL",
                "state": "UNESTABLISHED",
                "source_ids": ["source_csrc"],
            }
        ]
        validate_web_research_evidence(fixture)

    def test_time_status_market_calendar_and_usage_policy_fail_closed(self) -> None:
        mismatch = evidence_fixture()
        mismatch["sources"][0]["temporal_status"] = "AFTER_AS_OF"  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "temporal_status does not match"):
            validate_web_research_evidence(mismatch)

        calendar = evidence_fixture()
        calendar["market_context"]["calendar_verified"] = False  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "unverified market context"):
            validate_web_research_evidence(calendar)

        policy = evidence_fixture()
        policy["usage_policy"]["deterministic_input"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "research-only"):
            validate_web_research_evidence(policy)

    def test_local_and_credential_bearing_urls_are_rejected(self) -> None:
        for url in (
            "http://localhost/internal",
            "http://127.0.0.1/internal",
            "http://169.254.169.254/metadata",
            "https://user:pass@example.com/report",
        ):
            fixture = evidence_fixture()
            fixture["sources"][0]["url"] = url  # type: ignore[index]
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "source URL"):
                validate_web_research_evidence(fixture)


if __name__ == "__main__":
    unittest.main()
