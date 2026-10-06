"""The tool half of a chat turn: deciding, running, and wording a tool call.

Three pieces lifted out of process_with_tools, which was 1,320 lines:

  template_response  formats a handful of tool results directly, skipping a
                     model round trip when the result speaks for itself.
  direct_execute     the fast path — when the selector is confident, the tool
                     runs BEFORE the model is called at all, and the model is
                     asked once to put the result into words.
  run_tool_loop      the slower path — offer the tools, let the model ask,
                     run what it asks for, then make it answer from the
                     results with tools switched off.

Both entry points return a finished response dict, or None to mean "not my
turn, carry on" — matching the fall-through the inlined blocks had.

This is the code that acts on a real house. A mistake here is not a clumsy
sentence, it is a photograph taken or an email sent that nobody asked for, or
a claim that one was. The bodies were moved verbatim and checked line by line
against the originals.
"""

from __future__ import annotations

import re
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import bluetools as bt
from blue_reply_text import reads_as_deliberation, strip_reasoning_tags
from blue.server.thinking import THINK_OFF


def _missing_required_args(tool_name: str, tool_args: Dict[str, Any]) -> List[str]:
    """Required schema parameters that `tool_args` has no usable value for.

    Used to refuse a forced execution that would act on nothing. Unknown
    tools report nothing missing — this guards a known bad shape, it is not
    a validator."""
    for spec in bt.TOOLS:
        fn = spec.get("function", {}) if isinstance(spec, dict) else {}
        if fn.get("name") != tool_name:
            continue
        required = (fn.get("parameters") or {}).get("required") or []
        args = tool_args or {}

        def unusable(name: str) -> bool:
            if name not in args:
                return True
            value = args[name]
            # 0 and False are real values; "" and None are not.
            return value is None or (isinstance(value, str) and not value.strip())

        return [name for name in required if unusable(name)]
    return []


def template_response(tool_name, tool_args, tool_result):
    """Build a quick natural response from tool result without LLM."""
    try:
        data = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
    except (json.JSONDecodeError, TypeError):
        data = {}

    success = data.get('success', True) if isinstance(data, dict) else True

    if not success:
        error = data.get('error', 'Something went wrong') if isinstance(data, dict) else tool_result
        return f"Sorry, that didn't work: {error}"

    if tool_name == 'control_music':
        action = tool_args.get('action', '')
        action_words = {
            'pause': 'Paused the music.',
            'resume': 'Resumed playback.',
            'next': 'Skipping to next track.',
            'previous': 'Going back to previous track.',
            'volume_up': 'Turned the volume up.',
            'volume_down': 'Turned the volume down.',
            'mute': 'Muted.',
        }
        return action_words.get(action, f"Done — {action}.")

    if tool_name == 'play_music':
        query = tool_args.get('query', 'music')
        msg = data.get('message', '') if isinstance(data, dict) else ''
        if msg:
            return msg
        return f"Playing {query} for you."

    if tool_name == 'control_lights':
        action = tool_args.get('action', '')
        mood = tool_args.get('mood', '')
        color = tool_args.get('color', '')
        if mood:
            return f"Set the lights to {mood} mood."
        if color:
            return f"Changed the lights to {color}."
        if action == 'on':
            return "Lights are on."
        if action == 'off':
            return "Lights are off."
        msg = data.get('message', '') if isinstance(data, dict) else ''
        return msg or "Lights updated."

    if tool_name == 'get_local_time':
        if isinstance(data, dict):
            time_str = data.get('time', data.get('local_time', ''))
            date_str = data.get('date', '')
            action = tool_args.get('action', 'get_time')
            if action == 'get_date' and date_str:
                return f"Today is {date_str}."
            elif action == 'get_date_time' and date_str and time_str:
                return f"It's {time_str} on {date_str}."
            elif time_str:
                return f"It's {time_str}."
        return f"The time is {tool_result}." if tool_result else "Here's the time."

    if tool_name == 'set_timer':
        msg = data.get('message', '') if isinstance(data, dict) else ''
        return msg or "Timer set."

    if tool_name == 'music_visualizer':
        return "Light show started! The lights are syncing with the music."

    # Fallback
    return None


