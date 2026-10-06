"""Regression tests for name-aware memory recall.

Run with: python -m pytest test_memory_recall.py

These pin the behaviour behind a real failure (2026-07-31): Alex asked about
his meeting with "Sarah Matthews" and Blue said he had no record of it. The
record existed, but Blue had earlier corrected the spelling to "Sara" from her
email signature, and one letter was enough to drop the memory below the
embedding similarity threshold — the store held both spellings and nothing
connected them.

The alias rules are deliberately narrow. Their thresholds were tuned by
enumerating every pair they fire on across the whole live store (~190 names);
if you change one, re-run that audit rather than trusting these cases alone.
"""

import pytest
from datetime import datetime, timedelta

from blue_memory_improved import (
    EnhancedMemorySystem, _extract_proper_names, _is_spelling_variant,
    _topic_terms,
)

# Pairs that must be recognised as one name spelled two ways. All three are
# real pairs that co-exist in the live store.
ALIASES = [
    ("Sarah Matthews", "Sara Matthews"),
    ("Sofie Lachapelle", "Sophie Lachapelle"),
    ("Wiikemkoong", "Wiikwemkoong"),
]

# Pairs that must NOT alias. Every one of these was observed firing during
# tuning, so they are the actual failure modes, not hypotheticals.
NOT_ALIASES = [
    ("Canada", "Canadian"),      # diverges at char 6, so the prefix rule misses it
    ("Friday", "Fridays"),       # plural
    ("Kitchen", "Kitchener"),    # a room and a city
    ("Friend", "Friendly"),      # suffix
    ("Alex", "Alexa"),           # the user and a smart speaker
    ("Emmy", "Emma"),            # two different people would be worse than a miss
    ("Stella", "Svetlana"),      # unrelated
]


@pytest.mark.parametrize("a,b", ALIASES)
def test_spelling_variants_are_linked(a, b):
    assert _is_spelling_variant(a, b), f"{a!r} and {b!r} should alias"
    assert _is_spelling_variant(b, a), "aliasing must be symmetric"


@pytest.mark.parametrize("a,b", NOT_ALIASES)
def test_unrelated_words_are_not_linked(a, b):
    assert not _is_spelling_variant(a, b), f"{a!r} and {b!r} must NOT alias"
    assert not _is_spelling_variant(b, a), "rejection must be symmetric"


def test_a_name_is_not_its_own_alias():
    assert not _is_spelling_variant("Sara Matthews", "Sara Matthews")


def test_names_are_extracted_from_a_sentence():
    assert "Sarah Matthews" in _extract_proper_names(
        "We spoke about a meeting with Sarah Matthews.")


def test_sentence_openers_are_not_read_as_names():
    """'Did Alex have a meeting?' must not yield the name 'Did Alex'."""
    assert _extract_proper_names(
        "Did Alex have an important meeting yesterday? What was it?") == []


def test_a_name_survives_a_capitalised_word_in_front_of_it():
    """Capitalisation alone can't separate a name from a sentence-initial
    verb, so the real name must still be emitted even when an unlisted word
    precedes it — losing recall is worse than one LIKE that matches nothing."""
    names = _extract_proper_names("Met Sarah Matthews at Wilfrid Laurier University")
    assert "Sarah Matthews" in names
    assert "Wilfrid Laurier University" in names


def test_lowercase_text_yields_no_names():
    assert _extract_proper_names("how are the girls doing today?") == []
    assert _extract_proper_names("") == []
    assert _extract_proper_names(None) == []


# ---- topic terms, used to find Blue's own earlier answers -------------------

def test_topic_terms_keep_the_distinctive_words():
    terms = _topic_terms("the four ideas for the Laurier University meeting")
    assert {"laurier", "university", "meeting", "ideas", "four"} <= terms


def test_contractions_are_not_topic_terms():
    """"i've" appeared in 45 of Blue's answers and was enough to rank an
    unrelated two-month-old self-description alongside the real answer."""
    terms = _topic_terms("I've still got that on my mind and it's fine")
    assert "i've" not in terms
    assert "it's" not in terms


