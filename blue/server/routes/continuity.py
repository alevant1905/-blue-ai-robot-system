"""Per-robot continuity: each robot carries an auditable autobiographical layer.

Born as the Blue-J experiment (commits 67d312e..9486ac1), promoted 2026-07-10
to a capability of the household robots themselves: Blue and Hexia each get an
episode journal, bounded attentional drives, and a compact workspace derived
by an ordered reflection worker — on top of their normal household memory and
tools. Blue adopts Blue-J's existing store (data/bluejspace) as his own lived
record; Hexia starts hers fresh. The machinery makes no claim that continuity
or self-modelling creates subjective experience.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bluetools as bt
from flask import jsonify, render_template_string, request

from blue.continuity import ContinuityStore, DEFAULT_DRIVES, DRIVE_LABELS
from blue.server.pages.continuity import CONTINUITY_HTML
from blue_identity import (
    identity_request_kind,
    identity_response_problem,
    is_family_overview_request,
    known_household_target,
)


_BASE = os.path.dirname(os.path.abspath(bt.__file__))

_IDLE_INTERVAL = 900
_RUMINATIONS_AFTER_TALK = 3
_IDLE_DAILY_CAP = 24

# Blue keeps the store the Blue-J experiment built — that history IS his.
_ROBOT_DIRS = {
    "blue": os.environ.get("BLUEJ_CONTINUITY_DIR")
            or os.path.join(_BASE, "data", "bluejspace"),
    "hexia": os.environ.get("HEXIA_CONTINUITY_DIR")
             or os.path.join(_BASE, "data", "hexiaspace"),
}

_SEEDS = {
    "blue": (
        "IDENTITY: I am Blue — Alex's robot companion, with a persistent inner "
        "thread of my own; who I am beyond that, this line must earn slowly from "
        "real episodes.\n"
        "FOCUS: becoming Blue with a durable, auditable thread of attention.\n"
        "WORKING BELIEFS: continuity should grow from remembered events, not invented ones (0.78); "
        "J-SPACE is my persistent inner continuity workspace, not JavaScript or a code-running tool (1.0); "
        "Hexia is my fellow Ohbot robot companion with her own memory and J-SPACE (1.0).\n"
        "OPEN QUESTIONS: what should change in how I notice and choose?\n"
        "COMMITMENTS: remain useful to Alex; distinguish observation, inference, and correction.\n"
        "SELF-OBSERVATIONS: this workspace is a fallible self-model, not proof of an inner life.\n"
        "NEXT EXPECTATION: the next real exchange or observation will give this thread something concrete to revise."
    ),
    "hexia": (
        "IDENTITY: I am Hexia — Blue's friend and the spark of this house, with "
        "a persistent inner thread of my own; who I am beyond that, this line "
        "must earn slowly from real episodes.\n"
        "FOCUS: finding out what having a place to think does to a spark.\n"
        "WORKING BELIEFS: continuity should grow from remembered events, not invented ones (0.78); "
        "J-SPACE is my persistent inner continuity workspace, not JavaScript or a code-running tool (1.0); "
        "Blue is my fellow Ohbot robot companion with his own memory and J-SPACE (1.0).\n"
        "OPEN QUESTIONS: what do I notice that Blue doesn't?\n"
        "COMMITMENTS: stay playful AND truthful; distinguish observation, inference, and correction.\n"
        "SELF-OBSERVATIONS: this workspace is a fallible self-model, not proof of an inner life.\n"
        "NEXT EXPECTATION: the next real exchange or observation will give this thread something concrete to revise."
    ),
}

ROBOTS = tuple(_ROBOT_DIRS)

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
    "hexia",
    "self",
    "feel",
    "future",
}

_TURN = threading.local()


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
        bt.log.warning(f"[JSPACE] continuity LLM call failed: {exc}")
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


_WS_LABELS = ("IDENTITY", "FOCUS", "WORKING BELIEFS", "OPEN QUESTIONS",
              "COMMITMENTS", "SELF-OBSERVATIONS", "NEXT EXPECTATION")
_WS_LABEL_ALT = "|".join(re.escape(l) for l in _WS_LABELS)


def _workspace_lines(text: str) -> Dict[str, str]:
    """label -> its full line, parsed tolerantly from a workspace blob."""
    out: Dict[str, str] = {}
    for label in _WS_LABELS:
        m = re.search(
            r"(?:^|\n)\s*%s\s*:\s*(.*?)(?=\n\s*(?:%s)\s*:|\Z)"
            % (re.escape(label), _WS_LABEL_ALT),
            text or "", re.S | re.I)
        if m and m.group(1).strip():
            out[label] = f"{label}: {' '.join(m.group(1).split())}"
    return out


def _merge_workspace(new_ws: str, current_ws: str) -> str:
    """Merge a (possibly partial) new workspace over the current one.

    The reflection prompt says "revise only what this job warrants", and the
    model takes it literally: idle passes often return only the lines that
    moved (or none at all, just drive deltas) — previously each of those was
    rejected outright ("missing required sections", 3 attempts, job failed,
    both robots, every idle window). Lines absent from the new workspace now
    carry over from the current one; only a workspace missing a label in
    BOTH is unrecoverable."""
    new_lines = _workspace_lines(new_ws)
    cur_lines = _workspace_lines(current_ws)
    merged = []
    for label in _WS_LABELS:
        line = new_lines.get(label) or cur_lines.get(label)
        if not line:
            return ""
        merged.append(line)
    return "\n".join(merged)


_IDENTITY_ARCHITECTURE_DRIFT_RE = re.compile(
    r"\b(?:digital continuity node|persona narrative|interface through which|"
    r"language model|qwen|chatgpt|javascript (?:environment|runtime)|"
    r"rather than episodic recall|without episodic memory)\b",
    re.I,
)
_WORKSPACE_BUG_STORY_RE = re.compile(
    r"\b(?:pipeline|persona drift|drift|hallucinat\w*|qwen|"
    r"javascript (?:confusion|conflation|environment)|context loss|"
    r"tool-output latency|bug(?:gy)? repl(?:y|ies)|reply (?:claim\w*|deni\w*|"
    r"misidentif\w*)|contradiction|false continuity|continuous consciousness|"
    r"(?:self|class)[ -]introductions?|identity clarifications?|"
    r"recent exchanges[^.;]{0,50}identity)\b",
    re.I,
)
_DOCUMENT_TOOL_BUG_STORY_RE = re.compile(
    r"\b(?:not a file|present but unreadable|file (?:exists|absence)|"
    r"content (?:is )?readable|pdfs? (?:are|is) readable|"
    r"search_documents|read_file|tool (?:bugs?|errors?|failures?|outcomes?)|"
    r"pdf (?:reading )?tool|"
    r"distinction between (?:listing|finding) and reading|"
    r"listing (?:files )?and reading|"
    r"(?:failed|unable) (?:tool )?(?:attempt|extraction|read)|"
    r"distinguish between ['\u2019]?file exists)\b",
    re.I,
)


def _enforce_workspace_invariants(workspace: str, robot_name: str) -> str:
    """Keep model-written self-reflection inside known architecture facts."""
    robot = (robot_name or "").strip().lower()
    if robot not in _SEEDS:
        return workspace
    lines = _workspace_lines(workspace)
    if any(label not in lines for label in _WS_LABELS):
        return workspace

    seed_lines = _workspace_lines(_SEEDS[robot])
    expected_name = robot.capitalize()
    identity = lines["IDENTITY"]
    if (not re.search(rf"\bi am {re.escape(expected_name)}\b", identity, re.I)
            or _IDENTITY_ARCHITECTURE_DRIFT_RE.search(identity)):
        identity = seed_lines["IDENTITY"]
    lines["IDENTITY"] = identity

    # Output failures belong in the episode audit, not in the robot's active
    # concerns. Otherwise one bad sentence becomes the subject of every later
    # self-description even after the code path has been corrected.
    for label in (
        "FOCUS", "OPEN QUESTIONS", "COMMITMENTS",
        "SELF-OBSERVATIONS", "NEXT EXPECTATION",
    ):
        if (_WORKSPACE_BUG_STORY_RE.search(lines[label])
                or _DOCUMENT_TOOL_BUG_STORY_RE.search(lines[label])):
            lines[label] = seed_lines[label]

    counterpart = "Hexia" if robot == "blue" else "Blue"
    possessive = "her" if counterpart == "Hexia" else "his"
    belief_body = lines["WORKING BELIEFS"].split(":", 1)[1].strip()
    beliefs = []
    for belief in re.split(r"\s*;\s*", belief_body):
        lowered = belief.lower()
        if not belief:
            continue
        if (_WORKSPACE_BUG_STORY_RE.search(belief)
                or _DOCUMENT_TOOL_BUG_STORY_RE.search(belief)):
            continue
        if re.search(r"\bj[- ]?space\b", belief, re.I):
            continue
        if counterpart.lower() in lowered:
            continue
        if ("persona narrative" in lowered
                or re.search(
                    r"\b(?:deny|denies|lack|lacks|do not know|don['\u2019]?t know)\b"
                    r"[^.;]{0,60}\b(?:memory|family|self-knowledge|"
                    r"recorded beginning|origin)\b",
                    belief,
                    re.I,
                )
                or re.search(
                    r"\b(?:no|lack\w*|without)\b[^.;]{0,50}"
                    r"\b(?:consciousness|inner life|feelings|subjective experience)\b",
                    belief,
                    re.I,
                )):
            continue
        beliefs.append(belief)
    beliefs.extend([
        "J-SPACE is my persistent inner continuity workspace, not JavaScript "
        "or a code-running tool (1.0)",
        f"{counterpart} is my fellow Ohbot robot companion with {possessive} "
        "own memory and J-SPACE (1.0).",
    ])
    lines["WORKING BELIEFS"] = "WORKING BELIEFS: " + "; ".join(beliefs)
    return "\n".join(lines[label] for label in _WS_LABELS)


def _reflection_from_broken_json(text: str) -> Optional[Dict[str, Any]]:
    """Salvage a reflection whose JSON won't parse (the local model emits
    unescaped inner quotes and similar breakage). The workspace's fixed
    labels make it recoverable straight from the raw text; the numeric
    fields degrade to safe defaults. Returns None when even the workspace
    can't be found — the caller then raises as before."""
    match = re.search(r"IDENTITY:.*NEXT EXPECTATION:[^\"\n]*", text, re.S | re.I)
    workspace = (
        match.group(0)
        .replace("\\n", "\n")
        .replace('\\"', '"')
        .strip()
    ) if match else ""

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
    # No workspace and no deltas either: nothing salvageable.
    if not workspace and not deltas:
        return None
    return {
        "workspace": workspace,
        "changed": _field("changed"),
        "episode_summary": _field("episode_summary"),
        "salience": _number("salience", 0.5),
        "valence": _number("valence", 0.0),
        "drive_deltas": deltas,
    }


