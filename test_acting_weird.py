"""2026-09-24 afternoon: "Blue is acting weird".

Five things went wrong in one DH399 conversation, none new: a canned tool
menu, an email non sequitur after "wrong", Russian after "hi blue", a
syllabus answer invented past a truncated attachment, and a check-in that
reported made-up work. Each test is the real turn.
"""

import bluetools as bt  # before blue.server.*: the package imports it

import pytest

from blue_identity import identity_request_kind, identity_response_problem

ATTACHED = ('[Attached document: DH399 AL 2026F.pdf]\n"""\nDH399: AI Agents at Work and '
            'in Society\nEmail: alevant@wlu.ca\nFrom Monday to Friday, expect a reply to '
            'your email within 48 hours.\nClass Schedule\nSeptember 11: Introduction\n'
            '"""\n\nhere\'s the correct syllabus')


# ---- "wrong" became a forced reply_gmail --------------------------------------

def test_a_bare_correction_reruns_the_users_words_not_the_attachment():
    thread = [
        {"role": "user", "content": "what is assigned for tomorrow in the dh399 syllabus"},
        {"role": "assistant", "content": "The syllabus lists AI Lab 5 for tomorrow."},
        {"role": "user", "content": ATTACHED},
        {"role": "assistant", "content": "Thank you. This syllabus has the full class schedule."},
        {"role": "user", "content": "wrong"},
    ]
    query = bt._schedule_correction_query("wrong", thread)
    # the dated question, not the attachment's "here's the correct syllabus"
    assert query == "what is assigned for tomorrow in the dh399 syllabus"
    primary = bt.TOOL_SELECTOR.select_tool(query).primary_tool
    assert primary is None or primary.tool_name != "reply_gmail"


def test_an_attachment_full_of_email_is_not_a_request_to_send():
    assert not bt._user_requested_action("send_gmail", ATTACHED)
    assert bt._user_requested_action("send_gmail", "email Nick the summary")
    assert bt.detect_hallucinated_action("Thanks for sending that over.") != "send_gmail"


# ---- the syllabus date lookup never ran -----------------------------------------

@pytest.mark.parametrize("entry, expected", [
    ({"folder": "DH399", "filename": "DH399_AL_2026F.docx"}, True),
    ({"folder": "CS101", "filename": "CS101A_Levant_2026F.docx"}, True),
    ({"folder": "Courses/DH201", "filename": "DH201_AL_2026F.docx"}, True),
    ({"folder": "DH399", "filename": "Wooldridge_ch7.pdf"}, False),
    ({"folder": "readings", "filename": "DH399_notes.docx"}, False),
    ({"folder": "", "filename": "Fall syllabus.docx"}, True),
])
def test_a_course_folder_syllabus_is_recognised(entry, expected):
    assert bt._looks_like_syllabus_entry(entry) is expected


def test_the_date_lookup_finds_the_row_in_a_course_code_syllabus(monkeypatch, tmp_path):
    doc = tmp_path / "DH399_AL_2026F.docx"
    doc.write_text("x")
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"folder": "DH399", "filename": "DH399_AL_2026F.docx", "filepath": str(doc)}]})
    monkeypatch.setattr(bt, "extract_text_from_file", lambda fp: (
        "Grading ...\nClass Schedule\nSeptember 18: What is AI?\n"
        "September 25: What is under the hood of an AI agent?\nReadings: Pasquinelli ch. 1\n"
        "October 2: Agents at work\n"))
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_DOCS", [], raising=False)
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", [], raising=False)
    text = bt._syllabus_schedule_text(query="what is assigned for september 25 in dh399")
    assert text and "What is under the hood" in text


# ---- a cut attachment says so ---------------------------------------------------

def test_a_long_attachment_keeps_its_schedule_and_says_it_was_cut():
    body = "Policies. " * 1500 + "Class Schedule\nSeptember 25: What is under the hood\n"
    kept = bt._cap_attachment_text(body, "DH399.pdf")
    assert "September 25: What is under the hood" in kept
    assert "TRUNCATED" in kept and len(kept) < 8600
    assert bt._cap_attachment_text("short", "a.pdf") == "short"
    wrapped = f'[Attached document: DH399.pdf]\n"""\n{kept}\n"""\n\nwhat is tomorrow?'
    assert bt._intent_text(wrapped).strip() == "what is tomorrow?"


# ---- the canned "Did you want to X or Y?" ----------------------------------------

def test_look_at_is_not_a_clock_time():
    for msg in ("look at the whole syllabus its there in the class schedule",
                "look at this document in your library meeting_notes_laurier_ai_proposal.md"):
        result = bt.TOOL_SELECTOR.select_tool(msg)
        assert not result.needs_disambiguation, msg
        assert result.primary_tool.tool_name == "search_documents", msg
    for msg in ("I have a meeting with Bob at 3pm tomorrow",
                "schedule the dentist at 10 on friday"):
        assert bt.TOOL_SELECTOR.select_tool(msg).primary_tool.tool_name == "create_reminder", msg


