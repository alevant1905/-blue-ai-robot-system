"""
Gmail intent detector.

Detects:
- read_gmail: Check/read emails
- send_gmail: Send new emails
- reply_gmail: Reply to emails
"""

import re
from functools import lru_cache
from typing import Dict, List, Optional

from .base import BaseDetector
from .vision import is_email_snapshot_request
from ..models import ToolIntent
from ..constants import ToolPriority
from ..utils import has_any_word


_ADDRESS_RE = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
_EMAIL_NOUNS = ['email', 'emails', 'mail', 'gmail', 'inbox']

# The robots' names, as they open a request: "hexia check my email",
# "Casper send Stella an email…". Spoken to Hexia or Casper with no comma
# (push-to-talk rarely writes one), "hexia" was taken for the clause's first
# word and the request for a statement, so the mail tools were never offered
# (S4 final review). The same names as blue_identity._ROBOT_NAME_ALT.
_ROBOT_NAMES = r"(?:blue|hexia|casper|caspar|kasper|pico|picoh)"

# Blue as the RECIPIENT: "I think I've got a draft to send to you" was read
# as "send to" at 0.95 and mailed alex.levant@example.com (2026-08-12).
_SENT_TO_BLUE_RE = re.compile(
    r"\bsend(?:ing)?\b(?:[^.!?]{0,30}\bto\s+you\b|\s+(?:it\s+)?you\b)")

# A reply to an email, as opposed to "how would you respond to her" or "what
# did she say in reply to that argument", which scored reply_gmail at 0.95.
_REPLY_IMPERATIVE_RE = re.compile(
    r"^\s*(?:(?:" + _ROBOT_NAMES + r"|ok(?:ay)?|please|now|so|and)[,\s]+)*"
    r"(?:reply|respond|write\s+(?:a\s+)?reply)\b")


_SEND_IMPERATIVE_RE = re.compile(
    r"^\s*(?:(?:" + _ROBOT_NAMES
    + r"|ok(?:ay)?|please|now|so|and|then|hey)[,\s]+)*"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+)?"
    r"send\b[^.!?]{0,40}\bto\b")
_SEND_NEGATED_RE = re.compile(
    r"\b(?:don'?t|do\s+not|never|no\s+need\s+to|won'?t|shouldn'?t)\s+"
    r"(?:\w+\s+){0,2}(?:send|e-?mail)\b")
_SEND_ASKED_ABOUT_RE = re.compile(
    r"^\s*(?:(?:" + _ROBOT_NAMES + r"|so|and|hey)[,\s]+)*"
    r"(?:did|have|has|why\s+did|when\s+did|"
    r"who\s+did|what\s+did|where\s+did)\b[^.!?]{0,60}\bsen[dt]\b")


# Email tools act on Alex's real inbox, so they need a request addressed to
# Blue, not a sentence about email. "i'm thinking of having my DH399 students
# build an agent that reads the news and emails them a digest" read the inbox
# at 0.80 on "read" + "email" (harness, 2026-10-05), and "It summarizes news
# and sends the newsfeed by email to me", Alex describing his autoGPT, forced
# send_gmail at 0.95 on "email to" (live, 2026-09-27). A verb is asked for
# when it opens its clause ("check your e-mail"), follows a request frame
# ("can you…", "I want you to…", "go ahead and…"), or is joined by "and" to a
# verb that does ("check your e-mail and reply…", "draft and send").
_READ_VERBS = ("check", "read", "show", "see", "look", "open")
_SEND_VERBS = ("send", "email", "compose", "write", "draft", "resend",
               "forward")
_REPLY_VERBS = ("reply", "respond", "answer", "write")
_FOLLOWUP_ASKS = ("go ahead", "do it", "try it", "try again", "retry",
                  "go on then")
# A reply asked for with the noun: "send a reply to stella's email", "compose
# a reply to the email from felix". Read only as a verb, these lost
# reply_gmail to send_gmail, and Felix would get a new email instead of a
# threaded reply (S4 review).
_REPLY_ASK_RE = re.compile(
    r"\b(?:" + "|".join(_REPLY_VERBS) + r")\b"
    r"|\b(?:send|draft|compose|write|shoot)\s+(?:[a-z']+\s+)?an?\s+"
    r"(?:[a-z]+\s+)?(?:reply|response)\b")

# A literal address ends a clause too: "the address is x@y.ca I want you to
# send…" arrives without a full stop. So does a new line: "i like it" and
# "send an email to stella…" on two lines are two sentences.
_CLAUSE_BREAK_RE = re.compile(
    r"[.!?;:]+(?=\s|$)|,|\n|\s[-–—]+\s|\S+@\S+\.[a-z]{2,}")
