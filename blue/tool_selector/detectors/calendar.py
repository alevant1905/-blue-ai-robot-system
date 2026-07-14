"""Calendar and events intent detector."""

from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


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

        return None
