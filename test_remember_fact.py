"""Explicit "update your memory" has to actually write something.

Alex corrected Athena's age five times in one sitting (2026-08-19) and Blue
answered "I have updated my records" every time. He had not: no tool wrote to
the `facts` table at all, and the extractor's explicit-remember branch files
such things as a MEMORY, which <known_facts> instructs the model to trust
LESS than the stale fact it was meant to replace.

Run: python -m pytest test_remember_fact.py -q
"""

import json

import pytest

import bluetools as bt
from blue.server import tool_handlers
from blue.tool_selector.detectors.memory import MemoryDetector


# --------------------------------------------------------------- the detector

def fires(message: str):
    """The intent MemoryDetector returns for a message, or None."""
    intents = MemoryDetector().detect(message, message.lower(), {})
    return intents[0] if intents else None


STORE = [
    "I want you to update your memory so that you can know for sure in the "
    "future Athena's correct age",
    "update your records: Athena is eleven",
    "please correct your records, Athena is 11 now",
    "remember that Athena is eleven",
    "make a note that Vilda starts grade 3 in September",
    "keep in mind that Stella teaches at KCI",
    "write that down",
    "lock that in so you stop contradicting me",
]

# Questions ABOUT what Blue knows. The old extractor matched a bare
# "remember" anywhere in the message, so this exact sentence stored the
# fragment "about our family" as a user note (live 2026-08-19 07:47).
RECALL = [
    "tell me what you remember about our family",
    "what do you remember about Athena",
    "do you remember Stella's email",
    "what do you know about my courses",
    "can you remember what I said yesterday",
    "remind me what Athena's age is",
]

NOT_MEMORY = [
    "how old is Athena?",
    "we need to sell this house very soon",
    "that's not less than six weeks away",
    "don't remember that, it was wrong",
    "forget about the house viewing",
]


@pytest.mark.parametrize("message", STORE)
def test_storage_instructions_select_remember_fact(message):
    intent = fires(message)
    assert intent is not None, f"no write intent for {message!r}"
    assert intent.tool_name == "remember_fact"


@pytest.mark.parametrize("message", RECALL)
def test_asking_what_blue_knows_never_writes(message):
    assert fires(message) is None, f"recall question treated as a write: {message!r}"


@pytest.mark.parametrize("message", NOT_MEMORY)
def test_unrelated_and_negated_messages_do_not_write(message):
    assert fires(message) is None, f"spurious write intent for {message!r}"


def test_dont_forget_is_a_store_not_a_negation():
    """The negation guard must not swallow the one imperative that contains
    a negative."""
    intent = fires("don't forget that Athena is eleven")
    assert intent is not None and intent.tool_name == "remember_fact"


# ---------------------------------------------------------------- the handler

def test_saving_a_fact_reaches_the_store(monkeypatch):
    written = {}
    monkeypatch.setattr(bt, "save_blue_facts",
                        lambda facts: written.update(facts) or True)

    result = json.loads(bt.execute_tool(
        "remember_fact", {"fact_key": "athena_age", "fact_value": "11"}))

    assert written == {"athena_age": "11"}
    assert result["success"] is True


def test_a_rejected_save_is_reported_as_a_failure(monkeypatch):
    """save_facts drops junk silently. The model must be told, or it will
    announce a save that did not happen — the whole bug."""
    monkeypatch.setattr(bt, "save_blue_facts", lambda facts: False)

    result = json.loads(bt.execute_tool(
        "remember_fact", {"fact_key": "athena_age", "fact_value": "11"}))

    assert result["success"] is False
    assert "not saved" in result["message"]


def test_missing_arguments_do_not_claim_a_save(monkeypatch):
    called = []
    monkeypatch.setattr(bt, "save_blue_facts", lambda facts: called.append(facts))

    result = json.loads(bt.execute_tool("remember_fact", {}))

    assert result["success"] is False
    assert not called, "attempted a write with no key or value"


def test_a_store_failure_is_not_swallowed(monkeypatch):
    def boom(facts):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(bt, "save_blue_facts", boom)
    result = json.loads(bt.execute_tool(
        "remember_fact", {"fact_key": "athena_age", "fact_value": "11"}))

    assert result["success"] is False
    assert "database is locked" in result["message"]


# ------------------------------------------------------------------ the wiring

def test_the_tool_is_advertised_to_the_model():
    assert "remember_fact" in {t["function"]["name"] for t in (bt.TOOLS or [])}


def test_the_tool_survives_the_conversational_reflex_filter():
    """"update your memory: Athena is 11" reads as conversational, and that
    turn only offers the reflex set. A tool missing from it cannot be called
    where it matters most."""
    assert "remember_fact" in bt._REFLEX_TOOL_NAMES
