"""Alex's speed settings for the language model, set from the chat page.

Two settings, saved in data/model_settings.json (BLUE_MODEL_SETTINGS_FILE
moves it; the test suite does) and read on every request, so a change holds
from the next message on, with no restart:

thinking  "off" | "low" | "medium" | "high". "off": no turn reasons first.
          Otherwise each chat turn still decides for itself
          (blue/server/thinking.py: greetings and small talk never think) and
          a turn that thinks does so at this effort. Unset: BLUE_THINKING_EFFORT,
          else "low" (Alex's choice, 2026-10-06).

context_length  The context, in tokens, the model is loaded with, or None to
          leave it to LM Studio / Bionic. On 2026-11-17 Bionic loaded
          qwen3.8-27b by itself at 206,336 tokens, which filled 31.7 of the
          RTX 5090's 32 GB, and Blue got slow. The chat page reloads the model
          at the chosen size (blue/lm_model.apply_context), and when nothing is
          loaded Blue loads it at that size himself (lm_model.post). Blue's
          input budget follows the loaded context (bluetools._lm_input_budget).

Pure settings: no bluetools import, no model calls.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

THINKING_CHOICES = ("off", "low", "medium", "high")
_EFFORTS = ("low", "medium", "high")

# What the chat page offers. Blue's system prompt and the tools he may call
# take ~16k tokens on their own, so 16k leaves little room for the
# conversation: the smallest that still holds a few exchanges.
CONTEXT_CHOICES = (16384, 32768, 65536, 131072)
MIN_CONTEXT = 8192
MAX_CONTEXT = 262144

_lock = threading.Lock()
_cache: Dict[str, Any] = {"path": None, "mtime": None, "data": None}
_UNSET = object()


def _path() -> Path:
    env = os.environ.get("BLUE_MODEL_SETTINGS_FILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "model_settings.json"


def _read() -> Dict[str, Any]:
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _lock:
        if (_cache["path"] == str(path) and _cache["mtime"] == mtime
                and _cache["data"] is not None):
            return dict(_cache["data"])
    data: Dict[str, Any] = {}
    if mtime is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
    clean: Dict[str, Any] = {}
    if data.get("thinking") in THINKING_CHOICES:
        clean["thinking"] = data["thinking"]
    ctx = _valid_context(data.get("context_length"))
    if ctx:
        clean["context_length"] = ctx
    with _lock:
        _cache.update(path=str(path), mtime=mtime, data=clean)
    return dict(clean)


def _valid_context(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if MIN_CONTEXT <= value <= MAX_CONTEXT else None


def _env_effort() -> str:
    effort = (os.environ.get("BLUE_THINKING_EFFORT") or "low").strip().lower()
    return effort if effort in _EFFORTS else "low"


def thinking() -> str:
    """"off", or the effort a turn that thinks is asked for."""
    return _read().get("thinking") or _env_effort()


def thinking_saved() -> bool:
    return "thinking" in _read()


def context_length() -> Optional[int]:
    """The chosen context in tokens, or None for the server's own."""
    return _read().get("context_length")


def snapshot() -> Dict[str, Any]:
    return {"thinking": thinking(), "context_length": context_length()}


def save(*, thinking: Any = _UNSET, context_length: Any = _UNSET) -> Dict[str, Any]:
    """Change one or both settings; returns the new snapshot.

    Raises ValueError for a value outside the choices. ``context_length``
    None goes back to the server's own choice.
    """
    data = _read()
    if thinking is not _UNSET:
        if thinking not in THINKING_CHOICES:
            raise ValueError(f"thinking must be one of {', '.join(THINKING_CHOICES)}")
        data["thinking"] = thinking
    if context_length is not _UNSET:
        if context_length is None:
            data.pop("context_length", None)
        else:
            ctx = _valid_context(context_length)
            if not ctx:
                raise ValueError(f"context_length must be a whole number of tokens "
                                 f"from {MIN_CONTEXT} to {MAX_CONTEXT}, or null")
            data["context_length"] = ctx
    data["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    with _lock:
        _cache.update(path=None, mtime=None, data=None)
    return snapshot()
