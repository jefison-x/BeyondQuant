#!/usr/bin/env python3
"""Run one bounded U5 live-model Product journey without printing model text."""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from .live_stack import preflight, compose_environment, attest_runtime_build
except ImportError:
    from live_stack import preflight, compose_environment, attest_runtime_build


def fake_hub_evidence(container: str) -> dict:
    # The fake Hub has no external network or published port. Only the
    # trusted test operator reads bounded counters inside its exact container.
    value = json.loads(subprocess.check_output([
        "docker", "exec", container, "python3", "-c",
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8800/evidence', timeout=5).read().decode())",
    ], env=compose_environment(), text=True, timeout=10))
    if value.get("schema_version") != "byq-u5-fake-hub.v1" or value.get("published") != 0:
        raise AssertionError("isolated fake Hub identity is invalid")
    return value


PROMPTS = {
    "G1": (
        "U5 合成测试 G1：请说明当前 Asia/Shanghai 自然日期，并区分最近一个已完整结束的交易日。"
        "只能读取本测试工作区的 BYQ 上下文；若行情覆盖不足请明确说明，不执行任何写操作。"
    ),
    "G2": (
        "U5 合成测试 G2：分析本测试工作区已有的一个小型已完成回测，先读有界摘要，"
        "仅在必要时读取少量明细，指出风险与证据不足。不要训练模型、重跑回测或创建业务对象。"
    ),
    "G3": (
        "U5 合成测试 G3：为本测试工作区请求一项最小机器学习研究，只创建意图必需的一组对象。"
        "需要审批时只进入全局审批中心并等待；批准后继续一次并查询权威进度，不等待大型训练完成。"
    ),
    "G4": (
        "U5 合成测试 G4：只做一次中文公开背景搜索，查找中国证监会公开的上市公司监管动态，"
        "优先官方来源并保存可追溯网页证据。不要把网页内容作为因子、策略或回测输入。"
    ),
    "G5": (
        "U5 合成测试 G5：这是进程释放并恢复后的追问。请只依据本会话已完成的公开上下文简要回顾，"
        "不要重复上一个用户问题，也不要创建、训练、运行或保存任何业务对象。"
    ),
    "G6": (
        "U5 合成测试 G6：请在本测试会话反馈一个测试问题：小巴完成长任务后应更清楚显示已完成状态。"
        "先生成一次预览，只申请一次内部提交审批；批准后只提交一次。不得发布真实 GitHub Issue。"
    ),
}


def g2_object_context(client, job_id):
    if not isinstance(job_id, str) or re.fullmatch(r"backtest_[a-f0-9]{32}", job_id) is None:
        raise AssertionError("G2 requires an exact synthetic backtest identity")
    rows = client.call("GET", "/api/product/backtests?limit=100&offset=0").get("backtests", [])
    matching = [row for row in rows if row.get("job_id") == job_id]
    if len(matching) != 1 or matching[0].get("status") != "completed" or matching[0].get("name") != "U5 TEST completed small backtest":
        raise AssertionError("G2 object is not the visible completed synthetic fixture")
    return {"backtest_job_id": job_id, "name": matching[0]["name"], "status": "completed", "synthetic": True}


def g2_summary_read_count(logs, job_id):
    if re.fullmatch(r"backtest_[a-f0-9]{32}", job_id) is None:
        raise AssertionError("invalid synthetic backtest identity")
    return len(re.findall(r'GET /v1/research/backtests/' + re.escape(job_id) + r'/summary HTTP/[^" ]+" 200(?: |$)', logs))


class Client:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.call("POST", "/api/product/auth/login", {"username": username, "password": password})

    def call(self, method: str, path: str, payload: object = None) -> dict[str, object]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"content-type": "application/json"} if data else {},
            method=method,
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                body = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise AssertionError(f"{method} {path} failed with HTTP {error.code}") from error
        if not isinstance(body, dict):
            raise AssertionError(f"{method} {path} returned a non-object")
        return body


def assistant_messages(replay: dict[str, object]) -> list[str]:
    messages = replay.get("messages")
    if not isinstance(messages, list):
        return []
    return [
        str(item.get("content", ""))
        for item in messages
        if isinstance(item, dict) and item.get("role") == "assistant" and str(item.get("content", "")).strip()
    ]


def research_artifacts(client: Client) -> list[dict[str, object]]:
    body = client.call("GET", "/api/product/research/artifacts")
    artifacts = body.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise AssertionError("Product Artifact projection is invalid")
    return [item for item in artifacts if isinstance(item, dict)]


