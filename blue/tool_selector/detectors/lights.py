"""
Lights control intent detector.

Detects:
- control_lights: Turn on/off, change color, set mood, adjust brightness
"""

from typing import Dict, List, Optional
import re

from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority
from ..utils import has_word, has_any_word


class LightsDetector(BaseDetector):
    """Detects smart home lighting intents."""

    # Light control keywords
    NOUNS = ['light', 'lights', 'lamp', 'lamps', 'bulb', 'bulbs', 'hue']
    ACTIONS = ['turn on', 'turn off', 'switch on', 'switch off', 'set', 'change', 'dim', 'brighten', 'adjust', 'on', 'off']
    COLORS = [
        'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'white', 'pink',
        'cyan', 'magenta', 'lime', 'teal', 'amber', 'violet', 'turquoise',
        'warm white', 'cool white', 'daylight', 'gold', 'coral', 'salmon'
    ]
    MOODS = [
        'moonlight', 'sunset', 'ocean', 'forest', 'romance', 'party',
        'focus', 'relax', 'energize', 'movie', 'fireplace', 'arctic',
        'sunrise', 'galaxy', 'tropical', 'reading', 'dinner', 'night',
        'cozy', 'warm', 'cool', 'natural', 'romantic', 'chill', 'calm',
        'zen', 'meditation', 'spa', 'beach', 'campfire', 'candle', 'aurora',
        'rainbow', 'disco', 'club', 'concert', 'gaming', 'tv', 'sleep'
    ]

    # Phrases where "light" is an adjective, not about lighting
    LIGHT_ADJECTIVE_PHRASES = [
        'light snack', 'light meal', 'light reading', 'light exercise',
        'light work', 'light duty', 'light touch', 'light breeze',
        'light rain', 'light traffic', 'light weight', 'light load',
        'light blue', 'light green', 'light pink', 'light grey', 'light gray',
        'light brown', 'light yellow', 'light purple', 'light orange',
        'bring to light', 'see the light', 'light of day', 'in light of',
        'light years', 'speed of light', 'light as a feather'
    ]

    # Phrases that should go to visualizer, not lights
    VISUALIZER_PHRASES = ['light show', 'lights dance', 'sync lights', 'disco mode', 'party lights']

    def detect(
        self,
        message: str,
        msg_lower: str,
        context: Dict
    ) -> List[ToolIntent]:
        """Detect light control intents."""
        intents = []

        # Early exits
        if self._is_light_adjective(msg_lower):
            return intents
        if self._is_visualizer_intent(msg_lower):
            return intents

        # Detect control intent
        control_intent = self._detect_control_intent(msg_lower, context)
        if control_intent:
            intents.append(control_intent)

        return intents

    def _is_light_adjective(self, msg_lower: str) -> bool:
        """Check if 'light' is used as adjective."""
        return any(phrase in msg_lower for phrase in self.LIGHT_ADJECTIVE_PHRASES)

    def _is_visualizer_intent(self, msg_lower: str) -> bool:
        """Check if this should go to music visualizer."""
        return any(phrase in msg_lower for phrase in self.VISUALIZER_PHRASES)

    def _detect_control_intent(
        self,
        msg_lower: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect light control intent."""

        has_light = has_any_word(self.NOUNS, msg_lower)
        has_action = any(action in msg_lower for action in self.ACTIONS)
        has_color = has_any_word(self.COLORS, msg_lower)
        has_mood = has_any_word(self.MOODS, msg_lower)

        confidence = 0.0
        reasons = []

        if has_light and (has_action or has_color or has_mood):
            confidence = 0.95
            reasons.append("light + action/color/mood")

        elif has_mood and not has_light:
            # Mood words alone are weak - need context
            set_context = any(w in msg_lower for w in ['set', 'change', 'make', 'switch to', 'turn to'])
            explicit_light_ref = any(w in msg_lower for w in ['it', 'them', 'the lights', 'the light', 'lighting', 'brightness'])

            if set_context and explicit_light_ref and not context.get('has_music_in_history') and 'play' not in msg_lower:
                confidence = 0.70
                reasons.append("mood keyword with set context + light reference")
            else:
                confidence = 0.40  # Too low
                reasons.append("mood keyword but no clear light context")

        elif has_color and ('set' in msg_lower or 'change' in msg_lower or 'make' in msg_lower):
            if has_light or context.get('has_lights_in_history') or 'light' in msg_lower:
                confidence = 0.88
                reasons.append("color + set/change + light context")
            else:
                confidence = 0.45  # Too ambiguous
                reasons.append("color + set/change but no light context")

        elif has_light:
            if has_action or context.get('has_lights_in_history'):
                confidence = 0.65
                reasons.append("light noun mentioned with action/context")
            else:
                confidence = 0.40  # Too low
                reasons.append("light noun only - ambiguous")

        # Exclude visualizer
        if 'visualizer' in msg_lower or 'light show' in msg_lower:
            confidence = 0

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='control_lights',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params=self._extract_params(msg_lower)
        )

    def _extract_params(self, msg_lower: str) -> Dict:
        """Extract light control parameters."""
        params = {'action': 'status'}  # Default

        # Detect action
        if 'turn on' in msg_lower or 'switch on' in msg_lower:
            params['action'] = 'on'
        elif 'turn off' in msg_lower or 'switch off' in msg_lower:
            params['action'] = 'off'

        # Detect mood
        for mood in self.MOODS:
            if mood in msg_lower:
                params['action'] = 'mood'
                params['mood'] = mood
                break

        # Detect color (if no mood found)
        if 'mood' not in params:
            for color in self.COLORS:
                if color in msg_lower:
                    params['action'] = 'color'
                    params['color'] = color
                    break

        # Extract brightness (0-100)
        brightness_patterns = [
            r'(\d{1,3})\s*%',
            r'brightness\s*(?:to\s*)?(\d{1,3})',
            r'(?:at|to)\s*(\d{1,3})\s*(?:percent|%)?',
            r'set\s*(?:to\s*)?(\d{1,3})',
        ]
        for pattern in brightness_patterns:
            match = re.search(pattern, msg_lower)
            if match:
                bri = int(match.group(1))
                if 0 <= bri <= 100:
                    params['brightness'] = int(bri * 254 / 100)  # Convert to 0-254
                    if params['action'] == 'status':
                        params['action'] = 'brightness'
                    break

        # Natural language brightness
        if 'dim' in msg_lower and 'brightness' not in params:
            params['brightness'] = 50
            if params['action'] == 'status':
                params['action'] = 'brightness'
        elif 'bright' in msg_lower and 'brightness' not in params:
            params['brightness'] = 254
            if params['action'] == 'status':
                params['action'] = 'brightness'
        elif 'half' in msg_lower and 'brightness' not in params:
            params['brightness'] = 127
            if params['action'] == 'status':
                params['action'] = 'brightness'

        return params
