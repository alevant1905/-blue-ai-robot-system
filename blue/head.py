"""Direct hardware control of an Ohbot head — replaces the Ohbot app.

This module drives one OR MORE Ohbot heads over USB serial via the official
`ohbot` Python library. Each robot head is a `RobotHead` instance with its own
serial connection, calibration file, lip state and idle loop. Blue is the
default head; Hexia (a second Ohbot, the "Xyloh") is a second instance.

Why a class (it used to be module globals):
  The `ohbot` library is a per-import singleton — importing `ohbot.ohbot`
  auto-connects to the FIRST board it finds and keeps one global serial port.
  To run two heads we load an INDEPENDENT copy of that module per instance
  (`_load_private_ohbot`), each pinned to a specific board, so their globals
  (ser/port/connected) don't collide. The Ohbot desktop app must NOT be running
  or it will hold the serial port and our connect will fail.

Board identity is pinned by USB serial number (COM numbers drift across
reboots) in `data/heads.json`, so Blue's physical board stays Blue and Hexia's
stays Hexia. A board that isn't present/assigned degrades to logged no-ops, so
the rest of Blue (and Hexia's persona/chat) keeps running with no hardware.

Back-compat: the original module-level API (`head.look(...)`, `head.init()`,
`head._DEFAULT_CENTER`, …) is preserved as thin aliases onto the default Blue
instance, so every existing `blue_head.*` call site keeps working unchanged.
"""

import importlib.util
import json
import os
import random
import sys
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

# Defaults: 5 for everything; LIDBLINK rests at 8 (eyelids relaxed-open looks
# better on most Ohbot units than a hard 5). Calibration GUI overrides these.
_DEFAULT_CENTERS = {m: _DEFAULT_CENTER for m in ALL_MOTORS}
_DEFAULT_CENTERS[LIDBLINK] = 8.0

# The primary robot — the one that auto-claims a lone board for back-compat.
_PRIMARY = "blue"

# Registry of which physical board belongs to which robot, pinned by USB serial
# number so COM-port renumbering doesn't swap the heads. {role: {serial_number, port_hint}}
_REGISTRY_PATH = os.path.join(os.getcwd(), "data", "heads.json")


def _log(msg: str) -> None:
    print(f"[HEAD] {msg}")


def _clip(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


# ---- ohbot library + serial discovery --------------------------------------

_OHBOT_LIB = False
_OHBOT_PY = None  # filesystem path to ohbot/ohbot.py, for loading private copies
try:
    _sub = importlib.util.find_spec("ohbot.ohbot")  # imports blank pkg __init__ only
    if _sub is not None and _sub.origin:
        _OHBOT_PY = _sub.origin
        _OHBOT_LIB = True
except Exception:
    _OHBOT_LIB = False

try:
    import serial as _serial
    import serial.tools.list_ports as _list_ports_mod
except Exception:
    _serial = None
    _list_ports_mod = None


def _list_boards():
    """All serial ports with their identifying metadata (does not open them)."""
    out = []
    if _list_ports_mod is None:
        return out
    try:
        for p in _list_ports_mod.comports():
            out.append({
                "device": p.device,
                "serial_number": getattr(p, "serial_number", None),
                "vid": getattr(p, "vid", None),
                "pid": getattr(p, "pid", None),
                "description": getattr(p, "description", None),
            })
    except Exception as e:
        _log(f"list ports error: {e!r}")
    return out


def _serial_for_port(device):
    for b in _list_boards():
        if b["device"] == device:
            return b.get("serial_number")
    return None


def _probe_ohbot(device):
    """Send the Ohbot 'v' handshake to a port; return the version ("v1"/"v2") if
    it answers like an Ohbot-compatible board, else None. Opens and CLOSES the
    port — never holds it (so it's safe to probe boards we're not using)."""
    if _serial is None or not device:
        return None
    try:
        s = _serial.Serial(device, 19200)
        s.timeout = 0.5
        s.write_timeout = 0.5
        s.flushInput()
        s.write("v\n".encode("latin-1"))
        line = s.readline()
        s.close()
        if "v1".encode("latin-1") in line:
            return "v1"
        if "v2".encode("latin-1") in line:
            return "v2"
    except Exception:
        return None
    return None


def _load_registry():
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_registry(reg):
    try:
        os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, indent=2)
    except Exception as e:
        _log(f"registry save error: {e!r}")


def assign_board(role, serial_number, port_hint=""):
    """Pin a physical board (by USB serial number) to a robot role. Persists."""
    reg = _load_registry()
    reg[str(role)] = {"serial_number": serial_number, "port_hint": port_hint}
    _save_registry(reg)
    return reg


