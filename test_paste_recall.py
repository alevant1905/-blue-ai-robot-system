"""Recall names a pasted document; it never quotes or matches on it.

Run with: python -m pytest test_paste_recall.py

On 07-13 Alex pasted the transcript of a Princeton event into chat
(conversation_log 6893/6894, 99.5k characters each). By its own words it
shares two terms with nearly any question, so it out-ranked every real
exchange: it sat in <remembered_days> as the "POSITIVE MATCH for the current
question" on 53 of 103 harness turns (2026-10-05), and "what did we talk
about yesterday?" was answered with 420 characters of it. An attached
Reigeluth and Castelle chapter rode in <j_space> on 112 of 116, its first 360
characters quoted in the exchange summary.

Only a chat turn is read as a paste when it is long. The email auto-reply,
panel and duet assemble their queries from several pieces past 2,000
characters, and those still search by their own words (the last section).

Every block here is built against a scratch database or a temporary J-space
store, never the live ones.
"""

import datetime
from datetime import timedelta

import pytest

import bluetools as bt  # before blue.server.*: the package imports it

from blue_identity import (
    bulk_paste_recall_words,
    bulk_paste_stub,
    is_bulk_paste,
    recalled_evidence_fallback,
)
from blue_memory_improved import EnhancedMemorySystem
from test_bluejspace import continuity_module  # noqa: F401  (fixture)
from test_chat_pipeline import chat, reply_of  # noqa: F401  (fixture)

# The 07-13 paste, rebuilt to its size: a talk transcript that says "talk",
# "yesterday", "consciousness" and "Princeton" over and over.
TRANSCRIPT_LINE = (
    "0:066 secondsUh welcome uh to this event. Uh I'm Sanji Verora, director "
    "of Princeton Language and Intelligence. Today's talk is about "
    "consciousness and whether it could arise in AI models, as the speaker "
    "said yesterday.")
PASTE = ("hers the transcript: \nSearch transcript\nChapter 1: Introduction\n"
         + "\n".join([TRANSCRIPT_LINE] * 560))
PASTE_WORDS = ("Sanji", "Princeton", "welcome uh", "Search transcript")

# 10071's shape: the chapter between triple quotes, Alex's ask after it.
CHAPTER = ("CHAPTER 3\nWhat Kind of Learning Is Machine Learning?\nTyler "
           "Reigeluth and Michael Castelle\nIntroduction\nAt the outset of his "
           "1803 lectures on pedagogy, Kant famously stated that the human "
           "being is the only creature that must be educated. ") * 60
ATTACHED = (
    "[Attached document: Jonathan Roberge, Michael Castelle - The Cultural "
    "Life of Machine Learning_ An Incursion into Critical AI Studies-Palgrave "
    "Macmillan (2021)-91-127.pdf]\n\"\"\"\n" + CHAPTER + "\n\"\"\"\n\n"
    "produce a Reading Report for the attached article by rogerge and "
    "castelle for dh399")
CHAPTER_WORDS = ("CHAPTER 3", "What Kind of Learning", "Kant", "pedagogy")

# 8885, typed at length: the longest user turn in the log that is not a paste.
TYPED = ("i'm still working on the course outlines. here are the course "
         "descriptions. " + "that one is the intro course and it covers "
         "generative ai from the ground up, with weekly labs. " * 18)


def test_the_paste_is_named_by_its_first_line():
    stub = bulk_paste_stub(PASTE, "Alex")
    assert stub == f"Alex shared a long document: 'hers the transcript:' ({len(PASTE):,} chars)"
    assert len(PASTE) > 99000


def test_an_attachment_is_named_with_the_words_said_beside_it():
    stub = bulk_paste_stub(ATTACHED, "Alex")
    assert stub.startswith(
        "Alex shared a document: 'Jonathan Roberge, Michael Castelle - The "
        "Cultural Life of…'")
    assert stub.endswith(
        ', saying: "produce a Reading Report for the attached article by '
        'rogerge and castelle for dh399"')
    assert not any(word in stub for word in CHAPTER_WORDS)


