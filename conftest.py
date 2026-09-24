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
"""

import os

import pytest

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
os.environ.setdefault("BLUE_EMAIL_AUTOREPLY_DISABLED", "1")
os.environ.setdefault("BLUE_MEMORY_VECTORS", "0")
os.environ.setdefault("BLUE_HEADS_DISABLED", "1")


@pytest.fixture(autouse=True)
def _no_live_vector_store(monkeypatch):
    try:
        import blue_memory_improved as bmi
    except Exception:
        return
    monkeypatch.setattr(bmi, "_get_memory_collection", lambda: None)
