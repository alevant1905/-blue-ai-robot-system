"""Regression tests for local-library document grounding and retries."""

import json

import pytest

import bluetools as bt
from blue.tool_selector.detectors.documents import DocumentsDetector


@pytest.fixture
def noble_record(tmp_path):
    path = tmp_path / "CMDS4740" / "Noble_Introduction.pdf"
    path.parent.mkdir()
    path.write_bytes(b"%PDF-test")
    return {
        "filename": "Noble_Introduction.pdf",
        "filepath": str(path),
        "folder": "CMDS4740",
        "text_preview": "The Power of Algorithms",
        "indexed_in_rag": True,
    }


def test_named_document_resolver_handles_title_and_voice_possessive(
        monkeypatch, noble_record):
    index = {"documents": [
        noble_record,
        {"filename": "Lyon_Chapter_1.pdf", "folder": "CMDS4740"},
    ]}
    monkeypatch.setattr(bt, "load_document_index", lambda: index)

    assert bt._resolve_document_entry(
        "look for noble introduction")["filename"] == "Noble_Introduction.pdf"
    assert bt._resolve_document_entry(
        "can you see nobles text now")["filename"] == "Noble_Introduction.pdf"
    assert bt._resolve_document_entry("try again") is None


def test_named_pdf_read_returns_extracted_text(monkeypatch, noble_record):
    extracted = (
        "The Power of Algorithms\n"
        "This book is about the power of algorithms in the age of neoliberalism "
        "and the ways digital decisions reinforce oppressive social relationships."
    )
    monkeypatch.setattr(bt, "extract_text_from_file", lambda _: extracted)

    result = bt._read_resolved_document(
        "look for noble introduction", noble_record, max_results=3)

    assert "LOCAL LIBRARY READ SUCCEEDED" in result
    assert "[Noble_Introduction.pdf]" in result
    assert "age of neoliberalism" in result
    assert "CMDS4740" in result


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("its in your library folder", False),
        ("what's in your library", True),
        ("list my documents", True),
    ],
)
def test_library_assertion_is_not_an_inventory_request(query, expected):
    assert bt._is_document_list_request(query) is expected


@pytest.mark.parametrize(
    "message",
    [
        "try again",
        "its in your library folder",
        "yes you have that tool",
        "try it again. i know you can do it",
        "why cant you access the text",
    ],
)
def test_document_followups_carry_the_recent_file(
        monkeypatch, noble_record, message):
    monkeypatch.setattr(
        bt,
        "_resolve_document_entry",
        lambda text: noble_record if "noble" in text.lower() else None,
    )
    messages = [
        {"role": "user", "content": "look for Noble introduction"},
        {"role": "assistant", "content": "I cannot access the text."},
        {"role": "user", "content": message},
    ]

    assert bt._document_followup_query(
        message, messages) == "read Noble_Introduction.pdf"


def test_this_course_followup_uses_recent_syllabus_folder(
        monkeypatch, noble_record):
    syllabus = {
        "filename": "CMDS4740_Syllabus_2026_S2.docx",
        "folder": "CMDS4740",
    }
    monkeypatch.setattr(bt, "list_library_folders", lambda: ["AI", "CMDS4740"])
    monkeypatch.setattr(
        bt,
        "_resolve_document_entry",
        lambda text: syllabus if "syllab" in text.lower() else None,
    )
    current = "reflect on who you are in relation to the critiques of ai in this course"
    messages = [
        {"role": "assistant", "content": (
            "CMDS4740_Syllabus_2026_S2.docx is in the CMDS4740 folder."
        )},
        {"role": "user", "content": current},
    ]

    query = bt._course_followup_query(current, messages)

    assert query.startswith("Based on the CMDS4740 course documents")
    assert current in query


def test_document_refusal_detector_distinguishes_grounded_answer():
    assert bt.detect_document_refusal(
        "I cannot access the text because I lack the PDF-reading tool."
    )
    assert not bt.detect_document_refusal(
        "Noble calls this technological redlining [Noble_Introduction.pdf]."
    )
    assert bt._document_search_succeeded(
        "LOCAL LIBRARY READ SUCCEEDED: [Noble_Introduction.pdf]\nActual text"
    )


def test_selector_routes_unique_five_letter_author_and_voice_form(
        monkeypatch, tmp_path):
    index_path = tmp_path / "document_index.json"
    index_path.write_text(json.dumps({"documents": [
        {"filename": "Noble_Introduction.pdf", "folder": "CMDS4740"},
        {"filename": "Lyon_Chapter_1.pdf", "folder": "CMDS4740"},
    ]}), encoding="utf-8")

    monkeypatch.setattr(
        DocumentsDetector, "_index_path",
        classmethod(lambda cls: str(index_path)),
    )
    monkeypatch.setattr(DocumentsDetector, "_lib_tokens_by_doc", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_rare_tokens", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_phrases", None)
    monkeypatch.setattr(DocumentsDetector, "_lib_mtime", -1.0)
    detector = DocumentsDetector()

    for message in ("look for noble introduction", "can you see nobles text now"):
        intents = detector.detect(message, message.lower(), {})
        assert intents
        assert intents[0].tool_name == "search_documents"
        assert intents[0].confidence >= 0.9
