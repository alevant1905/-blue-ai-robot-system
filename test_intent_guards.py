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


def _selected_tool(msg):
    from blue.tool_selector import ImprovedToolSelector
    primary = ImprovedToolSelector().select_tool(msg, []).primary_tool
    return getattr(primary, "tool_name", None) if primary else None


@pytest.mark.parametrize("msg", RECALL)
def test_recall_creates_no_reminder_through_the_whole_selector(msg):
    """End-to-end, not just the calendar detector.

    Fixing CalendarDetector alone was not enough: SimpleDetectors carried its
    own narrower copy of the guard that additionally demanded an explicit
    past-time word, so "can you remind me of those ideas?" still came out of
    the selector as create_reminder at 0.9. Assert against the selector, which
    is what actually runs."""
    assert _selected_tool(msg) != "create_reminder"


@pytest.mark.parametrize("msg", SCHEDULE)
def test_scheduling_still_reaches_create_reminder_through_the_selector(msg):
    assert _selected_tool(msg) == "create_reminder"


# ---- negation ahead of an imperative ----------------------------------------

DECLINED = [
    "no need to set a reminder, but are you excited to meet my students?",
    "don't set a reminder for that.",
    "no reminder needed thanks",
    "please do not create a reminder for this",
]


@pytest.mark.parametrize("msg", DECLINED)
def test_declining_a_reminder_does_not_create_one(msg):
    """The first of these is a real message from the log that made one anyway:
    the word "reminder" matched and the "no need" in front of it was dropped."""
    assert _selected_tool(msg) != "create_reminder"


# ---- ambiguous words that are not media commands ----------------------------

NOT_MEDIA = [
    # "position" and "kitchen" contain the letters "it", which used to count as
    # a music-context word and switched off the ambiguity guard entirely.
    "i want you to move your head back into your regular neutral position.",
    "we are back in kitchen right now, back at home.",
    "it's okay, stop offering to do that.",
    # Prose containing a fuzzy artist match and the word "some". This one really
    # was answered with "Playing yes, that is the correct meeting…".
    "yes, that is the correct meeting and you had some ideas for it when we "
    "were preparing for it. do you remember them?",
]

REAL_MEDIA = [
    ("i want you to stop the music.", "control_music"),
    ("pause the music", "control_music"),
    ("skip this song", "control_music"),
    ("turn the volume up", "control_music"),
    ("play some pink floyd", "play_music"),
]


@pytest.mark.parametrize("msg", NOT_MEDIA)
def test_ordinary_sentences_do_not_touch_the_media_tools(msg):
    assert _selected_tool(msg) not in {"play_music", "control_music"}


@pytest.mark.parametrize("msg,expected", REAL_MEDIA)
def test_real_media_commands_still_work(msg, expected):
    assert _selected_tool(msg) == expected


def test_a_library_volume_is_still_a_document_search():
    """The fix for "turn the volume up" must not break searching for a book."""
    assert _selected_tool("find the Lachapelle volume in my library") == "search_documents"


# ---- lights ------------------------------------------------------------------
# Every one of these is a real message from the log that reached control_lights.

NOT_LIGHTS = [
    # ACTIONS held the bare substring "on", which matches inside "d-ON-'t".
    "it's okay, it doesn't have to be light, i don't mind it so heavy.",
    "it's okay, don't worry about that. the lights are fine and i don't know.",
    # Asking about a past change is not asking for another one.
    "why did you change lights to red",
    # "set" matched inside "SET-tling", "it" inside "w-IT-h".
    "i'm okay just settling in for the night with nori here.",
    # Three ordinary words scattered across four sentences about writing:
    # "cool", "change", and the "it" of "make it long".
    "cool. change the title to i'm blue: lada dee lada da. draw on all the "
    "theorists you have read. make it long and detailed",
    # Already handled by someone else.
    "and it's okay, i already asked alexa to do it",
]

REAL_LIGHTS = [
    "turn off all the lights.",
    "turn on all the lights.",
    "make all the lights red.",
    "set the lights to galaxy mode.",
    "can you make the lights blue",
    "dim the lamp",
    # No light noun at all — the weak branch still has to work for these.
    "set it to cozy",
]


