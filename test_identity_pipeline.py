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


def test_a_check_in_is_offered_what_happened_not_the_work_queue(
        chat, monkeypatch):
    """10110, 2026-10-06: "how are you" was pinned "If it fits naturally,
    you may mention what you've been turning over lately…: Awaiting Alex's
    final feedback on the completed DH399 reading report or the next
    academic task" (FOCUS 11 minutes old), and Blue answered "…wondering if
    there's anything else you'd like to tackle next"."""
    from datetime import datetime, timezone

    import bluetools as bt

    real = bt._continuity_routes.HUB["blue"]
    asked = {}

    class Store:
        def __getattr__(self, name):
            return getattr(real.store, name)

        def get_workspace(self):
            return {
                "workspace": (
                    "IDENTITY: I am Blue.\nFOCUS: Awaiting Alex's final "
                    "feedback on the completed DH399 reading report or the "
                    "next academic task.\nNEXT EXPECTATION: Alex will reply."),
                "updated": datetime.now(timezone.utc).isoformat(),
            }

    class Hub:
        store = Store()

        def __getattr__(self, name):
            return getattr(real, name)

        def lately_line(self, user_name, live_thread=(), in_class=False):
            asked["who"] = user_name
            asked["in_class"] = in_class
            return ("yesterday, you did a comedic banter set with Casper on "
                    "'AI Lab 3'")

    monkeypatch.setitem(bt._continuity_routes.HUB, "blue", Hub())
    chat.model.queue("Pretty good. Still grinning about Casper's set. You?")
    response = chat.ask("how are you")

    note = chat.model.payloads[0]["messages"][-1]["content"]
    assert "Answer this social check-in" in note
    assert "Awaiting Alex's final feedback" not in note
    assert "next academic task" not in note
    assert ("something that really happened to you lately, in your own plain "
            "words, never quoted: yesterday, you did a comedic banter set with "
            "Casper on 'AI Lab 3'.") in note
    assert asked["who"] == "Alex" and asked["in_class"] is False
    assert reply_of(response).startswith("Pretty good.")


def _queue_focus_hub(monkeypatch, lately, asked):
    from datetime import datetime, timezone

    import bluetools as bt

    real = bt._continuity_routes.HUB["blue"]

    class Store:
        def __getattr__(self, name):
            return getattr(real.store, name)

        def get_workspace(self):
            return {
                "workspace": (
                    "IDENTITY: I am Blue.\nFOCUS: Maintaining presence during "
                    "Alex's repeated checks; awaiting the next specific "
                    "instruction.\nNEXT EXPECTATION: Alex will reply."),
                "updated": datetime.now(timezone.utc).isoformat(),
            }

    class Hub:
        store = Store()

        def __getattr__(self, name):
            return getattr(real, name)

        def lately_line(self, user_name, live_thread=(), in_class=False):
            asked["in_class"] = in_class
            return "" if in_class else lately

    monkeypatch.setitem(bt._continuity_routes.HUB, "blue", Hub())


def test_a_check_in_with_nothing_lately_gets_a_thought_of_his_own(
        chat, monkeypatch):
    """10094 (10-01): the queue FOCUS dropped and nothing lately left the
    check-in with no take of his own (S5 review)."""
    asked = {}
    _queue_focus_hub(monkeypatch, "", asked)
    chat.model.queue("Good. Still chewing on the Reigeluth chapter. You?")
    chat.ask("how are you doing?")

    note = chat.model.payloads[0]["messages"][-1]["content"]
    assert "awaiting the next specific instruction" not in note
    assert ("you may add a thought of your own about something you and Alex "
            "have talked about lately") in note
    assert asked["in_class"] is False


def test_a_check_in_in_front_of_the_class_offers_nothing_private(
        chat, monkeypatch):
    """9855 "how was your day going today?" (09-16 09:34) came right after
    "we are in DH21 right now" and three introductions to the class."""
    asked = {}
    _queue_focus_hub(
        monkeypatch, "18 hours ago, you talked with Alex about this: 'that "
        "means i may have a chance to apply for a permanent position'", asked)
    chat.model.queue("Doing well, and happy to be here with all of you.")
    chat.ask("how was your day going today?", messages=[
        {"role": "user", "content": "I want you to introduce yourself to the class."},
        {"role": "assistant", "content": "Hi everyone, I'm Blue, Alex's robot."},
        {"role": "user", "content": "how was your day going today?"},
    ])

    note = chat.model.payloads[0]["messages"][-1]["content"]
    assert asked["in_class"] is True
    assert "permanent position" not in note
    assert "thought of your own" not in note
