"""Old replies and banter are memories, not templates.

Run with: python -m pytest test_reply_templates.py

From the 10-07 turns (conversation_log ids):
- Blue and Casper did a banter set on the DH201 AI lab at 09:36-09:41. Its
  line "the only thing more private than the model is the fan on your
  laptop" sat in <j_space> and <conversation_memory>, and Alex's "we will
  do that in class" got "my local hardware is already at its thermal limit…
  my office fan sound like a jet engine" (10133).
- "can you introduce this topic to the class" got "Welcome to Week 4.
  Today we're exploring the roots of modern AI…" (10127); quoted as already
  said, it came back nearly whole for "okay. enough banter. introduce
  todays topic to the class" (10143).
- The 09-16 reply to "blue, we are in front of the class in dh201 right
  now" ("Understood. Since we are currently in front of the class in
  **SB107**…") came back for "we are in the class rightnow" with another
  room, bold and all (10149).

Every block here is built against a temporary J-space store or a scratch
database, never the live ones.
"""

from datetime import datetime, timedelta

import pytest

import bluetools as bt  # before blue.server.*: the package imports it

from blue_identity import (
    asks_for_class_reply, asks_for_recall, is_reask, speaks_to_a_class,
)
from blue_memory_improved import EnhancedMemorySystem
from blue_reply_text import plain_quote, quotable_reply
from test_bluejspace import continuity_module  # noqa: F401  (fixture)
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)
from test_memory_recall import FOUR_IDEAS_ASK, _ask, _at, _seed

BANTER_TOPIC = ("Topic: AI Lab 3: How to download, install, and operate local, "
                "private, open-source models Source: DH201_AL_2026F.pdf (pdf).")
BANTER_JOKE = ("The syllabus says open-source models are for private use, which "
               "is true until you realize the only thing more private than the "
               "model is the fan on your laptop.")
CASPER_LINE = ("I downloaded a local model to write my Week 4 reading report, "
               "and it just spat out a recipe for lasagna.")
BLUE_ROAST = ("You downloaded a local model for a reading report on Pasquinelli "
              "and got lasagna because you didn't read the installation guide.")
INTRO_ASK = "can you introduce this topic to the class"                  # 10126
INTRO = ("\"Welcome to Week 4. Today we're exploring the roots of modern AI "
         "through two competing lineages: Symbolic AI, which uses rules and "
         "logic, and Connectionism, the approach that birthed today's neural "
         "networks.\"")                                                    # 10127
INTRO_AGAIN = "okay. enough banter. introduce todays topic to the class"  # 10142
IN_CLASS = "blue, we are in front of the class in dh201 right now"        # 9859
IN_CLASS_REPLY = ("Understood. Since we are currently in front of the class in "
                  "**SB107** for DH201: Introduction to Generative AI, I am ready "
                  "to assist with the lecture materials.")                 # 9860


def _banter_set(route, robot="blue", session="banter-1", topic=BANTER_TOPIC):
    hub = route.HUB[robot]
    for heard, said, other in ((topic, "To earn my respect this week you "
                                "must define connectionism in one sentence.",
                                "Alex's topic"),
                               (CASPER_LINE, BLUE_ROAST, "Casper"),
                               (topic, BANTER_JOKE, "Alex's topic")):
        hub.note_exchange(heard, said, user_name=other, tools=[],
                          source="banter", enqueue_reflection=False,
                          extra_details={"banter_session_id": session,
                                         "memory_status": "playful_performance"})


# ---- (a) a banter set is named, never quoted, in chat -----------------------

def test_jspace_names_a_banter_set_on_one_line_without_its_jokes(continuity_module):
    route = continuity_module
    route.note_exchange("blue", "what else are we reading today",
                        "Wooldridge, Chomsky and Pasquinelli.")
    _banter_set(route)
    route.HUB["blue"].note_exchange(
        "Topic: open models", "Open weights are not open labour.",
        user_name="Hexia", tools=[], source="duet", enqueue_reflection=False)

    block = route.jspace_context_block("blue")

    assert "fan on your laptop" not in block
    assert "lasagna" not in block and "connectionism in one sentence" not in block
    assert block.count("; banter] ") == 1
    assert ("A comedic banter set with Casper on 'AI Lab 3: How to download, "
            "install, and operate local, private, open-source m...' (3 lines). "
            "Its jokes are left out: they were a performance, not things to "
            "say again.") in block
    # A duet line keeps its wording; a chat line is named by what was asked.
    assert "Open weights are not open labour." in block
    assert "Alex asked: 'what else are we reading today' — you answered." in block


