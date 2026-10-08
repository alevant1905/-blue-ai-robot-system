"""No document machinery in conversation (S6, plan C10).

Run with: python -m pytest test_sources_in_conversation.py

- Every library read ended "Put [filename] right after each claim taken from
  this text", and LOCAL LIBRARY, <expertise> and <focused_documents> said
  "cite [filename]" too. 37% of Blue's October replies carry a bracketed
  filename: "…Chapter 2 "The Golden Age" [DH201_AL_2026F.docx]." to "what are
  we doing in dh201 today?" (10118), and the same tag with no tool call at
  all, the model reasoning "I should cite the source document." (10114). A
  reading report presented to the class carried 140-character PDF names in
  brackets (10098).
- "today's AI Lab for dh201: How to download, install, and operate local,
  private, open-source models" (10130) told Blue what the lab was. "open",
  inside "open-source", read as "open the DH201 folder", the syllabus was
  fast-executed, and the reply was a failed lookup (10131): "I can't pull
  the installation guide or command-line instructions from them."
- "search" inside "research" made every remark about his research talk a
  library search (19 turns on 04-23).

SAFETY: the pipeline tests use test_chat_pipeline's chat fixture, which stubs
execute_tool and both model transports before anything runs. The detector
tests read a library written to tmp, never the live document_index.json.
"""

import json

import pytest

import bluetools as bt
from blue.server import tool_pipeline
from blue.server.prompts import CHAT_SYSTEM_PROMPT
from blue.tool_selector.detectors.documents import DocumentsDetector
from test_chat_pipeline import _tool_call, chat, reply_of  # noqa: F401  (fixture)

LAB_TITLE = ("today's AI Lab for dh201: How to download, install, and operate "
             "local, private, open-source models")
READ = ("LOCAL LIBRARY READ SUCCEEDED: [DH201_AL_2026F.docx] was resolved in "
        "folder DH201 and 28,487 characters were extracted directly from the "
        "file. The passages below are the document's actual text.\n\n"
        "[DH201_AL_2026F.docx]\nWeek 4 - October 7: Lineages of AI: "
        "Connectionism and Symbolic AI")