# Greetings, acknowledgements and the fillers that come before a verb:
# "sounds good send…", "can you pls check…", "blue go check your email".
_PREAMBLE_RE = re.compile(
    r"^(?:(?:" + _ROBOT_NAMES
    + r"|ok(?:ay)?|yes|yeah|yep|sure|please|pls|plz|now|so|and|then"
    r"|hey|hi|also|great|good|cool|alright|right|well|oh|no|just|immediately"
    r"|thanks|thank\s+you|perfect|sounds\s+good|awesome|nice|maybe|actually"
    r"|quickly|kindly|go(?!\s+(?:ahead|on)\b))\b\s*)+")
_REQUEST_FRAME_RE = re.compile(
    r"^(?:(?:can|could|would|will)\s+(?:you|u)"
    r"|do\s+you\s+think(?=\s+(?:you|u)\b)"
    r"|i\s+(?:was\s+)?wonder(?:ing)?\s+if\s+(?:you|u)\s+(?:could|can|would|might)"
    r"|would\s+it\s+be\s+possible\s+(?:for\s+(?:you|u)\s+)?to"
    r"|is\s+it\s+possible\s+for\s+(?:you|u)\s+to"
    r"|i(?:\s+(?:want|need|wanted|would\s+like)|'?d\s+like)(?:\s+you)?\s+to"
    r"|you\s+(?:can|could|should|need\s+to|have\s+to|must|just)"
    r"|go\s+ahead(?:\s+and)?|let\s+me|let'?s|help\s+me|please)\b\s*")
# "would you mind sending…" asks with the -ing form.
_MIND_FRAME_RE = re.compile(r"\b(?:would|do)\s+(?:you|u)\s+mind\s+$")
# First words that make a clause a statement rather than an instruction.
_NOT_AN_IMPERATIVE = frozenset("""
i i'm im i'll i've i'd you you're you've he she it it's its they we we're
that this these those there here the a an my your his her our their what
who which when where why how if because since someone everyone nobody
people students agent agents
""".split())
# A modal makes a clause a description, not an instruction: "so basically
# the agent will check email and reply…", "imagine an agent that could check
# your email and reply…" (S4 review). Not after "you" ("see if you can find
# the email from stella and reply to it"), and not in a clause that opens
# with an email verb ("check if stella will be there and email her").
_MODAL_RE = re.compile(
    r"(?<!\byou )\b(?:will|would|could|can|should|might|may)\b"
    r"|\b[a-z]+'(?:ll|d)\b")
_EMAIL_VERBS = frozenset(_READ_VERBS + _SEND_VERBS + _REPLY_VERBS)


def _peel_request(clause: str) -> str:
    """The clause with its greeting, politeness and request frame removed."""
    text = clause.strip()
    while True:
        peeled = _REQUEST_FRAME_RE.sub("", _PREAMBLE_RE.sub("", text), count=1)
        peeled = peeled.strip()
        if peeled == text:
            return text
        text = peeled


def _opens_with_imperative(clause: str) -> bool:
    text = _peel_request(clause)
    words = re.findall(r"[a-z']+", text)
    if not words or words[0] in _NOT_AN_IMPERATIVE:
        return False
    return words[0] in _EMAIL_VERBS or not _MODAL_RE.search(text)


@lru_cache(maxsize=32)
def _verbs_re(verbs: tuple) -> "re.Pattern":
    return re.compile(r"\b(?:" + "|".join(re.escape(v) for v in verbs) + r")\b")


@lru_cache(maxsize=32)
def _gerunds_re(verbs: tuple) -> Optional["re.Pattern"]:
    forms = [(v[:-1] if v.endswith("e") and not v.endswith("ee") else v) + "ing"
             for v in verbs if " " not in v]
    return re.compile(r"\b(?:" + "|".join(forms) + r")\b") if forms else None


def asks_blue_to(msg_lower: str, verbs, after_now: bool = False) -> bool:
    """True if one of `verbs` is asked of Blue.

    `verbs` is a tuple of base forms (whole words) or a compiled pattern.
    `after_now` also takes a verb that follows a spoken "now" — for the
    follow-up asks only.
    """
    text = (msg_lower or "").replace("’", "'")
    if isinstance(verbs, re.Pattern):
        pattern, gerunds = verbs, None
    else:
        pattern, gerunds = _verbs_re(tuple(verbs)), _gerunds_re(tuple(verbs))
    for clause in _CLAUSE_BREAK_RE.split(text):
        for m in pattern.finditer(clause):
            before = _peel_request(clause[:m.start()])
            if not before:
                return True
            # "…you're hallucinating now do it immediately" — a spoken
            # run-on whose "now" starts the instruction. "my students now
            # check their email on their phones" is a statement.
            if after_now and re.search(r"\bnow$", before):
                return True
            joined = re.search(r"\band(?:\s+then)?$", before)
            if joined and _opens_with_imperative(before[:joined.start()]):
                return True
        for m in (gerunds.finditer(clause) if gerunds else ()):
            mind = _MIND_FRAME_RE.search(clause[:m.start()])
            if mind and not _peel_request(clause[:mind.start()]):
                return True
    return False


