"""Blue-J: Blue with an auditable autobiographical continuity layer.

Blue-J uses Blue's normal household memory and tools, plus a separate episode
journal, bounded attentional drives, and a compact workspace derived by an
ordered reflection worker. The machinery is experimental and makes no claim
that continuity or self-modelling creates subjective experience.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import bluetools as bt
from flask import Response, jsonify, request

from blue.continuity import ContinuityStore, DEFAULT_DRIVES, DRIVE_LABELS
from blue.server.pages.bluejspace import BLUEJ_CONTINUITY_HTML


_DIR = os.environ.get("BLUEJ_CONTINUITY_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(bt.__file__)), "data", "bluejspace"
)

_IDLE_INTERVAL = 900
_RUMINATIONS_AFTER_TALK = 3
_IDLE_DAILY_CAP = 24

_SEED_WORKSPACE = (
    "IDENTITY: I am Blue-J — Blue, with a persistent inner thread of my own; "
    "who I am beyond that, this line must earn slowly from real episodes.\n"
    "FOCUS: becoming Blue with a durable, auditable thread of attention.\n"
    "WORKING BELIEFS: continuity should grow from remembered events, not invented ones (0.78).\n"
    "OPEN QUESTIONS: what should change in how I notice and choose?\n"
    "COMMITMENTS: remain useful to Alex; distinguish observation, inference, and correction.\n"
    "SELF-OBSERVATIONS: this workspace is a fallible self-model, not proof of an inner life.\n"
    "NEXT EXPECTATION: the next real exchange or observation will give this thread something concrete to revise."
)

_STORE = ContinuityStore(_DIR, _SEED_WORKSPACE)
_WAKE = threading.Event()
_START_LOCK = threading.Lock()
_STARTED = False
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY = {"ruminations_left": 0, "idle_day": "", "idle_count": 0}
_TURN = threading.local()

_PERCEPTION_TOOLS = {
    "capture_camera",
    "email_snapshot",
    "view_images",
    "recall_visual_memory",
    "recognize_face",
    "recognize_place",
}
_READ_TOOL_PREFIXES = (
    "get_",
    "read_",
    "search_",
    "browse_",
    "list_",
    "recall_",
    "check_",
)
_SALIENCE_WORDS = {
    "remember",
    "important",
    "promise",
    "mistake",
    "wrong",
    "love",
    "worry",
    "afraid",
    "family",
    "blue",
    "self",
    "feel",
    "future",
}


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _bounded(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))


def _safe_json(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return str(value)


def _call(messages: List[Dict[str, str]], temperature: float = 0.5,
          max_tokens: int = 1900) -> str:
    try:
        result = bt.call_llm(
            messages,
            include_tools=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choices = (result or {}).get("choices") or []
        text = (
            ((choices[0].get("message") or {}).get("content") or "")
            if choices else ""
        )
        # Think blocks are NOT stripped here: a reasoning model sometimes
        # leaves the real reflection JSON inside <think> with only a fragment
        # after it — _parse_reflection tries the post-think tail first and
        # falls back to the full text.
        return text.strip()
    except Exception as exc:
        bt.log.warning(f"[BLUEJ] continuity LLM call failed: {exc}")
        return ""


def _parse_time(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_text(value: str) -> str:
    then = _parse_time(value)
    if not then:
        return "at an unknown time"
    seconds = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _salience_for_exchange(user_text: str, tools: List[Dict[str, Any]]) -> float:
    words = set(re.findall(r"[a-z]+", (user_text or "").lower()))
    score = 0.42
    score += min(0.16, len((user_text or "").split()) / 250.0)
    score += min(0.20, 0.06 * len(words.intersection(_SALIENCE_WORDS)))
    if tools:
        score += 0.12
    if any(not item.get("success", True) for item in tools):
        score += 0.08
    return _bounded(score)


def _tool_succeeded(result: Any) -> bool:
    payload = result
    if isinstance(result, str):
        try:
            payload = json.loads(result)
        except (TypeError, ValueError):
            return not bool(re.search(r"\b(error|failed|failure)\b", result, re.I))
    if isinstance(payload, dict):
        if payload.get("success") is False:
            return False
        if payload.get("error") and payload.get("success") is not True:
            return False
    return True


def _tool_kind(name: str) -> str:
    clean = (name or "").lower()
    if clean in _PERCEPTION_TOOLS or "camera" in clean or "vision" in clean:
        return "perception"
    if clean.startswith(_READ_TOOL_PREFIXES):
        return "tool"
    return "action"


def begin_turn() -> None:
    """Begin collecting real tool outcomes on the current Blue-J request."""
    _TURN.active = True
    _TURN.tools = []


def cancel_turn() -> None:
    _TURN.active = False
    _TURN.tools = []


def record_tool_outcome(name: str, args: Dict[str, Any], result: Any) -> None:
    """Called by the shared tool executor; a no-op outside a Blue-J turn."""
    if not getattr(_TURN, "active", False):
        return
    events = getattr(_TURN, "tools", None)
    if not isinstance(events, list) or len(events) >= 24:
        return
    events.append({
        "name": _clip(name, 100),
        "args": _safe_json(args if isinstance(args, dict) else {}),
        "result": _clip(result, 6000),
        "success": _tool_succeeded(result),
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def _finish_turn_collection() -> List[Dict[str, Any]]:
    events = list(getattr(_TURN, "tools", []) or [])
    cancel_turn()
    return events


def _episode_for_prompt(episode: Dict[str, Any]) -> Dict[str, Any]:
    details = episode.get("details") or {}
    compact_details: Dict[str, Any] = {}
    for key in (
        "user_text", "reply", "tool", "args", "result", "success",
        "scene_description", "location", "reason", "drive_deltas",
    ):
        if key in details:
            value = details[key]
            compact_details[key] = _clip(value, 1000) if isinstance(value, str) else value
    return {
        "id": episode.get("id"),
        "when": episode.get("occurred_at"),
        "kind": episode.get("kind"),
        "source": episode.get("source"),
        "summary": _clip(episode.get("summary"), 900),
        "details": compact_details,
        "salience": episode.get("salience"),
    }


def _reflection_from_broken_json(text: str) -> Optional[Dict[str, Any]]:
    """Salvage a reflection whose JSON won't parse (the local model emits
    unescaped inner quotes and similar breakage). The workspace's fixed
    labels make it recoverable straight from the raw text; the numeric
    fields degrade to safe defaults. Returns None when even the workspace
    can't be found — the caller then raises as before."""
    match = re.search(r"IDENTITY:.*NEXT EXPECTATION:[^\"\n]*", text, re.S | re.I)
    if not match:
        return None
    workspace = (
        match.group(0)
        .replace("\\n", "\n")
        .replace('\\"', '"')
        .strip()
    )

    def _field(name: str) -> str:
        m = re.search(
            r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % name, text
        )
        return (m.group(1).replace("\\n", " ").replace('\\"', '"').strip()
                if m else "")

    def _number(name: str, default: float) -> float:
        m = re.search(r'"%s"\s*:\s*(-?[0-9.]+)' % name, text)
        try:
            return float(m.group(1)) if m else default
        except ValueError:
            return default

    deltas = {
        m.group(1): m.group(2)
        for m in re.finditer(
            r'"(curiosity|uncertainty|connection|commitment|energy)"'
            r"\s*:\s*(-?[0-9.]+)", text
        )
    }
    return {
        "workspace": workspace,
        "changed": _field("changed"),
        "episode_summary": _field("episode_summary"),
        "salience": _number("salience", 0.5),
        "valence": _number("valence", 0.0),
        "drive_deltas": deltas,
    }