def test_two_attachments_and_an_unclosed_one():
    two = ('[Attached document: DH399 AL 2026F.pdf]\n"""\nWeek 1\n"""\n'
           '[Attached document: DH201 AL 2026F.pdf]\n"""\nWeek 1\n"""\n'
           "here are the other two courses")
    assert bulk_paste_stub(two, "Alex").startswith(
        "Alex shared 2 documents, first: 'DH399 AL 2026F.pdf'")
    assert bulk_paste_recall_words(two) == (
        "DH399 AL 2026F.pdf DH201 AL 2026F.pdf here are the other two courses")
    # Cut off before its closing quotes: only the words before it are his.
    unclosed = 'what is this? [Attached document: notes.md]\n"""\n' + "Week 1 " * 400
    assert bulk_paste_recall_words(unclosed) == "notes.md what is this?"


def test_typed_text_is_not_a_paste():
    assert 1700 < len(TYPED) < 2000
    assert not is_bulk_paste(TYPED)
    assert bulk_paste_stub(TYPED) == ""
    assert bulk_paste_recall_words(TYPED) == TYPED
    assert not is_bulk_paste("what did we talk about yesterday?")


def test_a_paste_offers_no_words_to_search_by():
    """Nothing marks where Alex's words end in a long paste; an attachment
    is found by its name and the ask."""
    assert bulk_paste_recall_words(PASTE) == ""
    words = bulk_paste_recall_words(ATTACHED)
    assert "Castelle" in words and "Reading Report" in words
    assert not any(word in words for word in CHAPTER_WORDS)


# --------------------------------------------------------------------------
# <remembered_days>, <earlier_sessions>, <recent_history>, <earlier_answers>
# --------------------------------------------------------------------------

def _at(days_ago, hour, minute=0):
    return (datetime.datetime.now() - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def _seed(memory, rows):
    conn = memory._conn()
    for when, role, content in rows:
        conn.execute(
            "INSERT INTO conversation_log (timestamp, user_name, role, content, "
            "session_id, importance, robot) VALUES (?, 'Alex', ?, ?, NULL, 5, 'blue')",
            (when.isoformat(), role, content))
    conn.commit()
    conn.close()


@pytest.fixture
def scratch(tmp_path):
    """07-13 as it was logged (84 days back), and a Friday three days ago."""
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [
        (_at(84, 10, 36), "user",
         "get the transcript https://www.youtube.com/watch?v=55kStwlulEg"),
        (_at(84, 10, 36), "assistant",
         "I can't pull the transcript directly from YouTube. If you paste the "
         "transcript here, I can work with it."),
        (_at(84, 10, 37), "user", PASTE),
        (_at(84, 10, 37), "user", PASTE.split("\n", 1)[1]),
        (_at(84, 10, 38), "user", "too big?"),
        (_at(84, 10, 38), "assistant", "I'm having trouble connecting."),
        (_at(84, 10, 38), "user", "okay"),
        (_at(3, 11, 0), "user", "lets wrap up the agents unit outline"),
        (_at(3, 11, 1), "assistant", "Done — the outline has four weeks."),
    ])
    return memory


def test_yesterday_is_not_answered_from_the_july_paste(scratch):
    """recall_thread[1]: nothing was said yesterday, and the paste matched
    "what did we talk about yesterday?" on "talk" and "yesterday"."""
    block = scratch._build_recalled_days_block(
        "what did we talk about yesterday?", robot="blue")
    assert not any(word in block for word in PASTE_WORDS)
    assert block == ""


def test_a_paste_is_no_anchor_by_its_own_words(scratch):
    block = scratch._build_recalled_days_block(
        "what did the princeton speaker say about consciousness?", robot="blue")
    assert block == ""


