"""A question about a course's room, rules or a named assignment is answered
from that course's syllabus.

"and what room?" after "when is dh201 again?" got "search came up empty on
a room number" (10-05 harness), and "follow the specific requirements of the
assignment as stated in the syllabus" got "it doesn't list specific
requirements for the reading reports" (live 10-01): the syllabus has both,
under "Lecture and location" and "Reading Report (20%)". Hexia, asked "do
you know the location of my office" and then "look at one of my syllabi and
tell me the location of my office", said she didn't know (live 09-08).
The syllabus texts below have the real files' shape, not their contents.
"""

import bluetools as bt  # before blue.server.*: the package imports it

import pytest

from blue.server import syllabus_sections as ss


DH201 = (
    "DH201: Introduction to Generative AI\n"
    "Wednesday 10:00am-12:50pm \n"
    "Fall 2026 \n"
    "Lecture and location\n"
    "Wednesday 10:00am - 12:50pm in SB107. \n"
    "Instructor: Dr. A. Teacher\n"
    "Office hours: Friday 10:30am – 11:30am in DAWB 2-138 or by appointment. \n"
    "Email: teacher@example.edu\n"
    "Start the subject line of your email with “DH201”\n"
    "From Monday to Friday, expect a reply to your email within 48 hours.\n"
    "\n"
    "Course Description:\n"
    "\n"
    "A hands-on introduction to generative AI.\n"
    "Course Requirements:\n"
    "1) Reading Report – 20%\n"
    "2) Project and Presentation – 30%\n"
    "3) Class Participation – 20%\n"
    "4) Personal Journal of Reflections – 30%\n"
    "\n"
    "Reading Report (20%): \n"
    "\n"
    "A group of three students will start off the discussion of each text by "
    "presenting a Reading Report of 15 minutes in length. The Reading Report "
    "will include the following: a) Summary of main point of text, b) Secondary "
    "points, c) Key theorists/sources used, d) Relevant ideas from sources used, "
    "e) Relationship to course themes, and f) Key passages.\n"
    "\n"
    "Next steps: Sign up early to get the text and date you want!\n"
    "\n"
    "Personal Journal of Reflections (30%):\n"
    "\n"
    "Keep a weekly journal. Using no more than 250 words, identify the key point.\n"
    "\n"
    "Late Penalty:\n"
    "Assignments will not be accepted after the due date.\n"
    "\n"
    "Class Schedule\n"
    "\n"
    "Week 1 - September 16: Introduction\n"
    "\n"
    "Reading Reports:\n"
    "____________________ and __________________ and __________________\n"
)
# DH399 differs where it matters: its room line and its reading report.
DH399 = (DH201.replace("DH201", "DH399")
         .replace("Wednesday 10:00am - 12:50pm in SB107.", "Friday 11:30am - 2:20pm in SB107.")
         .replace("f) Key passages.", "f) Key passages. You will receive your grade "
                                      "with feedback within 7 days."))
# CS101's assignments are listed, not headed.
CS101 = (
    "CS101-A: Canadian Communication in Context\n"
    "Lecture and location\n"
    "Friday 8:30 - 10:20am in ART 1E1\n"
    "Course description\n"
    "An introduction to Canadian communication studies.\n"
    "Assignments and evaluation\n"
    "15%\tAnnotated bibliography is due Oct. 2. It will require you to locate "
    "scholarly sources for your research paper.\n"
    "15%\tMidterm exam (one-hour) will be administered during Oct. 23.\n"
    "The exam will be based on readings and lectures from Sept. 11 – Oct. 16.\n"
    "20%\tResearch paper is due December 4. Guidelines will be discussed on Sept. 25.\n"
    "Course schedule and important dates\n"
    "September 11 – Introduction\n"
)


# ---- which part a message asks about ------------------------------------------

