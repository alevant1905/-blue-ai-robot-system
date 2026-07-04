"""Visual-memory GUI routes, extracted verbatim from bluetools.py.

Shared state (VISUAL_MEMORY_AVAILABLE, get_visual_memory, VISUAL_REF_DIR,
FACE_RECOGNITION_AVAILABLE, FACE_ENGINE, execute_tool, _vision_queue)
stays in bluetools and is read via `bt.<name>` at request time.
"""
import json
import os

import bluetools as bt
from flask import Response, jsonify, request
from werkzeug.utils import secure_filename

from blue.server.pages.visual import VISUAL_HTML


def _visual_item(entity_type, e):
    img = e.get("image_path")
    return {
        "id": e["id"],
        "name": e.get("name", ""),
        "relationship": e.get("relationship", "") or "",
        "typical_appearance": e.get("typical_appearance", "") or "",
        "description": e.get("description", "") or "",
        "common_locations": e.get("common_locations", "") or "",
        "typical_contents": e.get("typical_contents", "") or "",
        "typical_lighting": e.get("typical_lighting", "") or "",
        "category": e.get("category", "") or "",
        "typical_location": e.get("typical_location", "") or "",
        "notes": e.get("notes", "") or "",
        "has_image": bool(img and os.path.exists(img)),
    }


_VISUAL_TYPES = {"person", "place", "object"}


def _save_visual_reference(etype, eid, src_path):
    """Copy a captured/uploaded image into the reference dir and point the
    entity at it. Returns the stored path."""
    import shutil
    os.makedirs(bt.VISUAL_REF_DIR, exist_ok=True)
    ext = os.path.splitext(src_path)[1].lower() or ".jpg"
    dest = os.path.join(bt.VISUAL_REF_DIR, f"{etype}_{eid}{ext}")
    shutil.copyfile(src_path, dest)
    bt.get_visual_memory().set_entity_image(etype, eid, dest)
    return dest


def _face_enrollment_feedback(etype, image_path):
    """Best-effort: for a person reference photo, report whether a usable face
    was detected so the GUI can warn when recognition won't work. Returns a
    dict to merge into the route's JSON response."""
    if etype != "person" or not bt.FACE_RECOGNITION_AVAILABLE:
        return {}
    try:
        res = bt.FACE_ENGINE.enroll_validate(image_path)
        if not res.get("available"):
            return {}
        if res.get("face_found"):
            return {"face_found": True}
        return {"face_found": False,
                "warning": "No face detected in this photo — Blue won't be able "
                           "to recognize this person from it. Try a clear, "
                           "front-facing photo."}
    except Exception as e:
        print(f"   [FACE] enrollment validation skipped: {e}")
        return {}


def register(app):
    @app.route('/visual', methods=['GET'])
    def visual_page():
        return Response(VISUAL_HTML, mimetype="text/html")

    @app.route('/visual/list', methods=['GET'])
    def visual_list():
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        etype = request.args.get('type', 'person')
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "error": "bad type"}), 400
        vm = bt.get_visual_memory()
        items = [_visual_item(etype, e) for e in vm.list_entities(etype)]
        return jsonify({"success": True, "items": items})

    @app.route('/visual/entity', methods=['POST'])
    def visual_create():
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        etype = d.get('type')
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "message": "bad type"}), 400
        return jsonify(bt.get_visual_memory().add_entity(etype, d))

    @app.route('/visual/entity/update', methods=['POST'])
    def visual_update():
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        etype = d.get('type')
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "message": "bad type"}), 400
        try:
            eid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing id"}), 400
        return jsonify(bt.get_visual_memory().update_entity(etype, eid, d))

    @app.route('/visual/entity/delete', methods=['POST'])
    def visual_delete():
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        etype = d.get('type')
        try:
            eid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing id"}), 400
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "message": "bad type"}), 400
        return jsonify(bt.get_visual_memory().delete_entity(etype, eid))

    @app.route('/visual/image', methods=['GET', 'POST'])
    def visual_image():
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        if request.method == 'GET':
            etype = request.args.get('type')
            try:
                eid = int(request.args.get('id'))
            except (TypeError, ValueError):
                return ("bad id", 400)
            if etype not in _VISUAL_TYPES:
                return ("bad type", 400)
            e = bt.get_visual_memory().get_entity(etype, eid)
            path = (e or {}).get("image_path")
            if not path or not os.path.exists(path):
                return ("no image", 404)
            from flask import send_file
            return send_file(path)
        # POST: upload a reference photo (multipart: type, id, file)
        etype = request.form.get('type')
        try:
            eid = int(request.form.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing id"}), 400
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "message": "bad type"}), 400
        f = request.files.get('file')
        if not f or not f.filename:
            return jsonify({"success": False, "message": "no file"}), 400
        os.makedirs(bt.VISUAL_REF_DIR, exist_ok=True)
        ext = os.path.splitext(secure_filename(f.filename))[1].lower() or ".jpg"
        dest = os.path.join(bt.VISUAL_REF_DIR, f"{etype}_{eid}{ext}")
        try:
            f.save(dest)
            bt.get_visual_memory().set_entity_image(etype, eid, dest)
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500
        return jsonify({"success": True, **_face_enrollment_feedback(etype, dest)})

    @app.route('/visual/capture', methods=['POST'])
    def visual_capture():
        """Capture from Blue's camera and use it as this entity's reference photo."""
        if not bt.VISUAL_MEMORY_AVAILABLE:
            return jsonify({"success": False, "error": "visual memory unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        etype = d.get('type')
        try:
            eid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing id"}), 400
        if etype not in _VISUAL_TYPES:
            return jsonify({"success": False, "message": "bad type"}), 400
        try:
            raw = bt.execute_tool("capture_camera", {})
            info = json.loads(raw) if isinstance(raw, str) else (raw or {})
            if not info.get("success") or not info.get("filepath"):
                return jsonify({"success": False, "message": info.get("error", "camera unavailable")})
            dest = _save_visual_reference(etype, eid, info["filepath"])
            # Don't let this reference grab linger in the live vision queue.
            try:
                bt._vision_queue.clear()
            except Exception:
                pass
            return jsonify({"success": True, **_face_enrollment_feedback(etype, dest)})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500
