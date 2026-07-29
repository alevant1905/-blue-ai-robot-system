"""Regression tests for local-library document grounding and retries."""

import json

import pytest

import bluetools as bt
from blue.tool_selector.detectors.documents import DocumentsDetector
from blue.tool_selector.detectors.simple_detectors import TimersDetector


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


def test_selector_does_not_turn_shared_class_memory_into_document_search():
    detector = DocumentsDetector()
    message = "What did you think of our class yesterday at York University?"
    assert detector.detect(message, message.lower(), {}) == []


def test_recall_wording_does_not_create_a_reminder():
    detector = TimersDetector()
    message = "Can you remind me of what you did yesterday?"
    assert detector.detect(message, message.lower(), {}) == []

    scheduled = "Remind me tomorrow to call Mom"
    intents = detector.detect(scheduled, scheduled.lower(), {})
    assert intents and intents[0].tool_name == "create_reminder"


def test_dated_recall_context_is_not_treated_as_user_intent():
    pinned = (
        '<dated_episode_recall date="2026-07-16">\n'
        '- Alex asked: what do you see in the classroom?\n'
        '</dated_episode_recall>\n\n'
        'Do you remember what the class looked like?'
    )
    assert bt._intent_text(pinned) == "Do you remember what the class looked like?"
    assert not bt.detect_camera_capture_intent(bt._intent_text(pinned))


def test_shared_recall_followup_inherits_recent_yesterday_anchor():
    current = "Do you remember what the class looked like?"
    messages = [
        {"role": "user", "content": "What did you do yesterday?"},
        {"role": "assistant", "content": "I joined you at your York class."},
        {"role": "user", "content": current},
    ]
    query = bt._temporal_recall_query(current, messages)
    assert query.startswith(current)
    assert "Referenced time from the preceding exchange: yesterday" in query


def test_face_match_is_saved_even_when_vision_prose_omits_the_name(
        monkeypatch, tmp_path):
    image = tmp_path / "capture.jpg"
    image.write_bytes(b"camera frame")
    recorded = {}

    class FakeVisualMemory:
        def get_recognition_people(self):
            return [{"name": "Alex", "relationship": "creator"}]

        def resolve_person_name(self, name):
            return "Alex" if "Alex" in name else name

        def canonicalize_people(self, names):
            return list(dict.fromkeys(self.resolve_person_name(n) for n in names))

        def get_all_places(self):
            return []

        def log_observation(self, **kwargs):
            recorded["observation"] = kwargs
            return 71

        def update_seen(self, *args, **kwargs):
            recorded.setdefault("seen", []).append((args, kwargs))
            return True

    monkeypatch.setattr(bt, "VISUAL_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "get_visual_memory", lambda: FakeVisualMemory())
    monkeypatch.setattr(bt, "_last_vision_image_paths", [str(image)])
    monkeypatch.setattr(bt, "_last_vision_recognition", {
        "observer": "hexia",
        "matches": [{
            "name": "Alex (Doctor Levant)",
            "confidence": 0.84,
            "method": "opencv_sface",
        }],
    })

    bt._save_visual_observation(
        "A person is seated in a bright office.", observer="hexia")

    observation = recorded["observation"]
    assert observation["observer"] == "hexia"
    assert observation["people_present"] == ["Alex"]
    assert observation["recognition"][0]["name"] == "Alex"
    assert recorded["seen"][0][1] == {
        "observer": "hexia",
        "confidence": 0.84,
        "observation_id": 71,
    }
