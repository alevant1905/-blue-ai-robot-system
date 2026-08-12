"""Small in-process priority gate for the single local LM Studio model.

Foreground speech must not compete with notebook and continuity reflections.
The gate serializes the participating calls and lets a waiting foreground call
go before newly-arriving background work.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator


_CONDITION = threading.Condition()
_ACTIVE = False
_FOREGROUND_WAITERS = 0

# Re-entrancy is not a nicety here. The gate is taken at the HTTP call itself
# so that tool execution, retrieval, and other slow non-model work never hold
# it — but the routes that already declare their priority (duet, banter,
# panel, continuity) wrap whole turns that reach those same calls. Without a
# depth counter the inner acquire would wait on a slot its own thread is
# holding, and the request would hang forever.
_LOCAL = threading.local()

# When a human last had the model. Serializing background work against a live
# turn is not enough on its own: measured, it only converts a steady +0.4s into
# a coin flip between no delay and waiting out a whole reflection. The real fix
# is not to start the reflection while someone is talking, and this is the
# signal for it — every user-facing surface already asks for foreground.
_LAST_FOREGROUND_AT = 0.0

# Not starting a reflection while someone is talking still leaves the case the
# gate cannot help with: the reflection was already generating when Alex hit
# send. Serializing then means his turn waits out the rest of it — measured at
# 13-28s. This counter is the signal a background call watches to give the
# model back mid-generation; it moves on every foreground acquisition.
_FOREGROUND_EPOCH = 0


def _mark_foreground() -> None:
    global _LAST_FOREGROUND_AT, _FOREGROUND_EPOCH
    _LAST_FOREGROUND_AT = time.monotonic()
    _FOREGROUND_EPOCH += 1


def seconds_since_foreground() -> float:
    """How long since a user-facing call last held (or wanted) the model."""
    if not _LAST_FOREGROUND_AT:
        return float("inf")
    return max(0.0, time.monotonic() - _LAST_FOREGROUND_AT)


def foreground_epoch() -> int:
    """A counter that advances whenever a foreground call takes the model."""
    return _FOREGROUND_EPOCH


def preemption_check():
    """A predicate that becomes true once a foreground call wants the model.

    Take it at the top of a background call and pass it to the transport; the
    epoch is sampled now, so only foreground work arriving *after* this point
    counts. Marked on the way in to the gate as well as out, so a turn that is
    still queued for the model already preempts.
    """
    start = _FOREGROUND_EPOCH
    return lambda: _FOREGROUND_EPOCH != start


@contextmanager
def llm_slot(foreground: bool = False) -> Iterator[None]:
    """Serialize one call to the single local model.

    Nested acquisitions on the same thread are no-ops: the outermost caller
    owns the slot and its ``foreground`` choice stands, so a background
    reflection cannot promote itself by calling through a helper that asks
    for foreground priority.
    """
    global _ACTIVE, _FOREGROUND_WAITERS
    depth = getattr(_LOCAL, "depth", 0)
    if depth:
        _LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LOCAL.depth = depth
        return

    if foreground:
        # Marked on the way in as well as out: a turn that is still waiting
        # for the model is exactly when new background work must not start.
        _mark_foreground()
    with _CONDITION:
        if foreground:
            _FOREGROUND_WAITERS += 1
        try:
            while _ACTIVE or (not foreground and _FOREGROUND_WAITERS > 0):
                _CONDITION.wait()
            _ACTIVE = True
        finally:
            if foreground:
                _FOREGROUND_WAITERS -= 1
    _LOCAL.depth = 1
    try:
        yield
    finally:
        _LOCAL.depth = 0
        if foreground:
            _mark_foreground()
        with _CONDITION:
            _ACTIVE = False
            _CONDITION.notify_all()
