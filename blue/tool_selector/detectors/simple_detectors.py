"""
Simple detectors for straightforward intent patterns.

Includes: Automation, Contacts, Habits, Notes, Timers, System, Utilities, MediaLibrary, Locations
"""

from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class AutomationDetector(BaseDetector):
    """Detects automation and routine intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        # NOTE: run_routine tool is not implemented. "Good morning" / "good night"
        # are handled as greetings by the conversation system, so we don't
        # return a tool intent here to avoid "Unknown tool" errors.
        return []


class ContactsDetector(BaseDetector):
    """Detects contact management intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        # NOTE: list_contacts / add_contact tools are not implemented.
        # Returning no intents to avoid "Unknown tool" errors.
        # The LLM can handle contact-related questions conversationally.
        return []


class HabitsDetector(BaseDetector):
    """Detects habit tracking intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        # NOTE: complete_habit / create_habit tools are not implemented.
        # Returning no intents to avoid "Unknown tool" errors.
        return []


class NotesDetector(BaseDetector):
    """Detects notes and tasks intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        create_signals = ['create note', 'add note', 'make a note', 'save note', 'write note']
        task_signals = ['add task', 'create task', 'new task', 'add to do', 'add todo']
        list_signals = ['show notes', 'list notes', 'my notes', 'show tasks', 'list tasks']

        if any(s in msg_lower for s in create_signals):
            return [ToolIntent(
                tool_name='create_note',
                confidence=0.85,
                priority=ToolPriority.MEDIUM,
                reason="note creation keywords",
                extracted_params={}
            )]
        elif any(s in msg_lower for s in task_signals):
            return [ToolIntent(
                tool_name='create_task',
                confidence=0.85,
                priority=ToolPriority.MEDIUM,
                reason="task creation keywords",
                extracted_params={}
            )]
        elif any(s in msg_lower for s in list_signals):
            return [ToolIntent(
                tool_name='search_notes',
                confidence=0.85,
                priority=ToolPriority.MEDIUM,
                reason="list notes/tasks keywords",
                extracted_params={}
            )]
        return []


class TimersDetector(BaseDetector):
    """Detects timer and reminder intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        timer_signals = ['set timer', 'start timer', 'timer for', 'countdown']
        reminder_signals = ['remind me', 'set reminder', 'reminder to', 'reminder for']

        if any(s in msg_lower for s in timer_signals):
            # Extract duration text for the timer tool
            import re
            duration_match = re.search(r'(?:for\s+)?(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?)', msg_lower)
            params = {}
            if duration_match:
                amount = int(duration_match.group(1))
                unit = duration_match.group(2)
                if unit.startswith('h'):
                    params = {"duration": amount * 3600, "label": f"{amount} hour timer"}
                elif unit.startswith('s'):
                    params = {"duration": amount, "label": f"{amount} second timer"}
                else:
                    params = {"duration": amount * 60, "label": f"{amount} minute timer"}
            else:
                params = {"action": "set_timer"}
            return [ToolIntent(
                tool_name='set_timer',
                confidence=0.90,
                priority=ToolPriority.HIGH,
                reason="timer keywords",
                extracted_params=params
            )]
        elif any(s in msg_lower for s in reminder_signals):
            return [ToolIntent(
                tool_name='create_reminder',
                confidence=0.90,
                priority=ToolPriority.HIGH,
                reason="reminder keywords",
                extracted_params={}
            )]
        return []


class SystemDetector(BaseDetector):
    """Detects system control intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        clipboard_signals = ['copy', 'clipboard', 'paste']
        screenshot_signals = ['screenshot', 'screen capture', 'capture screen']
        volume_signals = ['volume up', 'volume down', 'mute', 'unmute']
        launch_signals = ['open', 'launch', 'start'] if any(app in msg_lower for app in ['chrome', 'firefox', 'notepad', 'calculator']) else []

        if any(s in msg_lower for s in screenshot_signals):
            return [ToolIntent(
                tool_name='take_screenshot',
                confidence=0.90,
                priority=ToolPriority.MEDIUM,
                reason="screenshot keywords",
                extracted_params={}
            )]
        # NOTE: clipboard_operation tool is not implemented, skip it.
        elif launch_signals:
            return [ToolIntent(
                tool_name='launch_application',
                confidence=0.85,
                priority=ToolPriority.MEDIUM,
                reason="launch app keywords",
                extracted_params={}
            )]
        return []


class UtilitiesDetector(BaseDetector):
    """Detects utility operations."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        calc_signals = ['calculate', 'math', 'compute', 'what is', 'how much is']
        date_signals = [
            'what day', 'what date', "today's date", 'current date',
            'what time', 'current time', "what's the time", 'time is it',
            'date and time', 'time and date', 'current date and time',
            'date today', 'time right now',
        ]

        if any(s in msg_lower for s in calc_signals) and any(op in msg_lower for op in ['+', '-', '*', '/', 'plus', 'minus', 'times', 'divided']):
            return [ToolIntent(
                tool_name='run_javascript',
                confidence=0.85,
                priority=ToolPriority.LOW,
                reason="calculation keywords - using JS engine",
                extracted_params={}
            )]
        elif any(s in msg_lower for s in date_signals):
            # Determine if user wants date, time, or both
            date_only = ['what day', 'what date', "today's date", 'current date', 'date today']
            time_only = ['what time', 'current time', "what's the time", 'time is it', 'time right now']
            wants_date = any(s in msg_lower for s in date_only)
            wants_time = any(s in msg_lower for s in time_only)
            if wants_date and not wants_time:
                action = "get_date"
            elif wants_time and not wants_date:
                action = "get_time"
            else:
                action = "get_date_time"
            return [ToolIntent(
                tool_name='get_local_time',
                confidence=0.95,
                priority=ToolPriority.LOW,
                reason="date/time query",
                extracted_params={"action": action}
            )]
        return []


class MediaLibraryDetector(BaseDetector):
    """Detects media library (podcasts) intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        # NOTE: add_podcast / list_podcasts tools are not implemented.
        # Returning no intents to avoid "Unknown tool" errors.
        return []


class LocationsDetector(BaseDetector):
    """Detects location management intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        # NOTE: save_location / list_locations tools are not implemented.
        # Returning no intents to avoid "Unknown tool" errors.
        return []
