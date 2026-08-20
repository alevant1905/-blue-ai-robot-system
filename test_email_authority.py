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
    "mx.google.com; spf=pass; dmarc=pass (p=NONE) header.from=gmail.com",
    "mx.google.com; dkim=pass header.d=gmail.com; dmarc=pass",
])
def test_owner_mail_with_a_passing_stamp_is_trusted(auth):
    assert bt._email_sender_is_owner(_headers(auth), f"Alex <{OWNER}>") is True


@pytest.mark.parametrize("auth", [
    "mx.google.com; spf=pass; dmarc=pass (p=NONE)",
    "mx.google.com; dkim=pass; dmarc=pass",
])
def test_a_pass_that_names_no_domain_is_not_enough(auth):
    """A result with no header.i/d/from cannot be checked for alignment.

    Gmail always names the domain, so a stamp that does not is either not
    Gmail's or has been trimmed. Refusing costs Alex nothing worse than the
    read-only whitelist; accepting hands the house to whoever wrote it.
    """
    assert bt._email_sender_is_owner(_headers(auth), f"Alex <{OWNER}>") is False


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
    """A fail is disqualifying wherever it appears in the stamp."""
    assert bt._email_sender_is_owner(_headers(auth), f"Alex <{OWNER}>") is False


def test_a_stranger_with_a_perfect_stamp_is_still_a_stranger():
    """Passing DKIM proves the sender is who they say — not that they are Alex."""
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass; dmarc=pass"),
        "Someone Else <stranger@example.com>") is False


def test_a_display_name_cannot_borrow_the_owner_address():
    """An attacker must not become Alex by putting his address in the name.

    Found 2026-08-19 while writing this file, fixed the same day. The check
    used to pull EVERY address out of the From line and ask whether any was
    an owner address, so a display name was enough; the stamp was then only
    searched for "dkim=pass" anywhere, which the attacker's own domain
    supplies honestly.
    """
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass header.i=@example.com; dmarc=pass"),
        f'"{OWNER}" <attacker@example.com>') is False


@pytest.mark.parametrize("sender", [
    '"{owner}" <attacker@example.com>',
    "{owner} <attacker@example.com>",
    "Alex <attacker@example.com>, {owner}",
    "attacker@example.com ({owner})",
    "{owner} attacker@example.com",
])
def test_the_owner_address_anywhere_but_the_addr_spec_is_not_alex(sender):
    """Every shape that puts the address somewhere other than the envelope.

    The unquoted ones matter most: parseaddr reads
        {owner} <attacker@example.com>
    as TWO addresses and hands back the first, which is the owner's. A From
    line with more than one address is not something real mail does here, so
    it is refused rather than guessed at.
    """
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass header.i=@example.com; dmarc=pass"),
        sender.format(owner=OWNER)) is False

def test_another_gmail_user_cannot_wear_the_owner_address():
    """The one spoof domain alignment cannot catch, so the parse must.

    Gmail signs every gmail.com sender with the same header.i=@gmail.com and
    an aligned dmarc=pass. An attacker with their own gmail account gets a
    perfectly honest stamp for the owner's domain, so alignment says yes.
    What stops them is that

        alevant1905@gmail.com <attacker@gmail.com>

    parses as TWO addresses - parseaddr hands back the first, the owner's -
    and a From line with more than one address is refused outright.
    """
    real_gmail_stamp = ("mx.google.com; dkim=pass header.i=@gmail.com "
                        "header.s=20230601; spf=pass "
                        "smtp.mailfrom=attacker@gmail.com; dmarc=pass "
                        "(p=NONE sp=QUARANTINE dis=NONE) header.from=gmail.com")
    for sender in (f"{OWNER} <attacker@gmail.com>",
                   f'"{OWNER}" <attacker@gmail.com>',
                   f"Alex <attacker@gmail.com>, {OWNER}"):
        assert bt._email_sender_is_owner(_headers(real_gmail_stamp),
                                         sender) is False, sender


