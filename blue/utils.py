"""
Blue Robot Utility Functions
============================
Common utility functions used across the Blue system.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

# ================================================================================
# LOGGING
# ================================================================================

def setup_logger(name: str = "blue", level: str = "INFO") -> logging.Logger:
    """Set up and return a logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


log = setup_logger()


# ================================================================================
# COMPOUND REQUEST PARSING (v8)
# ================================================================================

# ================================================================================
# PASTED TEXT
# ================================================================================

# Text pasted straight into the chat box is evidence, not instruction — but it
# arrives with no attachment marker, so the attachment stripping in
# bluetools._intent_text never saw it. Alex pasted 5756 characters of Blue's own
# notes back into the chat; intent detection ran on all of it, matched a request
# for a self-introduction in the document's closing line ("allows you to present
# yourself as a strategic partner") and lifted a venue out of "students gain
# technical skills in prompt engineering". Blue answered "Hello everyone at
# prompt engineering" (2026-07-31).
PASTED_BLOCK_MIN_CHARS = 700
PASTED_FRAMING_MAX_CHARS = 200

# Markdown-ish line starts: headings, bullets, numbered items, bold labels.
# Prose does not begin lines this way; pasted documents do.
_PASTED_STRUCTURE_RE = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|\*\*)", re.M)


def strip_pasted_block(text: str) -> str:
    """Reduce a pasted document to the user's own words around it.

    Only fires on long, visibly structured text. A long unstructured message is
    someone actually typing at length and passes through untouched. When a paste
    carries no framing words at all the result is empty on purpose: no
    detectable intent is the correct reading of "here, look at this".
    """
    if not text or len(text) < PASTED_BLOCK_MIN_CHARS:
        return text
    first = _PASTED_STRUCTURE_RE.search(text)
    if not first and text.count("\n") < 6:
        return text
    head = text[:first.start()].strip() if first else ""
    # Framing running past a couple of sentences is the document's own preamble,
    # not the user talking. Cut at a word boundary.
    if len(head) > PASTED_FRAMING_MAX_CHARS:
        head = head[:PASTED_FRAMING_MAX_CHARS].rsplit(" ", 1)[0]
    # A trailing paragraph is the user's real question only if it looks like
    # one. Accepting any short last paragraph swallowed a document's closing
    # line, which is what triggered the self-introduction above.
    tail = ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if paragraphs:
        last = paragraphs[-1]
        looks_like_a_question = (
            (last.endswith("?") and len(last) < 200) or len(last) <= 60
        )
        if (looks_like_a_question and not _PASTED_STRUCTURE_RE.search(last)
                and last not in head):
            tail = last
    return " ".join(p for p in (head, tail) if p).strip()


def parse_compound_request(message: str) -> List[Dict[str, Any]]:
    """
    Parse compound requests into individual actions.
    Handle "play jazz and turn on relaxing lights" as two actions.

    Returns list of {action, query, priority} dicts.
    """
    msg_lower = message.lower().strip()
    actions = []

    connectors = [' and ', ' then ', ' also ', ' plus ', ', and ', ' & ']
    has_connector = any(conn in msg_lower for conn in connectors)

    if not has_connector:
        return []

    parts = [msg_lower]
    for conn in connectors:
        new_parts = []
        for part in parts:
            new_parts.extend(part.split(conn))
        parts = new_parts

    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) < 3:
            continue

        action_type = _identify_action_type(part)
        if action_type:
            actions.append({
                'action': action_type,
                'query': part,
                'priority': i,
                'original': part
            })

    return actions if len(actions) > 1 else []


def _identify_action_type(text: str) -> Optional[str]:
    """Identify the action type from a text fragment."""
    text = text.lower()

    if any(w in text for w in ['play', 'put on', 'listen to', 'queue']):
        if any(w in text for w in ['music', 'song', 'jazz', 'rock', 'pop', 'by ']):
            return 'play_music'

    if any(w in text for w in ['light', 'lamp', 'bright', 'dim']):
        if any(w in text for w in ['turn', 'set', 'make', 'switch']):
            return 'control_lights'
        if any(w in text for w in ['mood', 'scene', 'party', 'relax', 'romantic']):
            return 'control_lights'

    if any(w in text for w in ['pause', 'stop', 'skip', 'next', 'volume', 'louder', 'quieter']):
        return 'control_music'

    if 'weather' in text:
        return 'get_weather'

    if 'email' in text or 'inbox' in text:
        if any(w in text for w in ['send', 'write', 'compose']):
            return 'send_gmail'
        if any(w in text for w in ['check', 'read', 'show']):
            return 'read_gmail'
        if any(w in text for w in ['reply', 'respond']):
            return 'reply_gmail'

    if any(w in text for w in ['see', 'look', 'photo', 'camera', 'picture']):
        return 'capture_camera'

    if any(w in text for w in ['timer', 'remind', 'alarm']):
        return 'set_timer'

    return None


