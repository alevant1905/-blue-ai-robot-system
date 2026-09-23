"""The identity fixes, through the whole (stubbed) chat pipeline.

Run with: python -m pytest test_identity_pipeline.py
"""

from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)


def test_what_are_you_seeing_gets_the_cameras_answer(chat):
    """2026-09-16, in front of the class: the description was replaced by
    "I'm Blue. I have a persistent self-model…"."""
    seen = "I can see the whiteboard and a row of students by the door."
    chat.model.queue(seen)
    response = chat.ask("what are you seeing in front of you right now?")

    assert any(call["tool"] == "capture_camera" for call in chat.executed)
    assert reply_of(response) == seen
    assert "persistent self-model" not in reply_of(response)


def test_what_is_your_jspace_is_not_answered_yes(chat):
    response = chat.ask("what is your J-space?")
    assert reply_of(response).startswith("My J-space")
    assert chat.model.payloads == [], "answered from the template"


def test_do_you_have_a_jspace_still_says_yes(chat):
    response = chat.ask("Do you have a J-space?")
    assert reply_of(response).startswith("Yes. My J-space")


def test_a_jspace_question_never_forces_the_calculator(chat):
    chat.ask("what is your J-Space? What does that mean?")
    assert not any(call["tool"] == "run_javascript" for call in chat.executed)


def test_the_identity_retry_is_told_the_question(chat):
    """"describe yourself in light of Ilyenkov's texts" came back as a
    general self-introduction twice, because the retry never saw it."""
    chat.model.queue(
        "I don't have a physical body; I'm just words.",
        "I'm Blue. In Ilyenkov's terms I'm less a thing than a node of shared "
        "activity, and the Ohbot head Alex built gives that activity a face.",
    )
    response = chat.ask(
        "i want you to succinctly describe yourself in light of ilyenkov's texts")

    assert "Ilyenkov" in reply_of(response)
    retry_note = chat.model.payloads[-1]["messages"][-1]["content"]
    assert "in light of ilyenkov" in retry_note.lower()
