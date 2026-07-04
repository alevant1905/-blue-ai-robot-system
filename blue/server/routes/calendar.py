"""Calendar GUI routes, extracted verbatim from bluetools.py.

Shared state (ENHANCED_TOOLS_AVAILABLE, CalendarManager) stays in
bluetools and is read via `bt.<name>` at request time.
"""
import bluetools as bt
from flask import Response, jsonify, request

from blue.server.pages.calendar import CALENDAR_HTML


def _combine_when(date_str: str, start_str: str) -> str:
    """Build an ISO 'YYYY-MM-DDTHH:MM' from the calendar form's date + time."""
    date_str = (date_str or "").strip()
    start_str = (start_str or "").strip()
    if date_str and start_str:
        return f"{date_str}T{start_str}"
    return date_str or start_str


def register(app):
    @app.route('/calendar', methods=['GET'])
    def calendar_page():
        return Response(CALENDAR_HTML, mimetype="text/html")

    @app.route('/calendar/events', methods=['GET'])
    def calendar_events():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "calendar unavailable"}), 503
        try:
            res = bt.CalendarManager.list_events(
                request.args.get('start', ''),
                request.args.get('end', ''),
                user_name=(request.args.get('user') or None),
            )
            return jsonify(res)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/calendar/event', methods=['POST'])
    def calendar_event_create():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "calendar unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        res = bt.CalendarManager.create_reminder(
            user_name=(d.get('user') or 'Alex'),
            title=(d.get('title') or '').strip() or 'Untitled',
            when=_combine_when(d.get('date'), d.get('start')),
            description=d.get('description') or '',
            end=d.get('end') or '',
            recurrence=d.get('recurrence') or '',
            remind_before=str(d.get('remind_before_min', 0)),
            until=d.get('until') or '',
        )
        return jsonify(res)

    @app.route('/calendar/event/update', methods=['POST'])
    def calendar_event_update():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "calendar unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        try:
            rid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing event id"}), 400
        when = _combine_when(d.get('date'), d.get('start')) if d.get('date') else None
        lead = d.get('remind_before_min')
        res = bt.CalendarManager.update_reminder(
            reminder_id=rid,
            title=d.get('title'),
            when=when,
            end=d.get('end'),
            description=d.get('description'),
            recurrence=d.get('recurrence'),
            remind_before=(str(lead) if lead is not None else None),
            until=d.get('until'),
        )
        return jsonify(res)

    @app.route('/calendar/event/delete', methods=['POST'])
    def calendar_event_delete():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "calendar unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        try:
            rid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing event id"}), 400
        return jsonify(bt.CalendarManager.delete_reminder(rid))
