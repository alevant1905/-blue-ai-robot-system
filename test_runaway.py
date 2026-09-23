"""Regression tests for trimming a looping reply.

Run with: python -m pytest test_runaway.py

On 2026-09-23 the chat call (then max_tokens=-1) returned a 99,666-char reply:
one real answer, then the same "One more thing..." / "Also..." paragraphs
repeated until the model stopped. The fixture below has that shape.
"""

from blue.server.runaway import cut_repeats, to_last_sentence, trim_runaway

ANSWER = (
    "I have noted her name and role, but to recognize her face I need a clear "
    "reference photo. You can upload one on the Visual Memory page."
)
LOOP = (
    "\n\nOne more thing: since we are talking about classes, I just wanted to "
    "confirm that this is the lecture we're in right now, correct?"
    "\n\nAlso, if you have any specific goals for today's lecture, I can help "
    "keep notes or summarize key points if you'd like. Just let me know!"
)


def test_looping_reply_is_cut_after_first_pass():
    runaway = ANSWER + LOOP * 200 + "\n\nAnd since we're on the topic of the TA"
    out = trim_runaway(runaway, truncated=True)
    assert out == (ANSWER + LOOP).strip()
    assert len(out) < 600


def test_normal_reply_is_untouched():
    reply = (
        "Weekly hands-on makes sense for DH201.\n\n"
        "* **Weeks 1-3: Inspect & Compare.** Students run the same prompts.\n"
        "* **Weeks 4-7: Build & Fine-tune.** Small sandbox tasks.\n\n"
        "Want me to sketch the assessment next?"
    )
    assert trim_runaway(reply) == reply
    assert trim_runaway(reply, truncated=False) == reply


def test_chorus_and_repeated_citations_are_kept():
    chorus = ("(I'd put the librarians on a rocket to the moon)\n"
              "(I'd replace the highways with a roller coaster)\n")
    song = "Verse one goes here.\n" + chorus + "Verse two goes here.\n" + chorus
    assert trim_runaway(song) == song
    cited = ("The lab maps onto the proposal [meeting_notes_laurier_ai_proposal.md]. "
             "It also ties to sovereignty [meeting_notes_laurier_ai_proposal.md].")
    assert trim_runaway(cited) == cited


def test_short_stock_phrases_may_recur():
    reply = "Got it. I'll do that. Got it. Talk soon."
    assert cut_repeats(reply) == reply


def test_repeated_code_lines_are_not_cut():
    reply = (
        "Try this:\n```python\n"
        "print('this line is long enough to count as a sentence here')\n"
        "print('this line is long enough to count as a sentence here')\n"
        "```\nThat prints it twice."
    )
    assert trim_runaway(reply) == reply


def test_capped_reply_drops_trailing_fragment():
    text = "The first sentence is complete. The second one is also fine. And then the"
    assert to_last_sentence(text) == (
        "The first sentence is complete. The second one is also fine.")


def test_capped_reply_without_a_usable_boundary_gets_an_ellipsis():
    assert to_last_sentence("A single long clause with no end") == (
        "A single long clause with no end…")


def test_complete_capped_reply_is_kept():
    assert to_last_sentence('He said "yes."') == 'He said "yes."'


def test_empty_and_non_text_pass_through():
    assert trim_runaway("") == ""
    assert trim_runaway(None) is None
