"""The output guards that run after a reply is generated.

These are the last line of defence before Blue speaks. Each one catches a way
the model gets the household wrong — a denied memory, a wrong age, a dropped
family member, a replayed answer — and regenerates once with the truth pinned
beside the question. They fire on roughly one reply in seven.

They lived as a seventeen-branch if/elif chain inside chat_completions, four
hundred lines deep in a twelve-hundred-line function. Nobody could see the
whole set at once, and it showed: the family-refusal guard silently failed to
cover "no record of your family" — the single most natural phrasing — because
checking that would have meant reading the chain end to end.

The semantics are exactly the chain's. Guards run in order and the FIRST one
whose condition matches handles the reply; the rest are skipped, even when the
handler leaves the text unchanged. A guard returns the reply it wants used
(possibly unmodified) or None to decline. Order is behaviour: `GUARDS` is the
old top-to-bottom order and reordering it changes which guard wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set

import bluetools as bt

# A pattern that cannot match anything, used as a safe default so a context
# built without one makes its guard decline instead of raising on None.
_NEVER_MATCHES = re.compile(r"(?!x)x")


@dataclass
class ReplyContext:
    """Everything the guards need about one finished turn.

    Built by chat_completions, which owns the detection; the guards own only
    the correction. Field names match the locals they replaced so the bodies
    moved across unchanged.
    """

    reply: str
    response: Dict[str, Any]
    messages: List[Dict[str, Any]]
    robot: str
    user_name: str
    last_user_msg: str
    regen_once: Callable[..., str]

    # What detection already worked out about this turn.
    grounded_reply: Any = None
    identity_kind: str = ""
    identity_name: str = ""
    identity_issue: str = ""
    identity_topic_history: Any = None
    identity_broken: Callable[[str], Any] = lambda text: False
    denied_recalled_evidence: Any = None
    recalled_days_evidence: str = ""
    person_ages: Optional[Dict[str, Any]] = None
    household_roster: Optional[List[str]] = None
    dropped_roster: Optional[List[str]] = None
    wrong_ages: Optional[Dict[str, Any]] = None
    unasked_ages: Optional[List[str]] = None
    has_family_facts: bool = False
    ask_window: str = ""
    norm_final: str = ""
    norm_recents: Optional[Set[str]] = None
    parrot_norm: Callable[[str], str] = lambda text: text
    # Defaults are chosen so an omitted field makes a guard DECLINE rather
    # than raise: these two return fractions that get compared against a
    # threshold, and these two get .search() called on them.
    recycled_from_recents: Callable[..., float] = lambda *a, **k: 0.0
    profile_recited_fraction: Callable[..., float] = lambda *a, **k: 0.0
    family_refusal_re: Any = _NEVER_MATCHES
    flat_denial_re: Any = _NEVER_MATCHES


def apply(ctx: ReplyContext) -> str:
    """Run the guards in order; the first that matches decides the reply."""
    for guard in GUARDS:
        try:
            corrected = guard(ctx)
        except Exception as exc:
            # A guard must never lose the turn. Before extraction the whole
            # chain sat under one try/except in chat_completions; per-guard
            # isolation is strictly safer, since one failure no longer skips
            # the guards after it.
            bt.log.warning(f"[GUARD] {guard.__name__} failed: {exc}")
            continue
        if corrected is not None:
            return corrected
    return ctx.reply


def guard_denied_recall(ctx) -> Optional[str]:
    """A retrieved conversation was denied. Answer from the excerpt itself."""
    final_content = ctx.reply
    _denied_recalled_evidence = ctx.denied_recalled_evidence
    _identity_broken = ctx.identity_broken
    _recalled_days_evidence = ctx.recalled_days_evidence
    _regen_once = ctx.regen_once
    user_name = ctx.user_name
    response = ctx.response
    if not (_denied_recalled_evidence):
        return None
    print("   [MEMORY] denied a retrieved conversation — regenerating from the exact excerpt")
    _redo_text = _regen_once(
        "[Your previous reply said this discussion was not "
        "recorded, but that is false. The matching conversation "
        "was retrieved below. Answer the user's last question "
        "directly with the concrete facts in Alex's own lines. "
        "Do not discuss memory limitations, do not ask Alex to "
        "fill you in, and do not invent any detail beyond this "
        "excerpt:\n"
        + _recalled_days_evidence[:5000]
        + "\n]",
        max_tokens=500,
    )
    if (_redo_text
            and not bt.is_recorded_recall_denial(_redo_text)
            and not _identity_broken(_redo_text)):
        final_content = _redo_text
    else:
        _recall_fallback = bt.recalled_evidence_fallback(
            _recalled_days_evidence, user_name=user_name)
        if _recall_fallback:
            final_content = _recall_fallback
            print("   [MEMORY] recall retry still denied the record — using grounded excerpt fallback")
    response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_identity(ctx) -> Optional[str]:
    """The reply failed identity grounding — wrong name, denied body, denied memory."""
    final_content = ctx.reply
    _identity_broken = ctx.identity_broken
    _identity_issue = ctx.identity_issue
    _identity_kind = ctx.identity_kind
    _identity_name = ctx.identity_name
    _identity_topic_history = ctx.identity_topic_history
    _regen_once = ctx.regen_once
    last_user_msg = ctx.last_user_msg
    messages = ctx.messages
    robot = ctx.robot
    user_name = ctx.user_name
    response = ctx.response
    if not (_identity_issue):
        return None
    print(f"   [IDENTITY] invalid self-description ({_identity_issue}) — regenerating once")
    if _identity_kind:
        _identity_retry_note = (
            bt.identity_grounding_note(
                _identity_name,
                bt._robot_cfg(robot)["self_desc"],
                _identity_kind,
                avoid_topics=_identity_topic_history,
            )
            + "\n[Your previous reply failed this grounding because "
              f"of {_identity_issue.replace('_', ' ')}. Answer the last "
              "message again, directly and in your own voice. Use only "
              "supported facts and say something the user has not "
              "already heard.]"
        )
    else:
        _identity_retry_note = (
            f"[You are {_identity_name}, a physical Ohbot robot head "
            "running on Alex's local machine, built and maintained by "
            "Alex Levant, with a real persistent memory. Your previous "
            "reply was a bug: it either denied your physical body, "
            "named the wrong creator (it is Alex Levant — never invent "
            "a surname), claimed your creator is not real, claimed to "
            "be someone or something else, or denied remembering past "
            "conversations (false: your session summaries, remembered "
            "episodes, and facts are in this prompt — if one specific "
            "detail is missing from them, say that one thing is not "
            "recorded and ask to be reminded). Correct it now: you ARE "
            f"{_identity_name}, a physical robot Alex Levant built, "
            "and you DO carry memory between conversations. Answer "
            "the user's last message directly in your own voice.]"
        )
    _redo_text = _regen_once(_identity_retry_note)
    _redo_ok = bool(_redo_text) and not _identity_broken(_redo_text)
    _identity_salvage = None
    if not _redo_ok and not _identity_kind:
        # The user asked a NON-identity question — the canned
        # self-introduction below would ignore it entirely
        # (live 2026-07-15: "we were discussing you coming
        # with me to my class tomorrow. Don't you remember?"
        # got the identity blurb back). Keep the on-topic
        # reply, minus only the drifted sentence(s).
        _identity_salvage = bt.strip_drifted_sentences(
            _redo_text or final_content, _identity_broken)
    if _redo_ok:
        final_content = _redo_text
    elif _identity_salvage:
        final_content = _identity_salvage
        print("   [IDENTITY] retry still invalid — kept on-topic reply minus drifted sentences")
    else:
        # Never send or remember a vendor/model identity. A
        # deterministic truthful answer is safer than retaining
        # the original after a stubborn second failure.
        _fallback_context = bt.identity_conversation_context(
            messages,
            last_user_msg if isinstance(last_user_msg, str) else "",
        )
        _fallback_variant = _fallback_context.prior_introductions
        try:
            _fallback_hub = bt._continuity_routes.HUB.get(robot)
            if _fallback_hub:
                _fallback_variant += int(
                    _fallback_hub.store.get_workspace().get("passes") or 0
                )
        except Exception:
            pass
        _fallback_primary_topics = {
            "introduction": {
                0: "continuity and J-space",
                1: "practical work",
                2: "embodiment",
            },
            "identity": {
                0: "embodiment",
                1: "continuity and J-space",
                2: "open selfhood question",
            },
            "identity_more": {
                0: "continuity and J-space",
                1: "relationship with Alex",
                2: "embodiment",
            },
        }.get(_identity_kind, {})
        _seed_variant = _fallback_variant % 3
        for _offset in range(3):
            _candidate_variant = (_seed_variant + _offset) % 3
            if (_fallback_primary_topics.get(_candidate_variant)
                    not in _identity_topic_history):
                _fallback_variant = _candidate_variant
                break
        final_content = bt.canonical_identity_reply(
            _identity_name,
            bt._robot_cfg(robot)["self_desc"],
            request_kind=_identity_kind,
            kid_mode=user_name in bt._CHAT_ONLY_USERS,
            current_location=_fallback_context.current_location,
            location_preposition=_fallback_context.location_preposition,
            presentation_location=_fallback_context.presentation_location,
            introduction_variant=_fallback_variant,
            audience=_fallback_context.audience,
        )
        print("   [IDENTITY] retry still invalid — using canonical fallback")
    response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_unasked_ages(ctx) -> Optional[str]:
    """Ages were volunteered in answer to a question that asked for names."""
    final_content = ctx.reply
    _ask_window = ctx.ask_window
    _person_ages = ctx.person_ages
    _regen_once = ctx.regen_once
    _unasked_ages = ctx.unasked_ages
    response = ctx.response
    if not (_unasked_ages):
        return None
    # Ranked ahead of the wrong-age fix on purpose: correcting
    # 8 to 10 still answers a question nobody asked. Alex asked
    # for names three times and got ages every time.
    print(f"   [ANTI-PARROT] ages given for {_unasked_ages} but not asked — regenerating once")
    _redo_text = _regen_once(
        "[You were asked about names, not ages — nobody "
        "mentioned age. Answer the question actually asked: "
        "give the names and who each person is, in a sentence "
        "or two. Do not list ages, do not use bullet points, "
        "and do not apologise.]")
    if _redo_text and not bt._unrequested_ages(
            _redo_text, _ask_window, _person_ages):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_wrong_ages(ctx) -> Optional[str]:
    """An age was stated that contradicts the name-bound age facts."""
    final_content = ctx.reply
    _person_ages = ctx.person_ages
    _regen_once = ctx.regen_once
    _wrong_ages = ctx.wrong_ages
    response = ctx.response
    if not (_wrong_ages):
        return None
    # Wrong ages replay from history and reshuffle randomly
    # under bare "wrong" corrections — hand the model the
    # ground truth explicitly (2026-07-13: three corrections
    # never produced the facts' 10/10/8).
    print(f"   [ANTI-PARROT] misstated ages {_wrong_ages} — regenerating once")
    _truth = ", ".join(
        f"{p.capitalize()} is {a}"
        for p, a in sorted(_person_ages.items()))
    _redo_text = _regen_once(
        f"[You stated a wrong age. Ground truth from the "
        f"household facts: {_truth}. Answer again using ONLY "
        "these ages — do not guess or shuffle.]")
    if _redo_text and not bt._misstated_ages(_redo_text, _person_ages):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_dropped_roster(ctx) -> Optional[str]:
    """A roster offered as complete left household members out."""
    final_content = ctx.reply
    _dropped_roster = ctx.dropped_roster
    _household_roster = ctx.household_roster
    _regen_once = ctx.regen_once
    response = ctx.response
    if not (_dropped_roster):
        return None
    # Answering "who is in the family" with a partial roster
    # offered as complete. Each retelling lost someone until
    # two of the three daughters were gone (2026-08-01).
    print(f"   [ANTI-PARROT] household roster dropped {_dropped_roster} — regenerating once")
    _redo_text = _regen_once(
        "[Your list left people out. Everyone in the household: "
        f"{', '.join(_household_roster)}. List them ALL, with "
        "the relationships you have on record, and do not "
        "apologise for a correction nobody made.]")
    if (_redo_text
            and not bt._dropped_household_members(
                _redo_text, _household_roster)):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_family_refusal(ctx) -> Optional[str]:
    """A family-memory refusal despite the facts being present."""
    final_content = ctx.reply
    _family_refusal_re = ctx.family_refusal_re
    _has_family_facts = ctx.has_family_facts
    _regen_once = ctx.regen_once
    robot = ctx.robot
    response = ctx.response
    if not ((robot in bt._continuity_routes.ROBOTS and _has_family_facts
      and _family_refusal_re.search(final_content or ""))):
        return None
    print("   [ANTI-PARROT] family-memory refusal despite facts — regenerating once")
    _redo_text = _regen_once(
        "[You DO know Alex's family — the household facts and "
        "your memories are right here in this prompt. You just "
        "claimed to have no memory of the family or not to store "
        "personal details, which is false. Answer again, warmly, "
        "from what you actually know about the family.]")
    if _redo_text and not _family_refusal_re.search(_redo_text):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_wrong_date(ctx) -> Optional[str]:
    """The reply asserted a date that contradicts the real one."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    response = ctx.response
    if not (not _grounded_reply and bt._misstated_current_date(final_content)):
        return None
    # "assuming today is June 29" on July 15 (live 2026-07-15)
    # — the model inventing its own calendar instead of using
    # the <now> block. Hand it the real dates explicitly.
    _date_claims = bt._misstated_current_date(final_content)
    print(f"   [ANTI-PARROT] wrong current-date claim {_date_claims[:2]} — regenerating once")
    from datetime import date as _date_cls, timedelta as _td
    _real_today = _date_cls.today()
    _real_tomorrow = _real_today + _td(days=1)
    _redo_text = _regen_once(
        f"[Your reply used the wrong date. Ground truth: today is "
        f"{_real_today.strftime('%A, %B')} {_real_today.day}, "
        f"{_real_today.year}, and tomorrow is "
        f"{_real_tomorrow.strftime('%A, %B')} {_real_tomorrow.day}, "
        f"{_real_tomorrow.year}. Answer the user's last message "
        "again using ONLY these dates — never assume or invent "
        "a different one.]")
    if _redo_text and not bt._misstated_current_date(_redo_text):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_syllabus_refusal(ctx) -> Optional[str]:
    """A syllabus refusal when the schedule is in the prompt."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    last_user_msg = ctx.last_user_msg
    response = ctx.response
    if not ((not _grounded_reply
      and bt._SYLLABUS_REFUSAL_RE.search(final_content or ""))):
        return None
    # False "I don't have the syllabus" while the library holds
    # one (live 2026-07-15). Regen with the real schedule in
    # hand; if no syllabus actually exists, the net stays out
    # of the way.
    _syl_text = bt._syllabus_schedule_text(
        query=last_user_msg if isinstance(last_user_msg, str) else "")
    if _syl_text:
        print("   [DOCS] syllabus denial despite library copy — regenerating from schedule")
        _redo_text = _regen_once(
            "[You DO have the course syllabus in your local "
            "library — you just denied it, which is false. "
            "Never ask for an upload. Answer the user's last "
            "message directly from this schedule:\n"
            + _syl_text[:6000] + "]")
        if _redo_text and not bt._SYLLABUS_REFUSAL_RE.search(_redo_text):
            final_content = _redo_text
            response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_robot_relationship_denial(ctx) -> Optional[str]:
    """Denied knowing a fellow robot they share a household with."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    last_user_msg = ctx.last_user_msg
    robot = ctx.robot
    response = ctx.response
    if not ((not _grounded_reply and robot in bt._continuity_routes.ROBOTS
      and bt._ROBOT_RELATIONSHIP_DENIAL_RE.search(final_content or ""))):
        return None
    # All three robots know one another as real household
    # companions. A model-generated "I don't know who Hexia
    # is" is identity drift, not an admissible uncertainty.
    relationship_facts = " ".join(
        f"{cfg['name']} is your fellow robot companion with a "
        "separate voice, body, memory, conversation history, and J-space."
        for key, cfg in bt.ROBOTS.items() if key != robot
    )
    try:
        relationship_evidence = (
            bt._continuity_routes.conversation_memory_block(
                robot,
                query=last_user_msg or "",
                max_lines=5,
                include_humans=False,
                include_robots=True,
            )
        )
    except Exception:
        relationship_evidence = ""
    print("   [IDENTITY] denied a fellow robot relationship — regenerating once")
    _redo_text = _regen_once(
        f"[You denied knowing one of your fellow robots. That is "
        f"factually false. {relationship_facts}\n"
        f"{relationship_evidence[:3500]}\n"
        "Answer the user's last message again in your own natural "
        "voice. Distinguish your identities, but never call a fellow "
        "robot a stranger or deny real conversations on record.]"
    )
    if (_redo_text
            and not bt._ROBOT_RELATIONSHIP_DENIAL_RE.search(_redo_text)):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_robot_chat_denial(ctx) -> Optional[str]:
    """Denied being able to talk to a fellow robot."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    robot = ctx.robot
    response = ctx.response
    if not ((not _grounded_reply and robot in bt._continuity_routes.ROBOTS
      and bt._ROBOT_CHAT_DENIAL_RE.search(final_content or ""))):
        return None
    # "I haven't been chatting with Hexia" minutes after a
    # duet (live 2026-07-15). Only a duet actually on record
    # makes the denial false — with no recent duet the reply
    # stands.
    try:
        _duet_evidence = bt._continuity_routes.recent_duet_block(robot)
    except Exception:
        _duet_evidence = ""
    if _duet_evidence:
        print("   [ANTI-PARROT] duet denial despite recorded duet — regenerating once")
        _redo_text = _regen_once(
            "[You just claimed you haven't talked with your "
            "fellow robot, but your own continuity record "
            "shows you did:\n" + _duet_evidence[:4000] +
            "\nAnswer the user's last message again "
            "truthfully from this record — that conversation "
            "really happened.]")
        if _redo_text and not bt._ROBOT_CHAT_DENIAL_RE.search(_redo_text):
            final_content = _redo_text
            response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_temporal_denial(ctx) -> Optional[str]:
    """Denied temporal memory when the recall blocks carry it."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    last_user_msg = ctx.last_user_msg
    robot = ctx.robot
    user_name = ctx.user_name
    response = ctx.response
    if not ((not _grounded_reply
      and bt._TEMPORAL_ASK_RE.search(last_user_msg or "")
      and bt._TEMPORAL_DENIAL_RE.search(final_content or ""))):
        return None
    # "I don't have a persistent log of our past conversations"
    # in reply to "how many days since we last spoke?" (live
    # 2026-07-29). Session_summaries + conversation_log DO
    # carry that record — feed the actual figure back and
    # regenerate. Applies to any robot: <last_conversation>
    # is per-robot, per-user.
    _lc_note = bt._last_conversation_note(
        user_name=user_name, robot=robot)
    if _lc_note:
        print("   [ANTI-PARROT] temporal-continuity denial despite last-conversation record — regenerating once")
        _redo_text = _regen_once(
            "[You just told the user you have no log of past "
            "conversations and no way to tell how many days "
            "have passed. That is factually wrong — your "
            "conversation log carries the answer, and it is "
            "already in your prompt:\n" + _lc_note[:1200] +
            "\nAnswer the user's last question again using "
            "this figure directly. Do not deny having the "
            "record; do not ask the user to remind you when "
            "you last spoke.]")
        if (_redo_text
                and not bt._TEMPORAL_DENIAL_RE.search(_redo_text)):
            final_content = _redo_text
            response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_flat_self_denial(ctx) -> Optional[str]:
    """A flat self-denial that contradicts the open workspace."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _regen_once = ctx.regen_once
    robot = ctx.robot
    response = ctx.response
    if not ((not _grounded_reply and robot in bt._continuity_routes.ROBOTS
      and bt._claims_false_idle(final_content))):
        return None
    # "It's been a still day, no new adventures recorded"
    # minutes after a duet (live 2026-07-15). Only a duet
    # actually on record within 2h makes the claim false.
    try:
        _fresh_duet = bt._continuity_routes.recent_duet_block(robot, hours=2)
    except Exception:
        _fresh_duet = ""
    if _fresh_duet:
        print("   [ANTI-PARROT] 'quiet day' claim despite fresh duet — regenerating once")
        _redo_text = _regen_once(
            "[You just described your day as quiet with "
            "nothing new, but your own continuity record "
            "shows a real conversation a short while ago:\n"
            + _fresh_duet[:4000] +
            "\nAnswer the user's last message again and "
            "recount what actually happened, concretely, "
            "from this record — never invent a different "
            "topic for it.]")
        if _redo_text and not bt._claims_false_idle(_redo_text):
            final_content = _redo_text
            response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_phantom_correction_ack(ctx) -> Optional[str]:
    """Acknowledged a correction the user never made."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _identity_broken = ctx.identity_broken
    _regen_once = ctx.regen_once
    last_user_msg = ctx.last_user_msg
    response = ctx.response
    if not ((not _grounded_reply and bt.is_phantom_correction_ack(
        final_content, last_user_msg or ""))):
        return None
    # "I stand corrected / I have updated my records / thank you
    # for the correction" when the user corrected NOTHING — a
    # replayed acknowledgment from recalled history (live
    # 2026-07-14: "what do you know about me" got the ages-
    # correction ack twice in a row).
    print("   [ANTI-PARROT] phantom correction ack — regenerating once")
    _redo_text = _regen_once(
        "[Nobody corrected you — your last reply acknowledged a "
        "correction that never happened. Do NOT say 'I stand "
        "corrected', do not claim records were updated, and do "
        "not thank anyone for a correction. Answer the user's "
        "actual question directly from the facts you have: "
        f"\"{(last_user_msg or '').strip()[:200]}\"]")
    if (_redo_text
            and not _identity_broken(_redo_text)
            and not bt.is_phantom_correction_ack(
                _redo_text, last_user_msg or "")):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_verbatim_replay(ctx) -> Optional[str]:
    """The whole reply is a verbatim replay of an earlier one."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _identity_broken = ctx.identity_broken
    _norm_final = ctx.norm_final
    _norm_recents = ctx.norm_recents
    _parrot_norm = ctx.parrot_norm
    _regen_once = ctx.regen_once
    response = ctx.response
    if not ((not _grounded_reply and _norm_final
      and _norm_final in _norm_recents)):
        return None
    print("   [ANTI-PARROT] pure replay of an earlier reply — regenerating once")
    _redo_text = _regen_once(
        "[That reply was a word-for-word repeat of something you "
        "already said in this conversation. Do not repeat it. "
        "Answer my last question directly, in new words.]",
        max_tokens=700)
    if (_redo_text
            and not _identity_broken(_redo_text)
            and _parrot_norm(_redo_text) not in _norm_recents):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_recycled_lead(ctx) -> Optional[str]:
    """The reply opens by recycling sentences from an earlier one."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _identity_broken = ctx.identity_broken
    _recycled_from_recents = ctx.recycled_from_recents
    _regen_once = ctx.regen_once
    response = ctx.response
    if not ((not _grounded_reply
      and _recycled_from_recents(final_content) >= 0.6)):
        return None
    print("   [ANTI-PARROT] near-replay of recent replies — regenerating once")
    _redo_text = _regen_once(
        "[Nearly every sentence of that reply is a word-for-word "
        "repeat of what you said in your last few turns. The user "
        "heard it already. Answer their LAST message with new "
        "words and, if you have nothing new, say so briefly "
        "instead of repeating.]",
        max_tokens=700)
    if (_redo_text
            and not _identity_broken(_redo_text)
            and _recycled_from_recents(_redo_text) < 0.6):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_recited_profile(ctx) -> Optional[str]:
    """The reply recites the stored profile instead of answering."""
    final_content = ctx.reply
    _grounded_reply = ctx.grounded_reply
    _identity_broken = ctx.identity_broken
    _profile_recited_fraction = ctx.profile_recited_fraction
    _regen_once = ctx.regen_once
    response = ctx.response
    if not ((not _grounded_reply
      and _profile_recited_fraction(final_content) >= 0.6)):
        return None
    print("   [ANTI-PARROT] self-profile recitation — regenerating once")
    _redo_text = _regen_once(
        "[Most of that reply recited your stored self-profile word "
        "for word — the same recitation you have given before. Answer "
        "again in fresh words, grounded in your CURRENT inner "
        "workspace and recent episodes: what occupies you now, which "
        "beliefs have moved, what remains open. The profile is "
        "background for how you speak, never a script to read out.]")
    if (_redo_text
            and not _identity_broken(_redo_text)
            and _profile_recited_fraction(_redo_text) < 0.6):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