def test_a_paste_inside_a_recalled_exchange_is_one_line(scratch):
    block = scratch._build_recalled_days_block(
        "do you remember the youtube transcript i asked you to get?",
        robot="blue")

    assert "Alex: get the transcript https://www.youtube.com" in block
    assert f"  Alex shared a long document: 'hers the transcript:' ({len(PASTE):,} chars)" in block
    assert block.count("hers the transcript") == 1
    assert "Alex: too big?" in block
    assert not any(word in block for word in ("Sanji", "Princeton", "welcome uh"))
    assert len(block) < 2000

    # The recall guard's last resort names it from the same block.
    reply = recalled_evidence_fallback(block, user_name="Alex")
    assert reply.startswith(
        'I found the recorded exchange from ' + scratch._friendly_day_label(
            _at(84, 0).date().isoformat())
        + '. You said: "get the transcript https://www.youtube.com/watch?v=55kStwlulEg". '
        'Later you sent a long message that starts "hers the transcript…". '
        'Later you sent a long message that starts "Search transcript…".')
    assert "Sanji" not in reply and "Princeton" not in reply


def test_the_fallback_names_an_attachment_stub():
    block = ("<remembered_days>\n- 3 days ago (Friday):\n"
             f"  {bulk_paste_stub(ATTACHED, 'Alex')}\n"
             "  Blue: Here is a reading report draft.\n"
             "  Alex: thanks\n</remembered_days>")
    reply = recalled_evidence_fallback(block, user_name="Alex")
    assert reply.startswith(
        "I found the recorded exchange from 3 days ago (Friday). You shared "
        'the document "Jonathan Roberge, Michael Castelle - The Cultural Life '
        'of" and said: "produce a Reading Report')
    assert 'You later said: "thanks".' in reply
    assert not any(word in reply for word in CHAPTER_WORDS)


def test_an_attachment_is_named_inside_an_excerpt_but_never_its_anchor(scratch):
    _seed(scratch, [
        (_at(4, 14, 14), "user",
         "i'm sending you the castelle chapter for the dh399 reading report"),
        (_at(4, 14, 15), "user", ATTACHED),
        (_at(4, 14, 16), "assistant", "Here is a reading report draft for "
         "the Reigeluth & Castelle chapter."),
    ])
    block = scratch._build_recalled_days_block(
        "remember the castelle reading report?", robot="blue")
    assert "Alex: i'm sending you the castelle chapter" in block
    assert f"  {bulk_paste_stub(ATTACHED, 'Alex')}\n" in block
    assert "Here is a reading report draft" in block
    assert not any(word in block for word in CHAPTER_WORDS)
    # Only the words beside the attachment say "rogerge": no anchor.
    assert scratch._build_recalled_days_block(
        "what did i say about rogerge?", robot="blue") == ""


def test_a_reply_reading_the_paste_back_is_not_quoted(scratch):
    """8274's shape: a pasted blog post, and "Playing " + all of it lowered
    as Blue's turn. Inside an excerpt the paste is a stub and its echo goes."""
    post = ("What Makes Us Human?\nRethinking the brain, emotion, art, and "
            "intelligence in the age of AI\n" + "Before I finally decided to "
            "read the neuroscience, I assumed feeling was computation. " * 30)
    _seed(scratch, [
        (_at(5, 8, 45), "user", "can you read this blog post about being human"),
        (_at(5, 8, 46), "user", post),
        (_at(5, 8, 47), "assistant", "Playing " + post.lower()),
        (_at(5, 8, 48), "user", "whats its main claim"),
        (_at(5, 8, 49), "assistant",
         "It argues that emotion is the ground of intelligence, not an add-on."),
    ])
    block = scratch._build_recalled_days_block(
        "remember the blog post about being human?", robot="blue")
    assert "Alex: can you read this blog post about being human" in block
    assert "  Alex shared a long document: 'What Makes Us Human?'" in block
    assert "Playing" not in block
    assert "finally decided" not in block.lower()
    assert "It argues that emotion is the ground" in block


def test_earlier_sessions_name_a_paste(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [
        (_at(2, 10, 37), "user", PASTE),
        (_at(2, 10, 38), "user", "too big?"),
        (_at(2, 11, 0), "user", ATTACHED),
    ])
    block = memory._build_session_history_block(robot="blue")
    assert "Alex shared a long document: 'hers the transcript:'" in block
    assert bulk_paste_stub(ATTACHED, "Alex") in block
    assert "Alex: too big?" in block
    assert not any(word in block for word in PASTE_WORDS[:3] + CHAPTER_WORDS)