@pytest.mark.parametrize("text, topics", [
    ("when is dh201 again?", ["when_where"]),
    ("what room are we in?", ["when_where"]),
    ("what room is the class in?", ["when_where"]),
    ("what time does the lecture start?", ["when_where"]),
    ("what are the office hours for dh399?", ["office_hours"]),
    ("do you know the location of my office", ["office_hours"]),
    ("what's the instructor email for cs101?", ["contact"]),
    ("how is dh201 graded?", ["assessment"]),
    ("What are the main assignments for CS101.", ["assessment"]),
    ("Go over the assignment with the class", ["assessment"]),
    ("follow the specific requirements of the assignment as stated in the syllabus",
     ["assessment"]),
    ("how much is the reading report worth?", ["the reading report"]),
    ("when is the journal due?", ["the journal"]),
    ("what's the midterm like in cs101?", ["the midterm"]),
    ("what's the late policy?", ["late"]),
    ("is attendance mandatory in cs101?", ["attendance"]),
    ("how do students contact me?", ["contact"]),
    ("what's the final project for dh201?", ["the project"]),
])
def test_a_course_question_names_its_part(text, topics):
    assert ss.asked_topics(text) == topics


# During DH399 on the calendar, with DH399 picked in the Context panel, or
# right after "when is dh201 again?", each of these got that course's grading,
# email, room or project (review of e897c8b).
NOT_ABOUT_A_COURSE = (
    "what percentage of jobs will AI agents replace?",
    "how can I reach Leo?",
    "who is teaching you all this?",
    "save his email",
    "what do you think about public participation in AI policy?",
    "what time does the movie start tonight?",
    "which room has the best light for a photo?",
    "what are the requirements for a passport?",
    "tell me about your final project",
    "how much is my car worth?",
    "what weight should I use for squats?",
    "I need to attend a meeting at 3",
    "what percentage of students use AI?",
    "can you summarize this research paper?",
    "what do you think of the midterm elections?",
    "how are AI agents evaluated?",
    "what did you write in your personal journal?",
    # a year is not a course code
    "what percentage of jobs will AI replace by 2030?",
    "where were you in 2019?",
)


@pytest.mark.parametrize("text", NOT_ABOUT_A_COURSE)
def test_a_loose_form_names_no_part_without_a_course(text):
    assert ss.asked_topics(text) == []


@pytest.mark.parametrize("text", [
    "what percentage of jobs will AI agents replace?",
    "how can I reach Leo?",
    "what time does the movie start tonight?",
    "which room has the best light for a photo?",
])
def test_a_loose_form_after_a_course_question_must_point_back(text):
    assert ss.asked_topics(text, after_course_question=True) == []


@pytest.mark.parametrize("text, topics", [
    ("and what room?", ["when_where"]),
    ("what room?", ["when_where"]),
    ("what time does it start?", ["when_where"]),
    ("how much is it worth?", ["assessment"]),
])
def test_a_loose_form_after_a_course_question_counts(text, topics):
    assert ss.asked_topics(text) == []
    assert ss.asked_topics(text, after_course_question=True) == topics


@pytest.mark.parametrize("text, topics", [
    ("what percentage of the grade is participation?", ["attendance", "assessment"]),
    ("how can students reach the instructor?", ["contact"]),
    ("what are the requirements for the assignment?", ["assessment"]),
    ("when is the final project due in dh201?", ["the project"]),
])
def test_a_loose_form_with_a_course_word_or_code_counts(text, topics):
    assert ss.asked_topics(text) == topics


def test_asking_what_was_said_is_not_a_syllabus_question():
    assert ss.asks_what_was_said(
        "what did you tell me last week about the reading report for dh399?")
    assert ss.asks_what_was_said("what did we decide about the final project for dh201?")
    assert not ss.asks_what_was_said("do you remember what room dh201 is in?")
    assert not ss.asks_what_was_said("what did the syllabus say about late work?")


@pytest.mark.parametrize("text", [
    "where are you right now?",
    "what room are you in?",
    "what's your email?",
    "what email did you send?",
    "what did you write in your journal today?",
    "when I was in class a student asked about agents",
    "it's late, good night",
    "how would you grade something like that?",
    "the living room is cold",
    "i've been thinking about whether AI agents will replace a lot of office jobs",
    "what's the weather tomorrow",
    "hi blue",
    "i'm working on a project for the house",
])
def test_small_talk_names_no_part(text):
    assert ss.asked_topics(text) == []


# ---- the part, cut out by its heading -------------------------------------------

def _only(text, topic):
    found = ss.sections(text, topic)
    assert len(found) == 1, found
    return found[0][1]


