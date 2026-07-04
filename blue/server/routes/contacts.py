"""Contacts GUI routes, extracted verbatim from bluetools.py.

Shared state (ENHANCED_TOOLS_AVAILABLE, ContactManager) stays in
bluetools and is read via `bt.<name>` at request time.
"""
import bluetools as bt
from flask import Response, jsonify, request

from blue.server.pages.contacts import CONTACTS_HTML


def register(app):
    @app.route('/contacts', methods=['GET'])
    def contacts_page():
        return Response(CONTACTS_HTML, mimetype="text/html")

    @app.route('/contacts/list', methods=['GET'])
    def contacts_list():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "contacts unavailable"}), 503
        try:
            return jsonify(bt.ContactManager.list_contacts(request.args.get('q', '')))
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/contacts', methods=['POST'])
    def contacts_create():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "contacts unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        return jsonify(bt.ContactManager.add_contact(
            name=d.get('name', ''), email=d.get('email', ''),
            phone=d.get('phone', ''), relationship=d.get('relationship', ''),
            notes=d.get('notes', ''),
        ))

    @app.route('/contacts/update', methods=['POST'])
    def contacts_update():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "contacts unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        try:
            cid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing contact id"}), 400
        return jsonify(bt.ContactManager.update_contact(
            cid, name=d.get('name'), email=d.get('email'), phone=d.get('phone'),
            relationship=d.get('relationship'), notes=d.get('notes'),
        ))

    @app.route('/contacts/delete', methods=['POST'])
    def contacts_delete():
        if not bt.ENHANCED_TOOLS_AVAILABLE:
            return jsonify({"success": False, "error": "contacts unavailable"}), 503
        d = request.get_json(force=True, silent=True) or {}
        try:
            cid = int(d.get('id'))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "missing contact id"}), 400
        return jsonify(bt.ContactManager.delete_contact(cid))
