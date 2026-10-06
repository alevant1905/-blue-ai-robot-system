"""Asking Blue to learn a face, from the 2026-10-05 harness.

"remember what she looks like so next time you recognize her" got "Done —
I've got her look on file: bread-bun hat, strawberry skirt" (pre-Phase-1
main) and "I'll remember her as the student in the bread-bun hat and
strawberry skirt" (recited from 09-23). Nothing said in chat saves a face.
is_face_request decides when the FACE REQUEST note goes in; run over the
5,056 logged user turns it matches exactly the six real requests below.
"""

import pytest

from blue.tool_selector.detectors.vision import is_face_request, is_own_face_request


@pytest.mark.parametrize("text", [
    # The six real requests (2026-05-24 x5, 2026-09-23).
    "i want you to remember what they look like so you can recognize them next time",
    "very good. understand that they move around. its best to remember what "
    "they look like instead of where they are.",
    "good. its athena and vilda at the table. try to get a good look at them "
    "so you can remember what they look like",
    "take a fresh look at the girls at the table so you can remember what they look like",
    "She wears different things. Try to remember what she looks like",
    "I want you to remember what she looks like so next time you can recognize "
    "her can you do that?",
    # The harness turn.
    "remember what she looks like so next time you recognize her",
    "remember her face",
    "can you remember his face?",
    "remember what Clover looks like",
    "remember clover's face",
    "learn what he looks like",
    "I'll show you Felix so you can recognize him next time",
])
def test_asking_blue_to_learn_a_face(text):
    assert is_face_request(text)


@pytest.mark.parametrize("text", [
    "do you remember what she looks like?",
    "Do u remember what Felix looks like?",
    "do you remember what everyone in the family looks like?",
    "what does she look like?",
    "don't remember her face",
    "remember that she is 11",
    "can you recognize faces?",
    "she looks like her mom",
    "remember what this room looks like",
    "remember what that painting looks like",
    "remember what it looks like when the lights are off",
    "keep his face out of the photos",
    "record her face for the video",
    "remember that face you made yesterday, so funny",
    "she's the TA, so that you know her schedule",
    "that's Clover, she's a TA for CS101",
    "Do you remember what you look like.",
])
def test_not_a_request_to_learn_a_face(text):
    assert not is_face_request(text)


def test_a_request_about_the_speakers_own_face():
    assert is_own_face_request("remember my face so you can recognize me")
    assert is_own_face_request("remember what I look like")
    assert not is_own_face_request("remember what she looks like")
