"""Non-forwarding Provider: schema-valid domain rejection then one valid repair."""
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from helpers import fields, stream
from tests.test_strategy_artifact import strategy_payload
from tests.test_ml_strategy import valid_strategy

state = {"calls": 0, "total": 0, "hint_observed": False}


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
            assert set(body) == {"owner", "action"}
            assert re.fullmatch(r"ci-f7-repair-(strategy|ml)", body["owner"])
            assert body["action"] in {"byq_strategy_validate", "byq_ml_strategy_create"}
            state.update(calls=0, hint_observed=False, **body)
            self.send_response(204)
            self.end_headers()
            return
        state["calls"] += 1
        state["total"] += 1
        count, action = state["calls"], state["action"]
        assert count <= 5 and state["total"] <= 10, "native stop did not bound repair"
        results = [m.get("content") for m in body.get("messages", []) if m.get("role") == "tool"]
        if count == 5:
            assert fields(results, "artifact_id"), "repair did not yield an artifact"
            raw = stream(None, {}, count, text="合成策略已校验；未批准、未训练、未回测。")
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if count == 1:
            name, args = "byq_agent_run_start", {"role_id": "strategy_researcher" if action == "byq_strategy_validate" else "ml_researcher", "idempotency_key": "diagnostic-run"}
        elif count == 2:
            name, args = "byq_research_task_create", {"owner_principal": state["owner"],
                "title": "合成错误提示验收", "objective": "验证一次修正与安全错误，不执行研究。",
                "trace_id": "not-authority", "idempotency_key": "diagnostic-task"}
        else:
            if count == 4:
                visible = json.dumps(results)
                expected = "strategy.script" if action == "byq_strategy_validate" else "split.train.start"
                assert expected in visible, "model did not receive the safe field hint"
                assert "synthetic_private_module" not in visible
                assert "request_sha256" not in visible and "input_sha256" not in visible
                state["hint_observed"] = True
            strategy = strategy_payload(script=f"import synthetic_private_module_{count}") if action == "byq_strategy_validate" else valid_strategy()
            if action == "byq_ml_strategy_create":
                strategy["split"]["train"]["start"] = "2020-02-31" if count == 3 else "2020-01-01"
            if count == 4 and action == "byq_strategy_validate":
                strategy = strategy_payload()
            name, args = action, {"task_id": fields(results, "task_id")[-1],
                "agent_run_id": fields(results, "run_id")[-1], "idempotency_key": f"diagnostic-{count}",
                "strategy": strategy, **({"trace_id": "not-authority"} if action == "byq_strategy_validate" else {})}
        raw = stream("mcp__byq__" + name, args, count)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
