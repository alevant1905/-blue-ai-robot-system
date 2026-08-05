"""Everything spliced into a turn before the model sees it.

The 172 lines that decide what Blue knows when he answers: sanitising the
inbound thread, the durable memory blocks, dated recall, the canonical family
facts, recorded self-history, camera memory, live web research and Wikipedia.

Lifted whole out of chat_completions. It reads as a pipeline and now looks
like one: messages go in, an enriched message list comes out. Every block is
individually guarded, so a failure in one source costs that source and not
the turn.
"""

from __future__ import annotations

from typing import Any, Dict, List

import bluetools as bt


def build(messages: List[Dict[str, Any]], *, _grounded_reply, _self_request_kind, focus, language, last_user_msg, research_turn, robot, user_name, wiki_turn) -> List[Dict[str, Any]]:
    """Return `messages` with this turn's context spliced in."""
    messages = bt._sanitize_inbound_messages(messages, robot=robot)

    # INJECT HISTORICAL CONTEXT (only for LLM-bound requests). Chat-only
    # kids (Vilda's iPad) are skipped on purpose: we never splice Alex's
    # semantic memories/facts/schedule into her chat — it keeps her
    # experience simple and avoids surfacing Alex's private notes (or his
    # calendar) to a child. Within-session continuity still comes from
    # the turns the page carries on each request.
    # Memory belongs to the speaker, not to the length of the message.
    # The old >3-word gate made exactly the most contextual turns —
    # "still?", "what about Hexia?", "go on" — forget conversations
    # from another window. The memory layer is already cheap, dedupes
    # the live thread, and its own builder avoids semantic search when
    # there is no useful anchor, so inject it on every non-canonical
    # adult LLM turn.
    _needs_history = bool(
        not _grounded_reply
        and user_name not in bt._CHAT_ONLY_USERS
        and last_user_msg
    )
    if _needs_history:
        # Enhanced memory has its own SQLite store and ChromaDB — it
        # does NOT depend on the legacy `blue_database` module. Don't
        # gate it on bt.CONVERSATION_DB_AVAILABLE; that flag only covers
        # the legacy fallback path below.
        if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
            should_inject = bt.memory_system.should_inject_context(messages)
            if should_inject:
                historical_context = bt.memory_system.build_context(messages, user_name=user_name, robot=robot)
                # Library focus active: drop the cross-conversation
                # SEMANTIC recall blocks so a past chat about a different
                # course/topic can't bleed into a focused conversation.
                # Identity facts, explicit notes, daily rhythms and the
                # current thread's recent history are kept.
                if historical_context and (focus.get("docs") or focus.get("folders")):
                    _FOCUS_DROP = ("<relevant_memories>", "<proactive_hint>",
                                   "<earlier_sessions>", "<remembered_days>",
                                   "<connections>")
                    _before = len(historical_context)
                    historical_context = [
                        m for m in historical_context
                        if not any(tag in (m.get("content") or "") for tag in _FOCUS_DROP)
                    ]
                    _dropped = _before - len(historical_context)
                    if _dropped:
                        print(f"   [FOCUS] dropped {_dropped} cross-conversation recall "
                              f"block(s) to stay on the focused material")
                if historical_context:
                    print(f"   [MEMORY] ✓ Injecting {len(historical_context)} messages (semantic + recent)")
                    messages = bt._splice_context_after_system(messages, historical_context)
        elif bt.CONVERSATION_DB_AVAILABLE and bt.should_include_history(messages):
            historical_context = bt.load_recent_context(user_name=user_name, limit=6)
            if historical_context:
                print(f"   [MEMORY] Injecting {len(historical_context)} messages from history")
                messages = bt._splice_context_after_system(messages, historical_context[-6:])

    # Explicit relative-day recall gets the referenced J-space episodes
    # pinned beside the live question. The generic J-space head only
    # carries a small recent window, and a nearby document tool result
    # previously overpowered yesterday's real York class records.
    if (robot in bt._continuity_routes.ROBOTS and last_user_msg
            and isinstance(last_user_msg, str)
            and user_name not in bt._CHAT_ONLY_USERS):
        try:
            _recall_query = bt._temporal_recall_query(last_user_msg, messages)
            _dated_recall = bt._continuity_routes.temporal_recall_block(
                robot, _recall_query)
            if _dated_recall:
                for _recall_i in range(len(messages) - 1, -1, -1):
                    _recall_m = messages[_recall_i]
                    if (_recall_m.get("role") == "user"
                            and isinstance(_recall_m.get("content"), str)):
                        messages[_recall_i] = {
                            **_recall_m,
                            "content": (
                                f"{_dated_recall}\n\n"
                                f"{_recall_m['content']}"
                            ),
                        }
                        print("   [JSPACE] Pinned dated episode recall beside live turn")
                        break
        except Exception as e:
            bt.log.warning(f"[JSPACE] dated recall injection failed: {e}")

    # Family questions and family corrections ("what do you remember
    # about our family", "the girls' ages are wrong") get the canonical
    # family facts spliced in as an authoritative <family> block, so the
    # ground truth is present rather than only caught on output.
    if (last_user_msg and isinstance(last_user_msg, str)
            and user_name not in bt._CHAT_ONLY_USERS
            and bt._FAMILY_QUERY_RE.search(last_user_msg)):
        try:
            _fam_block = bt._family_ground_truth_block()
            if _fam_block:
                print("   [FAMILY] ✓ Injecting canonical family facts")
                messages = bt._splice_context_after_system(
                    messages, [{"role": "system", "content": _fam_block}])
        except Exception as e:
            bt.log.warning(f"[FAMILY] injection failed: {e}")

    # Self-evolution questions ("how have you changed?", "has your
    # self-understanding changed since yesterday?") get the robot's
    # REAL recorded workspace revisions spliced in. Without this the
    # question is unanswerable from the prompt — the model either
    # denied changing at all or confabulated a growth story (the
    # invented Peter Singer arc, 2026-07-13).
    if (robot in bt._continuity_routes.ROBOTS and last_user_msg
            and isinstance(last_user_msg, str)
            and (bt._SELF_EVOLUTION_RE.search(last_user_msg)
                 or _self_request_kind in {
                     "evolution", "origin", "self_memory", "identity_more",
                 })):
        try:
            _sh_block = bt._continuity_routes.change_history_block(robot)
            if _sh_block:
                print("   [JSPACE] ✓ Injecting recorded self-change history")
                messages = bt._splice_context_after_system(
                    messages, [{"role": "system", "content": _sh_block}])
        except Exception as e:
            bt.log.warning(f"[JSPACE] self-history injection failed: {e}")

    # Visual memory: if the message names a person/place the camera
    # knows, splice in when they were last seen. Gated on the name
    # match itself rather than message length — "seen Stella?" is two
    # words but deserves a real answer. (Kids' chat stays visual-free.)
    if (user_name not in bt._CHAT_ONLY_USERS and last_user_msg
            and not _grounded_reply and not _self_request_kind):
        _vis_block = bt._visual_context_block(
            last_user_msg, observer=robot)
        if _vis_block:
            print(f"   [VISUAL] ✓ Injecting camera-memory context")
            messages = bt._splice_context_after_system(
                messages, [{"role": "system", "content": _vis_block}])

    # Live web research (opt-in via the chat page's toggle): ground
    # this reply in fresh search findings. Kids' chat-only pages never
    # get web content spliced in; a failed search degrades to a normal
    # answer rather than an error.
    if research_turn and user_name not in bt._CHAT_ONLY_USERS and last_user_msg:
        try:
            _rblock = bt._web_research_block(bt._research_query_from(last_user_msg))
            if _rblock:
                print(f"   [RESEARCH] ✓ Injecting {len(_rblock)} chars of live web findings")
                messages = bt._splice_context_after_system(
                    messages, [{"role": "system", "content": _rblock}])
            else:
                print(f"   [RESEARCH] search returned nothing usable — answering without")
        except Exception as e:
            bt.log.warning(f"[RESEARCH] failed: {e}")

    # Wikipedia consult (the chat page's book toggle): ground this reply
    # in the encyclopedia's own summary of the subject, in the
    # conversation's language. Same gating as web research — kids' pages
    # never get it; a miss degrades to a normal answer rather than an error.
    if wiki_turn and user_name not in bt._CHAT_ONLY_USERS and last_user_msg:
        try:
            _wblock = bt._wikipedia_block(bt._research_query_from(last_user_msg),
                                       lang=language or 'en')
            if _wblock:
                print(f"   [WIKI] ✓ Injecting {len(_wblock)} chars of Wikipedia summary")
                messages = bt._splice_context_after_system(
                    messages, [{"role": "system", "content": _wblock}])
            else:
                print(f"   [WIKI] no usable article — answering without")
        except Exception as e:
            bt.log.warning(f"[WIKI] failed: {e}")
    return messages
