"""Vision and camera intent detector."""

from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class VisionDetector(BaseDetector):
    """Detects camera, image viewing, and recognition intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        camera_intent = self._detect_camera_intent(msg_lower, context)
        if camera_intent:
            intents.append(camera_intent)

        view_intent = self._detect_view_image_intent(msg_lower, context)
        if view_intent:
            intents.append(view_intent)

        recognition_intent = self._detect_recognition_intent(msg_lower, context)
        if recognition_intent:
            intents.append(recognition_intent)

        remember_intent = self._detect_remember_person_intent(msg_lower, context)
        if remember_intent:
            intents.append(remember_intent)

        recall_intent = self._detect_recall_intent(msg_lower, context)
        if recall_intent:
            intents.append(recall_intent)

        return intents

    def _detect_camera_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        strong_signals = [
            'take a picture', 'take a photo', 'capture image', 'camera capture',
            'snap a photo', 'take screenshot', 'get an image'
        ]
        # Present-tense "look right now" phrasings. Blue is a physical robot
        # with a camera, so "what do you see" means look through it NOW — a
        # live capture, not a recollection. Past-tense ("what did you see")
        # is handled separately by _detect_recall_intent, so these stay
        # strictly present tense to avoid stealing recall queries.
        live_view_signals = [
            'what do you see', 'what can you see', 'what are you seeing',
            'what are you looking at', 'what do you see right now',
            'describe what you see', 'tell me what you see',
            "what's in front of you", 'what is in front of you',
            'look around', 'look through your camera', 'use your camera',
            'open your camera', 'turn on your camera', 'can you see me',
            'do you see me', 'look at me', 'what does it look like there',
        ]
        camera_keywords = ['camera', 'picture', 'photo', 'image', 'snapshot', 'capture']
        action_verbs = ['take', 'capture', 'snap', 'get', 'grab']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.95
            reasons.append("explicit camera keywords")
        elif any(s in msg_lower for s in live_view_signals):
            confidence = 0.90
            reasons.append("live-view request - capturing camera")
        elif any(v in msg_lower for v in action_verbs) and any(k in msg_lower for k in camera_keywords):
            confidence = 0.85
            reasons.append("action verb + camera keyword")

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='capture_camera',
            confidence=confidence,
            priority=ToolPriority.HIGH,
            reason=' | '.join(reasons),
            extracted_params={}
        )

    def _detect_view_image_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        strong_signals = [
            'show me the image', 'display the picture', 'view the photo',
            'let me see', 'show the picture', 'display image'
        ]
        view_verbs = ['show', 'display', 'view', 'see', 'look at']
        image_nouns = ['image', 'picture', 'photo', 'screenshot']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.90
            reasons.append("explicit view image keywords")
        elif any(v in msg_lower for v in view_verbs) and any(n in msg_lower for n in image_nouns):
            confidence = 0.80
            reasons.append("view verb + image noun")
        elif context.get('has_camera_in_history'):
            if any(v in msg_lower for v in view_verbs):
                confidence = 0.70
                reasons.append("view verb + camera context")

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='view_image',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params={}
        )

    def _detect_recognition_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        face_signals = [
            'who is this', 'who is that', 'recognize face', 'identify person',
            'who am i looking at', "who's this", "who's that"
        ]
        place_signals = [
            'where is this', 'what place is this', 'recognize location',
            'identify place', 'where am i'
        ]

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in face_signals):
            confidence = 0.92
            reasons.append("face recognition keywords - capturing camera")
        elif any(s in msg_lower for s in place_signals):
            confidence = 0.92
            reasons.append("place recognition keywords - capturing camera")

        if confidence <= 0:
            return None

        # Recognition requires a camera capture first; the vision model
        # handles identification from the captured image.
        return ToolIntent(
            tool_name='capture_camera',
            confidence=confidence,
            priority=ToolPriority.HIGH,
            reason=' | '.join(reasons),
            extracted_params={}
        )

    def _detect_remember_person_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        """Detect intent to store/update person information in visual memory."""
        # Person-related context — must be present for any match
        has_person_context = any(w in msg_lower for w in [
            'glasses', 'beard', 'mustache', 'hair', 'tall', 'short',
            'wears', 'looks like', 'appearance', 'face',
        ])
        # Names being explicitly taught
        has_name_teaching = any(s in msg_lower for s in [
            'his name is', 'her name is', 'their name is',
            "that's not", 'wrong person', 'wrong name',
            "you're confusing", 'mixed up',
        ])

        if not has_person_context and not has_name_teaching:
            return None

        # Remember/correction signals (only evaluated when person context exists)
        remember_signals = [
            'remember that', 'remember this', 'i want you to remember',
            "don't forget", 'keep in mind',
        ]
        correction_signals = [
            "doesn't have", "doesn't wear", 'only has',
            'has glasses', 'has a beard', 'has a mustache',
            'not felix', 'not alex',
        ]

        has_remember = any(s in msg_lower for s in remember_signals)
        has_correction = any(s in msg_lower for s in correction_signals)

        if has_name_teaching:
            return ToolIntent(
                tool_name='remember_person',
                confidence=0.95,
                priority=ToolPriority.HIGH,
                reason='person identity correction',
                extracted_params={}
            )
        elif has_person_context and (has_remember or has_correction):
            return ToolIntent(
                tool_name='remember_person',
                confidence=0.93,
                priority=ToolPriority.HIGH,
                reason='person memory update/correction',
                extracted_params={}
            )
        return None

    def _detect_recall_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        # Strong signals - clearly about visual recall
        strong_recall_signals = [
            'what did you see', 'what have you seen', 'what did you notice',
            'who was here', 'who did you see',
            'visual memory', 'remember seeing', 'earlier you saw',
            'visual timeline', 'what have you observed',
            'what were you looking at', 'last time you looked',
            'do you remember seeing', 'what did you observe'
        ]

        # Weak signals - only valid with camera context
        weak_recall_signals = [
            'what changed', "what's changed", "what's different",
            'what was happening', 'what happened today'
        ]

        if any(s in msg_lower for s in strong_recall_signals):
            return ToolIntent(
                tool_name='recall_visual_memory',
                confidence=0.90,
                priority=ToolPriority.HIGH,
                reason='visual memory recall keywords',
                extracted_params={}
            )
        elif any(s in msg_lower for s in weak_recall_signals):
            # Only trigger if there's camera/vision history
            if context.get('has_camera_in_history'):
                return ToolIntent(
                    tool_name='recall_visual_memory',
                    confidence=0.75,
                    priority=ToolPriority.HIGH,
                    reason='weak recall signal + camera context',
                    extracted_params={}
                )
        return None
