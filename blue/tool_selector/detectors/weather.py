"""Weather intent detector."""

from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class WeatherDetector(BaseDetector):
    """Detects weather forecast requests."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        weather_intent = self._detect_weather_intent(msg_lower)
        if weather_intent:
            intents.append(weather_intent)

        return intents

    def _detect_weather_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        strong_signals = [
            'weather forecast', 'check weather', 'what is the weather',
            "what's the weather", 'weather today', 'weather this week'
        ]
        weather_nouns = ['weather', 'forecast', 'temperature', 'rain', 'snow', 'precipitation']
        question_verbs = ['what', 'how', 'will it', 'is it']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.95
            reasons.append("explicit weather keywords")
        elif any(n in msg_lower for n in weather_nouns):
            if any(v in msg_lower for v in question_verbs):
                confidence = 0.85
                reasons.append("weather noun + question")
            else:
                confidence = 0.70
                reasons.append("weather noun mentioned")

        if confidence <= 0:
            return None

        # Extract location if present, default to local
        params = {}
        if ' in ' in msg_lower:
            parts = msg_lower.split(' in ')
            if len(parts) > 1:
                params['location'] = parts[1].split()[0]
        if not params:
            params = {"location": "local"}

        return ToolIntent(
            tool_name='get_weather',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params=params
        )