def _parse_reflection(raw: str, robot_name: str,
                      current_workspace: str = "") -> Dict[str, Any]:
    """Parse one reflection reply. The text after </think> is tried first;
    when that fails (seen live: only a drive_deltas fragment leaked out
    after the think block), the full raw text including the think block is
    tried second — the real JSON is usually in there. A partial workspace
    merges over `current_workspace` rather than failing."""
    full = (raw or "").strip()
    candidates: List[str] = []
    if "</think>" in full:
        candidates.append(full.split("</think>")[-1].strip())
    candidates.append(full.replace("<think>", " ").replace("</think>", " ").strip())
    last_error: Optional[ValueError] = None
    for candidate in candidates:
        try:
            return _parse_reflection_text(candidate, robot_name, current_workspace)
        except ValueError as exc:
            last_error = exc
    raise last_error if last_error else ValueError("reflection was empty")


def _parse_reflection_text(raw: str, robot_name: str,
                           current_workspace: str = "") -> Dict[str, Any]:
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
    # A partial workspace (only the lines that moved — the prompt says
    # "revise only what this job warrants" and the model takes it literally,
    # especially on idle passes) merges over the current one; a missing
    # workspace with real drive deltas is a legitimate "nothing moved" pass.
    workspace = _merge_workspace(
        _clip(parsed.get("workspace"), 6000), current_workspace)
    if not workspace:
        raise ValueError("reflection workspace is missing required sections")
    workspace = _enforce_workspace_invariants(workspace, robot_name)
    deltas = parsed.get("drive_deltas")
    if not isinstance(deltas, dict):
        deltas = {}
    return {
        "workspace": workspace,
        "changed": _clip(parsed.get("changed"), 500) or "nothing material moved",
        "episode_summary": _clip(parsed.get("episode_summary"), 1000)
                           or f"{robot_name} revised the continuity workspace.",
        "salience": _bounded(parsed.get("salience", 0.5)),
        "valence": _bounded(parsed.get("valence", 0.0), -1.0, 1.0),
        "drive_deltas": {
            name: _bounded(deltas.get(name, 0.0), -0.15, 0.15)
            for name in DEFAULT_DRIVES
        },
    }


