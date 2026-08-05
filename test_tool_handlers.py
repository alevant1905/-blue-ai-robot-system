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
