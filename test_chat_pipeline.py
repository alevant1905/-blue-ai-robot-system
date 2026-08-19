"""Characterization tests for the chat pipeline.

Why these exist: `chat_completions` (1,183 lines) and `process_with_tools`
(1,287 lines) are the two largest functions in the app and, before this file,
were executed by exactly zero tests — the suite ran 522 green while never once
touching the code that answers a message. Refactoring them against that suite
would have been refactoring blind, because almost any breakage would have kept
it green.

These tests pin OBSERVABLE behaviour of the pipeline end to end, not internal
structure, so the pipeline can be restructured underneath them.

SAFETY: this module drives the real Flask app, which controls a real house.
`execute_tool` is stubbed before anything can call it, the model is stubbed at
its single HTTP seam, and every persistence path is redirected — no email is
sent, no head moves, and the real memory database is never written to.
"""

import base64
import datetime
import json
import types

import pytest

import bluetools as bt


# --------------------------------------------------------------------------
# Harness
# --------------------------------------------------------------------------

class ModelStub:
    """Stands in for LM Studio at the one seam every call funnels through."""

    def __init__(self):
        self.replies = []
        self.payloads = []        # every call, either transport
        self.main = []            # the tool-loop transport only
        self.default = "That's an interesting way to put it, Alex."

    def queue(self, *contents):
        self.replies.extend(contents)

    def __call__(self, payload, timeout=120, main=False):
        self.payloads.append(payload)
        if main:
            self.main.append(payload)
        content = self.replies.pop(0) if self.replies else self.default
        if isinstance(content, dict):          # a raw tool-call response
            return content
        return {"choices": [{"message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}]}

    # --- convenience accessors over what the model was actually shown ---
    @property
    def system_prompt(self):
        """From the tool-loop call — the one that carries the built prompt."""
        for message in self.main[-1]["messages"]:
            if message.get("role") == "system":
                return message.get("content") or ""
        return ""

    @property
    def last_user_message(self):
        for message in reversed(self.payloads[-1]["messages"]):
            if message.get("role") == "user":
                return message.get("content") or ""
        return ""

    @property
    def tool_count(self):
        return len(self.main[-1].get("tools") or [])


@pytest.fixture
def chat(monkeypatch):
    """A test client for /v1/chat/completions with every side effect stubbed."""
    model = ModelStub()

    # 1) THE HOUSE. Stubbed first and unconditionally: a stray tool call here
    #    would take a real photo, send real mail, or move a real robot.
    executed = []

    def execute_tool(name, args=None, *rest, **kwargs):
        executed.append({"tool": name, "args": args})
        return f"[stubbed {name}]"

    monkeypatch.setattr(bt, "execute_tool", execute_tool)

    # 2) THE MODEL. Both transports funnel through these two.
    monkeypatch.setattr(bt, "_post_to_model",
                        lambda payload, timeout=120: model(payload, timeout, main=True))

    def stream(payload, on_token, timeout=120):
        result = model(payload, timeout, main=True)
        text = result["choices"][0]["message"].get("content") or ""
        if on_token and text:
            for word in text.split(" "):
                on_token(word + " ")
        return result

    monkeypatch.setattr(bt, "_stream_from_model", stream)

    # There are TWO transports, not one. The tool loop goes through
    # _post_to_model; the guards' regenerations go through call_llm ->
    # LMStudioClient.chat. Leaving this one live sent regenerations to the real
    # LM Studio, which made the guard tests nondeterministic and slow.
    if getattr(bt, "_LM", None) is not None:
        monkeypatch.setattr(
            bt._LM, "chat",
            lambda messages, **kwargs: model({"messages": messages, **kwargs}),
        )

    # 3) PERSISTENCE. The real memory DB and journals must not be touched.
    saved = []
    monkeypatch.setattr(bt, "save_conversation_to_db",
                        lambda *a, **k: saved.append((a, k)))
    monkeypatch.setattr(bt, "extract_and_save_facts", lambda *a, **k: None)
    # The post-reply background thread consolidates, summarises and re-indexes
    # against the real store. Only the WRITERS are stubbed — the read paths
    # stay live, so assertions about <known_facts> still mean something.
    if getattr(bt, "memory_system", None):
        for writer in ("consolidate_if_needed", "summarize_previous_sessions",
                       "backfill_session_memories", "update_rhythms_if_due",
                       "add_memory", "store_memory", "save_fact"):
            if hasattr(bt.memory_system, writer):
                monkeypatch.setattr(bt.memory_system, writer,
                                    lambda *a, **k: None, raising=False)
    if hasattr(bt, "_continuity_routes"):
        monkeypatch.setattr(bt._continuity_routes, "note_exchange",
                            lambda *a, **k: [], raising=False)
        monkeypatch.setattr(bt._continuity_routes, "begin_turn",
                            lambda *a, **k: None, raising=False)
        monkeypatch.setattr(bt._continuity_routes, "cancel_turn",
                            lambda *a, **k: None, raising=False)

    # 4) HARDWARE. No head should twitch during a test run.
    monkeypatch.setattr(bt.blue_head, "get_head",
                        lambda *a, **k: types.SimpleNamespace(
                            driver="stub", eye_color=lambda *a: True,
                            nod_yes=lambda *a: True, shake_no=lambda *a: True,
                            lip_sequence=lambda *a, **k: True))

    bt.app.testing = True
    client = bt.app.test_client()

    def ask(text, **body):
        payload = {"messages": [{"role": "user", "content": text}], "robot": "blue"}
        payload.update(body)
        response = client.post("/v1/chat/completions", json=payload)
        return response

    return types.SimpleNamespace(
        ask=ask, model=model, executed=executed, saved=saved, client=client,
    )


def reply_of(response):
    return response.get_json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------
# The pipeline answers at all
# --------------------------------------------------------------------------

def test_a_plain_question_gets_the_model_s_answer(chat):
    chat.model.queue("Memory is a strange thing to be made of.")
    response = chat.ask("what do you make of memory?")

    assert response.status_code == 200
    assert reply_of(response) == "Memory is a strange thing to be made of."
    assert chat.executed == [], "a conversational turn must not touch the house"


def test_the_reply_is_persisted(chat):
    chat.ask("what do you make of memory?")
    assert chat.saved, "the exchange was never written to the conversation log"


def test_a_malformed_model_response_does_not_500(chat):
    """Ohbot says "I'm having trouble connecting" on a 500 — never do that."""
    chat.model.queue({"choices": []})
    response = chat.ask("are you there?")

    assert response.status_code == 200
    assert reply_of(response)


# --------------------------------------------------------------------------
# What the model is actually shown
# --------------------------------------------------------------------------

def test_the_system_prompt_is_not_deleted_by_the_vision_purge(chat):
    """The worst bug this harness found.

    The system prompt carries the line "CAMERA DISCIPLINE:". The vision purge
    scanned every message for the bare substring 'CAMERA', so index 0 matched
    on every turn — and on any turn where the user was not asking about vision
    it deleted that index. Blue lost his persona, his identity rules, his
    <known_facts>, the <family> block and every memory block, and answered
    from the conversation thread alone. It looked exactly like "he doesn't
    remember who we are".
    """
    chat.ask("what do you make of memory?")
    prompt = chat.model.system_prompt

    assert prompt, "the system message never reached the model"
    assert "CAMERA DISCIPLINE" in prompt, "the camera rule itself went missing"
    for block in ("<known_facts>", "<now>", "IDENTITY BOUNDARY"):
        assert block in prompt, f"{block} was stripped from the prompt"


def test_a_real_camera_message_is_still_purged(chat):
    """The purge must keep working for what it was actually for."""
    chat.model.queue("I can see the room.")
    response = chat.client.post("/v1/chat/completions", json={
        "robot": "blue",
        "messages": [
            {"role": "user", "content": "what do you see?"},
            {"role": "assistant", "content": "camera_NEW_1.jpg CAMERA capture shows a kitchen."},
            {"role": "user", "content": "thanks, now tell me about memory"},
        ],
    })

    assert response.status_code == 200
    prompt = chat.model.system_prompt
    assert prompt and "<known_facts>" in prompt, "the system prompt was culled again"
    stale = [m for m in chat.model.payloads[-1]["messages"]
             if "camera_NEW_" in str(m.get("content") or "")]
    assert stale == [], "the stale camera message survived the purge"


def test_the_household_facts_reach_the_prompt(chat):
    # A question that actually reaches the model — see the grounded-reply test
    # below for the questions that never do.
    chat.ask("what do you make of memory?")
    assert "<known_facts>" in chat.model.system_prompt


def test_a_canonical_household_question_never_reaches_the_model(chat):
    """Identity and roster questions are answered deterministically from the
    facts table. No LLM call is made at all — worth pinning, because it means
    prompt-level assertions are meaningless for these questions."""
    response = chat.ask("who is in my family?")

    assert response.status_code == 200
    assert reply_of(response)
    assert chat.model.main == [], "a canonical answer still ran the tool loop"


def test_the_stable_prefix_precedes_the_clock(chat):
    """The prompt-cache ordering, pinned end to end rather than by unit."""
    chat.ask("what do you make of memory?")
    prompt = chat.model.system_prompt
    assert "<now>" in prompt
    for marker in ("IDENTITY BOUNDARY:", "LANGUAGES:", "REMINDER TIME RULES:"):
        assert prompt.index(marker) < prompt.index("<now>")


def test_the_clock_precedes_the_schedule(chat):
    chat.ask("what do you make of memory?")
    prompt = chat.model.system_prompt
    for marker in ("Reminders in the next", "<recent_schedule>"):
        if marker in prompt:
            assert prompt.index("<now>") < prompt.index(marker)


def test_a_family_question_gets_the_canonical_block(chat):
    chat.ask("what should I get the girls for their birthdays?")
    assert "<family>" in chat.model.system_prompt


def test_an_unrelated_question_does_not_get_the_family_block(chat):
    chat.ask("what is the capital of Denmark?")
    assert "<family>" not in chat.model.system_prompt


def test_the_robot_persona_follows_the_requested_robot(chat):
    chat.ask("what do you make of memory?", robot="hexia")
    assert "Hexia" in chat.model.system_prompt


# --------------------------------------------------------------------------
# The output guards — the reason streaming had to stay preview-only
# --------------------------------------------------------------------------

def test_a_refusal_about_the_family_is_regenerated(chat):
    """"I don't have any record of your family" is false and must not ship."""
    chat.model.queue(
        "I don't have any record of your family, Alex.",
        "Athena, Emmy and Vilda — and Stella, of course.",
    )
    response = chat.ask("do you remember our family?")

    text = reply_of(response)
    assert "don't have any record" not in text.lower(), (
        "a family-memory refusal reached the user"
    )
    assert len(chat.model.payloads) >= 2, "the guard never regenerated"
    assert len(chat.model.main) == 1, "the regeneration went through the tool loop"


def test_a_verbatim_replay_of_the_previous_reply_is_caught(chat):
    """The classroom-introduction bug: the model re-says its last answer."""
    previous = "I am Blue, a companion robot built by Alex Levant."
    chat.model.queue(previous, "Forgetting is the more interesting half.")
    response = chat.client.post("/v1/chat/completions", json={
        "robot": "blue",
        "messages": [
            {"role": "user", "content": "who are you?"},
            {"role": "assistant", "content": previous},
            {"role": "user", "content": "and what about forgetting?"},
        ],
    })

    assert response.status_code == 200
    assert reply_of(response) != previous, "the model replayed its previous reply"


def test_a_clean_reply_is_not_regenerated(chat):
    """The guards must be quiet on an ordinary good answer."""
    chat.model.queue("Forgetting is the more interesting half of remembering.")
    chat.ask("what about forgetting?")
    assert len(chat.model.payloads) == 1, "an ordinary reply was regenerated"


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

def test_a_camera_request_runs_the_camera_tool(chat):
    chat.model.queue(
        {"choices": [{"message": {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "capture_camera", "arguments": "{}"}}]}}]},
        "I can see the kitchen table from here.",
    )
    response = chat.ask("what do you see right now?")

    assert response.status_code == 200
    assert any(call["tool"] == "capture_camera" for call in chat.executed)


