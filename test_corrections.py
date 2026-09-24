"""Corrections that stick, and claims that match what really happened.

Run with: python -m pytest test_corrections.py

From the 2026-09-23 audit. On 08-19, four days after Athena turned 11, Blue
said "Athena is 10. Her birthday is August 15, so she hasn't turned 11 yet":
ages were stored as a number and never moved. "Athena is no longer 10" and
"I want you to update your memory…" wrote nothing, yet Blue said "I have
updated my records". A clock time ("Emmy's appointment at 11:00 AM") read
as an age and got correct schedule answers regenerated.
"""

import ast
import re
import textwrap
from datetime import date

import pytest

import bluetools as bt  # before blue.server.*: they import it back
from blue_identity import age_on, derive_ages


# ---- ages come from a birthdate ---------------------------------------------

@pytest.mark.parametrize("today,expected", [
    (date(2026, 8, 14), 10),
    (date(2026, 8, 15), 11),
    (date(2026, 8, 19), 11),
    (date(2027, 8, 15), 12),
])
def test_an_age_is_worked_out_from_the_birthdate(today, expected):
    assert age_on("2015-08-15", today) == expected


def test_derived_ages_replace_the_stored_number():
    facts = {"athena_age": "10", "athena_birthdate": "2015-08-15", "emmy_age": "10"}
    out = derive_ages(facts, date(2026, 8, 19))
    assert out["athena_age"] == "11"
    assert out["emmy_age"] == "10", "no birthdate: the stored age stands"


def test_a_malformed_birthdate_derives_nothing():
    assert derive_ages({"athena_age": "10", "athena_birthdate": "August 15"},
                       date(2026, 8, 19))["athena_age"] == "10"


@pytest.fixture
def memory(tmp_path, monkeypatch):
    import datetime as dt
    import blue_memory_improved as bmi

    class Aug19(dt.date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 19)

    monkeypatch.setattr(bmi, "date", Aug19)
    return bmi.EnhancedMemorySystem(db_path=str(tmp_path / "facts.db"))


def test_a_stated_age_moves_the_birth_year_not_a_stale_number(memory):
    memory.save_facts({"athena_birthdate": "2015-08-15", "athena_age": "10"})
    assert memory.load_facts()["athena_age"] == "11"

    assert memory.save_facts({"athena_age": "11"}), "already true is a success"
    assert memory.load_facts()["athena_birthdate"] == "2015-08-15"

    # A background extraction ("why did you say Athena is 10?") must not move it.
    memory.save_facts({"athena_age": "10"})
    assert memory.load_facts()["athena_birthdate"] == "2015-08-15"

    # An explicit remember_fact does.
    memory.save_facts({"athena_age": "12"}, age_moves_birthdate=True)
    facts = memory.load_facts()
    assert facts["athena_birthdate"] == "2014-08-15"
    assert facts["athena_age"] == "12"


def test_the_prompt_block_shows_the_derived_age(memory):
    memory.save_facts({"athena_birthdate": "2015-08-15", "athena_age": "10"})
    block = memory._build_facts_block()
    assert re.search(r"Athena Age: 11", block)


def test_a_dictated_email_is_not_a_fact(memory):
    assert memory._is_junk_fact("email_address", "ALEVAT at gmail.com")
    assert not memory._is_junk_fact("stella_email", "stella.andonoff@gmail.com")
    assert not memory._is_junk_fact("alex_emails", "a@x.com, b@y.ca")
    assert not memory._is_junk_fact("email_preference", "prefers email over phone")


# ---- dates and times are not ages ---------------------------------------------