def _load_private_ohbot(tag, target_port):
    """Load an INDEPENDENT copy of ohbot.ohbot whose module globals (ser, port,
    connected) are private to this instance, connected to `target_port`.

    The real module auto-connects at import by scanning all comports and
    grabbing the first board. We temporarily restrict comports() to just
    `target_port` while the copy loads, so its auto-init grabs exactly our board
    and never touches the other head. Returns the module, or None on failure."""
    if not _OHBOT_LIB or not _OHBOT_PY or _list_ports_mod is None or not target_port:
        return None
    modname = f"ohbot_private_{tag}"
    try:
        spec = importlib.util.spec_from_file_location(modname, _OHBOT_PY)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        real_comports = _list_ports_mod.comports
        try:
            _list_ports_mod.comports = (
                lambda only=target_port, _r=real_comports: [p for p in _r() if p.device == only]
            )
            spec.loader.exec_module(mod)  # runs top-level init() -> connects to target_port
        finally:
            _list_ports_mod.comports = real_comports
        return mod
    except Exception as e:
        _log(f"[{tag}] private ohbot load failed: {e!r}")
        sys.modules.pop(modname, None)
        return None


# ---- Named actions / poses (shared constants) ------------------------------

# Offsets are amount from the calibrated rest; positions get clipped to 0-10.
_LOOK_OFFSETS = {
    "left":  (HEADTURN, +3.0),
    "right": (HEADTURN, -3.0),
    "up":    (HEADNOD,  +3.0),
    "down":  (HEADNOD,  -2.5),
}

# Each expression is { motor: offset_from_center }, applied with clipping.
_EXPRESSIONS = {
    "neutral":   {HEADTURN: 0, HEADNOD: 0, TOPLIP: 0, BOTTOMLIP: 0, LIDBLINK: 0, EYETURN: 0, EYETILT: 0},
    "happy":     {HEADNOD: +1.0, TOPLIP: +3.0, BOTTOMLIP: -3.0, LIDBLINK: 0},
    "sad":       {HEADNOD: -2.0, TOPLIP: -3.0, BOTTOMLIP: +3.0, LIDBLINK: -4.0},
    "surprised": {HEADNOD: +2.0, TOPLIP: 0, BOTTOMLIP: +4.0, LIDBLINK: +2.0},
    "curious":   {HEADTURN: +1.5, HEADNOD: +1.0, HEADROLL: +1.0, EYETURN: +1.0, LIDBLINK: 0},
    "wink":      {LIDBLINK: -8.0},  # both lids close briefly (we only have one)
}

# How far each lip travels at fully-open (offset from its calibrated centre).
# The top lip moves less than the jaw, like real speech.
_LIP_TOP_RANGE = 1.8
_LIP_BOTTOM_RANGE = 3.0

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


# ===========================================================================
# RobotHead — one Ohbot head (one serial board, one calibration, one face)
# ===========================================================================