def test_each_part_is_the_syllabus_own_words():
    assert "Wednesday 10:00am - 12:50pm in SB107." in _only(DH201, "when_where")
    assert _only(DH201, "office_hours").startswith("Office hours: Friday 10:30am")
    contact = _only(DH201, "contact")
    assert "Instructor: Dr. A. Teacher" in contact and "Start the subject line" in contact
    assert "4) Personal Journal of Reflections" in _only(DH201, "assessment")
    report = _only(DH201, "the reading report")
    # the requirements, not the schedule's sign-up blanks
    assert "f) Key passages" in report and "Next steps" in report and "___" not in report
    assert "250 words" in _only(DH201, "the journal")
    assert "not be accepted" in _only(DH201, "late")
    assert ss.sections(DH201, "the midterm") == []


def test_a_listed_assignment_is_its_own_item():
    midterm = _only(CS101, "the midterm")
    assert midterm.startswith("15% Midterm exam") and "The exam will be based" in midterm
    # the bibliography mentions "your research paper"; the paper is its own item
    assert _only(CS101, "the research paper").startswith("20% Research paper is due")
    assert "Friday 8:30 - 10:20am in ART 1E1" in _only(CS101, "when_where")


def test_a_part_inside_another_is_given_once():
    parts = ss.excerpts(DH201, ["when_where", "office_hours"])
    assert len(parts) == 1 and "Office hours" in parts[0][1]


# ---- the course, and the note ----------------------------------------------------

@pytest.fixture
def library(monkeypatch, tmp_path):
    texts = {"DH201": DH201, "DH399": DH399, "CS101": CS101}
    docs = []
    for code, text in texts.items():
        fn = f"{code}_AL_2026F.docx"
        path = tmp_path / fn
        path.write_text("x")
        docs.append({"folder": code, "filename": fn, "filepath": str(path)})
    by_path = {d["filepath"]: texts[d["folder"]] for d in docs}
    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": docs})
    monkeypatch.setattr(bt, "_syllabus_file_text", lambda fp: by_path.get(fp, ""))
    monkeypatch.setattr(bt, "_calendar_event_now", lambda now=None: None)
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_DOCS", [])
    monkeypatch.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", [])
    return monkeypatch


def _thread(*user_turns, reply="Sure."):
    msgs = []
    for i, text in enumerate(user_turns):
        msgs.append({"role": "user", "content": text})
        if i < len(user_turns) - 1:
            msgs.append({"role": "assistant", "content": reply})
    return msgs


def test_and_what_room_takes_the_course_of_the_question_before(library):
    note = bt._syllabus_section_note(_thread(
        "when is dh201 again?", "no, that's wrong, it's on wednesdays", "and what room?"))
    assert "<syllabus_section>" in note and "[DH201_AL_2026F.docx]" in note
    assert "Wednesday 10:00am - 12:50pm in SB107." in note
    assert "override anything in your memory" in note and "Otherwise ignore them" in note
    # the correction in between keeps the question too
    assert "SB107" in bt._syllabus_section_note(_thread(
        "when is dh201 again?", "no, that's wrong, it's on wednesdays"))
    # "and dh399?" keeps the question and changes the course
    note = bt._syllabus_section_note(_thread("what room is dh201 in?", "and dh399?"))
    assert "Friday 11:30am" in note and "Wednesday 10:00am" not in note


def test_the_assignment_is_the_one_the_turns_before_named(library):
    attached = ('[Attached document: Reigeluth.pdf]\n"""\nCHAPTER 3\nWhat Kind of '
                'Learning Is Machine Learning? DH201 Reading Report\n"""\n\n'
                'produce a Reading Report for the attached article for dh399')
    note = bt._syllabus_section_note(_thread(
        attached,
        "follow the specific requirements of the assignment as stated in the syllabus"))
    assert "[DH399_AL_2026F.docx]" in note and "within 7 days" in note
    assert "f) Key passages" in note and "Course Requirements" not in note
    # the course his last reply cited, four turns on
    thread = _thread("keep going", "keep going",
                     "i want you to present your reading report as if you were a "
                     "student in the class.",
                     reply="c) Key theorists [DH399_AL_2026F.docx]")
    assert "within 7 days" in bt._syllabus_section_note(thread)


