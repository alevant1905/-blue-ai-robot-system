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