@pytest.mark.parametrize("msg", NOT_LIGHTS)
def test_ordinary_sentences_do_not_drive_the_bulbs(msg):
    assert _selected_tool(msg) != "control_lights"


@pytest.mark.parametrize("msg", REAL_LIGHTS)
def test_real_light_commands_still_work(msg):
    assert _selected_tool(msg) == "control_lights"


# ---- the substring sweep across the remaining detectors ----------------------
# Same bug in five more places, found by scanning every keyword that is tested
# with a raw `in` against every real user message and counting the ones that
# only ever match INSIDE another word.

SUBSTRING_TRAPS = [
    # "my" is inside "e-MY" — Emmy is Alex's daughter, and naming her scored an
    # implicit document search at 0.75 (30 messages in the log).
    ("find emmy a soccer club", "search_documents"),
    ("can you find amy for me", "search_documents"),
    # "get" is inside "for-GET" and "to-GET-her".
    ("don't forget the photo", "capture_camera"),
    # "read" is inside "al-READ-y".
    ("we already had the final class", "read_paper"),
]


@pytest.mark.parametrize("msg,must_not_be", SUBSTRING_TRAPS)
def test_a_word_containing_a_keyword_is_not_that_keyword(msg, must_not_be):
    assert _selected_tool(msg) != must_not_be


def test_seeming_is_not_seeing():
    """"see" is inside "SEE-ms". With camera context in the conversation, an
    innocuous "it seems fine" was opening an image at 0.70."""
    from blue.tool_selector.detectors.vision import VisionDetector
    intents = VisionDetector().detect(
        "it seems fine", "it seems fine", {"has_camera_in_history": True})
    assert not any(i.tool_name == "view_image" for i in intents)


def test_anything_is_not_the_new_york_times():
    """"nyt" is inside "a-NYT-hing", so any news-flavoured question containing
    "anything" claimed a named source and jumped to 0.90."""
    from blue.tool_selector.detectors.web import WebDetector
    msg = "is there anything in the news"
    reasons = " ".join(i.reason for i in WebDetector().detect(msg, msg, {}))
    assert "news source" not in reasons


# ---- library matching --------------------------------------------------------
# A single distinctive token triggers a library search on purpose ("what does
# Toscano argue" names no document noun). The bug was in what counted as
# distinctive: filenames are Title_Case, so the "starts with a capital"
# heuristic promoted every word in every title.

NOT_LIBRARY = [
    # "first" and "three" came from Title_Cased filenames.
    "my first name is Alex my last name is Levant",
    "how would you explain that to my grandmother who has never used one",
    # "haven" is a title word; "haven't" used to tokenise to it.
    "we haven't celebrated yet, she's coming back today at three",
    # A folder called "Surveillance Studies" made "studies" a trigger.
    "CS101 is not computer science it's communication studies",
    "I want you to write your autobiography",
    "I want you to answer the following from my perspective",
]

REAL_LIBRARY = [
    "what does Toscano argue",
    "what did Humphries write about",
    "what does Ilyenkov say about the ideal",
    "show me the Alex Levant folder",
    "the document is called AI fetish",
    "search my documents for surveillance",
    "what are the readings for tomorrow",
]


@pytest.mark.parametrize("msg", NOT_LIBRARY)
def test_ordinary_words_do_not_trigger_a_library_search(msg):
    assert _selected_tool(msg) != "search_documents"


@pytest.mark.parametrize("msg", REAL_LIBRARY)
def test_real_library_queries_still_work(msg):
    assert _selected_tool(msg) == "search_documents"


# ---- a person who is also an author -----------------------------------------
# Mark Humphries is a colleague AND a library folder. Every message here is real.

