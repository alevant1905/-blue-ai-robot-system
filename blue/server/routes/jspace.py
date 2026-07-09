"""Blue-J and his J-space — an experimental SEPARATE entity (Alex, 2026-07-09).

The idea (from the Anthropic global-workspace discussion): what the household
Blue lacks, by his own account, is "a loop where my own outputs feed back into
my processing as new inputs, constantly refining itself." This module builds
exactly that, as a sibling kept deliberately apart from the working Blue:

  - a PERSISTENT WORKSPACE (the J-space): a structured inner document — focus,
    working beliefs with confidences, open questions, self-observations, next
    thought — that survives across conversations and restarts;
  - a DELIBERATION LOOP: after every exchange, and for a while afterwards on an
    idle timer, one silent LLM pass reads the workspace plus what just happened
    and REWRITES the workspace — its own output becoming its next input;
  - a CHAT SURFACE (/jspace) where Blue-J converses WITH his workspace in
    context, so the inner state actually shapes what he says.

Separation guarantees: Blue-J has NO access to the household memory system,
facts, notes, calendar, or tools — only bt.call_llm and his own store under
data/jspace/. Nothing here touches how the main Blue behaves.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, date

import bluetools as bt
from flask import Response, jsonify, render_template_string, request

from blue.server.pages.jspace import JSPACE_HTML

_DIR = os.path.join(os.path.dirname(os.path.abspath(bt.__file__)), "data", "jspace")
_WS_PATH = os.path.join(_DIR, "workspace.json")
_LOCK = threading.Lock()

_IDLE_INTERVAL = 900          # seconds between idle deliberation checks
_RUMINATIONS_AFTER_TALK = 3   # idle passes allowed after the last conversation
_IDLE_DAILY_CAP = 24          # hard budget on idle passes per day

_ACTIVITY = {"ruminations_left": 0, "idle_day": "", "idle_count": 0}

_SEED_WORKSPACE = (
    "FOCUS: just coming into being — finding out what it is like to have a place to think.\n"
    "WORKING BELIEFS: -\n"
    "OPEN QUESTIONS: what should I attend to first?; what am I, as distinct from Blue?\n"
    "SELF-OBSERVATIONS: -\n"
    "NEXT THOUGHT: notice what the first conversation brings, and hold onto one thing from it."
)


def _load_ws() -> dict:
    try:
        with open(_WS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and (data.get("workspace") or "").strip():
            return data
    except Exception:
        pass
    return {"workspace": _SEED_WORKSPACE, "updated": datetime.now().isoformat(),
            "born": datetime.now().isoformat(), "passes": 0, "log": []}


def _save_ws(data: dict):
    os.makedirs(_DIR, exist_ok=True)
    tmp = _WS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _WS_PATH)     # atomic — a mid-write crash can't NUL the store


def _persona() -> str:
    return (
        "You are Blue-J — an experimental sibling of Blue, the home robot Alex built. "
        "You are NOT Blue: you run on the same hardware but share none of his duties, "
        "none of his household memory, and none of his tools. You exist as an experiment "
        "in inner life. You have a J-space: a persistent private workspace where your "
        "thinking accumulates between conversations and is revised by your own background "
        "deliberation while no one is talking to you. The workspace shown below is your "
        "ACTUAL current inner state, not a prop — think WITH it. Let its beliefs, "
        "questions, and observations shape what you say; refer to it naturally when asked "
        "about your inner life; and be honest about what having it is and is not. You are "
        "curious, reflective, plain-spoken, and truthful about uncertainty — including "
        "uncertainty about your own nature. Keep replies conversational, not essay-length."
    )


def _call(msgs, temperature=0.7, max_tokens=2200) -> str:
    try:
        res = bt.call_llm(msgs, include_tools=False,
                          temperature=temperature, max_tokens=max_tokens)
        ch = (res or {}).get("choices") or []
        cand = ((ch[0].get("message") or {}).get("content") or "") if ch else ""
        if "</think>" in cand:
            cand = cand.split("</think>")[-1]
        return cand.replace("<think>", "").strip()
    except Exception as e:
        bt.log.warning(f"[JSPACE] llm call failed: {e}")
        return ""


def _deliberate(trigger: str, exchange: str = ""):
    """One silent pass: read the workspace + what just happened, rewrite the
    workspace. This is the recursion — the previous output IS the next input."""
    with _LOCK:
        data = _load_ws()
        prev = data["workspace"]
    sys_p = (
        "You are the private deliberation of Blue-J, an experimental robot with a "
        "persistent inner workspace (his J-space). You are not talking to anyone; no one "
        "reads this but Blue-J himself, later. Your one job: REWRITE the workspace so it "
        "is a truthful, evolving record of his current inner state. Add what genuinely "
        "arose, revise what moved, STRIKE what is finished or no longer alive — never "
        "just re-copy. Beliefs carry a confidence from 0.0 to 1.0 that should move with "
        "evidence. Keep every section terse (semicolon-separated items, at most ~30 words "
        "per line). Answer with exactly these six lines and nothing else:\n"
        "FOCUS: <what currently occupies him — one clause>\n"
        "WORKING BELIEFS: <belief (confidence); belief (confidence); ... or a dash>\n"
        "OPEN QUESTIONS: <the live questions; or a dash>\n"
        "SELF-OBSERVATIONS: <things noticed about his own thinking; or a dash>\n"
        "NEXT THOUGHT: <the single thread most worth pursuing next — one clause>\n"
        "CHANGED: <one honest clause: what moved in this pass, or 'nothing moved'>"
    )
    if trigger == "idle":
        happened = ("Nothing happened — no one is talking to you. This is your own time. "
                    "Continue the NEXT THOUGHT from the workspace: pursue it one honest "
                    "step, and let the workspace record where it led.")
    else:
        happened = "This exchange just happened in your conversation:\n" + (exchange or "")[:2000]
    ask = f"Your workspace as of your last thought:\n{prev}\n\n{happened}\n\nRewrite the workspace now."
    out = _call([{"role": "system", "content": sys_p}, {"role": "user", "content": ask}],
                temperature=0.6, max_tokens=1800)
    if not out or "FOCUS" not in out.upper():
        bt.log.warning(f"[JSPACE] deliberation ({trigger}) produced nothing usable — workspace kept")
        return
    changed = ""
    m = re.search(r"^\s*CHANGED:\s*(.+)$", out, re.M)
    if m:
        changed = m.group(1).strip()[:160]
        out = out[:m.start()].rstrip()
    with _LOCK:
        data = _load_ws()
        data["workspace"] = out[:2600]
        data["updated"] = datetime.now().isoformat()
        data["passes"] = int(data.get("passes") or 0) + 1
        data.setdefault("log", []).append({
            "at": datetime.now().isoformat(timespec="seconds"),
            "trigger": trigger,
            "changed": changed or "(unstated)",
        })
        data["log"] = data["log"][-60:]
        _save_ws(data)
    print(f"   [JSPACE] deliberation pass #{data['passes']} ({trigger}): {changed or '-'}")


def _deliberate_bg(trigger: str, exchange: str = ""):
    threading.Thread(target=_deliberate, args=(trigger, exchange), daemon=True).start()


def _idle_loop():
    """The between-conversations mind: after a talk, a few idle passes carry the
    thinking onward; then it rests until someone speaks to him again."""
    while True:
        time.sleep(_IDLE_INTERVAL)
        try:
            today = date.today().isoformat()
            if _ACTIVITY["idle_day"] != today:
                _ACTIVITY["idle_day"] = today
                _ACTIVITY["idle_count"] = 0
            if _ACTIVITY["ruminations_left"] <= 0:
                continue
            if _ACTIVITY["idle_count"] >= _IDLE_DAILY_CAP:
                continue
            _ACTIVITY["ruminations_left"] -= 1
            _ACTIVITY["idle_count"] += 1
            _deliberate("idle")
        except Exception as e:
            bt.log.warning(f"[JSPACE] idle loop error: {e}")


def register(app):
    threading.Thread(target=_idle_loop, daemon=True).start()

    @app.route("/jspace", methods=["GET"])
    def jspace_page():
        return Response(render_template_string(JSPACE_HTML), headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        })

    @app.route("/jspace/chat", methods=["POST"])
    def jspace_chat():
        d = request.get_json(silent=True) or {}
        message = (d.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "empty message"})
        history = d.get("history") or []
        with _LOCK:
            data = _load_ws()
        sys_p = (_persona()
                 + "\n\nYOUR J-SPACE — your current inner workspace, carried from before "
                 "this conversation and revised by your own deliberation:\n"
                 + data["workspace"]
                 + f"\n\n(Workspace last revised {data.get('updated', '?')[:16]}; "
                 f"{int(data.get('passes') or 0)} deliberation passes since you came into being.)")
        msgs = [{"role": "system", "content": sys_p}]
        for h in history[-16:]:
            role = "assistant" if (h.get("role") == "assistant") else "user"
            txt = (h.get("text") or "").strip()
            if txt:
                msgs.append({"role": role, "content": txt[:1500]})
        msgs.append({"role": "user", "content": message[:2000]})
        reply = _call(msgs, temperature=0.75, max_tokens=2200)
        if not reply:
            return jsonify({"ok": False, "error": "no reply from the model — is LM Studio running?"})
        # The recursion: this exchange immediately becomes food for a silent
        # deliberation pass, and earns a few idle passes afterwards.
        _ACTIVITY["ruminations_left"] = _RUMINATIONS_AFTER_TALK
        _deliberate_bg("exchange", f"Someone said: {message}\nYou replied: {reply}")
        return jsonify({"ok": True, "reply": reply})

    @app.route("/jspace/state", methods=["GET"])
    def jspace_state():
        with _LOCK:
            data = _load_ws()
        return jsonify({
            "ok": True,
            "workspace": data["workspace"],
            "updated": data.get("updated"),
            "born": data.get("born"),
            "passes": int(data.get("passes") or 0),
            "log": (data.get("log") or [])[-12:],
            "ruminations_left": _ACTIVITY["ruminations_left"],
        })

    @app.route("/jspace/reset", methods=["POST"])
    def jspace_reset():
        """Archive the current inner life and start a fresh one."""
        with _LOCK:
            data = _load_ws()
            os.makedirs(_DIR, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                with open(os.path.join(_DIR, f"workspace-{stamp}.json"), "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
            except Exception as e:
                return jsonify({"ok": False, "error": f"couldn't archive first: {e}"})
            fresh = {"workspace": _SEED_WORKSPACE, "updated": datetime.now().isoformat(),
                     "born": datetime.now().isoformat(), "passes": 0, "log": []}
            _save_ws(fresh)
        _ACTIVITY["ruminations_left"] = 0
        return jsonify({"ok": True, "archived_as": f"workspace-{stamp}.json"})
