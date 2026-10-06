"""Every conversation on a chat page is kept, and listed down its left side.

Run with: python -m pytest test_transcripts.py

Alex asked for a transcript of all his conversations with Blue, reachable from
the left of the chat screen. The page tags each turn with the conversation it
belongs to; chat_completions keeps the finished exchange under that id; the
sidebar lists, reopens and deletes them. Untagged callers (the Ohbot client,
scripts) and the kids' iPad are not transcribed.
"""

import pytest
import requests
from flask import Flask, render_template_string

from blue import transcripts
from blue.server.pages.chat import CHAT_HTML
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

CID = "3f2b8a1c-6d0e-4b7a-9c51-0a1b2c3d4e5f"


@pytest.fixture(autouse=True)
def _transcripts_in_tmp(tmp_path, monkeypatch):
    """Never the live data/chat_transcripts.db."""
    monkeypatch.setattr(transcripts, "DB_PATH", str(tmp_path / "chat_transcripts.db"))


def tagged(text, cid=CID, attachments=()):
    return {"id": cid, "text": text, "attachments": list(attachments)}


# --------------------------------------------------------------------------
# The store
# --------------------------------------------------------------------------

def test_a_conversation_is_kept_exchange_by_exchange():
    assert transcripts.record_turn(CID, "blue", "Alex", "what is memory?", "A record.")
    assert transcripts.record_turn(CID, "blue", "Alex", "and forgetting?", "Its edit.")

    kept = transcripts.get_transcript(CID, "blue", "Alex")
    assert [(m["role"], m["text"]) for m in kept["messages"]] == [
        ("user", "what is memory?"), ("assistant", "A record."),
        ("user", "and forgetting?"), ("assistant", "Its edit."),
    ]
    listed = transcripts.list_transcripts("blue", "Alex")
    assert [(t["id"], t["title"], t["turns"]) for t in listed] == [
        (CID, "what is memory?", 2)]


def test_what_was_sent_and_what_was_shown_are_both_kept():
    """A reopened chat must continue with the document text it was given,
    while the page shows only what was typed and the file's name."""
    sent = '[Attached document: notes.txt]\n"""\nBuy milk.\n"""\n\nwhat should I buy?'
    transcripts.record_turn(CID, "blue", "Alex", sent, "Milk.",
                            shown="what should I buy?", attachments=["notes.txt"])

    user = transcripts.get_transcript(CID, "blue", "Alex")["messages"][0]
    assert user["content"] == sent
    assert user["text"] == "what should I buy?"
    assert user["attachments"] == ["notes.txt"]


def test_the_title_is_the_first_thing_said_cut_at_a_word():
    said = ("could you walk me through how the reflection queue decides "
            "which episodes are worth revisiting overnight")
    transcripts.record_turn(CID, "blue", "Alex", said, "Gladly.")
    transcripts.record_turn(CID, "blue", "Alex", "something else", "Sure.")

    title = transcripts.list_transcripts("blue", "Alex")[0]["title"]
    assert title.endswith("…")
    assert len(title) <= 61
    assert said.startswith(title[:-1])
    assert title[-2] != " "


def test_an_attachment_only_message_is_titled_by_its_file():
    transcripts.record_turn(CID, "blue", "Alex", "What do you make of this?", "A cat.",
                            shown="", attachments=["cat.jpg"])
    assert transcripts.list_transcripts("blue", "Alex")[0]["title"] == "cat.jpg"


def test_conversations_are_listed_per_robot_most_recent_first():
    transcripts.record_turn("first-conversation", "blue", "Alex", "one", "1")
    transcripts.record_turn("hexia-conversation", "hexia", "Alex", "hi Hexia", "Hi!")
    transcripts.record_turn("second-conversation", "blue", "Alex", "two", "2")
    transcripts.record_turn("first-conversation", "blue", "Alex", "one again", "1 again")

    assert [t["id"] for t in transcripts.list_transcripts("blue", "Alex")] == [
        "first-conversation", "second-conversation"]
    assert [t["id"] for t in transcripts.list_transcripts("hexia", "Alex")] == [
        "hexia-conversation"]