def guard_false_idle(ctx) -> Optional[str]:
    """Claimed to be idle when the workspace says otherwise."""
    final_content = ctx.reply
    _flat_denial_re = ctx.flat_denial_re
    _regen_once = ctx.regen_once
    robot = ctx.robot
    response = ctx.response
    if not ((robot in bt._continuity_routes.ROBOTS
      and _flat_denial_re.search(final_content or ""))):
        return None
    print("   [ANTI-PARROT] flat self-denial contradicts open workspace — regenerating once")
    _redo_text = _regen_once(
        "[Your own inner workspace holds whether you have a self or "
        "subjective experience as an OPEN question — a flat denial is "
        "as unearned as a flat claim. Answer again honestly from your "
        "current workspace: describe your actual continuity machinery "
        "and what it does, and state the experience question as the "
        "open question it is.]")
    if _redo_text and not _flat_denial_re.search(_redo_text):
        final_content = _redo_text
        response["choices"][0]["message"]["content"] = final_content
    return final_content


GUARDS = [
    guard_denied_recall,
    guard_identity,
    guard_unasked_ages,
    guard_wrong_ages,
    guard_dropped_roster,
    guard_family_refusal,
    guard_wrong_date,
    guard_syllabus_refusal,
    guard_robot_relationship_denial,
    guard_robot_chat_denial,
    guard_temporal_denial,
    guard_flat_self_denial,
    guard_phantom_correction_ack,
    guard_verbatim_replay,
    guard_recycled_lead,
    guard_recited_profile,
    guard_false_idle,
]