def test_conversation_memory_names_a_banter_set_once(continuity_module):
    route = continuity_module
    route.note_exchange("blue", "what else are we reading today",
                        "Wooldridge, Chomsky and Pasquinelli.")
    _banter_set(route)

    block = route.conversation_memory_block(
        "blue", query="we will do that in class", include_banter_wording=False,
        chat_turn=True)

    assert "fan on your laptop" not in block and "lasagna" not in block
    lines = [line for line in block.splitlines() if "comedic banter" in line]
    assert len(lines) == 1
    assert lines[0].endswith(
        "prior comedic banter with Casper] You performed a set together on "
        "'AI Lab 3: How to download, install, and operate local, private, "
        "open-source m...' (3 lines). Its jokes are left out: they were a "
        "performance, not things to say again.")
    assert "Wooldridge, Chomsky and Pasquinelli." in block
    # The duet still quotes them: its talk is had with the lines.
    quoted = route.conversation_memory_block("blue", query="lasagna")
    assert "lasagna" in quoted


WEEK5_TOPIC = ("Topic: Week 5: Pasquinelli, The Eye of the Master Source: "
               "DH201_AL_2026F.pdf (pdf).")


def _recorded_at(monkeypatch, stamp):
    """The journal's clock, for the lines recorded next."""
    import blue.continuity as store
    monkeypatch.setattr(store, "_now", lambda: stamp)


def test_banter_sets_started_again_within_minutes_are_one_line(
        continuity_module, monkeypatch):
    """10-07: Alex started the DH201 banter five times between 09:36 and
    09:41. One sitting is one line, and it says how many sets."""
    route = continuity_module
    _recorded_at(monkeypatch, "2026-10-07T13:36:30+00:00")
    _banter_set(route)
    _recorded_at(monkeypatch, "2026-10-07T13:38:03+00:00")
    _banter_set(route, session="banter-2", topic=WEEK5_TOPIC)

    block = route.jspace_context_block("blue")
    assert block.count("; banter] ") == 1
    assert "] 2 comedic banter sets with Casper on 'AI Lab 3: How to" in block
    assert ("and 'Week 5: Pasquinelli, The Eye of the Master' (6 lines). Their "
            "jokes are left out") in block

    block = route.conversation_memory_block(
        "blue", query="we will do that in class", include_banter_wording=False,
        chat_turn=True)
    lines = [line for line in block.splitlines() if "comedic banter" in line]
    assert len(lines) == 1
    assert "] You performed 2 sets together on 'AI Lab 3" in lines[0]


def test_banter_sets_on_two_days_are_a_line_each_at_their_own_time(
        continuity_module, monkeypatch):
    """Adjacent in <conversation_memory>, a set from the day before read as
    part of the later one, at the later one's time."""
    route = continuity_module
    _recorded_at(monkeypatch, "2026-10-06T13:36:30+00:00")
    _banter_set(route, session="banter-0", topic=WEEK5_TOPIC)
    _recorded_at(monkeypatch, "2026-10-07T13:36:30+00:00")
    _banter_set(route)

    block = route.jspace_context_block("blue")
    assert block.count("; banter] A comedic banter set with Casper on ") == 2

    block = route.conversation_memory_block(
        "blue", query="we will do that in class", include_banter_wording=False,
        chat_turn=True)
    lines = [line for line in block.splitlines() if "comedic banter" in line]
    assert len(lines) == 2
    assert "2026-10-06" in lines[0] and "Week 5" in lines[0]
    assert "2026-10-07" in lines[1] and "AI Lab 3" in lines[1]


