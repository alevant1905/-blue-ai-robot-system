"""The chat page's Speed panel: thinking on/off and the model's context.

Run with: python -m pytest test_model_settings.py

On 2026-11-17 Bionic loaded qwen3.8-27b by itself at 206,336 tokens of
context, which filled 31.7 of the RTX 5090's 32 GB, and Alex found Blue too
slow. He asked to control the context and whether Blue thinks, directly from
the Blue app (blue/model_settings.py, blue/server/routes/model.py,
blue/lm_model.apply_context).
"""

import json

import pytest
import requests

import bluetools as bt
from blue import lm_model, model_settings
from blue.server.thinking import THINK_OFF, THINK_ON, THINKING_ALLOWANCE_TOKENS
from test_chat_pipeline import chat  # noqa: F401  (fixture)

QWEN = "qwen/qwen3.8-27b"
NO_MODEL = ('{"error":{"message":"No models loaded. Please load a model in '
            'the developer page or use the \'lms load\' command."}}')


class _Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {}

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def close(self):
        pass


class FakeBionic:
    """Loads, unloads and answers like Bionic 1.2.0 did on 2026-11-17."""

    def __init__(self, loaded=None, reachable=True):
        # instance_id -> context_length
        self.loaded = dict(loaded or {})
        self.reachable = reachable
        self.posts = []

    def get(self, url, timeout=None, **kw):
        if not self.reachable:
            raise requests.ConnectionError("refused")
        if url.endswith("/api/v1/models"):
            entries = [{"type": "llm", "key": QWEN, "loaded_instances": [
                {"id": iid, "config": {"context_length": ctx}}
                for iid, ctx in self.loaded.items()]},
                # Bionic lists a model twice (local gguf + LM Link mlx).
                {"type": "llm", "key": QWEN, "loaded_instances": []},
                {"type": "embedding", "key": "text-embedding-nomic-embed-text-v1.5",
                 "loaded_instances": [{"id": "text-embedding-nomic-embed-text-v1.5",
                                       "config": {"context_length": 2048}}]}]
            return _Response(200, {"models": entries})
        return _Response(404, "{}")

    def post(self, url, json=None, timeout=None, **kw):
        if not self.reachable:
            raise requests.ConnectionError("refused")
        self.posts.append((url.split("1234")[-1] if "1234" in url else url, json))
        if url.endswith("/api/v1/models/load"):
            ctx = json.get("context_length") or 206336
            self.loaded[json["model"]] = ctx
            return _Response(200, {"type": "llm", "instance_id": json["model"],
                                   "load_time_seconds": 8.2, "status": "loaded",
                                   "load_config": {"context_length": ctx}})
        if url.endswith("/api/v1/models/unload"):
            self.loaded.pop(json["instance_id"], None)
            return _Response(200, {"instance_id": json["instance_id"]})
        named = (json or {}).get("model")
        if not self.loaded and (not named or named == "local-model"):
            return _Response(400, NO_MODEL)
        if named and named != "local-model" and named not in self.loaded:
            self.loaded[named] = 206336          # JIT, at Bionic's own size
        return _Response(200, {"model": QWEN, "choices": [
            {"message": {"role": "assistant", "content": "OK."}}]})

    def paths(self):
        return [p for p, _ in self.posts]


@pytest.fixture
def bionic(monkeypatch):
    def install(**kw):
        fake = FakeBionic(**kw)
        monkeypatch.setattr(requests, "get", fake.get)
        monkeypatch.setattr(requests, "post", fake.post)
        return fake
    return install


BASE = "http://127.0.0.1:1234"
URL = BASE + "/v1/chat/completions"


# --- the settings -------------------------------------------------------

def test_unset_it_is_what_it_was(monkeypatch):
    monkeypatch.delenv("BLUE_THINKING_EFFORT", raising=False)
    assert model_settings.snapshot() == {"thinking": "low", "context_length": None}
    monkeypatch.setenv("BLUE_THINKING_EFFORT", "medium")
    assert model_settings.thinking() == "medium"


def test_a_saved_choice_wins_and_survives_a_reread(monkeypatch):
    monkeypatch.setenv("BLUE_THINKING_EFFORT", "medium")
    model_settings.save(thinking="off", context_length=32768)
    model_settings._cache.update(path=None, mtime=None, data=None)  # a restart
    assert model_settings.snapshot() == {"thinking": "off", "context_length": 32768}
    model_settings.save(context_length=None)
    assert model_settings.snapshot() == {"thinking": "off", "context_length": None}


@pytest.mark.parametrize("change", [
    {"thinking": "fast"}, {"thinking": None}, {"context_length": 1000},
    {"context_length": 10**7}, {"context_length": "32768"}, {"context_length": True},
])
def test_values_outside_the_choices_are_refused(change):
    with pytest.raises(ValueError):
        model_settings.save(**change)
    assert model_settings.snapshot()["context_length"] is None