def test_someone_elses_conversation_is_not_shown_added_to_or_deleted():
    transcripts.record_turn(CID, "blue", "Alex", "private", "Noted.")

    assert transcripts.get_transcript(CID, "blue", "Vilda") is None
    assert transcripts.get_transcript(CID, "hexia", "Alex") is None
    assert not transcripts.record_turn(CID, "blue", "Vilda", "mine now", "No.")
    assert not transcripts.record_turn(CID, "hexia", "Alex", "mine now", "No.")
    assert not transcripts.delete_transcript(CID, "blue", "Vilda")
    assert len(transcripts.get_transcript(CID, "blue", "Alex")["messages"]) == 2


def test_unusable_ids_and_empty_exchanges_are_refused():
    for bad in ("", "short", "has spaces in it", "../../etc/passwd", "x" * 65, None, 12345678):
        assert not transcripts.record_turn(bad, "blue", "Alex", "hi", "Hello.")
    assert not transcripts.record_turn(CID, "blue", "Alex", "   ", "Hello.")
    assert not transcripts.record_turn(CID, "blue", "Alex", "hi", "")
    assert transcripts.list_transcripts("blue", "Alex") == []


def test_a_deleted_conversation_is_gone_with_its_messages():
    transcripts.record_turn(CID, "blue", "Alex", "forget this", "Done.")
    assert transcripts.delete_transcript(CID, "blue", "Alex")

    assert transcripts.get_transcript(CID, "blue", "Alex") is None
    assert transcripts.list_transcripts("blue", "Alex") == []
    # The same id starts afresh rather than inheriting the old messages.
    transcripts.record_turn(CID, "blue", "Alex", "new start", "Hello.")
    assert len(transcripts.get_transcript(CID, "blue", "Alex")["messages"]) == 2


# --------------------------------------------------------------------------
# Through the chat endpoint and the sidebar's routes
# --------------------------------------------------------------------------

def test_a_chat_page_turn_is_kept_and_listed(chat):
    chat.model.queue("Memory is a strange thing to be made of.")
    response = chat.ask("what do you make of memory?",
                        transcript=tagged("what do you make of memory?"))
    assert response.status_code == 200

    listed = chat.client.get("/chat/transcripts?robot=blue").get_json()["transcripts"]
    assert [(t["id"], t["title"]) for t in listed] == [(CID, "what do you make of memory?")]
    kept = chat.client.get(f"/chat/transcripts/{CID}?robot=blue").get_json()
    assert [(m["role"], m["text"]) for m in kept["messages"]] == [
        ("user", "what do you make of memory?"),
        ("assistant", reply_of(response)),
    ]


def test_an_attached_documents_text_is_kept_behind_what_was_typed(chat):
    """The page splices a document's text into the message it sends; the
    transcript shows what was typed and keeps the rest for continuing."""
    sent = '[Attached document: notes.txt]\n"""\nBuy milk.\n"""\n\nwhat should I buy?'
    chat.ask(sent, transcript=tagged("what should I buy?", attachments=["notes.txt"]))

    user = transcripts.get_transcript(CID, "blue", "Alex")["messages"][0]
    assert (user["content"], user["text"], user["attachments"]) == (
        sent, "what should I buy?", ["notes.txt"])


def test_the_kept_reply_is_the_one_the_page_was_sent(chat):
    """The guards rewrite replies after the model finishes; the transcript
    holds what Blue actually said, leaked reasoning and all removed."""
    chat.model.queue("He wants it short.\n</think>\n\nMemory is a strange thing.")
    response = chat.ask("what do you make of memory?", transcript=tagged("memory?"))

    kept = transcripts.get_transcript(CID, "blue", "Alex")
    assert kept["messages"][-1]["content"] == reply_of(response) == "Memory is a strange thing."


