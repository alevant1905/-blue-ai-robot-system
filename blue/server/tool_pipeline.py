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
from typing import Any, Dict, List, Optional

import bluetools as bt


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
                   improved_tool_args, last_user_message, robot):
    """The fast path. Returns (response, pending_force_tool).

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
            "run locally in Kitchener. A locally hosted language model is one "
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
            "original request directly from that text and cite [filename]. "
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
    response = bt.call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1)
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
                    "built by Alex and running locally in Kitchener. Your local "
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
                    "own library. Answer the request substantively, cite the "
                    "source as [filename], and never deny access or mention "
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
                clean_messages, include_tools=False, force_tool=None, iteration=1)
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

        if improved_force_tool == "web_search" and bt.detect_web_refusal(content):
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
            retry = bt.call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1)
            if retry:
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
        return {"choices": [{"message": {"role": "assistant", "content": "Done!"}}]}, pending_force_tool
    return None, pending_force_tool


def run_tool_loop(_detect_msg, _identity_kind, conversation_messages,
                  improved_force_tool, improved_tool_args, is_greeting,
                  last_user_message, max_iterations, on_token, user_name,
                  pending_force_tool=None):
    """Offer the tools, run what the model asks for, then make it answer.

    Returns a finished response, or None if the loop ran out of iterations
    without producing one (the caller supplies the fallback, as before).

    The loop-carried state was initialised above the loop when this was
    inline; it is initialised here now. `iteration` in particular is
    incremented on entry, so it has to exist first.
    """
    iteration = 0
    _conversational_turn = False
    _web_refusal_forced = False
    _leaked_tool_forced = False
    _phantom_claim_corrected = False
    _calendar_denial_forced = False
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
            if pending_force_tool:
                force_tool = pending_force_tool
                pending_force_tool = None
                print(f"   [HALLUCINATION-RETRY] Forcing {force_tool} with tools enabled")
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
                                          on_token=on_token)
                if not response:
                    return {"choices": [{"message": {"role": "assistant", "content": "I'm having trouble connecting."}}]}
                return response

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
            )

            if not response:
                return {"choices": [{"message": {"role": "assistant", "content": "I'm having trouble connecting."}}]}

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
                    if missing:
                        print(f"   [SKIP] not direct-executing {correct_tool} — "
                              f"no {', '.join(missing)} was extracted")
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
                        continue

                # The model wrote a tool call as visible TEXT instead of calling it
                # (the "<tool_call>...</tool_call> reached the user as words" bug).
                # Parse it and run it for real; the next iteration composes the
                # answer from the actual result.
                _leaked = None if _leaked_tool_forced else bt.parse_leaked_tool_call(content)
                if _leaked and _leaked[0] in {
                        t.get("function", {}).get("name") for t in bt.TOOLS}:
                    _leaked_tool_forced = True
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
                    continue

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
                if (bt.detect_web_refusal(content) and not _web_refusal_forced
                        and not _memory_recall_turn):
                    _web_refusal_forced = True
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
                    continue

                # The model disowned the calendar it actually maintains ("I don't
                # have a persistent calendar", "read-only access", "add it manually
                # in your calendar app"). Load the REAL calendar and make him answer
                # from it — and, if Alex asked for a change, edit it with his tools.
                if (bt.ENHANCED_TOOLS_AVAILABLE and not _calendar_denial_forced
                        and bt.detect_calendar_denial(content)
                        and bt._CALENDAR_TOPIC_RE.search(last_user_message or "")):
                    _calendar_denial_forced = True
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
                    pending_force_tool = "reschedule_reminder" if bt._user_asked_calendar_edit(last_user_message) else None
                    continue

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
                    continue

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
                if hallucinated_tool and not force_tool:
                    # The force-retry below turns the claim into a REAL action —
                    # only right when the user actually asked for one. A claim
                    # nobody asked for ("I sent the introduction email to the
                    # class", 2026-07-09) must be regenerated, and if the model
                    # insists, scrubbed — NEVER executed.
                    if not bt._user_requested_action(hallucinated_tool, last_user_message):
                        if _phantom_claim_corrected:
                            print(f"   [WARN] AI still claiming {hallucinated_tool} nobody asked for — scrubbing the claim")
                            cleaned = bt._scrub_action_claim_sentences(content, hallucinated_tool)
                            response["choices"][0]["message"]["content"] = cleaned
                            if bt._last_vision_image_paths and cleaned:
                                bt._save_visual_observation(cleaned, observer=bt._ACTIVE_CHAT_ROBOT)
                            return response
                        _phantom_claim_corrected = True
                        print(f"   [WARN] AI claimed {hallucinated_tool} nobody asked for — regenerating, NOT executing")
                        conversation_messages.append({
                            "role": "user",
                            "content": (
                                "[Correction: you claimed you performed an action, but the "
                                "user did not ask for any such action and no tool was called. "
                                "Nothing was sent or done. Do NOT perform, offer, or claim any "
                                "action. Just answer the user's actual question directly: "
                                f"\"{(last_user_message or '').strip()[:300]}\"]"
                            ),
                        })
                        continue
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
                    pending_force_tool = hallucinated_tool
                    continue

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
                            continue

                # Auto-save visual observation if this response was about an image
                content = assistant_message.get("content", "")
                if bt._last_vision_image_paths and content:
                    bt._save_visual_observation(content, observer=bt._ACTIVE_CHAT_ROBOT)

                print("[OK] Response complete (no tool calls)")
                return response

            print(f"[TOOL] Model requested {len(tool_calls)} tool call(s)")

            # Check if model is using tools when it shouldn't
            if is_greeting and not force_tool:
                print(f"   [WARN] Model called tool for greeting/casual chat - this is unnecessary!")
                # Let it proceed but warn in logs

            conversation_messages.append(assistant_message)

            for tool_call in tool_calls:
                function_name = tool_call["function"]["name"]
                function_args = json.loads(tool_call["function"]["arguments"])
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
