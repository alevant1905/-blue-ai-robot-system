import json

from flask import Flask

from blue.server.routes import tts


def _voice(voice_id, locale="en-CA", name="Liam", gender="Male"):
    return {
        "id": voice_id,
        "name": name,
        "locale": locale,
        "gender": gender,
        "personalities": ["Friendly"],
        "categories": ["General"],
        "provider": "edge",
    }


def _app(monkeypatch, tmp_path):
    voices = [
        _voice("en-CA-LiamNeural"),
        _voice("fr-CA-AntoineNeural", "fr-CA", "Antoine"),
    ]
    monkeypatch.setattr(tts, "_PREFS_PATH", str(tmp_path / "voices.json"))
    monkeypatch.setattr(tts, "get_voice_catalog", lambda force=False: list(voices))
    app = Flask(__name__)
    tts.register(app)
    app.testing = True
    return app


def test_voice_catalog_can_be_filtered_by_language(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()

    response = client.get("/tts/voices?lang=en")

    assert response.status_code == 200
    assert response.json["count"] == 1
    assert response.json["voices"][0]["id"] == "en-CA-LiamNeural"


def test_default_preferences_are_distinct_and_neural(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()

    blue = client.get("/tts/preferences/blue").json
    hexia = client.get("/tts/preferences/hexia").json
    casper = client.get("/tts/preferences/casper").json

    assert blue["provider"] == hexia["provider"] == casper["provider"] == "edge"
    assert casper["robot"] == "casper"
    assert len({blue["voice"], hexia["voice"], casper["voice"]}) == 3


def test_preference_is_persisted_per_robot(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()

    response = client.post(
        "/tts/preferences/casper",
        json={"provider": "edge", "voice": "en-CA-LiamNeural"},
    )

    assert response.status_code == 200
    assert client.get("/tts/preferences/casper").json["voice"] == "en-CA-LiamNeural"
    assert client.get("/tts/preferences/pico").json["voice"] == "en-CA-LiamNeural"
    with open(tmp_path / "voices.json", encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["pico"] == {"provider": "edge", "voice": "en-CA-LiamNeural"}


def test_unknown_neural_voice_is_rejected(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()

    response = client.post(
        "/tts/preferences/blue",
        json={"provider": "edge", "voice": "not-a-real-voice"},
    )

    assert response.status_code == 400
    assert response.json["error"] == "unknown neural voice"


def test_synthesis_returns_audio_and_clamps_controls(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    seen = {}

    def fake_audio(text, voice, rate, pitch):
        seen.update(text=text, voice=voice, rate=rate, pitch=pitch)
        return b"fake-mp3"

    monkeypatch.setattr(tts, "_cached_audio", fake_audio)
    response = app.test_client().post(
        "/tts/synthesize",
        json={
            "text": "Hello Casper",
            "voice": "en-CA-LiamNeural",
            "rate": 99,
            "pitch": -10,
        },
    )

    assert response.status_code == 200
    assert response.data == b"fake-mp3"
    assert response.content_type == "audio/mpeg"
    assert seen == {
        "text": "Hello Casper",
        "voice": "en-CA-LiamNeural",
        "rate": 2.0,
        "pitch": 0.5,
    }


def test_synthesis_rejects_oversized_text(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()

    response = client.post(
        "/tts/synthesize",
        json={"text": "x" * (tts._MAX_TEXT_CHARS + 1), "voice": "en-CA-LiamNeural"},
    )

    assert response.status_code == 413