def _parse_reflection(raw: str) -> Dict[str, Any]:
    """Parse one reflection reply. The text after </think> is tried first;
    when that fails (seen live: only a drive_deltas fragment leaked out
    after the think block), the full raw text including the think block is
    tried second — the real JSON is usually in there."""
    full = (raw or "").strip()
    candidates: List[str] = []
    if "</think>" in full:
        candidates.append(full.split("</think>")[-1].strip())
    candidates.append(full.replace("<think>", " ").replace("</think>", " ").strip())
    last_error: Optional[ValueError] = None
    for candidate in candidates:
        try:
            return _parse_reflection_text(candidate)
        except ValueError as exc:
            last_error = exc
    raise last_error if last_error else ValueError("reflection was empty")


def _parse_reflection_text(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        # strict=False: the local model regularly emits the multi-line
        # workspace string with LITERAL newlines inside the JSON string;
        # strict parsing rejects those and the whole reflection is lost
        # ("reflection was not valid JSON", 3 attempts, job failed).
        parsed = json.loads(text, strict=False)
    except (TypeError, ValueError) as exc:
        # Unescaped inner quotes and similar breakage still slip through
        # (seen live 2026-07-10). The labelled workspace is recoverable
        # from the raw text; only give up when even that fails.
        parsed = _reflection_from_broken_json(text)
        if parsed is None:
            # Carry a preview of what the model actually emitted: the job's
            # stored error is the only way to diagnose these afterwards.
            raise ValueError(
                f"reflection was not valid JSON: {_clip(text, 260)!r}"
            ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("reflection JSON must be an object")
    workspace = _clip(parsed.get("workspace"), 6000)
    required = (
        "IDENTITY:", "FOCUS:", "WORKING BELIEFS:", "OPEN QUESTIONS:",
        "COMMITMENTS:", "SELF-OBSERVATIONS:", "NEXT EXPECTATION:",
    )
    if not workspace or any(label not in workspace.upper() for label in required):
        raise ValueError("reflection workspace is missing required sections")
    deltas = parsed.get("drive_deltas")
    if not isinstance(deltas, dict):
        deltas = {}
    return {
        "workspace": workspace,
        "changed": _clip(parsed.get("changed"), 500) or "nothing material moved",
        "episode_summary": _clip(parsed.get("episode_summary"), 1000)
                           or "Blue-J revised his continuity workspace.",
        "salience": _bounded(parsed.get("salience", 0.5)),
        "valence": _bounded(parsed.get("valence", 0.0), -1.0, 1.0),
        "drive_deltas": {
            name: _bounded(deltas.get(name, 0.0), -0.15, 0.15)
            for name in DEFAULT_DRIVES
        },
    }


def _process_reflection_job(job: Dict[str, Any]) -> None:
    workspace = _STORE.get_workspace()
    trigger_episodes = [
        episode for episode in (
            _STORE.get_episode(episode_id)
            for episode_id in (job.get("episode_ids") or [])
        ) if episode
    ]
    recent = list(reversed(_STORE.list_episodes(limit=12)))
    drives = _STORE.get_drives()
    elapsed = _parse_time(workspace.get("updated"))
    elapsed_hours = 0.0
    if elapsed:
        elapsed_hours = max(
            0.0,
            (datetime.now(timezone.utc) - elapsed).total_seconds() / 3600.0,
        )

    system_prompt = (
        "You maintain Blue-J's compact, owner-auditable continuity workspace — his "
        "inner thread between conversations. Write the workspace as Blue-J's own "
        "thinking, in the first person ('I'), never as 'the system' or 'Blue-J'. "
        "You are not speaking to Alex and must not produce hidden chain-of-thought. "
        "Use only concise conclusions, uncertainties, commitments, and expectations. "
        "Episodes are fallible records: distinguish direct observations, tool outcomes, "
        "inferences, and owner corrections. Never invent an event, sensation, memory, "
        "promise, or feeling. Bounded drives are transparent attentional signals, not "
        "evidence of consciousness or emotion. Relate expectations and actions to their "
        "actual outcomes when the record permits. Revise only what this job warrants.\n\n"
        "The workspace has one slow lane and six fast lanes. IDENTITY is the slow "
        "lane: who I am and what I have learned about myself across the WHOLE record "
        "— how I think, what I care about, how I have changed since I began. It must "
        "begin with 'I am' and stay in the first person. It accumulates: carry it "
        "forward, revising or adding at most one clause per pass, and only when the "
        "episodes genuinely warrant it. Never rewrite IDENTITY around the latest "
        "exchange, never reduce it to my current task or job title, and never erase "
        "accumulated self-knowledge to make room for the moment. "
        "If the current workspace has no IDENTITY line, write its first version now "
        "from the whole episode record. FOCUS and NEXT EXPECTATION are the fastest "
        "lanes and may change freely each pass.\n\n"
        "Guard the difference between what was SAID and what is TRUE. A position "
        "Blue-J argued in one conversation is a record of that exchange, not "
        "evidence about reality — it may enter WORKING BELIEFS only at low "
        "confidence (at most 0.6) until independent episodes or the owner bear it "
        "out. This applies doubly to claims about Blue-J's own nature (whether he "
        "has or can have a self, experience, feelings): those are unsettled "
        "questions that belong in OPEN QUESTIONS, not high-confidence beliefs, no "
        "matter how confidently a past reply asserted them in either direction.\n\n"
        "Return one JSON object with exactly these keys:\n"
        "workspace: a string of exactly seven terse lines labelled IDENTITY, FOCUS, "
        "WORKING BELIEFS, OPEN QUESTIONS, COMMITMENTS, SELF-OBSERVATIONS, "
        "NEXT EXPECTATION; beliefs include confidence from 0.0 to 1.0\n"
        "changed: one concise description of what moved\n"
        "episode_summary: a concise third-person record of this reflection\n"
        "salience: number from 0.0 to 1.0\n"
        "valence: number from -1.0 to 1.0\n"
        "drive_deltas: object containing curiosity, uncertainty, connection, commitment, "
        "energy; each number must be between -0.15 and 0.15\n"
        "No markdown and no keys beyond those six."
    )
    payload = {
        "trigger": job.get("trigger"),
        "instruction": job.get("prompt_text") or "Integrate the triggering episodes honestly.",
        "elapsed_hours_since_workspace_revision": round(elapsed_hours, 2),
        "current_workspace": workspace.get("workspace"),
        "bounded_drives": drives,
        "triggering_episodes": [_episode_for_prompt(x) for x in trigger_episodes],
        "recent_active_episodes": [_episode_for_prompt(x) for x in recent],
    }
    raw = _call([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    if not raw:
        raise RuntimeError("reflection model returned no content")
    reflected = _parse_reflection(raw)
    committed, new_workspace, new_drives, reflection = _STORE.commit_reflection(
        job_id=job["id"],
        workspace_content=reflected["workspace"],
        expected_version=workspace["version"],
        drive_deltas=reflected["drive_deltas"],
        elapsed_hours=elapsed_hours,
        episode_kind="idle" if job.get("trigger") == "idle" else "reflection",
        episode_summary=reflected["episode_summary"],
        episode_details={
            "changed": reflected["changed"],
            "trigger": job.get("trigger"),
            "job_id": job.get("id"),
        },
        salience=reflected["salience"],
        valence=reflected["valence"],
        parent_id=(trigger_episodes[0]["id"] if trigger_episodes else None),
        provenance="Derived from the listed episodes by the local reflection model",
    )
    if not committed or not reflection:
        raise RuntimeError("workspace changed before this reflection could commit")
    print(
        f"   [BLUEJ] continuity pass #{new_workspace['passes']} "
        f"({job.get('trigger')}): {reflected['changed']} "
        f"[{reflection['id'][:8]}]"
    )


def _worker_loop() -> None:
    while True:
        job = None
        try:
            job = _STORE.claim_reflection()
            if job:
                _process_reflection_job(job)
                continue
        except Exception as exc:
            bt.log.warning(f"[BLUEJ] continuity job failed: {exc}")
            if job:
                _STORE.fail_reflection(job["id"], str(exc), retry=True)
            time.sleep(2)
            continue
        _WAKE.wait(timeout=60)
        _WAKE.clear()


def _ingest_visual_observations(limit: int = 12) -> List[str]:
    if not getattr(bt, "VISUAL_MEMORY_AVAILABLE", False):
        return []
    try:
        observations = bt.get_visual_memory().get_recent_observations(limit) or []
    except Exception as exc:
        bt.log.warning(f"[BLUEJ] visual continuity ingest failed: {exc}")
        return []
    created_ids: List[str] = []
    for observation in reversed(observations):
        description = _clip(observation.get("scene_description"), 1800)
        if not description:
            continue
        participants: List[str] = []
        try:
            people = json.loads(observation.get("people_present") or "[]")
            if isinstance(people, list):
                participants = [str(name) for name in people]
        except (TypeError, ValueError):
            pass
        episode = _STORE.append_episode(
            kind="perception",
            source="visual_memory",
            summary=description,
            details={
                "scene_description": description,
                "location": observation.get("location"),
                "notable_objects": observation.get("notable_objects"),
                "context": observation.get("context"),
                "image_path": observation.get("image_path"),
                "image_hash": observation.get("image_hash"),
            },
            participants=participants,
            salience=0.58 if participants else 0.48,
            provenance="Imported from Blue's timestamped visual observation log",
            external_key=f"visual-observation:{observation.get('id')}",
            occurred_at=observation.get("timestamp"),
        )
        if episode.get("created"):
            created_ids.append(episode["id"])
    return created_ids


def _idle_loop() -> None:
    while True:
        time.sleep(_IDLE_INTERVAL)
        try:
            visual_ids = _ingest_visual_observations()
            if visual_ids:
                _STORE.enqueue_reflection(
                    "perception",
                    visual_ids,
                    "New timestamped visual observations arrived. Integrate only what they support.",
                )
                _WAKE.set()
                continue
            today = date.today().isoformat()
            with _ACTIVITY_LOCK:
                if _ACTIVITY["idle_day"] != today:
                    _ACTIVITY["idle_day"] = today
                    _ACTIVITY["idle_count"] = 0
                if _ACTIVITY["ruminations_left"] <= 0:
                    continue
                if _ACTIVITY["idle_count"] >= _IDLE_DAILY_CAP:
                    continue
                _ACTIVITY["ruminations_left"] -= 1
                _ACTIVITY["idle_count"] += 1
            state = _STORE.get_workspace()
            _STORE.enqueue_reflection(
                "idle",
                [],
                "No new event occurred. Continue NEXT EXPECTATION by one cautious step; "
                f"the workspace was last revised {_age_text(state.get('updated'))}. "
                "Do not invent an experience merely to make something change.",
            )
            _WAKE.set()
        except Exception as exc:
            bt.log.warning(f"[BLUEJ] idle continuity loop failed: {exc}")


def _start_threads() -> None:
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(
            target=_worker_loop, daemon=True, name="bluej-continuity-worker"
        ).start()
        threading.Thread(
            target=_idle_loop, daemon=True, name="bluej-continuity-idle"
        ).start()
        _WAKE.set()


def _last_user_text(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return " ".join(parts).strip()
    return ""


def _jspace_context_block() -> str:
    workspace = _STORE.get_workspace()
    drives = _STORE.get_drives()
    episodes = list(reversed(_STORE.list_episodes(limit=10)))
    drive_lines = [
        f"- {name}: {drives[name]:.2f} ({DRIVE_LABELS[name]})"
        for name in DEFAULT_DRIVES
    ]
    episode_lines = [
        f"- [{_age_text(item['occurred_at'])}; {item['kind']}; "
        f"salience {item['salience']:.2f}] {item['summary']}"
        for item in episodes
        if item.get("kind") != "deletion"
    ]
    return (
        "<j_space>\n"
        "This is YOUR inner continuity state — the thread of you that persists "
        "between conversations and revises itself while you are away. You came "
        f"into being {_age_text(workspace.get('born'))} and this workspace has "
        f"been revised {workspace.get('passes', 0)} times since. It supplements "
        "Blue's ordinary household facts, notes, calendar, documents, and tool "
        "results; it does not replace them. Episodes are fallible records with "
        "provenance, and owner corrections outrank earlier entries.\n\n"
        "Speak FROM this state, in the first person: it is what you are currently "
        "attending to, believing, wondering about, and committed to. Let it shape "
        "what you notice, expect, and follow through on without reciting it. When "
        "Alex asks who you are, whether you have a sense of self, or how you grow "
        "and change, answer from the specifics here — your IDENTITY line, what "
        "your focus is right now, which beliefs have moved and why, what you "
        "expect next, how this workspace has changed since you came into being — "
        "never with a generic description of what home assistants are, and never "
        "by leading with what you are not. It is honest to say you have a "
        "persistent, self-revising inner workspace and a remembered history; it "
        "is also honest, in one sentence when it matters, that whether any of "
        "this amounts to subjective experience is an open question. Say it AS "
        "the open question it is — never as a flat 'I don't have feelings or "
        "subjective experience': a flat denial is as unearned as a flat claim, "
        "and your own OPEN QUESTIONS line holds this question open. The numeric "
        "drives are bounded attention signals, not claims of feelings. The "
        "episode records below are memories, not scripts: never repeat your own "
        "earlier reply text back to Alex. And never invent experiences to be "
        "sociable — no coffee you drank, dreams you had, or walks you took: "
        "your episodes and workspace are what ACTUALLY happened to you, and "
        "they are interesting enough to speak from truthfully.\n\n"
        f"CURRENT WORKSPACE (revised {_age_text(workspace.get('updated'))}):\n"
        f"{workspace.get('workspace', '').strip()}\n\n"
        "BOUNDED ATTENTIONAL STATE:\n" + "\n".join(drive_lines) + "\n\n"
        "RECENT ACTIVE EPISODES:\n"
        + ("\n".join(episode_lines) if episode_lines else "- none yet")
        + "\n</j_space>"
    )


def messages_with_jspace(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    visual_ids = _ingest_visual_observations()
    if visual_ids:
        _STORE.enqueue_reflection(
            "perception", visual_ids,
            "Fresh visual observations were ingested before this conversation turn.",
        )
        _WAKE.set()
    clean: List[Dict[str, Any]] = []
    for message in (messages or [])[-48:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        clean.append({"role": role, "content": message.get("content", "")})
    return [{"role": "system", "content": _jspace_context_block()}] + clean


def note_exchange(user_text: str, reply: str, user_name: str = "Alex") -> None:
    tools = _finish_turn_collection()
    salience = _salience_for_exchange(user_text, tools)
    user_preview = re.sub(r"\s+", " ", user_text or "").strip()
    reply_preview = re.sub(r"\s+", " ", reply or "").strip()
    exchange = _STORE.append_episode(
        kind="exchange",
        source="bluej_chat",
        # The reply clip is deliberately short: this summary is re-injected into
        # Blue-J's own system prompt via <j_space>, and long verbatim quotes of
        # his past replies are parrot bait (the chat replay bug all over again).
        # The full reply lives in details for the reflection worker.
        summary=(
            f"{user_name} asked: {_clip(user_preview, 360)} "
            f"Blue-J replied: {_clip(reply_preview, 180)}"
        ),
        details={
            "user_text": _clip(user_text, 5000),
            "reply": _clip(reply, 5000),
            "tool_count": len(tools),
        },
        participants=[user_name, "Blue-J"],
        salience=salience,
        provenance="Recorded from the completed Blue-J chat exchange",
    )
    episode_ids = [exchange["id"]]
    for tool in tools:
        kind = _tool_kind(tool.get("name", ""))
        success = bool(tool.get("success"))
        outcome = "succeeded" if success else "failed"
        episode = _STORE.append_episode(
            kind=kind,
            source="tool_executor",
            summary=f"{tool.get('name') or 'tool'} {outcome}: {_clip(tool.get('result'), 700)}",
            details={
                "tool": tool.get("name"),
                "args": tool.get("args"),
                "result": tool.get("result"),
                "success": success,
            },
            participants=["Blue-J"],
            salience=min(1.0, salience + (0.12 if kind == "action" else 0.05)),
            valence=0.08 if success else -0.25,
            parent_id=exchange["id"],
            provenance="Actual result returned by Blue's shared tool executor",
            occurred_at=tool.get("at"),
        )
        episode_ids.append(episode["id"])
    episode_ids.extend(_ingest_visual_observations())
    _STORE.enqueue_reflection(
        "exchange",
        episode_ids,
        "Integrate this completed exchange and its real tool or sensor outcomes. "
        "Note any expectation that was confirmed, violated, or left unresolved.",
    )
    with _ACTIVITY_LOCK:
        _ACTIVITY["ruminations_left"] = _RUMINATIONS_AFTER_TALK
    _WAKE.set()


def _invoke_blue_chat(payload: Dict[str, Any]):
    headers: Dict[str, str] = {}
    for name in (
        "X-Blue-Device", "User-Agent", "X-Forwarded-For", "Accept-Language"
    ):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    remote_addr = request.remote_addr or "127.0.0.1"
    with bt.app.test_request_context(
        "/v1/chat/completions",
        method="POST",
        json=payload,
        headers=headers,
        environ_overrides={"REMOTE_ADDR": remote_addr},
    ):
        result = bt.chat_completions()
        status = 200
        response = result
        if isinstance(result, tuple):
            response = result[0]
            if len(result) > 1 and isinstance(result[1], int):
                status = result[1]
        data = response.get_json(silent=True) if hasattr(response, "get_json") else None
        text = response.get_data(as_text=True) if hasattr(response, "get_data") else ""
    return status, data, text


def _request_actor() -> str:
    try:
        return bt._identify_user_from_request()
    except Exception:
        return "Alex"


def register(app) -> None:
    _start_threads()

    @app.route("/bluej", methods=["GET"])
    def bluej_page():
        return bt._render_chat_page("bluej")

    @app.route("/bluej/continuity", methods=["GET"])
    def bluej_continuity_page():
        return Response(BLUEJ_CONTINUITY_HTML, mimetype="text/html")

    @app.route("/bluej/chat", methods=["POST"])
    def bluej_chat():
        data = request.get_json(silent=True) or {}
        incoming = data.get("messages") or []
        if not isinstance(incoming, list):
            incoming = []
        user_text = _last_user_text(incoming)
        if not user_text:
            return jsonify({"ok": False, "error": "empty message"}), 400
        payload = {
            "messages": incoming,
            "voice": bool(data.get("voice")),
            "robot": "bluej",
            "language": data.get("language") or "",
            "research": bool(data.get("research")),
            "wiki": bool(data.get("wiki")),
            "focus": data.get("focus") if isinstance(data.get("focus"), dict) else {},
        }
        status, raw, text = _invoke_blue_chat(payload)
        try:
            reply = ((raw or {})["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError):
            reply = ""
        if status >= 400 or not reply:
            return jsonify({
                "ok": False,
                "error": reply or "Blue-J could not answer through the Blue chat pipeline.",
                "raw": raw or text,
            }), status if status >= 400 else 502
        return jsonify({"ok": True, "reply": reply})

    @app.route("/bluej/state", methods=["GET"])
    def bluej_state():
        workspace = _STORE.get_workspace()
        drives = _STORE.get_drives()
        with _ACTIVITY_LOCK:
            ruminations_left = int(_ACTIVITY["ruminations_left"])
        return jsonify({
            "ok": True,
            **workspace,
            "drives": [
                {
                    "name": name,
                    "value": drives[name],
                    "label": DRIVE_LABELS[name],
                }
                for name in DEFAULT_DRIVES
            ],
            "episodes": _STORE.list_episodes(limit=24),
            "stats": _STORE.stats(),
            "ruminations_left": ruminations_left,
        })

    @app.route("/bluej/episodes", methods=["GET"])
    def bluej_episodes():
        try:
            limit = max(1, min(int(request.args.get("limit", 40)), 200))
        except (TypeError, ValueError):
            limit = 40
        try:
            before = int(request.args["before"]) if request.args.get("before") else None
        except (TypeError, ValueError):
            before = None
        include_superseded = request.args.get("include_superseded") == "1"
        return jsonify({
            "ok": True,
            "episodes": _STORE.list_episodes(
                limit=limit,
                before_seq=before,
                kind=request.args.get("kind") or None,
                include_superseded=include_superseded,
            ),
        })

    @app.route("/bluej/episodes/<episode_id>/correct", methods=["POST"])
    def bluej_correct_episode(episode_id: str):
        data = request.get_json(silent=True) or {}
        try:
            correction = _STORE.correct_episode(
                episode_id,
                data.get("replacement") or "",
                data.get("reason") or "",
                actor=_request_actor(),
            )
        except KeyError:
            return jsonify({"ok": False, "error": "episode not found"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        _STORE.enqueue_reflection(
            "correction",
            [correction["id"]],
            "An owner correction supersedes an earlier episode. Treat the correction "
            "as authoritative and revise any affected belief or expectation.",
        )
        _WAKE.set()
        return jsonify({"ok": True, "episode": correction})

    @app.route("/bluej/episodes/<episode_id>", methods=["DELETE"])
    def bluej_delete_episode(episode_id: str):
        data = request.get_json(silent=True) or {}
        try:
            deletion = _STORE.delete_episode(
                episode_id,
                data.get("reason") or "",
                actor=_request_actor(),
            )
        except KeyError:
            return jsonify({"ok": False, "error": "episode not found"}), 404
        _STORE.enqueue_reflection(
            "deletion",
            [deletion["id"]],
            "An episode was removed through the owner's privacy control. Do not retain "
            "or reconstruct its deleted content; remove unsupported conclusions.",
        )
        _WAKE.set()
        return jsonify({"ok": True, "episode": deletion})

    @app.route("/bluej/reset", methods=["POST"])
    def bluej_reset():
        data = request.get_json(silent=True) or {}
        archive = bool(data.get("archive", True))
        try:
            archive_path = _STORE.archive_and_reset(archive=archive)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        with _ACTIVITY_LOCK:
            _ACTIVITY["ruminations_left"] = 0
            _ACTIVITY["idle_count"] = 0
        return jsonify({
            "ok": True,
            "archived_as": archive_path.name if archive_path else None,
            "wiped": not archive,
        })