def test_the_tool_schema_is_sent_on_an_ordinary_turn(chat):
    """It costs ~9,300 tokens but catches elliptical follow-ups the selector
    cannot see. If this ever changes it should be a decision, not a drift."""
    chat.ask("what do you make of memory?")
    assert chat.model.tool_count > 0


# --------------------------------------------------------------------------
# The live preview
# --------------------------------------------------------------------------

def test_a_stream_id_makes_the_turn_emit_tokens(chat):
    from blue.server.routes import stream as stream_routes

    stream_routes.open_stream("chartest")
    chat.model.queue("Words arriving one at a time.")
    response = chat.ask("say something", stream_id="chartest")

    assert response.status_code == 200
    body = chat.client.get("/chat/stream/chartest").get_data(as_text=True)
    deltas = "".join(
        json.loads(line[6:]).get("delta", "")
        for line in body.splitlines()
        if line.startswith("data: ")
    )
    assert deltas.strip() == "Words arriving one at a time."


def test_the_guarded_reply_is_what_the_post_returns(chat):
    """The preview is advisory; the POST is authoritative."""
    from blue.server.routes import stream as stream_routes

    stream_routes.open_stream("chartest2")
    chat.model.queue(
        "I don't have any record of your family, Alex.",
        "Athena, Emmy and Vilda.",
    )
    response = chat.ask("do you remember our family?", stream_id="chartest2")

    assert "don't have any record" not in reply_of(response).lower()


