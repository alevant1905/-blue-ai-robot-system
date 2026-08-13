"""The live token preview: SSE side channel and the streamed transport.

The preview exists so the user sees words arriving instead of a spinner. It is
deliberately NOT what gets spoken: the server's output guards rewrite roughly
one reply in seven after generation finishes, so the POST stays authoritative.
These tests pin both halves of that contract.
"""

import json
import threading
import time

import pytest
from flask import Flask

from blue.server.routes import stream as stream_routes


@pytest.fixture
def client():
    app = Flask("stream-test")
    stream_routes.register(app)
    app.testing = True
    return app.test_client()


def _deltas(payload):
    """Pull the delta strings out of an SSE body."""
    out = []
    for line in payload.splitlines():
        if line.startswith("data: "):
            body = json.loads(line[6:])
            if "delta" in body:
                out.append(body["delta"])
    return out


def test_tokens_reach_the_subscriber_in_order(client):
    stream_routes.open_stream("turn-1")
    sink = stream_routes.token_sink("turn-1")
    assert sink is not None
    for piece in ("Memory ", "is ", "not ", "storage."):
        sink(piece)
    stream_routes.close_stream("turn-1")

    body = client.get("/chat/stream/turn-1").get_data(as_text=True)
    assert _deltas(body) == ["Memory ", "is ", "not ", "storage."]


def test_no_subscriber_means_no_callback_at_all(client):
    """The non-streaming path must not pay for per-token work."""
    assert stream_routes.token_sink("nobody-is-listening") is None
    assert stream_routes.token_sink("") is None
    assert stream_routes.token_sink(None) is None


def test_closing_ends_the_event_stream(client):
    stream_routes.open_stream("turn-2")
    stream_routes.close_stream("turn-2")
    body = client.get("/chat/stream/turn-2").get_data(as_text=True)
    assert "event: end" in body


def test_a_second_turn_cannot_reuse_a_closed_id(client):
    stream_routes.open_stream("turn-3")
    stream_routes.close_stream("turn-3")
    assert stream_routes.token_sink("turn-3") is None


def test_abandoned_streams_are_pruned(monkeypatch):
    monkeypatch.setattr(stream_routes, "_STREAM_TTL_SECONDS", 0.01)
    stream_routes.open_stream("abandoned")
    time.sleep(0.05)
    stream_routes.open_stream("fresh")
    assert "abandoned" not in stream_routes._STREAMS
    stream_routes.close_stream("fresh")


def test_registry_is_bounded(monkeypatch):
    monkeypatch.setattr(stream_routes, "_MAX_STREAMS", 4)
    for i in range(12):
        stream_routes.open_stream(f"bulk-{i}")
    assert len(stream_routes._STREAMS) <= 4
    for i in range(12):
        stream_routes.close_stream(f"bulk-{i}")


def test_a_bad_id_is_rejected(client):
    assert client.get("/chat/stream/%20").status_code == 400


def test_subscriber_sees_tokens_while_the_turn_is_still_running(client):
    """The whole point: deltas arrive during generation, not after it."""
    stream_routes.open_stream("turn-live")
    sink = stream_routes.token_sink("turn-live")
    seen_at = []

    def produce():
        for piece in ("one ", "two ", "three"):
            time.sleep(0.02)
            sink(piece)
            seen_at.append(time.monotonic())
        stream_routes.close_stream("turn-live")

    t = threading.Thread(target=produce)
    start = time.monotonic()
    t.start()
    body = client.get("/chat/stream/turn-live").get_data(as_text=True)
    t.join(timeout=5)

    assert _deltas(body) == ["one ", "two ", "three"]
    # The producer was still going when the stream opened.
    assert seen_at and seen_at[0] > start


# --- the streamed transport itself -----------------------------------------

class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        return iter(self._lines)


def _sse(*objects):
    out = [b"data: " + json.dumps(o).encode() for o in objects]
    out.append(b"data: [DONE]")
    return out


def test_streamed_call_returns_the_same_shape_as_a_blocking_one(monkeypatch):
    """Everything downstream depends on this: the guards, the tool loop, the
    logging all expect a completed choices/message dict."""
    import bluetools as bt

    lines = _sse(
        {"choices": [{"delta": {"content": "Memory "}}]},
        {"choices": [{"delta": {"content": "matters."}}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}]},
    )
    monkeypatch.setattr(bt.requests, "post",
                        lambda *a, **k: _FakeResponse(lines))

    seen = []
    result = bt._stream_from_model({"messages": []}, seen.append)

    assert result["choices"][0]["message"]["content"] == "Memory matters."
    assert result["choices"][0]["message"]["role"] == "assistant"
    assert seen == ["Memory ", "matters."]


def test_streamed_tool_calls_are_reassembled(monkeypatch):
    """Fragmented tool-call arguments must come back as one valid call."""
    import bluetools as bt

    lines = _sse(
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "capture_camera",
                                                  "arguments": '{"qu'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": 'ery":"x"}'}}]}}]},
    )
    monkeypatch.setattr(bt.requests, "post",
                        lambda *a, **k: _FakeResponse(lines))

    seen = []
    result = bt._stream_from_model({"messages": []}, seen.append)
    call = result["choices"][0]["message"]["tool_calls"][0]

    assert call["function"]["name"] == "capture_camera"
    assert json.loads(call["function"]["arguments"]) == {"query": "x"}
    # A turn that ends in a tool call has no answer to preview.
    assert seen == []


def test_a_broken_client_pipe_does_not_fail_the_turn(monkeypatch):
    """The reply still has to be logged, guarded and stored."""
    import bluetools as bt

    lines = _sse(
        {"choices": [{"delta": {"content": "still "}}]},
        {"choices": [{"delta": {"content": "answered"}}]},
    )
    monkeypatch.setattr(bt.requests, "post",
                        lambda *a, **k: _FakeResponse(lines))

    def exploding_sink(piece):
        raise BrokenPipeError("the browser went away")

    result = bt._stream_from_model({"messages": []}, exploding_sink)
    assert result["choices"][0]["message"]["content"] == "still answered"


def test_no_hop_by_hop_headers_on_the_event_stream(client):
    """PEP 3333 bars a WSGI app from setting "Connection". Waitress asserted
    on it and killed the response for EVERY stream (live 2026-08-13):
    AssertionError: Connection is a "hop-by-hop" header."""
    stream_routes.open_stream("turn-hop")
    stream_routes.close_stream("turn-hop")
    resp = client.get("/chat/stream/turn-hop")
    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade",
    }
    assert not {k.lower() for k, _ in resp.headers} & hop_by_hop
    assert resp.headers["Cache-Control"].startswith("no-cache")
