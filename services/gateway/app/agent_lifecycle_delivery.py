"""Durable delivery bookkeeping for BYQ WorkflowTrace, never a model/job queue."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event


MAX_ATTEMPTS = 8
DEADLINE_SECONDS = 24 * 3600
BACKOFF_SECONDS = (2, 5, 15, 60, 300, 900, 3600, 3600)


class LifecycleDelivery:
    def __init__(self, root, traces, send, *, clock=time.time):
        self.root = Path(root)
        self.traces, self.send, self.clock = traces, send, clock
        self.stop = threading.Event()
        self.thread = None

    def register(self, session):
        # Reuse the trace filename validator; no paths come from event payloads.
        self.traces._path(session.session_id)
        context = {"session_id": session.session_id, "trace_id": session.trace_id,
                   "conversation_id": session.conversation_id, "workspace_id": session.workspace_id,
                   "owner": session.principal.subject}
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{session.session_id}.lifecycle.json"
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                if json.loads(path.read_text())["context"] != context:
                    raise ValueError("lifecycle delivery context cannot change")
            else:
                self._save(path, {"context": context, "cursor": 0, "pending": {}})

    def _save(self, path, state):
        # Atomic replace + file/directory fsync; attempt charge precedes network.
        fd, name = tempfile.mkstemp(prefix=".lifecycle-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(state, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def drain(self, path):
        with path.with_suffix(".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            state = json.loads(path.read_text())
            ctx = state["context"]
            # Recovers the crash gap between trace fsync and delivery bookkeeping.
            trace_path = self.traces._path(ctx["session_id"])
            modified = trace_path.stat().st_mtime_ns if trace_path.exists() else 0
            sources = (self.traces.read(ctx["session_id"], after_sequence=state["cursor"])
                       if modified != state.get("trace_mtime_ns") else [])
            for source in sources[:256]:
                try:
                    event = project_lifecycle_event(source, ctx["session_id"], ctx["trace_id"])
                except ValueError:
                    # Preserve a visible local rejection, not a fabricated ack.
                    state["pending"][str(source["sequence"])] = {"status": "invalid_event"}
                    event = None
                if event and event["outcome"] != "active":
                    terminals = state.setdefault("terminal_events", {})
                    if event["root_run_id"] in terminals:
                        # Soft cancellation can later emit a discarded-result
                        # notification. The original terminal remains canonical.
                        event = None
                    else:
                        terminals[event["root_run_id"]] = event["sequence"]
                if event:
                    state["pending"][str(source["sequence"])] = {
                        "event": event, "status": "pending", "attempts": 0,
                        "created_at": self.clock(), "next_at": self.clock()}
                state["cursor"] = source["sequence"]
            if modified != state.get("trace_mtime_ns"):
                state["trace_mtime_ns"] = modified if len(sources) <= 256 else None
                self._save(path, state)
            budget = 16
            for key, item in list(state["pending"].items()):
                if self.stop.is_set() or budget == 0:
                    break
                if item["status"] != "pending":
                    continue
                now = self.clock()
                if item["attempts"] >= MAX_ATTEMPTS or now >= item["created_at"] + DEADLINE_SECONDS:
                    item["status"] = "exhausted"
                    self._save(path, state)
                    continue
                if now < item["next_at"]:
                    continue
                budget -= 1
                item["attempts"] += 1
                item["next_at"] = now + BACKOFF_SECONDS[item["attempts"] - 1]
                self._save(path, state)
                try:
                    reply = self.send(ctx, item["event"])
                    if reply != {"receipt": lifecycle_receipt(item["event"])}:
                        raise ValueError("lifecycle receipt mismatch")
                except Exception:
                    # All failures consume the same durable, finite budget.
                    # No raw error/credential is persisted; never dispatch DSH.
                    continue
                state["last_receipt"] = reply["receipt"]
                del state["pending"][key]
                self._save(path, state)

    def run_once(self):
        for path in sorted(self.root.glob("*.lifecycle.json")):
            if self.stop.is_set():
                break
            try:
                self.drain(path)
            except (OSError, ValueError, KeyError, TypeError):
                # A damaged session ledger cannot block other sessions.
                continue

    def status(self, context):
        self.traces._path(context["session_id"])
        path = self.root / f"{context['session_id']}.lifecycle.json"
        result = {"schema_version": "agent-run-delivery-status.v1", "state": "not_registered",
                  "pending_events": 0, "exhausted_events": 0, "rejected_events": 0,
                  "max_attempts": MAX_ATTEMPTS, "deadline_seconds": DEADLINE_SECONDS}
        if not path.exists():
            return result
        try:
            state = json.loads(path.read_text())
            if state["context"] != context:
                raise ValueError("delivery context mismatch")
            for item in state["pending"].values():
                field = {"pending": "pending_events", "exhausted": "exhausted_events"}.get(item["status"], "rejected_events")
                result[field] += 1
            trace_path = self.traces._path(context["session_id"])
            changed = trace_path.exists() and trace_path.stat().st_mtime_ns != state.get("trace_mtime_ns")
            result["state"] = ("attention_required" if result["exhausted_events"] or result["rejected_events"] else
                               "pending" if result["pending_events"] or changed else "up_to_date")
        except (OSError, ValueError, KeyError, TypeError):
            result["state"] = "unavailable"
        return result

    def start(self):
        self.stop.clear()
        def work():
            while not self.stop.is_set():
                self.run_once()
                self.stop.wait(1.0)
        self.thread = threading.Thread(target=work, name="byq-agent-lifecycle-delivery", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
