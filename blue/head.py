"""Direct hardware control of Blue's Ohbot head — replaces the Ohbot app.

Blue talks to the Ohbot board over USB serial via the official `ohbot` Python
library (in 4.x the real module is `from ohbot import ohbot`, and it
auto-connects on import). On this branch, the Ohbot desktop app must NOT be
running, or it will hold the serial port and we can't connect.

What this module owns:
  * Connection lifecycle (init / close / reset).
  * Per-motor calibrated REST positions, persisted to `data/head_calibration.json`.
  * Movement primitives that are calibration-aware: look / nod_yes / shake_no /
    blink / wink / expressions, all defined as offsets from the calibrated rest.
  * Lip flap during speech (`lip_start` / `lip_stop`).
  * A daemon "thoughtful" idle loop that does subtle micro-motions when Blue
    isn't otherwise moving (`auto_enable(True/False)`).
  * Raw write access for the calibration GUI sliders (`move_raw`).

Safe by design: missing library / missing board / closed-app are all no-ops
that log once, so the rest of Blue keeps running.
"""

import json
import os
import random
import threading
import time

# Motor channel numbers (Ohbot board). Hardcoded so this module doesn't depend
# on whichever name the installed `ohbot` package exposes for them.
HEADNOD = 0
HEADTURN = 1
EYETURN = 2
LIDBLINK = 3
TOPLIP = 4
BOTTOMLIP = 5
EYETILT = 6
HEADROLL = 7   # head tilt left/right (rotation), separate from HeadTurn

ALL_MOTORS = (HEADNOD, HEADTURN, EYETURN, LIDBLINK, TOPLIP, BOTTOMLIP, EYETILT, HEADROLL)
MOTOR_NAMES = {
    HEADNOD: "HeadNod",
    HEADTURN: "HeadTurn",
    EYETURN: "EyeTurn",
    LIDBLINK: "LidBlink",
    TOPLIP: "TopLip",
    BOTTOMLIP: "BottomLip",
    EYETILT: "EyeTilt",
    HEADROLL: "HeadRoll",
}

_MIN_POS = 0.0
_MAX_POS = 10.0
_DEFAULT_CENTER = 5.0

# ---- Connection state ------------------------------------------------------

_lock = threading.Lock()
_initialized = False
_available = False
_warned_missing = False
_ohbot = None

_OHBOT_LIB = False
try:
    import importlib as _importlib
    _importlib.import_module("ohbot")
    _OHBOT_LIB = True
except Exception:
    _OHBOT_LIB = False


def _log(msg: str) -> None:
    print(f"[HEAD] {msg}")


