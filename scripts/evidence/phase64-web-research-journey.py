#!/usr/bin/env python3
"""Optional credentialed Product Agent Web Search journey.

The script uses durable Product login and the Gateway only.  Credentials come
from environment variables and are never printed or persisted in evidence.
"""

from __future__ import annotations

import atexit
import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request


BASE = os.environ.get("BYQ_REAL_BASE_URL", "http://127.0.0.1:8100").rstrip("/")
USERNAME = os.environ["BYQ_E2E_ADMIN_USERNAME"]
PASSWORD = os.environ["BYQ_E2E_ADMIN_PASSWORD"]
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)
session_id: str | None = None


def request(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    outgoing = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"content-type": "application/json"} if body else {},
        method=method,
    )
    with opener.open(outgoing, timeout=30) as response:
        if response.status not in {200, 201, 202}:
            raise AssertionError(f"unexpected Product API status: {response.status}")
        value = json.load(response)
        if not isinstance(value, dict):
            raise AssertionError("Product API response must be an object")
        return value


def cleanup_session() -> None:
    if session_id is None:
        return
    try:
        request("DELETE", f"/v1/agent/sessions/{urllib.parse.quote(session_id)}")
    except Exception:
        # Best-effort smoke cleanup must not hide the journey's real result.
        pass


atexit.register(cleanup_session)

request("POST", "/api/product/auth/login", {"username": USERNAME, "password": PASSWORD})
before_body = request("GET", "/api/product/research/artifacts")
before_artifacts = before_body.get("artifacts")
before_ids = {
    str(item.get("artifact_id"))
    for item in before_artifacts
    if isinstance(before_artifacts, list) and isinstance(item, dict)
} if isinstance(before_artifacts, list) else set()
created = request("POST", "/v1/agent/sessions", {})
session_id = str(created["session_id"])
prompt = (
    "请直接交给市场研究能力，只进行一次中文 Web Search，检索中国证监会公开的上市公司监管动态。"
    "本题不需要读取 BYQ 行情、交易日或数据截止，也不要读取其他研究对象。优先引用官方来源，"
    "保留标题、链接、发布时间和检索时间；如果无法建立因果请明确说明。请创建最小研究任务并把"
    "本次网页证据保存为研究记录，但不要把网页数字用于因子、策略或回测。"
)
accepted = request(
    "POST",
    f"/v1/agent/sessions/{urllib.parse.quote(session_id)}/turns",
    {"content": prompt},
)
if accepted.get("accepted") is not True:
    raise AssertionError("Product Agent did not accept the Web Research turn")

assistant_text = ""
replay: dict[str, object] = {}
deadline = time.monotonic() + int(os.environ.get("BYQ_E2E_AGENT_TIMEOUT_SECONDS", "900"))
while time.monotonic() < deadline:
    replay = request("GET", f"/v1/agent/sessions/{urllib.parse.quote(session_id)}")
    messages = replay.get("messages")
    if isinstance(messages, list):
        answers = [
            str(item.get("content", ""))
            for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]
        if answers and answers[-1].strip():
            assistant_text = answers[-1]
            break
    time.sleep(2)
if not assistant_text:
    raise AssertionError(f"Product Agent did not produce a durable assistant answer: {session_id}")
if "http://" not in assistant_text and "https://" not in assistant_text:
    raise AssertionError("Product answer did not preserve source URLs")

serialized_replay = json.dumps(replay, ensure_ascii=False).lower()
for forbidden in (
    "deepseek_api_key",
    "opencode_api_key",
    "byq_mcp_token",
    "session.event",
    "tool_use",
    "raw_dsh",
):
    if forbidden in serialized_replay:
        raise AssertionError(f"private runtime field leaked: {forbidden}")

artifact_body = request("GET", "/api/product/research/artifacts")
artifacts = artifact_body.get("artifacts")
if not isinstance(artifacts, list):
    raise AssertionError("Product Artifact projection is invalid")
matching = [
    item
    for item in artifacts
    if isinstance(item, dict)
    and item.get("kind") == "web_research_evidence"
    and str(item.get("artifact_id")) not in before_ids
]
if not matching:
    raise AssertionError("saved Web Research Evidence artifact was not found")
content = matching[0].get("content")
if not isinstance(content, dict) or content.get("usage_policy") != {
    "research_only": True,
    "deterministic_input": False,
    "authoritative_market_data": False,
}:
    raise AssertionError("saved Web Research Evidence usage policy is invalid")

print(
    json.dumps(
        {
            "assistant_answer": "source-bearing-and-normalized",
            "artifact_kind": "web_research_evidence",
            "credential": "externally-configured-not-read",
            "product_path": "Gateway/Product API",
            "resume": "durable-before-smoke-cleanup",
            "session_id": session_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