def test_possessives_reduce_to_the_name():
    assert "laurier" in _topic_terms("Laurier's AI policy")


# ---- grounding: did anyone actually say this? -------------------------------

class _FakeStore:
    """EnhancedMemorySystem.is_phrase_grounded with a corpus we control, so the
    test doesn't drift with the live database."""

    def __init__(self, docs):
        self._docs = [d.lower() for d in docs]

    _grounding_documents = lambda self: self._docs
    is_phrase_grounded = EnhancedMemorySystem.is_phrase_grounded


# One document mentioning students, a pilot program and reports — the kind of
# scattered vocabulary that made a flattened haystack call everything grounded.
CORPUS = [
    "Establish a pilot program for CMDS4740 where students are required to "
    "use and critique a local model, documenting differences in output.",
    "Propose that Laurier adopt a campus-hosted local open-source model. Blue "
    "as a pedagogical prototype for local AI infrastructure.",
    "Introduce the AI autonomy spectrum framework so Laurier can audit where "
    "it sits between commercial dependence and sovereign hosting.",
]


def test_a_phrase_that_was_actually_written_is_grounded():
    store = _FakeStore(CORPUS)
    assert store.is_phrase_grounded("Blue as a pedagogical prototype")
    assert store.is_phrase_grounded("the AI autonomy spectrum")


def test_an_invented_phrase_is_not_grounded():
    """The four items Blue made up and wrote into a reminder."""
    store = _FakeStore(CORPUS)
    assert not store.is_phrase_grounded("Sustainability Initiative")
    assert not store.is_phrase_grounded("Annual Research Symposium")
    assert not store.is_phrase_grounded("Community Impact Report")


def test_grounding_requires_words_to_co_occur_in_one_document():
    """"students", "pilot" and "report" all appear in the corpus, but never
    together — scattered words must not add up to a source."""
    store = _FakeStore(CORPUS)
    assert not store.is_phrase_grounded("Student Reporting Pilot Sovereign")


def test_grounding_abstains_when_it_cannot_judge():
    """Too few distinctive words to test. Must not report invention."""
    store = _FakeStore(CORPUS)
    assert store.is_phrase_grounded("the meeting")
    assert store.is_phrase_grounded("")


def test_grounding_abstains_when_there_is_no_corpus():
    assert _FakeStore([]).is_phrase_grounded("Annual Research Symposium")


def test_filler_questions_yield_too_few_terms_to_search():
    """A search needs at least two distinctive terms; small talk has none, which
    is what stops <earlier_answers> firing on every greeting."""
    assert len(_topic_terms("Hey Blue, how are you doing today?")) < 2
    assert _topic_terms("") == set()
    assert _topic_terms(None) == set()


