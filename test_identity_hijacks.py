"""Identity templates must answer the question actually asked.

Run with: python -m pytest test_identity_hijacks.py

From the 2026-09-23 log audit. In front of Alex's class, "what are you seeing
in front of you right now?" was classified as an identity question, so the
camera's description failed the identity check and was replaced by "I'm Blue.
I have a persistent self-model…". "what is your J-Space? What does that mean?"
forced the JavaScript calculator (the hyphen counted as a minus sign) and got
"Yes. My J-space is…". "describe yourself in light of Ilyenkov's texts" got a
general self-introduction, twice.
"""

import pytest

from blue_identity import (
    canonical_identity_reply,
    contextual_identity_request_kind,
    identity_repetition_kind,
    identity_request_kind,
    identity_response_problem,
    strip_drifted_sentences,
)


@pytest.mark.parametrize("message", [
    "what are you seeing in front of your head now?",
    "what are you seeing in front of you right now?",
    "I'm well. What do you mean what are you referring to in relation to the "
    "Nauri banter? Is it completed social event on your mind?",
    "Say nori what are you munching on.",
    "Who are you looking at right now.",
    "walk me through your development of the syllabus",
    "what's your development plan for the course?",
    "how did you develop that idea?",
    "start the song from the beginning",
    "can you read me the syllabus from the beginning?",
])
def test_questions_about_something_else_are_not_identity_questions(message):
    assert identity_request_kind(message) is None


@pytest.mark.parametrize("message", [
    "what are you, really?",
    "so what are you, Blue?",
    "If you're more than just code running on a server what are you what is "
    "that more.",
    "if you're not neutral, what are you",
    "Who are you blue really?",
    "What are yuo?",
    "what are you made of?",
])
def test_what_are_you_still_asks_what_blue_is(message):
    assert identity_request_kind(message) == "identity"


@pytest.mark.parametrize("message", [
    "can you describe your own developmental history",
    "describe your journey from the beginning to who you are today",
])
def test_developmental_history_is_an_evolution_question(message):
    assert identity_request_kind(message) == "evolution"


def test_remembering_your_beginning_is_still_origin():
    assert identity_request_kind(
        "Do you remember your existence from the beginning?") == "origin"


def test_an_attachment_is_not_the_previous_identity_question():
    """The raw turn holds the attachment; the caller classifies only the
    user's words. The pasted 'Who are you?' must not count as the question
    'tell me more' follows up."""
    messages = [
        {"role": "user", "content": "what's the weather?"},
        {"role": "assistant", "content": "Sunny."},
        {"role": "user",
         "content": '[Attached document: a.pdf]\n"""Who are you?"""\n\ntell me more'},
    ]
    assert contextual_identity_request_kind("tell me more", messages) is None


def test_the_jspace_template_does_not_open_with_yes():
    reply = canonical_identity_reply("Blue", "Alex's robot companion", "jspace")
    assert reply.startswith("My J-space")


def test_topic_overlap_and_sentence_replay_are_told_apart():
    previous = ["I'm Blue, Alex's robot companion. My J-space carries focus, "
                "beliefs and remembered episodes, and I run on local hardware."]
    replay = previous[0]
    paraphrase = ("I'm Blue. What persists between our conversations is my "
                  "J-space, and my language work happens on a local machine.")
    assert identity_repetition_kind(replay, previous, "identity") == "sentences"
    assert identity_repetition_kind(paraphrase, previous, "identity") == "topics"


def test_one_false_sentence_is_dropped_and_the_framing_kept():
    reply = ("I'm Blue, Alex's robot companion. In Ilyenkov's terms I'm less a "
             "thing than a node of shared activity. I don't have a physical "
             "body. The Ohbot head Alex built gives that activity a face.")

    def sentence_broken(s):
        return identity_response_problem(
            s, "Blue", ["Hexia", "Casper"], request_kind="identity",
            completeness=False)

    salvaged = strip_drifted_sentences(
        reply, sentence_broken, max_dropped=1,
        whole_is_broken=lambda t: identity_response_problem(
            t, "Blue", ["Hexia", "Casper"], request_kind="identity"))
    assert salvaged is not None
    assert "Ilyenkov" in salvaged
    assert "don't have a physical body" not in salvaged


def test_salvage_gives_up_when_more_than_one_sentence_is_false():
    reply = ("I don't have a physical body. I have no creator. "
             "I'm Blue, and I like Ilyenkov.")
    assert strip_drifted_sentences(
        reply,
        lambda s: identity_response_problem(
            s, "Blue", [], request_kind="identity", completeness=False),
        max_dropped=1) is None


def test_completeness_is_still_required_of_a_whole_answer():
    assert identity_response_problem(
        "Hello everyone.", "Blue", [], request_kind="introduction") == "missing_name"
    assert identity_response_problem(
        "Hello everyone.", "Blue", [], request_kind="introduction",
        completeness=False) is None


def test_the_calculator_needs_real_arithmetic():
    from blue.tool_selector import ImprovedToolSelector
    selector = ImprovedToolSelector()

    def tool(message):
        primary = selector.select_tool(message, []).primary_tool
        return primary.tool_name if primary else None

    assert tool("what is your J-Space? What does that mean?") is None
    assert tool("what is your self-model?") is None
    assert tool("What is felix's e-mail.") != "run_javascript"
    assert tool("what is sometimes called the singularity") != "run_javascript"
    assert tool("what is 12 - 5") == "run_javascript"
    assert tool("what is 7 times 6") == "run_javascript"
