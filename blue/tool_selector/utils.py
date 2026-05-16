"""
Utility functions for tool selection.

Provides fuzzy matching, string normalization, and helper functions.
"""

import re
from functools import lru_cache
from typing import List, Optional, Tuple


@lru_cache(maxsize=512)
def _compile_word_pattern(word: str) -> re.Pattern:
    """Cache compiled regex patterns for word boundary matching."""
    return re.compile(r'\b' + re.escape(word) + r'\b')


def has_word(word: str, text: str) -> bool:
    """
    Check if a word appears as a whole word in text (not as a substring).

    Uses word boundary matching to avoid false positives like
    'light' matching 'highlight' or 'stop' matching 'nonstop'.

    Args:
        word: The word to search for (can be multi-word phrase)
        text: The text to search in (should be lowercase)

    Returns:
        True if word appears as a whole word/phrase

    Examples:
        >>> has_word('light', 'turn on the light')
        True
        >>> has_word('light', 'highlight this text')
        False
        >>> has_word('stop', 'stop the music')
        True
        >>> has_word('stop', 'nonstop flight')
        False
    """
    return bool(_compile_word_pattern(word).search(text))


@lru_cache(maxsize=256)
def _compile_multi_word_pattern(words: Tuple[str, ...]) -> re.Pattern:
    """Cache compiled regex for matching any of multiple words."""
    pattern = r'\b(?:' + '|'.join(re.escape(w) for w in words) + r')\b'
    return re.compile(pattern)


def has_any_word(words: List[str], text: str) -> bool:
    """
    Check if any of the words appear as whole words in text.

    Args:
        words: List of words/phrases to search for
        text: The text to search in (should be lowercase)

    Returns:
        True if any word appears as a whole word/phrase

    Examples:
        >>> has_any_word(['light', 'lamp'], 'turn on the light')
        True
        >>> has_any_word(['light', 'lamp'], 'highlight this text')
        False
    """
    return bool(_compile_multi_word_pattern(tuple(words)).search(text))


def fuzzy_match(query: str, targets: List[str], threshold: float = 0.75) -> Optional[str]:
    """
    Find the best fuzzy match for a query in a list of targets.

    Uses simple similarity ratio - no external dependencies.

    Args:
        query: The search string
        targets: List of possible matches
        threshold: Minimum similarity (0.0 to 1.0)

    Returns:
        Best matching target or None if no good match

    Examples:
        >>> fuzzy_match("beatls", ["beatles", "beach boys"])
        'beatles'
        >>> fuzzy_match("xyz", ["abc", "def"], threshold=0.5)
        None
    """
    if not query or not targets:
        return None

    query_lower = query.lower().strip()

    # Exact match first
    for target in targets:
        if query_lower == target.lower():
            return target

    # Substring match
    for target in targets:
        if query_lower in target.lower() or target.lower() in query_lower:
            return target

    # Similarity matching
    best_match = None
    best_score = 0.0

    for target in targets:
        score = _string_similarity(query_lower, target.lower())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = target

    return best_match


def _string_similarity(s1: str, s2: str) -> float:
    """
    Calculate string similarity using character-based comparison.

    Uses a combination of Levenshtein distance and bigram similarity.

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity score between 0.0 and 1.0
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    # Calculate Levenshtein distance
    def levenshtein_distance(s1, s2):
        if len(s1) < len(s2):
            return levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost of insertions, deletions, or substitutions
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    # Calculate similarity from Levenshtein distance
    max_len = max(len(s1), len(s2))
    distance = levenshtein_distance(s1, s2)
    levenshtein_sim = 1.0 - (distance / max_len)

    # Also calculate bigram similarity for context
    def get_bigrams(s):
        return set(s[i:i+2] for i in range(len(s) - 1)) if len(s) > 1 else {s}

    b1 = get_bigrams(s1)
    b2 = get_bigrams(s2)

    intersection = len(b1 & b2)
    union = len(b1 | b2)
    bigram_sim = intersection / union if union > 0 else 0.0

    # Return weighted average (favor Levenshtein for typos)
    return 0.7 * levenshtein_sim + 0.3 * bigram_sim


def normalize_artist_name(name: str) -> str:
    """
    Normalize artist name for matching.

    Handles common variations like "The Beatles" vs "Beatles",
    ampersands, etc.

    Args:
        name: Artist name to normalize

    Returns:
        Normalized artist name

    Examples:
        >>> normalize_artist_name("The Beatles")
        'beatles'
        >>> normalize_artist_name("Simon & Garfunkel")
        'simon and garfunkel'
    """
    if not name:
        return ""

    # Common replacements
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

    # Remove "the " prefix for matching
    if result.startswith('the '):
        result = result[4:]

    return result


def extract_quoted_text(message: str) -> List[str]:
    """
    Extract text within quotes from a message.

    Args:
        message: Input message

    Returns:
        List of quoted strings

    Examples:
        >>> extract_quoted_text('Send email with subject "Meeting tomorrow"')
        ['Meeting tomorrow']
    """
    # Match both single and double quotes
    patterns = [
        r'"([^"]+)"',  # Double quotes
        r"'([^']+)'",  # Single quotes
    ]

    quoted_texts = []
    for pattern in patterns:
        matches = re.findall(pattern, message)
        quoted_texts.extend(matches)

    return quoted_texts


def contains_time_reference(message: str) -> bool:
    """
    Check if message contains time-related references.

    Args:
        message: Input message

    Returns:
        True if time reference found

    Examples:
        >>> contains_time_reference("tomorrow at 3pm")
        True
        >>> contains_time_reference("hello world")
        False
    """
    time_patterns = [
        'tomorrow', 'today', 'tonight', 'morning', 'afternoon',
        'evening', 'monday', 'tuesday', 'wednesday', 'thursday',
        'friday', 'saturday', 'sunday', 'next week', 'next month',
        'at ', 'pm', 'am', ':00', 'o\'clock', 'oclock',
    ]
    msg_lower = message.lower()
    return any(pattern in msg_lower for pattern in time_patterns)


def split_compound_request(message: str) -> List[str]:
    """
    Split a compound request into individual parts.

    Args:
        message: Input message that may contain multiple requests

    Returns:
        List of individual request strings

    Examples:
        >>> split_compound_request("Turn on lights and play music")
        ['Turn on lights', 'play music']
    """
    from .constants import COMPOUND_CONJUNCTIONS

    msg = message
    for conjunction in COMPOUND_CONJUNCTIONS:
        if conjunction in msg.lower():
            # Split on the conjunction (case-insensitive)
            parts = re.split(re.escape(conjunction), msg, flags=re.IGNORECASE)
            return [part.strip() for part in parts if part.strip()]

    # No compound pattern found
    return [message]