def test_recent_history_names_a_paste(tmp_path, monkeypatch):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    now = datetime.datetime.now()
    _seed(memory, [
        (now - timedelta(hours=3), "user", PASTE),
        (now - timedelta(hours=3), "assistant",
         "That's a long transcript — want me to pull out the main argument?"),
        (now - timedelta(hours=2), "user", ATTACHED),
        (now - timedelta(hours=2), "assistant",
         "Here is a reading report draft for the Reigeluth & Castelle chapter."),
    ])
    # Only <recent_history> is under test; the other blocks read nothing.
    for name in ("_build_facts_block", "_build_user_notes_block",
                 "get_proactive_memories", "_build_last_conversation_block",
                 "_build_session_history_block", "_build_recalled_days_block",
                 "_build_past_answers_block", "_build_rhythms_block",
                 "_build_connections_block"):
        monkeypatch.setattr(memory, name, lambda *a, **k: "")
    monkeypatch.setattr(memory, "search_memories", lambda *a, **k: [])

    parts = memory.build_context(
        [{"role": "user", "content": "where were we?"}], user_name="Alex")
    history = next(p["content"] for p in parts
                   if "<recent_history>" in p["content"])
    assert "USER: Alex shared a long document: 'hers the transcript:'" in history
    assert "USER: " + bulk_paste_stub(ATTACHED, "Alex") in history
    assert "Here is a reading report draft" in history
    assert not any(word in history for word in PASTE_WORDS[:3] + CHAPTER_WORDS)


def test_earlier_answers_are_not_searched_by_a_pasted_document(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    thread = [{"role": "user", "content": PASTE},
              {"role": "assistant", "content": "Want the main argument?"}]
    terms = memory._topic_query_terms(
        thread, "what do you make of it?", chat_turn=True)
    assert not terms & {"consciousness", "princeton", "sanji", "transcript"}
    # The live turn itself: an attachment searches by its name and the ask.
    terms = memory._topic_query_terms([], ATTACHED, chat_turn=True)
    assert {"castelle", "reading", "report"} <= terms
    assert not terms & {"pedagogy", "kant", "creature", "educated"}


def test_the_day_recap_names_a_paste(tmp_path, monkeypatch):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [
        (_at(2, 10, 37), "user", PASTE),
        (_at(2, 10, 38), "user", "too big?"),
        (_at(2, 11, 0), "user", ATTACHED),
    ])
    seen = []
    monkeypatch.setattr(memory, "_summarize_transcript",
                        lambda transcript, day: seen.append(transcript) or ("", ""))
    memory.summarize_session(_at(2, 0).date().isoformat())
    assert seen and "USER: Alex shared a long document: 'hers the transcript:'" in seen[0]
    assert "USER: " + bulk_paste_stub(ATTACHED, "Alex") in seen[0]
    assert not any(word in seen[0] for word in PASTE_WORDS[:3] + CHAPTER_WORDS)


# --------------------------------------------------------------------------
# J-space: <j_space>, <conversation_memory>, <dated_episode_recall>
# --------------------------------------------------------------------------

REPORT = ("Sure—here's the core of it: Reigeluth and Castelle argue that we've "
          "lost sight of how fundamentally social learning is.")


def test_a_pasted_document_is_one_line_in_j_space(continuity_module):
    route = continuity_module
    route.note_exchange("blue", ATTACHED, REPORT, user_name="Alex")

    episode = route.HUB["blue"].store.list_episodes(kind="exchange")[0]
    stub = bulk_paste_stub(ATTACHED, "Alex")
    assert episode["summary"] == f"{stub} Blue replied: {REPORT}"
    assert episode["details"]["user_text_stub"] == stub
    # The reflection worker still reads the document.
    assert "What Kind of Learning" in episode["details"]["user_text"]

    for block in (route.jspace_context_block("blue"),
                  route.conversation_memory_block("blue", query="castelle"),
                  route.temporal_recall_block(
                      "blue", "what do you remember from today?")):
        assert stub in block
        assert not any(word in block for word in CHAPTER_WORDS)