@pytest.fixture
def library(monkeypatch, tmp_path):
    """A library like Alex's: three course syllabi and a talk script."""
    index_path = tmp_path / "document_index.json"
    index_path.write_text(json.dumps({"documents": [
        {"filename": "DH201_AL_2026F.docx", "folder": "DH201"},
        {"filename": "DH399_AL_2026F.docx", "folder": "DH399"},
        {"filename": "CS101A_Levant_2026F.docx", "folder": "CS101"},
        {"filename": "Job_Talk_Script7.docx", "folder": "Alex Levant"},
        {"filename": "When_Models_Disagree...Transcriptio.txt",
         "folder": "Mark Humphries Substack"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(DocumentsDetector, "_index_path",
                        classmethod(lambda cls: str(index_path)))
    monkeypatch.setattr(DocumentsDetector, "_lib_tokens_by_doc", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_rare_tokens", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_phrases", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_mtime", -1.0)
    return DocumentsDetector()


def _searches(detector, message):
    return detector._detect_search_intent(message.lower(), {}) is not None


# ---- statements are not searches ------------------------------------------------

@pytest.mark.parametrize("message", [
    LAB_TITLE,                                                     # 10130
    "today we have orientation for the TAs for cs101",             # 9723
    "today's topic for dh201 is connectionism and symbolic ai",
    "tomorrow's reading for dh399 is reigeluth and castelle",
    "so today's lab in cs101: building a chatbot with python",
    "today we're covering chapter 2 of the dh201 syllabus",
    "today's AI lab for dh201: how to review and access open models",
    # "search" inside "research" (04-23)
    "I hope they like our research talk.",
    "We are at the end of the research talk do you have any final thoughts.",
    "Do you think they will like my research talk.",
    # "look for" inside "look forward"
    "I look forward to the talk tomorrow",
])
def test_a_statement_that_shares_a_topic_does_not_search(library, message):
    assert not _searches(library, message)


@pytest.mark.parametrize("message", [
    "what's today's lab for dh201?",
    "today's reading for dh201 is what?",
    "what are we doing in dh201 today?",
    "tell me about today's lab for dh201",
    "today's lab is in the dh201 syllabus, check it",
    "today's lab for dh201 is on local models, can you look at the syllabus",
    "open the dh201 folder",
    "open the dh201 syllabus and find the open-source lab",
    "dh201",
    "search my documents for the research talk",
    "find my research talk",
    "searching my files for the job talk script",
    # a document verb outranks the statement
    "today we have to search the documents for the lab handout",
    "what did i say about ilyenkov in my research talk?",
])
def test_a_question_or_request_about_a_document_still_searches(library, message):
    assert _searches(library, message)


@pytest.mark.parametrize("message", [
    # a request after the frame, with no "?" (review of S6)
    "today we do dh399, what's the assignment",
    "tomorrow we have dh399 what are the readings",
    "today's class is dh399, remind me what the assignment is",
    "today's topic for dh201 is connectionism, introduce it to the class",
    "this week's reading for dh399 is reigeluth and castelle, explain the "
    "main claim",
    "today's reading for dh399 is toscano, summarize it for the class",
    "today's reading for dh201 is wooldridge chapter 2. what does he argue",
    "today's class for dh201 is about the reading report. explain the "
    "assignment",
    "today we have the dh201 lab, introduce the topic to the class",
    "today's topic in dh201: connectionism. introduce it",
    "today's lab is in the dh201 syllabus check it",
])
def test_a_request_after_the_frame_still_searches(library, message):
    assert _searches(library, message)


@pytest.mark.parametrize("message", [
    # a ":" title's words ask nothing, whatever they are
    "today's lecture for dh201: open-source models and the politics of open "
    "weights",
    "today's class for dh399: peer review of the first assignment drafts",
    "today's lab for dh201: a closer look at transformers",
    "today's lab for cs101: how to search your files with grep",
    "today's ai lab for dh201: how to download, install, and operate local, "
    "private, open-source models. what a day",
])
def test_a_title_s_words_are_not_a_request(library, message):
    assert not _searches(library, message)


def test_a_clock_time_is_no_title(library):
    assert _searches(library, "today's class is at 11:30, check the syllabus")


@pytest.mark.parametrize("message,searches", [
    ("open the dh201 syllabus", True),
    ("reopen the job talk script", True),
    ("i opened the pdf but it was blank, check the file", True),
    ("give me an open-source alternative to the pdf reader", False),
    ("read all the documents that i checkmarked in the library folder", True),
    ("the open-source release notes look solid", False),
])
def test_the_re_read_verbs_are_words(library, message, searches):
    assert _searches(library, message) is searches


def test_open_source_is_not_the_verb_open(library):
    """The source fix by itself: the lab's title alone, without "today's",
    is a passing mention of the course."""
    title = ("ai lab for dh201: how to download, install, and operate local, "
             "private, open-source models")
    assert library._library_match(title) is None
    assert library._library_match("open dh201") is not None


# ---- the answer note ---------------------------------------------------------------

def _thread(*users):
    return [{"role": "user", "content": u} for u in users]


def test_a_casual_read_names_its_source_in_words():
    note = tool_pipeline.source_credit_note(
        "what are we doing in dh201 today?",
        _thread("what are we doing in dh201 today?"))
    assert "[filename]" not in note and "right after each claim" not in note
    assert "say in words where something comes from" in note
    assert "no brackets or filenames" in note
    # A report asked for keeps a label per section; the model knows which
    # it was asked for.
    assert "report or a document, give each section's source one short label" in note
    # b5079b2: his own office number is not the syllabus's.
    assert "never something the user just told you" in note


@pytest.mark.parametrize("message,thread,spoken", [
    ("what else are we reading today", None, True),               # spoken turn
    ("present your reading report to the class", None, False),    # 10097
    ("i want you to present your reading report as if you were a student "
     "in the class.", None, False),                                # 10079
    ("what else are we reading today",
     ["we are in the class rightnow", "what else are we reading today"], False),
    ("read it out loud", None, False),
])
def test_what_is_heard_or_presented_has_no_brackets_at_all(message, thread, spoken):
    note = tool_pipeline.source_credit_note(
        message, _thread(*(thread or [message])), spoken=spoken)
    assert note.startswith("This reply will be heard or presented to a room: "
                           "no brackets, filenames or source labels at all")
    assert "short label" not in note


@pytest.mark.parametrize("message", [
    "what is the present tense of lernen",
    "i got vilda a present for her birthday",
    "write a reading report on the reigeluth chapter",
    # Alex presents; Blue writes
    "i will present the paper at the conference, write me a report on it "
    "with sources",
    "i'm presenting the chapter at the conference, outline it for me",
    "the students present their reading reports today",
    "at present the reading is wooldridge chapter 2",
])
def test_a_present_that_is_not_presenting_is_written(message):
    note = tool_pipeline.source_credit_note(message, _thread(message))
    assert note.startswith("If the user asked for a report or a document")


@pytest.mark.parametrize("message", [
    "pretend you are a student in the class and present your reading report "
    "on this text",                                                # 10081
    "ok, present it",
    "can you read that out loud",
])
def test_blue_asked_to_present_is_heard(message):
    note = tool_pipeline.source_credit_note(message, _thread(message))
    assert note.startswith("This reply will be heard or presented to a room")


# Every syllabus Alex attaches or pastes says students "start off the
# discussion of each text by presenting a Reading Report".
ATTACHED_SYLLABUS = (
    '[Attached document: DH399 AL 2026F.pdf]\n"""\nDH399: AI Agents at Work '
    'and in Society\nReading Report (20%): Students will start off the '
    'discussion of each text by presenting a Reading Report of 10 minutes.\n'
    '"""\nwrite a reading report on the castelle chapter for dh399')


def test_presenting_is_read_from_his_words_not_an_attachment():
    note = tool_pipeline.source_credit_note(
        ATTACHED_SYLLABUS, _thread(ATTACHED_SYLLABUS))
    assert note.startswith("If the user asked for a report or a document")


def test_a_message_with_an_image_is_read_from_its_text_parts():
    parts = [{"type": "text", "text": "present it to the class"},
             {"type": "image_url", "image_url": {"url": "data:image/png;base64,"}}]
    note = tool_pipeline.source_credit_note(parts, [{"role": "user",
                                                     "content": parts}])
    assert note.startswith("This reply will be heard or presented to a room")
    note = tool_pipeline.source_credit_note(
        [{"type": "text", "text": "what does this page say"}], [])
    assert note.startswith("If the user asked for a report or a document")


# ---- the standing rules ------------------------------------------------------------

def test_no_standing_rule_asks_for_a_bracketed_filename(monkeypatch):
    assert "cite [filename]" not in CHAT_SYSTEM_PROMPT
    assert "never as a bracketed filename" in CHAT_SYSTEM_PROMPT
    assert "nothing said aloud or to a class has one" in CHAT_SYSTEM_PROMPT

    monkeypatch.setattr(bt, "load_document_index", lambda: {"documents": [
        {"filename": "Job_Talk_Script7.docx", "text_preview": "My research"}]})
    expertise = bt._build_expertise_block()
    assert "[filename.pdf]" not in expertise and "[Job_Talk_Script7" not in expertise
    assert "say so in words" in expertise
    assert "short label" in expertise


def test_the_passages_header_asks_for_no_brackets_and_still_reads_as_a_read():
    text = bt._format_doc_chunks([{
        "filename": "Job_Talk_Script7.docx", "content": "Activity theory…",
        "score": 0.8, "chunk_index": 0, "total_chunks": 3}], is_expertise=True)
    assert "Cite sources inline" not in text
    assert bt._document_search_succeeded(text)


# ---- end to end ----------------------------------------------------------------------

@pytest.fixture
def reads(chat, library, monkeypatch):
    """search_documents finds the DH201 syllabus; nothing else runs."""
    def execute_tool(name, args=None, *rest, **kwargs):
        chat.executed.append({"tool": name, "args": args})
        return READ if name == "search_documents" else f"[stubbed {name}]"

    monkeypatch.setattr(bt, "execute_tool", execute_tool)
    return chat


def _note_after_the_read(chat):
    call = next(p for p in chat.model.payloads if any(
        m.get("role") == "tool" for m in p["messages"]))
    return call["messages"][-1]["content"]


def test_the_lab_title_is_answered_without_a_search(reads):
    reads.model.queue("LM Studio would be the gentle way in for that lab.")
    reply = reply_of(reads.ask(LAB_TITLE))

    assert reply == "LM Studio would be the gentle way in for that lab."
    assert reads.executed == []


def test_a_fast_path_read_is_answered_in_words(reads):
    reads.model.queue("Week 4: Lineages of AI, Wooldridge chapter 2.")
    reads.ask("what are we doing in dh201 today?")

    assert [c["tool"] for c in reads.executed] == ["search_documents"]
    note = _note_after_the_read(reads)
    assert note.startswith("[The local search_documents call above SUCCEEDED")
    assert "Put [filename]" not in note
    assert "say in words where something comes from" in note


def test_a_typed_report_with_a_syllabus_attached_is_written(reads):
    """The fast path's note reads presenting from his words only."""
    reads.model.queue("Reading Report: Reigeluth and Castelle …")
    reads.ask(ATTACHED_SYLLABUS)

    assert [c["tool"] for c in reads.executed] == ["search_documents"]
    note = _note_after_the_read(reads)
    assert "If the user asked for a report or a document" in note
    assert "heard or presented to a room" not in note


def test_a_spoken_read_has_no_brackets_at_all(reads):
    reads.model.queue("Week 4: Lineages of AI, Wooldridge chapter 2.")
    reads.ask("what are we doing in dh201 today?", voice=True)

    note = _note_after_the_read(reads)
    assert "no brackets, filenames or source labels at all" in note


def test_a_read_the_model_asks_for_is_credited_the_same_way(reads):
    """"isnt there another reading too?" (10120): the model called the
    search itself, and the loop's answer note now says how to credit it."""
    reads.model.queue(
        _tool_call("search_documents",
                   json.dumps({"query": "Week 4 October 7 readings DH201"})),
        "Two more: Chomsky's op-ed and Pasquinelli's chapter 8.")
    reads.ask("isnt there another reading too?")

    assert [c["tool"] for c in reads.executed] == ["search_documents"]
    note = _note_after_the_read(reads)
    assert note.startswith("[Answer the user naturally using the tool results "
                           "above. Do not call more tools. If the user asked "
                           "for a report or a document")


def test_a_lookup_that_found_nothing_gets_no_credit_note(chat):
    """The stub's "[stubbed search_documents]" is no read: the loop's note
    stays as it was."""
    chat.model.queue(
        _tool_call("search_documents", json.dumps({"query": "lab handout"})),
        "Nothing on that in your files.")
    chat.ask("isnt there another reading too?")

    note = _note_after_the_read(chat)
    assert note.startswith("[Answer the user naturally using the tool results "
                           "above. Do not call more tools.]")
    assert "short label" not in note and "brackets" not in note
