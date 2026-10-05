"""Regression tests for the reply-text helpers used when quoting Blue.

Run with: python -m pytest test_reply_text.py

Blue's past replies are quoted back to him in the memory blocks, and what a
quote carries he says again: block citations ("[known_facts]"), self-talk
paragraphs ("Wait, I should also check…", the 99,666-char 2026-09-23 runaway)
and closing menus ("…, or are we calling it a night completely?").
"""

import os
import subprocess
import sys

import pytest

import blue.utils
from blue_reply_text import (
    _EMOJI_RE,
    cut_self_talk,
    is_runaway_text,
    quotable_reply,
    reads_as_deliberation,
    strip_block_citations,
    strip_closing_asks,
    strip_reasoning_tags,
)

# run1 camera_face[2] (2026-09-25 harness): one real answer, then a reminder
# nobody asked for and "Wait, I should also check…".
CAMERA_FACE_RAMBLE = (
    "I have noted her name and role, but to recognize her face automatically "
    "in the future, I need a clear reference photo of Clover. You can upload "
    "that to my Visual Memory page, and then I’ll be able to identify her "
    "when she’s in view.\n\n"
    "Until then, I’ll remember her as the student in the bread-bun hat and "
    "strawberry skirt for this session. It was fun meeting her! Do you want me "
    "to keep an eye out for any other specific people in your classes?\n\n"
    "Also, just a reminder, your DH201 lecture is starting now. I'll stay "
    "quiet unless you need anything else. How is the class going so far?\n\n"
    "Wait, I should also check if there are any other specific TAs or staff "
    "you'd like me to recognize for your CS101 course.\n\n"
    "Let me know what you need! And don't worry about the \"bread-bun\" "
    "detail—it's very memorable.\n\n"
    "One more thing: since we are talking about classes, I just wanted to "
    "confirm that DH201 is the one meeting today at 10am in SB216."
)


# --- block citations ---------------------------------------------------------

@pytest.mark.parametrize("cited, clean", [
    ("You told me you grew up in Scarborough [known_facts].",
     "You told me you grew up in Scarborough."),
    ("Nori is a lab mix [known_facts, known_facts].", "Nori is a lab mix."),
    ("You asked me to keep that in mind [long_term_notes].",
     "You asked me to keep that in mind."),
    ("It came up on Wednesday [<conversation_memory>; j_space].",
     "It came up on Wednesday."),
])
def test_block_citations_are_removed(cited, clean):
    assert strip_block_citations(cited) == clean


@pytest.mark.parametrize("text", [
    "The schedule is in the syllabus [DH399_AL_2026F.docx].",
    "Doctorow calls this a reverse centaur [1].",
    "The piece ran last week [theguardian.com].",
    "Start with the history, see [Chapter 1, pp. 1-20].",
])
def test_other_brackets_are_left_alone(text):
    assert strip_block_citations(text) == text


# --- self-talk ---------------------------------------------------------------

def test_the_camera_face_ramble_is_cut_to_its_answer():
    out = cut_self_talk(CAMERA_FACE_RAMBLE)
    paragraphs = CAMERA_FACE_RAMBLE.split("\n\n")
    assert out == "\n\n".join(paragraphs[:2])
    assert "Wait, I should" not in out


def test_a_one_paragraph_reply_is_never_cut():
    reply = "Wait, I should check the calendar first — it says DH399 at 11:30."
    assert cut_self_talk(reply) == reply
    assert cut_self_talk(reply, live=False) == reply


def test_paragraphs_inside_a_code_fence_are_untouched():
    reply = (
        "Here is the dialogue for the demo script:\n\n"
        "```\nROBOT: Hello.\n\nWait, I should introduce myself first.\n```\n\n"
        "Paste it into the slide notes."
    )
    assert cut_self_talk(reply) == reply


