"""
Intent detectors organized by domain.

Each detector is responsible for identifying user intents related to
a specific feature domain (music, email, lights, etc.).
"""

from .base import BaseDetector, DetectorRegistry
from .music import MusicDetector
from .gmail import GmailDetector
from .lights import LightsDetector
from .documents import DocumentsDetector
from .web import WebDetector
from .scholar import ScholarDetector
from .vision import VisionDetector
from .weather import WeatherDetector
from .calendar import CalendarDetector
from .simple_detectors import (
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

__all__ = [
    'BaseDetector',
    'DetectorRegistry',
    'MusicDetector',
    'GmailDetector',
    'LightsDetector',
    'DocumentsDetector',
    'WebDetector',
    'ScholarDetector',
    'VisionDetector',
    'WeatherDetector',
    'CalendarDetector',
    'AutomationDetector',
    'ContactsDetector',
    'HabitsDetector',
    'NotesDetector',
    'TimersDetector',
    'SystemDetector',
    'UtilitiesDetector',
    'MediaLibraryDetector',
    'LocationsDetector',
]
