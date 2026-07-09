"""Web search and browsing intent detector."""

import re
from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class WebDetector(BaseDetector):
    """Detects web search and browsing intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        search_intent = self._detect_search_intent(msg_lower)
        if search_intent:
            intents.append(search_intent)

        browse_intent = self._detect_browse_intent(msg_lower)
        if browse_intent:
            intents.append(browse_intent)

        return intents

    def _detect_search_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        strong_signals = [
            'search the web', 'search online', 'google', 'search google',
            'look up online', 'search the internet', 'find on the web'
        ]
        medium_signals = ['search for', 'look up', 'find out about']
        temporal = ['latest', 'recent', 'current', 'today', 'this week']
        news_topics = ['news', 'headlines', 'price', 'score', 'weather',
                       'results', 'standings', 'stock', 'market']
        # Named news sources strongly imply web search
        news_sources = ['guardian', 'bbc', 'cnn', 'reuters', 'nyt',
                        'new york times', 'washington post', 'times',
                        'al jazeera', 'associated press', 'sky news']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.95
            reasons.append("explicit web search")
        elif any(s in msg_lower for s in medium_signals):
            confidence = 0.75
            reasons.append("generic search")
        elif any(t in msg_lower for t in temporal):
            if any(topic in msg_lower for topic in news_topics):
                confidence = 0.85
                reasons.append("temporal + news/price")
        # "headlines from the guardian" — news topic + named source
        if any(topic in msg_lower for topic in news_topics) and \
           any(src in msg_lower for src in news_sources):
            confidence = max(confidence, 0.90)
            if "news source + topic" not in reasons:
                reasons.append("news source + topic")

        # Reduce for document search
        doc_signals = ['my document', 'my file', 'my contract', 'my pdf']
        if any(s in msg_lower for s in doc_signals):
            confidence = max(0, confidence - 0.6)

        if confidence <= 0:
            return None

        # Extract the actual search topic, stripping conversational filler
        query = self._extract_search_query(msg_lower)

        return ToolIntent(
            tool_name='web_search',
            confidence=confidence,
            priority=ToolPriority.LOW,
            reason=' | '.join(reasons),
            extracted_params={'query': query}
        )

    @staticmethod
    def _extract_search_query(msg: str) -> str:
        """Strip conversational preamble to extract the actual search topic.

        The regex capture must be scrubbed too: 'search the web and tell me
        who is left in the fifa world cup' captures 'and tell me who is
        left...' — sent verbatim to the engine it returns junk (2026-07-09)."""
        filler = [
            'try again ', 'again ', 'once more ',
            'and ', 'then ', 'also ', 'now ', 'just ', 'go ',
            'i want you to ', 'can you ', 'please ', 'could you ',
            'do a ', 'run a ', 'search for ', 'search ', 'google ',
            'look up ', 'find out about ', 'find out ', 'find ', 'summarize ',
            'give me ', 'show me ', 'tell me ', 'tell us ', 'get me ',
            'let me know ', 'check ',
            'what are ', "what's ", 'what is ',
        ]

        def strip_filler(q: str) -> str:
            changed = True
            while changed:
                changed = False
                for f in filler:
                    if q.startswith(f):
                        q = q[len(f):]
                        changed = True
            # Trailing errand: "..., and tell me about it"
            q = re.sub(r'[,.;]?\s*(?:and|then)\s+(?:tell|let)\s+(?:me|us)\b.*$', '', q)
            return q.strip().rstrip('.!?').strip()

        # Try explicit "search for X" / "google X" / "look up X" patterns
        patterns = [
            r'(?:search|google|look up|find)\s+(?:the web |the internet |the net |online )?(?:for |about |on )?(.+)',
            r'(?:i want you to |can you |please )?(?:do a |run a )?(?:google |web |internet )?search\s+(?:for |about |on )?(.+)',
        ]
        for pat in patterns:
            m = re.search(pat, msg)
            if m:
                q = strip_filler(m.group(1).strip().rstrip('.!?'))
                if q:
                    return q
        # Fallback: strip common prefixes from the whole message
        return strip_filler(msg) or msg

    def _detect_browse_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        browse_verbs = ['browse', 'open', 'visit', 'go to', 'navigate to', 'load', 'fetch']

        has_email = bool(re.search(r'\b[\w.-]+@[\w.-]+\.\w+\b', msg_lower))
        has_url = bool(re.search(r'https?://|www\.', msg_lower)) or \
                  (bool(re.search(r'\.(com|org|net)\b', msg_lower)) and not has_email)
        has_verb = any(v in msg_lower for v in browse_verbs)

        confidence = 0.0
        reasons = []

        if has_url:
            if has_verb:
                confidence = 0.95
                reasons.append("URL + browse verb")
            else:
                confidence = 0.85
                reasons.append("URL detected")
        elif has_verb and 'website' in msg_lower:
            confidence = 0.75
            reasons.append("browse + website")

        if confidence <= 0:
            return None

        url_match = re.search(r'https?://\S+|www\.\S+|\b\w+\.(com|org|net)\b', msg_lower)
        url = url_match.group(0) if url_match else None

        return ToolIntent(
            tool_name='browse_website',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params={'url': url, 'extract': 'text'}
        )