def test_a_clock_denial_is_regenerated_end_to_end(chat):
    """Proves the wiring, not just the pattern: a recorded denial goes in, the
    guard fires inside the real pipeline, and the corrected reply comes out."""
    chat.model.queue(
        "I don't actually have direct access to your device's clock or "
        "timezone settings, so I can't tell you.",
        "It's Tuesday, and just gone lunchtime.",
    )
    # NOT "what time is it?" — that is confidently routed to the get_local_time
    # tool and the model never gets to deny anything. The recorded denials all
    # happened when the clock came up incidentally, which is this shape.
    response = chat.ask("how has your morning been so far?")

    text = reply_of(response)
    assert "device's clock" not in text, "the clock denial reached the user"
    assert len(chat.model.payloads) >= 2, "the guard never regenerated"


def test_a_denial_naming_someone_on_record_is_regenerated(chat):
    """The Felix case, through the whole pipeline. No pattern can enumerate
    people, so this one is checked against the facts table."""
    chat.model.queue(
        "I don't have any record of a Felix in our shared history.",
        "Felix is your brother — he's in Waterloo with Svetlana.",
    )
    response = chat.ask("do you remember Felix?")

    assert "don't have any record" not in reply_of(response).lower()
    assert len(chat.model.payloads) >= 2, "the guard never regenerated"