# Sending mail, asked of Blue. The hallucinated-action recovery turns a
# reply that SAYS mail went into a real send (bluetools._user_requested_action),
# and it asked only whether "email", "send" or "message" appeared anywhere: the
# remark that no longer reached send_gmail here ("i'm thinking of having my
# students build an agent that reads the news and emails them a digest"),
# answered "…reading the headlines and sending the digest every morning…",
# had send_gmail forced with "get the recipient from the recent conversation",
# and the call ran (S4 final review, stubbed model). So did "It summarizes
# news and sends the newsfeed by email to me" (live 10047).
# "tell" counts as it did, but not "tell me": "tell me about the email you
# sent stella" asks for an account, not a send. Writing, and a follow-up
# ("…you're hallucinating now do it", log 367; "…there is no attachment.
# Try it again.", 4706), is mail only when mail is named: "write your
# autobiography" and "draft the proposal" send nothing.
_SEND_MAIL_ASKS = ("send", "resend", "forward", "email", "mail", "message",
                   "reply", "respond")
_WRITE_MAIL_ASKS = ("write", "draft", "compose", "shoot")
_TELL_SOMEONE_RE = re.compile(r"\btell\b(?!\s+(?:me|us)\b)")
_WRITE_TO_RE = re.compile(r"\bwrite\s+(?:back\s+)?to\b")


def asks_to_send_mail(msg_lower: str) -> bool:
    """True if this message asks Blue to send, forward or reply to mail."""
    text = (msg_lower or "").replace("e-mail", "email").replace("e mail", "email")
    if (asks_blue_to(text, _SEND_MAIL_ASKS) or asks_blue_to(text, _TELL_SOMEONE_RE)
            or asks_blue_to(text, _WRITE_TO_RE)):
        return True
    return has_any_word(_EMAIL_NOUNS + ['message'], text) and (
        asks_blue_to(text, _WRITE_MAIL_ASKS)
        or asks_blue_to(text, _FOLLOWUP_ASKS, after_now=True))


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
        # "any new email?" asks without a verb; everything else needs one
        # that Blue is asked to do.
        noun_only = any(s in msg_lower for s in
                        ('any new email', 'unread email', 'recent email'))
        if not noun_only and not asks_blue_to(msg_lower, _READ_VERBS):
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

        has_address = bool(_ADDRESS_RE.search(message))
        if _SENT_TO_BLUE_RE.search(msg_lower) and not has_address:
            return None
        # Asking about a send, or telling Blue not to send, is never a send:
        # "Did you send the photo to stella…?", "Don't send anything to … yet".
        if _SEND_NEGATED_RE.search(msg_lower) or _SEND_ASKED_ABOUT_RE.search(msg_lower):
            return None

        send_signals = {
            'strong': [
                'send email to', 'send an email', 'email to', 'compose email',
                'write email to', 'send them an email'
            ],
            'medium': ['send', 'compose', 'draft']
        }
        # "send to" names no medium; it's an email only when one is in view.
        if has_address or has_any_word(_EMAIL_NOUNS, msg_lower):
            send_signals['strong'].append('send to')
        # Only an instruction to Blue: "Stella said she would send the forms
        # to alevant@yorku.ca" names an address and a send, and is neither.
        if has_address and _SEND_IMPERATIVE_RE.search(msg_lower):
            send_signals['strong'].append('send')

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
        # Whole words: "read" is inside "al-READ-y", which was quietly
        # subtracting 0.3 from send confidence on unrelated sentences.
        if has_any_word(['check', 'read', 'reading', 'show my'], msg_lower):
            confidence = max(0, confidence - 0.3)
            reasons.append("reduced: read indicators")

        if confidence <= 0:
            return None
        if not (asks_blue_to(msg_lower, _SEND_VERBS)
                or asks_blue_to(msg_lower, _FOLLOWUP_ASKS, after_now=True)):
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
        has_email_noun = has_any_word(_EMAIL_NOUNS + ['message', 'messages'],
                                      msg_lower)

        if any(signal in msg_lower for signal in reply_signals['strong']):
            if has_email_noun:
                confidence = 0.95
                reasons.append("explicit reply keywords")
            elif (context.get('has_email_in_history')
                  and _REPLY_IMPERATIVE_RE.search(msg_lower)):
                confidence = 0.75
                reasons.append("reply imperative + email context")
        elif any(verb in msg_lower for verb in reply_signals['medium']):
            if has_email_noun:
                confidence = 0.80
                reasons.append("reply verb + email context")

        if confidence <= 0:
            return None
        if not asks_blue_to(msg_lower, _REPLY_ASK_RE):
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
