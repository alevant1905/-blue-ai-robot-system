"""Calendar and events intent detector."""

import re
from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority

# "Remind me" is two different requests wearing one phrase. "Remind me TO call
# her" schedules something; "remind me OF what we decided" asks to be told
# again. Treating both as scheduling turns a memory question into a calendar
# write — and because the tool is then forced, the model invents arguments to
# fill it. Asked "can you remind me of those ideas?", Blue created a reminder
# whose description listed four ideas it had made up (2026-07-31).
_RECALL_PHRASING_RE = re.compile(
    r"\bremind me\s+(?:of|about)\b"
    r"|\bremind me\s+(?:what|who|which|whose|where|why|how)\b"
    r"|\bremind me,?\s+(?:did|do|does|was|were|is|are|had|have)\b",
    re.I,
)

# A concrete future time turns recall-shaped phrasing back into a real
# scheduling request: "remind me about the dentist tomorrow at 3".
_FUTURE_TIME_RE = re.compile(
    r"\bin \d+\s*(?:minute|min|hour|day|week)"
    r"|\bat \d{1,2}(?::\d{2})?\s*(?:am|pm)?\b"
    r"|\b\d{1,2}\s*(?:am|pm)\b"
    r"|\btomorrow\b|\btonight\b|\blater\b"
    r"|\bthis (?:morning|afternoon|evening)\b"
    r"|\bnext (?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\bon (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)

# Past-tense framing means the thing already exists and is being asked about,
# not planned: "remind me what those ideas WERE".
_PAST_FRAMING_RE = re.compile(
    r"\b(?:were|was|had|used to|we discussed|you said|you had|you came up with"
    r"|talked about|last time|earlier|back then)\b",
    re.I,
)


# Saying "no need to set a reminder" must not set a reminder. Negation ahead of
# an imperative is a recurring failure in this codebase — the keyword matches
# and the "don't" in front of it is discarded.
_REMINDER_DECLINED_RE = re.compile(
    r"\b(?:no need|don'?t|do not|dont|no|not)\b[^.!?]{0,24}"
    r"\b(?:set|make|create|add|need)\b[^.!?]{0,16}\breminder\b"
    r"|\bno reminder\b"
    r"|\bwithout (?:a |any )?reminder\b",
    re.I,
)


# "When is my meeting with X" is a schedule lookup, but the strong-signal list
# below only carried the possessive forms ("when is my", "when's the"), so
# "when is THE meeting with mark Humphries" and "when is OUR meeting" matched
# nothing — and while the library matcher was still claiming his name, they
# became document searches. "What time is my class" went to get_local_time,
# which answers with the clock instead of the timetable.
#
# The event noun is required, so "when is the sun setting" is unaffected, and
# the "is/are/was" must sit close behind the question word, which keeps
# "when in class I will ask you to introduce yourself" out.
_WHEN_IS_EVENT_RE = re.compile(
    r"\b(?:when|what time)\b[^.?!]{0,12}\b(?:is|are|was|will)\b[^.?!]{0,24}"
    r"\b(?:meeting|meetings|appointment|appointments|call|class|classes|lecture|"
    r"seminar|lunch|dinner|coffee|event|events|reminder|reminders|party|"
    r"practice|rehearsal|recital|game|flight|train|deadline)\b",
    re.I,
)


def is_schedule_time_question(msg_lower: str) -> bool:
    """True for "when is my meeting with X" / "what time is the class"."""
    return bool(_WHEN_IS_EVENT_RE.search(msg_lower or ""))


def is_reminder_declined(msg_lower: str) -> bool:
    """True when the user explicitly said NOT to set a reminder.

    Shared by every detector that can produce create_reminder. Keeping a
    private copy in each is how "can you remind me of those ideas?" survived a
    fix to only one of them."""
    return bool(_REMINDER_DECLINED_RE.search(msg_lower or ""))


def is_reminder_recall_request(msg_lower: str) -> bool:
    """True when "remind me ..." asks to be TOLD something, not reminded later.

    Recall phrasing wins unless the message also names a concrete future time
    and is not framed in the past tense — so "remind me about the dentist
    tomorrow at 3" still schedules, while "remind me what we agreed" does not.
    """
    text = msg_lower or ""
    if not _RECALL_PHRASING_RE.search(text):
        return False
    if _PAST_FRAMING_RE.search(text):
        return True
    return not _FUTURE_TIME_RE.search(text)


class CalendarDetector(BaseDetector):
    """Detects calendar and event-related intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        # Cancel runs first — phrases like "cancel my dentist reminder"
        # contain the word "reminder" and would otherwise also match the
        # list/create paths. Returning early here avoids that ambiguity.
        cancel = self._detect_cancel(msg_lower)
        if cancel:
            return [cancel]

        reschedule = self._detect_reschedule(msg_lower)
        if reschedule:
            return [reschedule]

        create_event = self._detect_create_event(msg_lower)
        if create_event:
            intents.append(create_event)

        list_events = self._detect_list_events(msg_lower)
        if list_events:
            intents.append(list_events)

        return intents

    def _detect_cancel(self, msg_lower: str) -> Optional[ToolIntent]:
        # Cancellation = a cancel verb appearing before a schedule noun.
        # Substring-only matching ("cancel ... reminder") is too rigid for
        # phrases like "cancel my dentist reminder" or "delete the 5pm
        # reminder", so we check both: a verb position and a noun position,
        # and require verb-before-noun (avoids matching "I have a reminder
        # to cancel my subscription").
        cancel_verbs = (
            'cancel ', 'delete ', 'remove ', 'scratch ', 'drop ',
            'nevermind ', 'never mind ', 'forget ', 'call off',
        )
        schedule_nouns = (
            'reminder', 'appointment', 'meeting', 'event',
        )

        verb_pos = -1
        for v in cancel_verbs:
            i = msg_lower.find(v)
            if i != -1 and (verb_pos == -1 or i < verb_pos):
                verb_pos = i
        if verb_pos == -1:
            return None

        noun_pos = -1
        for n in schedule_nouns:
            i = msg_lower.find(n, verb_pos)
            if i != -1 and (noun_pos == -1 or i < noun_pos):
                noun_pos = i
        if noun_pos == -1 or noun_pos <= verb_pos:
            return None

        # Only fire if the noun is close-ish to the verb (within ~50 chars).
        # Prevents long compound sentences from accidentally triggering.
        if noun_pos - verb_pos > 50:
            return None

        return ToolIntent(
            tool_name='cancel_reminder',
            confidence=0.88,
            priority=ToolPriority.MEDIUM,
            reason='explicit cancellation request',
            extracted_params={},
        )

    def _detect_reschedule(self, msg_lower: str) -> Optional[ToolIntent]:
        # "move my 3pm to 4pm", "reschedule the meeting", "push the dentist to
        # next week", "revise my calendar to end CMDS4740 on August 4", "update
        # my schedule". Needs an edit verb near a schedule/calendar noun.
        # reschedule_reminder now self-resolves the reminder by title_query
        # (like cancel_reminder), so forcing it directly is safe — the model no
        # longer has to look up the numeric id first.
        verbs = (
            'reschedule', 'move my', 'move the', 'move that', 'push back',
            'push the', 'push my', 'postpone', 'bump ', 'shift my',
            'shift the', 'change the time', 'change my', 'change the',
            'rename the', 'revise', 'edit my', 'edit the', 'update my',
            'update the', 'end my ', 'end the ', 'set the end', 'change the end',
        )
        nouns = (
            'reminder', 'appointment', 'meeting', 'event', 'reservation',
            'calendar', 'schedule', 'class', 'course',
        )
        if any(v in msg_lower for v in verbs) and any(n in msg_lower for n in nouns):
            return ToolIntent(
                tool_name='reschedule_reminder',
                confidence=0.85,
                priority=ToolPriority.MEDIUM,
                reason='reschedule/edit request',
                extracted_params={},
            )
        return None

    def _detect_create_event(self, msg_lower: str) -> Optional[ToolIntent]:
        # Past-tense gate — never fire on retrospective statements like
        # "yesterday's meeting" or "I had a call at 3". Without this, the
        # rest of the detector would treat "I had a meeting at 3pm" as a
        # request to create a reminder.
        past_markers = (
            'yesterday', ' ago ', ' ago.', 'last week', 'last month',
            'last monday', 'last tuesday', 'last wednesday',
            'last thursday', 'last friday', 'last saturday', 'last sunday',
            'i had a ', 'we had a ', 'there was a ',
            'how was', "how'd", 'how did',
        )
        if any(p in msg_lower for p in past_markers):
            return None

        # Explicit refusal. "No need to set a reminder, but are you excited to
        # meet my students?" was creating one anyway — the word "reminder" was
        # enough, and the negation in front of it was never read.
        if _REMINDER_DECLINED_RE.search(msg_lower):
            return None

        # "Remind me of/what ..." asks to be told, not to be reminded. Firing
        # create_reminder here forces a write tool onto a memory question.
        if is_reminder_recall_request(msg_lower):
            return None

        # Strong signals — explicit reminder or event creation request.
        # Order doesn't matter; the first match decides confidence.
        strong_signals = (
            # Direct creation verbs (legacy)
            'create event', 'add event', 'schedule event',
            'create appointment', 'schedule meeting',
            'add to calendar', 'create reminder',
            # Natural English: verb + (article) + reminder
            'set a reminder', 'set reminder', 'set me a reminder',
            'make a reminder', 'make me a reminder',
            'add a reminder', 'create a reminder',
            'give me a reminder', 'give a reminder',
            # "Remind me" variants (trailing space avoids "remind men")
            'remind me ',
            # Memory-aid framings
            "don't let me forget", "don't forget that",
            'can you remember', 'could you remember', 'please remember',
            'remember that i have', 'remember that we have',
            'remember that the', 'remember that my',
            'remember to ',
        )
        if any(s in msg_lower for s in strong_signals):
            return ToolIntent(
                tool_name='create_reminder',
                confidence=0.92,
                priority=ToolPriority.MEDIUM,
                reason='explicit reminder request',
                extracted_params={},
            )

        # Medium signal — declarative future-event statements like "I have
        # a meeting with Bob at 4pm". Requires a time indicator AND a
        # declarative pattern AND an event noun, so it doesn't fire on
        # ambiguous prose.
        time_indicators = (
            ' at ', 'tomorrow', 'today', 'tonight', 'this afternoon',
            'this evening', 'this morning',
            'next week', 'next monday', 'next tuesday', 'next wednesday',
            'next thursday', 'next friday', 'next saturday', 'next sunday',
            'on monday', 'on tuesday', 'on wednesday',
            'on thursday', 'on friday', 'on saturday', 'on sunday',
            'in an hour', 'in a few hours', 'in 30 min', 'in 15 min',
        )
        declarative_starts = (
            'i have a ', 'i have an ', 'we have a ', 'we have an ',
            "i've got a ", "we've got a ",
            'the meeting is', 'the call is', 'the appointment is',
        )
        event_nouns = (
            'meeting', 'appointment', 'call with', 'event',
            'lunch with', 'dinner with', 'coffee with',
        )

        has_time = any(t in msg_lower for t in time_indicators)
        if has_time:
            if (any(d in msg_lower for d in declarative_starts)
                    and any(n in msg_lower for n in event_nouns)):
                return ToolIntent(
                    tool_name='create_reminder',
                    confidence=0.78,
                    priority=ToolPriority.MEDIUM,
                    reason='declarative future event',
                    extracted_params={},
                )
            # Legacy fallback: time + schedule/meet/appointment keyword
            if any(v in msg_lower for v in ('schedule', 'meeting', 'appointment')):
                return ToolIntent(
                    tool_name='create_reminder',
                    confidence=0.75,
                    priority=ToolPriority.MEDIUM,
                    reason='time + schedule keyword',
                    extracted_params={},
                )

        return None

    def _detect_list_events(self, msg_lower: str) -> Optional[ToolIntent]:
        # Past-tense gate — "what did I have yesterday" is a retrospective
        # question, not a schedule lookup.
        past_markers = (
            'yesterday', 'last week', 'last month',
            'how was', "how'd", 'how did',
        )
        if any(p in msg_lower for p in past_markers):
            return None

        # Strong explicit phrasings — schedule / calendar / reminders /
        # agenda. Covers the natural ways a user asks "what's coming up?".
        strong_signals = (
            # Legacy explicit
            'show my calendar', 'list events', "what's on my calendar",
            'my schedule', 'show schedule', 'upcoming events',
            # Calendar/agenda variants
            "what's on my agenda", 'my agenda', 'on my agenda',
            "what's on today", "what's on tomorrow",
            "what's on this week", "what's on this weekend",
            # "what do I have …"
            'what do i have today', 'what do i have tomorrow',
            'what do i have this', 'what do i have on',
            'what do i have coming up', 'what i have today',
            # "anything …"
            'anything today', 'anything tomorrow', 'anything scheduled',
            'anything coming up', 'anything on my', 'anything planned',
            # "coming up"
            "what's coming up", 'what is coming up',
            'coming up today', 'coming up tomorrow', 'coming up this',
            # "what's next"
            "what's next", 'what is next', 'whats next',
            # Reminders
            'any reminders', 'my reminders', 'list reminders',
            'list my reminders', 'show reminders', 'show my reminders',
            'what reminders', 'what are my reminders', "what's my reminder",
            'pending reminders', 'upcoming reminders',
            # Plans
            'any plans', 'do i have plans', 'do i have any plans',
            'my plans for', 'plans for today', 'plans for tomorrow',
            # "when is my X" / "what time is my X"
            "when's my", 'when is my', 'what time is my',
            'when do i have', "when's the",
        )

        if any(s in msg_lower for s in strong_signals):
            return ToolIntent(
                tool_name='get_upcoming_reminders',
                confidence=0.90,
                priority=ToolPriority.MEDIUM,
                reason='explicit schedule/calendar query',
                extracted_params={'user_name': 'Alex'},
            )

        # "When is the/our meeting with X", "what time is my class" — asking
        # for the time OF a known event. Ranked above the clock and the
        # library, both of which used to take these.
        if is_schedule_time_question(msg_lower):
            return ToolIntent(
                tool_name='get_upcoming_reminders',
                confidence=0.92,
                priority=ToolPriority.HIGH,
                reason='asks the time of a scheduled event',
                extracted_params={'user_name': 'Alex'},
            )

        return None