def direct_execute(_DIRECT_EXEC_TOOLS, conversation_messages, improved_force_tool,
                   improved_tool_args, last_user_message, robot, *, thinking=None):
    """The fast path. Returns (response, pending_force_tool).

    `thinking` is the turn's decision for bt.call_lm_studio. The two
    retries below (an answer that denied a read or dodged the results) are
    guard retries and never think; with no decision they send nothing.

    `response` is a finished turn, or None to fall through to the loop.
    `pending_force_tool` is the one piece of state that crosses over: when the
    model claims an action it never called, this path queues the tool for the
    loop to force rather than answering here ("Fall through to the iteration
    loop; do NOT return", below). It was an ordinary local shared between two
    blocks of one function; it is now an explicit hand-off.
    """
    pending_force_tool = None
    # Inverted to a guard clause: the whole function exists for this one
    # condition, so the body reads better unnested.
    if not (improved_force_tool and improved_force_tool in _DIRECT_EXEC_TOOLS
                and improved_tool_args is not None and isinstance(improved_tool_args, dict)):
        return None, pending_force_tool

    print(f"\n[FAST-EXEC] Direct tool execution: {improved_force_tool} with {improved_tool_args}")
    tool_result = bt.execute_tool(improved_force_tool, improved_tool_args)
    print(f"   [OK] {improved_force_tool} completed")
    document_read_succeeded = (
        improved_force_tool == "search_documents"
        and bt._document_search_succeeded(tool_result)
    )
    document_self_reflection = bool(
        document_read_succeeded
        and bt.identity_request_kind(last_user_message) == "selfhood"
        and re.search(r"\b(?:reflect|relation)\w*\b", last_user_message, re.I)
    )
    self_reflection_grounding = ""
    if document_self_reflection:
        self_reflection_grounding = (
            " For this self-reflection, keep both sides grounded: you are "
            "Blue, Alex's physical Ohbot robot companion, built by Alex and "
            "run locally on Alex's own workstation. A locally hosted language model is one "
            "component of you, not your identity. Your conversations, sensor "
            "data, memories, and J-space remain on Alex's hardware by design; "
            "do not recast yourself as a generic cloud LLM, a Google/OpenAI "
            "product, or a corporate data-extraction service. Local operation "
            "does not make you neutral: reflect critically on inherited model "
            "and corpus biases, choices in your code and retrieval, omissions "
            "in Alex's library, and the power created by a camera and persistent "
            "memory inside a household. Name yourself as Blue, mention your "
            "Ohbot embodiment and J-space continuity, and relate those concrete "
            "facts to the document rather than making generic AI claims."
        )

    # Add tool call + result to conversation so LLM can format the response
    conversation_messages.append({
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "direct_exec", "type": "function",
                       "function": {"name": improved_force_tool,
                                   "arguments": json.dumps(improved_tool_args)}}]
    })
    conversation_messages.append({
        "role": "tool",
        "tool_call_id": "direct_exec",
        "name": improved_force_tool,
        "content": tool_result
    })
    if improved_force_tool == "web_search":
        answer_guard = (
            "[Answer directly from the live web_search results above. If the "
            "results identify teams, matchups, scores, standings, dates, or "
            "names, state them explicitly. Do NOT say you can look it up, do "
            "NOT ask whether the user wants you to search, and do NOT tell "
            "the user to check another website. If the results are weak or "
            "conflict, say what you found and name the uncertainty.]"
        )
    elif improved_force_tool == "search_documents" and document_read_succeeded:
        answer_guard = (
            "[The local search_documents call above SUCCEEDED and returned "
            "text extracted from the user's real library files. Answer the "
            "user's own message, using this text where it bears on it, in the "
            "length and form the system message asks for. Put [filename] right "
            "after each claim taken from this text — never after something the "
            "user just told you, the calendar, or yourself. "
            "Do not claim the PDF, path, text, or reading tool is unavailable; "
            "do not fall back to training data; and do not ask for an upload. "
            f"{self_reflection_grounding} No more tools.]"
        )
    else:
        answer_guard = "[Answer naturally using the tool results above. No more tools.]"
    conversation_messages.append({
        "role": "user",
        "content": answer_guard
    })
    # Single LLM call just to format the response
    response = bt.call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1,
                                 thinking=thinking)
    _retry_thinking = THINK_OFF if thinking else None
    if response:
        content = response["choices"][0]["message"].get("content", "")
        self_reflection_issue = None
        if document_self_reflection:
            self_reflection_issue = bt.identity_response_problem(
                content,
                bt._robot_cfg(robot)["name"],
                other_names=[
                    bt._robot_cfg(r)["name"] for r in bt.ROBOTS
                    if r != robot
                ],
                request_kind="identity",
            )
        if (improved_force_tool == "search_documents"
                and document_read_succeeded
                and (bt.detect_document_refusal(content) or self_reflection_issue)):
            reason = (f"identity drift ({self_reflection_issue})"
                      if self_reflection_issue else "access denial")
            print(f"   [DOCS] Read succeeded, but response had {reason} - regenerating from clean evidence")
            clean_identity = ""
            if document_self_reflection:
                clean_identity = (
                    " You are Blue, Alex's physical Ohbot robot companion, "
                    "built by Alex and running locally on Alex's own workstation. Your local "
                    "language model is a component, not your identity. Your "
                    "persistent J-space carries remembered episodes, working "
                    "beliefs, commitments, and self-revisions on Alex's hardware. "
                    "Do not describe yourself as a generic or corporate cloud "
                    "LLM. Explain how this local architecture resists data "
                    "extraction while remaining vulnerable to inherited bias, "
                    "curatorial omissions, and household camera/memory power."
                )
            clean_messages = [
                {"role": "system", "content": (
                    bt._robot_cfg(robot)["persona_line"] + "\n"
                    "The local document reader has succeeded. Treat the "
                    "extract below as authoritative evidence from the user's "
                    "own library. Answer the request substantively, cite "
                    "[filename] after claims taken from it, and never deny access or mention "
                    "training data as a substitute for the source, uploads, "
                    "missing tools, or invented paths."
                    + clean_identity
                )},
                {"role": "user", "content": (
                    f"Original request: {last_user_message}\n\n"
                    f"LOCAL DOCUMENT TOOL RESULT:\n{tool_result[:12000]}"
                )},
            ]
            retry = bt.call_lm_studio(
                clean_messages, include_tools=False, force_tool=None, iteration=1,
                thinking=_retry_thinking)
            if retry:
                retry_content = retry["choices"][0]["message"].get("content", "")
                retry_identity_issue = None
                if document_self_reflection:
                    retry_identity_issue = bt.identity_response_problem(
                        retry_content,
                        bt._robot_cfg(robot)["name"],
                        other_names=[
                            bt._robot_cfg(r)["name"] for r in bt.ROBOTS
                            if r != robot
                        ],
                        request_kind="identity",
                    )
                if (retry_content
                        and not bt.detect_document_refusal(retry_content)
                        and not retry_identity_issue):
                    return retry, pending_force_tool

            # A stubborn formatter must never turn a successful read into a
            # false capability denial. Return grounded evidence rather than
            # preserving the bad answer.
            source_match = re.search(
                r"\[([^\]\n]+\.(?:pdf|docx?|txt|md))\]", tool_result, re.I)
            source = source_match.group(1) if source_match else "local document"
            evidence = re.sub(r"\s+", " ", tool_result.split("\n", 2)[-1]).strip()
            evidence = evidence[:700].rstrip()
            if document_self_reflection:
                fallback = (
                    f"I'm Blue, Alex's locally run Ohbot robot companion, and "
                    f"I read [{source}] directly. My persistent J-space and "
                    "camera make me more than a stateless text interface, but "
                    "they also give me powers of memory and observation that "
                    "deserve scrutiny. Local operation keeps household data out "
                    "of a corporate extraction pipeline; it does not make my "
                    "model, code, retrieval choices, or library neutral. The "
                    f"source grounds that tension this way: {evidence}"
                )
            else:
                fallback = (
                    f"I found and read [{source}] successfully. The extracted "
                    f"text says: {evidence}"
                )
            return {"choices": [{"message": {
                "role": "assistant", "content": fallback,
            }}]}, pending_force_tool

        if improved_force_tool == "web_search" and (
                bt.detect_web_refusal(content) or bt._SEARCH_OFFER_RE.search(content or "")):
            print("   [WEB] Search ran, but response dodged the answer - retrying from results")
            conversation_messages.append({"role": "assistant", "content": content})
            conversation_messages.append({
                "role": "user",
                "content": (
                    "[You already ran web_search and have live results above. "
                    "Now answer the user's question directly from those results. "
                    "List the teams/matchups/scores/names if present. Do not ask "
                    "to look it up, and do not tell the user to check a website.]"
                ),
            })
            retry = bt.call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1,
                                      thinking=_retry_thinking)
            # An empty retry is no answer: keep the first one, as when the
            # call fails outright, rather than send nothing.
            if retry and _reply_text(retry):
                return retry, pending_force_tool

        # COMPOUND-REQUEST HALLUCINATION GUARD:
        # Fast-exec ran ONE tool (e.g. browse_website). If the user's
        # original request was compound ("browse + email"), the model
        # often confabulates the second action ("…sent to you at X")
        # since no second tool was called. Catch that here so the email
        # actually goes out, not just the words "email sent". Falls
        # through to the iteration loop with the right pending tool.
        hallucinated_tool = bt.detect_hallucinated_action(content)
        if hallucinated_tool and hallucinated_tool != improved_force_tool:
            # email_snapshot already captured AND mailed the photo: "I've
            # sent you the picture" / "I snapped a photo" is the truth.
            # Forcing send_gmail here would fire a SECOND, attachment-less
            # email; forcing capture_camera would bt.re-shoot for nothing.
            if improved_force_tool == "email_snapshot" and hallucinated_tool in (
                    "send_gmail", "reply_gmail", "capture_camera"):
                if bt._last_vision_image_paths and content:
                    bt._save_visual_observation(content, observer=bt._ACTIVE_CHAT_ROBOT)
                return response, pending_force_tool

            # The retry is meant for COMPOUND requests ("browse + email"):
            # one tool runs, the model narrates the second action without
            # calling its tool, and we force it through. Narrow false-
            # positive guard: after read_gmail, the model often
            # references PAST send/reply activity from earlier turns
            # ("I sent a standard response...") without the user having
            # asked for any send. Suppress the retry in that specific
            # case unless the user message itself contains a write verb.
            if improved_force_tool == "read_gmail" and hallucinated_tool in ("send_gmail", "reply_gmail", "auto_reply_emails"):
                _user_text = (last_user_message or "").lower()
                _write_intent_words = (
                    "send", "email ", "emailing", "reply", "respond",
                    "tell ", "write ", "message ", " text ", "forward",
                    "compose", "shoot ", "ping ", "answer",
                )
                if not any(w in _user_text for w in _write_intent_words):
                    print(
                        f"   [SKIP-RETRY] response sounds like "
                        f"{hallucinated_tool} but user only asked to "
                        f"read (\"{(last_user_message or '')[:60]}\") "
                        f"— treating it as narration about past mail."
                    )
                    if bt._last_vision_image_paths and content:
                        bt._save_visual_observation(content, observer=bt._ACTIVE_CHAT_ROBOT)
                    return response, pending_force_tool

            # Same safety gate as the main loop: a send/mail claim the user
            # never asked for is scrubbed, not executed.
            if hallucinated_tool in ("send_gmail", "reply_gmail", "email_snapshot") and \
                    not bt._user_requested_action(hallucinated_tool, last_user_message):
                print(f"   [SKIP-RETRY] {hallucinated_tool} claim but the user asked for "
                      f"no such action — scrubbing the claim instead of executing it")
                cleaned = bt._scrub_action_claim_sentences(content, hallucinated_tool)
                response["choices"][0]["message"]["content"] = cleaned
                if bt._last_vision_image_paths and cleaned:
                    bt._save_visual_observation(cleaned, observer=bt._ACTIVE_CHAT_ROBOT)
                return response, pending_force_tool

            print(f"   [WARN] Fast-exec model claimed to {hallucinated_tool} after {improved_force_tool} — running it for real")
            # Drop the synthetic "[Answer naturally...]" guard turn so
            # the loop's next call doesn't see it as the latest user msg.
            while conversation_messages and (
                conversation_messages[-1].get("role") == "user"
                and "[Answer naturally" in (conversation_messages[-1].get("content") or "")
            ):
                conversation_messages.pop()
            conversation_messages.append({
                "role": "assistant",
                "content": content,
            })
            conversation_messages.append({
                "role": "user",
                "content": (
                    f"You said you performed that action, but you didn't "
                    f"actually call any tool. Use the {hallucinated_tool} "
                    f"tool now to actually do it — extract the recipient, "
                    f"subject, and body from this conversation."
                ),
            })
            pending_force_tool = hallucinated_tool
            # Fall through to the iteration loop; do NOT return.
        else:
            if bt._last_vision_image_paths and content:
                bt._save_visual_observation(content, observer=bt._ACTIVE_CHAT_ROBOT)
            return response, pending_force_tool
    else:
        # The tool already ran; only the call that words its result failed.
        # "Done!" claimed success and threw the result away.
        return bt.model_unavailable_reply(
            robot, tool_ran=improved_force_tool), pending_force_tool
    return None, pending_force_tool


