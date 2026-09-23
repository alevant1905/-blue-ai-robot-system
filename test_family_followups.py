"""Family follow-ups move on instead of repeating.

Run with: python -m pytest test_family_followups.py

On the evening of 2026-08-19 "what else", "who else is in our family" and
"think hard who else is in our family" got the same roster or the same "that
is the full set" line, and "wht about my brother" reached the model, which
said Alex has no brother. Felix, Svetlana, Chris and Tina had been in the
facts table since July.
"""

import pytest

from blue_identity import (
    canonical_family_reply_kind,
    canonical_household_reply,
    is_family_overview_request,
    known_relative_target,
)

FACTS = {
    "partner_name": "Stella",
    "partner_occupation": "Teaches visual arts at KCI",
    "partner_parent_names": "Chris, Tina",
    "partner_parent_location": "Scarborough",
    "brother_name": "Felix",
    "brother_spouse": "Svetlana",
    "daughter_name": "Athena, Emmy, Vilda",
    "athena_age": "11",
    "emmy_age": "10",
    "vilda_age": "8",
    "employer": "Wilfrid Laurier University",
    "pet_name": "Nori",
    "pet_breed": "Black Goldendoodle",
}


def thread(*turns, kid=False, user="Alex"):
    messages, replies = [], []
    for text in turns:
        messages.append({"role": "user", "content": text})
        reply = canonical_household_reply(
            text, "blue", FACTS, user, messages=messages, kid_mode=kid)
        replies.append(reply)
        messages.append({"role": "assistant", "content": reply or "a model reply"})
    return replies


def test_the_roster_names_the_relatives_on_record_and_keeps_ages():
    roster, = thread("tell me what you remember about our family")
    assert "Athena (11)" in roster, "Alex checks age corrections against it"
    assert "brother Felix and his wife Svetlana" in roster
    assert "Chris and Tina" in roster


def test_a_who_question_gets_names_not_ages():
    roster, = thread("who is in our family")
    assert "Athena" in roster and "(11)" not in roster


def test_what_else_after_the_roster_gives_the_detail():
    _, detail = thread("tell me what you remember about our family", "what else")
    assert canonical_family_reply_kind(detail) == "detail"


def test_what_else_after_something_else_is_not_about_the_family():
    assert canonical_household_reply(
        "what else", "blue", FACTS, "Alex",
        messages=[{"role": "user", "content": "dh399 is ai agents"},
                  {"role": "assistant", "content": "Right. So DH201 is Intro..."},
                  {"role": "user", "content": "what else"}]) is None


def test_the_evening_of_august_19_moves_on_each_time():
    replies = thread(
        "tell me what you remember about our family",
        "what else",
        "who else is in our family",
        "think hard who else is in our family",
    )
    kinds = [canonical_family_reply_kind(r) for r in replies]
    assert kinds == ["roster", "detail", "others", "others"]
    assert "Felix" in replies[2]
    assert replies[3] != replies[2], "a repeat is not word for word"


def test_everything_always_gets_the_full_detail():
    first, second = thread(
        "tell me everything you remember about our family",
        "tell me everything you remember about our family")
    assert canonical_family_reply_kind(first) == "detail"
    assert canonical_family_reply_kind(second) == "detail"


def test_a_roster_behind_a_briefing_prefix_is_still_recognised():
    prefixed = ("Heads up, Alex — 'DH201' is starting now. I know your family "
                "as you and Stella, your partner; ...")
    assert canonical_family_reply_kind(prefixed) == "roster"


def test_vilda_gets_names_only():
    reply, = thread("What else do you know about our family?",
                    kid=True, user="Vilda")
    assert "Vilda" in reply and "Nori" in reply
    assert "Laurier" not in reply and "(8)" not in reply


@pytest.mark.parametrize("message,expected", [
    ("wht about my brother", "Felix is your brother, and Svetlana is his wife."),
    ("who is felix", "Felix is your brother, and Svetlana is his wife."),
    ("do you remember who my brother is?",
     "Felix is your brother, and Svetlana is his wife."),
    ("what about my sister-in-law",
     "Svetlana is Felix's wife, your sister-in-law."),
    ("who are stella's parents",
     "Chris and Tina are Stella's parents; they live in Scarborough."),
])
def test_relatives_on_record_are_answered_from_the_facts(message, expected):
    assert canonical_household_reply(message, "blue", FACTS, "Alex") == expected


@pytest.mark.parametrize("message", [
    "felix is my brother",
    "what about john",
    "what about my brother's birthday",
    "is Felix coming over this weekend?",
])
def test_statements_and_other_questions_about_relatives_go_to_the_model(message):
    assert canonical_household_reply(message, "blue", FACTS, "Alex") is None


def test_a_brother_not_on_record_is_not_invented():
    facts = {k: v for k, v in FACTS.items()
             if k not in ("brother_name", "brother_spouse")}
    assert known_relative_target("what about my brother", facts) == "brother"
    assert canonical_household_reply(
        "what about my brother", "blue", facts, "Alex") is None


def test_the_household_still_wins_over_relatives():
    assert "Casper" in canonical_household_reply(
        "Who is Casper?", "blue", FACTS, "Alex")


@pytest.mark.parametrize("message", [
    "tell me about our family trip to toronto",
    "what do you remember about our family vacation",
    "who is in the family room",
    "what do you know about the family reunion",
    "tell us about the family dinner on sunday",
    "do we have someone else from our family coming to dinner?",
])
def test_a_family_event_or_room_is_not_a_roster_question(message):
    assert not is_family_overview_request(message)


@pytest.mark.parametrize("message", [
    "tell me what you remember about our family and don't use asterisks",
    "Tell me everything you remember about our family, Fasper.",
    "think hard who else is in our family",
    "who else is part of our family",
])
def test_the_logged_family_questions_still_count(message):
    assert is_family_overview_request(message)
