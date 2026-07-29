"""Focused guards for Casper/Picoh integration and motor safety."""

import importlib
import json
import logging
import sys
import types

import pytest

from blue import head
from blue_identity import canonical_household_reply


class _FakeSerial:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakePicoh:
    connected = True

    def __init__(self):
        self.moves = []
        self.detached = []
        self.colours = []
        self.shapes = []
        self.ser = _FakeSerial()
        self.closed = False

    def move(self, motor, pos, speed=5, eye=0):
        self.moves.append((motor, pos, speed, eye))

    def detach(self, motor):
        self.detached.append(motor)

    def baseColour(self, r, g, b):
        self.colours.append((r, g, b))

    def setEyeShape(self, shape):
        self.shapes.append(shape)

    def close(self):
        self.closed = True


def test_picoh_is_registered_with_safe_capabilities():
    pico = head.get_head("pico")
    state = pico.get_calibration()

    assert head.all_heads().keys() == {"blue", "hexia", "pico"}
    assert state["driver"] == "picoh"
    assert state["color_target"] == "base"
    assert head.TOPLIP not in state["supported_motors"]
    assert head.HEADROLL not in state["supported_motors"]
    assert state["centers"][head.LIDBLINK] == 10.0


def test_picoh_adapter_never_drives_missing_top_lip_or_roll(
        monkeypatch, tmp_path):
    fake = _FakePicoh()
    monkeypatch.setattr(head, "_PICOH_LIB", True)
    monkeypatch.setattr(head, "_load_private_picoh", lambda _tag, _port: fake)
    monkeypatch.setattr(head, "_serial_for_port", lambda _port: None)

    pico = head.PicohHead("pico-test", str(tmp_path / "pico.json"))
    pico._calibration["auto_movement"] = False
    assert pico.init("COM99")

    before = list(fake.moves)
    assert not pico.move_raw(head.TOPLIP, 7)
    assert not pico.move_raw(head.HEADROLL, 7)
    assert fake.moves == before

    pico._set_mouth(0.75)
    assert fake.moves[-1][0] == head.BOTTOMLIP
    assert all(move[0] != head.TOPLIP for move in fake.moves)
    assert all(move[0] != head.HEADROLL for move in fake.moves)

    assert pico.eye_color(2, 4, 6)
    assert fake.colours[-1] == (2, 4, 6)
    assert pico.expression("happy")
    assert fake.shapes[-1] == "Heart"
    assert pico.eye_expression("alert")
    assert fake.shapes[-1] == "Angry"
    assert pico.eye_expression("curious")
    assert fake.shapes[-1] == "SmallBall"
    # Mood-only eye changes must not add any head/jaw motor movements.
    mood_move_count = len(fake.moves)
    assert pico.eye_expression("sad")
    assert fake.shapes[-1] == "Sad"
    assert len(fake.moves) == mood_move_count

    pico.close()
    assert fake.closed
    assert fake.ser.closed


def test_board_assignment_persists_driver_and_transfers_serial(
        monkeypatch, tmp_path):
    registry = tmp_path / "heads.json"
    monkeypatch.setattr(head, "_REGISTRY_PATH", str(registry))

    head.assign_board("blue", "SERIAL-3", "COM8", driver="ohbot")
    head.assign_board("pico", "SERIAL-3", "COM8", driver="picoh")

    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert "blue" not in saved
    assert saved["pico"] == {
        "serial_number": "SERIAL-3",
        "port_hint": "COM8",
        "driver": "picoh",
    }


def test_casper_has_grounded_household_identity_and_legacy_alias():
    reply = canonical_household_reply(
        "Who is Casper?", robot="blue", user_name="Alex")
    assert reply
    assert "Casper" in reply
    assert "Picoh" in reply
    assert "three servos" in reply
    assert "J-space" in reply
    legacy_reply = canonical_household_reply(
        "Who is Pico?", robot="blue", user_name="Alex")
    assert legacy_reply == reply


@pytest.fixture
def pico_head_routes(monkeypatch):
    fake_bt = types.ModuleType("bluetools")
    fake_bt.log = logging.getLogger("pico-head-test")
    fake_bt.ROBOTS = {
        "blue": {"name": "Blue", "model": "Ohbot"},
        "hexia": {"name": "Hexia", "model": "Xyloh"},
        "pico": {"name": "Casper", "model": "Picoh"},
    }
    fake_bt._robot_id = lambda robot="blue": {
        "casper": "pico", "caspar": "pico", "picoh": "pico",
    }.get((robot or "blue").strip().lower(), (robot or "blue").strip().lower())
    fake_bt._robot_cfg = lambda robot="blue": fake_bt.ROBOTS.get(
        fake_bt._robot_id(robot), fake_bt.ROBOTS["blue"])
    monkeypatch.setitem(sys.modules, "bluetools", fake_bt)
    sys.modules.pop("blue.server.routes.head", None)
    module = importlib.import_module("blue.server.routes.head")
    yield module
    sys.modules.pop("blue.server.routes.head", None)


def test_casper_head_pages_are_routable(pico_head_routes):
    from flask import Flask

    app = Flask(__name__)
    pico_head_routes.register(app)
    client = app.test_client()

    page = client.get("/head/casper")
    assert page.status_code == 200
    assert b"Casper" in page.data
    assert b"Picoh" in page.data

    # Old bookmarks remain connected to Casper's stable internal hardware key.
    state = client.get("/head/pico/state")
    assert state.status_code == 200
    assert state.get_json()["driver"] == "picoh"

    setup = client.get("/heads")
    assert setup.status_code == 200
    assert b'"name": "Casper"' in setup.data
    assert b'"driver": "picoh"' in setup.data


def test_casper_mood_route_changes_base_and_matrix_eyes(
        pico_head_routes, monkeypatch):
    from flask import Flask

    class _MoodHead:
        driver = "picoh"

        def __init__(self):
            self.colour = None
            self.expression_name = None

        def eye_color(self, r, g, b):
            self.colour = (r, g, b)
            return True

        def eye_expression(self, name):
            self.expression_name = name
            return True

    mood_head = _MoodHead()
    monkeypatch.setattr(
        pico_head_routes.blue_head, "get_head", lambda _robot: mood_head)
    app = Flask(__name__)
    pico_head_routes.register(app)

    response = app.test_client().post(
        "/head/casper/mood",
        json={
            "r": 10, "g": 0, "b": 0,
            "name": "alert", "expression": "alert",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert mood_head.colour == (10, 0, 0)
    assert mood_head.expression_name == "alert"
