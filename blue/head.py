"""Direct hardware control of Blue's Ohbot head — replaces the Ohbot app.

Blue talks to the Ohbot board over USB serial via the official `ohbot` Python
library (`pip install ohbot`). On this branch, the Ohbot desktop app must NOT
be running, or it will hold the serial port and we can't connect.

Safe by design:
  * If the library isn't installed, every call is a no-op (logged once).
  * If the board isn't reachable, every call is a no-op.
  * A module-level lock serialises board writes (the serial link is one
    writer at a time, and movements get called from many threads).

Public surface (small on purpose; the chat tool wraps these):
    init(), close(), is_available()
    look(direction), nod_yes(times), shake_no(times), blink(times)
    expression(mood), eye_color(r, g, b), say(text)
    reset()
"""

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

# Position range each motor accepts. 5 is the rest/centre position.
_MIN_POS = 0.0
_MAX_POS = 10.0
_CENTER = 5.0

_lock = threading.Lock()
_initialized = False
_available = False
_warned_missing = False

# In ohbot 4.x the real module lives in a submodule (top-level `import ohbot`
# exposes nothing). The submodule auto-connects to the board on import — there
# is no explicit init() — so we defer the import until init() to avoid opening
# the serial port at module load time.
_ohbot = None
_OHBOT_LIB = False
try:
    import importlib as _importlib
    _importlib.import_module("ohbot")  # presence check only
    _OHBOT_LIB = True
except Exception:
    _OHBOT_LIB = False


def _log(msg: str) -> None:
    print(f"[HEAD] {msg}")


def _clip(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def is_available() -> bool:
    """True once the board is connected and ready."""
    return _available


def init(port_name: str = "") -> bool:
    """Connect to the Ohbot board. Idempotent — safe to call repeatedly.

    The ohbot 4.x library auto-connects on import (it scans serial ports). All
    we do here is import the submodule and verify the board responded. Returns
    True on success. On failure (no library, no board, port held by the Ohbot
    app), returns False and the rest of the module becomes a no-op.
    """
    global _initialized, _available, _warned_missing, _ohbot
    if _initialized:
        return _available
    if not _OHBOT_LIB:
        if not _warned_missing:
            _log("ohbot library not installed (pip install ohbot). Head control disabled.")
            _warned_missing = True
        _initialized = True
        return False
    try:
        with _lock:
            # Import the actual ohbot submodule (this triggers the serial scan).
            from ohbot import ohbot as _oh  # type: ignore
            _ohbot = _oh
            # The lib has a `connected` flag/callable that tells us if a board
            # responded on any scanned port. Treat any truthy value as connected.
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
    return _available


def close() -> None:
    """Stop driving the motors and release the serial port."""
    global _initialized, _available
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
    """Return motors to rest and turn off the eye LEDs."""
    if not init():
        return False
    try:
        with _lock:
            _ohbot.reset()
        return True
    except Exception as e:
        _log(f"reset() error: {e!r}")
        return False


def _move(motor: int, pos: float, speed: float = 5.0) -> bool:
    if not init():
        return False
    try:
        with _lock:
            _ohbot.move(int(motor), _clip(pos, _MIN_POS, _MAX_POS), _clip(speed, 1.0, 10.0))
        return True
    except Exception as e:
        _log(f"move({motor},{pos},{speed}) error: {e!r}")
        return False


# ---- Named, higher-level actions (what the chat tool calls) ----

# Bigger = further from centre (5). Tuned conservatively so it looks natural,
# not jerky, on a stock Ohbot.
_LOOK = {
    "left":     {"motor": HEADTURN, "pos": 8.0},
    "right":    {"motor": HEADTURN, "pos": 2.0},
    "up":       {"motor": HEADNOD,  "pos": 8.0},
    "down":     {"motor": HEADNOD,  "pos": 2.5},
}


def look(direction: str, speed: float = 4.0) -> bool:
    """Turn/tilt the head: left, right, up, down, center."""
    d = (direction or "").lower().strip()
    if d in ("center", "centre", "forward", "front", "straight", "ahead"):
        _move(HEADTURN, _CENTER, speed)
        _move(HEADNOD, _CENTER, speed)
        return True
    spec = _LOOK.get(d)
    if not spec:
        return False
    return _move(spec["motor"], spec["pos"], speed)


def nod_yes(times: int = 2) -> bool:
    """Nod up-and-down. Returns to centre at the end."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    for _ in range(times):
        _move(HEADNOD, 3.0, speed=7)
        time.sleep(0.35)
        _move(HEADNOD, 7.0, speed=7)
        time.sleep(0.35)
    _move(HEADNOD, _CENTER, speed=6)
    return True


def shake_no(times: int = 2) -> bool:
    """Shake side-to-side. Returns to centre at the end."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    for _ in range(times):
        _move(HEADTURN, 3.0, speed=7)
        time.sleep(0.35)
        _move(HEADTURN, 7.0, speed=7)
        time.sleep(0.35)
    _move(HEADTURN, _CENTER, speed=6)
    return True


def blink(times: int = 1) -> bool:
    """Quick eyelid blink(s)."""
    if not init():
        return False
    times = int(_clip(times, 1, 5))
    for _ in range(times):
        _move(LIDBLINK, 0.0, speed=10)
        time.sleep(0.10)
        _move(LIDBLINK, 10.0, speed=10)
        time.sleep(0.18)
    return True


# Quick facial poses. Positions are best-effort across Ohbot units — they can
# be retuned without changing the chat tool.
_EXPRESSIONS = {
    "neutral":   {HEADTURN: 5.0, HEADNOD: 5.0, TOPLIP: 5.0, BOTTOMLIP: 5.0, LIDBLINK: 8.0, EYETURN: 5.0, EYETILT: 5.0},
    "happy":     {HEADNOD: 6.0,  TOPLIP: 8.0,  BOTTOMLIP: 2.0, LIDBLINK: 8.0},
    "sad":       {HEADNOD: 3.0,  TOPLIP: 2.0,  BOTTOMLIP: 8.0, LIDBLINK: 4.0},
    "surprised": {HEADNOD: 7.0,  TOPLIP: 5.0,  BOTTOMLIP: 9.0, LIDBLINK: 10.0},
    "wink":      {LIDBLINK: 0.0},
    "curious":   {HEADTURN: 6.5, HEADNOD: 6.0, EYETURN: 6.0, LIDBLINK: 8.0},
}


def expression(mood: str, speed: float = 5.0) -> bool:
    """Apply a named facial pose."""
    pose = _EXPRESSIONS.get((mood or "").lower().strip())
    if pose is None:
        return False
    if not init():
        return False
    for motor, pos in pose.items():
        _move(motor, pos, speed)
    if (mood or "").lower().strip() == "wink":
        time.sleep(0.25)
        _move(LIDBLINK, 10.0, speed=10)
    return True


def eye_color(r: int, g: int, b: int) -> bool:
    """Set the eye LEDs (each channel 0-10)."""
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
    """Speak via the Ohbot board with lip-synced mouth motion.

    Uses ohbot.say(), which on Windows speaks through Microsoft SAPI and drives
    the lip motors in sync. Returns once speech finishes.
    """
    text = (text or "").strip()
    if not text:
        return False
    if not init():
        return False
    try:
        with _lock:
            _ohbot.say(text, untilDone=True, lipSync=bool(lip_sync))
        return True
    except Exception as e:
        _log(f"say error: {e!r}")
        return False