def test_a_voice_denial_is_regenerated_end_to_end(chat):
    """Proves the wiring: Blue claiming he cannot speak, through the real
    pipeline, comes out corrected."""
    chat.model.queue(
        "I can't speak to her directly since I don't have a voice output.",
        "I can say it out loud when she's in the room — want me to?",
    )
    response = chat.ask("could you tell Stella dinner is ready?")

    text = reply_of(response)
    assert "voice output" not in text, "the voice denial reached the user"
    assert len(chat.model.payloads) >= 2, "the guard never regenerated"


# --------------------------------------------------------------------------
# The transport the pipeline actually uses
# --------------------------------------------------------------------------

def test_the_live_client_accepts_a_cancel_callback_without_sending_it(monkeypatch):
    """There are two LMStudioClient classes; this is the one chat calls.

    Adding ``should_cancel`` to the copy in blue/llm.py alone was not enough:
    on the live path the callback fell through **kwargs into the request body
    and every reflection died with "Object of type function is not JSON
    serializable" — silently, since _call swallows the error and returns "".
    Unit tests against the other copy all passed.
    """
    seen = {}

    def stream_abandonable(url, payload, timeout, should_cancel):
        seen["payload"] = payload
        seen["should_cancel"] = should_cancel
        return {"cancelled": True, "partial_chars": 7}

    monkeypatch.setattr(bt._blue_llm, "stream_abandonable", stream_abandonable)

    result = bt._LM.chat([{"role": "user", "content": "reflect"}],
                         max_tokens=1900, should_cancel=lambda: True)

    assert result == {"cancelled": True, "partial_chars": 7}
    assert "should_cancel" not in seen["payload"], \
        "a python callable must never reach the request body"
    assert callable(seen["should_cancel"])
    assert seen["payload"]["max_tokens"] == 1900


