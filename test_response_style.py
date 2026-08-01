"""Regression tests for conversational response style.

Run with: python -m pytest test_response_style.py

Measured across assistant replies since 2026-06-01: a content-free closing
offer on 14% of Blue's, 17% of Hexia's and 20% of Casper's; emoji on 15% / 42%
/ 51%. A strong "no lists, no emoji, get to the point" rule already existed but
applied only to SPOKEN turns, so typed chat had nothing at all — and Casper's
four-turn chat on 2026-08-01 closed every single turn with "Is there anything
specific you'd like me to help with? 😊".
"""

import pytest

from blue.utils import strip_conversational_filler as strip

CLOSERS = [
    "Is there anything specific you wanted to know about them?",
    "Is there anything else I can help with?",
    "Let me know if you need anything else!",
    "Let me know if you have any questions.",
    "How can I help you with everyone being home?",
    "Hope that helps!",
    "Feel free to ask if you need more.",
]


@pytest.mark.parametrize("closer", CLOSERS)
def test_closing_filler_is_removed(closer):
    body = "Your meeting with Sara Matthews is tomorrow at 10am."
    assert strip(f"{body} {closer}") == body


def test_several_closers_are_all_removed():
    assert strip("The girls are Athena, Emmy and Vilda. Is there anything "
                 "else? Let me know!") == "The girls are Athena, Emmy and Vilda."


def test_a_genuine_offer_is_kept():
    """"Would you like me to set a reminder?" is a real question the user
    answers. Stripping it would break the interaction."""
    text = "I added it to your calendar. Would you like me to set a reminder as well?"
    assert strip(text) == text


def test_substantive_replies_are_untouched():
    text = "Your meeting with Sara Matthews is tomorrow at 10am in the Arts building."
    assert strip(text) == text


# ---- emoji -------------------------------------------------------------------

def test_emoji_are_removed_by_default():
    assert strip("Thanks for catching that. 🙈 Emmy is 10. 😊") == \
        "Thanks for catching that. Emmy is 10."


def test_emoji_survive_for_the_kids_page():
    """Vilda's iPad is meant to be friendly; the strip is for the adult chat."""
    text = "That sounds fun! 😊"
    assert strip(text, allow_emoji=True) == text


def test_emoji_removal_does_not_leave_double_spaces():
    assert "  " not in strip("Emmy is 10 🙈 and Athena is 10.")


# ---- structure ---------------------------------------------------------------

def test_paragraph_breaks_survive():
    """An earlier version split the whole reply into sentences and rejoined
    with spaces, silently flattening every paragraph break in long answers."""
    text = "First paragraph here.\n\nSecond paragraph here."
    assert strip(text) == text


def test_a_bulleted_body_survives_while_its_closer_goes():
    text = ("Your readings:\n"
            "* **Chapter 2** of Surveillance, Media and Society\n"
            "* **Chapter 6** of The Education Industrial Complex\n\n"
            "Let me know if you need any help with the readings!")
    out = strip(text)
    assert "Chapter 6" in out and "* **Chapter 2**" in out
    assert "Let me know" not in out


# ---- safety ------------------------------------------------------------------

def test_a_reply_that_is_only_a_closer_is_kept():
    """Better to answer with a closer than with nothing."""
    text = "Is there anything else I can help with?"
    assert strip(text) == text


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_is_returned_unchanged(text):
    assert strip(text) == text


def test_output_is_never_empty_for_non_empty_input():
    for text in ("Hope that helps!", "Let me know!", "😊", "Anything else?"):
        assert strip(text).strip()
