"""The system prompt must keep a long, byte-stable cacheable prefix.

llama.cpp re-prefills from the first byte that changed. When the volatile
blocks sat at the top of the system message, <now> -- which carries the current
time -- invalidated the cache every minute, taking the persona, the rules and
the ~9,300-token tool schema down with it. Measured on the loaded 35B: 1.99s
per turn with the volatile blocks first, 0.75s with them last.

These tests pin the ordering so a later edit cannot quietly move a per-turn
block back above the stable text.
"""

import re

import bluetools as bt


VOLATILE_TAGS = ("<now>", "<location>", "<current_activity>")


def _system_text(messages=None, robot="blue"):
    msg = bt.build_dynamic_system_message(
        messages if messages is not None else [],
        bt.build_system_preamble(robot_name=bt._robot_cfg(robot)["name"]),
        robot=robot,
    )
    return msg["content"]


def test_every_volatile_block_still_appears():
    """Reordering must not have dropped a block on the floor."""
    text = _system_text()
    for tag in VOLATILE_TAGS:
        assert tag in text, f"{tag} vanished from the system prompt"


def test_no_block_is_duplicated():
    text = _system_text()
    for tag in VOLATILE_TAGS:
        assert text.count(tag) == 1, f"{tag} appears {text.count(tag)} times"


def test_identity_and_rules_come_before_the_clock():
    """The stable text is the prefix; per-turn state is the tail."""
    text = _system_text()
    now_at = text.index("<now>")
    for marker in ("IDENTITY BOUNDARY:", "EMBODIMENT", "LANGUAGES:",
                   "NO FAKE ACTIONS:", "REMINDER TIME RULES:"):
        assert marker in text, f"{marker} missing"
        assert text.index(marker) < now_at, (
            f"{marker} sits after <now> — it would be re-prefilled every turn"
        )


def test_clock_change_only_invalidates_the_tail():
    """Two turns a minute apart must share nearly the whole prompt.

    This is the property that makes the cache work: the divergence point is
    what gets re-prefilled, so it has to be deep into the message.
    """
    a = _system_text()
    b = re.sub(r"Current time: [^\n]*", "Current time: 11:11 PM (Eastern)", a)
    assert a != b, "the fixture failed to simulate a clock change"

    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    shared = common / len(a)
    assert shared > 0.80, (
        f"only {shared:.0%} of the prompt survives a clock tick; the volatile "
        "blocks have drifted back toward the top"
    )


def test_the_clock_is_readable_before_the_schedule():
    """<now> must precede the schedule blocks, cache cost notwithstanding.

    The schedule labels its entries relatively ("5 days ago (Thursday)"),
    which the model can only resolve once it knows today's date. With the
    clock placed after them it read the oldest entry and asserted it as
    "yesterday, Tuesday July 28".
    """
    text = _system_text()
    now_at = text.index("<now>")
    for marker in ("Reminders in the next", "<recent_schedule>"):
        at = text.find(marker)
        if at != -1:
            assert now_at < at, f"{marker} sits above <now>"


def test_the_library_listing_stays_in_the_cacheable_prefix():
    """The corpus dump is ~4,300 chars — a third of the prompt.

    It changes when Alex adds a document or pins a focus, not between one
    question and the next. Parking it in the tail cut the cacheable share
    from 98% to 51% on its own.
    """
    text = _system_text()
    listing = text.find("LOCAL LIBRARY")
    assert listing != -1
    assert listing < text.index("<now>"), (
        "the library listing drifted into the per-turn tail"
    )


def test_previous_replies_do_not_sit_above_the_rules():
    """anti_repetition_context quotes the last replies, so it changes every
    turn. It belongs in the tail with the rest of the per-turn state."""
    messages = [
        {"role": "user", "content": "tell me about the surveillance reading"},
        {"role": "assistant", "content": "x" * 300},
    ]
    text = _system_text(messages)
    quoted = text.find("x" * 200)
    if quoted == -1:
        return  # anti-repetition did not fire; nothing to order
    assert quoted > text.index("REMINDER TIME RULES:"), (
        "the previous reply is quoted above the stable rules"
    )
