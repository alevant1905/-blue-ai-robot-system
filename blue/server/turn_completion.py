"""Finishing a turn: checking the reply, then delivering and recording it.

The 424 lines that run after the model has answered. Detection first — wrong
ages, a dropped family member, a replayed answer, a broken self-description —
then the guards in blue/server/reply_guards.py decide what is actually said,
then the reply is styled, spoken, and written to memory.

Lifted whole out of chat_completions, which is now a readable sequence:
identify the speaker, build the context, generate, finish. The nested helpers
the detection uses (_parrot_norm, _identity_broken, _verbatim_fraction and
friends) came with it — they are only used here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

import bluetools as bt


# Compiled once. These were rebuilt on every single turn, and living inside
# finish() meant the only way to check one was to drive a whole request.
_family_refusal_re = re.compile(
            r"(?:do (?:not|n['’]?t) (?:\w+ )?(?:have|store|keep|retain|access)"
            r"|have no|don['’]?t (?:\w+ )?have)[^.!?]{0,60}"
            r"(?:personal (?:details|information|memor)|"
            r"persistent memor|memor[a-z]* of past|"
            r"(?:real[- ]?world )?facts about (?:you|your)|"
            r"memor[a-z]* (?:of|about) (?:your |the )?(?:family|you)|"
            # "no record of your family" is the phrasing the models
            # actually reach for, and it was not covered — the guard
            # only knew "memory of" and "information about". The same
            # miss showed up in Panel Mode for a named relative
            # ("I don't have any record of a Felix", 2026-08-04).
            r"record[a-z]* (?:of|about|on) "
            r"(?:your |the |a |an )?(?:family|relatives?|brother|sister|parents?|"
            # recorded: "I don't have a record of your dog's name yet" —
            # the pet is in the facts table under pet_name.
            r"dogs?|pets?|cats?|daughters?|sons?|wife|husband|partner)|"
            r"information about (?:your |the )?family)"
            r"|i (?:respect your privacy and|do(?:n['’]?t| not))"
            r"[^.!?]{0,40}store personal"
            r"|do(?:n['’]?t| not) (?:truly |really |actually )?know "
            r"who you are"
            r"|i (?:couldn['’]?t|could not) find[^.!?]{0,60}"
            r"(?:information|records?|contacts?)"
            r"|(?:might|may|could) have been a hallucination"
            r"|was (?:just )?a hallucination"
            # Recorded, and false — the facts table had all of these:
            #   "I don't have the names of other family members yet"
            #   "I don't actually have their ages stored in my permanent memory"
            r"|(?:do(?:n['’]?t| not)|have no) [^.!?]{0,40}"
            r"names? of (?:the )?(?:other )?(?:family|household) members?"
            r"|(?:do(?:n['’]?t| not)) [^.!?]{0,40}"
            r"(?:stored|saved|kept) in my (?:permanent|persistent|long[- ]?term) memor",
            re.I)


def denies_a_known_person(text: str) -> bool:
    """A memory denial that names someone Blue actually has on record.

    Regexes can enumerate words like "family" or "brother"; they cannot
    enumerate people. "I don't have any record of a Felix in our shared
    history" slipped past every pattern because Felix is a name — which is
    exactly the failure that opened the 2026-08-04 investigation. So this
    checks the household roster instead of guessing.

    Deliberately scoped to MEMORY denials. "I don't see Stella's name in the
    syllabus" is an honest answer about a document and must not be touched.
    """
    body = str(text or "")
    if not _MEMORY_DENIAL_RE.search(body):
        return False
    if _ABOUT_A_DOCUMENT_RE.search(body):
        return False
    low = body.lower()
    return any(re.search(rf"\b{re.escape(n.lower())}\b", low)
               for n in _people_on_record() if n)


def _people_on_record() -> List[str]:
    """Everyone Blue has a name for — not the same as the household roster.

    `bt._canonical_household_names()` answers "who lives here", and is used to
    check a roster is complete. That deliberately excludes the brother, his
    wife, and the partner's parents — which is why "I don't have any record of
    a Felix" was invisible to a check built on it. This answers the different
    question: whose name would Blue be wrong to deny knowing.
    """
    try:
        if not (bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system):
            return []
        facts = bt.memory_system.load_facts() or {}
    except Exception:
        return []
    names: List[str] = []
    for key, value in facts.items():
        if not str(key).endswith(("_name", "_names", "_spouse")):
            continue
        if bt.memory_system._is_bot_fact(key):
            continue
        for piece in re.split(r"[,|;]|\sand\s", str(value or "")):
            piece = piece.strip()
            if len(piece) > 1 and piece.lower() not in (n.lower() for n in names):
                names.append(piece)
    return names


# "no record of", "don't remember", "not in my memory" — the memory-shaped
# denials, as opposed to a denial about what a document contains.
_MEMORY_DENIAL_RE = re.compile(
    r"\b(?:do(?:n['’]?t| not)|have no|haven['’]?t)\b[^.!?]{0,50}"
    r"(?:record|memor|recollection|stored|saved|on file|know who|met)"
    r"|\bnot in my (?:memory|records?)\b",
    re.I)

_ABOUT_A_DOCUMENT_RE = re.compile(
    r"\b(?:in (?:the |your |that )?(?:document|documents|syllabus|file|files|"
    r"pdf|paper|reading|folder|library)|search (?:results?|snippets?))\b", re.I)

# Compiled once. These were rebuilt on every single turn, and living inside
# finish() meant the only way to check one was to drive a whole request.
_flat_denial_re = re.compile(
            r"\bi (?:don['’]?t|do not) have (?:consciousness|a sense of self|"
            r"subjective experience|feelings|an? inner life|"
            r"an? (?:\w+ )?['\"“”‘’]?j[-_ ]?space|any form of internal|"
            r"an? (?:internal|inner) (?:mental )?(?:space|workspace)|"
            r"a persistent (?:inner )?workspace)", re.I)




def _parrot_norm(s):
    """Text reduced to comparable words, for the repetition checks."""
    return re.sub(r'\W+', ' ', (s or '').lower()).strip()


def _verbatim_fraction(reply_text, source_norm, min_sents):
    """How much of a reply's substance is lifted word for word.

    Only long sentences count, and only once there are `min_sents` of them:
    a short reply that happens to share a phrase is not a recitation.
    """
    if not source_norm:
        return 0.0
    sentences = re.split(r'(?<=[.!?])\s+', reply_text or '')
    long_sents = [s for s in sentences if len(_parrot_norm(s)) >= 40]
    if len(long_sents) < min_sents:
        return 0.0
    hits = sum(1 for s in long_sents if _parrot_norm(s) in source_norm)
    return hits / len(long_sents)

def _run_reply_guards(final_content, response, *, messages, robot,
                      last_user_msg, user_messages, user_name,
                      _grounded_reply):
    """Check the finished reply and correct it where it went wrong.

    Parroting, recycled openings, identity drift, misstated ages, a dropped
    household member, a denied recollection the journal actually holds.

    Returns the text to use. `response` is updated in place as it goes, so
    a failure part-way through leaves the corrections already made rather
    than losing the reply.
    """
    # Anti-parrot net: if the model replayed its previous reply verbatim
    # before answering (the classroom-introduction bug), cut the replay.
    try:
        _, _prev_assist = bt._last_exchange(messages)
        if _prev_assist:
            _deparroted = bt._strip_parroted_prefix(final_content, _prev_assist)
            if _deparroted != final_content:
                final_content = _deparroted
                response["choices"][0]["message"]["content"] = final_content
        # And the finer-grained variant: individual sentences replayed
        # from ANY earlier reply as a preamble to the real answer.
        _derecycled = bt._strip_recycled_lead(final_content, messages)
        if _derecycled != final_content:
            final_content = _derecycled
            response["choices"][0]["message"]["content"] = final_content

        # Compare against the last several assistant turns, not just
        # the previous one: seen live 2026-07-10, a mis-heard question
        # got a word-for-word replay of the reply from TWO turns back.
        _recent_assists = [
            m.get("content") for m in messages
            if m.get("role") == "assistant" and isinstance(m.get("content"), str)
        ][-6:]
        _norm_final = _parrot_norm(final_content)
        _norm_recents = {_parrot_norm(a) for a in _recent_assists if a}
        if _prev_assist:
            _norm_recents.add(_parrot_norm(_prev_assist))
        def _regen_once(note, max_tokens=900):
            # The model's chat template only allows ONE system message,
            # at position 0 (anything else → LM Studio 400): merge the
            # persona into an existing head system message if present.
            _retry_msgs = list(messages) + [
                {"role": "assistant", "content": final_content},
                {"role": "user", "content": note},
            ]
            _persona = bt._robot_cfg(robot)["persona_line"]
            if _retry_msgs and _retry_msgs[0].get("role") == "system":
                _retry_msgs[0] = {"role": "system", "content": (
                    _persona + "\n\n" + (_retry_msgs[0].get("content") or ""))}
            else:
                _retry_msgs.insert(0, {"role": "system", "content": _persona})
            _redo = bt.call_llm(_retry_msgs, include_tools=False,
                             temperature=0.8, max_tokens=max_tokens)
            _t = ""
            try:
                _t = (((_redo or {}).get("choices") or [{}])[0]
                      .get("message", {}).get("content") or "").strip()
            except (AttributeError, IndexError, TypeError):
                _t = ""
            if "</think>" in _t:
                _t = _t.split("</think>")[-1].strip()
            return _t


        # Identity questions pull the injected self-profile out
        # near-verbatim, and each recitation differs slightly from the
        # last — so it reads as "repeating himself" while no two
        # replies match exactly. Detect against the SOURCE.
        def _profile_recited_fraction(reply_text):
            try:
                return _verbatim_fraction(
                    reply_text, _parrot_norm(bt.get_self_profile(robot)), 3)
            except Exception:
                return 0.0

        # Near-replay with a varied tail: "I'm just a head in a box,
        # Dr. Levant—I don't have GPS..." came back three turns
        # running (2026-07-12), each time with a different final
        # clause — exact-match equality never fires on those.
        _recents_norm = _parrot_norm(" ".join(a for a in _recent_assists if a))
        def _recycled_from_recents(reply_text):
            return _verbatim_fraction(reply_text, _recents_norm, 2)

        # A flat denial of self/experience contradicts the robot's own
        # workspace, which holds that question OPEN (seen live: "I
        # don't have consciousness or a sense of self" one turn after
        # "an open question I hold as an open question").
        # Includes denials of the j-space ITSELF — those aren't even
        # philosophy, they'bt.re factually false (Hexia: "No, I do not
        # have a 'j-space'" with her workspace right in the prompt,
        # 2026-07-12). Optional quote chars around j-space.


        # This is the only identity check that runs. Two older regexes
        # lived here for the incidents below and were shadowed by a
        # second def of the same name, so they had not fired in months;
        # the shared validator catches both, which is what let them go:
        #   2026-07-12  "I'm Blue!" on Hexia's page, off poisoned thread
        #               history from the facts-table incident.
        #   2026-07-13  called out on a hallucination, Blue swung to "a
        #               large language model developed by Google", no body,
        #               no memory. All factually false in this house.
        # test_identity.py pins both.
        # Apply the shared request-aware identity validator as the final
        # authority. It also catches Qwen/Alibaba-style model boilerplate
        # and nameless generic introductions, which the legacy patterns
        # above do not cover.
        _identity_kind = bt.contextual_identity_request_kind(
            last_user_msg if isinstance(last_user_msg, str) else "",
            messages,
        )
        _identity_name = bt._robot_cfg(robot)["name"]
        _identity_others = [
            bt._robot_cfg(r)["name"]
            for r in bt.ROBOTS if r != robot
        ] if robot in bt.ROBOTS else []
        _identity_topic_history = tuple(dict.fromkeys(
            topic
            for reply in _recent_assists[-3:]
            for topic in bt.identity_reply_topics(reply)
        ))

        def _identity_broken(text):
            problem = bt.identity_response_problem(
                text,
                _identity_name,
                other_names=_identity_others,
                request_kind=_identity_kind,
            )
            if problem:
                return problem
            if bt.identity_repeats_recent_reply(
                text, _recent_assists, _identity_kind
            ):
                return "repeats_recent_identity"
            return None

        _identity_issue = _identity_broken(final_content)

        # Evidence-aware shared recall. A scoped "I don't have that
        # conversation" can be honest in general, so the identity
        # validator cannot reject it unconditionally. On this turn,
        # however, <remembered_days> is positive proof that the exact
        # exchange was retrieved. Pin that compact excerpt beside the
        # retry; if the local model still denies it, answer
        # deterministically from Alex's own recorded lines.
        _recalled_days_evidence = ""
        if _identity_kind == "shared_recall":
            for _recall_message in messages:
                _recall_content = _recall_message.get("content", "")
                if not isinstance(_recall_content, str):
                    continue
                _recall_matches = re.findall(
                    r"<remembered_days>.*?</remembered_days>",
                    _recall_content,
                    re.S,
                )
                if _recall_matches:
                    _recalled_days_evidence = _recall_matches[-1]
        _denied_recalled_evidence = bool(
            _recalled_days_evidence
            and bt.is_recorded_recall_denial(final_content)
        )

        _person_ages = bt._canonical_person_ages()
        _wrong_ages = (bt._misstated_ages(final_content, _person_ages)
                       if _person_ages else {})

        # Family-memory refusal despite having the facts: "I don't
        # store personal details / no memory of your family" while the
        # facts block holds the family (2026-07-13, triggered by the
        # focus block's over-broad 'out of scope' — but a fresh
        # boilerplate refusal can happen without focus too).
        # A roster answer that quietly loses people. Only checked when
        # the user actually asked about the household, so an ordinary
        # mention of one or two names is never treated as a list.
        _household_roster = bt._canonical_household_names()
        _roster_answer = bool(
            _household_roster
            and ((last_user_msg and isinstance(last_user_msg, str)
                  and bt._ROSTER_QUERY_RE.search(last_user_msg))
                 or bt._COMPLETENESS_CLAIM_RE.search(final_content or "")))
        _dropped_roster = (
            bt._dropped_household_members(final_content, _household_roster)
            if _roster_answer else [])

        # The frame carries across turns: "not just the kids" is a
        # follow-up to "do you remember everyone's names" and inherits
        # its question. Any mention of age in the window switches the
        # check off, so it can only ever under-fire.
        _ask_window = " ".join(
            str(m.get("content") or "")
            for m in user_messages[-3:]) if user_messages else ""
        _unasked_ages = bt._unrequested_ages(
            final_content, _ask_window, _person_ages)

        _has_family_facts = bool(_person_ages)
        if not _has_family_facts:
            try:
                if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
                    _ff = bt.memory_system.load_facts() or {}
                    _has_family_facts = bool(
                        _ff.get("daughter_name") or _ff.get("partner_name"))
            except Exception:
                _has_family_facts = False

        # The seventeen output guards now live in
        # blue/server/reply_guards.py — same conditions, same order,
        # same bodies. The first guard that matches decides the reply.
        final_content = bt._reply_guards.apply(bt._reply_guards.ReplyContext(
            reply=final_content,
            response=response,
            messages=messages,
            robot=robot,
            user_name=user_name,
            last_user_msg=last_user_msg,
            regen_once=_regen_once,
            grounded_reply=_grounded_reply,
            identity_kind=_identity_kind,
            identity_name=_identity_name,
            identity_issue=_identity_issue,
            identity_topic_history=_identity_topic_history,
            identity_broken=_identity_broken,
            denied_recalled_evidence=_denied_recalled_evidence,
            recalled_days_evidence=_recalled_days_evidence,
            person_ages=_person_ages,
            household_roster=_household_roster,
            dropped_roster=_dropped_roster,
            wrong_ages=_wrong_ages,
            unasked_ages=_unasked_ages,
            has_family_facts=_has_family_facts,
            ask_window=_ask_window,
            norm_final=_norm_final,
            norm_recents=_norm_recents,
            parrot_norm=_parrot_norm,
            recycled_from_recents=_recycled_from_recents,
            profile_recited_fraction=_profile_recited_fraction,
            denies_known_person=denies_a_known_person,
            family_refusal_re=_family_refusal_re,
            flat_denial_re=_flat_denial_re,
        ))
        response["choices"][0]["message"]["content"] = final_content
    except Exception as e:
        bt.log.warning(f"[ANTI-PARROT] check failed: {e}")
    return final_content

def finish(response: Dict[str, Any], *, _grounded_reply, last_user_msg, messages, robot, user_messages, user_name) -> Dict[str, Any]:
    """Check, correct, deliver and record the reply. Mutates `response`."""
    try:
        final_content = response["choices"][0]["message"].get("content", "")
    except (KeyError, IndexError, TypeError):
        bt.log.error(f"[RESPONSE] Malformed response from process_with_tools: "
                  f"{str(response)[:200]}")
        final_content = (
            (isinstance(response, dict) and response.get("response"))
            or "Sorry, something went wrong on my end — could you say that again?"
        )
        response = {"choices": [{"message": {
            "role": "assistant", "content": final_content,
        }}]}

    final_content = _run_reply_guards(
        final_content, response, messages=messages, robot=robot,
        last_user_msg=last_user_msg, user_messages=user_messages,
        user_name=user_name, _grounded_reply=_grounded_reply)

    # Strip the closing offer and the emoji. Done here rather than by
    # instruction because the persona has asked for concise replies all
    # along and still gets "Is there anything specific you'd like me to
    # help with? 😊" on one turn in five. The kids' chat keeps its
    # emoji — Vilda's page is meant to be friendly.
    try:
        if final_content:
            _styled = bt.strip_conversational_filler(
                final_content,
                allow_emoji=user_name in bt._CHAT_ONLY_USERS)
            if _styled and _styled != final_content:
                _dropped_chars = len(final_content) - len(_styled)
                print(f"   [STYLE] trimmed {_dropped_chars} chars of filler/emoji")
                final_content = _styled
                response["choices"][0]["message"]["content"] = final_content
    except Exception as e:
        bt.log.warning(f"[STYLE] filler strip failed: {e}")

    # Prepend proactive content: the once-a-day schedule briefing,
    # then any reminder alerts queued by the heartbeat thread. Done
    # literally rather than via system-prompt instruction so delivery
    # doesn't depend on LLM compliance — earlier turns showed Blue can
    # hallucinate having mentioned things he didn't. Both are built
    # from real reminder rows, never from the model's guesses.
    # Never lead Vilda's replies with the schedule briefing / reminder
    # alerts — Blue doesn't discuss the calendar with the kids' iPad.
    if bt.PROACTIVE_QUEUE_AVAILABLE and user_name not in bt._CHAT_ONLY_USERS and robot == "blue":
        _proactive_parts = []
        try:
            _briefing = bt.blue_proactive.daily_briefing_if_due()
            if _briefing:
                _proactive_parts.append(_briefing)
        except Exception as e:
            bt.log.warning(f"[PROACTIVE] daily briefing failed: {e}")
        _alerts = bt.blue_proactive.drain_for_response()
        if _alerts:
            _proactive_parts.append(_alerts)
        if _proactive_parts:
            _prefix = " ".join(_proactive_parts)
            final_content = f"{_prefix} {final_content}".strip()
            response["choices"][0]["message"]["content"] = final_content
            print(f"[PROACTIVE] Prepended {len(_prefix)} chars (briefing/alerts)")

    if final_content:
        print(f"[OUT] Sending response: {final_content[:100]}..." if len(final_content) > 100 else f"[OUT] Sending response: {final_content}")

        bt.save_conversation_to_db(
            user_name=user_name,
            role="assistant",
            content=final_content,
            session_id=None,
            robot=robot,
        )

        # AUTO-SAVE LEARNED FACTS & CONSOLIDATE (background thread to avoid blocking response)
        import threading
        def _background_fact_extraction(msgs, uname):
            try:
                # The facts/memory store is Alex's (single-owner profile).
                # Don't mine another speaker's turns into it, or Blue would
                # later report Vilda's statements back to Alex as his own.
                if (uname or bt._DEFAULT_USER) != bt._DEFAULT_USER:
                    return
                if bt.extract_and_save_facts(msgs):
                    bt.log.info("[MEM] ✓ Auto-saved learned facts (background)")
                if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
                    bt.memory_system.consolidate_if_needed(user_name=uname)
                    # Backfill one past-day recap per turn so Blue has
                    # cross-day continuity ("yesterday we discussed X").
                    bt.memory_system.summarize_previous_sessions()
                    # Index existing day-recaps for semantic recall so
                    # an old conversation can resurface by relevance
                    # (one-shot, cheap no-op after the first call).
                    bt.memory_system.backfill_session_memories()
                    # Recompute behavioural rhythms (rate-limited
                    # internally — a cheap no-op most turns).
                    bt.memory_system.update_rhythms_if_due()
            except Exception as e:
                bt.log.warning(f"[MEM] Background auto-save failed: {e}")

        # Pass the last few turns (not the whole transcript) so the
        # extractor can use Q-A context. Example: assistant asks
        # "what's your favorite food?", user says "pizza" — without
        # the prior assistant turn, "pizza" looks like noise. Four
        # turns is enough context, small enough to stay cheap.
        non_system = [m for m in messages if m.get("role") != "system"]
        latest_context = non_system[-4:] if non_system else []
        latest_context.append({"role": "assistant", "content": final_content})

        threading.Thread(
            target=_background_fact_extraction,
            args=(latest_context, user_name),
            daemon=True
        ).start()

        if robot in bt._continuity_routes.ROBOTS:
            try:
                bt._continuity_routes.note_exchange(
                    robot, last_user_msg, final_content, user_name=user_name
                )
            except Exception as e:
                bt.log.warning(f"[JSPACE] could not schedule J-space pass: {e}")
            finally:
                _continuity_turn_started = False
    return response