def test_a_hand_edited_file_is_read_and_bad_values_ignored():
    path = model_settings._path()
    path.write_text(json.dumps({"thinking": "medium", "context_length": 3}),
                    encoding="utf-8")
    assert model_settings.snapshot() == {"thinking": "medium", "context_length": None}


def test_the_suite_never_writes_blues_settings():
    assert "blue-test-jspace-" in model_settings._path().as_posix()


# --- thinking -----------------------------------------------------------

@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(bt, "_REASONING_REFUSED_BY", set())
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": QWEN})
    monkeypatch.setattr(bt, "_lm_input_budget", lambda: 100_000)


def _payload(thinking):
    return bt._lm_studio_payload([{"role": "user", "content": "why?"}],
                                 include_tools=False, force_tool=None,
                                 iteration=1, tool_scope="full", thinking=thinking)


@pytest.mark.parametrize("chosen, effort", [
    ("off", "none"), ("low", "low"), ("medium", "medium"), ("high", "high")])
def test_a_turn_that_thinks_goes_out_at_the_chosen_effort(fresh, chosen, effort):
    model_settings.save(thinking=chosen)
    payload = _payload(THINK_ON)
    assert payload["reasoning_effort"] == effort
    assert payload["max_tokens"] == bt._chat_max_tokens() + (
        THINKING_ALLOWANCE_TOKENS if effort != "none" else 0)
    assert _payload(THINK_OFF)["reasoning_effort"] == "none"
    assert _payload(None)["reasoning_effort"] == "none"


def test_a_model_that_never_thinks_still_doesnt(fresh, monkeypatch):
    model_settings.save(thinking="high")
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": "qwen/qwen3.6-35b-a3b"})
    assert _payload(THINK_ON)["reasoning_effort"] == "none"


def test_thinking_off_reaches_a_real_question_on_the_chat_page(chat):
    chat.ask("what do you make of memory?")
    assert chat.model.main[-1]["reasoning_effort"] == "low"
    model_settings.save(thinking="off")
    chat.ask("what do you make of memory?")
    assert chat.model.main[-1]["reasoning_effort"] == "none"
    assert chat.model.main[-1]["max_tokens"] == bt._reply_budget.IDEA_REPLY_TOKENS


# --- the context --------------------------------------------------------

def test_reloading_at_a_new_size(bionic):
    srv = bionic(loaded={QWEN: 206336})
    result = lm_model.apply_context(BASE, 32768)
    assert result["ok"] and result["changed"]
    assert (result["model"], result["context_length"]) == (QWEN, 32768)
    assert srv.paths() == ["/api/v1/models/unload", "/api/v1/models/load"]
    assert srv.posts[1][1] == {"model": QWEN, "context_length": 32768,
                               "echo_load_config": True}
    assert srv.loaded == {QWEN: 32768}
    record = lm_model.remembered()
    assert (record["model"], record["context_length"]) == (QWEN, 32768)


def test_the_same_size_or_the_server_default_reloads_nothing(bionic):
    srv = bionic(loaded={QWEN: 32768})
    assert lm_model.apply_context(BASE, 32768)["changed"] is False
    assert lm_model.apply_context(BASE, None)["changed"] is False
    assert srv.posts == []


def test_with_nothing_loaded_the_remembered_model_is_loaded_at_the_size(bionic):
    srv = bionic(loaded={})
    lm_model.remember(QWEN, 206336)
    result = lm_model.apply_context(BASE, 65536)
    assert result["changed"] and srv.loaded == {QWEN: 65536}
    assert srv.paths() == ["/api/v1/models/load"]


def test_nothing_known_to_load_is_said_plainly(bionic):
    bionic(loaded={})
    result = lm_model.apply_context(BASE, 32768)
    assert result["ok"] is False and "Load one in Bionic or LM Studio" in result["error"]


def test_an_unreachable_server_is_said_plainly(bionic):
    bionic(reachable=False)
    result = lm_model.apply_context(BASE, 32768)
    assert result["ok"] is False and "Can't reach" in result["error"]


def test_after_an_idle_unload_the_model_comes_back_at_the_chosen_size(bionic):
    """Named in the request it would come back at Bionic's own 206,336."""
    srv = bionic(loaded={})
    lm_model.remember(QWEN)
    model_settings.save(context_length=32768)
    response = lm_model.post(URL, {"messages": []}, timeout=5)
    assert response.status_code == 200
    assert srv.paths() == ["/v1/chat/completions", "/api/v1/models/load",
                           "/v1/chat/completions"]
    assert srv.loaded == {QWEN: 32768}