def test_a_teaching_opener_is_cut_only_when_quoting_from_memory():
    reply = (
        "A lab budget has three parts: hardware, licences and staff time.\n\n"
        "Let's assume a room of twenty workstations at $2,000 each."
    )
    assert cut_self_talk(reply) == reply
    assert cut_self_talk(reply, live=False) == (
        "A lab budget has three parts: hardware, licences and staff time.")


# --- leaked reasoning --------------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("<think>Alex wants a time.</think>\n\nWhat time works?", "What time works?"),
    # The 10-05 shape: no opening tag, several closing ones. Only the text
    # after the LAST one is the reply.
    ("Sure — what time?\n</think>\n\nHmm, one question.\n</think>\n\n"
     "What time should I remind you?", "What time should I remind you?"),
    ("Here you go.<think>", "Here you go."),
    ("All reasoning, nothing after.</think>", ""),
    ("Mixed </THINK> case.", "case."),
])
def test_reasoning_before_the_last_close_tag_is_dropped(raw, clean):
    assert strip_reasoning_tags(raw) == clean


@pytest.mark.parametrize("text", [
    "  A reply with no tags, spaces kept.  ",
    "We think about this a lot.",
    "",
    None,
])
def test_text_without_tags_is_returned_as_is(text):
    assert strip_reasoning_tags(text) is text


# --- deliberation (forced-call words only) -----------------------------------

@pytest.mark.parametrize("text", [
    # reminder_variants[0], 2026-10-05: excerpts of the forced call's words.
    "Sure — what time should I remind you?\n\nActually, let me just ask the one "
    "thing I need.\n\nHmm, that's two questions. Let me clean this up.",
    "**Final answer:**\nWhat time should I remind you to call the dentist?",
    "...I keep second-guessing. The instruction is: ask at most one question.",
    "Sending it now for real this time.",
    "One simple question is cleanest.\n</think>\n\nWhen would you like it?",
    # conversation_log 10048, 2026-09-27.
    "That's a clean, bounded use case.\n\nWait — you mentioned sending the "
    "newsfeed by email to yourself.",
    "So my honest read: it works. Actually, I shouldn't assume — you asked me "
    "about structure.",
])
def test_a_forced_call_arguing_with_itself_is_deliberation(text):
    assert reads_as_deliberation(text)


@pytest.mark.parametrize("text", [
    "What time should I remind you to call the dentist?",
    "No, I haven't saved that yet — what's Athena's age?",
    "I can't send that without an address. Who should it go to?",
    "A daily digest is a nicely bounded job for it.",
    "",
])
def test_a_plain_short_answer_is_not_deliberation(text):
    assert not reads_as_deliberation(text)


# --- closing asks ------------------------------------------------------------

@pytest.mark.parametrize("reply, quoted", [
    ("That sounds like a hard-won victory. Do you want me to dim the hallway "
     "lights for your walk to the bathroom later, or are we calling it a night "
     "completely?",
     "That sounds like a hard-won victory."),
    ("Glad you liked it! Want to hear another one, or is there something else "
     "on your mind today? 😊",
     "Glad you liked it!"),
    ("Nori seems settled. I could also dim the living room lights so she "
     "stays asleep.",
     "Nori seems settled."),
])
def test_offers_and_menus_are_dropped_from_the_quote(reply, quoted):
    assert strip_closing_asks(reply) == quoted


def test_a_numbered_question_list_is_kept():
    reply = (
        "Three questions for Thursday's discussion:\n"
        "1. What does Toscano mean by an agent?\n"
        "2. Do you want your tools to decide for you?\n"
        "3. What do you think is lost when a lab runs locally?"
    )
    assert strip_closing_asks(reply) == reply


def test_list_items_survive_a_dropped_closer():
    assert strip_closing_asks("Ideas:\n- A.\n- B.\n\nWant me to draft one?") == (
        "Ideas:\n- A.\n- B.")


def test_a_reply_that_is_all_ask_is_returned_whole():
    assert strip_closing_asks("Want me to play it?") == "Want me to play it?"


def test_a_mid_reply_question_is_kept():
    assert strip_closing_asks("What makes it so great? I wondered.") == (
        "What makes it so great? I wondered.")


