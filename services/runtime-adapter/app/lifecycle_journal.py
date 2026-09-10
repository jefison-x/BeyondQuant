"""ADR-0064: BYQ evidence only; never DSH state, prompts or a model queue."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from .contracts import make_workflow_trace_event, validate_workflow_trace_event
from .identifiers import validate_identifier
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import validate_call_evidence


MAX_BYTES = 8 * 1024 * 1024
MAX_PRIVATE_CALLS = 1024


class JournalBusy(RuntimeError):
    pass


class LifecycleJournal:
    @staticmethod
    def _context(context):
        if not isinstance(context, dict) or set(context) != {"session_id", "trace_id", "owner", "workspace_id"}:
            raise ValueError("invalid journal context")
        for name in ("session_id", "trace_id"):
            validate_identifier(context[name], field=name)
        for name in ("owner", "workspace_id"):
            value = context[name]
            if not isinstance(value, str) or not value or value != value.strip() or len(value) > 128:
                raise ValueError("invalid journal owner")

    @classmethod
    def claim(cls, root, context, *, create=False):
        cls._context(context)
        root = Path(root)
        if root.is_symlink():
            raise ValueError("journal directory cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        mounts = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            before, after = line.split(" - ", 1)
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), before.split()[4])
            resolved = str(root.resolve())
            if resolved == mount or resolved.startswith(mount.rstrip("/") + "/"):
                mounts.append((len(mount), after.split()[0]))
        if not mounts or max(mounts)[1] not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "overlay", "tmpfs"}:
            raise ValueError("recovery requires a local coherent filesystem")
        obj = cls()
        obj.path = root / (context["session_id"] + ".json")
        if obj.path.is_symlink():
            raise ValueError("journal cannot be a symlink")
        obj.lock = os.open(root / (context["session_id"] + ".lock"),
                           os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(obj.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise JournalBusy("the original evidence owner is still present") from exc
            token = os.read(obj.lock, 128).decode("ascii")
            if not obj.path.exists() and create and not token:
                token = uuid.uuid4().hex
                os.write(obj.lock, token.encode())
                os.fsync(obj.lock)
            if re.fullmatch("[0-9a-f]{32}", token) is None and obj.path.exists():
                raise ValueError("original owner lock identity is missing")
            stat = os.fstat(obj.lock)
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            obj.lease_identity = hashlib.sha256(f"{boot}:{stat.st_dev}:{stat.st_ino}:{token}".encode()).hexdigest()
            if obj.path.exists():
                obj.state = cls.read(obj.path)
                if obj.state["context"] != context or obj.state["lease_identity"] != obj.lease_identity:
                    raise ValueError("journal identity mismatch")
                if obj.state["open_root"] is not None:
                    # Acquiring the SAME never-unlinked kernel lock is required;
                    # neither a 404 nor a PID/time comparison authorizes this.
                    obj.observe(make_workflow_trace_event(session_id=context["session_id"],
                        trace_id=context["trace_id"], sequence=obj.state["sequence"] + 1,
                        kind="session.closed", source="runtime-adapter", payload={
                            "run_id": obj.state["open_root"]["root_run_id"], "reason": "executor-owner-lost"}),
                        generation=obj.state["open_root"]["generation"])
            elif create:
                obj.state = {"context": dict(context), "sequence": 0, "open_root": None,
                             "events": [], "prompts": {}, "terminal_acks": {}, "calls": [], "lease_identity": obj.lease_identity}
                obj._save(obj.state)
            else:
                raise FileNotFoundError("no durable runtime evidence")
            return obj
        except BaseException:
            obj.close()
            raise

    @staticmethod
    def read(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("journal exceeds recovery bound")
        envelope = json.loads(data)
        if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "state", "sha256"}
                or envelope["schema_version"] not in {"byq-lifecycle-journal.v1", "byq-lifecycle-journal.v2", "byq-lifecycle-journal.v3"}):
            raise ValueError("invalid journal envelope")
        state = envelope["state"]
        digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if envelope["sha256"] != digest:
            raise ValueError("journal integrity mismatch")
        # Verify historical bytes before the explicit, fail-closed migration.
        # A v1 journal proves no terminal acknowledgements, never implicit ACK.
        if envelope["schema_version"] == "byq-lifecycle-journal.v1":
            if not isinstance(state, dict) or "terminal_acks" in state:
                raise ValueError("invalid historical journal state")
            state["terminal_acks"] = {}
        if envelope["schema_version"] != "byq-lifecycle-journal.v3":
            if not isinstance(state, dict) or "calls" in state:
                raise ValueError("invalid historical private evidence state")
            state["calls"] = []
        return LifecycleJournal.validate(state)

    @staticmethod
    def validate(state):
        if not isinstance(state, dict) or set(state) != {"context", "sequence", "open_root", "events", "prompts", "terminal_acks", "calls", "lease_identity"}:
            raise ValueError("invalid journal state")
        if not isinstance(state["lease_identity"], str) or re.fullmatch("[0-9a-f]{64}", state["lease_identity"]) is None:
            raise ValueError("invalid owner lock identity")
        if (not isinstance(state["events"], list) or not isinstance(state["prompts"], dict)
                or not isinstance(state["terminal_acks"], dict)):
            raise ValueError("invalid journal collections")
        LifecycleJournal._context(state["context"])
        if type(state["sequence"]) is not int or not 0 <= state["sequence"] < 2**63 - 1:
            raise ValueError("invalid journal sequence")
        opened = None
        previous = 0
        roots = set()
        terminal_receipts = {}
        for event in state["events"]:
            validate_workflow_trace_event(event)
            if not previous < event["sequence"] <= state["sequence"]:
                raise ValueError("journal ordering mismatch")
            previous = event["sequence"]
            if (event["session_id"], event["trace_id"], event["source"]) != (
                    state["context"]["session_id"], state["context"]["trace_id"], "runtime-adapter"):
                raise ValueError("journal event identity mismatch")
            root = event["payload"].get("run_id")
            if not isinstance(root, str) or re.fullmatch("[0-9a-f]{32}", root) is None:
                raise ValueError("invalid journal root")
            if event["kind"] == "session.started":
                if set(event["payload"]) != {"run_id"}:
                    raise ValueError("root start contains non-evidence data")
                if opened is not None or root in roots:
                    raise ValueError("overlapping journal roots")
                opened = root
                roots.add(root)
            else:
                projected = project_lifecycle_event(event, event["session_id"], event["trace_id"])
                if projected is None or root not in roots:
                    raise ValueError("unowned journal lifecycle")
                if projected["outcome"] != "active":
                    if set(event["payload"]) != {"run_id"}:
                        raise ValueError("terminal contains non-evidence data")
                    if opened != root:
                        raise ValueError("contradictory journal terminal")
                    opened = None
                    terminal_receipts[root] = lifecycle_receipt(projected)
        current = state["open_root"]
        if opened is None:
            if current is not None:
                raise ValueError("unproven open root")
        elif (not isinstance(current, dict) or set(current) != {"root_run_id", "generation"}
              or current["root_run_id"] != opened or not isinstance(current["generation"], str)
              or not 1 <= len(current["generation"]) <= 128):
            raise ValueError("invalid root generation")
        for key, receipt in state["prompts"].items():
            if (not isinstance(key, str) or not 8 <= len(key) <= 128 or not isinstance(receipt, dict)
                    or set(receipt) != {"root_run_id", "content_sha256"}
                    or not isinstance(receipt["root_run_id"], str) or receipt["root_run_id"] not in roots
                    or not isinstance(receipt["content_sha256"], str)
                    or re.fullmatch("[0-9a-f]{64}", receipt["content_sha256"]) is None):
                raise ValueError("invalid durable prompt receipt")
        for root, receipt in state["terminal_acks"].items():
            if (not isinstance(receipt, dict) or type(receipt.get("sequence")) is not int
                    or root not in terminal_receipts or receipt != terminal_receipts[root]):
                raise ValueError("invalid durable terminal acknowledgement")
        if not isinstance(state["calls"], list) or len(state["calls"]) > MAX_PRIVATE_CALLS:
            raise ValueError("private call evidence exceeds retention bound")
        for index, evidence in enumerate(state["calls"], 1):
            validate_call_evidence(evidence)
            if evidence["sequence"] != index or evidence["root_run_id"] not in roots:
                raise ValueError("private call evidence has no matching journal root")
        return state

    def _save(self, state):
        self.validate(state)
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        data = json.dumps({"schema_version": "byq-lifecycle-journal.v3", "state": state,
                          "sha256": hashlib.sha256(encoded).hexdigest()},
                          sort_keys=True, separators=(",", ":")).encode()
        if len(data) > MAX_BYTES:
            raise ValueError("journal capacity reached; evidence must be retained")
        fd, name = tempfile.mkstemp(prefix=".evidence-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def observe(self, event, *, generation, prompt=None):
        # Runtime emits only a closed reference for these cards. Gateway
        # hydrates them through an owner-scoped Domain read before public
        # persistence. They are sequence observations, never recovery evidence.
        reference = {
            'agent.card.backtest_context': ('job_id', r'backtest_[0-9a-f]{32}'),
            'agent.card.approval': ('approval_id', r'agent_approval_[0-9a-f]{32}'),
        }.get(event.get('kind'))
        if reference and event.get('source') == 'runtime-adapter':
            key, pattern = reference
            payload = event.get('payload')
            if (not isinstance(payload, dict) or set(payload) != {key}
                    or not isinstance(payload[key], str) or re.fullmatch(pattern, payload[key]) is None):
                raise ValueError('invalid internal card reference')
            validate_workflow_trace_event({**event, 'kind': 'session.ready', 'payload': {}})
        else:
            validate_workflow_trace_event(event)
        if (event["session_id"], event["trace_id"]) != (self.state["context"]["session_id"], self.state["context"]["trace_id"]):
            raise ValueError("event belongs to a different journal")
        state = copy.deepcopy(self.state)
        if event["sequence"] <= state["sequence"]:
            raise ValueError("journal sequence must advance")
        state["sequence"] = event["sequence"]
        if event["kind"] == "session.started":
            if state["open_root"] is not None:
                raise ValueError("previous root has no terminal")
            root = event["payload"]["run_id"]
            state["open_root"] = {"root_run_id": root, "generation": generation}
            state["events"].append(event)
            if prompt is not None:
                key, digest = prompt
                if key in state["prompts"]:
                    raise ValueError("prompt receipt cannot be replaced")
                state["prompts"][key] = {"root_run_id": root, "content_sha256": digest}
        else:
            projected = project_lifecycle_event(event, state["context"]["session_id"], state["context"]["trace_id"])
            if projected:
                if projected["outcome"] == "active":
                    state["events"].append(event)
                elif state["open_root"] and state["open_root"]["root_run_id"] == projected["root_run_id"]:
                    state["open_root"] = None
                    state["events"].append({**event, "payload": {"run_id": projected["root_run_id"]}})
        self._save(state)
        self.state = state

    def observe_call(self, evidence):
        validate_call_evidence(evidence)
        opened = self.state["open_root"]
        if (opened is None or evidence["root_run_id"] != opened["root_run_id"]
                or evidence["generation"] != opened["generation"]
                or evidence["sequence"] != len(self.state["calls"]) + 1):
            raise ValueError("private call evidence does not belong to the open root")
        state = copy.deepcopy(self.state)
        state["calls"].append(dict(evidence))
        self._save(state)
        self.state = state

    def acknowledge_terminal(self, receipt):
        root = receipt.get("root_run_id") if isinstance(receipt, dict) else None
        if not isinstance(root, str):
            raise ValueError("invalid terminal acknowledgement root")
        state = copy.deepcopy(self.state)
        state["terminal_acks"][root] = receipt
        # Validation binds the closed receipt to the exact persisted terminal.
        self._save(state)
        self.state = state

    def receipt(self, key, content_sha256):
        return self.lookup(self.state, key, content_sha256)

    @staticmethod
    def lookup(state, key, content_sha256):
        receipt = state["prompts"].get(key)
        if receipt is None:
            return {"schema_version": "prompt-receipt.v1", "state": "outcome_unknown"}
        if receipt["content_sha256"] != content_sha256:
            raise ValueError("prompt receipt content conflicts")
        return {"schema_version": "prompt-receipt.v1", "state": "accepted", "run_id": receipt["root_run_id"]}

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
