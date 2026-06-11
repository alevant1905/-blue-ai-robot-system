"""
Gmail intent detector.

Detects:
- read_gmail: Check/read emails
- send_gmail: Send new emails
- reply_gmail: Reply to emails
"""

import re
from typing import Dict, List, Optional

from .base import BaseDetector
from .vision import is_email_snapshot_request
from ..models import ToolIntent
from ..constants import ToolPriority


class GmailDetector(BaseDetector):
    """Detects Gmail/email-related intents."""

    def detect(
        self,
        message: str,
        msg_lower: str,
        context: Dict
    ) -> List[ToolIntent]:
        """Detect Gmail intents."""
        # Normalize "e-mail" / "e mail" -> "email" so detection isn't fooled
        # by a hyphen. Real-world transcriptions vary wildly here.
        msg_lower = msg_lower.replace("e-mail", "email").replace("e mail", "email")

        intents = []

        # Detect read intent
        read_intent = self._detect_read_intent(msg_lower, context)
        if read_intent:
            intents.append(read_intent)

        # Detect send intent
        send_intent = self._detect_send_intent(msg_lower, message, context)
        if send_intent:
            intents.append(send_intent)

        # Detect reply intent
        reply_intent = self._detect_reply_intent(msg_lower, context)
        if reply_intent:
            intents.append(reply_intent)

        return intents

    def _detect_read_intent(
        self,
        msg_lower: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect read email intent."""

        read_signals = {
            'strong': [
                'check my email', 'check email', 'check my inbox',
                'read my email', 'read my gmail', 'check my gmail',
                'show my inbox', 'any new email', 'unread email', 'recent email'
            ],
            'medium': ['check', 'read', 'show', 'see'],
            'weak': ['email', 'gmail', 'inbox', 'message']
        }

        confidence = 0.0
        reasons = []

        # Strong signals
        if any(signal in msg_lower for signal in read_signals['strong']):
            confidence = 0.95
            reasons.append("explicit read keywords")

        # Medium signals need email context
        elif any(verb in msg_lower for verb in read_signals['medium']):
            if any(noun in msg_lower for noun in read_signals['weak']):
                confidence = 0.80
                reasons.append("read verb + email noun")
            elif context.get('has_email_in_history'):
                confidence = 0.70
                reasons.append("read verb + email context")

        # Weak signals need strong context
        elif any(noun in msg_lower for noun in read_signals['weak']):
            if context.get('has_email_in_history'):
                confidence = 0.50
                reasons.append("email noun + conversation context")

        # Exclude if sending or replying
        if 'send' in msg_lower or 'reply' in msg_lower or 'respond' in msg_lower:
            confidence = max(0, confidence - 0.4)
            reasons.append("reduced: send/reply detected")

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='read_gmail',
            confidence=confidence,
            priority=ToolPriority.CRITICAL,
            reason=' | '.join(reasons),
            extracted_params=self._extract_read_params(msg_lower)
        )

    def _detect_send_intent(
        self,
        msg_lower: str,
        message: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect send email intent."""

        # "Email me a photo of what you see" is the composite email_snapshot
        # (VisionDetector emits it) — a plain send_gmail here would win the
        # confidence sort and mail an empty message with no photo.
        if is_email_snapshot_request(msg_lower):
            return None

        send_signals = {
            'strong': [
                'send email to', 'send an email', 'email to', 'compose email',
                'send to', 'write email to', 'send them an email'
            ],
            'medium': ['send', 'compose', 'draft']
        }

        # Follow-up imperatives — "go ahead", "send it now", "do it again", etc.
        # On their own these don't mention email. They only fire when the
        # recent conversation already established a send_gmail intent that
        # didn't complete.
        followup_imperatives = (
            "go ahead", "send it", "send that", "send it now", "send it again",
            "do it", "do it now", "try it now", "try again", "retry",
            "send again", "resend", "go on then",
        )
        is_followup_imperative = any(p in msg_lower for p in followup_imperatives)

        confidence = 0.0
        reasons = []

        if any(signal in msg_lower for signal in send_signals['strong']):
            confidence = 0.95
            reasons.append("explicit send keywords")

            # Boost if email address detected
            if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', message):
                confidence = min(1.0, confidence + 0.05)
                reasons.append("email address found")

        elif any(verb in msg_lower for verb in send_signals['medium']) and (
            'email' in msg_lower or 'message' in msg_lower
        ):
            confidence = 0.75
            reasons.append("send verb + email context")

        # Follow-up imperative: "go ahead", "send it now", "send it again" with
        # recent email context. Runs regardless of whether 'send' appeared
        # alone (a bare 'send' didn't pass the email-noun check above).
        if confidence == 0.0 and is_followup_imperative:
            recent_tools = context.get("recent_tools") or []
            recent_email_tool = bool(recent_tools) and recent_tools[0] in ("send_gmail", "reply_gmail")
            if context.get("has_email_in_history") or recent_email_tool:
                confidence = 0.80
                reasons.append("follow-up imperative + recent email context")

        # Exclude if reading
        if any(word in msg_lower for word in ['check', 'read', 'show my']):
            confidence = max(0, confidence - 0.3)
            reasons.append("reduced: read indicators")

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='send_gmail',
            confidence=confidence,
            priority=ToolPriority.CRITICAL,
            reason=' | '.join(reasons),
            extracted_params=self._extract_send_params(msg_lower)
        )

    def _detect_reply_intent(
        self,
        msg_lower: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect reply to email intent."""

        reply_signals = {
            'strong': [
                'reply to', 'respond to', 'reply to all', 'send a reply',
                'write a reply', 'answer the email', 'reply to email'
            ],
            'medium': ['reply', 'respond', 'answer']
        }

        confidence = 0.0
        reasons = []

        if any(signal in msg_lower for signal in reply_signals['strong']):
            confidence = 0.95
            reasons.append("explicit reply keywords")
        elif any(verb in msg_lower for verb in reply_signals['medium']):
            if any(noun in msg_lower for noun in ['email', 'message', 'inbox']):
                confidence = 0.80
                reasons.append("reply verb + email context")

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='reply_gmail',
            confidence=confidence,
            priority=ToolPriority.CRITICAL,
            reason=' | '.join(reasons),
            extracted_params=self._extract_reply_params(msg_lower)
        )

    def _extract_read_params(self, msg_lower: str) -> Dict:
        """Extract parameters for read operation."""
        params = {}

        # Detect unread filter
        if 'unread' in msg_lower:
            params['unread'] = True

        # Detect from filter
        from_match = re.search(r'from\s+([A-Za-z0-9._%+-]+(?:@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})?)', msg_lower)
        if from_match:
            params['from'] = from_match.group(1)

        # Detect count
        count_match = re.search(r'(\d+)\s+(?:most recent|latest|last|recent)', msg_lower)
        if count_match:
            params['max_results'] = int(count_match.group(1))
        else:
            params['max_results'] = 10  # Default

        return params

    def _extract_send_params(self, msg_lower: str) -> Dict:
        """Extract parameters for send operation."""
        params = {}

        # Extract email address
        email_match = re.search(r'\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b', msg_lower)
        if email_match:
            params['to'] = email_match.group(1)

        # Extract subject (quoted text)
        subject_match = re.search(r'subject\s*[:\"]?\s*["\']([^"\']+)["\']', msg_lower)
        if subject_match:
            params['subject'] = subject_match.group(1)

        # Extract body (quoted text)
        body_match = re.search(r'(?:body|saying|message)\s*[:\"]?\s*["\']([^"\']+)["\']', msg_lower)
        if body_match:
            params['body'] = body_match.group(1)

        return params

    def _extract_reply_params(self, msg_lower: str) -> Dict:
        """Extract parameters for reply operation."""
        params = {}

        # Reply to all
        if 'reply to all' in msg_lower or 'reply all' in msg_lower:
            params['reply_all'] = True

        # Extract body (quoted text)
        body_match = re.search(r'(?:saying|message)\s*[:\"]?\s*["\']([^"\']+)["\']', msg_lower)
        if body_match:
            params['body'] = body_match.group(1)

        return params
