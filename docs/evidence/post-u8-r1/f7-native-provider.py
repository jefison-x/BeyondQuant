"""Bounded local-only native sibling correction probe; never forwards traffic."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
state = {"calls": 0, "total_calls": 0, "root_calls": 0, "children": {"1": 0, "2": 0}, "steps": []}


def fields(value, key):
    if isinstance(value, str):
        try:
            return fields(json.loads(value), key)
        except (ValueError, RecursionError):
            return []
    if isinstance(value, list):
        return [found for item in value for found in fields(item, key)]
    if isinstance(value, dict):
        own = [value[key]] if isinstance(value.get(key), str) else []
        return own + [found for item in value.values() for found in fields(item, key)]
    return []


def stream(name, arguments, number, text=None):
    delta = {"role": "assistant"}
    if text is None:
        delta["tool_calls"] = [{"index": 0, "id": f"native-{number}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}]
    else:
        delta["content"] = text
    frames = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if text is None else "stop"}],
         "usage": {"prompt_tokens": 4, "completion_tokens": 2}}]
    return ("".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n").encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        with lock:
            result = {key: state[key] for key in ("calls", "total_calls", "root_calls", "children", "steps")}
            encoded = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        if not 0 < length <= 2 * 1024 * 1024:
            self.send_error(413)
            return
        body = json.loads(self.rfile.read(length))
        if self.path == "/control":
            assert set(body) == {"action", "owner"}
            assert body["action"] in {"byq_strategy_validate", "byq_ml_strategy_create"}
            assert re.fullmatch(r"ci-f7-native-[a-z]+", body["owner"])
            with lock:
                state.update(calls=0, root_calls=0, children={"1": 0, "2": 0}, steps=[], **body)
            self.send_response(204)
            self.end_headers()
            return
        with lock:
            state["calls"] += 1
            state["total_calls"] += 1
            count = state["calls"]
            action, owner = state["action"], state["owner"]
        if count > 12:
            self.send_error(429, "synthetic request cap")
            return
        delegate = "byq_delegate_strategy_research" if action == "byq_strategy_validate" else "byq_delegate_ml_research"
        role = "strategy_researcher" if action == "byq_strategy_validate" else "ml_researcher"
        tools = {item["function"]["name"] for item in body.get("tools", [])}
        messages = body.get("messages", [])
        results = [item.get("content") for item in messages if item.get("role") == "tool"]
        if delegate in tools:
            with lock:
                state["root_calls"] += 1
                stage = state["root_calls"]
            if stage == 1:
                name, args = "byq_agent_run_start", {"role_id": "quant_orchestrator", "idempotency_key": "native-root"}
            elif stage == 2:
                state["parent"] = fields(results, "run_id")[-1]
                name, args = "byq_research_task_create", {"owner_principal": owner, "title": "Synthetic native sibling test",
                    "objective": "No research execution; verify siblings cannot reset correction", "trace_id": "synthetic-not-authority",
                    "idempotency_key": "native-task"}
            elif stage in (3, 4):
                state["task"] = fields(results, "task_id")[-1]
                name, args = delegate, {"description": "Bounded synthetic sibling probe",
                    "prompt": f"F7_CHILD_{stage - 2} parent={state['parent']} task={state['task']}. Synthetic validation only, no training."}
            else:
                self.send_error(422, "unexpected root continuation")
                return
            actor = "root"
        else:
            markers = set(re.findall(r"F7_CHILD_([12])", json.dumps(messages)))
            if len(markers) != 1:
                self.send_error(422, "ambiguous synthetic child")
                return
            actor = next(iter(markers))
            with lock:
                state["children"][actor] += 1
                stage = state["children"][actor]
            if stage == 1:
                name, args = "byq_agent_run_start", {"role_id": role, "parent_run_id": state["parent"],
                    "idempotency_key": "native-child-" + actor}
            elif stage == 2:
                run = fields(results, "run_id")[-1]
                name, args = action, {"task_id": state["task"], "agent_run_id": run,
                    "idempotency_key": "native-invalid-" + actor, "strategy": {}}
            elif actor == "1" and stage == 3:
                name, args = None, {}
            else:
                self.send_error(422, "unexpected child continuation")
                return
        wire_name = name if name is None or name.startswith("byq_delegate_") else "mcp__byq__" + name
        if wire_name is not None and wire_name not in tools:
            self.send_error(422, "synthetic tool outside ceiling")
            return
        with lock:
            state["steps"].append({"actor": actor, "stage": stage, "tool": name})
        response = stream(wire_name, args, count,
            text="Synthetic first child has recorded one invalid input. Research is incomplete." if name is None else None)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8801), Handler).serve_forever()
