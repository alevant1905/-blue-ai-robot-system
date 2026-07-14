"""Document operations intent detector."""

import os
import re
import json
from collections import Counter
from typing import Dict, List, Optional
from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority


# Words too generic to identify a specific library document. Used to filter
# both the library's title tokens and the query tokens before matching.
_GENERIC_TERMS = set("""
the a an and or of to in on for with about into from your my our its their this that these those
what how who why when where which whose is are was were be been do does did can could would should will
document documents file files pdf docx doc txt md paper papers book books note notes text texts page pages
theory learning research design technology machine human humans power politics future world
talk talks script scripts lecture lectures report reports essay essays draft drafts manuscript
chapter chapters syllabus release journal version copy summary final intro introduction
tell read show find search looking look give get open review according say says said argue argues
me you it please new old here there thing things stuff topic content help know need want
""".split())


# Academic course/reading phrasings. This user is a professor; questions like
# "what are the readings for tomorrow", "what's due this week", "what do I read
# for class" are answered by the syllabus/course documents — but they name no
# title, so they used to match no tool and Blue invented excuses ("path issue")
# or answers. Word-boundary anchored to avoid false hits ("spreading", "ready").
_COURSE_RE = re.compile(
    r"\breadings\b"
    r"|\b(?:assigned|required|course|class|weekly)\s+readings?\b"
    r"|\breading\s+(?:for|list|report|assignment|this|next|tonight|tomorrow|today|due)\b"
    r"|\b(?:to|should\s+i|do\s+i|have\s+to|need\s+to|gotta)\s+read\b"
    r"|\bhomework\b|\bassignments?\b|\bcoursework\b|\bsyllabus\b"
    r"|\b(?:lecture|seminar)\s+(?:notes|reading|readings|material|materials)\b"
    r"|\bcourse\s+(?:material|materials|outline|schedule|reading|readings)\b"
    r"|\bdue\b(?!\s+to\b)",   # "what is due this week", "due tomorrow" — but not "due to"
    re.I,
)


