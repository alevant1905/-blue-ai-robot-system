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
live index (2026-09-23, "athena age: 12"). Every test gets no vector store.
"""

import os

import pytest

os.environ.setdefault("BLUE_CONTINUITY_THREADS", "0")
os.environ.setdefault("BLUE_EMAIL_AUTOREPLY_DISABLED", "1")


@pytest.fixture(autouse=True)
def _no_live_vector_store(monkeypatch):
    try:
        import blue_memory_improved as bmi
    except Exception:
        return
    monkeypatch.setattr(bmi, "_get_memory_collection", lambda: None)
