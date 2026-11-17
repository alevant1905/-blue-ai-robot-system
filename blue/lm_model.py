"""Which model to ask for when the model server has none loaded.

Blue names no model of his own choosing: whatever is loaded answers (Alex,
2026-10-07: "use whatever is loaded"). LM Studio keeps a model loaded until
someone unloads it, so that always worked.

Bionic, LM Studio's agent app, serves the same API on the same address
(127.0.0.1:1234) but keeps nothing loaded for an API caller. A request that
names no model, or the placeholder "local-model", is refused with "No models
loaded". A request that names a real model has it loaded on the spot
(qwen/qwen3.8-27b took 8 s on 2026-11-17, Bionic 1.2.0), and Bionic unloads it
again after an hour idle. Blue's first message that morning got only the
refusal.

So a refusal for want of a loaded model is answered by asking once more,
naming a model: BLUE_LM_MODEL when it is set, otherwise the last language
model Blue saw loaded or answering, remembered in data/lm_model.json across
restarts (BLUE_LM_MODEL_FILE moves it; the test suite does). Nothing changes
while a model is loaded, and a request that already names a model of its own
is left alone. With nothing remembered and nothing set, the refusal stands and
Blue says the model isn't loaded, as before.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# Names that mean "whatever is loaded", not a model. blue/llm.py and the older
# client in bluetools.py send "local-model" when LM_STUDIO_MODEL is unset.
PLACEHOLDER_MODELS = frozenset({"", "local-model"})

# The same wording _classify_lm_failure keys on in bluetools.py.
_NO_MODEL_RE = re.compile(r"no models? (?:are )?loaded|model (?:is )?not loaded", re.I)

_lock = threading.Lock()
_cache: Dict[str, Any] = {"path": None, "record": None}


def _path() -> Path:
    env = os.environ.get("BLUE_LM_MODEL_FILE")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "lm_model.json"


def remembered() -> Dict[str, Any]:
    """The remembered model record ({"model", "context_length", "seen_at"}),
    or {} when there is none."""
    path = _path()
    with _lock:
        if _cache["path"] == str(path) and _cache["record"] is not None:
            return dict(_cache["record"])
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        if not isinstance(record, dict) or not isinstance(record.get("model"), str):
            record = {}
        _cache.update(path=str(path), record=record)
        return dict(record)


def _usable_name(model_id: Any) -> str:
    model = model_id.strip() if isinstance(model_id, str) else ""
    if model in PLACEHOLDER_MODELS or "embed" in model.lower():
        return ""
    return model


def remember(model_id: Any, context_length: Any = None) -> None:
    """Note the language model that is loaded or just answered, and the
    context it was loaded with when known. Written only when it changes."""
    model = _usable_name(model_id)
    if not model:
        return
    ctx = (context_length if isinstance(context_length, int)
           and not isinstance(context_length, bool) and context_length > 0
           else None)
    record = remembered()
    same = record.get("model") == model
    if same and (ctx is None or record.get("context_length") == ctx):
        return
    new: Dict[str, Any] = {"model": model}
    if ctx:
        new["context_length"] = ctx
    elif same and record.get("context_length"):
        new["context_length"] = record["context_length"]
    new["seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(new, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass  # still remembered for this run
    with _lock:
        _cache.update(path=str(path), record=new)


def fallback_model() -> Optional[str]:
    """The model to name when none is loaded, or None when there is none to
    name."""
    env = _usable_name(os.environ.get("BLUE_LM_MODEL"))
    if env:
        return env
    return remembered().get("model") or None


def fallback_context_length() -> Optional[int]:
    """The context the fallback model was last seen loaded with, when that
    model is the remembered one."""
    record = remembered()
    ctx = record.get("context_length")
    if record.get("model") and record.get("model") == fallback_model() \
            and isinstance(ctx, int) and ctx > 0:
        return ctx
    return None


def is_no_model(response: Any) -> bool:
    """A 4xx refusal because no model is loaded."""
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or not 400 <= status < 500:
        return False
    try:
        text = response.text or ""
    except Exception:
        return False
    return bool(_NO_MODEL_RE.search(text))


def post(url: str, payload: Any, **kwargs: Any):
    """requests.post(url, json=payload, **kwargs), asked once more naming a
    model when the server refuses for want of a loaded one.

    Returns the response the caller would have had, or the retry's. Works for
    stream=True too: the refusal is read (it is small) and closed before the
    retry, whose response is returned unread.
    """
    response = requests.post(url, json=payload, **kwargs)
    if not isinstance(payload, dict) or not is_no_model(response):
        return response
    if _usable_name(payload.get("model")):
        return response   # it asked for a model by name: that refusal is the answer
    model = fallback_model()
    if not model:
        return response
    print(f"   [LM] no model loaded: asking for {model} by name "
          f"(Bionic loads it on request)", flush=True)
    try:
        response.close()
    except Exception:
        pass
    return requests.post(url, json={**payload, "model": model}, **kwargs)