def test_no_course_no_note(library):
    assert bt._syllabus_section_note(_thread("what room?")) == ""
    assert bt._syllabus_section_note(_thread(
        "can you produce a reading report according to the requirements in "
        "the syllabus for the terranova reading")) == ""
    # a course whose syllabus is not in the library
    assert bt._syllabus_section_note(_thread("what's the late policy for cmds4740?")) == ""
    # a day's assignment is that day's row (<syllabus_day>), not the term's list
    assert bt._syllabus_section_note(_thread("what's the assignment for dh201 tomorrow?")) == ""
    assert "Course Requirements" in bt._syllabus_section_note(
        _thread("what are the assignments for dh201?"))


@pytest.mark.parametrize("text", (
    "where are you right now?", "what's your email?", "thanks. sorry for snapping",
    "what did you write in your journal?", "not bad, you?", "no worries, thanks",
    "and what about dinner?", "what time does the movie start tonight?",
    "how can I reach Leo?", "what percentage of jobs will AI agents replace?"))
def test_small_talk_after_a_course_question_gets_nothing(library, text):
    assert bt._syllabus_section_note(_thread("when is dh201 again?", text)) == ""


def test_a_short_follow_up_keeps_the_question(library):
    assert "SB107" in bt._syllabus_section_note(_thread("when is dh201 again?", "and the room?"))
    assert "SB107" in bt._syllabus_section_note(_thread(
        "when is dh201 again?", "no, it's on wednesdays"))
    assert "SB107" in bt._syllabus_section_note(_thread(
        "what room is dh201 in?", "what time does it start?"))


def test_another_robots_line_is_not_the_question_before(library):
    """In Panel's tool path the other robots' lines are user messages."""
    msgs = [{"role": "user", "content": "Alex: let's talk about agents"},
            {"role": "user", "content": "[Hexia, another robot in the panel, said]: "
                                        "when is dh201 again?"},
            {"role": "user", "content": "and what room?"}]
    assert bt._syllabus_section_note(msgs) == ""


def test_the_class_on_now_is_the_course(library):
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: CS101: Canadian Communication in Context (Lecture)"})
    assert "ART 1E1" in bt._syllabus_section_note(_thread("what room are we in?"))


@pytest.mark.parametrize("text", NOT_ABOUT_A_COURSE)
def test_the_class_on_now_is_not_every_question(library, text):
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: DH399: AI Agents at Work and in Society (Lecture)"})
    assert bt._syllabus_section_note(_thread(text)) == ""


def test_a_course_not_in_the_library_is_not_the_class_on_now(library):
    """Logged reading report turns for CS240J and CMDS4740, whose syllabi are
    gone, would have got DH399's requirements during DH399."""
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: DH399: AI Agents at Work and in Society (Lecture)"})
    assert bt._syllabus_section_note(_thread(
        "write a reading report on the text by lyon for cmds4740")) == ""
    assert bt._syllabus_section_note(_thread(
        "Look at the syllabus for CS240J under reading report.",
        "The specific requirements for reading reports are listed in the syllabus.")) == ""
    # a year is not a course
    assert "within 7 days" in bt._syllabus_section_note(_thread(
        "how is the reading report graded in 2026?"))


@pytest.mark.parametrize("text", NOT_ABOUT_A_COURSE)
def test_the_one_picked_course_is_not_every_question(library, text):
    library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", ["DH399"])
    assert bt._syllabus_section_note(_thread(text)) == ""


def _not_today():
    """'friday', or 'thursday' when today is a Friday."""
    from datetime import date
    return "friday" if date.today().weekday() != 4 else "thursday"