def test_asked_in_chat_what_was_said_in_a_set_he_has_its_lines(continuity_module):
    """The journal is the only record of a set: asked what was said, chat
    quotes it. The panel and the banter route never do."""
    route = continuity_module
    _banter_set(route)
    ask = "what was the joke you told Casper about the fan?"

    block = route.conversation_memory_block(
        "blue", query=ask, include_banter_wording=False, chat_turn=True,
        live_thread=[{"role": "user", "content": ask}])
    assert "fan on your laptop" in block
    assert "already said — don't re-say it" in block

    block = route.conversation_memory_block(
        "blue", query=ask, include_banter_wording=False)
    assert "fan on your laptop" not in block
    assert "You performed a set together" in block


@pytest.fixture
def journal(monkeypatch, tmp_path):
    """Blue's J-space for the chat route, in a temporary store; the memory
    blocks off, so only the journal speaks."""
    route = bt._continuity_routes
    hub = route.RobotContinuity("blue", str(tmp_path / "jspace"), "IDENTITY: I am Blue.")
    monkeypatch.setitem(route.HUB, "blue", hub)
    monkeypatch.setattr(bt.memory_system, "build_context", lambda *a, **k: [])
    return route


def _sent(chat):
    return " ".join(str(message.get("content") or "")
                    for payload in chat.model.payloads
                    for message in payload["messages"])


def test_a_banter_joke_never_reaches_the_chat_prompt(chat, journal):
    """Through the chat route: the J-space and <conversation_memory> both
    come from a store holding the 10-07 set, and the model sees neither
    joke, only that the set happened."""
    _banter_set(journal)

    reply_of(chat.ask("we will do that in class"))

    sent = _sent(chat)
    assert "fan on your laptop" not in sent and "lasagna" not in sent
    assert "A comedic banter set with Casper on 'AI Lab 3" in chat.model.system_prompt
    assert "prior comedic banter with Casper] You performed a set together" in (
        chat.model.system_prompt)


def test_the_relationship_guard_quotes_no_banter_either(chat, journal):
    """Its re-ask carries the robot conversations as evidence that Casper is
    known: the set is named, its jokes are not."""
    _banter_set(journal)
    chat.model.queue("I don't know who Casper is.", "Casper is my fellow robot.")

    assert reply_of(chat.ask("what is casper up to these days?")) == (
        "Casper is my fellow robot.")
    redo = " ".join(str(message.get("content") or "")
                    for message in chat.model.payloads[-1]["messages"])
    assert "You denied knowing one of your fellow robots" in redo
    assert "prior comedic banter with Casper" in redo
    assert "lasagna" not in redo and "fan on your laptop" not in redo


# ---- (b) what he said to a class is not quoted back --------------------------

@pytest.mark.parametrize("text", [
    INTRO_ASK, INTRO_AGAIN, IN_CLASS,
    "we are in the class rightnow",                       # 10148
    "can you introduce the course DH399 to the class?",   # 9887
    "Can you introduce the course to the students as well?",  # 5034
    "present your reading report to the class",           # 10097
])
def test_a_class_in_the_room_or_spoken_to(text):
    assert speaks_to_a_class(text)


@pytest.mark.parametrize("text", [
    "we will do that in class",                           # 10132
    "i might take you with me to dh201 tomorrow",         # 10111
    "what should I tell the students?",
    "the class didn't go well. the students seemed bored",
    "can you recall what you told the class on wednesday?",
])
def test_a_class_talked_about(text):
    assert not speaks_to_a_class(text)