SRC = open("bluetools.py", encoding="utf-8").read()
TREE = ast.parse(SRC)
NS = {"re": re}
for node in TREE.body:
    if (isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") in ("_AGE_TAIL", "_NOT_AN_AGE_RE")):
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<a>", "exec"), NS)
    if isinstance(node, ast.FunctionDef) and node.name == "_misstated_ages":
        exec(textwrap.dedent(ast.get_source_segment(SRC, node)), NS)
AGES = {"emmy": "10", "athena": "11", "vilda": "8"}


@pytest.mark.parametrize("reply", [
    "Athena’s birthday is August 15. I just set a reminder for it for you.",
    "Emmy’s dentist appointment at 11:00 AM (I’ve got a reminder set for 10:30 AM)",
    "It's Emmy's doctor's appointment on Thursday, May 21 at 2:40 PM.",
    "Athena was born in 2015.",
    "Athena's birthday is 8/15.",
    "Emmy's birthday is March 3.",
    "Vilda's swim lesson is at 4:30.",
    "Emmy has the dentist at 11:00, then school.",
])
def test_a_date_or_a_time_is_not_an_age(reply):
    assert NS["_misstated_ages"](reply, AGES) == {}


@pytest.mark.parametrize("reply", [
    "Athena is 8. Her birthday is August 15.",
    "Athena (8), Emmy (10), Vilda (5).",
    "Athena is 10 years old.",
])
def test_a_wrong_age_is_still_caught(reply):
    assert NS["_misstated_ages"](reply, AGES)


# ---- claims must match what the tools did --------------------------------------

from blue.server.turn_completion import _scrub_unbacked_write_claims as scrub  # noqa: E402


def test_a_claimed_save_answering_a_question_is_removed():
    reply = "She's 11 now. I've updated my records so it sticks this time."
    assert scrub(reply, [], user_text="How old is athena") == "She's 11 now."


def test_a_statement_may_still_be_saved_after_the_reply():
    """The background extractor saves plain statements after the reply."""
    reply = "Got it. I've updated my notes: Vilda is not in French immersion."
    assert scrub(reply, [], user_text="vilda is not in french immersion") == reply


def test_a_reminder_or_task_write_backs_a_locked_in_claim():
    for tool in ("create_reminder", "reschedule_reminder", "create_task"):
        reply = "I've locked it in for Friday at 3 PM."
        assert scrub(reply, [{"name": tool, "success": True}],
                     user_text="remind me friday at 3 to call the dentist") == reply


def test_completed_reminders_back_a_cleared_claim():
    reply = "Done — I've cleared the two remaining CMDS4740 reminders."
    assert scrub(reply, [{"name": "complete_reminder", "success": True}],
                 user_text="yes") == reply


def test_an_earlier_save_backs_did_you_save_that():
    reply = "Yes, I've saved that to my memory."
    assert scrub(reply, [], user_text="did you save that?",
                 recent={"remember_fact"}) == reply


@pytest.mark.parametrize("reply", [
    "All I have saved in my memory about Felix is that he's your brother.",
    "Everything I have stored in my notes says Athena turned 11 on August 15.",
    "The only address I have saved in my records is stella.andonoff@gmail.com.",
])
def test_recall_is_not_a_claim(reply):
    assert scrub(reply, [], user_text="what do you know about felix?") == reply


def test_a_real_save_keeps_its_claim():
    reply = "Done, Alex. Athena is eleven now, and I've locked that in."
    outcomes = [{"name": "remember_fact", "success": True}]
    assert scrub(reply, outcomes) == reply


def test_nothing_is_judged_when_nobody_was_collecting():
    reply = "I have updated my records."
    assert scrub(reply, None) == reply


def test_a_claimed_cleared_reminder_with_no_reminder_tool_is_removed():
    reply = ("Right here. Just finished clearing out those last CMDS4740 "
             "reminders, so the schedule's finally calm.")
    assert "clearing" not in scrub(reply, [])


def test_asking_to_be_told_is_not_a_claim():
    reply = "Please tell me what it is so I can lock it in correctly this time."
    assert scrub(reply, []) == reply


def test_a_bare_claim_becomes_an_honest_not_saved():
    out = scrub("Got it. I've updated my memory for Vilda: she's eight.", [],
                user_text="remember that vilda is eight")
    assert "isn't saved" in out


# ---- voice turns and check-backs --------------------------------------------------

def test_a_named_guess_is_a_check_back_and_a_vague_one_is_not():
    assert bt._CHECKBACK_RE.search(
        "I didn't catch that — did you mean how old is Athena?")
    assert not bt._CHECKBACK_RE.search("Did you mean something specific?")


def test_a_check_back_is_not_a_denial_of_a_known_person():
    from blue.server.turn_completion import denies_a_known_person
    assert not denies_a_known_person(
        "I don't know who Howl Satina is — did you mean how old is Athena?")


def test_placeholder_recipients_are_refused_before_gmail_is_touched(monkeypatch):
    called = []
    monkeypatch.setattr(bt, "get_gmail_service", lambda: called.append(1))
    monkeypatch.setattr(bt, "GMAIL_AVAILABLE", True)
    for to in ("alex.levant@example.com", "Alex Levant <alex.levant@example.com>",
               "alex.levant@example.com."):
        result = bt._execute_send_gmail({"to": to, "subject": "Draft", "body": "x"})
        assert '"success": false' in result, to
    assert called == []


def test_the_kids_page_cannot_write_facts():
    assert "remember_fact" in bt._KID_BLOCKED_TOOLS


def test_the_send_detector_needs_an_instruction():
    from blue.tool_selector.selector import ImprovedToolSelector
    selector = ImprovedToolSelector()

    def tool(message):
        primary = selector.select_tool(message, []).primary_tool
        return primary.tool_name if primary else None

    for message in ("Did you send the photo to stella.andonoff@gmail.com?",
                    "Don't send anything to stella.andonoff@gmail.com yet",
                    "Stella said she would send the forms to alevant@yorku.ca next week",
                    "Did you send an email to Stella?"):
        assert tool(message) != "send_gmail", message
    for message in ("send it to stella@example.com",
                    "can you send the photo to x@y.com",
                    "please send the draft to alevant@yorku.ca"):
        assert tool(message) == "send_gmail", message


def test_your_brother_asked_of_the_robot_is_not_alexs_brother():
    from blue_identity import canonical_household_reply
    facts = {"brother_name": "Felix", "brother_spouse": "Svetlana",
             "daughter_name": "Athena, Emmy, Vilda"}
    assert canonical_household_reply("who is your brother?", "blue", facts, "Alex") is None


def test_a_yes_to_an_offer_can_still_be_a_phantom_correction():
    from blue_identity import is_phantom_correction_ack
    assert is_phantom_correction_ack("Right. I stand corrected—Athena is 10.", "yes")
    assert is_phantom_correction_ack(
        "You're right—I've been stuck in my introduction loop.",
        "tell the class about yourself")


def test_a_fresh_database_can_store_memories(memory):
    """The insert fills legacy columns the new schema never created, so every
    memory saved to a new database failed with only a printed warning."""
    import sqlite3
    memory._store_memory("event", "swim", "Vilda swam her first length today.")
    with sqlite3.connect(memory.db_path) as conn:
        rows = conn.execute("SELECT content FROM memories").fetchall()
    assert rows == [("Vilda swam her first length today.",)]
