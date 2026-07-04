"""Head/heads control routes, extracted verbatim from bluetools.py.

Shared state (ROBOTS, _robot_cfg, log) stays in bluetools and is read
via bt.<name> at request time; blue_head is the blue.head module and
is imported directly. /chat/attach and /chat/eyes stay in bluetools
(chat/vision subsystem).
"""
import bluetools as bt
from flask import Response, jsonify, render_template_string, request

from blue import head as blue_head
from blue.server.pages.head import HEAD_HTML, HEADS_HTML, OHBOT_HEADS_JS


# ============================================================================
# Head control GUI + endpoints (this branch only — Vilda's iPad is blocked by
# _restrict_chat_only_users; only /head/lip is allowed for the kid so the chat
# page can drive the lip-flap during speech).
# ============================================================================



def _render_head_page(robot="blue"):
    """Serve the head-tuning GUI for a robot (Blue at /head, Hexia at
    /head/hexia). Same HEAD_HTML; every control targets this robot's head."""
    cfg = bt._robot_cfg(robot)
    return Response(render_template_string(
        HEAD_HTML, head_robot=(robot if robot in bt.ROBOTS else "blue"),
        head_robot_name=cfg["name"],
    ), headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    })



def register(app):
    @app.route('/head', methods=['GET'])
    def head_page():
        """Serve Blue's head tuning GUI. Chat-only users (Vilda) are bounced here by
        _restrict_chat_only_users before this handler runs."""
        return _render_head_page("blue")


    @app.route('/head/<robot>', methods=['GET'])
    def head_page_robot(robot):
        """Per-robot head tuning GUI (e.g. /head/hexia). Static /head/<verb> routes
        (state, move, …) out-rank this, so only real robot names land here."""
        return _render_head_page(robot)


    # All head routes are robot-aware: the bare path (/head/lip-seq) drives Blue for
    # back-compat; the /head/<robot>/... variant (e.g. /head/hexia/lip-seq) drives a
    # named head. `blue_head.get_head(name)` returns the right RobotHead (Blue for
    # any unknown name). A head with no connected board is a graceful no-op.
    # Shared Web Serial head driver — loaded by /duet, the chat pages and /head so a
    # non-PC device (e.g. the MacBook) can drive Ohbot heads plugged into ITS OWN
    # USB-C ports straight from the browser, replicating the slice of the `ohbot`
    # library + blue/head.py the PC uses. Served raw (no Jinja); the doubled
    # backslashes are Python escaping so the browser receives real JS "\n".


    @app.route('/js/ohbot-heads.js', methods=['GET'])
    def ohbot_heads_js():
        """The shared Web Serial head driver (see OHBOT_HEADS_JS). Served raw, no
        cache, so a server restart always ships fresh JS to /duet, chat and /head."""
        return Response(OHBOT_HEADS_JS, headers={
            "Content-Type": "application/javascript; charset=utf-8",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        })


    @app.route('/head/state', methods=['GET'])
    @app.route('/head/<robot>/state', methods=['GET'])
    def head_state(robot='blue'):
        return jsonify(blue_head.get_head(robot).get_calibration())


    @app.route('/head/move', methods=['POST'])
    @app.route('/head/<robot>/move', methods=['POST'])
    def head_move(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        motor = int(d.get('motor', -1))
        pos = float(d.get('pos', blue_head._DEFAULT_CENTER))
        speed = float(d.get('speed', 7))
        ok = h.move_raw(motor, pos, speed)
        return jsonify({"ok": bool(ok)})


    @app.route('/head/calibrate', methods=['POST'])
    @app.route('/head/<robot>/calibrate', methods=['POST'])
    def head_calibrate(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        motor = int(d.get('motor', -1))
        pos = float(d.get('pos', blue_head._DEFAULT_CENTER))
        ok = h.set_center(motor, pos)
        return jsonify({"ok": bool(ok), "centers": h.get_calibration()["centers"]})


    @app.route('/head/eye-color', methods=['POST'])
    @app.route('/head/<robot>/eye-color', methods=['POST'])
    def head_color(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        ok = h.eye_color(int(d.get('r', 0)), int(d.get('g', 0)), int(d.get('b', 0)))
        return jsonify({"ok": bool(ok)})


    @app.route('/head/action', methods=['POST'])
    @app.route('/head/<robot>/action', methods=['POST'])
    def head_action(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        action = (d.get('action') or '').lower().strip()
        times = int(d.get('times') or 2)
        ok = False
        if action.startswith('look_'):
            ok = h.look(action[len('look_'):])
        elif action == 'nod_yes':
            ok = h.nod_yes(times)
        elif action == 'shake_no':
            ok = h.shake_no(times)
        elif action == 'blink':
            ok = h.blink(times)
        elif action in ('happy', 'sad', 'surprised', 'curious', 'neutral', 'wink'):
            ok = h.expression(action)
        return jsonify({"ok": bool(ok), "action": action})


    @app.route('/head/auto', methods=['POST'])
    @app.route('/head/<robot>/auto', methods=['POST'])
    def head_auto(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        h.auto_enable(bool(d.get('enabled', False)))
        return jsonify({"ok": True, "auto_movement": h.auto_enabled()})


    @app.route('/head/lip', methods=['POST'])
    @app.route('/head/<robot>/lip', methods=['POST'])
    def head_lip(robot='blue'):
        """Start or stop the lip-flap loop. Called by the chat page during speech.
        Chat-only users (Vilda's iPad) are blocked upstream by
        _restrict_chat_only_users — the robot stays still while Blue talks to her."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        if bool(d.get('on', False)):
            h.lip_start()
        else:
            h.lip_stop()
        return jsonify({"ok": True, "lip_active": h.lip_is_active()})


    @app.route('/head/lip-seq', methods=['POST'])
    @app.route('/head/<robot>/lip-seq', methods=['POST'])
    def head_lip_seq(robot='blue'):
        """Play a timed mouth schedule the browser built from the reply text, so
        the jaw moves during words and CLOSES during pauses (realistic lip-sync).
        Each frame is [openness 0-1, hold_seconds]. Chat-only users (Vilda's iPad)
        are blocked upstream — Blue doesn't move the robot when talking to her."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        raw = d.get('frames') or []
        frames = []
        for fr in raw[:4000]:
            try:
                op = max(0.0, min(1.0, float(fr[0])))
                hold = max(0.01, min(1.5, float(fr[1])))
                frames.append((op, hold))
            except Exception:
                continue
        if not frames:
            return jsonify({"ok": False, "error": "no frames"}), 400
        h.lip_play_sequence(frames)
        return jsonify({"ok": True, "frames": len(frames)})


    @app.route('/head/reset', methods=['POST'])
    @app.route('/head/<robot>/reset', methods=['POST'])
    def head_reset(robot='blue'):
        return jsonify({"ok": bool(blue_head.get_head(robot).reset())})


    @app.route('/head/restore-defaults', methods=['POST'])
    @app.route('/head/<robot>/restore-defaults', methods=['POST'])
    def head_restore_defaults(robot='blue'):
        h = blue_head.get_head(robot)
        for m, c in blue_head._DEFAULT_CENTERS.items():
            h.set_center(m, c)
        h.reset()
        return jsonify({"ok": True, "centers": h.get_calibration()["centers"]})


    @app.route('/head/reconnect', methods=['POST'])
    @app.route('/head/<robot>/reconnect', methods=['POST'])
    def head_reconnect(robot='blue'):
        h = blue_head.get_head(robot)
        ok = h.reconnect()
        return jsonify({"ok": bool(ok), "available": h.is_available()})


    @app.route('/head/expression', methods=['POST'])
    @app.route('/head/<robot>/expression', methods=['POST'])
    def head_expression_apply(robot='blue'):
        """Apply a named expression (built-in or custom)."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        return jsonify({"ok": bool(h.apply_expression(d.get('name', ''))),
                        "name": d.get('name', '')})


    @app.route('/head/expression-save', methods=['POST'])
    @app.route('/head/<robot>/expression-save', methods=['POST'])
    def head_expression_save(robot='blue'):
        """Save a named pose. If `positions` is omitted, captures the current pose."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        name = (d.get('name') or '').strip()
        positions = d.get('positions') or None
        if positions is not None and not isinstance(positions, dict):
            return jsonify({"ok": False, "error": "positions must be an object"}), 400
        ok = h.save_expression(name, positions)
        if not ok:
            return jsonify({"ok": False, "error": "empty name or collides with a built-in"}), 400
        return jsonify({"ok": True, "expressions": h.list_expressions()})


    @app.route('/head/expression-delete', methods=['POST'])
    @app.route('/head/<robot>/expression-delete', methods=['POST'])
    def head_expression_delete(robot='blue'):
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        ok = h.delete_expression((d.get('name') or '').strip())
        return jsonify({"ok": bool(ok), "expressions": h.list_expressions()})


    @app.route('/head/demo', methods=['POST'])
    @app.route('/head/<robot>/demo', methods=['POST'])
    def head_demo(robot='blue'):
        """Run through every built-in motion + expression once so the user can
        verify everything works."""
        import time as _t, threading as _th
        h = blue_head.get_head(robot)
        sequence = [
            ("action", "look_left"), ("action", "look_right"),
            ("action", "look_up"), ("action", "look_down"), ("action", "look_center"),
            ("action", "nod_yes"), ("action", "shake_no"),
            ("action", "blink"), ("action", "wink"),
            ("expression", "happy"), ("expression", "sad"),
            ("expression", "surprised"), ("expression", "curious"),
            ("expression", "neutral"),
        ]
        def _run():
            try:
                for kind, name in sequence:
                    if kind == "action":
                        if name.startswith("look_"):
                            h.look(name[len("look_"):])
                        elif name == "nod_yes":
                            h.nod_yes(2)
                        elif name == "shake_no":
                            h.shake_no(2)
                        elif name == "blink":
                            h.blink(1)
                        elif name == "wink":
                            h.expression("wink")
                    else:
                        h.expression(name)
                    _t.sleep(1.4)
                h.reset()
            except Exception as e:
                bt.log.warning(f"[HEAD] demo error: {e}")
        _th.Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True})


    @app.route('/head/idle-config', methods=['POST'])
    @app.route('/head/<robot>/idle-config', methods=['POST'])
    def head_idle_config(robot='blue'):
        """Tune the idle loop: frequency (0-10) and amplitude (0-10). Persisted."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        h.set_idle_params(frequency=d.get('frequency'), amplitude=d.get('amplitude'))
        cal = h.get_calibration()
        return jsonify({"ok": True, "idle_frequency": cal["idle_frequency"], "idle_amplitude": cal["idle_amplitude"]})


    @app.route('/head/hf-config', methods=['POST'])
    @app.route('/head/<robot>/hf-config', methods=['POST'])
    def head_hf_config(robot='blue'):
        """Set hands-free wake-word sensitivity (0-10). Chat pages pick up the new
        value at next load (the /chat HTML embeds it as a Jinja-rendered constant)."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        h.set_hf_sensitivity(d.get('sensitivity'))
        return jsonify({"ok": True, "hf_sensitivity": h.get_calibration()["hf_sensitivity"]})


    @app.route('/head/lip-config', methods=['POST'])
    @app.route('/head/<robot>/lip-config', methods=['POST'])
    def head_lip_config(robot='blue'):
        """Lip-sync settings: flip the polarity of either lip motor, and/or set
        how far each lip travels from neutral while talking. Hardware varies
        between Ohbot units — a unit whose mouth arc is narrower than the default
        travel stalls a lip against its mechanical stop (looks stuck), so travel
        is per-robot and user-tunable."""
        h = blue_head.get_head(robot)
        d = request.get_json(silent=True) or {}
        h.set_lip_invert(top=d.get('invert_top'), bottom=d.get('invert_bottom'))
        if d.get('top_range') is not None or d.get('bottom_range') is not None:
            h.set_lip_ranges(top=d.get('top_range'), bottom=d.get('bottom_range'))
        if d.get('flap_speed') is not None:
            h.set_lip_speed(d.get('flap_speed'))
        if d.get('drive') is not None:
            h.set_lip_drive(d.get('drive'))
        cal = h.get_calibration()
        return jsonify({"ok": True,
                        "lip_invert_top": cal["lip_invert_top"], "lip_invert_bottom": cal["lip_invert_bottom"],
                        "lip_top_range": cal["lip_top_range"], "lip_bottom_range": cal["lip_bottom_range"],
                        "lip_speed": cal["lip_speed"], "lip_drive": cal["lip_drive"]})


    @app.route('/head/lip-test', methods=['POST'])
    @app.route('/head/<robot>/lip-test', methods=['POST'])
    def head_lip_test(robot='blue'):
        """Run the lip flap for ~4 seconds so the user can calibrate polarity
        without having to make the robot speak."""
        import time as _t, threading as _th
        h = blue_head.get_head(robot)
        def _run():
            try:
                h.lip_start()
                _t.sleep(4.0)
                h.lip_stop()
            except Exception as e:
                bt.log.warning(f"[HEAD] lip-test error: {e}")
        _th.Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True})


    @app.route('/head/lip-sweep', methods=['POST'])
    @app.route('/head/<robot>/lip-sweep', methods=['POST'])
    def head_lip_sweep(robot='blue'):
        """Sweep each lip motor through its full 0-10 range, one at a time (top
        lip first), then return to rest. Unlike the lip test — which only flaps
        around the calibrated rest — this shows whether each lip physically
        responds anywhere in its range, and where the live zone is, so the user
        can recalibrate the rest position into it."""
        ok = blue_head.get_head(robot).lip_sweep()
        return jsonify({"ok": bool(ok)})


    @app.route('/head/lip-relax', methods=['POST'])
    @app.route('/head/<robot>/lip-relax', methods=['POST'])
    def head_lip_relax(robot='blue'):
        """Power off (detach) just the lip servos so a jammed mouth can be moved
        by hand without the motors fighting back (a stalled servo holds against
        the blockage, buzzes and overheats). The lips re-attach on the next lip
        command — talking, lip test/sweep, a lip slider — or on reset."""
        return jsonify({"ok": bool(blue_head.get_head(robot).lip_relax())})




    @app.route('/heads', methods=['GET'])
    def heads_page():
        """Setup UI: list connected boards and assign each to a robot (Blue/Hexia)."""
        return Response(render_template_string(HEADS_HTML), headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        })


    @app.route('/heads/detect', methods=['GET'])
    def heads_detect():
        """JSON: every serial board, whether it answers the Ohbot handshake, and
        which robot it's pinned to. Used by the /heads setup page."""
        return jsonify(blue_head.detect_boards())


    @app.route('/heads/assign', methods=['POST'])
    def heads_assign():
        """Pin a board (by USB serial number) to a robot role, then reconnect that
        head so the change takes effect immediately."""
        d = request.get_json(silent=True) or {}
        role = (d.get('role') or '').strip().lower()
        serial = (d.get('serial_number') or '').strip()
        if role not in bt.ROBOTS:
            return jsonify({"ok": False, "error": "unknown robot role"}), 400
        if not serial:
            return jsonify({"ok": False, "error": "missing serial_number"}), 400
        blue_head.assign_board(role, serial)
        h = blue_head.get_head(role)
        try:
            h.reconnect()
        except Exception as e:
            bt.log.warning(f"[HEADS] reconnect after assign failed: {e}")
        return jsonify({
            "ok": True,
            "role": role,
            "available": bool(h.is_available()),
            "detect": blue_head.detect_boards(),
        })
