"""Local-only scripted transport probe, not a natural-language model evaluation."""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from native_provider import fields, stream

GOAL = "合成验收：沪深300近三年普通动量双均线，每周调仓，先研究凯利仓位管理。"
NEW = "改为中证500，只讨论方案，不执行研究。"
state = {"phase": 1, "calls": 0, "total": 0, "checks": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        raw = json.dumps(state).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        if not 0 < length <= 2 * 1024 * 1024:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        if self.path == "/control":
            assert set(body) == {"phase"} and body["phase"] in (2, 3)
            assert body["phase"] == state["phase"] + 1
            state.update(phase=body["phase"], calls=0)
            self.send_response(204)
            self.end_headers()
            return
        state["calls"] += 1
        state["total"] += 1
        count, phase = state["calls"], state["phase"]
        if count > 5 or state["total"] > 10:
            self.send_error(429)
            return
        messages = body.get("messages", [])
        serialized = json.dumps(messages, ensure_ascii=False)
        results = [item.get("content") for item in messages if item.get("role") == "tool"]
        answer = None
        try:
            if phase == 1:
                if count == 1:
                    name, args = "byq_agent_run_start", {"role_id": "strategy_researcher", "idempotency_key": "recovery-root"}
                elif count == 2:
                    name, args = "byq_research_task_create", {"owner_principal": "ci-recovery-context", "title": "原始沪深300合成研究",
                        "objective": GOAL, "trace_id": "synthetic-not-authority", "idempotency_key": "recovery-task"}
                else:
                    assert count in (3, 4)
                    name, args = "byq_strategy_validate", {"task_id": fields(results, "task_id")[-1],
                        "agent_run_id": fields(results, "run_id")[-1], "idempotency_key": f"recovery-invalid-{count}",
                        "strategy": {} if count == 3 else {"name": "invalid-repair"}}
            elif phase == 2:
                if count == 1:
                    assert GOAL in serialized and "继续" in serialized
                    assert not re.search(r"task_[a-f0-9]{32}", serialized)
                    state["checks"].append("original-goal-present-without-private-task-id")
                    name, args = "byq_agent_context", {}
                elif count == 2:
                    ids = fields(results, "task_id")
                    assert len(set(ids)) == 1
                    assert "沪深300" in json.dumps(results, ensure_ascii=False)
                    name, args = "byq_research_get", {"entity_type": "research_task", "entity_id": ids[0]}
                    state["checks"].append("exact-id-discovered-only-from-mcp-context")
                else:
                    assert count == 3 and GOAL in fields(results, "objective")
                    name, args = None, {}
                    answer = "已找到原会话的沪深300任务，研究尚未完成；本轮只核查，没有执行训练或回测。"
                    state["checks"].append("original-task-read-without-recreation")
            else:
                assert count == 1 and NEW in serialized
                name, args = None, {}
                answer = "本轮以中证500新要求为准，只讨论方案，不继续执行此前沪深300任务。"
                state["checks"].append("explicit-new-goal-delivered")
            wire = None if name is None else "mcp__byq__" + name
            assert wire is None or wire in {item["function"]["name"] for item in body.get("tools", [])}
        except (AssertionError, IndexError):
            state["checks"].append(f"FAILED-phase-{phase}-call-{count}")
            self.send_error(422, "synthetic probe invariant failed")
            return
        raw = stream(wire, args, state["total"], text=answer)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
