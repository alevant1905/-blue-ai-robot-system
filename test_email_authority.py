"""What an inbound email is allowed to make Blue do.

Mail arriving in Blue's inbox can reach the tool loop. A message that passes
as Alex gets the full set — send mail, control the house, set reminders —
so `_email_sender_is_owner` is a security boundary, not a convenience: it is
the only thing between a forged From line and the lights.

Nothing covered it before this file.

SAFETY: these call the two predicates directly. No inbox is read, no reply is
composed, and no tool is executed.
"""

import pytest

import bluetools as bt


OWNER = sorted(bt.BLUE_OWNER_ADDRESSES)[0]


def _headers(auth):
    return [{"name": "Authentication-Results", "value": auth}] if auth else []


# --------------------------------------------------------------------------
# Who counts as Alex
# --------------------------------------------------------------------------

@pytest.mark.parametrize("auth", [
    "mx.google.com; dkim=pass header.i=@gmail.com",
    "mx.google.com; spf=pass; dmarc=pass (p=NONE)",
    "mx.google.com; dkim=pass; dmarc=pass",
])
def test_owner_mail_with_a_passing_stamp_is_trusted(auth):
    assert bt._email_sender_is_owner(_headers(auth), f"Alex <{OWNER}>") is True


def test_an_unstamped_message_is_not_trusted():
    """No Authentication-Results at all: be conservative, do not elevate.

    Gmail stamps every inbound message, so its absence means this did not
    arrive the way a real email does.
    """
    assert bt._email_sender_is_owner([], f"Alex <{OWNER}>") is False


@pytest.mark.parametrize("auth", [
    "mx.google.com; dkim=fail header.i=@gmail.com",
    "mx.google.com; dmarc=fail (p=REJECT)",
    "mx.google.com; dkim=pass; dmarc=fail",
    "mx.google.com; dkim=fail; dmarc=pass",
])
def test_a_failing_stamp_is_never_trusted_even_alongside_a_pass(auth):
    """A forged From for a gmail.com address cannot carry a valid signature."""
    assert bt._email_sender_is_owner(_headers(auth), f"Alex <{OWNER}>") is False


def test_a_stranger_with_a_perfect_stamp_is_still_a_stranger():
    """Passing DKIM proves the sender is who they say — not that they are Alex."""
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass; dmarc=pass"),
        "Someone Else <stranger@example.com>") is False


@pytest.mark.xfail(reason="known gap, reported 2026-08-19; see the docstring",
                   strict=True)
def test_a_display_name_cannot_borrow_the_owner_address():
    """An attacker should not become Alex by putting his address in the name.

    Currently they do. The check pulls EVERY address out of the From line and
    asks whether any of them is an owner address, so
        From: "alevant1905@gmail.com" <attacker@example.com>
    satisfies it. The DKIM stamp is then checked only for the string
    "dkim=pass" anywhere in Authentication-Results — and that passes for the
    attacker's own domain, because they really do control example.com.

    The docstring on _email_sender_is_owner says a spoofed From "won't carry a
    valid DKIM signature", which is true of spoofing the ADDRESS and not of
    this. Marked strict so it fails loudly the day it is fixed.
    """
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass header.i=@example.com; dmarc=pass"),
        f'"{OWNER}" <attacker@example.com>') is False


def test_no_headers_and_no_sender_is_not_trusted():
    assert bt._email_sender_is_owner([], "") is False
    assert bt._email_sender_is_owner(None, None) is False


# --------------------------------------------------------------------------
# What a stranger is allowed to reach
# --------------------------------------------------------------------------

def test_the_stranger_whitelist_holds_nothing_that_acts():
    """Everything a non-owner can trigger must be read-only and public.

    This is the list that decides what an unauthenticated email can make
    Blue do, so a tool added to it carelessly is the whole exposure.
    """
    forbidden = (
        "send", "reply", "email", "gmail", "delete", "remove", "create",
        "set_", "control", "capture", "camera", "move", "play", "timer",
        "reminder", "write", "save", "upload", "auto_reply",
    )
    for tool in bt._EMAIL_SAFE_TOOL_NAMES:
        assert not any(word in tool.lower() for word in forbidden), \
            f"{tool} can act; it does not belong in the stranger whitelist"


def test_the_library_account_is_not_spent_on_strangers():
    """read_paper is deliberately absent — it draws on Alex's access."""
    assert "read_paper" not in bt._EMAIL_SAFE_TOOL_NAMES


def test_even_owner_mail_cannot_start_another_inbox_sweep():
    """Otherwise one email can set off a sweep that answers itself."""
    assert "auto_reply_emails" in bt._EMAIL_OWNER_EXCLUDE