def test_another_days_class_is_not_the_class_on_now(library):
    """During the Wednesday DH201 lecture, "what time is my friday class?"
    got DH201's "Wednesday 10:00am - 12:50pm", as overriding memory."""
    day = _not_today()
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: DH201: Introduction to Generative AI (Lecture)"})
    for text in (f"what time is my {day} class?", f"what room is {day}'s class in?",
                 "when do my classes start this term?", "when is my next class?"):
        assert "Wednesday 10:00am" not in bt._syllabus_section_note(_thread(text)), text
    # nor the one picked course
    library.setattr(bt, "_calendar_event_now", lambda now=None: None)
    library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", ["DH201"])
    assert bt._syllabus_section_note(_thread(f"what time is my {day} class?")) == ""
    library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", [])
    # nor the course of the turn before
    assert bt._syllabus_section_note(_thread(
        "when is dh201 again?", f"and what room is my {day} class in?")) == ""
    # the class meeting now still is
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: DH201: Introduction to Generative AI (Lecture)"})
    assert "SB107" in bt._syllabus_section_note(_thread("what room is the class in today?"))


def test_asking_what_was_said_gets_no_note(library):
    """<earlier_answers> answers these; the note says the syllabus
    overrides his earlier replies."""
    assert bt._syllabus_section_note(_thread(
        "what did you tell me last week about the reading report for dh399?")) == ""
    assert bt._syllabus_section_note(_thread(
        "what did we decide about the final project for dh201?")) == ""
    assert "SB107" in bt._syllabus_section_note(_thread(
        "do you remember what room dh201 is in?"))


def test_a_course_the_thread_implies_must_be_in_focus(library):
    """The Context panel picks DH399: "what room?" after a DH201 question
    gets no other course's room; a course named in the message is still
    read; with nothing implied, the one picked course is the course."""
    library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", ["DH399"])
    assert bt._syllabus_section_note(_thread("when is dh201?", "and what room?")) == ""
    assert "Wednesday 10:00am" in bt._syllabus_section_note(_thread("what room is dh201 in?"))
    assert "Friday 11:30am" in bt._syllabus_section_note(_thread("what room is the class in?"))


def test_a_picked_reading_puts_its_course_in_focus(library, tmp_path):
    """With only the reading picked (the file, or its DH399/readings folder),
    the requirements turn after a DH399 reading report request got nothing:
    the syllabus itself was not among the picks (review of e897c8b)."""
    docs = bt.load_document_index()["documents"] + [
        {"folder": "DH399/readings", "filename": "Reigeluth.pdf",
         "filepath": str(tmp_path / "Reigeluth.pdf")},
        {"folder": "Readings", "filename": "Castelle.pdf",
         "filepath": str(tmp_path / "Castelle.pdf")}]
    library.setattr(bt, "load_document_index", lambda: {"documents": docs})
    thread = _thread("produce a Reading Report for the attached article for dh399",
                     "follow the specific requirements of the assignment as stated "
                     "in the syllabus")
    for docs_picked, folders_picked in ((["Reigeluth.pdf"], []), ([], ["DH399/readings"])):
        library.setattr(bt, "_ACTIVE_FOCUS_DOCS", docs_picked)
        library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", folders_picked)
        note = bt._syllabus_section_note(thread)
        assert "[DH399_AL_2026F.docx]" in note and "f) Key passages" in note
        # and no other course's
        assert bt._syllabus_section_note(_thread("when is dh201?", "and what room?")) == ""
    # a reading filed under no course leaves the course the thread named
    library.setattr(bt, "_ACTIVE_FOCUS_DOCS", ["Castelle.pdf"])
    library.setattr(bt, "_ACTIVE_FOCUS_FOLDERS", [])
    assert "f) Key passages" in bt._syllabus_section_note(thread)
    # but is not the class on the calendar
    library.setattr(bt, "_calendar_event_now", lambda now=None: {
        "title": "Alex: DH201: Introduction to Generative AI (Lecture)"})
    assert bt._syllabus_section_note(_thread("what room is the class in?")) == ""


def test_the_note_reaches_the_model_before_the_style_note(library):
    msgs = _thread("when is dh201 again?", "and what room?")
    out = bt._chat_system_message(msgs, robot="blue", user_name="Alex", voice=False,
                                  language="", system_addendum="", heard=False)
    system = out[0]["content"]
    assert "<syllabus_section>" in system
    assert system.index("</syllabus_section>") < system.index("\nSTYLE:")
    # not on the kids' page
    out = bt._chat_system_message(_thread("when is dh201 again?", "and what room?"),
                                  robot="blue", user_name="Vilda", voice=False,
                                  language="", system_addendum="", heard=False)
    assert "<syllabus_section>" not in out[0]["content"]
