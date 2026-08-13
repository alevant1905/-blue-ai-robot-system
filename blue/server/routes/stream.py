"""Live token preview for a chat turn, on a side channel.

The obvious way to stream would be to turn /v1/chat/completions itself into a
generator. That endpoint is the most safety-critical code in the app: after
the model finishes, roughly one reply in seven is rewritten by an output guard
— identity drift, a dropped household member, a wrong age, a denied memory, a
verbatim replay of the previous answer. Those guards need the COMPLETE reply,
and several of them regenerate it outright. Handing the browser fragments as
they arrive would mean speaking answers the guards exist to catch.

So the POST is left exactly as it was — same pipeline, same guards, same
authoritative JSON reply. The browser additionally subscribes here with a
stream id it made up, and the chat turn feeds its content deltas into that
subscription as they arrive. The preview is for the eyes only: the page
speaks, stores and remembers the POST's answer, never this one.

If nothing subscribes, the turn behaves exactly as before.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Dict, Optional

from flask import Response, jsonify


# stream_id -> {"q": Queue, "created": monotonic}
_STREAMS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()

# A browser that navigates away mid-turn never drains its queue. Nothing is
# ever added after the turn ends, so the only cost is memory — but a robot
# that runs for weeks would accumulate them.
_STREAM_TTL_SECONDS = 300.0
_MAX_STREAMS = 64

# Sent when the turn produced no tokens for this subscriber (a tool call, a
# canonical grounded answer, or a turn that finished before anyone subscribed).
_DONE = object()


def _prune_locked(now: float) -> None:
    stale = [
        key for key, entry in _STREAMS.items()
        if now - entry["created"] > _STREAM_TTL_SECONDS
    ]
    for key in stale:
        _STREAMS.pop(key, None)
    while len(_STREAMS) > _MAX_STREAMS:
        oldest = min(_STREAMS, key=lambda k: _STREAMS[k]["created"])
        _STREAMS.pop(oldest, None)


def open_stream(stream_id: str) -> Optional[Dict[str, Any]]:
    """Register or fetch a subscriber's entry. None for an unusable id.

    Normally the browser subscribes first and the turn follows, but the two
    race and either order has to work.
    """
    stream_id = str(stream_id or "").strip()[:80]
    if not stream_id:
        return None
    now = time.monotonic()
    with _LOCK:
        entry = _STREAMS.get(stream_id)
        if entry is None:
            entry = {"q": queue.Queue(), "created": now, "done": False}
            _STREAMS[stream_id] = entry
        # Pruned after inserting, so the cap is a real ceiling on the registry
        # rather than one-more-than-the-cap.
        _prune_locked(now)
        return entry


def token_sink(stream_id: Any):
    """A callback the chat turn can hand to the model, or None.

    None when nobody is listening, which keeps the non-streaming path free of
    any per-token work at all.
    """
    stream_id = str(stream_id or "").strip()[:80]
    if not stream_id:
        return None
    with _LOCK:
        entry = _STREAMS.get(stream_id)
        if entry is None or entry["done"]:
            return None

    def sink(piece: str) -> None:
        entry["q"].put(piece)

    return sink


def close_stream(stream_id: Any) -> None:
    """Mark the turn finished for its subscriber.

    The entry is marked rather than removed. EventSource reconnects on its
    own, and a subscriber that arrives (or returns) after the turn ended must
    drain whatever was buffered and then be told to stop — if the id vanished,
    that reconnect would create a fresh empty entry and sit on an open
    connection until the TTL expired. Pruning happens later, by age.
    """
    stream_id = str(stream_id or "").strip()[:80]
    if not stream_id:
        return
    with _LOCK:
        entry = _STREAMS.get(stream_id)
        if entry is None or entry["done"]:
            return
        entry["done"] = True
    entry["q"].put(_DONE)


def register(app) -> None:
    @app.route("/chat/stream/<stream_id>", methods=["GET"])
    def chat_stream(stream_id: str):
        entry = open_stream(stream_id)
        if entry is None:
            return jsonify({"ok": False, "error": "bad stream id"}), 400
        stream_queue = entry["q"]

        def events():
            # An immediate comment flushes headers so the browser reports the
            # connection as open before the turn's first token arrives.
            yield ": open\n\n"
            deadline = time.monotonic() + _STREAM_TTL_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = stream_queue.get(timeout=min(15.0, remaining))
                except queue.Empty:
                    # A finished turn that produced nothing for us (a tool
                    # call, or an id nobody ever fed) must not hold the
                    # connection open for the full TTL.
                    if entry["done"]:
                        break
                    yield ": keep-alive\n\n"   # keep proxies from timing out
                    continue
                if item is _DONE:
                    break
                yield f"data: {json.dumps({'delta': item})}\n\n"
            yield "event: end\ndata: {}\n\n"

        return Response(
            events(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "X-Accel-Buffering": "no",   # don't let a proxy buffer the stream
                # No "Connection" header: it is hop-by-hop, and PEP 3333 bars a
                # WSGI app from setting one. Waitress raised AssertionError on
                # every single stream, which killed the response mid-flight.
                # The server manages keep-alive itself.
            },
        )
