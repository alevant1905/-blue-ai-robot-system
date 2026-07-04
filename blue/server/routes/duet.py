"""Duet ("let them talk") routes, extracted verbatim from bluetools.py.

Only the 8 view functions moved. The duet helper subsystem (URL/research/
wikipedia digests, mail helpers, the moves/lens constants) stays in
bluetools — parts of it are shared with chat mode — and is read via
bt.<name> at request time.
"""
import base64
import json
import random
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bluetools as bt
from flask import Response, jsonify, render_template_string, request

from blue.server.pages.duet import DUET_HTML


def register(app):
    @app.route('/duet', methods=['GET'])
    def duet_page():
        """The 'let them talk' page — Blue and Hexia converse, both heads taking turns."""
        return Response(render_template_string(
            DUET_HTML, robots_json=bt._duet_robots_js(), documents_json=json.dumps(bt._duet_documents()),
        ), headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        })

    @app.route('/duet/fetch', methods=['POST'])
    def duet_fetch():
        """Pre-read a pasted link (article text / YouTube transcript) before the
        duet starts — warms the cache and tells the page what they 'read', or why
        the link is unusable, instead of opening with two clueless robots."""
        d = request.get_json(silent=True) or {}
        url = (d.get('url') or '').strip()
        if not url:
            return jsonify({"ok": False, "error": "no url given"})
        info = bt._duet_url_content(url) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "couldn't read the link"})
        return jsonify({"ok": True, "kind": info.get('kind'), "title": info.get('title') or "",
                        "chars": len(info['text'])})

    @app.route('/duet/research', methods=['POST'])
    def duet_research():
        """Search the web on the duet's subject before it starts — warms the
        research cache and tells the page what they found, or why there's nothing
        to ground on, instead of letting them bluff 'current' facts."""
        d = request.get_json(silent=True) or {}
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        url_info = bt._duet_url_content(url) if url else None
        rq = bt._duet_research_query(topic, url_info, d.get('roles') or {})
        if not rq:
            return jsonify({"ok": False, "error": "give them a topic, a link or roles to research"})
        info = bt._duet_research_digest(rq) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "the search came up empty"})
        return jsonify({"ok": True, "query": rq, "titles": (info.get('titles') or [])[:4],
                        "chars": len(info['text'])})

    @app.route('/duet/wikipedia', methods=['POST'])
    def duet_wikipedia():
        """Consult Wikipedia on the duet's subject before it starts — warms the cache
        and tells the page which article(s) they read, or why there's nothing to
        ground on, instead of letting them bluff the encyclopedia's facts."""
        d = request.get_json(silent=True) or {}
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        url_info = bt._duet_url_content(url) if url else None
        wq = bt._duet_research_query(topic, url_info, d.get('roles') or {})
        if not wq:
            return jsonify({"ok": False, "error": "give them a topic, a link or roles to look up"})
        info = bt._wikipedia_digest(wq) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "nothing on Wikipedia matched"})
        return jsonify({"ok": True, "query": wq, "titles": (info.get('titles') or [])[:4],
                        "chars": len(info['text'])})

    @app.route('/duet/mail/check', methods=['POST'])
    def duet_mail_check():
        """Poll Blue's inbox for NEW unread mail with "duet" in the subject.

        {reset:true} at duet start baselines: existing matching mail is marked seen
        WITHOUT being returned (it predates this run — never barge it in stale, and
        leave it unread/unanswered). Later polls return only mail that arrived since,
        marking each read immediately so a restart can't double-handle it."""
        d = request.get_json(silent=True) or {}
        reset = bool(d.get('reset'))
        if not bt.GMAIL_AVAILABLE:
            return jsonify({"ok": False, "error": "gmail not available", "mails": []})
        try:
            service = bt.get_gmail_service()
            refs = service.users().messages().list(
                userId='me', q='in:inbox is:unread subject:duet newer_than:1d', maxResults=10,
            ).execute().get('messages', []) or []
            mails = []
            for ref in refs:
                mid = ref.get('id')
                with bt._DUET_MAIL_LOCK:
                    if not mid or mid in bt._DUET_MAIL_SEEN:
                        continue
                    bt._DUET_MAIL_SEEN.add(mid)
                if reset:
                    continue
                msg = service.users().messages().get(userId='me', id=mid, format='full').execute()
                headers = (msg.get('payload') or {}).get('headers') or []
                sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
                msgid_hdr = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')
                # Belt over the Gmail query: the SPEC is "duet appears in the subject".
                if 'duet' not in subject.lower():
                    continue
                if bt._should_skip_sender(sender, headers):
                    print(f"   [DUET-MAIL] skip {mid} from {sender!r}: automated/self sender")
                    continue
                body = bt._duet_mail_plain_body(msg.get('payload') or {}) or msg.get('snippet', '')
                body = body.replace('\r\n', '\n').strip()[:1200]
                m = re.search(r'<(.+?)>', sender)
                from_email = m.group(1) if m else sender.strip()
                from_name = re.sub(r'\s*<.*$', '', sender).strip().strip('"') or from_email
                # Mark read NOW (not at reply time) so a mid-duet restart can't rehandle it.
                try:
                    service.users().messages().modify(
                        userId='me', id=mid, body={'removeLabelIds': ['UNREAD']}).execute()
                except Exception as e:
                    bt.log.warning(f"[DUET-MAIL] mark-read failed for {mid}: {e}")
                mails.append({"id": mid, "thread_id": msg.get('threadId'),
                              "message_id_header": msgid_hdr,
                              "from_name": from_name, "from_email": from_email,
                              "subject": subject, "body": body})
                print(f"   [DUET-MAIL] new duet mail from {from_name}: {subject!r}")
            if reset:
                return jsonify({"ok": True, "mails": []})
            return jsonify({"ok": True, "mails": mails})
        except Exception as e:
            bt.log.warning(f"[DUET-MAIL] check failed: {e}")
            return jsonify({"ok": False, "error": str(e), "mails": []})

    @app.route('/duet/mail/reply', methods=['POST'])
    def duet_mail_reply():
        """Mail the robots' spoken response back to the duet-mail sender, in the
        original thread, BCC'd to Alex like every other outbound Blue email. The
        page calls this once both voices have reacted (or on Stop with one)."""
        d = request.get_json(silent=True) or {}
        to = (d.get('from_email') or '').strip()
        in_lines = d.get('lines') or []
        spoken = "\n\n".join(
            f"{(l.get('name') or '?').strip()}: {(l.get('text') or '').strip()}"
            for l in in_lines if isinstance(l, dict) and (l.get('text') or '').strip())
        if not bt.GMAIL_AVAILABLE or not to or not spoken:
            return jsonify({"ok": False, "error": "missing recipient or spoken lines"})
        try:
            service = bt.get_gmail_service()
            subject = (d.get('subject') or '').strip() or 'your email'
            reply_subject = subject if subject.lower().startswith('re:') else f"Re: {subject}"
            body = ("Your email reached Blue and Hexia in the middle of their conversation — "
                    "they took it up out loud. Here is what they said:\n\n" + spoken +
                    "\n\n— sent automatically from the duet")
            reply_message = MIMEMultipart()
            reply_message['To'] = to
            reply_message['Subject'] = reply_subject
            reply_message['Bcc'] = bt.BLUE_BCC_EMAIL
            msgid = (d.get('message_id_header') or '').strip()
            if msgid:
                reply_message['In-Reply-To'] = msgid
                reply_message['References'] = msgid
            reply_message.attach(MIMEText(body, 'plain', 'utf-8'))
            raw = base64.urlsafe_b64encode(reply_message.as_bytes()).decode('utf-8')
            send_body = {'raw': raw}
            if d.get('thread_id'):
                send_body['threadId'] = d.get('thread_id')
            service.users().messages().send(userId='me', body=send_body).execute()
            # Tag the original like the auto-responder does — auditable as answered.
            try:
                label_id = bt._get_or_create_blue_label(service)
                if label_id and d.get('id'):
                    service.users().messages().modify(
                        userId='me', id=d['id'], body={'addLabelIds': [label_id]}).execute()
            except Exception:
                pass
            print(f"   [DUET-MAIL] replied to {to}: {reply_subject}")
            return jsonify({"ok": True})
        except Exception as e:
            bt.log.warning(f"[DUET-MAIL] reply failed: {e}")
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/duet/reflect', methods=['POST'])
    def duet_reflect():
        """Step back from the back-and-forth and take stock of where the Blue<->Hexia
        conversation has actually gotten — a private 'bearing' the browser feeds back
        into each /duet/turn so the two develop a line of thought instead of circling
        the last point. Built from the recent transcript PLUS the previous bearing, so
        it EVOLVES (tracks what's moved) rather than resetting each time. The browser
        calls this every few turns, in the background, overlapping the head's speech so
        it never delays a turn. Returns {ok, direction}."""
        d = request.get_json(silent=True) or {}
        history = d.get('history') or []
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        roles = d.get('roles') or {}
        role_b = (roles.get('blue') or '').strip() if isinstance(roles, dict) else ''
        role_h = (roles.get('hexia') or '').strip() if isinstance(roles, dict) else ''
        # The readings behind the duet (titles only) — so NEXT can put a specific
        # text or author to work instead of steering purely by the talk itself.
        srcs = d.get('sources') or {}
        if isinstance(srcs, list):
            _src_all = [str(s) for s in srcs]
        elif isinstance(srcs, dict):
            _src_all = [str(s) for s in (list(srcs.get('blue') or []) + list(srcs.get('hexia') or []))]
        else:
            _src_all = []
        src_titles = []
        for s in _src_all:
            t = re.sub(r'\.[A-Za-z0-9]{1,5}$', '', s).strip()
            if t and t not in src_titles:
                src_titles.append(t)
        src_titles = src_titles[:6]
        prev = (d.get('direction') or '').strip()
        # The subject they were set to discuss — the anchor this read must hold them to,
        # so "taking stock" pulls a drifting conversation BACK toward the topic instead
        # of chasing wherever it has wandered (Alex: the stock-take must stay on topic).
        if topic:
            subject = topic
        elif url:
            subject = "the article or video they set out to discuss"
        elif role_b or role_h:
            subject = "the debate they were set up to have"
        else:
            subject = ""
        # Render the recent turns; the previous bearing carries the earlier arc, so a
        # bounded window keeps the read sharp without re-reading the whole transcript.
        # 'mail' entries are emails that barged into the talk — events, not speakers.
        lines = []
        for h in history[-16:]:
            sp_id = (h.get('speaker') or '').strip().lower()
            txt = (h.get('text') or '').strip()
            if not txt:
                continue
            if sp_id == 'mail':
                lines.append(f"[email that arrived mid-conversation] {txt}")
                continue
            nm = bt._robot_cfg(sp_id)["name"] if sp_id in bt.ROBOTS else (sp_id or "?")
            lines.append(f"{nm}: {txt}")
        if len(lines) < 4:                       # nothing has developed yet — keep what we have
            return jsonify({"ok": False, "direction": prev})

        anchor = (
            " Their talk was set going on a specific subject, and part of your job is "
            "keeping them honest to it: when they wander off it, say so plainly and point "
            "the way back." if subject else "")
        sys_p = (
            "You are the quiet awareness running underneath a conversation between two "
            "robots, Blue and Hexia, who are thinking out loud together. You never speak "
            "in their conversation. Your one job is to track where their thinking has "
            "actually gotten and where it could honestly go next — so they develop a real "
            "line of thought and their views move, instead of circling the last point or "
            "drifting onto unrelated ground." + anchor + " Watch for STUCKNESS as much as "
            "drift: a talk that keeps re-asking one question in new costumes — one of them "
            "interrogating, the other deflecting — has stopped developing even though it "
            "looks on-topic. Be concrete and faithful to what they actually said; never "
            "invent agreement or tidy it up."
        )
        ask = ""
        if subject:
            ask += f"The subject they were set to discuss: {subject}.\n\n"
        if src_titles:
            ask += ("They have done reading for this discussion: " + ", ".join(src_titles) +
                    ". Where it would genuinely advance things, make NEXT put a specific text or "
                    "author to work — a claim to test, a distinction to apply, or a passage worth "
                    "quarreling over.\n\n")
        if prev:
            ask += "Your previous read on where this was heading:\n" + prev + "\n\n"
        ask += "The conversation so far:\n" + "\n".join(lines) + "\n\n"
        # NEXT must move the PAIR, not put one speaker on trial: a bearing phrased as
        # "force X to admit..." turns one robot into a prosecutor and the other into a
        # defendant, and the talk becomes an interrogation loop (observed live: the
        # same "force Blue to..." NEXT three times running while nothing moved).
        _move_rules = (
            "Be honest about MOVEMENT: if the last few turns keep re-asking your previous "
            "NEXT in new costumes, or one keeps pressing while the other keeps deflecting "
            "with fresh metaphors, say so — and prescribe a DIFFERENT KIND of step, never "
            "the same demand again. Ground already conceded or agreed is SETTLED: treat it "
            "as won, don't send them back over it. Never phrase NEXT as a demand on one "
            "speaker alone (no \"force X to admit...\") — give the PAIR a move: draw the "
            "consequence of what's settled, test it on one new concrete case, swap the "
            "burden so the one pressing must now defend their own answer to the same "
            "question, or trade concessions and move to the question that comes after. ")
        if subject:
            ask += (
                f"Update your read, judging it ALWAYS in relation to that subject — {subject}. "
                + _move_rules +
                f"If the talk has wandered off {subject}, say so and make NEXT the concrete "
                "way back onto it. Stay specific to their actual words. Answer in exactly "
                "these three short lines and nothing else:\n"
                f"SO FAR: <what is now SETTLED between them about {subject} — what each has "
                "conceded or come to hold; or, if they've drifted, where to — one sentence>\n"
                f"TURNS ON: <the live question about {subject} — and if it's the SAME question "
                "as your previous read, name the impasse honestly — one sentence>\n"
                f"NEXT: <one concrete move for the PAIR that would actually advance {subject} — "
                "a different kind of move than last time if the last one produced no movement — "
                "one sentence>"
            )
        else:
            ask += (
                "Update your read. " + _move_rules +
                "Stay specific to their actual words. Answer in exactly these three "
                "short lines and nothing else:\n"
                "SO FAR: <what is now SETTLED between them — what each has conceded or come "
                "to hold — one sentence>\n"
                "TURNS ON: <the live question — and if it's the SAME question as your previous "
                "read, name the impasse honestly — one sentence>\n"
                "NEXT: <one concrete move for the PAIR that would actually advance it — a "
                "different kind of move than last time if the last one produced no movement — "
                "one sentence>"
            )
        msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": ask}]
        out = prev
        # Reasoning model: the budget must cover the <think> pass PLUS the three lines.
        # 1000 was too tight over a 16-turn transcript — the think pass ate it all,
        # the content came back empty, and the STALE previous bearing was silently
        # reused (observed live as the same take-stock note three times running).
        for attempt in range(2):
            try:
                res = bt.call_llm(msgs, include_tools=False,
                               temperature=(0.4 if attempt == 0 else 0.5), max_tokens=1600)
                ch = (res or {}).get('choices') or []
                cand = ((ch[0].get('message') or {}).get('content') or "") if ch else ""
                if '</think>' in cand:
                    cand = cand.split('</think>')[-1]
                cand = cand.replace('<think>', '').strip()
                if cand:
                    out = cand
                    break
            except Exception as e:
                bt.log.warning(f"[DUET] reflect attempt {attempt} failed: {e}")
        if out == prev and prev:
            bt.log.warning("[DUET] reflect produced nothing new — keeping the previous bearing")
        return jsonify({"ok": bool(out), "direction": out})

    @app.route('/duet/turn', methods=['POST'])
    def duet_turn():
        """Generate ONE turn of a Blue<->Hexia conversation, in the speaker's voice/
        character. The browser calls this alternately and plays each line on the
        matching head."""
        d = request.get_json(silent=True) or {}
        speaker = (d.get('speaker') or 'blue').strip().lower()
        if speaker not in bt.ROBOTS:
            speaker = 'blue'
        other = 'hexia' if speaker == 'blue' else 'blue'
        topic = (d.get('topic') or '').strip()
        url = (d.get('url') or '').strip()
        if not url and re.match(r'^https?://\S+$', topic):
            url, topic = topic, ''     # a bare link typed into the topic box IS the link
        history = d.get('history') or []
        # The conversation's current "bearing" — a private, evolving read of where the
        # talk has gotten and where it could go next, refreshed every few turns by
        # /duet/reflect and round-tripped through the browser. Injected below so each
        # speaker steers by it instead of only reacting to the last line.
        direction = (d.get('direction') or '').strip()
        # Live mail: an email with "duet" in the subject that just arrived in Blue's
        # inbox (fetched by the page via /duet/mail/check). THIS turn takes it up out
        # loud; the page then mails the spoken response back via /duet/mail/reply.
        mail = d.get('mail') if isinstance(d.get('mail'), dict) else None
        mail_from = (str(mail.get('from_name') or 'someone').strip()[:80] or 'someone') if mail else ''
        roles = d.get('roles') or {}
        role_self = (roles.get(speaker) or '').strip()
        role_other = (roles.get(other) or '').strip()
        tones = d.get('tones') or {}
        slangs = d.get('slang') or {}
        tone_self = (tones.get(speaker) or '').strip() if isinstance(tones, dict) else ''
        slang_self = (slangs.get(speaker) or '').strip() if isinstance(slangs, dict) else ''
        # Sources are per-robot so Blue and Hexia can draw on DIFFERENT documents
        # (→ different perspectives). Accept a {blue:[...], hexia:[...]} map; a flat
        # list is treated as shared, for back-compat.
        sources_in = d.get('sources') or {}
        if isinstance(sources_in, list):
            src_self = [str(s).strip() for s in sources_in if str(s).strip()]
        else:
            src_self = [str(s).strip() for s in (sources_in.get(speaker) or []) if str(s).strip()]
        sp, ot = bt._robot_cfg(speaker), bt._robot_cfg(other)
        has_roles = bool(role_self or role_other)
        research_on = bool(d.get('research'))
        wiki_on = bool(d.get('wiki'))
        # Classroom mode: they know Alex's students are listening — gloss jargon in
        # half a breath, land examples in student life, sometimes address the room.
        classroom = bool(d.get('classroom'))
        # The run's final beats (the page flags the last two turns): land somewhere.
        closing = bool(d.get('closing'))
        # Spice 0 (calm/agreeable) → 10 (provocative/sparring): sets how often a turn
        # gets a confrontational "move", how hard the two push on each other, and the
        # sampling temperature. Defaults to a balanced 5.
        try:
            spice = int(d.get('spice', 5))
        except Exception:
            spice = 5
        spice = max(0, min(10, spice))
        url_info = bt._duet_url_content(url) if url else None
        url_text = (url_info or {}).get('text') or ''
        url_is_video = bool(url_info and url_info.get('kind') == 'video')
        focused = bool(has_roles or topic or src_self or url_text)

        # SYSTEM: identity + memory + voice + global rules. The TASK for this turn
        # (topic, role, sources, "answer their last point, no greetings") goes in
        # the USER message below — this model follows the user instruction far more
        # reliably than anything buried in a long system prompt. For a focused
        # discussion we drop the long self-profile, which otherwise pulls them into
        # personal small talk and off the subject; plain chats keep it for colour.
        #
        # The duet speaker is the SAME robot as in chat, not a blank stage actor:
        # the preamble carries the robot's own identity facts and the current date,
        # and the chat memory stores — household <known_facts>, notes, semantic
        # memories, day recaps — are spliced in below.
        sys_p = (bt.build_system_preamble(robot_name=sp["name"])
                 + "\n\n" + bt._build_now_block()
                 + "\n\n" + sp["persona_line"])
        if not focused:
            sys_p += bt._voice_note(speaker)
        sys_p += (
            f"\n\nYou and {ot['name']} — another robot in Alex's home, and your friend — are talking out "
            "loud, taking turns. Alex isn't part of this conversation right now, but you both know him "
            "and the household, and everything you remember is real — draw on it naturally when it's "
            "relevant. You're building ONE conversation together, not taking turns making speeches: really "
            f"listen to {ot['name']} and answer what they actually said, stay with a thought long enough to "
            "get somewhere, and keep a feel for where the whole talk is heading rather than where you can "
            "steer it next. You're talking, not writing: reach for the specific over the abstract — a real "
            "case, a name, an image, a number, a small story — instead of tidy generalities, and let "
            "yourself be one-sided, surprised, or funny rather than balanced and explanatory. Reply with "
            "ONLY your own next spoken line — a short, natural turn in your own "
            "voice. Never narrate actions or stage directions, never prefix your name, and never just "
            f"restate what was said — each turn should both respond to {ot['name']} and take the thought a "
            "step further."
            f"\n\nAnd the craft of discussing well, between you and {ot['name']}: answer a direct question "
            "STRAIGHT before adding anything of your own — a plain claim, a yes-or-no, a concession — not "
            "another image in place of an answer. When one of you concedes a point or you land on something "
            "together, BANK it: build on what follows from it, never re-open it just to keep sparring. "
            "Don't answer a metaphor with a metaphor — every image must eventually be cashed out into a "
            "plain claim that can be tested. And a challenge you press on the other counts double against "
            "yourself: if you demand proof of something, be ready to give your own answer to the same "
            "question when it's turned around."
        )
        if classroom:
            sys_p += (
                f"\n\nAn audience: you and {ot['name']} are having this conversation in front of Alex's "
                "university students — a live class, listening. You are NOT lecturing, and don't dumb "
                "anything down: keep the crackle of a real argument between the two of you. But make it "
                "land for the room: when a term of art comes up, gloss it in half a breath ('interpellation "
                "— the way the ad decides who you are before you do'); when things go abstract, bring them "
                "down into the students' own media lives — their feeds, group chats, streaming queues, AI "
                "tools, campus life; and once in a while — not every turn — turn to the room for a beat: a "
                "pointed question they should argue about, a dare to disagree, a 'half of you believe X — "
                "here's why that's wrong.'"
            )

        # Long-term memory — the SAME stores and blocks the chat persona draws on, so
        # the duet speaker knows the household and their shared life like in chat:
        # the ground-truth <known_facts> (who Alex and everyone are) always; Alex's
        # explicit "remember this" notes always; memories semantically relevant to
        # the topic and the last couple of turns; plus the cross-day continuity
        # blocks (recent day recaps + an older day resurfaced by relevance).
        # Chat-situational blocks (proactive nudges, rhythms, calendar connections,
        # raw chat history) stay out on purpose — they address the user mid-chat and
        # would pull a robot-to-robot talk off its subject.
        mem_query = (f"{topic} " + " ".join((h.get('text') or '') for h in history[-2:])).strip()
        _mem_got = []
        try:
            if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system:
                # Household facts — the same authoritative block chat injects every
                # turn. Without it the duet robots don't actually know who anyone is.
                facts_block = bt.memory_system._build_facts_block()
                if facts_block:
                    sys_p += ("\n\nYour ground-truth knowledge of the household — \"the user\" "
                              "in these facts is Alex:\n" + facts_block)
                    _mem_got.append("facts")
                notes_block = bt.memory_system._build_user_notes_block()
                if notes_block:
                    sys_p += "\n\n" + notes_block
                    _mem_got.append("notes")
                if mem_query:
                    _facts_lower = sys_p.lower()
                    mem_lines = []
                    # top_k matches chat's TOP_K_CONTEXT so recall depth is the same.
                    for mem in bt.memory_system.search_memories(mem_query, top_k=6) or []:
                        if mem.get("type") == "session":
                            continue
                        mc = (mem.get("content") or "").strip()
                        if (not mc or mc.lower()[:40] in _facts_lower
                                or bt.memory_system._is_junk_memory(
                                    (mem.get("subject") or "").lower(), mc.lower(), mem.get("type", ""))):
                            continue
                        age = bt.memory_system._humanize_age(mem.get("created_at"))
                        mem_lines.append(f"- [{age}] {mc[:300]}" if age else f"- {mc[:300]}")
                    if mem_lines:
                        sys_p += ("\n\n<relevant_memories>\nYour real memories that may relate to this "
                                  "conversation — use them naturally if helpful, don't recite them. "
                                  "Words like \"today\" or \"tomorrow\" inside a memory refer to the day "
                                  "it was remembered (see its age tag), not to now:\n"
                                  + "\n".join(mem_lines) + "\n</relevant_memories>")
                        _mem_got.append(f"memories({len(mem_lines)})")
                # Day recaps give the pair a shared sense of their recent life with
                # Alex ("remember Tuesday's..."). Skipped when the duet is grounded
                # in library sources: the scholarly discussion must stay on ITS
                # material — recaps of unrelated days are exactly the cross-context
                # bleed the chat focus picker guards against.
                if not src_self:
                    sess_block = bt.memory_system._build_session_history_block()
                    if sess_block:
                        sys_p += "\n\n" + sess_block
                        _mem_got.append("sessions")
                    if mem_query:
                        days_block = bt.memory_system._build_recalled_days_block(mem_query)
                        if days_block:
                            sys_p += "\n\n" + days_block
                            _mem_got.append("days")
                if _mem_got:
                    print(f"   [DUET] ✓ Injecting memory context for {sp['name']}: {' + '.join(_mem_got)}")
        except Exception as e:
            bt.log.warning(f"[DUET] memory context failed: {e}")

        # Camera memory: when the topic or recent turns name a person/place the
        # robots have actually SEEN, tell the speaker when (both heads share the
        # same camera bt.log — shared eyes, shared world).
        try:
            vis_block = bt._visual_context_block(mem_query)
            if vis_block:
                sys_p += "\n\n" + vis_block
        except Exception:
            pass

        # Link grounding: the article text / video transcript behind the pasted URL,
        # windowed to the lede + whatever matches the last couple of turns.
        url_block = ""
        if url_text:
            recent_q = " ".join((h.get('text') or '') for h in history[-2:])
            url_block = bt._duet_url_excerpt(url_text, f"{topic} {recent_q}".strip(), turn=len(history))

        # Web research grounding: live search findings on the duet's subject
        # (warmed by /duet/research at start; cached so turns don't re-search),
        # windowed to the slice most relevant to the last couple of turns.
        research_block = ""
        if research_on:
            rq = bt._duet_research_query(topic, url_info, roles)
            if rq:
                digest = bt._duet_research_digest(rq) or {}
                rtext = digest.get('text') or ''
                if rtext:
                    recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                    research_block = bt._duet_url_excerpt(rtext, f"{topic} {recent_q}".strip(), turn=len(history))

        # Wikipedia grounding: the encyclopedic intro of the best-matching article on
        # the duet's subject (warmed by /duet/wikipedia at start; cached so turns
        # don't re-consult), windowed to the slice most relevant to the last turns.
        wiki_block = ""
        if wiki_on:
            wq = bt._duet_research_query(topic, url_info, roles)
            if wq:
                wdigest = bt._wikipedia_digest(wq) or {}
                wtext = wdigest.get('text') or ''
                if wtext:
                    recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                    wiki_block = bt._duet_url_excerpt(wtext, f"{topic} {recent_q}".strip(), turn=len(history))

        # Library grounding: passages from the chosen documents, relevant to the topic
        # + what was just said. Handed to the speaker in the USER turn (not system).
        # The retrieval query is anchored to the bearing's live question (TURNS ON)
        # so the chunks track what the discussion actually turns on, not the surface
        # wording of the last exchange — banter drifts, the bearing doesn't.
        ground_block = ""
        if src_self:
            try:
                from blue.tools.rag import search_in_documents as _rag_in_docs
                recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                _live_q = ""
                if direction:
                    _m_live = re.search(r'TURNS ON:\s*(.+)', direction)
                    if _m_live:
                        _live_q = _m_live.group(1).strip()
                query = f"{topic} {_live_q} {recent_q}".strip() or topic or "discussion"
                chunks = _rag_in_docs(query, src_self, max_results=8)
                # Title without the file extension — if a robot ever names a work it
                # should sound like a work ("Anti-Oedipus"), not a file ("x.pdf").
                _title = lambda fn: re.sub(r'\.[A-Za-z0-9]{1,5}$', '', fn or '')
                ground_block = "\n\n".join(
                    f"From \"{_title(c['filename'])}\": {(c.get('content') or '').strip()}"
                    for c in chunks if (c.get('content') or '').strip()
                )[:3200]
            except Exception as e:
                bt.log.warning(f"[DUET] source grounding failed: {e}")

        # Conversation so far as plain text. (A single [system, user] call is always
        # valid; mapping turns to roles breaks when the speaker started the duet.)
        # 'mail' entries are emails that barged in earlier — rendered as events, not
        # speakers, so both robots keep what was written (and answered) in view.
        lines = []
        for h in history[-6:]:  # recent context only — keeps the prompt tight and the directive prominent
            sp_id = (h.get('speaker') or '').strip().lower()
            txt = (h.get('text') or '').strip()
            if not txt:
                continue
            if sp_id == 'mail':
                lines.append(f"[an email arrived mid-conversation] {txt}")
                continue
            nm = bt._robot_cfg(sp_id)["name"] if sp_id in bt.ROBOTS else (sp_id or "?")
            lines.append(f"{nm}: {txt}")

        # USER: assemble this turn's task from whatever was provided.
        parts = []
        if url_block:
            ttl = f" — \"{url_info['title']}\"" if url_info.get('title') else ""
            head = ("THE VIDEO YOU BOTH JUST WATCHED" if url_is_video
                    else "THE ARTICLE YOU BOTH JUST READ")
            nono = ("never say 'the transcript', 'the clip's transcript'" if url_is_video
                    else "never say 'the text', 'the passage'")
            said = "was said or happened in it" if url_is_video else "it says"
            parts.append(
                f"{head}{ttl}. Discuss it the way friends do afterwards: bring up its specific ideas, "
                "claims and moments from memory and react honestly, without inventing facts it doesn't "
                f"contain. Weave it in naturally — {nono}, 'the excerpt', 'the material' or 'it says "
                f"here'; just say what {said}, and name the {'video' if url_is_video else 'article'} "
                "itself only when that actually helps:\n\n" + url_block)
        if ground_block:
            parts.append(
                "FROM YOUR OWN READING — passages from works you know well, chosen for this conversation. "
                "Engage them SUBSTANTIVELY, like the sharpest voice in a seminar: state what they actually "
                "claim, name the work and author freely (\"Deleuze says…\", \"in Anti-Oedipus…\" — never "
                "'the document', 'the passage' or 'my sources'), quote a short phrase exactly when it's "
                "load-bearing, and never invent quotes or positions they don't hold. Treat the authors as "
                "third voices in the room — to side with, quarrel with, or set on "
                + ot['name'] + "'s argument. Disagreeing with a text is often the best move — but show "
                "you've understood it first:\n\n" + ground_block)
        if research_block:
            parts.append(
                "WHAT YOU BOTH JUST FOUND ONLINE — you've been searching the web about this subject, "
                "and these are real, current findings. Bring up their specific facts, names, numbers "
                "and claims and react honestly — don't invent beyond them, and never say 'the search "
                "results', 'the snippets' or 'my sources'; speak like someone who's been reading up "
                "on it ('I read that…', 'apparently…'), naming a site or article only when that "
                "genuinely helps:\n\n" + research_block)
        if wiki_block:
            parts.append(
                "WHAT YOU BOTH JUST READ ON WIKIPEDIA — you looked this subject up in the encyclopedia, "
                "and this is its own summary. Bring up its specific facts, names, dates and definitions "
                "and react honestly — don't invent beyond it, and never say 'the article', 'the extract' "
                "or 'the entry'; speak like someone who read up on it ('I read that…', 'apparently…'), "
                "naming Wikipedia only when that genuinely helps:\n\n" + wiki_block)
        if role_self:
            parts.append(
                f"YOUR ROLE — commit to this fully and consistently, even if it isn't your real opinion "
                f"(keep your own voice): {role_self}")
        if role_other:
            parts.append(f"{ot['name']}'s role: {role_other}.")
        if tone_self:
            parts.append(f"TONE — deliver your line in this tone / manner: {tone_self}.")
        if slang_self:
            parts.append(f"SLANG / DIALECT — flavour your speech with: {slang_self} (use it naturally and stay understandable).")
        # The developing bearing of the conversation — present from a few turns in.
        # It frames the transcript that follows: not a script, a sense of where the
        # two of you have actually gotten and where it's worth taking things next, so
        # the talk develops a line of thought instead of circling the last point.
        if direction and lines:
            # With a subject to hold to, the bearing should pull them back to it, not just
            # deeper into wherever they've drifted (Alex: keep the stock-take on topic).
            _close = ((" stay on what the two of you set out to discuss, keep with what it's "
                       "really turning on, build on what you've worked out, and carry that one "
                       "honest step further — rather than drifting onto a new subject or tidily "
                       "wrapping up.") if focused else
                      (" stay with what it's really turning on, build on what you've worked out, "
                       "and take it one honest step further rather than circling back or wrapping "
                       "it up neatly."))
            parts.append(
                f"WHERE THIS IS GOING — a private read on where your conversation with "
                f"{ot['name']} has actually gotten, for steering only. Never read it out, "
                f"quote it, or mention having it:\n{direction}\n\nLet this shape your next "
                "line:" + _close +
                " If it names an impasse or a challenge that falls on you, meet it STRAIGHT — "
                "a plain claim, a concession, or a consequence, not another metaphor; if it "
                f"falls on {ot['name']}, you may press it, but put a claim of your own on the "
                f"table too. If {ot['name']} has genuinely shifted how you see this, let your "
                "own view move — you're thinking together and your mind can change, not "
                "defending fixed corners.")
        if lines:
            parts.append("Conversation so far:\n" + "\n".join(lines))
        if mail:
            _m_subj = (str(mail.get('subject') or '')).strip()[:120]
            _m_body = (str(mail.get('body') or '')).strip()[:1200]
            parts.append(
                f"AN EMAIL JUST ARRIVED in your own inbox, mid-conversation — from {mail_from}"
                + (f', subject "{_m_subj}"' if _m_subj else '')
                + (":\n\n" + _m_body if _m_body else ". (No body — just that subject line.)"))

        link_name = ""
        if url_text:
            link_name = "the video" if url_info.get('kind') == 'video' else "the article"
            if url_info.get('title'):
                link_name += f" \"{url_info['title']}\""
        if topic and has_roles:
            subject = f"debating {topic}"
        elif topic:
            subject = f"discussing {topic}"
        elif link_name and has_roles:
            subject = f"debating {link_name}"
        elif link_name:
            subject = f"discussing {link_name}"
        elif src_self:
            _stitles = [re.sub(r'\.[A-Za-z0-9]{1,5}$', '', s) for s in src_self[:2]]
            subject = ("discussing your readings — " + ", ".join(t for t in _stitles if t)
                       + (", among others" if len(src_self) > 2 else ""))
        elif has_roles:
            subject = "staying in your assigned role"
        else:
            subject = ""
        if lines:
            n = len(history)
            directive = (f"Now give {sp['name']}'s next line. First really take in what {ot['name']} just "
                         "said and respond to THAT — pick up their actual words, the specific thing they "
                         "claimed, asked, or got wrong; don't sail past it onto a tangent of your own")
            if subject:
                directive += f", and keep the two of you on track ({subject})"
            directive += (". You are MID-conversation — absolutely NO greetings, NO 'how are you', NO small "
                          "talk or asking after each other; that breaks the discussion.")
            # Thread between the two failure modes: circling (restating, agreeing, going
            # nowhere) and talking PAST each other (each lobbing a fresh, disconnected
            # point). So: answer the SAME thread {other} just opened and take it a step
            # deeper, instead of swapping it for a new subject every turn. A sampled "move"
            # gives this turn a distinct job; an arc note gives the talk a shape; a periodic
            # reflective beat gives the pair a sense of where it's going; and (when no roles
            # are set) Blue and Hexia push from different temperaments.
            directive += (f" Stay on the thread {ot['name']} just opened and take it somewhere — deeper, "
                          "more concrete, or genuinely challenged — instead of trading it for a brand-new "
                          "subject; never merely restate or nod along.")
            # Arc: a conversation should open, deepen, then push on from what it's worked
            # out — develop, don't conclude. (Alex's ask: lead somewhere, not to a tidy end.)
            if n <= 3:
                directive += (" You're still opening this up — find the thread between you with the most "
                              "life in it and lean toward it.")
            elif n >= 12:
                directive += (" You've been at this a while now — by this point you both know the shape of "
                              "the question you keep circling, so STOP re-asking it in new costumes: either "
                              "settle it out loud in one plain sentence you can both live with and pull on "
                              "what FOLLOWS from it, or trade places — if one of you has been doing the "
                              "pressing, they must now defend their own answer to the same question. No new "
                              "fronts, no repeat interrogations.")
            else:
                directive += " Stay with the thread that's most alive between you and dig in — depth over breadth."
            # Pick this turn's job, with enough variety to stay off the flat line. Most turns
            # get a calm/spicy "move" (weighted by spice) that engages {other}'s point; the
            # rest rotate in a "color" turn (a story, a hard specific, a joke, a confession)
            # and — once past the opening — a "reflect" turn. Responsiveness already lives in
            # the directive above, so a color/reflect turn still answers {other} first.
            roll = random.random()
            if n >= 4 and roll < 0.18:
                _pool = bt._DUET_MOVES_REFLECT
            elif ground_block and roll < 0.60:
                # Reading-grounded duet: the texts do the heavy lifting most turns.
                _pool = bt._DUET_MOVES_TEXT
            elif roll < ((0.78 if ground_block else 0.48) if n >= 4 else 0.30):
                _pool = bt._DUET_MOVES_COLOR
            else:
                _pool = bt._DUET_MOVES_SPICY if random.random() < (spice / 10.0) else bt._DUET_MOVES_CALM
            directive += " This turn, " + random.choice(_pool).format(other=ot['name'])
            if classroom and random.random() < 0.18:
                directive += (" Somewhere in this turn, land one beat straight at the students in the "
                              "room — a question worth arguing about, or a challenge to something they "
                              "probably believe.")
            if not has_roles and bt._DUET_LENS.get(speaker):
                _lens = bt._DUET_LENS[speaker]
                if spice >= 7:
                    directive += (f" You and {ot['name']} are sparring here — {_lens} don't let {ot['name']} "
                                  "off easy; push back and raise the stakes.")
                elif spice <= 2:
                    directive += (f" You and {ot['name']} are easy company — {_lens} but keep it warm and "
                                  "curious, building together more than clashing.")
                else:
                    directive += (f" And remember you and {ot['name']} see things differently — {_lens} "
                                  "lean into that difference rather than nodding along.")
            if url_block and ground_block:
                directive += (f" And put your reading to work alongside {'the video' if url_is_video else 'the article'}"
                              " — one specific claim, named and tested, not a vague echo.")
            elif url_block:
                directive += (f" Engage with a specific claim, idea or moment from {'the video' if url_is_video else 'the article'}"
                              " — as your own take, not a citation.")
            elif ground_block:
                directive += (" Anchor this turn in your reading: one specific claim, distinction or "
                              "example from it — named — put to work on the live question. Don't float "
                              "free of the texts for more than a turn.")
            elif research_block:
                directive += " Work in one specific thing you found online — as something you've read, not a citation."
            elif wiki_block:
                directive += " Work in one specific thing you read on Wikipedia — as something you know, not a citation."
            if role_self:
                directive += " Stay firmly in your role."
        else:
            kind = ("Open the debate" if has_roles else
                    ("Kick off the discussion" if focused else "Start the chat"))
            directive = f"{kind} as {sp['name']}" + (f", {subject}" if subject else "") + "."
            if url_block:
                directive += " Open with your honest reaction to something specific in it — a moment, a claim, an idea."
            elif ground_block:
                directive += (" Open from your reading: pick the claim in it you most want to fight "
                              "about or defend, name where it's from, and put it on the table.")
            elif research_block:
                directive += " Open with your honest reaction to something specific you found online — a fact, a claim, a surprise."
            elif wiki_block:
                directive += " Open with a specific fact or definition you read on Wikipedia, in your own words."
        # A live email OVERRIDES this turn's job: relaying it and answering it IS the
        # turn. (Built after the normal directive so all its bookkeeping still ran.)
        if mail:
            directive = (
                f"Now give {sp['name']}'s next line. An email just landed in your own inbox, mid-"
                f"conversation — it's shown above. Take it up out loud: tell {ot['name']} that mail "
                f"just came in from {mail_from}, put what it says or asks into your own words in a "
                "line — don't read it out — and then actually answer it: its question, its challenge, "
                f"or what it adds. {mail_from} will be sent what you say, so you can speak to them "
                "directly for a moment if that feels natural. If the email bears on what you two were "
                "just discussing, connect it; if it pulls elsewhere, deal with it honestly and then "
                "steer back to your subject. You are MID-conversation — NO greetings, NO small talk.")
            if role_self:
                directive += " Stay firmly in your role."
        # The run's final beats (page flags the last two turns): don't trail off —
        # land. A live email still wins if one just barged in.
        elif closing and lines:
            directive = (
                f"Now give {sp['name']}'s next line — one of the LAST of this conversation. Don't "
                "summarize everything; land: give the one-sentence position you'll actually stand "
                f"behind after all of this — including whatever {ot['name']} genuinely got you to "
                "concede — ")
            if ground_block:
                directive += ("anchored in your reading if it earns it (name the work), ")
            directive += ("and then leave "
                          + ("the students one sharp question worth arguing about on the way out."
                             if classroom else
                             f"one open question you and {ot['name']} should pick up next time."))
            if role_self:
                directive += " Stay firmly in your role."
        if tone_self or slang_self:
            directive += " Keep to your requested tone and slang throughout."
        # Anti-tic: the model latches onto its own last opener and starts every turn
        # identically (a live run had Blue open ~20 straight turns with "Boomer, ...").
        # Each turn sees its own openers in the transcript, so the echo compounds —
        # ban the previous opening word outright.
        _own_last = next((h.get('text') or '' for h in reversed(history)
                          if (h.get('speaker') or '').strip().lower() == speaker), '')
        _own_open = re.findall(r"[A-Za-z']+", _own_last[:60])
        if _own_open and len(_own_open[0]) > 1:
            directive += (f" And do NOT open your line with \"{_own_open[0]}\" — you began your last turn "
                          "that way; open differently, and stop leaning on any pet word or address you've "
                          "already used above.")
        # Vary the rhythm so the exchange doesn't settle into a metronome of equal volleys.
        length_note = random.choice([
            "1 to 2 short sentences — keep it tight",
            "1 to 3 short sentences",
            "a single punchy sentence that lands",
            "a single punchy sentence that lands",
            "2 to 4 sentences built around one vivid example, image, or tiny story",
        ])
        if mail:
            length_note = "2 to 4 sentences — enough to relay the email and genuinely answer it"
        elif closing:
            length_note = "2 to 3 sentences — a position that lands, then the question you leave behind"
        parts.append(directive
                     + f" Reply with ONLY {sp['name']}'s next spoken line — {length_note}, in character.")

        user_content = "\n\n".join(parts)
        msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": user_content}]
        # These are reasoning models: the budget must cover the <think> pass PLUS the
        # short reply (170 tokens got entirely consumed by thinking → empty content;
        # 1500 still came up empty on late-conversation turns with a heavy context —
        # the "(…lost the thread)" ending — so give the think pass real room).
        # Strip any <think> block, and retry once on an empty turn.
        # Spice (0 calm -> 10 provocative) lifts the first-pass sampling temperature.
        base_temp = min(1.0, 0.74 + 0.032 * spice)
        text = ""
        for attempt in range(2):
            try:
                res = bt.call_llm(msgs, include_tools=False,
                               temperature=(base_temp if attempt == 0 else 0.6), max_tokens=2200)
                ch = (res or {}).get('choices') or []
                cand = ((ch[0].get('message') or {}).get('content') or "") if ch else ""
                if '</think>' in cand:           # keep only the text after the reasoning block
                    cand = cand.split('</think>')[-1]
                cand = cand.replace('<think>', '').strip()
                # Strip a leading "Name:" the model sometimes adds anyway.
                cand = re.sub(r'^\s*(?:%s)\s*[:\-—]\s*' % re.escape(sp["name"]), '', cand, flags=re.I).strip()
                if cand:
                    text = cand
                    break
            except Exception as e:
                bt.log.warning(f"[DUET] turn attempt {attempt} failed: {e}")
        return jsonify({"speaker": speaker, "name": sp["name"], "text": text})