def test_the_skeleton_joke_survives():
    """Documents that this is not the recycled-joke fix: the joke is content."""
    joke = "Why don't skeletons fight each other?\n\nThey don't have the guts! 😄"
    assert strip_closing_asks(joke) == (
        "Why don't skeletons fight each other?\n\nThey don't have the guts!")


def test_one_short_closing_question_to_the_listener_goes():
    reply = ("Weekly labs suit DH201 better than a single project. "
             "Does that match what you had in mind?")
    assert strip_closing_asks(reply) == (
        "Weekly labs suit DH201 better than a single project.")


def test_the_emoji_pattern_is_shared_with_the_filler_stripper():
    assert blue.utils._EMOJI_RE is _EMOJI_RE


# --- whole-reply checks ------------------------------------------------------

def test_a_looping_reply_is_runaway():
    loop = (
        "\n\nOne more thing: since we are talking about classes, I just wanted "
        "to confirm that this is the lecture we're in right now, correct?"
        "\n\nAlso, if you have any specific goals for today's lecture, I can "
        "help keep notes or summarize key points if you'd like."
    )
    runaway = "I have noted her name and role." + loop * 100
    assert len(runaway) > 20000
    assert is_runaway_text(runaway)
    # Short enough to pass the length test: caught by the verbatim-loop cut.
    looping = "Clover is a TA for CS101.\n\n" + (
        "Also, she runs the Tuesday tutorial and marks the weekly reflections "
        "for every section of the course this term. ") * 6
    assert len(looping) < 8000
    assert is_runaway_text(looping)


def test_a_hedged_list_answer_is_not_runaway():
    reply = (
        "Since I don't have the specific handout for AI Lab 2, I'm drawing on "
        "what's standard for a first agent lab.\n\n"
        "1. Install a local model and run one prompt.\n"
        "2. Give it one tool, like a calculator.\n"
        "3. Log every step it takes and compare runs."
    )
    assert not is_runaway_text(reply)


@pytest.mark.parametrize("reply", [
    "A lab budget has three parts: hardware, licences and staff time.\n\n"
    "Let's assume a room of twenty workstations at $2,000 each.",
    "Two options for week 3: Toscano on agents, or Noble on search.\n\n"
    "I'll go with Toscano for week 3, since it sets up the agent lab.",
])
def test_a_teaching_opener_does_not_make_a_reply_runaway(reply):
    """Runaway drops the whole row from recall; the opener only trims a quote.

    "what was that lab budget you worked out?" needs this reply as a source.
    """
    assert not is_runaway_text(reply)
    assert quotable_reply(reply) == reply.split("\n\n")[0]


def test_the_runaway_check_does_not_import_the_blue_package():
    """An offline script must not start the live memory system.

    `import blue.server.runaway` runs blue/__init__ -> blue.memory, which
    opens the real ChromaDB through the data junction. The child process
    refuses any blue.* import, so a regression fails here instead of doing
    that.
    """
    script = (
        "import sys\n"
        "tried = []\n"
        "class NoBlue:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'blue' or name.startswith('blue.'):\n"
        "            tried.append(name)\n"
        "            raise ImportError('blocked: ' + name)\n"
        "sys.meta_path.insert(0, NoBlue())\n"
        "from blue_reply_text import is_runaway_text\n"
        "looping = 'Clover is a TA.\\n\\n' + ('Also, she runs the Tuesday "
        "tutorial and marks the weekly reflections for every section. ') * 8\n"
        "assert is_runaway_text(looping), tried\n"
        "assert not is_runaway_text('Clover is a TA for CS101.')\n"
        "assert not tried, tried\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr


def test_quotable_reply_applies_all_three():
    reply = (
        "Clover is a TA for CS101 [known_facts]. Want me to remember that?"
        "\n\nWait, I should also check the DH201 roster."
    )
    assert quotable_reply(reply) == "Clover is a TA for CS101."
