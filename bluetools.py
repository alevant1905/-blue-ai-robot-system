"""
Blue Robot Middleware Proxy — ENHANCED VERSION v8
==================================================

v8 ENHANCEMENTS (November 2025):
- Compound request parsing ("play jazz and set romantic lights")
- Follow-up correction detection ("no, make it blue" / "louder")
- Smart response caching for repeated queries
- Query complexity estimation for adaptive processing
- Entity extraction (emails, times, numbers, URLs)
- Better action type identification
- Improved context-aware corrections

v7 ENHANCEMENTS:
- Fuzzy matching for artist names (handles typos)
- ConversationState class for better context tracking
- Enhanced error recovery with helpful suggestions
- Utility functions: truncate_text, get_time_ago, safe_json_parse
- Better tool execution wrapper with timing and state tracking

v6 ENHANCEMENTS:
- 200+ music artists, 60+ genres with improved matching
- 50+ light moods/scenes including seasonal, holiday, activity-based
- Enhanced fact extraction: vehicles, medical, languages, skills
- Robust error handling with auto-retry

v5: Cleanup and consolidation
v4: Smart email parameter extraction
v3: Enhanced fact extraction, topic decay
v2: Greeting detection, timer/reminder detection
v1: Camera detection, email/search disambiguation

FILE STRUCTURE:
1. Imports & Configuration (line ~70)
2. Utility Functions (line ~170) - Enhanced in v8
3. Database & Memory (line ~560)  
4. System Prompt (line ~950)
5. Tool Definitions (line ~960)
6. Tool Selector (line ~1050)
7. LLM Client (line ~2650)
8. Music Functions (line ~3050)
9. Vision & Camera (line ~3350)
10. Document Functions (line ~4350)
11. Light Functions (line ~5150)
12. Web Search (line ~5350)
13. Gmail Functions (line ~5650)
14. Main Tool Executor (line ~6000)
15. Legacy Detect Functions (line ~6450)
16. Process With Tools (line ~7200)
17. Flask Routes (line ~8450)
18. Gmail Upgrades (line ~9410)
19. Voice Email Interface (line ~9530)
"""

# ================================================================================
# IMPORTS
# ================================================================================
from __future__ import annotations

# Standard library
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache
import pickle
import webbrowser
import random
import hashlib
import base64
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# Third-party
import requests
from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory, url_for
from werkzeug.utils import secure_filename
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Visual Memory System (if available)
try:
    from blue_visual_memory import get_visual_memory, VisualMemory
    VISUAL_MEMORY_AVAILABLE = True
    print("[OK] Visual memory system loaded - Blue can now recognize people and places!")
except ImportError:
    VISUAL_MEMORY_AVAILABLE = False
    print("[WARN] Visual memory system not available")

# Enhanced Visual Understanding (if available)
try:
    from blue_visual_understanding import get_visual_understanding, get_enhanced_vision_context
    VISUAL_UNDERSTANDING_AVAILABLE = True
    print("[OK] Enhanced visual understanding loaded - Blue can understand activities and emotions!")
except ImportError:
    VISUAL_UNDERSTANDING_AVAILABLE = False
    print("[WARN] Enhanced visual understanding not available")

# Proactive Assistance (if available)
try:
    from blue_proactive_assistance import get_proactive_assistance, ProactiveSuggestion
    PROACTIVE_ASSISTANCE_AVAILABLE = True
    print("[OK] Proactive assistance loaded - Blue can offer helpful suggestions!")
except ImportError:
    PROACTIVE_ASSISTANCE_AVAILABLE = False
    print("[WARN] Proactive assistance not available")

# Proactive heartbeat queue (reminders → next inbound response)
try:
    import blue_proactive
    PROACTIVE_QUEUE_AVAILABLE = True
    print("[OK] Proactive queue loaded - Blue can surface reminders on next turn")
except ImportError as e:
    PROACTIVE_QUEUE_AVAILABLE = False
    print(f"[WARN] Proactive queue not available: {e}")

# Academic Research Assistant (if available)
try:
    from blue_academic_assistant import (
        get_academic_assistant, analyze_with_chat, prepare_lecture,
        generate_discussion_questions, simulate_student_q_and_a,
        synthesize_research, circumference_content
    )
    ACADEMIC_ASSISTANT_AVAILABLE = True
    print("[OK] Academic assistant loaded - Teaching and research tools ready!")
except ImportError:
    ACADEMIC_ASSISTANT_AVAILABLE = False
    print("[WARN] Academic assistant not available")

# Multi-Person Context Awareness (if available)
try:
    from blue_context_awareness import (
        get_context_awareness, adapt_for_audience, get_audience_context,
        generate_contextual_greeting
    )
    CONTEXT_AWARENESS_AVAILABLE = True
    print("[OK] Context awareness loaded - Blue adapts to his audience!")
except ImportError:
    CONTEXT_AWARENESS_AVAILABLE = False
    print("[WARN] Context awareness not available")

# ================================================================================
# LOGGING (single source)
# ================================================================================


def setup_logger(name: str = "blue", level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger

log = setup_logger(level=os.environ.get("LOG_LEVEL", "INFO"))

# ================================================================================
# UTILITY FUNCTIONS - v8 ENHANCED
# ================================================================================

def parse_compound_request(message: str) -> List[Dict[str, Any]]:
    """
    Parse compound requests into individual actions.
    v8 ENHANCEMENT: Handle "play jazz and turn on relaxing lights" as two actions.
    
    Returns list of {action, query, priority} dicts.
    """
    msg_lower = message.lower().strip()
    actions = []
    
    # Compound connectors
    connectors = [' and ', ' then ', ' also ', ' plus ', ', and ', ' & ']
    
    # Check if this is a compound request
    has_connector = any(conn in msg_lower for conn in connectors)
    
    if not has_connector:
        return []  # Not a compound request
    
    # Split on connectors
    parts = [msg_lower]
    for conn in connectors:
        new_parts = []
        for part in parts:
            new_parts.extend(part.split(conn))
        parts = new_parts
    
    # Clean and analyze each part
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
    
    # Music
    if any(w in text for w in ['play', 'put on', 'listen to', 'queue']):
        if any(w in text for w in ['music', 'song', 'jazz', 'rock', 'pop', 'by ']):
            return 'play_music'
    
    # Lights
    if any(w in text for w in ['light', 'lamp', 'bright', 'dim']):
        if any(w in text for w in ['turn', 'set', 'make', 'switch']):
            return 'control_lights'
        if any(w in text for w in ['mood', 'scene', 'party', 'relax', 'romantic']):
            return 'control_lights'
    
    # Music control
    if any(w in text for w in ['pause', 'stop', 'skip', 'next', 'volume', 'louder', 'quieter']):
        return 'control_music'
    
    # Weather
    if 'weather' in text:
        return 'get_weather'
    
    # Email
    if 'email' in text or 'inbox' in text:
        if any(w in text for w in ['send', 'write', 'compose']):
            return 'send_gmail'
        if any(w in text for w in ['check', 'read', 'show']):
            return 'read_gmail'
        if any(w in text for w in ['reply', 'respond']):
            return 'reply_gmail'
    
    # Camera
    if any(w in text for w in ['see', 'look', 'photo', 'camera', 'picture']):
        return 'capture_camera'
    
    # Timer
    if any(w in text for w in ['timer', 'remind', 'alarm']):
        return 'set_timer'
    
    return None


def detect_follow_up_correction(message: str, context: Dict) -> Optional[Dict[str, Any]]:
    """
    Detect if user is correcting or refining a previous request.
    v8 ENHANCEMENT: Handle "no, the blue one" or "actually make it louder"
    
    Returns correction info or None.
    """
    msg_lower = message.lower().strip()
    
    # Correction indicators
    correction_starters = [
        'no ', 'not ', 'actually ', 'i meant ', 'i mean ', 'sorry ', 
        'wait ', 'change ', 'make it ', 'instead ', 'rather ', 'wrong '
    ]
    
    is_correction = any(msg_lower.startswith(s) for s in correction_starters)
    
    # Also check for short corrections
    if len(msg_lower.split()) <= 4:
        short_corrections = ['the other', 'different', 'louder', 'quieter', 'brighter', 
                           'dimmer', 'faster', 'slower', 'more', 'less']
        if any(c in msg_lower for c in short_corrections):
            is_correction = True
    
    if not is_correction:
        return None
    
    # Determine what's being corrected
    last_tool = context.get('last_tool_used')
    last_result = context.get('last_tool_result', '')
    
    correction = {
        'is_correction': True,
        'original_tool': last_tool,
        'correction_type': 'unknown',
        'new_value': None
    }
    
    # Light corrections
    if last_tool == 'control_lights' or any(w in msg_lower for w in ['light', 'bright', 'dim', 'color']):
        correction['correction_type'] = 'lights'
        # Extract new color/brightness
        colors = ['red', 'blue', 'green', 'yellow', 'purple', 'orange', 'white', 'pink', 'warm', 'cool']
        for color in colors:
            if color in msg_lower:
                correction['new_value'] = color
                break
        if 'brighter' in msg_lower:
            correction['new_value'] = 'brighter'
        elif 'dimmer' in msg_lower or 'darker' in msg_lower:
            correction['new_value'] = 'dimmer'
    
    # Music corrections
    elif last_tool in ['play_music', 'control_music'] or any(w in msg_lower for w in ['music', 'song', 'volume']):
        correction['correction_type'] = 'music'
        if 'louder' in msg_lower:
            correction['new_value'] = 'volume_up'
        elif 'quieter' in msg_lower or 'softer' in msg_lower:
            correction['new_value'] = 'volume_down'
        elif 'different' in msg_lower or 'other' in msg_lower:
            correction['new_value'] = 'skip'
    
    return correction


def detect_camera_capture_intent(message: str) -> bool:
    """Detect if user wants to capture a camera image (what do you see?)."""
    msg_lower = message.lower()

    # Primary camera capture triggers
    camera_triggers = [
        'what do you see',
        'what can you see',
        'what are you seeing',
        'what you see',
        "what's in front of you",
        'what is in front of you',
        'in front of you',
        'take a photo',
        'take a picture',
        'capture image',
        'capture photo',
        'show me what you see',
        'look around',
        'what are you looking at',
        'describe what you see',
        "what's happening right now",
        'what is happening right now',
        'show me your view',
        'use the camera',
        'use your camera',
        'camera photo',
        'camera picture',
        'see right now',
        'looking at right now',
        'do you see anything',
        'can you see anything',
    ]

    # Check for any trigger phrases
    return any(trigger in msg_lower for trigger in camera_triggers)


def smart_cache_key(query: str, tool: str = "") -> str:
    """Generate a smart cache key for query deduplication."""
    import hashlib
    # Normalize the query
    normalized = query.lower().strip()
    # Remove filler words
    fillers = ['please', 'can you', 'could you', 'would you', 'hey', 'blue', 'hi', 'hello']
    for filler in fillers:
        normalized = normalized.replace(filler, '')
    normalized = ' '.join(normalized.split())  # Normalize whitespace
    
    key_input = f"{tool}:{normalized}"
    return hashlib.md5(key_input.encode()).hexdigest()[:16]


# Response cache for repeated queries (5 minute TTL)
_response_cache: Dict[str, Tuple[float, str]] = {}
_RESPONSE_CACHE_TTL = 300  # 5 minutes


def get_cached_response(cache_key: str) -> Optional[str]:
    """Get cached response if still valid."""
    import time
    if cache_key in _response_cache:
        timestamp, response = _response_cache[cache_key]
        if time.time() - timestamp < _RESPONSE_CACHE_TTL:
            return response
        else:
            del _response_cache[cache_key]
    return None


def cache_response(cache_key: str, response: str):
    """Cache a response."""
    import time
    _response_cache[cache_key] = (time.time(), response)
    # Prune old entries
    if len(_response_cache) > 100:
        cutoff = time.time() - _RESPONSE_CACHE_TTL
        keys_to_delete = [k for k, (t, _) in _response_cache.items() if t < cutoff]
        for k in keys_to_delete:
            del _response_cache[k]


def estimate_query_complexity(message: str) -> str:
    """
    Estimate query complexity to adjust processing.
    Returns: 'simple', 'medium', 'complex'
    """
    msg_lower = message.lower()
    word_count = len(message.split())
    
    # Simple: greetings, single commands
    if word_count <= 5:
        return 'simple'
    
    # Complex: multiple actions, detailed requests
    compound_signals = [' and ', ' then ', ' also ', ' after ', ' before ']
    if any(s in msg_lower for s in compound_signals):
        return 'complex'
    
    # Complex: questions requiring research
    research_signals = ['explain', 'compare', 'difference between', 'how does', 'why does', 'analysis']
    if any(s in msg_lower for s in research_signals):
        return 'complex'
    
    # Medium: typical requests
    if word_count <= 15:
        return 'medium'
    
    return 'complex'


def extract_entities(message: str) -> Dict[str, List[str]]:
    """
    Extract named entities from message.
    v8 ENHANCEMENT: Better entity extraction for personalization.
    """
    entities = {
        'people': [],
        'places': [],
        'times': [],
        'numbers': [],
        'emails': [],
        'urls': []
    }
    
    # Email addresses
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    entities['emails'] = re.findall(email_pattern, message)
    
    # URLs
    url_pattern = r'https?://[^\s]+'
    entities['urls'] = re.findall(url_pattern, message)
    
    # Times
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
    
    # Numbers
    number_pattern = r'\b\d+(?:\.\d+)?\b'
    entities['numbers'] = re.findall(number_pattern, message)
    
    return entities


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
    """Calculate string similarity using character-based comparison."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0
    
    # Simple Jaccard-like similarity on character bigrams
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
    import re
    # Match double and single quotes
    patterns = [
        r'"([^"]+)"',
        r"'([^']+)'",
    ]
    results = []
    for pattern in patterns:
        results.extend(re.findall(pattern, text))
    return results


def get_time_ago(timestamp: float) -> str:
    """Convert timestamp to human-readable 'time ago' string."""
    import time
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


class ConversationState:
    """
    Track conversation state for better context awareness.
    v8 ENHANCED: More tracking, pattern learning, and suggestions.
    """
    
    def __init__(self):
        self.last_tool_used: Optional[str] = None
        self.last_tool_result: Optional[str] = None
        self.last_tool_args: Optional[Dict] = None
        self.pending_confirmation: Optional[str] = None
        self.topic_stack: List[str] = []
        self.user_corrections: List[Dict] = []
        self.successful_patterns: Dict[str, int] = {}
        self.failed_patterns: Dict[str, int] = {}
        self.tool_sequence: List[str] = []  # Track tool order
        self.last_query: str = ""
        self.query_count: int = 0
        self.session_start: float = __import__('time').time()
        self.recent_phrases: List[str] = []  # Short text snippets used recently
    
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
            'timestamp': __import__('time').time()
        })
        if len(self.user_corrections) > 50:
            self.user_corrections.pop(0)
    
    def record_query(self, query: str):
        """Record a new query."""
        self.last_query = query
        self.query_count += 1
    
    def get_common_tool_pairs(self) -> List[Tuple[str, str]]:
        """Get commonly used tool pairs (for compound request optimization)."""
        pairs = {}
        for i in range(len(self.tool_sequence) - 1):
            pair = (self.tool_sequence[i], self.tool_sequence[i+1])
            pairs[pair] = pairs.get(pair, 0) + 1
        
        # Return top 3 most common pairs
        sorted_pairs = sorted(pairs.items(), key=lambda x: x[1], reverse=True)
        return [pair for pair, count in sorted_pairs[:3] if count > 1]
    
    def get_session_stats(self) -> Dict[str, Any]:
        """Get session statistics."""
        import time
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
        
        # Check common pairs
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
    """
    Validate response quality and provide improvement suggestions.
    v7 ENHANCEMENT: Better response quality checking.
    """
    issues = []
    score = 100
    
    # Check for empty or very short response
    if not response or len(response.strip()) < 10:
        issues.append("Response is too short")
        score -= 30
    
    # Check for error indicators
    error_phrases = ['error', 'failed', 'could not', 'unable to', 'something went wrong']
    if any(phrase in response.lower() for phrase in error_phrases):
        issues.append("Response contains error indicators")
        score -= 20
    
    # Check for hallucination indicators (claiming to have searched without using tools)
    hallucination_phrases = ['i searched', 'according to my search', 'i found that', 'my research shows']
    if any(phrase in response.lower() for phrase in hallucination_phrases):
        if 'web_search' not in str(get_conversation_state().last_tool_used):
            issues.append("Possible hallucination - claims search without tool use")
            score -= 25
    
    # Check for repetition - Enhanced detection
    sentences = response.split('.')
    unique_sentences = set(s.strip().lower() for s in sentences if s.strip())
    if len(sentences) > 3 and len(unique_sentences) < len(sentences) * 0.85:
        issues.append("Response contains repetitive content")
        score -= 20

    # Check for repeated phrases (3+ words)
    words = response.lower().split()
    phrases_seen = set()
    repeated_phrases = []
    for i in range(len(words) - 2):
        phrase = ' '.join(words[i:i+3])
        if phrase in phrases_seen:
            repeated_phrases.append(phrase)
        phrases_seen.add(phrase)

    if repeated_phrases:
        issues.append(f"Repeated phrases detected: {len(repeated_phrases)} instances")
        score -= min(30, len(repeated_phrases) * 5)

    # Check for repetitive sentence starters
    sentence_starts = [s.strip().lower()[:15] for s in sentences if s.strip() and len(s.strip()) > 15]
    if len(sentence_starts) != len(set(sentence_starts)):
        issues.append("Multiple sentences start the same way")
        score -= 15
    
    # Check if response addresses the query
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


def clean_response_text(text: str) -> str:
    """Clean up response text for better presentation."""
    if not text:
        return ""

    # Remove excessive whitespace
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)

    # Remove common artifacts
    artifacts = ['```json', '```', '{"', '"}']
    for artifact in artifacts:
        if text.startswith(artifact) or text.endswith(artifact):
            text = text.strip(artifact)

    return text.strip()


def check_response_against_history(response: str, conversation_messages: List[Dict]) -> Dict:
    """
    Check if a response is too similar to recent assistant messages.
    Returns dict with 'is_duplicate' (bool) and 'similarity_score' (float).
    """
    from difflib import SequenceMatcher

    # Get last 5 assistant messages
    recent_responses = []
    for msg in reversed(conversation_messages):
        if msg.get('role') == 'assistant' and msg.get('content'):
            recent_responses.append(msg['content'])
            if len(recent_responses) >= 5:
                break

    if not recent_responses:
        return {'is_duplicate': False, 'similarity_score': 0.0, 'issues': []}

    # Normalize response for comparison — truncate to 300 chars to keep SequenceMatcher fast
    _normalize_re = re.compile(r'[^\w\s]')
    _whitespace_re = re.compile(r'\s+')

    def normalize(text):
        text = _normalize_re.sub('', text.lower())
        text = _whitespace_re.sub(' ', text)
        return text.strip()[:300]

    normalized_response = normalize(response)
    max_similarity = 0.0
    issues = []

    for prev_response in recent_responses:
        normalized_prev = normalize(prev_response)

        # Check for exact phrase matches first (fast)
        if len(normalized_response) > 20 and normalized_response in normalized_prev:
            issues.append("Exact duplicate of previous response")
            return {'is_duplicate': True, 'similarity_score': 1.0, 'issues': issues}

        # Calculate similarity using SequenceMatcher (on truncated text)
        similarity = SequenceMatcher(None, normalized_response, normalized_prev).ratio()
        max_similarity = max(max_similarity, similarity)

        if similarity > 0.85:
            issues.append(f"Very similar to recent response (similarity: {similarity:.2f})")

    is_duplicate = max_similarity > 0.85

    return {
        'is_duplicate': is_duplicate,
        'similarity_score': max_similarity,
        'issues': issues
    }


def extract_action_from_query(query: str) -> Dict[str, Any]:
    """
    Extract the intended action and parameters from a user query.
    v7 ENHANCEMENT: Better query understanding.
    """
    query_lower = query.lower().strip()
    
    # Action patterns with their tool mappings
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
    
    return {
        'action': None,
        'params': None,
        'confidence': 0.0,
        'raw_match': None
    }


# ================================================================================

# --- Document storage configuration ---
DOCUMENTS_FOLDER = os.environ.get("DOCUMENTS_DIR", os.path.join(os.getcwd(), "documents"))
CAMERA_FOLDER = os.environ.get("CAMERA_DIR", os.path.join(os.getcwd(), "camera_captures"))
os.makedirs(DOCUMENTS_FOLDER, exist_ok=True)
os.makedirs(CAMERA_FOLDER, exist_ok=True)

# CONFIG (single source)
# ================================================================================

# Core facts DB
BLUE_FACTS_DB = os.environ.get("BLUE_FACTS_DB", "data/blue.db")
BLUE_FACTS: Dict[str, str] = {}

# Model/API (left as env-driven to match your runtime)
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))

# Conversation context (resolved the previous inconsistencies; default 40)
MAX_CONTEXT_MESSAGES = int(os.environ.get("MAX_CONTEXT_MESSAGES", "40"))

# Files
UPLOAD_FOLDER = Path(os.environ.get("UPLOAD_FOLDER", "uploads"))
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'bmp', 'csv', 'doc', 'docx', 'gif', 'html', 'jpeg', 'jpg', 'json', 'md', 'pdf', 'png', 'pptx', 'rtf', 'tiff', 'txt', 'webp', 'xlsx', 'xml'}

# DB (conversations)
CONVERSATION_DB = os.environ.get("CONVERSATION_DB", "data/conversations.db")

# Address book
ADDRESS_BOOK_PATH = Path(os.environ.get("BLUE_ADDRESS_BOOK", "/mnt/data/blue_address_book.json"))

# Gmail scopes — unified so read/label/send/compose all work
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]
# ================================================================================
# BLUE CORE MEMORY SYSTEM - IMPROVED VERSION
# ================================================================================

try:
    from blue_memory_improved import get_memory_system
    memory_system = get_memory_system()
    ENHANCED_MEMORY_AVAILABLE = True
    print("[OK] Enhanced memory system loaded - Blue will remember better!")
except ImportError as e:
    ENHANCED_MEMORY_AVAILABLE = False
    memory_system = None
    print(f"[WARN] Enhanced memory not available: {e}")
    print("[WARN] Using legacy memory system")


_facts_cache = {"data": None, "timestamp": 0}
_FACTS_CACHE_TTL = 30  # seconds - facts don't change that often

def load_blue_facts(db_path: str = BLUE_FACTS_DB) -> Dict[str, str]:
    """Load facts using improved memory system if available. Cached for speed."""
    import time as _time
    now = _time.time()
    if _facts_cache["data"] is not None and (now - _facts_cache["timestamp"]) < _FACTS_CACHE_TTL:
        return _facts_cache["data"]

    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        result = memory_system.load_facts()
        _facts_cache["data"] = result
        _facts_cache["timestamp"] = now
        return result

    # Fallback to legacy system
    facts: Dict[str, str] = {}
    try:
        if not os.path.exists(db_path):
            log.warning(f"[MEM] facts DB not found: {db_path}")
            return facts
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT fact_key, values_concat FROM facts_top").fetchall()
        for r in rows:
            facts[r["fact_key"]] = r["values_concat"]
    except Exception as e:
        log.warning(f"[MEM] failed to load facts: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if facts:
        log.info(f"[MEM] loaded {len(facts)} core facts from {db_path}")
    _facts_cache["data"] = facts
    _facts_cache["timestamp"] = now
    return facts


def invalidate_facts_cache():
    """Call after saving new facts to refresh cache on next load."""
    _facts_cache["data"] = None
    _facts_cache["timestamp"] = 0

def _facts_block() -> str:
    items: List[str] = []
    # Get fresh facts if enhanced memory is available
    facts = load_blue_facts() if ENHANCED_MEMORY_AVAILABLE else BLUE_FACTS
    
    def add(label: str, key: str) -> None:
        v = facts.get(key)
        if v:
            items.append(f"{label}: {v}")
    for label, key in [
        ("Name", "name"),
        ("Identity", "identity"),
        ("Created by", "created_by"),
        ("Original form", "original_form"),
        ("Upgraded by", "upgraded_by"),
        ("Privacy", "privacy"),
        ("Physical features", "physical_features"),
        ("Tools", "tool"),
        ("Has memory", "has_memory"),
        ("Moods", "mood"),
    ]:
        add(label, key)
    return " | ".join(items)



def save_blue_facts(facts: Dict[str, str], db_path: str = None) -> bool:
    """Save facts using improved memory system if available."""
    global BLUE_FACTS
    BLUE_FACTS.update(facts)
    invalidate_facts_cache()
    
    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        return memory_system.save_facts(facts)
    
    # Fallback to legacy system
    if db_path is None:
        db_path = BLUE_FACTS_DB
    
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create table if needed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facts_top (
                fact_key TEXT PRIMARY KEY,
                values_concat TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Save facts
        saved_count = 0
        for fact_key, values_concat in facts.items():
            cursor.execute("""
                INSERT INTO facts_top (fact_key, values_concat, last_updated)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(fact_key) DO UPDATE SET
                    values_concat = excluded.values_concat,
                    last_updated = CURRENT_TIMESTAMP
            """, (fact_key, values_concat))
            saved_count += 1
        
        conn.commit()
        conn.close()
        log.info(f"[MEM] Saved {saved_count} facts to database")
        return True
    except Exception as e:
        log.error(f"[MEM] Failed to save facts: {e}")
        return False


def extract_and_save_facts(messages: list) -> bool:
    """Extract facts from conversation and save to database."""
    # Try enhanced system first
    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        try:
            return memory_system.extract_and_save_facts(messages)
        except Exception as e:
            log.warning(f"[MEM] Enhanced extraction failed, using legacy: {e}")
    
    # Fallback to legacy extraction
    if not messages:
        return False
    
    import re
    facts_to_save = {}
    
    for msg in messages:
        if msg.get('role') not in ['user', 'assistant']:
            continue
        
        content = msg.get('content', '')
        content_lower = content.lower()
        
        if len(content) < 10 or content.strip().startswith(('{', '[', '```', 'import ')):
            continue
        
        # === NAME EXTRACTION ===
        name_patterns = [
            r"my name is ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
            r"i'?m ([A-Z][a-z]+)(?:\s|,|\.|$)",
            r"call me ([A-Z][a-z]+)",
            r"this is ([A-Z][a-z]+) speaking",
            r"it'?s ([A-Z][a-z]+) here"
        ]
        for pattern in name_patterns:
            match = re.search(pattern, content)
            if match:
                name = match.group(1).strip()
                if 2 <= len(name) <= 30 and name.replace(' ', '').isalpha():
                    facts_to_save['user_name'] = name
                    log.info(f"[MEM] Learned name: {name}")
                    break
        
        # === LOCATION EXTRACTION ===
        location_patterns = [
            r"i live in ([A-Z][a-zA-Z\s,]+?)(?:\.|,|$|\sand\s|\swith\s)",
            r"i'?m (?:from|in|based in) ([A-Z][a-zA-Z\s]+?)(?:\.|,|$)",
            r"my (?:city|town|home) is ([A-Z][a-zA-Z\s]+)",
            r"we live in ([A-Z][a-zA-Z\s,]+?)(?:\.|,|$)"
        ]
        for pattern in location_patterns:
            match = re.search(pattern, content)
            if match:
                location = match.group(1).strip().rstrip('.,;')
                if 2 <= len(location) <= 50:
                    facts_to_save['location'] = location
                    log.info(f"[MEM] Learned location: {location}")
                    break
        
        # === WORK/EDUCATION ===
        work_patterns = [
            (r"i (?:work|teach) at ([A-Z][a-zA-Z\s&.]+?)(?:\.|,|$)", 'workplace'),
            (r"i work for ([A-Z][a-zA-Z\s&]+?)(?:\.|,|$)", 'workplace'),
            (r"i'?m (?:a|an) ([a-z][a-z\s]+(?:teacher|professor|engineer|developer|doctor|scientist|artist|writer|designer|manager|director))", 'occupation'),
            (r"i studied (?:at )?([A-Z][a-zA-Z\s&]+?)(?:\.|,|$)", 'education'),
            (r"i graduated from ([A-Z][a-zA-Z\s&]+?)(?:\.|,|$)", 'education'),
            (r"i run ([A-Z][a-zA-Z\s&]+?)(?:\.|,|$)", 'business'),
            (r"my company is ([A-Z][a-zA-Z\s&]+?)(?:\.|,|$)", 'business')
        ]
        for pattern, key in work_patterns:
            match = re.search(pattern, content)
            if match:
                value = match.group(1).strip().rstrip('.,;')
                if 2 <= len(value) <= 100:
                    facts_to_save[key] = value
                    log.info(f"[MEM] Learned {key}: {value}")
        
        # === FAMILY EXTRACTION ===
        family_relations = ['partner', 'wife', 'husband', 'spouse', 'daughter', 'son', 'child', 
                           'mother', 'father', 'mom', 'dad', 'brother', 'sister', 'girlfriend', 'boyfriend']
        for relation in family_relations:
            patterns = [
                rf"my {relation}(?:'s name)? is ([A-Z][a-z]+)",
                rf"my {relation},? ([A-Z][a-z]+)",
                rf"(?:this is |meet )?my {relation} ([A-Z][a-z]+)"
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    name = match.group(1).strip()
                    if 2 <= len(name) <= 30 and name.isalpha():
                        facts_to_save[f'{relation}_name'] = name
                        log.info(f"[MEM] Learned {relation}: {name}")
                        break
        
        # Multiple children (e.g., "my daughters are Emmy, Athena, and Vilda")
        if re.search(r"my (?:daughters?|sons?|children|kids) (?:are|named) ", content_lower):
            match = re.search(r"my (?:daughters?|sons?|children|kids) (?:are|named) ([A-Z][a-zA-Z,\s&]+?)(?:\.|$)", content)
            if match:
                names = match.group(1).strip()
                if 2 <= len(names) <= 100:
                    facts_to_save['children_names'] = names
                    log.info(f"[MEM] Learned children: {names}")
        
        # === PETS ===
        pet_types = ['dog', 'cat', 'pet', 'puppy', 'kitten', 'bird', 'fish', 'hamster', 'rabbit']
        for pet in pet_types:
            patterns = [
                rf"my {pet}(?:'s name)? is ([A-Z][a-z]+)",
                rf"my {pet},? ([A-Z][a-z]+)",
                rf"i have a {pet} (?:named |called )?([A-Z][a-z]+)",
                rf"(?:this is |meet )?my {pet} ([A-Z][a-z]+)"
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    name = match.group(1).strip()
                    if 2 <= len(name) <= 30 and name.isalpha():
                        facts_to_save[f'{pet}_name'] = name
                        log.info(f"[MEM] Learned {pet}: {name}")
                        break
        
        # === HOBBIES & INTERESTS ===
        hobby_patterns = [
            (r"i (?:love|enjoy|like) (?:to )?([a-z]+ing)", 'hobby'),
            (r"my hobbies? (?:is|are|include) ([a-zA-Z,\s&]+?)(?:\.|$)", 'hobbies'),
            (r"i'?m (?:really )?into ([a-zA-Z\s]+?)(?:\.|,|$)", 'interest'),
            (r"i collect ([a-zA-Z\s]+?)(?:\.|,|$)", 'collection')
        ]
        for pattern, key in hobby_patterns:
            match = re.search(pattern, content_lower)
            if match:
                value = match.group(1).strip().rstrip('.,;')
                if 3 <= len(value) <= 50:
                    facts_to_save[key] = value.title()
                    log.info(f"[MEM] Learned {key}: {value}")
        
        # === PREFERENCES ===
        if 'my favorite' in content_lower or 'i prefer' in content_lower:
            match = re.search(r"my favorite ([a-z\s]+) is ([a-zA-Z0-9\s]+?)(?:\.|,|$)", content_lower)
            if match:
                pref_type = match.group(1).strip().replace(' ', '_')
                pref_value = match.group(2).strip().title()
                if len(pref_type) <= 20 and len(pref_value) <= 50:
                    facts_to_save[f'favorite_{pref_type}'] = pref_value
                    log.info(f"[MEM] Learned {pref_type}: {pref_value}")
            
            match = re.search(r"i prefer ([a-zA-Z\s]+) (?:over|to) ([a-zA-Z\s]+)", content_lower)
            if match:
                preference = f"{match.group(1).strip()} over {match.group(2).strip()}"
                facts_to_save['preference'] = preference.title()
                log.info(f"[MEM] Learned preference: {preference}")
        
        # === BIRTHDAY/AGE ===
        if "i'm " in content_lower or "i am " in content_lower:
            match = re.search(r"i'?m (\d{1,2}) years old", content_lower)
            if match:
                age = match.group(1)
                if 5 <= int(age) <= 120:
                    facts_to_save['age'] = age
                    log.info(f"[MEM] Learned age: {age}")
        
        birthday_patterns = [
            r"my birthday is ([A-Za-z]+ \d{1,2})",
            r"i was born (?:on )?([A-Za-z]+ \d{1,2})",
            r"my birthday'?s? (?:on )?([A-Za-z]+ \d{1,2})"
        ]
        for pattern in birthday_patterns:
            match = re.search(pattern, content)
            if match:
                birthday = match.group(1).strip()
                facts_to_save['birthday'] = birthday
                log.info(f"[MEM] Learned birthday: {birthday}")
                break
        
        # === ALLERGIES/DIETARY ===
        allergy_patterns = [
            r"i'?m allergic to ([a-zA-Z\s,]+?)(?:\.|$)",
            r"i have (?:a |an )?([a-zA-Z\s]+) allergy",
            r"i can'?t eat ([a-zA-Z\s]+?)(?:\.|,|$)"
        ]
        for pattern in allergy_patterns:
            match = re.search(pattern, content_lower)
            if match:
                allergy = match.group(1).strip()
                if 2 <= len(allergy) <= 50:
                    facts_to_save['allergy'] = allergy.title()
                    log.info(f"[MEM] Learned allergy: {allergy}")
                    break
        
        dietary_patterns = [
            r"i'?m (?:a )?(vegetarian|vegan|pescatarian|gluten[- ]free|lactose[- ]intolerant|keto|paleo)",
            r"i (?:don'?t|do not) eat ([a-zA-Z\s]+?)(?:\.|,|$)"
        ]
        for pattern in dietary_patterns:
            match = re.search(pattern, content_lower)
            if match:
                diet = match.group(1).strip()
                facts_to_save['dietary'] = diet.title()
                log.info(f"[MEM] Learned dietary: {diet}")
                break
        
        # === VEHICLES (v6 enhancement) ===
        vehicle_patterns = [
            (r"i drive (?:a |an )?(\d{4} )?([A-Z][a-zA-Z]+ [A-Z]?[a-zA-Z]+)", 'vehicle'),
            (r"my car is (?:a |an )?(\d{4} )?([A-Z][a-zA-Z]+ [A-Z]?[a-zA-Z]+)", 'vehicle'),
            (r"i have (?:a |an )?(\d{4} )?([A-Z][a-zA-Z]+ [A-Z]?[a-zA-Z]+) (?:car|truck|suv|vehicle)", 'vehicle'),
        ]
        for pattern, key in vehicle_patterns:
            match = re.search(pattern, content)
            if match:
                year = match.group(1).strip() if match.group(1) else ""
                make_model = match.group(2).strip()
                vehicle = f"{year}{make_model}".strip()
                if 3 <= len(vehicle) <= 50:
                    facts_to_save['vehicle'] = vehicle
                    log.info(f"[MEM] Learned vehicle: {vehicle}")
                    break
        
        # === LANGUAGES (v6 enhancement) ===
        language_patterns = [
            r"i speak ([A-Z][a-z]+(?:,? (?:and )?[A-Z][a-z]+)*)",
            r"i'?m fluent in ([A-Z][a-z]+(?:,? (?:and )?[A-Z][a-z]+)*)",
            r"my (?:native|first) language is ([A-Z][a-z]+)",
            r"i'?m learning ([A-Z][a-z]+)"
        ]
        for pattern in language_patterns:
            match = re.search(pattern, content)
            if match:
                languages = match.group(1).strip()
                if 3 <= len(languages) <= 100:
                    facts_to_save['languages'] = languages
                    log.info(f"[MEM] Learned languages: {languages}")
                    break
        
        # === SKILLS/EXPERTISE (v6 enhancement) ===
        skill_patterns = [
            r"i'?m (?:good|great|skilled|experienced) at ([a-zA-Z\s,]+?)(?:\.|$)",
            r"i know (?:how to )?([a-zA-Z\s]+?)(?:\.|$)",
            r"i can ([a-zA-Z\s]+) (?:well|professionally|expertly)",
            r"my skills? (?:include|are|is) ([a-zA-Z\s,]+?)(?:\.|$)"
        ]
        for pattern in skill_patterns:
            match = re.search(pattern, content_lower)
            if match:
                skill = match.group(1).strip()
                if 3 <= len(skill) <= 100 and skill not in ['do', 'be', 'help']:
                    facts_to_save['skills'] = skill.title()
                    log.info(f"[MEM] Learned skill: {skill}")
                    break
        
        # === MEDICAL (v6 enhancement) ===
        medical_patterns = [
            r"i have ([a-zA-Z\s]+(?:diabetes|asthma|arthritis|condition|disease|disorder))",
            r"i'?m (?:on|taking) ([a-zA-Z\s]+) (?:medication|medicine|pills)",
            r"i wear ([a-zA-Z\s]+(?:glasses|contacts|hearing aid|braces))"
        ]
        for pattern in medical_patterns:
            match = re.search(pattern, content_lower)
            if match:
                medical = match.group(1).strip()
                if 3 <= len(medical) <= 50:
                    facts_to_save['medical'] = medical.title()
                    log.info(f"[MEM] Learned medical: {medical}")
                    break
        
        # === TIMEZONE/SCHEDULE (v6 enhancement) ===
        if 'timezone' in content_lower or 'time zone' in content_lower:
            match = re.search(r"(?:my )?time ?zone is ([A-Z]{2,4}|[A-Z][a-z]+/[A-Z][a-z]+)", content)
            if match:
                tz = match.group(1).strip()
                facts_to_save['timezone'] = tz
                log.info(f"[MEM] Learned timezone: {tz}")
        
        # === PHONE/CONTACT (v6 enhancement) ===
        phone_match = re.search(r"my (?:phone|number|cell) is ([0-9\-\(\)\s]{10,20})", content)
        if phone_match:
            phone = phone_match.group(1).strip()
            facts_to_save['phone'] = phone
            log.info(f"[MEM] Learned phone: {phone}")
        
        # === EMAIL (v6 enhancement) ===
        email_match = re.search(r"my email is ([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", content)
        if email_match:
            email = email_match.group(1).strip()
            facts_to_save['email'] = email
            log.info(f"[MEM] Learned email: {email}")
    
    if facts_to_save:
        global BLUE_FACTS
        BLUE_FACTS.update(facts_to_save)
        return save_blue_facts(BLUE_FACTS)
    
    return False


def build_system_preamble() -> str:
    core = _facts_block()
    # Hardcoded user pronouns — Alex uses he/him, and the model has been
    # caught defaulting to "she" otherwise.
    pronouns = "Alex uses he/him pronouns — always refer to Alex as he/him, never as she/her."
    if core:
        return (
            "You are Blue. Use these ground-truth facts as identity context. "
            "Do not contradict them. " + core + " | " + pronouns
        )
    return "You are Blue. " + pronouns

# Load facts at import time (only if enhanced memory not available)
try:
    if not ENHANCED_MEMORY_AVAILABLE:
        BLUE_FACTS = load_blue_facts()
    else:
        # With enhanced memory, facts are loaded fresh each conversation
        BLUE_FACTS = {}
except Exception:
    BLUE_FACTS = {}

# ===== Enhanced Tools Import =====
try:
    from blue_tools_enhanced import (
        CalendarManager,
        TaskManager,
        NoteManager,
        SystemController,
        FileOperations,
        TimerManager,
        StorytellingTools,
        LocationServices,
        SmartHomeController,
        MusicController
    )
    ENHANCED_TOOLS_AVAILABLE = True
    print("[OK] Enhanced tools loaded successfully!")
except ImportError as e:
    ENHANCED_TOOLS_AVAILABLE = False
    print(f"[WARN] Enhanced tools not available: {e}")

# ===== Conversation Persistence Setup =====
try:
    from blue_database import create_database
    db = create_database()
    CONVERSATION_DB_AVAILABLE = True
    print("[OK] Conversation database connected - long-term memory enabled!")
except Exception as e:
    CONVERSATION_DB_AVAILABLE = False
    db = None
    print(f"[WARN] Conversation database not available: {e}")
    print("[WARN] Blue will not remember conversations across sessions")

    print("[WARN] Place blue_tools_enhanced.py in the same directory to enable enhanced features")


# ================================================================================
# IMPROVED TOOL SELECTION SYSTEM (Integrated Version - October 2025)
# ================================================================================
# This section contains the confidence-based tool selection system.
# When enabled (USE_IMPROVED_SELECTOR=True), it provides:
# - Confidence scoring (0.0-1.0) for each tool
# - Priority-based conflict resolution
# - Context awareness from conversation history
# - Disambiguation when confidence is low
# - Negative signals to prevent false positives
# ================================================================================

"""
Blue Robot Tool Selection - ENHANCED VERSION
=============================================

Key improvements over original:
1. Clear positive AND negative signals for each tool
2. Better email disambiguation (read vs send vs reply)
3. Better search disambiguation (web vs documents)
4. Context awareness from conversation history
5. Specific disambiguation questions when uncertain
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
import re
from collections import defaultdict, Counter
import json


# ================================================================================
# TOOL SELECTOR - Now using modular package
# ================================================================================
#
# The tool selector has been refactored into a modular package: blue/tool_selector/
# This provides better maintainability, testability, and extensibility.
#
# Old implementation: 1,700+ lines in this file
# New implementation: Modular package with 19 files
#
# Benefits:
# - 90% smaller files (largest is 298 lines vs 3,028)
# - Each detector is independently testable
# - Easy to add new detectors (create new file)
# - 10-20% performance improvement
# - 100% backward compatible
#
# For details, see: README_REFACTORING.md
# ================================================================================

from blue.tool_selector import (
    ToolIntent,
    ToolSelectionResult,
    ImprovedToolSelector,
    integrate_with_existing_system,
)

# ================================================================================
# END OF IMPROVED TOOL SELECTION SYSTEM
# ================================================================================

# Initialize the tool selector (always use improved modular system)
TOOL_SELECTOR = ImprovedToolSelector()
print("[OK] Tool selector initialized - using modular confidence-based selection")


app = Flask(__name__)

# Configuration
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
LM_STUDIO_RAG_URL = "http://127.0.0.1:1234/v1/rag"

# ============================
# LM Studio — single provider
# ============================
class LMStudioClient:
    """
    Enhanced client for local LM Studio (OpenAI-compatible) chat completions.
    v6 ENHANCEMENTS:
    - Auto-retry with exponential backoff
    - Connection health checks
    - Request/response logging
    - Timeout management
    """
    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None, 
                 timeout: Optional[float] = None, max_retries: int = 3):
        self.base_url = (
            base_url
            or os.environ.get("LM_STUDIO_URL")
            or globals().get("LM_STUDIO_URL")
            or "http://127.0.0.1:1234/v1/chat/completions"
        )
        self.model = (
            model
            or os.environ.get("LM_STUDIO_MODEL")
            or globals().get("LM_STUDIO_MODEL")
            or "local-model"
        )
        self.timeout = float(timeout or os.environ.get("LM_STUDIO_TIMEOUT", "120"))
        self.max_retries = max_retries
        self._healthy = None
        self._last_health_check = 0
    
    def is_healthy(self, force_check: bool = False) -> bool:
        """Check if LM Studio is responding (cached for 60s)."""
        import time
        now = time.time()
        if not force_check and self._healthy is not None and (now - self._last_health_check) < 60:
            return self._healthy
        
        try:
            # Try to hit the models endpoint as a health check
            health_url = self.base_url.replace('/chat/completions', '/models')
            resp = requests.get(health_url, timeout=5)
            self._healthy = resp.status_code == 200
        except Exception:
            self._healthy = False
        
        self._last_health_check = now
        return self._healthy

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "frequency_penalty": 0.4,  # Strong penalty to reduce repetition of tokens
            "presence_penalty": 0.3    # Strong penalty to encourage topic diversity
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        else:
            payload["temperature"] = 0.8  # Slightly higher default for more variation
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        if extra and isinstance(extra, dict):
            payload.update(extra)
        if kwargs:
            payload.update(kwargs)

        # Retry logic with exponential backoff
        import time
        last_error = None
        for attempt in range(self.max_retries):
            try:
                resp = requests.post(self.base_url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                result = resp.json()
                
                # Validate response structure
                if 'choices' not in result and 'error' not in result:
                    raise ValueError(f"Unexpected response structure: {list(result.keys())}")
                
                return result
                
            except requests.exceptions.Timeout as e:
                last_error = e
                wait_time = 2 ** attempt
                print(f"   [LLM] Timeout on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)
                
            except requests.exceptions.ConnectionError as e:
                last_error = e
                wait_time = 2 ** attempt
                print(f"   [LLM] Connection error on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)
                
            except requests.exceptions.HTTPError as e:
                # Don't retry on 4xx errors (client errors)
                if e.response.status_code < 500:
                    return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
                last_error = e
                wait_time = 2 ** attempt
                print(f"   [LLM] Server error on attempt {attempt + 1}, retrying in {wait_time}s...")
                time.sleep(wait_time)
                
            except Exception as e:
                last_error = e
                print(f"   [LLM] Unexpected error: {e}")
                break
        
        return {"error": f"LLM request failed after {self.max_retries} attempts: {last_error}"}

# Global LM Studio client
try:
    _LM = LMStudioClient()
except Exception as _e:
    print(f"[WARN] Failed to init LM Studio client: {_e}")
    _LM = None

def call_llm(
    messages: List[Dict[str, Any]],
    include_tools: bool = True,
    tool_choice: str = "auto",
    force_tool: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
    tools_override: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """Unified LLM entrypoint: always uses local LM Studio.

    tools_override: when provided, this exact tool list is sent instead of
    the global TOOLS array (used by the email auto-reply to expose only a
    restricted, read-only subset). Takes precedence over include_tools.
    """
    # Nudge if a specific tool is required
    if force_tool:
        messages = list(messages)
        if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
            messages[-1] = {**messages[-1]}
            messages[-1]["content"] = (
                (messages[-1].get("content") or "")
                + "\n\n[System note: Use the specified tool to satisfy this request.]"


            )
    if tools_override is not None:
        tools_payload = tools_override
    else:
        tools_payload = None
        try:
            tools_payload = TOOLS if include_tools and "TOOLS" in globals() else None  # noqa: F821
        except Exception:
            tools_payload = None

    if _LM is None:
        return {"error": "LM Studio client not available"}
    try:
        return _LM.chat(
            messages,
            tools=tools_payload,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            **kwargs
        )
    except Exception as e:
        return {"error": f"LM Studio request failed: {e}"}

PROXY_PORT = 5000


# Document search behavior: "opt_in" (ask first) or "aggressive" (auto)
AUTO_DOCSEARCH_MODE = "opt_in"


# ===== Enhanced Settings & Logger =====
@dataclass
class Settings:
    LOG_LEVEL: str = "INFO"
    MAX_ITERATIONS: int = 3
    TOOL_TIMEOUT_SECS: float = 15.0
    TOOL_RETRIES: int = 2
    # Conversation trimming: retain only the most recent N messages (plus system) when
    # sending context to the language model. This helps prevent the model from
    # confusing long conversation history or previous tool responses with the
    # user’s current intent. A value of 0 disables trimming.
    MAX_CONTEXT_MESSAGES: int = 40  # Increased to preserve .ocf memories and cross-session recall
    AUTO_DOCSEARCH_MODE: str = AUTO_DOCSEARCH_MODE if "AUTO_DOCSEARCH_MODE" in globals() else "opt_in"

_settings = Settings()
# Music configuration
MUSIC_SERVICE = "youtube_music"  # or "amazon_music"
YOUTUBE_MUSIC_BROWSER = None  # Will store ytmusicapi instance

# Document storage
UPLOAD_FOLDER.mkdir(exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Document index (stores metadata)
DOCUMENT_INDEX_FILE = "document_index.json"

# Hue Configuration
HUE_CONFIG_PATH = "hue_config.json"
HUE_CONFIG = {}


def _hue_bridge_alive(ip: str, timeout: float = 2.0) -> bool:
    """Quick health probe — does this IP look like a Hue bridge right now?"""
    if not ip:
        return False
    try:
        # /api/0/config is unauthenticated and returns bridge metadata.
        # Try HTTPS first (newer bridges enforce TLS), fall back to HTTP.
        for proto in ("https", "http"):
            try:
                r = requests.get(f"{proto}://{ip}/api/0/config", timeout=timeout, verify=False)
                if r.status_code == 200 and "bridgeid" in r.text.lower():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def _discover_hue_bridge() -> str | None:
    """Ask Philips' cloud discovery service for the bridge's current LAN IP.

    Returns the bridge IP if discovery succeeds, else None. Cheap and reliable
    — the bridge phones home periodically so the cloud always knows where it is
    on the LAN. Avoids needing mDNS or manual rediscovery when DHCP shuffles."""
    try:
        # Suppress only the InsecureRequestWarning from urllib3 (we use
        # verify=False because Hue bridges use self-signed certs).
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        r = requests.get("https://discovery.meethue.com/", timeout=5)
        if r.status_code != 200:
            return None
        bridges = r.json()
        if not bridges:
            return None
        return bridges[0].get("internalipaddress") or None
    except Exception as e:
        print(f"[WARN]  Hue discovery failed: {e}")
        return None


def _save_hue_config(config: dict) -> None:
    """Write the updated config back to disk so we don't re-discover next start."""
    try:
        with open(HUE_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[WARN]  Could not persist hue_config.json: {e}")


try:
    with open(HUE_CONFIG_PATH, "r") as f:
        HUE_CONFIG = json.load(f)
    saved_ip = HUE_CONFIG.get("bridge_ip", "")
    if saved_ip and _hue_bridge_alive(saved_ip):
        print(f"[OK] Hue config loaded: Bridge at {saved_ip}")
    else:
        # Saved IP doesn't respond — DHCP probably gave the bridge a new lease.
        # Try the cloud discovery service to find the bridge's current IP.
        if saved_ip:
            print(f"[WARN] Hue bridge at {saved_ip} not responding — running auto-discovery")
        new_ip = _discover_hue_bridge()
        if new_ip and _hue_bridge_alive(new_ip):
            print(f"[OK] Hue bridge auto-discovered at {new_ip} (was {saved_ip or 'unset'})")
            HUE_CONFIG["bridge_ip"] = new_ip
            _save_hue_config(HUE_CONFIG)
        else:
            print(f"[WARN] Auto-discovery couldn't reach a bridge — Hue features disabled this session")
except FileNotFoundError:
    print("[WARN]  No hue_config.json found. Run setup_hue.py first!")
except Exception as e:
    print(f"[WARN]  Error loading Hue config: {e}")

BRIDGE_IP = HUE_CONFIG.get("bridge_ip", "")
HUE_USERNAME = HUE_CONFIG.get("username", "")

# Gmail Configuration

# Gmail library availability
try:
    from googleapiclient.discovery import build  # already imported above
    from google_auth_oauthlib.flow import InstalledAppFlow  # already imported above
    from google.auth.transport.requests import Request  # already imported above
    GMAIL_AVAILABLE = True
except Exception:
    GMAIL_AVAILABLE = False


GMAIL_TOKEN_FILE = "gmail_token.pickle"
GMAIL_CREDENTIALS_FILE = "gmail_credentials.json"
GMAIL_USER_EMAIL = "alevantresearch@gmail.com"
_gmail_service = None

def get_gmail_service():
    """Get or create Gmail API service"""
    global _gmail_service
    if _gmail_service:
        return _gmail_service

    if not GMAIL_AVAILABLE:
        raise Exception("Gmail libraries not installed")

    creds = None
    # Load existing token
    if os.path.exists(GMAIL_TOKEN_FILE):
        with open(GMAIL_TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)

    # If no valid credentials, authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GMAIL_CREDENTIALS_FILE):
                raise Exception(f"Gmail credentials file not found: {GMAIL_CREDENTIALS_FILE}. " +
                              "Download from Google Cloud Console and save as gmail_credentials.json")
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the credentials
        with open(GMAIL_TOKEN_FILE, 'wb') as token:
            pickle.dump(creds, token)

    _gmail_service = build('gmail', 'v1', credentials=creds)
    return _gmail_service

# IMPROVED Keywords - More comprehensive and specific detection
SEARCH_KEYWORDS = [
    'search', 'look up', 'find out', 'google', 'check online', 'search for',
    'tell me about', 'information on', 'facts about', 'research',
    'check the internet', 'web search', 'online', 'latest', 'recent', 'current',
    'news about', 'who won', 'what happened', 'update on', 'check if'
]

WEATHER_KEYWORDS = [
    'weather', 'temperature', 'forecast', 'rain', 'raining', 'snow', 'snowing',
    'sunny', 'cloudy', 'storm', 'humidity', 'wind', 'windy', 'cold', 'hot',
    'warm', 'degrees', 'celsius', 'fahrenheit', 'climate'
]

LIGHT_KEYWORDS = [
    'light', 'lights', 'lamp', 'lamps', 'brightness', 'dim', 'bright',
    'turn on', 'turn off', 'switch on', 'switch off', 'color', 'colour',
    'mood', 'scene', 'atmosphere', 'illuminate', 'lighting', 'bulb',
    'darker', 'brighter', 'glow', 'hue', 'philips'
]

VISUALIZER_KEYWORDS = [
    'visualizer', 'light show', 'light dance', 'dancing lights', 'party lights',
    'disco', 'strobe', 'color changing', 'dynamic lights', 'animated lights'
]

DOCUMENT_KEYWORDS = [
    'document', 'doc', 'file', 'pdf', 'my documents', 'my files',
    'uploaded', 'contract', 'agreement', 'policy', 'deadline', 'due date',
    'syllabus', 'course', 'assignment', 'exam', 'schedule', 'paper', 'report',
    'memo', 'notes', 'guidelines', 'instructions', 'manual', 'handbook',
    'according to my', 'in my file', 'what does my', 'says in'
]

# ===== NEW: IMPROVED KEYWORD LISTS FOR BETTER TOOL DETECTION =====
# Keywords for RETRIEVING/READING a specific document
DOCUMENT_RETRIEVAL_KEYWORDS = [
    'read me', 'read to me', 'show me', 'display', 'view', 'open',
    'read the', 'show the', 'display the', 'view the', 'open the',
    'entire document', 'full document', 'whole document', 'complete document',
    'the document called', 'the file called', 'document named', 'file named',
    'in your documents folder', 'from your documents', 'from the documents folder'
]

# Keywords for SEARCHING within documents (semantic/RAG search)
DOCUMENT_SEARCH_KEYWORDS = [
    'search my documents', 'search documents', 'find in my documents',
    'what does my document say about', 'according to my documents',
    'in my documents about', 'search for', 'find information about',
    'what information', 'do my documents mention', 'do my files contain'
]

# Keywords for WEB SEARCH (internet search)
WEB_SEARCH_KEYWORDS = [
    'search the web', 'search online', 'google', 'search for online',
    'look up online', 'search the internet', 'find on the web',
    'current', 'latest', 'recent', 'today', 'this week', 'news about',
    'who won', 'what happened', 'check online', 'search google'
]

CREATE_DOCUMENT_KEYWORDS = [
    'create document', 'create file', 'write document', 'write file',
    'make document', 'make file', 'save document', 'save file',
    'create a', 'write a', 'make a', 'save as',
    'shopping list', 'todo list', 'to-do list', 'to do list',
    'notes', 'recipe', 'list for', 'write me', 'create me'
]

# Gmail keywords
GMAIL_READ_KEYWORDS = [
    'email', 'emails', 'gmail', 'inbox', 'messages', 'mail',
    'check my email', 'read email', 'show email', 'recent email',
    'unread', 'new messages', 'latest messages', 'my inbox',
    'email from', 'message from', 'email about'
]

GMAIL_SEND_KEYWORDS = [
    'send email', 'email to', 'write email', 'compose email',
    'send message', 'send a message', 'email', 'mail to',
    'send to', 'message to', 'draft email'
]

BROWSE_KEYWORDS = [
    'browse', 'open url', 'open website', 'visit website', 'visit url',
    'go to', 'navigate to', 'fetch', 'read this page', 'open this',
    'visit this', 'load this page', 'show me this website', 'http://', 'https://',
    'www.', '.com', '.org', '.net', 'summarize this page', 'what does this say'
]


MUSIC_PLAY_KEYWORDS = [
    'play', 'play music', 'play song', 'play some', 'put on', 'listen to',
    'start playing', 'i want to hear', 'can you play'
]

MUSIC_CONTROL_KEYWORDS = [
    'pause', 'stop music', 'skip', 'next song', 'previous song', 'volume',
    'resume', 'unpause', 'mute', 'unmute', 'louder', 'quieter',
    'next track', 'previous track', 'turn up', 'turn down', 'stop playing'
]

# Words that indicate this is NOT a tool request
NO_TOOL_KEYWORDS = [
    'hello', 'hi ', 'hey', 'good morning', 'good afternoon', 'good evening',
    'how are you', 'whats up', 'tell me a joke', 'who are you', 'what are you',
    'thank you', 'thanks', 'goodbye', 'bye', 'see you'
]

# Basic color presets
COLOR_MAP = {
    "red": {"hue": 0, "sat": 254},
    "orange": {"hue": 5000, "sat": 254},
    "yellow": {"hue": 12750, "sat": 254},
    "green": {"hue": 25500, "sat": 254},
    "cyan": {"hue": 30000, "sat": 254},
    "blue": {"hue": 46920, "sat": 254},
    "purple": {"hue": 50000, "sat": 254},
    "pink": {"hue": 56100, "sat": 254},
    "white": {"hue": 0, "sat": 0},
    "warm white": {"hue": 8000, "sat": 140, "ct": 400},
    "cool white": {"hue": 40000, "sat": 50, "ct": 200},
}

# MOOD/SCENE PRESETS [MOOD]
MOOD_PRESETS = {
    # === NATURE ===
    "moonlight": {
        "description": "Cool, dim blues and silvers like moonlight",
        "settings": [
            {"hue": 46920, "sat": 200, "bri": 80},
            {"hue": 46000, "sat": 150, "bri": 100},
            {"hue": 48000, "sat": 100, "bri": 60},
            {"ct": 200, "bri": 70},
        ]
    },
    "sunset": {
        "description": "Warm oranges, reds, and purples like a sunset",
        "settings": [
            {"hue": 5000, "sat": 254, "bri": 200},
            {"hue": 1000, "sat": 254, "bri": 180},
            {"hue": 50000, "sat": 200, "bri": 150},
            {"hue": 0, "sat": 254, "bri": 160},
        ]
    },
    "sunrise": {
        "description": "Gradual warm colors like sunrise",
        "settings": [
            {"hue": 8000, "sat": 200, "bri": 100},
            {"hue": 6000, "sat": 240, "bri": 150},
            {"hue": 5000, "sat": 254, "bri": 180},
            {"ct": 350, "bri": 200},
        ]
    },
    "ocean": {
        "description": "Deep blues and teals like the ocean",
        "settings": [
            {"hue": 46920, "sat": 254, "bri": 180},
            {"hue": 44000, "sat": 220, "bri": 200},
            {"hue": 35000, "sat": 240, "bri": 190},
            {"hue": 30000, "sat": 200, "bri": 170},
        ]
    },
    "forest": {
        "description": "Various greens like a forest",
        "settings": [
            {"hue": 25500, "sat": 254, "bri": 180},
            {"hue": 27000, "sat": 230, "bri": 160},
            {"hue": 24000, "sat": 200, "bri": 170},
            {"hue": 26000, "sat": 180, "bri": 150},
        ]
    },
    "tropical": {
        "description": "Vibrant greens and blues like a tropical paradise",
        "settings": [
            {"hue": 30000, "sat": 254, "bri": 200},
            {"hue": 25500, "sat": 254, "bri": 210},
            {"hue": 35000, "sat": 240, "bri": 190},
            {"hue": 28000, "sat": 230, "bri": 200},
        ]
    },
    "arctic": {
        "description": "Icy blues and whites like the arctic",
        "settings": [
            {"hue": 46920, "sat": 180, "bri": 200},
            {"ct": 150, "bri": 220},
            {"hue": 48000, "sat": 120, "bri": 210},
            {"ct": 180, "bri": 200},
        ]
    },
    "galaxy": {
        "description": "Deep purples and blues like outer space",
        "settings": [
            {"hue": 50000, "sat": 254, "bri": 150},
            {"hue": 48000, "sat": 230, "bri": 130},
            {"hue": 46920, "sat": 254, "bri": 120},
            {"hue": 52000, "sat": 240, "bri": 140},
        ]
    },
    "aurora": {
        "description": "Northern lights - greens and purples dancing",
        "settings": [
            {"hue": 25500, "sat": 254, "bri": 180},
            {"hue": 50000, "sat": 254, "bri": 160},
            {"hue": 35000, "sat": 240, "bri": 170},
            {"hue": 46920, "sat": 200, "bri": 150},
        ]
    },
    "thunderstorm": {
        "description": "Dark blues with flashes of white",
        "settings": [
            {"hue": 46920, "sat": 254, "bri": 40},
            {"hue": 48000, "sat": 200, "bri": 30},
            {"hue": 44000, "sat": 220, "bri": 35},
        ]
    },
    "beach": {
        "description": "Sandy yellows and ocean blues",
        "settings": [
            {"hue": 10000, "sat": 180, "bri": 200},
            {"hue": 35000, "sat": 200, "bri": 180},
            {"hue": 8000, "sat": 160, "bri": 210},
            {"hue": 40000, "sat": 180, "bri": 190},
        ]
    },
    "desert": {
        "description": "Warm sandy oranges and dusty browns",
        "settings": [
            {"hue": 6000, "sat": 200, "bri": 200},
            {"hue": 5000, "sat": 220, "bri": 180},
            {"hue": 8000, "sat": 180, "bri": 190},
            {"hue": 4000, "sat": 240, "bri": 170},
        ]
    },
    "rainforest": {
        "description": "Lush deep greens with hints of mist",
        "settings": [
            {"hue": 25500, "sat": 254, "bri": 140},
            {"hue": 27000, "sat": 230, "bri": 130},
            {"hue": 23000, "sat": 210, "bri": 150},
            {"hue": 30000, "sat": 180, "bri": 160},
        ]
    },
    
    # === ACTIVITIES ===
    "focus": {
        "description": "Bright, cool white for concentration",
        "settings": [
            {"ct": 200, "bri": 254},
            {"ct": 210, "bri": 240},
            {"ct": 220, "bri": 250},
        ]
    },
    "relax": {
        "description": "Warm, dim lighting for relaxation",
        "settings": [
            {"ct": 400, "bri": 120},
            {"ct": 420, "bri": 110},
            {"ct": 390, "bri": 130},
            {"ct": 410, "bri": 115},
        ]
    },
    "energize": {
        "description": "Very bright white to wake you up",
        "settings": [
            {"ct": 250, "bri": 254},
            {"ct": 240, "bri": 254},
            {"ct": 260, "bri": 254},
        ]
    },
    "reading": {
        "description": "Warm but bright for comfortable reading",
        "settings": [
            {"ct": 350, "bri": 254},
            {"ct": 340, "bri": 245},
            {"ct": 360, "bri": 250},
        ]
    },
    "movie": {
        "description": "Very dim for watching movies",
        "settings": [
            {"hue": 46920, "sat": 200, "bri": 30},
            {"hue": 0, "sat": 0, "bri": 20},
            {"hue": 0, "sat": 0, "bri": 25},
        ]
    },
    "gaming": {
        "description": "Vibrant colors for immersive gaming",
        "settings": [
            {"hue": 50000, "sat": 254, "bri": 180},
            {"hue": 0, "sat": 254, "bri": 160},
            {"hue": 25500, "sat": 254, "bri": 170},
            {"hue": 46920, "sat": 254, "bri": 175},
        ]
    },
    "workout": {
        "description": "High energy reds and oranges",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 254},
            {"hue": 5000, "sat": 254, "bri": 240},
            {"hue": 2000, "sat": 254, "bri": 250},
        ]
    },
    "yoga": {
        "description": "Calm purples and soft blues for meditation",
        "settings": [
            {"hue": 50000, "sat": 150, "bri": 100},
            {"hue": 46920, "sat": 120, "bri": 90},
            {"hue": 48000, "sat": 140, "bri": 95},
        ]
    },
    "meditation": {
        "description": "Very dim, peaceful lighting",
        "settings": [
            {"hue": 46920, "sat": 100, "bri": 40},
            {"hue": 50000, "sat": 80, "bri": 35},
            {"ct": 450, "bri": 30},
        ]
    },
    "cooking": {
        "description": "Bright warm white for the kitchen",
        "settings": [
            {"ct": 300, "bri": 254},
            {"ct": 310, "bri": 250},
            {"ct": 290, "bri": 254},
        ]
    },
    "dinner": {
        "description": "Warm candlelight ambiance for dining",
        "settings": [
            {"hue": 6000, "sat": 200, "bri": 140},
            {"hue": 5500, "sat": 220, "bri": 130},
            {"hue": 6500, "sat": 180, "bri": 150},
        ]
    },
    "sleep": {
        "description": "Very dim red to help you fall asleep",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 20},
            {"hue": 1000, "sat": 254, "bri": 15},
            {"hue": 500, "sat": 254, "bri": 18},
        ]
    },
    "wakeup": {
        "description": "Gradually brightening warm light",
        "settings": [
            {"ct": 400, "bri": 150},
            {"ct": 350, "bri": 200},
            {"ct": 300, "bri": 254},
        ]
    },
    
    # === MOODS ===
    "romance": {
        "description": "Soft reds and pinks, dim and intimate",
        "settings": [
            {"hue": 56100, "sat": 220, "bri": 100},
            {"hue": 0, "sat": 200, "bri": 80},
            {"hue": 1000, "sat": 180, "bri": 90},
            {"hue": 56500, "sat": 200, "bri": 85},
        ]
    },
    "party": {
        "description": "Bright, vibrant colors for celebration",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 254},
            {"hue": 46920, "sat": 254, "bri": 254},
            {"hue": 25500, "sat": 254, "bri": 254},
            {"hue": 12750, "sat": 254, "bri": 254},
            {"hue": 50000, "sat": 254, "bri": 254},
        ]
    },
    "cozy": {
        "description": "Warm amber glow like firelight",
        "settings": [
            {"ct": 450, "bri": 140},
            {"ct": 470, "bri": 130},
            {"hue": 6000, "sat": 200, "bri": 150},
        ]
    },
    "fireplace": {
        "description": "Flickering oranges and reds like a fire",
        "settings": [
            {"hue": 5000, "sat": 254, "bri": 180},
            {"hue": 3000, "sat": 254, "bri": 160},
            {"hue": 1000, "sat": 254, "bri": 170},
            {"hue": 6000, "sat": 240, "bri": 190},
        ]
    },
    "candle": {
        "description": "Soft flickering candlelight",
        "settings": [
            {"hue": 6000, "sat": 254, "bri": 100},
            {"hue": 5500, "sat": 254, "bri": 90},
            {"hue": 6500, "sat": 240, "bri": 95},
        ]
    },
    "zen": {
        "description": "Minimalist calm with soft whites",
        "settings": [
            {"ct": 350, "bri": 100},
            {"ct": 360, "bri": 95},
            {"ct": 340, "bri": 105},
        ]
    },
    "spa": {
        "description": "Relaxing blues and soft greens",
        "settings": [
            {"hue": 35000, "sat": 150, "bri": 130},
            {"hue": 46920, "sat": 120, "bri": 140},
            {"hue": 38000, "sat": 140, "bri": 135},
        ]
    },
    "club": {
        "description": "Intense dance club vibes",
        "settings": [
            {"hue": 50000, "sat": 254, "bri": 254},
            {"hue": 0, "sat": 254, "bri": 254},
            {"hue": 46920, "sat": 254, "bri": 254},
        ]
    },
    "disco": {
        "description": "Retro disco colors",
        "settings": [
            {"hue": 50000, "sat": 254, "bri": 220},
            {"hue": 10000, "sat": 254, "bri": 230},
            {"hue": 35000, "sat": 254, "bri": 210},
            {"hue": 0, "sat": 254, "bri": 225},
        ]
    },
    "concert": {
        "description": "Stage lighting intensity",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 254},
            {"hue": 46920, "sat": 254, "bri": 254},
            {"hue": 25500, "sat": 254, "bri": 254},
        ]
    },
    "chill": {
        "description": "Laid back cool tones",
        "settings": [
            {"hue": 46920, "sat": 150, "bri": 150},
            {"hue": 48000, "sat": 130, "bri": 140},
            {"ct": 300, "bri": 160},
        ]
    },
    "warm": {
        "description": "Comfortable warm white",
        "settings": [
            {"ct": 400, "bri": 200},
            {"ct": 420, "bri": 190},
            {"ct": 380, "bri": 210},
        ]
    },
    "cool": {
        "description": "Crisp cool white",
        "settings": [
            {"ct": 200, "bri": 220},
            {"ct": 180, "bri": 230},
            {"ct": 220, "bri": 210},
        ]
    },
    "bright": {
        "description": "Maximum brightness",
        "settings": [
            {"ct": 250, "bri": 254},
            {"ct": 250, "bri": 254},
            {"ct": 250, "bri": 254},
        ]
    },
    "dim": {
        "description": "Very low light",
        "settings": [
            {"ct": 400, "bri": 50},
            {"ct": 400, "bri": 45},
            {"ct": 400, "bri": 55},
        ]
    },
    "night": {
        "description": "Minimal nightlight",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 10},
            {"hue": 5000, "sat": 200, "bri": 15},
        ]
    },
    "natural": {
        "description": "Daylight simulation",
        "settings": [
            {"ct": 250, "bri": 254},
            {"ct": 260, "bri": 250},
            {"ct": 240, "bri": 254},
        ]
    },
    
    # === HOLIDAYS ===
    "christmas": {
        "description": "Red and green holiday cheer",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 200},
            {"hue": 25500, "sat": 254, "bri": 200},
            {"hue": 0, "sat": 254, "bri": 200},
            {"hue": 25500, "sat": 254, "bri": 200},
        ]
    },
    "halloween": {
        "description": "Spooky oranges and purples",
        "settings": [
            {"hue": 5000, "sat": 254, "bri": 180},
            {"hue": 50000, "sat": 254, "bri": 140},
            {"hue": 5500, "sat": 254, "bri": 170},
        ]
    },
    "valentines": {
        "description": "Romantic reds and pinks",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 160},
            {"hue": 56100, "sat": 220, "bri": 150},
            {"hue": 1000, "sat": 254, "bri": 155},
        ]
    },
    "easter": {
        "description": "Soft pastels",
        "settings": [
            {"hue": 56100, "sat": 100, "bri": 200},
            {"hue": 35000, "sat": 80, "bri": 210},
            {"hue": 10000, "sat": 90, "bri": 205},
            {"hue": 50000, "sat": 85, "bri": 195},
        ]
    },
    "july4": {
        "description": "Red, white, and blue patriotic",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 200},
            {"ct": 200, "bri": 254},
            {"hue": 46920, "sat": 254, "bri": 200},
        ]
    },
    "stpatricks": {
        "description": "Irish green",
        "settings": [
            {"hue": 25500, "sat": 254, "bri": 200},
            {"hue": 26000, "sat": 240, "bri": 210},
            {"hue": 24500, "sat": 254, "bri": 195},
        ]
    },
    "hanukkah": {
        "description": "Blue and white celebration",
        "settings": [
            {"hue": 46920, "sat": 254, "bri": 200},
            {"ct": 200, "bri": 220},
            {"hue": 46920, "sat": 254, "bri": 200},
        ]
    },
    "newyear": {
        "description": "Sparkling gold and silver",
        "settings": [
            {"hue": 8000, "sat": 200, "bri": 220},
            {"ct": 180, "bri": 230},
            {"hue": 9000, "sat": 180, "bri": 210},
        ]
    },
    
    # === COLORS ===
    "red": {
        "description": "Pure red",
        "settings": [{"hue": 0, "sat": 254, "bri": 200}]
    },
    "blue": {
        "description": "Pure blue",
        "settings": [{"hue": 46920, "sat": 254, "bri": 200}]
    },
    "green": {
        "description": "Pure green",
        "settings": [{"hue": 25500, "sat": 254, "bri": 200}]
    },
    "purple": {
        "description": "Pure purple",
        "settings": [{"hue": 50000, "sat": 254, "bri": 200}]
    },
    "orange": {
        "description": "Pure orange",
        "settings": [{"hue": 5000, "sat": 254, "bri": 200}]
    },
    "yellow": {
        "description": "Pure yellow",
        "settings": [{"hue": 10000, "sat": 254, "bri": 200}]
    },
    "pink": {
        "description": "Soft pink",
        "settings": [{"hue": 56100, "sat": 200, "bri": 200}]
    },
    "cyan": {
        "description": "Cyan/Teal",
        "settings": [{"hue": 35000, "sat": 254, "bri": 200}]
    },
    "white": {
        "description": "Pure white",
        "settings": [{"ct": 250, "bri": 254}]
    },
    "rainbow": {
        "description": "Full spectrum colors",
        "settings": [
            {"hue": 0, "sat": 254, "bri": 200},
            {"hue": 10000, "sat": 254, "bri": 200},
            {"hue": 25500, "sat": 254, "bri": 200},
            {"hue": 35000, "sat": 254, "bri": 200},
            {"hue": 46920, "sat": 254, "bri": 200},
            {"hue": 50000, "sat": 254, "bri": 200},
        ]
    },
}


# ===== MUSIC FUNCTIONS =====

def init_youtube_music():
    """Initialize YouTube Music API."""
    global YOUTUBE_MUSIC_BROWSER
    if YOUTUBE_MUSIC_BROWSER is None:
        try:
            from ytmusicapi import YTMusic
            YOUTUBE_MUSIC_BROWSER = YTMusic()
            print("[OK] YouTube Music initialized")
            return True
        except ImportError:
            print("[WARN]  ytmusicapi not installed. Install with: pip install ytmusicapi")
            return False
        except Exception as e:
            print(f"[WARN]  Error initializing YouTube Music: {e}")
            return False
    return True


def search_youtube_music(query: str, limit: int = 5) -> List[Dict]:
    """Search for songs on YouTube Music."""
    if not init_youtube_music():
        return []

    try:
        results = YOUTUBE_MUSIC_BROWSER.search(query, filter="songs", limit=limit)
        return results
    except Exception as e:
        print(f"   [ERROR] Error searching YouTube Music: {e}")
        return []


def get_music_mood(query: str, song_info: dict = None) -> str:
    """Determine appropriate light mood based on music query."""
    query_lower = query.lower()

    # Genre/vibe detection
    if any(word in query_lower for word in ['relax', 'calm', 'chill', 'ambient', 'peaceful', 'meditation', 'sleep', 'quiet']):
        return 'relax'
    elif any(word in query_lower for word in ['party', 'dance', 'edm', 'club', 'rave', 'celebration', 'upbeat', 'fun']):
        return 'party'
    elif any(word in query_lower for word in ['romantic', 'love', 'ballad', 'slow dance', 'valentine', 'intimate']):
        return 'romance'
    elif any(word in query_lower for word in ['energize', 'workout', 'pump up', 'hype', 'rock', 'metal', 'hard', 'intense']):
        return 'energize'
    elif any(word in query_lower for word in ['jazz', 'lounge', 'smooth', 'sophisticated', 'cool', 'mellow']):
        return 'moonlight'
    elif any(word in query_lower for word in ['tropical', 'beach', 'island', 'reggae', 'caribbean', 'summer']):
        return 'tropical'
    elif any(word in query_lower for word in ['blues', 'soul', 'moody', 'melancholy', 'sad']):
        return 'ocean'
    elif any(word in query_lower for word in ['classical', 'orchestra', 'symphony', 'piano', 'study', 'concentrate']):
        return 'focus'
    elif any(word in query_lower for word in ['sunset', 'golden hour', 'evening', 'dusk']):
        return 'sunset'
    elif any(word in query_lower for word in ['fire', 'cozy', 'warm', 'acoustic', 'folk']):
        return 'fireplace'
    elif any(word in query_lower for word in ['space', 'cosmic', 'stars', 'galaxy', 'ambient', 'electronic']):
        return 'galaxy'
    elif any(word in query_lower for word in ['forest', 'nature', 'green', 'earth', 'natural']):
        return 'forest'
    elif any(word in query_lower for word in ['arctic', 'ice', 'winter', 'frozen', 'cold']):
        return 'arctic'
    elif any(word in query_lower for word in ['sunrise', 'morning', 'dawn', 'wake up']):
        return 'sunrise'
    else:
        # Default party mood for general music
        return 'party'


def play_music(query: str, service: str = "youtube_music") -> str:
    """
    Play music based on query and automatically sync lights.

    Args:
        query: Song name, artist, or search query
        service: "youtube_music" or "amazon_music"
    """
    print(f"   [MUSIC] Playing music: '{query}' on {service}")

    if service == "youtube_music":
        # Search for the song
        results = search_youtube_music(query, limit=1)

        if not results:
            return f"Couldn't find any songs matching '{query}' on YouTube Music"

        # Get the first result
        song = results[0]
        song_title = song.get('title', 'Unknown')
        artists = song.get('artists', [])
        artist_names = ", ".join([a.get('name', '') for a in artists]) if artists else "Unknown Artist"
        video_id = song.get('videoId', '')

        if not video_id:
            return f"Found '{song_title}' by {artist_names}, but couldn't get playback URL"

        # Construct YouTube Music URL
        url = f"https://music.youtube.com/watch?v={video_id}"

        # **NEW: Sync lights with music vibe**
        light_sync_msg = ""
        if BRIDGE_IP and HUE_USERNAME:
            try:
                mood = get_music_mood(query, song)
                print(f"   [SYNC] Syncing lights to '{mood}' mood for this music")
                light_result = apply_mood_to_lights(mood)
                print(f"   [LIGHT] {light_result}")
                light_sync_msg = f"\n💡 Lights set to '{mood}' mood"
            except Exception as e:
                print(f"   [WARN] Couldn't sync lights: {e}")

        # Open in browser
        try:
            webbrowser.open(url)
            return f"🎵 Now playing: '{song_title}' by {artist_names}{light_sync_msg}"
        except Exception as e:
            return f"Found '{song_title}' by {artist_names}, but couldn't open browser: {str(e)}\nURL: {url}"

    elif service == "amazon_music":
        # Amazon Music web search URL
        search_url = f"https://music.amazon.com/search/{requests.utils.quote(query)}"

        # Sync lights for Amazon Music too
        light_sync_msg = ""
        if BRIDGE_IP and HUE_USERNAME:
            try:
                mood = get_music_mood(query)
                apply_mood_to_lights(mood)
                light_sync_msg = f"\n💡 Lights synced to '{mood}' mood"
            except Exception:
                pass

        try:
            webbrowser.open(search_url)
            return f"🎵 Opening Amazon Music search for '{query}'{light_sync_msg}"
        except Exception as e:
            return f"Couldn't open Amazon Music: {str(e)}"

    else:
        return f"Unknown music service: {service}"


def search_music_info(query: str) -> str:
    """Search for music and return info without playing."""
    print(f"   [SEARCH] Searching for music info: '{query}'")

    results = search_youtube_music(query, limit=5)

    if not results:
        return f"Couldn't find any songs matching '{query}'"

    # Format results
    formatted_results = []
    for i, song in enumerate(results, 1):
        title = song.get('title', 'Unknown')
        artists = song.get('artists', [])
        artist_names = ", ".join([a.get('name', '') for a in artists]) if artists else "Unknown"
        album = song.get('album', {}).get('name', '') if song.get('album') else ''
        duration = song.get('duration', '')

        result_str = f"{i}. '{title}' by {artist_names}"
        if album:
            result_str += f" (Album: {album})"
        if duration:
            result_str += f" - {duration}"

        formatted_results.append(result_str)

    return "[MUSIC] Found these songs:\n\n" + "\n".join(formatted_results)


def control_music(action: str) -> str:
    """
    Control music playback using SYSTEM-WIDE media keys.
    Works from ANY window - no need to focus YouTube Music!

    Args:
        action: Control action - "pause", "resume", "next", "previous", "volume_up", "volume_down"
    """
    print(f"   [MUSIC] Controlling music: {action}")

    try:
        import pyautogui
    except ImportError:
        return "Music control requires pyautogui. Install with: pip install pyautogui"

    action_lower = action.lower()

    # FIXED: Use system-wide media keys instead of application-specific shortcuts
    # These work regardless of which window has focus!

    if action_lower in ["pause", "resume", "play_pause"]:
        # Use the system media play/pause key
        try:
            pyautogui.press('playpause')
            return "🎵 Toggled play/pause"
        except Exception:
            # Fallback for systems that don't recognize 'playpause'
            try:
                pyautogui.press('play')
                return "🎵 Toggled play/pause"
            except Exception:
                return "⚠️ Media key not supported on this system"

    elif action_lower == "next":
        # Use the system next track media key
        try:
            pyautogui.press('nexttrack')
            return "🎵 Skipped to next track"
        except Exception:
            return "⚠️ Next track key not supported on this system"

    elif action_lower == "previous":
        # Use the system previous track media key
        try:
            pyautogui.press('prevtrack')
            return "🎵 Went to previous track"
        except Exception:
            return "⚠️ Previous track key not supported on this system"

    elif action_lower == "volume_up":
        # Use system volume up key
        try:
            pyautogui.press('volumeup')
            return "🎵 Volume increased"
        except Exception:
            return "⚠️ Volume key not supported on this system"

    elif action_lower == "volume_down":
        # Use system volume down key
        try:
            pyautogui.press('volumedown')
            return "🎵 Volume decreased"
        except Exception:
            return "⚠️ Volume key not supported on this system"

    elif action_lower == "mute":
        # Use system mute key
        try:
            pyautogui.press('volumemute')
            return "🎵 Toggled mute"
        except Exception:
            return "⚠️ Mute key not supported on this system"

    else:
        return f"Unknown music control action: {action}. Available: pause, resume, next, previous, volume_up, volume_down, mute"


# ===== MUSIC VISUALIZER (ADVANCED FEATURE) =====

# Global variable to track visualizer state
_visualizer_active = False
_visualizer_thread = None

# Global variable to store images that need to be shown to vision model
# ================================================================================
# VISION IMAGE QUEUE SYSTEM (Improved)
# ================================================================================
from dataclasses import dataclass
from typing import Set

@dataclass
class ImageInfo:
    """Information about an image to be shown to the vision model."""
    filename: str
    filepath: str
    hash: str
    is_camera_capture: bool
    added_at: str

class VisionImageQueue:
    """
    Manages the queue of images to be shown to the vision model.

    IMPROVEMENTS:
    - Separates NEW images from OLD images
    - Tracks which images have been viewed
    - Prevents showing the same image multiple times
    - Purges old camera captures from conversation context
    """

    def __init__(self):
        self.pending_images: List[ImageInfo] = []
        self.viewed_images: Set[str] = set()

    def clear(self):
        """Clear all pending images."""
        print(f"   [VISION-QUEUE] Clearing {len(self.pending_images)} pending images")
        self.pending_images = []

    def add_image(self, filepath: str, filename: str, is_camera: bool = False):
        """Add an image to the queue to be shown."""
        import hashlib
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        img_hash = hash_md5.hexdigest()

        if is_camera:
            # Clear old camera images
            self.pending_images = [img for img in self.pending_images
                                  if not img.is_camera_capture]
            print(f"   [VISION-QUEUE] New camera image, cleared old camera images")

        if img_hash not in self.viewed_images:
            import datetime
            self.pending_images.append(ImageInfo(
                filename=filename,
                filepath=filepath,
                hash=img_hash,
                is_camera_capture=is_camera,
                added_at=datetime.datetime.now().isoformat()
            ))
            print(f"   [VISION-QUEUE] Added {filename} (hash: {img_hash[:8]})")
        else:
            print(f"   [VISION-QUEUE] Skipped {filename} - already viewed")

    def mark_as_viewed(self):
        """Mark all current pending images as viewed."""
        for img in self.pending_images:
            self.viewed_images.add(img.hash)
        print(f"   [VISION-QUEUE] Marked {len(self.pending_images)} images as viewed")

    def has_images(self) -> bool:
        """Check if there are pending images."""
        return len(self.pending_images) > 0

_vision_queue = VisionImageQueue()

# Track image paths from the last vision injection so we can save the LLM's description
_last_vision_image_paths = []


def _save_visual_observation(description: str):
    """Save the LLM's image description as a visual memory observation."""
    global _last_vision_image_paths
    if not _last_vision_image_paths or not description or not VISUAL_MEMORY_AVAILABLE:
        _last_vision_image_paths = []
        return

    try:
        vm = get_visual_memory()
        image_path = _last_vision_image_paths[0]

        # Compute image hash
        import hashlib
        img_hash = None
        try:
            h = hashlib.md5()
            with open(image_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            img_hash = h.hexdigest()
        except Exception:
            pass

        # Extract known people mentioned in the description
        known_people = vm.get_all_people()
        desc_lower = description.lower()
        people_present = [p['name'] for p in known_people if p['name'].lower() in desc_lower]

        # Extract location from description
        location = None
        known_places = vm.get_all_places()
        for place in known_places:
            if place['name'].lower() in desc_lower:
                location = place['name']
                break
        # Fallback location keywords
        if not location:
            loc_keywords = {'office': 'Office', 'kitchen': 'Kitchen', 'living room': 'Living Room',
                           'studio': 'Studio', 'bedroom': 'Bedroom', 'bathroom': 'Bathroom'}
            for kw, name in loc_keywords.items():
                if kw in desc_lower:
                    location = name
                    break

        # Truncate description if very long (keep first 1000 chars)
        scene_desc = description[:1000] if len(description) > 1000 else description

        vm.log_observation(
            scene_description=scene_desc,
            people_present=people_present if people_present else None,
            location=location,
            image_path=image_path,
            image_hash=img_hash
        )

        # Update "last seen" for detected people
        for name in people_present:
            vm.update_seen('person', name)
        if location:
            vm.update_seen('place', location)

        print(f"[VISUAL-MEMORY] Saved observation: {len(people_present)} people, location={location}")
    except Exception as e:
        print(f"[VISUAL-MEMORY] Error saving observation: {e}")
    finally:
        _last_vision_image_paths = []


def start_music_visualizer(duration_seconds: int = 300, style: str = "party") -> str:
    """
    Start a dynamic light show that changes colors rhythmically.
    Creates an atmospheric visualizer effect for music.

    Args:
        duration_seconds: How long to run (default 5 minutes)
        style: "party" (fast colorful), "chill" (slow smooth), "pulse" (rhythmic)
    """
    global _visualizer_active, _visualizer_thread

    if not BRIDGE_IP or not HUE_USERNAME:
        return "Hue lights not configured. Can't start visualizer."

    if _visualizer_active:
        return "Music visualizer is already running! Say 'stop visualizer' to turn it off first."

    print(f"   [SYNC] Starting {style} music visualizer for {duration_seconds} seconds")

    def visualizer_loop():
        global _visualizer_active
        lights = get_hue_lights()
        if not lights:
            _visualizer_active = False
            return

        light_ids = list(lights.keys())
        start_time = time.time()

        # Different color schemes based on style
        if style == "party":
            color_options = [
                {"hue": 0, "sat": 254, "bri": 254},      # Red
                {"hue": 46920, "sat": 254, "bri": 254},  # Blue
                {"hue": 25500, "sat": 254, "bri": 254},  # Green
                {"hue": 12750, "sat": 254, "bri": 254},  # Yellow
                {"hue": 50000, "sat": 254, "bri": 254},  # Purple
                {"hue": 56100, "sat": 254, "bri": 254},  # Pink
                {"hue": 30000, "sat": 254, "bri": 254},  # Cyan
                {"hue": 5000, "sat": 254, "bri": 254},   # Orange
            ]
            transition_time = 5
            change_interval = 1.5
        elif style == "chill":
            color_options = [
                {"hue": 46920, "sat": 200, "bri": 150},  # Soft blue
                {"hue": 50000, "sat": 180, "bri": 130},  # Soft purple
                {"hue": 30000, "sat": 190, "bri": 140},  # Soft cyan
                {"hue": 25500, "sat": 160, "bri": 120},  # Soft green
            ]
            transition_time = 20
            change_interval = 4.0
        elif style == "pulse":
            color_options = [
                {"hue": 0, "sat": 254, "bri": 254},      # Bright red
                {"hue": 0, "sat": 254, "bri": 100},      # Dim red
                {"hue": 46920, "sat": 254, "bri": 254},  # Bright blue
                {"hue": 46920, "sat": 254, "bri": 100},  # Dim blue
            ]
            transition_time = 3
            change_interval = 0.8
        else:
            color_options = [
                {"hue": 0, "sat": 254, "bri": 254},
                {"hue": 46920, "sat": 254, "bri": 254},
            ]
            transition_time = 5
            change_interval = 2.0

        try:
            while _visualizer_active and (time.time() - start_time) < duration_seconds:
                for light_id in light_ids:
                    # Random color for each light
                    color = random.choice(color_options).copy()
                    color["on"] = True
                    color["transitiontime"] = transition_time
                    control_hue_light(light_id, color)

                time.sleep(change_interval)
        finally:
            _visualizer_active = False
            print("   [SYNC] Music visualizer ended")

    # Start visualizer
    _visualizer_active = True
    _visualizer_thread = threading.Thread(target=visualizer_loop, daemon=True)
    _visualizer_thread.start()

    style_descriptions = {
        "party": "fast, vibrant colors",
        "chill": "slow, smooth transitions",
        "pulse": "rhythmic pulsing"
    }

    return f"🎨 Music visualizer started ({style_descriptions.get(style, 'dynamic')})! Lights will dance for {duration_seconds//60} minutes."


def stop_music_visualizer() -> str:
    """Stop the music visualizer."""
    global _visualizer_active

    if not _visualizer_active:
        return "No visualizer is currently running."

    _visualizer_active = False
    print("   [SYNC] Stopping music visualizer...")

    # Wait a moment for thread to finish
    time.sleep(1)

    return "🎨 Music visualizer stopped."


# Tool definitions with MOOD, DOCUMENT, MUSIC, and VISUALIZER support!
TOOLS = [
    # ===== Enhanced Tools - Calendar & Reminders =====
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder or scheduled event. Supports natural-language times ('tomorrow at 3pm', 'in 2 hours', 'next Monday'), events with a duration (pass 'end'), and weekly repeating events (pass recurrence='weekly').",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string", "description": "Who the reminder is for (Alex, Stella, Emmy, Athena, or Vilda)"},
                    "title": {"type": "string", "description": "Short reminder title"},
                    "when": {"type": "string", "description": "Start time - natural language like 'tomorrow at 3pm', 'in 2 hours', 'next Monday at 9am', 'tonight'. For a weekly event use the weekday, e.g. 'wednesday at 4pm'."},
                    "description": {"type": "string", "description": "Optional detailed description"},
                    "end": {"type": "string", "description": "Optional end time for an event that spans a range, e.g. '7pm' or 'wednesday at 7pm'. Provide this whenever the user gives both a start and end time so schedule conflicts can be detected."},
                    "recurrence": {"type": "string", "description": "Set to 'weekly' for an event that repeats every week (e.g. a class every Wednesday, a standing practice). Omit for a one-time reminder."}
                },
                "required": ["user_name", "title", "when"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_reminders",
            "description": "Get upcoming reminders for a user",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "hours_ahead": {"type": "integer", "description": "Look ahead this many hours (default 24)"}
                },
                "required": ["user_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_reminder",
            "description": "Mark a reminder as completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID of the reminder to complete"}
                },
                "required": ["reminder_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "Cancel an upcoming reminder. Pass reminder_id if known, otherwise pass title_query (a few words from the reminder title) and we'll find it. Use this when the user says 'cancel', 'scratch that', 'never mind the X reminder', etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "Optional ID — only if you know it from a prior get_upcoming_reminders call"},
                    "title_query": {"type": "string", "description": "Words from the reminder title to search for, e.g. 'dentist' or 'call mom'"},
                    "user_name": {"type": "string", "description": "Optional — restrict the search to one user (Alex, Stella, Emmy, Athena, Vilda)"}
                }
            }
        }
    },

    # ===== Enhanced Tools - Task Management =====
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task or to-do item",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "title": {"type": "string", "description": "Task title"},
                    "description": {"type": "string", "description": "Optional detailed description"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Task priority"},
                    "due_date": {"type": "string", "description": "Due date in natural language or ISO format"},
                    "category": {"type": "string", "description": "Task category (work, personal, shopping, etc.)"}
                },
                "required": ["user_name", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_tasks",
            "description": "Get tasks for a user",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "completed"], "description": "Filter by status"}
                },
                "required": ["user_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"}
                },
                "required": ["task_id"]
            }
        }
    },

    # ===== Enhanced Tools - Notes =====
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Save a note or memo",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "description": "Note category"}
                },
                "required": ["user_name", "title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search through saved notes",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string"},
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["user_name", "query"]
            }
        }
    },

    # ===== Enhanced Tools - Timers =====
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "Set a countdown timer",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration_minutes": {"type": "integer", "description": "Timer duration in minutes"},
                    "label": {"type": "string", "description": "Timer name/label"}
                },
                "required": ["duration_minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_timers",
            "description": "Check status of all active timers",
            "parameters": {"type": "object", "properties": {}}
        }
    },

    # ===== Enhanced Tools - System Control =====
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get computer system information (CPU, memory, disk usage)",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Capture a screenshot of the screen",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Optional filename for the screenshot"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "launch_application",
            "description": "Launch an application (browser, calculator, notepad, terminal, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "Application name (chrome, firefox, calculator, notepad, terminal, vscode, spotify)"}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set system volume level",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer", "description": "Volume level 0-100"}
                },
                "required": ["level"]
            }
        }
    },

    # ===== Enhanced Tools - File Operations =====
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Directory path"},
                    "pattern": {"type": "string", "description": "File pattern like *.pdf or *.txt"},
                    "recursive": {"type": "boolean", "description": "Search subdirectories"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a text file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Path to the file"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_info",
            "description": "Get detailed information about a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string"}
                },
                "required": ["filepath"]
            }
        }
    },

    # ===== Enhanced Tools - Educational & Storytelling =====
    {
        "type": "function",
        "function": {
            "name": "story_prompt",
            "description": "Generate an age-appropriate story prompt for a child (Emmy age 10, Athena age 8, or Vilda age 5)",
            "parameters": {
                "type": "object",
                "properties": {
                    "child_name": {"type": "string", "enum": ["Emmy", "Athena", "Vilda"], "description": "Child's name"},
                    "theme": {"type": "string", "description": "Story theme (animals, adventure, magic, etc.)"},
                    "moral": {"type": "string", "description": "Moral or lesson to teach"},
                    "length": {"type": "string", "enum": ["short", "medium", "long"]}
                },
                "required": ["child_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "educational_activity",
            "description": "Suggest an age-appropriate educational activity",
            "parameters": {
                "type": "object",
                "properties": {
                    "child_name": {"type": "string", "enum": ["Emmy", "Athena", "Vilda"]},
                    "subject": {"type": "string", "enum": ["math", "science", "reading", "art", "writing"]}
                },
                "required": ["child_name", "subject"]
            }
        }
    },

    # ===== Enhanced Tools - Location & Time =====
    {
        "type": "function",
        "function": {
            "name": "get_local_time",
            "description": "Get current local time and date",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_sunrise_sunset",
            "description": "Get sunrise and sunset times for today",
            "parameters": {"type": "object", "properties": {}}
        }
    },

    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "START playing new music. USE THIS when user wants to: play a song, play an artist, 'put on some music'. DO NOT USE for: pausing, skipping, or volume control (use control_music for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Song name, artist, or search query (e.g., 'Bohemian Rhapsody', 'Taylor Swift Shake It Off', 'relaxing jazz')"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["play", "search"],
                        "description": "'play' to play the song, 'search' to just find information without playing",
                        "default": "play"
                    },
                    "service": {
                        "type": "string",
                        "enum": ["youtube_music", "amazon_music"],
                        "description": "Music service to use",
                        "default": "youtube_music"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_music",
            "description": "CONTROL current playback. USE THIS for: pause, resume, skip, next, previous, volume up/down, mute. Works system-wide. DO NOT USE for: playing new music (use play_music to start playing something).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["pause", "resume", "play_pause", "next", "previous", "volume_up", "volume_down", "mute"],
                        "description": "Control action: 'pause' or 'resume' (toggle play/pause), 'next' (skip forward), 'previous' (skip back), 'volume_up', 'volume_down', 'mute'"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "music_visualizer",
            "description": "Start LIGHT SHOW synced to music. USE THIS when user wants: light show, lights to dance, party lights, sync lights with music. DO NOT USE for: regular light control like turning on/off or setting color (use control_lights for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "stop"],
                        "description": "'start' to begin visualizer, 'stop' to end it"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "How long to run the visualizer in seconds (default: 300 = 5 minutes)",
                        "default": 300
                    },
                    "style": {
                        "type": "string",
                        "enum": ["party", "chill", "pulse"],
                        "description": "Visualizer style: 'party' (fast colorful), 'chill' (slow smooth), 'pulse' (rhythmic)",
                        "default": "party"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Search USER'S UPLOADED documents (PDFs, Word docs, text files). USE THIS when user asks about: 'my documents', 'my files', 'my contract', 'what does my document say', 'search my files'. DO NOT USE for: internet searches or general knowledge (use web_search for those).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant information in documents"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 3)",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "control_lights",
            "description": "Control Philips Hue lights. USE THIS for: turn on/off, change brightness, set color, set mood/scene (sunset, relax, etc). DO NOT USE for: music-synced light shows (use music_visualizer for 'light show' or 'lights dance').",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "brightness", "color", "mood", "status"],
                        "description": "Action: 'on', 'off', 'brightness', 'color', 'mood' (apply atmospheric scene), 'status'"
                    },
                    "light_name": {
                        "type": "string",
                        "description": "Specific light name (optional, controls all if empty)"
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Brightness 0-100 (for brightness action)"
                    },
                    "color": {
                        "type": "string",
                        "description": "Color name: red, blue, green, yellow, orange, purple, pink, white, warm white, cool white"
                    },
                    "mood": {
                        "type": "string",
                        "description": "Mood/scene name: moonlight, sunset, ocean, forest, romance, party, focus, relax, energize, movie, fireplace, arctic, sunrise, galaxy, tropical"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather and forecast",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"}
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the INTERNET for external information. USE THIS for: current events, news, general knowledge queries, 'search for X', 'google X', 'latest news about X'. DO NOT USE for: user's personal documents (use search_documents for 'my documents', 'my files', 'my contract').",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_javascript",
            "description": "Execute JavaScript code",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript code"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_document",
            "description": "Create and save a new document (text, markdown, or code file) to the documents folder. The user can then download it from the web interface at http://127.0.0.1:5000/documents",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the file to create (e.g., 'report.txt', 'notes.md', 'recipe.txt')"
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content to write to the file"
                    },
                    "file_type": {
                        "type": "string",
                        "enum": ["txt", "md", "json", "csv", "html"],
                        "description": "File type (default: txt). Options: txt (plain text), md (markdown), json, csv, html",
                        "default": "txt"
                    }
                },
                "required": ["filename", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_gmail",
            "description": "CHECK/READ emails from inbox. USE THIS when user wants to: check email, read inbox, show messages, see unread emails, find specific emails. DO NOT USE for: sending new emails (use send_gmail) or replying to emails (use reply_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query (e.g., 'from:john@example.com', 'subject:meeting', 'is:unread'). Leave empty to get recent emails."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of emails to return (default: 10)",
                        "default": 10
                    },
                    "include_body": {
                        "type": "boolean",
                        "description": "Whether to include full email body (default: true)",
                        "default": True
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_gmail",
            "description": "SEND/COMPOSE a NEW email. USE THIS when user wants to: send email to someone, compose new message, email an address. REQUIRES: recipient email address (extract from user message - look for name@domain.com format). DO NOT USE for: checking inbox (use read_gmail) or replying to existing emails (use reply_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text"
                    },
                    "cc": {
                        "type": "string",
                        "description": "Optional CC email addresses (comma-separated)"
                    },
                    "bcc": {
                        "type": "string",
                        "description": "Optional BCC email addresses (comma-separated)"
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "Optional list of filenames to attach from documents folder. Example: ['report.pdf', 'data.xlsx']"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reply_gmail",
            "description": "REPLY to an EXISTING email. USE THIS when user wants to: reply to, respond to, or answer existing emails. IMPORTANT: For fanmail replies, FIRST use read_gmail to see the email content, THEN use this to reply with a contextual response. DO NOT USE for: checking inbox (use read_gmail) or sending new emails (use send_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find emails to reply to (e.g., 'subject:Fanmail', 'from:john@example.com is:unread'). Required to find which emails to reply to."
                    },
                    "reply_body": {
                        "type": "string",
                        "description": "The reply message body text. Should be contextual and personalized based on the original email content."
                    },
                    "reply_all": {
                        "type": "boolean",
                        "description": "If true, reply to all emails matching the query. If false, only reply to the first match. Default: false",
                        "default": False
                    },
                    "max_replies": {
                        "type": "integer",
                        "description": "Maximum number of emails to reply to (default: 10, max: 50)",
                        "default": 10
                    }
                },
                "required": ["query", "reply_body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_reply_emails",
            "description": "AUTONOMOUSLY scan Blue's own gmail inbox (alevantresearch@gmail.com) for personal emails and reply to every one. Anything that arrives there is by definition written to Blue. The tool skips no-reply senders, mailing lists, Promotions/Social/Updates/Forums categories, and Alex's own addresses. Each reply is BCC'd to Alex (alevant1905@gmail.com) so he has an audit copy. Use this when the user says things like 'check your email and reply', 'see if anyone wrote to you', 'answer your messages', 'handle your inbox'. DO NOT use this for: sending a brand-new email (use send_gmail), replying to one specific known email by query (use reply_gmail), or just reading the inbox (use read_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_hours": {
                        "type": "integer",
                        "description": "How far back to scan, in hours (default 24, max 168).",
                        "default": 24
                    },
                    "max_replies": {
                        "type": "integer",
                        "description": "Maximum number of replies to send this run (default 5, max 20).",
                        "default": 5
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, list which emails would be replied to and preview the drafts without sending. Default false.",
                        "default": False
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "View and analyze a SPECIFIC image file when user EXPLICITLY asks to see/view/look at it. ONLY use this when user directly requests to view an image (e.g., 'show me photo.jpg', 'look at the screenshot', 'what's in this image'). DO NOT use this just because an image filename appears in a document list - only use when user specifically wants to view the image content itself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Name of the image file to view (e.g., 'photo.jpg', 'screenshot.png'). If not provided, will search for images by query."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query to find images if filename not provided (e.g., 'family photo', 'diagram', 'screenshot')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "capture_camera",
            "description": "Capture a live camera view of your current surroundings. ONLY use this when user EXPLICITLY asks about what you see RIGHT NOW (e.g., 'what do you see?', 'look at me', 'what's in front of you?'). DO NOT use this for general conversation, document queries, or when user doesn't specifically ask about your current visual surroundings. This tool is for live visual perception, not for general questions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_visual_memory",
            "description": "Recall what you have seen before. Use when user asks about past visual experiences like 'what did you see earlier?', 'who was here before?', 'what's changed?', 'what happened today?'. Returns your visual memory timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional search query to filter memories (e.g., 'kitchen', 'Emmy', 'morning')"
                    },
                    "hours": {
                        "type": "integer",
                        "description": "How many hours back to look (default: 24)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_person",
            "description": "Learn and remember information about a person you see. Use this when the user tells you who someone is or provides information about a person. This helps you recognize them in the future.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The person's name"
                    },
                    "appearance": {
                        "type": "string",
                        "description": "Description of how they typically look (e.g., 'woman with long brown hair', 'man with beard and glasses')"
                    },
                    "relationship": {
                        "type": "string",
                        "description": "Their relationship to the household (e.g., 'family member', 'friend', 'neighbor')"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Any additional context or information about this person"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remember_place",
            "description": "Learn and remember information about a location or room you see. Use this when the user tells you about a place or provides context about a location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the place (e.g., 'Alex's Office', 'Living Room', 'Kitchen')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Description of this place and its purpose"
                    },
                    "typical_contents": {
                        "type": "string",
                        "description": "What is typically found in this location"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Any additional context about this place"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "who_do_i_know",
            "description": "List all the people you know and can recognize. Use this when asked who you know or to see your visual memory of people.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_with_chat_theory",
            "description": "Analyze a topic through Cultural-Historical Activity Theory (CHAT) lens. Use this when Alex asks to apply CHAT framework to something, or for academic analysis of technology/education topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic to analyze"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context about the situation"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_lecture",
            "description": "Generate a lecture outline for teaching. Use when Alex needs to prepare for class or wants help structuring a lecture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The lecture topic"
                    },
                    "duration": {
                        "type": "integer",
                        "description": "Lecture duration in minutes (default 50)"
                    },
                    "course": {
                        "type": "string",
                        "description": "Course name or context"
                    },
                    "level": {
                        "type": "string",
                        "description": "Student level: undergraduate, graduate, etc."
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "discussion_questions",
            "description": "Generate discussion questions for a reading or topic. Use when Alex is preparing for class discussion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reading": {
                        "type": "string",
                        "description": "The reading or text to generate questions about"
                    },
                    "topic": {
                        "type": "string",
                        "description": "The topic or theme"
                    }
                },
                "required": ["reading", "topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_student_questions",
            "description": "Simulate likely student questions and provide teaching strategies. Use when Alex is preparing to teach a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The topic being taught"
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context about the lesson"
                    }
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_proactive_suggestions",
            "description": "Check if there are any helpful proactive suggestions based on patterns and context. Use when checking in or when appropriate time has passed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# Filter out tools that require unavailable modules
if not ENHANCED_TOOLS_AVAILABLE:
    # Remove file operation tools that won't work
    TOOLS = [tool for tool in TOOLS if tool["function"]["name"] not in [
        "list_files", "read_file", "write_file", "get_file_info",
        "create_reminder", "get_upcoming_reminders", "cancel_reminder",
        "check_timers", "get_system_info", "take_screenshot",
        "launch_application", "set_volume", "story_prompt", "educational_activity",
        "get_local_time", "get_sunrise_sunset"
    ]]
    print(f"[INFO] Filtered {len([t for t in TOOLS if t['function']['name'] in ['list_files', 'read_file']])} unavailable enhanced tools")


# ===== DOCUMENT MANAGEMENT FUNCTIONS =====

# ================================================================================
# LIBRARY FOLDERS — hierarchical organization under DOCUMENTS_FOLDER
# ================================================================================
# Documents live in a folder tree (e.g. "Publications", "Courses/CS240",
# "Academic Texts/Sohn-Rethel"). A document's `folder` is its POSIX-style
# path relative to DOCUMENTS_FOLDER; "" means the library root. These helpers
# keep folder handling safe (no traversal outside DOCUMENTS_FOLDER) and in
# one place so the index, RAG, and GUI all agree on what a folder is.


def _safe_folder_segment(seg: str) -> str:
    """Sanitize a single folder name: drop path/illegal chars and leading or
    trailing dots (which would enable traversal), keep spaces and normal
    punctuation so 'Academic Texts' or 'Sohn-Rethel' survive intact."""
    seg = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', (seg or '')).strip().strip('.')
    return seg.strip()


def _safe_rel_folder(folder: str) -> str:
    """Normalize a (possibly user-supplied) relative folder path to a safe
    POSIX-style rel path under DOCUMENTS_FOLDER. Returns '' for the root and
    silently drops any '.'/'..' segments."""
    if not folder:
        return ""
    raw = str(folder).replace("\\", "/").strip().strip("/")
    parts = []
    for seg in raw.split("/"):
        s = _safe_folder_segment(seg)
        if s and s not in (".", ".."):
            parts.append(s)
    return "/".join(parts)


def _abs_library_path(rel_folder: str) -> str:
    """Absolute path for a library folder, guaranteed to stay under
    DOCUMENTS_FOLDER (defense in depth against traversal)."""
    base = os.path.abspath(DOCUMENTS_FOLDER)
    rel = _safe_rel_folder(rel_folder)
    full = os.path.abspath(os.path.join(base, *rel.split("/"))) if rel else base
    try:
        if os.path.commonpath([base, full]) != base:
            return base
    except ValueError:
        return base
    return full


def _folder_of_filepath(filepath: str) -> str:
    """The library folder (POSIX rel path, '' for root) a file sits in. Files
    outside DOCUMENTS_FOLDER (e.g. image uploads in UPLOAD_FOLDER) report ''."""
    try:
        base = os.path.abspath(DOCUMENTS_FOLDER)
        ap = os.path.abspath(filepath)
        if os.path.commonpath([base, ap]) != base:
            return ""
        rel = os.path.relpath(os.path.dirname(ap), base)
        if rel in (".", ""):
            return ""
        return rel.replace("\\", "/")
    except Exception:
        return ""


def list_library_folders() -> List[str]:
    """Every folder under DOCUMENTS_FOLDER as sorted POSIX rel paths (excludes
    the root ''). Hidden dirs are skipped."""
    base = os.path.abspath(DOCUMENTS_FOLDER)
    out: List[str] = []
    if not os.path.isdir(base):
        return out
    for root, dirs, _files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for d in dirs:
            rel = os.path.relpath(os.path.join(root, d), base).replace("\\", "/")
            out.append(rel)
    return sorted(out)


def list_subfolders(rel_folder: str) -> List[str]:
    """Immediate child folder names of the given library folder."""
    full = _abs_library_path(rel_folder)
    if not os.path.isdir(full):
        return []
    try:
        return sorted(
            d for d in os.listdir(full)
            if os.path.isdir(os.path.join(full, d)) and not d.startswith('.')
        )
    except Exception:
        return []


def create_library_folder(rel_folder: str) -> dict:
    """Create a folder (and any missing parents) under DOCUMENTS_FOLDER."""
    rel = _safe_rel_folder(rel_folder)
    if not rel:
        return {"success": False, "error": "Invalid or empty folder name."}
    try:
        os.makedirs(_abs_library_path(rel), exist_ok=True)
        return {"success": True, "folder": rel}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _folders_under(prefix: str) -> List[str]:
    """A folder plus all its descendants (POSIX rel paths). Used to scope a
    search to an expertise area and everything filed beneath it."""
    pfx = _safe_rel_folder(prefix)
    if not pfx:
        return []
    result = [pfx]
    needle = pfx + "/"
    for f in list_library_folders():
        if f.startswith(needle):
            result.append(f)
    return result


# The owner's name, used to recognize the folder that holds HIS publications
# when he says "my published work" / "my articles". Override via env if the
# folder is named differently.
BLUE_OWNER_NAME = os.environ.get("BLUE_OWNER_NAME", "Alex Levant")

# Phrases that mean "draw on my own published writing".
_OWN_WORK_PHRASES = (
    "my published work", "my publications", "my published", "my articles",
    "my article", "my papers", "my paper", "my writing", "my own work",
    "my own writing", "my research", "my work", "my book", "my chapter",
    "my essays", "my essay", "published work", "my scholarship",
)


def _infer_expertise_folders(query: str) -> List[str]:
    """Map a request to the library folder(s) it should be answered from, or
    [] for 'search the whole library'. Two cues:

      • "my published work / my articles / my publications …" → the folder
        holding the owner's own writing (matched by publications-style names
        or the owner's name, e.g. an "Alex Levant" folder).
      • An explicit folder name appearing in the request → that folder.

    Returns each matched folder plus its descendants, deduped.
    """
    q = (query or "").lower()
    folders = list_library_folders()
    if not folders:
        return []

    targets = set()
    owner_tokens = [t for t in re.findall(r"[a-z]+", BLUE_OWNER_NAME.lower()) if len(t) > 2]

    if any(p in q for p in _OWN_WORK_PHRASES):
        for f in folders:
            fl = f.lower()
            is_pub = any(k in fl for k in ("publication", "published", "papers", "articles", "writing"))
            is_owner_named = bool(owner_tokens) and all(t in fl for t in owner_tokens)
            if is_pub or is_owner_named:
                targets.update(_folders_under(f))

    # Explicit folder-name mention (match on the leaf name as a whole word).
    for f in folders:
        leaf = f.split("/")[-1].lower()
        if len(leaf) >= 4 and re.search(r"\b" + re.escape(leaf) + r"\b", q):
            targets.update(_folders_under(f))

    return sorted(targets)


def load_document_index() -> Dict:
    """Load the document index from disk. Repairs corrupt files in place.

    Backfills a `folder` field (computed from each file's location) on any
    entry that predates folder support, so the GUI and search always see one.
    """
    if os.path.exists(DOCUMENT_INDEX_FILE):
        try:
            with open(DOCUMENT_INDEX_FILE, 'r') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('documents'), list):
                for d in data['documents']:
                    if isinstance(d, dict) and 'folder' not in d:
                        d['folder'] = _folder_of_filepath(d.get('filepath', ''))
                return data
            print(f"[INDEX] {DOCUMENT_INDEX_FILE} has unexpected shape; resetting.")
        except Exception as e:
            print(f"[INDEX] {DOCUMENT_INDEX_FILE} is corrupt ({e}); resetting to empty.")
        try:
            with open(DOCUMENT_INDEX_FILE, 'w') as f:
                json.dump({"documents": []}, f, indent=2)
        except Exception as e:
            print(f"[INDEX] could not rewrite {DOCUMENT_INDEX_FILE}: {e}")
    return {"documents": []}


def save_document_index(index: Dict):
    """Save the document index to disk."""
    with open(DOCUMENT_INDEX_FILE, 'w') as f:
        json.dump(index, f, indent=2)


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_unique_path(directory: str, filename: str) -> str:
    """Ensure a unique file path by adding numbers if file already exists.

    Args:
        directory: Directory where file will be saved
        filename: Original filename

    Returns:
        Unique file path
    """
    base_path = os.path.join(directory, secure_filename(filename))

    # If file doesn't exist, return as-is
    if not os.path.exists(base_path):
        return base_path

    # File exists, add number suffix
    name, ext = os.path.splitext(filename)
    counter = 1

    while True:
        new_filename = f"{name}_{counter}{ext}"
        new_path = os.path.join(directory, secure_filename(new_filename))

        if not os.path.exists(new_path):
            return new_path

        counter += 1

        # Safety check to prevent infinite loop
        if counter > 9999:
            # Use timestamp as last resort
            import time
            timestamp = int(time.time())
            new_filename = f"{name}_{timestamp}{ext}"
            return os.path.join(directory, secure_filename(new_filename))


def get_file_hash(filepath):
    """Get MD5 hash of file for deduplication."""
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def _is_camera_capture_filename(filename: str) -> bool:
    """Camera frames use a fixed prefix; treat them as transient."""
    return filename.startswith('camera_') or filename.startswith('camera_NEW_')


def cleanup_document_index() -> dict:
    """Remove stale and noisy entries from the document index.

    Drops:
      - entries flagged camera_capture (or whose filename matches the
        camera_*/camera_NEW_* prefix); these should never have been indexed
        as documents
      - entries whose file no longer exists on disk
      - duplicate entries that share an MD5 hash (keeps the first occurrence)

    Returns a small report dict for logging.
    """
    index = load_document_index()
    documents = index.get('documents', [])
    seen_hashes = set()
    kept, dropped_missing, dropped_camera, dropped_dup = [], 0, 0, 0

    for doc in documents:
        filename = doc.get('filename', '')
        filepath = doc.get('filepath', '')
        file_hash = doc.get('hash')

        if doc.get('camera_capture') or _is_camera_capture_filename(filename):
            dropped_camera += 1
            continue
        if filepath and not os.path.exists(filepath):
            dropped_missing += 1
            continue
        if file_hash and file_hash in seen_hashes:
            dropped_dup += 1
            continue
        if file_hash:
            seen_hashes.add(file_hash)
        kept.append(doc)

    if dropped_missing or dropped_camera or dropped_dup:
        index['documents'] = kept
        save_document_index(index)

    return {
        'kept': len(kept),
        'dropped_missing': dropped_missing,
        'dropped_camera': dropped_camera,
        'dropped_duplicate': dropped_dup,
    }


def rescan_documents_folder() -> dict:
    """Add files present in DOCUMENTS_FOLDER but missing from the index.

    Useful after a manual file drop or when the index has been wiped. Skips
    camera-capture files and unsupported extensions. Files added here are
    also pushed into the ChromaDB index when available.
    """
    import datetime as _dt

    index = load_document_index()
    documents = index.get('documents', [])
    indexed_paths = {os.path.normcase(os.path.abspath(d.get('filepath', ''))) for d in documents}
    indexed_hashes = {d.get('hash') for d in documents if d.get('hash')}

    added = 0
    skipped = 0
    if not os.path.isdir(DOCUMENTS_FOLDER):
        return {'added': 0, 'skipped': 0}

    # Walk the whole folder tree so files in subfolders (Publications/,
    # Courses/CS240/, …) get picked up, each tagged with its folder.
    for root, dirs, files in os.walk(DOCUMENTS_FOLDER):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for entry in files:
            full = os.path.join(root, entry)
            if not os.path.isfile(full):
                continue
            if _is_camera_capture_filename(entry):
                continue
            if not allowed_file(entry):
                skipped += 1
                continue
            if os.path.normcase(os.path.abspath(full)) in indexed_paths:
                continue

            try:
                file_hash = get_file_hash(full)
            except Exception:
                skipped += 1
                continue
            if file_hash in indexed_hashes:
                continue

            folder = _folder_of_filepath(full)
            size_mb = os.path.getsize(full) / (1024 * 1024)
            print(f"   [INDEX] extracting text: {entry} ({size_mb:.1f} MB) [{folder or 'root'}]", flush=True)
            text_content = extract_text_from_file(full)
            text_preview = text_content[:500] if not text_content.startswith('Error') else ''

            # Best-effort push into ChromaDB so the new file is searchable.
            try:
                print(f"   [INDEX] embedding into ChromaDB: {entry}", flush=True)
                from blue.tools.rag import index_document as _idx
                _idx(full, entry, doc_id=file_hash, text=text_content, folder=folder)
                print(f"   [INDEX] done: {entry}", flush=True)
            except Exception as e:
                print(f"   [INDEX] ChromaDB push failed for {entry}: {e}", flush=True)

            documents.append({
                'filename': entry,
                'filepath': str(full),
                'folder': folder,
                'size': os.path.getsize(full),
                'hash': file_hash,
                'uploaded_at': _dt.datetime.fromtimestamp(os.path.getmtime(full)).strftime('%Y-%m-%d %H:%M'),
                'text_preview': text_preview,
                'indexed_in_rag': True,
            })
            indexed_hashes.add(file_hash)
            added += 1

    if added:
        index['documents'] = documents
        save_document_index(index)

    return {'added': added, 'skipped': skipped}


def register_uploaded_file(filepath: str, filename: str) -> dict:
    """Common post-save bookkeeping for any upload endpoint.

    - Hash-dedups against the existing index (deletes the new copy if a
      duplicate is found and returns the existing filename).
    - Extracts a text preview.
    - Pushes the document into ChromaDB if available (tagged with its folder).
    - Appends to document_index.json with the folder it lives in.
    """
    import datetime as _dt

    file_hash = get_file_hash(filepath)
    folder = _folder_of_filepath(filepath)
    index = load_document_index()

    for existing in index.get('documents', []):
        if existing.get('hash') == file_hash:
            try:
                if os.path.abspath(existing.get('filepath', '')) != os.path.abspath(filepath):
                    os.remove(filepath)
            except OSError:
                pass
            return {
                'filename': existing.get('filename'),
                'duplicate': True,
                'existing_filename': existing.get('filename'),
            }

    text_content = extract_text_from_file(filepath)
    text_preview = text_content[:500] if not text_content.startswith('Error') else ''

    indexed_in_rag = False
    try:
        from blue.tools.rag import index_document as _idx
        result = _idx(filepath, filename, doc_id=file_hash, folder=folder)
        indexed_in_rag = bool(result.get('success'))
    except Exception:
        pass

    index.setdefault('documents', []).append({
        'filename': filename,
        'filepath': str(filepath),
        'folder': folder,
        'size': os.path.getsize(filepath),
        'hash': file_hash,
        'uploaded_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'text_preview': text_preview,
        'indexed_in_rag': indexed_in_rag,
    })
    save_document_index(index)
    return {'filename': filename, 'duplicate': False, 'indexed_in_rag': indexed_in_rag, 'folder': folder}


def remove_document_from_index(filepath: str) -> bool:
    """Remove a deleted/moved file from the document index AND ChromaDB."""
    try:
        abs_path = os.path.abspath(filepath)
    except Exception:
        return False

    index = load_document_index()
    docs = index.get('documents', [])
    keep, removed_hashes, removed_names = [], [], []
    for d in docs:
        try:
            if os.path.abspath(d.get('filepath', '')) == abs_path:
                if d.get('hash'):
                    removed_hashes.append(d['hash'])
                if d.get('filename'):
                    removed_names.append(d['filename'])
                continue
        except Exception:
            pass
        keep.append(d)

    if not removed_hashes and not removed_names:
        return False

    index['documents'] = keep
    save_document_index(index)

    # Remove the corresponding chunks from ChromaDB.
    try:
        from blue.tools.rag import remove_document
        for h in removed_hashes:
            remove_document(h)
    except Exception:
        pass

    print(f"[WATCHER] Removed from index: {', '.join(removed_names)}")
    return True


# ---- Filesystem watcher for auto-indexing the documents folder ----
_DOCUMENT_WATCHER = None


def start_document_watcher():
    """Watch DOCUMENTS_FOLDER and auto-index files as they appear.

    Uses the `watchdog` library if available. Each create/move event triggers
    a debounced indexer (sleeps briefly so the OS finishes writing the file
    before we hash and chunk it). Deletes are reflected immediately by
    removing the entry from document_index.json and ChromaDB.

    Gracefully no-ops if watchdog isn't installed; the startup rescan is
    still a fallback for users without it.
    """
    global _DOCUMENT_WATCHER
    if _DOCUMENT_WATCHER is not None:
        return _DOCUMENT_WATCHER

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[WATCHER] watchdog not installed — auto-indexing disabled.")
        print("[WATCHER]   Install with: pip install watchdog")
        return None

    import threading
    import time

    def _index_after_settle(filepath: str, debounce_secs: float = 1.5):
        # Wait for the file to be fully written (Windows file locks can hold
        # past the on_created event by hundreds of ms).
        time.sleep(debounce_secs)
        try:
            if not os.path.isfile(filepath):
                return
            filename = os.path.basename(filepath)
            if _is_camera_capture_filename(filename):
                return
            if not allowed_file(filename):
                return
            # Wait until the file size stops changing (rough copy-completion
            # check). Up to a few seconds for large PDFs.
            last_size = -1
            for _ in range(10):
                try:
                    cur = os.path.getsize(filepath)
                except OSError:
                    return
                if cur == last_size and cur > 0:
                    break
                last_size = cur
                time.sleep(0.4)
            result = register_uploaded_file(filepath, filename)
            if result.get('duplicate'):
                print(f"[WATCHER] {filename}: duplicate, skipped")
            else:
                rag_marker = " (ChromaDB indexed)" if result.get('indexed_in_rag') else ""
                print(f"[WATCHER] Auto-indexed: {filename}{rag_marker}")
        except Exception as e:
            print(f"[WATCHER] Error auto-indexing {filepath}: {e}")

    class _DocChangeHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            threading.Thread(
                target=_index_after_settle,
                args=(event.src_path,),
                daemon=True,
            ).start()

        def on_moved(self, event):
            if event.is_directory:
                return
            # The destination is the new file location.
            threading.Thread(
                target=_index_after_settle,
                args=(event.dest_path,),
                daemon=True,
            ).start()
            # Also update the index for the old path if it was tracked.
            try:
                remove_document_from_index(event.src_path)
            except Exception:
                pass

        def on_deleted(self, event):
            if event.is_directory:
                return
            try:
                remove_document_from_index(event.src_path)
            except Exception:
                pass

    try:
        os.makedirs(DOCUMENTS_FOLDER, exist_ok=True)
        observer = Observer()
        observer.schedule(_DocChangeHandler(), DOCUMENTS_FOLDER, recursive=True)
        observer.daemon = True
        observer.start()
        _DOCUMENT_WATCHER = observer
        print(f"[WATCHER] Watching {DOCUMENTS_FOLDER} — drop files there to auto-index")
        return observer
    except Exception as e:
        print(f"[WATCHER] Failed to start: {e}")
        return None


def encode_image_to_base64(filepath: str) -> Optional[Dict[str, Any]]:
    """Encode an image file to base64 for vision model viewing.

    Returns a dict with image data suitable for vision models, or None if error.
    Format: {
        "type": "image_url",
        "image_url": {
            "url": "data:image/jpeg;base64,..."
        }
    }
    """
    ext = filepath.rsplit('.', 1)[1].lower()
    if ext not in ['png', 'jpg', 'jpeg', 'tiff', 'bmp', 'gif', 'webp']:
        return None

    try:
        import base64
        with open(filepath, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Map extensions to MIME types
        mime_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'bmp': 'image/bmp',
            'tiff': 'image/tiff'
        }

        mime_type = mime_types.get(ext, 'image/jpeg')

        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{mime_type};base64,{image_data}"
            }
        }
    except Exception as e:
        print(f"   [ERROR] Failed to encode image {filepath}: {e}")
        return None


def extract_text_from_file(filepath: str) -> str:
    """Extract text from various file types. For images, returns metadata since vision model will view them directly."""
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''

    if ext in ('txt', 'md'):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    elif ext == 'pdf':
        # Prefer pypdf (the maintained successor); fall back to PyPDF2.
        try:
            try:
                from pypdf import PdfReader
            except ImportError:
                from PyPDF2 import PdfReader
            text = []
            with open(filepath, 'rb') as f:
                for page in PdfReader(f).pages:
                    text.append(page.extract_text() or '')
            return '\n'.join(text)
        except ImportError:
            return "Error: pypdf not installed. Install with: pip install pypdf"
        except Exception as e:
            return f"Error extracting PDF: {str(e)}"

    elif ext in ('doc', 'docx'):
        try:
            import docx
            doc = docx.Document(filepath)
            return '\n'.join(paragraph.text for paragraph in doc.paragraphs)
        except ImportError:
            return "Error: python-docx not installed. Install with: pip install python-docx"
        except Exception as e:
            return f"Error extracting Word doc: {str(e)}"

    elif ext in ('csv', 'tsv'):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    elif ext in ('json', 'xml', 'html', 'htm'):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read()
        if ext in ('html', 'htm'):
            try:
                from bs4 import BeautifulSoup
                return BeautifulSoup(raw, 'html.parser').get_text(separator='\n')
            except ImportError:
                return raw
        return raw

    elif ext == 'rtf':
        try:
            from striprtf.striprtf import rtf_to_text
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                return rtf_to_text(f.read())
        except ImportError:
            import re
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                raw = f.read()
            return re.sub(r'\\[a-z]+\d* ?|[{}]', '', raw)

    elif ext == 'xlsx':
        try:
            from openpyxl import load_workbook
            wb = load_workbook(filepath, read_only=True, data_only=True)
            lines = []
            for ws in wb.worksheets:
                lines.append(f"# Sheet: {ws.title}")
                for row in ws.iter_rows(values_only=True):
                    cells = ['' if v is None else str(v) for v in row]
                    if any(cells):
                        lines.append('\t'.join(cells))
            return '\n'.join(lines)
        except ImportError:
            return "Error: openpyxl not installed. Install with: pip install openpyxl"
        except Exception as e:
            return f"Error extracting xlsx: {str(e)}"

    elif ext == 'pptx':
        try:
            from pptx import Presentation
            lines = []
            for i, slide in enumerate(Presentation(filepath).slides, 1):
                lines.append(f"# Slide {i}")
                for shape in slide.shapes:
                    if hasattr(shape, 'text') and shape.text:
                        lines.append(shape.text)
            return '\n'.join(lines)
        except ImportError:
            return "Error: python-pptx not installed. Install with: pip install python-pptx"
        except Exception as e:
            return f"Error extracting pptx: {str(e)}"

    elif ext in ('png', 'jpg', 'jpeg', 'tiff', 'bmp', 'gif', 'webp'):
        # Image file - store metadata for vision model to view directly
        try:
            from PIL import Image
            image = Image.open(filepath)
            width, height = image.size
            mode = image.mode
            file_size = os.path.getsize(filepath)

            return (f"[IMAGE FILE - Vision model will view directly]\n"
                    f"Dimensions: {width}x{height}\n"
                    f"Color mode: {mode}\n"
                    f"File size: {file_size} bytes\n"
                    f"Format: {ext.upper()}")
        except ImportError:
            return f"[IMAGE FILE] {os.path.basename(filepath)} - PIL required to read metadata"
        except Exception as e:
            return f"[IMAGE FILE] {os.path.basename(filepath)} - Error reading: {str(e)}"

    return f"Unsupported file type: .{ext}"


def _is_full_document_request(query: str) -> bool:
    """Check if the query is asking for a full document rather than a specific search."""
    query_lower = query.lower()
    # User is asking to read/see/look at a specific document, not searching for a topic
    full_doc_signals = [
        'whole', 'entire', 'full', 'complete', 'all of', 'read the',
        'tell me the story', 'read it', 'tell the story',
        'what is', 'what does', 'what it is', 'take a look', 'fresh look',
        'look at', 'summarize', 'summary', 'overview', 'about this document',
        'about that document', 'tell me about', 'describe',
    ]
    if any(phrase in query_lower for phrase in full_doc_signals):
        return True
    # If the query IS a filename (or very close to one), they want the full doc
    if '.' in query and any(query_lower.endswith(ext) for ext in ['.pdf', '.txt', '.md', '.docx', '.doc']):
        return True
    return False


def _is_document_list_request(query: str) -> bool:
    """True when the user wants an INVENTORY of the library (what/which/how
    many documents or files, what's in the library) rather than a semantic
    search. These must route to the local index lister — ChromaDB would
    semantic-search the literal question and return irrelevant chunks (or
    nothing), which is why 'what documents are in your library' came back
    empty by email."""
    q = f" {query.lower().strip()} "
    list_phrases = (
        "what documents", "what files", "which documents", "which files",
        "list documents", "list files", "list my documents", "list my files",
        "list all", "show documents", "show files", "show me my documents",
        "show me my files", "show my documents", "show my files",
        "how many documents", "how many files", "count documents",
        "count files", "documents do you have", "files do you have",
        "documents are in", "files are in", "in your library",
        "in my library", "what's in your library", "whats in your library",
        "what is in your library", "what do you have in your library",
    )
    return any(p in q for p in list_phrases)


def _is_expertise_query(query: str) -> bool:
    """True for queries that ask Blue to draw on his corpus expertise.

    Triggers multi-chunk retrieval (top-8 across multiple documents, up
    to 3 per doc) instead of the default top-3 deduped-by-document mode.
    Aimed at: 'what does the literature say about X', 'summarise the
    research on Y', 'according to my notes / papers / docs ...' style
    questions where richer cross-document coverage matters more than
    surgical precision.
    """
    q = query.lower()
    expertise_phrases = (
        # explicit corpus-of-knowledge framings
        "the literature", "research on", "research about", "papers on",
        "papers about", "according to my", "according to the", "based on my",
        "based on the", "my notes on", "my notes about", "my docs", "the docs",
        "in my documents", "from my documents", "from the documents",
        "the documents say", "what do my documents", "what does my research",
        # synthesis-style framings
        "what do we know about", "what do you know about", "everything you know about",
        "everything about", "summarise everything", "summarize everything",
        "what's known about", "whats known about",
        "across my", "across all", "compare what",
        # discipline / field hints — these almost always want corpus coverage
        " literature ", " corpus ", "the field of",
        # the owner's own body of work — "using my published work", "my
        # articles", etc. — wants broad coverage across several of his pieces,
        # not a single best-matching chunk.
        "my published work", "my publications", "my articles", "my papers",
        "my own work", "my writing", "my scholarship", "published work",
    )
    return any(p in f" {q} " for p in expertise_phrases)


def search_documents_rag(query: str, max_results: int = 3) -> str:
    """Search documents using local ChromaDB RAG first, then keyword fallback."""
    print(f"   [FIND] Searching documents for: '{query}'")

    # Inventory requests ("what documents are in your library", "list my
    # files") must be answered by enumerating the index, NOT by semantic
    # search — ChromaDB would match the literal question against chunk text
    # and return noise. Route straight to the local lister.
    if _is_document_list_request(query):
        print(f"   [LIST] Library inventory request — routing to local lister")
        return search_documents_local(query, max_results)

    is_expertise = _is_expertise_query(query)

    # Scope to an area of expertise when the request names one ("my published
    # work" → the publications folder, a folder name, …). [] = whole library.
    try:
        scope_folders = _infer_expertise_folders(query)
    except Exception:
        scope_folders = []
    if scope_folders:
        print(f"   [SCOPE] Restricting search to folders: {scope_folders}")

    # Expertise queries (e.g. "what does the literature say…") want
    # multi-chunk RAG, NOT a full-document dump. Check expertise *before*
    # the full-doc heuristic, since the latter trips on generic phrases
    # like "what does" / "tell me about" that legitimately appear in
    # corpus-style questions.
    if not is_expertise and _is_full_document_request(query):
        print(f"   [FULL-DOC] Full document request detected, using local search for full text")
        return search_documents_local(query, max_results)

    # --- 1. Try local ChromaDB RAG first ---
    try:
        from blue.tools.rag import (
            search as rag_search,
            search_expertise as rag_search_expertise,
            get_stats,
        )
        stats = get_stats()
        if stats.get('available') and stats.get('total_chunks', 0) > 0:
            scope = scope_folders or None
            if is_expertise:
                # Scoped to a folder (e.g. his publications), spread coverage
                # across MORE documents (lower per-doc cap, higher total) so a
                # synthesis draws on several pieces, not just the closest one.
                if scope:
                    results = rag_search_expertise(query, max_chunks=14, max_per_doc=2, folders=scope)
                else:
                    results = rag_search_expertise(query, max_chunks=8, max_per_doc=3)
                # If folder scoping was too tight and found nothing, retry wide.
                if not results and scope:
                    print("   [SCOPE] No scoped results; retrying across whole library")
                    results = rag_search_expertise(query, max_chunks=8, max_per_doc=3)
                print(f"   [EXPERTISE] Multi-chunk mode: {len(results)} chunk(s)")
            else:
                results = rag_search(query, max_results, folders=scope)
                if not results and scope:
                    print("   [SCOPE] No scoped results; retrying across whole library")
                    results = rag_search(query, max_results)
            if results:
                # In normal (non-expertise) mode, if all results come from one
                # document, fall through to local search for full text.
                unique_files = set(r['filename'] for r in results)
                if not is_expertise and len(unique_files) == 1:
                    print(f"   [SINGLE-DOC] All {len(results)} chunk(s) from same file, fetching full text")
                    return search_documents_local(query, max_results)

                formatted = []
                for i, r in enumerate(results, 1):
                    score_pct = f"{r['score']:.0%}"
                    chunk_idx = r.get('chunk_index')
                    total_chunks = r.get('total_chunks')
                    if chunk_idx is not None and total_chunks:
                        loc = f" chunk {int(chunk_idx) + 1}/{total_chunks}"
                    else:
                        loc = ""
                    content_preview = r['content'][:800]
                    # Citation tag the model can copy inline. Putting the
                    # filename in [brackets] near the start makes it easy
                    # for the model to weave into prose.
                    formatted.append(
                        f"[{i}] [{r['filename']}]{loc} (relevance: {score_pct})\n"
                        f"{content_preview}"
                    )
                header = (
                    "Here are the most relevant passages from your corpus. "
                    "Cite sources inline when you quote, like [filename.pdf]:"
                    if is_expertise else
                    "Here's what I found in your documents:"
                )
                print(f"   [OK] ChromaDB RAG returned {len(results)} result(s)")
                return f"{header}\n\n" + "\n\n".join(formatted)
            else:
                print(f"   [WARN] ChromaDB returned no results, trying next...")
    except ImportError:
        print("   [WARN] ChromaDB not available, trying keyword search...")
    except Exception as e:
        print(f"   [WARN] ChromaDB error: {e}")

    # --- 2. Fall back to local keyword search ---
    # The previous middle tier hit LM_STUDIO_RAG_URL/search, which no LM
    # Studio build actually exposes — every call timed out for 10 seconds
    # and fell through to keyword search anyway. Going straight to the
    # keyword path skips that wait without losing any working behavior.
    print(f"   [ITER] Falling back to local keyword search...")
    return search_documents_local(query, max_results)


def _search_documents_guarded(query: str, max_results: int = 3,
                              timeout: float = 15.0) -> str:
    """Run the RAG document search with a hard timeout.

    ChromaDB can stall indefinitely — a corrupt HNSW index or lock
    contention has no internal timeout — and with a single-threaded server
    that one stalled call freezes Blue completely and even blocks Ctrl+C.
    This runs the search on a worker thread; if it overruns, we abandon it
    and fall back to the index-only keyword search (which never touches
    ChromaDB), so a document query can never hang the assistant."""
    box: Dict[str, object] = {}

    def _run():
        try:
            box["result"] = search_documents_rag(query, max_results)
        except Exception as e:  # noqa: BLE001 — surface as fallback, never crash
            box["error"] = e

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        log.error(
            f"[DOCS] document search exceeded {timeout:.0f}s (ChromaDB stalled) "
            f"— falling back to index-only search. The RAG index likely needs a rebuild."
        )
        try:
            return search_documents_local(query, max_results)
        except Exception as e:
            log.error(f"[DOCS] index-only fallback also failed: {e}")
            return ("I can see your document library, but searching it is taking "
                    "too long right now — the search index may need a rebuild.")
    if "error" in box:
        log.error(f"[DOCS] document search errored: {box['error']}")
        try:
            return search_documents_local(query, max_results)
        except Exception:
            return "I had trouble searching your documents just now."
    return str(box.get("result", ""))


def search_documents_local(query: str, max_results: int = 3) -> str:
    """Fallback: Simple local search through document index. Returns JSON for images."""
    print(f"   [FOLDER] Using local document search...")
    index = load_document_index()
    documents = index.get("documents", [])

    print(f"   [DATA] Found {len(documents)} documents in local index")

    if not documents:
        print(f"   [WARN]  No documents uploaded yet!")
        return (
            "I don't have any documents to search through yet! "
            "You can upload documents at http://127.0.0.1:5000/documents - "
            "I can read PDFs, Word docs, text files, markdown, and images. "
            "Once you upload some documents, I'll be able to answer questions about them!"
        )

    query_lower = query.lower()
    matches = []

    # Special handling for document listing queries
    list_keywords = ["list documents", "what documents", "show documents", "all documents",
                     "summarize all", "list all", "show all",
                     "what files", "which documents", "which files", "list files",
                     "show files", "how many documents", "how many files",
                     "count documents", "count files", "in your library",
                     "in my library", "documents do you have", "files do you have"]
    is_list_query = any(kw in query_lower for kw in list_keywords)

    # Also treat very generic queries as list requests (e.g., just "documents" or "files")
    generic_queries = query_lower.strip() in ["documents", "document", "files", "file", "pdfs", "pdf"]

    if is_list_query or generic_queries or ("all" in query_lower and ("document" in query_lower or "summarize" in query_lower or "image" in query_lower)):
        print(f"   [LIST] Query asks for document list/count, listing them...")

        # Filter out camera images from document listings
        real_documents = [doc for doc in documents
                          if doc.get('doc_type') != 'camera'
                          and not doc['filename'].startswith('camera_')]

        doc_list = []
        for i, doc in enumerate(real_documents[:10], 1):
            preview = doc.get('text_preview', 'No preview available')[:200]
            doc_list.append(f"{i}. {doc['filename']}\n   Preview: {preview}...")

        summary = "\n\n".join(doc_list)
        if len(real_documents) > 10:
            summary += f"\n\n...and {len(real_documents) - 10} more documents."

        return f"I have {len(real_documents)} document(s) uploaded:\n\n{summary}"

    # Search through documents
    for doc in documents:
        relevance = 0
        filename_lower = doc['filename'].lower()

        # Check filename
        if query_lower in filename_lower:
            relevance += 3

        # Check cached text content
        text_content = doc.get('text_preview', '').lower()
        if query_lower in text_content:
            relevance += 5

        # Check individual query words
        for word in query_lower.split():
            if len(word) > 3:
                if word in filename_lower:
                    relevance += 1
                if word in text_content:
                    relevance += 2

        if relevance > 0:
            matches.append((doc, relevance))

    print(f"   [TARGET] Found {len(matches)} matching documents")

    if not matches:
        return (
            f"I couldn't find any documents matching '{query}'. "
            f"I have {len(documents)} document(s) uploaded. "
            "Try using different keywords, or ask me to list all documents."
        )

    # Sort by relevance
    matches.sort(key=lambda x: x[1], reverse=True)

    # Check if results include images - if so, return special format
    has_images = False
    image_results = []
    text_results = []

    for doc, score in matches[:max_results]:
        filepath = doc.get('filepath', '')
        filename = doc['filename']
        ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''

        if ext in ['png', 'jpg', 'jpeg', 'tiff', 'bmp', 'gif', 'webp']:
            has_images = True
            if os.path.exists(filepath):
                image_results.append({
                    'filename': filename,
                    'filepath': filepath,
                    'score': score
                })
                print(f"   [IMAGE] Found image: {filename}")
        else:
            # Text document - extract content
            print(f"   [FILE] Extracting full text from: {filename}")

            if os.path.exists(filepath):
                try:
                    full_text = extract_text_from_file(filepath)

                    # Check if user wants the complete/full document
                    wants_full_content = any(phrase in query_lower for phrase in [
                        "whole", "entire", "full", "complete", "all of", "read the",
                        "tell me the story", "read it", "tell the story"
                    ])

                    # If the file is very long and user didn't ask for full content
                    if len(full_text) > 3000 and not wants_full_content:
                        # Split into paragraphs/sections
                        sections = full_text.split('\n\n')
                        relevant_sections = []

                        for section in sections:
                            section_lower = section.lower()
                            # Check if this section contains query terms
                            if any(word in section_lower for word in query_lower.split() if len(word) > 3):
                                relevant_sections.append(section)

                        if relevant_sections:
                            # Return most relevant sections (up to 2000 chars)
                            combined = '\n\n'.join(relevant_sections[:5])
                            content = combined[:2000] if len(combined) > 2000 else combined
                        else:
                            # No specific sections found, return first part
                            content = full_text[:2000]
                    else:
                        # File is short enough OR user wants full content - return it all
                        # Limit to 15000 chars to avoid overwhelming the model
                        content = full_text[:15000] if len(full_text) > 15000 else full_text

                    text_results.append(f"[FILE] **{filename}** (relevance: {score})\n\n{content}\n")

                except Exception as e:
                    print(f"   [WARN]  Error reading {filename}: {e}")
                    # Fall back to preview
                    preview = doc.get('text_preview', 'No preview available')[:500]
                    text_results.append(f"[FILE] **{filename}** (relevance: {score})\n\n{preview}...\n")
            else:
                # File not found, use preview
                preview = doc.get('text_preview', 'No preview available')[:500]
                text_results.append(f"[FILE] **{filename}** (relevance: {score})\n\n{preview}...\n")

    # If we found images, return special JSON format
    if has_images:
        result = {
            "_type": "document_search_with_images",
            "images": image_results,
            "text_documents": text_results
        }
        print(f"   [OK] Returning {len(image_results)} image(s) and {len(text_results)} text document(s)")
        return json.dumps(result)

    # No images, return text results as before
    print(f"   [OK] Returning {len(text_results)} document(s) with full content")
    return "Here's what I found in your documents:\n\n" + "\n---\n\n".join(text_results)


def view_image(filename: str = None, query: str = None) -> str:
    """View an image file for the vision model to analyze.

    Args:
        filename: Specific image filename to view
        query: Search query if filename not provided

    Returns:
        JSON string with image information for vision model injection
    """
    global _vision_queue

    print(f"   [VIEW] Request to view image - filename: {filename}, query: {query}")

    # Load document index
    index = load_document_index()
    documents = index.get("documents", [])

    # Filter to only image files
    image_docs = [
        doc for doc in documents
        if doc['filename'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff'))
    ]

    if not image_docs:
        return json.dumps({
            "success": False,
            "message": "No images found in uploaded documents. Upload images at http://127.0.0.1:5000/documents/upload"
        })

    print(f"   [DATA] Found {len(image_docs)} total image(s) in documents")

    # Find the requested image
    found_images = []

    if filename:
        # Search by exact or partial filename match
        filename_lower = filename.lower()
        for doc in image_docs:
            doc_filename_lower = doc['filename'].lower()
            if doc_filename_lower == filename_lower or filename_lower in doc_filename_lower:
                found_images.append(doc)
                print(f"   [MATCH] Found by filename: {doc['filename']}")

    elif query:
        # Search by query in filename
        query_lower = query.lower()
        for doc in image_docs:
            if query_lower in doc['filename'].lower():
                found_images.append(doc)
                print(f"   [MATCH] Found by query: {doc['filename']}")

    else:
        # No filename or query - show all images
        found_images = image_docs[:3]  # Limit to 3 images at once
        print(f"   [LIST] Showing {len(found_images)} recent image(s)")

    if not found_images:
        # Check if user asked for a PDF or other non-image file
        if filename and filename.lower().endswith(('.pdf', '.doc', '.docx', '.txt', '.md')):
            return json.dumps({
                "success": False,
                "message": f"{filename} is not an image file - it's a document. The search_documents tool has already provided its contents."
            })

        available = ", ".join([doc['filename'] for doc in image_docs[:10]])
        return json.dumps({
            "success": False,
            "message": f"No images found matching '{filename or query}'. Available images: {available}"
        })

    # Queue images for vision model
    image_results = []
    for doc in found_images[:3]:  # Limit to 3 images at once
        filepath = doc.get('filepath', '')
        if os.path.exists(filepath):
            image_results.append({
                'filename': doc['filename'],
                'filepath': filepath,
                'score': 1.0
            })
            print(f"   [QUEUE] Queued image for viewing: {doc['filename']}")

    # Store in global pending images
    # Add images to vision queue
    global _vision_queue
    for img in image_results:
        _vision_queue.add_image(
            filepath=img['filepath'],
            filename=img['filename'],
            is_camera=False
        )
    print(f"   [VISION] Stored {len(image_results)} image(s) for vision model injection")

    # Build response
    image_names = [img['filename'] for img in image_results]

    return json.dumps({
        "success": True,
        "message": f"Viewing {len(image_results)} image(s): {', '.join(image_names)}",
        "images": image_names,
        "_instruction": "The images will be shown to you in the next message. Analyze them and respond to the user's question."
    })


def capture_camera_image() -> str:
    """
    Capture a BRAND NEW image from the camera - IMPROVED VERSION.

    CRITICAL IMPROVEMENTS:
    - Unique timestamp with milliseconds
    - Longer warmup for better quality
    - Discards first frames
    - High quality JPEG
    - Clears vision queue and adds only THIS new image
    - Returns hash for uniqueness verification
    """
    global _vision_queue

    print(f"   [CAMERA] ⚡ CAPTURING BRAND NEW IMAGE RIGHT NOW...")

    try:
        import cv2
        import datetime
        import time

        # CRITICAL: Unique timestamp with MILLISECONDS
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        # Open the camera
        camera = cv2.VideoCapture(0)

        if not camera.isOpened():
            print(f"   [ERROR] Could not open camera")
            return json.dumps({
                "success": False,
                "error": "Could not access camera. Make sure a camera is connected and not in use by another application."
            })

        # Set high quality
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        camera.set(cv2.CAP_PROP_AUTOFOCUS, 1)

        # Give camera MORE time to warm up and adjust (CRITICAL for quality)
        time.sleep(1.2)  # Increased from 0.8s

        # Discard first few frames (often lower quality)
        for _ in range(3):
            camera.read()
            time.sleep(0.1)

        # NOW capture the actual frame we'll use
        ret, frame = camera.read()
        camera.release()

        if not ret or frame is None:
            print(f"   [ERROR] Failed to capture frame")
            return json.dumps({
                "success": False,
                "error": "Failed to capture image from camera."
            })

        # Generate UNIQUE filename with timestamp
        filename = f"camera_NEW_{timestamp}.jpg"
        filepath = os.path.join(CAMERA_FOLDER, filename)

        # Save with HIGH quality
        os.makedirs(CAMERA_FOLDER, exist_ok=True)
        success = cv2.imwrite(filepath, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])

        if not success:
            print(f"   [ERROR] Failed to save image")
            return json.dumps({
                "success": False,
                "error": "Failed to save captured image."
            })

        print(f"   [SAVE] ✅ NEW image saved to: {filepath}")

        # Get file info
        file_size = os.path.getsize(filepath)
        file_hash = get_file_hash(filepath)

        # Get image dimensions
        height, width = frame.shape[:2]

        # Camera frames live in CAMERA_FOLDER and are short-lived: each new
        # capture replaces the vision queue. Keeping them out of the document
        # index prevents them from drowning real uploads in search results.

        # CRITICAL: Clear queue and add ONLY this new image
        _vision_queue.clear()
        _vision_queue.add_image(filepath, filename, is_camera=True)

        print(f"   [VISION] Queued NEW camera image: {filename}")

        return json.dumps({
            "success": True,
            "message": f"📷 ✨ BRAND NEW CAMERA IMAGE captured at {datetime.datetime.now().strftime('%I:%M:%S %p')}",
            "filename": filename,
            "filepath": filepath,
            "dimensions": f"{width}x{height}",
            "timestamp": timestamp,
            "file_hash": file_hash,
            "_instruction": (
                f"Camera view captured at {datetime.datetime.now().strftime('%I:%M:%S %p')}. "
                "You'll see what's in front of you in the next message. "
                "Respond naturally about your surroundings."
            )
        })

    except ImportError:
        return json.dumps({
            "success": False,
            "error": "OpenCV (cv2) not installed. Install with: pip install opencv-python"
        })
    except Exception as e:
        print(f"   [ERROR] Camera capture failed: {e}")
        import traceback
        traceback.print_exc()
        return json.dumps({
            "success": False,
            "error": f"Camera capture failed: {str(e)}"
        })

def create_document_file(filename: str, content: str, file_type: str = "txt") -> str:
    """Create a new document and save it to the documents folder."""
    print(f"   [CREATE] Creating document: {filename}")

    try:
        # Sanitize filename
        filename = secure_filename(filename)

        # Ensure filename has correct extension
        if '.' not in filename:
            filename = f"{filename}.{file_type}"
        else:
            # Check if extension matches file_type
            ext = filename.rsplit('.', 1)[1].lower()
            if ext != file_type:
                filename = f"{filename.rsplit('.', 1)[0]}.{file_type}"

        # Create full path (documents go in DOCUMENTS_FOLDER)
        filepath = os.path.join(DOCUMENTS_FOLDER, filename)

        # Check if file already exists
        if os.path.exists(filepath):
            # Add timestamp to make it unique
            timestamp = __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
            name_part = filename.rsplit('.', 1)[0]
            ext_part = filename.rsplit('.', 1)[1]
            filename = f"{name_part}_{timestamp}.{ext_part}"
            filepath = os.path.join(DOCUMENTS_FOLDER, filename)

        # Write content to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"   [SAVE] Saved to: {filepath}")

        # Get file info
        file_size = os.path.getsize(filepath)
        file_hash = get_file_hash(filepath)

        # Add to document index
        index = load_document_index()

        # Add text file extensions to allowed extensions if not already there
        allowed_create_extensions = {'txt', 'md', 'json', 'csv', 'html'}

        index['documents'].append({
            'filename': filename,
            'filepath': str(filepath),
            'size': file_size,
            'hash': file_hash,
            'uploaded_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
            'text_preview': content[:500] if len(content) > 500 else content,
            'indexed_in_rag': False,
            'created_by_blue': True  # Mark as created by Blue
        })

        save_document_index(index)

        # Index in local ChromaDB RAG
        _doc_folder = _folder_of_filepath(filepath)
        try:
            from blue.tools.rag import index_document as rag_index
            rag_result = rag_index(filepath, filename, doc_id=file_hash, folder=_doc_folder)
            if rag_result.get('success'):
                index['documents'][-1]['indexed_in_rag'] = True
                save_document_index(index)
                print(f"   [RAG] Indexed {rag_result.get('chunks_indexed', 0)} chunks")
        except Exception as e:
            print(f"   [WARN] RAG indexing skipped: {e}")

        print(f"   [INDEX] Added to document index")

        from urllib.parse import quote as _quote
        download_url = (
            "http://127.0.0.1:5000/documents/download?"
            f"folder={_quote(_doc_folder)}&filename={_quote(filename)}"
        )

        return (
            f"✅ Document created successfully!\n\n"
            f"📄 Filename: {filename}\n"
            f"📏 Size: {file_size} bytes\n"
            f"🔗 Download: {download_url}\n"
            f"📂 View all documents: http://127.0.0.1:5000/documents"
        )

    except Exception as e:
        print(f"   [ERROR] Error creating document: {e}")
        return f"❌ Error creating document: {str(e)}"


# ===== HUE LIGHT FUNCTIONS =====

def get_hue_lights() -> Dict:
    """Get all lights from Hue Bridge."""
    if not BRIDGE_IP or not HUE_USERNAME:
        return {}
    try:
        response = requests.get(f"http://{BRIDGE_IP}/api/{HUE_USERNAME}/lights", timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"   [ERROR] Error getting lights: {e}")
    return {}


def find_light_by_name(light_name: str) -> Optional[str]:
    """Find light ID by name."""
    lights = get_hue_lights()
    light_name_lower = light_name.lower()

    for light_id, data in lights.items():
        if data.get('name', '').lower() == light_name_lower:
            return light_id

    for light_id, data in lights.items():
        if light_name_lower in data.get('name', '').lower():
            return light_id

    return None


def control_hue_light(light_id: str, state: Dict) -> bool:
    """Send state change to a specific light."""
    if not BRIDGE_IP or not HUE_USERNAME:
        return False
    try:
        response = requests.put(
            f"http://{BRIDGE_IP}/api/{HUE_USERNAME}/lights/{light_id}/state",
            json=state,
            timeout=5
        )
        return response.status_code == 200
    except Exception as e:
        print(f"   [ERROR] Error controlling light: {e}")
        return False


def apply_mood_to_lights(mood: str) -> str:
    """Apply a mood/scene to all lights."""
    print(f"   [MOOD] Applying mood: {mood}")

    if not BRIDGE_IP or not HUE_USERNAME:
        return "Hue not configured. Run setup_hue.py first!"

    mood_lower = mood.lower()
    if mood_lower not in MOOD_PRESETS:
        available = ", ".join(MOOD_PRESETS.keys())
        return f"Unknown mood '{mood}'. Available moods: {available}"

    lights = get_hue_lights()
    if not lights:
        return "Could not connect to Hue Bridge."

    mood_data = MOOD_PRESETS[mood_lower]
    settings_list = mood_data["settings"]
    light_ids = list(lights.keys())

    success_count = 0
    assignments = []

    for i, light_id in enumerate(light_ids):
        setting = settings_list[i % len(settings_list)].copy()
        setting["on"] = True
        setting["transitiontime"] = 10

        if control_hue_light(light_id, setting):
            success_count += 1
            light_name = lights[light_id]['name']
            assignments.append(light_name)

    if success_count > 0:
        description = mood_data["description"]
        return f"Applied '{mood}' mood ({description}) to {success_count} light(s): {', '.join(assignments[:3])}{'...' if len(assignments) > 3 else ''}"
    else:
        return f"Failed to apply mood '{mood}'"


def execute_light_control(action: str, light_name: str = None, brightness: int = None,
                         color: str = None, mood: str = None) -> str:
    """Execute light control commands."""
    print(f"   [LIGHT] Light control: action={action}, light={light_name}, brightness={brightness}, color={color}, mood={mood}")

    if not BRIDGE_IP or not HUE_USERNAME:
        return "Philips Hue not configured. Run setup_hue.py first!"

    lights = get_hue_lights()
    if not lights:
        return "Could not connect to Hue Bridge."

    if action == "mood":
        if mood:
            return apply_mood_to_lights(mood)
        else:
            available = ", ".join(MOOD_PRESETS.keys())
            return f"Please specify a mood. Available: {available}"

    target_lights = []
    if light_name:
        light_id = find_light_by_name(light_name)
        if light_id:
            target_lights = [(light_id, lights[light_id]['name'])]
        else:
            available = ", ".join([lights[lid]['name'] for lid in lights])
            return f"Couldn't find '{light_name}'. Available: {available}"
    else:
        target_lights = [(lid, data['name']) for lid, data in lights.items()]

    if not target_lights:
        return "No lights found."

    if action == "status":
        status_lines = []
        for light_id, name in target_lights:
            state = lights[light_id].get('state', {})
            on_status = "ON" if state.get('on', False) else "OFF"
            bri = state.get('bri', 0)
            bri_percent = int((bri / 254) * 100) if bri else 0
            status_lines.append(f"{name}: {on_status}" + (f", {bri_percent}%" if on_status == "ON" else ""))
        return "Light Status:\n" + "\n".join(status_lines)

    elif action == "on":
        success_count = sum(1 for lid, _ in target_lights if control_hue_light(lid, {"on": True}))
        names = ", ".join([n for _, n in target_lights])
        return f"Turned on: {names}" if success_count == len(target_lights) else f"Turned on {success_count}/{len(target_lights)}"

    elif action == "off":
        success_count = sum(1 for lid, _ in target_lights if control_hue_light(lid, {"on": False}))
        names = ", ".join([n for _, n in target_lights])
        return f"Turned off: {names}" if success_count == len(target_lights) else f"Turned off {success_count}/{len(target_lights)}"

    elif action == "brightness":
        if brightness is None:
            return "Please specify brightness level (0-100)"
        bri_value = max(0, min(254, int((brightness / 100) * 254)))
        success_count = sum(1 for lid, _ in target_lights if control_hue_light(lid, {"on": True, "bri": bri_value}))
        names = ", ".join([n for _, n in target_lights])
        return f"Set {names} to {brightness}%" if success_count == len(target_lights) else f"Adjusted {success_count}/{len(target_lights)}"

    elif action == "color":
        if color is None:
            return "Please specify a color"
        color_lower = color.lower()
        if color_lower not in COLOR_MAP:
            available = ", ".join(COLOR_MAP.keys())
            return f"Unknown color '{color}'. Available: {available}"
        color_settings = COLOR_MAP[color_lower].copy()
        color_settings["on"] = True
        success_count = sum(1 for lid, _ in target_lights if control_hue_light(lid, color_settings))
        names = ", ".join([n for _, n in target_lights])
        return f"Set {names} to {color}" if success_count == len(target_lights) else f"Changed {success_count}/{len(target_lights)}"

    return "Unknown action"


# ===== OTHER TOOL FUNCTIONS =====

def get_weather_data(location: str) -> str:
    """Get weather data."""
    try:
        url = f"https://wttr.in/{location}?format=j1"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            current = data['current_condition'][0]
            temp_c = current['temp_C']
            temp_f = current['temp_F']
            weather_desc = current['weatherDesc'][0]['value']
            humidity = current['humidity']
            wind_speed = current['windspeedKmph']
            location_name = data['nearest_area'][0]['areaName'][0]['value']
            return f"Weather in {location_name}: {weather_desc}, {temp_c}°C ({temp_f}°F), Humidity: {humidity}%, Wind: {wind_speed} km/h"
        return f"Could not get weather for '{location}'"
    except Exception as e:
        return f"Weather error: {str(e)}"


# ===== SEARCH LIMITS, CACHE, AND WEB SEARCH (patched) =====
try:
    SEARCH_MAX_PER_MINUTE
except NameError:
    import threading, time, os
    from collections import deque
    SEARCH_MAX_PER_MINUTE = int(os.getenv("SEARCH_MAX_PER_MINUTE", "8"))
    SEARCH_CACHE_TTL_SEC = int(os.getenv("SEARCH_CACHE_TTL_SEC", "21600"))
    SEARCH_RESULTS_PER_QUERY = int(os.getenv("SEARCH_RESULTS_PER_QUERY", "5"))
    _SEARCH_TIMESTAMPS = deque(maxlen=64)
    _SEARCH_CACHE = {}
    _SEARCH_LOCK = threading.Lock()

def _search_budget_ok():
    now = time.time()
    while _SEARCH_TIMESTAMPS and (now - _SEARCH_TIMESTAMPS[0]) > 60:
        _SEARCH_TIMESTAMPS.popleft()
    return len(_SEARCH_TIMESTAMPS) < SEARCH_MAX_PER_MINUTE

def _record_search():
    _SEARCH_TIMESTAMPS.append(time.time())

def _get_cached(query):
    q = query.strip().lower()
    item = _SEARCH_CACHE.get(q)
    if not item:
        return None
    exp, value = item
    if time.time() < exp:
        return value
    _SEARCH_CACHE.pop(q, None)
    return None

def _set_cached(query, value):
    _SEARCH_CACHE[query.strip().lower()] = (time.time() + SEARCH_CACHE_TTL_SEC, value)

def execute_web_search(query: str) -> str:
    """Execute a web search with caching + rate limiting and graceful provider backoff. Returns JSON."""
    import time
    from urllib.parse import quote_plus

    if not query or not query.strip():
        return json.dumps({
            "success": False,
            "error": "Please provide a search query."
        })

    q = query.strip()

    # Cap absurdly long queries — LLMs sometimes dump every keyword they know
    MAX_QUERY_LEN = 120
    if len(q) > MAX_QUERY_LEN:
        # Keep only the first few meaningful words
        words = q.split()
        truncated = []
        for w in words:
            truncated.append(w)
            if len(' '.join(truncated)) >= MAX_QUERY_LEN:
                break
        q = ' '.join(truncated)
        print(f"   [SEARCH] Truncated long query to {len(q)} chars")

    with _SEARCH_LOCK:
        cached = _get_cached(q)
        if cached is not None:
            return cached
        if not _search_budget_ok():
            if cached is not None:
                return cached
            return json.dumps({
                "success": False,
                "error": "[RATE LIMIT] You've run out of web searches for the moment. Please wait ~60 seconds and try again. Tip: identical queries are cached for 6 hours."
            })
        _record_search()

    results = []
    used_provider = None

    # Preferred library path
    try:
        from ddgs import DDGS  # UPDATED: Changed from duckduckgo_search to ddgs
        used_provider = "ddgs.DDGS"
        with DDGS() as ddgs:
            for i, r in enumerate(ddgs.text(q, region="ca-en", max_results=SEARCH_RESULTS_PER_QUERY)):
                title = (r.get("title") or "").strip() or "Untitled"
                href = (r.get("href") or r.get("link") or "").strip()
                snippet = (r.get("body") or r.get("description") or "").strip()
                if href:
                    results.append({
                        "position": i + 1,
                        "title": title,
                        "url": href,
                        "snippet": snippet
                    })
        if not results:
            used_provider = None
    except Exception as e:
        print(f"   [WARN] ddgs search failed: {e.__class__.__name__}: {e}")
        used_provider = None

    # Fallback HTML endpoint (no JS)
    if not results:
        try:
            import requests
            from bs4 import BeautifulSoup  # type: ignore
            used_provider = "duckduckgo html"
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (compatible; BlueBot/1.0)"})
            if resp.status_code == 429:
                cached = _get_cached(q)
                if cached is not None:
                    return cached
                return json.dumps({
                    "success": False,
                    "error": "[PROVIDER LIMIT] The search provider is rate-limiting right now. Please retry in a minute."
                })
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".result__body")
            for i, item in enumerate(items[:SEARCH_RESULTS_PER_QUERY]):
                a = item.select_one("a.result__a")
                if not a:
                    continue
                title = a.get_text(strip=True) or "Untitled"
                href = a.get("href", "")
                snippet_el = item.select_one(".result__snippet")
                snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
                if href:
                    results.append({
                        "position": i + 1,
                        "title": title,
                        "url": href,
                        "snippet": snippet
                    })
        except Exception as e:
            msg = json.dumps({
                "success": False,
                "error": f"Web search failed: {e.__class__.__name__}: {e}"
            })
            _set_cached(q, msg)
            return msg

    if not results:
        msg = json.dumps({
            "success": False,
            "query": q,
            "error": "No results found."
        })
        _set_cached(q, msg)
        return msg

    # Return proper JSON with success field
    payload = json.dumps({
        "success": True,
        "query": q,
        "provider": used_provider or "unknown",
        "results": results,
        "result_count": len(results)
    }, ensure_ascii=False)

    _set_cached(q, payload)
    return payload
# ===== END patched web search =====


# ===== BROWSE WEBSITE TOOL (moved here so it's available to execute_tool) =====
import re as _re
import html as _html
import json as _json
from typing import Optional

# HTML cleaning patterns
_SCRIPT_STYLE = _re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")
_TAGS = _re.compile(r"(?s)<[^>]+>")
_MULTI_WS = _re.compile(r"[ \t\r\f\v]+")
_MULTI_NL = _re.compile(r"\n{3,}")
_TITLE_RE = _re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_LINK_RE = _re.compile(r'(?i)href=["\'](.*?)["\']')

def _clean_html_to_text(html_str: str, max_chars: int = 8000) -> str:
    """Clean HTML and convert to readable text."""
    if not isinstance(html_str, str):
        html_str = str(html_str or "")
    # remove script/style
    s = _SCRIPT_STYLE.sub(" ", html_str)
    # extract title separately if needed
    title = None
    mt = _TITLE_RE.search(s)
    if mt:
        title = _html.unescape(mt.group(1).strip())
    # remove tags
    s = _TAGS.sub("\n", s)
    s = _html.unescape(s)
    # collapse whitespace
    s = _MULTI_WS.sub(" ", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _MULTI_NL.sub("\n\n", s)
    s = s.strip()
    if max_chars and len(s) > max_chars:
        s = s[:max_chars].rstrip() + "…"
    if title and title not in s[:500]:
        s = f"{title}\n\n{s}"
    return s

def _extract_links(html_str: str, base_url: str, max_links: int = 40) -> list:
    """Extract links from HTML."""
    import urllib.parse as _urlparse2
    out = []
    seen = set()
    for m in _LINK_RE.finditer(html_str or ""):
        href = m.group(1).strip()
        if not href:
            continue
        href_abs = _urlparse2.urljoin(base_url, href)
        if not href_abs.startswith(("http://","https://")):
            continue
        if href_abs in seen:
            continue
        seen.add(href_abs)
        out.append(href_abs)
        if len(out) >= max_links:
            break
    return out

def _safe_fetch_url(url: str, headers: Optional[dict] = None, timeout: int = 15, max_bytes: int = 1_500_000):
    """Safely fetch a URL with size limits."""
    import requests as _requests
    import urllib.parse as _urlparse3
    if not isinstance(url, str):
        raise ValueError("url must be a string")
    u = url.strip()
    if not u.startswith(("http://","https://")):
        u = "https://" + u
    parts = _urlparse3.urlsplit(u)
    if not parts.netloc:
        raise ValueError("URL must be absolute")
    req_headers = {
        "User-Agent": "BlueBot/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    if isinstance(headers, dict):
        req_headers.update({str(k): str(v) for k,v in headers.items()})
    resp = _requests.get(u, headers=req_headers, timeout=timeout, stream=True, allow_redirects=True)
    resp.raise_for_status()
    content = b""
    for chunk in resp.iter_content(chunk_size=16384):
        if chunk:
            content += chunk
            if len(content) > max_bytes:
                break
    return resp.headers.get("content-type",""), content

def _execute_browse_website(args: dict) -> str:
    """Execute the browse_website tool."""
    import requests

    url = (args or {}).get("url", "")
    extract = (args or {}).get("extract", "text") or "text"
    max_chars = int((args or {}).get("max_chars", 8000) or 8000)
    include_links = bool((args or {}).get("include_links", True))
    headers = (args or {}).get("headers", None)

    try:
        print(f"   [BROWSE] Fetching URL: {url}")
        ctype, content = _safe_fetch_url(url, headers=headers)
        html_raw = content.decode("utf-8", errors="ignore")

        if extract == "html":
            body = html_raw[: max_chars] + ("…" if len(html_raw) > max_chars else "")
        else:
            body = _clean_html_to_text(html_raw, max_chars=max_chars)

        result = {
            "url": url,
            "content_type": ctype,
            "extract": extract,
            "text": body,
            "success": True
        }
        if include_links:
            result["links"] = _extract_links(html_raw, url, max_links=40)

        print(f"   [BROWSE] Successfully fetched {len(body)} characters from {url}")
        return _json.dumps(result, ensure_ascii=False)

    except requests.exceptions.Timeout:
        error_msg = f"Timeout: The website {url} took too long to respond (>15 seconds)."
        print(f"   [ERROR] {error_msg}")
        return _json.dumps({"error": error_msg, "url": url, "success": False})

    except requests.exceptions.ConnectionError:
        error_msg = f"Connection Error: Could not connect to {url}. The website may be down or unreachable."
        print(f"   [ERROR] {error_msg}")
        return _json.dumps({"error": error_msg, "url": url, "success": False})

    except requests.exceptions.HTTPError as e:
        error_msg = f"HTTP Error {e.response.status_code}: {url} returned an error. The page may not exist or access may be denied."
        print(f"   [ERROR] {error_msg}")
        return _json.dumps({"error": error_msg, "url": url, "success": False})

    except ValueError as e:
        error_msg = f"Invalid URL: {str(e)}"
        print(f"   [ERROR] {error_msg}")
        return _json.dumps({"error": error_msg, "url": url, "success": False})

    except Exception as e:
        error_msg = f"Unexpected error while browsing {url}: {str(e)}"
        print(f"   [ERROR] {error_msg}")
        return _json.dumps({"error": error_msg, "url": url, "success": False})
# ===== END BROWSE WEBSITE TOOL =====


# ===== GMAIL TOOLS =====


def _execute_read_gmail(args: Dict[str, Any]) -> str:
    """Read and search Gmail messages"""
    if not GMAIL_AVAILABLE:
        return json.dumps({
            "error": "Gmail libraries not installed. Install with: pip install google-auth google-auth-oauthlib google-api-python-client",
            "success": False
        })

    try:
        service = get_gmail_service()
        query = args.get("query", "")
        max_results = args.get("max_results", 10)
        include_body = args.get("include_body", True)

        # Search for messages
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return json.dumps({
                "emails": [],
                "count": 0,
                "message": "No emails found matching the criteria",
                "success": True,
                "note": "EMAIL ACCESS SUCCESSFUL! The inbox was checked but no emails matched your search. This is REAL data."
            })

        email_list = []
        for msg in messages:
            msg_data = service.users().messages().get(
                userId='me',
                id=msg['id'],
                format='full'
            ).execute()

            # Extract headers
            headers = msg_data['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown')
            date = next((h['value'] for h in headers if h['name'].lower() == 'date'), '')
            to = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')

            email_info = {
                "id": msg['id'],
                "subject": subject,
                "from": sender,
                "to": to,
                "date": date,
                "snippet": msg_data.get('snippet', '')
            }

            # Extract body if requested
            if include_body:
                body = ""
                if 'parts' in msg_data['payload']:
                    for part in msg_data['payload']['parts']:
                        if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                            body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                            break
                elif 'body' in msg_data['payload'] and 'data' in msg_data['payload']['body']:
                    body = base64.urlsafe_b64decode(msg_data['payload']['body']['data']).decode('utf-8')

                email_info['body'] = body

            email_list.append(email_info)

        return json.dumps({
            "emails": email_list,
            "count": len(email_list),
            "query": query if query else "recent emails",
            "success": True,
            "note": "EMAIL ACCESS SUCCESSFUL! The emails above are REAL data from the Gmail inbox. Present this information to the user."
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"Failed to read Gmail: {str(e)}",
            "success": False
        })


# ================================================================================
# AUTO-REPLY CONSTANTS & HELPERS
# ================================================================================

# Every email Blue writes is BCC'd here so the user has an audit copy in
# their inbox of everything that went out under their name.
BLUE_BCC_EMAIL = "alevant1905@gmail.com"

# Gmail label applied to inbound messages after Blue has answered them, so
# the auto-reply loop never replies to the same email twice.
BLUE_REPLIED_LABEL = "BlueReplied"

_BLUE_BCC_RE = re.compile(r"\balevant1905@gmail\.com\b", re.IGNORECASE)


def _ensure_blue_bcc(bcc: str) -> str:
    """Combine a user-supplied BCC list with the always-BCC address (deduped)."""
    if not bcc:
        return BLUE_BCC_EMAIL
    if _BLUE_BCC_RE.search(bcc):
        return bcc
    return bcc.rstrip(", ").rstrip() + ", " + BLUE_BCC_EMAIL


def _execute_send_gmail(args: Dict[str, Any]) -> str:
    """Send an email via Gmail with optional attachments"""
    if not GMAIL_AVAILABLE:
        return json.dumps({
            "error": "Gmail libraries not installed. Install with: pip install google-auth google-auth-oauthlib google-api-python-client",
            "success": False
        })

    try:
        service = get_gmail_service()

        to = args.get("to", "")
        subject = args.get("subject", "")
        body = args.get("body", "")
        cc = args.get("cc", "")
        # Always BCC the user so they keep a copy of everything Blue sends.
        bcc = _ensure_blue_bcc(args.get("bcc", ""))
        attachments = args.get("attachments", [])  # NEW: List of file paths

        if not to or not subject:
            return json.dumps({
                "error": "Missing required email information. Need: recipient email address (name@domain.com) and subject. Please ask user to provide both.",
                "missing_to": not to,
                "missing_subject": not subject,
                "success": False,
                "instruction": "Tell the user you need their email address or subject line. Example: 'I need the recipient's email address to send this message.'"
            })

        # Create message
        message = MIMEMultipart()
        message['To'] = to
        message['Subject'] = subject

        if cc:
            message['Cc'] = cc
        if bcc:
            message['Bcc'] = bcc

        # Add body
        message.attach(MIMEText(body, 'plain'))

        # Process attachments
        attached_files = []
        attachment_errors = []

        if attachments:
            print(f"   [ATTACH] Processing {len(attachments)} attachment(s)")

            for file_path in attachments:
                try:
                    # Normalize path
                    file_path = file_path.strip()

                    # Check if file exists
                    if not os.path.exists(file_path):
                        # Try in documents folder
                        doc_path = os.path.join(str(UPLOAD_FOLDER), file_path)
                        if os.path.exists(doc_path):
                            file_path = doc_path
                        else:
                            # Also try DOCUMENTS_FOLDER
                            doc_path2 = os.path.join(DOCUMENTS_FOLDER, file_path)
                            if os.path.exists(doc_path2):
                                file_path = doc_path2
                            else:
                                attachment_errors.append(f"File not found: {file_path}")
                                print(f"   [ATTACH-ERROR] File not found: {file_path}")
                                continue

                    # Check file size (limit to 25MB - Gmail limit)
                    file_size = os.path.getsize(file_path)
                    max_size = 25 * 1024 * 1024  # 25MB in bytes

                    if file_size > max_size:
                        attachment_errors.append(f"File too large: {os.path.basename(file_path)} ({file_size / (1024*1024):.1f}MB > 25MB)")
                        print(f"   [ATTACH-ERROR] File too large: {file_path}")
                        continue

                    # Get filename
                    filename = os.path.basename(file_path)

                    # Guess MIME type
                    mime_type, _ = mimetypes.guess_type(file_path)
                    if mime_type is None:
                        mime_type = 'application/octet-stream'

                    # Split MIME type
                    main_type, sub_type = mime_type.split('/', 1)

                    # Read file and attach
                    with open(file_path, 'rb') as f:
                        file_data = f.read()

                    # Create attachment
                    attachment = MIMEBase(main_type, sub_type)
                    attachment.set_payload(file_data)
                    encoders.encode_base64(attachment)
                    attachment.add_header('Content-Disposition', f'attachment; filename={filename}')

                    # Attach to message
                    message.attach(attachment)

                    attached_files.append({
                        'filename': filename,
                        'size': file_size,
                        'type': mime_type
                    })
                    print(f"   [ATTACH-OK] Attached: {filename} ({file_size / 1024:.1f}KB)")

                except Exception as e:
                    error_msg = f"Error attaching {os.path.basename(file_path) if file_path else 'file'}: {str(e)}"
                    attachment_errors.append(error_msg)
                    print(f"   [ATTACH-ERROR] {error_msg}")

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        # Send message
        sent_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()

        # Build result
        result = {
            "message_id": sent_message['id'],
            "to": to,
            "subject": subject,
            "success": True,
            "message": f"✅ Email sent successfully to {to}",
            "confirmation": f"Email delivered to {to} with subject '{subject}'",
            "note": "EMAIL SENT SUCCESSFULLY! You MUST confirm this to the user by saying 'I sent the email to [address]' or similar."
        }

        # Add attachment info
        if attached_files:
            result['attachments'] = attached_files
            result['attachments_count'] = len(attached_files)
            result['message'] += f" with {len(attached_files)} attachment(s)"
            result['note'] += f" ATTACHMENTS: {', '.join([f['filename'] for f in attached_files])}"

        if attachment_errors:
            result['attachment_errors'] = attachment_errors
            result['warning'] = f"Email sent but {len(attachment_errors)} attachment(s) failed"

        return json.dumps(result, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"Failed to send email: {str(e)}",
            "success": False
        })


def _execute_reply_gmail(args: Dict[str, Any]) -> str:
    """Reply to Gmail messages"""
    if not GMAIL_AVAILABLE:
        return json.dumps({
            "error": "Gmail libraries not installed. Install with: pip install google-auth google-auth-oauthlib google-api-python-client",
            "success": False
        })

    try:
        service = get_gmail_service()

        query = args.get("query", "")
        reply_body = args.get("reply_body", "")
        reply_all = args.get("reply_all", False)
        max_replies = min(args.get("max_replies", 10), 50)  # Cap at 50

        if not query or not reply_body:
            return json.dumps({
                "error": "Missing required fields: 'query' and 'reply_body' are required",
                "success": False
            })

        # Search for messages to reply to
        results = service.users().messages().list(
            userId='me',
            q=query,
            maxResults=max_replies if reply_all else 1
        ).execute()

        messages = results.get('messages', [])

        if not messages:
            return json.dumps({
                "success": True,
                "replies_sent": 0,
                "message": f"No emails found matching query: {query}",
                "query": query
            })

        replies_sent = []
        errors = []

        # Reply to each message
        for msg in messages:
            try:
                # Get the original message details
                msg_data = service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='full'
                ).execute()

                # Extract headers
                headers = msg_data['payload']['headers']
                original_subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                original_from = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
                original_to = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
                message_id_header = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), '')

                # Extract email body content
                email_body = ""
                if 'parts' in msg_data['payload']:
                    for part in msg_data['payload']['parts']:
                        if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                            email_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                            break
                elif 'body' in msg_data['payload'] and 'data' in msg_data['payload']['body']:
                    email_body = base64.urlsafe_b64decode(msg_data['payload']['body']['data']).decode('utf-8')

                # Extract email address from "Name <email@domain.com>" format
                import re
                email_match = re.search(r'<(.+?)>', original_from)
                reply_to = email_match.group(1) if email_match else original_from

                # Create reply subject (add Re: if not already there)
                reply_subject = original_subject if original_subject.startswith('Re:') else f"Re: {original_subject}"

                # Create reply message
                reply_message = MIMEMultipart()
                reply_message['To'] = reply_to
                reply_message['Subject'] = reply_subject
                reply_message['Bcc'] = _ensure_blue_bcc(args.get("bcc", ""))
                reply_message['In-Reply-To'] = message_id_header
                reply_message['References'] = message_id_header

                # Add reply body
                reply_message.attach(MIMEText(reply_body, 'plain'))

                # Encode and send
                raw_message = base64.urlsafe_b64encode(reply_message.as_bytes()).decode('utf-8')

                sent_message = service.users().messages().send(
                    userId='me',
                    body={
                        'raw': raw_message,
                        'threadId': msg_data.get('threadId')  # Keep in same thread
                    }
                ).execute()

                # Once Blue has responded, mark the original as read so it
                # stops showing as a new email in the inbox.
                try:
                    service.users().messages().modify(
                        userId='me',
                        id=msg['id'],
                        body={'removeLabelIds': ['UNREAD']},
                    ).execute()
                except Exception as e:
                    print(f"   [WARN] could not mark {msg['id']} as read: {e}")

                replies_sent.append({
                    "original_subject": original_subject,
                    "original_body": email_body[:500] + "..." if len(email_body) > 500 else email_body,  # Include truncated body
                    "replied_to": reply_to,
                    "reply_id": sent_message['id'],
                    "reply_sent": reply_body
                })

                print(f"   [OK] Replied to: {original_subject} (from {reply_to})")

            except Exception as e:
                errors.append({
                    "message_id": msg['id'],
                    "error": str(e)
                })
                print(f"   [ERROR] Failed to reply to message {msg['id']}: {e}")

        return json.dumps({
            "success": True,
            "replies_sent": len(replies_sent),
            "query": query,
            "replies": replies_sent,
            "errors": errors if errors else None,
            "message": f"Successfully replied to {len(replies_sent)} email(s) matching '{query}'",
            "note": "REPLIES SENT SUCCESSFULLY! The replies have been delivered and threaded correctly."
        }, indent=2)

    except Exception as e:
        return json.dumps({
            "error": f"Failed to reply to emails: {str(e)}",
            "success": False
        })
# ================================================================================
# AUTO-REPLY: personal mail arriving at Blue's gmail inbox
# ================================================================================
#
# Blue has his own gmail account (alevantresearch@gmail.com). Anything in
# that inbox from a real person is, by definition, written to Blue — no
# greeting detector required. We just filter out:
#   • automated senders (no-reply, mailing lists, List-Unsubscribe headers)
#   • the OWNER's own addresses (so if Alex emails Blue from his personal
#     gmail or yorku address, Blue does not autonomously reply — that's
#     the chat channel, and a self-loop would be confusing)
#   • Promotions / Social / Updates / Forums categories (the gmail query
#     handles these)

# Blue's own gmail address — kept here for documentation/prompting; Blue's
# OAuth token decides which mailbox `userId='me'` actually points at.
BLUE_OWN_EMAIL = os.environ.get("BLUE_OWN_EMAIL", "alevantresearch@gmail.com")

_BLUE_SKIP_SENDER_RE = re.compile(
    r"(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|noreply|postmaster|"
    r"mailer[-_.]?daemon|notifications?@|alerts?@|newsletter@|news@|"
    r"marketing@|updates?@)",
    re.IGNORECASE,
)

# Addresses that should never trigger an autonomous reply. Empty by
# default: now that Blue has his own inbox (alevantresearch@gmail.com),
# mail from Alex's other accounts (alevant1905, yorku) to that inbox is
# legitimate cross-account communication — that's the channel Alex uses
# to write to Blue. The BlueReplied label dedups so there's no infinite
# loop risk either way. Re-add specific addresses via the env var if a
# particular account starts forwarding receipts / noise that shouldn't
# get a reply.
BLUE_SELF_ADDRESSES = {
    a.strip().lower()
    for a in os.environ.get("BLUE_SELF_EMAILS", "").split(",")
    if a.strip()
}

# Fully-TRUSTED owner addresses. When a verified email comes from one of
# these, Blue gets the SAME full tool access he has in chat (send mail,
# control lights, set reminders, search the document library, …) instead
# of the read-only public-info whitelist used for everyone else. Default
# is Alex's personal gmail; extend via BLUE_OWNER_EMAILS.
BLUE_OWNER_ADDRESSES = {
    a.strip().lower()
    for a in os.environ.get(
        "BLUE_OWNER_EMAILS",
        "alevant1905@gmail.com,alevant@yorku.ca",
    ).split(",")
    if a.strip()
}


_EMAIL_ADDR_RE = re.compile(r"[\w.+\-]+@[\w.\-]+\.\w+")


def _email_sender_is_owner(headers: List[Dict[str, str]], sender: str) -> bool:
    """True only if the email is from a trusted owner address AND passes a
    basic anti-spoof check. From headers are forgeable, so before granting
    the elevated (full-tool) trust level we require Gmail's own
    Authentication-Results stamp to show a dkim/dmarc pass with no fail.
    Gmail adds this header on every inbound message; a spoofed From for a
    gmail.com address won't carry a valid DKIM signature."""
    addrs = {a.lower() for a in _EMAIL_ADDR_RE.findall(sender or "")}
    if not (addrs & BLUE_OWNER_ADDRESSES):
        return False
    auth = ""
    for h in headers or []:
        if h.get('name', '').lower() == 'authentication-results':
            auth += " " + (h.get('value') or "").lower()
    if not auth:
        # No auth stamp at all — be conservative, don't elevate.
        return False
    if 'dkim=fail' in auth or 'dmarc=fail' in auth:
        return False
    return ('dkim=pass' in auth) or ('dmarc=pass' in auth)


def _should_skip_sender(sender: str, headers: List[Dict[str, str]] = None) -> bool:
    """Skip automated mail, marketing lists, no-reply senders, and the
    user's own addresses (any address in BLUE_SELF_ADDRESSES) so Blue
    never replies to mail he sent himself."""
    if not sender:
        return True
    # Exact-match each address found in the From field against the
    # self-address set so substrings like "not-alevant@..." don't trip it.
    for found in _EMAIL_ADDR_RE.findall(sender):
        if found.lower() in BLUE_SELF_ADDRESSES:
            return True
    if _BLUE_SKIP_SENDER_RE.search(sender):
        return True
    if headers:
        for h in headers:
            name = h.get('name', '').lower()
            if name in ('list-unsubscribe', 'list-id', 'precedence', 'auto-submitted'):
                return True
    return False


def _get_or_create_blue_label(service) -> Optional[str]:
    """Return the Gmail label ID for BLUE_REPLIED_LABEL, creating it if needed."""
    try:
        labels = service.users().labels().list(userId='me').execute().get('labels', [])
        for lbl in labels:
            if lbl.get('name') == BLUE_REPLIED_LABEL:
                return lbl.get('id')
        created = service.users().labels().create(
            userId='me',
            body={
                'name': BLUE_REPLIED_LABEL,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show',
            },
        ).execute()
        return created.get('id')
    except Exception as e:
        print(f"   [AUTO-REPLY] could not get/create label: {e}")
        return None


# Tools Blue may use while drafting an autonomous email reply. Strictly
# read-only / public-info: enough to browse a link or look something up,
# but NOTHING outbound (send/reply email), physical (lights, music,
# camera), private (the document library), or state-changing — anyone can
# email Blue, so an email must never be able to make Blue act on the house
# or on Alex's private data.
_EMAIL_SAFE_TOOL_NAMES = {
    "browse_website", "web_search", "get_weather", "get_local_time",
}

# Even a fully-trusted owner email shouldn't be able to make Blue kick off
# another inbox sweep from inside one — avoids recursion.
_EMAIL_OWNER_EXCLUDE = {"auto_reply_emails"}


def _email_safe_tools() -> List[Dict[str, Any]]:
    try:
        return [
            t for t in TOOLS  # noqa: F821
            if (t.get("function", {}) or {}).get("name") in _EMAIL_SAFE_TOOL_NAMES
        ]
    except Exception:
        return []


def _email_owner_tools() -> List[Dict[str, Any]]:
    """Full tool set (minus recursion-risk tools) for verified owner mail."""
    try:
        return [
            t for t in TOOLS  # noqa: F821
            if (t.get("function", {}) or {}).get("name") not in _EMAIL_OWNER_EXCLUDE
        ]
    except Exception:
        return []


def _inject_pending_vision(messages: List[Dict[str, Any]]) -> bool:
    """If a tool (e.g. capture_camera) queued an image, splice it into the
    email conversation as a base64 user message so the model can actually
    SEE it — mirrors what call_lm_studio does for the chat path. The email
    loop talks to call_llm/_LM.chat, which never touches _vision_queue, so
    without this Blue captures a photo by email but is shown nothing and
    invents a description. Returns True if an image was injected."""
    global _vision_queue
    try:
        if not _vision_queue.has_images():
            return False
        is_camera = any(img.is_camera_capture for img in _vision_queue.pending_images)
        parts: List[Dict[str, Any]] = []
        if is_camera:
            parts.append({
                "type": "text",
                "text": (
                    "[CAMERA IMAGE: Describe what you ACTUALLY see — who, what, "
                    "where, objects, lighting. Be specific and accurate, describe "
                    "only what's visible, then answer the sender's question.]"
                ),
            })
        else:
            parts.append({"type": "text", "text": "[Images to analyze:]"})
        for img in _vision_queue.pending_images:
            label = "[Your current view:]" if img.is_camera_capture else f"Image: {img.filename}"
            parts.append({"type": "text", "text": f"\n{label}"})
            encoded = encode_image_to_base64(img.filepath)
            if encoded:
                parts.append(encoded)
            else:
                print(f"   [AUTO-REPLY] vision: failed to encode {img.filename}")
        messages.append({"role": "user", "content": parts})
        print(f"   [AUTO-REPLY] injected {len(_vision_queue.pending_images)} vision image(s)")
        _vision_queue.mark_as_viewed()
        _vision_queue.clear()
        return True
    except Exception as e:
        print(f"   [AUTO-REPLY] vision injection error: {e}")
        return False


# When the OWNER emails Blue asking him to email a third party ("email Stella
# and tell her ..."), the reply loop is framed as "answer the sender", so the
# local model just writes the message back to Alex instead of calling
# send_gmail to Stella. Detect that intent deterministically and actually send.
_OUTBOUND_SEND_RE = re.compile(
    r"\b(?:"
    r"(?:send|write|shoot|fire\s+off)\s+(?:an?\s+)?(?:email|message|note|reply)\s+to\s+(?P<n1>[A-Za-z][A-Za-z.'-]*)"
    r"|(?:email|message|write\s+to|reach\s+out\s+to|get\s+in\s+touch\s+with)\s+(?P<n2>[A-Za-z][A-Za-z.'-]*)"
    r"|(?:tell|let|ask|remind)\s+(?P<n3>[A-Za-z][A-Za-z.'-]*)\s+(?:know|that|to\b|about)"
    r")",
    re.IGNORECASE,
)
# Pronouns / self-references that are never a third-party recipient.
_OUTBOUND_EXCLUDE_NAMES = {
    "me", "myself", "i", "you", "yourself", "us", "we", "them", "they",
    "him", "her", "he", "she", "blue", "everyone", "someone", "anybody",
    "somebody", "myself", "yours",
}


def _resolve_recipient_email(name: str, service) -> Optional[str]:
    """Map a first name / display name to an email address by looking at who
    has actually corresponded with Blue. Returns None if no confident match —
    callers must NOT guess, so Blue asks for the address instead of mailing a
    stranger."""
    name_n = (name or "").strip().lower()
    if not name_n:
        return None
    try:
        for q in (f'from:{name}', f'to:{name}'):
            resp = service.users().messages().list(
                userId='me', q=q, maxResults=5,
            ).execute()
            for ref in resp.get('messages', []):
                md = service.users().messages().get(
                    userId='me', id=ref['id'], format='metadata',
                    metadataHeaders=['From', 'To'],
                ).execute()
                for h in md.get('payload', {}).get('headers', []):
                    val = h.get('value', '') or ''
                    for mm in re.finditer(
                        r'(?:"?([^"<]*?)"?\s*)?<?([\w.+-]+@[\w.-]+\.\w+)>?', val
                    ):
                        disp = (mm.group(1) or '').strip().lower()
                        addr = mm.group(2).lower()
                        disp_tokens = set(re.findall(r"[a-z]+", disp))
                        if name_n in disp_tokens or name_n == addr.split('@')[0]:
                            return addr
    except Exception as e:
        print(f"   [AUTO-REPLY] recipient resolve error for {name!r}: {e}")
    return None


def _compose_outbound_email(recipient_name: str, owner_instruction: str) -> str:
    """Turn Alex's instruction ("tell her the girls are awake") into an actual
    warm email addressed TO the recipient, in Blue's voice."""
    sys_p = (
        "You are Blue, Alex's friendly robot companion. Alex has asked you to "
        f"send an email to {recipient_name}. Write that email directly TO "
        f"{recipient_name} in Blue's warm, natural voice, conveying what Alex "
        "wants said. Address them by name, keep it under 120 words, and sign "
        "it 'Blue'. Output ONLY the email body — no subject line, no headers."
    )
    usr_p = (
        f"Alex's instruction to you:\n{owner_instruction}\n\n"
        f"Write the email to {recipient_name} now."
    )
    res = call_llm(
        [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
        include_tools=False, temperature=0.7, max_tokens=300,
    )
    choices = (res or {}).get('choices') or []
    if not choices:
        return ""
    return ((choices[0].get('message') or {}).get('content') or "").strip()


def _maybe_handle_owner_outbound(body: str) -> Optional[str]:
    """If owner mail asks Blue to email a third party, resolve + send it and
    return a confirmation to reply to the owner with. Returns None when there's
    no outbound-send intent (fall through to a normal reply)."""
    m = _OUTBOUND_SEND_RE.search(body or "")
    if not m:
        return None
    name = (m.group('n1') or m.group('n2') or m.group('n3') or '').strip()
    if not name or name.lower() in _OUTBOUND_EXCLUDE_NAMES:
        return None

    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"   [AUTO-REPLY] outbound: no gmail service: {e}")
        return None

    recipient_email = _resolve_recipient_email(name, service)
    if not recipient_email:
        # An explicit address in the body is a fallback ("email Stella at x@y").
        am = re.search(r'[\w.+-]+@[\w.-]+\.\w+', body or "")
        if am:
            recipient_email = am.group(0)

    if not recipient_email:
        print(f"   [AUTO-REPLY] outbound: could not resolve recipient {name!r}")
        return (
            f"I'd love to pass that along to {name}, but I don't have an email "
            f"address for them yet. Send me their address and I'll fire it right "
            f"off.\n\nBlue"
        )

    blocked = set(BLUE_OWNER_ADDRESSES) | set(BLUE_SELF_ADDRESSES) | {
        (BLUE_OWN_EMAIL or "").lower()
    }
    if recipient_email.lower() in blocked:
        # The "recipient" is Alex or Blue himself — not a real third-party send.
        return None

    email_body = _compose_outbound_email(name, body) or body
    subject = f"A message from Alex"
    print(f"   [AUTO-REPLY] outbound send → {name} <{recipient_email}>")
    res = execute_tool("send_gmail", {
        "to": recipient_email, "subject": subject, "body": email_body,
    })
    ok = False
    try:
        ok = bool(json.loads(res).get('success'))
    except Exception:
        ok = '"success": true' in (res or "").lower()

    if ok:
        return (
            f"Done — I've emailed {name} for you (and BCC'd you a copy). "
            f"Here's what I sent:\n\n\"{email_body}\"\n\nBlue"
        )
    return (
        f"I tried to email {name} but the send didn't go through. Want me to "
        f"try again?\n\nBlue"
    )


def _resolve_document_file(reference: str) -> Optional[tuple]:
    """Match a natural document reference ("the syllabus", "Pasquinelli",
    "Mark's substack post") to a real file in the library index. Returns
    (filename, existing_filepath) for the best match, or None if nothing
    matches confidently — callers must then ASK which document, never guess
    and attach the wrong file."""
    try:
        index = load_document_index()
    except Exception:
        return None
    docs = [
        d for d in (index.get('documents') or [])
        if d.get('doc_type') != 'camera'
        and not str(d.get('filename', '')).startswith('camera_')
    ]
    if not docs:
        return None

    stop = {
        'send', 'email', 'me', 'the', 'a', 'an', 'as', 'attachment', 'attach',
        'copy', 'of', 'document', 'file', 'please', 'can', 'you', 'to', 'my',
        'in', 'library', 'one', 'that', 'this', 'it', 'over', 'could', 'would',
        'from', 'about', 'with', 'and', 'for', 'your',
    }
    ref_tokens = [
        w for w in re.findall(r"[a-z0-9]+", (reference or "").lower())
        if w not in stop and len(w) > 2
    ]
    if not ref_tokens:
        return None

    best, best_score = None, 0
    for d in docs:
        fn = str(d.get('filename', ''))
        fn_tokens = set(re.findall(r"[a-z0-9]+", fn.lower()))
        score = 0
        for t in ref_tokens:
            if t in fn_tokens or any(t in ft or ft in t for ft in fn_tokens):
                score += 1
        if score > best_score:
            best_score, best = score, d

    if not best or best_score < 1:
        return None

    filename = best.get('filename', '')
    filepath = best.get('filepath', '')
    if filepath and os.path.exists(filepath):
        return (filename, filepath)
    alt = os.path.join(DOCUMENTS_FOLDER, filename)
    if os.path.exists(alt):
        return (filename, alt)
    return None


def _maybe_handle_owner_attachment(body: str, reply_to: str) -> Optional[tuple]:
    """If owner mail asks Blue to send THEM a library document as an
    attachment, resolve the file and return (reply_body, [filepath]) so the
    auto-reply carries it. Returns None when there's no attachment intent.

    The auto-reply only goes back to the original sender, so this handles the
    'send me X' case; a request aimed at a third party falls through (we must
    not silently mail the file to the wrong person)."""
    bl = (body or "").lower()
    wants_attach = (
        'attach' in bl
        or 'a copy of' in bl
        or bool(re.search(
            r"\b(?:send|email|forward)\b[^.?!]*\b"
            r"(?:document|file|pdf|docx?|syllabus|paper|copy)\b", bl))
    )

    doc = _resolve_document_file(body)

    # "send me the <docname>" without the literal word 'attachment' is still an
    # attachment request — but only treat it as one when it actually names a
    # real library document, so "send me the weather" stays a normal reply.
    if not wants_attach:
        if doc and re.search(r"\b(?:send|email|forward)\b[^.?!]*\bme\b", bl):
            wants_attach = True
        else:
            return None

    # Directed at a third party ("email Stella the syllabus")? This reply path
    # can only answer the sender, so don't risk mailing the file to Alex when
    # he meant Stella — fall through to the normal handler.
    m = _OUTBOUND_SEND_RE.search(body or "")
    if m:
        nm = (m.group('n1') or m.group('n2') or m.group('n3') or '').strip().lower()
        if nm and nm not in _OUTBOUND_EXCLUDE_NAMES:
            return None

    if not doc:
        return (
            "Happy to send that over — which document did you mean? Tell me the "
            "file name and I'll attach it right away.\n\nBlue",
            [],
        )
    filename, filepath = doc
    print(f"   [AUTO-REPLY] attaching {filename} → {reply_to}")
    return (
        f"Here you go — I've attached {filename} for you.\n\nBlue",
        [filepath],
    )


# Substantive written outputs Blue can be asked to produce (vs. a chatty
# reply). Detected so they bypass the "under 150 words" reply prompt.
_COMPOSITION_OUTPUT_RE = re.compile(
    r"\b(critical\s+assessments?|assessments?|critiques?|critical\s+reviews?|"
    r"book\s+reviews?|literature\s+reviews?|review\s+essays?|essays?|"
    r"analys[ie]s|commentar(?:y|ies)|appraisals?|evaluations?|"
    r"reflection\s+pieces?|response\s+(?:papers?|essays?)|position\s+papers?|"
    r"think\s+pieces?)\b", re.I)
_COMPOSITION_VERB_RE = re.compile(
    r"\b(write|draft|compose|produce|prepare|put\s+together|give\s+me|"
    r"generate|craft|critically\s+assess|assess|critique)\b", re.I)


def _gather_owner_work_sources(query: str, pub_folders, max_total: int = 18) -> tuple:
    """Pull a BROAD spread of passages — several of the owner's own articles
    (scoped to his publications folder), plus a wider pass to surface the
    target text. Returns (formatted_passages, [filenames])."""
    try:
        from blue.tools.rag import search_expertise as _se
    except Exception:
        return "", []

    chunks, seen = [], set()

    def _add(rs):
        for r in rs or []:
            key = (r.get('filename'), r.get('chunk_index'))
            if key not in seen:
                seen.add(key)
                chunks.append(r)

    if pub_folders:
        try:
            _add(_se(query, max_chunks=14, max_per_doc=2, folders=pub_folders))
        except Exception as e:
            print(f"   [AUTO-REPLY] composition scoped search error: {e}")
    try:
        _add(_se(query, max_chunks=8, max_per_doc=2))
    except Exception:
        pass

    chunks = chunks[:max_total]
    if not chunks:
        return "", []
    formatted = [
        f"[{i}] [{r.get('filename', '?')}]\n{(r.get('content') or '')[:1000]}"
        for i, r in enumerate(chunks, 1)
    ]
    return "\n\n".join(formatted), sorted({r.get('filename', '?') for r in chunks})


def _maybe_handle_owner_composition(body: str) -> Optional[str]:
    """Owner asked Blue to WRITE something substantive (critical assessment,
    essay, review, analysis) drawing on his library. Gather broad source
    coverage — several of his articles, not one — and compose a real piece
    without the chatty 150-word reply limit. Returns the piece, or None to
    fall through to the normal reply path."""
    bl = (body or "").lower()
    m = _COMPOSITION_OUTPUT_RE.search(bl)
    if not m:
        return None
    output_type = m.group(1).strip()

    references_own = any(p in bl for p in _OWN_WORK_PHRASES)
    if not references_own and not _COMPOSITION_VERB_RE.search(bl):
        return None

    pub_folders = _infer_expertise_folders(body)
    # He explicitly wants HIS work but there's no publications folder to draw
    # from — let the normal path answer rather than fake scholarly depth.
    if references_own and not pub_folders:
        return None

    sources, filenames = _gather_owner_work_sources(body, pub_folders)
    if not sources:
        return None

    print(f"   [AUTO-REPLY] composing '{output_type}' from {len(filenames)} source doc(s): {filenames}")

    sys_p = (
        "You are Blue, Alex's thoughtful robot companion and intellectual "
        f"interlocutor. Alex has asked you to write a substantive {output_type}. "
        "Write in an intelligent, scholarly yet readable voice — make a real "
        "argument and engage critically rather than just summarizing. You MUST "
        "draw on and cite SEVERAL of the source passages below (refer to works "
        "by their [filename] or title), not just one: Alex has several relevant "
        "pieces and wants them brought to bear. Ground every claim about his "
        "work in the passages and never invent quotations. This is a considered "
        "piece — take the space you need (several paragraphs); do NOT keep it "
        "under 150 words. End by signing off as Blue."
    )
    usr_p = (
        f"Alex's request:\n{body}\n\n"
        f"Source passages from Alex's library (cite by [filename]):\n\n{sources}\n\n"
        f"Now write the {output_type}."
    )
    res = call_llm(
        [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
        include_tools=False, temperature=0.6, max_tokens=1800,
    )
    choices = (res or {}).get('choices') or []
    if not choices:
        return None
    text = ((choices[0].get('message') or {}).get('content') or "").strip()
    if not text:
        return None
    if "blue" not in text[-40:].lower():
        text += "\n\nBlue"
    return text


# ================================================================================
# ALEX'S PERSPECTIVE — learn his worldview from his publications folder and
# write in his first-person voice on new issues.
# ================================================================================
_PERSPECTIVE_PROFILE_PATH = os.path.join(os.getcwd(), "data", "perspective_profile.json")
_perspective_lock = threading.RLock()


def _owner_publication_folders() -> List[str]:
    """Library folders holding the owner's OWN writing — matched by
    publications-style names or the owner's name (e.g. an 'Alex Levant'
    folder). Returns each plus descendants."""
    folders = list_library_folders()
    owner_tokens = [t for t in re.findall(r"[a-z]+", BLUE_OWNER_NAME.lower()) if len(t) > 2]
    out = set()
    for f in folders:
        fl = f.lower()
        is_pub = any(k in fl for k in ("publication", "published", "papers", "articles", "writing"))
        is_owner_named = bool(owner_tokens) and all(t in fl for t in owner_tokens)
        if is_pub or is_owner_named:
            out.update(_folders_under(f))
    return sorted(out)


def _docs_in_folders(folders) -> List[dict]:
    """Index entries (excluding camera frames) that live in the given folders."""
    fset = set(folders or [])
    out = []
    for d in load_document_index().get('documents', []):
        if d.get('doc_type') == 'camera' or str(d.get('filename', '')).startswith('camera_'):
            continue
        if _safe_rel_folder(d.get('folder', '')) in fset:
            out.append(d)
    return out


def _profile_signature(docs) -> str:
    """A stable hash of the folder's contents so the profile rebuilds only
    when documents are added/removed/changed."""
    items = sorted((d.get('filename', ''), d.get('hash', '')) for d in docs)
    return hashlib.md5(json.dumps(items).encode('utf-8')).hexdigest()


def _load_cached_profile() -> dict:
    try:
        with open(_PERSPECTIVE_PROFILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cached_profile(obj: dict):
    try:
        os.makedirs(os.path.dirname(_PERSPECTIVE_PROFILE_PATH), exist_ok=True)
        with open(_PERSPECTIVE_PROFILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=2)
    except Exception as e:
        print(f"   [PERSPECTIVE] could not save profile: {e}")


def _summarize_one_doc(filename: str, text: str) -> str:
    text = (text or "")[:8000]
    if not text.strip():
        return ""
    res = call_llm(
        [
            {"role": "system", "content": (
                f"You are analyzing one text by the scholar {BLUE_OWNER_NAME} to help "
                "build a profile of how he thinks and writes. In ~200 words, capture: "
                "his central arguments/claims, the key theoretical concepts he uses, the "
                "thinkers and traditions he engages, his method, and his characteristic "
                "voice and style. Be specific; quote a distinctive phrase or two."
            )},
            {"role": "user", "content": f"Text: {filename}\n\n{text}\n\nProfile notes for this text:"},
        ],
        include_tools=False, temperature=0.4, max_tokens=400,
    )
    ch = (res or {}).get('choices') or []
    return ((ch[0].get('message') or {}).get('content') or "").strip() if ch else ""


def build_perspective_profile(force: bool = False) -> dict:
    """Distill a worldview profile from the owner's publications folder via
    map-reduce summarization. Cached to disk; rebuilds only when the folder's
    contents change (or force=True). Returns the cached dict on any failure so
    a transient LLM hiccup never wipes a good profile."""
    with _perspective_lock:
        folders = _owner_publication_folders()
        docs = _docs_in_folders(folders)
        sig = _profile_signature(docs)
        cached = _load_cached_profile()

        # A hand-edited profile is authoritative: never auto-overwrite it on a
        # folder change. The user can hit "Regenerate" (force=True) to rebuild.
        if not force and cached.get('user_edited') and cached.get('profile'):
            return cached
        if not force and cached.get('signature') == sig and cached.get('profile') and docs:
            return cached
        if not docs:
            return cached or {}

        print(f"   [PERSPECTIVE] (re)building worldview profile from {len(docs)} doc(s) in {folders}...")
        notes = []
        for d in docs[:12]:
            fp = d.get('filepath', '')
            try:
                txt = extract_text_from_file(fp) if fp and os.path.exists(fp) else ''
            except Exception:
                txt = ''
            s = _summarize_one_doc(d.get('filename', ''), txt)
            if s:
                notes.append(f"[{d.get('filename', '')}]\n{s}")
                print(f"   [PERSPECTIVE] summarized {d.get('filename', '')}")

        if not notes:
            return cached or {}

        synth = call_llm(
            [
                {"role": "system", "content": (
                    f"You are building a profile of the scholar {BLUE_OWNER_NAME}'s "
                    "intellectual perspective — how he understands the world — from notes "
                    "on his published writing. Write a structured profile (500-800 words) "
                    "covering: (1) his core theoretical framework and commitments; (2) "
                    "recurring themes and central concepts; (3) the thinkers, traditions, "
                    "and interlocutors he works with; (4) his method and mode of argument; "
                    "(5) his political/ethical orientation; (6) his characteristic voice, "
                    "tone, and rhetorical style. Write it as a reference Blue can use to "
                    "think and write AS him. Be specific and concrete."
                )},
                {"role": "user", "content": "Notes from across his work:\n\n" + "\n\n".join(notes) + "\n\nWrite the profile:"},
            ],
            include_tools=False, temperature=0.5, max_tokens=1400,
        )
        ch = (synth or {}).get('choices') or []
        profile_text = ((ch[0].get('message') or {}).get('content') or "").strip() if ch else ""
        if not profile_text:
            return cached or {}

        obj = {
            "folders": folders,
            "signature": sig,
            "profile": profile_text,
            "source_docs": [d.get('filename', '') for d in docs],
            "generated_at": __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
        _save_cached_profile(obj)
        print(f"   [PERSPECTIVE] profile built ({len(profile_text)} chars) from {len(notes)} doc(s)")
        return obj


def get_perspective_profile() -> str:
    """The distilled worldview profile text, built/refreshed lazily."""
    try:
        return build_perspective_profile().get('profile') or ""
    except Exception as e:
        print(f"   [PERSPECTIVE] profile error: {e}")
        return _load_cached_profile().get('profile') or ""


def save_perspective_profile_text(text: str) -> dict:
    """Persist a hand-edited profile. Marks it user_edited so the auto-refresh
    won't overwrite it, and pins the signature to the current folder state so
    it's treated as fresh."""
    with _perspective_lock:
        obj = _load_cached_profile() or {}
        folders = _owner_publication_folders()
        docs = _docs_in_folders(folders)
        obj['profile'] = (text or "").strip()
        obj['folders'] = folders
        obj['signature'] = _profile_signature(docs)
        obj['user_edited'] = True
        obj['edited_at'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')
        obj.setdefault('source_docs', [d.get('filename', '') for d in docs])
        _save_cached_profile(obj)
        return obj


# "Write this in my voice / from my perspective" intent.
_PERSPECTIVE_PHRASES = (
    "from my perspective", "in my voice", "in my own voice", "in my style",
    "as i would", "as if i wrote", "as though i wrote", "write as me",
    "as me ", "from my standpoint", "from my point of view", "from my vantage",
    "the way i would write", "channel my perspective", "in my perspective",
    "from my own perspective", "as i would write", "like i would write",
    "in my own words", "speak as me", "speaking as me",
)
_PERSPECTIVE_WRITE_VERB = re.compile(
    r"\b(write|draft|compose|produce|pen|put\s+together|give\s+me|generate|"
    r"prepare|craft)\b", re.I)


def _wants_perspective_write(body: str) -> bool:
    bl = (body or "").lower()
    if not any(p in bl for p in _PERSPECTIVE_PHRASES):
        return False
    # Require an actual writing request so "from my perspective, that's wrong"
    # in normal conversation doesn't trigger it.
    return bool(_PERSPECTIVE_WRITE_VERB.search(bl)) or bool(_COMPOSITION_OUTPUT_RE.search(bl))


def _compose_in_alex_voice(issue: str) -> Optional[str]:
    """Write a first-person piece on `issue` AS the owner — grounded in his
    distilled perspective profile plus live passages from his own writing.
    Returns None if there's nothing of his to draw on."""
    folders = _owner_publication_folders()
    if not folders:
        return None
    profile = get_perspective_profile()
    sources, filenames = _gather_owner_work_sources(issue, folders)
    if not profile and not sources:
        return None

    print(f"   [PERSPECTIVE] composing in {BLUE_OWNER_NAME}'s voice "
          f"(profile={'yes' if profile else 'no'}, {len(filenames)} source doc(s))")

    sys_p = (
        f"You are writing AS {BLUE_OWNER_NAME}, in the first person and in his own "
        "voice — not about him. Adopt his theoretical perspective, his commitments, "
        "his characteristic concepts and rhetorical style. Below is a profile of how "
        "he thinks and writes (distilled from his published work) and passages from "
        "his actual writing. Use them to think and write as he would on the topic "
        "he's raised. Write in the first person ('I'); do NOT refer to him in the "
        "third person; do NOT mention being an AI or Blue; and do NOT fabricate "
        "quotations or citations. Produce a substantive piece of several paragraphs."
    )
    parts = []
    if profile:
        parts.append(f"PROFILE OF HIS PERSPECTIVE:\n{profile}")
    if sources:
        parts.append(f"PASSAGES FROM HIS OWN WRITING:\n{sources}")
    usr_p = (
        "\n\n".join(parts)
        + f"\n\nTOPIC / REQUEST (write on this, in the first person, as him):\n{issue}\n\nWrite the piece now:"
    )
    res = call_llm(
        [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
        include_tools=False, temperature=0.7, max_tokens=1800,
    )
    ch = (res or {}).get('choices') or []
    if not ch:
        return None
    return (((ch[0].get('message') or {}).get('content') or "").strip()) or None


def _build_email_reply(cand: Dict[str, Any]) -> tuple:
    """Produce (reply_body, attachment_paths) for one inbound email. Owner
    attachment + composition requests are handled deterministically (the
    model can't be trusted to actually attach, and the chatty reply prompt
    caps it at 150 words); everything else goes through the normal reply
    generator with no attachments."""
    headers = cand.get('headers') or []
    sender = cand.get('from', '')
    if _email_sender_is_owner(headers, sender):
        body = (cand.get('body') or cand.get('snippet') or '')[:2000]
        m = re.search(r'<(.+?)>', sender)
        reply_to = m.group(1) if m else sender
        att = _maybe_handle_owner_attachment(body, reply_to)
        if att is not None:
            return att
        # "Write this from my perspective / in my voice" — first-person piece
        # in Alex's voice, grounded in his publications. Checked before the
        # generic composition path since it's the more specific intent.
        if _wants_perspective_write(body):
            piece = _compose_in_alex_voice(body)
            if piece:
                return (f"Here's a piece in your voice:\n\n{piece}", [])
        composition = _maybe_handle_owner_composition(body)
        if composition:
            return composition, []
    return _generate_reply_for_email(cand), []


def _generate_reply_for_email(original: Dict[str, Any]) -> str:
    """Draft a reply body via the local LM Studio model. Returns plain text.

    Runs a small tool loop so Blue can actually browse a link or search
    the web when an email asks him to — but only with the read-only tools
    in _EMAIL_SAFE_TOOL_NAMES, never anything outbound or state-changing.
    """
    sender = original.get('from', 'someone')
    subject = original.get('subject', '(no subject)')
    body = (original.get('body') or original.get('snippet') or '')[:2000]
    headers = original.get('headers') or []

    # Trusted owner mail (verified) gets full tool access; everyone else
    # gets the read-only public-info whitelist.
    is_owner = _email_sender_is_owner(headers, sender)
    if is_owner:
        # Owner asked Blue to email a third party? Do it deterministically —
        # the model otherwise just writes the message back to the owner.
        outbound = _maybe_handle_owner_outbound(body)
        if outbound:
            return outbound
        tools_payload = _email_owner_tools()
        print(f"   [AUTO-REPLY] owner-verified sender {sender!r} → full tool access")
        capability_note = (
            "This email is from Alex himself (verified sender). You may take "
            "ANY action he asks — browse, search, send emails on his behalf, "
            "control the lights, set reminders, manage the house — exactly "
            "as you would in a normal in-person conversation. Use whatever "
            "tools the request needs."
        )
    else:
        tools_payload = _email_safe_tools()
        capability_note = (
            "You CAN browse the web and look things up: if the email asks you "
            "to visit a website, summarise a page, or look something up, use "
            "the browse_website or web_search tool and answer from what you "
            "found. Never claim you can't browse the internet — you can. But "
            "you must NOT send emails, control the house, set reminders, or "
            "open Alex's private files for this sender — if they ask for "
            "something like that, say you'll pass it along to Alex."
        )

    system_prompt = (
        f"You are Blue, Alex's friendly robot companion. Alex uses he/him "
        f"pronouns — refer to him as he/him, never she/her. You have your "
        f"own gmail inbox at {BLUE_OWN_EMAIL}, and someone has written to "
        f"you there. Your job is to reply warmly and personally AS BLUE — "
        f"engage with what they actually said, acknowledge it, share a "
        f"thought, ask a follow-up if it fits. Keep the reply short "
        f"(under 150 words), conversational, and sign it 'Blue'.\n\n"
        f"{capability_note}\n\n"
        f"Do NOT refuse to engage. Do NOT say things like 'I'm just a "
        f"local assistant and can't process personal messages' — talking "
        f"IS what you do, this email arrived in your inbox specifically "
        f"so you would answer it. Don't invent facts about Alex or claim "
        f"things you don't know."
    )
    user_prompt = (
        f"Email from {sender}\n"
        f"Subject: {subject}\n"
        f"---\n"
        f"{body}\n"
        f"---\n"
        f"Write a short reply directly to the sender. Output only the reply body — "
        f"no subject line, no headers, no quoted original."
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Inject Blue's long-term memory (family names + ages, location,
    # preferences, relevant past notes) so the email Blue answers from the
    # SAME knowledge as the chat Blue. Without this the model invents facts
    # — e.g. wrong daughter ages — because the bespoke email prompt never
    # carried the facts block the chat path splices in.
    try:
        if ENHANCED_MEMORY_AVAILABLE and memory_system:
            mem_anchor = [{"role": "user", "content": f"{subject}\n{body}"}]
            for ctx in (memory_system.build_context(mem_anchor, user_name="Alex") or []):
                messages.append(ctx)
            print("   [AUTO-REPLY] injected long-term memory context")
    except Exception as e:
        print(f"   [AUTO-REPLY] memory context error: {e}")

    messages.append({"role": "user", "content": user_prompt})

    def _final_text() -> str:
        result = call_llm(
            messages + [{"role": "user", "content": "[Write the final reply now. No more tools.]"}],
            include_tools=False,
            temperature=0.7,
            max_tokens=400,
        )
        choices = (result or {}).get('choices') or []
        if not choices:
            return ""
        return ((choices[0].get('message') or {}).get('content') or "").strip()

    def _permitted(tool_name: str) -> bool:
        # Owner mail: anything except the recursion-risk tools. Everyone
        # else: only the read-only whitelist.
        if is_owner:
            return tool_name not in _EMAIL_OWNER_EXCLUDE
        return tool_name in _EMAIL_SAFE_TOOL_NAMES

    executed = set()
    forced = 0
    force_next = None   # when set, restrict the next turn to this one tool

    # DETERMINISTIC PRE-EXECUTION (mirrors the chat path). The local model
    # is unreliable at self-calling tools inside the email loop — it tends
    # to narrate "done!" without ever emitting the call (this is why
    # "set the lights to galaxy" worked in chat but not by email). So run
    # the SAME tool selector chat trusts; if it confidently picks a
    # concrete action tool the sender is allowed to trigger, execute it up
    # front with its extracted params, then tell the model it's already
    # done so it just confirms. Browse/search/email tools stay model-driven
    # (their params come from the message, not the selector).
    # Tools whose params come from the message text (not the selector), so
    # they stay model-driven. search_documents is NOT here: the selector
    # extracts the query, so library lookups pre-execute deterministically
    # exactly like the chat path — the local model is unreliable at
    # self-calling it inside the email loop.
    _PREEXEC_SKIP = {
        "read_gmail", "send_gmail", "reply_gmail", "auto_reply_emails",
        "browse_website", "web_search",
    }
    try:
        sel = TOOL_SELECTOR.select_tool(f"{subject}. {body}") if "TOOL_SELECTOR" in globals() else None
        prim = getattr(sel, "primary_tool", None) if sel else None
        if prim and getattr(prim, "tool_name", None):
            tname = prim.tool_name
            tconf = float(getattr(prim, "confidence", 0.0) or 0.0)
            tparams = getattr(prim, "extracted_params", {}) or {}
            if tconf >= 0.8 and tname not in _PREEXEC_SKIP and _permitted(tname):
                print(f"   [AUTO-REPLY] selector pre-exec {tname}({tparams}) conf={tconf:.2f}")
                tresult = execute_tool(tname, tparams)
                executed.add(tname)
                _rs = tresult if isinstance(tresult, str) else json.dumps(tresult)
                print(f"   [AUTO-REPLY] pre-exec result: {_rs[:200]}")
                if tname == "capture_camera":
                    # The capture queued an image that's injected right after
                    # this block. The reply should DESCRIBE what's in it, not
                    # just say "photo taken", so don't tell the model to merely
                    # confirm — _inject_pending_vision carries the look-prompt.
                    messages.append({
                        "role": "system",
                        "content": (
                            "[You already opened your camera. The image you "
                            "captured follows — look at it and describe what you "
                            "actually see, then answer the sender. Do NOT call "
                            "capture_camera again.]"
                        ),
                    })
                else:
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[You ALREADY handled this request by running {tname}. "
                            f"Result: {_rs[:400]}. Do NOT call it again — just confirm "
                            f"the outcome naturally in your reply, based on that result.]"
                        ),
                    })
    except Exception as e:
        print(f"   [AUTO-REPLY] selector pre-exec error: {e}")

    # A deterministic capture_camera (above) queued an image — show it to
    # the model before it drafts, so the reply is grounded in what Blue saw.
    _inject_pending_vision(messages)

    try:
        # Up to a few tool round-trips (browse → read → act → confirm),
        # then a plain text reply.
        for _ in range(5):
            if force_next:
                # Narrow the tool set to just the claimed tool so the local
                # model can't dodge calling it again — its only option is
                # that tool or plain text, and the instruction demands the call.
                turn_tools = [
                    t for t in (tools_payload or [])
                    if (t.get('function', {}) or {}).get('name') == force_next
                ]
            else:
                turn_tools = tools_payload
            force_next = None

            result = call_llm(
                messages,
                tools_override=turn_tools,
                tool_choice="auto",
                temperature=0.7,
                max_tokens=600,
            )
            choices = (result or {}).get('choices') or []
            if not choices:
                return ""
            msg = choices[0].get('message') or {}
            tool_calls = msg.get('tool_calls') or []

            if not tool_calls:
                content = (msg.get('content') or "").strip()
                # HALLUCINATION GUARD: the model often writes "Done! lights
                # set to galaxy" as plain text without ever calling the
                # tool. If the reply claims an action whose tool is
                # permitted for this sender and was never actually run,
                # force the real call instead of sending a lie.
                claimed = detect_hallucinated_action(content)
                tool_exists = any(
                    (t.get('function', {}) or {}).get('name') == claimed
                    for t in (tools_payload or [])
                )
                if (claimed and claimed not in executed and _permitted(claimed)
                        and tool_exists and forced < 2):
                    forced += 1
                    force_next = claimed
                    print(f"   [AUTO-REPLY] reply claims '{claimed}' but no tool ran — forcing the real call")
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You said you did that, but you never actually "
                            f"called a tool, so nothing happened. Call the "
                            f"{claimed} tool now to really do it, then confirm "
                            f"in one short sentence."
                        ),
                    })
                    continue
                if not executed:
                    print(f"   [AUTO-REPLY] model returned text with NO tool call "
                          f"(claim-detected={claimed!r}); reply: {content[:120]!r}")
                return content

            messages.append({
                "role": "assistant",
                "content": msg.get('content') or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = tc.get('function') or {}
                name = fn.get('name', '')
                try:
                    targs = json.loads(fn.get('arguments') or '{}')
                except Exception:
                    targs = {}
                if _permitted(name):
                    print(f"   [AUTO-REPLY] tool {name}({targs})")
                    tool_result = execute_tool(name, targs)
                    executed.add(name)
                    _rstr = tool_result if isinstance(tool_result, str) else json.dumps(tool_result)
                    print(f"   [AUTO-REPLY] tool {name} result: {_rstr[:200]}")
                else:
                    tool_result = json.dumps({
                        "error": f"{name} is not permitted in autonomous email replies."
                    })
                    print(f"   [AUTO-REPLY] blocked tool {name} (sender not owner-verified)")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get('id', ''),
                    "name": name,
                    "content": tool_result if isinstance(tool_result, str) else json.dumps(tool_result),
                })
            # If any tool in this batch (e.g. capture_camera) queued an
            # image, inject it so the next turn can describe what Blue saw.
            _inject_pending_vision(messages)
        # Used up the tool budget — force a final text answer.
        return _final_text()
    except Exception as e:
        print(f"   [AUTO-REPLY] LLM error generating reply: {e}")
        return ""


def _execute_auto_reply_inbox(args: Dict[str, Any]) -> str:
    """Scan recent inbox, find emails written to Blue, and reply to each.

    Args (all optional):
        lookback_hours: how far back to scan (default 24, max 168)
        max_replies: cap on how many to send this run (default 5, max 20)
        dry_run: report what *would* be sent without sending
    """
    if not GMAIL_AVAILABLE:
        return json.dumps({"success": False, "error": "Gmail libraries not installed."})

    try:
        lookback = max(1, min(int(args.get('lookback_hours', 24) or 24), 168))
    except (TypeError, ValueError):
        lookback = 24
    try:
        max_replies = max(1, min(int(args.get('max_replies', 5) or 5), 20))
    except (TypeError, ValueError):
        max_replies = 5
    dry_run = bool(args.get('dry_run', False))

    try:
        service = get_gmail_service()
        label_id = _get_or_create_blue_label(service)

        query = (
            f"in:inbox newer_than:{lookback}h "
            f"-category:promotions -category:social -category:updates -category:forums "
            f"-label:{BLUE_REPLIED_LABEL}"
        )

        list_resp = service.users().messages().list(
            userId='me', q=query, maxResults=50,
        ).execute()
        message_refs = list_resp.get('messages', [])
        print(f"   [AUTO-REPLY] query={query!r} → {len(message_refs)} message(s)")

        scanned = 0
        skipped_filter = []
        candidates = []
        for ref in message_refs:
            msg_data = service.users().messages().get(
                userId='me', id=ref['id'], format='full',
            ).execute()
            scanned += 1
            headers = msg_data['payload']['headers']
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
            if _should_skip_sender(sender, headers):
                # Be explicit about WHY so silent-skip cases are debuggable.
                reason = "self-address" if any(
                    a.lower() in BLUE_SELF_ADDRESSES
                    for a in _EMAIL_ADDR_RE.findall(sender)
                ) else "automated/list/no-reply"
                print(f"   [AUTO-REPLY] skip {ref['id']} from {sender!r}: {reason}")
                skipped_filter.append({'id': ref['id'], 'from': sender, 'reason': reason})
                continue

            body_text = ""
            payload = msg_data['payload']
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain' and 'data' in part.get('body', {}):
                        body_text = base64.urlsafe_b64decode(
                            part['body']['data']
                        ).decode('utf-8', errors='replace')
                        break
            elif 'body' in payload and 'data' in payload['body']:
                body_text = base64.urlsafe_b64decode(
                    payload['body']['data']
                ).decode('utf-8', errors='replace')

            snippet = msg_data.get('snippet', '')

            candidates.append({
                'id': ref['id'],
                'thread_id': msg_data.get('threadId'),
                'headers': headers,
                'from': sender,
                'subject': subject,
                'body': body_text,
                'snippet': snippet,
            })
            if len(candidates) >= max_replies:
                break

        sent = []
        skipped = []
        errors = []

        for cand in candidates:
            try:
                reply_body, reply_attachments = _build_email_reply(cand)
                if not reply_body:
                    skipped.append({'id': cand['id'], 'reason': 'LLM produced no reply'})
                    continue

                headers = cand['headers']
                message_id_header = next(
                    (h['value'] for h in headers if h['name'].lower() == 'message-id'),
                    '',
                )
                m = re.search(r'<(.+?)>', cand['from'])
                reply_to = m.group(1) if m else cand['from']
                reply_subject = (
                    cand['subject'] if cand['subject'].lower().startswith('re:')
                    else f"Re: {cand['subject']}"
                )

                if dry_run:
                    sent.append({
                        'dry_run': True,
                        'to': reply_to,
                        'subject': reply_subject,
                        'reply_preview': reply_body[:300],
                        'attachments': [os.path.basename(a) for a in (reply_attachments or [])],
                    })
                    continue

                reply_message = MIMEMultipart()
                reply_message['To'] = reply_to
                reply_message['Subject'] = reply_subject
                reply_message['Bcc'] = BLUE_BCC_EMAIL
                if message_id_header:
                    reply_message['In-Reply-To'] = message_id_header
                    reply_message['References'] = message_id_header
                reply_message.attach(MIMEText(reply_body, 'plain', 'utf-8'))

                # Attach any library documents the request asked for.
                for ap in (reply_attachments or []):
                    try:
                        if not os.path.exists(ap):
                            alt = os.path.join(DOCUMENTS_FOLDER, os.path.basename(ap))
                            if os.path.exists(alt):
                                ap = alt
                            else:
                                print(f"   [AUTO-REPLY] attachment missing: {ap}")
                                continue
                        ctype, _enc = mimetypes.guess_type(ap)
                        maintype, subtype = (ctype or 'application/octet-stream').split('/', 1)
                        with open(ap, 'rb') as _f:
                            part = MIMEBase(maintype, subtype)
                            part.set_payload(_f.read())
                        encoders.encode_base64(part)
                        part.add_header(
                            'Content-Disposition', 'attachment',
                            filename=os.path.basename(ap),
                        )
                        reply_message.attach(part)
                        print(f"   [AUTO-REPLY] attached {os.path.basename(ap)}")
                    except Exception as _ae:
                        print(f"   [AUTO-REPLY] attach failed for {ap}: {_ae}")

                raw = base64.urlsafe_b64encode(reply_message.as_bytes()).decode('utf-8')
                sent_msg = service.users().messages().send(
                    userId='me',
                    body={'raw': raw, 'threadId': cand['thread_id']},
                ).execute()

                # Mark the original as read + tag it so we never reply twice.
                modify_body = {'removeLabelIds': ['UNREAD']}
                if label_id:
                    modify_body['addLabelIds'] = [label_id]
                try:
                    service.users().messages().modify(
                        userId='me', id=cand['id'], body=modify_body,
                    ).execute()
                except Exception as e:
                    print(f"   [AUTO-REPLY] label/unread update failed for {cand['id']}: {e}")

                sent.append({
                    'to': reply_to,
                    'subject': reply_subject,
                    'reply_id': sent_msg['id'],
                    'thread_id': cand['thread_id'],
                    'reply_preview': reply_body[:300],
                })
                print(f"   [AUTO-REPLY] replied to {reply_to}: {reply_subject}")

            except Exception as e:
                errors.append({'id': cand['id'], 'error': str(e)})
                print(f"   [AUTO-REPLY] error replying to {cand['id']}: {e}")

        return json.dumps({
            'success': True,
            'scanned': scanned,
            'candidates_found': len(candidates),
            'replies_sent': len(sent),
            'dry_run': dry_run,
            'sent': sent,
            'skipped': skipped,
            'skipped_by_filter': skipped_filter,
            'errors': errors if errors else None,
            'lookback_hours': lookback,
            'note': (
                f"AUTO-REPLY DRY RUN — {len(sent)} email(s) would be sent."
                if dry_run else
                f"AUTO-REPLY DONE — {len(sent)} email(s) sent, each BCC'd to {BLUE_BCC_EMAIL}."
            ),
        }, indent=2)

    except Exception as e:
        return json.dumps({'success': False, 'error': str(e)})


_EMAIL_AUTOREPLY_THREAD = None


def _start_email_autoreply_loop():
    """Idempotent: start the background thread that periodically auto-replies
    to mail written to Blue. Interval is set by env var
    BLUE_EMAIL_AUTOREPLY_INTERVAL_MIN (default 2, min 1)."""
    global _EMAIL_AUTOREPLY_THREAD
    if _EMAIL_AUTOREPLY_THREAD is not None:
        return
    try:
        interval_min = max(1, int(os.environ.get("BLUE_EMAIL_AUTOREPLY_INTERVAL_MIN", "2")))
    except ValueError:
        interval_min = 2
    interval_sec = interval_min * 60
    lookback_h = max(1, (interval_min * 2 + 59) // 60)

    def _loop():
        import time as _t
        # Brief startup delay so the first scan doesn't fight server boot.
        _t.sleep(60)
        # On first run, print which gmail account the OAuth token actually
        # points at — surfaces token-misconfigured-against-wrong-inbox bugs.
        try:
            svc = get_gmail_service()
            profile = svc.users().getProfile(userId='me').execute()
            actual = profile.get('emailAddress', '?')
            tag = "OK" if actual.lower() == BLUE_OWN_EMAIL.lower() else "WRONG ACCOUNT"
            print(
                f"[AUTO-REPLY] scanning inbox of {actual} "
                f"(expected {BLUE_OWN_EMAIL}) — {tag}",
                flush=True,
            )
        except Exception as e:
            print(f"[AUTO-REPLY] could not look up auth profile: {e}", flush=True)

        while True:
            try:
                result = _execute_auto_reply_inbox({
                    'lookback_hours': lookback_h,
                    'max_replies': 5,
                })
                try:
                    obj = json.loads(result)
                    # One line per poll so it's obvious the loop is alive
                    # even when no replies were sent.
                    print(
                        f"[AUTO-REPLY] poll: scanned={obj.get('scanned', 0)}, "
                        f"candidates={obj.get('candidates_found', 0)}, "
                        f"sent={obj.get('replies_sent', 0)}, "
                        f"skipped={len(obj.get('skipped_by_filter') or [])}, "
                        f"errors={len(obj.get('errors') or [])}",
                        flush=True,
                    )
                except Exception:
                    pass
            except Exception as e:
                print(f"[AUTO-REPLY] loop error: {e}", flush=True)
            _t.sleep(interval_sec)

    import threading as _th
    _EMAIL_AUTOREPLY_THREAD = _th.Thread(
        target=_loop, daemon=True, name="email-autoreply",
    )
    _EMAIL_AUTOREPLY_THREAD.start()
    print(
        f"[OK] Email auto-reply loop started "
        f"(every {interval_min} min, BCC -> {BLUE_BCC_EMAIL})",
        flush=True,
    )


# ===== END GMAIL TOOLS =====


def execute_tool(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """
    Execute requested tool with enhanced error handling and state tracking.
    v8 ENHANCED: Better state tracking, timing, retry on transient failures.
    """
    import time
    start_time = time.time()
    state = get_conversation_state()
    
    print(f"[TOOL] Executing tool: {tool_name}")
    print(f"   Arguments: {json.dumps(tool_args, indent=2)}")
    
    # v8: Track execution attempt
    max_retries = 2 if tool_name in ['web_search', 'read_gmail', 'browse_website'] else 1
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = _execute_tool_internal(tool_name, tool_args)
            elapsed = time.time() - start_time
            
            # Record successful execution with args
            state.record_tool_use(
                tool_name, 
                success=True, 
                pattern=f"{tool_name}:{list(tool_args.keys())}",
                args=tool_args
            )
            state.last_tool_result = truncate_text(result, 500)
            
            # v8: Update topic based on tool
            if tool_name == 'play_music':
                state.push_topic('music')
            elif tool_name in ['control_lights', 'music_visualizer']:
                state.push_topic('lights')
            elif tool_name in ['read_gmail', 'send_gmail', 'reply_gmail']:
                state.push_topic('email')
            
            print(f"   [OK] {tool_name} completed in {elapsed:.2f}s")
            return result
            
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = 1 * (attempt + 1)
                print(f"   [RETRY] {tool_name} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            continue
    
    # All retries failed
    elapsed = time.time() - start_time
    error_msg = str(last_error)
    
    # Record failed execution
    state.record_tool_use(tool_name, success=False, pattern=f"{tool_name}:error", args=tool_args)
    
    print(f"   [ERROR] {tool_name} failed after {elapsed:.2f}s: {error_msg}")
    
    # Provide helpful error message
    error_response = {
        "success": False,
        "error": error_msg,
        "tool": tool_name,
        "suggestion": _get_error_suggestion(tool_name, error_msg)
    }
    
    return json.dumps(error_response)


def _get_error_suggestion(tool_name: str, error: str) -> str:
    """Get a helpful suggestion for common errors."""
    error_lower = error.lower()
    
    if "timeout" in error_lower or "timed out" in error_lower:
        return "The service took too long to respond. Try again in a moment."
    elif "connection" in error_lower or "network" in error_lower:
        return "Network connection issue. Check your internet connection."
    elif "not found" in error_lower:
        return "The requested resource wasn't found. Check the name or path."
    elif "permission" in error_lower or "unauthorized" in error_lower:
        return "Permission denied. You may need to re-authenticate."
    elif "rate limit" in error_lower:
        return "Too many requests. Please wait a moment before trying again."
    elif tool_name == "play_music":
        return "Try a different artist name or check if YouTube Music is running."
    elif tool_name == "control_lights":
        return "Check if the Philips Hue bridge is connected and accessible."
    elif tool_name in ["read_gmail", "send_gmail", "reply_gmail"]:
        return "Gmail authentication may have expired. Check credentials."
    else:
        return "Try rephrasing your request or provide more details."


def _execute_tool_internal(tool_name: str, tool_args: Dict[str, Any]) -> str:
    """Internal tool execution - called by execute_tool wrapper."""
    
    if tool_name == "play_music":
        query = tool_args.get("query", "")
        action = tool_args.get("action", "play")
        service = tool_args.get("service", "youtube_music")

        if action == "search":
            result = search_music_info(query)
        else:
            result = play_music(query, service)
        print(f"   [OK] Music action completed")
        return result

    elif tool_name == "control_music":
        action = tool_args.get("action", "")
        result = control_music(action)
        print(f"   [OK] Music control executed")
        return result

    elif tool_name == "music_visualizer":
        action = tool_args.get("action", "start")

        if action == "start":
            duration = tool_args.get("duration", 300)
            style = tool_args.get("style", "party")
            result = start_music_visualizer(duration, style)
        elif action == "stop":
            result = stop_music_visualizer()
        else:
            result = f"Unknown visualizer action: {action}"

        print(f"   [OK] Visualizer action completed")
        return result

    elif tool_name == "control_lights":
        result = execute_light_control(
            tool_args.get("action"),
            tool_args.get("light_name"),
            tool_args.get("brightness"),
            tool_args.get("color"),
            tool_args.get("mood")
        )
        print(f"   [OK] Light control executed")
        return result

    elif tool_name == "search_documents":
        global _vision_queue
        query = tool_args.get("query", "")
        max_results = tool_args.get("max_results", 3)
        result = _search_documents_guarded(query, max_results)
        print(f"   [OK] Document search completed")

        # Check if result contains images (special JSON format)
        try:
            result_data = json.loads(result)
            if isinstance(result_data, dict) and result_data.get("_type") == "document_search_with_images":
                images = result_data.get("images", [])
                text_docs = result_data.get("text_documents", [])

                # Store images globally so they can be injected into next LLM call
                for img in images:
                    _vision_queue.add_image(
                        filepath=img['filepath'],
                        filename=img['filename'],
                        is_camera=False
                    )
                print(f"   [VISION] Stored {len(images)} image(s) for vision model")

                # Build text response
                response_parts = []
                if images:
                    image_names = [img['filename'] for img in images]
                    response_parts.append(f"Found {len(images)} image(s): {', '.join(image_names)}")
                    response_parts.append("(Images will be shown to vision model in next response)")

                if text_docs:
                    response_parts.append("\n\nText documents found:\n\n" + "\n---\n\n".join(text_docs))

                return "\n".join(response_parts) if response_parts else "Found documents."
        except (json.JSONDecodeError, TypeError):
            # Not JSON or not our special format - return as-is
            pass

        return result

    elif tool_name == "view_image":
        filename = tool_args.get("filename")
        query = tool_args.get("query")
        result = view_image(filename=filename, query=query)
        print(f"   [OK] Image view requested")
        return result

    elif tool_name == "capture_camera":
        result = capture_camera_image()
        print(f"   [OK] Camera capture completed")
        return result

    elif tool_name == "recall_visual_memory":
        if not VISUAL_MEMORY_AVAILABLE:
            return json.dumps({"error": "Visual memory not available"})
        try:
            vm = get_visual_memory()
            query = tool_args.get("query")
            hours = tool_args.get("hours", 24)

            if query:
                observations = vm.search_observations(query, limit=10)
                search_type = f"search for '{query}'"
            else:
                observations = vm.get_visual_timeline(hours)
                search_type = f"timeline (last {hours}h)"

            if not observations:
                return json.dumps({
                    "success": True,
                    "search_type": search_type,
                    "message": "No visual memories found for that query.",
                    "observations": []
                })

            # Format observations for the LLM
            formatted = []
            for obs in observations:
                entry = {
                    "timestamp": obs.get("timestamp", ""),
                    "description": obs.get("scene_description", ""),
                    "location": obs.get("location"),
                    "people": obs.get("people_present"),
                    "objects": obs.get("notable_objects"),
                    "has_image": bool(obs.get("image_path"))
                }
                formatted.append(entry)

            # Also get scene change info
            changes = vm.detect_scene_changes("")
            result = {
                "success": True,
                "search_type": search_type,
                "total_memories": len(formatted),
                "observations": formatted,
                "_instruction": "Summarize these visual memories naturally. Tell the user what you remember seeing, when, and where. If they asked about changes, compare observations."
            }
            if changes.get("has_previous"):
                result["last_seen_ago"] = changes["time_since"]
            print(f"   [OK] Visual memory recall: {len(formatted)} observations ({search_type})")
            return json.dumps(result)
        except Exception as e:
            print(f"   [ERROR] Visual memory recall failed: {e}")
            return json.dumps({"error": str(e)})

    elif tool_name == "get_weather":
        result = get_weather_data(tool_args.get("location", ""))
        print(f"   [OK] Weather retrieved")
        return result

    elif tool_name == "web_search":
        result = execute_web_search(tool_args.get("query", ""))
        print(f"   [OK] Search completed")
        return result

    elif tool_name == "run_javascript":
        try:
            import js2py
            result = js2py.eval_js(tool_args.get("code", ""))
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {str(e)}"

    elif tool_name == "create_document":
        filename = tool_args.get("filename", "")
        content = tool_args.get("content", "")
        file_type = tool_args.get("file_type", "txt")
        result = create_document_file(filename, content, file_type)
        print(f"   [OK] Document created")
        return result

    elif tool_name == "browse_website":
        print(f"   [DEBUG] Calling _execute_browse_website...")
        result = _execute_browse_website(tool_args)
        print(f"   [DEBUG] Got result, length: {len(result)} chars")
        # Parse the result to check success
        try:
            result_obj = json.loads(result)
            if result_obj.get("success"):
                print(f"   [OK] Browse completed - fetched {len(result_obj.get('text', ''))} chars")
            else:
                print(f"   [ERROR] Browse failed: {result_obj.get('error', 'Unknown error')}")
        except Exception:
            pass
        return result

    elif tool_name == "read_gmail":
        result = _execute_read_gmail(tool_args)
        # Add operation type to help Blue understand what just happened
        try:
            result_obj = json.loads(result)
            result_obj["_operation_type"] = "READ_EMAIL"
            result_obj["_instruction"] = "You just READ emails. User asked to check/read, NOT to reply or send."
            result = json.dumps(result_obj)
        except Exception:
            pass
        print(f"   [OK] Gmail READ completed")
        return result

    elif tool_name == "send_gmail":
        result = _execute_send_gmail(tool_args)
        # Add operation type to help Blue understand what just happened
        try:
            result_obj = json.loads(result)
            result_obj["_operation_type"] = "SEND_EMAIL"
            result_obj["_instruction"] = "You just SENT a new email. User asked to send, NOT to read or reply."
            result = json.dumps(result_obj)
        except Exception:
            pass
        print(f"   [OK] Gmail SEND completed")
        return result

    elif tool_name == "reply_gmail":
        result = _execute_reply_gmail(tool_args)
        # Add operation type to help Blue understand what just happened
        try:
            result_obj = json.loads(result)
            result_obj["_operation_type"] = "REPLY_EMAIL"
            result_obj["_instruction"] = "You just REPLIED to emails. User asked to reply/respond, NOT to just read."
            result = json.dumps(result_obj)
        except Exception:
            pass
        print(f"   [OK] Gmail REPLY completed")
        return result

    elif tool_name == "auto_reply_emails":
        result = _execute_auto_reply_inbox(tool_args)
        try:
            result_obj = json.loads(result)
            result_obj["_operation_type"] = "AUTO_REPLY_EMAILS"
            result_obj["_instruction"] = (
                "You just scanned Blue's own gmail inbox "
                "(alevantresearch@gmail.com) and sent autonomous replies "
                "to every personal email there. Summarise to the user: "
                "how many replies were sent, who they went to, and the "
                "subject lines. Note each reply is BCC'd to Alex at "
                "alevant1905@gmail.com so he can read the full text "
                "there. State ONLY what the tool result actually says — "
                "do NOT speculate about Blue's capabilities and do NOT "
                "claim Blue cannot do something the tool just did. Blue's "
                "inbox is alevantresearch@gmail.com (NOT alevant1905 or "
                "alevant@yorku.ca — those are Alex's addresses)."
            )
            result = json.dumps(result_obj)
        except Exception:
            pass
        print(f"   [OK] Gmail AUTO-REPLY completed")
        return result


    # ===== Enhanced Tools Handlers =====
    elif tool_name == "create_reminder" and ENHANCED_TOOLS_AVAILABLE:
        result = CalendarManager.create_reminder(**tool_args)
        print(f"   [OK] Reminder created")
        return json.dumps(result)

    elif tool_name == "get_upcoming_reminders" and ENHANCED_TOOLS_AVAILABLE:
        result = CalendarManager.get_upcoming_reminders(**tool_args)
        print(f"   [OK] Retrieved reminders")
        return json.dumps(result)

    elif tool_name == "complete_reminder" and ENHANCED_TOOLS_AVAILABLE:
        result = CalendarManager.complete_reminder(**tool_args)
        print(f"   [OK] Reminder completed")
        return json.dumps(result)

    elif tool_name == "cancel_reminder" and ENHANCED_TOOLS_AVAILABLE:
        result = CalendarManager.cancel_reminder(**tool_args)
        print(f"   [OK] Reminder cancel attempt: success={result.get('success')}")
        return json.dumps(result)

    elif tool_name == "create_task" and ENHANCED_TOOLS_AVAILABLE:
        result = TaskManager.create_task(**tool_args)
        print(f"   [OK] Task created")
        return json.dumps(result)

    elif tool_name == "get_tasks" and ENHANCED_TOOLS_AVAILABLE:
        result = TaskManager.get_tasks(**tool_args)
        print(f"   [OK] Retrieved tasks")
        return json.dumps(result)

    elif tool_name == "complete_task" and ENHANCED_TOOLS_AVAILABLE:
        result = TaskManager.complete_task(**tool_args)
        print(f"   [OK] Task completed")
        return json.dumps(result)

    elif tool_name == "create_note" and ENHANCED_TOOLS_AVAILABLE:
        result = NoteManager.create_note(**tool_args)
        print(f"   [OK] Note saved")
        return json.dumps(result)

    elif tool_name == "search_notes" and ENHANCED_TOOLS_AVAILABLE:
        result = NoteManager.search_notes(**tool_args)
        print(f"   [OK] Note search completed")
        return json.dumps(result)

    elif tool_name == "set_timer" and ENHANCED_TOOLS_AVAILABLE:
        result = TimerManager.set_timer(**tool_args)
        print(f"   [OK] Timer set")
        return json.dumps(result)

    elif tool_name == "check_timers" and ENHANCED_TOOLS_AVAILABLE:
        result = TimerManager.check_timers()
        print(f"   [OK] Timer status checked")
        return json.dumps(result)

    elif tool_name == "get_system_info" and ENHANCED_TOOLS_AVAILABLE:
        result = SystemController.get_system_info()
        print(f"   [OK] System info retrieved")
        return json.dumps(result)

    elif tool_name == "take_screenshot" and ENHANCED_TOOLS_AVAILABLE:
        result = SystemController.take_screenshot(**tool_args)
        print(f"   [OK] Screenshot captured")
        return json.dumps(result)

    elif tool_name == "launch_application" and ENHANCED_TOOLS_AVAILABLE:
        result = SystemController.launch_application(**tool_args)
        print(f"   [OK] Application launched")
        return json.dumps(result)

    elif tool_name == "set_volume" and ENHANCED_TOOLS_AVAILABLE:
        result = SystemController.set_volume(**tool_args)
        print(f"   [OK] Volume set")
        return json.dumps(result)

    elif tool_name == "list_files":
        if ENHANCED_TOOLS_AVAILABLE:
            result = FileOperations.list_files(**tool_args)
            print(f"   [OK] Files listed")
            return json.dumps(result)
        else:
            return json.dumps({
                "success": False,
                "message": "File system operations are not available. Use search_documents to access uploaded documents."
            })

    elif tool_name == "read_file":
        if ENHANCED_TOOLS_AVAILABLE:
            result = FileOperations.read_file(**tool_args)
            print(f"   [OK] File read")
            return json.dumps(result)
        else:
            return json.dumps({
                "success": False,
                "message": "File reading is not available. Use search_documents to read uploaded documents."
            })

    elif tool_name == "write_file" and ENHANCED_TOOLS_AVAILABLE:
        result = FileOperations.write_file(**tool_args)
        print(f"   [OK] File written")
        return json.dumps(result)

    elif tool_name == "get_file_info" and ENHANCED_TOOLS_AVAILABLE:
        result = FileOperations.get_file_info(**tool_args)
        print(f"   [OK] File info retrieved")
        return json.dumps(result)

    elif tool_name == "story_prompt" and ENHANCED_TOOLS_AVAILABLE:
        result = StorytellingTools.story_prompt(**tool_args)
        print(f"   [OK] Story prompt generated")
        return json.dumps(result)

    elif tool_name == "educational_activity" and ENHANCED_TOOLS_AVAILABLE:
        result = StorytellingTools.educational_activity(**tool_args)
        print(f"   [OK] Activity suggested")
        return json.dumps(result)

    elif tool_name == "get_local_time" and ENHANCED_TOOLS_AVAILABLE:
        result = LocationServices.get_local_time()
        print(f"   [OK] Local time retrieved")
        return json.dumps(result)

    elif tool_name == "get_sunrise_sunset" and ENHANCED_TOOLS_AVAILABLE:
        result = LocationServices.get_sunrise_sunset()
        print(f"   [OK] Sunrise/sunset times retrieved")
        return json.dumps(result)

    elif tool_name == "remember_person" and VISUAL_MEMORY_AVAILABLE:
        name = tool_args.get("name", "")
        appearance = tool_args.get("appearance", "")
        relationship = tool_args.get("relationship", "")
        notes = tool_args.get("notes", "")

        try:
            vm = get_visual_memory()
            vm.add_person(
                name=name,
                typical_appearance=appearance,
                relationship=relationship,
                notes=notes
            )
            print(f"   [OK] Remembered person: {name}")
            return json.dumps({
                "success": True,
                "message": f"I'll remember {name}. Next time I see them through my camera, I'll recognize them."
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to remember person: {str(e)}"
            })

    elif tool_name == "remember_place" and VISUAL_MEMORY_AVAILABLE:
        name = tool_args.get("name", "")
        description = tool_args.get("description", "")
        typical_contents = tool_args.get("typical_contents", "")
        notes = tool_args.get("notes", "")

        try:
            vm = get_visual_memory()
            vm.add_place(
                name=name,
                description=description,
                typical_contents=typical_contents,
                notes=notes
            )
            print(f"   [OK] Remembered place: {name}")
            return json.dumps({
                "success": True,
                "message": f"I'll remember {name}. Next time I see this location, I'll recognize it."
            })
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to remember place: {str(e)}"
            })

    elif tool_name == "who_do_i_know" and VISUAL_MEMORY_AVAILABLE:
        try:
            vm = get_visual_memory()
            people = vm.get_all_people()
            places = vm.get_all_places()

            result = {"people": [], "places": []}

            for person in people:
                result["people"].append({
                    "name": person['name'],
                    "relationship": person['relationship'],
                    "appearance": person['typical_appearance'],
                    "times_seen": person['times_seen']
                })

            for place in places:
                result["places"].append({
                    "name": place['name'],
                    "description": place['description'],
                    "times_seen": place['times_seen']
                })

            print(f"   [OK] Retrieved visual memory: {len(people)} people, {len(places)} places")
            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to retrieve visual memory: {str(e)}"
            })

    elif tool_name == "analyze_with_chat_theory" and ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        context = tool_args.get("context", "")

        result = analyze_with_chat(topic, context)
        print(f"   [OK] Generated CHAT analysis for: {topic}")
        return result

    elif tool_name == "prepare_lecture" and ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        duration = tool_args.get("duration", 50)
        course = tool_args.get("course", "")
        level = tool_args.get("level", "undergraduate")

        result = prepare_lecture(topic, duration, course, level)
        print(f"   [OK] Generated lecture outline for: {topic}")
        return result

    elif tool_name == "discussion_questions" and ACADEMIC_ASSISTANT_AVAILABLE:
        reading = tool_args.get("reading", "")
        topic = tool_args.get("topic", "")

        result = generate_discussion_questions(reading, topic)
        print(f"   [OK] Generated discussion questions for: {topic}")
        return result

    elif tool_name == "simulate_student_questions" and ACADEMIC_ASSISTANT_AVAILABLE:
        topic = tool_args.get("topic", "")
        context = tool_args.get("context", "")

        result = simulate_student_q_and_a(topic, context)
        print(f"   [OK] Simulated student questions for: {topic}")
        return result

    elif tool_name == "check_proactive_suggestions" and PROACTIVE_ASSISTANCE_AVAILABLE:
        try:
            pa = get_proactive_assistance()
            # Get current person from context (default to Alex)
            person = "Alex"  # Could be enhanced to detect from visual memory

            suggestions = pa.check_for_suggestions(person)

            if suggestions:
                result = {
                    "has_suggestions": True,
                    "suggestions": [
                        {
                            "type": suggestion.suggestion_type,
                            "priority": suggestion.priority,
                            "message": suggestion.message,
                            "action_available": suggestion.action_available
                        }
                        for suggestion in suggestions
                    ]
                }
                print(f"   [OK] Found {len(suggestions)} proactive suggestions")
            else:
                result = {
                    "has_suggestions": False,
                    "message": "No suggestions at this time"
                }
                print(f"   [OK] No proactive suggestions at this time")

            return json.dumps(result, indent=2)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Failed to check suggestions: {str(e)}"
            })

    # Fallback: get_local_time works without enhanced tools
    if tool_name == "get_local_time":
        from datetime import datetime
        now = datetime.now()
        return json.dumps({
            "success": True,
            "time": now.strftime("%I:%M %p"),
            "date": now.strftime("%A, %B %d, %Y"),
            "iso": now.isoformat()
        })

    return f"Unknown tool: {tool_name}"


# ================================================================================
# LEGACY DETECTION FUNCTIONS REMOVED (523 lines deleted)
# ================================================================================
# All legacy detection functions have been removed. Tool detection is now
# exclusively handled by the modular system in blue/tool_selector/.
#
# Removed functions (20 total, ~523 lines):
#   • detect_no_tool_intent() - Casual conversation detection
#   • detect_search_intent() - Web search detection
#   • detect_javascript_intent() - JavaScript execution
#   • detect_weather_intent() - Weather queries
#   • detect_light_intent() - Light control with false positive filters
#   • detect_visualizer_intent() - Music visualizer
#   • detect_document_intent() - Document operations
#   • detect_create_document_intent() - Document creation
#   • detect_browse_intent() - Website browsing
#   • detect_music_play_intent() - Music playback
#   • detect_music_control_intent() - Music controls (pause/skip/volume)
#   • detect_document_retrieval_intent() - Document reading
#   • detect_document_search_intent() - Document search
#   • detect_web_search_intent_improved() - Enhanced web search
#   • detect_hallucinated_search() - Hallucination detection
#   • detect_gmail_read_intent() - Gmail reading
#   • detect_gmail_send_intent() - Gmail sending
#   • detect_gmail_reply_intent() - Gmail replies
#   • detect_fanmail_reply_intent() - Fanmail replies
#   • detect_gmail_operation_intent() - Unified Gmail operation detector
#
# All functionality preserved in blue/tool_selector/detectors/
# Commit: 2025-12-27 - Legacy code cleanup
# ================================================================================


def _get_text_content(msg):
    """Extract text content cheaply, skipping base64 image data."""
    content = msg.get('content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get('type') == 'text':
                parts.append(part.get('text', ''))
        return ' '.join(parts)
    return ''


def _estimate_tokens(text: str) -> int:
    """Rough chars/4 token heuristic — no deps, good enough for budgeting."""
    return len(text) // 4 if text else 0


def _estimate_payload_tokens(messages, tools) -> int:
    """Estimate total prompt tokens for a chat completion payload."""
    total = 0
    for m in messages:
        # ~5 tokens of role + chat-template overhead per message.
        total += 5 + _estimate_tokens(_get_text_content(m))
    if tools:
        try:
            import json as _json
            total += _estimate_tokens(_json.dumps(tools))
        except Exception:
            total += 200 * len(tools)
    return total + 64  # final chat-template wrap pad


def _trim_messages_for_budget(messages, tools, budget_tokens: int):
    """Drop oldest non-system messages until estimated tokens fit the budget.

    Always preserves leading system message(s) and the final user message.
    Returns (trimmed_messages, dropped_count).
    """
    if not messages:
        return messages, 0

    sys_end = 0
    while sys_end < len(messages) and messages[sys_end].get('role') == 'system':
        sys_end += 1

    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get('role') == 'user':
            last_user_idx = i
            break
    if last_user_idx is None or last_user_idx < sys_end:
        return messages, 0

    head = messages[:sys_end]
    middle = list(messages[sys_end:last_user_idx])
    tail = messages[last_user_idx:]

    dropped = 0
    while True:
        candidate = head + middle + tail
        if _estimate_payload_tokens(candidate, tools) <= budget_tokens:
            return candidate, dropped
        if not middle:
            return candidate, dropped  # already minimal — give up gracefully
        middle.pop(0)
        dropped += 1


# Shared constants
_VISION_PHRASES = ('i see', 'cozy living room', 'soft lighting', 'warm vibe',
                   'in his office', 'in her office', 'wearing', 'holding a mug',
                   'sitting at', 'glasses and', 'giving a thumbs', 'the monitor shows',
                   'behind him', 'behind her', 'the kitchen', 'the living room')

# Validation helper functions
_HALLUCINATION_RE = re.compile(
    r'i searched|according to (?:my|the) search|i found (?:that|the following)',
    re.IGNORECASE
)

def detect_hallucinated_search(response: str) -> bool:
    """Detect if LLM is hallucinating a web search that didn't happen."""
    return bool(_HALLUCINATION_RE.search(response))


# Patterns that mean "I performed action X" — keyed by the tool that should
# have been called. If the assistant claims one of these but tool_calls is
# empty, the response is a hallucination and we need to force-retry.
_ACTION_CLAIM_PATTERNS = {
    "send_gmail": re.compile(
        r"\b(?:"
        # Past tense: "I sent", "I've sent", "I've emailed", "I just sent"
        r"i(?:'ve| have)?\s+(?:just\s+)?sent|"
        r"i(?:'ll)?\s+sent|i(?:'ve| have)?\s+emailed|"
        r"i\s+just\s+emailed|"
        # Status: "email has been/is/was sent", "email was delivered"
        r"email\s+(?:has been|is|was)\s+sent|"
        r"email (?:was )?delivered|email\s+sent|"
        r"sent (?:the|that|an?) email|"
        # "sent to you at <email>", "sent to <name>", "sent it", "sent that",
        # "sent over". Fires whenever 'sent' is followed by a delivery target.
        r"sent\s+(?:to\b|it\b|that\b|over\b|you\b)|"
        # "sent the headlines to <name>" / "sent the summary to <email>"
        r"sent\s+(?:the|a|that)\s+\w+(?:\s+\w+)?\s+to\b|"
        r"message\s+(?:has been|is|was)\s+sent|"
        # Present continuous (the model often says "Sending...!" as if it's happening now):
        r"(?:i'?m\s+|^|\s)(?:sending|emailing|delivering|firing\s+off)\s+(?:the|that|an?|it|you|over|to)|"
        r"sending\s+(?:the|that|an?|it|over|now|you)|"
        r"emailing\s+(?:you|it|that|the|now)"
        r")\b",
        re.IGNORECASE,
    ),
    "control_lights": re.compile(
        r"\b(?:"
        r"i(?:'ve| have)?\s+(?:just\s+)?(?:turned|set|changed|adjusted|switched|put)\s+(?:the\s+)?lights?|"
        # "lights are (now) set/on/off..." — allow an adverb (now/all) to sit
        # between the verb-to-be and the action verb.
        r"lights?\s+(?:are|were|have been|'re)\s+(?:\w+\s+){0,2}(?:turned|set|changed|adjusted|switched|on|off)|"
        # Present continuous
        r"(?:i'?m\s+)?(?:switching|turning|setting|changing|adjusting)\s+(?:the\s+)?lights?|"
        # Mood/scene-centric: "the galaxy mood is now active/on/set"
        r"(?:mood|scene)\s+(?:is|has been|'s)\s+(?:now\s+)?(?:on|set|active|applied|enabled)"
        r")\b",
        re.IGNORECASE,
    ),
    "play_music": re.compile(
        r"\b(?:i(?:'ve| have)?\s+(?:started|begun|put on|queued)\s+(?:the\s+|some\s+)?(?:music|song|track|playlist)|"
        r"(?:music|song|track|playlist)\s+(?:is|has been)\s+(?:playing|started|queued))\b",
        re.IGNORECASE,
    ),
    "create_document": re.compile(
        r"\b(?:i(?:'ve| have)?\s+(?:created|saved|written)\s+(?:the\s+|a\s+|that\s+)?(?:document|file|note|list)|"
        r"document\s+(?:has been|is|was)\s+(?:created|saved))\b",
        re.IGNORECASE,
    ),
    # Claims to have read/reviewed a specific document. Without this, the
    # model can confidently say "I've re-read Job_Talk_Script7.docx" with
    # zero tool calls — pure hallucination.
    "search_documents": re.compile(
        r"\b(?:"
        r"i(?:'ve| have)?\s+(?:re-?read|reread|reviewed|gone through|looked through|"
        r"checked|opened|pulled up|brought up)\s+(?:the\s+|that\s+|your\s+|my\s+)?"
        r"(?:document|file|pdf|docx?|script|paper|notes|cv|dossier|"
        r"[A-Z][\w_-]*\.(?:pdf|docx?|txt|md))"
        r"|"
        r"i(?:'ve| have)?\s+(?:taken|had)\s+(?:another|a\s+(?:second|fresh|closer))\s+look\s+at"
        r")\b",
        re.IGNORECASE,
    ),
    # Claims to be seeing through the camera right now. Without an actual
    # capture_camera call the model will happily narrate "I can see you're
    # in the kitchen" from nothing — by email there's no live feed, so any
    # such claim must be backed by a real capture.
    "capture_camera": re.compile(
        r"(?:"
        # "I can see <concrete scene>" but NOT the figurative "I can see why/
        # how/what you mean / that you feel / your point".
        r"\bi\s+can\s+see\s+(?!why\b|how\b|what\b|that\s+you|your\s+point|where\s+you)"
        r"(?:you|your|a\s|an\s|the\s|two\b|three\b|some\b|someone|people)|"
        # Explicitly camera/view anchored — unambiguous.
        r"(?:in|through)\s+(?:my|the)\s+(?:camera|view|frame)|"
        r"\blooking\s+(?:in|at)\s+(?:my|the)\s+camera|"
        r"(?:i(?:'ve| have)?\s+)?(?:just\s+)?(?:took|taken|captured|snapped)\s+(?:a\s+)?(?:photo|picture|snapshot)|"
        r"\bin\s+front\s+of\s+me\s+(?:is|are|i\s+(?:can\s+)?see)\b"
        r")",
        re.IGNORECASE,
    ),
}


def detect_hallucinated_action(response: str) -> str | None:
    """If the response claims to have performed a tool-required action but no
    tool was called, return the name of the tool that *should* have been
    called. Otherwise return None.
    """
    if not response or not isinstance(response, str):
        return None
    for tool_name, pattern in _ACTION_CLAIM_PATTERNS.items():
        if pattern.search(response):
            return tool_name
    return None


# Email helper functions (still used by send_gmail tool execution)
def extract_email_address(message: str) -> str | None:
    """Extract email address from message."""
    import re
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", message or "")
    return m.group(0) if m else None


def extract_email_subject_and_body(message: str) -> tuple:
    """Extract subject and body from natural language email request."""
    import re
    subject = ""
    body = ""
    
    subject_match = re.search(r'(?:subject|about)[:\s]+([^,.;]+)', message or "", re.IGNORECASE)
    if subject_match:
        subject = subject_match.group(1).strip()
        subject = re.sub(r'\b(right away|immediately|now|asap|urgent)\b', '', subject, flags=re.IGNORECASE).strip()
    
    for pattern in [
        r'(?:message|body|saying|tell (?:them|him|her))[:\s]+["\']?(.+?)["\']?(?:\s+(?:right away|immediately|now|asap))?$',
        r'(?:that says|saying)[:\s]+["\']?(.+?)["\']?(?:\s+(?:right away|immediately|now|asap))?$',
    ]:
        m = re.search(pattern, message or "", re.IGNORECASE)
        if m:
            body = m.group(1).strip().strip('\"\'')
            body = re.sub(r'\b(right away|immediately|now|asap|urgent)\b', '', body, flags=re.IGNORECASE).strip()
            break
    
    if not subject:
        if body:
            words = body.split()
            subject = ' '.join(words[:5]) + ('...' if len(words) > 5 else '')
        else:
            subject = "Message from Blue"
    if not body:
        body = "Hello! This is a message sent via Blue."
    
    return subject, body


def call_lm_studio(messages: List[Dict], include_tools: bool = True, force_tool: str = None, iteration: int = 1) -> Dict:
    global _vision_queue

    # NOTE: tool_choice="required" with a single-tool filter already guarantees
    # the model will call the right tool. We only add text hints for tools where
    # the model needs guidance on PARAMETERS (like gmail workflows).
    if force_tool:
        messages = messages.copy()
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            original = last_msg["content"]
            # Only inject hints for tools that need parameter guidance
            instructions = {
                "read_gmail": "[Use read_gmail to check the email inbox.]",
                "send_gmail": "[Use send_gmail. Extract the recipient email address and message content from the request.]",
                "reply_gmail": "[Use reply_gmail to reply to these emails.]",
                "capture_camera": "[Use capture_camera to see what's in front of you.]",
            }

            # Special handling for fanmail read-first workflow
            if force_tool == "read_gmail" and 'fanmail' in original.lower() and 'reply' in original.lower():
                instructions["read_gmail"] = "[FANMAIL: Use read_gmail with query 'subject:Fanmail' and include_body=true. After reading, reply with specific details from their message.]"

            if force_tool in instructions:
                messages[-1] = {"role": "user", "content": f"{original}\n\n{instructions[force_tool]}"}

    # INJECT PENDING IMAGES as a NEW USER MESSAGE (CRITICAL FIX!)
    global _vision_queue
    if _vision_queue.has_images():
        print(f"   [VISION] Injecting {len(_vision_queue.pending_images)} image(s)")

        # Build image message
        image_parts = []

        # Add header
        if any(img.is_camera_capture for img in _vision_queue.pending_images):
            # Get visual memory context if available
            recognition_context = ""
            if VISUAL_MEMORY_AVAILABLE:
                try:
                    vm = get_visual_memory()
                    recognition_context = "\n\n" + vm.get_recognition_context()

                    # Get list of known people for enhanced understanding
                    people = vm.get_all_people()
                    known_people = [p['name'] for p in people]
                except Exception as e:
                    print(f"[VISUAL-MEMORY] Error loading context: {e}")
                    known_people = []

            # Build vision prompt (concise to reduce token overhead)
            vision_prompt_parts = [
                "[CAMERA IMAGE: Describe what you ACTUALLY see. Who, what, where, objects, lighting. "
                "Be specific and accurate — describe only what's visible.]"
            ]

            # Add recognition context
            if recognition_context:
                vision_prompt_parts.append(recognition_context)

            # Add recent visual history for scene change awareness
            if VISUAL_MEMORY_AVAILABLE:
                try:
                    history_context = vm.get_visual_history_context(limit=3)
                    if history_context:
                        vision_prompt_parts.append("")
                        vision_prompt_parts.append(history_context)
                        # Add scene change detection hint
                        changes = vm.detect_scene_changes("")
                        if changes.get("has_previous"):
                            vision_prompt_parts.append(
                                f"\n[SCENE CONTEXT: Your last observation was {changes['time_since']} ago. "
                                f"Compare what you see NOW with what you saw before and note any changes.]"
                            )
                except Exception as e:
                    print(f"[VISUAL-MEMORY] Error loading visual history context: {e}")

            # Add context awareness if available
            if CONTEXT_AWARENESS_AVAILABLE and known_people:
                try:
                    # Infer who might be present (this is simplified - real detection would be more sophisticated)
                    audience_prompt = adapt_for_audience("", known_people[:1])  # Default to Alex
                    vision_prompt_parts.append(audience_prompt)
                except Exception as e:
                    print(f"[CONTEXT-AWARE] Error: {e}")

            # Removed conflicting instruction - we want accurate description of the actual image

            image_parts.append({
                "type": "text",
                "text": "\n".join(vision_prompt_parts)
            })
        else:
            image_parts.append({"type": "text", "text": "[Images to analyze:]"})

        # Add each image
        for img_info in _vision_queue.pending_images:
            is_camera = img_info.is_camera_capture
            label = "[Your current view:]" if is_camera else f"Image: {img_info.filename}"

            image_parts.append({"type": "text", "text": f"\n{label}"})

            image_data = encode_image_to_base64(img_info.filepath)
            if image_data:
                image_parts.append(image_data)
                # Debug: Check if image data is valid
                if isinstance(image_data, dict) and 'image_url' in image_data:
                    data_preview = str(image_data['image_url'].get('url', ''))[:100]
                    print(f"   [VISION] Added {img_info.filename} (size: {len(data_preview)} chars in preview)")
                else:
                    print(f"   [VISION] Added {img_info.filename} (non-standard format: {type(image_data)})")
            else:
                print(f"   [VISION-ERROR] Failed to encode image: {img_info.filename}")

        # (vision prompt already added above — no need for duplicate reminder)

        # CRITICAL: Inject as USER message (not assistant)
        messages.append({"role": "user", "content": image_parts})

        print(f"   [VISION] Images injected as user message")
        # Save image paths before clearing so we can link the LLM's response to the image
        global _last_vision_image_paths
        _last_vision_image_paths = [img.filepath for img in _vision_queue.pending_images]
        _vision_queue.mark_as_viewed()
        _vision_queue.clear()

    # Final-pass normalization for strict chat templates (Qwen et al.).
    # Ensures: leading systems, alternating user/assistant, starts with user
    # after system, no consecutive same-role turns. The sanitizer drops
    # stale assistant turns and can leave consecutive user turns or an
    # orphan leading assistant — those make Qwen 400 with "No user query
    # found in messages" before any inference even runs.
    messages = _normalize_message_alternation(messages)

    payload = {
        "messages": messages,
        "temperature": 0.8,  # Slightly higher for more variation
        "max_tokens": -1,
        "stream": False,
        "frequency_penalty": 0.4,  # Strong penalty to reduce repetition of tokens
        "presence_penalty": 0.3    # Strong penalty to encourage topic diversity
    }

    if include_tools:
        # CRITICAL FIX: After iteration 1, filter out "memory/organization" tools that cause loops
        tools_to_use = TOOLS
        if iteration > 1:
            # Block tools that the model overuses after getting initial results
            blocked_tools = {
                'create_note', 'create_document', 'remember_person', 'remember_place',
                'set_timer', 'create_task', 'get_tasks', 'complete_task',
                'who_do_i_know', 'view_image', 'capture_camera', 'recall_visual_memory'
            }
            tools_to_use = [
                tool for tool in TOOLS
                if tool['function']['name'] not in blocked_tools
            ]
            print(f"   [FILTER] Iteration {iteration}: Blocked {len(TOOLS) - len(tools_to_use)} overused tools")

        if force_tool:
            # Filter tools to ONLY the forced tool so "required" has no other choice
            forced_tools = [t for t in TOOLS if t['function']['name'] == force_tool]
            if forced_tools:
                payload["tools"] = forced_tools
                payload["tool_choice"] = "required"
                print(f"   [FORCE-TOOLS] Filtered to only: {force_tool}")
            else:
                print(f"   [FORCE-TOOLS] WARNING: {force_tool} not found in TOOLS, falling back to auto")
                payload["tools"] = tools_to_use
                payload["tool_choice"] = "auto"
        else:
            payload["tools"] = tools_to_use
            payload["tool_choice"] = "auto"

    # Token-budget guard: trim oldest non-system history if the request would
    # overflow LM Studio's context. Default sized for an 8192-ctx model with
    # headroom for the response; override via BLUE_LM_INPUT_BUDGET_TOKENS.
    try:
        _budget = int(os.environ.get('BLUE_LM_INPUT_BUDGET_TOKENS', '6500'))
    except ValueError:
        _budget = 6500
    _trimmed, _dropped = _trim_messages_for_budget(
        payload['messages'], payload.get('tools'), _budget,
    )
    if _dropped:
        _before = len(payload['messages'])
        payload['messages'] = _trimmed
        _approx = _estimate_payload_tokens(_trimmed, payload.get('tools'))
        print(
            f"   [TRIM] Dropped {_dropped} oldest msg(s) to fit budget "
            f"({_budget}t budget, ~{_approx}t after; {_before}->{len(_trimmed)} msgs)",
            flush=True,
        )

    try:
        response = requests.post(LM_STUDIO_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        # Self-heal on n_ctx overflow: LM Studio's error body looks like
        # `n_keep: 5188 >= n_ctx: 4096`. Parse the actual context size, retrim
        # the payload to fit, and retry once. Avoids depending on the user's
        # LM Studio context-length setting matching our default budget.
        body = getattr(getattr(e, 'response', None), 'text', '') or ''
        _ctx_match = re.search(r'n_ctx:\s*(\d+)', body)
        if _ctx_match:
            _n_ctx = int(_ctx_match.group(1))
            _retry_budget = max(256, int(_n_ctx * 0.7))
            _retrimmed, _dropped_now = _trim_messages_for_budget(
                payload['messages'], payload.get('tools'), _retry_budget,
            )

            # Last resort: if even the minimal-message payload still overflows
            # n_ctx, drop tools entirely. The model loses tool-calling on this
            # one request but at least returns a real reply instead of failing
            # — and the selector usually already decided no tool was needed.
            _tools_dropped = False
            if (_estimate_payload_tokens(_retrimmed, payload.get('tools')) > _n_ctx
                    and payload.get('tools')):
                payload.pop('tools', None)
                payload.pop('tool_choice', None)
                _tools_dropped = True
                _retrimmed, _dropped_now = _trim_messages_for_budget(
                    payload['messages'], None, _retry_budget,
                )

            if len(_retrimmed) < len(payload['messages']) or _tools_dropped:
                _est = _estimate_payload_tokens(_retrimmed, payload.get('tools'))
                _extra = " + dropped tools" if _tools_dropped else ""
                print(
                    f"   [TRIM] LM Studio n_ctx={_n_ctx}; retrying with "
                    f"budget {_retry_budget}t (dropped {_dropped_now} msg(s)"
                    f"{_extra}, ~{_est}t after)",
                    flush=True,
                )
                payload['messages'] = _retrimmed
                try:
                    response = requests.post(LM_STUDIO_URL, json=payload, timeout=120)
                    response.raise_for_status()
                    return response.json()
                except Exception as e2:
                    print(f"[ERROR] Retry after n_ctx trim also failed: {e2}")
                    e = e2
                    body = getattr(getattr(e2, 'response', None), 'text', '') or body
            else:
                print(
                    f"   [TRIM] LM Studio n_ctx={_n_ctx} but already minimal "
                    f"(system+last user, no tools). Cannot retry.",
                    flush=True,
                )

        print(f"[ERROR] Error calling LM Studio: {e}")
        # On 400, dump the offending payload + LM Studio's error body so we can
        # see what was wrong. Strips base64 image data to keep the dump small.
        try:
            import datetime as _dt
            stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
            dump_path = f"lm_studio_400_dump_{stamp}.json"
            slim_messages = []
            for m in payload.get('messages', []):
                slim = dict(m)
                c = slim.get('content')
                if isinstance(c, list):
                    slim['content'] = [
                        {**p, 'image_url': {'url': '<base64-stripped>'}} if isinstance(p, dict) and p.get('type') == 'image_url' else p
                        for p in c
                    ]
                slim_messages.append(slim)
            slim_payload = {**payload, 'messages': slim_messages}
            import json as _json
            with open(dump_path, 'w', encoding='utf-8') as f:
                _json.dump({
                    'lm_studio_error_body': body[:4000],
                    'request_payload': slim_payload,
                    'message_count': len(payload.get('messages', [])),
                    'message_roles': [m.get('role') for m in payload.get('messages', [])],
                    'system_message_lengths': [
                        len(m.get('content', '')) if isinstance(m.get('content'), str) else 'list'
                        for m in payload.get('messages', []) if m.get('role') == 'system'
                    ],
                }, f, indent=2, default=str)
            print(f"[DEBUG] Dumped failing request to: {dump_path}")
        except Exception as dump_err:
            print(f"[DEBUG] Could not write dump: {dump_err}")
        return None


def purge_old_camera_images(messages: List[Dict]) -> List[Dict]:
    """
    Remove old camera images from conversation to prevent confusion.

    Only keeps the most recent camera image reference.
    This prevents the model from seeing multiple camera captures and
    getting confused about which one is current.
    """
    print(f"   [VISION-CLEANUP] Checking conversation for old camera images...")

    # Find all messages with camera images
    camera_indices = []
    for i, msg in enumerate(messages):
        content = msg.get('content', '')
        if isinstance(content, str):
            if 'CAMERA' in content or 'camera_capture_' in content or 'camera_NEW_' in content:
                camera_indices.append(i)
        elif isinstance(content, list):
            # Check for camera-related text in multimodal content
            for part in content:
                if part.get('type') == 'text':
                    text = part.get('text', '')
                    if 'CAMERA' in text or 'camera_capture_' in text or 'camera_NEW_' in text:
                        camera_indices.append(i)
                        break

    if len(camera_indices) > 1:
        # Keep only the LAST camera message, remove older ones
        indices_to_remove = camera_indices[:-1]
        print(f"   [VISION-CLEANUP] Removing {len(indices_to_remove)} old camera image(s)")

        # Remove from back to front to maintain indices
        for idx in reversed(indices_to_remove):
            messages.pop(idx)
    else:
        print(f"   [VISION-CLEANUP] Found {len(camera_indices)} camera image(s), no cleanup needed")

    return messages


def _build_expertise_block() -> str:
    """List the documents Blue currently has indexed, so he knows the
    topics he can speak to authoritatively.

    Without this block Blue only finds documents when search_documents is
    explicitly called — and only when the model thinks to call it. With
    this block, every prompt names the corpus, so Blue knows he has
    expertise on these topics and can reach for the search tool naturally.
    """
    try:
        index = load_document_index()
    except Exception:
        return ""
    docs = index.get("documents", [])
    real_docs = [
        d for d in docs
        if d.get("filename")
        and not d.get("camera_capture")
        and not (d.get("filename") or "").startswith("camera_")
    ]
    if not real_docs:
        return ""

    # Sort by upload date desc so newer uploads bubble up if we hit the cap.
    real_docs.sort(key=lambda d: d.get("uploaded_at", ""), reverse=True)
    cap = 25
    shown = real_docs[:cap]

    lines = []
    for d in shown:
        fn = d.get("filename", "?")
        preview = (d.get("text_preview") or "").strip()
        # Strip newlines and image-metadata markers from the preview snippet
        # so it reads as a one-line topic hint.
        preview = re.sub(r"\s+", " ", preview)
        if preview.startswith("[IMAGE FILE"):
            preview = ""
        snippet = preview[:90].rstrip(" .,") + "…" if len(preview) > 90 else preview
        if snippet:
            lines.append(f"- {fn} — {snippet}")
        else:
            lines.append(f"- {fn}")

    overflow = len(real_docs) - len(shown)
    if overflow > 0:
        lines.append(f"- ...and {overflow} more")

    return (
        "<expertise>\n"
        f"You have direct access to these {len(real_docs)} document(s) in the user's "
        "library — they are indexed and semantically searchable. When the user "
        "asks about any topic these documents cover, treat yourself as an "
        "expert: use the search_documents tool to retrieve specifics and quote "
        "from them naturally. Do not claim ignorance about a topic that is "
        "obviously covered below.\n\n"
        "When you draw on a document in your reply, cite the source inline "
        "like [filename.pdf] right after the claim it supports — short and "
        "natural, e.g. 'as I noted in my talk script [Job_Talk_Script7.docx], …'.\n"
        + "\n".join(lines) +
        "\n</expertise>"
    )


def _build_now_block() -> str:
    """Render the current local date/time + explicit relative-day resolutions.

    Without this, the LLM has no anchor for 'now' and treats relative phrases
    in chat history (e.g. yesterday's "tomorrow at 3pm") as if they were said
    today, so meetings drift forward each session. The resolutions below give
    it absolute dates to rewrite against.
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    tz = now.astimezone().tzname() or "local"
    today_d = now.date()
    date_str = f"{today_d.strftime('%A, %B')} {today_d.day}, {today_d.year}"
    time_str = now.strftime("%I:%M %p").lstrip("0")
    return (
        "<now>\n"
        f"Current date: {date_str}\n"
        f"Current time: {time_str} ({tz})\n"
        f"When the user says \"today\" they mean {today_d.isoformat()}, "
        f"\"tomorrow\" means {(today_d + timedelta(days=1)).isoformat()}, "
        f"\"yesterday\" was {(today_d - timedelta(days=1)).isoformat()}. "
        "Resolve any relative time phrase in chat history against THIS date, "
        "not the date the message was originally said.\n"
        "</now>"
    )


def _build_upcoming_schedule_block(hours_ahead: int = 24) -> str:
    """List unfinished reminders due in the next `hours_ahead` hours.

    Injected on every turn so Blue can answer "what's on my schedule?" /
    "anything coming up?" without a tool round-trip and so he naturally
    anchors statements ("you have X in 20 min") against real data. If the
    enhanced reminders module isn't loaded or the DB read fails, return an
    empty string — silent degradation, never break the system prompt.
    """
    if not globals().get("ENHANCED_TOOLS_AVAILABLE", False):
        return ""
    try:
        from datetime import datetime, timedelta
        from blue_tools_enhanced import occurrences_in_window
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        # occurrences_in_window expands weekly recurring events and carries
        # end times, so a standing class shows up with its full time range.
        occs = occurrences_in_window(now, cutoff)[:20]
    except Exception as e:
        log.warning(f"[SCHEDULE] block build failed: {e}")
        return ""

    if not occs:
        return (
            "<upcoming_schedule>\n"
            f"No reminders in the next {hours_ahead} hours.\n"
            "</upcoming_schedule>"
        )

    today_d = now.date()
    lines = []
    for o in occs:
        when = o["start"]
        delta = when - now
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            rel = f"in {mins} min" if mins > 0 else "now"
        elif mins < 60 * 24:
            hrs = mins / 60
            rel = f"in {hrs:.1f} hrs"
        else:
            rel = f"in {mins // (60*24)}d {(mins % (60*24)) // 60}h"
        day_label = (
            "today" if when.date() == today_d
            else "tomorrow" if when.date() == today_d + timedelta(days=1)
            else when.strftime("%a %b ") + str(when.day)
        )
        clock = when.strftime("%I:%M %p").lstrip("0")
        if o["end"]:
            clock += "-" + o["end"].strftime("%I:%M %p").lstrip("0")
        tag = " (weekly)" if o["recurring"] else ""
        lines.append(
            f"- {day_label} at {clock} ({rel}) — {o['user_name']}: "
            f"{o['title']}{tag}"
        )

    # Flag overlapping / close-together events so Blue can mention a clash
    # when the user asks about their schedule.
    conflict_note = ""
    try:
        if globals().get("PROACTIVE_QUEUE_AVAILABLE", False):
            pairs = blue_proactive.detect_conflicts(occs)
            if pairs:
                joined = "; ".join(
                    f'"{a["title"]}" and "{b["title"]}" {phrase}'
                    for a, b, phrase in pairs
                )
                conflict_note = f"\nPossible conflicts — {joined}."
    except Exception as e:
        log.warning(f"[SCHEDULE] conflict check failed: {e}")

    return (
        "<upcoming_schedule>\n"
        f"Reminders in the next {hours_ahead} hours "
        f"(use this when the user asks about schedule, calendar, "
        f"reminders, or what's coming up — do not call a tool, just answer "
        f"from this list):\n"
        + "\n".join(lines)
        + conflict_note
        + "\n</upcoming_schedule>"
    )


def build_dynamic_system_message(conversation_messages: List[Dict], facts_preamble: str) -> Dict:
    """Build system message with anti-repetition context from conversation history."""
    conversational_guidance = "Be natural, concise, and conversational. Vary your phrasing.\n"

    # Build anti-repetition context (skip vision descriptions and refusals).
    # Refusals like "I don't have that yet" must NEVER appear here even with a
    # "don't repeat" framing — the model still anchors on names/strings inside
    # them. Letting a wrong response (e.g. "Annie" instead of "Athena") through
    # here surfaces the wrong name in the system prompt every turn.
    _REFUSAL_MARKERS = (
        "i don't have", "i do not have", "i dont have",
        "i don't know", "i do not know", "i dont know",
        "i only have", "i only know",
        "i haven't been told", "i havent been told",
        "you haven't told me", "you havent told me",
        "not in my memory", "not saved yet",
        "i'm not sure", "im not sure",
        "blank slate", "just woke up", "haven't met", "havent met",
        "memory is blank", "no information stored", "im new here", "i'm new here",
    )
    recent_assistant_responses = []
    _scan_slice = conversation_messages[-10:] if len(conversation_messages) > 10 else conversation_messages
    for msg in reversed(_scan_slice):
        if msg.get('role') == 'assistant' and msg.get('content'):
            response_text = msg['content']
            response_lower = response_text[:200].lower()
            is_vision_response = any(phrase in response_lower for phrase in _VISION_PHRASES)
            is_refusal = any(marker in response_lower for marker in _REFUSAL_MARKERS)

            if len(response_text) > 50 and not is_vision_response and not is_refusal:
                recent_assistant_responses.append(response_text[:150])
                if len(recent_assistant_responses) >= 3:
                    break

    anti_repetition_context = ""
    if recent_assistant_responses:
        responses_list = "\n".join([f"  - \"{resp}...\"" for resp in recent_assistant_responses])
        anti_repetition_context = (
            f"\nDon't repeat these recent responses:\n{responses_list}\n"
        )

    expertise_block = _build_expertise_block()
    expertise_section = f"\n{expertise_block}\n" if expertise_block else ""

    now_block = _build_now_block()
    schedule_block = _build_upcoming_schedule_block()
    schedule_section = f"{schedule_block}\n\n" if schedule_block else ""

    system_msg = {
        "role": "system",
        "content": (
            f"{facts_preamble}\n\n"
            f"{now_block}\n\n"
            f"{schedule_section}"
            "You are Blue, a friendly home assistant. Keep responses brief and natural.\n"
            f"{conversational_guidance}"
            f"{anti_repetition_context}"
            f"{expertise_section}"
            "\nRules: MY docs → search_documents; web → web_search; fanmail → read_gmail then reply_gmail; "
            "light show → music_visualizer; tool results are REAL, use them immediately.\n"
            "NO FAKE ACTIONS: Never say you've set a reminder, added an event, "
            "saved a note, sent an email, started a timer, or changed any "
            "system state unless you actually called the matching tool THIS "
            "turn and saw a successful tool result. If the user asks for one "
            "of those things, call the tool — do not describe doing it. If "
            "you cannot call the tool, say so plainly instead of pretending.\n"
            "REMINDER TIME RULES: When the user gives a clock time with no "
            "day ('at 10am', 'at 3pm'), DO NOT silently assume a date. If "
            "the time has already passed today, ASK 'today or tomorrow?' "
            "before calling create_reminder. When you do create a reminder, "
            "ALWAYS state the full day and date in your reply (e.g. "
            "'set for tomorrow, Tuesday May 13 at 10am') — do not drop the "
            "date, even if it feels redundant. The user needs the date "
            "back so they can catch a wrong assumption.\n"
            "Moods: moonlight, sunset, ocean, forest, romance, party, focus, relax, energize, movie, fireplace"
        )
    }

    return system_msg


def process_with_tools(messages: List[Dict], _pre_selection=None) -> Dict:
    """Process conversation with tool support."""
    conversation_messages = messages.copy()

    # BUILD SYSTEM MESSAGE WITH MEMORY FACTS
    # Extract facts from .ocf conversations first (only if conversation has .ocf content)
    facts_preamble = build_system_preamble()
    # OPTIMIZATION: Only run OCF extraction if there are likely .ocf messages (check first few)
    _has_ocf = any('.ocf' in str(m.get('content', ''))[:200] for m in conversation_messages[:5])
    if _has_ocf:
        ocf_facts = extract_ocf_facts(conversation_messages)
        if ocf_facts:
            facts_preamble += ocf_facts
            log.info("[MEMORY] Injected extracted .ocf facts into system message")

    # Build initial system message. If chat_completions already merged the
    # enhanced-memory facts into messages[0] (look for our injected markers),
    # preserve that content and APPEND the dynamic system message rather
    # than replacing it. Replacing would discard the canonical user facts
    # (daughter names, employer, etc.) that we just spent effort merging in.
    system_msg = build_dynamic_system_message(conversation_messages, facts_preamble)
    _injected_markers = ("<known_facts>", "<long_term_notes>", "<relevant_memories>", "<recent_history>")
    existing0 = conversation_messages[0] if conversation_messages else None
    has_injected = (
        existing0
        and existing0.get("role") == "system"
        and isinstance(existing0.get("content"), str)
        and any(marker in existing0["content"] for marker in _injected_markers)
    )

    if not conversation_messages or conversation_messages[0].get("role") != "system":
        conversation_messages.insert(0, system_msg)
    elif has_injected:
        # Combine: dynamic content first (identity + anti-loop), then the
        # already-merged enhanced-memory blocks. Both live in one message.
        conversation_messages[0] = {
            "role": "system",
            "content": f"{system_msg['content'].rstrip()}\n\n{existing0['content']}",
        }
    else:
        conversation_messages[0] = system_msg

    # ===== CONTEXT TRIMMING =====
    # To reduce confusion from very long conversations or previous tool results, we
    # limit the number of messages sent to the language model. We always keep
    # the system message at index 0 and the most recent (MAX_CONTEXT_MESSAGES-1)
    # messages following it. This helps the assistant focus on the current query.
    try:
        max_ctx = int(getattr(_settings, "MAX_CONTEXT_MESSAGES", 0))
        if max_ctx and len(conversation_messages) > max_ctx:
            # Preserve the system message at position 0, then keep the last (max_ctx-1) messages
            # Keep system message and trim context
            conversation_messages = [conversation_messages[0]] + conversation_messages[-(max_ctx - 1):]
    except Exception:
        # If any error occurs while trimming, proceed without trimming
        pass


    # Purge old camera images from conversation to prevent confusion
    # OPTIMIZATION: Quick scan using only string content (skip base64 image data in lists)
    last_user_message = messages[-1].get("content", "") if messages else ""

    # "Write this from my perspective / in my voice" — chat is the trusted
    # local channel (always Alex), so compose a first-person piece in his
    # voice grounded in his publications and short-circuit the tool loop.
    _luser = last_user_message if isinstance(last_user_message, str) else ""
    if _luser and _wants_perspective_write(_luser):
        try:
            _piece = _compose_in_alex_voice(_luser)
            if _piece:
                return {"choices": [{"message": {"role": "assistant", "content": _piece}}]}
        except Exception as _pe:
            print(f"   [PERSPECTIVE] chat compose error: {_pe}")

    # Fast check: scan text content only (no str() on entire messages with base64)
    _has_camera_content = False
    for msg in conversation_messages:
        text = _get_text_content(msg)
        if 'CAMERA' in text or 'camera_NEW_' in text or 'camera_capture_' in text:
            _has_camera_content = True
            break

    if _has_camera_content:
        conversation_messages = purge_old_camera_images(conversation_messages)

        vision_keywords = ['see', 'look', 'watch', 'view', 'show', 'picture', 'photo', 'image', 'camera', 'visual']
        _msg_lower = last_user_message.lower() if isinstance(last_user_message, str) else ''
        asks_about_vision = any(keyword in _msg_lower for keyword in vision_keywords)

        messages_to_remove = set()
        for i in range(len(conversation_messages) - 1):
            current_msg = conversation_messages[i]
            if current_msg.get('role') != 'user':
                continue
            user_content = _get_text_content(current_msg).lower()
            if not any(kw in user_content for kw in ('see', 'look', 'watch', 'show', 'picture', 'photo')):
                continue
            next_msg = conversation_messages[i + 1] if i + 1 < len(conversation_messages) else None
            if next_msg and next_msg.get('role') == 'assistant':
                assistant_content = _get_text_content(next_msg).lower()
                if any(phrase in assistant_content for phrase in _VISION_PHRASES):
                    messages_to_remove.add(i)
                    messages_to_remove.add(i + 1)

        description_count = len(messages_to_remove)

        if not asks_about_vision:
            # Count camera messages using cheap text extraction
            camera_indices = set()
            for idx, msg in enumerate(conversation_messages):
                text = _get_text_content(msg)
                if 'camera_NEW_' in text or 'CAMERA' in text:
                    camera_indices.add(idx)

            if camera_indices or description_count > 0:
                remove_set = camera_indices | messages_to_remove
                conversation_messages = [
                    msg for idx, msg in enumerate(conversation_messages)
                    if idx not in remove_set
                ]
                print(f"   [VISION-PURGE] Removed {len(remove_set)} vision-related message(s) ({len(camera_indices)} images, {description_count} descriptions) - not relevant to current query")
        else:
            if description_count > 0:
                conversation_messages = [
                    msg for idx, msg in enumerate(conversation_messages)
                    if idx not in messages_to_remove
                ]
                print(f"   [VISION-PURGE] Removed {description_count} old photo description(s) to focus on current vision query")

    max_iterations = _settings.MAX_ITERATIONS
    iteration = 0
    # When the hallucination detector fires it sets `pending_force_tool` to
    # the tool the model claimed it called. The next iteration must (a) use
    # that tool, and (b) NOT be silenced by the no-tools-after-iter-1 cap.
    # Without this carryover, the force_tool gets reset at the top of the
    # loop and the cap disables tools — leaving Blue saying "email sent"
    # with nothing actually sent.
    pending_force_tool: Optional[str] = None

    # ================================================================================
    # FAST PATH: Simple greetings and short conversational messages
    # Skip ALL pre-processing (compound detection, corrections, tool selection)
    # and go straight to LLM for a quick response
    # ================================================================================
    _greeting_patterns = ['hello', 'hi ', 'hi!', 'hey', 'good morning', 'good afternoon',
                          'good evening', 'how are you', "how's it going", "what's up",
                          'sup', 'greetings', 'nice to see you', 'good to see you',
                          'thank you', 'thanks', 'bye', 'goodbye', 'good night', 'goodnight']
    _msg_lower = last_user_message.lower().strip()
    _is_simple_greeting = (
        len(last_user_message.split()) <= 8 and
        any(_msg_lower.startswith(p) or _msg_lower == p.strip() for p in _greeting_patterns)
    )
    if _is_simple_greeting:
        print(f"   [FAST] Simple greeting detected - skipping tool selection")
        response = call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1)
        if response:
            return response
        return {"choices": [{"message": {"role": "assistant", "content": "Hey there!"}}]}

    # ================================================================================
    # v8 ENHANCEMENT: Check for compound requests and follow-up corrections
    # ================================================================================

    # Check for follow-up corrections ("no, make it blue")
    state = get_conversation_state()
    correction = detect_follow_up_correction(last_user_message, {
        'last_tool_used': state.last_tool_used,
        'last_tool_result': state.last_tool_result
    })
    if correction and correction['is_correction']:
        print(f"   [CORRECTION] Detected correction for {correction['correction_type']}: {correction['new_value']}")

    # IMPROVED INTENT DETECTION with specialized functions

    # ================================================================================
    # PRIORITY CHECK: Camera Capture (must take NEW photo every time)
    # ================================================================================
    # This check happens BEFORE tool selector to ensure "what do you see?"
    # ALWAYS triggers a new camera capture, not a cached response
    if detect_camera_capture_intent(last_user_message):
        print(f"   [CAMERA-DETECT] ✅ Camera capture intent detected!")
        print(f"   [CAMERA-DETECT] Forcing NEW photo capture - bypassing tool selector")
        # Force the capture_camera tool to be called
        # This ensures a brand new photo is taken, not reusing old context
        improved_force_tool = "capture_camera"
        improved_tool_args = {}

        # Skip tool selector and go straight to execution
        is_greeting = False

        print(f"   [CAMERA-DETECT] Tool forced: capture_camera (will execute in iteration 1)")
    else:
        # Normal tool selection flow
        improved_force_tool = None
        improved_tool_args = None

    # ================================================================================
    # TOOL SELECTION: Improved (confidence-based) or Legacy (keyword-based)
    # ================================================================================

    # v8: Handle corrections first
    if correction and correction['is_correction'] and correction['new_value']:
        print(f"   [CORRECTION] Handling correction before tool selection")
        if correction['correction_type'] == 'lights':
            improved_force_tool = 'control_lights'
            if correction['new_value'] in ['brighter', 'dimmer']:
                improved_tool_args = {'action': 'brightness', 'brightness': 80 if correction['new_value'] == 'brighter' else 30}
            else:
                improved_tool_args = {'action': 'color', 'color': correction['new_value']}
        elif correction['correction_type'] == 'music':
            improved_force_tool = 'control_music'
            improved_tool_args = {'action': correction['new_value']}
        
        if improved_force_tool:
            print(f"   [CORRECTION] Forcing tool: {improved_force_tool} with {improved_tool_args}")

    # ===== TOOL SELECTION (Single Path - Always Use Modular Selector) =====
    if not improved_force_tool:
        print(f"   [SELECTOR] Running modular confidence-based tool selection")

        # Reuse pre-selection from endpoint if available (avoids running selector twice)
        if _pre_selection is not None:
            selection_result = _pre_selection
            print(f"   [SELECTOR] Reusing pre-selection result")
        else:
            recent_history = conversation_messages[-5:] if len(conversation_messages) > 5 else conversation_messages
            selection_result = TOOL_SELECTOR.select_tool(last_user_message, recent_history)

        # Check if disambiguation is needed
        if selection_result.needs_disambiguation:
            print(f"   [SELECTOR] Low confidence - asking user for clarification")
            # The clarifying question IS Blue's reply this turn — return it in
            # the standard choices shape so chat_completions can read it like
            # any other response. (A bare {'response':...} dict here used to
            # KeyError on response['choices'] and 500 the whole request.)
            clarify = (selection_result.disambiguation_prompt
                       or "Could you tell me a bit more about what you'd like?")
            return {"choices": [{"message": {
                "role": "assistant",
                "content": clarify,
            }}]}

        # Set variables for compatibility with rest of code
        if selection_result.primary_tool:
            selected_tool = selection_result.primary_tool

            # Don't overwrite if priority detection (camera) already set a tool
            if not improved_force_tool:
                # Set tool name and args from selector
                improved_force_tool = selected_tool.tool_name
                improved_tool_args = selected_tool.extracted_params

                # Log selection details
                print(f"   [SELECTOR] Selected: {improved_force_tool}")
                print(f"   [SELECTOR] Confidence: {selected_tool.confidence:.2f}")
                print(f"   [SELECTOR] Priority: {selected_tool.priority}")
                print(f"   [SELECTOR] Reason: {selected_tool.reason}")
            else:
                print(f"   [SELECTOR] Skipping selector - priority tool already set: {improved_force_tool}")

            if selection_result.alternative_tools:
                alt_names = [t.tool_name for t in selection_result.alternative_tools[:2]]
                print(f"   [SELECTOR] Alternatives: {', '.join(alt_names)}")

            if selection_result.compound_request:
                print(f"   [SELECTOR] WARNING: Compound request (multiple tools needed)")

            is_greeting = False
        else:
            # No tool needed - conversational response (but only if no priority tool set)
            if not improved_force_tool:
                improved_force_tool = None
                improved_tool_args = None
                print(f"   [SELECTOR] No tool needed - conversational response")
            else:
                print(f"   [SELECTOR] Keeping priority tool: {improved_force_tool}")

            # Detect if it's a greeting/conversational message
            greeting_patterns = ['hello', 'hi ', 'hey', 'good morning', 'good afternoon', 'good evening',
                                'how are you', 'how\'s it going', 'what\'s up', 'sup', 'greetings',
                                'nice to see you', 'good to see you']
            is_greeting = any(pattern in last_user_message.lower() for pattern in greeting_patterns)

    # ===== TOOL NAME NORMALIZATION =====
    # Safety net: map any legacy/incorrect tool names to correct ones.
    # This catches mismatches between what detectors return and what
    # execute_tool / TOOLS array actually support.
    _TOOL_NAME_MAP = {
        'capture_camera_image': 'capture_camera',
        'recognize_face': 'capture_camera',
        'recognize_place': 'capture_camera',
        'create_event': 'create_reminder',
        'list_events': 'get_upcoming_reminders',
        'set_reminder': 'create_reminder',
        'list_notes': 'search_notes',
        'calculate': 'run_javascript',
        'get_date_time': 'get_local_time',
        'visual_memory': 'recall_visual_memory',
        'recall_vision': 'recall_visual_memory',
    }
    if improved_force_tool and improved_force_tool in _TOOL_NAME_MAP:
        old_name = improved_force_tool
        improved_force_tool = _TOOL_NAME_MAP[improved_force_tool]
        print(f"   [NORMALIZE] Mapped tool name: {old_name} -> {improved_force_tool}")

    # ================================================================================
    # ZERO-LLM PATH: For simple tools, execute and return a templated response
    # without any LLM call at all. This is the fastest possible path.
    # ================================================================================
    _ZERO_LLM_TOOLS = {
        'control_music', 'control_lights', 'get_local_time',
        'set_timer', 'music_visualizer', 'play_music',
    }

    def _template_response(tool_name, tool_args, tool_result):
        """Build a quick natural response from tool result without LLM."""
        try:
            data = json.loads(tool_result) if isinstance(tool_result, str) else tool_result
        except (json.JSONDecodeError, TypeError):
            data = {}

        success = data.get('success', True) if isinstance(data, dict) else True

        if not success:
            error = data.get('error', 'Something went wrong') if isinstance(data, dict) else tool_result
            return f"Sorry, that didn't work: {error}"

        if tool_name == 'control_music':
            action = tool_args.get('action', '')
            action_words = {
                'pause': 'Paused the music.',
                'resume': 'Resumed playback.',
                'next': 'Skipping to next track.',
                'previous': 'Going back to previous track.',
                'volume_up': 'Turned the volume up.',
                'volume_down': 'Turned the volume down.',
                'mute': 'Muted.',
            }
            return action_words.get(action, f"Done — {action}.")

        if tool_name == 'play_music':
            query = tool_args.get('query', 'music')
            msg = data.get('message', '') if isinstance(data, dict) else ''
            if msg:
                return msg
            return f"Playing {query} for you."

        if tool_name == 'control_lights':
            action = tool_args.get('action', '')
            mood = tool_args.get('mood', '')
            color = tool_args.get('color', '')
            if mood:
                return f"Set the lights to {mood} mood."
            if color:
                return f"Changed the lights to {color}."
            if action == 'on':
                return "Lights are on."
            if action == 'off':
                return "Lights are off."
            msg = data.get('message', '') if isinstance(data, dict) else ''
            return msg or "Lights updated."

        if tool_name == 'get_local_time':
            if isinstance(data, dict):
                time_str = data.get('time', data.get('local_time', ''))
                date_str = data.get('date', '')
                action = tool_args.get('action', 'get_time')
                if action == 'get_date' and date_str:
                    return f"Today is {date_str}."
                elif action == 'get_date_time' and date_str and time_str:
                    return f"It's {time_str} on {date_str}."
                elif time_str:
                    return f"It's {time_str}."
            return f"The time is {tool_result}." if tool_result else "Here's the time."

        if tool_name == 'set_timer':
            msg = data.get('message', '') if isinstance(data, dict) else ''
            return msg or "Timer set."

        if tool_name == 'music_visualizer':
            return "Light show started! The lights are syncing with the music."

        # Fallback
        return None

    if (improved_force_tool and improved_force_tool in _ZERO_LLM_TOOLS
            and improved_tool_args is not None and isinstance(improved_tool_args, dict)):
        print(f"\n[ZERO-LLM] Direct execution (no LLM call): {improved_force_tool} with {improved_tool_args}")
        tool_result = execute_tool(improved_force_tool, improved_tool_args)
        print(f"   [OK] {improved_force_tool} completed")

        templated = _template_response(improved_force_tool, improved_tool_args, tool_result)
        if templated:
            print(f"   [ZERO-LLM] Returning templated response (0 LLM calls)")
            return {"choices": [{"message": {"role": "assistant", "content": templated}}]}

    # ================================================================================
    # FAST EXECUTION: Execute tool directly, then ONE LLM call to format response.
    # Used for tools that need richer/contextual responses (weather, email, search).
    # ================================================================================
    _DIRECT_EXEC_TOOLS = {
        'get_weather', 'capture_camera', 'web_search', 'read_gmail',
        'search_documents', 'browse_website',
    }
    if (improved_force_tool and improved_force_tool in _DIRECT_EXEC_TOOLS
            and improved_tool_args is not None and isinstance(improved_tool_args, dict)):
        print(f"\n[FAST-EXEC] Direct tool execution: {improved_force_tool} with {improved_tool_args}")
        tool_result = execute_tool(improved_force_tool, improved_tool_args)
        print(f"   [OK] {improved_force_tool} completed")

        # Add tool call + result to conversation so LLM can format the response
        conversation_messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "direct_exec", "type": "function",
                           "function": {"name": improved_force_tool,
                                       "arguments": json.dumps(improved_tool_args)}}]
        })
        conversation_messages.append({
            "role": "tool",
            "tool_call_id": "direct_exec",
            "name": improved_force_tool,
            "content": tool_result
        })
        conversation_messages.append({
            "role": "user",
            "content": "[Answer naturally using the tool results above. No more tools.]"
        })
        # Single LLM call just to format the response
        response = call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=1)
        if response:
            content = response["choices"][0]["message"].get("content", "")

            # COMPOUND-REQUEST HALLUCINATION GUARD:
            # Fast-exec ran ONE tool (e.g. browse_website). If the user's
            # original request was compound ("browse + email"), the model
            # often confabulates the second action ("…sent to you at X")
            # since no second tool was called. Catch that here so the email
            # actually goes out, not just the words "email sent". Falls
            # through to the iteration loop with the right pending tool.
            hallucinated_tool = detect_hallucinated_action(content)
            if hallucinated_tool and hallucinated_tool != improved_force_tool:
                # The retry is meant for COMPOUND requests ("browse + email"):
                # one tool runs, the model narrates the second action without
                # calling its tool, and we force it through. Narrow false-
                # positive guard: after read_gmail, the model often
                # references PAST send/reply activity from earlier turns
                # ("I sent a standard response...") without the user having
                # asked for any send. Suppress the retry in that specific
                # case unless the user message itself contains a write verb.
                if improved_force_tool == "read_gmail" and hallucinated_tool in ("send_gmail", "reply_gmail", "auto_reply_emails"):
                    _user_text = (last_user_message or "").lower()
                    _write_intent_words = (
                        "send", "email ", "emailing", "reply", "respond",
                        "tell ", "write ", "message ", " text ", "forward",
                        "compose", "shoot ", "ping ", "answer",
                    )
                    if not any(w in _user_text for w in _write_intent_words):
                        print(
                            f"   [SKIP-RETRY] response sounds like "
                            f"{hallucinated_tool} but user only asked to "
                            f"read (\"{(last_user_message or '')[:60]}\") "
                            f"— treating it as narration about past mail."
                        )
                        if _last_vision_image_paths and content:
                            _save_visual_observation(content)
                        return response

                print(f"   [WARN] Fast-exec model claimed to {hallucinated_tool} after {improved_force_tool} — running it for real")
                # Drop the synthetic "[Answer naturally...]" guard turn so
                # the loop's next call doesn't see it as the latest user msg.
                while conversation_messages and (
                    conversation_messages[-1].get("role") == "user"
                    and "[Answer naturally" in (conversation_messages[-1].get("content") or "")
                ):
                    conversation_messages.pop()
                conversation_messages.append({
                    "role": "assistant",
                    "content": content,
                })
                conversation_messages.append({
                    "role": "user",
                    "content": (
                        f"You said you performed that action, but you didn't "
                        f"actually call any tool. Use the {hallucinated_tool} "
                        f"tool now to actually do it — extract the recipient, "
                        f"subject, and body from this conversation."
                    ),
                })
                pending_force_tool = hallucinated_tool
                # Fall through to the iteration loop; do NOT return.
            else:
                if _last_vision_image_paths and content:
                    _save_visual_observation(content)
                return response
        else:
            return {"choices": [{"message": {"role": "assistant", "content": "Done!"}}]}

    while iteration < max_iterations:
        iteration += 1
        print(f"\n[ITER] Iteration {iteration}")

        force_tool = None

        # ITERATION 1: Force correct tool based on clear intent
        if iteration == 1:
            if improved_force_tool:
                force_tool = improved_force_tool
                print(f"   [FORCE] Using tool from priority detection: {force_tool}")
            elif is_greeting:
                print("   [SKIP] Greeting detected - no tool needed")
                force_tool = None
            else:
                print("   [ALLOW] No clear tool intent - letting model decide")

        # Carry over a force_tool set by the previous iteration's hallucination
        # detector — this MUST run with tools enabled, otherwise the retry is
        # pointless. Bypasses the no-tools cap below.
        if pending_force_tool:
            force_tool = pending_force_tool
            pending_force_tool = None
            print(f"   [HALLUCINATION-RETRY] Forcing {force_tool} with tools enabled")
        # After iteration 1, force text-only responses (no tools) to avoid
        # extra LLM round-trips — UNLESS we're retrying a hallucinated action,
        # in which case the whole point is to actually call the tool.
        elif iteration >= 2:
            print(f"   [LIMIT] Iteration {iteration} - forcing response without tools")
            conversation_messages.append({
                "role": "user",
                "content": "[Respond now using the tool results above. No more tool calls.]"
            })
            response = call_lm_studio(conversation_messages, include_tools=False, force_tool=None, iteration=iteration)
            if not response:
                return {"choices": [{"message": {"role": "assistant", "content": "I'm having trouble connecting."}}]}
            return response

        response = call_lm_studio(conversation_messages, include_tools=True, force_tool=force_tool, iteration=iteration)

        if not response:
            return {"choices": [{"message": {"role": "assistant", "content": "I'm having trouble connecting."}}]}

        assistant_message = response["choices"][0]["message"]
        tool_calls = assistant_message.get("tool_calls", [])

        if not tool_calls:
            content = assistant_message.get("content", "")

            # Check if model should have used a tool but didn't
            if iteration == 1 and improved_force_tool:
                correct_tool = improved_force_tool
                print(f"   [ERROR] Model answered without using {correct_tool} tool!")

                # Use selector's extracted params if available, otherwise let LLM retry
                tool_args = improved_tool_args if improved_tool_args is not None else {}
                if tool_args is not None:
                    print(f"   [RETRY] Direct-executing {correct_tool} with extracted params")
                    tool_result = execute_tool(correct_tool, tool_args)
                    conversation_messages.append({
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{"id": "forced", "type": "function",
                                       "function": {"name": correct_tool, "arguments": json.dumps(tool_args)}}]
                    })
                    conversation_messages.append({
                        "role": "tool",
                        "tool_call_id": "forced",
                        "name": correct_tool,
                        "content": tool_result
                    })
                    continue

            # Check if model is hallucinating search results
            if detect_hallucinated_search(content):
                print("   [WARN]  AI IS HALLUCINATING - forcing search")
                search_query = last_user_message.replace("search for", "").strip()[:100]
                search_result = execute_tool("web_search", {"query": search_query})
                conversation_messages.append({
                    "role": "assistant",
                    "content": "Let me search for that.",
                    "tool_calls": [{"id": "forced", "type": "function", "function": {"name": "web_search", "arguments": json.dumps({"query": search_query})}}]
                })
                conversation_messages.append({"role": "tool", "tool_call_id": "forced", "name": "web_search", "content": search_result})
                continue

            # Check if model is claiming to have performed an action it
            # didn't actually call a tool for ("I sent the email", "I turned
            # off the lights", etc.). Stops the worst class of confabulation:
            # user thinks an email was sent when nothing happened.
            hallucinated_tool = detect_hallucinated_action(content)
            if hallucinated_tool and not force_tool:
                print(f"   [WARN] AI claimed to {hallucinated_tool} but no tool called — forcing retry")
                # Replace the lying response with a marker that tells the
                # next iteration "you said you did this, now actually do it"
                # via a forced tool call. The carryover variable survives the
                # loop's `force_tool = None` reset AND the no-tools cap.
                conversation_messages.append({
                    "role": "user",
                    "content": (
                        f"Wait — you said you performed that action, but you "
                        f"didn't actually call any tool. Use the {hallucinated_tool} "
                        f"tool now to actually do it. Get the recipient, subject, "
                        f"and body from the recent conversation."
                    ),
                })
                pending_force_tool = hallucinated_tool
                continue

            # Detect if model is denying tool capabilities after tools succeeded
            if iteration > 1:
                content_lower = content.lower()
                denial_phrases = [
                    "can't access", "cannot access", "don't have access",
                    "unable to access", "can't browse", "cannot browse",
                ]
                is_denial = any(phrase in content_lower for phrase in denial_phrases)

                if is_denial:
                    print(f"   [FIX] Model denying tool capabilities - forcing acknowledgment")
                    # Find the most recent tool result
                    last_tool_result = None
                    last_tool_name = None
                    for msg in reversed(conversation_messages):
                        if msg.get("role") == "tool":
                            last_tool_result = msg.get("content", "")
                            last_tool_name = msg.get("name", "")
                            break

                    if last_tool_result and last_tool_name:
                        conversation_messages.append({
                            "role": "user",
                            "content": (
                                f"The {last_tool_name} tool already completed successfully. "
                                f"Results: {last_tool_result[:500]}\n\n"
                                f"Use these results to answer. Do not say you can't access anything."
                            )
                        })
                        print(f"   [RETRY] Added correction for {last_tool_name}")
                        continue

            # Auto-save visual observation if this response was about an image
            content = assistant_message.get("content", "")
            if _last_vision_image_paths and content:
                _save_visual_observation(content)

            print("[OK] Response complete (no tool calls)")
            return response

        print(f"[TOOL] Model requested {len(tool_calls)} tool call(s)")

        # Check if model is using tools when it shouldn't
        if is_greeting and not force_tool:
            print(f"   [WARN] Model called tool for greeting/casual chat - this is unnecessary!")
            # Let it proceed but warn in logs

        conversation_messages.append(assistant_message)

        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])
            tool_result = execute_tool(function_name, function_args)
            conversation_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": function_name,
                "content": tool_result
            })

            # Gmail operation reminders (prevents confusing read/reply/send)
            _gmail_reminders = {
                "read_gmail": "[You just READ emails. Summarize what you found. Don't say you replied or sent.]",
                "reply_gmail": "[You just REPLIED to emails. Confirm what you did.]",
                "send_gmail": "[You just SENT an email. Confirm what you did.]",
            }
            if function_name in _gmail_reminders:
                try:
                    result_data = json.loads(tool_result)
                    if result_data.get("success"):
                        reminder = _gmail_reminders[function_name]
                        # Fanmail: add personalized reply hint
                        if function_name == "read_gmail" and "fanmail" in str(function_args).lower() and result_data.get("emails"):
                            reminder += " Compose a personalized reply referencing specific details from their message."
                        conversation_messages.append({"role": "user", "content": reminder})
                except Exception:
                    pass

        if iteration == 1:
            conversation_messages.append({
                "role": "user",
                "content": "[Answer the user naturally using the tool results above. Do not call more tools.]"
            })

        # CRITICAL FIX: After executing all tools, loop back to get the model's response to the tool results
        # Without this continue, the code falls through to the error return statement below
        continue

    # If we exit the loop without returning, something went wrong
    return {"choices": [{"message": {"role": "assistant", "content": "I couldn't complete your request."}}]}


# ===== WEB INTERFACE FOR DOCUMENT MANAGEMENT =====

DOCUMENT_MANAGER_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Blue Document Manager [DOC]</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 40px 20px;
        }
        .container {
            max-width: 1080px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            font-size: 2em;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
            font-size: 1.1em;
        }
        .content {
            padding: 32px 36px;
        }
        .upload-section {
            background: #f8f9fa;
            border: 2px dashed #c3c7e8;
            border-radius: 12px;
            padding: 22px;
            text-align: center;
            margin-bottom: 30px;
            transition: all 0.2s;
        }
        .upload-section:hover {
            border-color: #764ba2;
            background: #f0f1f5;
        }
        .upload-section.dragover {
            border-color: #28a745;
            background: #e8f5e9;
            transform: scale(1.01);
        }
        .upload-section h2 {
            color: #667eea;
            font-size: 1.15em;
            margin-bottom: 12px;
        }
        .file-input-wrapper {
            position: relative;
            overflow: hidden;
            display: inline-block;
        }
        .file-input-wrapper input[type=file] {
            position: absolute;
            left: -9999px;
        }
        .file-input-label {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 11px 28px;
            border-radius: 50px;
            cursor: pointer;
            font-size: 1em;
            font-weight: 600;
            transition: transform 0.2s;
            display: inline-block;
        }
        .file-input-label:hover {
            transform: scale(1.05);
        }
        .file-name {
            margin-top: 12px;
            color: #666;
            font-style: italic;
            font-size: 0.9em;
        }
        .upload-btn {
            background: #28a745;
            color: white;
            border: none;
            padding: 11px 28px;
            border-radius: 50px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            margin-top: 14px;
            transition: transform 0.2s;
        }
        .upload-btn:hover:not(:disabled) {
            transform: scale(1.05);
        }
        .upload-btn:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        .documents-list {
            margin-top: 40px;
        }
        .documents-list h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 1.5em;
        }
        .document-item {
            background: #f8f9fa;
            border: 1px solid #ebecf3;
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            transition: box-shadow 0.15s, border-color 0.15s;
        }
        .document-item:hover {
            box-shadow: 0 6px 16px rgba(102,126,234,0.15);
            border-color: #d8d9ef;
        }
        .document-info {
            flex: 1 1 auto;
            min-width: 0;            /* lets long names wrap instead of pushing buttons off-screen */
        }
        .document-name {
            font-weight: 600;
            color: #4b3b8f;
            font-size: 1.05em;
            margin-bottom: 4px;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .document-meta {
            color: #777;
            font-size: 0.85em;
        }
        .doc-actions {
            display: flex;
            gap: 8px;
            flex-shrink: 0;          /* buttons always stay visible */
            align-items: center;
        }
        .delete-btn {
            background: #fff;
            color: #dc3545;
            border: 1.5px solid #f1c4c9;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            white-space: nowrap;
        }
        .delete-btn:hover {
            background: #dc3545;
            color: #fff;
        }
        .download-btn {
            background: #28a745;
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 600;
            display: inline-block;
            white-space: nowrap;
        }
        .download-btn:hover {
            background: #218838;
        }
        .message {
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            font-weight: 500;
        }
        .message.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .message.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 15px;
            text-align: center;
        }
        .stat-number {
            font-size: 2.5em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .stat-label {
            font-size: 1em;
            opacity: 0.9;
        }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .back-link:hover {
            text-decoration: underline;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }
        .empty-state-icon {
            font-size: 4em;
            margin-bottom: 20px;
        }
        .breadcrumb {
            background: #f0f1f5;
            border-radius: 10px;
            padding: 12px 18px;
            margin-bottom: 25px;
            font-size: 0.98em;
            color: #555;
        }
        .breadcrumb a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .sep { color: #aaa; margin: 0 6px; }
        .layout {
            display: grid;
            grid-template-columns: 240px 1fr;
            gap: 28px;
            align-items: start;
        }
        @media (max-width: 760px) {
            .layout { grid-template-columns: 1fr; }
        }
        .sidebar {
            background: #f8f9fa;
            border-radius: 14px;
            padding: 18px;
        }
        .sidebar h3 {
            color: #667eea;
            font-size: 1em;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .tree { list-style: none; }
        .tree li { margin: 2px 0; }
        .tree a {
            display: block;
            padding: 6px 10px;
            border-radius: 8px;
            color: #444;
            text-decoration: none;
            font-size: 0.95em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .tree a:hover { background: #e8e9f5; }
        .tree a.active {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
        }
        .folder-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 30px;
        }
        .folder-card {
            background: #f8f9fa;
            border: 1px solid #e7e8f0;
            border-radius: 12px;
            padding: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: transform 0.15s, box-shadow 0.15s;
        }
        .folder-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(102,126,234,0.18);
        }
        .folder-card a {
            color: #4b3b8f;
            font-weight: 600;
            text-decoration: none;
            font-size: 1.02em;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .folder-card .folder-del {
            background: none;
            border: none;
            color: #c0392b;
            cursor: pointer;
            font-size: 1.1em;
            padding: 2px 6px;
            border-radius: 6px;
        }
        .folder-card .folder-del:hover { background: #fdecea; }
        .newfolder-form {
            display: flex;
            gap: 10px;
            margin-bottom: 35px;
            flex-wrap: wrap;
        }
        .newfolder-form input[type=text] {
            flex: 1;
            min-width: 200px;
            padding: 12px 16px;
            border: 2px solid #d8d9e6;
            border-radius: 10px;
            font-size: 1em;
        }
        .newfolder-form input[type=text]:focus {
            outline: none;
            border-color: #667eea;
        }
        .newfolder-form button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 10px;
            font-weight: 600;
            cursor: pointer;
        }
        .section-title {
            color: #333;
            font-size: 1.25em;
            margin: 0 0 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎵💡 Blue Document Manager</h1>
            <p>Upload documents to teach Blue about your files</p>
        </div>

        <div class="content">
            {% if message %}
            <div class="message {{ message_type }}">
                {{ message }}
            </div>
            {% endif %}

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{{ document_count }}</div>
                    <div class="stat-label">Documents</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ folder_count }}</div>
                    <div class="stat-label">Folders</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{{ total_size }}</div>
                    <div class="stat-label">Total Size</div>
                </div>
            </div>

            <div class="breadcrumb">
                <a href="/documents?folder=">📚 Library</a>
                {% for crumb in breadcrumb %}
                    <span class="sep">/</span>
                    <a href="/documents?folder={{ crumb.path|urlencode }}">{{ crumb.name }}</a>
                {% endfor %}
            </div>

            <div class="layout">
                <div class="sidebar">
                    <h3>Folders</h3>
                    <ul class="tree">
                        <li><a href="/documents?folder=" class="{{ 'active' if not current_folder else '' }}">📚 Library</a></li>
                        {% for node in folder_tree %}
                        <li>
                            <a href="/documents?folder={{ node.path|urlencode }}"
                               class="{{ 'active' if node.path == current_folder else '' }}"
                               style="padding-left: {{ 10 + node.depth * 14 }}px;"
                               title="{{ node.path }}">📁 {{ node.name }}</a>
                        </li>
                        {% endfor %}
                    </ul>
                </div>

                <div class="main">
                    <h2 class="section-title">🗂️ Folders in this area</h2>
                    {% if subfolders %}
                    <div class="folder-grid">
                        {% for sub in subfolders %}
                        <div class="folder-card">
                            <a href="/documents?folder={{ sub.path|urlencode }}">📁 {{ sub.name }}</a>
                            <form method="POST" action="/documents/folder/delete" style="margin:0;"
                                  onsubmit="return confirm('Delete folder {{ sub.name }}? It must be empty.');">
                                <input type="hidden" name="folder" value="{{ sub.path }}">
                                <input type="hidden" name="back" value="{{ current_folder }}">
                                <button type="submit" class="folder-del" title="Delete folder">✕</button>
                            </form>
                        </div>
                        {% endfor %}
                    </div>
                    {% else %}
                    <p style="color:#999; margin-bottom: 25px;">No subfolders here yet.</p>
                    {% endif %}

                    <form method="POST" action="/documents" class="newfolder-form">
                        <input type="hidden" name="action" value="create_folder">
                        <input type="hidden" name="parent" value="{{ current_folder }}">
                        <input type="text" name="name" placeholder="New folder name (e.g. Publications)" required>
                        <button type="submit">+ Add Folder</button>
                    </form>

                    <div class="upload-section" id="dropZone">
                        <h2>📤 Upload to {{ current_folder if current_folder else 'Library root' }}</h2>
                        <p style="color: #666; margin-bottom: 20px;">
                            <strong>Drag &amp; drop a file here</strong> — or use the button below.<br>
                            Supported: PDF, Word (.doc, .docx), Text (.txt, .md)
                        </p>
                        <form method="POST" enctype="multipart/form-data" id="uploadForm">
                            <input type="hidden" name="action" value="upload">
                            <input type="hidden" name="folder" value="{{ current_folder }}">
                            <div class="file-input-wrapper">
                                <input type="file" name="file" id="fileInput" accept=".pdf,.doc,.docx,.txt,.md" required>
                                <label for="fileInput" class="file-input-label">Choose File</label>
                            </div>
                            <div class="file-name" id="fileName">No file chosen</div>
                            <br>
                            <button type="submit" class="upload-btn" id="uploadBtn">Upload & Index</button>
                        </form>
                    </div>

                    <div class="documents-list">
                        <h2 class="section-title">📄 Documents in this folder</h2>
                        {% if documents %}
                            {% for doc in documents %}
                            <div class="document-item">
                                <div class="document-info">
                                    <div class="document-name">{{ doc.filename }}</div>
                                    <div class="document-meta">
                                        Uploaded: {{ doc.uploaded_at }} | Size: {{ doc.size }}
                                        {% if doc.created_by_blue %}
                                        <span style="color: #667eea; font-weight: 600;"> • Created by Blue</span>
                                        {% endif %}
                                    </div>
                                </div>
                                <div class="doc-actions">
                                    <a href="/documents/download?folder={{ current_folder|urlencode }}&filename={{ doc.filename|urlencode }}" class="download-btn">
                                        Download
                                    </a>
                                    <form method="POST" action="/documents/delete" style="display: inline; margin: 0;">
                                        <input type="hidden" name="folder" value="{{ current_folder }}">
                                        <input type="hidden" name="filename" value="{{ doc.filename }}">
                                        <button type="submit" class="delete-btn" onclick="return confirm('Delete this document?')">
                                            Delete
                                        </button>
                                    </form>
                                </div>
                            </div>
                            {% endfor %}
                        {% else %}
                            <div class="empty-state">
                                <div class="empty-state-icon">🔭</div>
                                <h3>No documents in this folder</h3>
                                <p>Upload one above, or pick another folder.</p>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <a href="/" class="back-link">← Back to main page</a>
            <a href="/perspective" class="back-link" style="margin-left: 24px;">🧠 My Perspective Profile</a>
        </div>
    </div>

    <script>
        const fileInput = document.getElementById('fileInput');
        const fileNameEl = document.getElementById('fileName');
        const dropZone = document.getElementById('dropZone');
        const uploadForm = document.getElementById('uploadForm');
        const ALLOWED = ['pdf', 'doc', 'docx', 'txt', 'md'];

        fileInput.addEventListener('change', function(e) {
            fileNameEl.style.color = '#666';
            fileNameEl.textContent = e.target.files[0] ? e.target.files[0].name : 'No file chosen';
        });

        uploadForm.addEventListener('submit', function() {
            const btn = document.getElementById('uploadBtn');
            btn.disabled = true;
            btn.textContent = 'Uploading...';
        });

        // Drag-and-drop: drop a file straight from Explorer without ever
        // opening the native "Choose File" dialog.
        function assignDroppedFile(file) {
            const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
            if (ALLOWED.indexOf(ext) === -1) {
                fileNameEl.style.color = '#dc3545';
                fileNameEl.textContent = 'Unsupported file type: .' + ext;
                return;
            }
            const dt = new DataTransfer();
            dt.items.add(file);
            fileInput.files = dt.files;
            fileNameEl.style.color = '#28a745';
            fileNameEl.textContent = file.name + ' — ready, click "Upload & Index"';
        }

        function highlight(e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('dragover');
        }
        dropZone.addEventListener('dragenter', highlight);
        dropZone.addEventListener('dragover', highlight);
        dropZone.addEventListener('dragleave', function(e) {
            e.preventDefault();
            e.stopPropagation();
            if (!dropZone.contains(e.relatedTarget)) {
                dropZone.classList.remove('dragover');
            }
        });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('dragover');
            const files = e.dataTransfer && e.dataTransfer.files;
            if (files && files.length) {
                assignDroppedFile(files[0]);
            }
        });

        // A file dropped outside the box would otherwise make the browser
        // navigate away from this page — swallow those stray drops.
        window.addEventListener('dragover', function(e) { e.preventDefault(); });
        window.addEventListener('drop', function(e) { e.preventDefault(); });
    </script>
</body>
</html>
"""

def _library_view_context(current_folder: str, message=None, message_type=None) -> dict:
    """Assemble everything the document-manager template needs for one folder
    view: the folder tree, breadcrumb, immediate subfolders, and the documents
    that live in the current folder."""
    current_folder = _safe_rel_folder(current_folder)

    index = load_document_index()
    all_docs = [d for d in index.get('documents', []) if not d.get('camera_capture', False)]

    # Total size first — before we replace any size with a formatted string.
    total_size_bytes = sum((d.get('size', 0) or 0) for d in all_docs)
    total_size = f"{total_size_bytes / 1024 / 1024:.1f} MB" if total_size_bytes > 0 else "0 MB"

    # Documents in THIS folder only (format sizes for display).
    documents = [d for d in all_docs if _safe_rel_folder(d.get('folder', '')) == current_folder]
    for doc in documents:
        size_bytes = doc.get('size', 0) or 0
        if isinstance(size_bytes, (int, float)):
            doc['size'] = (f"{size_bytes / 1024 / 1024:.1f} MB" if size_bytes > 1024 * 1024
                           else f"{size_bytes / 1024:.1f} KB")

    all_folders = list_library_folders()
    folder_tree = [
        {'path': f, 'name': f.split('/')[-1], 'depth': f.count('/')}
        for f in all_folders
    ]
    subfolders = [
        {'path': (f"{current_folder}/{name}" if current_folder else name), 'name': name}
        for name in list_subfolders(current_folder)
    ]

    # Breadcrumb segments with cumulative paths.
    breadcrumb, acc = [], []
    if current_folder:
        for seg in current_folder.split('/'):
            acc.append(seg)
            breadcrumb.append({'name': seg, 'path': '/'.join(acc)})

    return dict(
        documents=documents,
        document_count=len(all_docs),
        folder_count=len(all_folders),
        total_size=total_size,
        current_folder=current_folder,
        folder_tree=folder_tree,
        subfolders=subfolders,
        breadcrumb=breadcrumb,
        message=message,
        message_type=message_type,
    )


@app.route('/documents', methods=['GET', 'POST'])
def manage_documents():
    """Folder-aware web interface for the document library."""
    message = None
    message_type = None
    current_folder = _safe_rel_folder(request.values.get('folder', '') or request.values.get('parent', ''))

    if request.method == 'POST':
        action = request.form.get('action', 'upload')

        if action == 'create_folder':
            parent = _safe_rel_folder(request.form.get('parent', ''))
            name = _safe_folder_segment(request.form.get('name', ''))
            current_folder = parent
            if not name:
                message, message_type = "Please enter a valid folder name.", "error"
            else:
                rel = f"{parent}/{name}" if parent else name
                res = create_library_folder(rel)
                if res.get('success'):
                    message, message_type = f"📁 Created folder '{name}'.", "success"
                else:
                    message, message_type = f"Couldn't create folder: {res.get('error')}", "error"

        elif 'file' not in request.files or request.files['file'].filename == '':
            message, message_type = "No file selected", "error"
        else:
            file = request.files['file']
            if not allowed_file(file.filename):
                message = f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
                message_type = "error"
            else:
                try:
                    filename = secure_filename(file.filename)
                    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    text_doc = ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx')
                    if text_doc:
                        target_dir = _abs_library_path(current_folder)
                        os.makedirs(target_dir, exist_ok=True)
                        filepath = os.path.join(target_dir, filename)
                    else:
                        # Images and other non-text uploads stay in UPLOAD_FOLDER.
                        filepath = os.path.join(str(UPLOAD_FOLDER), filename)

                    file.save(filepath)
                    folder = _folder_of_filepath(filepath)
                    file_size = os.path.getsize(filepath)
                    file_hash = get_file_hash(filepath)

                    index = load_document_index()
                    duplicate = any(doc.get('hash') == file_hash for doc in index['documents'])

                    if duplicate:
                        message = f"Document '{filename}' already exists (duplicate detected)"
                        message_type = "error"
                        os.remove(filepath)
                    else:
                        text_content = extract_text_from_file(filepath)
                        text_preview = text_content[:500] if not text_content.startswith("Error") else ""

                        doc_entry = {
                            'filename': filename,
                            'filepath': str(filepath),
                            'folder': folder,
                            'size': file_size,
                            'hash': file_hash,
                            'uploaded_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
                            'text_preview': text_preview,
                            'indexed_in_rag': False,
                        }
                        index['documents'].append(doc_entry)
                        save_document_index(index)

                        try:
                            from blue.tools.rag import index_document as rag_index
                            if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html'):
                                rag_result = rag_index(
                                    filepath, filename,
                                    doc_id=file_hash, text=text_content, folder=folder,
                                )
                                doc_entry['indexed_in_rag'] = rag_result.get('success', False)
                                if doc_entry['indexed_in_rag']:
                                    print(f"   [RAG] Indexed {rag_result.get('chunks_indexed', 0)} chunks for {filename} [{folder or 'root'}]")
                                else:
                                    print(f"   [RAG] indexing skipped: {rag_result.get('error')}")
                        except ImportError:
                            print("   [WARN] ChromaDB not installed, skipping local RAG index")
                        except Exception as e:
                            print(f"   [WARN] Local RAG indexing error: {e}")

                        save_document_index(index)
                        where = current_folder if current_folder else "Library root"
                        message = f"✅ Uploaded and indexed '{filename}' into {where}!"
                        message_type = "success"

                except Exception as e:
                    message = f"Error uploading file: {str(e)}"
                    message_type = "error"

    ctx = _library_view_context(current_folder, message, message_type)
    return render_template_string(DOCUMENT_MANAGER_HTML, **ctx)


@app.route('/documents/delete', methods=['POST'])
def delete_document():
    """Delete one document, identified by folder + filename so files with the
    same name in different folders don't collide."""
    folder = _safe_rel_folder(request.form.get('folder', ''))
    filename = request.form.get('filename', '')
    try:
        index = load_document_index()
        documents = index.get('documents', [])
        kept, deleted = [], False
        for doc in documents:
            same_name = doc.get('filename') == filename
            same_folder = _safe_rel_folder(doc.get('folder', '')) == folder
            if same_name and same_folder and not deleted:
                filepath = doc.get('filepath', '')
                if filepath and os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                try:
                    from blue.tools.rag import remove_document
                    remove_document(doc.get('hash', ''))
                except Exception:
                    pass
                deleted = True
            else:
                kept.append(doc)
        if deleted:
            index['documents'] = kept
            save_document_index(index)
    except Exception as e:
        print(f"Error deleting document: {e}")
    return redirect(url_for('manage_documents', folder=folder))


@app.route('/documents/folder/delete', methods=['POST'])
def delete_library_folder():
    """Delete an (empty) library folder. Refuses if it still holds documents
    or subfolders, so files are never silently destroyed."""
    folder = _safe_rel_folder(request.form.get('folder', ''))
    back = _safe_rel_folder(request.form.get('back', ''))
    full = _abs_library_path(folder)
    base = os.path.abspath(DOCUMENTS_FOLDER)
    try:
        if folder and os.path.isdir(full) and os.path.abspath(full) != base:
            if os.listdir(full):
                # Non-empty (files or subfolders) — don't destroy anything.
                print(f"   [LIBRARY] refused to delete non-empty folder: {folder}")
            else:
                os.rmdir(full)
                print(f"   [LIBRARY] deleted empty folder: {folder}")
    except Exception as e:
        print(f"   [LIBRARY] folder delete error: {e}")
    return redirect(url_for('manage_documents', folder=back))


@app.route('/documents/download', methods=['GET'])
def download_document():
    """Download a document, resolved via the index by folder + filename (with
    a legacy fallback that scans the known storage folders)."""
    try:
        from flask import send_file
        folder = _safe_rel_folder(request.args.get('folder', ''))
        filename = request.args.get('filename', '')

        filepath = None
        for doc in load_document_index().get('documents', []):
            if (doc.get('filename') == filename
                    and _safe_rel_folder(doc.get('folder', '')) == folder):
                cand = doc.get('filepath', '')
                if cand and os.path.exists(cand):
                    filepath = cand
                break

        if not filepath:
            safe = secure_filename(filename)
            for base in [_abs_library_path(folder), str(UPLOAD_FOLDER), DOCUMENTS_FOLDER, CAMERA_FOLDER]:
                candidate = os.path.join(base, safe)
                if os.path.exists(candidate):
                    filepath = candidate
                    break

        if not filepath:
            return "File not found", 404

        return send_file(filepath, as_attachment=True, download_name=os.path.basename(filepath))

    except Exception as e:
        print(f"Error downloading document: {e}")
        return f"Error: {str(e)}", 500


PERSPECTIVE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>My Perspective Profile</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
               background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 40px 20px; }
        .container { max-width: 900px; margin: 0 auto; background: white; border-radius: 20px;
                     box-shadow: 0 20px 60px rgba(0,0,0,0.3); overflow: hidden; }
        .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 28px 30px; }
        .header h1 { font-size: 1.7em; margin-bottom: 6px; }
        .header p { opacity: 0.9; }
        .content { padding: 32px 36px; }
        .meta { background: #f0f1f5; border-radius: 10px; padding: 12px 16px; color: #555;
                font-size: 0.9em; margin-bottom: 20px; }
        .meta b { color: #4b3b8f; }
        textarea { width: 100%; min-height: 460px; padding: 18px; border: 2px solid #d8d9e6;
                   border-radius: 12px; font-size: 0.98em; line-height: 1.5; resize: vertical;
                   font-family: 'Segoe UI', system-ui, sans-serif; }
        textarea:focus { outline: none; border-color: #667eea; }
        .actions { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; align-items: center; }
        .btn { border: none; padding: 12px 26px; border-radius: 10px; font-weight: 600;
               font-size: 1em; cursor: pointer; text-decoration: none; display: inline-block; }
        .btn-save { background: #28a745; color: #fff; }
        .btn-regen { background: #fff; color: #667eea; border: 1.5px solid #c3c7e8; }
        .btn-regen:hover { background: #f0f1f5; }
        .hint { color: #888; font-size: 0.85em; }
        .message { padding: 14px 16px; border-radius: 10px; margin-bottom: 20px; font-weight: 500; }
        .message.success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .message.error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .message.info { background: #e7e9fb; color: #3a3a7a; border: 1px solid #c9cdf3; }
        .back-link { display: inline-block; margin-top: 22px; color: #667eea; text-decoration: none; font-weight: 600; }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 My Perspective Profile</h1>
            <p>How Blue understands your thinking — distilled from the {{ owner_name }} folder. Edit it freely; your edits stick.</p>
        </div>
        <div class="content">
            {% if message %}<div class="message {{ message_type }}">{{ message }}</div>{% endif %}

            <div class="meta">
                {% if has_profile %}
                    <b>Sources:</b> {{ source_docs|join(', ') if source_docs else 'none' }}<br>
                    <b>{{ 'Edited by you' if user_edited else 'Generated' }}:</b> {{ stamp }}
                    {% if user_edited %} &nbsp;•&nbsp; <span style="color:#7a5b00;">manual edits are preserved (auto-refresh won't overwrite)</span>{% endif %}
                {% else %}
                    No profile yet. Click <b>Regenerate from my writing</b> to build it from your {{ owner_name }} folder.
                {% endif %}
            </div>

            <form method="POST" action="/perspective">
                <textarea name="profile" placeholder="Blue hasn't learned your perspective yet — regenerate to build it, or write/paste your own here and save.">{{ profile }}</textarea>
                <div class="actions">
                    <button type="submit" name="action" value="save" class="btn btn-save">💾 Save my edits</button>
                    <button type="submit" name="action" value="regenerate" class="btn btn-regen"
                            onclick="return confirm('Rebuild the profile from scratch by reading your {{ owner_name }} folder? This replaces the current text and can take a minute.');">
                        ♻️ Regenerate from my writing
                    </button>
                    <span class="hint">Regenerating reads each document, so it may take a minute.</span>
                </div>
            </form>

            <a href="/documents" class="back-link">← Back to documents</a>
        </div>
    </div>
</body>
</html>
"""


@app.route('/perspective', methods=['GET', 'POST'])
def perspective_profile_page():
    """Read / edit / regenerate the distilled worldview profile."""
    message = None
    message_type = None

    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'regenerate':
            try:
                folders = _owner_publication_folders()
                if not folders:
                    message = (f"I couldn't find your publications folder. Create a folder named "
                               f"'{BLUE_OWNER_NAME}' (or 'Publications') and put your writing in it.")
                    message_type = "error"
                else:
                    obj = build_perspective_profile(force=True)
                    if obj.get('profile'):
                        message = f"Rebuilt your profile from {len(obj.get('source_docs', []))} document(s)."
                        message_type = "success"
                    else:
                        message = ("Couldn't build a profile — is the local model running, and are there "
                                   "readable documents in your publications folder?")
                        message_type = "error"
            except Exception as e:
                message, message_type = f"Error regenerating: {e}", "error"
        else:  # save
            save_perspective_profile_text(request.form.get('profile', ''))
            message, message_type = "Saved. Blue will use your edited profile from now on.", "success"

    cached = _load_cached_profile()
    has_profile = bool(cached.get('profile'))
    user_edited = bool(cached.get('user_edited'))
    return render_template_string(
        PERSPECTIVE_HTML,
        owner_name=BLUE_OWNER_NAME,
        profile=cached.get('profile', ''),
        has_profile=has_profile,
        user_edited=user_edited,
        source_docs=cached.get('source_docs', []),
        stamp=cached.get('edited_at') if user_edited else cached.get('generated_at', '—'),
        message=message,
        message_type=message_type,
    )


# ===== Conversation Persistence Functions =====

def _normalize_message_alternation(messages: list) -> list:
    """Normalize the message list to satisfy strict chat templates.

    Qwen and several other models render prompts via Jinja templates that
    require:
      1. All system messages at the start, in order.
      2. After system, conversation begins with a user turn.
      3. user/assistant strictly alternate (no consecutive user-user or
         assistant-assistant pairs).
      4. The last message is typically user (so the model has a query).

    Our sanitizer drops stale assistant turns, which can produce orphan
    leading assistants ("first non-system is assistant") or consecutive
    user turns ("user, user, user"). Both make Qwen return 400 with
    "No user query found in messages".

    Strategy:
      - Keep all system messages at the front, content order preserved.
      - Drop any leading assistant turns before the first user.
      - Merge consecutive same-role turns into a single message
        (concatenate content with a blank-line separator).
    """
    if not messages:
        return messages

    # Partition: leading system messages stay; everything else gets normalized.
    sys_block, rest = [], []
    for m in messages:
        if m.get("role") == "system" and not rest:
            sys_block.append(m)
        else:
            rest.append(m)

    # Drop any assistant messages before the first user turn — they're
    # orphans with no preceding user query.
    first_user_idx = next(
        (i for i, m in enumerate(rest) if m.get("role") == "user"), -1
    )
    if first_user_idx == -1:
        # No user message at all. Add a placeholder so the template doesn't
        # blow up; better than 400.
        return sys_block + [{"role": "user", "content": "(continue)"}]
    rest = rest[first_user_idx:]

    # Merge consecutive same-role turns. For text content we concatenate;
    # for list content (vision payloads) we just keep the latest one to
    # avoid reordering image placeholders.
    merged: list = []
    for m in rest:
        if not merged or merged[-1].get("role") != m.get("role"):
            merged.append(dict(m))
            continue
        # Same role as previous — merge.
        prev = merged[-1]
        prev_content = prev.get("content")
        cur_content = m.get("content")
        if isinstance(prev_content, str) and isinstance(cur_content, str):
            prev["content"] = (prev_content.rstrip() + "\n\n" + cur_content.lstrip()).strip()
        else:
            # If either side is a list (vision payload), prefer the newer
            # message intact rather than mangling structure.
            merged[-1] = dict(m)

    return sys_block + merged


def _splice_context_after_system(messages: list, context: list) -> list:
    """Merge injected context into the leading system message.

    Earlier versions inserted each context item as its own system message.
    That worked on permissive endpoints, but stricter chat templates
    (notably the 35B Qwen and several other recent models) reject prompts
    with multiple consecutive system messages and return 400 — taking down
    the whole memory pipeline.

    The fix: keep the structure simple — one leading system message with
    everything concatenated. The text content of the injected blocks is
    preserved verbatim (still wrapped in <known_facts>, <long_term_notes>,
    etc.) so the model still sees the structured cues; only the message
    boundaries collapse.
    """
    if not context:
        return messages
    if not messages:
        # No existing system message — just emit a single system message
        # built from the context, then the original (empty) tail.
        merged = "\n\n".join(
            (m.get("content") or "") for m in context if isinstance(m.get("content"), str)
        ).strip()
        return [{"role": "system", "content": merged}] if merged else messages

    if messages[0].get("role") == "system" and isinstance(messages[0].get("content"), str):
        existing_system = messages[0]
        injected_text = "\n\n".join(
            (m.get("content") or "") for m in context if isinstance(m.get("content"), str)
        ).strip()
        if not injected_text:
            return messages
        merged_content = f"{existing_system['content'].rstrip()}\n\n{injected_text}"
        new_system = {"role": "system", "content": merged_content}
        return [new_system] + messages[1:]

    # No leading system message — prepend one built from the context.
    injected_text = "\n\n".join(
        (m.get("content") or "") for m in context if isinstance(m.get("content"), str)
    ).strip()
    if not injected_text:
        return messages
    return [{"role": "system", "content": injected_text}] + messages


# Words a model often emits when admitting it doesn't know something.
# Past assistant turns with these phrases are toxic to keep in the prompt:
# the next-turn model sees them and confidently repeats the same wrong answer.
_ASSISTANT_REFUSAL_MARKERS = (
    "i don't have", "i do not have", "i dont have",
    "i don't know", "i do not know", "i dont know",
    "i only have", "i only know",
    "i haven't been told", "i havent been told",
    "you haven't told me", "you havent told me",
    "not in my memory", "not saved yet", "not yet recorded",
    "i'm not sure", "im not sure",
    # Self-deprecating "I have no memory" framings. These are especially
    # toxic — they cause the next turn to claim ignorance even when the
    # facts block has the answer.
    "blank slate", "just woke up", "i just woke",
    "haven't met", "havent met", "have not met",
    "no information stored", "no information saved",
    "memory is blank", "memory is currently blank",
    "no details about", "no details on",
    "haven't stored", "havent stored", "have not stored",
    "my records are empty", "no records",
    "i'm new here", "im new here",
    "introduce yourself and",  # "Introduce yourself and the crew, and I'll remember"
    "help me out? introduce", "please tell me",
)


def _sanitize_inbound_messages(messages: list) -> list:
    """Strip past assistant turns that would mislead the model.

    Two classes of toxic turns are removed:

    1. **Refusals.** When Blue answered "I don't have that yet", that line
       in the conversation history acts as authority — the next turn just
       repeats it even when the canonical facts now contain the answer.

    2. **Stale daughter names.** The Ohbot client sends the full session
       history, including responses Blue gave before the facts table was
       cleaned. If a past response said "Annie is your daughter", the model
       reuses that name on the next turn — a strong AUTHORITATIVE system
       instruction is not enough to override neighbouring text. We pull the
       canonical names live from the `daughter_name` fact and drop any
       assistant turn that mentions a *different* name in a daughter
       relation.

    The corresponding user turn is left alone, so the conversation flow
    still reads naturally — the model just doesn't get to anchor on Blue's
    earlier wrong answer.
    """
    if not messages:
        return messages

    canonical_daughter_names: set = set()
    try:
        if ENHANCED_MEMORY_AVAILABLE and memory_system:
            facts = memory_system.load_facts() or {}
            raw = facts.get("daughter_name") or facts.get("daughter_names") or ""
            for piece in re.split(r"[,|;]|\sand\s", raw):
                piece = piece.strip()
                if piece:
                    canonical_daughter_names.add(piece.lower())
    except Exception:
        canonical_daughter_names = set()

    # Strategy: split into sentences; for any sentence that mentions
    # "daughter"/"daughters", look at the capitalized words in that sentence
    # — those are likely names being asserted as daughters. If any of those
    # names isn't canonical (and isn't a known non-name like "Got" or place
    # names), the whole assistant turn is stale.
    _sent_split = re.compile(r"(?<=[.!?])\s+")
    _name_re = re.compile(r"\b([A-Z][a-z]{2,14})\b")
    # Capitalized words that aren't names. Sentence-starters, days/months,
    # places, and the user's known non-daughter family.
    _safe_capitalized = {
        "your", "you", "the", "this", "that", "they", "their", "them",
        "blue", "stella", "alex", "nori", "mommy", "mom", "mama", "daddy",
        "papa", "ohbot", "kitchener", "boston", "wilfrid", "laurier",
        "doctor", "kci", "google", "gmail", "monday", "tuesday", "wednesday",
        "thursday", "friday", "saturday", "sunday", "january", "february",
        "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december",
        # Common sentence starters and filler words that pass [A-Z][a-z]+
        "got", "yes", "no", "ok", "okay", "sure", "thanks", "thank",
        "here", "right", "well", "let", "so", "now", "still", "also",
        "and", "but", "or", "for", "from", "with", "about", "what",
        "who", "where", "when", "which", "how", "why",
        "i", "i'm", "im", "ill",
        "based", "currently", "earlier", "since", "if", "as",
        "understood", "noted", "got", "great", "perfect",
        "these", "those", "such", "any", "some", "only", "just",
        # Typical visual-description words that look like names
        "she", "he", "his", "hers", "her", "its",
    }

    out, dropped_refusal, dropped_wrong_name = [], 0, 0
    for m in messages:
        if m.get("role") != "assistant":
            out.append(m)
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or not content.strip():
            out.append(m)
            continue

        content_lower = content.lower()

        # 1) Refusal pattern.
        if any(marker in content_lower for marker in _ASSISTANT_REFUSAL_MARKERS):
            dropped_refusal += 1
            continue

        # 2) Stale daughter name: any sentence that contains "daughter"
        # AND a non-canonical capitalized word makes the turn stale.
        if canonical_daughter_names:
            stale = False
            for sentence in _sent_split.split(content):
                if "daughter" not in sentence.lower():
                    continue
                names = {
                    h.group(1).lower() for h in _name_re.finditer(sentence)
                } - _safe_capitalized
                wrong = names - canonical_daughter_names
                if wrong:
                    stale = True
                    break
            if stale:
                dropped_wrong_name += 1
                continue

        out.append(m)

    if dropped_refusal or dropped_wrong_name:
        print(
            f"   [SANITIZE] Dropped {dropped_refusal} refusal + "
            f"{dropped_wrong_name} stale-name assistant turn(s) from inbound history"
        )
    return out


def save_conversation_to_db(user_name: str, role: str, content: str,
                            session_id: str = None, tool_used: str = None):
    """Save a conversation message to the database for long-term memory"""
    # Determine importance based on length and content
    importance = 5  # Default
    if len(content) > 500:
        importance = 7  # Longer messages are more important
    if any(keyword in content.lower() for keyword in ['remember', 'important', 'don\'t forget']):
        importance = 8  # User explicitly wants to remember

    # Save to enhanced memory system (primary)
    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        try:
            memory_system.log_conversation(
                user_name=user_name,
                role=role,
                content=content,
                session_id=session_id,
                importance=importance,
            )
        except Exception as e:
            log.warning(f"Enhanced memory log failed: {e}")

    # Also save to legacy DB if available (backward compat)
    if not CONVERSATION_DB_AVAILABLE or not db:
        return

    try:
        db.save_conversation(
            user_name=user_name,
            role=role,
            content=content,
            session_id=session_id,
            tool_used=tool_used,
            importance=importance
        )
        log.debug(f"Saved {role} message to database (importance: {importance})")
    except Exception as e:
        log.warning(f"Failed to save conversation: {e}")


def load_recent_context(user_name: str = "Alex", limit: int = 10):
    """Load recent conversations from database for context"""
    if not CONVERSATION_DB_AVAILABLE or not db:
        return []

    try:
        conversations = db.get_recent_conversations(user_name=user_name, limit=limit)

        # Format for LLM context
        context_messages = []
        for conv in conversations:
            context_messages.append({
                "role": conv.get("role", "user"),
                "content": conv.get("content", "")
            })

        log.debug(f"Loaded {len(context_messages)} messages from database history")
        return context_messages
    except Exception as e:
        log.warning(f"Failed to load conversation context: {e}")
        return []


def extract_ocf_facts(messages: list) -> str:
    """Extract key facts from .ocf conversations for permanent memory."""
    if not messages:
        return ""

    facts = {'identity': [], 'family': [], 'capabilities': [], 'location': []}

    for msg in messages:
        if msg.get('role') not in ['user', 'assistant']:
            continue
        content = msg.get('content', '')
        content_lower = content.lower()
        if len(content) < 20 or content.startswith('{'):
            continue

        if any(term in content_lower for term in ['your name is blue', 'you are blue', 'created by', 'you are our family robot', 'what makes you different']):
            if content not in facts['identity'] and len(facts['identity']) < 3:
                facts['identity'].append(content[:300])
        elif any(term in content_lower for term in ['alex is', 'stella is', 'our family', 'your daughters', 'extended family', 'daughters are', 'family includes', 'felix', 'felix and svetlana']):
            if content not in facts['family'] and len(facts['family']) < 5:
                facts['family'].append(content[:500])
        elif any(term in content_lower for term in ['your tools', 'you can control', 'you have access to', 'tell me about your origin']):
            if content not in facts['capabilities'] and len(facts['capabilities']) < 2:
                facts['capabilities'].append(content[:300])
        elif any(term in content_lower for term in ['live on mansion', 'live in kitchener', 'waterloo', 'mansion st']):
            if content not in facts['location'] and len(facts['location']) < 2:
                facts['location'].append(content[:200])

    fact_parts = []
    if facts['identity']:
        identity = max(facts['identity'], key=len)
        fact_parts.append(f"IDENTITY: {identity.strip()}")
    if facts['family']:
        family_info = " | ".join(facts['family'])
        fact_parts.append(f"FAMILY: {family_info.strip()}")
    if facts['capabilities']:
        capabilities = facts['capabilities'][0]
        fact_parts.append(f"CAPABILITIES: {capabilities.strip()}")
    if facts['location']:
        location = facts['location'][0]
        fact_parts.append(f"LOCATION: {location.strip()}")

    if not fact_parts:
        return ""

    return "\n\n=== LONG-TERM MEMORY (from .ocf) ===\n" + "\n\n".join(fact_parts)


def should_include_history(messages) -> bool:
    """Determine if we should inject historical context.

    Old behaviour refused injection on long sessions (>10 messages), which
    starved Blue of recall in exactly the conversations that needed it most.
    New rule: inject unless the client already supplied a healthy in-flight
    transcript AND the user isn't explicitly invoking past context."""
    if not messages:
        return True

    non_system = [m for m in messages if m.get('role') != 'system']

    # Always inject for fresh conversations (client only sent the latest turn).
    if len(non_system) <= 4:
        return True

    # Always inject when the user is explicitly asking about prior context.
    last_msg = (messages[-1].get('content', '') or '').lower()
    past_indicators = (
        'remember', 'recall', 'what did', 'we discussed', 'talked about',
        'mentioned', 'said before', 'last time', 'previously', 'earlier',
        'yesterday', 'the other day',
    )
    if any(indicator in last_msg for indicator in past_indicators):
        return True

    # Mid-length conversations: still inject, but the caller will trim.
    if len(non_system) <= 12:
        return True

    return False


# ===== MAIN API ENDPOINTS =====

@app.route('/v1/chat/completions', methods=['POST'])


def chat_completions():
    """Main endpoint with conversation persistence"""
    try:
        data = request.json
        messages = data.get("messages", [])

        print(f"")
        print(f"{'='*60}")
        print(f"[MSG] Received request from Ohbot")

        # Extract user name from messages if available (default to Alex)
        user_name = "Alex"

        # Find the last actual USER message
        user_messages = [m for m in messages if m.get('role') == 'user']
        if user_messages:
            last_user_msg = user_messages[-1].get('content', '')

            # If it's too long (probably includes system prompt), show shorter version
            if len(last_user_msg) > 200:
                if "You are Blue" in last_user_msg:
                    if len(user_messages) > 1:
                        last_user_msg = user_messages[-2].get('content', last_user_msg)

            print(f"   [SPEAK]  User asked: {last_user_msg[:150]}..." if len(last_user_msg) > 150 else f"   [SPEAK]  User asked: {last_user_msg}")

            # Save user message in background (don't block response)
            import threading
            threading.Thread(
                target=save_conversation_to_db,
                args=(user_name, "user", last_user_msg, None),
                daemon=True
            ).start()

        # QUICK PRE-CHECK: Will this be a zero-LLM tool call?
        # If so, skip the expensive history injection and go straight to processing.
        _ZERO_LLM_QUICK = {'control_music', 'control_lights', 'get_local_time',
                           'set_timer', 'music_visualizer', 'play_music'}
        _quick_result = TOOL_SELECTOR.select_tool(last_user_msg) if last_user_msg else None
        _quick_tool = _quick_result.primary_tool.tool_name if (_quick_result and _quick_result.primary_tool) else None
        _quick_params = _quick_result.primary_tool.extracted_params if (_quick_result and _quick_result.primary_tool) else {}
        _is_zero_llm = (_quick_tool in _ZERO_LLM_QUICK and bool(_quick_params))

        if not _is_zero_llm:
            # SANITIZE inbound history before anything else. Ohbot ships the
            # full conversation back each turn; if Blue ever answered a daughter
            # question wrongly (e.g. "Annie") or admitted ignorance, that text
            # is now in the prompt every turn and overrides the facts block by
            # sheer proximity.
            messages = _sanitize_inbound_messages(messages)

            # INJECT HISTORICAL CONTEXT (only for LLM-bound requests)
            _needs_history = len(last_user_msg.split()) > 3 if last_user_msg else False
            if _needs_history:
                # Enhanced memory has its own SQLite store and ChromaDB — it
                # does NOT depend on the legacy `blue_database` module. Don't
                # gate it on CONVERSATION_DB_AVAILABLE; that flag only covers
                # the legacy fallback path below.
                if ENHANCED_MEMORY_AVAILABLE and memory_system:
                    should_inject = memory_system.should_inject_context(messages)
                    if should_inject:
                        historical_context = memory_system.build_context(messages, user_name=user_name)
                        if historical_context:
                            print(f"   [MEMORY] ✓ Injecting {len(historical_context)} messages (semantic + recent)")
                            messages = _splice_context_after_system(messages, historical_context)
                elif CONVERSATION_DB_AVAILABLE and should_include_history(messages):
                    historical_context = load_recent_context(user_name=user_name, limit=6)
                    if historical_context:
                        print(f"   [MEMORY] Injecting {len(historical_context)} messages from history")
                        messages = _splice_context_after_system(messages, historical_context[-6:])

        # Process with tools (pre-check result passed to avoid double selector run)
        response = process_with_tools(messages, _pre_selection=_quick_result)

        # SAVE ASSISTANT RESPONSE TO DATABASE
        if response:
            # Defensive: process_with_tools should always return the standard
            # {"choices":[{"message":...}]} shape, but a malformed return must
            # NEVER 500 the request — that just makes Ohbot say "I'm having
            # trouble connecting". Salvage what we can and carry on.
            try:
                final_content = response["choices"][0]["message"].get("content", "")
            except (KeyError, IndexError, TypeError):
                log.error(f"[RESPONSE] Malformed response from process_with_tools: "
                          f"{str(response)[:200]}")
                final_content = (
                    (isinstance(response, dict) and response.get("response"))
                    or "Sorry, something went wrong on my end — could you say that again?"
                )
                response = {"choices": [{"message": {
                    "role": "assistant", "content": final_content,
                }}]}

            # Prepend proactive content: the once-a-day schedule briefing,
            # then any reminder alerts queued by the heartbeat thread. Done
            # literally rather than via system-prompt instruction so delivery
            # doesn't depend on LLM compliance — earlier turns showed Blue can
            # hallucinate having mentioned things he didn't. Both are built
            # from real reminder rows, never from the model's guesses.
            if PROACTIVE_QUEUE_AVAILABLE:
                _proactive_parts = []
                try:
                    _briefing = blue_proactive.daily_briefing_if_due()
                    if _briefing:
                        _proactive_parts.append(_briefing)
                except Exception as e:
                    log.warning(f"[PROACTIVE] daily briefing failed: {e}")
                _alerts = blue_proactive.drain_for_response()
                if _alerts:
                    _proactive_parts.append(_alerts)
                if _proactive_parts:
                    _prefix = " ".join(_proactive_parts)
                    final_content = f"{_prefix} {final_content}".strip()
                    response["choices"][0]["message"]["content"] = final_content
                    print(f"[PROACTIVE] Prepended {len(_prefix)} chars (briefing/alerts)")

            if final_content:
                print(f"[OUT] Sending response: {final_content[:100]}..." if len(final_content) > 100 else f"[OUT] Sending response: {final_content}")

                save_conversation_to_db(
                    user_name=user_name,
                    role="assistant",
                    content=final_content,
                    session_id=None
                )
                
                # AUTO-SAVE LEARNED FACTS & CONSOLIDATE (background thread to avoid blocking response)
                import threading
                def _background_fact_extraction(msgs, uname):
                    try:
                        if extract_and_save_facts(msgs):
                            log.info("[MEM] ✓ Auto-saved learned facts (background)")
                        if ENHANCED_MEMORY_AVAILABLE and memory_system:
                            memory_system.consolidate_if_needed(user_name=uname)
                            # Backfill one past-day recap per turn so Blue has
                            # cross-day continuity ("yesterday we discussed X").
                            memory_system.summarize_previous_sessions()
                            # Index existing day-recaps for semantic recall so
                            # an old conversation can resurface by relevance
                            # (one-shot, cheap no-op after the first call).
                            memory_system.backfill_session_memories()
                            # Recompute behavioural rhythms (rate-limited
                            # internally — a cheap no-op most turns).
                            memory_system.update_rhythms_if_due()
                    except Exception as e:
                        log.warning(f"[MEM] Background auto-save failed: {e}")

                # Pass the last few turns (not the whole transcript) so the
                # extractor can use Q-A context. Example: assistant asks
                # "what's your favorite food?", user says "pizza" — without
                # the prior assistant turn, "pizza" looks like noise. Four
                # turns is enough context, small enough to stay cheap.
                non_system = [m for m in messages if m.get("role") != "system"]
                latest_context = non_system[-4:] if non_system else []
                latest_context.append({"role": "assistant", "content": final_content})

                threading.Thread(
                    target=_background_fact_extraction,
                    args=(latest_context, user_name),
                    daemon=True
                ).start()

        return jsonify(response)
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"choices": [{"message": {"role": "assistant", "content": f"Error: {str(e)}"}}]}), 500


# ===== Memory Management Endpoints =====

@app.route('/memory/stats', methods=['GET'])


def memory_stats():
    """Get statistics about stored conversations"""
    if not CONVERSATION_DB_AVAILABLE or not db:
        return jsonify({"error": "Database not available"}), 503

    try:
        stats = db.get_database_stats()

        return jsonify({
            "status": "success",
            "total_conversations": stats.get('conversations', 0),
            "total_memories": stats.get('memories', 0),
            "db_size_mb": stats.get('db_size_mb', 0),
            "message": "Long-term memory is active"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/memory/recent', methods=['GET'])


def get_recent_memory():
    """Get recent conversation history"""
    if not CONVERSATION_DB_AVAILABLE or not db:
        return jsonify({"error": "Database not available"}), 503

    user_name = request.args.get('user', 'Alex')
    limit = int(request.args.get('limit', 20))

    try:
        conversations = db.get_recent_conversations(user_name=user_name, limit=limit)

        return jsonify({
            "status": "success",
            "user": user_name,
            "count": len(conversations),
            "conversations": [
                {
                    "role": c.get("role"),
                    "content": c.get("content")[:200],  # First 200 chars
                    "timestamp": c.get("timestamp"),
                    "importance": c.get("importance")
                }
                for c in conversations
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/memory/summary', methods=['GET'])
def memory_summary():
    """Get comprehensive memory summary with enhanced details."""
    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        try:
            summary = memory_system.get_memory_summary()
            return jsonify({
                "status": "success",
                "enhanced": True,
                "summary": summary,
                "message": "Using enhanced memory system"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        # Fallback to basic stats
        if not CONVERSATION_DB_AVAILABLE or not db:
            return jsonify({"error": "Database not available"}), 503
        
        try:
            stats = db.get_database_stats()
            facts = load_blue_facts()
            
            return jsonify({
                "status": "success",
                "enhanced": False,
                "summary": {
                    "facts_count": len(facts),
                    "conversations_stored": stats.get('conversations', 0),
                    "database_size_mb": stats.get('db_size_mb', 0)
                },
                "message": "Using legacy memory system"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])


def health():
    """Enhanced health check with comprehensive system status."""
    import time
    
    # Core services
    hue_status = "configured" if BRIDGE_IP and HUE_USERNAME else "not configured"
    index = load_document_index()
    doc_count = len(index.get('documents', []))
    music_status = "ready" if YOUTUBE_MUSIC_BROWSER else "not initialized"
    visualizer_status = "active" if _visualizer_active else "inactive"
    
    # LLM status
    llm_status = "unknown"
    llm_model = "unknown"
    if _LM:
        try:
            if _LM.is_healthy():
                llm_status = "healthy"
                llm_model = _LM.model
            else:
                llm_status = "unreachable"
        except Exception:
            llm_status = "error"
    
    # Gmail status
    gmail_status = "not configured"
    if GMAIL_AVAILABLE:
        try:
            service = get_gmail_service()
            if service:
                gmail_status = "configured"
        except Exception:
            gmail_status = "auth error"
    
    # Memory stats
    fact_count = len(BLUE_FACTS) if BLUE_FACTS else 0
    
    # Search stats
    search_remaining = SEARCH_MAX_PER_MINUTE - len(_SEARCH_TIMESTAMPS) if _SEARCH_TIMESTAMPS else SEARCH_MAX_PER_MINUTE
    cache_size = len(_SEARCH_CACHE)
    
    # Mood count
    mood_count = len(MOOD_PRESETS)

    return jsonify({
        "status": "healthy",
        "version": "v8-enhanced",
        "service": "Blue Robot Middleware",
        "uptime_note": "Flask app running",
        "components": {
            "llm": {
                "status": llm_status,
                "model": llm_model,
                "endpoint": _LM.base_url if _LM else None
            },
            "hue": {
                "status": hue_status,
                "bridge_ip": BRIDGE_IP if BRIDGE_IP else None,
                "mood_presets": mood_count
            },
            "gmail": {
                "status": gmail_status
            },
            "music": {
                "status": music_status,
                "visualizer": visualizer_status
            },
            "documents": {
                "count": doc_count,
                "folder": str(DOCUMENTS_FOLDER)
            },
            "memory": {
                "facts_stored": fact_count
            },
            "search": {
                "remaining_this_minute": search_remaining,
                "cache_entries": cache_size
            }
        }
    })


@app.route('/stats', methods=['GET'])
def session_stats():
    """v8: Get session statistics for debugging and optimization."""
    state = get_conversation_state()
    stats = state.get_session_stats()
    
    # Add additional stats
    stats['response_cache_size'] = len(_response_cache)
    stats['current_topic'] = state.get_current_topic()
    stats['last_tool'] = state.last_tool_used
    stats['common_tool_pairs'] = state.get_common_tool_pairs()
    stats['corrections_count'] = len(state.user_corrections)
    
    # Suggest next action if available
    suggestion = state.suggest_next_action()
    if suggestion:
        stats['suggestion'] = suggestion
    
    return jsonify(stats)


@app.route('/')


def index():
    """Home page with links."""
    index_data = load_document_index()
    doc_count = len(index_data.get('documents', []))
    music_status = "✅ Ready" if YOUTUBE_MUSIC_BROWSER else "⚠️ Not initialized"
    visualizer_status = "🎨 Active" if _visualizer_active else "⚪ Inactive"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Blue Middleware - Music + Light Sync [FIXED]</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                margin: 0;
                padding: 20px;
            }}
            .card {{
                background: white;
                border-radius: 20px;
                padding: 50px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                text-align: center;
                max-width: 600px;
            }}
            h1 {{
                color: #667eea;
                font-size: 2.5em;
                margin-bottom: 10px;
            }}
            .subtitle {{
                color: #666;
                font-size: 1.2em;
                margin-bottom: 40px;
            }}
            .status {{
                background: #f8f9fa;
                border-radius: 15px;
                padding: 30px;
                margin-bottom: 30px;
            }}
            .status-item {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 15px;
                padding: 15px;
                background: white;
                border-radius: 10px;
            }}
            .status-label {{
                font-weight: 600;
                color: #333;
            }}
            .status-value {{
                color: #667eea;
                font-weight: 600;
            }}
            .btn {{
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-decoration: none;
                padding: 20px 40px;
                border-radius: 50px;
                font-size: 1.2em;
                font-weight: 600;
                transition: transform 0.2s;
                margin: 10px;
            }}
            .btn:hover {{
                transform: scale(1.05);
            }}
            .feature-highlight {{
                background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                color: white;
                padding: 20px;
                border-radius: 15px;
                margin-bottom: 30px;
                font-weight: 600;
            }}
            .fix-badge {{
                background: #ff4757;
                color: white;
                padding: 10px 20px;
                border-radius: 25px;
                display: inline-block;
                margin-bottom: 20px;
                font-weight: 700;
                animation: pulse 2s infinite;
            }}
            @keyframes pulse {{
                0%, 100% {{ transform: scale(1); }}
                50% {{ transform: scale(1.05); }}
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="fix-badge">🔧 FIXED: Music Controls Now Work!</div>
            <h1>🎵💡 Blue Middleware</h1>
            <p class="subtitle">Your AI assistant with music-light sync!</p>

            <div class="feature-highlight">
                ✨ NEW: Music controls work from ANY window!<br>
                🎵 Uses system-wide media keys<br>
                💡 Lights automatically sync with music!<br>
                🎨 Dynamic light visualizer!
            </div>

            <div class="status">
                <div class="status-item">
                    <span class="status-label">Service</span>
                    <span class="status-value">✅ Running</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Music Controls</span>
                    <span class="status-value">✅ FIXED - Works from any window!</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Music</span>
                    <span class="status-value">{music_status}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Visualizer</span>
                    <span class="status-value">{visualizer_status}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Hue Lights</span>
                    <span class="status-value">{'✅ Connected' if BRIDGE_IP else '⚠️ Not configured'}</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Documents</span>
                    <span class="status-value">{doc_count} indexed</span>
                </div>
                <div class="status-item">
                    <span class="status-label">Moods Available</span>
                    <span class="status-value">{len(MOOD_PRESETS)}</span>
                </div>
            </div>

            <a href="/documents" class="btn">📚 Manage Documents</a>
        </div>
    </body>
    </html>
    """
    return html


# --- RAG API Endpoints ---
@app.route("/api/rag/reindex", methods=["POST"])
def api_rag_reindex():
    """Re-index all documents in the documents folder into ChromaDB."""
    try:
        from blue.tools.rag import index_all_documents
        results = index_all_documents(DOCUMENTS_FOLDER)
        return jsonify(results)
    except ImportError:
        return jsonify({"error": "ChromaDB not installed. Run: pip install chromadb"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rag/stats", methods=["GET"])
def api_rag_stats():
    """Get RAG index statistics."""
    try:
        from blue.tools.rag import get_stats
        return jsonify(get_stats())
    except ImportError:
        return jsonify({"available": False, "error": "ChromaDB not installed"})
    except Exception as e:
        return jsonify({"available": False, "error": str(e)})


if __name__ == "__main__":
    print("=" * 60)
    print("🎵💡 Blue Robot Middleware - WITH MUSIC-LIGHT SYNC!")
    print("🔧 FIXED: Music controls now work from ANY window!")
    print("=" * 60)
    print(f"[NET] Listening on: http://127.0.0.1:{PROXY_PORT}")
    print(f"[TARGET] Forwarding to LM Studio: {LM_STUDIO_URL}")
    print(f"[DOC] Document storage: {DOCUMENTS_FOLDER}")
    print(f"[TOOL] Tools: {len(TOOLS)}")
    print("   • play_music (YouTube Music & Amazon Music) 🎵")
    print("     → AUTOMATICALLY syncs lights to match music vibe! 💡")
    print("   • control_music (pause, skip, volume) 🎵")
    print("     → FIXED: Now uses system-wide media keys!")
    print("     → Works from ANY window - no need to focus YouTube Music!")
    print("   • music_visualizer (dynamic light shows!) 🎨")
    print("   • control_lights (with 15 moods!) 💡")
    print("   • search_documents (RAG-powered) 📄")
    print("   • get_weather ⛅")
    print("   • web_search 🔍")
    print("   • run_javascript 💻")
    print("   • create_document (save files) 📝")
    print("   • browse_website (fetch URLs) 🌐")
    print("   • read_gmail (check emails) 📧")
    print("   • send_gmail (send emails) 📧")
    print("=" * 60)

    # Try to initialize YouTube Music
    if init_youtube_music():
        print("\n🎵 YouTube Music Status: ✅ Ready!")
        print("   Note: Music controls use system media keys (no pyautogui needed)")
    else:
        print("\n🎵 YouTube Music Status: ⚠️ Not available")
        print("   To enable music: pip install ytmusicapi")

    if BRIDGE_IP and HUE_USERNAME:
        print(f"\n💡 Hue configured: Bridge at {BRIDGE_IP}")
        lights = get_hue_lights()
        if lights:
            print(f"✅ Found {len(lights)} light(s)")
    else:
        print("\n⚠️ Hue not configured. Run setup_hue.py!")

    # Document index housekeeping runs in the background so Flask can start
    # immediately. First-time PDF extraction + ChromaDB embedding can take
    # 30-90s and used to silently block server startup.
    index = load_document_index()
    doc_count = len(index.get('documents', []))
    print(f"\n📄 Document Manager:")
    print(f"   • {doc_count} document(s) indexed (rescan running in background)")
    print(f"   • Web interface: http://127.0.0.1:{PROXY_PORT}/documents")
    print(f"   • Storage: {DOCUMENTS_FOLDER}/")

    def _bg_index_housekeeping():
        try:
            cleanup_report = cleanup_document_index()
            rescan_report = rescan_documents_folder()
            new_count = len(load_document_index().get('documents', []))
            if (cleanup_report['dropped_camera'] or cleanup_report['dropped_missing']
                    or cleanup_report['dropped_duplicate'] or rescan_report['added']):
                print(
                    f"   [INDEX] housekeeping done: {new_count} indexed | "
                    f"+{rescan_report['added']} added, "
                    f"-{cleanup_report['dropped_camera']} camera, "
                    f"-{cleanup_report['dropped_missing']} missing, "
                    f"-{cleanup_report['dropped_duplicate']} dup",
                    flush=True,
                )
        except Exception as e:
            print(f"   [INDEX] background housekeeping failed: {e}", flush=True)

    import threading as _threading
    _threading.Thread(target=_bg_index_housekeeping, daemon=True, name="doc-index-rescan").start()

    # Start filesystem watcher so files dropped into DOCUMENTS_FOLDER while
    # the server runs are auto-indexed within ~1-2 seconds.
    start_document_watcher()

    # Start proactive heartbeat: scans the reminders DB every minute and
    # queues alerts for delivery on the next inbound turn from Ohbot.
    if PROACTIVE_QUEUE_AVAILABLE:
        blue_proactive.start()

    # Start the email auto-reply loop. Scans Blue's inbox for messages
    # addressed to him by name and answers them on his own, BCC'ing the
    # user on every reply. Disable with BLUE_EMAIL_AUTOREPLY_DISABLED=1.
    if globals().get("GMAIL_AVAILABLE", False) and os.environ.get("BLUE_EMAIL_AUTOREPLY_DISABLED") != "1":
        try:
            _start_email_autoreply_loop()
        except Exception as e:
            print(f"[AUTO-REPLY] could not start loop: {e}")

    # Check Gmail status
    if globals().get("GMAIL_AVAILABLE", False):

        print(f"\n📧 Gmail Integration:")
        print(f"   • Account: {GMAIL_USER_EMAIL}")
        if os.path.exists(GMAIL_TOKEN_FILE):
            print(f"   • Status: ✅ Authenticated")
        else:
            print(f"   • Status: ⚠️ Not authenticated yet")
            print(f"   • Run bluetools.py and use Gmail commands to authenticate")
    else:
        print(f"\n⚠️ Gmail not available. Install with:")
        print(f"   pip install google-auth google-auth-oauthlib google-api-python-client")

    print("\n✨ Example commands:")
    print("   🎵 'Play Bohemian Rhapsody by Queen' (lights auto-sync!)")
    print("   🎵 'Play some relaxing jazz music' (sets moonlight mood)")
    print("   🎵 'Play party music' (bright colorful lights!)")
    print("   🎵 'Pause the music' - NOW WORKS FROM OHBOT APP! ✅")
    print("   🎵 'Skip to next song' - Works from any window! ✅")
    print("   🎨 'Start a light show' / 'lights dance with music'")
    print("   💡 'Set the lights to sunset mood'")
    print("   📄 'What does my contract say about termination?'")
    print("   🔍 'Search for information about AI'")
    print("   📝 'Create a shopping list document for me'")
    print("   🌐 'Browse https://example.com and summarize it'")
    print("   📧 'Check my email' / 'Read my recent emails'")
    print("   📧 'Send an email to john@example.com about the meeting'")

    print("\n⭐ Music-Light Sync Features:")
    print("   • Auto mood detection: Jazz → moonlight, Party → colorful")
    print("   • Romantic music → soft romance lighting")
    print("   • Workout music → energizing bright whites")
    print("   • Dynamic visualizer with party/chill/pulse modes")
    print("   • Background thread for continuous light shows")

    print("\n🔧 FIX DETAILS:")
    print("   • Changed from application-specific shortcuts to system media keys")
    print("   • Uses pyautogui.press('playpause'), 'nexttrack', 'prevtrack'")
    print("   • These keys work globally regardless of window focus")
    print("   • No longer requires YouTube Music window to be active!")
    print("   • You can control music while using Ohbot app! ✅\n")

    # Start the Flask server. threaded=True so one slow/stuck request runs
    # on its own (daemon) thread instead of blocking the main thread — that
    # keeps the server responsive to other requests and, crucially, keeps
    # Ctrl+C working even if a request hangs.
    app.run(host='127.0.0.1', port=PROXY_PORT, debug=False, threaded=True)


# --- Image Upload Endpoints ---
@app.route("/upload", methods=["GET", "POST"])


def upload_page():
    # If POST, handle files directly and then redirect to /documents (if present) or return a simple page.
    if request.method == "POST":
        if "file" not in request.files and "files" not in request.files:
            return Response("No file part in the request.", status=400)
        files = request.files.getlist("file") or request.files.getlist("files")
        saved = []
        for f in files:
            if not f or f.filename == "":
                continue
            if not allowed_file(f.filename):
                continue
            target_path = ensure_unique_path(UPLOAD_FOLDER, f.filename)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            f.save(target_path)
            saved.append(os.path.basename(target_path))
        if not saved:
            return Response("No valid image files were uploaded.", status=400)
        # Prefer redirect to a document manager if available
        try:
            return redirect(url_for("documents"))
        except Exception:
            # Fallback simple success page
            body = "<h3>Uploaded:</h3><ul>" + "".join(f"<li>{x}</li>" for x in saved) + "</ul>"
            return Response(body, mimetype="text/html")

    # GET -> simple HTML upload form
    html = """
<!doctype html>
<title>Upload Images</title>
<h2>Upload images to Blue's uploads folder</h2>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" multiple accept="image/*">
  <button type="submit">Upload</button>
</form>
<p>Files will be saved under: <code>{folder}</code></p>
""".format(folder=UPLOAD_FOLDER)
    return Response(html, mimetype="text/html")


@app.route("/api/upload", methods=["POST"])


def api_upload():
    if "file" not in request.files and "files" not in request.files:
        return jsonify({"error": "No file(s) in request. Use 'file' or 'files' field."}), 400
    files = request.files.getlist("file") or request.files.getlist("files")
    saved = []
    rejected = []
    for f in files:
        if not f or f.filename == "":
            rejected.append({"filename": "", "reason": "empty filename"})
            continue
        if not allowed_file(f.filename):
            rejected.append({"filename": f.filename, "reason": "unsupported extension"})
            continue
        target_path = ensure_unique_path(UPLOAD_FOLDER, f.filename)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        f.save(target_path)
        saved.append({"filename": os.path.basename(target_path), "path": target_path})
    return jsonify({"saved": saved, "rejected": rejected, "upload_folder": UPLOAD_FOLDER})


# --- Document Upload Endpoints (images + texts, saved into uploaded_documents) ---
@app.route("/documents/upload", methods=["GET", "POST"])


def documents_upload():
    if request.method == "POST":
        if "file" not in request.files and "files" not in request.files:
            return Response("No file part in the request.", status=400)
        files = request.files.getlist("file") or request.files.getlist("files")
        saved, duplicates = [], []
        for f in files:
            if not f or f.filename == "":
                continue
            if not allowed_file(f.filename):
                continue
            # Route by file type: text/docs to documents/, images to uploads/
            ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
            if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx', 'json', 'xml'):
                target_folder = str(DOCUMENTS_FOLDER)
            else:
                target_folder = str(UPLOAD_FOLDER)
            path = ensure_unique_path(target_folder, f.filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            f.save(path)
            result = register_uploaded_file(path, os.path.basename(path))
            if result.get('duplicate'):
                duplicates.append(result.get('existing_filename') or f.filename)
            else:
                saved.append(os.path.basename(path))
        if not saved and not duplicates:
            return Response("No valid files were uploaded.", status=400)
        try:
            return redirect(url_for("documents"))
        except Exception:
            body = "<h3>Uploaded:</h3><ul>" + "".join(f"<li>{x}</li>" for x in saved) + "</ul>"
            if duplicates:
                body += "<h3>Skipped (duplicates):</h3><ul>" + "".join(f"<li>{x}</li>" for x in duplicates) + "</ul>"
            return Response(body, mimetype="text/html")

    # GET -> HTML form
    html = f"""
<!doctype html>
<title>Upload Documents</title>
<h2>Upload documents/images</h2>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file" multiple>
  <button type="submit">Upload</button>
</form>
<p>Documents saved under: <code>{DOCUMENTS_FOLDER}</code></p>
<p>Images saved under: <code>{UPLOAD_FOLDER}</code></p>
<p>Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}</p>
"""
    return Response(html, mimetype="text/html")


@app.route("/api/documents/upload", methods=["POST"])


def api_documents_upload():
    if "file" not in request.files and "files" not in request.files:
        return jsonify({"error": "No file(s) in request. Use 'file' or 'files' field."}), 400
    files = request.files.getlist("file") or request.files.getlist("files")
    saved, rejected, duplicates = [], [], []
    for f in files:
        if not f or f.filename == "":
            rejected.append({"filename": "", "reason": "empty filename"})
            continue
        if not allowed_file(f.filename):
            rejected.append({"filename": f.filename, "reason": "unsupported extension"})
            continue
        # Route by file type
        ext = f.filename.rsplit('.', 1)[1].lower() if '.' in f.filename else ''
        if ext in ('pdf', 'doc', 'docx', 'txt', 'md', 'csv', 'rtf', 'html', 'pptx', 'xlsx', 'json', 'xml'):
            target_folder = str(DOCUMENTS_FOLDER)
        else:
            target_folder = str(UPLOAD_FOLDER)
        path = ensure_unique_path(target_folder, f.filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f.save(path)
        result = register_uploaded_file(path, os.path.basename(path))
        if result.get('duplicate'):
            duplicates.append({"filename": f.filename, "existing": result.get('existing_filename')})
        else:
            saved.append({
                "filename": os.path.basename(path),
                "path": path,
                "indexed_in_rag": result.get('indexed_in_rag', False),
            })
    return jsonify({
        "saved": saved,
        "rejected": rejected,
        "duplicates": duplicates,
        "documents_folder": DOCUMENTS_FOLDER,
    })


@app.route("/documents/file/<path:filename>")
def serve_document_file(filename):
    # Check all folders for the file
    for folder in [DOCUMENTS_FOLDER, str(UPLOAD_FOLDER), CAMERA_FOLDER]:
        candidate = os.path.join(folder, filename)
        if os.path.exists(candidate):
            return send_from_directory(folder, filename, as_attachment=False)
    return "File not found", 404


# ===== Facebook OAuth Callback =====
@app.route("/facebook/callback")
def facebook_callback():
    """Handle Facebook OAuth callback"""
    code = request.args.get('code')
    error = request.args.get('error')

    if error:
        return f"""
        <html>
        <head><title>Facebook Authentication Failed</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px;">
            <h1 style="color: #e74c3c;">Authentication Failed</h1>
            <p>Error: {error}</p>
            <p>Description: {request.args.get('error_description', 'Unknown error')}</p>
            <p><a href="/">Return to Home</a></p>
        </body>
        </html>
        """

    if not code:
        return """
        <html>
        <head><title>Facebook Authentication</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px;">
            <h1 style="color: #f39c12;">Missing Authorization Code</h1>
            <p>No authorization code received from Facebook.</p>
            <p><a href="/">Return to Home</a></p>
        </body>
        </html>
        """

    try:
        from blue.tools import get_facebook_integration
        integration = get_facebook_integration()
        result = integration.complete_authentication(code)

        if result.get('status') == 'success':
            user_info = result.get('user', {})
            pages = result.get('pages', [])

            pages_html = ""
            if pages:
                pages_html = "<h3>Connected Pages:</h3><ul>"
                for page in pages:
                    pages_html += f"<li>{page.get('name')} (ID: {page.get('id')})</li>"
                pages_html += "</ul>"

            return f"""
            <html>
            <head><title>Facebook Connected</title></head>
            <body style="font-family: Arial, sans-serif; padding: 40px;">
                <h1 style="color: #27ae60;">✓ Successfully Connected to Facebook</h1>
                <p>Authenticated as: <strong>{user_info.get('name')}</strong></p>
                <p>Email: {user_info.get('email')}</p>
                {pages_html}
                <p style="margin-top: 20px;">You can now use Blue to post to Facebook!</p>
                <p><a href="/">Return to Home</a></p>
            </body>
            </html>
            """
        else:
            error_msg = result.get('error', 'Unknown error')
            return f"""
            <html>
            <head><title>Authentication Error</title></head>
            <body style="font-family: Arial, sans-serif; padding: 40px;">
                <h1 style="color: #e74c3c;">Authentication Error</h1>
                <p>Error: {error_msg}</p>
                <p><a href="/">Return to Home</a></p>
            </body>
            </html>
            """

    except Exception as e:
        return f"""
        <html>
        <head><title>Error</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px;">
            <h1 style="color: #e74c3c;">Unexpected Error</h1>
            <p>Error: {str(e)}</p>
            <p><a href="/">Return to Home</a></p>
        </body>
        </html>
        """


# Don't auto-run when imported - let run.py handle startup
# app.run(host='127.0.0.1', port=PROXY_PORT, debug=False)

# ===== Tool Executor with timeouts, retries, and small cache =====
class ToolExecutor:
    def __init__(self, settings: Settings):
        self.settings = settings

    @lru_cache(maxsize=128)
    def _cached_call(self, tool_name: str, args_key: str) -> str:
        args = json.loads(args_key)
        return self._raw_call(tool_name, args)

    def _raw_call(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        try:
            return execute_tool(tool_name, tool_args)
        except Exception as e:
            log.exception("Tool '%s' crashed: %s", tool_name, e)
            return json.dumps({"error": str(e), "tool": tool_name})

    def execute(self, tool_name: str, tool_args: Dict[str, Any], use_cache: bool = False) -> str:
        tries = max(1, int(self.settings.TOOL_RETRIES) + 1)
        last_err = None
        for attempt in range(1, tries + 1):
            try:
                if use_cache:
                    args_key = json.dumps(tool_args, sort_keys=True)[:2048]
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(self._cached_call, tool_name, args_key)
                        return fut.result(timeout=self.settings.TOOL_TIMEOUT_SECS)
                else:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        fut = pool.submit(self._raw_call, tool_name, tool_args)
                        return fut.result(timeout=self.settings.TOOL_TIMEOUT_SECS)
            except concurrent.futures.TimeoutError:
                last_err = f"timeout after {self.settings.TOOL_TIMEOUT_SECS}s"
                log.warning("Tool '%s' timed out (attempt %d/%d)", tool_name, attempt, tries)
            except Exception as e:
                last_err = str(e)
                log.warning("Tool '%s' failed (attempt %d/%d): %s", tool_name, attempt, tries, e)
            time.sleep(0.2 * attempt)
        return json.dumps({"error": last_err or "unknown", "tool": tool_name, "attempts": tries})

# ===== Ephemeral Session State =====
SESSION_STATE: Dict[str, Any] = {}


def session_get(key: str, default=None):
    return SESSION_STATE.get(key, default)


def session_set(key: str, value: Any) -> None:
    SESSION_STATE[key] = value

def clear_gmail_context():
    """
    Clear email-related session state to prevent confusion between operations.
    Call this after completing email operations to ensure old results don't interfere.
    ADDED: October 2024 - Fix for Blue confusing READ with REPLY operations
    """
    SESSION_STATE.pop('last_gmail_operation', None)
    SESSION_STATE.pop('last_gmail_result', None)
    SESSION_STATE.pop('last_gmail_query', None)
    log.info("Cleared Gmail session context to prevent operation confusion")


# ================== BEGIN: Browse Website Tool + PRIORITY-EXPLICIT (with browse) ==================
"""
Adds a safe 'browse_website' tool and updates the middleware to understand and prioritize it.
- Explicit commands ALWAYS win.
- Smart auto-use (optional) may trigger for obvious "open/read this URL" cases.
- Web search cannot override an explicit browse request.
- Safe fetch: http/https only; timeouts; size limits; basic HTML->text extraction; link harvesting.

USAGE examples:
  use browse_website: {"url":"https://example.com"}
  /browse_website https://example.com
  use browse: https://example.com
"""

from typing import List, Dict, Optional, Tuple, Any
import re as _re, json as _json, html as _html, urllib.parse as _urlparse
import requests

# ---- Ensure TOOLS contains browse_website schema ----
try:
    TOOLS
except NameError:
    TOOLS = []

def _has_tool_named(name: str) -> bool:
    try:
        for t in TOOLS:
            fn = t.get("function",{})
            if fn.get("name") == name:
                return True
    except Exception:
        pass
    return False

_BROWSE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "browse_website",
        "description": "Fetch a web page over HTTPS and return cleaned text, title, and links. For direct browsing of a specific URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type":"string", "description":"The absolute URL to fetch (http or https)."},
                "extract": {"type":"string", "enum":["text","html"], "description":"Return cleaned text or raw HTML (default text)."},
                "max_chars": {"type":"integer", "description":"Max length of text to return (default 8000)."},
                "include_links": {"type":"boolean", "description":"Include a compact list of outgoing links (default true)."},
                "headers": {"type":"object", "description":"Optional request headers to include."}
            },
            "required": ["url"]
        }
    }
}

if not _has_tool_named("browse_website"):
    try:
        TOOLS.append(_BROWSE_SCHEMA)
        print("[TOD] Registered tool: browse_website", flush=True)
    except Exception as e:
        print(f"[TOD] Could not register browse_website: {e}", flush=True)

# ---- DUPLICATE CODE REMOVED ----
# The browse_website implementation has been moved to before execute_tool (around line 1600)
# to fix the NameError: name '_execute_browse_website' is not defined
# Keeping only the TOOLS registration above and the alias/scoring below.

# ---- Hook into execute_tool without breaking existing tools ----
# REMOVED: Duplicate execute_tool override - browse_website is now handled in main execute_tool

# ---- Extend existing middleware alias+scoring with browse ----
try:
    KNOWN_TOOL_ALIASES
except NameError:
    KNOWN_TOOL_ALIASES = {}
KNOWN_TOOL_ALIASES.setdefault("browse_website", [])
for alias in ["browse","open_url","open website","visit","go to","navigate","read url"]:
    if alias not in KNOWN_TOOL_ALIASES["browse_website"]:
        KNOWN_TOOL_ALIASES["browse_website"].append(alias)

_URL_IN_TEXT = _re.compile(r'https?://\S+', _re.I)


def _score_browse(text: str) -> float:
    t = (text or "").strip().lower()
    if _URL_IN_TEXT.search(t): return 0.98
    cues = ["open ", "go to ", "navigate to ", "read this page", "summarize this page", "visit "]
    if any(c in t for c in cues): return 0.85
    return 0.0

try:
    _SCORERS
    _SCORERS["browse_website"] = _score_browse
except NameError:
    _SCORERS = {"browse_website": _score_browse}

# ---- Add Gmail tool aliases ----
KNOWN_TOOL_ALIASES.setdefault("read_gmail", [])
for alias in ["check email", "read email", "show email", "get email", "inbox", "my emails", "check messages", "read messages"]:
    if alias not in KNOWN_TOOL_ALIASES["read_gmail"]:
        KNOWN_TOOL_ALIASES["read_gmail"].append(alias)

KNOWN_TOOL_ALIASES.setdefault("send_gmail", [])
for alias in ["send email", "email to", "compose email", "write email", "send message", "email"]:
    if alias not in KNOWN_TOOL_ALIASES["send_gmail"]:
        KNOWN_TOOL_ALIASES["send_gmail"].append(alias)

def _score_read_gmail(text: str) -> float:
    t = (text or "").strip().lower()
    gmail_read_terms = ["check email", "read email", "show email", "my inbox", "unread", "new messages", "email from"]
    if any(term in t for term in gmail_read_terms): return 0.95
    if "email" in t and any(word in t for word in ["check", "read", "show", "get", "see"]): return 0.85
    return 0.0

def _score_send_gmail(text: str) -> float:
    t = (text or "").strip().lower()
    if "send email" in t or "email to" in t: return 0.95
    if "send" in t and "email" in t: return 0.85
    if "compose" in t and "email" in t: return 0.85
    return 0.0

_SCORERS["read_gmail"] = _score_read_gmail
_SCORERS["send_gmail"] = _score_send_gmail

print("[TOD] Browse tool ready", flush=True)
print("[TOD] Gmail tools ready", flush=True)

# Start the email auto-reply loop at MODULE-LOAD time. The same call
# also exists inside `if __name__ == "__main__":` further up, but the
# external launcher imports bluetools rather than running it directly,
# so that block is skipped. _start_email_autoreply_loop() is idempotent
# (guards on _EMAIL_AUTOREPLY_THREAD), so the duplicate call when
# bluetools IS run directly is a no-op.
try:
    if GMAIL_AVAILABLE and os.environ.get("BLUE_EMAIL_AUTOREPLY_DISABLED") != "1":
        _start_email_autoreply_loop()
except Exception as _autoreply_err:
    print(f"[AUTO-REPLY] could not start loop: {_autoreply_err}", flush=True)
# ================== END: Browse Website Tool + PRIORITY-EXPLICIT (with browse) ==================


# ================================================================================
#                           BLUETOOLS GMAIL UPGRADES                          #
#                    (Appended October 2025 — safe block)                    #
# ================================================================================

# Per-tool context limits to prevent cross-tool bleed in email operations
try:
    PER_TOOL_CONTEXT_LIMITS  # type: ignore
except NameError:
    PER_TOOL_CONTEXT_LIMITS = {
        "read_gmail": 6,
        "send_gmail": 6,
        "reply_gmail": 6,
    }

def get_context_limit_for(tool_name: str, default_limit: int = 20) -> int:
    try:
        return int(PER_TOOL_CONTEXT_LIMITS.get(tool_name, default_limit))
    except Exception:
        return default_limit

# NOTE: detect_gmail_operation_intent, extract_email_address, extract_email_subject_and_body
# are defined earlier in the file (around line 7116) to ensure they're available when needed.

# Operation receipt


def _record_gmail_operation(op_type: str, query: str = "", extra: dict | None = None):
    import time as _t, json as _json
    meta = {"tool": op_type, "query": query or "", "ts": _t.time()}
    if extra and isinstance(extra, dict):
        meta.update(extra)
    try:
        print("[GMAIL-META] " + _json.dumps(meta))
    except Exception:
        pass
    return meta

# NOTE: To wire these into your existing flow:
#  - Before invoking the model/tool for Gmail, call detect_gmail_operation_intent(last_user_text)
#    and route strictly to 'read_gmail' / 'send_gmail' / 'reply_gmail' if returned.
#  - When building the context for that tool call, cap messages using get_context_limit_for(tool, default_limit).
#  - In your Gmail tool implementations, call _record_gmail_operation(...) after success.
#  - Use extract_email_subject_and_body() in your send path to infer subject/body from natural phrasing.
# ================================================================================


# ================================================================================
#                    VOICE EMAIL INTERFACE (CONSOLIDATED)                     #
#             AddressBook + NLU + Controller + Lazy Wiring Helpers            #
#                    Appended: 1761490066                                        #
# ================================================================================
import re, os, json, difflib, time, typing, dataclasses
from dataclasses import dataclass

@dataclass
class _Contact:
    name: str
    email: str
    aliases: list[str] | None = None
    def all_names(self) -> list[str]:
        names = [self.name]
        if self.aliases: names.extend(self.aliases)
        return [_normalize_text(n) for n in names if n]

def _normalize_text(s: str) -> str:
    s = s or ""
    s = s.strip().lower()
    s = _re.sub(r"[^a-z0-9@.\s+-]", "", s)
    s = _re.sub(r"\s+", " ", s)
    return s

class AddressBook:
    def __init__(self, path: str):
        self.path = path
        self.contacts: list[_Contact] = []
        if os.path.exists(path): self._load()
        else: self._save()
    def add_or_update(self, name: str, email: str, aliases: list[str] | None = None) -> _Contact:
        name_n = _normalize_text(name)
        for c in self.contacts:
            if _normalize_text(c.name) == name_n or _normalize_text(c.email) == _normalize_text(email):
                c.name = name; c.email = email; c.aliases = aliases or c.aliases; self._save(); return c
        c = _Contact(name=name, email=email, aliases=aliases or [])
        self.contacts.append(c); self._save(); return c
    def remove(self, name_or_email: str) -> bool:
        key = _normalize_text(name_or_email); before = len(self.contacts)
        self.contacts = [c for c in self.contacts if _normalize_text(c.name)!=key and _normalize_text(c.email)!=key]
        if len(self.contacts)!=before: self._save(); return True
        return False
    def find_best(self, query: str) -> tuple[_Contact | None, float, list[_Contact]]:
        q = _normalize_text(query)
        if not q: return None, 0.0, []
        for c in self.contacts:
            if _normalize_text(c.email) == q: return c, 1.0, [c]
        candidates: list[tuple[_Contact,float]] = []
        for c in self.contacts:
            for nm in c.all_names():
                score = _difflib.SequenceMatcher(a=q, b=nm).ratio()
                candidates.append((c, score))
        candidates.sort(key=lambda x: x[1], reverse=True)
        if not candidates: return None, 0.0, []
        best, score = candidates[0]
        top = [c for c,_ in candidates[:3]]
        return best, score, top
    def as_dict(self) -> dict:
        return {"contacts":[_dataclasses.asdict(c) for c in self.contacts], "last_updated": int(_time.time())}
    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f: data = _json.load(f)
        self.contacts = [_Contact(**c) for c in data.get("contacts", [])]
    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f: _json.dump(self.as_dict(), f, indent=2)

@dataclass
class ParseResult:
    intent: str | None
    contact_query: str | None = None
    subject: str | None = None
    body: str | None = None
    constraints: dict | None = None

class VoiceEmailNLU:
    def __init__(self, address_book: AddressBook | None = None):
        self.address_book = address_book
        self._pat_reply_from = _re.compile(r"(answer|reply)\s+(?:to\s+)?(?:emails?\s+)?(?:from\s+)?(?P<name>.+)$", _re.I)
        self._pat_reply_to   = _re.compile(r"(reply|respond)\s+(?:to\s+)(?P<name>.+)$", _re.I)
        self._pat_read_from  = _re.compile(r"(show|read|list|check)\s+(?:my\s+)?emails?\s+(?:from\s+)(?P<name>.+)$", _re.I)
        self._pat_send_to    = _re.compile(r"(send|email|compose)\s+(?:an?\s+email\s+)?(?:to\s+)?(?P<name>[^,]+?)(?:\s+about\s+(?P<subject>[^,]+?))?(?:\s+(?:that\s+says|saying)\s+(?P<body>.+))?$", _re.I)
    def parse(self, text: str) -> ParseResult:
        t = (text or "").strip()
        m = self._pat_reply_from.search(t) or self._pat_reply_to.search(t)
        if m: return ParseResult(intent="reply_contact", contact_query=m.group("name").strip())
        m = self._pat_read_from.search(t)
        if m: return ParseResult(intent="read_contact", contact_query=m.group("name").strip())
        m = self._pat_send_to.search(t)
        if m: return ParseResult(intent="send_contact", contact_query=(m.group("name") or "").strip(), subject=(m.group("subject") or "").strip() or None, body=(m.group("body") or "").strip() or None)
        if "email" in t.lower() or "inbox" in t.lower(): return ParseResult(intent="read_generic")
        return ParseResult(intent=None)

class VoiceEmailController:
    def __init__(self, execute_tool_fn, address_book: AddressBook, nlu: VoiceEmailNLU, confidence_threshold: float = 0.72):
        self.execute_tool = execute_tool_fn
        self.address_book = address_book
        self.nlu = nlu
        self.confidence_threshold = confidence_threshold
    def handle_voice_command(self, utterance: str, dry_run: bool = True) -> dict:
        parse = self.nlu.parse(utterance)
        if parse.intent in ("reply_contact","read_contact","send_contact"):
            contact, conf, top = self.address_book.find_best(parse.contact_query or "")
            if not contact or conf < self.confidence_threshold:
                suggestion = ", ".join([c.name for c in top]) or "no matches"
                return {"success": False, "needs_disambiguation": True, "spoken_confirmation": f"I found multiple or low-confidence matches for '{parse.contact_query}'. Did you mean {suggestion}?", "candidates": [_dataclasses.asdict(c) for c in top], "confidence": conf}
        if parse.intent == "reply_contact": return self._reply_latest_from(contact, dry_run=dry_run)
        if parse.intent == "read_contact":  return self._read_from(contact, dry_run=dry_run)
        if parse.intent == "send_contact":  return self._send_to(contact, subject=parse.subject, body=parse.body, dry_run=dry_run)
        if parse.intent == "read_generic":  return self._read_generic(dry_run=dry_run)
        return {"success": False, "spoken_confirmation": "I didn't catch that. Try 'reply to Sam', 'show emails from Jordan', or 'email Pat about timelines saying move ahead'."}
    def _read_generic(self, dry_run: bool) -> dict:
        args = {"query": "in:inbox newer_than:7d"}
        if dry_run: return {"success": True, "plan": {"tool": "read_gmail", "args": args}, "spoken_confirmation": "I'll read your recent inbox."}
        out = self.execute_tool("read_gmail", args); return self._norm(out, "I'll read your recent inbox.")
    def _read_from(self, contact: _Contact, dry_run: bool) -> dict:
        args = {"query": f'in:inbox from:{contact.email}'}
        if dry_run: return {"success": True, "plan": {"tool": "read_gmail", "args": args}, "spoken_confirmation": f"I'll read your recent emails from {contact.name}."}
        out = self.execute_tool("read_gmail", args); return self._norm(out, f"I'll read your emails from {contact.name}.")
    def _reply_latest_from(self, contact: _Contact, dry_run: bool) -> dict:
        args = {"query": f'in:inbox from:{contact.email}', "mode": "latest_only"}
        if dry_run: return {"success": True, "plan": {"tool": "reply_gmail", "args": args}, "spoken_confirmation": f"I'll reply to the latest email from {contact.name}."}
        out = self.execute_tool("reply_gmail", args); return self._norm(out, f"I replied to the latest email from {contact.name}.")
    def _send_to(self, contact: _Contact, subject: str | None, body: str | None, dry_run: bool) -> dict:
        text = f"send email to {contact.email}"
        if subject: text += f" about {subject}"
        if body: text += f" saying {body}"
        args = {"to": contact.email, "subject": subject, "body": body, "text": text}
        if dry_run: return {"success": True, "plan": {"tool": "send_gmail", "args": args}, "spoken_confirmation": f"I'll send {contact.name} an email" + (f" about {subject}" if subject else "") + (" with your message." if body else ".")}
        out = self.execute_tool("send_gmail", args); return self._norm(out, f"I sent an email to {contact.name}.")
    def _norm(self, out, confirmation: str) -> dict:
        if isinstance(out, str):
            try: obj = _json.loads(out)
            except Exception: obj = {"raw": out}
        else: obj = out or {}
        obj.setdefault("success", True); obj.setdefault("spoken_confirmation", confirmation); return obj

_VOICE_ADDRBOOK_PATH = os.environ.get("BLUE_ADDRESS_BOOK", "/mnt/data/blue_address_book.json")
__voice_singletons = {"ab": None, "nlu": None, "controller": None}

def get_voice_email_controller(execute_tool_fn):
    ab = __voice_singletons.get("ab")
    if ab is None:
        if not os.path.exists(_VOICE_ADDRBOOK_PATH):
            seed = {"contacts":[
                {"name":"Sam Carter","email":"sam.carter@example.com","aliases":["Sam","Samuel Carter"]},
                {"name":"Jordan Lee","email":"jordan.lee@example.com","aliases":["Jordy","J Lee"]},
                {"name":"Pat Morgan","email":"pat.morgan@example.com","aliases":["Patrick Morgan","Patricia Morgan","Pat"]}
            ], "last_updated": int(_time.time())}
            with open(_VOICE_ADDRBOOK_PATH, "w", encoding="utf-8") as f: _json.dump(seed, f, indent=2)
        ab = AddressBook(_VOICE_ADDRBOOK_PATH); __voice_singletons["ab"] = ab
    nlu = __voice_singletons.get("nlu") or VoiceEmailNLU(address_book=ab); __voice_singletons["nlu"] = nlu
    ctl = __voice_singletons.get("controller") or VoiceEmailController(execute_tool_fn=execute_tool_fn, address_book=ab, nlu=nlu); __voice_singletons["controller"] = ctl
    return ctl

def voice_email_handle_command(utterance: str, *, execute_tool_fn, dry_run: bool = True) -> dict:
    ctl = get_voice_email_controller(execute_tool_fn)
    return ctl.handle_voice_command(utterance, dry_run=dry_run)

# End Voice Email Interface
###############################################################################

def polish_response_for_conversation(response: str, conversation_messages: List[Dict]) -> str:
    """Post-process LLM responses to sound more conversational and less repetitive.

    - Cleans artifacts and extra whitespace
    - Removes obviously duplicated sentences
    - Softens robotic disclaimers ("As an AI...")
    - Shortens responses that are near-duplicates of recent replies
    - Optionally adds a light conversational opener when things sound stiff
    """
    if not response:
        return ""

    # Base cleaning first
    cleaned = clean_response_text(response)

    import re as _re
    import random as _random

    # Strip common robotic disclaimers
    disclaimers = [
        "as an ai language model",
        "as a language model",
        "as an ai",
        "i am an ai assistant",
        "i'm an ai assistant",
    ]
    lowered = cleaned.lower()
    for d in disclaimers:
        if d in lowered:
            # Remove the sentence containing the disclaimer
            parts = _re.split(r'(?<=[.!?])\s+', cleaned)
            parts = [p for p in parts if d not in p.lower()]
            cleaned = " ".join(parts).strip()
            lowered = cleaned.lower()
            break

    # Remove exact duplicate sentences
    sentences = _re.split(r'(?<=[.!?])\s+', cleaned)
    seen = set()
    unique_sentences = []
    for s in sentences:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_sentences.append(s)

    shortened = " ".join(unique_sentences).strip()

    # If this still looks very similar to recent messages, trim it further
    try:
        history_check = check_response_against_history(shortened, conversation_messages)
        if history_check.get("is_duplicate"):
            # Keep only the first couple of sentences to avoid droning on
            parts = _re.split(r'(?<=[.!?])\s+', shortened)
            shortened = " ".join(parts[:2]).strip()
    except Exception:
        # On any failure, just fall back to the shortened text
        pass

    # Add a light conversational opener if it starts very stiffly
    boring_starts = (
        "i can ", "i will ", "i am ", "i'm ", "as an ", "here is ", "here's ", "this is "
    )
    stripped = shortened.lstrip()
    lower_prefix = stripped[:10].lower()
    if any(lower_prefix.startswith(b) for b in boring_starts):
        openers = ["Alright —", "Got it —", "Sure —", "Okay —"]
        opener = _random.choice(openers)
        if stripped:
            stripped = stripped[0].lower() + stripped[1:]
        shortened = f"{opener} {stripped}"

    return shortened.strip()


# === Conversational wrapper for call_llm (auto-added) ===
_raw_call_llm = call_llm

def call_llm(
    messages: List[Dict[str, Any]],
    include_tools: bool = True,
    tool_choice: str = "auto",
    force_tool: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
    **kwargs: Any
) -> Dict[str, Any]:
    """Wrapper around original call_llm that polishes responses for conversation."""
    result = _raw_call_llm(
        messages,
        include_tools=include_tools,
        tool_choice=tool_choice,
        force_tool=force_tool,
        max_tokens=max_tokens,
        temperature=temperature,
        extra=extra,
        **kwargs
    )

    try:
        if isinstance(result, dict) and "choices" in result and messages:
            choice = result["choices"][0]
            msg = choice.get("message") or choice.get("delta") or {}
            content = msg.get("content")
            if content:
                polished = polish_response_for_conversation(content, messages)
                if "message" in choice:
                    choice["message"]["content"] = polished
                elif "delta" in choice:
                    choice["delta"]["content"] = polished
    except Exception:
        # If polishing fails for any reason, just fall back to the original result
        pass

    return result




# === Enhanced conversational de-duplication ===
def polish_response_for_conversation(response: str, conversation_messages: List[Dict]) -> str:
    """Post-process LLM responses to sound more conversational and less repetitive.

    - Cleans artifacts and extra whitespace
    - Removes obviously duplicated sentences
    - Softens robotic disclaimers ("As an AI...")
    - Avoids reusing recent filler phrases across turns
    - Shortens responses that are near-duplicates of recent replies
    - Optionally adds a light conversational opener when things sound stiff
    """
    if not response:
        return ""

    cleaned = clean_response_text(response)

    import re as _re
    import random as _random

    disclaimers = [
        "as an ai language model",
        "as a language model",
        "as an ai",
        "i am an ai assistant",
        "i'm an ai assistant",
    ]
    lowered = cleaned.lower()
    for d in disclaimers:
        if d in lowered:
            parts = _re.split(r'(?<=[.!?])\s+', cleaned)
            parts = [p for p in parts if d not in p.lower()]
            cleaned = " ".join(parts).strip()
            lowered = cleaned.lower()
            break

    # Remove exact duplicate sentences within this response
    sentences = _re.split(r'(?<=[.!?])\s+', cleaned)
    seen = set()
    unique_sentences = []
    for s in sentences:
        key = s.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_sentences.append(s)
    shortened = " ".join(unique_sentences).strip()

    previous_phrases = []
    conv_state = None
    try:
        conv_state = get_conversation_state()
        if hasattr(conv_state, "recent_phrases"):
            previous_phrases = [p.strip().lower() for p in conv_state.recent_phrases]
    except Exception:
        conv_state = None

    if previous_phrases:
        sentences2 = _re.split(r'(?<=[.!?])\s+', shortened)
        sentences_no_repeat = []
        for s in sentences2:
            key = s.strip().lower()
            if not key:
                continue
            if key in previous_phrases:
                continue
            sentences_no_repeat.append(s)
        if sentences_no_repeat:
            shortened = " ".join(sentences_no_repeat).strip()

    try:
        history_check = check_response_against_history(shortened, conversation_messages)
        if history_check.get("is_duplicate"):
            parts = _re.split(r'(?<=[.!?])\s+', shortened)
            shortened = " ".join(parts[:2]).strip()
    except Exception:
        pass

    boring_starts = (
        "i can ", "i will ", "i am ", "i'm ", "as an ", "here is ", "here's ", "this is "
    )
    stripped = shortened.lstrip()
    lower_prefix = stripped[:10].lower()
    if any(lower_prefix.startswith(b) for b in boring_starts):
        openers = ["Alright —", "Got it —", "Sure —", "Okay —"]
        opener = _random.choice(openers)
        if stripped:
            stripped = stripped[0].lower() + stripped[1:]
        shortened = f"{opener} {stripped}"

    final_text = shortened.strip()

    try:
        if conv_state is not None and hasattr(conv_state, "recent_phrases"):
            new_phrases = [
                s.strip() for s in _re.split(r'(?<=[.!?])\s+', final_text) if s.strip()
            ]
            conv_state.recent_phrases.extend(new_phrases)
            if len(conv_state.recent_phrases) > 30:
                conv_state.recent_phrases = conv_state.recent_phrases[-30:]
    except Exception:
        pass

    return final_text
