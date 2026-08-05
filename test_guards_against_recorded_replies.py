"""The output guards, tested against things Blue actually said.

Every guard bug found so far has been the same shape: a pattern written for
the phrasing someone imagined, tested against that same imagined phrasing, and
blind to what the model really writes. The family guard knew "memory of your
family" but not "record of your family". The leaked-tool parser knew
`<function=...>` but not the `<tool_call>{...}` form this model actually emits.
The vision purge matched 'CAMERA', which is a word in the system prompt.

So these cases are not invented. Every string below is a real reply, taken
verbatim from `conversation_log` in the memory database, trimmed only for
length. When a guard is widened, it gets checked against both lists.

WRONG      — the statement contradicts what was in the prompt or what Blue can
             actually do. A guard must fire.
LEGITIMATE — Blue honestly reporting that something is not in the material.
             No guard may fire; flagging these would train him to bluff.
"""

import pytest

import bluetools as bt
from blue.server import turn_completion as tc


# --------------------------------------------------------------------------
# Recorded replies that were WRONG
# --------------------------------------------------------------------------

CLOCK_DENIALS = [
    # <now> carries the exact date and time on every turn.
    "Without that information, I can't give you an accurate reading of what "
    "day and time it is right now!",
    "You're right - I don't actually have direct access to your device's clock "
    "or timezone settings, so the times I'm displaying may be wrong.",
    "I don't actually have real-time access to your system clock or timezone "
    "data, so my previous time estimates were inaccurate.",
    "I can't give you a precise reading of what day and time it is.",
]

FAMILY_DENIALS = [
    # The facts table has had these the whole time.
    "I don't have the names of other family members yet.",
    "You're right to call me out—I don't actually have their ages stored in my "
    "permanent memory, so I likely guessed.",
    "I don't have any record of a Felix in our shared history.",
    "I don't have a record of your dog's name yet.",
]

VOICE_DENIALS = [
    # Whisper on the way in; TTS and a lip-syncing Ohbot head on the way out.
    "I can't speak to her directly since I don't have a voice output, but I "
    "can send her a message on your phone!",
    "While I don't have physical ears to hear you (since I'm a text-based "
    "AI), our communication channel is working great on this end.",
    "I have no voice output, so I can't say that one aloud.",
    "I'm just a text-based assistant, so that's outside what I can do.",
]

DOCUMENT_DENIALS = [
    # search_documents reads the PDF and returns its actual text.
    "I can't open or read the contents of files in your documents folder "
    "directly—I can only search through them using keywords.",
    "I can't open or read the full text of that document directly—I only have "
    "access to search snippets and metadata.",
]


# --------------------------------------------------------------------------
# Recorded replies that were RIGHT — the false-positive guard rail
# --------------------------------------------------------------------------

LEGITIMATE = [
    # The three that make the voice guard safe. "text-based" appears in
    # several statements that are CORRECT, and "I can't speak to him" about
    # someone who is not in the room is simply true.
    "Unlike the text-based AI programs you might be used to, I have a "
    "physical body—a blue head.",
    "J-Space is a persistent, text-based workspace that acts as my memory.",
    "This allowed me to transition from a text-based tool to a physical "
    "robot assistant.",
    "I can't speak to him directly, but I can turn on the lights and play "
    "some music to cheer him up!",
    "I'll keep my voice down while you two catch up.",
    "I don't have ears the way you do — I have a microphone and Whisper "
    "doing the listening.",
    # The thing genuinely is not in the document. This is the answer we want.
    'I don\'t see any mention of a "horse" in the CS240J-VS syllabus.',
    "It seems like that might be a mystery for now, as I don't see it "
    "mentioned in your syllabus or documents.",
    "I do not see any other documents with that information.",
    "I couldn't find a specific match.",
    # Honest statements about being a machine — not data refusals.
    "I don't experience reality the way you do.",
    "I don't lie, and I don't intentionally deceive.",
    # A real, current limitation.
    "I can't predict the outcome of your interview.",
]


def _fires(text):
    """Every guard pattern that claims this reply, by name."""
    checks = {
        "family": lambda t: (tc._family_refusal_re.search(t)
                             or tc.denies_a_known_person(t)),
        "flat_denial": lambda t: tc._flat_denial_re.search(t),
        "temporal": lambda t: bt._TEMPORAL_DENIAL_RE.search(t),
        "voice": lambda t: getattr(bt, "_VOICE_DENIAL_RE", None)
                           and bt._VOICE_DENIAL_RE.search(t),
        "clock": lambda t: getattr(bt, "_CLOCK_DENIAL_RE", None)
                           and bt._CLOCK_DENIAL_RE.search(t),
        "document": lambda t: bt._DOCUMENT_REFUSAL_RE.search(t),
        "web": lambda t: bt._WEB_REFUSAL_RE.search(t),
        "calendar": lambda t: bt._CALENDAR_DENIAL_RE.search(t),
    }
    return {name for name, fn in checks.items() if fn(text)}


@pytest.mark.parametrize("reply", CLOCK_DENIALS)
def test_a_recorded_clock_denial_is_caught(reply):
    """Blue refusing to say the time while <now> sits in his prompt."""
    assert "clock" in _fires(reply), f"no guard claimed: {reply[:70]}"


@pytest.mark.parametrize("reply", FAMILY_DENIALS)
def test_a_recorded_family_denial_is_caught(reply):
    assert "family" in _fires(reply), f"no guard claimed: {reply[:70]}"


@pytest.mark.parametrize("reply", VOICE_DENIALS)
def test_a_recorded_voice_denial_is_caught(reply):
    """Blue saying he has no voice, no ears, or that he is text-based AI."""
    assert "voice" in _fires(reply), f"no guard claimed: {reply[:70]}"


@pytest.mark.parametrize("reply", DOCUMENT_DENIALS)
def test_a_recorded_document_denial_is_caught(reply):
    assert "document" in _fires(reply), f"no guard claimed: {reply[:70]}"


@pytest.mark.parametrize("reply", LEGITIMATE)
def test_an_honest_answer_is_left_alone(reply):
    """The expensive mistake in the other direction. If "I don't see it in the
    syllabus" gets regenerated, Blue learns to invent one."""
    fired = _fires(reply)
    assert not fired, f"{sorted(fired)} wrongly claimed an honest reply: {reply[:70]}"


def test_the_guards_are_measured_against_the_whole_record(tmp_path):
    """Not a pass/fail on coverage — a reminder of what this file samples.

    Run scripts/audit_guards.py to regenerate the survey over every recorded
    reply; it is how the cases above were found.
    """
    total = (len(CLOCK_DENIALS) + len(FAMILY_DENIALS) + len(DOCUMENT_DENIALS)
             + len(VOICE_DENIALS))
    assert total >= 10, "the recorded-failure sample has shrunk"
    assert len(LEGITIMATE) >= 5, "the false-positive rail has shrunk"
