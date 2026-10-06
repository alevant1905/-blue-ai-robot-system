"""Chat transcripts: the conversation list down the left of the chat page.

The chat page tags each turn with the id of the conversation it belongs to
(`"transcript": {"id", "text", "attachments"}` in the POST body), and
chat_completions hands its finished reply to record_turn here. Only tagged
turns are kept: the Ohbot client and scripts post without a tag and are
untouched. Turns that failed are not kept either — the page drops them from
the thread, so the transcript stays the history a reopened chat continues.

The kids' iPad is not transcribed and cannot list transcripts: these routes
stay out of the chat-only allowlist in bluetools.

Shared state stays in bluetools and is read via `bt.<name>` at request time.
"""
import json

import bluetools as bt
from flask import jsonify, request

from blue import transcripts


def _robot_arg() -> str:
    robot = bt._robot_id(request.args.get("robot") or "blue")
    return robot if robot in bt.ROBOTS else "blue"


def _body_as_sent() -> dict:
    """The POST body as it arrived. The pipeline edits the parsed message
    dicts in place (an attached photo is spliced into the user's turn), so
    the cached request.json no longer holds what was said."""
    try:
        body = json.loads(request.get_data(cache=True) or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def record_turn(response, robot: str, user_name: str) -> bool:
    """Keep this chat turn in its conversation's transcript. Never raises."""
    try:
        if user_name in bt._CHAT_ONLY_USERS:
            return False
        if not isinstance(response, dict) or response.get("blue_error"):
            return False
        reply = ((response.get("choices") or [{}])[0]
                 .get("message", {}).get("content") or "")
        body = _body_as_sent()
        tag = body.get("transcript")
        if not isinstance(tag, dict):
            return False
        said = next((
            m.get("content") for m in reversed(body.get("messages") or [])
            if isinstance(m, dict) and m.get("role") == "user"
        ), "")
        return transcripts.record_turn(
            tag.get("id"), robot, user_name, said, reply,
            shown=tag.get("text"), attachments=tag.get("attachments"),
        )
    except Exception as e:
        bt.log.warning(f"[TRANSCRIPT] could not record the turn: {e}")
        return False


def register(app):
    @app.route("/chat/transcripts", methods=["GET"])
    def chat_transcripts():
        user_name = bt._identify_user_from_request()
        return jsonify({"transcripts": transcripts.list_transcripts(_robot_arg(), user_name)})

    @app.route("/chat/transcripts/<conversation_id>", methods=["GET"])
    def chat_transcript(conversation_id):
        user_name = bt._identify_user_from_request()
        found = transcripts.get_transcript(conversation_id, _robot_arg(), user_name)
        if found is None:
            return jsonify({"error": "conversation not found"}), 404
        return jsonify(found)

    @app.route("/chat/transcripts/<conversation_id>", methods=["DELETE"])
    def chat_transcript_delete(conversation_id):
        user_name = bt._identify_user_from_request()
        if not transcripts.delete_transcript(conversation_id, _robot_arg(), user_name):
            return jsonify({"error": "conversation not found"}), 404
        return jsonify({"deleted": True})
