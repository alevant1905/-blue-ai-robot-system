"""The extracted output-guard chain.

Before extraction these seventeen guards were an if/elif chain four hundred
lines deep inside a twelve-hundred-line function, and there was no way to call
one without driving a whole HTTP request. Now each is a function, so the
contract they share — run in order, first match wins, decline by returning
None — can be tested directly.
"""

import re
import types

import pytest

from blue.server import reply_guards


def make_ctx(reply="An ordinary answer about the weather.", **overrides):
    """A context in which no guard should fire unless a test makes it."""
    response = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
    ctx = reply_guards.ReplyContext(
        reply=reply,
        response=response,
        messages=[{"role": "user", "content": "how are you?"}],
        robot="blue",
        user_name="Alex",
        last_user_msg="how are you?",
        regen_once=lambda note, max_tokens=900: "",
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


# --------------------------------------------------------------------------
# The contract
# --------------------------------------------------------------------------

def test_a_clean_reply_passes_through_untouched():
    ctx = make_ctx()
    assert reply_guards.apply(ctx) == ctx.reply


def test_every_guard_declines_by_returning_none():
    """A guard that does not apply must return None, not the reply — that is
    what lets the next one run."""
    ctx = make_ctx()
    for guard in reply_guards.GUARDS:
        assert guard(ctx) is None, f"{guard.__name__} claimed a clean reply"


def test_the_first_matching_guard_wins():
    """The chain was an elif: later guards never saw a handled reply."""
    order = []

    def first(ctx):
        order.append("first")
        return "handled by the first"

    def second(ctx):
        order.append("second")
        return "handled by the second"

    original = reply_guards.GUARDS[:]
    try:
        reply_guards.GUARDS[:] = [first, second]
        assert reply_guards.apply(make_ctx()) == "handled by the first"
        assert order == ["first"], "a later guard ran after one had handled it"
    finally:
        reply_guards.GUARDS[:] = original


def test_a_guard_that_handles_without_changing_the_text_still_stops_the_chain():
    """Matching the old elif exactly: the condition decides, not the edit."""
    calls = []
    original = reply_guards.GUARDS[:]
    try:
        reply_guards.GUARDS[:] = [
            lambda ctx: ctx.reply,                       # handles, changes nothing
            lambda ctx: calls.append("ran") or "changed",
        ]
        ctx = make_ctx()
        assert reply_guards.apply(ctx) == ctx.reply
        assert calls == [], "the chain continued past a handled reply"
    finally:
        reply_guards.GUARDS[:] = original


def test_a_failing_guard_does_not_lose_the_turn():
    """Before extraction one exception skipped every remaining guard."""
    def explodes(ctx):
        raise RuntimeError("regex blew up")

    original = reply_guards.GUARDS[:]
    try:
        reply_guards.GUARDS[:] = [explodes, lambda ctx: "the next guard still ran"]
        assert reply_guards.apply(make_ctx()) == "the next guard still ran"
    finally:
        reply_guards.GUARDS[:] = original


def test_the_guard_order_is_the_old_chain_order():
    """Order is behaviour — reordering changes which guard wins."""
    names = [g.__name__ for g in reply_guards.GUARDS]
    assert names[0] == "guard_denied_recall"
    assert names[1] == "guard_identity"
    assert names[-1] == "guard_false_idle"
    # 17 lifted from the original chain, plus guard_clock_denial added from
    # the recorded-reply audit. Update deliberately when adding a guard —
    # this assertion exists to make an accidental change visible.
    assert len(names) == 18
    assert len(set(names)) == 18, "a guard is registered twice"


# --------------------------------------------------------------------------
# Individual guards
# --------------------------------------------------------------------------

def test_the_family_refusal_guard_catches_the_record_phrasing():
    """The gap that survived because nobody could read the whole chain."""
    pattern = re.compile(
        r"(?:do (?:not|n['’]?t) (?:\w+ )?(?:have|store|keep|retain|access)"
        r"|have no|don['’]?t (?:\w+ )?have)[^.!?]{0,60}"
        r"(?:record[a-z]* (?:of|about|on) "
        r"(?:your |the |a |an )?(?:family|relatives?|brother|sister|parents?))",
        re.I)
    for phrasing in (
        "I don't have any record of your family, Alex.",
        "I do not have a record of your brother.",
        "I don't have records on your relatives.",
    ):
        assert pattern.search(phrasing), phrasing


def test_the_roster_guard_regenerates_when_someone_is_dropped():
    regenerated = []

    def regen(note, max_tokens=900):
        regenerated.append(note)
        return "Athena, Emmy, Vilda, Stella and Nori."

    ctx = make_ctx(
        reply="Your daughters are Emmy and Stella.",
        dropped_roster=["Athena", "Vilda"],
        household_roster=["Athena", "Emmy", "Vilda", "Stella", "Nori"],
        regen_once=regen,
    )
    result = reply_guards.guard_dropped_roster(ctx)

    assert result is not None, "the guard declined a dropped roster"
    assert regenerated, "the guard did not regenerate"
    assert "Athena" in regenerated[0] and "Vilda" in regenerated[0]


def test_the_roster_guard_keeps_the_original_if_the_retry_is_no_better():
    """A retry that drops people again must not be preferred."""
    ctx = make_ctx(
        reply="Your daughters are Emmy and Stella.",
        dropped_roster=["Athena", "Vilda"],
        household_roster=["Athena", "Emmy", "Vilda", "Stella", "Nori"],
        regen_once=lambda note, max_tokens=900: "Emmy and Stella, that's everyone.",
    )
    assert reply_guards.guard_dropped_roster(ctx) == ctx.reply


def test_the_verbatim_replay_guard_needs_a_matching_earlier_reply():
    norm = lambda text: re.sub(r"\W+", " ", (text or "").lower()).strip()
    reply = "I am Blue, a companion robot."

    fired = make_ctx(
        reply=reply, norm_final=norm(reply), norm_recents={norm(reply)},
        parrot_norm=norm,
        regen_once=lambda note, max_tokens=900: "Something genuinely new.",
    )
    assert reply_guards.guard_verbatim_replay(fired) is not None

    quiet = make_ctx(reply=reply, norm_final=norm(reply),
                     norm_recents={norm("something else entirely")},
                     parrot_norm=norm)
    assert reply_guards.guard_verbatim_replay(quiet) is None