def _clip(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ---- Calibration (per-motor rest position) ---------------------------------

# Defaults: 5 for everything; LIDBLINK rests at 8 (eyelids relaxed-open looks
# better on most Ohbot units than a hard 5). Calibration GUI overrides these.
_DEFAULT_CENTERS = {m: _DEFAULT_CENTER for m in ALL_MOTORS}
_DEFAULT_CENTERS[LIDBLINK] = 8.0

_CALIB_PATH = os.path.join(os.getcwd(), "data", "head_calibration.json")
# Lip-motor polarity varies between Ohbot units, so each lip has an invert
# flag. With invert=False: opening the mouth increases the motor value;
# invert=True: opening decreases it. The GUI exposes both so the user can
# experiment without code changes.
_calibration = {
    "centers": dict(_DEFAULT_CENTERS),
    "auto_movement": True,
    "lip_invert_top": False,
    "lip_invert_bottom": False,
    # Idle "thoughtful" movement, both on a 0-10 scale (user-tuneable from GUI).
    # 5 ≈ matches the original feel; defaults skew slightly more active.
    "idle_frequency": 7,   # how often a motion happens (0=quiet, 10=lively)
    "idle_amplitude": 5,   # how big each motion is (0=subtle, 10=expressive)
    # Hands-free wake-word sensitivity on the chat page (0=strict, 10=sensitive).
    # The chat page reads this at load and derives its VAD thresholds from it.
    "hf_sensitivity": 5,
}


def _load_calibration():
    """Read calibration JSON from disk if it exists; otherwise keep defaults."""
    try:
        if os.path.exists(_CALIB_PATH):
            with open(_CALIB_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            saved_centers = data.get("centers") or {}
            for k, v in saved_centers.items():
                try:
                    _calibration["centers"][int(k)] = float(_clip(float(v), _MIN_POS, _MAX_POS))
                except Exception:
                    pass
            if "auto_movement" in data:
                _calibration["auto_movement"] = bool(data["auto_movement"])
            for k in ("lip_invert_top", "lip_invert_bottom"):
                if k in data:
                    _calibration[k] = bool(data[k])
            for k in ("idle_frequency", "idle_amplitude", "hf_sensitivity"):
                if k in data:
                    try:
                        _calibration[k] = float(_clip(float(data[k]), 0, 10))
                    except Exception:
                        pass
            if isinstance(data.get("custom_expressions"), dict):
                cust = {}
                for nm, pose in data["custom_expressions"].items():
                    if not isinstance(pose, dict):
                        continue
                    try:
                        cust[nm] = {int(k): float(v) for k, v in pose.items()}
                    except Exception:
                        continue
                _calibration["custom_expressions"] = cust
    except Exception as e:
        _log(f"calibration load skipped: {e!r}")


def _save_calibration():
    try:
        os.makedirs(os.path.dirname(_CALIB_PATH), exist_ok=True)
        out = {
            "centers": {str(k): float(v) for k, v in _calibration["centers"].items()},
            "auto_movement": bool(_calibration["auto_movement"]),
            "lip_invert_top": bool(_calibration.get("lip_invert_top", False)),
            "lip_invert_bottom": bool(_calibration.get("lip_invert_bottom", False)),
            "idle_frequency": float(_calibration.get("idle_frequency", 7)),
            "idle_amplitude": float(_calibration.get("idle_amplitude", 5)),
            "hf_sensitivity": float(_calibration.get("hf_sensitivity", 5)),
            "custom_expressions": {
                nm: {str(k): float(v) for k, v in pose.items()}
                for nm, pose in (_calibration.get("custom_expressions") or {}).items()
            },
        }
        with open(_CALIB_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception as e:
        _log(f"calibration save error: {e!r}")


def center(motor: int) -> float:
    """Calibrated rest position for a motor (0-10)."""
    return float(_calibration["centers"].get(int(motor), _DEFAULT_CENTER))


def get_calibration():
    """Snapshot of the current calibration (centers + flags)."""
    return {
        "centers": {int(k): float(v) for k, v in _calibration["centers"].items()},
        "motor_names": dict(MOTOR_NAMES),
        "auto_movement": bool(_calibration["auto_movement"]),
        "lip_invert_top": bool(_calibration.get("lip_invert_top", False)),
        "lip_invert_bottom": bool(_calibration.get("lip_invert_bottom", False)),
        "idle_frequency": float(_calibration.get("idle_frequency", 7)),
        "idle_amplitude": float(_calibration.get("idle_amplitude", 5)),
        "hf_sensitivity": float(_calibration.get("hf_sensitivity", 5)),
        "available": _available,
        "current_pose": current_pose(),
        "builtin_expressions": sorted(_EXPRESSIONS.keys()),
        "custom_expressions": dict(_calibration.get("custom_expressions") or {}),
    }


def set_idle_params(frequency=None, amplitude=None) -> bool:
    """Adjust the idle loop. Pass None to leave a value unchanged. Persists."""
    if frequency is not None:
        _calibration["idle_frequency"] = float(_clip(float(frequency), 0, 10))
    if amplitude is not None:
        _calibration["idle_amplitude"] = float(_clip(float(amplitude), 0, 10))
    _save_calibration()
    return True


def set_hf_sensitivity(value) -> bool:
    """Set the hands-free wake-word sensitivity (0-10). Persists."""
    if value is None:
        return False
    _calibration["hf_sensitivity"] = float(_clip(float(value), 0, 10))
    _save_calibration()
    return True


def _idle_interval_range():
    """Map the 0-10 frequency slider to a (min, max) seconds-between-motions
    range. 0 = quiet (rare), 5 ≈ original, 10 = nearly constant.

    While Blue is SPEAKING (lip-flap active), tighten the range — people
    gesture more often when talking; we want head/eye motion to come along
    with the jaw, not freeze."""
    f = _clip(float(_calibration.get("idle_frequency", 7)), 0, 10) / 10.0
    lo, hi = 0.8 + (1 - f) * 5.2, 2.5 + (1 - f) * 9.5
    if _lip_active:
        lo = max(0.35, lo * 0.45)
        hi = max(1.2, hi * 0.45)
    return (lo, hi)


def _idle_amp_mult():
    """Map the 0-10 amplitude slider to a motion-size multiplier.
    0 → 0.3x (barely there), 5 → 1.0x (original), 10 → 2.0x (expressive).
    Slightly subtler during speech so the gestures support the talking
    rather than distract from it."""
    a = _clip(float(_calibration.get("idle_amplitude", 5)), 0, 10)
    base = 0.3 + (a / 5.0) * 0.7 if a <= 5 else 1.0 + ((a - 5) / 5.0) * 1.0
    return base * 0.7 if _lip_active else base


def set_lip_invert(top=None, bottom=None) -> bool:
    """Flip the polarity of the top or bottom lip motor. Persists.
    Pass None to leave a flag unchanged."""
    if top is not None:
        _calibration["lip_invert_top"] = bool(top)
    if bottom is not None:
        _calibration["lip_invert_bottom"] = bool(bottom)
    _save_calibration()
    return True


def set_center(motor: int, pos: float) -> bool:
    """Save `pos` as motor's calibrated rest position. Persists to disk."""
    m = int(motor)
    if m not in ALL_MOTORS:
        return False
    _calibration["centers"][m] = float(_clip(pos, _MIN_POS, _MAX_POS))
    _save_calibration()
    return True


# ---- Activity bookkeeping (for the idle loop) ------------------------------

_busy_until = 0.0  # Unix time; idle loop skips if now < this.


def _mark_busy(seconds: float = 1.0):
    global _busy_until
    t = time.time() + max(0.05, float(seconds))
    if t > _busy_until:
        _busy_until = t


# ---- Connection lifecycle --------------------------------------------------

def is_available() -> bool:
    return _available


def init(port_name: str = "") -> bool:
    """Connect to the Ohbot board (idempotent). Loads calibration on first call."""
    global _initialized, _available, _warned_missing, _ohbot
    if _initialized:
        return _available
    _load_calibration()
    if not _OHBOT_LIB:
        if not _warned_missing:
            _log("ohbot library not installed (pip install ohbot). Head control disabled.")
            _warned_missing = True
        _initialized = True
        return False
    try:
        with _lock:
            from ohbot import ohbot as _oh  # type: ignore
            _ohbot = _oh
            conn_attr = getattr(_oh, "connected", True)
            connected_ok = bool(conn_attr() if callable(conn_attr) else conn_attr)
            if not connected_ok:
                raise RuntimeError("ohbot: no board responded on any serial port")
            _oh.reset()
            _available = True
            _log("Ohbot head connected and reset to neutral.")
    except Exception as e:
        _log(f"could not connect to Ohbot board ({e!r}). Is the Ohbot app closed?")
        _available = False
    _initialized = True
    # Park everything at the calibrated centres so first impressions match the
    # saved calibration (the board's own reset puts them at 5).
    if _available:
        for m in ALL_MOTORS:
            _move_internal(m, center(m), speed=3.0)
    _start_auto_thread()
    return _available


def close() -> None:
    global _initialized, _available, _auto_stop
    _auto_stop = True
    if _OHBOT_LIB and _available:
        try:
            with _lock:
                _ohbot.reset()
                _ohbot.close()
        except Exception as e:
            _log(f"close() error: {e!r}")
    _initialized = False
    _available = False


def reset() -> bool:
    """Return motors to their CALIBRATED rest positions and turn off the LEDs."""
    if not init():
        return False
    try:
        with _lock:
            _ohbot.reset()
        for m in ALL_MOTORS:
            _move_internal(m, center(m), speed=4.0)
        return True
    except Exception as e:
        _log(f"reset() error: {e!r}")
        return False


# ---- Low-level move --------------------------------------------------------

# Last commanded position per motor — read by current_pose() so "save the
# current pose as an expression" knows what was sent. Updated in _move_internal.
_last_pos = {m: _DEFAULT_CENTERS[m] for m in ALL_MOTORS}


def _move_internal(motor: int, pos: float, speed: float = 5.0) -> bool:
    """Write to a motor; assumes init() already ran and we want the raw pos.
    Does not bump the busy timer (used by the idle loop too)."""
    if not _available:
        return False
    try:
        pos_c = _clip(pos, _MIN_POS, _MAX_POS)
        with _lock:
            _ohbot.move(int(motor), pos_c, _clip(speed, 1.0, 10.0))
        _last_pos[int(motor)] = float(pos_c)
        return True
    except Exception as e:
        _log(f"move({motor},{pos},{speed}) error: {e!r}")
        return False


def current_pose():
    """Snapshot of the last commanded position per motor."""
    return {int(k): float(v) for k, v in _last_pos.items()}


def _move(motor: int, pos: float, speed: float = 5.0) -> bool:
    """Explicit (user/LLM-initiated) move. Bumps the busy timer."""
    if not init():
        return False
    _mark_busy(1.0)
    return _move_internal(motor, pos, speed)


def move_raw(motor: int, pos: float, speed: float = 5.0) -> bool:
    """Drive a motor directly to an absolute position 0-10 (for the GUI sliders)."""
    return _move(motor, pos, speed)


# ---- Named, higher-level actions (calibration-aware) -----------------------

# Offsets are amount from the calibrated rest; positions get clipped to 0-10.
_LOOK_OFFSETS = {
    "left":  (HEADTURN, +3.0),
    "right": (HEADTURN, -3.0),
    "up":    (HEADNOD,  +3.0),
    "down":  (HEADNOD,  -2.5),
}


def look(direction: str, speed: float = 4.0) -> bool:
    """Turn/tilt the head: left, right, up, down, center."""
    d = (direction or "").lower().strip()
    if d in ("center", "centre", "forward", "front", "straight", "ahead"):
        _move(HEADTURN, center(HEADTURN), speed)
        _move(HEADNOD, center(HEADNOD), speed)
        return True
    spec = _LOOK_OFFSETS.get(d)
    if not spec:
        return False
    motor, off = spec
    return _move(motor, center(motor) + off, speed)


def nod_yes(times: int = 2) -> bool:
    """Nod up-and-down. Returns to calibrated rest at the end."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    c = center(HEADNOD)
    _mark_busy(times * 0.75 + 0.5)
    for _ in range(times):
        _move_internal(HEADNOD, c - 2.0, speed=7)
        time.sleep(0.35)
        _move_internal(HEADNOD, c + 2.0, speed=7)
        time.sleep(0.35)
    _move_internal(HEADNOD, c, speed=6)
    return True


def shake_no(times: int = 2) -> bool:
    """Shake side-to-side. Returns to calibrated rest at the end."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    c = center(HEADTURN)
    _mark_busy(times * 0.75 + 0.5)
    for _ in range(times):
        _move_internal(HEADTURN, c - 2.0, speed=7)
        time.sleep(0.35)
        _move_internal(HEADTURN, c + 2.0, speed=7)
        time.sleep(0.35)
    _move_internal(HEADTURN, c, speed=6)
    return True


def blink(times: int = 1) -> bool:
    """Quick eyelid blink(s). Returns lids to calibrated rest."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    c = center(LIDBLINK)
    _mark_busy(times * 0.4 + 0.2)
    for _ in range(times):
        _move_internal(LIDBLINK, 0.0, speed=10)
        time.sleep(0.10)
        _move_internal(LIDBLINK, c, speed=10)
        time.sleep(0.18)
    return True


# Each expression is { motor: offset_from_center }, applied with clipping.
_EXPRESSIONS = {
    "neutral":   {HEADTURN: 0, HEADNOD: 0, TOPLIP: 0, BOTTOMLIP: 0, LIDBLINK: 0, EYETURN: 0, EYETILT: 0},
    "happy":     {HEADNOD: +1.0, TOPLIP: +3.0, BOTTOMLIP: -3.0, LIDBLINK: 0},
    "sad":       {HEADNOD: -2.0, TOPLIP: -3.0, BOTTOMLIP: +3.0, LIDBLINK: -4.0},
    "surprised": {HEADNOD: +2.0, TOPLIP: 0, BOTTOMLIP: +4.0, LIDBLINK: +2.0},
    "curious":   {HEADTURN: +1.5, HEADNOD: +1.0, HEADROLL: +1.0, EYETURN: +1.0, LIDBLINK: 0},
    "wink":      {LIDBLINK: -8.0},  # both lids close briefly (we only have one)
}


def expression(mood: str, speed: float = 5.0) -> bool:
    """Apply a named facial pose (all positions relative to calibrated centres)."""
    m = (mood or "").lower().strip()
    pose = _EXPRESSIONS.get(m)
    if pose is None:
        return False
    if not init():
        return False
    _mark_busy(0.8)
    for motor, off in pose.items():
        _move_internal(motor, center(motor) + off, speed)
    if m == "wink":
        time.sleep(0.25)
        _move_internal(LIDBLINK, center(LIDBLINK), speed=10)
    return True


# ---- Custom expressions (user-saved poses) --------------------------------

def list_expressions():
    """All available expression names: built-in + custom (user-saved)."""
    return {
        "builtin": sorted(_EXPRESSIONS.keys()),
        "custom": sorted((_calibration.get("custom_expressions") or {}).keys()),
    }


def save_expression(name, positions=None) -> bool:
    """Save a named pose. If positions is None, captures whatever each motor
    was last commanded to. Names that collide with built-ins are rejected."""
    name = (name or "").strip()
    if not name or name.lower() in _EXPRESSIONS:
        return False
    pose_src = positions if positions else current_pose()
    pose = {}
    for k, v in pose_src.items():
        try:
            m = int(k)
            if m not in ALL_MOTORS:
                continue
            pose[m] = float(_clip(float(v), _MIN_POS, _MAX_POS))
        except Exception:
            continue
    cust = dict(_calibration.get("custom_expressions") or {})
    cust[name] = pose
    _calibration["custom_expressions"] = cust
    _save_calibration()
    return True


def delete_expression(name) -> bool:
    cust = dict(_calibration.get("custom_expressions") or {})
    if name in cust:
        del cust[name]
        _calibration["custom_expressions"] = cust
        _save_calibration()
        return True
    return False


def apply_expression(name, speed: float = 5.0) -> bool:
    """Apply ANY named expression (built-in or custom). Custom poses are
    absolute positions; built-ins are relative to calibrated centres."""
    if not init():
        return False
    nm = (name or "").strip()
    if nm.lower() in _EXPRESSIONS:
        return expression(nm)
    cust = (_calibration.get("custom_expressions") or {}).get(nm)
    if not cust:
        return False
    _mark_busy(0.8)
    for motor, pos in cust.items():
        _move_internal(int(motor), float(pos), speed)
    return True


def reconnect() -> bool:
    """Force a clean disconnect and reconnect to the board — useful after
    closing/reopening the Ohbot app, or if the serial link went stale."""
    global _initialized, _available
    close()
    _initialized = False
    _available = False
    return init()


def eye_color(r: int, g: int, b: int) -> bool:
    if not init():
        return False
    try:
        with _lock:
            _ohbot.eyeColour(int(_clip(r, 0, 10)), int(_clip(g, 0, 10)), int(_clip(b, 0, 10)))
        return True
    except Exception as e:
        _log(f"eyeColour error: {e!r}")
        return False


def say(text: str, lip_sync: bool = True) -> bool:
    """Speak via the Ohbot board's SAPI + native lip-sync. Blocks until done."""
    text = (text or "").strip()
    if not text:
        return False
    if not init():
        return False
    _mark_busy(60.0)  # generous; ohbot.say blocks until done
    try:
        with _lock:
            _ohbot.say(text, untilDone=True, lipSync=bool(lip_sync))
        return True
    except Exception as e:
        _log(f"say error: {e!r}")
        return False
    finally:
        global _busy_until
        _busy_until = time.time() + 0.3


# ---- Lip flap during browser-side speech -----------------------------------

_lip_active = False
_lip_thread = None

# How far each lip travels at fully-open (offset from its calibrated centre).
# The top lip moves less than the jaw, like real speech.
_LIP_TOP_RANGE = 1.8
_LIP_BOTTOM_RANGE = 3.0


def _set_mouth(openness: float) -> None:
    """Drive both lip motors to express a mouth openness from 0.0 (closed,
    at calibrated rest) to 1.0 (fully open). The per-lip polarity flags in
    calibration determine which direction is "open" on this unit, so the
    user can flip a checkbox in the GUI if their wiring is opposite.
    """
    openness = _clip(openness, 0.0, 1.0)
    top_sign = -1.0 if _calibration.get("lip_invert_top") else +1.0
    bot_sign = -1.0 if _calibration.get("lip_invert_bottom") else +1.0
    _move_internal(TOPLIP, center(TOPLIP) + top_sign * _LIP_TOP_RANGE * openness, speed=10)
    _move_internal(BOTTOMLIP, center(BOTTOMLIP) + bot_sign * _LIP_BOTTOM_RANGE * openness, speed=10)


def _lip_loop():
    """Open and shut the mouth repeatedly until lip_stop() is called. The
    motion alternates between FULLY open and FULLY closed so the mouth
    actually shuts between syllables (the earlier bug was sitting on two
    offsets that never returned to rest)."""
    global _lip_active
    try:
        while _lip_active and _available:
            _set_mouth(random.uniform(0.78, 1.0))   # open
            time.sleep(random.uniform(0.08, 0.13))
            if not _lip_active:
                break
            _set_mouth(0.0)                          # closed
            time.sleep(random.uniform(0.07, 0.12))
    finally:
        _set_mouth(0.0)


def lip_start() -> bool:
    """Begin the lip-flap loop. Idempotent."""
    global _lip_active, _lip_thread
    if not init():
        return False
    if _lip_active:
        return True
    _lip_active = True
    _mark_busy(120.0)
    _lip_thread = threading.Thread(target=_lip_loop, name="blue-lip-flap", daemon=True)
    _lip_thread.start()
    return True


def lip_stop() -> bool:
    """End the lip-flap loop and close the mouth."""
    global _lip_active, _busy_until
    _lip_active = False
    _busy_until = time.time() + 0.3
    return True


def lip_is_active() -> bool:
    return bool(_lip_active)


# ---- Thoughtful idle motion ------------------------------------------------

_auto_thread = None
_auto_stop = False


def auto_enabled() -> bool:
    return bool(_calibration.get("auto_movement", True))


def auto_enable(on: bool) -> bool:
    """Turn the thoughtful idle loop on/off. Persisted."""
    _calibration["auto_movement"] = bool(on)
    _save_calibration()
    return True


def _nudge(motor, offset, speed, hold_min, hold_max):
    """Offset a motor from its calibrated rest, hold briefly, return to rest.
    The offset is scaled by the idle amplitude slider."""
    c = center(motor)
    _move_internal(motor, c + offset * _idle_amp_mult(), speed=speed)
    time.sleep(random.uniform(hold_min, hold_max))
    _move_internal(motor, c, speed=speed)


# Recipe table for idle motions. Blinks are listed twice because they're a
# natural high-frequency motion; the others get one slot each. Each non-blink
# entry is (motor, [possible offsets], speed, hold_min, hold_max). The offsets
# get scaled by the idle amplitude slider at execution time.
_IDLE_RECIPES = [
    ("blink", None),
    ("blink", None),
    ("nudge", (HEADNOD,  [-0.8, -0.5, 0.5, 0.8], 3, 0.6, 1.1)),
    ("nudge", (HEADTURN, [-1.0, -0.6, 0.6, 1.0], 3, 0.8, 1.4)),
    ("nudge", (HEADROLL, [-0.6, -0.4, 0.4, 0.6], 3, 0.8, 1.4)),
    ("nudge", (EYETURN, [+1.5, -1.5],            6, 0.4, 0.8)),
    ("nudge", (EYETILT, [+1.2, -1.2],            5, 0.4, 0.9)),
]


def _do_idle_motion():
    """Pick one small, natural-looking motion (scaled by the amplitude slider)."""
    kind, spec = random.choice(_IDLE_RECIPES)
    if kind == "blink":
        c = center(LIDBLINK)
        _move_internal(LIDBLINK, 0.0, speed=10)
        time.sleep(0.10)
        _move_internal(LIDBLINK, c, speed=10)
    else:
        motor, choices, speed, hold_min, hold_max = spec
        _nudge(motor, random.choice(choices), speed, hold_min, hold_max)


def _auto_loop():
    """Background thread: subtle motions to keep Blue looking alive. Two
    modes:
      * idle (no speech) — runs when auto_enabled() is on and Blue isn't in
        the middle of an explicit move; respects _busy_until.
      * speaking — runs whenever the lip-flap is active, even if auto idle
        is off, and bypasses _busy_until (the lip thread bumps it 120s).
    """
    # Stagger the first motion so it doesn't fire the instant the server starts.
    time.sleep(random.uniform(3.0, 6.0))
    while not _auto_stop:
        lo, hi = _idle_interval_range()
        time.sleep(random.uniform(lo, hi))
        try:
            if not _available:
                continue
            if _lip_active:
                # Talking: gesture along with the speech, regardless of toggle.
                _do_idle_motion()
            elif auto_enabled() and time.time() >= _busy_until:
                _do_idle_motion()
        except Exception as e:
            _log(f"idle motion error: {e!r}")
            time.sleep(2.0)


def _start_auto_thread():
    global _auto_thread, _auto_stop
    if _auto_thread is not None and _auto_thread.is_alive():
        return
    _auto_stop = False
    _auto_thread = threading.Thread(target=_auto_loop, name="blue-head-idle", daemon=True)
    _auto_thread.start()