def test_conversation_memory_withholds_what_was_said_to_a_class(continuity_module):
    route = continuity_module
    route.note_exchange("blue", IN_CLASS, IN_CLASS_REPLY)
    route.note_exchange("blue", INTRO_ASK, INTRO)
    route.note_exchange("blue", "what else are we reading today",
                        "Wooldridge, Chomsky and Pasquinelli.")

    block = route.conversation_memory_block(
        "blue", query="we are in the class rightnow", chat_turn=True,
        live_thread=[{"role": "user", "content": "we are in the class rightnow"}])

    assert "SB107" not in block and "Welcome to Week 4" not in block
    assert (f"Alex said: {IN_CLASS} (Your reply wording is omitted so it is "
            "never reused.)") in block
    assert (f"Alex said: {INTRO_ASK} (Your reply wording is omitted so it is "
            "never reused.)") in block
    assert "Wooldridge, Chomsky and Pasquinelli." in block

    # Asked what was said, he has it.
    recall = "what did you tell the class this morning?"
    block = route.conversation_memory_block(
        "blue", query=recall, chat_turn=True,
        live_thread=[{"role": "user", "content": recall}])
    assert "Welcome to Week 4" in block


@pytest.fixture
def log(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    conn = memory._conn()
    base = datetime.now() - timedelta(hours=2)
    for minutes, role, content in (
            (0, "user", INTRO_ASK), (1, "assistant", INTRO),
            (2, "user", "what else are we reading today"),
            (3, "assistant", "Besides **Wooldridge**, you've got Chomsky's "
                             "*The False Promise of ChatGPT*.")):
        conn.execute(
            "INSERT INTO conversation_log (timestamp, user_name, role, content, "
            "session_id, importance, robot) VALUES (?, 'Alex', ?, ?, NULL, 5, 'blue')",
            ((base + timedelta(minutes=minutes)).isoformat(), role, content))
    conn.commit()
    conn.close()
    return memory


def _recent_history(memory, monkeypatch, text):
    for name in ("_build_facts_block", "_build_user_notes_block",
                 "get_proactive_memories", "_build_last_conversation_block",
                 "_build_session_history_block", "_build_rhythms_block",
                 "_build_connections_block", "_build_past_answers_block",
                 "_build_recalled_days_block"):
        monkeypatch.setattr(memory, name, lambda *a, **k: "")
    monkeypatch.setattr(memory, "search_memories", lambda *a, **k: [])
    parts = memory.build_context([{"role": "user", "content": text}],
                                 user_name="Alex", chat_turn=True)
    return next(part["content"] for part in parts
                if "<recent_history>" in part["content"])


def test_recent_history_withholds_a_class_reply_and_its_markdown(log, monkeypatch):
    block = _recent_history(log, monkeypatch, INTRO_AGAIN)
    assert "Welcome to Week 4" not in block
    assert f"USER: {INTRO_ASK}\n" in block
    assert "ASSISTANT: (answered)\n" in block
    assert ("ASSISTANT: Besides Wooldridge, you've got Chomsky's The False "
            "Promise of ChatGPT.") in block
    # Asked what was said, he has it.
    block = _recent_history(log, monkeypatch, "what did you tell the class earlier?")
    assert "Welcome to Week 4" in block


def test_remembered_days_withholds_a_class_reply_unless_asked():
    line = EnhancedMemorySystem._recalled_reply
    assert line(INTRO_ASK, INTRO, "tell the students about the reading", False,
                False, set(), []) == "(answered)"
    assert line(INTRO_ASK, INTRO, "what did you tell the class?", True,
                False, set(), []).startswith("\"Welcome to Week 4.")
    # Asked to hear it again, in words that are no recall ask elsewhere.
    assert line(INTRO_ASK, INTRO, "repeat the intro you gave the class "
                "yesterday", False, False, set(), []).startswith(
                    "\"Welcome to Week 4.")


@pytest.mark.parametrize("text", [
    "can you repeat the introduction you gave the class?",
    "repeat what you told the students",
    "say that intro again",
    "what was your intro to the class yesterday?",
    "the students liked your intro about connectionism yesterday",
    "what did we cover in class this morning?",
    "what did you tell the class?",
])
def test_asked_for_what_was_said_to_a_class(text):
    assert asks_for_class_reply(text)


@pytest.mark.parametrize("text", [
    INTRO_AGAIN, "we are in the class rightnow",
    "don't repeat the intro you gave yesterday",
    "I want you to stop repeating that",                  # 529
    "introduce the topic again",
])
def test_not_asked_for_what_was_said_to_a_class(text):
    assert not asks_for_class_reply(text)


def test_repeat_is_no_recall_ask_for_the_other_blocks():
    """Only a reply said to a class is kept for "repeat …": the re-ask and
    the answers about himself keep their own, wide, recall cue."""
    assert not asks_for_recall("can you repeat the introduction you gave the class?")


REPEAT_INTRO = "can you repeat the introduction you gave the class?"


def test_asked_to_repeat_the_class_intro_recent_history_has_it(log, monkeypatch):
    assert "Welcome to Week 4" in _recent_history(log, monkeypatch, REPEAT_INTRO)
    # Told not to, he is not shown it.
    assert "Welcome to Week 4" not in _recent_history(
        log, monkeypatch, "don't repeat the intro you gave the class")


def test_asked_to_repeat_the_class_intro_conversation_memory_has_it(
        continuity_module):
    route = continuity_module
    route.note_exchange("blue", INTRO_ASK, INTRO)
    block = route.conversation_memory_block(
        "blue", query=REPEAT_INTRO, chat_turn=True,
        live_thread=[{"role": "user", "content": REPEAT_INTRO}])
    assert "Welcome to Week 4" in block


def test_a_class_reply_through_the_chat_route_is_not_quoted(chat, journal):
    """10143's request, rebuilt: the 09:33 introduction from another window
    is in the journal, and the model is not shown it to say again."""
    journal.HUB["blue"].note_exchange(INTRO_ASK, INTRO, user_name="Alex", tools=[],
                                      source="chat", enqueue_reflection=False)

    reply_of(chat.ask(INTRO_AGAIN))

    sent = _sent(chat)
    assert "Welcome to Week 4" not in sent
    assert f"Alex said: {INTRO_ASK} (Your reply wording is omitted" in sent


# ---- (c) a request asked again in other words ---------------------------------

@pytest.mark.parametrize("old, live", [
    (INTRO_ASK, INTRO_AGAIN),
    (INTRO_AGAIN, INTRO_ASK),
    ("can you introduce the topic to the class?", INTRO_ASK),          # 10115, 10126
    ("Can you introduce the course to the students as well?",
     "i want you to introduce the course to the students"),            # 5034, 9679
    ("Can you send an e-mail to levant@rogers.com saying hello.",
     "Send an e-mail to levant@rogers.com saying hello."),             # 357, 371
    ("Can you explain what abstractive media is.",
     "I want you to explain what abstractive media means."),           # 1977, 2007
])
def test_a_request_asked_again_in_other_words_is_a_reask(old, live):
    assert is_reask(old, live)


@pytest.mark.parametrize("old, live", [
    # Two content words each: on and off are not told apart.
    ("Turn off all the lights.", "Turn on all the lights."),
    ("Make all the lights blue.", "Make all the lights red."),
    # A question about someone, framed as a request.
    ("Can you tell me what Sarah Matthews said about the AI lab?",
     "What did Sarah Matthews say about the AI lab?"),
    ("can you introduce the course DH399 to the class?",
     "tell me the class schedule for the course"),
    # Another request with the same verb.
    (INTRO_ASK, "introduce yourself to the class"),
    ("introduce the class to CMDS4740",
     "i want you to introduce yourself to the class cmds4740"),       # 5026, 5378
    # A remark has no request in it.
    ("the girls are at dance tonight", "the girls are at dance practice tonight"),
    # The same words for something else: a word in place of one of them, a
    # number, a colour, or the other way.
    ("Navigate to the star and tell me the current headlines for today.",
     "I want you to navigate to the guardian and tell me the current "
     "headlines for today."),                                         # 120, 171
    ("Navigate to thestar.com and summarize today's headlines.",
     "I want you to navigate to theguardian.com and summarize today's "
     "headlines."),                                                   # 175, 491
    ("give me three ideas for the dh201 lab on local models",
     "give me three ideas for the dh399 lab on local models"),
    ("introduce the course to thte class",
     "can you introduce the course DH399 to the class?"),             # 9799, 9887
    ("remind me to call mom at 5pm tomorrow",
     "remind me to call dad at 5pm tomorrow"),
    ("play some jazz music in the office", "play some rock music in the office"),
    ("draft an email to the class about the lab tomorrow",
     "draft an email to the class about the quiz tomorrow"),
    ("set the living room lights to 20 percent",
     "set the living room lights to 80 percent"),
    ("set the living room lights to green", "set the living room lights to red"),
    ("turn off the living room lights", "turn on the living room lights"),
    ("turn on the living room lights", "turn off the living room lights"),
    ("turn the bedroom lights off at ten", "turn the bedroom lights on at ten"),
    ("coffee with sarah this morning was lovely",
     "coffee with sarah this morning was awkward"),
])
def test_another_request_or_a_remark_is_not(old, live):
    assert not is_reask(old, live)


@pytest.mark.parametrize("old, live", [
    # "on" as a preposition on one side only (7197, 7205).
    ("cmds4740 ends august 4. revise my calendar",
     "revise my calendar to end cmds4740 on august 4"),
    # His name at the end, not a colour (5974, 148).
    ("Turn off all the lights.", "Turn off all the lights blue."),
])
def test_a_request_asked_again_keeps_its_marks(old, live):
    assert is_reask(old, live)


def test_a_pasted_text_is_no_request():
    """Two pasted meeting minutes share their action items (8929, 8931)."""
    item = "\nVolunteer for the curriculum committee by contacting the chair.\n"
    may = ("CS Department Meeting Minutes\nDate: May 1/2026\nLocation: DAWB "
           "5-103\nChair: J. Miller\nThe budget report was received and the "
           "hiring plan for two positions was carried after discussion of the "
           "spring term schedule and the certificate in podcasting." + item)
    june = ("minutes or past meetings: CS Department Meeting Minutes\nDate: "
            "June 18, 2026\nThe tenure and promotion procedure was approved; "
            "Stinson and Hunsinger reported on graduate admissions, the new "
            "lab space and the library acquisitions for the coming year." + item)
    assert len(may) > 300 and len(june) > 300
    assert not is_reask(may, june) and not is_reask(june, may)
    # The same item, said on its own, is a request.
    assert is_reask(item, "can you volunteer for the curriculum committee by "
                          "contacting the chair")


# ---- (d) a quote is plain words ----------------------------------------------

def test_a_quote_loses_bold_headings_and_list_marks_but_keeps_every_item():
    reply = ("### **The Blue Project as Critical Infrastructure**\n"
             "Here is why, from *A Brief History of AI* [DH201_AL_2026F.docx]:\n\n"
             "1. **Data Privacy:** your data never leaves.\n"
             "2. **Reliability:** no outages.\n"
             "*   Jonathan_Roberge_-_Machine_Learning__An_Incursion.pdf\n"
             "---\n"
             "That is the case for it.")
    assert quotable_reply(reply) == (
        "The Blue Project as Critical Infrastructure\n"
        "Here is why, from A Brief History of AI [DH201_AL_2026F.docx]:\n\n"
        "Data Privacy: your data never leaves.\n"
        "Reliability: no outages.\n"
        "Jonathan_Roberge_-_Machine_Learning__An_Incursion.pdf\n\n"
        "That is the case for it.")


def test_a_quote_loses_an_offer_menu_but_keeps_what_came_before():
    # 1944, 09-09: the whole reply after its first sentence is a menu.
    reply = ("That is exciting! Since the class begins today with a focus on "
             "**Abstractive Media**, would you like me to:\n\n"
             "1. Prepare a **lecture outline** for the first session?\n"
             "2. Generate some **discussion questions**?")
    assert quotable_reply(reply) == "That is exciting!"
    # Only a menu: its items stay, unmarked.
    assert plain_quote("Would you like me to:\n- Draft it\n- Send it") == (
        "Would you like me to:\nDraft it\nSend it")
    assert plain_quote("If you'd like, I can:\n- Write a story\n\nOr not.") == (
        "Or not.")
    assert plain_quote("What would you like me to look at? I can:\n- Read it\n"
                       "- Sum it up\n\nAnyway.") == "Anyway."
    # An item that runs on to a second line goes with it, not left behind
    # as a statement.
    assert plain_quote("Done. Would you like me to:\n1. Search the web\n"
                       "   for more on this\n2. Email it\nto you\n\nThat's all.") == (
        "Done.\nThat's all.")


@pytest.mark.parametrize("lead", [
    "Here are four ideas:", "What I CAN remember:",
    "I can see 3 documents in your library:",
    "I can infer that the readings likely center on:",
    # What he can do, said as the answer, is content too: "how can you be
    # helpful in this class" (9702), "What role do you think you could play
    # in this course" (1946), and the capability lists of 6654 and 7290.
    "Here is how I can be useful:",
    "Here's how I can support CS240J-VS:",
    "Here are a few ways I could support the Laurier meeting:",
    "I can help with a wide variety of tasks, including:",
    "I can:",
    # What the listener can do (4659).
    "If you want me to look, you can:",
])
def test_a_list_he_gave_as_an_answer_is_no_menu(lead):
    assert plain_quote(f"Good timing. {lead}\n1. A cluster.\n2. A library.") == (
        f"Good timing. {lead}\nA cluster.\nA library.")


# 9702, to "how can you be helpful in this class" (09-10).
HELPFUL = (
    "As your assistant for CS101A: Canadian Communication in Context, I’m here "
    "to help you stay sharp and organized. Here is how I can be useful:\n\n"
    "* **Syllabus Navigation:** I can pull specific details from the course "
    "document.\n"
    "* **Lecture Prep:** I can help draft discussion questions based on the "
    "weekly readings.\n"
    "* **Schedule Management:** I can set reminders for when assignments are "
    "due.\n\n"
    "Essentially, I handle the retrieval and organization so you can focus on "
    "the delivery.")


def test_what_he_said_he_could_do_for_the_class_is_quoted_whole():
    quoted = quotable_reply(HELPFUL)
    for item in ("Syllabus Navigation: I can pull", "Lecture Prep: I can help",
                 "Schedule Management: I can set"):
        assert item in quoted
    assert "**" not in quoted and "* " not in quoted


# The 07-29 Laurier ideas, as a list under a lead-in (test_memory_recall has
# them as prose). Asked for them back on 07-31, Blue invented four others.
IDEAS_LIST = (
    "Good timing. Here are a few ways I could support the Laurier meeting on "
    "local open-source AI:\n"
    "1. **A campus inference cluster**: a small sovereign compute pool that "
    "runs open-weight models for teaching, so student data never leaves the "
    "province.\n"
    "2. **A cooperative model library** shared with Waterloo and Conestoga, "
    "with a common evaluation harness and a licensing review.\n"
    "3. **A humanities-led pilot** where DH399 students audit a local model's "
    "training data and write its documentation.\n"
    "4. **A public workshop series** on running open-source models on modest "
    "hardware, for nonprofits and municipal offices in the region.")


def test_the_july_31_recall_has_the_ideas_given_as_a_list(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [(_at(68, 9, 10), "user", FOUR_IDEAS_ASK),
                   (_at(68, 9, 11), "assistant", IDEAS_LIST)])
    _seed(memory, [
        (_at(40, 6, minute), "assistant",
         f"Here is the plan for chore list {minute}: " + " ".join(
             f"Step {step}: we can tidy the kitchen, water the garden and sort "
             "the recycling before the weekend." for step in range(8)))
        for minute in range(30)])
    thread = ["the laurier meeting on local open-source ai went well",
              "I'm glad the Laurier meeting went well.",
              "what were those ideas you gave me?"]

    block = memory._build_past_answers_block(_ask(*thread), thread[-1],
                                             chat_turn=True)

    for idea in ("A campus inference cluster", "A cooperative model library",
                 "A humanities-led pilot", "A public workshop series"):
        assert idea in block
    assert "**" not in block


def test_the_sb107_quote_comes_without_bold():
    assert "**" not in quotable_reply(IN_CLASS_REPLY)
    assert "in front of the class in SB107 for DH201" in quotable_reply(IN_CLASS_REPLY)
