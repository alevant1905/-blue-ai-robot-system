"""Small in-process priority gate for the single local LM Studio model.

Foreground speech must not compete with notebook and continuity reflections.
The gate serializes the participating calls and lets a waiting foreground call
go before newly-arriving background work.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


_CONDITION = threading.Condition()
_ACTIVE = False
_FOREGROUND_WAITERS = 0


@contextmanager
def llm_slot(foreground: bool = False) -> Iterator[None]:
    global _ACTIVE, _FOREGROUND_WAITERS
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
    try:
        yield
    finally:
        with _CONDITION:
            _ACTIVE = False
            _CONDITION.notify_all()