# ================================================================================
# A FORCED CALL THAT CAME BACK AS WORDS
# ================================================================================
# tool_choice "required" does not guarantee a call. "remind me to call the
# dentist" (2026-10-05 harness) forced create_reminder, and the model wrote
# 6,976 characters deciding which question to ask: "Hmm, that's two
# questions", "Final answer:" again and again, three "</think>" tags. All of
# it was the reply. On 09-27 "It summarizes news and sends the newsfeed by
# email to me" forced send_gmail, which shipped 3,020 characters of "Wait —",
# "Actually, I shouldn't assume" and three self-introductions. With no
# arguments from the selector there was nothing to run instead, so the words
# went out. Now they never do:
#   create_reminder  a plain "remind me to X" with no time in it is set for
#                    about an hour from now and the time is said (Alex's
#                    default: pick and state a time); a request that names
#                    nothing to remind about gets one short question. A time,
#                    or a "that" from the turn before, goes to the retry.
#   anything else    one retry with tool_choice "auto" and a note, then an
#                    honest line if the retry's words are no better, or if
#                    they say the work was done without a call.

# Mail is not offered again on the retry. The forced call already declined to
# send, and a second chance to send mail should come from the user.
_OUTWARD_TOOLS = {"send_gmail", "reply_gmail", "email_snapshot"}

# What did not happen, for the honest line.
_FORCED_TOOL_UNDONE = {
    "send_gmail": "nothing was sent",
    "reply_gmail": "nothing was sent",
    "email_snapshot": "no photo was taken or sent",
    "create_reminder": "no reminder was set",
    "cancel_reminder": "no reminder was changed",
    "reschedule_reminder": "no reminder was changed",
    "complete_reminder": "no reminder was changed",
    "remember_fact": "nothing was saved",
    "remember_person": "nothing was saved",
    "remember_place": "nothing was saved",
    "add_contact": "nothing was saved",
    "create_note": "no note was saved",
    "update_note": "no note was changed",
    "create_document": "no document was saved",
}

_REMINDER_QUESTION = "What should I remind you about, and when?"


def _forced_tool_honest_line(tool: str) -> str:
    """One true sentence for a forced tool that never ran. It has to fit a
    request ("remind me…") and a statement the selector misread as one."""
    undone = _FORCED_TOOL_UNDONE.get(tool, "nothing was done")
    return f"I didn't act on that, so {undone}; say it again if you'd like me to."


def _forced_prose_unshippable(text, finish_reason, *, forced) -> bool:
    """Words that must not be the reply: empty, cut at the token cap, arguing
    with itself, or, from a forced call itself (whose answer was supposed to
    be a call), longer than a short reply."""
    text = (text or "").strip()
    return (not text
            or finish_reason == "length"
            or (forced and len(text) > bt._FORCED_PROSE_MAX_CHARS)
            or reads_as_deliberation(text))


def _reply_text(response) -> str:
    """The words of a model response, "" when it has none (a malformed
    response, an error, or reasoning that used the whole budget)."""
    try:
        message = (response.get("choices") or [{}])[0].get("message") or {}
        return strip_reasoning_tags((message.get("content") or "").strip())
    except (AttributeError, IndexError, TypeError):
        return ""


def _replace_reply(response, text):
    """Make `text` the turn's reply. It is a template, not the model's
    words, so the replay nets must not regenerate it through the model."""
    choice = response["choices"][0]
    choice["message"] = {"role": "assistant", "content": text}
    choice["finish_reason"] = "stop"
    response["blue_templated"] = True


# A retry that says the forced tool's work is done. The forced call declined,
# and a retry that makes no call has done nothing either. "Got it — I'll
# remind you at 3 PM to call your mom." was shipped and stored with nothing
# in the calendar: detect_hallucinated_action knows mail, lights, music and
# documents, and no reminder (review of c41250f). One pattern per kind of
# write, matched sentence by sentence (_retry_claims).
_DID = (r"\bi(?:['’]ve| have| just)?\s+(?:just\s+|now\s+|also\s+|already\s+"
        r"|(?:gone|went) ahead and\s+)?")
_WILL = (r"\b(?:i['’]ll|i will|i['’]m going to|i am going to|let me)\s+"
         r"(?:go ahead and\s+|be sure to\s+|make sure to\s+|definitely\s+)?")
_DONE_OPENER = (r"^\s*(?:all set|you['’]re (?:all )?set|done|sorted|consider it done"
                r"|set|saved|added|booked|scheduled)\s*(?:[!.,:;—–-]|$)")