def test_an_exchange_recorded_before_the_stub_is_named_too(continuity_module):
    """10103 as it sits in Blue's journal: the summary quotes the chapter and
    the stored text stops at 5,000 characters."""
    route = continuity_module
    kept = ATTACHED[:4997].rstrip() + "..."
    route.HUB["blue"].store.append_episode(
        kind="exchange", source="chat",
        summary=f"Alex asked: {' '.join(ATTACHED.split())[:357]}... Blue replied: {REPORT}",
        details={"user_text": kept, "reply": REPORT, "tool_count": 0},
        participants=["Alex", "Blue"], salience=0.7)

    block = route.jspace_context_block("blue")
    # Its length is unknown, and the ask after the chapter was cut off. A
    # chat exchange in <j_space> is named by what was asked, not the reply.
    assert ("Alex shared a document: 'Jonathan Roberge, Michael Castelle - The "
            "Cultural Life of…' — you answered.") in block
    assert "Sure—here's the core" not in block
    assert not any(word in block for word in CHAPTER_WORDS)
    memory = route.conversation_memory_block("blue", query="castelle chapter")
    assert "Alex shared a document" in memory
    assert "Sure—here's the core" in memory
    assert not any(word in memory for word in CHAPTER_WORDS)


def test_a_paste_is_not_retrieved_by_its_own_words(continuity_module):
    route = continuity_module
    route.note_exchange("blue", PASTE, "That's a long transcript.", user_name="Alex")
    for index in range(6):
        route.note_exchange("blue", f"Routine check-in {index}",
                            f"Routine answer {index}", user_name="Alex")

    block = route.conversation_memory_block(
        "blue", query="what did the princeton speaker say about consciousness?")
    assert "Routine check-in 5" in block
    assert "hers the transcript" not in block
    assert not any(word in block for word in PASTE_WORDS)


def test_a_long_duet_line_is_not_taken_for_a_paste(continuity_module):
    route = continuity_module
    line = "Governance is about who can refuse. " * 70
    route.note_duet_line("blue", "Hexia", line, "Then refusal belongs in the design.")
    episode = route.HUB["blue"].store.list_episodes(kind="exchange")[0]
    assert episode["summary"].startswith("Hexia asked: Governance is about")
    assert "shared a long document" not in route.jspace_context_block("blue")


# --------------------------------------------------------------------------
# Through the pipeline
# --------------------------------------------------------------------------

# The 10-05 harness draft, verbatim.
RECALL_DRAFT = (
    "I don't have a record of us talking yesterday — our last conversation was "
    "actually Friday, three days ago, when we wrapped up that DH399 reading "
    "report on Reigeluth and Castelle. So if something came up on Sunday or "
    "Saturday, I'm not holding it; want to fill me in?")


def test_recall_thread_prompt_carries_no_paste(chat, scratch, monkeypatch):
    """recall_thread[1] with the 07-13 rows: nothing of the transcript
    reaches the prompt as a remembered day, and the honest draft ships."""
    monkeypatch.setattr(bt.memory_system, "_build_recalled_days_block",
                        scratch._build_recalled_days_block)
    monkeypatch.setattr(bt.memory_system, "has_conversation_on",
                        scratch.has_conversation_on)
    chat.model.queue(RECALL_DRAFT, "")
    reply = reply_of(chat.ask("what did we talk about yesterday?"))

    assert reply.startswith("I don't have a record of us talking yesterday")
    sent = " ".join(str(message.get("content") or "")
                    for payload in chat.model.payloads
                    for message in payload["messages"])
    assert "<remembered_days>" not in sent


