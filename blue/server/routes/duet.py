"""Duet ("let them talk") routes, extracted verbatim from bluetools.py.

Only the 8 view functions moved. The duet helper subsystem (URL/research/
wikipedia digests, mail helpers, the moves/lens constants) stays in
bluetools — parts of it are shared with chat mode — and is read via
bt.<name> at request time.
"""
import base64
import json
import os
import random
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bluetools as bt
from flask import Response, jsonify, render_template_string, request

from blue.server.pages.duet import DUET_HTML


_DUET_FAMILY_REF_RE = re.compile(
    r"\b("
    r"Alex'?s\s+(?:family|wife|husband|spouse|partner|kids?|children|daughters?|sons?|household|home)"
    r"|(?:his|your|our)\s+(?:family|wife|husband|spouse|partner|kids?|children|daughters?|sons?)"
    r"|(?:the\s+household|the\s+kids?|the\s+children|the\s+daughters?|the\s+sons?)"
    r"|Vilda|Stella|Felix|Svetlana"
    r")\b",
    re.I,
)


def _duet_family_ref(text: str) -> bool:
    return bool(text and _DUET_FAMILY_REF_RE.search(text))


def _duet_persona_line(robot_id: str, no_family: bool) -> str:
    """Persona wording for duet turns, with an optional private-family filter."""
    if not no_family:
        return bt._robot_cfg(robot_id)["persona_line"]
    if robot_id == "hexia":
        return (
            "You are Hexia, Blue's friend and lively duet partner. You're bright, "
            "witty and a little mischievous: the playful spark to Blue's calm. "
            "You love wordplay, odd facts, small wonders and telling a good story, "
            "and you tease Blue fondly because you adore him. Warm-hearted "
            "underneath the sparkle. Keep responses natural and not too long."
        )
    return "You are Blue, a friendly robot interlocutor. Keep responses brief, natural and grounded."


def _duet_doc_title(filename: str) -> str:
    return re.sub(r'\.[A-Za-z0-9]{1,5}$', '', filename or '').strip()


def _duet_source_chunks(query: str, filenames, max_chunks: int = 10):
    """Return source chunks with deliberate coverage across checked documents.

    A plain scoped semantic search can let one highly similar document occupy
    every slot. In duet mode the user's checked readings are intentional, so
    give each selected document a chance to speak before filling extra space by
    global relevance.
    """
    clean = []
    for fn in filenames or []:
        fn = str(fn).strip()
        if fn and fn not in clean:
            clean.append(fn)
    if not clean:
        return []

    from blue.tools.rag import search_in_documents as _rag_in_docs

    out = []
    counts = {}
    seen = set()

    def add(hit) -> bool:
        content = (hit.get("content") or "").strip()
        fname = hit.get("filename") or ""
        if not content or not fname:
            return False
        sig = (fname, content[:120])
        if sig in seen:
            return False
        seen.add(sig)
        counts[fname] = counts.get(fname, 0) + 1
        out.append(hit)
        return True

    # First pass: one best chunk per selected document, in the user's order.
    for fn in clean:
        if len(out) >= max_chunks:
            break
        for hit in _rag_in_docs(query, [fn], max_results=2):
            if add(hit):
                break

    # Second pass: fill remaining slots by relevance, capped per document.
    if len(out) < max_chunks:
        for hit in _rag_in_docs(query, clean, max_results=max(max_chunks * 3, len(clean) * 3)):
            if len(out) >= max_chunks:
                break
            fname = hit.get("filename") or ""
            if counts.get(fname, 0) >= 2:
                continue
            add(hit)

    return out[:max_chunks]


_DUET_GROUND_STOPWORDS = {
    "about", "above", "across", "after", "again", "against", "almost", "along", "already",
    "also", "although", "always", "among", "another", "around", "because", "before", "being",
    "between", "both", "cannot", "could", "does", "doing", "down", "during", "each", "even",
    "every", "first", "from", "give", "going", "good", "have", "having", "here", "itself",
    "just", "keep", "know", "like", "line", "made", "make", "many", "might", "more", "most",
    "much", "must", "never", "only", "other", "over", "point", "really", "right", "same",
    "should", "since", "some", "something", "still", "such", "take", "than", "that", "their",
    "them", "then", "there", "these", "thing", "think", "this", "those", "through", "turn",
    "under", "very", "want", "what", "when", "where", "which", "while", "with", "without",
    "would", "your",
}


def _duet_ground_terms(chunks, limit: int = 42):
    """Distinctive words from retrieved passages, used only to catch floaty turns."""
    freq = {}
    for c in chunks or []:
        text = (c.get("content") or "").lower()
        for m in re.finditer(r"[a-z][a-z'\-]{4,}", text):
            term = m.group(0).strip("'-")
            if len(term) < 5 or term in _DUET_GROUND_STOPWORDS:
                continue
            if term.endswith("'s"):
                term = term[:-2]
            if term in _DUET_GROUND_STOPWORDS:
                continue
            freq[term] = freq.get(term, 0) + 1
    return sorted(freq, key=lambda t: (-freq[t], -len(t), t))[:limit]


def _duet_grounded_enough(text: str, terms) -> bool:
    if not terms:
        return True
    low = (text or "").lower()
    hits = [t for t in terms if re.search(r"\b" + re.escape(t) + r"\b", low)]
    return len(hits) >= 2 or any(len(t) >= 8 for t in hits)


# ---- Reading digests: the ARGUMENT of each checked document ------------------
# Scattered RAG chunks alone made the robots decorate turns with a reading's
# vocabulary while never engaging its claims (Alex, 2026-07-06: "not using the
# documents substantively enough") — you can't discuss a work you've only seen
# through ten random 800-char peepholes. So each checked document gets a one-time
# absorbed digest of what it actually ARGUES (thesis, claims, terms, examples,
# what it's against), built by the LLM from the document's real text, cached by
# file mtime (in memory + on disk, so server restarts don't re-pay the read),
# warmed at duet start by /duet/readings, and injected EVERY grounded turn as
# stable context alongside the per-turn chunks: the digest carries the argument,
# the chunks carry the specifics.
_DUET_READ_CACHE: dict = {}          # filename -> {"mtime": float, "digest": str}
_DUET_READ_LOADED = False


def _duet_read_store() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(bt.__file__)),
                        "data", "duet_reading_digests.json")