def test_a_continued_conversation_keeps_only_the_new_exchange(chat):
    """The page resends the whole thread each turn; only its last user
    message is this turn's."""
    chat.model.queue("First answer.", "Second answer.")
    chat.ask("first question", transcript=tagged("first question"))
    thread = [
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "First answer."},
        {"role": "user", "content": "second question"},
    ]
    chat.client.post("/v1/chat/completions", json={
        "messages": thread, "robot": "blue", "transcript": tagged("second question")})

    kept = transcripts.get_transcript(CID, "blue", "Alex")
    assert [m["text"] for m in kept["messages"] if m["role"] == "user"] == [
        "first question", "second question"]


def test_an_untagged_caller_is_not_transcribed(chat):
    """The Ohbot client and scripts post without a conversation id."""
    chat.ask("what do you make of memory?")
    assert transcripts.list_transcripts("blue", "Alex") == []


def test_a_failed_turn_is_not_kept(chat):
    """The page drops a failed turn from its thread; the transcript, which a
    reopened chat continues from, must not keep it either."""
    failure = requests.models.Response()
    failure.status_code = 400
    failure._content = b'{"error":"No models loaded."}'
    chat.model.queue(requests.HTTPError("400 Client Error", response=failure))
    response = chat.ask("hello", transcript=tagged("hello"))

    assert response.get_json().get("blue_error")
    assert transcripts.list_transcripts("blue", "Alex") == []


def test_the_kids_ipad_is_not_transcribed_and_cannot_list(chat):
    ipad = {"X-Blue-Device": "ipad"}
    chat.client.post("/v1/chat/completions", headers=ipad, json={
        "messages": [{"role": "user", "content": "hi Blue"}],
        "robot": "blue", "transcript": tagged("hi Blue")})

    assert transcripts.list_transcripts("blue", "Vilda") == []
    assert chat.client.get("/chat/transcripts?robot=blue", headers=ipad).status_code == 403
    assert chat.client.get(f"/chat/transcripts/{CID}?robot=blue", headers=ipad).status_code == 403


def test_a_conversation_can_be_deleted_from_the_sidebar(chat):
    chat.ask("remember nothing of this", transcript=tagged("remember nothing of this"))

    assert chat.client.delete(f"/chat/transcripts/{CID}?robot=blue").get_json() == {"deleted": True}
    assert chat.client.get(f"/chat/transcripts/{CID}?robot=blue").status_code == 404
    assert chat.client.delete(f"/chat/transcripts/{CID}?robot=blue").status_code == 404


def test_another_robots_page_does_not_see_blues_conversations(chat):
    chat.ask("just between us", transcript=tagged("just between us"))

    assert chat.client.get("/chat/transcripts?robot=hexia").get_json()["transcripts"] == []
    assert chat.client.get(f"/chat/transcripts/{CID}?robot=hexia").status_code == 404


# --------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------

def render(kid):
    app = Flask("transcripts-test")
    with app.app_context():
        return render_template_string(
            CHAT_HTML, kid=kid, hf_sens=5, robot_name="Blue", continuity_href="",
            robot_json='{"id":"blue","name":"Blue","head":"blue","accent":"#3da9fc"}',
        )


def test_the_chat_page_lists_conversations_down_the_left():
    page = render(kid=False)
    assert '<body class="has-history">' in page
    assert 'id="history"' in page and 'id="histNew"' in page
    assert "transcript: transcriptTag" in page, "turns are not tagged with their conversation"


def test_the_kid_page_has_no_list_and_tags_nothing():
    page = render(kid=True)
    assert '<body class="kid">' in page
    assert 'id="history"' not in page
    # With no list on the page, historyOn stays false and no tag is sent.
    assert "let historyOn = !!historyEl;" in page