# ================================================================================
# FOLLOW-UP CORRECTION DETECTION (v8)
# ================================================================================

def detect_follow_up_correction(message: str, context: Dict) -> Optional[Dict[str, Any]]:
    """
    Detect if user is correcting or refining a previous request.
    Handle "no, the blue one" or "actually make it louder"
    """
    msg_lower = message.lower().strip()

    correction_starters = [
        'no ', 'not ', 'actually ', 'i meant ', 'i mean ', 'sorry ',
        'wait ', 'change ', 'make it ', 'instead ', 'rather ', 'wrong '
    ]

    is_correction = any(msg_lower.startswith(s) for s in correction_starters)

    if len(msg_lower.split()) <= 4:
        short_corrections = ['the other', 'different', 'louder', 'quieter', 'brighter',
                           'dimmer', 'faster', 'slower', 'more', 'less']
        if any(c in msg_lower for c in short_corrections):
            is_correction = True

    if not is_correction:
        return None

    last_tool = context.get('last_tool_used')

    correction = {
        'is_correction': True,
        'original_tool': last_tool,
        'correction_type': 'unknown',
        'new_value': None
    }

    if last_tool == 'control_lights' or any(w in msg_lower for w in ['light', 'bright', 'dim', 'color']):
        correction['correction_type'] = 'lights'
        colors = ['red', 'blue', 'green', 'yellow', 'purple', 'orange', 'white', 'pink', 'warm', 'cool']
        for color in colors:
            if color in msg_lower:
                correction['new_value'] = color
                break
        if 'brighter' in msg_lower:
            correction['new_value'] = 'brighter'
        elif 'dimmer' in msg_lower or 'darker' in msg_lower:
            correction['new_value'] = 'dimmer'

    elif last_tool in ['play_music', 'control_music'] or any(w in msg_lower for w in ['music', 'song', 'volume']):
        correction['correction_type'] = 'music'
        if 'louder' in msg_lower:
            correction['new_value'] = 'volume_up'
        elif 'quieter' in msg_lower or 'softer' in msg_lower:
            correction['new_value'] = 'volume_down'
        elif 'different' in msg_lower or 'other' in msg_lower:
            correction['new_value'] = 'skip'

    return correction


# ================================================================================
# CACHING
# ================================================================================

_response_cache: Dict[str, Tuple[float, str]] = {}
_RESPONSE_CACHE_TTL = 300  # 5 minutes


def smart_cache_key(query: str, tool: str = "") -> str:
    """Generate a smart cache key for query deduplication."""
    normalized = query.lower().strip()
    fillers = ['please', 'can you', 'could you', 'would you', 'hey', 'blue', 'hi', 'hello']
    for filler in fillers:
        normalized = normalized.replace(filler, '')
    normalized = ' '.join(normalized.split())

    key_input = f"{tool}:{normalized}"
    return hashlib.md5(key_input.encode()).hexdigest()[:16]


def get_cached_response(cache_key: str) -> Optional[str]:
    """Get cached response if still valid."""
    if cache_key in _response_cache:
        timestamp, response = _response_cache[cache_key]
        if time.time() - timestamp < _RESPONSE_CACHE_TTL:
            return response
        else:
            del _response_cache[cache_key]
    return None


def cache_response(cache_key: str, response: str):
    """Cache a response."""
    _response_cache[cache_key] = (time.time(), response)
    if len(_response_cache) > 100:
        cutoff = time.time() - _RESPONSE_CACHE_TTL
        keys_to_delete = [k for k, (t, _) in _response_cache.items() if t < cutoff]
        for k in keys_to_delete:
            del _response_cache[k]


# ================================================================================
# QUERY ANALYSIS
# ================================================================================

def estimate_query_complexity(message: str) -> str:
    """
    Estimate query complexity to adjust processing.
    Returns: 'simple', 'medium', 'complex'
    """
    msg_lower = message.lower()
    word_count = len(message.split())

    if word_count <= 5:
        return 'simple'

    compound_signals = [' and ', ' then ', ' also ', ' after ', ' before ']
    if any(s in msg_lower for s in compound_signals):
        return 'complex'

    research_signals = ['explain', 'compare', 'difference between', 'how does', 'why does', 'analysis']
    if any(s in msg_lower for s in research_signals):
        return 'complex'

    if word_count <= 15:
        return 'medium'

    return 'complex'


