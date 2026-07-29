"""Server-side neural text-to-speech for every robot.

The chat pages still retain the browser's built-in Web Speech voices as an
offline fallback.  This module adds a device-independent catalog backed by
Microsoft Edge's online neural TTS service and stores one selection per robot,
so Blue, Hexia, and Casper sound the same from every browser.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List

from flask import Response, jsonify, request

try:
    import edge_tts
except Exception:  # pragma: no cover - exercised by the graceful API fallback
    edge_tts = None


_ROBOTS = {"blue", "hexia", "pico"}
_SUPPORTED_LANGUAGE_PREFIXES = {"en", "fr", "ru", "el", "da"}
_PREFS_PATH = os.environ.get("BLUE_TTS_PREFS", os.path.join("data", "voices.json"))
_VOICE_TTL_SECONDS = 6 * 60 * 60
_MAX_TEXT_CHARS = 5000
_AUDIO_CACHE_LIMIT = 48

# A distinct, natural default for each robot.  Nothing is written until the
# user changes a choice; these defaults simply make neural speech active after
# the feature is installed.
_DEFAULT_PREFERENCES = {
    "blue": {"provider": "edge", "voice": "en-CA-LiamNeural"},
    "hexia": {"provider": "edge", "voice": "en-US-AvaMultilingualNeural"},
    "pico": {"provider": "edge", "voice": "en-GB-RyanNeural"},
}

_voice_lock = threading.RLock()
_voice_catalog: List[Dict[str, Any]] = []
_voice_catalog_at = 0.0

_prefs_lock = threading.RLock()
_audio_lock = threading.RLock()
_audio_cache: "OrderedDict[str, bytes]" = OrderedDict()


def _run_async(awaitable):
    """Run one edge-tts coroutine from a normal synchronous Flask worker."""
    return asyncio.run(awaitable)


def _friendly_voice_name(voice: Dict[str, Any]) -> str:
    friendly = str(voice.get("FriendlyName") or "")
    match = re.match(r"Microsoft (.+?) Online \(", friendly)
    if match:
        return match.group(1)
    short = str(voice.get("ShortName") or "Neural voice")
    name = re.sub(r"^[a-z]{2,3}-[A-Z]{2}-", "", short)
    return re.sub(r"(Multilingual)?Neural$", "", name) or short


def _normalise_voice(voice: Dict[str, Any]) -> Dict[str, Any]:
    tags = voice.get("VoiceTag") or {}
    return {
        "id": str(voice.get("ShortName") or ""),
        "name": _friendly_voice_name(voice),
        "locale": str(voice.get("Locale") or ""),
        "gender": str(voice.get("Gender") or ""),
        "personalities": list(tags.get("VoicePersonalities") or []),
        "categories": list(tags.get("ContentCategories") or []),
        "provider": "edge",
}


def _robot_key(robot: str) -> str:
    key = str(robot or "").strip().lower()
    if key in {"casper", "caspar", "picoh"}:
        return "pico"
    return key


def _public_robot_key(robot: str) -> str:
    return "casper" if robot == "pico" else robot


async def _download_voice_catalog() -> List[Dict[str, Any]]:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")
    raw = await edge_tts.list_voices()
    voices = [_normalise_voice(v) for v in raw]
    voices = [v for v in voices if v["id"] and v["locale"]]
    voices.sort(key=lambda v: (v["locale"], v["name"], v["id"]))
    return voices


def get_voice_catalog(force: bool = False) -> List[Dict[str, Any]]:
    """Return the cached neural catalog, refreshing it every six hours."""
    global _voice_catalog, _voice_catalog_at
    now = time.monotonic()
    with _voice_lock:
        if _voice_catalog and not force and now - _voice_catalog_at < _VOICE_TTL_SECONDS:
            return list(_voice_catalog)
        try:
            fresh = _run_async(_download_voice_catalog())
        except Exception:
            # A stale catalog remains useful during a temporary network outage.
            if _voice_catalog:
                return list(_voice_catalog)
            raise
        _voice_catalog = fresh
        _voice_catalog_at = now
        return list(_voice_catalog)


def _read_preferences() -> Dict[str, Dict[str, str]]:
    with _prefs_lock:
        try:
            with open(_PREFS_PATH, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError, TypeError):
            raw = {}
        out: Dict[str, Dict[str, str]] = {}
        for robot in _ROBOTS:
            value = raw.get(robot) if isinstance(raw, dict) else None
            if isinstance(value, dict):
                provider = str(value.get("provider") or "browser")
                voice = str(value.get("voice") or "")
                if provider in {"edge", "browser"}:
                    out[robot] = {"provider": provider, "voice": voice}
        return out


def get_preference(robot: str) -> Dict[str, str]:
    robot = _robot_key(robot)
    robot = robot if robot in _ROBOTS else "blue"
    return _read_preferences().get(robot, dict(_DEFAULT_PREFERENCES[robot]))


def _write_preference(robot: str, provider: str, voice: str) -> Dict[str, str]:
    with _prefs_lock:
        preferences = _read_preferences()
        preferences[robot] = {"provider": provider, "voice": voice}
        folder = os.path.dirname(os.path.abspath(_PREFS_PATH))
        os.makedirs(folder, exist_ok=True)
        tmp = _PREFS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(preferences, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, _PREFS_PATH)
        return dict(preferences[robot])


def _percent_from_rate(rate: float) -> str:
    percent = round((rate - 1.0) * 100)
    return f"{percent:+d}%"


def _hz_from_pitch(pitch: float) -> str:
    # Browser pitch 1.0 is neutral.  Fifty hertz across a full multiplier step
    # keeps persona differences audible without making speech cartoonish.
    hz = round((pitch - 1.0) * 50)
    return f"{hz:+d}Hz"


async def _synthesise(text: str, voice: str, rate: float, pitch: float) -> bytes:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed")
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=_percent_from_rate(rate),
        pitch=_hz_from_pitch(pitch),
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk.get("data") or b"")
    if not audio:
        raise RuntimeError("the neural speech service returned no audio")
    return bytes(audio)


def _cached_audio(text: str, voice: str, rate: float, pitch: float) -> bytes:
    key_source = json.dumps(
        [text, voice, round(rate, 3), round(pitch, 3)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    key = hashlib.sha256(key_source).hexdigest()
    with _audio_lock:
        cached = _audio_cache.get(key)
        if cached is not None:
            _audio_cache.move_to_end(key)
            return cached
    audio = _run_async(_synthesise(text, voice, rate, pitch))
    with _audio_lock:
        _audio_cache[key] = audio
        _audio_cache.move_to_end(key)
        while len(_audio_cache) > _AUDIO_CACHE_LIMIT:
            _audio_cache.popitem(last=False)
    return audio


def _language_filter(voices: Iterable[Dict[str, Any]], language: str):
    language = language.strip().lower()
    if not language or language == "all":
        return list(voices)
    prefix = language.split("-", 1)[0]
    return [v for v in voices if v["locale"].lower().split("-", 1)[0] == prefix]


def register(app):
    @app.route("/tts/voices", methods=["GET"])
    def tts_voices():
        language = str(request.args.get("lang") or "")
        try:
            voices = _language_filter(get_voice_catalog(), language)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "provider": "edge",
                "voices": [],
                "error": str(exc),
            }), 503
        return jsonify({
            "ok": True,
            "provider": "edge",
            "online": True,
            "count": len(voices),
            "voices": voices,
        })

    @app.route("/tts/preferences/<robot>", methods=["GET", "POST"])
    def tts_preferences(robot):
        robot = _robot_key(robot)
        if robot not in _ROBOTS:
            return jsonify({"ok": False, "error": "unknown robot"}), 404
        if request.method == "GET":
            return jsonify({
                "ok": True,
                "robot": _public_robot_key(robot),
                **get_preference(robot),
            })

        data = request.get_json(silent=True) or {}
        provider = str(data.get("provider") or "").lower()
        voice = str(data.get("voice") or "").strip()
        if provider not in {"edge", "browser"}:
            return jsonify({"ok": False, "error": "provider must be edge or browser"}), 400
        if provider == "edge":
            try:
                valid_ids = {v["id"] for v in get_voice_catalog()}
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)}), 503
            if voice not in valid_ids:
                return jsonify({"ok": False, "error": "unknown neural voice"}), 400
        saved = _write_preference(robot, provider, voice)
        return jsonify({
            "ok": True,
            "robot": _public_robot_key(robot),
            **saved,
        })

    @app.route("/tts/synthesize", methods=["POST"])
    def tts_synthesize():
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        voice = str(data.get("voice") or "").strip()
        if not text:
            return jsonify({"ok": False, "error": "text is required"}), 400
        if len(text) > _MAX_TEXT_CHARS:
            return jsonify({
                "ok": False,
                "error": f"text exceeds {_MAX_TEXT_CHARS} characters",
            }), 413
        try:
            rate = max(0.5, min(2.0, float(data.get("rate", 1.0))))
            pitch = max(0.5, min(1.5, float(data.get("pitch", 1.0))))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "rate and pitch must be numbers"}), 400

        try:
            valid_ids = {v["id"] for v in get_voice_catalog()}
            if voice not in valid_ids:
                return jsonify({"ok": False, "error": "unknown neural voice"}), 400
            audio = _cached_audio(text, voice, rate, pitch)
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": f"neural speech is temporarily unavailable: {exc}",
            }), 503

        return Response(audio, headers={
            "Content-Type": "audio/mpeg",
            "Content-Length": str(len(audio)),
            "Cache-Control": "private, max-age=86400",
            "X-Blue-TTS-Provider": "edge",
        })
