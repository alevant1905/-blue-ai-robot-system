"""The chat page's Speed panel: whether the robots think before answering,
and the context their model is loaded with (blue/model_settings.py).

GET  /model/settings  the settings, the choices, and what is loaded now.
POST /model/settings  {"thinking": "off" | "low" | "medium" | "high"} and/or
                      {"context_length": 32768 | null}. A new size reloads the
                      model (seconds; 8 s for qwen3.8-27b), holding the model
                      gate so no reply is cut off by the unload. null goes back
                      to LM Studio's / Bionic's own size the next time it loads.

One model answers all three robots, so the settings are theirs together.
Shared state stays in bluetools and is read via bt.<name> at request time.
"""
import bluetools as bt
from flask import jsonify, request

from blue import lm_model, model_settings
from blue.llm_coordinator import llm_slot


def _base() -> str:
    return lm_model.server_base(bt.LM_STUDIO_URL)


def _state() -> dict:
    loaded = lm_model.loaded_models(_base(), timeout=3)
    model = lm_model.blues_model(loaded or [])
    now = next((i for i in loaded or [] if i.get("model") == model), None)
    return {
        "thinking": model_settings.thinking(),
        "context_length": model_settings.context_length(),
        "choices": {
            "thinking": list(model_settings.THINKING_CHOICES),
            "context_length": list(model_settings.CONTEXT_CHOICES),
        },
        "server": {
            "reachable": loaded is not None,
            "model": model,
            "loaded": now is not None,
            "context_length": (now or {}).get("context_length"),
            # A model outside BLUE_THINKING_MODELS never thinks, whatever
            # the setting (bluetools._model_thinks).
            "can_think": bool(model) and bt._model_thinks(model),
        },
    }


def register(app):
    @app.route('/model/settings', methods=['GET'])
    def model_settings_get():
        return jsonify(_state())

    @app.route('/model/settings', methods=['POST'])
    def model_settings_post():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Send a JSON object."}), 400
        changes = {k: body[k] for k in ("thinking", "context_length") if k in body}
        if not changes:
            return jsonify({"error": "Nothing to change: send thinking "
                                     "and/or context_length."}), 400
        try:
            model_settings.save(**changes)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if "thinking" in changes:
            print(f"   [SPEED] thinking -> {model_settings.thinking()}", flush=True)
        reload = None
        if "context_length" in changes:
            ctx = model_settings.context_length()
            with llm_slot(foreground=True):
                reload = lm_model.apply_context(_base(), ctx)
            # The input budget follows the loaded context: read it again.
            bt._lm_budget_cache["at"] = 0.0
            if reload.get("changed"):
                print(f"   [SPEED] context -> {reload['context_length']:,} tokens: "
                      f"reloaded {reload['model']} in {reload['seconds']}s", flush=True)
            elif not reload.get("ok"):
                print(f"   [SPEED] context -> {ctx}: {reload.get('error')}", flush=True)
            else:
                print(f"   [SPEED] context -> {ctx or 'the server default'} "
                      f"(nothing to reload)", flush=True)
        state = _state()
        state["reload"] = reload
        return jsonify(state), (200 if reload is None or reload.get("ok") else 502)
