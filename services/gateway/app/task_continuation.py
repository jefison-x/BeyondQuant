"""Consume BYQ task intents using existing registered conversation identities."""
from __future__ import annotations

import json
import fcntl
import os
import threading
import time
import math
import tempfile
from pathlib import Path


CONTEXT_SCHEMA = 'task-continuation-context.v1'
MAX_CONTEXT_BYTES = 4096
_CONTEXT_FIELDS = {'session_id', 'trace_id', 'conversation_id', 'workspace_id', 'owner'}


class TaskContinuationDelivery:
    def __init__(self, root: Path, consume, *, reconcile=None, now=time.time):
        self.root, self.consume = Path(root), consume
        self.reconcile = reconcile
        self.now = now
        self.stop = threading.Event()
        self.thread = None
        self.cursor = ''

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

    def tick(self):
        enabled = os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1'
        if not enabled and self.reconcile is None:
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
            try:
                context = self._read_context(path)
                if self.reconcile is not None:
                    self._reconcile_with_backoff(path, context)
                if enabled:
                    self.consume(context)
            except Exception:
                # The Backend owns every intent/uncertain liability. A transport
                # failure never fabricates a receipt or retries a model write.
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
        if self.thread is not None or (os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1' and self.reconcile is None):
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
