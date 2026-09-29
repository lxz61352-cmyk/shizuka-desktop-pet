# -*- coding: utf-8 -*-
"""Process-level request rate limiter for provider profiles (P4.1).

Shared by desktop and weixin in the same process. Uses a monotonic clock;
waiting is cancellable and a cancelled wait never sends a request. It never
retries 429s and never touches keys or request bodies.
"""
import threading
import time

_LOCK = threading.Lock()
_LAST_SENT = {}
_LAST_WAIT_SECONDS = 0.0


class ProviderWaitCancelled(Exception):
    """Waiting for a provider slot was cancelled before any request was sent."""

    def __init__(self):
        super(ProviderWaitCancelled, self).__init__(
            "request cancelled while waiting for provider slot")


def acquire(profile, cancel=None, *, clock=time.monotonic, sleep=time.sleep):
    """Block until the provider's minimum interval allows one request.

    Returns True when the caller may send. Raises ProviderWaitCancelled when
    `cancel()` becomes true while waiting. `clock`/`sleep` are injectable for
    fake-clock tests (production must never trigger real sleeps in tests).
    """
    global _LAST_WAIT_SECONDS
    if not profile:
        _LAST_WAIT_SECONDS = 0.0
        return True
    interval = float(profile.get("min_interval") or 0.0)
    if interval <= 0:
        _LAST_WAIT_SECONDS = 0.0
        return True
    key = profile.get("key") or profile.get("provider") or "unknown"
    started = clock()
    while True:
        if cancel is not None and cancel():
            _LAST_WAIT_SECONDS = clock() - started
            raise ProviderWaitCancelled()
        with _LOCK:
            now = clock()
            last = _LAST_SENT.get(key)
            if last is None or now - last >= interval:
                _LAST_SENT[key] = now
                _LAST_WAIT_SECONDS = clock() - started
                return True
            remaining = interval - (now - last)
        slice_ = min(remaining, 1.0)
        if slice_ > 0:
            sleep(slice_)


def reset():
    global _LAST_WAIT_SECONDS
    with _LOCK:
        _LAST_SENT.clear()
    _LAST_WAIT_SECONDS = 0.0


def last_sent(key):
    with _LOCK:
        return _LAST_SENT.get(key)


def last_wait_seconds():
    return _LAST_WAIT_SECONDS
