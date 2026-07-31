"""Regression tests for the guards that keep intent detection off non-command text.

Run with: python -m pytest test_intent_guards.py

Two failures from 2026-07-31, both from detectors reading text that was never
an instruction:

1. Alex pasted 5756 characters of Blue's own meeting notes into the chat. The
   document's closing line ("allows you to present yourself as a strategic
   partner") matched the self-introduction detector, and "students gain
   technical skills in prompt engineering" supplied a venue. Blue answered
   "Hello everyone at prompt engineering."
2. Asked "can you remind me of those ideas?", the calendar detector saw the
   substring "remind me " and forced create_reminder at 0.92 confidence. The
   model then invented the arguments, and a reminder describing four ideas that
   never existed was written to the database.
"""

import pytest

from blue.tool_selector.detectors.calendar import (
    CalendarDetector, is_reminder_recall_request,
)
from blue.utils import PASTED_BLOCK_MIN_CHARS, strip_pasted_block

# A pasted document in the shape that caused the bug: framing words, then
# markdown structure, then a closing line about the READER presenting himself.
PASTED_DOC = (
    "these were your ideas As requested, here are the four ideas for your "
    "meeting with Sarah Matthews at Laurier.\n\n"
    "### 1. \"Blue\" as a Pedagogical Prototype\n\n"
    "**Core Concept:**\nPropose that Laurier adopt a campus-hosted model.\n\n"
    "*   **Skill Building:** Students gain technical skills in prompt "
    "engineering, fine-tuning, and evaluation.\n\n"
    "### 2. The AI Autonomy Spectrum\n\n"
    "**Core Concept:**\nIntroduce your framework to help Laurier evaluate its "
    "strategy along a spectrum of autonomy versus dependence.\n\n"
    "*   **Low Autonomy:** Commercial APIs where data leaves the campus, "
    "models are proprietary, and outcomes cannot be audited.\n"
    "*   **High Autonomy:** Open-source models hosted on-premise, allowing "
    "full control over data, fine-tuning and ethical guardrails.\n\n"
    "### 3. Curriculum Integration as a Living Lab\n\n"
    "**Core Concept:**\nStudents build and fine-tune local agents for campus "
    "needs rather than only studying them in the abstract.\n\n"
    "**Actionable Step:**\nCollaborate with IT Services on a sandbox where "
    "students can experiment with local models safely.\n\n"
    "This framework allows you to present yourself not just as a faculty "
    "member, but as a strategic partner in Laurier's future AI policy.\n"
)


def test_the_pasted_document_is_long_enough_to_trigger_the_guard():
    """Guard the guard: if this fixture shrinks below the threshold the tests
    below would pass for the wrong reason."""
    assert len(PASTED_DOC) >= PASTED_BLOCK_MIN_CHARS


def test_paste_keeps_the_users_framing_words():
    assert strip_pasted_block(PASTED_DOC).startswith("these were your ideas")


def test_paste_drops_the_document_body():
    out = strip_pasted_block(PASTED_DOC)
    assert "prompt engineering" not in out
    assert "present yourself" not in out


def test_short_messages_pass_through_untouched():
    for msg in ("Can you remind me of those ideas?", "Turn off all the lights.",
                "", "Hey Blue, how are you doing today?"):
        assert strip_pasted_block(msg) == msg


def test_long_unstructured_prose_passes_through_untouched():
    """Someone typing at length is not pasting a document."""
    essay = ("I have been thinking about how the course should be organised "
             "and I want to talk it through with you before I commit to it. ") * 12
    assert len(essay) >= PASTED_BLOCK_MIN_CHARS
    assert strip_pasted_block(essay) == essay


def test_a_trailing_question_after_a_paste_is_kept():
    out = strip_pasted_block(PASTED_DOC + "\nWhat do you make of these?\n")
    assert "What do you make of these?" in out


def test_a_bare_paste_with_no_framing_yields_no_intent():
    """"Here, look at this" with nothing else is not a command."""
    body = PASTED_DOC[PASTED_DOC.index("### 1."):]
    assert strip_pasted_block(body) == ""


# ---- "remind me" recall vs schedule -----------------------------------------

RECALL = [
    "can you remind me of those ideas?",
    "remind me what those ideas were",
    "remind me who sarah matthews is",
    "remind me about what we discussed",
    "remind me why we picked that one",
]

SCHEDULE = [
    "remind me to call sarah",
    "remind me to pick up the girls at 5pm",
    "remind me about the dentist tomorrow at 3",
    "set a reminder for the meeting on monday",
    "remind me about the meeting next week",
    "don't let me forget the dance recital tonight",
]


@pytest.mark.parametrize("msg", RECALL)
def test_recall_phrasing_is_not_a_scheduling_request(msg):
    assert is_reminder_recall_request(msg)
    assert CalendarDetector()._detect_create_event(msg) is None


@pytest.mark.parametrize("msg", SCHEDULE)
def test_scheduling_requests_still_create_reminders(msg):
    assert not is_reminder_recall_request(msg)
    intent = CalendarDetector()._detect_create_event(msg)
    assert intent is not None and intent.tool_name == "create_reminder"
