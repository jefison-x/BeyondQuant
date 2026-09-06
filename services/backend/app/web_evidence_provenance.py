"""Read-only trusted producer policy for Web Research Evidence."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


_SCHEMA = "web-evidence-provenance-policy.v1"
_PRODUCER_FIELDS = {
    "plugin_id", "plugin_version", "release_id", "qualification_state", "attestation_sha256"
}
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def default_policy_path() -> Path:
    configured = os.environ.get("BYQ_WEB_EVIDENCE_PROVENANCE_POLICY")
    if configured:
        return Path(configured)
    container_path = Path("/app/web-evidence-provenance.json")
    if container_path.is_file():
        return container_path
    return Path(__file__).resolve().parents[3] / "config/dsh/generated/web-evidence-provenance.json"


def load_web_evidence_provenance(path: Path | None = None) -> dict[str, object]:
    policy_path = path or default_policy_path()
    value = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "mode", "active_producer", "recognized_producers"
    }:
        raise ValueError("web evidence provenance policy has an invalid closed schema")
    if value["schema_version"] != _SCHEMA or value["mode"] not in {"qualified", "candidate"}:
        raise ValueError("web evidence provenance policy is unsupported")
    producers = value["recognized_producers"]
    if not isinstance(producers, list) or not producers:
        raise ValueError("web evidence provenance policy has no recognized producers")
    identities: set[tuple[str, str]] = set()
    for producer in producers:
        _validate_producer(producer)
        identity = (producer["plugin_id"], producer["plugin_version"])
        if identity in identities:
            raise ValueError("web evidence provenance policy has duplicate producers")
        identities.add(identity)
    active = value["active_producer"]
    _validate_producer(active)
    if active not in producers:
        raise ValueError("active web evidence producer is not recognized")
    if value["mode"] == "qualified" and any(
        item["qualification_state"] != "QUALIFIED" for item in producers
    ):
        raise ValueError("qualified web evidence policy contains an unqualified producer")
    if value["mode"] == "qualified" and active["qualification_state"] != "QUALIFIED":
        raise ValueError("default web evidence producer is not qualified")
    if value["mode"] == "candidate" and active["qualification_state"] != "CANDIDATE":
        raise ValueError("candidate web evidence policy does not identify a candidate")
    return value


def _validate_producer(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _PRODUCER_FIELDS:
        raise ValueError("web evidence producer has an invalid closed schema")
    if value["plugin_id"] != "web-search":
        raise ValueError("web evidence producer plugin is unsupported")
    for field in ("plugin_version", "release_id", "qualification_state"):
        if not isinstance(value[field], str) or not value[field]:
            raise ValueError(f"web evidence producer {field} is invalid")
    if value["qualification_state"] not in {"QUALIFIED", "CANDIDATE"}:
        raise ValueError("web evidence producer qualification state is invalid")
    if not isinstance(value["attestation_sha256"], str) or _SHA256.fullmatch(value["attestation_sha256"]) is None:
        raise ValueError("web evidence producer attestation is invalid")


def recognized_producer(plugin_id: object, plugin_version: object) -> bool:
    policy = load_web_evidence_provenance()
    return any(
        item["plugin_id"] == plugin_id and item["plugin_version"] == plugin_version
        for item in policy["recognized_producers"]
    )