def extract_entities(message: str) -> Dict[str, List[str]]:
    """Extract named entities from message."""
    entities = {
        'people': [],
        'places': [],
        'times': [],
        'numbers': [],
        'emails': [],
        'urls': []
    }

    entities['emails'] = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', message)
    entities['urls'] = re.findall(r'https?://[^\s]+', message)

    time_patterns = [
        r'\d{1,2}:\d{2}(?:\s*[ap]m)?',
        r'\d{1,2}\s*(?:am|pm)',
        r'(?:noon|midnight|morning|afternoon|evening|night)',
        r'(?:today|tomorrow|yesterday)',
        r'(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)',
    ]
    for pattern in time_patterns:
        matches = re.findall(pattern, message.lower())
        entities['times'].extend(matches)

    entities['numbers'] = re.findall(r'\b\d+(?:\.\d+)?\b', message)

    return entities


def extract_action_from_query(query: str) -> Dict[str, Any]:
    """Extract the intended action and parameters from a user query."""
    query_lower = query.lower().strip()

    action_patterns = {
        'play_music': [r'^play\s+(.+)', r'^put on\s+(.+)', r'^listen to\s+(.+)'],
        'control_lights': [r'^turn (on|off)\s+(.+)?lights?', r'^set lights? to\s+(.+)', r'^(\w+) mode for lights'],
        'web_search': [r'^search (?:for\s+)?(.+)', r'^google\s+(.+)', r'^look up\s+(.+)'],
        'read_gmail': [r'^check (?:my )?email', r'^read (?:my )?email', r'^show (?:my )?inbox'],
        'send_gmail': [r'^send (?:an )?email to\s+(.+)', r'^email\s+(\S+@\S+)'],
        'get_weather': [r'^weather (?:in\s+)?(.+)?', r'^what\'?s the weather'],
        'capture_camera': [r'^what do you see', r'^take a photo', r'^look around'],
    }

    for tool, patterns in action_patterns.items():
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return {
                    'action': tool,
                    'params': match.groups() if match.groups() else None,
                    'confidence': 0.9,
                    'raw_match': match.group(0)
                }

    return {'action': None, 'params': None, 'confidence': 0.0, 'raw_match': None}


# ================================================================================
# STRING UTILITIES
# ================================================================================

def fuzzy_match(query: str, targets: List[str], threshold: float = 0.75) -> Optional[str]:
    """Find the best fuzzy match for a query in a list of targets."""
    if not query or not targets:
        return None

    query_lower = query.lower().strip()

    for target in targets:
        if query_lower == target.lower():
            return target

    for target in targets:
        if query_lower in target.lower() or target.lower() in query_lower:
            return target

    best_match = None
    best_score = 0.0

    for target in targets:
        score = _string_similarity(query_lower, target.lower())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = target

    return best_match


def _string_similarity(s1: str, s2: str) -> float:
    """Calculate string similarity using character bigrams."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    def get_bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1)) if len(s) > 1 else {s}

    b1 = get_bigrams(s1)
    b2 = get_bigrams(s2)

    intersection = len(b1 & b2)
    union = len(b1 | b2)

    return intersection / union if union > 0 else 0.0


def normalize_artist_name(name: str) -> str:
    """Normalize artist name for matching."""
    if not name:
        return ""

    replacements = {
        '&': 'and',
        '+': 'and',
        ' - ': ' ',
        "'s": 's',
        '"': '',
    }

    result = name.lower().strip()
    for old, new in replacements.items():
        result = result.replace(old, new)

    if result.startswith('the '):
        result = result[4:]

    return result


def safe_json_parse(text: str, default: Any = None) -> Any:
    """Safely parse JSON with fallback."""
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to max length with suffix."""
    if not text or len(text) <= max_length:
        return text or ""
    return text[:max_length - len(suffix)] + suffix


def extract_quoted_text(text: str) -> List[str]:
    """Extract all quoted strings from text."""
    patterns = [r'"([^"]+)"', r"'([^']+)'"]
    results = []
    for pattern in patterns:
        results.extend(re.findall(pattern, text))
    return results