class RobotHead:
    def __init__(self, name: str, calib_path: str):
        self.name = name
        self._calib_path = calib_path
        self._lock = threading.Lock()
        self._initialized = False
        self._available = False
        self._warned_missing = False
        self._ohbot = None
        self._port = ""

        # Lip-motor polarity varies between Ohbot units, so each lip has an
        # invert flag. With invert=False opening the mouth increases the motor
        # value; invert=True opening decreases it. The GUI exposes both.
        self._calibration = {
            "centers": dict(_DEFAULT_CENTERS),
            "auto_movement": True,
            "lip_invert_top": False,
            "lip_invert_bottom": False,
            # Idle "thoughtful" movement, 0-10 each (user-tuneable from GUI).
            "idle_frequency": 7,   # how often a motion happens (0=quiet, 10=lively)
            "idle_amplitude": 5,   # how big each motion is (0=subtle, 10=expressive)
            # Hands-free wake-word sensitivity on the chat page (0=strict, 10=sensitive).
            "hf_sensitivity": 5,
        }

        self._busy_until = 0.0      # Unix time; idle loop skips if now < this.
        # Last commanded position per motor — read by current_pose().
        self._last_pos = {m: _DEFAULT_CENTERS[m] for m in ALL_MOTORS}

        self._lip_active = False
        self._lip_thread = None
        self._lip_token = 0         # bumped on every new lip action; stale loops stop

        self._auto_thread = None
        self._auto_stop = False

    # ---- Calibration (per-motor rest position) -----------------------------

    def _load_calibration(self):
        """Read calibration JSON from disk if it exists; else keep defaults."""
        try:
            if os.path.exists(self._calib_path):
                with open(self._calib_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_centers = data.get("centers") or {}
                for k, v in saved_centers.items():
                    try:
                        self._calibration["centers"][int(k)] = float(_clip(float(v), _MIN_POS, _MAX_POS))
                    except Exception:
                        pass
                if "auto_movement" in data:
                    self._calibration["auto_movement"] = bool(data["auto_movement"])
                for k in ("lip_invert_top", "lip_invert_bottom"):
                    if k in data:
                        self._calibration[k] = bool(data[k])
                for k in ("idle_frequency", "idle_amplitude", "hf_sensitivity"):
                    if k in data:
                        try:
                            self._calibration[k] = float(_clip(float(data[k]), 0, 10))
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
                    self._calibration["custom_expressions"] = cust
        except Exception as e:
            _log(f"[{self.name}] calibration load skipped: {e!r}")

    def _save_calibration(self):
        try:
            os.makedirs(os.path.dirname(self._calib_path), exist_ok=True)
            out = {
                "centers": {str(k): float(v) for k, v in self._calibration["centers"].items()},
                "auto_movement": bool(self._calibration["auto_movement"]),
                "lip_invert_top": bool(self._calibration.get("lip_invert_top", False)),
                "lip_invert_bottom": bool(self._calibration.get("lip_invert_bottom", False)),
                "idle_frequency": float(self._calibration.get("idle_frequency", 7)),
                "idle_amplitude": float(self._calibration.get("idle_amplitude", 5)),
                "hf_sensitivity": float(self._calibration.get("hf_sensitivity", 5)),
                "custom_expressions": {
                    nm: {str(k): float(v) for k, v in pose.items()}
                    for nm, pose in (self._calibration.get("custom_expressions") or {}).items()
                },
            }
            with open(self._calib_path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
        except Exception as e:
            _log(f"[{self.name}] calibration save error: {e!r}")

    def center(self, motor: int) -> float:
        """Calibrated rest position for a motor (0-10)."""
        return float(self._calibration["centers"].get(int(motor), _DEFAULT_CENTER))

    def get_calibration(self):
        """Snapshot of the current calibration (centers + flags)."""
        return {
            "centers": {int(k): float(v) for k, v in self._calibration["centers"].items()},
            "motor_names": dict(MOTOR_NAMES),
            "auto_movement": bool(self._calibration["auto_movement"]),
            "lip_invert_top": bool(self._calibration.get("lip_invert_top", False)),
            "lip_invert_bottom": bool(self._calibration.get("lip_invert_bottom", False)),
            "idle_frequency": float(self._calibration.get("idle_frequency", 7)),
            "idle_amplitude": float(self._calibration.get("idle_amplitude", 5)),
            "hf_sensitivity": float(self._calibration.get("hf_sensitivity", 5)),
            "available": self._available,
            "current_pose": self.current_pose(),
            "builtin_expressions": sorted(_EXPRESSIONS.keys()),
            "custom_expressions": dict(self._calibration.get("custom_expressions") or {}),
        }

    def set_idle_params(self, frequency=None, amplitude=None) -> bool:
        """Adjust the idle loop. Pass None to leave a value unchanged. Persists."""
        if frequency is not None:
            self._calibration["idle_frequency"] = float(_clip(float(frequency), 0, 10))
        if amplitude is not None:
            self._calibration["idle_amplitude"] = float(_clip(float(amplitude), 0, 10))
        self._save_calibration()
        return True

    def set_hf_sensitivity(self, value) -> bool:
        """Set the hands-free wake-word sensitivity (0-10). Persists."""
        if value is None:
            return False
        self._calibration["hf_sensitivity"] = float(_clip(float(value), 0, 10))
        self._save_calibration()
        return True

    def _idle_interval_range(self):
        """Map the 0-10 frequency slider to a (min, max) seconds-between-motions
        range. 0 = quiet (rare), 5 ≈ original, 10 = nearly constant. While
        SPEAKING (lip-flap active), tighten the range — people gesture more when
        talking; we want head/eye motion to come along with the jaw."""
        f = _clip(float(self._calibration.get("idle_frequency", 7)), 0, 10) / 10.0
        lo, hi = 0.8 + (1 - f) * 5.2, 2.5 + (1 - f) * 9.5
        if self._lip_active:
            lo = max(0.35, lo * 0.45)
            hi = max(1.2, hi * 0.45)
        return (lo, hi)

    def _idle_amp_mult(self):
        """Map the 0-10 amplitude slider to a motion-size multiplier.
        0 → 0.3x (barely there), 5 → 1.0x (original), 10 → 2.0x (expressive).
        Slightly subtler during speech so gestures support the talking."""
        a = _clip(float(self._calibration.get("idle_amplitude", 5)), 0, 10)
        base = 0.3 + (a / 5.0) * 0.7 if a <= 5 else 1.0 + ((a - 5) / 5.0) * 1.0
        return base * 0.7 if self._lip_active else base

    def set_lip_invert(self, top=None, bottom=None) -> bool:
        """Flip the polarity of the top or bottom lip motor. Persists.
        Pass None to leave a flag unchanged."""
        if top is not None:
            self._calibration["lip_invert_top"] = bool(top)
        if bottom is not None:
            self._calibration["lip_invert_bottom"] = bool(bottom)
        self._save_calibration()
        return True

    def set_center(self, motor: int, pos: float) -> bool:
        """Save `pos` as motor's calibrated rest position. Persists to disk."""
        m = int(motor)
        if m not in ALL_MOTORS:
            return False
        self._calibration["centers"][m] = float(_clip(pos, _MIN_POS, _MAX_POS))
        self._save_calibration()
        return True

    # ---- Activity bookkeeping (for the idle loop) --------------------------

    def _mark_busy(self, seconds: float = 1.0):
        t = time.time() + max(0.05, float(seconds))
        if t > self._busy_until:
            self._busy_until = t

    # ---- Connection lifecycle ----------------------------------------------

    def is_available(self) -> bool:
        return self._available

    def _resolve_port(self, port_name: str = ""):
        """Decide which physical board this robot should connect to.
        Explicit arg > registry pin (by USB serial) > (primary only) auto-pick a
        lone unclaimed board. Returns a COM device string, or None."""
        if port_name:
            return port_name
        reg = _load_registry()
        sn = (reg.get(self.name) or {}).get("serial_number")
        boards = _list_boards()
        if sn:
            for b in boards:
                if b.get("serial_number") == sn:
                    return b["device"]
            return None  # assigned board not currently present
        if self.name != _PRIMARY:
            return None  # secondary robots must be explicitly assigned
        # Primary (Blue) back-compat: claim a lone board that isn't pinned elsewhere.
        claimed = {(v or {}).get("serial_number") for v in reg.values() if v}
        candidates = [b for b in boards if b.get("serial_number") not in claimed]
        if len(candidates) == 1:
            return candidates[0]["device"]
        for b in candidates:
            if _probe_ohbot(b["device"]):
                return b["device"]
        return None

    def init(self, port_name: str = "") -> bool:
        """Connect to this robot's Ohbot board (idempotent). Loads calibration
        on first call. A missing/unassigned board is a graceful no-op."""
        if self._initialized:
            return self._available
        self._load_calibration()
        if not _OHBOT_LIB:
            if not self._warned_missing:
                _log("ohbot library not installed (pip install ohbot). Head control disabled.")
                self._warned_missing = True
            self._initialized = True
            return False
        target = self._resolve_port(port_name)
        if not target:
            if not self._warned_missing:
                _log(f"[{self.name}] no board assigned/found — head disabled (no-op).")
                self._warned_missing = True
            self._initialized = True
            self._available = False
            return False
        try:
            oh = _load_private_ohbot(self.name, target)
            if oh is None:
                raise RuntimeError("could not load private ohbot module")
            self._ohbot = oh
            conn_attr = getattr(oh, "connected", True)
            connected_ok = bool(conn_attr() if callable(conn_attr) else conn_attr)
            if not connected_ok:
                raise RuntimeError(f"no board responded on {target}")
            with self._lock:
                oh.reset()
            self._available = True
            self._port = target
            _log(f"[{self.name}] Ohbot head connected on {target} and reset to neutral.")
        except Exception as e:
            _log(f"[{self.name}] could not connect ({e!r}). Is the Ohbot app closed?")
            self._available = False
        self._initialized = True
        # Park everything at the calibrated centres so first impressions match
        # the saved calibration (the board's own reset puts them at 5).
        if self._available:
            self._autopin(target)
            for m in ALL_MOTORS:
                self._move_internal(m, self.center(m), speed=3.0)
        self._start_auto_thread()
        return self._available

    def _autopin(self, target):
        """First successful connect with no registry entry pins this robot to the
        board's USB serial number, so it stays this robot's board across reboots."""
        reg = _load_registry()
        if (reg.get(self.name) or {}).get("serial_number"):
            return
        sn = _serial_for_port(target)
        if sn:
            assign_board(self.name, sn, target)
            _log(f"[{self.name}] pinned to board serial {sn} ({target}).")

    def close(self) -> None:
        self._auto_stop = True
        if _OHBOT_LIB and self._available and self._ohbot is not None:
            try:
                with self._lock:
                    self._ohbot.reset()
                    self._ohbot.close()
                    # ohbot.close() only detaches motors — free the serial port
                    # too so a later reconnect can reopen it.
                    ser = getattr(self._ohbot, "ser", None)
                    if ser is not None:
                        try:
                            ser.close()
                        except Exception:
                            pass
            except Exception as e:
                _log(f"[{self.name}] close() error: {e!r}")
        self._initialized = False
        self._available = False

    def reset(self) -> bool:
        """Return motors to CALIBRATED rest positions and turn off the LEDs."""
        if not self.init():
            return False
        try:
            with self._lock:
                self._ohbot.reset()
            for m in ALL_MOTORS:
                self._move_internal(m, self.center(m), speed=4.0)
            return True
        except Exception as e:
            _log(f"[{self.name}] reset() error: {e!r}")
            return False

    def reconnect(self) -> bool:
        """Force a clean disconnect and reconnect — useful after closing/reopening
        the Ohbot app, plugging in a board, or if the serial link went stale."""
        self.close()
        self._initialized = False
        self._available = False
        self._warned_missing = False
        return self.init()

    # ---- Low-level move ----------------------------------------------------

    def _move_internal(self, motor: int, pos: float, speed: float = 5.0) -> bool:
        """Write to a motor; assumes init() ran and we want the raw pos. Does not
        bump the busy timer (used by the idle loop too)."""
        if not self._available:
            return False
        try:
            pos_c = _clip(pos, _MIN_POS, _MAX_POS)
            with self._lock:
                self._ohbot.move(int(motor), pos_c, _clip(speed, 1.0, 10.0))
            self._last_pos[int(motor)] = float(pos_c)
            return True
        except Exception as e:
            _log(f"[{self.name}] move({motor},{pos},{speed}) error: {e!r}")
            return False

    def current_pose(self):
        """Snapshot of the last commanded position per motor."""
        return {int(k): float(v) for k, v in self._last_pos.items()}

    def _move(self, motor: int, pos: float, speed: float = 5.0) -> bool:
        """Explicit (user/LLM-initiated) move. Bumps the busy timer."""
        if not self.init():
            return False
        self._mark_busy(1.0)
        return self._move_internal(motor, pos, speed)

    def move_raw(self, motor: int, pos: float, speed: float = 5.0) -> bool:
        """Drive a motor directly to an absolute position 0-10 (GUI sliders)."""
        return self._move(motor, pos, speed)

    # ---- Named, higher-level actions (calibration-aware) -------------------

    def look(self, direction: str, speed: float = 4.0) -> bool:
        """Turn/tilt the head: left, right, up, down, center."""
        d = (direction or "").lower().strip()
        if d in ("center", "centre", "forward", "front", "straight", "ahead"):
            self._move(HEADTURN, self.center(HEADTURN), speed)
            self._move(HEADNOD, self.center(HEADNOD), speed)
            return True
        spec = _LOOK_OFFSETS.get(d)
        if not spec:
            return False
        motor, off = spec
        return self._move(motor, self.center(motor) + off, speed)

    def nod_yes(self, times: int = 2) -> bool:
        """Nod up-and-down. Returns to calibrated rest at the end."""
        if not self.init():
            return False
        times = int(_clip(times, 1, 5))
        c = self.center(HEADNOD)
        self._mark_busy(times * 0.75 + 0.5)
        for _ in range(times):
            self._move_internal(HEADNOD, c - 2.0, speed=7)
            time.sleep(0.35)
            self._move_internal(HEADNOD, c + 2.0, speed=7)
            time.sleep(0.35)
        self._move_internal(HEADNOD, c, speed=6)
        return True

    def shake_no(self, times: int = 2) -> bool:
        """Shake side-to-side. Returns to calibrated rest at the end."""
        if not self.init():
            return False
        times = int(_clip(times, 1, 5))
        c = self.center(HEADTURN)
        self._mark_busy(times * 0.75 + 0.5)
        for _ in range(times):
            self._move_internal(HEADTURN, c - 2.0, speed=7)
            time.sleep(0.35)
            self._move_internal(HEADTURN, c + 2.0, speed=7)
            time.sleep(0.35)
        self._move_internal(HEADTURN, c, speed=6)
        return True

    def blink(self, times: int = 1) -> bool:
        """Quick eyelid blink(s). Returns lids to calibrated rest."""
        if not self.init():
            return False
        times = int(_clip(times, 1, 5))
        c = self.center(LIDBLINK)
        self._mark_busy(times * 0.4 + 0.2)
        for _ in range(times):
            self._move_internal(LIDBLINK, 0.0, speed=10)
            time.sleep(0.10)
            self._move_internal(LIDBLINK, c, speed=10)
            time.sleep(0.18)
        return True

    def expression(self, mood: str, speed: float = 5.0) -> bool:
        """Apply a named facial pose (positions relative to calibrated centres)."""
        m = (mood or "").lower().strip()
        pose = _EXPRESSIONS.get(m)
        if pose is None:
            return False
        if not self.init():
            return False
        self._mark_busy(0.8)
        for motor, off in pose.items():
            self._move_internal(motor, self.center(motor) + off, speed)
        if m == "wink":
            time.sleep(0.25)
            self._move_internal(LIDBLINK, self.center(LIDBLINK), speed=10)
        return True

    # ---- Custom expressions (user-saved poses) -----------------------------

    def list_expressions(self):
        """All available expression names: built-in + custom (user-saved)."""
        return {
            "builtin": sorted(_EXPRESSIONS.keys()),
            "custom": sorted((self._calibration.get("custom_expressions") or {}).keys()),
        }

    def save_expression(self, name, positions=None) -> bool:
        """Save a named pose. If positions is None, captures whatever each motor
        was last commanded to. Names that collide with built-ins are rejected."""
        name = (name or "").strip()
        if not name or name.lower() in _EXPRESSIONS:
            return False
        pose_src = positions if positions else self.current_pose()
        pose = {}
        for k, v in pose_src.items():
            try:
                m = int(k)
                if m not in ALL_MOTORS:
                    continue
                pose[m] = float(_clip(float(v), _MIN_POS, _MAX_POS))
            except Exception:
                continue
        cust = dict(self._calibration.get("custom_expressions") or {})
        cust[name] = pose
        self._calibration["custom_expressions"] = cust
        self._save_calibration()
        return True

    def delete_expression(self, name) -> bool:
        cust = dict(self._calibration.get("custom_expressions") or {})
        if name in cust:
            del cust[name]
            self._calibration["custom_expressions"] = cust
            self._save_calibration()
            return True
        return False

    def apply_expression(self, name, speed: float = 5.0) -> bool:
        """Apply ANY named expression (built-in or custom). Custom poses are
        absolute positions; built-ins are relative to calibrated centres."""
        if not self.init():
            return False
        nm = (name or "").strip()
        if nm.lower() in _EXPRESSIONS:
            return self.expression(nm)
        cust = (self._calibration.get("custom_expressions") or {}).get(nm)
        if not cust:
            return False
        self._mark_busy(0.8)
        for motor, pos in cust.items():
            self._move_internal(int(motor), float(pos), speed)
        return True

    def eye_color(self, r: int, g: int, b: int) -> bool:
        if not self.init():
            return False
        try:
            with self._lock:
                self._ohbot.eyeColour(int(_clip(r, 0, 10)), int(_clip(g, 0, 10)), int(_clip(b, 0, 10)))
            return True
        except Exception as e:
            _log(f"[{self.name}] eyeColour error: {e!r}")
            return False

    def say(self, text: str, lip_sync: bool = True) -> bool:
        """Speak via the Ohbot board's SAPI + native lip-sync. Blocks until done."""
        text = (text or "").strip()
        if not text:
            return False
        if not self.init():
            return False
        self._mark_busy(60.0)  # generous; ohbot.say blocks until done
        try:
            with self._lock:
                self._ohbot.say(text, untilDone=True, lipSync=bool(lip_sync))
            return True
        except Exception as e:
            _log(f"[{self.name}] say error: {e!r}")
            return False
        finally:
            self._busy_until = time.time() + 0.3

    # ---- Lip flap during browser-side speech -------------------------------

    def _set_mouth(self, openness: float) -> None:
        """Drive both lip motors to a mouth openness from 0.0 (closed, at
        calibrated rest) to 1.0 (fully open). Per-lip polarity flags decide which
        direction is "open" on this unit (flip a checkbox in the GUI if opposite)."""
        openness = _clip(openness, 0.0, 1.0)
        top_sign = -1.0 if self._calibration.get("lip_invert_top") else +1.0
        bot_sign = -1.0 if self._calibration.get("lip_invert_bottom") else +1.0
        self._move_internal(TOPLIP, self.center(TOPLIP) + top_sign * _LIP_TOP_RANGE * openness, speed=10)
        self._move_internal(BOTTOMLIP, self.center(BOTTOMLIP) + bot_sign * _LIP_BOTTOM_RANGE * openness, speed=10)

    def _lip_loop(self, my_token):
        """Continuous open/shut flap (fallback when no timed sequence is given)."""
        try:
            while self._lip_active and self._available and self._lip_token == my_token:
                self._set_mouth(random.uniform(0.78, 1.0))   # open
                time.sleep(random.uniform(0.08, 0.13))
                if not self._lip_active or self._lip_token != my_token:
                    break
                self._set_mouth(0.0)                          # closed
                time.sleep(random.uniform(0.07, 0.12))
        finally:
            if self._lip_token == my_token:
                self._set_mouth(0.0)

    def _lip_seq_loop(self, my_token, frames):
        """Play a timed mouth schedule: each frame is (openness 0-1, hold seconds).
        The browser builds these from the reply text so the jaw moves during words
        and CLOSES during the gaps — far more lifelike than a constant flap."""
        try:
            for openness, hold in frames:
                if not self._lip_active or self._lip_token != my_token or not self._available:
                    break
                self._set_mouth(openness)
                time.sleep(hold)
        finally:
            if self._lip_token == my_token:
                self._set_mouth(0.0)
                self._lip_active = False

    def lip_start(self) -> bool:
        """Begin the continuous lip-flap (fallback path). Idempotent-ish."""
        if not self.init():
            return False
        self._lip_token += 1
        my = self._lip_token
        self._lip_active = True
        self._mark_busy(120.0)
        self._lip_thread = threading.Thread(
            target=self._lip_loop, args=(my,), name=f"{self.name}-lip-flap", daemon=True)
        self._lip_thread.start()
        return True

    def lip_play_sequence(self, frames) -> bool:
        """Play a timed mouth schedule (list of [openness, hold_seconds]).
        Supersedes any current flap/sequence. The realistic path used in speech."""
        if not self.init() or not frames:
            return False
        self._lip_token += 1
        my = self._lip_token
        self._lip_active = True
        total = sum(h for _, h in frames)
        self._mark_busy(min(120.0, total + 1.0))
        self._lip_thread = threading.Thread(
            target=self._lip_seq_loop, args=(my, frames), name=f"{self.name}-lip-seq", daemon=True)
        self._lip_thread.start()
        return True

    def lip_stop(self) -> bool:
        """Stop any lip motion and close the mouth."""
        self._lip_active = False
        self._lip_token += 1            # invalidate any running loop
        self._set_mouth(0.0)
        self._busy_until = time.time() + 0.3
        return True

    def _lip_sweep_run(self, my_token):
        """Drive each lip through its FULL motor range, one lip at a time, then
        return both to the calibrated rest. Diagnostic for "the lips don't
        move": the talking flap only travels a small band around the calibrated
        rest, so a rest parked in a mechanical dead zone (e.g. the top lip
        pressed below its centre stop) makes speech look frozen even though
        commands flow. The sweep shows where each lip's live zone actually is —
        and a lip that stays still across the whole sweep has a loose servo
        arm/linkage, not a software problem."""
        waypoints = (0.0, 2.5, 5.0, 7.5, 10.0, 5.0)
        try:
            for motor in (TOPLIP, BOTTOMLIP):
                for pos in waypoints:
                    if self._lip_token != my_token or not self._available:
                        return
                    self._move_internal(motor, pos, speed=3.0)
                    time.sleep(0.55)
                self._move_internal(motor, self.center(motor), speed=4.0)
                time.sleep(0.4)
        finally:
            if self._lip_token == my_token:
                self._set_mouth(0.0)

    def lip_sweep(self) -> bool:
        """Start the full-range lip sweep in the background (~8 s). Supersedes
        any running flap/sequence; a new lip action cancels the sweep."""
        if not self.init():
            return False
        self._lip_token += 1
        my = self._lip_token
        self._lip_active = False
        self._mark_busy(16.0)
        threading.Thread(
            target=self._lip_sweep_run, args=(my,),
            name=f"{self.name}-lip-sweep", daemon=True).start()
        return True

    def lip_relax(self) -> bool:
        """De-energize ONLY the lip servos (detach motors 4 & 5). For working
        on the mouth mechanism: a jammed lip servo holds (and buzzes) against
        the blockage and will overheat if left straining — relaxed, the lips
        can be moved by hand to feel where the mechanism binds. They re-attach
        automatically on the next lip command (talking, lip test/sweep, lip
        slider) or on reset/init, which park the lips at their centres."""
        if not self.init():
            return False
        self._lip_active = False
        self._lip_token += 1            # stop any flap/sequence/sweep first
        try:
            with self._lock:
                self._ohbot.detach(TOPLIP)
                self._ohbot.detach(BOTTOMLIP)
            return True
        except Exception as e:
            _log(f"[{self.name}] lip_relax error: {e!r}")
            return False

    def lip_is_active(self) -> bool:
        return bool(self._lip_active)

    # ---- Thoughtful idle motion --------------------------------------------

    def auto_enabled(self) -> bool:
        return bool(self._calibration.get("auto_movement", True))

    def auto_enable(self, on: bool) -> bool:
        """Turn the thoughtful idle loop on/off. Persisted."""
        self._calibration["auto_movement"] = bool(on)
        self._save_calibration()
        return True

    def _nudge(self, motor, offset, speed, hold_min, hold_max):
        """Offset a motor from its calibrated rest, hold briefly, return to rest.
        The offset is scaled by the idle amplitude slider."""
        c = self.center(motor)
        self._move_internal(motor, c + offset * self._idle_amp_mult(), speed=speed)
        time.sleep(random.uniform(hold_min, hold_max))
        self._move_internal(motor, c, speed=speed)

    def _do_idle_motion(self):
        """Pick one small, natural-looking motion (scaled by amplitude slider)."""
        kind, spec = random.choice(_IDLE_RECIPES)
        if kind == "blink":
            c = self.center(LIDBLINK)
            self._move_internal(LIDBLINK, 0.0, speed=10)
            time.sleep(0.10)
            self._move_internal(LIDBLINK, c, speed=10)
        else:
            motor, choices, speed, hold_min, hold_max = spec
            self._nudge(motor, random.choice(choices), speed, hold_min, hold_max)

    def _auto_loop(self):
        """Background thread: subtle motions to keep the head looking alive.
          * idle (no speech) — runs when auto_enabled() and not mid-explicit-move.
          * speaking — runs whenever the lip-flap is active, even if auto idle is
            off, and bypasses _busy_until (the lip thread bumps it 120s)."""
        time.sleep(random.uniform(3.0, 6.0))  # don't fire the instant the server starts
        while not self._auto_stop:
            lo, hi = self._idle_interval_range()
            time.sleep(random.uniform(lo, hi))
            try:
                if not self._available:
                    continue
                if self._lip_active:
                    self._do_idle_motion()  # talking: gesture along, regardless of toggle
                elif self.auto_enabled() and time.time() >= self._busy_until:
                    self._do_idle_motion()
            except Exception as e:
                _log(f"[{self.name}] idle motion error: {e!r}")
                time.sleep(2.0)

    def _start_auto_thread(self):
        if self._auto_thread is not None and self._auto_thread.is_alive():
            return
        self._auto_stop = False
        self._auto_thread = threading.Thread(
            target=self._auto_loop, name=f"{self.name}-head-idle", daemon=True)
        self._auto_thread.start()


# ===========================================================================
# Instances + registry of robots
# ===========================================================================

_CALIB_PATH = os.path.join(os.getcwd(), "data", "head_calibration.json")
_CALIB_PATH_HEXIA = os.path.join(os.getcwd(), "data", "head_calibration_hexia.json")

blue = RobotHead("blue", _CALIB_PATH)
hexia = RobotHead("hexia", _CALIB_PATH_HEXIA)

_ROBOTS = {"blue": blue, "hexia": hexia}


def get_head(name) -> RobotHead:
    """Fetch a robot head by name (defaults to Blue for unknown names)."""
    return _ROBOTS.get((name or _PRIMARY).strip().lower(), blue)


def all_heads():
    return dict(_ROBOTS)


def close_all():
    for h in _ROBOTS.values():
        try:
            h.close()
        except Exception:
            pass


def detect_boards():
    """Snapshot for the setup UI: every serial board, whether it answers the
    Ohbot handshake, and which robot (if any) it's pinned to. Ports currently
    held open by a connected head are reported as compatible without re-probing
    (you can't reopen a held port)."""
    reg = _load_registry()
    role_by_serial = {}
    for role, info in reg.items():
        sn = (info or {}).get("serial_number")
        if sn:
            role_by_serial[sn] = role
    held = {}
    for role, h in _ROBOTS.items():
        if getattr(h, "_available", False) and getattr(h, "_port", ""):
            held[h._port] = role
    boards = []
    for b in _list_boards():
        dev = b["device"]
        sn = b.get("serial_number")
        held_role = held.get(dev)
        boards.append({
            "device": dev,
            "serial_number": sn,
            "vid": b.get("vid"),
            "pid": b.get("pid"),
            "description": b.get("description"),
            "ohbot_compatible": True if held_role else bool(_probe_ohbot(dev)),
            "assigned_to": role_by_serial.get(sn),
            "held_by": held_role,
        })
    return {"boards": boards, "registry": reg}


# ---- Back-compat module-level API (delegates to the default Blue instance) --
# Every existing `blue_head.<fn>(...)` call site keeps working unchanged.
init = blue.init
close = blue.close
reset = blue.reset
reconnect = blue.reconnect
is_available = blue.is_available
look = blue.look
nod_yes = blue.nod_yes
shake_no = blue.shake_no
blink = blue.blink
expression = blue.expression
apply_expression = blue.apply_expression
save_expression = blue.save_expression
delete_expression = blue.delete_expression
list_expressions = blue.list_expressions
eye_color = blue.eye_color
say = blue.say
move_raw = blue.move_raw
set_center = blue.set_center
center = blue.center
get_calibration = blue.get_calibration
auto_enable = blue.auto_enable
auto_enabled = blue.auto_enabled
set_idle_params = blue.set_idle_params
set_hf_sensitivity = blue.set_hf_sensitivity
set_lip_invert = blue.set_lip_invert
lip_start = blue.lip_start
lip_stop = blue.lip_stop
lip_play_sequence = blue.lip_play_sequence
lip_is_active = blue.lip_is_active
lip_sweep = blue.lip_sweep
lip_relax = blue.lip_relax
current_pose = blue.current_pose
