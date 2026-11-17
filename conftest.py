"""Test-suite guard: never touch the live background workers or vector store.

Importing bluetools registers the continuity routes and starts the email
auto-reply loop at module load. Without these switches, a test run starts
workers that claim real reflection jobs from data/*space/continuity.db and
run them on the live model, and — in any run longer than a minute — a real
sweep of Blue's Gmail inbox that can send replies. Pytest imports this file
before any test module, so the switches are set before bluetools loads.

The memory module's vector index is a module-global ChromaDB at
data/chromadb, shared by every EnhancedMemorySystem whatever its db_path: a
test that saved facts to a temporary database still upserted them into the
live index (2026-09-23, "athena age: 12"). BLUE_MEMORY_VECTORS=0 keeps the
suite from opening it at all: importing bluetools builds the memory system,
whose self-heal opened the live index while the server had it open.

Importing bluetools also connects every robot head and resets it to neutral.
That only failed because the running server held the serial ports; with the
server stopped, a test run would move Blue, Hexia and Casper.
BLUE_HEADS_DISABLED=1 stops the real board loaders (a fake board still works).

The read paths of the live memory DB write access counts to it; see
_no_live_memory_touches below.

Every chat payload is trimmed to the input budget, which _lm_input_budget
reads from the loaded model with a GET to LM Studio's /api/v0/models when
its cache is cold. The chat-page tests stub both transports but not that,
so a test run asked Alex's live LM Studio, sized its payloads by
whatever model was loaded (or 6,500 tokens when it was down), and wrote the
live model's id into _lm_loaded_model (whole-branch review, 10-06). A fixed
budget keeps the suite off the network and the same on every machine.

The thinking switches are the shell's, not the suite's. The README tells Alex
to export BLUE_THINKING_MODELS: set to "" in the shell that ran pytest, 22
tests failed, and with BLUE_THINKING_EFFORT=medium 20 (S1 review). The
effort is read when bluetools loads, so both go before it does; the tests
that need either set it themselves.
"""

import atexit
import json
import os
import shutil
import tempfile

import pytest

# Each robot's J-space store opens when bluetools loads, and opening one can
# write to it: the workspace invariants are re-applied and, when they change
# anything, a "corrected identity" episode is appended. A suite run on
# 2026-11-16, with the server stopped, added one to Casper's live journal.
# The suite gets stores of its own; a test that wants a particular store
# still sets these itself (test_bluejspace.py).
_JSPACE_TMP = tempfile.mkdtemp(prefix="blue-test-jspace-")
atexit.register(shutil.rmtree, _JSPACE_TMP, ignore_errors=True)
for _var, _name in (("BLUEJ_CONTINUITY_DIR", "blue"),
                    ("HEXIA_CONTINUITY_DIR", "hexia"),
                    ("PICO_CONTINUITY_DIR", "pico")):
    os.environ.setdefault(_var, os.path.join(_JSPACE_TMP, _name))

# Every model response a test fakes names a model, and Blue remembers the last
# one in data/lm_model.json to ask for it by name when none is loaded
# (blue/lm_model.py). The suite remembers into a file of its own, emptied
# before each test so no test asks for a model another one answered with.
_LM_MODEL_FILE = os.path.join(_JSPACE_TMP, "lm_model.json")
os.environ["BLUE_LM_MODEL_FILE"] = _LM_MODEL_FILE
os.environ.pop("BLUE_LM_MODEL", None)
# Likewise the chat page's Speed settings (thinking off, a context size):
# Alex's saved choice must not decide what the suite's turns send.
_MODEL_SETTINGS_FILE = os.path.join(_JSPACE_TMP, "model_settings.json")
os.environ["BLUE_MODEL_SETTINGS_FILE"] = _MODEL_SETTINGS_FILE

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
os.environ.setdefault("BLUE_EMAIL_AUTOREPLY_DISABLED", "1")
os.environ.setdefault("BLUE_MEMORY_VECTORS", "0")
os.environ.setdefault("BLUE_HEADS_DISABLED", "1")
os.environ.setdefault("BLUE_LM_INPUT_BUDGET_TOKENS", "100000")
os.environ.pop("BLUE_THINKING_MODELS", None)
os.environ.pop("BLUE_THINKING_EFFORT", None)