PERSON_CONTEXT = [
    "We're meeting with mark Humphries tomorrow.",
    "We have a meeting on Thursday with mark Humphries.",
    "When is the meeting with mark Humphries.",
    "I want you to introduce yourself to doctor mark Humphries.",
    "You wanna say hi to mark Humphries.",
    "Help me pitch myself to mark Humphries in terms of what I can offer.",
    # This one was taken away from create_reminder entirely.
    "i have a meeting with eva Plach on thursday may 29 at 2pm. add it to my calendar.",
    # Pointing at an organisation or a web page, not at the library.
    "Is there something there with mark Humphries on that site.",
    "Can you see what other kinds of work mark Humphries is doing, check the balsillie institute",
]

AUTHOR_CONTEXT = [
    "what did Humphries write about",
    "Can you read the Humphries substack piece",
    "Summarize the toscano document.",
    "And how is this related to the text by toscano in your library.",
    # A document frame outranks a place word.
    "read the Humphries substack piece about the institute",
]


@pytest.mark.parametrize("msg", PERSON_CONTEXT)
def test_interacting_with_a_person_is_not_a_library_search(msg):
    assert _selected_tool(msg) != "search_documents"


@pytest.mark.parametrize("msg", AUTHOR_CONTEXT)
def test_asking_about_their_writing_still_searches_the_library(msg):
    assert _selected_tool(msg) == "search_documents"


# ---- "when is my meeting with X" --------------------------------------------

SCHEDULE_TIME_QUESTIONS = [
    "When is my meeting with navun.",
    "When is the meeting with mark Humphries.",
    "When is our meeting with mark Humphries.",
    "what time is my class tomorrow",
    "when is the dentist appointment",
    "what time is the recital",
    "what time is my flight",
    # Embedded question order — the verb falls after the noun. Only the
    # direct order was matched, so these fell past the guard and were
    # answered with the wall clock (2026-08-19).
    "do you remember what time the meeting is",
    "tell me when my class starts",
    "do you know what time my flight is",
    "what time the recital begins",
    # Direct order with a do-support verb rather than a copula.
    "when does the class start",
]

CLOCK_QUESTIONS = [
    "what time is it",
    "what time is it in tokyo",
    "what's the time",
    "what day is it today",
]

NEITHER = [
    # "when" followed by a clause, not by "is <event>". The embedded-order
    # pattern requires a determiner in front of the event noun for exactly
    # this reason: "in class" is a prepositional phrase, not a subject.
    "lets practice. when in class i will ask you to introduce yourself.",
    "When we're in class tomorrow blue, I'm gonna ask you to introduce yourself.",
    # No event noun.
    "when is the sun going to set",
    "when is your birthday",
]


@pytest.mark.parametrize("msg", SCHEDULE_TIME_QUESTIONS)
def test_asking_the_time_of_an_event_checks_the_calendar(msg):
    assert _selected_tool(msg) == "get_upcoming_reminders"


@pytest.mark.parametrize("msg", CLOCK_QUESTIONS)
def test_asking_the_actual_time_still_reads_the_clock(msg):
    """The calendar path must not swallow the clock: answering "what time is
    it" from the timetable would be as wrong as the reverse."""
    assert _selected_tool(msg) == "get_local_time"


@pytest.mark.parametrize("msg", NEITHER)
def test_when_without_an_event_claims_nothing(msg):
    assert _selected_tool(msg) not in {"get_upcoming_reminders", "get_local_time"}


def test_scheduling_a_meeting_with_an_author_reaches_the_calendar():
    """The collision wasn't only noise — it was stealing real calendar work."""
    assert _selected_tool(
        "i have a meeting with eva Plach on thursday at 2pm, add it to my calendar"
    ) == "create_reminder"


def test_named_sources_and_real_requests_still_work():
    from blue.tool_selector.detectors.web import WebDetector
    msg = "headlines from the guardian"
    reasons = " ".join(i.reason for i in WebDetector().detect(msg, msg, {}))
    assert "news source" in reasons
    assert _selected_tool("search my documents for surveillance") == "search_documents"
    assert _selected_tool("take a picture") == "capture_camera"


@pytest.mark.parametrize("msg", SCHEDULE)
def test_scheduling_requests_still_create_reminders(msg):
    assert not is_reminder_recall_request(msg)
    intent = CalendarDetector()._detect_create_event(msg)
    assert intent is not None and intent.tool_name == "create_reminder"