def test_with_no_size_chosen_it_is_asked_for_by_name_as_before(bionic):
    srv = bionic(loaded={})
    lm_model.remember(QWEN)
    lm_model.post(URL, {"messages": []}, timeout=5)
    assert srv.paths() == ["/v1/chat/completions", "/v1/chat/completions"]


def test_the_budget_with_nothing_loaded_is_the_chosen_size(monkeypatch):
    class _Models:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": []}

    monkeypatch.setattr(bt.requests, "get", lambda url, timeout=None: _Models())
    monkeypatch.setattr(bt, "_lm_loaded_model", {"id": None})
    lm_model.remember(QWEN, 206336)
    model_settings.save(context_length=32768)
    assert bt._detect_lm_context_size() == 32768


def test_the_v0_list_is_read_when_there_is_no_v1(monkeypatch):
    def get(url, timeout=None, **kw):
        if url.endswith("/api/v1/models"):
            return _Response(404, '{"error":"Unexpected endpoint"}')
        return _Response(200, {"data": [
            {"id": QWEN, "type": "vlm", "state": "loaded", "loaded_context_length": 32768},
            {"id": "text-embedding-nomic-embed-text-v1.5", "type": "embeddings",
             "state": "loaded", "loaded_context_length": 2048}]})

    monkeypatch.setattr(requests, "get", get)
    assert lm_model.loaded_models(BASE) == [
        {"model": QWEN, "instance_id": QWEN, "context_length": 32768}]


# --- the route ----------------------------------------------------------

@pytest.fixture
def client():
    return bt.app.test_client()


def _local(**kw):
    return {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}, **kw}


def test_the_panel_reads_the_settings_and_what_is_loaded(client, bionic):
    bionic(loaded={QWEN: 206336})
    data = client.get("/model/settings", **_local()).get_json()
    assert data["thinking"] == "low" and data["context_length"] is None
    assert data["choices"]["thinking"] == ["off", "low", "medium", "high"]
    assert data["server"] == {"reachable": True, "model": QWEN, "loaded": True,
                              "context_length": 206336, "can_think": True}


def test_switching_thinking_off_from_the_panel(client, bionic, capsys):
    srv = bionic(loaded={QWEN: 206336})
    response = client.post("/model/settings", **_local(json={"thinking": "off"}))
    assert response.status_code == 200
    assert response.get_json()["thinking"] == "off"
    assert model_settings.thinking() == "off"
    assert srv.posts == [], "thinking reloads nothing"
    assert "[SPEED] thinking -> off" in capsys.readouterr().out


def test_choosing_a_size_from_the_panel_reloads_under_the_gate(
        client, bionic, monkeypatch):
    srv = bionic(loaded={QWEN: 206336})
    held = []
    from contextlib import contextmanager

    @contextmanager
    def gate(foreground=False):
        held.append(foreground)
        yield

    from blue.server.routes import model as model_routes
    monkeypatch.setattr(model_routes, "llm_slot", gate)
    monkeypatch.setitem(bt._lm_budget_cache, "at", 12345.0)
    response = client.post("/model/settings", **_local(json={"context_length": 32768}))
    data = response.get_json()
    assert response.status_code == 200
    assert data["reload"]["changed"] and data["server"]["context_length"] == 32768
    assert held == [True]
    assert srv.loaded == {QWEN: 32768}
    assert bt._lm_budget_cache["at"] == 0.0, "the budget is read again"


def test_a_failed_reload_keeps_the_choice_and_says_why(client, bionic):
    bionic(reachable=False)
    response = client.post("/model/settings", **_local(json={"context_length": 32768}))
    assert response.status_code == 502
    assert "Can't reach" in response.get_json()["reload"]["error"]
    assert model_settings.context_length() == 32768


@pytest.mark.parametrize("body", [{}, {"thinking": "fast"}, {"context_length": 5}, [1]])
def test_bad_requests_change_nothing(client, bionic, body):
    bionic(loaded={QWEN: 206336})
    response = client.post("/model/settings", **_local(json=body))
    assert response.status_code == 400
    assert model_settings.snapshot() == {"thinking": "low", "context_length": None}


def test_the_chat_page_has_the_panel_but_not_in_kid_mode():
    """test_pages_render.py renders the page and node-checks its script."""
    from flask import render_template_string
    from blue.server.pages.chat import CHAT_HTML
    with bt.app.test_request_context("/chat"):
        adult = render_template_string(CHAT_HTML, robot_name="Blue", kid=False)
        kid = render_template_string(CHAT_HTML, robot_name="Blue", kid=True)
    assert 'id="speedBtn"' in adult and 'id="speedPanel"' in adult
    assert "'/model/settings'" in adult
    assert 'id="speedBtn"' not in kid and 'id="speedPanel"' not in kid