def test_a_close_call_between_tools_goes_to_the_model_not_a_menu():
    msg = "save a note that says abc"
    selection = bt.TOOL_SELECTOR.select_tool(msg)
    choice = bt._chat_choose_tool([{"role": "user", "content": msg}], msg,
                                  correction=None, user_name="Alex",
                                  pre_selection=selection)
    assert choice.reply is None, "no canned clarifying question"
    assert not choice.force_tool or not selection.needs_disambiguation


# ---- Russian after "hi blue" ------------------------------------------------------

@pytest.mark.parametrize("text, lang", [
    ("hi blue", "en"), ("you okey", "en"), ("чи", "ru"), ("Привет, как дела?", "ru"),
    ("merci beaucoup", "fr"), ("hej Blue, hvordan går det", "da"), ("12:30", ""),
])
def test_the_newest_message_language(text, lang):
    assert bt._message_language(text) == lang


def test_on_auto_an_english_message_gets_an_english_reply_note():
    msgs = bt._chat_system_message(
        [{"role": "user", "content": "чи"}, {"role": "assistant", "content": "Привет!"},
         {"role": "user", "content": "hi blue"}],
        robot="blue", user_name="Alex", voice=False, language="", system_addendum="")
    system = next(m["content"] for m in msgs if m.get("role") == "system")
    assert "newest message is in English" in system


# ---- "you okey" and invented work -------------------------------------------------

@pytest.mark.parametrize("text", ["you okey", "u good?", "are you alright, blue?",
                                  "hey blue, you ok?"])
def test_are_you_ok_is_a_check_in(text):
    assert identity_request_kind(text) == "self_state"


@pytest.mark.parametrize("text", ["are you okay with that plan", "you good with this?"])
def test_a_question_about_a_plan_is_not_a_check_in(text):
    assert identity_request_kind(text) != "self_state"


def test_a_check_in_reports_no_invented_work():
    made_up = ("I'm doing well, thanks for asking. Just finishing up some work on the "
               "DH399 course materials. How are you?")
    assert identity_response_problem(made_up, "Blue", request_kind="self_state") \
        == "invented_current_activity"
    honest = "Doing well — I've had your DH399 class on my mind. How are you?"
    assert identity_response_problem(honest, "Blue", request_kind="self_state") is None


# ---- a note Alex asked Blue to keep was merged away ------------------------------

def test_distinct_user_notes_are_never_merged(tmp_path, monkeypatch):
    import sqlite3
    import blue_memory_improved as bmi
    memory = bmi.EnhancedMemorySystem(db_path=str(tmp_path / "m.db"))
    for text in ("where it will for laurier university not at home",
                 "what she looks like", "about the girls", "their dance"):
        memory._store_memory("user_note", "user-requested memory", text, importance=0.9)
    memory._merge_duplicate_memories()
    with sqlite3.connect(memory.db_path) as conn:
        kept = {r[0] for r in conn.execute("SELECT content FROM memories WHERE type='user_note'")}
    assert "where it will for laurier university not at home" in kept
    assert len(kept) == 4


# ---- review round: the fixes must not open new holes -------------------------------

def test_spoken_and_24_hour_times_still_make_reminders():
    for msg in ("can you remember that I have a haircut at three",
                "please remember that my flight is at 1530"):
        assert bt.TOOL_SELECTOR.select_tool(msg).primary_tool.tool_name == "create_reminder", msg
    for msg in ("look at one of the class schedules", "at one point the syllabus changed"):
        tools = [i.tool_name for i in bt.TOOL_SELECTOR._detect_all_intents(msg, {})]
        assert "create_reminder" not in tools, msg


def test_the_tools_that_tied_are_offered_but_not_forced():
    msg = "save a note that says abc"
    selection = bt.TOOL_SELECTOR.select_tool(msg)
    assert selection.needs_disambiguation
    bt._chat_choose_tool([{"role": "user", "content": msg}], msg, correction=None,
                         user_name="Alex", pre_selection=selection)
    offered = set(bt._TURN_OFFER.tools)
    assert {"remember_fact", "create_document"} <= offered
    payload = bt._lm_studio_payload([{"role": "user", "content": msg}], include_tools=True,
                                    force_tool=None, iteration=1, tool_scope="reflex")
    names = {t["function"]["name"] for t in payload.get("tools", [])}
    assert "create_document" in names and "web_search" in names
    assert payload.get("tool_choice") in (None, "auto")


