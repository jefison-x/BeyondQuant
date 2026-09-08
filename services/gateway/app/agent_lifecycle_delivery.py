"""Durable delivery bookkeeping for BYQ WorkflowTrace, never a model/job queue."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import call_evidence_receipt, validate_call_evidence


MAX_ATTEMPTS = 8
DEADLINE_SECONDS = 24 * 3600
BACKOFF_SECONDS = (2, 5, 15, 60, 300, 900, 3600, 3600)


class LifecycleDelivery:
    def __init__(self, root, traces, send, *, clock=time.time, recover=None, answers=False, private_source=None):
        if private_source is not None and (answers or recover is not None):
            raise ValueError("private evidence cannot use public projection recovery")
        self.root = Path(root)
        self.traces, self.send, self.clock = traces, send, clock
        self.stop = threading.Event()
        self.thread = None
        self.recover = recover
        self.answers = answers
        self.private_source = private_source
        self.suffix = "domain-calls" if private_source is not None else "answers" if answers else "lifecycle"

    def _project(self, source, context):
        if self.private_source is not None:
            return validate_call_evidence(source)
        if not self.answers:
            return project_lifecycle_event(source, context["session_id"], context["trace_id"])
        if (source.get("session_id"), source.get("trace_id"), source.get("kind"), source.get("source")) != (
                context["session_id"], context["trace_id"], "agent.output.delta", "runtime-adapter"):
            return None
        payload = source.get("payload", {})
        if (payload.get("schema_version") != "workflow-answer.v1" or payload.get("channel") != "answer"
                or not isinstance(payload.get("delta"), str) or not payload["delta"].strip()):
            raise ValueError("invalid public answer projection")
        return {"schema_version": "public-answer-delivery.v1", "sequence": source["sequence"],
                "content": payload["delta"].strip()}

    def receipt(self, event):
        if self.private_source is not None:
            return call_evidence_receipt(event)
        if not self.answers:
            return lifecycle_receipt(event)
        return {"schema_version": "public-answer-receipt.v1", "workflow_sequence": event["sequence"],
                "content_sha256": hashlib.sha256(event["content"].encode()).hexdigest()}

    def deliver_session(self, session):
        self.register(session)
        self.drain(self.root / f"{session.session_id}.{self.suffix}.json")

    def register(self, session):
        # Reuse the trace filename validator; no paths come from event payloads.
        self.traces._path(session.session_id)
        context = {"session_id": session.session_id, "trace_id": session.trace_id,
                   "conversation_id": session.conversation_id, "workspace_id": session.workspace_id,
                   "owner": session.principal.subject}
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{session.session_id}.{self.suffix}.json"
        with path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                if json.loads(path.read_text())["context"] != context:
                    raise ValueError("lifecycle delivery context cannot change")
                state = json.loads(path.read_text())
                if state.get("recovery_done"):
                    state["recovery_done"] = False
                    self._save(path, state)
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
            if self.private_source is None and not self.answers and not state.get("durable_terminal_ack_migrated"):
                # v1 Adapter acknowledgements were memory-only (and a 404 was
                # accepted). Reconcile already-delivered exact terminal events
                # once through the same finite outbox. Never replay prompts,
                # registrations, domain actions, or reset a pending retry budget.
                target = state.setdefault("terminal_ack_migration_target", state["cursor"])
                cursor = state.get("terminal_ack_migration_cursor", 0)
                sources = [source for source in self.traces.read(ctx["session_id"], after_sequence=cursor)
                           if source["sequence"] <= target][:256]
                for source in sources:
                    event = self._project(source, ctx)
                    if (event and event["outcome"] != "active"
                            and state.get("terminal_events", {}).get(event["root_run_id"]) == event["sequence"]
                            and str(event["sequence"]) not in state["pending"]):
                        state["pending"][str(event["sequence"])] = {
                            "event": event, "status": "pending", "attempts": 0,
                            "created_at": self.clock(), "next_at": self.clock()}
                    state["terminal_ack_migration_cursor"] = source["sequence"]
                if target == 0 or state.get("terminal_ack_migration_cursor", 0) >= target:
                    state["durable_terminal_ack_migrated"] = True
                state["terminal_ack_migration_unavailable"] = not sources and not state.get("durable_terminal_ack_migrated", False)
                self._save(path, state)
            if (self.recover is not None and not state.get("recovery_done") and not state.get("recovery_exhausted")
                    and self.clock() >= state.get("next_recovery_at", 0)):
                # Passive evidence recovery, never a prompt/job retry. Throttle
                # before HTTP, including across Gateway restarts.
                failures = state.get("recovery_failures", 0)
                if failures >= MAX_ATTEMPTS or self.clock() >= state.get("recovery_failure_since", self.clock()) + DEADLINE_SECONDS:
                    state["recovery_exhausted"] = True
                    state["recovery_unavailable"] = True
                else:
                    failures += 1
                    state["recovery_failures"] = failures
                    state.setdefault("recovery_failure_since", self.clock())
                    state["next_recovery_at"] = self.clock() + max(30, BACKOFF_SECONDS[failures - 1])
                    self._save(path, state)
                    try:
                        state["recovery_done"] = self.recover(ctx)
                        state["recovery_unavailable"] = False
                        state["next_recovery_at"] = self.clock() + 30
                        state.pop("recovery_failures", None)
                        state.pop("recovery_failure_since", None)
                    except Exception:
                        state["recovery_unavailable"] = True
                        if failures >= MAX_ATTEMPTS:
                            state["recovery_exhausted"] = True
                self._save(path, state)
            # Recovers the crash gap between trace fsync and delivery bookkeeping.
            if self.private_source is not None:
                # Private observations never enter TraceStore, SSE, answers or
                # model context. Reuse the durable finite delivery engine only.
                sources = self._private_page(path, state)
                modified = None
            else:
                trace_path = self.traces._path(ctx["session_id"])
                modified = trace_path.stat().st_mtime_ns if trace_path.exists() else 0
                sources = (self.traces.read(ctx["session_id"], after_sequence=state["cursor"])
                           if modified != state.get("trace_mtime_ns") else [])
            for source in sources[:256]:
                try:
                    event = self._project(source, ctx)
                except ValueError:
                    # Preserve a visible local rejection, not a fabricated ack.
                    state["pending"][str(source["sequence"])] = {"status": "invalid_event"}
                    event = None
                if event and self.private_source is None and not self.answers and event["outcome"] != "active":
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
            if sources or modified != state.get("trace_mtime_ns"):
                state["trace_mtime_ns"] = modified if len(sources) <= 256 else None
                self._save(path, state)
            budget = 16
            for key, item in sorted(state["pending"].items(), key=lambda pair: int(pair[0])):
                if self.stop.is_set() or budget == 0:
                    break
                if item["status"] != "pending":
                    if self.answers:
                        break  # Never overtake a rejected/exhausted earlier answer.
                    continue
                now = self.clock()
                if item["attempts"] >= MAX_ATTEMPTS or now >= item["created_at"] + DEADLINE_SECONDS:
                    item["status"] = "exhausted"
                    self._save(path, state)
                    if self.answers:
                        break
                    continue
                if now < item["next_at"]:
                    if self.answers:
                        break
                    continue
                budget -= 1
                item["attempts"] += 1
                item["next_at"] = now + BACKOFF_SECONDS[item["attempts"] - 1]
                self._save(path, state)
                try:
                    reply = self.send(ctx, item["event"])
                    if reply != {"receipt": self.receipt(item["event"])}:
                        raise ValueError("lifecycle receipt mismatch")
                except Exception:
                    # All failures consume the same durable, finite budget.
                    # No raw error/credential is persisted; never dispatch DSH.
                    if self.answers:
                        break
                    continue
                state["last_receipt"] = reply["receipt"]
                del state["pending"][key]
                self._save(path, state)

    def _private_page(self, path, state):
        now = self.clock()
        trace_path = self.traces._path(state["context"]["session_id"])
        modified = trace_path.stat().st_mtime_ns if trace_path.exists() else 0
        if (state.get("source_idle") and state.get("source_idle_trace_mtime") == modified
                and state["cursor"] >= state.get("source_idle_target", 2**63)):
            return []  # No perpetual HTTP/fsync polling of historical idle conversations.
        if state.get("source_exhausted") or now < state.get("source_next_at", 0):
            return []
        failures = state.get("source_failures", 0)
        if failures >= MAX_ATTEMPTS or now >= state.get("source_failure_since", now) + DEADLINE_SECONDS:
            state["source_exhausted"] = True
            state["source_unavailable"] = True
            self._save(path, state)
            return []
        state["source_failures"] = failures + 1
        state.setdefault("source_failure_since", now)
        state["source_next_at"] = now + BACKOFF_SECONDS[failures]
        self._save(path, state)  # charge before the read, including a crash
        try:
            reply = self.private_source(state["context"], state["cursor"])
            if (not isinstance(reply, dict) or set(reply) != {"schema_version", "events", "more", "idle"}
                    or reply["schema_version"] != "domain-call-page.v1"
                    or not isinstance(reply["events"], list) or len(reply["events"]) > 256
                    or type(reply["idle"]) is not bool or type(reply["more"]) is not bool or reply["more"] and not reply["events"]):
                raise ValueError("invalid private evidence page")
            previous = state["cursor"]
            for source in reply["events"]:
                validate_call_evidence(source)
                if source["sequence"] != previous + 1 or source["sequence"] > 1024:
                    raise ValueError("private evidence sequence gap or retention overflow")
                previous = source["sequence"]
        except Exception:
            state["source_unavailable"] = True
            if failures + 1 >= MAX_ATTEMPTS:
                state["source_exhausted"] = True
            self._save(path, state)
            return []
        state.pop("source_failures", None)
        state.pop("source_failure_since", None)
        state["source_unavailable"] = False
        state["source_idle"] = reply["idle"] and not reply["more"]
        state["source_idle_trace_mtime"] = modified
        state["source_idle_target"] = previous
        state["source_next_at"] = now + (1 if reply["more"] else 2)
        # Cursor and pending events are committed together by drain. A crash
        # here only re-reads the exact page; it cannot lose an observation.
        self._save(path, state)
        return reply["events"]

    def run_once(self):
        for path in sorted(self.root.glob(f"*.{self.suffix}.json")):
            if self.stop.is_set():
                break
            try:
                self.drain(path)
            except (OSError, ValueError, KeyError, TypeError):
                # A damaged session ledger cannot block other sessions.
                continue

    def status(self, context):
        self.traces._path(context["session_id"])
        path = self.root / f"{context['session_id']}.{self.suffix}.json"
        result = {"schema_version": "domain-call-delivery-status.v1" if self.private_source is not None else "public-answer-delivery-status.v1" if self.answers else "agent-run-delivery-status.v1", "state": "not_registered",
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
            changed = self.private_source is None and trace_path.exists() and trace_path.stat().st_mtime_ns != state.get("trace_mtime_ns")
            result["state"] = ("attention_required" if result["exhausted_events"] or result["rejected_events"] else
                               "pending" if result["pending_events"] or changed else "up_to_date")
            if self.private_source is None and not self.answers and not state.get("durable_terminal_ack_migrated") and result["state"] == "up_to_date":
                result["state"] = "pending"
            if state.get("recovery_unavailable") or state.get("terminal_ack_migration_unavailable") or state.get("source_unavailable"):
                result["state"] = "unavailable"
        except (OSError, ValueError, KeyError, TypeError):
            result["state"] = "unavailable"
        return result

    def start(self):
        self.stop.clear()
        def work():
            while not self.stop.is_set():
                self.run_once()
                self.stop.wait(1.0)
        self.thread = threading.Thread(target=work, name=f"byq-{self.suffix}-delivery", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)
