"""
Integration layer for backward compatibility.

Provides the same interface as the pre-refactor flat module for
seamless integration with existing code.
"""

from typing import Dict, List, Optional, Tuple

from .selector import ImprovedToolSelector
from .models import ToolIntent, ToolSelectionResult


def integrate_with_existing_system(
    message: str,
    conversation_messages: List[Dict],
    selector: Optional[ImprovedToolSelector] = None
) -> Tuple[Optional[str], Optional[Dict], Optional[str]]:
    """
    Integration function to use the improved selector with existing Blue code.

    This function provides the same interface as the original integration function,
    making it a drop-in replacement.

    Args:
        message: Current user message
        conversation_messages: Full conversation history
        selector: Instance of ImprovedToolSelector (creates new one if None)

    Returns:
        Tuple of (forced_tool_name, tool_args, user_feedback_message)
        - forced_tool_name: Name of tool to execute, or None
        - tool_args: Arguments for the tool, or None
        - user_feedback_message: Message to show user (e.g., disambiguation), or None

    Example:
        >>> selector = ImprovedToolSelector()
        >>> tool, args, feedback = integrate_with_existing_system(
        ...     "play some jazz music",
        ...     [],
        ...     selector
        ... )
        >>> tool
        'play_music'
        >>> args
        {'query': 'some jazz music'}
        >>> feedback
        None
    """
    # Create selector if not provided
    if selector is None:
        selector = ImprovedToolSelector()

    # Get recent history for context (last 5 messages)
    recent_history = conversation_messages[-5:] if len(conversation_messages) > 5 else conversation_messages

    # Run selection
    result = selector.select_tool(message, recent_history)

    if not result.primary_tool:
        # No tool needed - regular conversation
        return None, None, None

    if result.needs_disambiguation:
        # Ask user for clarification
        return None, None, result.disambiguation_prompt

    # Return the selected tool
    tool_name = result.primary_tool.tool_name
    tool_args = result.primary_tool.extracted_params

    # Add logging (matches original behavior)
    print(f"   [TOOL-SELECTOR] Selected: {tool_name}")
    print(f"   [TOOL-SELECTOR] Confidence: {result.primary_tool.confidence:.2f}")
    print(f"   [TOOL-SELECTOR] Reason: {result.primary_tool.reason}")

    if result.alternative_tools:
        alt_names = [t.tool_name for t in result.alternative_tools[:2]]
        print(f"   [TOOL-SELECTOR] Alternatives: {', '.join(alt_names)}")

    if result.compound_request:
        print(f"   [TOOL-SELECTOR] WARNING: Compound request detected")

    return tool_name, tool_args, None


# Singleton instance for convenience
_default_selector = None


def get_default_selector() -> ImprovedToolSelector:
    """
    Get the default global selector instance.

    Useful for maintaining state across calls without passing selector explicitly.

    Returns:
        Singleton ImprovedToolSelector instance
    """
    global _default_selector
    if _default_selector is None:
        _default_selector = ImprovedToolSelector()
    return _default_selector


def select_tool_simple(message: str, history: List[Dict] = None) -> Optional[str]:
    """
    Simplified interface that just returns the tool name.

    Args:
        message: User message
        history: Optional conversation history

    Returns:
        Tool name or None

    Example:
        >>> select_tool_simple("play some music")
        'play_music'
    """
    selector = get_default_selector()
    result = selector.select_tool(message, history or [])

    if result.primary_tool and not result.needs_disambiguation:
        return result.primary_tool.tool_name

    return None