def test_the_chat_route_says_its_turn_is_a_chat_turn(chat, monkeypatch):
    """Only the chat route reads a long message as a paste; it says so to
    both builders, and nobody else does (the tests below)."""
    seen = {}

    def build_context(messages, user_name="Alex", robot="blue", chat_turn=False):
        seen["context"] = chat_turn
        return []

    def conversation_memory_block(robot, query="", max_lines=9,
                                  include_humans=True, include_robots=True,
                                  include_banter_wording=True, chat_turn=False,
                                  live_thread=()):
        seen["journal"] = chat_turn
        # The browser's thread, so the journal leaves out what it carries.
        seen["thread"] = [m.get("content") for m in live_thread
                          if m.get("role") in ("user", "assistant")]
        return ""

    monkeypatch.setattr(bt.memory_system, "build_context", build_context)
    monkeypatch.setattr(bt._continuity_routes, "conversation_memory_block",
                        conversation_memory_block)
    chat.model.queue("We talked about the Laurier lab.")
    reply_of(chat.ask("what did we say about the laurier lab?", messages=[
        {"role": "user", "content": "the laurier meeting went well"},
        {"role": "assistant", "content": "Glad to hear it."},
        {"role": "user", "content": "what did we say about the laurier lab?"},
    ]))
    assert seen == {"context": True, "journal": True, "thread": [
        "the laurier meeting went well", "Glad to hear it.",
        "what did we say about the laurier lab?"]}


# --------------------------------------------------------------------------
# The same builders outside chat: email, panel, duet
# --------------------------------------------------------------------------
# Their queries are assembled from several pieces and pass 2,000 characters
# without being a paste. Read as one, they searched by nothing (review of
# 3231805): an email quoting Blue's Laurier answer lost <remembered_days> and
# <earlier_answers>, a panel query its recall of the Laurier lab.

LAURIER_ASK = "i need four ideas for the laurier meeting on local open-source ai in canada"
LAURIER_ANSWER = (
    "Here are four ideas for the Laurier meeting on local open-source AI in "
    "Canada. First, a campus inference cluster: a small sovereign compute pool "
    "that runs open-weight models for teaching, so student data never leaves "
    "the province. Second, a cooperative model library shared with Waterloo "
    "and Conestoga, with a common evaluation harness and a licensing review. "
    "Third, a humanities-led pilot where DH399 students audit a local model's "
    "training data and write its documentation. Fourth, a public workshop "
    "series on running open-source models on modest hardware, for nonprofits "
    "and municipal offices in the region. Each could start within a term, and "
    "the cluster is the one the others lean on.")


@pytest.fixture
def laurier(scratch):
    """The scratch DB plus the 07-29-shaped exchange, and thirty unrelated
    long answers so a Laurier term is rare in Blue's writing, as it is."""
    _seed(scratch, [
        (_at(68, 9, 10), "user", LAURIER_ASK),
        (_at(68, 9, 11), "assistant", LAURIER_ANSWER),
        (_at(68, 9, 14), "user", "the cluster sounds strongest to me"),
    ])
    # Numbered steps: one sentence said eight times is a loop, and a loop is
    # not an earlier answer.
    _seed(scratch, [
        (_at(40, 6, minute), "assistant",
         f"Here is the plan for chore list {minute}: " + " ".join(
             f"Step {step}: we can tidy the kitchen, water the garden and sort "
             "the recycling before the weekend." for step in range(8)))
        for minute in range(30)
    ])
    return scratch


def _laurier_email():
    """bluetools._generate_reply_for_email's memory anchor for a reply to the
    07-29 thread: the subject, then the body cut at 2,000 characters."""
    quoted = "\n".join("> " + line for line in LAURIER_ANSWER.split(". "))
    earlier = "\n".join(["> > " + LAURIER_ASK] * 20)
    body = (
        "Hi Blue,\n\nThanks for the detailed development notes. Of the four "
        "Laurier ideas, which one do you think is strongest, and which should I "
        "bring to the dean first?\n\nAlex\n\nOn Wed, Jul 29, 2026, Blue wrote:\n"
        + quoted + "\n" + earlier)[:2000]
    return f"Re: Detailed Development: Local Open-Source AI in Canada\n{body}"


