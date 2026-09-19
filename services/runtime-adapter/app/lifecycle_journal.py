"""ADR-0064: BYQ evidence only; never DSH state, prompts or a model queue."""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from . import executor_identity
from .contracts import make_workflow_trace_event, validate_workflow_trace_event
from .executor_identity import ExecutorIdentityError
from .identifiers import validate_identifier
from packages.contracts.agent_run_lifecycle import lifecycle_receipt, project_lifecycle_event
from packages.contracts.domain_call_admission import validate_call_evidence


MAX_BYTES = 8 * 1024 * 1024
MAX_PRIVATE_CALLS = 1024
JOURNAL_SCHEMA_VERSION = "byq-lifecycle-journal.v4"
JOURNAL_SCHEMA_VERSIONS = frozenset({
    "byq-lifecycle-journal.v1", "byq-lifecycle-journal.v2",
    "byq-lifecycle-journal.v3", "byq-lifecycle-journal.v4",
})
REANCHOR_AUDIT_DIR = "reanchor-audit"
REANCHOR_SCHEMA_VERSION = "byq-lifecycle-lease-reanchor.v1"
_LEASE_HEX = re.compile(r"[0-9a-f]{64}")
_TOKEN_HEX = re.compile(r"[0-9a-f]{32}")
_LOCAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "overlay", "tmpfs"}


class JournalBusy(RuntimeError):
    pass


class JournalIdentityMismatch(ValueError):
    """The stored lease belongs to a different stable executor identity.

    ADR-0079: identity/epoch mismatch (a different deployment, a fenced
    old-epoch writer, a copied lock object, a missing/corrupt epoch record) is
    an explicit, stable fail-closed condition. It must not be collapsed into
    "unknown session" or a generic server fault. A host reboot never changes
    the identity.
    """