_THEM = r"\s+(?:it|that|this|them|those|these|the|your)\b"
_RETRY_CLAIM_RES = {
    "reminder": re.compile(
        _DONE_OPENER
        + r"|^\s*(?:set|scheduled|booked)\s+for\b"
        + r"|" + _WILL + r"(?:remind|ping|nudge|alert|notify|buzz)\s+you\b"
        + r"|" + _WILL + r"(?:set|add|create|schedule|put|pop|book)\b[^.!?]{0,30}"
                         r"\b(?:reminders?|calendar|alarm)\b"
        + r"|" + _DID + r"(?:set|added|created|scheduled|saved|put|booked|logged"
                        r"|entered|popped|made|updated)\b[^.!?]{0,30}"
                        r"\b(?:reminders?|calendar|alarm|schedule)\b"
        + r"|\b(?:added|saved|scheduled|booked|logged|put)\b[^.!?]{0,30}"
          r"\b(?:to|on|in(?:to)?)\s+(?:the |your |my )?(?:calendar|reminders|schedule)\b"
        + r"|\breminders?(?:['’]s| is| has been| was| are| have been)?\s+(?:now\s+|all\s+)?"
          r"(?:set|saved|created|added|scheduled|booked|in place|locked in)\b"
        # "Emmy's dentist appointment is set for 11:00 AM" (2295), "That's set."
        # Not "it was set up to test…" (2588), a reminder described.
        + r"|\b(?:(?:appointment|event|meeting)(?:['’]s| is| has been| was)"
          r"|(?:it|that)(?:['’]s| is| has been))\s+"
          r"(?:now\s+|all\s+)?(?:set|scheduled|booked|locked in)\b"
        + r"|\b(?:it['’]s|that['’]s|it is|that is|it['’]ll be|you['’]re)\s+(?:now\s+|all\s+)?"
          r"(?:on|in) (?:the |your |my )?(?:calendar|reminders|schedule)\b"
        + r"|\byou['’]ll (?:get|receive|have|hear)\s+(?:a |the |your |my )?"
          r"(?:reminder|ping|nudge|notification|alert|heads[- ]up)\b",
        re.I),
    "reminder_change": re.compile(
        _DONE_OPENER
        + r"|" + _DID + r"(?:moved|rescheduled|pushed|shifted|changed|updated"
                        r"|cancel+ed|deleted|removed|cleared|dropped|marked|completed"
                        r"|checked off|ticked off|crossed off|ended)" + _THEM
        + r"|" + _WILL + r"(?:move|reschedule|push|shift|change|update|cancel"
                         r"|delete|remove|clear|mark|complete|check off|tick off"
                         r"|cross off|end)" + _THEM
        + r"|\b(?:reminders?|event|appointment|it|that)(?:['’]s| is| has been| was"
          r"| are| have been)\s+(?:now\s+|all\s+)?(?:moved|rescheduled|pushed"
          r"|cancel+ed|deleted|removed|cleared|marked|done|completed?|gone"
          r"|off (?:the|your) (?:list|calendar))\b",
        re.I),
    "note": re.compile(
        _DONE_OPENER
        + r"|" + _DID + r"(?:saved|created|added|jotted|noted|written|stored|filed|put"
                        r"|updated|appended|made|started)\b[^.!?]{0,30}"
                        r"\b(?:notes?|document|doc|file|notebook)\b"
        + r"|" + _WILL + r"(?:save|create|add|jot|write|store|file|put|update|append"
                         r"|make)\b[^.!?]{0,30}\b(?:notes?|document|doc|file|notebook)\b"
        + r"|\b(?:saved|added|stored|jotted|filed|appended)\b[^.!?]{0,30}"
          r"\b(?:as|to|in(?:to)?)\s+(?:a |an |the |your |my )?(?:notes?|document|doc|file"
          r"|notebook)\b"
        + r"|\b(?:notes?|document|doc|file)(?:['’]s| is| has been| was| are| have been)"
          r"\s+(?:now\s+)?(?:saved|created|updated|added|ready|done|written|stored)\b",
        re.I),
    "contact": re.compile(
        _DONE_OPENER
        + r"|" + _DID + r"(?:added|saved|stored|put|updated|entered)\b[^.!?]{0,40}"
                        r"\b(?:contacts?|address book|phone book)\b"
        + r"|" + _WILL + r"(?:add|save|store|put|update|enter)\b[^.!?]{0,40}"
                         r"\b(?:contacts?|address book|phone book)\b"
        + r"|\b(?:added|saved|stored)\b[^.!?]{0,40}\b(?:to|in(?:to)?)\s+"
          r"(?:the |your |my )?(?:contacts|address book|phone book)\b"
        + r"|\bcontact(?:['’]s| is| has been| was)\s+(?:now\s+)?(?:saved|added|created"
          r"|updated)\b",
        re.I),
    # Past tense only. A statement can force remember_person ("that's Clover,
    # she's a TA"), and "I'll remember that" may come true: the background
    # extractor keeps facts from statements after the reply.
    "memory": re.compile(
        _DID + r"(?:saved|stored|added|remembered|recorded|logged|filed|put|updated"
               r"|memori[sz]ed|locked|committed)\b[^.!?]{0,40}"
               r"\b(?:memory|memories|records?|people|contacts?|places?|profile)\b"
        + r"|\b(?:saved|stored|added|filed|logged)\b[^.!?]{0,30}\b(?:to|in(?:to)?)\s+"
          r"(?:the |your |my )?(?:memory|memories|records|people|places|contacts)\b",
        re.I),
}
_RETRY_CLAIM_KIND = {
    "create_reminder": "reminder",
    "reschedule_reminder": "reminder_change", "cancel_reminder": "reminder_change",
    "complete_reminder": "reminder_change",
    "create_note": "note", "update_note": "note", "create_document": "note",
    "add_contact": "contact",
    "remember_fact": "memory", "remember_person": "memory",
    "remember_place": "memory",
}
# Not a claim: a question ("Should I set a reminder for 3 PM?", "What time
# should I remind you?"), an offer that waits on the user ("Tell me the day
# and I'll set it", "Once you tell me the day, I'll remind you", "… if you'd
# like"), a denial in the same clause ("No reminder is set yet"), or recall
# ("Here is what I have stored in my memory", "As I noted in my notes").
_QUESTION_RE = re.compile(
    r"^\W*(?:do|does|did|should|shall|can|could|would|will|want|is|are|was|were"
    r"|have|has|what|when|which|where|how|who)\b[^?]*\?\s*$", re.I)
_MODAL_BEFORE_RE = re.compile(
    r"\b(?:should|shall|can|could|may|might|would|me to|you to|like to|want to)\s*$",
    re.I)
_WAITS_BEFORE_RE = re.compile(
    r"\b(?:if|once|as soon as|whenever|when|after|until)\s+you\b"
    r"|\b(?:tell|give|send|let)\s+me\b|\bsay the word\b", re.I)
_WAITS_AFTER_RE = re.compile(
    r"^[^.!?]*\b(?:if|once|as soon as|when|after)\s+you(?:['’]d)?\s+"
    r"(?:tell|give|let me know|say|confirm|pick|choose|send|share|decide|want"
    r"|like|would like)\b", re.I)
_DENIAL_RE = re.compile(r"\b(?:not|never|no|nothing|cannot|unable)\b|n['’]t\b", re.I)
_RECALL_BEFORE_RE = re.compile(
    r"\b(?:what|all|everything|anything|only|which|as)\s*$", re.I)
_CLAUSE_RE = re.compile(r"[,;:(—–]|\s-\s")


def _says_done(pattern, sentence) -> bool:
    if _QUESTION_RE.match(sentence):
        return False
    for m in pattern.finditer(sentence):
        before, after = sentence[:m.start()], sentence[m.end():]
        if (_MODAL_BEFORE_RE.search(before) or _WAITS_BEFORE_RE.search(before)
                or _RECALL_BEFORE_RE.search(before)
                or _WAITS_AFTER_RE.match(after)
                or _DENIAL_RE.search(_CLAUSE_RE.split(before)[-1])):
            continue
        return True
    return False


def _retry_claims(text, tool):
    """Split a retry's words into (kept, claimed): `claimed` are the sentences
    that say `tool`'s work is done. Kept keeps its own whitespace, so the
    paragraph breaks survive. A tool whose claims are not judged here (mail
    has bt.detect_hallucinated_action, judged with _claim_sentences) claims
    nothing."""
    return _claim_sentences(text, _RETRY_CLAIM_RES.get(_RETRY_CLAIM_KIND.get(tool)))


def _claim_sentences(text, pattern):
    """_retry_claims for any claim pattern: (kept, claimed)."""
    text = (text or "").strip()
    if pattern is None or not text:
        return text, []
    parts = re.split(r"(?<=[.!?])(\s+)", text)
    kept, claimed = [], []
    for sentence, gap in zip(parts[0::2], parts[1::2] + [""]):
        if _says_done(pattern, sentence):
            claimed.append(sentence)
        else:
            kept.append(sentence + gap)
    return "".join(kept).strip(), claimed