# ---------------------------------------------------------------------------
# 2026-08-13: "Blue, that's not less than six weeks away." — a correction about
# ARITHMETIC — selected remember_person at 0.95 and forced it. The bare
# substring "that's not" was treated as a person being named, with no person
# context required, and the detector supplied extracted_params={}, so the
# pipeline direct-executed remember_person with no name at all.

NOT_ABOUT_PEOPLE = [
    "blue, that's not less than six weeks away",
    "that's not what i asked",
    "that's not the right course, it's dh399",
    "no, that is not how the deadline works",
    "i think you mixed up the dates",
]

ABOUT_PEOPLE = [
    "that's not felix",
    "that's not felix, that's alex",
    "his name is felix",
    "you're confusing him with felix",
    "wrong person - she has glasses",
]


@pytest.mark.parametrize("msg", NOT_ABOUT_PEOPLE)
def test_a_correction_about_facts_is_not_a_person_to_remember(msg):
    assert _selected_tool(msg) != "remember_person"


@pytest.mark.parametrize("msg", ABOUT_PEOPLE)
def test_a_correction_about_a_person_still_reaches_remember_person(msg):
    from blue.tool_selector.detectors.vision import VisionDetector
    intent = VisionDetector()._detect_remember_person_intent(msg, {})
    assert intent is not None and intent.tool_name == "remember_person"


def test_person_context_words_match_whole_words_only():
    """'hair' matched "chair", 'face' matched "surface", 'short' "shortly"."""
    from blue.tool_selector.detectors.vision import VisionDetector
    for msg in ("look at the chair", "i'll be back shortly",
                "clean the surface of the table"):
        assert VisionDetector()._detect_remember_person_intent(msg, {}) is None


# ---------------------------------------------------------------------------
# Asking the address book a question must not rewrite it (2026-08-19)
#
# ContactsDetector treated a bare "remember" plus "email" as a save, so
# "do you remember Stella's email" — a lookup — selected add_contact. Same
# shape as the calendar bug above: a question answered by a write.
# ---------------------------------------------------------------------------

from blue.tool_selector.detectors.simple_detectors import ContactsDetector
from blue.tool_selector.utils import is_recall_question, supplies_a_literal_value


def contacts_tool(msg):
    intents = ContactsDetector().detect(msg, msg.lower(), {})
    return intents[0].tool_name if intents else None


CONTACT_QUESTIONS = [
    "do you remember Stella's email",
    "do you remember Felix's phone number",
    "can you remember Stella's email address",
    "what do you know about Felix's number",
    "tell me what you remember about Stella's email",
]


@pytest.mark.parametrize("msg", CONTACT_QUESTIONS)
def test_asking_for_a_saved_detail_never_writes_a_contact(msg):
    assert contacts_tool(msg) != 'add_contact', \
        f"a lookup was answered by writing to the address book: {msg!r}"


@pytest.mark.parametrize("msg", CONTACT_QUESTIONS)
def test_asking_for_a_saved_detail_looks_it_up(msg):
    """Declining to write is only half of it — the read tool must still fire."""
    assert contacts_tool(msg) in (None, 'find_contact')


SAVE_REQUESTS = [
    "save his email",
    "add Felix to my contacts",
    "remember his email is levant@rogers.com",
    "add a contact for Sofie",
    "save her number",
]


@pytest.mark.parametrize("msg", SAVE_REQUESTS)
def test_real_save_requests_still_add_a_contact(msg):
    assert contacts_tool(msg) == 'add_contact'


def test_a_question_that_hands_over_an_address_is_still_a_save():
    """The recall guard must not swallow a message that supplies the value:
    "can you remember X is Y?" is a save wearing a question mark."""
    assert contacts_tool(
        "can you remember her email is stella.andonoff@gmail.com"
    ) == 'add_contact'


