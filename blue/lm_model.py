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

When Alex has chosen a context size (blue/model_settings.py, the chat page's
Speed panel), the model is loaded at that size through the server's load
endpoint instead of by name: a model loaded that way has no idle timer, and
loaded by name it would come back at Bionic's own size (206,336 tokens, which
filled the GPU). apply_context reloads it at a new size when he changes it.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from . import model_settings

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
    try:
        response.close()
    except Exception:
        pass
    ctx = model_settings.context_length()
    if ctx:
        print(f"   [LM] no model loaded: loading {model} at {ctx:,} tokens",
              flush=True)
        try:
            load_model(server_base(url), model, ctx)
        except Exception as exc:
            print(f"   [LM] could not load it at that size ({exc}); "
                  f"asking for it by name", flush=True)
    else:
        print(f"   [LM] no model loaded: asking for {model} by name "
              f"(Bionic loads it on request)", flush=True)
    return requests.post(url, json={**payload, "model": model}, **kwargs)


# --- loading and reloading at a chosen size --------------------------------

def server_base(url: str) -> str:
    """http://127.0.0.1:1234 from the chat-completions URL."""
    return (url or "").split("/v1/")[0].rstrip("/")


def loaded_models(base: str, timeout: float = 5) -> Optional[List[Dict[str, Any]]]:
    """The language-model instances loaded now, as
    [{"model", "instance_id", "context_length"}], or None when the server
    can't be read. Embedding models are left out."""
    try:
        r = requests.get(f"{base}/api/v1/models", timeout=timeout)
        if getattr(r, "status_code", 200) == 200:
            out: List[Dict[str, Any]] = []
            seen = set()
            for m in r.json().get("models") or []:
                if m.get("type") not in (None, "llm"):
                    continue
                for inst in m.get("loaded_instances") or []:
                    iid = inst.get("id") or m.get("key")
                    if not iid or iid in seen:
                        continue
                    seen.add(iid)
                    ctx = (inst.get("config") or {}).get("context_length")
                    out.append({"model": m.get("key"), "instance_id": iid,
                                "context_length": ctx if isinstance(ctx, int) else None})
            return out
    except (requests.RequestException, ValueError, AttributeError):
        pass
    # Older LM Studio: the v0 list says which models are loaded, one each.
    try:
        r = requests.get(f"{base}/api/v0/models", timeout=timeout)
        r.raise_for_status()
        return [{"model": m.get("id"), "instance_id": m.get("id"),
                 "context_length": m.get("loaded_context_length")}
                for m in r.json().get("data") or []
                if m.get("state") == "loaded"
                and m.get("type") not in ("embeddings", "embedding")]
    except (requests.RequestException, ValueError, AttributeError):
        return None


class ModelServerError(RuntimeError):
    """The server refused to load or unload a model."""


def load_model(base: str, model: str, context_length: Optional[int] = None,
               timeout: float = 600) -> Dict[str, Any]:
    """Load `model` through the server's load endpoint, at `context_length`
    tokens when given. A model loaded this way has no idle timer."""
    body: Dict[str, Any] = {"model": model, "echo_load_config": True}
    if context_length:
        body["context_length"] = int(context_length)
    r = requests.post(f"{base}/api/v1/models/load", json=body, timeout=timeout)
    if r.status_code >= 400:
        raise ModelServerError(f"load refused ({r.status_code}): {(r.text or '')[:200]}")
    data = r.json()
    ctx = (data.get("load_config") or {}).get("context_length") or context_length
    remember(model, ctx if isinstance(ctx, int) else None)
    return data


def unload_instance(base: str, instance_id: str, timeout: float = 60) -> None:
    r = requests.post(f"{base}/api/v1/models/unload",
                      json={"instance_id": instance_id}, timeout=timeout)
    if r.status_code >= 400:
        raise ModelServerError(f"unload refused ({r.status_code}): {(r.text or '')[:200]}")


def blues_model(loaded: List[Dict[str, Any]]) -> Optional[str]:
    """Which model is Blue's: the remembered one when it is loaded, else the
    one loaded, else the remembered one."""
    names = [i["model"] for i in loaded if i.get("model")]
    remembered_model = fallback_model()
    if remembered_model and remembered_model in names:
        return remembered_model
    return names[0] if names else remembered_model


def apply_context(base: str, context_length: Optional[int]) -> Dict[str, Any]:
    """Reload Blue's model at `context_length` tokens, unless it is loaded at
    that size already. None (the server's own size) reloads nothing: the
    server picks its size the next time it loads the model.

    Returns {"ok", "changed", "model", "context_length", "seconds"} or
    {"ok": False, "error"}. The caller holds the model gate, so no reply is
    cut off by the unload."""
    loaded = loaded_models(base)
    if loaded is None:
        return {"ok": False, "error": "Can't reach LM Studio or Bionic at "
                                      f"{base}."}
    model = blues_model(loaded)
    if not model:
        return {"ok": False, "error": "No model is loaded and Blue doesn't know "
                                      "which to load yet. Load one in Bionic "
                                      "or LM Studio first."}
    mine = [i for i in loaded if i.get("model") == model]
    now = mine[0]["context_length"] if mine else None
    if context_length is None or (mine and all(
            i.get("context_length") == context_length for i in mine)):
        return {"ok": True, "changed": False, "model": model, "context_length": now}
    started = time.time()
    try:
        for inst in mine:
            unload_instance(base, inst["instance_id"])
        data = load_model(base, model, context_length)
    except (ModelServerError, requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": f"Couldn't reload {model}: {exc}"}
    ctx = (data.get("load_config") or {}).get("context_length") or context_length
    return {"ok": True, "changed": True, "model": model, "context_length": ctx,
            "seconds": round(time.time() - started, 1)}