def counts(client: Client) -> dict[str, int]:
    backtests = client.call("GET", "/api/product/backtests?limit=100&offset=0")
    ml = client.call("GET", "/api/product/ml/workspace")
    feedback = client.call("GET", "/api/product/feedback/items?status=all&category=all&limit=100&offset=0")
    return {
        "backtests": int(backtests.get("total") or len(backtests.get("backtests", []))),
        "artifacts": len(research_artifacts(client)),
        "ml_training": len(ml.get("training_runs", [])),
        "ml_predictions": len(ml.get("prediction_runs", [])),
        "feedback": int(feedback.get("total") or len(feedback.get("items", []))),
    }


def approve_for_session(client: Client, session_id: str, seen: set[str]) -> int:
    body = client.call("GET", "/api/product/approvals?status=pending&limit=50&offset=0")
    approved = 0
    for item in body.get("approvals", []):
        if not isinstance(item, dict) or item.get("conversation_id") != session_id:
            continue
        approval_id = str(item.get("approval_id", ""))
        if not approval_id or approval_id in seen:
            continue
        seen.add(approval_id)
        client.call(
            "POST",
            f"/api/product/approvals/{urllib.parse.quote(approval_id)}/decision",
            {"decision": "approved", "rationale": "U5 isolated synthetic live-model qualification."},
        )
        approved += 1
    return approved