def test_call_llm_carries_the_cancel_callback_through_to_the_client(monkeypatch):
    """call_llm is wrapped twice; the kwarg has to survive both layers."""
    seen = {}
    monkeypatch.setattr(
        bt._LM, "chat",
        lambda messages, **kwargs: seen.update(kwargs) or {"cancelled": True})

    result = bt.call_llm([{"role": "user", "content": "reflect"}],
                         include_tools=False, should_cancel=lambda: True)

    assert callable(seen.get("should_cancel"))
    assert result == {"cancelled": True}, \
        "a cancelled result must pass through the response polisher untouched"


# --------------------------------------------------------------------------
# What the model is offered on an ordinary turn
# --------------------------------------------------------------------------

def _tool_names(payload):
    return {t["function"]["name"] for t in (payload.get("tools") or [])}


def test_a_conversational_turn_is_offered_the_reflex_set_only(chat):
    """53 schemas re-prefill on every turn because they render after the
    system message: ~8.3k tokens to answer "I'm working on DH201"."""
    chat.ask("I'm working on DH201 right now.")

    offered = _tool_names(chat.model.main[-1])
    assert offered, "some tools must remain — the detector is not always right"
    assert offered <= bt._REFLEX_TOOL_NAMES
    assert "capture_camera" in offered, \
        "the one tool measurably wanted on a turn the selector called chat"
    assert "auto_reply_emails" not in offered


def test_a_turn_the_selector_has_an_opinion_about_still_acts(chat):
    """Trimming must not touch a turn with detected intent."""
    chat.ask("search my documents for the reading list")

    assert any(call["tool"] == "search_documents" for call in chat.executed), \
        f"the detected tool never ran: {[c['tool'] for c in chat.executed]}"
    for payload in chat.model.main:
        offered = _tool_names(payload)
        assert not (offered and offered <= bt._REFLEX_TOOL_NAMES), \
            "a turn with detected intent was handed the conversational subset"


def test_a_forced_tool_survives_reflex_scope(chat):
    """force_tool wins. The retry that turns a phantom claim into a real
    action passes through here, and must still see the tool it forces —
    send_gmail is not in the reflex set."""
    bt.call_lm_studio(
        [{"role": "user", "content": "send that email"}],
        force_tool="send_gmail", tool_scope="reflex",
    )

    payload = chat.model.main[-1]
    assert _tool_names(payload) == {"send_gmail"}
    assert payload["tool_choice"] == "required"


# --------------------------------------------------------------------------
# Turns that are answered before the model is consulted
# --------------------------------------------------------------------------
# These three paths used to be bare `return`s buried in the middle of
# process_with_tools. They now come back as `_ChatToolChoice.reply` and are
# unwrapped by the caller, so they are worth pinning: a mistake there would
# not fail loudly, it would just start calling the model.

def test_a_blocked_tool_gets_a_decline_and_never_reaches_the_house(chat):
    reply = bt.process_with_tools(
        [{"role": "user", "content": "play some music"}], user_name="Vilda")

    content = reply["choices"][0]["message"]["content"]
    assert "not something I can do here" in content
    assert chat.executed == [], "a blocked tool must not run"


def test_a_device_command_is_answered_without_asking_the_model(chat):
    reply = bt.process_with_tools(
        [{"role": "user", "content": "turn off the lights"}], user_name="Alex")

    assert any(call["tool"] == "control_lights" for call in chat.executed), \
        f"the lights tool never ran: {[c['tool'] for c in chat.executed]}"
    assert chat.model.main == [], "the zero-LLM path must not call the model"
    assert reply["choices"][0]["message"]["content"]


def test_a_bare_greeting_skips_the_pipeline(chat):
    reply = bt.process_with_tools(
        [{"role": "user", "content": "hello"}], user_name="Alex")

    assert reply["choices"][0]["message"]["content"]
    assert chat.executed == [], "a greeting must not touch the house"