# The documents detector matches a message against Alex's real library, read
# from the untracked document_index.json at request time. Any test that goes
# through the selector therefore passed or failed by what was on his disk: a
# DH201 folder uploaded on 08-12 broke a chat test within two hours, and the
# Toscano file leaving the library failed two detector tests for weeks with
# no code change. The suite reads this fixed library instead, through the
# real index loader, so the tokenizer and the rare-token rules are still what
# is under test. A test that needs another library sets its own after this.
_PINNED_LIBRARY = [
    {"filename": "Toscano_Fanaticism_On_The_Uses_Of_An_Idea.pdf",
     "folder": "Toscano"},
    {"filename": "Ilyenkov_Dialectics_Of_The_Ideal.pdf", "folder": "Marx"},
    {"filename": "When_Models_Disagree_First_Transcription.txt",
     "folder": "Mark Humphries Substack"},
    {"filename": "Levant_AI_Fetish_Three_Theses.docx", "folder": "Alex Levant"},
    {"filename": "Levant_Smart_Matter.pdf", "folder": "Alex Levant"},
    # Three files in one folder, as in the real one: a folder word found in
    # more than two documents is no single-word trigger ("surveillance").
    {"filename": "Safe_Haven_Data_Policy.pdf",
     "folder": "Surveillance Studies"},
    {"filename": "Zuboff_Instrumentarianism.pdf",
     "folder": "Surveillance Studies"},
    {"filename": "Lyon_Panopticism.pdf", "folder": "Surveillance Studies"},
    {"filename": "DH201_AL_2026F_workshop.pdf", "folder": "DH201"},
    {"filename": "DH399_AL_2026F_syllabus.pdf", "folder": "DH399"},
    {"filename": "CS101_AL_2026F_syllabus.pdf", "folder": "CS101"},
]


@pytest.fixture(autouse=True)
def _no_remembered_model():
    for path in (_LM_MODEL_FILE, _MODEL_SETTINGS_FILE):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    from blue import lm_model, model_settings
    lm_model._cache.update(path=None, record=None)
    model_settings._cache.update(path=None, mtime=None, data=None)
    yield


@pytest.fixture(autouse=True)
def _pinned_library(tmp_path_factory, monkeypatch):
    try:
        from blue.tool_selector.detectors.documents import (
            DocumentsDetector as D)
    except Exception:
        return
    index = tmp_path_factory.getbasetemp() / "pinned_document_index.json"
    if not index.exists():
        index.write_text(json.dumps({"documents": _PINNED_LIBRARY}),
                         encoding="utf-8")
    # Everything _refresh_library writes is restored after each test, so a
    # test that pins its own library never leaks it into the next one.
    monkeypatch.setattr(D, "_index_path", classmethod(lambda cls: str(index)))
    monkeypatch.setattr(D, "_lib_tokens_by_doc", None)
    monkeypatch.setattr(D, "_lib_rare_tokens", None)
    monkeypatch.setattr(D, "_lib_phrases", None)
    monkeypatch.setattr(D, "_lib_mtime", -1.0)


@pytest.fixture(autouse=True)
def _no_live_vector_store(monkeypatch):
    try:
        import blue_memory_improved as bmi
    except Exception:
        return
    monkeypatch.setattr(bmi, "_get_memory_collection", lambda: None)


# Reading the live memory DB writes to it: every search_memories hit bumps
# its access_count and last_accessed (_touch_memories), and every
# <known_facts> block starts a thread that bumps use_count and last_used_at
# on the facts it shows (_touch_facts_used). Both feed recall ranking. The
# chat tests keep those read paths live on purpose, so a suite run at 21:15
# on 10-08, three hours after Alex's last turn, stamped two of his session
# memories and the 25 facts in <known_facts> (whole-branch review). Six of
# the test files alone added 2,625 to the facts' use_count and an access to
# each of the two memories. A test's own temporary database still gets them.
@pytest.fixture(autouse=True)
def _no_live_memory_touches(monkeypatch):
    try:
        import blue_memory_improved as bmi
    except Exception:
        return
    live = os.path.realpath(str(bmi.MEMORY_DB_PATH))
    for name in ("_touch_memories", "_touch_facts_used"):
        original = getattr(bmi.EnhancedMemorySystem, name, None)
        if original is None:
            continue

        def guarded(self, *args, _original=original, **kwargs):
            if os.path.realpath(str(self.db_path)) == live:
                return None
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(bmi.EnhancedMemorySystem, name, guarded)


# The chat route's J-space block (messages_with_jspace) first ingests the
# robot's recent visual observations: each becomes an episode in the LIVE
# data/<robot>space/continuity.db and queues a "perception" reflection that
# the server then runs on the real model (whole-branch review, 10-08). The
# chat fixture stubs note_exchange and begin_turn but not this. A hub on a
# test's own directory still ingests. Only patched once the routes module is
# loaded, so tests that never import bluetools don't pay for it.
@pytest.fixture(autouse=True)
def _no_live_jspace_ingest(monkeypatch):
    import sys
    routes = sys.modules.get("blue.server.routes.continuity")
    if routes is None or not hasattr(routes, "RobotContinuity"):
        return
    live = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
    original = routes.RobotContinuity.ingest_visual_observations

    def guarded(self, *args, **kwargs):
        db = os.path.realpath(str(getattr(self.store, "db_path", "")))
        if db.startswith(live + os.sep):
            return []
        return original(self, *args, **kwargs)

    monkeypatch.setattr(routes.RobotContinuity, "ingest_visual_observations", guarded)