def get_time_ago(timestamp: float) -> str:
    """Convert timestamp to human-readable 'time ago' string."""
    diff = time.time() - timestamp

    if diff < 60:
        return "just now"
    elif diff < 3600:
        mins = int(diff / 60)
        return f"{mins} minute{'s' if mins != 1 else ''} ago"
    elif diff < 86400:
        hours = int(diff / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif diff < 604800:
        days = int(diff / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        weeks = int(diff / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"


def clean_response_text(text: str) -> str:
    """Clean up response text for better presentation."""
    if not text:
        return ""

    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    artifacts = ['```json', '```', '{"', '"}']
    for artifact in artifacts:
        if text.startswith(artifact) or text.endswith(artifact):
            text = text.strip(artifact)

    return text.strip()


# ================================================================================
# CONVERSATION STATE
# ================================================================================

class ConversationState:
    """Track conversation state for better context awareness."""

    def __init__(self):
        self.last_tool_used: Optional[str] = None
        self.last_tool_result: Optional[str] = None
        self.last_tool_args: Optional[Dict] = None
        self.pending_confirmation: Optional[str] = None
        self.topic_stack: List[str] = []
        self.user_corrections: List[Dict] = []
        self.successful_patterns: Dict[str, int] = {}
        self.failed_patterns: Dict[str, int] = {}
        self.tool_sequence: List[str] = []
        self.last_query: str = ""
        self.query_count: int = 0
        self.session_start: float = time.time()

    def record_tool_use(self, tool_name: str, success: bool, pattern: str = "", args: Dict = None):
        """Record tool usage for learning."""
        self.last_tool_used = tool_name
        self.last_tool_args = args or {}
        self.tool_sequence.append(tool_name)
        if len(self.tool_sequence) > 20:
            self.tool_sequence.pop(0)

        if pattern:
            if success:
                self.successful_patterns[pattern] = self.successful_patterns.get(pattern, 0) + 1
            else:
                self.failed_patterns[pattern] = self.failed_patterns.get(pattern, 0) + 1

    def push_topic(self, topic: str):
        """Add a topic to the stack."""
        if topic and (not self.topic_stack or self.topic_stack[-1] != topic):
            self.topic_stack.append(topic)
            if len(self.topic_stack) > 10:
                self.topic_stack.pop(0)

    def get_current_topic(self) -> Optional[str]:
        """Get the most recent topic."""
        return self.topic_stack[-1] if self.topic_stack else None

    def record_correction(self, original: str, corrected: str):
        """Record user corrections for learning."""
        self.user_corrections.append({
            'original': original,
            'corrected': corrected,
            'timestamp': time.time()
        })
        if len(self.user_corrections) > 50:
            self.user_corrections.pop(0)

    def record_query(self, query: str):
        """Record a new query."""
        self.last_query = query
        self.query_count += 1

    def get_common_tool_pairs(self) -> List[Tuple[str, str]]:
        """Get commonly used tool pairs."""
        pairs = {}
        for i in range(len(self.tool_sequence) - 1):
            pair = (self.tool_sequence[i], self.tool_sequence[i+1])
            pairs[pair] = pairs.get(pair, 0) + 1

        sorted_pairs = sorted(pairs.items(), key=lambda x: x[1], reverse=True)
        return [pair for pair, count in sorted_pairs[:3] if count > 1]

    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        return {
            'duration_minutes': (time.time() - self.session_start) / 60,
            'query_count': self.query_count,
            'tools_used': len(set(self.tool_sequence)),
            'most_used_tools': self._get_tool_frequency(),
            'corrections_made': len(self.user_corrections)
        }

    def _get_tool_frequency(self) -> Dict[str, int]:
        """Get tool usage frequency."""
        freq = {}
        for tool in self.tool_sequence:
            freq[tool] = freq.get(tool, 0) + 1
        return dict(sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5])

    def suggest_next_action(self) -> Optional[str]:
        """Suggest next action based on patterns."""
        if not self.last_tool_used:
            return None

        pairs = self.get_common_tool_pairs()
        for first, second in pairs:
            if first == self.last_tool_used:
                return f"You often use {second} after {first}. Would you like me to do that?"

        return None


# Global conversation state
_conversation_state = ConversationState()


def get_conversation_state() -> ConversationState:
    """Get the global conversation state."""
    return _conversation_state


def validate_response_quality(response: str, query: str) -> Dict[str, Any]:
    """Validate response quality and provide improvement suggestions."""
    issues = []
    score = 100

    if not response or len(response.strip()) < 10:
        issues.append("Response is too short")
        score -= 30

    error_phrases = ['error', 'failed', 'could not', 'unable to', 'something went wrong']
    if any(phrase in response.lower() for phrase in error_phrases):
        issues.append("Response contains error indicators")
        score -= 20

    hallucination_phrases = ['i searched', 'according to my search', 'i found that', 'my research shows']
    if any(phrase in response.lower() for phrase in hallucination_phrases):
        if 'web_search' not in str(_conversation_state.last_tool_used):
            issues.append("Possible hallucination - claims search without tool use")
            score -= 25

    sentences = response.split('.')
    unique_sentences = set(s.strip().lower() for s in sentences if s.strip())
    if len(sentences) > 3 and len(unique_sentences) < len(sentences) * 0.7:
        issues.append("Response contains repetitive content")
        score -= 15

    query_words = set(query.lower().split())
    response_words = set(response.lower().split())
    overlap = len(query_words & response_words) / len(query_words) if query_words else 0
    if overlap < 0.2 and len(query_words) > 2:
        issues.append("Response may not address the query directly")
        score -= 10

    return {
        'score': max(0, score),
        'issues': issues,
        'is_valid': score >= 50
    }