# --------------------------------------------------------------------------
# Queued images reaching the model
# --------------------------------------------------------------------------
# _chat_inject_vision is 297 lines that nothing in this suite reached until
# now: it was inline in call_lm_studio, below the seam where the model is
# stubbed. These do not pin its face-recognition prose - that is the model's
# job - only that a queued image actually arrives in the user message, because
# when this path fails Blue describes a photo he was never shown.

def _one_pixel_png(path):
    path.write_bytes(base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        b"z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    return path


@pytest.fixture
def queued_camera_image(monkeypatch, tmp_path):
    """One camera capture waiting to be shown, and no lingering global state."""
    image = _one_pixel_png(tmp_path / "camera_NEW_probe.png")
    queue = bt.VisionImageQueue()
    queue.pending_images = [bt.ImageInfo(
        filename=image.name, filepath=str(image), hash="deadbeef",
        is_camera_capture=True,
        added_at=datetime.datetime.now().isoformat(), is_ambient=False)]
    monkeypatch.setattr(bt, "_vision_queue", queue)
    # every global this path writes, so the run leaves nothing behind
    monkeypatch.setattr(bt, "_recent_image_paths", [], raising=False)
    monkeypatch.setattr(bt, "_recent_image_at", 0.0, raising=False)
    monkeypatch.setattr(bt, "_last_vision_image_paths", [], raising=False)
    monkeypatch.setattr(bt, "_last_vision_recognition", {}, raising=False)
    return queue


def test_a_queued_image_is_merged_into_the_last_user_message(
        queued_camera_image):
    messages = [{"role": "system", "content": "you are blue"},
                {"role": "user", "content": "what do you see?"}]

    bt._chat_inject_vision(messages)

    content = messages[-1]["content"]
    assert isinstance(content, list), "the user turn must become multipart"
    assert "image_url" in [part.get("type") for part in content], \
        "no image part reached the model"
    assert messages[0]["content"] == "you are blue", "system turn untouched"


def test_a_shown_image_is_cleared_and_remembered(queued_camera_image):
    bt._chat_inject_vision([{"role": "user", "content": "what is this?"}])

    assert queued_camera_image.pending_images == [], "queue must be drained"
    assert bt._last_vision_image_paths, "what was shown must be recorded"
    # ...and armed for "what colour is it?" without a re-upload.
    assert bt._recent_image_paths


def test_nothing_queued_leaves_the_conversation_alone(monkeypatch):
    queue = bt.VisionImageQueue()
    queue.pending_images = []
    monkeypatch.setattr(bt, "_vision_queue", queue)
    monkeypatch.setattr(bt, "_recent_image_paths", [], raising=False)

    messages = [{"role": "user", "content": "hello"}]
    bt._chat_inject_vision(messages)

    assert messages == [{"role": "user", "content": "hello"}]


def test_an_attached_image_takes_the_non_camera_path(monkeypatch, tmp_path):
    """The path where the camera-capture branch never runs.

    Nothing in the suite covered attached images as opposed to camera frames,
    and they take a visibly different route through the injector.
    """
    image = _one_pixel_png(tmp_path / "attached.png")
    queue = bt.VisionImageQueue()
    queue.pending_images = [bt.ImageInfo(
        filename=image.name, filepath=str(image), hash="cafe",
        is_camera_capture=False,          # <- attached, not a camera frame
        added_at=datetime.datetime.now().isoformat(), is_ambient=False)]
    monkeypatch.setattr(bt, "_vision_queue", queue)
    monkeypatch.setattr(bt, "_recent_image_paths", [], raising=False)
    monkeypatch.setattr(bt, "_recent_image_at", 0.0, raising=False)
    monkeypatch.setattr(bt, "_last_vision_image_paths", [], raising=False)
    monkeypatch.setattr(bt, "_last_vision_recognition", {}, raising=False)

    messages = [{"role": "user", "content": "what is in this picture?"}]
    bt._chat_inject_vision(messages)

    assert "image_url" in [p.get("type") for p in messages[-1]["content"]]