# "remind me to call the dentist" -> ("to", "call the dentist"). Only a
# message that IS the request: one buried in a longer message goes to the
# retry, which can read the rest of it.
_REMINDER_ASK_RE = re.compile(
    r"^\s*(?:(?:hey|hi|ok(?:ay)?|so|oh|and|um+|blue|hexia|casper)\b[,!\s]*)*"
    r"(?:please\s+)?(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"(?:remind me\s+(?P<c1>to|that)\s+(?P<t1>.+)"
    r"|(?:set|make|add|create|give)(?: me)?(?: a)? reminder\s+"
    r"(?P<c2>to|that|about|for)\s+(?P<t2>.+)"
    r"|(?:don['’]?t|do not) let me forget\s+(?:(?P<c3>to)\s+)?(?P<t3>.+)"
    r"|remember\s+(?P<c4>to)\s+(?P<t4>.+))$",
    re.I | re.S)
# A request with nothing in it to be reminded of. Not "remind me about that":
# that leans on the turn before, which the retry can read and this can't.
_BARE_REMINDER_RE = re.compile(
    r"^\s*(?:(?:hey|hi|ok(?:ay)?|so|oh|and|um+|blue|hexia|casper)\b[,!\s]*)*"
    r"(?:please\s+)?(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"(?:remind me|(?:set|make|add|create|give)(?: me)?(?: a)? reminder)"
    r"(?:\s+(?:about|of|to do|for)?\s*something)?"
    r"(?:\s+(?:please|for me))?[\s.!?]*$",
    re.I)
# Any hint of when, and any word that could anchor one. Then the time is the
# user's to give and is not picked here (Phase 3's U16 will anchor reminders
# to classes); the retry gets the message instead. Deliberately wide: a miss
# sets "take my meds at nine" for 3:15 PM (review of c41250f), while a false
# hit only costs the retry — "turn on the porch light" goes to the model, as
# every reminder did before c41250f.
_REMINDER_TIME_CUE_RE = re.compile(
    r"\d"
    # a clock in words: "at nine", "four thirty", "half past", "five o'clock",
    # "this pm"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|fifteen|twenty|thirty|forty|fifty|half|quarter|o['’]?clock|[ap]\.?m"
    # a day or a date, misspelt too ("tomorow", "tmr")
    r"|today|tonight|tonite|2nite|tomm?orr?ow|tmrw?|2morr?ow|2moro|noon|midnight"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tues?|wed|thu|thurs?|fri|sat|sun|weekend"
    r"|january|february|march|april|may|june|july|august|september|october"
    r"|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec"
    # a part of the day, a meal, a class, a deadline
    r"|morning|afternoon|evening|night|overnight|eod|eow|eom|cob|first thing"
    r"|end of|breakfast|brunch|lunch(?:time)?|dinner(?:time)?|supper|bedtime"
    r"|class(?:es)?|lecture|seminar|meeting|office hours|semester|term"
    r"|holidays?|vacation|christmas|thanksgiving|easter"
    # a word that anchors one: "at lunch", "by Friday", "in March", "on the
    # way home", "next time", "this pm", "in a few", "after work"
    r"|at|by|around|till|til|until|before|after|on|in|during|within|from|past"
    r"|next|this|later|soon|asap|shortly|when|whenever|while|once|every"
    r"|daily|weekly|monthly|minutes?|mins?|hours?|hrs?|days?|weeks?|months?"
    r"|years?|a (?:bit|while|moment|sec|second))\b",
    re.I)
_VAGUE_REMINDER_WORDS = {
    "it", "that", "this", "them", "those", "these", "something", "stuff",
    "thing", "things", "so", "do", "the", "a", "an", "to", "about", "me", "of",
}
# "remind me to do that", "… to call him": what or who the turn before was
# about, which the retry can read.
_ANAPHORA = {"it", "that", "this", "them", "those", "these", "him", "her",
             "there"}
_SECOND_PERSON = [
    (r"\bI am\b", "you are"), (r"\bI was\b", "you were"),
    (r"\bI['’]m\b", "you're"), (r"\bI['’]ve\b", "you've"),
    (r"\bI['’]ll\b", "you'll"), (r"\bI['’]d\b", "you'd"),
    (r"\bmyself\b", "yourself"), (r"\bmine\b", "yours"),
    (r"\bmy\b", "your"), (r"\bme\b", "you"), (r"\bI\b", "you"),
]


def _second_person(phrase: str) -> str:
    """The user's "call my mom" said back to them: "call your mom"."""
    for pattern, repl in _SECOND_PERSON:
        phrase = re.sub(pattern, repl, phrase, flags=re.I)
    return phrase


def _reminder_ask(user_text: str):
    """What a plain reminder request asks to be reminded of.

    (connector, title) for "remind me to call the dentist"; ("", "") for a
    request that names nothing ("set a reminder", "remind me about
    something"); None when this is not a plain request with no time in it,
    or it leans on the conversation ("remind me about that").
    """
    text = (user_text or "").strip()
    if not text or "\n" in text or _REMINDER_TIME_CUE_RE.search(text):
        return None
    if _BARE_REMINDER_RE.match(text):
        return ("", "")
    m = _REMINDER_ASK_RE.match(text)
    if not m:
        return None
    # "don't let me forget the milk" has no "to": remind them about it.
    connector = (m.group("c1") or m.group("c2") or m.group("c3")
                 or m.group("c4") or "about").lower()
    title = m.group("t1") or m.group("t2") or m.group("t3") or m.group("t4")
    title = title.strip().strip(".!?,;: \"'“”")
    while True:
        tail = re.search(r"[\s,]*\b(?:please|thanks|thank you|for me|ok(?:ay)?)$",
                         title, re.I)
        if not tail:
            break
        title = title[:tail.start()].strip().strip(".!?,;: ")
    # Two sentences, or more than a short title: not plain.
    if re.search(r"[.!?;]\s+\S", title) or len(title) > 100 or len(title.split()) > 12:
        return None
    words = set(re.findall(r"[a-z']+", title.lower()))
    if words & _ANAPHORA:
        return None
    if not words - _VAGUE_REMINDER_WORDS:
        return ("", "")
    return ("about" if connector == "for" else connector, title)


def _default_reminder_time(now: datetime) -> datetime:
    """About an hour from now, rounded up to the next quarter hour. One that
    lands overnight (10 PM to 7 AM) moves to 9 AM instead."""
    t = now + timedelta(hours=1)
    if t.minute % 15 or t.second or t.microsecond:
        t += timedelta(minutes=15 - t.minute % 15)
    t = t.replace(second=0, microsecond=0)
    if t.hour >= 22:
        t = (t + timedelta(days=1)).replace(hour=9, minute=0)
    elif t.hour < 7:
        t = t.replace(hour=9, minute=0)
    return t


def _reminder_fallback(user_text: str, user_name: str,
                       now: Optional[datetime] = None) -> Optional[str]:
    """The reply for a forced create_reminder that wrote words instead.

    Sets the reminder at a picked time and says when, or asks the one
    question; None leaves the turn to the retry. Python picks the time and
    reads the day back from the tool's result: the model does no calendar
    math here.
    """
    ask = _reminder_ask(user_text)
    if ask is None:
        return None
    connector, title = ask
    if not title:
        print("   [FORCE] create_reminder: nothing to remind about — asking")
        return _REMINDER_QUESTION
    now = now or datetime.now()
    at = _default_reminder_time(now)
    when = f"{'today' if at.date() == now.date() else 'tomorrow'} at {at:%H:%M}"
    args = {"user_name": user_name or "Alex",
            "title": title[0].upper() + title[1:], "when": when}
    print(f"   [FORCE] create_reminder with a picked time (none was given): {args}")
    raw = bt.execute_tool("create_reminder", args)
    try:
        result = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        result = {}
    try:
        set_for = datetime.fromisoformat(result["when"]) if result.get("success") else None
    except (KeyError, TypeError, ValueError):
        set_for = None
    if set_for is None:
        return ("I tried to set that reminder but it didn't save; say it again "
                "with a time and I'll try once more.")
    clock = set_for.strftime("%I:%M %p").lstrip("0")
    date = f"{set_for:%A}, {set_for:%B} {set_for.day}"
    days = (set_for.date() - now.date()).days
    day = {0: f"today ({date})", 1: f"tomorrow ({date})"}.get(days, f"on {date}")
    return (f"Done — I'll remind you at {clock} {day} {connector} "
            f"{_second_person(title)}; say if you'd like a different time.")


def _forced_call_failed(response, tool, repairs, conversation_messages,
                        user_text, user_name):
    """A forced call wrote words and the selector supplied no arguments.

    Returns (retry, pending) like _judge_untooled_reply. The words are never
    the reply: they are not even kept in the conversation for the retry,
    which would only continue them.
    """
    content = response["choices"][0]["message"].get("content") or ""
    print(f"   [FORCE] {tool} came back as {len(content)} chars of text — "
          f"not shipping it")
    if tool == "create_reminder":
        reply = _reminder_fallback(user_text, user_name)
        if reply is not None:
            _replace_reply(response, reply)
            return False, None
    repairs.forced_retry = tool
    if tool in _OUTWARD_TOOLS:
        # "If they want something sent, ask for what is missing" alone made
        # the 09-27 statement a request: "I couldn't send that email just
        # now. Which inbox would you like it at?" (live check, 2026-10-05).
        note = (f"[Nothing was sent: {tool} was not called. Reply to what the "
                "user actually said, in one or two sentences. If they asked "
                "you to send something, say it hasn't gone and ask only for "
                "what is missing; if they were telling you something, answer "
                "that and don't bring up sending.]")
    else:
        note = (f"[You were asked to call {tool} and wrote text instead, so "
                "nothing has been done. If the user's last message asks for "
                f"that, call {tool} now with arguments from their own words. "
                "If it doesn't, or something it needs is missing, don't call "
                "it: answer the user directly in one or two sentences.]")
    conversation_messages.append({"role": "user", "content": note})
    return True, None


def _known_tool(name) -> bool:
    return name in {t.get("function", {}).get("name") for t in bt.TOOLS}


class _ReplyRepairs:
    """One-shot corrections for a reply that arrived without a tool call.

    Each fires at most once a turn. Without that a stubborn model and the
    loop ping-pong: it refuses, the loop forces a search, it refuses again.

    `forced_retry` is a tool whose forced call wrote words, queued for the
    one "auto" retry; `retried_tool` is that tool once the retry has run.
    """
    __slots__ = ("web_refusal", "leaked_tool", "phantom_claim",
                 "calendar_denial", "memory_write", "forced_retry",
                 "retried_tool")

    def __init__(self):
        self.web_refusal = False
        self.leaked_tool = False
        self.phantom_claim = False
        self.calendar_denial = False
        self.memory_write = False
        self.forced_retry = None
        self.retried_tool = None


def _judge_untooled_reply(response, assistant_message, repairs, *,
                          iteration, force_tool, conversation_messages,
                          improved_force_tool, improved_tool_args,
                          _detect_msg, last_user_message, user_name):
    """Decide what to do with a reply the model gave without calling a tool.

    Returns (retry, pending_force_tool). retry True means go round again,
    forcing that tool if one is named. False means the reply is the answer.

    `conversation_messages` and `repairs` are appended to and set in place,
    and `response` may be edited before it is accepted.
    """
    pending = None
    content = assistant_message.get("content", "")

    # Check if model should have used a tool but didn't
    if iteration == 1 and improved_force_tool:
        correct_tool = improved_force_tool
        print(f"   [ERROR] Model answered without using {correct_tool} tool!")

        # Use selector's extracted params if available, otherwise let LLM retry
        tool_args = improved_tool_args if improved_tool_args is not None else {}
        # ...but never run a tool with nothing to act on. The old
        # `is not None` test was always true, so a detector that
        # returned extracted_params={} (remember_person does) ran
        # the tool with {} — "[OK] Remembered person:" with a blank
        # name, writing an empty row (live 2026-08-13). If the
        # schema needs arguments the selector could not supply,
        # let the model's own answer stand.
        missing = _missing_required_args(correct_tool, tool_args)
        if missing and correct_tool == "remember_fact" and not repairs.memory_write:
            # "update your memory: …" was answered "I've updated my records"
            # with nothing written. Ask once more for the real call — or for
            # an honest "not saved" when no value was given.
            repairs.memory_write = True
            print("   [MEMORY] remember_fact was forced but not called — asking again")
            conversation_messages.append({"role": "assistant", "content": content})
            conversation_messages.append({"role": "user", "content": (
                "[Call remember_fact now with the fact_key and fact_value the "
                "user just gave. If they gave no value, do not call it: ask "
                "for the value and say plainly that nothing was saved.]")})
            return True, "remember_fact"
        if missing:
            print(f"   [SKIP] not direct-executing {correct_tool} — "
                  f"no {', '.join(missing)} was extracted")
            # Not when this pass forced a different tool (a claim handed
            # over from the fast path): the general check below judges that.
            # A call written out as text is still run, by the leaked-call
            # repair below.
            _written = None if repairs.leaked_tool else bt.parse_leaked_tool_call(content)
            if force_tool == correct_tool and not (_written and _known_tool(_written[0])):
                return _forced_call_failed(
                    response, correct_tool, repairs, conversation_messages,
                    bt._intent_text(last_user_message
                                    if isinstance(last_user_message, str) else ""),
                    user_name)
        else:
            print(f"   [RETRY] Direct-executing {correct_tool} with extracted params")
            tool_result = bt.execute_tool(correct_tool, tool_args)
            conversation_messages.append({
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "forced", "type": "function",
                               "function": {"name": correct_tool, "arguments": json.dumps(tool_args)}}]
            })
            conversation_messages.append({
                "role": "tool",
                "tool_call_id": "forced",
                "name": correct_tool,
                "content": tool_result
            })
            return True, pending

    # The model wrote a tool call as visible TEXT instead of calling it
    # (the "<tool_call>...</tool_call> reached the user as words" bug).
    # Parse it and run it for real; the next iteration composes the
    # answer from the actual result.
    _leaked = None if repairs.leaked_tool else bt.parse_leaked_tool_call(content)
    if _leaked and _known_tool(_leaked[0]):
        repairs.leaked_tool = True
        _lk_name, _lk_args = _leaked
        print(f"   [WARN] model wrote its {_lk_name} call as text — executing it for real")
        tool_result = bt.execute_tool(_lk_name, _lk_args)
        conversation_messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "leaked", "type": "function",
                            "function": {"name": _lk_name, "arguments": json.dumps(_lk_args)}}]
        })
        conversation_messages.append({"role": "tool", "tool_call_id": "leaked",
                                      "name": _lk_name, "content": tool_result})
        return True, pending

    # Words from a forced call (the remember_fact re-ask, a claimed action
    # being forced through) or from the one retry after a forced call wrote
    # words: they go out only if they read as a reply.
    if force_tool or repairs.retried_tool:
        _finish = ((response.get("choices") or [{}])[0] or {}).get("finish_reason")
        if _forced_prose_unshippable(content, _finish, forced=bool(force_tool)):
            _tool = force_tool or repairs.retried_tool
            print(f"   [FORCE] {_tool}: {len(content or '')} chars came back that "
                  f"are not a reply (finish_reason={_finish}) — honest line instead")
            _replace_reply(response, _forced_tool_honest_line(_tool))
            return False, None

    # The retry made no call, so whatever it says was done was not. A
    # reminder, note, document or contact was asked for in so many words, and
    # what is left beside the claim ("Sure thing! … Say hi to her for me!")
    # still reads as done: the honest line replaces it all. A memory tool can
    # be forced by a statement, so there only the claim goes and a real reply
    # around it stays ("Nice to meet Clover!").
    if repairs.retried_tool and not force_tool:
        _tool = repairs.retried_tool
        _kept, _claimed = _retry_claims(content, _tool)
        if _claimed:
            from blue.server.turn_completion import _substantive
            print(f"   [FORCE] retry after a failed forced {_tool} says it was "
                  f"done with no call ({_claimed[0][:80]!r}) — not shipping that")
            if _RETRY_CLAIM_KIND.get(_tool) == "memory" and _substantive(_kept):
                response["choices"][0]["message"]["content"] = _kept
            else:
                _replace_reply(response, _forced_tool_honest_line(_tool))
            return False, None

    # The model claimed it has no live/real-time access, or told the
    # user to go check a website — but web_search exists precisely for
    # this. Run the search it dodged and make it answer from results.
    _memory_recall_turn = (
        bt.identity_request_kind(_detect_msg) in {
            "shared_recall", "self_memory", "evolution", "origin",
        }
        or bool(re.search(
            r"\b(?:remember|recall|what did you do|how was your day)\b",
            _detect_msg,
            re.I,
        ))
    )
    if (bt.detect_web_refusal(content) and not repairs.web_refusal
            and not _memory_recall_turn):
        repairs.web_refusal = True
        print("   [WARN] model claimed no live access — forcing web_search")
        _q = _detect_msg.strip()[:160]
        # A bare follow-up ("tell me the latest") carries no subject —
        # borrow it from the previous user turn.
        if len(re.findall(r"[a-z0-9]{3,}", _q.lower())) < 3:
            _prev_users = [m.get("content", "") for m in conversation_messages
                           if m.get("role") == "user" and isinstance(m.get("content"), str)]
            if len(_prev_users) >= 2:
                _q = f"{_prev_users[-2].strip()[:120]} {_q}".strip()
        search_result = bt.execute_tool("web_search", {"query": _q})
        conversation_messages.append({
            "role": "assistant",
            "content": "Let me actually look that up.",
            "tool_calls": [{"id": "forced", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": _q})}}]
        })
        conversation_messages.append({"role": "tool", "tool_call_id": "forced", "name": "web_search", "content": search_result})
        conversation_messages.append({
            "role": "user",
            "content": ("[Those are LIVE web results you just fetched yourself. Answer "
                        "the question directly from them. Do NOT say you lack live or "
                        "real-time access, and do NOT tell the user to check a website.]")
        })
        return True, pending

    # The model disowned the calendar it actually maintains ("I don't
    # have a persistent calendar", "read-only access", "add it manually
    # in your calendar app"). Load the REAL calendar and make him answer
    # from it — and, if Alex asked for a change, edit it with his tools.
    if (bt.ENHANCED_TOOLS_AVAILABLE and not repairs.calendar_denial
            and bt.detect_calendar_denial(content)
            and bt._CALENDAR_TOPIC_RE.search(last_user_message or "")):
        repairs.calendar_denial = True
        print("   [WARN] model disowned the calendar — loading the real one")
        _cal_user = user_name or "Alex"
        _cal_args = {"user_name": _cal_user, "hours_ahead": 24 * 365}
        cal_result = bt.execute_tool("get_upcoming_reminders", _cal_args)
        conversation_messages.append({
            "role": "assistant",
            "content": "Let me check the calendar I keep for you.",
            "tool_calls": [{"id": "calforce", "type": "function",
                            "function": {"name": "get_upcoming_reminders",
                                         "arguments": json.dumps(_cal_args)}}]
        })
        conversation_messages.append({"role": "tool", "tool_call_id": "calforce",
                                      "name": "get_upcoming_reminders", "content": cal_result})
        conversation_messages.append({
            "role": "user",
            "content": (
                "[Those are the entries from Alex's ACTUAL household calendar, which "
                "you DO maintain. You are NOT read-only and this is NOT an external "
                "app — you can add, reschedule, and cancel events yourself with your "
                "reminder tools. Answer from these entries. If Alex asked you to "
                "change one (for example, end a class/course on a date), call "
                "reschedule_reminder now with that event's title_query and the new "
                "fields (until=<date> to end a repeat). Never say you don't have a "
                "calendar, that it's read-only, or that Alex must do it manually.]"
            ),
        })
        pending = "reschedule_reminder" if bt._user_asked_calendar_edit(last_user_message) else None
        return True, pending

    # Check if model is hallucinating search results
    if bt.detect_hallucinated_search(content):
        print("   [WARN]  AI IS HALLUCINATING - forcing search")
        search_query = last_user_message.replace("search for", "").strip()[:100]
        search_result = bt.execute_tool("web_search", {"query": search_query})
        conversation_messages.append({
            "role": "assistant",
            "content": "Let me search for that.",
            "tool_calls": [{"id": "forced", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": search_query})}}]
        })
        conversation_messages.append({"role": "tool", "tool_call_id": "forced", "name": "web_search", "content": search_result})
        return True, pending

    # Check if model is claiming to have performed an action it
    # didn't actually call a tool for ("I sent the email", "I turned
    # off the lights", etc.). Stops the worst class of confabulation:
    # user thinks an email was sent when nothing happened.
    hallucinated_tool = bt.detect_hallucinated_action(content)
    # A completed email_snapshot earlier in this turn makes later
    # "sent the photo" / "took a picture" wording TRUE — bt.re-forcing
    # send_gmail would mail a duplicate without the photo.
    if hallucinated_tool in ("email_snapshot", "send_gmail",
                             "reply_gmail", "capture_camera") and any(
            m.get("role") == "tool" and m.get("name") == "email_snapshot"
            for m in conversation_messages):
        hallucinated_tool = None
    if hallucinated_tool and not force_tool and repairs.retried_tool:
        # The forced call declined to do this a moment ago, so the claim is
        # invented, and the retry is no second chance to act. Judged sentence
        # by sentence, as the reminder claims are: the retry was told to say
        # the mail hasn't gone, and "I haven't sent it yet — what should the
        # email say?" matched on "sent it" and was scrubbed to "To be clear —
        # I didn't actually send or do anything just now. What would you
        # like to know?" (S4 final review). A denial or a question is not a
        # claim. What a request leaves beside a claim still reads as done
        # ("Sure!"), so there the honest line replaces it all.
        _kept, _claimed = _claim_sentences(
            content, bt._ACTION_CLAIM_PATTERNS.get(hallucinated_tool))
        if not _claimed:
            hallucinated_tool = None
        else:
            from blue.server.turn_completion import _substantive
            print(f"   [WARN] retry after a failed forced {repairs.retried_tool} "
                  f"claims {hallucinated_tool} ({_claimed[0][:80]!r}) — not shipping that")
            if (_substantive(_kept)
                    and not bt._user_requested_action(hallucinated_tool,
                                                      last_user_message)):
                response["choices"][0]["message"]["content"] = _kept
            else:
                _replace_reply(response, _forced_tool_honest_line(repairs.retried_tool))
            return False, None
    if hallucinated_tool and not force_tool:
        # The force-retry below turns the claim into a REAL action —
        # only right when the user actually asked for one. A claim
        # nobody asked for ("I sent the introduction email to the
        # class", 2026-07-09) must be regenerated, and if the model
        # insists, scrubbed — NEVER executed.
        if not bt._user_requested_action(hallucinated_tool, last_user_message):
            if repairs.phantom_claim:
                print(f"   [WARN] AI still claiming {hallucinated_tool} nobody asked for — scrubbing the claim")
                cleaned = bt._scrub_action_claim_sentences(content, hallucinated_tool)
                response["choices"][0]["message"]["content"] = cleaned
                if bt._last_vision_image_paths and cleaned:
                    bt._save_visual_observation(cleaned, observer=bt._ACTIVE_CHAT_ROBOT)
                return False, None
            repairs.phantom_claim = True
            print(f"   [WARN] AI claimed {hallucinated_tool} nobody asked for — regenerating, NOT executing")
            conversation_messages.append({
                "role": "user",
                "content": (
                    "[Correction: you claimed you performed an action, but the "
                    "user did not ask for any such action and no tool was called. "
                    "Nothing was sent or done. Do NOT perform or claim any "
                    "action. Just answer the user's actual question directly: "
                    f"\"{(last_user_message or '').strip()[:300]}\"]"
                ),
            })
            return True, pending
        print(f"   [WARN] AI claimed to {hallucinated_tool} but no tool called — forcing retry")
        # Replace the lying response with a marker that tells the
        # next iteration "you said you did this, now actually do it"
        # via a forced tool call. The carryover variable survives the
        # loop's `force_tool = None` reset AND the no-tools cap.
        conversation_messages.append({
            "role": "user",
            "content": (
                f"Wait — you said you performed that action, but you "
                f"didn't actually call any tool. Use the {hallucinated_tool} "
                f"tool now to actually do it. Get the recipient, subject, "
                f"and body from the recent conversation."
            ),
        })
        pending = hallucinated_tool
        return True, pending

    # Detect if model is denying tool capabilities after tools succeeded
    if iteration > 1:
        content_lower = content.lower()
        denial_phrases = [
            "can't access", "cannot access", "don't have access",
            "unable to access", "can't browse", "cannot browse",
        ]
        is_denial = any(phrase in content_lower for phrase in denial_phrases)

        if is_denial:
            print(f"   [FIX] Model denying tool capabilities - forcing acknowledgment")
            # Find the most recent tool result
            last_tool_result = None
            last_tool_name = None
            for msg in reversed(conversation_messages):
                if msg.get("role") == "tool":
                    last_tool_result = msg.get("content", "")
                    last_tool_name = msg.get("name", "")
                    break

            if last_tool_result and last_tool_name:
                conversation_messages.append({
                    "role": "user",
                    "content": (
                        f"The {last_tool_name} tool already completed successfully. "
                        f"Results: {last_tool_result[:500]}\n\n"
                        f"Use these results to answer. Do not say you can't access anything."
                    )
                })
                print(f"   [RETRY] Added correction for {last_tool_name}")
                return True, pending

    # Auto-save visual observation if this response was about an image
    content = assistant_message.get("content", "")
    if bt._last_vision_image_paths and content:
        bt._save_visual_observation(content, observer=bt._ACTIVE_CHAT_ROBOT)

    print("[OK] Response complete (no tool calls)")
    return False, None

def run_tool_loop(_detect_msg, _identity_kind, conversation_messages,
                  improved_force_tool, improved_tool_args, is_greeting,
                  last_user_message, max_iterations, on_token, user_name,
                  pending_force_tool=None, *, thinking=None):
    """Offer the tools, run what the model asks for, then make it answer.

    `thinking` is the turn's decision, passed to every call of the loop.

    Returns a finished response, or None if the loop ran out of iterations
    without producing one (the caller supplies the fallback, as before).

    The loop-carried state was initialised above the loop when this was
    inline; it is initialised here now. `iteration` in particular is
    incremented on entry, so it has to exist first.
    """
    iteration = 0
    _conversational_turn = False
    repairs = _ReplyRepairs()
    while iteration < max_iterations:
        iteration += 1
        print(f"\n[ITER] Iteration {iteration}")

        force_tool = None

        # ITERATION 1: Force correct tool based on clear intent
        if iteration == 1:
            if improved_force_tool:
                force_tool = improved_force_tool
                print(f"   [FORCE] Using tool from priority detection: {force_tool}")
            elif is_greeting:
                print("   [SKIP] Greeting detected - no tool needed")
                force_tool = None
                # A greeting is a conversational turn too: "do you want to
                # say hello to everyone?" was offered all 54 schemas, ~19.7k
                # prompt tokens against ~13k with the reflex set.
                _conversational_turn = True
            else:
                print("   [ALLOW] No clear tool intent - letting model decide")
                # Let it decide from the reflex set rather than all 53
                # schemas: they render after the system message and so are
                # re-prefilled every turn (~2.4s). A tool outside the set
                # that the model wanted is recovered by the hallucinated
                # action check below, which forces it on a retry.
                _conversational_turn = True

        # Carry over a force_tool set by the previous iteration's hallucination
        # detector — this MUST run with tools enabled, otherwise the retry is
        # pointless. Bypasses the no-tools cap below.
        retry_tool = None
        if pending_force_tool:
            force_tool = pending_force_tool
            pending_force_tool = None
            print(f"   [HALLUCINATION-RETRY] Forcing {force_tool} with tools enabled")
        # A forced call wrote words instead of calling: one more try, where
        # words are a fair answer (_forced_call_failed queued it).
        elif repairs.forced_retry:
            retry_tool = repairs.retried_tool = repairs.forced_retry
            repairs.forced_retry = None
            print(f"   [FORCE-RETRY] {retry_tool} not called — asking once more"
                  + (" without tools" if retry_tool in _OUTWARD_TOOLS
                     else " with tool_choice auto"))
        # After iteration 1, force text-only responses (no tools) to avoid
        # extra LLM round-trips — UNLESS we'bt.re retrying a hallucinated action,
        # in which case the whole point is to actually call the tool.
        elif iteration >= 2:
            print(f"   [LIMIT] Iteration {iteration} - forcing response without tools")
            conversation_messages.append({
                "role": "user",
                "content": "[Respond now using the tool results above. No more tool calls.]"
            })
            response = bt.call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=iteration,
                                      on_token=on_token, thinking=thinking)
            if not response:
                # Tools ran this turn; say which, since the answer is lost.
                _ran = sorted({
                    (call.get("function") or {}).get("name") or "tool"
                    for m in conversation_messages
                    for call in (m.get("tool_calls") or [])
                    if isinstance(call, dict)
                })
                return bt.model_unavailable_reply(
                    bt._ACTIVE_CHAT_ROBOT, user_name,
                    tool_ran=", ".join(_ran) or None)
            return response

        if retry_tool:
            _offer = retry_tool not in _OUTWARD_TOOLS
            # A retry, so no reasoning, as for the guards' regenerations. On a
            # note or document it also has the forced call's 8,192-token
            # room, and reasoning there is out of reach of the prose stop.
            response = bt.call_lm_studio(
                conversation_messages,
                include_tools=_offer,
                force_tool=retry_tool if _offer else None,
                iteration=iteration,
                on_token=on_token,
                force_choice="auto",
                thinking=THINK_OFF if thinking else None,
            )
        else:
            _include_tools = not (_identity_kind and not force_tool)
            if not _include_tools and iteration == 1:
                print("   [IDENTITY] Self/continuity question — answering from prompt state without tools")
            response = bt.call_lm_studio(
                conversation_messages,
                include_tools=_include_tools,
                force_tool=force_tool,
                iteration=iteration,
                on_token=on_token,
                tool_scope=("reflex" if _conversational_turn and not force_tool
                            else "full"),
                thinking=thinking,
            )

        if not response:
            return bt.model_unavailable_reply(bt._ACTIVE_CHAT_ROBOT, user_name)

        # A malformed reply must degrade, not raise. LM Studio can answer with
        # {"error": ...} or an empty choices list — an unloaded model, a
        # context overflow that survived the retrim, a template rejection. The
        # bare subscript here turned all of those into an IndexError that
        # escaped to a 500, which is precisely the path that makes Ohbot say
        # "I'm having trouble connecting" instead of anything useful.
        assistant_message = None
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict) and isinstance(first.get("message"), dict):
                    assistant_message = first["message"]
        if assistant_message is None:
            bt.log.error(f"[LLM] Unusable response shape: {str(response)[:300]}")
            return {"choices": [{"message": {
                "role": "assistant",
                "content": "Sorry — my language model returned something I "
                           "couldn't read. Could you say that again?",
            }}]}
        tool_calls = assistant_message.get("tool_calls", [])

        if not tool_calls:
            retry, pending_force_tool = _judge_untooled_reply(
                response, assistant_message, repairs,
                iteration=iteration, force_tool=force_tool,
                conversation_messages=conversation_messages,
                improved_force_tool=improved_force_tool,
                improved_tool_args=improved_tool_args,
                _detect_msg=_detect_msg,
                last_user_message=last_user_message,
                user_name=user_name)
            if retry:
                continue
            return response

        print(f"[TOOL] Model requested {len(tool_calls)} tool call(s)")

        # A call cut off by the token cap has truncated JSON arguments —
        # half a document, half an email. Running it would save or send the
        # fragment; parsing it used to raise straight to a 500.
        if (response.get("choices") or [{}])[0].get("finish_reason") == "length":
            print("   [LLM] tool call cut off at the length limit — not running it")
            return {"choices": [{"message": {"role": "assistant", "content": (
                "[System: that was cut off at the length limit before it could "
                "be saved or sent. Nothing was done — ask for a shorter version "
                "or in parts.]")}, "finish_reason": "length"}],
                "blue_error": "length"}

        # Check if model is using tools when it shouldn't
        if is_greeting and not force_tool:
            print(f"   [WARN] Model called tool for greeting/casual chat - this is unnecessary!")
            # Let it proceed but warn in logs

        conversation_messages.append(assistant_message)

        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            try:
                function_args = json.loads(tool_call["function"]["arguments"] or "{}")
            except (ValueError, TypeError) as exc:
                bt.log.warning(f"[TOOL] unreadable {function_name} arguments: {exc}")
                conversation_messages.append({
                    "role": "tool", "tool_call_id": tool_call["id"],
                    "name": function_name,
                    "content": json.dumps({"success": False, "error":
                        "The call's arguments were not valid JSON; nothing was run."}),
                })
                continue
            tool_result = bt.execute_tool(function_name, function_args)
            conversation_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": function_name,
                "content": tool_result
            })

            # Gmail operation reminders (prevents confusing read/reply/send)
            _gmail_reminders = {
                "read_gmail": "[You just READ emails. Summarize what you found. Don't say you replied or sent.]",
                "reply_gmail": "[You just REPLIED to emails. Confirm what you did.]",
                "send_gmail": "[You just SENT an email. Confirm what you did.]",
            }
            if function_name in _gmail_reminders:
                try:
                    result_data = json.loads(tool_result)
                    if result_data.get("success"):
                        reminder = _gmail_reminders[function_name]
                        # Fanmail: add personalized reply hint
                        if function_name == "read_gmail" and "fanmail" in str(function_args).lower() and result_data.get("emails"):
                            reminder += " Compose a personalized reply referencing specific details from their message."
                        conversation_messages.append({"role": "user", "content": reminder})
                except Exception:
                    pass

        if iteration == 1:
            conversation_messages.append({
                "role": "user",
                "content": "[Answer the user naturally using the tool results above. Do not call more tools.]"
            })

        # CRITICAL FIX: After executing all tools, loop back to get the model's response to the tool results
        # Without this continue, the code falls through to the error return statement below
        continue
    return None
