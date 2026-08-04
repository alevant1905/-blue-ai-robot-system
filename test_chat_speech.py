"""Neural speech is pipelined: synthesise the next chunk while this one plays.

Each neural chunk costs a synthesis round trip before it can be heard, and the
cost scales with length — measured against the running service, a 478-character
reply took 3.79s to render as one request against 1.33s for its first sentence.
Rendering the whole reply up front meant that entire wait was silence.

The browser voice is unaffected: it renders locally and was already chunked.
"""

import re

import pytest
from flask import Flask

from blue.server.pages.chat import CHAT_HTML


@pytest.fixture(scope="module")
def page():
    app = Flask("chat-speech-test")
    with app.app_context():
        from flask import render_template_string
        return render_template_string(
            CHAT_HTML,
            robot_json='{"id":"blue","name":"Blue","head":"blue","accent":"#3da9fc",'
                       '"voicePitch":1.0,"voiceRate":1.0}',
            documents_json="[]",
            folders_json="[]",
            voice_preferences_json="{}",
            robots_json="{}",
            places_json="[]",
            voice_pref_json="{}",
        )


def test_neural_speech_uses_its_own_chunker(page):
    """speechChunks groups to 220 chars — right for a local voice, ~3s of
    silence for a synthesised one."""
    assert "function neuralChunks(" in page
    assert "neuralChunks(msg)" in page, "speakNeural is not using the neural chunker"


def test_the_first_chunk_is_a_single_sentence(page):
    """That chunk alone decides time-to-first-word."""
    body = page[page.index("function neuralChunks("):]
    body = body[:body.index("\n        }") + 10]
    assert "sentences[0]" in body
    assert "sentences.slice(1)" in body
    # Later chunks keep the bigger grouping — they render during playback.
    assert "speechChunks(rest)" in body


def test_the_next_chunk_is_synthesised_before_the_current_one_finishes(page):
    """The entire point: overlap synthesis with playback."""
    body = page[page.index("async function speakNeural("):]
    body = body[:body.index("\n        function speak(")]
    # The prefetch is started BEFORE awaiting the current chunk.
    prefetch = body.index("pending = (i + 1 < chunks.length)")
    await_current = body.index("await current")
    assert prefetch < await_current, (
        "the next chunk is only requested after the current one is awaited — "
        "that is sequential, not pipelined"
    )
    assert "await playChunk(" in body


def test_an_inflight_prefetch_cannot_raise_unhandled(page):
    body = page[page.index("async function speakNeural("):]
    assert "pending.catch(" in body[:body.index("\n        function speak(")]


def test_a_failure_only_respeaks_what_was_not_said(page):
    """Falling back from the top would repeat sentences already heard."""
    body = page[page.index("async function speakNeural("):]
    body = body[:body.index("\n        function speak(")]
    assert "chunks.slice(spokenUpTo)" in body
    assert "speakBrowser(remaining)" in body


def test_lips_are_driven_per_chunk(page):
    """Lip frames are a timed schedule; one schedule for the whole reply would
    drift against audio that arrives in pieces."""
    body = page[page.index("function playChunk("):]
    body = body[:body.index("\n            }") + 14]
    assert "buildLipFrames(text, rate)" in body, (
        "lip frames are still built from the whole message, not the chunk"
    )


def test_a_voice_preview_is_not_chunked(page):
    """A preview is one short sample — splitting it buys nothing."""
    body = page[page.index("async function speakNeural("):]
    assert "previewOnly ? [msg] : neuralChunks(msg)" in body


def test_the_talking_state_is_entered_once(page):
    """Not re-entered per chunk, or the head would restart mid-sentence."""
    body = page[page.index("function playChunk("):]
    body = body[:body.index("\n            }") + 14]
    assert "if (!started)" in body


def test_browser_speech_still_uses_the_plain_chunker(page):
    """It renders locally; the neural split would only add utterance breaks."""
    body = page[page.index("function speakBrowser("):]
    body = body[:body.index("\n        async function speakNeural(")]
    assert "speechChunks(msg)" in body
    assert "neuralChunks(" not in body
