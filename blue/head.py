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
_calibration = {
    "centers": dict(_DEFAULT_CENTERS),
    "auto_movement": True,
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
    except Exception as e:
        _log(f"calibration load skipped: {e!r}")


def _save_calibration():
    try:
        os.makedirs(os.path.dirname(_CALIB_PATH), exist_ok=True)
        out = {
            "centers": {str(k): float(v) for k, v in _calibration["centers"].items()},
            "auto_movement": bool(_calibration["auto_movement"]),
        }
        with open(_CALIB_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
    except Exception as e:
        _log(f"calibration save error: {e!r}")


def center(motor: int) -> float:
    """Calibrated rest position for a motor (0-10)."""
    return float(_calibration["centers"].get(int(motor), _DEFAULT_CENTER))


def get_calibration():
    """Snapshot of the current calibration (centers + auto flag)."""
    return {
        "centers": {int(k): float(v) for k, v in _calibration["centers"].items()},
        "motor_names": dict(MOTOR_NAMES),
        "auto_movement": bool(_calibration["auto_movement"]),
        "available": _available,
    }


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

def _move_internal(motor: int, pos: float, speed: float = 5.0) -> bool:
    """Write to a motor; assumes init() already ran and we want the raw pos.
    Does not bump the busy timer (used by the idle loop too)."""
    if not _available:
        return False
    try:
        with _lock:
            _ohbot.move(int(motor), _clip(pos, _MIN_POS, _MAX_POS), _clip(speed, 1.0, 10.0))
        return True
    except Exception as e:
        _log(f"move({motor},{pos},{speed}) error: {e!r}")
        return False


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


def _lip_loop():
    """Open/close the mouth repeatedly until lip_stop() is called.

    Open: top lip rises a little, bottom lip (jaw) drops a lot.
    Closed: both lips back to their calibrated rest — mouth actually SHUT.

    The earlier bug was holding both lips at offsets from centre the whole
    time (the "closed" state was still offset), so the mouth never truly
    closed and the lips just quivered together. We alternate between
    fully-open and fully-closed instead, and vary the amplitude/timing a
    touch so it doesn't feel metronomic.
    """
    global _lip_active
    top_c = center(TOPLIP)
    bot_c = center(BOTTOMLIP)
    try:
        while _lip_active and _available:
            # Open: top lip rises (TOPLIP higher = up), jaw drops (BOTTOMLIP
            # HIGHER = jaw down, per the Ohbot convention). Both command
            # values go up, but physically the lips move APART — that's the
            # mouth opening.
            open_amt = random.uniform(2.4, 3.4)
            _move_internal(TOPLIP, top_c + open_amt * 0.6, speed=10)
            _move_internal(BOTTOMLIP, bot_c + open_amt, speed=10)
            time.sleep(random.uniform(0.08, 0.13))
            if not _lip_active:
                break
            # Closed: BOTH lips back to their calibrated rest.
            _move_internal(TOPLIP, top_c, speed=10)
            _move_internal(BOTTOMLIP, bot_c, speed=10)
            time.sleep(random.uniform(0.07, 0.12))
    finally:
        _move_internal(TOPLIP, top_c, speed=8)
        _move_internal(BOTTOMLIP, bot_c, speed=8)


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


def _do_idle_motion():
    """Pick one small, natural-looking motion."""
    choice = random.choice([
        "blink", "blink",                       # blinks are common
        "micro_nod", "micro_turn", "micro_tilt",
        "glance_left", "glance_right",
        "eye_up", "eye_down",
    ])
    if choice == "blink":
        c = center(LIDBLINK)
        _move_internal(LIDBLINK, 0.0, speed=10)
        time.sleep(0.10)
        _move_internal(LIDBLINK, c, speed=10)
    elif choice == "micro_nod":
        c = center(HEADNOD)
        amt = random.choice([-0.8, -0.5, 0.5, 0.8])
        _move_internal(HEADNOD, c + amt, speed=3)
        time.sleep(random.uniform(0.6, 1.1))
        _move_internal(HEADNOD, c, speed=3)
    elif choice == "micro_turn":
        c = center(HEADTURN)
        amt = random.choice([-1.0, -0.6, 0.6, 1.0])
        _move_internal(HEADTURN, c + amt, speed=3)
        time.sleep(random.uniform(0.8, 1.4))
        _move_internal(HEADTURN, c, speed=3)
    elif choice == "micro_tilt":
        c = center(HEADROLL)
        amt = random.choice([-0.6, -0.4, 0.4, 0.6])
        _move_internal(HEADROLL, c + amt, speed=3)
        time.sleep(random.uniform(0.8, 1.4))
        _move_internal(HEADROLL, c, speed=3)
    elif choice == "glance_left":
        c = center(EYETURN)
        _move_internal(EYETURN, c + 1.5, speed=6)
        time.sleep(random.uniform(0.4, 0.8))
        _move_internal(EYETURN, c, speed=6)
    elif choice == "glance_right":
        c = center(EYETURN)
        _move_internal(EYETURN, c - 1.5, speed=6)
        time.sleep(random.uniform(0.4, 0.8))
        _move_internal(EYETURN, c, speed=6)
    elif choice == "eye_up":
        c = center(EYETILT)
        _move_internal(EYETILT, c + 1.2, speed=5)
        time.sleep(random.uniform(0.4, 0.9))
        _move_internal(EYETILT, c, speed=5)
    elif choice == "eye_down":
        c = center(EYETILT)
        _move_internal(EYETILT, c - 1.2, speed=5)
        time.sleep(random.uniform(0.4, 0.9))
        _move_internal(EYETILT, c, speed=5)


def _auto_loop():
    """Background thread: subtle idle motions when Blue isn't doing anything else."""
    # Stagger the first motion so it doesn't fire the instant the server starts.
    time.sleep(random.uniform(3.0, 6.0))
    while not _auto_stop:
        time.sleep(random.uniform(2.5, 7.0))
        try:
            if not _available or not auto_enabled():
                continue
            if time.time() < _busy_until:
                continue
            if _lip_active:
                continue
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
