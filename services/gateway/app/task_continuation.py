"""Consume BYQ task intents using existing registered conversation identities."""
from __future__ import annotations

import json
import logging
import fcntl
import os
import threading
import time
import math
import tempfile
from pathlib import Path


CONTEXT_SCHEMA = 'task-continuation-context.v1'
CANCEL_SCHEMA = 'task-continuation-cancel.v2'
MAX_CONTEXT_BYTES = 4096
_CONTEXT_FIELDS = {'session_id', 'trace_id', 'conversation_id', 'workspace_id', 'owner'}
logger = logging.getLogger('uvicorn.error')


class CancelModeConflict(ValueError):
    """An fsynced cancellation intent cannot be silently changed."""


class TaskContinuationDelivery:
    def __init__(self, root: Path, consume, *, consume_default=None, reconcile=None,
                 cancel_pending=None, now=time.time):
        self.root, self.consume = Path(root), consume
        # The ordinary task-ready SignalJob path is independent of the legacy
        # F6 opt-in. It shares this registered-context poller but has a
        # separate callback so a default tick can never enter the legacy
        # permission/receipt consumer by accident.
        self.consume_default = consume_default
        self.reconcile = reconcile
        self.cancel_pending = cancel_pending
        self.now = now
        self.stop = threading.Event()
        self.thread = None
        self.cursor = ''
        self._reported_failures: set[tuple[str, str, str]] = set()

    @staticmethod
    def _validate_context(context):
        if not isinstance(context, dict) or set(context) != _CONTEXT_FIELDS:
            raise ValueError('invalid task continuation context')
        for key, value in context.items():
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError('invalid task continuation context')
            if key == 'session_id':
                allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
                if any(character not in allowed for character in value):
                    raise ValueError('invalid task continuation session identity')
        return dict(context)

    def register(self, session):
        context = self._validate_context({
            'session_id': session.session_id, 'trace_id': session.trace_id,
            'conversation_id': session.conversation_id, 'workspace_id': session.workspace_id,
            'owner': session.principal.subject,
        })
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{context['session_id']}.continuation.json"
        lock_path = self.root / f"{context['session_id']}.continuation.lock"
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                registered = self._read_context(path)
                if registered != context:
                    raise ValueError('task continuation context cannot change')
                return
            self._save_context(path, context)

    def _read_context(self, path):
        if path.stat().st_size > MAX_CONTEXT_BYTES:
            raise ValueError('task continuation context exceeds its size limit')
        value = json.loads(path.read_text())
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'context'}
                or value.get('schema_version') != CONTEXT_SCHEMA):
            raise ValueError('invalid task continuation context record')
        context = self._validate_context(value['context'])
        if path.name != f"{context['session_id']}.continuation.json":
            raise ValueError('task continuation context filename mismatch')
        return context

    def _save_context(self, path, context):
        fd, name = tempfile.mkstemp(prefix='.continuation-', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'schema_version': CONTEXT_SCHEMA, 'context': context}, stream,
                          sort_keys=True, separators=(',', ':'))
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

    def _cancel_path(self, context):
        return self.root / f"{context['session_id']}.continuation-cancel.json"

    def request_cancel(self, context, reservation_id, mode):
        """Fsync one exact stop intent before crossing the Backend boundary."""
        context = self._validate_context(context)
        if (not isinstance(reservation_id, str)
                or len(reservation_id) != 45
                or not reservation_id.startswith('continuation_')
                or any(character not in '0123456789abcdef' for character in reservation_id[13:])):
            raise ValueError('invalid continuation cancel reservation identity')
        if not isinstance(mode, str) or mode not in {'soft', 'hard'}:
            raise ValueError('invalid continuation cancel mode')
        context_path = self.root / f"{context['session_id']}.continuation.json"
        path = self._cancel_path(context)
        lock_path = self.root / f"{context['session_id']}.continuation.lock"
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not context_path.exists() or self._read_context(context_path) != context:
                raise ValueError('continuation cancel context is not registered')
            if path.exists():
                current_reservation_id, current_mode = self._read_cancel(path, context)
                if current_reservation_id != reservation_id:
                    raise ValueError('another exact continuation cancel is pending')
                if current_mode != mode:
                    raise CancelModeConflict('pending continuation cancel mode cannot change')
                return True
            value = {'schema_version': CANCEL_SCHEMA, 'context': context,
                     'reservation_id': reservation_id, 'mode': mode}
            fd, name = tempfile.mkstemp(prefix='.continuation-cancel-', dir=self.root)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(value, stream, sort_keys=True, separators=(',', ':'))
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
        return True

    def _read_cancel(self, path, expected_context):
        if path.stat().st_size > MAX_CONTEXT_BYTES:
            raise ValueError('continuation cancel marker exceeds its size limit')
        value = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(value, dict)
                or set(value) != {'schema_version', 'context', 'reservation_id', 'mode'}
                or value.get('schema_version') != CANCEL_SCHEMA):
            raise ValueError('invalid continuation cancel marker')
        context = self._validate_context(value.get('context'))
        if context != expected_context or path.name != f"{context['session_id']}.continuation-cancel.json":
            raise ValueError('continuation cancel marker context mismatch')
        reservation_id = value.get('reservation_id')
        if (not isinstance(reservation_id, str) or len(reservation_id) != 45
                or not reservation_id.startswith('continuation_')
                or any(character not in '0123456789abcdef' for character in reservation_id[13:])):
            raise ValueError('invalid continuation cancel marker identity')
        mode = value.get('mode')
        if not isinstance(mode, str) or mode not in {'soft', 'hard'}:
            raise ValueError('invalid continuation cancel marker mode')
        return reservation_id, mode

    def pending_cancel(self, context):
        context = self._validate_context(context)
        path = self._cancel_path(context)
        if not path.exists():
            return None
        lock_path = self.root / f"{context['session_id']}.continuation.lock"
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                return None
            return self._read_cancel(path, context)

    def clear_cancel(self, context, reservation_id, mode):
        context = self._validate_context(context)
        path = self._cancel_path(context)
        lock_path = self.root / f"{context['session_id']}.continuation.lock"
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists() or self._read_cancel(path, context) != (reservation_id, mode):
                return False
            path.unlink()
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return True

    def tick(self):
        enabled = os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1'
        if (not enabled and self.reconcile is None and self.consume_default is None
                and self.cancel_pending is None):
            return
        paths = sorted(self.root.glob('*.continuation.json'))
        candidates = [p for p in paths if p.name > self.cursor]
        if not candidates:
            self.cursor = ''
            candidates = paths
        for path in candidates[:8]:
            if self.stop.is_set():
                break
            self.cursor = path.name
            stage = 'context'
            try:
                context = self._read_context(path)
                pending_cancel = self.pending_cancel(context)
                if pending_cancel is not None:
                    stage = 'cancel_fence'
                    reservation_id, mode = pending_cancel
                    if (self.cancel_pending is None
                            or self.cancel_pending(context, reservation_id, mode) is not True):
                        continue
                    if not self.clear_cancel(context, reservation_id, mode):
                        continue
                if self.reconcile is not None:
                    stage = 'reconcile'
                    self._reconcile_with_backoff(path, context)
                if enabled:
                    stage = 'consume'
                    self.consume(context)
                elif self.consume_default is not None:
                    stage = 'consume_default'
                    self.consume_default(context)
            except Exception as exc:
                # The Backend owns every intent/uncertain liability. A transport
                # failure never fabricates a receipt or retries a model write.
                status = getattr(exc, 'status_code', None)
                category = (stage, type(exc).__name__, str(status) if type(status) is int else 'unknown')
                if category not in self._reported_failures:
                    logger.warning('task continuation delivery paused: stage=%s error=%s status=%s', *category)
                    self._reported_failures.add(category)
                continue

    def _reconcile_with_backoff(self, path, context):
        # A failed check is never evidence that the underlying write is absent.
        # Keep the lifecycle liability and retry, independently of F6 dispatch.
        state_path = path.with_suffix('.receipt-backoff.json')
        now, attempts = self.now(), 0
        try:
            if state_path.stat().st_size <= 4096:
                state = json.loads(state_path.read_text())
                if isinstance(state, dict) and state.get('context') == context:
                    attempts = max(0, min(7, int(state['attempts'])))
                    retry_at = float(state['retry_at'])
                    if math.isfinite(retry_at) and now < retry_at <= now + 300:
                        return
        except (OSError, ValueError, TypeError, KeyError):
            pass
        try:
            self.reconcile(context)
        except Exception:
            attempts = min(7, attempts + 1)
            state = dict(context=context, attempts=attempts,
                         retry_at=now + min(300, 30 * 2 ** (attempts - 1)))
            temporary = state_path.with_suffix('.tmp')
            try:
                temporary.write_text(json.dumps(state))
                os.replace(temporary, state_path)
            except OSError:
                pass
        else:
            try:
                state_path.unlink(missing_ok=True)
            except OSError:
                pass

    def start(self):
        if (self.thread is not None
                or (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1'
                    and self.reconcile is None and self.consume_default is None
                    and self.cancel_pending is None)):
            return
        self.stop.clear()
        def run():
            while not self.stop.is_set():
                self.tick()
                self.stop.wait(5)
        self.thread = threading.Thread(target=run, name='byq-task-continuation', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=45)
            if self.thread.is_alive():
                raise RuntimeError('task continuation consumer has not stopped')
            self.thread = None
