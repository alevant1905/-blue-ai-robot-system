"""Regression tests for name-aware memory recall.

Run with: python -m pytest test_memory_recall.py

These pin the behaviour behind a real failure (2026-07-31): Alex asked about
his meeting with "Sarah Matthews" and Blue said he had no record of it. The
record existed, but Blue had earlier corrected the spelling to "Sara" from her
email signature, and one letter was enough to drop the memory below the
embedding similarity threshold — the store held both spellings and nothing
connected them.

The alias rules are deliberately narrow. Their thresholds were tuned by
enumerating every pair they fire on across the whole live store (~190 names);
if you change one, re-run that audit rather than trusting these cases alone.
"""

import pytest

from blue_memory_improved import _extract_proper_names, _is_spelling_variant

# Pairs that must be recognised as one name spelled two ways. All three are
# real pairs that co-exist in the live store.
ALIASES = [
    ("Sarah Matthews", "Sara Matthews"),
    ("Sofie Lachapelle", "Sophie Lachapelle"),
    ("Wiikemkoong", "Wiikwemkoong"),
]

# Pairs that must NOT alias. Every one of these was observed firing during
# tuning, so they are the actual failure modes, not hypotheticals.
NOT_ALIASES = [
    ("Canada", "Canadian"),      # diverges at char 6, so the prefix rule misses it
    ("Friday", "Fridays"),       # plural
    ("Kitchen", "Kitchener"),    # a room and a city
    ("Friend", "Friendly"),      # suffix
    ("Alex", "Alexa"),           # the user and a smart speaker
    ("Emmy", "Emma"),            # two different people would be worse than a miss
    ("Stella", "Svetlana"),      # unrelated
]


@pytest.mark.parametrize("a,b", ALIASES)
def test_spelling_variants_are_linked(a, b):
    assert _is_spelling_variant(a, b), f"{a!r} and {b!r} should alias"
    assert _is_spelling_variant(b, a), "aliasing must be symmetric"


@pytest.mark.parametrize("a,b", NOT_ALIASES)
def test_unrelated_words_are_not_linked(a, b):
    assert not _is_spelling_variant(a, b), f"{a!r} and {b!r} must NOT alias"
    assert not _is_spelling_variant(b, a), "rejection must be symmetric"


def test_a_name_is_not_its_own_alias():
    assert not _is_spelling_variant("Sara Matthews", "Sara Matthews")


def test_names_are_extracted_from_a_sentence():
    assert "Sarah Matthews" in _extract_proper_names(
        "We spoke about a meeting with Sarah Matthews.")


def test_sentence_openers_are_not_read_as_names():
    """'Did Alex have a meeting?' must not yield the name 'Did Alex'."""
    assert _extract_proper_names(
        "Did Alex have an important meeting yesterday? What was it?") == []


def test_a_name_survives_a_capitalised_word_in_front_of_it():
    """Capitalisation alone can't separate a name from a sentence-initial
    verb, so the real name must still be emitted even when an unlisted word
    precedes it — losing recall is worse than one LIKE that matches nothing."""
    names = _extract_proper_names("Met Sarah Matthews at Wilfrid Laurier University")
    assert "Sarah Matthews" in names
    assert "Wilfrid Laurier University" in names


def test_lowercase_text_yields_no_names():
    assert _extract_proper_names("how are the girls doing today?") == []
    assert _extract_proper_names("") == []
    assert _extract_proper_names(None) == []
