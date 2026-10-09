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

import os

import pytest

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
os.environ.setdefault("BLUE_EMAIL_AUTOREPLY_DISABLED", "1")
os.environ.setdefault("BLUE_MEMORY_VECTORS", "0")
os.environ.setdefault("BLUE_HEADS_DISABLED", "1")
os.environ.setdefault("BLUE_LM_INPUT_BUDGET_TOKENS", "100000")
os.environ.pop("BLUE_THINKING_MODELS", None)
os.environ.pop("BLUE_THINKING_EFFORT", None)


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
