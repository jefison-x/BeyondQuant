"""Whole-request deadline for the two synchronous Linux feedback workers.

Only their main-thread HTTP calls may use this helper. It neither retries nor
starts background network work, and refuses to replace another active timer.
"""
from contextlib import contextmanager
import math
import signal
import threading


@contextmanager
def request_deadline(seconds: float):
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('positive finite HTTP deadline required')
    if threading.current_thread() is not threading.main_thread():
        raise TimeoutError('feedback HTTP requires the worker main thread')
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise TimeoutError('another real-time deadline is active')
    previous = signal.getsignal(signal.SIGALRM)

    def expired(_signum, _frame):
        raise TimeoutError('feedback HTTP deadline exceeded')

    signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
