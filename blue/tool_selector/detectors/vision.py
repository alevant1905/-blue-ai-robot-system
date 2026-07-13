"""Vision and camera intent detector."""

import re
from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


# ---- Camera view-control extraction (shared with bluetools' fast path) ----
# "what's on your left" / "look up and tell me what you see" → look direction;
# "zoom in on the table" / "look closer at the bottom right" → zoom + region.

_LOOK_DIR_RE = re.compile(
    r"\b(?:look|turn(?:\s+your\s+head)?|glance|face)\s+(?:to\s+)?(?:the\s+|your\s+)?(left|right|up|down)\b")
_SIDE_RE = re.compile(r"\b(?:on|to|at)\s+(?:your|the)\s+(left|right)\b")
_LOOK_BACK_RE = re.compile(r"\blook\s+(?:back\s+)?(?:at\s+the\s+)?(?:center|centre|straight|forward|ahead)\b")
_ZOOM_RE = re.compile(r"\bzoom(?:\s+(?:in|into|on|at))?\b|\bcloser look\b|\blook closer\b|\bmagnify\b|\bget closer\b")
_ZOOM_HARD_RE = re.compile(r"\b(?:way|right|really|much) (?:in|closer)\b|\bas close as\b|\bmax(?:imum)? zoom\b")
_ZOOM_REGION_RE = re.compile(
    r"\b(?:zoom[^.?!]*?|closer[^.?!]*?)\b(?:on|into|at|to)\s+the\s+"
    r"(top[- ]?left|top[- ]?right|bottom[- ]?left|bottom[- ]?right|left|right|top|bottom|middle|center|centre)\b")


def extract_camera_view_args(msg_lower: str) -> dict:
    """Pull camera view-control params (look / zoom / zoom_region) out of a
    message. Empty dict when none are present (plain straight-on capture)."""
    args = {}
    m = _LOOK_DIR_RE.search(msg_lower) or _SIDE_RE.search(msg_lower)
    if m:
        args["look"] = m.group(1)
    elif _LOOK_BACK_RE.search(msg_lower):
        args["look"] = "center"
    if _ZOOM_RE.search(msg_lower):
        args["zoom"] = 4.0 if _ZOOM_HARD_RE.search(msg_lower) else 2.0
        mr = _ZOOM_REGION_RE.search(msg_lower)
        if mr:
            reg = mr.group(1).replace(" ", "-")
            args["zoom_region"] = "center" if reg in ("middle", "centre") else reg
    return args


# ---- Snapshot-by-email ("take a photo of what you see and email it to me") ----
# Both halves must be present: a delivery phrase AND a photo/live-view phrase.
# "send an email to john" (no photo) and "take a photo" (no delivery) fall
# through to send_gmail / capture_camera as before.

_EMAIL_SNAPSHOT_MAIL_TRIGGERS = (
    'email me', 'email it', 'email that', 'email this', 'email a ',
    'email the ', 'email your', 'email what you', 'mail me', 'mail it',
    'send me', 'send it to', 'send that to', 'send this to', 'send one to',
    'by email', 'via email', 'in an email', 'over email',
    'to my email', 'to my inbox', 'and email', 'then email',
)
_EMAIL_SNAPSHOT_PHOTO_TRIGGERS = (
    'photo', 'picture', 'snapshot', 'snap of', 'snap a', 'image',
    'what you see', "what you're seeing", 'what you are seeing',
    'what you can see', 'what do you see', 'your view', 'your camera',
    'through your eyes', 'in front of you',
)
# Questions about PAST sending ("did you send me the picture?") are not a
# request to capture anything new.
_EMAIL_SNAPSHOT_NOT_NOW = (
    'did you send', 'did you email', 'have you sent', 'have you emailed',
    'when did you send', 'when did you email',
)


def is_email_snapshot_request(msg_lower: str) -> bool:
    """True when the user wants a FRESH camera shot delivered by email —
    'email me a photo of what you see', 'take a snapshot and send it to me'."""
    msg_lower = msg_lower.replace('e-mail', 'email').replace('e mail', 'email')
    if any(t in msg_lower for t in _EMAIL_SNAPSHOT_NOT_NOW):
        return False
    return (any(t in msg_lower for t in _EMAIL_SNAPSHOT_MAIL_TRIGGERS)
            and any(t in msg_lower for t in _EMAIL_SNAPSHOT_PHOTO_TRIGGERS))


_SNAP_TO_ADDR_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
# "email/send ... to <name>" — a contact name the executor resolves to an
# address. Single token only; anything pronoun-ish below is "me" → default.
_SNAP_TO_NAME_RE = re.compile(
    r"\b(?:email|send|mail|shoot|fire)\b[^.?!]*?\bto\s+([a-z][a-z'.-]{1,30})\b")
_SNAP_NOT_RECIPIENTS = {
    'me', 'my', 'myself', 'us', 'you', 'your', 'yourself', 'it', 'that',
    'this', 'the', 'him', 'her', 'them', 'blue', 'everyone', 'someone',
    'email', 'mail', 'gmail', 'inbox', 'see', 'look', 'show',
}


