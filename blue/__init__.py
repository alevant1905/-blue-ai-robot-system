"""
Blue AI Robot System Package
=============================

Importing this package imports nothing else. It used to import blue.utils,
blue.memory, blue.llm and blue.tool_selector on sight, and blue.memory built
the live memory system, so `import blue.tool_selector` in a test or a script
opened data/enhanced_memory.db. Modules under blue/ are now imported by the
code that uses them.

The names this package re-exported still resolve, on first use:

    from blue import ImprovedToolSelector, fuzzy_match, LMStudioClient
"""

import importlib
from typing import Any

__version__ = "9.1.0"

# name -> (submodule, attribute in that submodule)
_LAZY = {}
for _module, _names in {
    "utils": (
        "setup_logger", "log",
        "parse_compound_request", "detect_follow_up_correction",
        "smart_cache_key", "get_cached_response", "cache_response",
        "estimate_query_complexity", "extract_entities",
        "extract_action_from_query",
        "fuzzy_match", "normalize_artist_name", "safe_json_parse",
        "truncate_text", "extract_quoted_text", "get_time_ago",
        "clean_response_text",
        "ConversationState", "get_conversation_state",
        "validate_response_quality",
    ),
    "llm": (
        "LMStudioClient", "get_lm_client", "call_llm",
        "Settings", "settings",
        "LM_STUDIO_URL", "LM_STUDIO_MODEL", "LM_STUDIO_RAG_URL",
    ),
    "tool_selector": (
        "ToolIntent", "ToolSelectionResult",
        "ImprovedToolSelector", "integrate_with_existing_system",
    ),
}.items():
    for _name in _names:
        _LAZY[_name] = (_module, _name)
_LAZY["tool_fuzzy_match"] = ("tool_selector", "fuzzy_match")
_LAZY["tool_normalize_artist"] = ("tool_selector", "normalize_artist_name")
del _module, _names, _name

__all__ = ["__version__", *sorted(_LAZY)]


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'blue' has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{target[0]}", __name__), target[1])
    globals()[name] = value
    return value


def __dir__():
    return list(__all__)