def test_a_cs101_syllabus_with_a_course_schedule_heading_is_read(monkeypatch, tmp_path):
    cs = tmp_path / "CS101A_Levant_2026F.docx"; cs.write_text("x")
    dh = tmp_path / "DH201_AL_2026F.docx"; dh.write_text("x")
    texts = {
        str(cs): ("Course schedule and important dates\nOctober 16 – Networks and platforms\n"
                  "October 23 – Midterm\nOctober 30 – Data\n"),
        str(dh): "Class Schedule\nOctober 16: Generative images\n",
    }
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"folder": "DH201", "filename": "DH201_AL_2026F.docx", "filepath": str(dh)},
        {"folder": "CS101", "filename": "CS101A_Levant_2026F.docx", "filepath": str(cs)}]})
    monkeypatch.setattr(bt, "extract_text_from_file", lambda fp: texts[fp])
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_DOCS", [], raising=False)
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", [], raising=False)
    text = bt._syllabus_schedule_text(query="what are we doing in cs101 on october 16")
    assert text and "Networks and platforms" in text
    assert "Generative images" not in text, "another course must not fill the slot"


@pytest.mark.parametrize("text, lang", [
    ("Can you comment on my draft?", "en"), ("Er du ok?", "da"),
    ("c'est ok", "fr"), ("reply in French please", ""), ("ok", ""),
])
def test_language_evidence_has_no_homographs(text, lang):
    assert bt._message_language(text) == lang


@pytest.mark.parametrize("reply, flagged", [
    ("I'm doing well, thanks! Are you currently grading the DH399 essays?", False),
    ("Pretty good. Hope you're just wrapping up your day - how are you?", False),
    ("Just wrapped up some work on the DH399 course materials. How are you?", True),
    ("Doing fine. I finished some work on the slides earlier.", True),
    ("I'm doing well. I've been preparing your DH201 notes.", True),
])
def test_a_check_in_claims_only_the_robots_own_work(reply, flagged):
    problem = identity_response_problem(reply, "Blue", request_kind="self_state")
    assert (problem == "invented_current_activity") is flagged, reply


from test_chat_pipeline import chat  # noqa: E402,F401  (fixture)


def test_an_ambiguous_turn_is_never_the_zero_llm_shortcut(chat):
    """"stop the music and find the paper" tied control_music with a search;
    the shortcut skipped the memory build and sent the bare thread."""
    msg = "stop the music and find the paper on surveillance"
    assert bt.TOOL_SELECTOR.select_tool(msg).needs_disambiguation
    chat.ask(msg)
    assert chat.model.main, "the model was asked"
    assert "<known_facts>" in chat.model.system_prompt


# ---- evening: his own wrong answer had become a belief -------------------------------

def _one_course_library(monkeypatch, tmp_path, day):
    from datetime import date
    doc = tmp_path / "DH399_AL_2026F.docx"
    doc.write_text("x")
    label = f"{day.strftime('%B')} {day.day}"
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"folder": "DH399", "filename": "DH399_AL_2026F.docx", "filepath": str(doc)}]})
    monkeypatch.setattr(bt, "_syllabus_file_text", lambda fp: (
        f"Grading\nClass Schedule\n{label}: What is under the hood of an AI agent?\n"
        "Readings: Pasquinelli ch. 1\nAI Lab 2: How to turn your laptop into an AI workstation\n"))


def test_a_day_question_gets_the_syllabus_row_not_memory(monkeypatch, tmp_path):
    from datetime import date, timedelta
    _one_course_library(monkeypatch, tmp_path, date.today() + timedelta(days=1))
    note = bt._syllabus_day_note([{"role": "user", "content": "what do we have tomorrow"}])
    assert "What is under the hood" in note and "AI Lab 2" in note
    assert "override anything in your memory" in note and "Otherwise ignore them" in note
    # the corrections that followed keep the day
    thread = [{"role": "user", "content": "what do we have tomorrow"},
              {"role": "assistant", "content": "AI Lab 5: Building your own agents."},
              {"role": "user", "content": "its not lab 5"}]
    assert "What is under the hood" in bt._syllabus_day_note(thread)
    assert bt._syllabus_day_note([{"role": "user", "content": "play some jazz please"}]) == ""
    for other in ("what's the weather tomorrow", "remind me friday to call mom"):
        assert bt._syllabus_day_note([{"role": "user", "content": other}]) == "", other
    assert "What is under the hood" in bt._syllabus_day_note(
        [{"role": "user", "content": "what are we reading in dh399 tomorrow"}])


def test_a_weekday_is_a_day():
    from datetime import date
    assert bt._day_of("whats on friday").weekday() == 4
    assert bt._day_of("what's on today") == date.today()
    assert bt._day_of("play some jazz") is None


def test_the_day_note_reaches_the_model(chat, monkeypatch, tmp_path):
    from datetime import date, timedelta
    _one_course_library(monkeypatch, tmp_path, date.today() + timedelta(days=1))
    chat.ask("what do we have tomorrow")
    assert "<syllabus_day>" in chat.model.system_prompt
    assert chat.model.system_prompt.rstrip().endswith("No emoji."), "the style note stays last"