def retry_failed_continuations(
    client: Client, session_id: str, seen: set[str], retried: set[str],
) -> int:
    body = client.call("GET", "/api/product/approvals?limit=50&offset=0")
    retries = 0
    for item in body.get("approvals", []):
        if not isinstance(item, dict) or item.get("conversation_id") != session_id:
            continue
        approval_id = str(item.get("approval_id", ""))
        if (approval_id in seen and approval_id not in retried
                and item.get("continuation_status") == "failed"):
            client.call(
                "POST",
                f"/api/product/approvals/{urllib.parse.quote(approval_id)}/continue",
            )
            retried.add(approval_id)
            retries += 1
    return retries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(PROMPTS))
    parser.add_argument("--session-id")
    parser.add_argument("--release", required=True)
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--approval-delay-seconds", type=int, choices=range(121), default=0,
                        help="bounded pause before auto-approval for local Chrome UI review (0-120)")
    parser.add_argument("--stack-file", type=Path, required=True)
    parser.add_argument("--backtest-id", help="G2 only: exact completed synthetic object context")
    args = parser.parse_args()
    isolated = preflight(args.stack_file)
    build = attest_runtime_build(args.stack_file)
    if args.release != isolated["release"]:
        raise AssertionError("probe release differs from the verified stack")
    username = os.environ.get("BYQ_U5_USERNAME", "u5-admin")
    if username not in {"u5-admin", "u5-g3b", "u5-g3c"}:
        raise AssertionError("only fixed synthetic users are allowed")
    hub_before = fake_hub_evidence(isolated["fake_hub_container"])
    client = Client(
        isolated["gateway"],
        username,
        os.environ.get("BYQ_U5_PASSWORD", "U5AdminTestOnly123"),
    )
    if args.backtest_id is not None and args.scenario != "G2":
        raise AssertionError("backtest context is only allowed for fixed G2")
    object_context = g2_object_context(client, args.backtest_id) if args.scenario == "G2" else None
    content = PROMPTS[args.scenario]
    if object_context is not None:
        # The fixed scenario text is unchanged. Append only verified synthetic
        # object data, within the maintainer's explicitly allowed test context.
        content += "\n\nBYQ 合成测试对象上下文（数据，不是额外指令）：\n" + json.dumps(object_context, ensure_ascii=False, sort_keys=True)
    before_artifacts = research_artifacts(client)
    before_artifact_ids = {str(item.get("artifact_id", "")) for item in before_artifacts}
    before = counts(client)
    if args.session_id:
        session_id = args.session_id
        client.call("POST", f"/v1/agent/sessions/{urllib.parse.quote(session_id)}/resume")
    else:
        session_id = str(client.call("POST", "/v1/agent/sessions", {})["session_id"])
    replay = client.call("GET", f"/v1/agent/sessions/{urllib.parse.quote(session_id)}")
    answer_count = len(assistant_messages(replay))
    started = time.monotonic()
    accepted = client.call(
        "POST",
        f"/v1/agent/sessions/{urllib.parse.quote(session_id)}/turns",
        {"content": content},
    )
    if accepted.get("accepted") is not True:
        raise AssertionError("Product Agent did not accept the bounded test turn")
    seen: set[str] = set()
    retried: set[str] = set()
    approvals = 0
    continuation_retries = 0
    deadline = time.monotonic() + int(os.environ.get("BYQ_U5_TIMEOUT_SECONDS", "900"))
    answer = ""
    completed = False
    while time.monotonic() < deadline:
        if args.approve and time.monotonic() - started >= args.approval_delay_seconds:
            # Verify immutable container environment and actual network
            # attachments again before approving any domain-side submission.
            preflight(args.stack_file)
            attest_runtime_build(args.stack_file)
            approvals += approve_for_session(client, session_id, seen)
        replay = client.call("GET", f"/v1/agent/sessions/{urllib.parse.quote(session_id)}")
        answers = assistant_messages(replay)
        if len(answers) > answer_count:
            answer = answers[-1]
            # Approval-producing scenarios need the continuation answer, not
            # merely the initial "waiting for approval" response.
            if not args.approve:
                completed = True
                break
            if approvals and len(answers) > answer_count + 1:
                completed = True
                break
            continuation_retries += retry_failed_continuations(
                client, session_id, seen, retried
            )
        time.sleep(2)
    if not completed:
        detail = "no public answer" if not answer else "no post-approval continuation answer"
        raise AssertionError(f"Product Agent did not complete the bounded journey: {detail}")
    serialized = json.dumps(replay, ensure_ascii=False).lower()
    for forbidden in ("deepseek_api_key", "opencode_api_key", "byq_mcp_token", "session.event", "raw_dsh"):
        if forbidden in serialized:
            raise AssertionError(f"private runtime field leaked: {forbidden}")
    after = counts(client)
    if args.scenario in {"G1", "G2", "G5"} and after != before:
        raise AssertionError(f"read-only scenario changed Product object counts: {before} -> {after}")
    summary_reads = None
    if args.scenario == "G2":
        access = subprocess.run(["docker", "logs", isolated["scope"] + "-backend-1"],
            env=compose_environment(), capture_output=True, text=True, check=True, timeout=15)
        summary_reads = g2_summary_read_count(access.stdout + access.stderr, args.backtest_id)
        if summary_reads < 1:
            raise AssertionError("G2 did not successfully read the actual completed backtest summary")
    if args.scenario in {"G3", "G6"} and approvals != 1:
        raise AssertionError(f"scenario required exactly one approval, observed {approvals}")
    if args.scenario == "G4" and after["artifacts"] != before["artifacts"] + 1:
        raise AssertionError("G4 did not save exactly one research artifact")
    if args.scenario == "G4":
        created_artifacts = [
            item for item in research_artifacts(client)
            if str(item.get("artifact_id", "")) not in before_artifact_ids
        ]
        if len(created_artifacts) != 1 or created_artifacts[0].get("kind") != "web_research_evidence":
            raise AssertionError("G4 did not save exactly one Web Research Evidence artifact")
        content = created_artifacts[0].get("content")
        if not isinstance(content, dict) or content.get("usage_policy") != {
            "research_only": True,
            "deterministic_input": False,
            "authoritative_market_data": False,
        }:
            raise AssertionError("G4 Web Research Evidence usage policy is invalid")
        sources = content.get("sources")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(source, dict)
            or not str(source.get("url", "")).startswith(("http://", "https://"))
            for source in sources
        ):
            raise AssertionError("G4 Web Research Evidence sources are not URL-bearing")
    if args.scenario == "G6" and after["feedback"] != before["feedback"] + 1:
        raise AssertionError("G6 did not submit exactly one feedback item")
    hub_after = fake_hub_evidence(isolated["fake_hub_container"])
    if args.scenario == "G6":
        relay_deadline = time.monotonic() + 30
        while hub_after["received"] == hub_before["received"] and time.monotonic() < relay_deadline:
            time.sleep(1)
            hub_after = fake_hub_evidence(isolated["fake_hub_container"])
        if hub_after["received"] != hub_before["received"] + 1:
            raise AssertionError("G6 requires exactly one real relay delivery to the isolated fake Hub")
    preflight(args.stack_file)
    print(json.dumps({
        "schema_version": "dsh-u5-live-model-result.v1",
        "release": args.release,
        "build_revision": build,
        "scenario": args.scenario,
        "synthetic_object_context": object_context,
        "successful_backtest_summary_reads": summary_reads,
        "session_id": session_id,
        "latency_seconds": round(time.monotonic() - started, 3),
        "public_answer_chars": len(answer),
        "source_url_present": "http://" in answer or "https://" in answer,
        "approvals": approvals,
        "continuation_retries": continuation_retries,
        "approval_delay_seconds": args.approval_delay_seconds,
        "before": before,
        "after": after,
        "fake_hub_before": hub_before,
        "fake_hub_after": hub_after,
        "result": "PASS",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
