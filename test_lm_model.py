"""Blue under Bionic: a model is asked for by name when none is loaded.

Run with: python -m pytest test_lm_model.py

Bionic (LM Studio's agent app) serves LM Studio's API on 127.0.0.1:1234 but
keeps no model loaded for an API caller: a request naming no model, or the
placeholder "local-model", is refused with "No models loaded"; one naming a
real model has it loaded on the spot and unloaded after an hour idle. Blue
names no model (whatever is loaded answers), so on 2026-11-17 his first
message under Bionic got only the refusal (lm_studio_400_dump_20261117_093752).
"""

import json

import pytest
import requests

import bluetools as bt
from blue import lm_model

NO_MODEL = ('{"error":{"message":"No models loaded. Please load a model in '
            'the developer page or use the \'lms load\' command.",'
            '"type":"invalid_request_error","param":"model","code":null}}')
QWEN = "qwen/qwen3.8-27b"


class _Response:
    def __init__(self, status=200, body=None, lines=None):
        self.status_code = status
        self._body = body if body is not None else {
            "model": QWEN, "choices": [{"message": {"role": "assistant",
                                                    "content": "OK."}}]}
        self._lines = lines or []
        self.closed = False

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    @property
    def content(self):
        return self.text.encode()

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Server:
    """Answers like Bionic: nothing loaded until a request names a model."""

    def __init__(self, refuse=NO_MODEL, answer=None):
        self.calls = []
        self.responses = []
        self.refuse = refuse
        self.answer = answer or (lambda payload: _Response())

    def __call__(self, url, json=None, **kwargs):
        self.calls.append({"url": url, "json": json, "kwargs": kwargs})
        named = (json or {}).get("model")
        if not named or named == "local-model":
            response = _Response(400, self.refuse)
        else:
            response = self.answer(json)
        self.responses.append(response)
        return response


@pytest.fixture
def server(monkeypatch):
    srv = _Server()
    monkeypatch.setattr(requests, "post", srv)
    return srv


def _sse(*objects):
    out = [b"data: " + json.dumps(o).encode() for o in objects]
    out.append(b"data: [DONE]")
    return out


# --- the transport ------------------------------------------------------

def test_with_nothing_loaded_the_remembered_model_is_asked_for(server):
    lm_model.remember(QWEN, 206336)
    payload = {"messages": [{"role": "user", "content": "hi"}]}

    response = lm_model.post("http://x/v1/chat/completions", payload, timeout=5)

    assert response.status_code == 200
    assert [c["json"].get("model") for c in server.calls] == [None, QWEN]
    assert server.calls[1]["kwargs"] == {"timeout": 5}
    assert "model" not in payload, "the caller's payload is left as it was"


def test_the_placeholder_name_counts_as_no_name(server):
    lm_model.remember(QWEN)
    response = lm_model.post("u", {"model": "local-model", "messages": []})
    assert response.status_code == 200
    assert server.calls[-1]["json"]["model"] == QWEN


def test_with_nothing_remembered_the_refusal_stands(server):
    response = lm_model.post("u", {"messages": []})
    assert response.status_code == 400
    assert len(server.calls) == 1


def test_a_request_that_names_its_own_model_is_not_second_guessed(monkeypatch):
    calls = []

    def refuse(url, json=None, **kwargs):
        calls.append(json)
        return _Response(400, NO_MODEL)

    monkeypatch.setattr(requests, "post", refuse)
    lm_model.remember(QWEN)
    response = lm_model.post("u", {"model": "google/gemma-4-31b", "messages": []})
    assert response.status_code == 400
    assert len(calls) == 1


def test_other_refusals_are_not_retried(monkeypatch):
    calls = []

    def overflow(url, json=None, **kwargs):
        calls.append(json)
        return _Response(400, '{"error":"Context size has been exceeded."}')

    monkeypatch.setattr(requests, "post", overflow)
    lm_model.remember(QWEN)
    assert lm_model.post("u", {"messages": []}).status_code == 400
    assert len(calls) == 1


def test_the_environment_names_the_model_first(server, monkeypatch):
    lm_model.remember(QWEN)
    monkeypatch.setenv("BLUE_LM_MODEL", "google/gemma-4-31b")
    lm_model.post("u", {"messages": []})
    assert server.calls[-1]["json"]["model"] == "google/gemma-4-31b"
    assert lm_model.fallback_context_length() is None, \
        "the remembered context belongs to another model"


def test_a_streamed_refusal_is_closed_and_the_retry_streams(server):
    lm_model.remember(QWEN)
    response = lm_model.post("u", {"messages": []}, stream=True, timeout=7)
    assert server.calls[-1]["kwargs"] == {"stream": True, "timeout": 7}
    assert server.responses[0].closed, "the refused connection is let go"
    assert response is server.responses[1] and not response.closed


# --- what is remembered -------------------------------------------------

def test_remembering_writes_the_model_and_its_context(tmp_path, monkeypatch):
    path = tmp_path / "lm_model.json"
    monkeypatch.setenv("BLUE_LM_MODEL_FILE", str(path))
    lm_model.remember(QWEN, 206336)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["model"] == QWEN and record["context_length"] == 206336

    # A response names the model but not its context: the context is kept.
    lm_model.remember(QWEN)
    assert lm_model.fallback_context_length() == 206336

    # Another model: its own record, no borrowed context.
    lm_model.remember("google/gemma-4-31b")
    assert lm_model.fallback_model() == "google/gemma-4-31b"
    assert lm_model.fallback_context_length() is None


