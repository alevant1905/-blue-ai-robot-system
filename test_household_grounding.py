"""Regression tests for household grounding in conversation.

Run with: python -m pytest test_household_grounding.py

From a four-turn chat with Casper on 2026-08-01 in which he invented the
household three times over. Asked "do you remember everyone's names" he
apologised for a correction nobody had made, listed ages nobody asked for, and
got two of them wrong; asked again he gave different wrong ages; asked a third
time he offered "the correct list" with two of the three daughters missing.

Four independent guards failed. Each is pinned below. The functions live in
bluetools/blue_identity and are shared by all three robots, so these cover
Blue and Hexia too.

bluetools imports cannot be taken directly — importing it starts live threads
and can act on the real house — so the pure functions are lifted out with ast.
"""

import ast
import re
import textwrap

import pytest

from blue_identity import is_phantom_correction_ack

BLUETOOLS = "bluetools.py"
_SRC = open(BLUETOOLS, encoding="utf-8").read()
_TREE = ast.parse(_SRC)


def _lift(*names):
    """Exec the named module-level functions/assignments in isolation."""
    ns = {"re": re, "List": list}
    for node in _TREE.body:
        if isinstance(node, ast.Assign):
            target = getattr(node.targets[0], "id", "")
            if target in names:
                exec(compile(ast.Module(body=[node], type_ignores=[]),
                             "<c>", "exec"), ns)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(textwrap.dedent(ast.get_source_segment(_SRC, node)),
                         "<f>", "exec"), ns)
    return ns


NS = _lift("_misstated_ages", "_AGE_TAIL", "_NOT_AN_AGE_RE",
           "_dropped_household_members", "_ROSTER_QUERY_RE",
           "_COMPLETENESS_CLAIM_RE", "_FAMILY_QUERY_RE")

AGES = {"emmy": "10", "athena": "10", "vilda": "8"}
ROSTER = ["Athena", "Emmy", "Vilda", "Stella", "Nori"]


# ---- 1. wrong ages stated without a unit ------------------------------------

@pytest.mark.parametrize("reply", [
    "Emmy is 10. Athena is 8. Vilda is 5.",
    "* **Emmy** is **10**. * **Athena** is **8**. * **Vilda** is **5**.",
    "Athena is 8 years old",
])
def test_wrong_ages_are_caught(reply):
    """The guard used to require "years old" or brackets, so the bare form —
    the one the models actually write — went through unchecked."""
    assert NS["_misstated_ages"](reply, AGES)


@pytest.mark.parametrize("reply", [
    "Emmy is 10, Athena is 10, Vilda is 8",
    "Emmy is 10 minutes away from home",
    "Athena is in grade 5",
    "Athena is on page 5 of her book",
    "vilda goes to bed at 8",
])
def test_correct_or_non_age_numbers_are_not_flagged(reply):
    assert not NS["_misstated_ages"](reply, AGES)


# ---- 2. apologising for a correction nobody made ----------------------------

@pytest.mark.parametrize("user,reply", [
    ("do you remember everyones names",
     "Oops! Thanks for catching that. I must have mixed up the digits again."),
    ("not just the kids",
     "You're right! Let me update my memory: Emmy is 10."),
    ("stella is my partner. we also have a dog named nori",
     "My bad! I really need to lock this in. Thanks for the correction."),
])
def test_informal_phantom_apologies_are_caught(user, reply):
    """Only stiff phrasings ("I stand corrected") were listed; the local models
    apologise in a much more casual register."""
    assert is_phantom_correction_ack(reply, user)


@pytest.mark.parametrize("user,reply", [
    ("no, their ages are wrong", "My bad! Emmy is 10."),
    ("actually Vilda is 8", "You're right, Vilda is 8."),
    ("that is incorrect", "I stand corrected."),
])
def test_real_corrections_may_still_be_acknowledged(user, reply):
    assert not is_phantom_correction_ack(reply, user)


# ---- 3. the household block must reach roster questions ---------------------

@pytest.mark.parametrize("msg", [
    "everyone is home",
    "do you remember everyones names",
    "do you remember everyone's names",
    "not just the kids",
    "who lives here",
    "can you name everyone in the household",
    "tell me the names of the kids",
])
def test_roster_questions_inject_the_family_facts(msg):
    assert NS["_FAMILY_QUERY_RE"].search(msg)


@pytest.mark.parametrize("msg", [
    "what is the weather today",
    "turn off all the lights",
    "when is my meeting with mark humphries",
    "search my documents for surveillance",
])
def test_unrelated_messages_do_not(msg):
    assert not NS["_FAMILY_QUERY_RE"].search(msg)


# ---- 4. a roster answer that loses people -----------------------------------

def _dropped(user, reply):
    gate = (NS["_ROSTER_QUERY_RE"].search(user)
            or NS["_COMPLETENESS_CLAIM_RE"].search(reply))
    return NS["_dropped_household_members"](reply, ROSTER) if gate else []


def test_a_partial_list_offered_as_complete_is_caught():
    """Casper's third answer, presented as "the correct list"."""
    assert _dropped(
        "stella is my partner. we also have a dog named nori",
        "My bad! Here is the correct list: Emmy is 10. Stella (your partner). Nori.",
    ) == ["Athena", "Vilda"]


def test_naming_only_the_children_for_a_roster_question_is_caught():
    assert _dropped("do you remember everyones names",
                    "Emmy is 10. Athena is 10. Vilda is 8.") == ["Stella", "Nori"]


def test_a_complete_roster_passes():
    assert not _dropped(
        "do you remember everyones names",
        "Athena, Emmy and Vilda are the girls; Stella is your partner and "
        "Nori is the dog.")


def test_a_narrower_question_is_answered_completely_by_the_children():
    """"How old are the girls" answered with the three daughters is correct.
    Flagging it for omitting the dog would be worse than the original bug."""
    assert not _dropped("how old are the girls",
                        "Emmy and Athena are both 10, and Vilda is 8.")


def test_mentioning_someone_in_passing_is_not_a_roster():
    assert not _dropped("is emmy home",
                        "Yes, Emmy got back an hour ago and Stella is with her.")