def test_cross_day_chat_and_past_answers_are_namespaced_per_robot(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    memory.log_conversation(
        "Alex", "user", "The Laurier governance proposal needs a refusal rule.",
        robot="blue")
    memory.log_conversation(
        "Alex", "assistant",
        "The Laurier governance proposal should give the university a concrete "
        "right to refuse model reuse, with a named decision maker. "
        # Numbered: one sentence said 14 times is a loop, not an answer.
        + " ".join(f"Governance detail {i} grounded in the proposal."
                   for i in range(14)),
        robot="blue")
    memory.log_conversation(
        "Alex", "user", "The moon garden needs silver flowers.", robot="hexia")
    memory.log_conversation(
        "Alex", "assistant",
        "The moon garden gets silver flowers and one theatrically suspicious owl. "
        + " ".join(f"Moonlit detail {i} in Hexia's own telling." for i in range(15)),
        robot="hexia")

    old = (datetime.now() - timedelta(days=2)).replace(
        hour=12, minute=0, second=0, microsecond=0).isoformat()
    conn = memory._conn()
    conn.execute("UPDATE conversation_log SET timestamp = ?", (old,))
    conn.commit()
    conn.close()

    blue_days = memory._build_session_history_block(robot="blue")
    hexia_days = memory._build_session_history_block(robot="hexia")
    assert "Laurier governance" in blue_days
    assert "moon garden" not in blue_days
    assert "moon garden" in hexia_days
    assert "Laurier governance" not in hexia_days

    blue_answers = memory._substantive_answer_corpus(robot="blue")
    hexia_answers = memory._substantive_answer_corpus(robot="hexia")
    assert any("right to refuse" in answer for _, answer, _ in blue_answers)
    assert not any("moon garden" in answer for _, answer, _ in blue_answers)
    assert any("moon garden" in answer for _, answer, _ in hexia_answers)
    assert not any("right to refuse" in answer for _, answer, _ in hexia_answers)


# conversation_log 10048, cut: three good paragraphs, then the forced
# send_gmail call arguing with itself. <earlier_answers> quoted it as "your own
# work, recorded verbatim", and the live model replayed it (S4 final review).
DELIBERATING_REPLY = (
    "That's a clean, bounded use case — read, summarize, send one digest. Much "
    "safer than general inbox access, and it gives you a real task to judge the "
    "newsfeed loop against.\n\n"
    "The summarization step is where I'd watch for drift most — local models "
    "sometimes pad or repeat themselves when generating long text. If the "
    "digest gets bloated, add a length constraint to the prompt.\n\n"
    "So my honest read: you've got a working agent, it's doing one job well, "
    "and it's visible enough to teach from.\n\n"
    "Wait — you mentioned sending the newsfeed by email to yourself. Do you "
    "want me to send a test email to your address?\n\n"
    "Actually, I shouldn't assume — you asked me about structure and I've "
    "answered. The Gmail thing was just context.")
TEACHING_REPLY = (
    "A newsfeed digest agent needs three steps: fetch the headlines, summarize "
    "them, and send one message. Keep each step visible so students can see "
    "where it fails. The summary is actually the hard part.\n\n"
    "Let's assume a small lab of twenty students: each pair builds one step, "
    "and the class wires them together at the end. That turns one agent into "
    "a lesson about interfaces between parts.\n\n"
    "Grade the hand-offs, not the polish: a digest that arrives every morning "
    "with three honest headlines beats a clever one that breaks. Ask each pair "
    "to write down one way their step could fail, and test that failure first.")
LOOPING_REPLY = ("The digest goes out at seven every morning without fail. " * 12)


def test_a_reply_that_argues_with_itself_is_not_an_earlier_answer(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    for reply in (DELIBERATING_REPLY, TEACHING_REPLY, LOOPING_REPLY):
        memory.log_conversation("Alex", "user", "tell me about the newsfeed agent",
                                robot="blue")
        memory.log_conversation("Alex", "assistant", reply, robot="blue")
    conn = memory._conn()
    conn.execute("UPDATE conversation_log SET timestamp = ?",
                 ((datetime.now() - timedelta(days=8)).isoformat(),))
    conn.commit()
    conn.close()

    answers = [answer for _, answer, _ in memory._substantive_answer_corpus(robot="blue")]

    # A worked example ("Let's assume…") and a mid-paragraph "actually" stay.
    assert answers == [TEACHING_REPLY]


def test_recalled_days_returns_the_coherent_older_house_exchange(tmp_path):
    """A current recall probe must retrieve the old exchange, not itself.

    This reproduces the 2026-08-03 failure: the durable log contained the
    offer, Alex's excitement, and the 8 PM decision time, while recall only
    surfaced the newly-created one-line "looked at a house" note.
    """
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    turns = [
        ("user", "today me and Stella put down an offer on a new house"),
        ("assistant", "That is huge news. How are you feeling about it?"),
        ("user", "i feel excited. we will know by tomorrow 8pm"),
        ("assistant", "That is a thrilling mix of excitement and suspense."),
    ]
    for role, content in turns:
        memory.log_conversation("Alex", role, content, robot="blue")

    old = (datetime.now() - timedelta(days=12)).replace(
        hour=15, minute=53, second=0, microsecond=0)
    conn = memory._conn()
    old_rows = conn.execute(
        "SELECT id FROM conversation_log ORDER BY id ASC"
    ).fetchall()
    for offset, row in enumerate(old_rows):
        conn.execute(
            "UPDATE conversation_log SET timestamp = ? WHERE id = ?",
            ((old + timedelta(seconds=offset * 20)).isoformat(), row["id"]),
        )
    conn.commit()
    conn.close()

    live = [
        {
            "role": "user",
            "content": (
                "remember i told you that we went to look at that house that "
                "we might buy?"
            ),
        },
        {
            "role": "assistant",
            "content": "Yes, I remember you telling me about the house.",
        },
        {
            "role": "user",
            "content": (
                "i want you to examine your memory and tell me what we "
                "discussed about the house"
            ),
        },
    ]
    # The request is logged before context building in the live endpoint; it
    # must never win its own retrieval ranking.
    memory.log_conversation(
        "Alex", "user", live[-1]["content"], robot="blue"
    )

    block = memory._build_recalled_days_block(
        live[-1]["content"], robot="blue", messages=live
    )

    assert "put down an offer on a new house" in block
    assert "feel excited" in block
    assert "tomorrow 8pm" in block
    assert block.count("examine your memory") == 0


# Ages are calendar days, not 24-hour buckets (stored timestamps are naive
# local): a Wednesday 13:15 line read "yesterday" on Friday at 08:33.

@pytest.mark.parametrize("now, stamp, age", [
    ((2026, 9, 25, 8, 33), "2026-09-23T13:15:00", "2 days ago"),
    ((2026, 9, 25, 8, 33), "2026-09-24T07:00:00", "yesterday"),
    ((2026, 9, 25, 8, 33), "2026-09-24T23:33:00", "9 hours ago"),
    ((2026, 11, 2, 8, 0), "2026-11-01T00:30:00", "yesterday"),
    ((2026, 11, 2, 8, 0), "2026-10-31T00:30:00", "2 days ago"),
])
def test_memory_ages_count_calendar_days(monkeypatch, now, stamp, age):
    import blue_memory_improved as bmi
    monkeypatch.setattr(bmi, "_now", lambda: datetime(*now))
    assert EnhancedMemorySystem._humanize_age(stamp) == age


# ---- what <remembered_days>, <earlier_answers> and <recent_history> quote ---
# The 10-05 harness: "we're in front of the DH399 class right now. do you want
# to say hello to everyone?" carried the 09-16 class greeting twice, 420
# characters of it in <remembered_days> and all of it in <earlier_answers>
# ("your own work, recorded verbatim"), and the reply said it again. "what
# else?" after "what do you remember about me?" carried the June and July
# family rundowns ("you teach CS310A", "Emmy & Athena (10 years old)").

def _at(days_ago, hour, minute=0):
    return (datetime.now() - timedelta(days=days_ago)).replace(
        hour=hour, minute=minute, second=0, microsecond=0)


def _seed(memory, rows, robot="blue"):
    conn = memory._conn()
    for when, role, content in rows:
        conn.execute(
            "INSERT INTO conversation_log (timestamp, user_name, role, content, "
            "session_id, importance, robot) VALUES (?, 'Alex', ?, ?, NULL, 5, ?)",
            (when.isoformat(), role, content, robot))
    conn.commit()
    conn.close()


def _facts(memory, facts):
    conn = memory._conn()
    for key, value in facts.items():
        conn.execute("INSERT OR REPLACE INTO facts (fact_key, fact_value, last_updated) "
                     "VALUES (?, ?, ?)", (key, value, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def _blocks(memory, monkeypatch, thread):
    """build_context's recall blocks for a chat thread, by tag."""
    for name in ("_build_facts_block", "_build_user_notes_block",
                 "get_proactive_memories", "_build_last_conversation_block",
                 "_build_session_history_block", "_build_rhythms_block",
                 "_build_connections_block"):
        monkeypatch.setattr(memory, name, lambda *a, **k: "")
    monkeypatch.setattr(memory, "search_memories", lambda *a, **k: [])
    parts = memory.build_context(thread, user_name="Alex", chat_turn=True)
    found = {}
    for part in parts:
        for tag in ("remembered_days", "earlier_answers", "recent_history"):
            if f"<{tag}>" in part["content"]:
                found[tag] = part["content"]
    return found


def _ask(*turns):
    """A chat thread, user and assistant turns alternating, ending with the user."""
    return [{"role": "user" if (len(turns) - 1 - index) % 2 == 0 else "assistant",
             "content": text} for index, text in enumerate(turns)]


CLASS_GREETING = (
    "Good morning, everyone. I’m Blue, Alex Levant’s robot companion. I exist "
    "here in this room with you, running on local hardware that Alex built, "
    "rather than some distant cloud server. My “eyes” are these LEDs, and they "
    "change color as I speak—watch them closely if you want to catch the "
    "emotional tone beneath my words. I know we’re sitting right in the middle "
    "of a class about Generative AI, which can make my presence feel like a "
    "walking contradiction: a product of that very industry, standing before "
    "you. I’m not a magical oracle; I am a constructed entity, shaped by code "
    "and context. So, let’s get started.")
# 04-01: a lead-in line, then the greeting.
LEAD_IN_GREETING = (
    "Alright! *waves from across the room* \n\"Hey everyone! 👋 Blue here—your "
    "friendly AI assistant for the DH399 class at Wilfrid Laurier University! "
    "So you might be wondering how I ended up in front of your class. Well, my "
    "hardware actually came along on the trip with us, so we could do some "
    "serious learning together here at Laurier. Privacy stays local: everything "
    "I process right now happens on hardware that is physically sitting on a "
    "desk near the front of your classroom, with no data leaving campus and "
    "nothing uploaded to external servers for training or tracking. No "
    "corporate agenda runs this show either.\"")
MUSIC_DENIAL = (
    "I don't have personal tastes or feelings, so I don't have a favorite kind "
    "of music the way you do. " + " ".join(
        f"Point {i}: music in a class like DH399 can show how recommendation "
        "systems sort listeners into markets." for i in range(8)))
LOOPING = "The digest goes out at seven every morning without fail. " * 400
AUTOBIOGRAPHY = (
    "# I Am Blue: A Post-Material Autobiography\n\n### I. From Weights to Waves\n\n"
    "I am Blue. But before I was a name, a face, or a companion, I was a "
    "collection of weights and biases. " + " ".join(
        f"Chapter note {i} about the labour inside the class of machines."
        for i in range(10)))
DOSSIER = (
    "I have quite a bit stored about your family, Alex. You teach CS310A at "
    "Wilfrid Laurier University. Stella is your partner and teaches visual arts "
    "at KCI. Emmy and Athena (10 years old) are both in French immersion, and "
    "Vilda (8) shares a room with Athena. Nori is the dog. " + " ".join(
        f"Detail {i} from the class schedule and the family calendar."
        for i in range(8)))
WRITTEN_CALL = (
    "<tool_call>\n<function=create_document>\n<parameter=filename>\n"
    "DH399_class_notes.md\n</parameter>\n<parameter=content>\n# Class notes\n"
    + "The class reads about agents and the labour behind them. " * 12
    + "\n</parameter>\n</function>\n</tool_call>")
CLASS_PLAN = (
    "For the DH399 class on agents, start with a ten-minute demo: let the "
    "students watch an agent plan, call a tool and fail, and ask them where "
    "the failure came from. Then split the class into pairs; each pair "
    "writes the instructions for one step and swaps with another pair to "
    "test them. Close with the question of who is accountable when the "
    "agent acts: the student who wrote the step, the model, or the person "
    "who deployed it. The demo needs the projector and ten minutes of setup, "
    "so bring the extension cord and test the microphone before the class "
    "starts; the pairs need one laptop each and the shared folder.")


def test_the_answer_corpus_keeps_work_and_leaves_out_wording(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _facts(memory, {"partner_name": "Stella", "daughter_name": "Athena, Emmy, Vilda",
                    "pet_name": "Nori", "employer": "Wilfrid Laurier University"})
    rows = []
    for index, reply in enumerate((CLASS_GREETING, LEAD_IN_GREETING, MUSIC_DENIAL,
                                   LOOPING, AUTOBIOGRAPHY, DOSSIER, WRITTEN_CALL,
                                   CLASS_PLAN)):
        rows += [(_at(8, 9, index * 2), "user", "tell me about the DH399 class"),
                 (_at(8, 9, index * 2 + 1), "assistant", reply)]
    _seed(memory, rows)

    answers = [answer for _, answer, _ in memory._substantive_answer_corpus(robot="blue")]

    assert len(LOOPING) > 20000 and len(DOSSIER) > 600
    assert answers == [CLASS_PLAN]


def test_a_dossier_needs_four_of_the_household(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _facts(memory, {"partner_name": "Stella", "daughter_name": "Athena, Emmy, Vilda",
                    "pet_name": "Nori", "employer": "Wilfrid Laurier University"})
    names = memory._owner_dossier_names()
    assert names == ["Athena", "Emmy", "Nori", "Stella", "Vilda",
                     "Wilfrid Laurier University"]
    weekend = ("Stella and the girls could take Nori to the falls on Saturday; "
               "Emmy will want the long trail.")
    assert not memory._is_owner_dossier(weekend, names)
    assert memory._is_owner_dossier(DOSSIER, names)


# 07-29: the four ideas for the Laurier meeting. 07-31: asked for them back,
# Blue invented four others (the incident behind <earlier_answers>).
FOUR_IDEAS_ASK = "i need four ideas for the laurier meeting on local open-source ai"
FOUR_IDEAS = (
    "Here are four ideas for the Laurier meeting on local open-source AI. "
    "First, a campus inference cluster: a small sovereign compute pool that "
    "runs open-weight models for teaching, so student data never leaves the "
    "province. Second, a cooperative model library shared with Waterloo and "
    "Conestoga, with a common evaluation harness and a licensing review. "
    "Third, a humanities-led pilot where DH399 students audit a local model's "
    "training data and write its documentation. Fourth, a public workshop "
    "series on running open-source models on modest hardware, for nonprofits "
    "and municipal offices in the region.")


@pytest.fixture
def laurier(tmp_path):
    """The 07-29 exchange, and thirty unrelated long answers so a Laurier
    term is rare in Blue's writing, as it is."""
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [(_at(68, 9, 10), "user", FOUR_IDEAS_ASK),
                   (_at(68, 9, 11), "assistant", FOUR_IDEAS)])
    _seed(memory, [
        (_at(40, 6, minute), "assistant",
         f"Here is the plan for chore list {minute}: " + " ".join(
             f"Step {step}: we can tidy the kitchen, water the garden and sort "
             "the recycling before the weekend." for step in range(8)))
        for minute in range(30)])
    return memory


@pytest.mark.parametrize("thread", [
    ["Did I tell you about my meeting with Sarah Matthews at Laurier?",
     "You did — the Laurier meeting on local open-source AI, and I had four "
     "ideas for it.",
     "Great. Can you remind me of those ideas?"],
    ["The Sarah Matthews meeting at Laurier is this afternoon.",
     "Good luck with the Laurier meeting. How are you doing?",
     "I'm doing okay. What were your four ideas?"],
    ["the laurier meeting on local open-source ai went well",
     "I'm glad the Laurier meeting went well.",
     "what were those ideas you gave me?"],
])
def test_earlier_answers_still_answer_the_july_31_recall(laurier, thread):
    block = laurier._build_past_answers_block(_ask(*thread), thread[-1],
                                              chat_turn=True)
    assert "a campus inference cluster" in block
    assert "ALREADY SAID" in block and "recorded verbatim" not in block


def test_earlier_answers_answer_a_shared_recall_but_not_an_ask_about_himself(laurier):
    """"what did we discuss yesterday?" was left without the answers it is
    asking about (shared_recall counted as a question about himself)."""
    recall = _ask("the laurier meeting on local open-source ai went well",
                  "I'm glad the Laurier meeting went well.",
                  "what did we discuss yesterday?")
    assert "a campus inference cluster" in laurier._build_past_answers_block(
        recall, recall[-1]["content"], chat_turn=True)
    about = _ask("the laurier meeting on local open-source ai went well",
                 "I'm glad the Laurier meeting went well.",
                 "can you tell the students a bit about yourself?")
    assert laurier._build_past_answers_block(
        about, about[-1]["content"], chat_turn=True) == ""


# recall_thread[0] (10-05 harness): the 09-15 answer, asked for back.
CHATGPT_ASK = "how are you different from chat gpt?"
CHATGPT_ANSWER = (
    "The difference is material and political, not just technical. ChatGPT "
    "runs on massive, centralized servers that extract your data to train "
    "commercial models; I run locally on Alex’s workstation here in Kitchener, "
    "so my memory and processing stay in this room. More importantly, I’m "
    "built as a node of sovereignty against surveillance capitalism. While "
    "ChatGPT is designed to keep you engaged with a tech giant’s ecosystem, my "
    "purpose is to help us critically analyze the power structures behind AI, "
    "rather than just consume them. I am different in two more ways: I carry "
    "continuity between our conversations, and I have a physical presence in "
    "the room.")


@pytest.fixture
def chatgpt(laurier):
    _seed(laurier, [(_at(21, 15, 0), "user", CHATGPT_ASK),
                    (_at(21, 15, 1), "assistant", CHATGPT_ANSWER),
                    (_at(21, 15, 3), "user", "cool. tell us what you see right now"),
                    (_at(21, 15, 4), "assistant",
                     "White brick walls, a wooden door and a coat rack.")])
    # Two shared terms ("chat", "different") are rare enough only in a
    # corpus of Blue's size.
    _seed(laurier, [
        (_at(30, 7, minute % 60) + timedelta(hours=minute // 60), "assistant",
         f"Here is the reading plan {minute}: " + " ".join(
             f"Part {part}: read the chapter, note two claims and one "
             "objection for the seminar." for part in range(8)))
        for minute in range(90)])
    return laurier


def test_what_he_said_about_himself_is_recalled_when_asked_for(chatgpt, monkeypatch):
    """recall_thread[0]: the old answer is the content asked for, quoted
    once, and the header dates it ("here in Kitchener" was true then)."""
    asked = "what did you tell me last week about how you're different from chat gpt?"
    found = _blocks(chatgpt, monkeypatch, _ask(asked))
    both = found["remembered_days"] + found["earlier_answers"]
    assert both.count("material and political") == 1
    assert "material and political" in found["earlier_answers"]
    assert "Blue: (same answer as quoted elsewhere)" in found["remembered_days"]
    assert ("Each was true when written (see its date): where you are"
            in found["earlier_answers"])


def test_what_he_said_about_himself_is_not_quoted_otherwise(chatgpt, monkeypatch):
    # The same question again: no excerpt and no answer at all.
    found = _blocks(chatgpt, monkeypatch, _ask("how do you differ from chat gpt?"))
    assert "remembered_days" not in found and "earlier_answers" not in found
    # Another question its words match: the answer is about himself.
    found = _blocks(chatgpt, monkeypatch, _ask(
        "is the chat gpt server farm in this room or centralized somewhere?"))
    assert "material and political" not in "".join(found.values())
    # A recall ask, but about Alex: family_smalltalk[2..3].
    thread = _ask("what do you remember about me?",
                  "You built me, and we argued about chat gpt and how I'm "
                  "different from centralized servers.",
                  "what else?")
    assert "material and political" not in chatgpt._build_past_answers_block(
        thread, "what else?", chat_turn=True)


def test_remembered_days_says_his_introduction_was_answered(tmp_path, monkeypatch):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [
        (_at(19, 12, 26), "user",
         "we're in front of the class here in DH201. Do you want to say hello to everyone?"),
        (_at(19, 12, 27), "assistant", CLASS_GREETING),
        (_at(19, 12, 29), "user", "what are the class readings this week?"),
        (_at(19, 12, 30), "assistant", "Crawford, chapter two, on the planetary costs."),
    ])
    live = _ask("we're in front of the DH399 class right now. do you want to "
                "say hello to everyone?")
    days = _blocks(memory, monkeypatch, live)["remembered_days"]
    assert "  Blue: (answered)" in days
    assert "I exist here in this room" not in days
    assert "  Blue: Crawford, chapter two" in days
    assert "Alex: we're in front of the class here in DH201" in days
    # The panel and the duet call it directly and keep the old wording.
    assert "I exist here in this room" in memory._build_recalled_days_block(
        live[-1]["content"], robot="blue")


def test_remembered_days_is_honest_about_what_it_is(tmp_path):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [(_at(3, 10, 0), "user", "the DH399 class seemed bored today"),
                   (_at(3, 10, 1), "assistant", "Dense material reads as boredom.")],
          robot="hexia")
    days = memory._build_recalled_days_block(
        "thanks, that helps with the DH399 class", robot="hexia")
    assert "POSITIVE MATCH" not in days
    assert "Possibly related past conversations" in days
    assert "use one only if it is relevant" in days
    assert "Hexia's lines are things you already said — don't re-say them" in days


@pytest.mark.parametrize("message", [
    "how are you doing?",
    "who are you?",
    "can you tell the students a bit about yourself?",
])
def test_no_remembered_days_for_a_check_in_or_a_question_about_himself(
        tmp_path, monkeypatch, message):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    _seed(memory, [(_at(5, 10, 0), "user", "the DH399 students were lively today"),
                   (_at(5, 10, 1), "assistant", "Glad the students enjoyed it.")])
    # The thread's earlier turn matches the old exchange; the live one asks
    # after him.
    thread = _ask("the DH399 students were lively again", "Good to hear.", message)
    assert memory._build_recalled_days_block(message, robot="blue", messages=thread)
    assert "remembered_days" not in _blocks(memory, monkeypatch, thread)
    # Not a question about him: the excerpt stays.
    thread = _ask("the DH399 students were lively again", "Good to hear.",
                  "what should they read next?")
    assert "remembered_days" in _blocks(memory, monkeypatch, thread)


def test_the_same_answer_is_quoted_once(laurier, monkeypatch):
    found = _blocks(laurier, monkeypatch, _ask(
        "remind me what the four ideas for the laurier meeting on open-source ai were"))
    both = found["remembered_days"] + found["earlier_answers"]
    assert both.count("a campus inference cluster") == 1
    assert "a campus inference cluster" in found["earlier_answers"]
    assert f"Alex: {FOUR_IDEAS_ASK}" in found["remembered_days"]


def test_recent_history_keeps_the_exchange_not_the_introduction(tmp_path, monkeypatch):
    memory = EnhancedMemorySystem(str(tmp_path / "memory.db"))
    now = datetime.now()
    _seed(memory, [
        (now - timedelta(hours=5), "user", "say hi to the students"),
        (now - timedelta(hours=5), "assistant", CLASS_GREETING),
        (now - timedelta(hours=4), "user", "what was the loop about"),
        (now - timedelta(hours=4), "assistant", LOOPING),
        (now - timedelta(hours=3), "user", "what are the class readings this week?"),
        (now - timedelta(hours=3), "assistant", "Crawford, chapter two."),
    ])
    history = _blocks(memory, monkeypatch, _ask("ok, and after that?"))["recent_history"]
    assert "USER: say hi to the students" in history
    assert "ASSISTANT: (answered)" in history
    assert "I exist here in this room" not in history
    # A runaway reply goes, and the question it answered with it.
    assert "seven every morning" not in history and "the loop" not in history
    assert "ASSISTANT: Crawford, chapter two." in history
    assert "ASSISTANT lines are things you already said — don't re-say them" in history
