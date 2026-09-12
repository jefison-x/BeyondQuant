"""Consume BYQ task intents using existing registered conversation identities."""
from __future__ import annotations

import json
import os
import threading
import time
import math
from pathlib import Path


class TaskContinuationDelivery:
    def __init__(self, root: Path, consume, *, reconcile=None, now=time.time):
        self.root, self.consume = Path(root), consume
        self.reconcile = reconcile
        self.now = now
        self.stop = threading.Event()
        self.thread = None
        self.cursor = ''

    def tick(self):
        enabled = os.environ.get('BYQ_F6_EXECUTOR_ENABLED') == '1'
        if not enabled and self.reconcile is None:
            return
        paths = sorted(self.root.glob('*.lifecycle.json'))
        candidates = [p for p in paths if p.name > self.cursor]
        if not candidates:
            self.cursor = ''
            candidates = paths
        for path in candidates[:8]:
            if self.stop.is_set():
                break
            self.cursor = path.name
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
                context = json.loads(path.read_text())['context']
                if set(context) != {'session_id', 'trace_id', 'conversation_id', 'workspace_id', 'owner'}:
                    continue
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
