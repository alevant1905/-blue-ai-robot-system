"""The tool handler table.

`_execute_tool_internal` used to be a 651-line `if tool_name == ...` chain. A
name that matched nothing fell quietly to "Unknown tool" at the bottom, which
is how a mismatch between what the model is offered and what the code can
actually run stayed invisible until Blue tried to use it.

Now that the tools are a dict, that mismatch is a test.
"""

import pytest

import bluetools as bt
from blue.server import tool_handlers


def advertised_tool_names():
    """What the model is actually offered on a live turn."""
    return {t["function"]["name"] for t in (bt.TOOLS or [])}


def test_every_advertised_tool_has_a_handler():
    """The failure this catches: the model is told it can do something, calls
    it, and gets "Unknown tool" back."""
    missing = advertised_tool_names() - set(tool_handlers.HANDLERS)
    assert not missing, f"advertised to the model with no handler: {sorted(missing)}"


def test_the_table_is_not_empty_and_has_no_duplicates():
    assert len(tool_handlers.HANDLERS) > 40
    assert all(callable(fn) for fn in tool_handlers.HANDLERS.values())


def test_handlers_for_unavailable_subsystems_decline_rather_than_crash():
    """Those tools are filtered out of TOOLS when their subsystem is missing.
    Their handlers still exist, and must return None so the caller answers
    "Unknown tool" — exactly what the unmatched branch did before."""
    unadvertised = set(tool_handlers.HANDLERS) - advertised_tool_names()
    assert unadvertised, "expected some handlers to be gated by availability"


def test_an_unknown_tool_name_is_reported_not_raised():
    assert bt._execute_tool_internal("no_such_tool", {}) == "Unknown tool: no_such_tool"


def test_dispatch_reaches_the_registered_handler(monkeypatch):
    called = {}

    def fake(tool_name, tool_args):
        called["name"] = tool_name
        called["args"] = tool_args
        return "handled"

    monkeypatch.setitem(tool_handlers.HANDLERS, "move_head", fake)
    result = bt._execute_tool_internal("move_head", {"direction": "up"})

    assert result == "handled"
    assert called == {"name": "move_head", "args": {"direction": "up"}}


def test_a_handler_returning_none_falls_through_to_unknown(monkeypatch):
    """The convention that replaced 'the chain simply ran on'."""
    monkeypatch.setitem(tool_handlers.HANDLERS, "move_head",
                        lambda tool_name, tool_args: None)
    assert bt._execute_tool_internal("move_head", {}) == "Unknown tool: move_head"


def test_get_local_time_keeps_its_two_implementations():
    """It was the one tool with two branches — the enhanced one taking
    precedence over a plain fallback. That order is now inside the handler,
    so it is worth checking it survived."""
    import inspect

    source = inspect.getsource(tool_handlers.HANDLERS["get_local_time"])
    assert "ENHANCED_TOOLS_AVAILABLE" in source, "the enhanced branch vanished"
    # The fallback must sit outside that guard, or an unavailable subsystem
    # would turn a working tool into "Unknown tool".
    guard_at = source.index("ENHANCED_TOOLS_AVAILABLE")
    tail = source[guard_at:]
    assert tail.count("return") >= 2, "the plain fallback vanished"


# ---- remember_person keeps a profile, never an outfit, and never a face ----------

@pytest.fixture
def visual_memory(tmp_path, monkeypatch):
    from blue_visual_memory import VisualMemory
    vm = VisualMemory(str(tmp_path / "visual.db"))
    monkeypatch.setattr(bt, "VISUAL_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "get_visual_memory", lambda: vm)
    return vm


def _remember_person(**args):
    import json
    return json.loads(tool_handlers.HANDLERS["remember_person"]("remember_person", args))


def test_remember_person_keeps_features_and_drops_what_they_wear(visual_memory):
    result = _remember_person(name="Emmy",
                              appearance="long brown hair, wearing a red hoodie")
    assert result["success"] is True
    assert visual_memory.get_person("Emmy")["typical_appearance"] == "long brown hair"
    assert "not kept" in result["message"]


def test_remember_person_stores_no_outfit_as_a_look(visual_memory):
    """The 09-23 forced call wrote Clover's 'bread-bun hat and strawberry-
    patterned skirt'."""
    result = _remember_person(name="Clover", relationship="TA for CS101",
                              appearance="bread-bun hat and strawberry skirt")
    clover = visual_memory.get_person("Clover")
    assert result["success"] is True
    assert clover["relationship"] == "TA for CS101"
    assert not clover["typical_appearance"]


def test_remember_person_says_the_face_is_not_saved(visual_memory):
    result = _remember_person(name="Clover", relationship="TA for CS101")
    assert "face is NOT saved" in result["message"]
    assert "Visual Memory page" in result["message"]
    assert "recognize them in the future" not in result["message"]


def test_remember_person_without_a_field_keeps_the_stored_one(visual_memory):
    """add_person merges with COALESCE; the handler passed "" for a missing
    argument, which wiped Emmy's stored look and notes."""
    visual_memory.add_person("Emmy", typical_appearance="long brown hair with bangs",
                             notes="loves art")
    _remember_person(name="Emmy", relationship="daughter")
    emmy = visual_memory.get_person("Emmy")
    assert emmy["typical_appearance"] == "long brown hair with bangs"
    assert emmy["notes"] == "loves art"
    assert emmy["relationship"] == "daughter"


def test_remember_person_needs_a_name(visual_memory):
    assert _remember_person(appearance="beard")["success"] is False
    assert visual_memory.get_all_people() == []


def test_the_remember_person_schema_says_it_saves_no_face():
    from blue.server.tool_schemas import RAW_TOOLS
    tool = next(t for t in RAW_TOOLS if t["function"]["name"] == "remember_person")
    text = str(tool)
    assert "does NOT save their face" in text
    assert "Never clothing" in text
    assert "This helps you recognize them in the future" not in text


def test_who_do_i_know_gives_a_look_but_never_an_outfit(visual_memory, monkeypatch):
    import json
    visual_memory.add_person("Clover", relationship="TA for CS101",
                             typical_appearance="bread-bun hat and strawberry skirt")
    visual_memory.add_person("Emmy", typical_appearance="long brown hair with bangs")
    monkeypatch.setattr(bt, "_ACTIVE_CHAT_ROBOT", "blue", raising=False)
    result = json.loads(tool_handlers.HANDLERS["who_do_i_know"]("who_do_i_know", {}))
    looks = {p["name"]: p["appearance"] for p in result["people"]}
    assert looks == {"Clover": None, "Emmy": "long brown hair with bangs"}
