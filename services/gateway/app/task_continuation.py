"""Consume BYQ task intents using existing registered conversation identities."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


class TaskContinuationDelivery:
    def __init__(self, root: Path, consume):
        self.root, self.consume = Path(root), consume
        self.stop = threading.Event()
        self.thread = None
        self.cursor = ''

    def tick(self):
        if os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
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
                self.consume(context)
            except Exception:
                # The Backend owns every intent/uncertain liability. A transport
                # failure never fabricates a receipt or retries a model write.
                continue

    def start(self):
        if self.thread is not None or os.environ.get('BYQ_F6_EXECUTOR_ENABLED') != '1':
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