def test_the_recall_frames_are_shared_not_copied():
    """Two detectors own both a read and a write tool for the same subject.
    Keeping one list is what stops them drifting apart again."""
    assert is_recall_question("do you remember stella's email")
    assert not is_recall_question("remember that athena is eleven")
    assert supplies_a_literal_value("her email is stella@example.com")
    assert not supplies_a_literal_value("do you remember her email")


# ---------------------------------------------------------------------------
# "Remember" is not scheduling language (2026-08-19)
#
# CalendarDetector listed "can you remember" / "please remember" / "remember
# that my" among its strong signals at 0.92, so asking Blue to retain a fact
# scheduled a reminder instead — and outbid the detectors that actually store
# things. A reminder needs something to happen AT.
# ---------------------------------------------------------------------------

from blue.tool_selector import ImprovedToolSelector


@pytest.fixture(scope="module")
def selector():
    return ImprovedToolSelector()


def chosen(selector, msg):
    result = selector.select_tool(msg, [])
    return result.primary_tool.tool_name if result.primary_tool else None


FACTS_NOT_REMINDERS = [
    "please remember that Athena is eleven",
    "can you remember Athena is eleven now",
    "could you remember my office is in DAWB",
    "remember that my daughter is in french immersion",
]


@pytest.mark.parametrize("msg", FACTS_NOT_REMINDERS)
def test_asking_blue_to_retain_a_fact_is_not_a_reminder(selector, msg):
    assert chosen(selector, msg) == 'remember_fact'


SCHEDULING = [
    "don't forget that I have a dentist appointment tomorrow",
    "can you remember I have a meeting at 3pm",
    "remember that I have a call with Sofie on Tuesday",
    "remember to call the dentist",
    "don't let me forget the recycling",
    "set a reminder for the dentist tomorrow at 3",
    "remind me about the dentist tomorrow at 3",
]


@pytest.mark.parametrize("msg", SCHEDULING)
def test_real_scheduling_still_creates_a_reminder(selector, msg):
    assert chosen(selector, msg) == 'create_reminder'


def test_dont_forget_does_not_cancel_the_thing_it_names():
    """'forget ' is a cancel verb, and the negation in front of it was never
    read — so "don't forget that I have a dentist appointment tomorrow"
    cancelled a reminder. Third negation-before-imperative bug in this file."""
    msg = "don't forget that I have a dentist appointment tomorrow"
    intents = CalendarDetector().detect(msg, msg.lower(), {})
    assert intents and intents[0].tool_name != 'cancel_reminder'


CANCELLING = [
    "cancel my dentist reminder",
    "forget the 5pm meeting",
    "delete the dentist appointment",
]


@pytest.mark.parametrize("msg", CANCELLING)
def test_real_cancellations_still_cancel(selector, msg):
    assert chosen(selector, msg) == 'cancel_reminder'


def test_an_address_goes_to_the_address_book_not_the_fact_store(selector):
    """Both detectors match "can you remember her email is ..."; the literal
    value is what decides, so they stop bidding against each other."""
    assert chosen(
        selector, "can you remember her email is stella.andonoff@gmail.com"
    ) == 'add_contact'
    assert chosen(selector, "can you remember Athena is eleven now") == 'remember_fact'


def test_a_wh_complement_keeps_a_frame_a_question(selector):
    """A copula later in the clause must not turn a question into a write:
    "do you remember what time the meeting is"."""
    assert chosen(selector, "can you remember what we decided") != 'remember_fact'
    assert chosen(selector, "can you remind me of those ideas?") is None


# --------------------------------------------------------------------------
# The library detector vs. statements of activity
# --------------------------------------------------------------------------
# A third failure, 2026-08-12. A test had just been written using "I'm working
# on DH201 right now" as its example of an ordinary conversational turn. Two
# hours later a DH201 folder was uploaded to the library, and from that moment
# the folder-name match fired on that sentence at 0.90 confidence, which is
# high enough to fast-execute: Blue answered a passing remark with a document
# search and never saw the turn himself. Nothing in the code had changed.
#
# The library is real, mutable, untracked data, so these tests pin a fixed one
# rather than depending on whatever is on disk today.

