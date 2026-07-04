"""
Blue AI Robot System Package
=============================
A modular home assistant with music, lights, email, vision, and more.

Usage:
    from blue import utils, memory, llm
    from blue.utils import ConversationState, fuzzy_match
    from blue.memory import load_blue_facts, save_blue_facts
    from blue.llm import call_llm, LMStudioClient
"""

__version__ = "12.5.0"

# Re-export commonly used items for convenience
from .utils import (
    # Logging
    setup_logger, log,
    # Compound request parsing
    parse_compound_request, detect_follow_up_correction,
    # Caching
    smart_cache_key, get_cached_response, cache_response,
    # Query analysis
    estimate_query_complexity, extract_entities, extract_action_from_query,
    # String utilities
    fuzzy_match, normalize_artist_name, safe_json_parse,
    truncate_text, extract_quoted_text, get_time_ago, clean_response_text,
    # Conversation state
    ConversationState, get_conversation_state, validate_response_quality,
)

from .memory import (
    # Facts
    BLUE_FACTS, BLUE_FACTS_DB,
    load_blue_facts, save_blue_facts, extract_and_save_facts,
    build_system_preamble,
    # Memory system availability
    ENHANCED_MEMORY_AVAILABLE,
)

from .llm import (
    # Client
    LMStudioClient, get_lm_client, call_llm,
    # Settings
    Settings, settings,
    # URLs
    LM_STUDIO_URL, LM_STUDIO_MODEL, LM_STUDIO_RAG_URL,
)

from .tool_selector import (
    # Data classes
    ToolIntent, ToolSelectionResult,
    # Selector
    ImprovedToolSelector, integrate_with_existing_system,
    # Utilities
    fuzzy_match as tool_fuzzy_match, normalize_artist_name as tool_normalize_artist,
)

__all__ = [
    # Version
    '__version__',
    # Utils
    'setup_logger', 'log',
    'parse_compound_request', 'detect_follow_up_correction',
    'smart_cache_key', 'get_cached_response', 'cache_response',
    'estimate_query_complexity', 'extract_entities', 'extract_action_from_query',
    'fuzzy_match', 'normalize_artist_name', 'safe_json_parse',
    'truncate_text', 'extract_quoted_text', 'get_time_ago', 'clean_response_text',
    'ConversationState', 'get_conversation_state', 'validate_response_quality',
    # Memory
    'BLUE_FACTS', 'BLUE_FACTS_DB',
    'load_blue_facts', 'save_blue_facts', 'extract_and_save_facts',
    'build_system_preamble', 'ENHANCED_MEMORY_AVAILABLE',
    # LLM
    'LMStudioClient', 'get_lm_client', 'call_llm',
    'Settings', 'settings',
    'LM_STUDIO_URL', 'LM_STUDIO_MODEL', 'LM_STUDIO_RAG_URL',
    # Tool Selector
    'ToolIntent', 'ToolSelectionResult',
    'ImprovedToolSelector', 'integrate_with_existing_system',
    'tool_fuzzy_match', 'tool_normalize_artist',
]