def test_a_from_line_with_two_addresses_yields_no_envelope():
    """Isolated from the stamp, because the stamp cannot save this case."""
    assert bt._email_envelope_address(f"{OWNER} <attacker@gmail.com>") == ""
    assert bt._email_envelope_address(f"{OWNER}, someone@example.com") == ""
    assert bt._email_envelope_address(f"Alex <{OWNER}>") == OWNER


def test_a_pass_for_somebody_elses_domain_does_not_vouch_for_alex():
    """The stamp has to authenticate the sender's OWN domain.

    An attacker who relays through a host that signs its own mail gets a
    genuine dkim=pass. It says the message is really from example.com — not
    that example.com may speak as Alex.
    """
    assert bt._email_sender_is_owner(
        _headers("mx.google.com; dkim=pass header.i=@example.com; "
                 "dmarc=pass header.from=example.com"),
        f"Alex <{OWNER}>") is False


def test_a_pass_and_a_domain_must_come_from_the_same_clause():
    """Otherwise a failing signature lends its domain to an unrelated pass."""
    assert bt._auth_vouches_for_domain(
        "mx.google.com; dkim=temperror header.i=@gmail.com; "
        "dmarc=pass header.from=example.com", "gmail.com") is False


# The two real inboxes. A wrong fix here does not announce itself: Alex keeps
# getting replies, quietly demoted to the stranger whitelist.

GMAIL_STAMP = ("mx.google.com; dkim=pass header.i=@gmail.com header.s=20230601 "
               "header.b=aBc; spf=pass (google.com: domain of {owner} "
               "designates 209.85.220.41 as permitted sender) "
               "smtp.mailfrom={owner}; dmarc=pass (p=NONE sp=QUARANTINE "
               "dis=NONE) header.from=gmail.com")
YORKU_STAMP = ("mx.google.com; dkim=pass header.i=@yorku.ca header.s=selector1; "
               "spf=pass; dmarc=pass (p=REJECT sp=REJECT dis=NONE) "
               "header.from=yorku.ca")
# an institution whose mail is signed by its Microsoft tenant, DMARC aligning
O365_STAMP = ("mx.google.com; dkim=pass header.i=@yorku.onmicrosoft.com "
              "header.s=sel1; spf=pass; dmarc=pass (p=NONE) "
              "header.from=yorku.ca")


@pytest.mark.parametrize("sender, auth", [
    ("Alex <{owner}>", GMAIL_STAMP),
    ("{owner}", GMAIL_STAMP),
    ('"Alex Levant" <{owner}>', GMAIL_STAMP),
    ("Alex <{OWNER_UPPER}>", GMAIL_STAMP),
    ("Alex Levant <alevant@yorku.ca>", YORKU_STAMP),
    ("Alex Levant <alevant@yorku.ca>", O365_STAMP),
])
def test_alex_is_not_locked_out_of_his_own_email(sender, auth):
    """Realistic Gmail and institutional stamps, in the shapes they arrive in."""
    if "yorku" in sender and "alevant@yorku.ca" not in bt.BLUE_OWNER_ADDRESSES:
        pytest.skip("the institutional address is not configured here")
    sender = sender.format(owner=OWNER, OWNER_UPPER=OWNER.upper())
    assert bt._email_sender_is_owner(
        _headers(auth.format(owner=OWNER)), sender) is True


def test_a_subdomain_of_a_signed_domain_still_aligns():
    """DMARC relaxed alignment: a stamp for yorku.ca covers mail.yorku.ca."""
    assert bt._auth_vouches_for_domain(
        "mx.google.com; dmarc=pass header.from=yorku.ca", "mail.yorku.ca") is True


def test_alignment_does_not_run_the_suffix_match_backwards():
    """notyorku.ca must not borrow a stamp for yorku.ca, and vice versa."""
    stamp = "mx.google.com; dkim=pass header.i=@yorku.ca"
    assert bt._auth_vouches_for_domain(stamp, "notyorku.ca") is False
    assert bt._auth_vouches_for_domain(stamp, "yorku.ca.evil.com") is False
    assert bt._auth_vouches_for_domain(
        "mx.google.com; dkim=pass header.i=@mail.yorku.ca", "yorku.ca") is False


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