class DocumentsDetector(BaseDetector):
    """Detects document search and creation intents.

    Beyond generic phrasing ("my documents"), this detector is LIBRARY-AWARE:
    it loads the actual document titles/authors/folders from document_index.json
    and triggers a search when the query names one of them. Without this, a
    query like "what does Toscano argue" or "summarize the Three Body Problem"
    matched no tool, so the model answered with no source and hallucinated.
    """

    # Cached library signature, refreshed when document_index.json changes.
    _lib_tokens_by_doc = None   # list[set[str]] — distinctive tokens per document
    _lib_rare_tokens = None     # set[str] — tokens unique to one doc (len>=6)
    _lib_phrases = None         # set[str] — folder names (multi-word ok)
    _lib_mtime = -1.0

    @classmethod
    def _index_path(cls) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.normpath(os.path.join(here, "..", "..", ".."))
        p = os.path.join(root, "document_index.json")
        return p if os.path.exists(p) else "document_index.json"

    @classmethod
    def _refresh_library(cls) -> None:
        path = cls._index_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
        if cls._lib_tokens_by_doc is not None and mtime == cls._lib_mtime:
            return
        tokens_by_doc = []
        phrases = set()
        try:
            with open(path, encoding="utf-8") as f:
                idx = json.load(f)
            name_tok_docs = []   # per-doc set of proper-noun-ish tokens (for rare set)
            for d in idx.get("documents", []):
                fn = d.get("filename", "") or ""
                folder = d.get("folder", "") or ""
                stem = os.path.splitext(fn)[0]
                # Keep ORIGINAL case to tell proper nouns from sentence words.
                raw_words = [w for w in re.split(r"[\s_\-.]+", stem) if w]
                toks = {w.lower() for w in raw_words
                        if len(w) >= 4 and w.lower() not in _GENERIC_TERMS and not w.isdigit()}
                # Proper-noun-ish: starts uppercase (author surname / distinctive
                # title word). Excludes lowercase sentence words like "happened",
                # "future", "already" that live inside descriptive filenames and
                # would otherwise trigger on any sentence using that common word.
                name_toks = {w.lower() for w in raw_words
                             if w[:1].isupper() and len(w) >= 5
                             and w.lower() not in _GENERIC_TERMS and not w.isdigit()}
                if folder:
                    raw_f = [w for w in re.split(r"[\s_\-./\\]+", folder) if w]
                    for w in raw_f:
                        if len(w) >= 4 and w.lower() not in _GENERIC_TERMS and not w.isdigit():
                            toks.add(w.lower())
                            if w[:1].isupper() or any(ch.isdigit() for ch in w):
                                name_toks.add(w.lower())
                    fphrase = " ".join(w.lower() for w in raw_f)
                    if len(fphrase) >= 4:
                        phrases.add(fphrase)
                if toks:
                    tokens_by_doc.append(toks)
                name_tok_docs.append(name_toks)
            # Distinctive single-trigger tokens: proper-noun-ish, long, and not
            # spread across many documents — author surnames and unusual title
            # words (Noble, Ilyenkov, Toscano, Engestrom…). Five characters is
            # enough here because rarity still prevents common-word triggers.
            # <=2 docs (not ==1) so an
            # author appearing in two of their own works still counts.
            counts = Counter(t for s in name_tok_docs for t in s)
            rare = {t for t, c in counts.items() if c <= 2}
        except Exception:
            tokens_by_doc, rare, phrases = [], set(), set()
        cls._lib_tokens_by_doc = tokens_by_doc
        cls._lib_rare_tokens = rare
        cls._lib_phrases = phrases
        cls._lib_mtime = mtime

    @classmethod
    def _library_match(cls, msg_lower: str) -> Optional[str]:
        """Reason string if the query names something in the library, else None."""
        cls._refresh_library()
        if not cls._lib_tokens_by_doc:
            return None
        # A named folder ("my Alex Levant folder", "the AI folder").
        for ph in cls._lib_phrases:
            if ph and ph in msg_lower:
                return f"names library folder '{ph}'"
        qwords = {w for w in re.split(r"[^a-z0-9]+", msg_lower)
                  if len(w) >= 4 and w not in _GENERIC_TERMS}
        # Voice transcription commonly drops possessive apostrophes ("Noble's"
        # becomes "nobles"). Add the singular form only when it names a token
        # that really occurs in this library, avoiding broad stemming.
        library_tokens = set().union(*cls._lib_tokens_by_doc)
        qwords.update(
            w[:-1] for w in tuple(qwords)
            if len(w) >= 6 and w.endswith('s') and w[:-1] in library_tokens
        )
        if not qwords:
            return None
        # A distinctive single term (author surname / unusual title word).
        rare_hit = qwords & cls._lib_rare_tokens
        if rare_hit:
            return f"names library term '{sorted(rare_hit)[0]}'"
        # Two-plus distinctive tokens shared with a single document's title.
        for toks in cls._lib_tokens_by_doc:
            overlap = qwords & toks
            if len(overlap) >= 2:
                return "names a library document (" + ", ".join(sorted(overlap)[:3]) + ")"
        return None

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
            # Corrections such as "it's in your library folder" still need the
            # document tool; the conversation layer resolves what "it" names.
            "it's in your library", 'its in your library',
            "it's in my library", 'its in my library',
        ]

        # List/count queries - user wants to see what documents exist
        list_signals = [
            'what documents are', 'what documents do', 'what files are',
            'what files do', 'list documents', 'list files', 'list my documents',
            'list my files', 'show me my documents', 'show me my files',
            'show documents', 'show files', 'show my documents', 'show my files',
            'how many documents', 'how many files', 'count documents', 'count files',
            'documents in', 'files in', 'which documents', 'which files',
            # Explicit inventory phrasings. Bare "in your library" is not an
            # inventory request: "it's in your library" is a correction about
            # a particular file and is handled by the strong signals above.
            "what's in my library", "what's in your library",
            'what is in my library', 'what is in your library',
            'show my library', 'show your library', 'list my library',
            'list your library',
            'what do you have', 'what have you read',
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
                     'docx', 'doc', '.pdf', '.docx', '.txt', '.md', 'library',
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

        # Academic course/reading queries → the syllabus & course docs.
        if confidence < 0.8 and _COURSE_RE.search(msg_lower):
            confidence = max(confidence, 0.8)
            reasons.append("course/reading query")

        # LIBRARY-AWARE: the query names an actual document, author, or folder
        # in the library (e.g. "summarize the Three Body Problem", "what does
        # Toscano argue", "the AI folder"). This is the main fix for Blue
        # hallucinating instead of retrieving — those phrasings used to match
        # no tool at all.
        if confidence < 0.90:
            lib_reason = self._library_match(msg_lower)
            if lib_reason:
                confidence = max(confidence, 0.9)
                reasons.append(lib_reason)

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