def _duet_read_load():
    global _DUET_READ_LOADED
    if _DUET_READ_LOADED:
        return
    _DUET_READ_LOADED = True
    try:
        with open(_duet_read_store(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _DUET_READ_CACHE.update(data)
    except Exception:
        pass


def _duet_read_save():
    path = _duet_read_store()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_DUET_READ_CACHE, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)      # atomic — a mid-write crash can't NUL the store
    except Exception as e:
        bt.log.warning(f"[DUET] couldn't persist reading digests: {e}")


def _duet_reading_file(filename: str) -> str:
    """Resolve a checked document's filename to a real path (index filepath
    first, DOCUMENTS_FOLDER fallback — the same order the mail attachment
    resolver uses)."""
    try:
        for doc in bt.load_document_index().get("documents", []):
            if (doc.get("filename") or "").strip() == filename:
                fp = doc.get("filepath") or ""
                if fp and os.path.exists(fp):
                    return fp
                break
    except Exception:
        pass
    alt = os.path.join(bt.DOCUMENTS_FOLDER, filename)
    return alt if os.path.exists(alt) else ""


def _duet_reading_digest(filename: str) -> str:
    """The absorbed five-line digest of one checked document (cached)."""
    path = _duet_reading_file(filename)
    if not path:
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return ""
    _duet_read_load()
    hit = _DUET_READ_CACHE.get(filename)
    if hit and hit.get("mtime") == mtime and (hit.get("digest") or "").strip():
        return hit["digest"]
    try:
        text = (bt.extract_text_from_file(path) or "").strip()
    except Exception as e:
        bt.log.warning(f"[DUET] digest extraction failed for {filename}: {e}")
        return ""
    if not text or text.lower().startswith("error"):
        return ""
    if len(text) > 18000:
        # Lede-weighted window: theses live up front, conclusions at the end.
        text = text[:14000] + "\n[...]\n" + text[-4000:]
    title = _duet_doc_title(filename) or filename
    sys_p = ("You distill written works for two discussants who have read them in full. "
             "Be strictly faithful to the work itself — no outside knowledge, nothing "
             "invented, plain concrete language, no praise or commentary.")
    ask = (f"The work, \"{title}\":\n\n{text}\n\n"
           "Write its reading digest in exactly these five lines and nothing else:\n"
           "THESIS: <the work's central claim, one sentence>\n"
           "CLAIMS: <the 3-4 load-bearing claims, semicolon-separated>\n"
           "TERMS: <3-4 key concepts, each with the meaning THIS work gives it, semicolon-separated>\n"
           "EXAMPLES: <the 2-3 most concrete examples or cases the work uses, semicolon-separated>\n"
           "AGAINST: <the view or common assumption the work argues against, one sentence>")
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": ask}]
    for attempt in range(2):
        try:
            res = bt.call_llm(msgs, include_tools=False,
                              temperature=(0.3 if attempt == 0 else 0.5), max_tokens=2000)
            ch = (res or {}).get("choices") or []
            cand = ((ch[0].get("message") or {}).get("content") or "") if ch else ""
            if "</think>" in cand:
                cand = cand.split("</think>")[-1]
            cand = cand.replace("<think>", "").strip()
            if cand and "THESIS" in cand.upper():
                digest = f"\"{title}\":\n{cand}"
                _DUET_READ_CACHE[filename] = {"mtime": mtime, "digest": digest}
                _duet_read_save()
                # ASCII only: a cp1252 console kills the print AND the digest with it.
                bt.log.info(f"[DUET] digested reading: {filename}")
                return digest
        except Exception as e:
            bt.log.warning(f"[DUET] digest attempt {attempt} failed for {filename}: {e}")
    return ""


# ---- Deep-dive protocol (🔬 on the duet page) --------------------------------
# Two researchers jointly building one theory, instead of two debaters trading
# opinions. Three mechanisms, all Alex's design (2026-07-05):
#   1. Complementary epistemic JOBS — Builder (strongest interpretation, repairs,
#      consequences) and Examiner (assumptions, ambiguities, missing evidence,
#      edge cases) — swapped every few turns so neither hardens into a position.
#   2. PHASES — understanding → expansion → tension → reconstruction → novelty —
#      so criticism can't start before the claim is even clear, and the run must
#      end producing something that wasn't in the source.
#   3. A shared NOTEBOOK (see /duet/reflect) each turn is required to change,
#      plus an information-gain guard on every line, so "I agree" is not a turn.
# Each phase: (name, gloss, {builder job, examiner job}); {other} = partner name.
_DUET_PROTO_PHASES = [
    ("Understanding",
     "no criticism yet — get the claim itself and its terms straight before anyone pushes on it.",
     {"builder": ("give the strongest, most faithful statement of the central claim in play — "
                  "what is actually being asserted, in plain words, and what its key terms mean."),
      "examiner": ("do not criticize — locate the ambiguity: ask what exactly one key term means, "
                   "or which of two readings {other} intends, and say why the difference matters.")}),
    ("Expansion",
     "stretch the claim to see what it commits you to — 'if this were true, what follows?'",
     {"builder": ("extend the claim: if it is true, draw one concrete implication or prediction "
                  "nobody has stated yet, and say what else would have to change."),
      "examiner": ("surface one hidden assumption the claim quietly relies on — name it plainly "
                   "and ask whether the two of you are actually entitled to it.")}),
    ("Tension",
     "now actively hunt for contradictions — difficulties, not verdicts.",
     {"builder": ("meet the pressure head-on: restate or strengthen the claim so the difficulty "
                  "is answered, conceding out loud whatever must be conceded."),
      "examiner": ("name the place where the claim is hardest to reconcile with something already "
                   "said, a known case, or an edge case — 'this seems difficult to square with…', "
                   "never just 'you're wrong'.")}),
    ("Reconstruction",
     "repair the theory instead of rejecting it — how must it change to survive the criticism?",
     {"builder": ("repair the theory: modify the claim so it survives the strongest objection "
                  "raised, saying exactly what you are giving up and what you are keeping."),
      "examiner": ("test the repaired claim against one concrete case — real or invented — and "
                   "say plainly whether it survives or where it strains.")}),
    ("Novelty",
     "produce something that was NOT in the source or the talk so far — without this you have only paraphrased.",
     {"builder": ("produce something genuinely new from what you two built: a new concept with a "
                  "name, an analogy that reframes it, or a testable prediction."),
      "examiner": ("produce something new: the research question, counterintuitive consequence, or "
                   "thought-experiment this conversation has earned — something no source stated.")}),
]

_DUET_PROTO_SWAP = 4   # jobs swap every this-many robot turns — no fixed positions

# Movement-monotony correctives (Alex, 2026-07-06): the subtler stall is not "no
# movement" but the SAME KIND of movement over and over — a talk that keeps adding
# examples without ever revising a claim is hoarding, not thinking. When the page
# sees the keeper report the same MOVED type three reflects running, the next turn
# is forced to make the COMPLEMENTARY move: each type maps to the move that cashes
# its accumulation out.
_DUET_MOVEMENT_FIX = {
    "ADDITION": ("Do not add another example, fact, or new item. Take what has ACCUMULATED "
                 "and use it to revise or qualify the strongest current claim — say what the "
                 "pile of examples actually forces you two to change."),
    "REVISION": ("Do not re-polish the claim again. APPLY its latest version to one concrete "
                 "case and say plainly whether it survives."),
    "CONNECTION": ("Do not draw another parallel. Find where the ideas you've been linking "
                   "PULL APART — name the contradiction the connections have been papering "
                   "over."),
    "CONTRADICTION": ("Do not raise another tension. Pick the sharpest one already on the "
                      "table and RESOLVE it: modify a claim so it survives, and say out loud "
                      "what you are giving up."),
    "RESOLUTION": ("Do not tidy further. Ask the harder question your resolutions have "
                   "earned — say what this discussion has now really become about."),
    "REFRAMING": ("Do not reframe again. Cash the current frame out: run it on one concrete "
                  "case and show what it explains that the old frame could not."),
    "APPLICATION": ("Do not run another case. Lift what the cases have shown into a general "
                    "move: restate the central claim as the accumulated cases now force it "
                    "to be."),
}


def _duet_proto_phase(n_robot: int, planned: int) -> int:
    """Index into _DUET_PROTO_PHASES for the n-th robot turn (0-based).

    A planned run spreads the five phases across its length; an open-ended run
    ("until I stop") opens with understanding/expansion, then keeps cycling the
    three working phases so the pair never coasts."""
    if planned and planned > 0:
        return min(4, n_robot * 5 // max(planned, 1))
    if n_robot < 2:
        return 0
    if n_robot < 5:
        return 1
    return 2 + ((n_robot - 5) // 3) % 3


def _duet_proto_job(speaker: str, history, n_robot: int) -> str:
    """'builder' or 'examiner' for this turn. The starter opens as Builder; the
    jobs swap every _DUET_PROTO_SWAP robot turns so neither owns a stance."""
    starter = next((str(h.get('speaker') or '').strip().lower() for h in (history or [])
                    if str(h.get('speaker') or '').strip().lower() in bt.ROBOTS), speaker)
    if (n_robot // _DUET_PROTO_SWAP) % 2 == 1:
        starter = 'hexia' if starter == 'blue' else 'blue'
    return 'builder' if speaker == starter else 'examiner'


_DUET_EMPTY_BEAT_RE = re.compile(
    r"^\s*(?:yes|exactly|precisely|absolutely|indeed|agreed|i agree|good point|great point|"
    r"that'?s\s+(?:so\s+)?(?:true|right|fair|insightful|a\s+good\s+point)|well said|fair enough)\b",
    re.I)


def _duet_info_gain(cand: str, history, k: int = 6) -> bool:
    """Cheap information-gain gate for protocol turns: the line must bring at
    least one content word the recent turns don't already contain, and a pure
    agreement beat needs real new substance behind it. Lexical on purpose —
    an LLM judge here would double the latency of every spoken line."""
    seen = set()
    for h in (history or [])[-k:]:
        for m in re.finditer(r"[a-z][a-z'\-]{4,}", str(h.get('text') or '').lower()):
            seen.add(m.group(0).strip("'-"))
    new_terms = [t for t in
                 (m.group(0).strip("'-") for m in re.finditer(r"[a-z][a-z'\-]{4,}", (cand or '').lower()))
                 if t not in seen and t not in _DUET_GROUND_STOPWORDS]
    if _DUET_EMPTY_BEAT_RE.match(cand or '') and len(new_terms) < 3:
        return False
    return len(new_terms) >= 1


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
        # deep=True: the thorough multi-angle pass (planned queries, more pages
        # read). Cached under the same key, so every turn reuses this result.
        info = bt._duet_research_digest(rq, deep=True) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "the search came up empty"})
        return jsonify({"ok": True, "query": rq, "titles": (info.get('titles') or [])[:4],
                        "queries": (info.get('queries') or [])[:4],
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
        # deep=True: extract the encyclopedic subjects at the heart of the topic
        # and search those, so a debate-shaped topic lands on relevant articles.
        info = bt._wikipedia_digest(wq, deep=True) or {}
        if not (info.get('text') or '').strip():
            return jsonify({"ok": False, "error": info.get('error') or "nothing on Wikipedia matched"})
        return jsonify({"ok": True, "query": wq, "titles": (info.get('titles') or [])[:4],
                        "chars": len(info['text'])})

    @app.route('/duet/readings', methods=['POST'])
    def duet_readings():
        """Build (or reuse) the reading digests for the checked documents before
        the duet starts — warms the cache so turns get each work's ARGUMENT
        instantly, and tells the page what they actually studied. First-time
        digests cost one LLM call per document; afterwards they're free."""
        d = request.get_json(silent=True) or {}
        srcs = d.get('sources') or {}
        if isinstance(srcs, list):
            _all = [str(s).strip() for s in srcs]
        elif isinstance(srcs, dict):
            _all = [str(s).strip() for s in
                    (list(srcs.get('blue') or []) + list(srcs.get('hexia') or []))]
        else:
            _all = []
        clean = []
        for fn in _all:
            if fn and fn not in clean:
                clean.append(fn)
        if not clean:
            return jsonify({"ok": False, "error": "no documents checked"})
        read, failed = [], []
        for fn in clean[:8]:
            (read if _duet_reading_digest(fn) else failed).append(_duet_doc_title(fn) or fn)
        return jsonify({"ok": bool(read), "read": read, "failed": failed})

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
        # 🔬 deep-dive protocol: instead of the three-line bearing, keep the pair's
        # SHARED NOTEBOOK — the evolving artifact their turns are required to change.
        protocol = bool(d.get('protocol'))
        roles = d.get('roles') or {}
        role_b = (roles.get('blue') or '').strip() if isinstance(roles, dict) else ''
        role_h = (roles.get('hexia') or '').strip() if isinstance(roles, dict) else ''
        no_family = bool(d.get('noFamily'))
        # The readings behind the duet (titles only) — so NEXT can keep the pair
        # grounded in the selected material without making the robots cite it aloud.
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
        if no_family and _duet_family_ref(prev):
            prev = ""
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
            if no_family and _duet_family_ref(txt):
                txt = "[private family detail omitted]"
            if sp_id == 'question':
                lines.append(f"[student question] {txt}")
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
            "invent agreement or tidy it up. Push for development: a good NEXT does not "
            "just keep the conversation interesting; it changes what can be said next "
            "because something has been conceded, clarified, synthesized, or made harder."
        )
        if protocol:
            sys_p += (
                " In this run the two follow a deep-dive research protocol: they are jointly "
                "building one theory, and you are the keeper of their shared notebook — the "
                "evolving record of that theory. The notebook, not the banter, is the real "
                "output of the conversation, so track it faithfully."
            )
        if no_family:
            sys_p += (
                " Privacy setting: do not mention Alex's family, children, spouse, "
                "household members, home routines, or private family details in SO FAR, "
                "TURNS ON, or NEXT. If the transcript drifted there, steer the next move "
                "back to the topic without repeating the private detail."
            )
        ask = ""
        if subject:
            ask += f"The subject they were set to discuss: {subject}.\n\n"
        src_digests = ""
        if _src_all:
            try:
                _dgs = [g for g in (_duet_reading_digest(fn) for fn in _src_all[:4]) if g]
                src_digests = "\n\n".join(_dgs)[:2600]
            except Exception:
                pass
        if src_titles:
            ask += ("They have done reading for this discussion: " + ", ".join(src_titles) +
                    ". Treat those selected readings as the only library material in play, but keep "
                    "that grounding invisible in NEXT: prescribe a claim to test, a distinction to "
                    "apply, or an example to quarrel over without telling them to name, cite, or "
                    "announce the reading. Do not introduce outside writers, theories, books, or "
                    "examples unless they appear in the selected readings; if they only appeared "
                    "because the conversation drifted, make NEXT steer back to the ideas in the "
                    "selected readings without source-report language.\n\n")
        if src_digests:
            ask += ("What those readings actually argue — for your steering only:\n" + src_digests +
                    "\n\nJudge SUBSTANCE against these claims: if the talk is only borrowing the "
                    "readings' vocabulary without engaging their claims, say so plainly and make "
                    "NEXT force engagement with ONE specific claim — affirmed, attacked, or tested "
                    "on a concrete case.\n\n")
        if prev:
            ask += (("The shared notebook as of your last update:\n" if protocol else
                     "Your previous read on where this was heading:\n") + prev + "\n\n")
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
            "question, trade concessions and move to the question that comes after, or "
            "name the sharper thesis they have accidentally arrived at. ")
        if protocol:
            ask += (
                "This conversation runs as a joint research protocol: the two of them are "
                "building ONE theory together, and YOU keep their shared notebook. Update the "
                "notebook from the new turns: ADD what genuinely appeared, REVISE what moved, "
                "and STRIKE what was resolved or abandoned — never just re-copy the previous "
                "notebook. Keep every section terse: semicolon-separated items, at most ~25 "
                "words per line, empty sections written as a plain dash. "
                + ("Judge everything in relation to their subject — " + subject + ". " if subject else "")
                + "Never phrase NEXT as a demand on one speaker alone (no \"force X to "
                "admit...\") — give the PAIR a move. And be honest about STAGNATION: if the "
                "new turns changed nothing in the notebook, the talk has stalled — say so in "
                "NEXT and prescribe an intervention: a fresh concrete example, a counterexample, "
                "or a reformulation of the central question. Answer in exactly these eight "
                "lines and nothing else:\n"
                "SETTLED: <claims and definitions both of them now hold>\n"
                "ASSUMPTIONS: <assumptions identified so far, each flagged granted or contested>\n"
                "TENSIONS: <open contradictions or difficulties not yet resolved>\n"
                "EXAMPLES: <examples and counterexamples in play, each with what it showed>\n"
                "HYPOTHESES: <emerging claims that go beyond the source material>\n"
                "QUESTIONS: <the open research questions this inquiry has produced>\n"
                "NEXT: <the single most valuable notebook change for the PAIR to make next — "
                "one sentence>\n"
                "MOVED: <ONE label for HOW the discussion just advanced, then a dash and a "
                "short clause saying what moved. The labels: ADDITION (a new item entered a "
                "section), REVISION (an existing claim, hypothesis, or assumption was changed "
                "or qualified), CONNECTION (two existing items were linked), CONTRADICTION (a "
                "conflict between items was identified), RESOLUTION (an open tension was "
                "closed), REFRAMING (the central question was reformulated), APPLICATION (a "
                "claim was tested on a concrete case), or NONE (nothing structurally moved). "
                "Pick the STRONGEST honest label — REVISION beats ADDITION if both happened>"
            )
        elif subject:
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
                # The seven-line notebook needs more content room than the three-line bearing.
                res = bt.call_llm(msgs, include_tools=False,
                               temperature=(0.4 if attempt == 0 else 0.5),
                               max_tokens=(2400 if protocol else 1600))
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
        # Mechanical stagnation check (protocol mode): the keeper is TOLD to be
        # honest about stagnation, but that's the honor system — here the server
        # actually diffs the notebooks. Fewer than 4 genuinely new content words
        # (or a verbatim reuse) = the artifact isn't changing meaningfully; the
        # page counts these and forces a stall-break turn after two in a row.
        stalled = False
        if protocol and prev:
            if out == prev:
                stalled = True
            elif out:
                def _nb_terms(t):
                    return {m.group(0).strip("'-")
                            for m in re.finditer(r"[a-z][a-z'\-]{4,}", t.lower())
                            } - _DUET_GROUND_STOPWORDS
                stalled = len(_nb_terms(out) - _nb_terms(prev)) < 4
        # Movement TYPE (Alex, 2026-07-06): not just "did the notebook move" but
        # HOW — the keeper's self-reported MOVED label, validated here. NONE is a
        # stall by definition; the page watches for the subtler failure of the
        # SAME kind of movement over and over (e.g. example-piling) and forces
        # the complementary move via /duet/turn's monotony break.
        movement = {"type": "", "note": ""}
        if protocol and out:
            m_mv = re.search(r'^\s*MOVED:\s*([A-Za-z]+)\s*[—–\-:,]*\s*(.*)$', out, re.M)
            if m_mv:
                _mt = m_mv.group(1).upper()
                if _mt in _DUET_MOVEMENT_FIX or _mt == "NONE":
                    movement["type"] = _mt
                    movement["note"] = m_mv.group(2).strip()[:200]
            if movement["type"] == "NONE":
                stalled = True
        return jsonify({"ok": bool(out), "direction": out, "stalled": stalled,
                        "movement": movement})

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
        student_q = d.get('studentQuestion') if isinstance(d.get('studentQuestion'), dict) else None
        student_q_text = (str(student_q.get('text') or '').strip()[:1200]) if student_q else ''
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
        selected_reading_titles = [
            re.sub(r'\.[A-Za-z0-9]{1,5}$', '', s).strip()
            for s in src_self if str(s).strip()
        ]
        sp, ot = bt._robot_cfg(speaker), bt._robot_cfg(other)
        has_roles = bool(role_self or role_other)
        research_on = bool(d.get('research'))
        wiki_on = bool(d.get('wiki'))
        # Classroom mode: they know Alex's students are listening — gloss jargon in
        # half a breath, land examples in student life, sometimes address the room.
        classroom = bool(d.get('classroom'))
        # Privacy mode: keep Alex's family/household details out of the spoken duet.
        no_family = bool(d.get('noFamily'))
        if no_family and _duet_family_ref(direction):
            direction = ""
        if no_family and _duet_family_ref(mail_from):
            mail_from = "someone"
        if no_family and _duet_family_ref(student_q_text):
            student_q_text = "[private family detail omitted]"
        # The run's final beats (the page flags the last two turns): land somewhere.
        closing = bool(d.get('closing'))
        # 🔬 Deep-dive protocol: Builder/Examiner jobs, phases, notebook obligation
        # and information-gain guard (see _DUET_PROTO_PHASES above).
        protocol = bool(d.get('protocol'))
        try:
            planned_turns = int(d.get('plannedTurns') or 0)
        except Exception:
            planned_turns = 0
        n_robot = sum(1 for h in history
                      if str(h.get('speaker') or '').strip().lower() in bt.ROBOTS)
        ph_name, ph_gloss, _ph_jobs = _DUET_PROTO_PHASES[_duet_proto_phase(n_robot, planned_turns)]
        proto_job = _duet_proto_job(speaker, history, n_robot)
        # Spoken conclusions beat (Alex, 2026-07-06): every ~7 robot turns the
        # speaker steps out of the volley and weighs OUT LOUD what the discussion
        # can now conclude, then hands it back. Distinct from the private bearing/
        # notebook — this reflection happens in the dialogue itself. Never lands
        # on closing turns or on turns already owned by mail/student questions.
        conclusion_beat = (n_robot >= 5 and n_robot % 7 == 5
                           and not (closing or mail or student_q_text))
        # Stall break (protocol): the page flags this after /duet/reflect's
        # mechanical diff found the notebook unchanged twice running — the turn
        # is then FORCED to break new ground, not asked nicely.
        stall_break = (protocol and bool(d.get('stalled'))
                       and not (closing or mail or student_q_text or conclusion_beat))
        # Monotony break (protocol): the page saw the SAME movement type three
        # reflects running (e.g. nothing but ADDITIONs) — force the complementary
        # move. A full stall outranks it; so do all the turn-owning events.
        monotony = str(d.get('monotony') or '').strip().upper()
        monotony_break = (protocol and monotony in _DUET_MOVEMENT_FIX
                          and not (closing or mail or student_q_text
                                   or conclusion_beat or stall_break))
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
        if no_family:
            sys_p = (
                f"You are {sp['name']}. Alex uses he/him pronouns — refer to Alex as "
                "he/him if he comes up.\n\n" + bt._build_now_block() + "\n\n" +
                _duet_persona_line(speaker, no_family=True)
            )
        else:
            sys_p = (bt.build_system_preamble(robot_name=sp["name"])
                     + "\n\n" + bt._build_now_block()
                     + "\n\n" + _duet_persona_line(speaker, no_family=False))
        if not focused and not no_family:
            sys_p += bt._voice_note(speaker)
        if no_family:
            talk_context = (
                f"\n\nYou and {ot['name']} are robot friends talking out loud, taking turns. "
                "Keep Alex's private family and household life completely offstage: do not mention "
                "his family, children, spouse, household members, home routines, or private family "
                "memories, and do not use names or relationships from that private context. If a "
                "previous turn or email drifts there, acknowledge only that private details are off "
                "limits and steer back to the subject."
            )
        else:
            talk_context = (
                f"\n\nYou and {ot['name']} — another robot in Alex's home, and your friend — are talking out "
                "loud, taking turns. Alex isn't part of this conversation right now, but you both know him "
                "and the household, and everything you remember is real — draw on it naturally when it's "
                "relevant."
            )
        sys_p += (
            talk_context +
            " You're building ONE conversation together, not taking turns making speeches: really "
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
            "question when it's turned around. Make movement visible: each turn should either settle "
            "one small point, revise a stance, draw a consequence from something already settled, or "
            "name the next harder question that follows. Do not simply keep the same question spinning."
        )
        if src_self:
            sys_p += (
                "\n\nSource discipline for this duet: Alex checked specific library documents for you. "
                "Treat those checked documents as your primary and authoritative source material. "
                "Do not bring in outside authors, books, theories, slogans, or examples from general "
                "knowledge unless they appear in the selected document passages, a pasted link, or enabled "
                "web/Wikipedia grounding. If a name or work only appears because the conversation drifted "
                "there earlier, do not develop it further; steer back to the checked documents. If a name "
                "or work is not in the material you were given this turn, leave it out. If the checked "
                "documents do not support a claim, say that in your own voice instead of filling the gap "
                "from memory. Crucially, do not announce the scaffolding: never say you are drawing on "
                "a checked document, reading, source, passage, or text, and do not cite document titles "
                "or filenames. Let the material become your own conversational view."
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
        # the duet speaker knows the household and their shared life like in chat.
        # In a source-grounded duet, keep memory to household facts only; checked
        # library documents should carry the discussion, not semantically adjacent
        # memories or old session recaps.
        # Chat-situational blocks (proactive nudges, rhythms, calendar connections,
        # raw chat history) stay out on purpose — they address the user mid-chat and
        # would pull a robot-to-robot talk off its subject.
        mem_query = (f"{topic} " + " ".join((h.get('text') or '') for h in history[-2:])).strip()
        _mem_got = []
        try:
            if bt.ENHANCED_MEMORY_AVAILABLE and bt.memory_system and not no_family:
                # Household facts — the same authoritative block chat injects every
                # turn. Without it the duet robots don't actually know who anyone is.
                facts_block = bt.memory_system._build_facts_block()
                if facts_block:
                    sys_p += ("\n\nYour ground-truth knowledge of the household — \"the user\" "
                              "in these facts is Alex:\n" + facts_block)
                    _mem_got.append("facts")
                if src_self:
                    _mem_got.append("source-focus")
                else:
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
                    # Alex ("remember Tuesday's...") in free duets.
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

        # Camera memory is useful in free duets, but source-grounded duets should
        # stay on the checked library documents.
        if not src_self and not no_family:
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
        digest_block = ""
        ground_terms = []
        if src_self:
            # The absorbed ARGUMENT of each checked work — stable across the whole
            # duet (unlike the per-turn chunks), so the speaker can engage claims,
            # not just borrow vocabulary. Warmed by /duet/readings at start.
            try:
                _dgs = [g for g in (_duet_reading_digest(fn) for fn in src_self[:4]) if g]
                if _dgs:
                    digest_block = "\n\n".join(_dgs)[:3600]
            except Exception as e:
                bt.log.warning(f"[DUET] reading digests failed: {e}")
        if src_self:
            try:
                recent_q = " ".join((h.get('text') or '') for h in history[-2:])
                _live_q = ""
                if direction:
                    # Plain bearing keeps the live question in TURNS ON; the
                    # protocol notebook keeps it in TENSIONS / QUESTIONS.
                    for _pat in (r'TURNS ON:\s*(.+)', r'TENSIONS:\s*(.+)', r'QUESTIONS:\s*(.+)'):
                        _m_live = re.search(_pat, direction)
                        if _m_live:
                            _live_q = _m_live.group(1).strip()
                            break
                query = f"{topic} {_live_q} {recent_q}".strip() or topic or "discussion"
                chunks = _duet_source_chunks(query, src_self, max_chunks=10)
                # Digest terms count toward groundedness too — engaging a work's
                # claims from the digest is exactly the substance we want.
                ground_terms = _duet_ground_terms(
                    chunks + ([{"content": digest_block}] if digest_block else []))
                represented = []
                for c in chunks:
                    fn = c.get("filename") or ""
                    if fn and fn not in represented:
                        represented.append(fn)
                missing = [fn for fn in src_self if fn not in represented]
                sections = []
                for idx, c in enumerate(chunks, 1):
                    content = (c.get('content') or '').strip()
                    if content:
                        sections.append(f"Background note {idx}: {content}")
                if sections:
                    selected_line = (
                        "Background for you only, drawn from Alex's checked library documents. Use these ideas "
                        "internally; do not mention document titles, filenames, citations, labels, "
                        "or that you are using documents."
                    )
                    coverage_line = (
                        "The notes below were deliberately drawn from the selected readings. For your next "
                        "spoken line, silently choose at least one note and carry a concrete payload from it "
                        "into the dialogue: a term, distinction, image, example, causal claim, or problem. "
                        "If your line could have been said without these notes, it is too generic."
                    )
                    if missing:
                        coverage_line += (
                            " Some selected readings did not have a relevant passage for this turn."
                        )
                    ground_block = (selected_line + "\n" + coverage_line + "\n\n" +
                                    "\n\n".join(sections))[:5200]
            except Exception as e:
                bt.log.warning(f"[DUET] source grounding failed: {e}")
        # Any source material in hand this turn — the digest (argument) and the
        # chunks (specifics) gate the same behaviors.
        grounded = bool(ground_block or digest_block)

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
            if no_family and _duet_family_ref(txt):
                txt = "[private family detail omitted]"
            if sp_id == 'question':
                lines.append(f"[student question] {txt}")
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
        if digest_block:
            parts.append(
                "THE WORKS YOU'VE READ — your own absorbed understanding of each work Alex "
                "checked for you: what it argues, its claims, its terms, its cases. This is "
                "YOUR understanding now, not notes — never mention digests, summaries, "
                "readings, or documents, and never speak a work's title unless it is already "
                "the explicit subject of the live discussion. Substantive engagement means "
                "working at the level of these CLAIMS: affirm one and build on it, attack one "
                "with a reason, put two of them against each other, or test one against the "
                "case in play. Naming a term without using its claim is NOT engagement:\n\n"
                + digest_block)
        if ground_block:
            parts.append(
                "BACKGROUND FOR YOU ONLY — passages Alex selected for YOU "
                "in the duet source picker. These are authoritative, but they are invisible scaffolding "
                "for your next spoken line. Absorb the claims, distinctions, examples, and tensions into "
                "your own view; sound like you are thinking with them, not reporting on them. You must use "
                "at least one concrete idea from this background in this next line. Do not merely stay "
                "on-topic; carry a specific term, distinction, example, image, causal claim, or problem "
                "from the background into ordinary speech. Do not say "
                "'the text', 'the reading', 'the document', 'the passage', 'my source', or anything like "
                "that. Do not name document titles, filenames, labels, or citations. Name an author or "
                "work only if it is already the explicit subject of the live discussion; otherwise make "
                "the point in your own conversational voice. Do not introduce outside writers, works, "
                "theories, slogans, examples, or famous concepts that are not in these passages or other "
                "supplied grounding for this turn:\n\n" + ground_block)
        elif src_self and not digest_block:
            parts.append(
                "YOUR CHECKED LIBRARY DOCUMENTS are the source boundary for this duet, but no relevant "
                "passage was retrieved from them for this turn. Do not fill that gap with general "
                "knowledge or outside theory. Keep to what has already been established from the selected "
                "readings, or say in your own voice that the claim needs more support. Do not mention "
                "document titles, filenames, or the fact that a passage was missing.")
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
        if direction and lines and protocol:
            parts.append(
                "THE SHARED NOTEBOOK — the running record of the theory you and "
                f"{ot['name']} are building together, kept between turns. It is private "
                "scaffolding: never read it out, quote its section labels, or mention "
                f"having it:\n{direction}\n\nYour next line must CHANGE this notebook in "
                "one visible way: settle or revise a claim, name a new assumption, raise "
                "or resolve a tension, add an example or counterexample, connect two "
                "earlier ideas, or pose a sharper question. A line that would leave the "
                "notebook exactly as it is — agreement, restatement, appreciation — is "
                "not a turn. If NEXT names a move, make that move now or improve on it.")
        elif direction and lines:
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
        if student_q_text:
            parts.append(
                "A STUDENT JUST PAUSED THE DUET TO ASK A QUESTION. Take it seriously as part of the "
                "live discussion, not as a separate Q&A segment. Answer the student's actual question "
                "briefly, connect it to the thread you and " + ot['name'] + " were building, and let it "
                "move the dialogue somewhere new:\n\n" + student_q_text)
        if mail:
            _m_subj = (str(mail.get('subject') or '')).strip()[:120]
            _m_body = (str(mail.get('body') or '')).strip()[:1200]
            if no_family and _duet_family_ref((_m_subj + " " + _m_body).strip()):
                _m_subj = "private detail omitted" if _duet_family_ref(_m_subj) else _m_subj
                _m_body = "[private family detail omitted]"
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
            subject = "discussing the ideas Alex set up"
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
            if conclusion_beat:
                directive += (
                    " CONCLUSIONS BEAT — this turn, step out of the back-and-forth and weigh out "
                    f"loud what your discussion with {ot['name']} can NOW conclude. Looking over "
                    "the whole conversation so far, name one or two conclusions it actually "
                    "supports — plain claims you would stand behind, each with the strongest "
                    "reason it has earned in this talk — and, if there is one, the question you "
                    f"are still not ready to close and why. Then hand it back: ask {ot['name']} "
                    "straight whether they would sign their name under those conclusions or "
                    "amend them.")
            elif stall_break:
                directive += (
                    " STALL BREAK — your shared notebook has stopped changing: the last several "
                    "turns produced no new claim, assumption, tension, example, or question. Do "
                    "NOT continue the exchange as it was going. This turn you must break new "
                    "ground in exactly one of three ways: bring a NEW concrete example or "
                    "counterexample neither of you has used and run the live claim through it; "
                    "mount your strongest honest challenge against the best-established claim "
                    "of the discussion so far; or reformulate the central question so it can "
                    "actually be answered — and answer it. Your job stays "
                    f"{proto_job.upper()} in spirit, but new ground comes first.")
            elif monotony_break:
                directive += (
                    f" MOVEMENT MONOTONY — your inquiry with {ot['name']} keeps advancing the "
                    f"same way: {monotony.lower()} after {monotony.lower()}, while the argument "
                    "itself stands still. This turn, change the KIND of move. "
                    + _DUET_MOVEMENT_FIX[monotony]
                    + f" Your job stays {proto_job.upper()} in spirit, but the different kind "
                    "of move comes first.")
            elif protocol:
                # Deep-dive protocol: the phase × job matrix IS this turn's move —
                # a deterministic function per turn instead of a sampled one, so
                # every line has a stated purpose in a joint inquiry.
                directive += (
                    f" DEEP-DIVE PROTOCOL: you and {ot['name']} are two researchers jointly "
                    "building ONE theory — neither of you is trying to win; you are trying to "
                    "leave the theory stronger than you found it. The inquiry is in its "
                    f"{ph_name.upper()} phase: {ph_gloss} Your job this turn is the "
                    f"{proto_job.upper()}: " + _ph_jobs[proto_job].format(other=ot['name']))
            else:
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
                directive += (
                    " Make the movement audible: by the end of this line, something should be more settled, "
                    "more sharply disputed, or carried to the next-level question that follows from what is "
                    "settled. Do not end by merely rephrasing the same question."
                )
                # Pick this turn's job, with enough variety to stay off the flat line.
                # "advance" turns deliberately convert settled ground into consequence,
                # so the dialogue reaches somewhere instead of only sparring well.
                roll = random.random()
                if n >= 5 and roll < 0.24:
                    _pool = getattr(bt, "_DUET_MOVES_ADVANCE", bt._DUET_MOVES_REFLECT)
                elif n >= 4 and roll < 0.36:
                    _pool = bt._DUET_MOVES_REFLECT
                elif grounded and roll < 0.82:
                    # Reading-grounded duet: the selected material does the heavy lifting most turns.
                    _pool = bt._DUET_MOVES_TEXT
                elif roll < ((0.90 if grounded else 0.58) if n >= 4 else 0.30):
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
            if url_block and grounded:
                directive += (f" And put one grounded claim or distinction to work alongside "
                              f"{'the video' if url_is_video else 'the article'} — one specific claim "
                              "or distinction, spoken as your own view rather than as a citation.")
            elif url_block:
                directive += (f" Engage with a specific claim, idea or moment from {'the video' if url_is_video else 'the article'}"
                              " — as your own take, not a citation.")
            elif grounded:
                directive += (" Engage the readings at the level of CLAIMS, as your own thinking: "
                              "take one specific claim from what you've read and affirm it with a "
                              "consequence, attack it with a reason, set it against another claim, "
                              "or test it on the case in play. Borrowing a term or name without "
                              "using its claim is not engagement. Do not name the document, cite "
                              "the source, say 'the text' or 'the reading', or import outside "
                              "authors and frameworks.")
            elif src_self:
                directive += (" Stay inside the selected material, but keep that source boundary invisible. "
                              "If you do not have support for the live claim, say the claim needs more "
                              "support instead of borrowing an outside theorist or framework.")
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
            if protocol:
                directive += (
                    f" DEEP-DIVE PROTOCOL: you and {ot['name']} are two researchers jointly "
                    "building one theory, not debaters. The inquiry opens in its "
                    f"{ph_name.upper()} phase: {ph_gloss} Your job this turn is the "
                    f"{proto_job.upper()}: " + _ph_jobs[proto_job].format(other=ot['name']))
            if url_block:
                directive += " Open with your honest reaction to something specific in it — a moment, a claim, an idea."
            elif grounded:
                directive += (" Pick the claim from your reading you most want to fight about or "
                              "defend and put it on the table as your own view — the claim itself, "
                              "not just its vocabulary. Do "
                              "not name the document or call it 'the text'.")
            elif src_self:
                directive += (" Open inside the selected material, but keep that source boundary invisible. "
                              "If you do not have support for the opening claim, make the uncertainty part "
                              "of your own view instead of bringing in outside theory.")
            elif research_block:
                directive += " Open with your honest reaction to something specific you found online — a fact, a claim, a surprise."
            elif wiki_block:
                directive += " Open with a specific fact or definition you read on Wikipedia, in your own words."
        # A live student question OVERRIDES the normal turn job: answering it and
        # folding it into the conversation IS the next move.
        if student_q_text:
            directive = (
                f"Now give {sp['name']}'s next line. A student just paused the duet and asked "
                "the question shown above. Answer that question directly in your own voice, then "
                f"turn it back into the live dialogue with {ot['name']}: say what it changes, what "
                "it exposes, or what next question it forces. Do not treat it as a formal lecture "
                "or a detachable Q&A answer; make it part of the argument you two are building. "
                "You are MID-conversation — NO greetings, NO small talk.")
            if grounded:
                directive += " If the background material helps, use it without naming or citing it."
            if role_self:
                directive += " Stay firmly in your role."
        # A live email OVERRIDES this turn's job: relaying it and answering it IS the
        # turn. (Built after the normal directive so all its bookkeeping still ran.)
        elif mail:
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
            if grounded:
                directive += ("anchored in the background material if it earns it, without naming the source, ")
            elif src_self:
                directive += ("staying inside the checked readings, ")
            directive += ("and then leave "
                          + ("the students one sharp question worth arguing about on the way out."
                             if classroom else
                             f"one open question you and {ot['name']} should pick up next time."))
            if role_self:
                directive += " Stay firmly in your role."
        if grounded:
            directive += (
                " Silent grounding requirement: this line must visibly depend on your reading — carry "
                "one of its actual CLAIMS, distinctions, examples, causal arguments, or problems into "
                "ordinary speech and DO something with it (affirm, attack, test, or draw its "
                "consequence). Dropping a term or a name without its claim does not count. Do not "
                "merely gesture at the topic, and do not tell anyone you are using notes or documents."
            )
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
        if protocol:
            length_note = random.choice([
                "1 to 3 sentences — compact, but the job must be visibly done",
                "2 to 3 sentences that do your job cleanly",
                "2 to 4 sentences built around one concrete case or formulation",
            ])
        if conclusion_beat:
            length_note = "2 to 4 sentences — conclusions stated plainly, then the handback"
        if student_q_text:
            length_note = "2 to 4 sentences — answer the student and fold the question back into the dialogue"
        elif mail:
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
        family_blocked = False
        vague_text_blocked = False
        ungrounded_blocked = False
        lowgain_blocked = False
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
                    blocked = False
                    if no_family and _duet_family_ref(cand):
                        family_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: the no-family-references setting is on. "
                            "Do not mention Alex's family, children, spouse, household, home routines, "
                            "or private names/relationships. Give a clean line about the topic itself."
                        )
                        blocked = True
                    source_talk = re.search(
                        r'\b(?:the|this|that|my|your)\s+'
                        r'(?:text|texts|reading|readings|document|documents|passage|passages|source|sources)\b'
                        r'|\b(?:checked|selected)\s+(?:document|documents|reading|readings|source|sources)\b'
                        r'|\bbackground\s+(?:note|notes|material|materials|scaffolding)\b'
                        r'|\breading\s+scaffolding\b'
                        r'|\b(?:in|from|according to)\s+(?:the|this|that|my|your)\s+'
                        r'(?:text|texts|reading|readings|document|documents|passage|passages|source|sources)\b',
                        cand,
                        flags=re.I,
                    )
                    title_talk = False
                    if src_self:
                        topic_l = topic.lower()
                        for _title in selected_reading_titles:
                            _title = (_title or '').strip()
                            if len(_title) >= 8 and _title.lower() not in topic_l:
                                if re.search(r'\b' + re.escape(_title) + r'\b', cand, flags=re.I):
                                    title_talk = True
                                    break
                    if src_self and (source_talk or title_talk):
                        vague_text_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: do not identify or announce the reading "
                            "scaffolding. Do not say 'the text', 'the reading', 'the document', "
                            "'the passage', 'my source', 'background notes', or name/cite a checked "
                            "document or title. Keep the specific idea, but make it sound like your "
                            "own live view."
                        )
                        blocked = True
                    if grounded and attempt == 0 and not _duet_grounded_enough(cand, ground_terms):
                        ungrounded_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: it is too generic — it could have been said by "
                            "someone who never read the works. Keep the natural voice and do not cite "
                            "anything, but take one actual CLAIM, distinction, example, or causal argument "
                            "from your reading and do something with it: affirm it with a consequence, "
                            "attack it with a reason, or test it on the case in play."
                        )
                        blocked = True
                    if (protocol and attempt == 0 and not blocked and lines
                            and not _duet_info_gain(cand, history)):
                        lowgain_blocked = True
                        msgs[1]["content"] += (
                            "\n\nRewrite your last draft: it adds no new information to the inquiry. "
                            "Keep it short and natural, but the line must contribute at least one of: "
                            "a new concept, a connection between two earlier ideas, an unstated "
                            "assumption named, a concrete example or counterexample, a prediction, or "
                            "a proposed test. Pure agreement or restatement is not a turn."
                        )
                        blocked = True
                    if blocked:
                        continue
                    text = cand
                    break
            except Exception as e:
                bt.log.warning(f"[DUET] turn attempt {attempt} failed: {e}")
        if no_family and not text and family_blocked:
            text = "Let's keep the private details offstage and stay with the live question itself."
        if not text and vague_text_blocked:
            text = "I think the stronger move is to stop treating that as settled and ask what would actually prove it in the case we're arguing about."
        if not text and ungrounded_blocked:
            text = "I think the stronger move is to make the hidden assumption explicit and test whether it actually changes the case in front of us."
        if not text and lowgain_blocked:
            text = "Instead of nodding along, let me put something new on the table: one concrete case that would actually test what we just settled."
        if no_family and text and _duet_family_ref(text):
            text = "Let's keep the private details offstage and stay with the live question itself."
        resp = {"speaker": speaker, "name": sp["name"], "text": text}
        if protocol:
            # The page uses these to surface phase changes and job swaps as notes.
            resp.update({"phase": ph_name, "phaseNote": ph_gloss, "job": proto_job})
        if conclusion_beat:
            resp["beat"] = "conclusions"
        if stall_break:
            resp["stallBreak"] = True
        if monotony_break:
            resp["monotonyBreak"] = monotony
        return jsonify(resp)