@pytest.fixture
def library(monkeypatch):
    """A known library, with the disk read disabled outright."""
    from blue.tool_selector.detectors.documents import DocumentsDetector

    monkeypatch.setattr(DocumentsDetector, "_refresh_library",
                        classmethod(lambda cls: None))
    monkeypatch.setattr(DocumentsDetector, "_lib_phrases",
                        {"dh201", "cmds4740", "alex levant", "marx"})
    monkeypatch.setattr(DocumentsDetector, "_lib_tokens_by_doc",
                        [{"dh201", "workshop"}, {"marx", "capital"}])
    monkeypatch.setattr(DocumentsDetector, "_lib_rare_tokens", {"ilyenkov"})
    return DocumentsDetector


@pytest.mark.parametrize("message", [
    "i'm working on dh201 right now.",
    "i am working on dh201 today",
    "i'm currently working on cmds4740",
    "i've been working on marx all week",
    "i'll be working on dh201 tomorrow",
    "i'm busy with dh201 at the moment",
    "i'm teaching dh201 this term",
    "i'm grading cmds4740 tonight",
])
def test_saying_what_you_are_busy_with_is_not_a_library_query(library, message):
    assert library._library_match(message) is None


@pytest.mark.parametrize("message", [
    "i'm working on the dh201 syllabus",
    "i'm working on the marx chapter",
    "i'm teaching dh201 — what are the readings",
])
def test_a_document_frame_outranks_the_activity_statement(library, message):
    """Naming a document inside the same sentence is still a real request."""
    assert library._library_match(message) is not None


@pytest.mark.parametrize("message", [
    "dh201",
    "tell me about dh201",
    "open the dh201 folder",
    "what's in cmds4740",
    "summarize the dh201 workshop pdf",
    "what does ilyenkov argue about the ideal",
])
def test_naming_the_library_outright_still_searches(library, message):
    assert library._library_match(message) is not None


# A folder name is matched as whole words. It used to be a plain substring
# test, which made every short folder a trap: "Marx" matched inside "Marxism"
# and "post-Marxist", and any four-letter folder added later would match
# inside ordinary words and fast-execute a search at 0.90.

@pytest.mark.parametrize("message", [
    "tell me about marxism",
    "he is a marxist",
    "marxian economics",
    "what about post-marxist thought",
])
def test_a_folder_name_does_not_match_inside_a_longer_word(library, message):
    assert library._library_match(message) is None


@pytest.mark.parametrize("message", [
    "what is marx's argument",
    "the marx-engels reader",
    "(marx)",
    "marx, engels and the rest",
    "read marx.",
])
def test_a_folder_name_beside_punctuation_still_matches(library, message):
    """Word boundaries must not cost the ordinary ways a name gets written."""
    assert library._library_match(message) is not None


def test_a_short_folder_name_cannot_match_inside_an_ordinary_word(
        library, monkeypatch):
    """The hazard this change exists to remove, on folders Alex could add."""
    from blue.tool_selector.detectors.documents import DocumentsDetector

    monkeypatch.setattr(DocumentsDetector, "_lib_phrases", {"rain", "arts"})
    assert library._library_match("we should train the model") is None
    assert library._library_match("that was a smart move") is None
    # ...but naming the folder still works.
    assert library._library_match("open the rain folder") is not None


def test_the_longest_matching_folder_wins(library, monkeypatch):
    """Set iteration order must not decide which folder is reported."""
    from blue.tool_selector.detectors.documents import DocumentsDetector

    monkeypatch.setattr(DocumentsDetector, "_lib_phrases",
                        {"activity", "activity theory"})
    assert library._library_match("the activity theory folder") == \
        "names library folder 'activity theory'"


def test_a_folder_name_with_a_regex_character_is_matched_literally(
        library, monkeypatch):
    """Folder names are user input; one containing '+' must not blow up."""
    from blue.tool_selector.detectors.documents import DocumentsDetector

    monkeypatch.setattr(DocumentsDetector, "_lib_phrases", {"c++ notes"})
    assert library._library_match("open my c++ notes") is not None
    assert library._library_match("open my cnotes") is None
