"""
Detector for durable household-fact writes (remember_fact).

The distinction this detector exists to draw is STORE vs RECALL. The old
free-text extractor in blue_memory_improved.py matched a bare `remember`
anywhere in the message, so "tell me what you remember about our family" —
a question — was filed as an instruction, storing the fragment "about our
family" as a user note (live 2026-08-19 07:47). Meanwhile "I want you to
update your memory so that you can know for sure in the future Athena's
correct age" matched nothing at all, because it says neither "remember that"
nor "don't forget".

So: recall frames are checked FIRST and bail out, and a store intent needs an
explicit storage instruction rather than the mere presence of the word.
"""

from typing import Dict, List, Optional

from ..constants import ToolPriority
from ..models import ToolIntent
from ..utils import has_any_word, is_recall_question
from .base import BaseDetector


class MemoryDetector(BaseDetector):
    """Detects an instruction to durably record a household fact."""

    # Unambiguous instructions to fix the durable record. These are the
    # phrasings that used to produce "I have updated my records" with no
    # write behind it.
    STRONG_STORE = [
        'update your memory', 'update your records', 'update your record',
        'update that in your memory', 'correct your records',
        'correct your record', 'fix your records', 'fix your record',
        'update what you know', 'change what you know',
        'commit that to memory', 'commit this to memory',
        'save that to memory', 'store that in your memory',
        'put that in your memory', 'add that to your memory',
    ]

    # Ordinary "please retain this" phrasings.
    STORE_PHRASES = [
        'remember that', 'remember this', 'remember for next time',
        'remember going forward', 'make a note', 'note that',
        'keep in mind', 'write that down', 'write this down',
        'log that', 'save that', 'store that',
        'lock that in', 'lock this in',
        'keep track of', 'hold on to that',
    ]

    # "don't forget" is a STORE instruction despite the negation, so it is
    # matched explicitly rather than being caught by the negation guard.
    DONT_FORGET = ['do not forget', "don't forget", 'dont forget']

    # Negations that cancel a store instruction outright.
    NEGATIONS = [
        'do not remember', "don't remember", 'dont remember',
        'do not save', "don't save", 'do not store', "don't store",
        'stop remembering', 'forget that', 'forget about',
        'no need to remember', 'you do not have to remember',
    ]

    def detect(self, message: str, msg_lower: str,
               context: Dict) -> List[ToolIntent]:
        intent = self._detect_store_intent(msg_lower)
        return [intent] if intent else []

    def _detect_store_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        # A question about what Blue knows is never a write, no matter which
        # storage verbs it happens to contain.
        if is_recall_question(msg_lower):
            return None

        has_dont_forget = any(p in msg_lower for p in self.DONT_FORGET)

        # Negation before imperative — but "don't forget" is itself the
        # imperative, so it wins over the generic guard.
        if not has_dont_forget and any(n in msg_lower for n in self.NEGATIONS):
            return None

        if any(p in msg_lower for p in self.STRONG_STORE):
            return ToolIntent(
                tool_name='remember_fact',
                confidence=0.93,
                priority=ToolPriority.HIGH,
                reason='explicit instruction to update the durable record',
                extracted_params={},
            )

        if has_dont_forget or any(p in msg_lower for p in self.STORE_PHRASES):
            return ToolIntent(
                tool_name='remember_fact',
                confidence=0.82,
                priority=ToolPriority.MEDIUM,
                reason='user asked for something to be retained',
                extracted_params={},
            )

        # "my memory" / "your memory" alone is a conversation ABOUT memory,
        # not an instruction, so nothing fires here on purpose.
        return None
