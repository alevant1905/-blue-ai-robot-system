"""run.py is how Blue is started, and nothing tested it.

Its service report imported a second copy of the music, lights, Gmail and
camera code from blue/tools/ that the server never ran, so a tick at startup
said nothing about Blue (2026-11-16). It now reads the loaded server. These
tests cover everything in run.py short of opening the port.
"""

import sys
import types

import pytest

import run


def _server(**overrides):
    server = types.SimpleNamespace(
        BRIDGE_IP="10.0.0.89", HUE_USERNAME="user",
        get_hue_lights=lambda: {"1": {}, "2": {}},
        init_youtube_music=lambda: True,
        GMAIL_AVAILABLE=True,
        load_document_index=lambda: {"documents": [{}, {}, {}]},
        ROBOTS={"blue": {"name": "Blue"}, "hexia": {"name": "Hexia"},
                "pico": {"name": "Casper"}},
    )
    for key, value in overrides.items():
        setattr(server, key, value)
    return server


def test_importing_run_leaves_stdout_alone():
    """The console fix ran at import and rewrapped sys.stdout for whoever
    imported the module."""
    import importlib

    before = (sys.stdout, sys.stderr)
    importlib.reload(run)
    assert (sys.stdout, sys.stderr) == before


def test_the_selector_check_passes_and_plays_nothing(capsys):
    assert run.check_modular_imports() is True
    assert "Tool selector" in capsys.readouterr().out


def test_the_report_reads_the_loaded_server(capsys):
    run.check_services(_server())
    out = capsys.readouterr().out
    assert "Philips Hue: 2 light(s) at 10.0.0.89" in out
    assert "YouTube Music: Ready" in out
    assert "Gmail: Available" in out
    assert "Documents: 3 indexed" in out
    assert "Robots: Blue, Hexia, Casper" in out
    assert "❌" not in out


def test_a_bridge_that_does_not_answer_is_a_warning_not_a_tick(capsys):
    run.check_services(_server(get_hue_lights=lambda: {}))
    out = capsys.readouterr().out
    assert "no answer from the bridge at 10.0.0.89" in out
    assert "Philips Hue: 0 light" not in out


def test_one_failing_service_does_not_stop_the_report(capsys):
    def boom():
        raise RuntimeError("index unreadable")

    run.check_services(_server(load_document_index=boom, GMAIL_AVAILABLE=False))
    out = capsys.readouterr().out
    assert "❌ Documents: index unreadable" in out
    assert "Gmail: Not configured" in out
    assert "Robots: Blue, Hexia, Casper" in out


def test_the_real_server_has_everything_the_report_reads():
    """The report is duck-typed; this pins the names to the real module."""
    import bluetools as bt

    for name in ("BRIDGE_IP", "HUE_USERNAME", "get_hue_lights",
                 "init_youtube_music", "GMAIL_AVAILABLE",
                 "load_document_index", "ROBOTS", "app"):
        assert hasattr(bt, name), name
    assert [cfg["name"] for cfg in bt.ROBOTS.values()] == ["Blue", "Hexia", "Casper"]


def test_run_server_reports_then_serves(monkeypatch, capsys):
    import bluetools as bt

    served = []
    started = []
    monkeypatch.setattr(run, "check_services", lambda server: print("REPORT"))
    monkeypatch.setattr(run, "serve_app",
                        lambda app, host, port: served.append((app, host, port)))
    fake_proactive = types.SimpleNamespace(start=lambda: started.append(True))
    monkeypatch.setitem(sys.modules, "blue_proactive", fake_proactive)
    monkeypatch.setenv("BLUE_HOST", "127.0.0.1")
    monkeypatch.setenv("BLUE_PORT", "5999")

    run.run_server()

    assert served == [(bt.app, "127.0.0.1", 5999)]
    assert started == [True]
    assert "REPORT" in capsys.readouterr().out


@pytest.mark.parametrize("name", [
    "ImprovedToolSelector", "ToolIntent", "fuzzy_match", "LMStudioClient",
    "tool_fuzzy_match",
])
def test_the_blue_package_still_resolves_its_old_names(name):
    import blue

    assert getattr(blue, name) is not None


def test_importing_the_blue_package_starts_nothing():
    """`import blue.<anything>` used to import blue.memory, which built the
    live memory system."""
    import subprocess

    code = (
        "import sys, blue, blue.tool_selector, blue.server.security\n"
        "bad = [m for m in ('blue_memory_improved', 'bluetools', 'blue.llm') "
        "if m in sys.modules]\n"
        "print('LOADED', bad)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120).stdout
    assert "LOADED []" in out, out
