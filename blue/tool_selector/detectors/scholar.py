"""Scholarly research intent detector (academic journals / Laurier library)."""

import re
from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class ScholarDetector(BaseDetector):
    """Detects academic-journal search intents.

    Routes phrasings like "find peer-reviewed articles on X" or "search the
    Laurier library for X" to search_scholar rather than the generic
    web_search (which returns blogs and news) or search_documents (which is
    Alex's PERSONAL document library — "my library" stays with documents).
    """

    # Unambiguously scholarly — fire at high confidence on their own.
    STRONG_SIGNALS = [
        'peer-reviewed', 'peer reviewed', 'journal article', 'journal articles',
        'academic journal', 'academic journals', 'academic article',
        'academic articles', 'scholarly article', 'scholarly articles',
        'scholarly source', 'scholarly sources', 'scholarly literature',
        'academic literature', 'research article', 'research articles',
        'literature review', 'literature search', 'google scholar',
        'laurier library', 'university library', 'library database',
        'library databases', 'search omni', 'on omni', 'in omni',
        'academic paper', 'academic papers', 'research papers',
        'published research', 'academic research on', 'academic sources',
    ]

    # Scholarly-ish nouns that need a search verb nearby.
    MEDIUM_NOUNS = [
        'papers', 'studies', 'journals', 'articles', 'citations',
        'references', 'sources', 'bibliography', 'abstracts',
    ]
    SEARCH_VERBS = ['search', 'find', 'look for', 'look up', 'locate', 'get me', 'pull up']
    ACADEMIC_QUALIFIERS = [
        'academic', 'scholarly', 'scientific', 'empirical', 'published',
        'peer', 'research', 'journal',
    ]

    # A DOI in the message is a paper lookup, not a search.
    DOI_RE = re.compile(r'\b10\.\d{4,9}/[^\s"\']+', re.I)

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        doi_intent = self._detect_doi_lookup(message, msg_lower)
        if doi_intent:
            intents.append(doi_intent)

        search_intent = self._detect_scholar_search(msg_lower)
        if search_intent:
            intents.append(search_intent)

        return intents

    # Verbs that mean "get me the CONTENT", not just the metadata.
    READ_VERBS = ['read', 'summarize', 'summarise', 'analyze', 'analyse',
                  'full text', 'fulltext', 'download', 'what does it say',
                  'what does it argue', 'go through']

    def _detect_doi_lookup(self, message: str, msg_lower: str) -> Optional[ToolIntent]:
        m = self.DOI_RE.search(message)
        if not m:
            return None
        doi = m.group(0).rstrip('.,;)')
        # "read/summarize <DOI>" wants the article's content, not its record.
        if any(v in msg_lower for v in self.READ_VERBS):
            return ToolIntent(
                tool_name='read_paper',
                confidence=0.95,
                priority=ToolPriority.MEDIUM,
                reason='DOI + read/summarize verb',
                extracted_params={'doi': doi}
            )
        return ToolIntent(
            tool_name='get_paper',
            confidence=0.95,
            priority=ToolPriority.MEDIUM,
            reason='DOI in message',
            extracted_params={'doi': doi}
        )

    def _detect_scholar_search(self, msg_lower: str) -> Optional[ToolIntent]:
        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in self.STRONG_SIGNALS):
            confidence = 0.92
            reasons.append("explicit scholarly phrasing")
        elif (any(v in msg_lower for v in self.SEARCH_VERBS)
                and any(n in msg_lower for n in self.MEDIUM_NOUNS)
                and any(q in msg_lower for q in self.ACADEMIC_QUALIFIERS)):
            confidence = 0.85
            reasons.append("search verb + academic qualifier + scholarly noun")
        elif 'studies on' in msg_lower or 'studies about' in msg_lower or \
                'research on' in msg_lower or 'research about' in msg_lower:
            confidence = 0.75
            reasons.append("studies/research on topic")

        # "my library" / "your library" / "in my documents" is the personal
        # RAG document library, not the university's — stand down.
        personal = ['my library', 'your library', 'my document', 'my file',
                    'in my documents', 'in the library folder']
        if any(p in msg_lower for p in personal):
            confidence = max(0, confidence - 0.6)

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='search_scholar',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params={'query': self._extract_topic(msg_lower)}
        )

    @staticmethod
    def _extract_topic(msg: str) -> str:
        """Strip search preamble and scholarly qualifiers to get the topic."""
        patterns = [
            r'(?:search|find|look up|look for|locate|get me|pull up|give me|show me)\s+'
            r'(?:me\s+)?(?:some\s+)?(?:recent\s+)?'
            r'(?:peer[- ]reviewed\s+|academic\s+|scholarly\s+|scientific\s+|published\s+|empirical\s+)*'
            r'(?:journal\s+|research\s+)?'
            r'(?:articles?|papers?|studies|literature|sources?|journals?|research)\s+'
            r'(?:on|about|regarding|around|for)\s+(.+)',
            r'(?:studies|research|literature|articles?|papers?)\s+(?:on|about)\s+(.+)',
            # "search the laurier library / omni for X"
            r'(?:search|check|look\s+in|browse)\s+(?:the\s+)?'
            r'(?:laurier|university|school|wlu)?\s*(?:library|omni|databases?)\s+'
            r'(?:for|about|on)\s+(.+)',
        ]
        for pat in patterns:
            m = re.search(pat, msg)
            if m:
                q = m.group(1).strip().rstrip('.!?')
                # Trim trailing library references: "... in the laurier library"
                q = re.sub(r'\s+(?:in|from|at|using|via|through)\s+(?:the\s+)?'
                           r'(?:laurier|university|school|wlu)?\s*'
                           r'(?:library|omni|databases?)\s*$', '', q).strip()
                if q:
                    return q
        return msg.strip().rstrip('.!?')
