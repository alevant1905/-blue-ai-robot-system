"""
Main tool selector orchestrator.

Coordinates all detectors and manages tool selection logic.
"""

from typing import List, Dict, Optional
from collections import Counter

from .models import ToolIntent, ToolSelectionResult
from .constants import ToolPriority, ConfidenceThreshold, MIN_CONFIDENCE_GAP
from .context import extract_context, should_skip_tool_selection
from .detectors import (
    DetectorRegistry,
    MusicDetector,
    GmailDetector,
    LightsDetector,
    DocumentsDetector,
    WebDetector,
    ScholarDetector,
    VisionDetector,
    WeatherDetector,
    CalendarDetector,
    AutomationDetector,
    ContactsDetector,
    HabitsDetector,
    NotesDetector,
    TimersDetector,
    SystemDetector,
    UtilitiesDetector,
    MediaLibraryDetector,
    LocationsDetector,
)


class ImprovedToolSelector:
    """
    Enhanced tool selection engine with confidence scoring and context awareness.

    Coordinates multiple domain-specific detectors to identify user intents.
    """

    def __init__(self):
        """Initialize the tool selector with all detectors."""
        self.registry = DetectorRegistry()
        self.tool_usage_history = Counter()
        self.disambiguation_memory = {}
        self._register_all_detectors()

    def _register_all_detectors(self):
        """Register all available detectors."""
        # High-priority detectors
        self.registry.register('music', MusicDetector(), enabled=True)
        self.registry.register('gmail', GmailDetector(), enabled=True)

        # Medium-priority detectors
        self.registry.register('lights', LightsDetector(), enabled=True)
        self.registry.register('calendar', CalendarDetector(), enabled=True)
        self.registry.register('weather', WeatherDetector(), enabled=True)
        self.registry.register('documents', DocumentsDetector(), enabled=True)
        self.registry.register('vision', VisionDetector(), enabled=True)
        self.registry.register('timers', TimersDetector(), enabled=True)

        # Supporting detectors
        self.registry.register('web', WebDetector(), enabled=True)
        self.registry.register('scholar', ScholarDetector(), enabled=True)
        self.registry.register('notes', NotesDetector(), enabled=True)
        self.registry.register('system', SystemDetector(), enabled=True)
        self.registry.register('utilities', UtilitiesDetector(), enabled=True)

        # Contacts now has real handlers (add/list/find_contact).
        self.registry.register('contacts', ContactsDetector(), enabled=True)

        # Disabled: these detectors return tool names with no handler implemented
        # self.registry.register('automation', AutomationDetector(), enabled=True)
        # self.registry.register('habits', HabitsDetector(), enabled=True)
        # self.registry.register('media_library', MediaLibraryDetector(), enabled=True)
        # self.registry.register('locations', LocationsDetector(), enabled=True)

    def select_tool(
        self,
        message: str,
        conversation_history: List[Dict] = None
    ) -> ToolSelectionResult:
        """
        Main entry point for tool selection.

        Args:
            message: Current user message
            conversation_history: Recent conversation messages for context

        Returns:
            ToolSelectionResult with primary tool and alternatives
        """
        if conversation_history is None:
            conversation_history = []

        # Check if this is just casual chat (greetings, thanks, etc.)
        if should_skip_tool_selection(message):
            return ToolSelectionResult(
                primary_tool=None,
                alternative_tools=[],
                needs_disambiguation=False,
                disambiguation_prompt=None,
                compound_request=False
            )

        # Extract context from history
        context = extract_context(conversation_history)

        # Check for compound requests
        compound = self._detect_compound_patterns(message.lower())

        # Run all enabled detectors
        all_intents = self._detect_all_intents(message, context)

        # Filter out low-confidence intents
        viable_intents = [
            intent for intent in all_intents
            if intent.confidence >= ConfidenceThreshold.MINIMUM
        ]

        if not viable_intents:
            # No clear tool needed
            return ToolSelectionResult(
                primary_tool=None,
                alternative_tools=[],
                needs_disambiguation=False,
                disambiguation_prompt=None,
                compound_request=compound
            )

        # Sort by confidence (highest first), then by priority (lowest number = higher priority)
        viable_intents.sort(key=lambda x: (-x.confidence, x.priority))

        # Get primary and alternatives
        primary = viable_intents[0]
        alternatives = viable_intents[1:5]  # Top 4 alternatives

        # Check if disambiguation needed
        needs_disambiguation = False
        disambiguation_prompt = None

        if len(alternatives) > 0:
            # Check if top choice is ambiguous
            confidence_gap = primary.confidence - alternatives[0].confidence

            if confidence_gap < MIN_CONFIDENCE_GAP and primary.confidence < ConfidenceThreshold.HIGH:
                needs_disambiguation = True
                disambiguation_prompt = self._create_disambiguation_prompt(
                    primary, alternatives[:2]
                )

        # Remove conflicting intents from alternatives
        alternatives = [
            alt for alt in alternatives
            if not self._are_conflicting_intents(primary, alt)
        ]

        return ToolSelectionResult(
            primary_tool=primary,
            alternative_tools=alternatives,
            needs_disambiguation=needs_disambiguation,
            disambiguation_prompt=disambiguation_prompt,
            compound_request=compound
        )

    def _detect_all_intents(
        self,
        message: str,
        context: Dict
    ) -> List[ToolIntent]:
        """Run all enabled detectors and collect intents."""
        all_intents = []
        msg_lower = message.lower()

        for detector in self.registry.get_all_enabled():
            try:
                intents = detector.detect(message, msg_lower, context)
                all_intents.extend(intents)
            except Exception as e:
                # Log error but continue with other detectors
                print(f"Error in detector {detector.__class__.__name__}: {e}")

        return all_intents

    def _detect_compound_patterns(self, msg_lower: str) -> bool:
        """Check if message contains multiple requests."""
        from .constants import COMPOUND_CONJUNCTIONS

        for conjunction in COMPOUND_CONJUNCTIONS:
            if conjunction in msg_lower:
                return True

        return False

    def _are_conflicting_intents(self, intent1: ToolIntent, intent2: ToolIntent) -> bool:
        """Check if two intents conflict with each other."""
        # Same tool = not a conflict, just duplicate detection
        if intent1.tool_name == intent2.tool_name:
            return True

        # Define conflicting pairs
        conflicts = {
            ('read_gmail', 'send_gmail'),
            ('read_gmail', 'reply_gmail'),
            ('play_music', 'control_music'),
            ('search_documents', 'web_search'),
            ('search_scholar', 'web_search'),
            ('search_scholar', 'search_documents'),
        }

        pair = (intent1.tool_name, intent2.tool_name)
        reverse_pair = (intent2.tool_name, intent1.tool_name)

        return pair in conflicts or reverse_pair in conflicts

    def _create_disambiguation_prompt(
        self,
        primary: ToolIntent,
        alternatives: List[ToolIntent]
    ) -> str:
        """Create a disambiguation question for the user."""
        tool_names = {
            'read_gmail': 'read your email',
            'send_gmail': 'send an email',
            'play_music': 'play music',
            'control_lights': 'control lights',
            'search_documents': 'search your documents',
            'web_search': 'search the web',
            'search_scholar': 'search academic journals',
        }

        primary_name = tool_names.get(primary.tool_name, primary.tool_name)
        alt_names = [
            tool_names.get(alt.tool_name, alt.tool_name)
            for alt in alternatives
        ]

        if len(alt_names) == 1:
            return f"Did you want to {primary_name} or {alt_names[0]}?"
        else:
            alt_str = ', '.join(alt_names[:-1]) + f', or {alt_names[-1]}'
            return f"Did you want to {primary_name}, {alt_str}?"

    def record_tool_usage(self, tool_name: str, was_successful: bool):
        """
        Record tool usage for learning patterns.

        Args:
            tool_name: Name of the tool that was used
            was_successful: Whether the tool executed successfully
        """
        if was_successful:
            self.tool_usage_history[tool_name] += 1
