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

from blue_memory_improved import (
    EnhancedMemorySystem, _extract_proper_names, _is_spelling_variant,
    _topic_terms,
)

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


# ---- topic terms, used to find Blue's own earlier answers -------------------

def test_topic_terms_keep_the_distinctive_words():
    terms = _topic_terms("the four ideas for the Laurier University meeting")
    assert {"laurier", "university", "meeting", "ideas", "four"} <= terms


def test_contractions_are_not_topic_terms():
    """"i've" appeared in 45 of Blue's answers and was enough to rank an
    unrelated two-month-old self-description alongside the real answer."""
    terms = _topic_terms("I've still got that on my mind and it's fine")
    assert "i've" not in terms
    assert "it's" not in terms


def test_possessives_reduce_to_the_name():
    assert "laurier" in _topic_terms("Laurier's AI policy")


# ---- grounding: did anyone actually say this? -------------------------------

class _FakeStore:
    """EnhancedMemorySystem.is_phrase_grounded with a corpus we control, so the
    test doesn't drift with the live database."""

    def __init__(self, docs):
        self._docs = [d.lower() for d in docs]

    _grounding_documents = lambda self: self._docs
    is_phrase_grounded = EnhancedMemorySystem.is_phrase_grounded


# One document mentioning students, a pilot program and reports — the kind of
# scattered vocabulary that made a flattened haystack call everything grounded.
CORPUS = [
    "Establish a pilot program for CMDS4740 where students are required to "
    "use and critique a local model, documenting differences in output.",
    "Propose that Laurier adopt a campus-hosted local open-source model. Blue "
    "as a pedagogical prototype for local AI infrastructure.",
    "Introduce the AI autonomy spectrum framework so Laurier can audit where "
    "it sits between commercial dependence and sovereign hosting.",
]


def test_a_phrase_that_was_actually_written_is_grounded():
    store = _FakeStore(CORPUS)
    assert store.is_phrase_grounded("Blue as a pedagogical prototype")
    assert store.is_phrase_grounded("the AI autonomy spectrum")


def test_an_invented_phrase_is_not_grounded():
    """The four items Blue made up and wrote into a reminder."""
    store = _FakeStore(CORPUS)
    assert not store.is_phrase_grounded("Sustainability Initiative")
    assert not store.is_phrase_grounded("Annual Research Symposium")
    assert not store.is_phrase_grounded("Community Impact Report")


def test_grounding_requires_words_to_co_occur_in_one_document():
    """"students", "pilot" and "report" all appear in the corpus, but never
    together — scattered words must not add up to a source."""
    store = _FakeStore(CORPUS)
    assert not store.is_phrase_grounded("Student Reporting Pilot Sovereign")


def test_grounding_abstains_when_it_cannot_judge():
    """Too few distinctive words to test. Must not report invention."""
    store = _FakeStore(CORPUS)
    assert store.is_phrase_grounded("the meeting")
    assert store.is_phrase_grounded("")


def test_grounding_abstains_when_there_is_no_corpus():
    assert _FakeStore([]).is_phrase_grounded("Annual Research Symposium")


def test_filler_questions_yield_too_few_terms_to_search():
    """A search needs at least two distinctive terms; small talk has none, which
    is what stops <earlier_answers> firing on every greeting."""
    assert len(_topic_terms("Hey Blue, how are you doing today?")) < 2
    assert _topic_terms("") == set()
    assert _topic_terms(None) == set()