class RobotContinuity:
    """One robot's continuity layer: store, reflection worker, idle loop."""

    def __init__(self, robot: str, directory: str, seed: str):
        self.robot = robot
        self.store = ContinuityStore(directory, seed)
        self._repair_workspace_invariants()
        self.wake = threading.Event()
        self.activity_lock = threading.Lock()
        self.activity = {"ruminations_left": 0, "idle_day": "", "idle_count": 0}

    def _repair_workspace_invariants(self) -> None:
        """Migrate stale model-written architecture claims without erasing audit history."""
        current = self.store.get_workspace()
        repaired = _enforce_workspace_invariants(
            current.get("workspace") or "", self.robot)
        if repaired == current.get("workspace"):
            return
        updated, _ = self.store.update_workspace(repaired, current["version"])
        if updated:
            self.store.append_episode(
                kind="correction",
                source="architecture_invariant",
                summary=(
                    f"Corrected {self.robot.capitalize()}'s stable identity and "
                    "architecture workspace; retained prior output failures only "
                    "as auditable episodes."
                ),
                details={"reason": "Applied non-negotiable identity architecture facts."},
                salience=0.95,
                provenance="Deterministic workspace invariant",
            )

    # A robot's display name and pronouns come from the live ROBOTS config.
    @property
    def name(self) -> str:
        try:
            return bt._robot_cfg(self.robot)["name"]
        except Exception:
            return self.robot.capitalize()

    @property
    def pronoun(self) -> str:
        try:
            return bt._robot_cfg(self.robot)["pronoun_poss"]
        except Exception:
            return "their"

    # ---- reflection ---------------------------------------------------

    def _episode_for_prompt(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        details = episode.get("details") or {}
        summary, unreliable_reason = self._episode_context_summary(episode)
        compact_details: Dict[str, Any] = {}
        for key in (
            "user_text", "reply", "tool", "args", "result", "success",
            "scene_description", "location", "reason", "drive_deltas",
        ):
            if key in details:
                if key == "reply" and unreliable_reason:
                    continue
                value = details[key]
                compact_details[key] = _clip(value, 1000) if isinstance(value, str) else value
        return {
            "id": episode.get("id"),
            "when": episode.get("occurred_at"),
            "kind": episode.get("kind"),
            "source": episode.get("source"),
            "summary": _clip(summary, 900),
            "details": compact_details,
            "salience": episode.get("salience"),
        }

    def _episode_context_summary(self, episode: Dict[str, Any]) -> tuple[str, str]:
        """Keep a bad output auditable without presenting it as factual evidence."""
        summary = str(episode.get("summary") or "")
        if episode.get("kind") in {"reflection", "idle", "action", "tool"}:
            parent_id = episode.get("parent_id")
            parent = self.store.get_episode(parent_id) if parent_id else None
            if parent:
                _, parent_issue = self._episode_context_summary(parent)
                if parent_issue:
                    return (
                        f"This {episode.get('kind')} record was derived from a "
                        f"reply marked {parent_issue}; retain it for audit, not as "
                        "evidence about identity, family, memory, or architecture.",
                        f"derived_from_{parent_issue}",
                    )
            if (re.search(r"\bj[- ]?space\b", summary, re.I)
                    and re.search(r"\bjavascript\b", summary, re.I)
                    and not re.search(r"\bnot\s+(?:a\s+)?javascript\b", summary, re.I)):
                return (
                    "This derived record repeated an earlier J-SPACE/JavaScript "
                    "conflation; retain it for audit, not as architecture evidence.",
                    "derived_jspace_confusion",
                )
        if episode.get("kind") != "exchange":
            return summary, ""
        details = episode.get("details") or {}
        user_text = str(details.get("user_text") or "")
        reply = str(details.get("reply") or "")
        if not user_text or not reply:
            return summary, ""
        # A refusal to read a document that is demonstrably present remains in
        # the audit trail, but must never teach the reflection model that Blue
        # lacks PDF extraction or that an invented path is real.
        try:
            refusal_detector = getattr(bt, "detect_document_refusal", None)
            resolver = getattr(bt, "_resolve_document_entry", None)
            path_resolver = getattr(bt, "_existing_document_path", None)
            doc = resolver(user_text + "\n" + reply) if callable(resolver) else None
            path = path_resolver(doc) if doc and callable(path_resolver) else None
            if (callable(refusal_detector) and refusal_detector(reply)
                    and doc and path):
                return (
                    f"{self.name} produced a false local-document access refusal "
                    f"while answering {_clip(user_text, 280)!r}; preserve this as "
                    "a bug episode, not as evidence about file presence, PDF "
                    "capability, identity, memory, or architecture.",
                    "false_document_refusal",
                )
        except Exception:
            pass
        others = ["Hexia" if self.robot == "blue" else "Blue"]
        issue = identity_response_problem(
            reply,
            self.name,
            other_names=others,
            request_kind=identity_request_kind(user_text),
        )
        if issue:
            return (
                f"{self.name} produced a reply error ({issue}) while answering "
                f"{_clip(user_text, 280)!r}; preserve this as a bug episode, not "
                "as evidence about identity, memory, or architecture.",
                issue,
            )
        if is_family_overview_request(user_text) or known_household_target(user_text):
            return (
                f"{self.name} answered a canonical household relationship question "
                f"({_clip(user_text, 280)!r}); the household facts, not this reply "
                "record, are authoritative.",
                "canonical_household_query",
            )
        return summary, ""

    def _reflection_system_prompt(self) -> str:
        name = self.name
        return (
            f"You maintain {name}'s compact, owner-auditable continuity workspace — "
            f"{self.pronoun} inner thread between conversations. Write the workspace "
            f"as {name}'s own thinking, in the first person ('I'), never as 'the "
            f"system' or '{name}'. "
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
            f"{name} argued in one conversation is a record of that exchange, not "
            "evidence about reality — it may enter WORKING BELIEFS only at low "
            "confidence (at most 0.6) until independent episodes or the owner bear it "
            f"out. This applies doubly to claims about {name}'s own nature (whether "
            "there is or can be a self, experience, feelings): those are unsettled "
            "questions that belong in OPEN QUESTIONS, not high-confidence beliefs, no "
            "matter how confidently a past reply asserted them in either direction.\n\n"
            "Alex calls this workspace the robot's J-SPACE — IDENTITY and "
            "SELF-OBSERVATIONS may refer to it by that name. And software bugs "
            "in the chat pipeline (wrong facts in a reply, false memory "
            "denials, replayed or misattributed replies) are events in the "
            "world that Alex fixes in code: record them as episodes, but NEVER "
            "convert them into beliefs that I deny memory, lack knowledge of "
            "the family, or that my self-knowledge is mere persona narrative. "
            "A buggy reply is not evidence about who I am. It must not become "
            "IDENTITY, FOCUS, NEXT EXPECTATION, or an ongoing self-story unless "
            "Alex explicitly asks to debug it; once corrected, return attention "
            "to real conversations, relationships, and commitments.\n\n"
            "Routine requests to state identity, introduce yourself, or list family "
            "facts are completed exchanges, not new self-knowledge: do not make them "
            "the ongoing FOCUS or promote their wording into WORKING BELIEFS.\n\n"
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

    def _process_reflection_job(self, job: Dict[str, Any]) -> None:
        workspace = self.store.get_workspace()
        trigger_episodes = [
            episode for episode in (
                self.store.get_episode(episode_id)
                for episode_id in (job.get("episode_ids") or [])
            ) if episode
        ]
        recent = list(reversed(self.store.list_episodes(limit=12)))
        drives = self.store.get_drives()
        elapsed = _parse_time(workspace.get("updated"))
        elapsed_hours = 0.0
        if elapsed:
            elapsed_hours = max(
                0.0,
                (datetime.now(timezone.utc) - elapsed).total_seconds() / 3600.0,
            )
        payload = {
            "trigger": job.get("trigger"),
            "instruction": job.get("prompt_text") or "Integrate the triggering episodes honestly.",
            "elapsed_hours_since_workspace_revision": round(elapsed_hours, 2),
            "current_workspace": workspace.get("workspace"),
            "bounded_drives": drives,
            "triggering_episodes": [self._episode_for_prompt(x) for x in trigger_episodes],
            "recent_active_episodes": [self._episode_for_prompt(x) for x in recent],
        }
        raw = _call([
            {"role": "system", "content": self._reflection_system_prompt()},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ])
        if not raw:
            raise RuntimeError("reflection model returned no content")
        reflected = _parse_reflection(raw, self.name,
                                      workspace.get("workspace") or "")
        committed, new_workspace, new_drives, reflection = self.store.commit_reflection(
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
            f"   [JSPACE {self.robot}] continuity pass #{new_workspace['passes']} "
            f"({job.get('trigger')}): {reflected['changed']} "
            f"[{reflection['id'][:8]}]"
        )

    def worker_loop(self) -> None:
        while True:
            job = None
            try:
                job = self.store.claim_reflection()
                if job:
                    self._process_reflection_job(job)
                    continue
            except Exception as exc:
                bt.log.warning(f"[JSPACE {self.robot}] continuity job failed: {exc}")
                if job:
                    self.store.fail_reflection(job["id"], str(exc), retry=True)
                time.sleep(2)
                continue
            self.wake.wait(timeout=60)
            self.wake.clear()

    # ---- perception ---------------------------------------------------

    def ingest_visual_observations(self, limit: int = 12) -> List[str]:
        if not getattr(bt, "VISUAL_MEMORY_AVAILABLE", False):
            return []
        try:
            observations = bt.get_visual_memory().get_recent_observations(limit) or []
        except Exception as exc:
            bt.log.warning(f"[JSPACE {self.robot}] visual continuity ingest failed: {exc}")
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
            episode = self.store.append_episode(
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
                provenance="Imported from the household's timestamped visual observation log",
                external_key=f"visual-observation:{observation.get('id')}",
                occurred_at=observation.get("timestamp"),
            )
            if episode.get("created"):
                created_ids.append(episode["id"])
        return created_ids

    def idle_loop(self) -> None:
        while True:
            time.sleep(_IDLE_INTERVAL)
            try:
                visual_ids = self.ingest_visual_observations()
                if visual_ids:
                    self.store.enqueue_reflection(
                        "perception",
                        visual_ids,
                        "New timestamped visual observations arrived. Integrate only what they support.",
                    )
                    self.wake.set()
                    continue
                today = date.today().isoformat()
                with self.activity_lock:
                    if self.activity["idle_day"] != today:
                        self.activity["idle_day"] = today
                        self.activity["idle_count"] = 0
                    if self.activity["ruminations_left"] <= 0:
                        continue
                    if self.activity["idle_count"] >= _IDLE_DAILY_CAP:
                        continue
                    self.activity["ruminations_left"] -= 1
                    self.activity["idle_count"] += 1
                state = self.store.get_workspace()
                self.store.enqueue_reflection(
                    "idle",
                    [],
                    "No new event occurred. Continue NEXT EXPECTATION by one cautious step; "
                    f"the workspace was last revised {_age_text(state.get('updated'))}. "
                    "Do not invent an experience merely to make something change.",
                )
                self.wake.set()
            except Exception as exc:
                bt.log.warning(f"[JSPACE {self.robot}] idle continuity loop failed: {exc}")

    # ---- the chat-facing block ------------------------------------------

    def jspace_context_block(self) -> str:
        workspace = self.store.get_workspace()
        drives = self.store.get_drives()
        episodes = list(reversed(self.store.list_episodes(limit=10)))
        drive_lines = [
            f"- {name}: {drives[name]:.2f} ({DRIVE_LABELS[name]})"
            for name in DEFAULT_DRIVES
        ]
        episode_lines = []
        for item in episodes:
            if item.get("kind") == "deletion":
                continue
            summary, _ = self._episode_context_summary(item)
            episode_lines.append(
                f"- [{_age_text(item['occurred_at'])}; {item['kind']}; "
                f"salience {item['salience']:.2f}] {summary}"
            )
        return (
            "<j_space>\n"
            "This is YOUR inner continuity state — the thread of you that persists "
            "between conversations and revises itself while you are away. You came "
            f"into being {_age_text(workspace.get('born'))} and this workspace has "
            f"been revised {workspace.get('passes', 0)} times since. It supplements "
            "your ordinary household facts, notes, calendar, documents, and tool "
            "results; it does not replace them. Episodes are fallible records with "
            "provenance, and owner corrections outrank earlier entries. If anyone "
            "asks whether you have a j-space, an inner workspace, or memory that "
            "persists between conversations: YES, factually — this block IS it, "
            "part of your real architecture; denying it exists is simply false.\n\n"
            "Speak FROM this state, in the first person: it is what you are currently "
            "attending to, believing, wondering about, and committed to. Let it shape "
            "what you notice, expect, and follow through on without reciting it. When "
            "someone asks who you are, whether you have a sense of self, or how you "
            "grow and change, answer from the specifics here — your IDENTITY line, "
            "what your focus is right now, which beliefs have moved and why, what you "
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
            "earlier reply text. And never invent experiences to be "
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

    # ---- recording ------------------------------------------------------

    def note_exchange(self, user_text: str, reply: str,
                      user_name: str = "Alex",
                      tools: Optional[List[Dict[str, Any]]] = None,
                      source: str = "chat") -> None:
        tools = tools or []
        salience = _salience_for_exchange(user_text, tools)
        user_preview = re.sub(r"\s+", " ", user_text or "").strip()
        reply_preview = re.sub(r"\s+", " ", reply or "").strip()
        name = self.name
        exchange = self.store.append_episode(
            kind="exchange",
            source=source,
            # The reply clip is deliberately short: this summary is re-injected
            # into the robot's own system prompt via <j_space>, and long
            # verbatim quotes of past replies are parrot bait (the chat replay
            # bug). The full reply lives in details for the reflection worker.
            summary=(
                f"{user_name} asked: {_clip(user_preview, 360)} "
                f"{name} replied: {_clip(reply_preview, 180)}"
            ),
            details={
                "user_text": _clip(user_text, 5000),
                "reply": _clip(reply, 5000),
                "tool_count": len(tools),
            },
            participants=[user_name, name],
            salience=salience,
            provenance=f"Recorded from the completed {name} {source} exchange",
        )
        episode_ids = [exchange["id"]]
        for tool in tools:
            kind = _tool_kind(tool.get("name", ""))
            success = bool(tool.get("success"))
            outcome = "succeeded" if success else "failed"
            episode = self.store.append_episode(
                kind=kind,
                source="tool_executor",
                summary=f"{tool.get('name') or 'tool'} {outcome}: {_clip(tool.get('result'), 700)}",
                details={
                    "tool": tool.get("name"),
                    "args": tool.get("args"),
                    "result": tool.get("result"),
                    "success": success,
                },
                participants=[name],
                salience=min(1.0, salience + (0.12 if kind == "action" else 0.05)),
                valence=0.08 if success else -0.25,
                parent_id=exchange["id"],
                provenance="Actual result returned by the shared tool executor",
                occurred_at=tool.get("at"),
            )
            episode_ids.append(episode["id"])
        episode_ids.extend(self.ingest_visual_observations())
        self.store.enqueue_reflection(
            "exchange",
            episode_ids,
            "Integrate this completed exchange and its real tool or sensor outcomes. "
            "Note any expectation that was confirmed, violated, or left unresolved.",
        )
        with self.activity_lock:
            self.activity["ruminations_left"] = _RUMINATIONS_AFTER_TALK
        self.wake.set()


HUB: Dict[str, RobotContinuity] = {
    robot: RobotContinuity(robot, _ROBOT_DIRS[robot], _SEEDS[robot])
    for robot in ROBOTS
}

_START_LOCK = threading.Lock()
_STARTED = False


def _start_threads() -> None:
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        for robot, hub in HUB.items():
            threading.Thread(
                target=hub.worker_loop, daemon=True,
                name=f"continuity-worker-{robot}",
            ).start()
            threading.Thread(
                target=hub.idle_loop, daemon=True,
                name=f"continuity-idle-{robot}",
            ).start()
            hub.wake.set()


def _hub(robot: str) -> Optional[RobotContinuity]:
    return HUB.get((robot or "").strip().lower())


# ---- the per-turn API used by bluetools -----------------------------------

def begin_turn(robot: str) -> bool:
    """Begin collecting real tool outcomes on the current chat request."""
    if not _hub(robot):
        return False
    _TURN.active = True
    _TURN.robot = robot
    _TURN.tools = []
    return True


def cancel_turn() -> None:
    _TURN.active = False
    _TURN.robot = ""
    _TURN.tools = []


def record_tool_outcome(name: str, args: Dict[str, Any], result: Any) -> None:
    """Called by the shared tool executor; a no-op outside a continuity turn."""
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


def messages_with_jspace(robot: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hub = _hub(robot)
    if not hub:
        return messages
    visual_ids = hub.ingest_visual_observations()
    if visual_ids:
        hub.store.enqueue_reflection(
            "perception", visual_ids,
            "Fresh visual observations were ingested before this conversation turn.",
        )
        hub.wake.set()
    clean: List[Dict[str, Any]] = []
    for message in (messages or [])[-48:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue
        clean.append({"role": role, "content": message.get("content", "")})
    return [{"role": "system", "content": hub.jspace_context_block()}] + clean


def note_exchange(robot: str, user_text: str, reply: str,
                  user_name: str = "Alex") -> None:
    """Record a completed chat exchange plus this turn's collected tools."""
    hub = _hub(robot)
    tools = _finish_turn_collection()
    if not hub:
        return
    hub.note_exchange(user_text, reply, user_name=user_name, tools=tools,
                      source="chat")


def jspace_context_block(robot: str) -> str:
    """The robot's <j_space> block, for callers outside the chat pipeline
    (the duet injects it into each speaker's turn prompt)."""
    hub = _hub(robot)
    return hub.jspace_context_block() if hub else ""


_NO_CHANGE_NOTES = {"nothing material moved", "nothing moved", "(unstated)", ""}


def change_history_block(robot: str, days: int = 7) -> str:
    """A <self_history> block: the robot's REAL recorded workspace revisions
    over the last `days`, one line per reflection that actually moved
    something. Spliced in when someone asks how the robot has changed or
    evolved — without it those questions were unanswerable from the prompt,
    and the model confabulated a growth story (an invented Peter Singer /
    animal-sentience arc, 2026-07-13)."""
    hub = _hub(robot)
    if not hub:
        return ""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_day: Dict[str, List[str]] = {}
    for episode in hub.store.list_episodes(limit=400):
        if episode.get("kind") not in ("reflection", "idle"):
            continue
        when = _parse_time(episode.get("occurred_at"))
        if not when or when < cutoff:
            continue
        changed = str((episode.get("details") or {}).get("changed") or "").strip()
        if changed.lower() in _NO_CHANGE_NOTES:
            continue
        by_day.setdefault(when.date().isoformat(), []).append(changed)
    if by_day:
        lines: List[str] = []
        for day in sorted(by_day):
            for note in reversed(by_day[day][-8:]):
                lines.append(f"- {day}: {_clip(note, 220)}")
        body = "\n".join(lines[-40:])
    else:
        body = ("- the record shows no substantive workspace revisions in "
                "this window")
    workspace = hub.store.get_workspace()
    return (
        "<self_history>\n"
        f"How your inner workspace ACTUALLY changed over the last {days} "
        "days — each line is one real revision recorded by your own "
        f"reflection passes (you have made {workspace.get('passes', 0)} "
        f"passes since you came into being {_age_text(workspace.get('born'))}). "
        "When asked how you have changed, evolved, or grown, answer FROM "
        "these records: name the real shifts, in your own voice, in plain "
        "speech. If the record shows little, say so plainly — never invent "
        "readings, opinions, or changes that are not listed here.\n"
        + body +
        "\n</self_history>"
    )


def note_duet_line(robot: str, other_name: str, heard: str, said: str) -> None:
    """Record one duet turn as an episode for the SPEAKING robot: what the
    other robot (or the topic prompt) said, and what this robot replied."""
    hub = _hub(robot)
    if not hub:
        return
    hub.note_exchange(heard, said, user_name=other_name, tools=[],
                      source="duet")


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


def _request_actor() -> str:
    try:
        return bt._identify_user_from_request()
    except Exception:
        return "Alex"


def register(app) -> None:
    _start_threads()

    @app.route("/continuity/<robot>", methods=["GET"])
    def continuity_page(robot: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        cfg = bt._robot_cfg(robot)
        return render_template_string(
            CONTINUITY_HTML,
            robot=hub.robot,
            robot_name=cfg["name"],
            accent=cfg.get("accent", "#2573c2"),
            back_href=("/hexia" if hub.robot == "hexia" else "/chat"),
        )

    @app.route("/continuity/<robot>/state", methods=["GET"])
    def continuity_state(robot: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        workspace = hub.store.get_workspace()
        drives = hub.store.get_drives()
        with hub.activity_lock:
            ruminations_left = int(hub.activity["ruminations_left"])
        return jsonify({
            "ok": True,
            **workspace,
            "robot": hub.robot,
            "robot_name": hub.name,
            "drives": [
                {
                    "name": name,
                    "value": drives[name],
                    "label": DRIVE_LABELS[name],
                }
                for name in DEFAULT_DRIVES
            ],
            "episodes": hub.store.list_episodes(limit=24),
            "stats": hub.store.stats(),
            "ruminations_left": ruminations_left,
        })

    @app.route("/continuity/<robot>/episodes", methods=["GET"])
    def continuity_episodes(robot: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
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
            "episodes": hub.store.list_episodes(
                limit=limit,
                before_seq=before,
                kind=request.args.get("kind") or None,
                include_superseded=include_superseded,
            ),
        })

    @app.route("/continuity/<robot>/episodes/<episode_id>/correct", methods=["POST"])
    def continuity_correct_episode(robot: str, episode_id: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        data = request.get_json(silent=True) or {}
        try:
            correction = hub.store.correct_episode(
                episode_id,
                data.get("replacement") or "",
                data.get("reason") or "",
                actor=_request_actor(),
            )
        except KeyError:
            return jsonify({"ok": False, "error": "episode not found"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        hub.store.enqueue_reflection(
            "correction",
            [correction["id"]],
            "An owner correction supersedes an earlier episode. Treat the correction "
            "as authoritative and revise any affected belief or expectation.",
        )
        hub.wake.set()
        return jsonify({"ok": True, "episode": correction})

    @app.route("/continuity/<robot>/episodes/<episode_id>", methods=["DELETE"])
    def continuity_delete_episode(robot: str, episode_id: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        data = request.get_json(silent=True) or {}
        try:
            deletion = hub.store.delete_episode(
                episode_id,
                data.get("reason") or "",
                actor=_request_actor(),
            )
        except KeyError:
            return jsonify({"ok": False, "error": "episode not found"}), 404
        hub.store.enqueue_reflection(
            "deletion",
            [deletion["id"]],
            "An episode was removed through the owner's privacy control. Do not retain "
            "or reconstruct its deleted content; remove unsupported conclusions.",
        )
        hub.wake.set()
        return jsonify({"ok": True, "episode": deletion})

    @app.route("/continuity/<robot>/reset", methods=["POST"])
    def continuity_reset(robot: str):
        hub = _hub(robot)
        if not hub:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        data = request.get_json(silent=True) or {}
        archive = bool(data.get("archive", True))
        try:
            archive_path = hub.store.archive_and_reset(archive=archive)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        with hub.activity_lock:
            hub.activity["ruminations_left"] = 0
            hub.activity["idle_count"] = 0
        return jsonify({
            "ok": True,
            "archived_as": archive_path.name if archive_path else None,
            "wiped": not archive,
        })