def test_embedders_and_placeholders_are_never_remembered():
    lm_model.remember("text-embedding-nomic-embed-text-v1.5", 2048)
    lm_model.remember("local-model")
    lm_model.remember("")
    lm_model.remember(None)
    assert lm_model.fallback_model() is None


def test_a_damaged_file_is_no_model(tmp_path, monkeypatch):
    path = tmp_path / "lm_model.json"
    path.write_bytes(b"\x00\x00{not json")
    monkeypatch.setenv("BLUE_LM_MODEL_FILE", str(path))
    assert lm_model.remembered() == {}
    assert lm_model.fallback_model() is None


def test_the_suite_never_remembers_into_blues_data_folder():
    assert "blue-test-jspace-" in lm_model._path().as_posix()


# --- bluetools ----------------------------------------------------------

class _Models:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


def test_the_chat_call_asks_for_the_model_when_none_is_loaded(server):
    lm_model.remember(QWEN)
    result = bt._post_to_model({"messages": [{"role": "user", "content": "hi"}]})
    assert result["choices"][0]["message"]["content"] == "OK."
    assert server.calls[-1]["json"]["model"] == QWEN


def test_the_streamed_chat_call_asks_for_it_too(monkeypatch):
    lines = _sse({"model": QWEN, "choices": [{"delta": {"content": "Morning."}}]},
                 {"choices": [{"delta": {}, "finish_reason": "stop"}]})
    srv = _Server(answer=lambda payload: _Response(lines=lines))
    monkeypatch.setattr(requests, "post", srv)
    lm_model.remember(QWEN)
    seen = []
    result = bt._stream_from_model({"messages": []}, seen.append)
    assert result["choices"][0]["message"]["content"] == "Morning."
    assert seen == ["Morning."]
    assert srv.calls[-1]["json"]["model"] == QWEN
    assert srv.calls[-1]["kwargs"]["stream"] is True


def test_a_loaded_model_is_remembered_with_its_context(monkeypatch):
    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models([
        {"id": QWEN, "type": "vlm", "state": "loaded",
         "loaded_context_length": 206336}]))
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    assert bt._detect_lm_context_size() == 206336
    assert lm_model.remembered()["context_length"] == 206336


def test_with_nothing_loaded_the_budget_is_the_remembered_models(monkeypatch):
    """Otherwise the first turn after an idle hour was trimmed to the 6,500
    fallback and lost most of the conversation."""
    lm_model.remember(QWEN, 206336)
    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models([
        {"id": QWEN, "type": "vlm", "state": "not-loaded",
         "max_context_length": 262144}]))
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    assert bt._detect_lm_context_size() == 206336
    assert bt._lm_loaded_model["id"] == QWEN, "the model that will answer"


def test_with_nothing_loaded_or_remembered_the_context_is_unknown(monkeypatch):
    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models([]))
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    assert bt._detect_lm_context_size() is None


def test_the_answering_model_is_remembered(monkeypatch):
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    monkeypatch.setattr(bt, "_LM_MODEL_SEEN", {"id": None, "warned": set()})
    monkeypatch.setattr(bt, "_lm_budget_cache", {"value": None, "at": 0.0})
    bt._lm_turn_note({"model": QWEN, "usage": {}}, {"reasoning_effort": "none"})
    assert lm_model.fallback_model() == QWEN


def test_the_older_client_asks_for_it_too(server):
    lm_model.remember(QWEN)
    result = bt.LMStudioClient(max_retries=1).chat(
        [{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "OK."
    assert [c["json"]["model"] for c in server.calls] == ["local-model", QWEN]


def test_the_outage_line_names_both_apps(monkeypatch):
    monkeypatch.setattr(bt._LM_FAILURE, "kind", "no_model", raising=False)
    monkeypatch.setattr(bt._LM_FAILURE, "detail", "", raising=False)
    monkeypatch.setattr(bt._LM_FAILURE, "dump", "", raising=False)
    text = bt.model_unavailable_reply("blue", "Alex")["choices"][0]["message"]["content"]
    assert "isn't loaded in LM Studio or Bionic" in text
    monkeypatch.setattr(bt._LM_FAILURE, "kind", "unreachable")
    text = bt.model_unavailable_reply("blue", "Alex")["choices"][0]["message"]["content"]
    assert "LM Studio or Bionic" in text


# --- background calls ---------------------------------------------------

def test_reflections_ask_for_it_too(monkeypatch):
    from blue import llm as blue_llm
    lines = _sse({"choices": [{"delta": {"content": "{}"}}]})
    srv = _Server(answer=lambda payload: _Response(lines=lines))
    monkeypatch.setattr(requests, "post", srv)
    lm_model.remember(QWEN)
    result = blue_llm.stream_abandonable("u", {"messages": []}, 5, lambda: False)
    assert result["choices"][0]["message"]["content"] == "{}"
    assert srv.calls[-1]["json"]["model"] == QWEN


def test_fact_extraction_asks_for_it_too(server):
    import blue_memory_improved as bmi
    lm_model.remember(QWEN)
    assert bmi._llm_extract("anything") == "OK."
    assert server.calls[-1]["json"]["model"] == QWEN
