"""Document operations intent detector."""

from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


class DocumentsDetector(BaseDetector):
    """Detects document search and creation intents."""

    def detect(self, message: str, msg_lower: str, context: Dict) -> List[ToolIntent]:
        intents = []

        search_intent = self._detect_search_intent(msg_lower, context)
        if search_intent:
            intents.append(search_intent)

        create_intent = self._detect_create_intent(msg_lower)
        if create_intent:
            intents.append(create_intent)

        return intents

    def _detect_search_intent(self, msg_lower: str, context: Dict) -> Optional[ToolIntent]:
        strong_signals = [
            'search my documents', 'search documents for', 'find in my documents',
            'what do my documents say', 'according to my documents', 'search my files',
            'in my files', 'in my documents', 'look up in my',
        ]

        # List/count queries - user wants to see what documents exist
        list_signals = [
            'what documents are', 'what documents do', 'what files are',
            'what files do', 'list documents', 'list files', 'list my documents',
            'list my files', 'show me my documents', 'show me my files',
            'show documents', 'show files', 'show my documents', 'show my files',
            'how many documents', 'how many files', 'count documents', 'count files',
            'documents in', 'files in', 'which documents', 'which files'
        ]

        # Re-read / closer-look signals: user is asking Blue to (re-)inspect a
        # specific document. These need to route to search_documents because
        # otherwise the model just claims to have "re-read" the file without
        # actually fetching anything.
        # Phrase signals fire on their own (no extra context needed).
        re_read_signals = [
            'second look at', 'another look at', 'fresh look at',
            'closer look at', 'have a look at',
            're-read', 'reread', 'read again', 'read it again',
            'look back at', 'go back to the',
            'pull up the', 'bring up the',
        ]
        # Verb signals that need a doc-noun nearby in the same message.
        re_read_verbs = (
            'review', 'go through', 'look through', 'look at',
            'check', 'open', 'go back to', 'pull up', 'bring up',
        )

        doc_nouns = ['document', 'documents', 'file', 'files', 'pdf', 'contract',
                     'syllabus', 'report', 'assignment', 'essay', 'paper', 'notes',
                     'docx', 'doc', '.pdf', '.docx', '.txt', '.md',
                     'script', 'cv', 'cover letter', 'dossier', 'invitation',
                     'talk', 'lecture', 'manuscript', 'draft']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.95
            reasons.append("explicit document search")
        elif any(s in msg_lower for s in list_signals):
            # User wants to list/count documents
            confidence = 0.90
            reasons.append("document list/count query")
        elif any(s in msg_lower for s in re_read_signals):
            # User wants Blue to look at a specific document — this almost
            # always implies search_documents. Boost slightly if a doc noun
            # is also present (very strong signal).
            if any(n in msg_lower for n in doc_nouns):
                confidence = 0.92
                reasons.append("re-read/look-at + document noun")
            else:
                confidence = 0.85
                reasons.append("re-read / fresh-look phrasing")
        elif any(v in msg_lower for v in re_read_verbs) and any(n in msg_lower for n in doc_nouns):
            # Looser verb+noun match catches "review the job talk document",
            # "go through the talk script", "open the docx file" — anything
            # where words appear between the verb and the doc-noun.
            confidence = 0.88
            reasons.append("re-read verb + doc noun (proximity)")
        elif any(v in msg_lower for v in ['search', 'find', 'look for', 'look up']):
            if any(n in msg_lower for n in doc_nouns):
                if 'my' in msg_lower or 'our' in msg_lower:
                    confidence = 0.85
                    reasons.append("search + possessive + document")
                else:
                    confidence = 0.70
                    reasons.append("search + document")
            elif 'my' in msg_lower:
                confidence = 0.75
                reasons.append("search + possessive (implicit docs)")

        # Questions about documents (what/how questions)
        if ('what' in msg_lower or 'how' in msg_lower) and any(n in msg_lower for n in doc_nouns):
            # If already detected via list_signals, don't double-apply
            if confidence < 0.80:
                confidence = max(confidence, 0.75)
                reasons.append("question about document")

        # Reduce for web search
        if any(w in msg_lower for w in ['google', 'search online', 'search the web']):
            confidence = max(0, confidence - 0.4)

        if confidence <= 0:
            return None

        return ToolIntent(
            tool_name='search_documents',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params={'query': msg_lower[:100]}
        )

    def _detect_create_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        strong_signals = [
            'create a document', 'create a file', 'make a document',
            'write a document', 'save as a file', 'create a list', 'make me a list'
        ]
        create_nouns = ['document', 'file', 'list', 'note', 'notes', 'recipe']

        confidence = 0.0
        reasons = []

        if any(s in msg_lower for s in strong_signals):
            confidence = 0.90
            reasons.append("explicit creation keywords")
        elif any(v in msg_lower for v in ['create', 'make', 'write', 'save']):
            if any(n in msg_lower for n in create_nouns):
                confidence = 0.80
                reasons.append("create verb + document noun")

        if confidence <= 0:
            return None

        params = {}
        # Extract title/content if present (simplified)
        if '"' in msg_lower or "'" in msg_lower:
            params['has_content'] = True

        return ToolIntent(
            tool_name='create_document',
            confidence=confidence,
            priority=ToolPriority.MEDIUM,
            reason=' | '.join(reasons),
            extracted_params=params
        )