class LeaseReanchorConflict(ValueError):
    """The stored lease identity is not the value the operator expected.

    ADR-0078 re-lease fails closed on this conflict; it never blind-overwrites a
    lease that changed between inventory and apply.
    """


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

    @staticmethod
    def _require_local_coherent_filesystem(root):
        mounts = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            before, after = line.split(" - ", 1)
            mount = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), before.split()[4])
            resolved = str(root.resolve())
            if resolved == mount or resolved.startswith(mount.rstrip("/") + "/"):
                mounts.append((len(mount), after.split()[0]))
        if not mounts or max(mounts)[1] not in _LOCAL_FILESYSTEMS:
            raise ValueError("recovery requires a local coherent filesystem")

    @staticmethod
    def _resolve_executor(root, executor=None):
        """Resolve the stable executor identity, mapping fail-closed errors."""

        if executor is not None:
            return executor
        try:
            return executor_identity.resolve(root)
        except ExecutorIdentityError as exc:
            raise JournalIdentityMismatch(str(exc)) from exc

    @staticmethod
    def _lease_identity(executor, st_dev, st_ino, token):
        return executor_identity.lease_identity(executor, st_dev, st_ino, token)

    @staticmethod
    def _adopt_executor(state, executor, lease_identity):
        """First controlled claim of a legacy boot-bound journal -> stable v4."""

        adopted = copy.deepcopy(state)
        adopted["executor_identity"] = executor.deployment_id
        adopted["executor_epoch"] = executor.executor_epoch
        adopted["lease_identity"] = lease_identity
        return adopted

    @classmethod
    def claim(cls, root, context, *, create=False, executor=None):
        cls._context(context)
        root = Path(root)
        if root.is_symlink():
            raise ValueError("journal directory cannot be a symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        cls._require_local_coherent_filesystem(root)
        obj = cls()
        obj.root = root
        obj.executor = cls._resolve_executor(root, executor)
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
            if _TOKEN_HEX.fullmatch(token) is None and obj.path.exists():
                raise ValueError("original owner lock identity is missing")
            stat = os.fstat(obj.lock)
            obj.lease_identity = cls._lease_identity(obj.executor, stat.st_dev, stat.st_ino, token)
            if obj.path.exists():
                envelope = cls._read_envelope(obj.path)
                state = cls._migrate(envelope)
                if state["context"] != context:
                    raise JournalIdentityMismatch("journal identity mismatch")
                if envelope["schema_version"] != JOURNAL_SCHEMA_VERSION:
                    # The first controlled claim of a legacy boot-bound journal
                    # adopts the stable executor identity exactly once, under
                    # the exclusive owner lock, preserving all evidence.
                    state = cls._adopt_executor(state, obj.executor, obj.lease_identity)
                    obj._save(state, fenced=False)
                elif (state.get("executor_identity") != obj.executor.deployment_id
                      or state.get("executor_epoch") != obj.executor.executor_epoch
                      or state["lease_identity"] != obj.lease_identity):
                    raise JournalIdentityMismatch("journal identity mismatch")
                obj.state = state
                if obj.state["open_root"] is not None:
                    # Acquiring the SAME never-unlinked kernel lock is required;
                    # neither a 404 nor a PID/time comparison authorizes this.
                    obj.observe(make_workflow_trace_event(session_id=context["session_id"],
                        trace_id=context["trace_id"], sequence=obj.state["sequence"] + 1,
                        kind="session.closed", source="runtime-adapter", payload={
                            "run_id": obj.state["open_root"]["root_run_id"], "reason": "executor-owner-lost"}),
                        generation=obj.state["open_root"]["generation"])
            elif create:
                obj.state = {
                    "context": dict(context), "sequence": 0, "open_root": None,
                    "events": [], "prompts": {}, "terminal_acks": {}, "calls": [],
                    "lease_identity": obj.lease_identity,
                    "executor_identity": obj.executor.deployment_id,
                    "executor_epoch": obj.executor.executor_epoch,
                }
                obj._save(obj.state)
            else:
                raise FileNotFoundError("no durable runtime evidence")
            return obj
        except BaseException:
            obj.close()
            raise

    @classmethod
    def reanchor_lease(cls, root, session_id, *, expected_stored_lease, executor=None):
        """Explicitly re-bind a durable journal to the stable executor (ADR-0079).

        This is the exceptional repair path, not the reboot path: normal restart
        and reboot preserve the stable lease. Under the journal's exclusive owner
        lock (and the exclusive epoch lock) ONLY the executor binding is
        rewritten: ``executor_identity``, ``executor_epoch`` and
        ``lease_identity``. ``sequence``, ``events``, ``prompts``,
        ``terminal_acks``, ``calls``, ``open_root`` and ``context`` are preserved
        exactly; no domain or database state is touched. A legacy v3 journal is
        migrated to v4 in the same step.

        Fails closed: a live owner (lock held), a concurrent takeover, an
        unknown/malformed journal, an invalid expected lease, or a stored lease
        that changed since inventory all abort without mutating. A stored lease
        already equal to the current one is an idempotent no-op. A per-session
        audit record (timestamp, old and new lease, prior and new journal
        sha256) is committed atomically beside the journal before returning.
        """

        validate_identifier(session_id, field="session_id")
        if not isinstance(expected_stored_lease, str) or _LEASE_HEX.fullmatch(expected_stored_lease) is None:
            raise ValueError("invalid expected lease identity")
        root = Path(root)
        if root.is_symlink():
            raise ValueError("journal directory cannot be a symlink")
        cls._require_local_coherent_filesystem(root)
        identity = cls._resolve_executor(root, executor)
        path = root / (session_id + ".json")
        lock_path = root / (session_id + ".lock")
        if path.is_symlink() or lock_path.is_symlink():
            raise ValueError("journal cannot be a symlink")
        obj = cls()
        obj.root = root
        obj.executor = identity
        obj.path = path
        obj.lock = None
        staged = None
        saved = False
        try:
            try:
                obj.lock = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
            except FileNotFoundError:
                raise FileNotFoundError("no durable runtime evidence") from None
            try:
                fcntl.flock(obj.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise JournalBusy("the original evidence owner is still present") from exc
            token = os.read(obj.lock, 128).decode("ascii")
            if _TOKEN_HEX.fullmatch(token) is None:
                raise ValueError("original owner lock identity is missing")
            if not path.exists():
                raise FileNotFoundError("no durable runtime evidence")
            stat = os.fstat(obj.lock)
            current = cls._lease_identity(identity, stat.st_dev, stat.st_ino, token)
            with executor_identity.epoch_lock(root, exclusive=True):
                envelope = cls._read_envelope(path)
                state = cls._migrate(envelope)
                stored = state["lease_identity"]
                base = {
                    "session_id": session_id,
                    "previous_lease_identity": stored,
                    "current_lease_identity": current,
                    "executor_identity": identity.deployment_id,
                    "executor_epoch": identity.executor_epoch,
                    "database_rows_modified": False,
                    "production_data_deleted": False,
                }
                if stored == current and state.get("executor_identity") == identity.deployment_id:
                    return {**base, "status": "current", "changed": False,
                            "previous_journal_sha256": None, "journal_sha256": None,
                            "audit_path": None}
                if stored != expected_stored_lease:
                    raise LeaseReanchorConflict(
                        "stored lease identity does not match the expected value")
                prior_sha256 = envelope["sha256"]
                new_state = cls._adopt_executor(state, identity, current)
                new_sha256 = hashlib.sha256(
                    json.dumps(new_state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                audit = {
                    "schema_version": REANCHOR_SCHEMA_VERSION,
                    "timestamp": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
                    "action": "reanchor_lease",
                    "session_id": session_id,
                    "previous_lease_identity": stored,
                    "lease_identity": current,
                    "executor_identity": identity.deployment_id,
                    "executor_epoch": identity.executor_epoch,
                    "previous_journal_sha256": prior_sha256,
                    "journal_sha256": new_sha256,
                    "preserved": ["context", "sequence", "open_root", "events", "prompts",
                                  "terminal_acks", "calls"],
                    "reversible": True,
                    "database_rows_modified": False,
                    "production_data_deleted": False,
                }
                staged, final = cls._stage_reanchor_audit(root, audit)
                obj._save(new_state, fenced=False)
                saved = True
                cls._commit_reanchor_audit(staged, final)
                staged = None
                return {**base, "status": "reanchored", "changed": True,
                        "previous_journal_sha256": prior_sha256, "journal_sha256": new_sha256,
                        "audit_path": str(final)}
        finally:
            if staged is not None and not saved:
                Path(staged).unlink(missing_ok=True)
            obj.close()

    @classmethod
    def takeover_executor_epoch(cls, root, *, reason, operator=None):
        """Explicit, audited executor takeover; increments the monotonic epoch."""

        return executor_identity.takeover(root, reason=reason, operator=operator)

    @staticmethod
    def _stage_reanchor_audit(root, audit):
        directory = root / REANCHOR_AUDIT_DIR
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        final = directory / f"{audit['session_id']}.{audit['timestamp']}.json"
        if final.exists():
            raise FileExistsError(f"reanchor audit already exists: {final}")
        fd, name = tempfile.mkstemp(prefix=".reanchor-", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(audit, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        return name, final

    @staticmethod
    def _commit_reanchor_audit(staged, final):
        os.replace(staged, final)
        directory = os.open(Path(final).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    @staticmethod
    def _read_envelope(path):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("journal exceeds recovery bound")
        envelope = json.loads(data)
        if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "state", "sha256"}
                or envelope["schema_version"] not in JOURNAL_SCHEMA_VERSIONS):
            raise ValueError("invalid journal envelope")
        state = envelope["state"]
        digest = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if envelope["sha256"] != digest:
            raise ValueError("journal integrity mismatch")
        return envelope

    @staticmethod
    def _migrate(envelope):
        state = envelope["state"]
        schema = envelope["schema_version"]
        # Verify historical bytes before the explicit, fail-closed migration.
        # A v1 journal proves no terminal acknowledgements, never implicit ACK.
        if schema == "byq-lifecycle-journal.v1":
            if not isinstance(state, dict) or "terminal_acks" in state:
                raise ValueError("invalid historical journal state")
            state["terminal_acks"] = {}
        if schema in {"byq-lifecycle-journal.v1", "byq-lifecycle-journal.v2"}:
            if not isinstance(state, dict) or "calls" in state:
                raise ValueError("invalid historical private evidence state")
            state["calls"] = []
        return LifecycleJournal.validate(state)

    @staticmethod
    def read(path):
        return LifecycleJournal._migrate(LifecycleJournal._read_envelope(path))

    @staticmethod
    def validate(state):
        base = {"context", "sequence", "open_root", "events", "prompts", "terminal_acks", "calls", "lease_identity"}
        stable = {"executor_identity", "executor_epoch"}
        if not isinstance(state, dict) or set(state) not in (base, base | stable):
            raise ValueError("invalid journal state")
        if not isinstance(state["lease_identity"], str) or re.fullmatch("[0-9a-f]{64}", state["lease_identity"]) is None:
            raise ValueError("invalid owner lock identity")
        if stable <= set(state):
            if (not isinstance(state["executor_identity"], str)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", state["executor_identity"]) is None):
                raise ValueError("invalid stable executor identity")
            if type(state["executor_epoch"]) is not int or not 1 <= state["executor_epoch"] < 2**63:
                raise ValueError("invalid stable executor epoch")
        elif stable & set(state):
            raise ValueError("incomplete stable executor identity")
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

    def _save(self, state, *, fenced=True):
        self.validate(state)
        if "executor_identity" not in state or "executor_epoch" not in state:
            raise ValueError("journal state lacks a stable executor identity")
        if fenced:
            try:
                executor_identity.assert_write_allowed(
                    self.root, state["executor_identity"], state["executor_epoch"])
            except ExecutorIdentityError as exc:
                raise JournalIdentityMismatch(str(exc)) from exc
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
        data = json.dumps({"schema_version": JOURNAL_SCHEMA_VERSION, "state": state,
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

    def rebase(self, sequence):
        """Reconcile the durable public sequence with the Gateway trace.

        A restart can leave the journal ahead of the Gateway trace: the Runtime
        kept emitting while no collector persisted the projection. Durable
        evidence the Gateway never persisted is re-anchored immediately after
        ``sequence`` so replay is gap-free; the old numbers are free because the
        Gateway never stored them. A terminal receipt the Gateway already
        persisted binds its exact sequence and can never be renumbered.
        """

        if type(sequence) is not int or sequence < 0:
            raise ValueError("invalid rebase sequence")
        state = copy.deepcopy(self.state)
        acknowledged = {
            receipt["sequence"] for receipt in state["terminal_acks"].values()
            if type(receipt.get("sequence")) is int
        }
        tail = [event for event in state["events"] if event["sequence"] > sequence]
        if any(event["sequence"] in acknowledged for event in tail):
            raise ValueError("cannot rebase below acknowledged journal evidence")
        cursor = sequence
        for event in state["events"]:
            if event["sequence"] > sequence:
                cursor += 1
                event["sequence"] = cursor
        state["sequence"] = max(sequence, cursor)
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