def test_an_email_quoting_blue_still_recalls_the_exchange(laurier, monkeypatch):
    anchor = _laurier_email()
    assert len(anchor) > 2000 and is_bulk_paste(anchor)
    # Only the two recall blocks are under test.
    for name in ("_build_facts_block", "_build_user_notes_block",
                 "get_proactive_memories", "_build_last_conversation_block",
                 "_build_session_history_block", "_build_rhythms_block",
                 "_build_connections_block"):
        monkeypatch.setattr(laurier, name, lambda *a, **k: "")
    monkeypatch.setattr(laurier, "search_memories", lambda *a, **k: [])

    parts = laurier.build_context(
        [{"role": "user", "content": anchor}], user_name="Alex")
    text = "\n".join(p["content"] for p in parts)
    days = next(p["content"] for p in parts if "<remembered_days>" in p["content"])
    answers = next(p["content"] for p in parts if "<earlier_answers>" in p["content"])
    assert f"Alex: {LAURIER_ASK}" in days
    assert "a campus inference cluster" in answers
    assert not any(word in text for word in PASTE_WORDS)


def _panel_recall_query():
    """panel.py's recall_query: the topic, the live line and the last four
    lines, cut at 2,200. Continuous turns repeat history[-1] as the live line."""
    topic = "Should Laurier build its own local AI lab?"
    history = [
        "Blue: I keep coming back to the compute question. A lab that rents "
        "every cycle from a cloud vendor is not local in any sense that "
        "matters, and the students notice that. If Laurier wants a lab, it "
        "needs hardware it owns, even if that hardware is modest. " * 2,
        "Hexia: Owning hardware is the easy part to picture and the hard part "
        "to staff. Who maintains it in August when the graduate students are "
        "gone? I would rather see the faculty commit a technician before "
        "anyone signs a purchase order. " * 2,
        "Casper: You are both skipping the interesting bit, which is what the "
        "lab is for. A room full of machines is a server closet. A lab has a "
        "question it is trying to settle, and that question should come from "
        "the humanities side first. " * 2,
        "Blue: Fair, and the question could be the one the DH399 students "
        "already ask: what is in the training data, and who decided? A local "
        "lab lets them open the box instead of reading about it. " * 2,
    ]
    live = history[-1]
    tail = " ".join(history[-4:])
    return f"{topic} {live} {tail}".strip()[:2200]


def test_a_panel_query_still_recalls_the_lab_conversation(laurier):
    query = _panel_recall_query()
    assert len(query) > 2000 and is_bulk_paste(query)
    block = laurier._build_recalled_days_block(query, robot="blue")
    assert f"Alex: {LAURIER_ASK}" in block
    assert not any(word in block for word in PASTE_WORDS)
    # Read as a chat turn's paste, the same text searches by nothing.
    assert laurier._build_recalled_days_block(
        query, robot="blue", chat_turn=True) == ""


def test_a_panel_query_still_ranks_the_journal(continuity_module):
    route = continuity_module
    route.note_exchange("blue", LAURIER_ASK, LAURIER_ANSWER, user_name="Alex")
    for index in range(6):
        route.note_exchange("blue", f"Routine check-in {index}",
                            f"Routine answer {index}", user_name="Alex")
    query = _panel_recall_query()
    # As panel.py:601 calls it.
    block = route.conversation_memory_block(
        "blue", query=query, max_lines=5, include_humans=True,
        include_robots=True, include_banter_wording=False)
    assert "four ideas for the laurier meeting" in block
    assert route.conversation_memory_block(
        "blue", query=query, max_lines=5, include_humans=True,
        include_robots=True, include_banter_wording=False,
        chat_turn=True).count("laurier") == 0
    # A duet's query (duet.py:3540): the topic and the last two lines.
    duet_query = "Local AI at Laurier " + " ".join(
        ["Hexia: the lab is a question before it is a room. " * 25] * 2)
    assert len(duet_query) > 2000
    assert "four ideas for the laurier meeting" in route.conversation_memory_block(
        "blue", query=duet_query, max_lines=7)