def extract_email_snapshot_args(msg_lower: str) -> dict:
    """Params for the email_snapshot tool: camera view control plus the
    recipient (explicit address, or a contact name; absent means Alex)."""
    args = extract_camera_view_args(msg_lower)
    m = _SNAP_TO_ADDR_RE.search(msg_lower)
    if m:
        args["to"] = m.group(0)
    else:
        m = _SNAP_TO_NAME_RE.search(msg_lower)
        if m and m.group(1) not in _SNAP_NOT_RECIPIENTS:
            args["to"] = m.group(1)
    return args


class VisionDetector(BaseDetector):
    """Detects camera, image viewing, and recognition intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        # Snapshot-by-email outranks both plain capture and plain send: when
        # the message asks for a photo DELIVERED, neither half alone is right.
        snapshot_email_intent = self._detect_email_snapshot_intent(msg_lower, context)
        if snapshot_email_intent:
            intents.append(snapshot_email_intent)

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

    def _detect_email_snapshot_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        """'Email me a photo of what you see' → the composite email_snapshot
        tool (one deterministic capture+send; the local model can't be trusted
        to chain capture_camera then send_gmail itself)."""
        if not is_email_snapshot_request(msg_lower):
            return None
        return ToolIntent(
            tool_name='email_snapshot',
            confidence=0.97,
            priority=ToolPriority.CRITICAL,
            reason='photo of current view requested by email',
            extracted_params=extract_email_snapshot_args(msg_lower)
        )

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
        # Aim/zoom requests — the camera with view control ("what's to your
        # left", "zoom in on the table", "look up and tell me what you see").
        view_control_signals = [
            "what's on your left", "what's on your right",
            "what's to your left", "what's to your right",
            'what is on your left', 'what is on your right',
            'what is to your left', 'what is to your right',
            'see on your left', 'see on your right',
            'see to your left', 'see to your right',
            'zoom in', 'zoom into', 'zoom on', 'look closer', 'closer look',
            'look up and', 'look down and', 'look left and', 'look right and',
            'look to your left and', 'look to your right and',
        ]

        confidence = 0.0
        reasons = []

        # Statements ABOUT the camera/eyes/abilities and negated instructions
        # are not capture requests: "you already had control of the camera
        # and now you can change the color of your eyes" got the room
        # described back (2026-07-12), and "no need to describe what's in
        # front of you" re-fired a capture. Mirrors the guards in bluetools'
        # detect_camera_capture_intent.
        if re.search(r"\b(?:no need|don'?t|do not|stop|never|quit|enough|without)\b"
                     r"[^.!?]{0,50}\b(?:describ\w*|look\w*|captur\w*|photo\w*|"
                     r"picture\w*|camera|see|view)\b", msg_lower):
            return None
        if re.search(r"\b(?:that(?:'s| is)|this is|it(?:'s| is)|here(?:'s| is))\s+"
                     r"(?:exactly\s+)?what(?:'s| is)?\b", msg_lower):
            return None
        if (re.search(r"\byou (?:can|could|also|now|already|have|had)\b[^.!?]{0,60}"
                      r"\b(?:camera|eyes?|body)\b", msg_lower)
                and not any(s in msg_lower for s in live_view_signals)
                and not any(s in msg_lower for s in strong_signals)):
            return None

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.95
            reasons.append("explicit camera keywords")
        elif any(s in msg_lower for s in live_view_signals):
            confidence = 0.90
            reasons.append("live-view request - capturing camera")
        elif any(s in msg_lower for s in view_control_signals):
            confidence = 0.88
            reasons.append("view-control capture (aim/zoom)")
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
            extracted_params=extract_camera_view_args(msg_lower)
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

        # "When did you last see Stella?" / "have you seen Nori?" — recall
        # about a SPECIFIC person/thing. Extract what follows see/saw/seen as
        # the search query so the tool searches observations instead of just
        # dumping the 24h timeline.
        person_recall_signals = [
            'when did you last see', 'when did you see', 'last time you saw',
            'when was the last time you saw', 'have you seen', 'last saw',
            'who have you seen',
        ]

        if any(s in msg_lower for s in person_recall_signals):
            params = {}
            m = re.search(r"(?:see|saw|seen)\s+([a-z][a-z .'\-]{1,40}?)\s*[?.!]*$", msg_lower)
            if m:
                q = re.sub(r'^(?:the|my|our)\s+', '', m.group(1).strip())
                q = re.sub(r'\s*(?:today|yesterday|recently|lately|'
                           r'this (?:morning|afternoon|evening|week))$', '', q).strip()
                if q and q not in ('me', 'anything', 'something', 'anyone', 'someone'):
                    params['query'] = q
            return ToolIntent(
                tool_name='recall_visual_memory',
                confidence=0.88,
                priority=ToolPriority.HIGH,
                reason='last-seen recall about a person/thing',
                extracted_params=params
            )

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
