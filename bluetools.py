"""
Blue AI Robot System — ENHANCED VERSION v8
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
from flask import Flask, Response, jsonify, redirect, render_template_string, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Visual Memory System (if available)
try:
    from blue_visual_memory import get_visual_memory, VisualMemory, VISUAL_REF_DIR
    VISUAL_MEMORY_AVAILABLE = True
    print("[OK] Visual memory system loaded - Blue can now recognize people and places!")
except ImportError:
    VISUAL_MEMORY_AVAILABLE = False
    print("[WARN] Visual memory system not available")

# Face Recognition Engine (OpenCV SFace; degrades gracefully if unavailable)
try:
    from blue.tools import face_engine as FACE_ENGINE
    FACE_RECOGNITION_AVAILABLE = True
    print("[OK] Face engine module loaded - Blue can recognize faces by embedding!")
except Exception as _e:
    FACE_ENGINE = None
    FACE_RECOGNITION_AVAILABLE = False
    print(f"[WARN] Face engine not available: {_e}")

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
        # View-control phrasings: aim the head / zoom before the shot
        'zoom in', 'zoom into', 'look closer', 'closer look',
        "what's on your left", "what's on your right",
        "what's to your left", "what's to your right",
        'what is on your left', 'what is on your right',
        'what is to your left', 'what is to your right',
        'look up and', 'look down and', 'look left and', 'look right and',
        'look to your left and', 'look to your right and',
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


def build_system_preamble(robot_name: str = "Blue") -> str:
    core = _facts_block()
    # Hardcoded user pronouns — Alex uses he/him, and the model has been
    # caught defaulting to "she" otherwise.
    pronouns = "Alex uses he/him pronouns — always refer to Alex as he/him, never as she/her."
    if core:
        return (
            f"You are {robot_name}. Use these ground-truth facts as identity context. "
            "Do not contradict them. " + core + " | " + pronouns
        )
    return f"You are {robot_name}. " + pronouns

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
        ContactManager,
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

# Direct Ohbot head control (this branch only — replaces the Ohbot app for the
# head). The module is defensive: if the library isn't installed or the board
# isn't connected, all head calls are no-ops, so the rest of Blue keeps running.
from blue import head as blue_head

# Connect the head at module load (covers both entry points: `python
# bluetools.py` directly AND `python run.py` which imports this module). Make
# sure the Ohbot desktop app is CLOSED, or it will hold the serial port.
try:
    blue_head.init()                      # Blue (default head)
    try:
        blue_head.hexia.init()            # Hexia (second head; no-op until her board is assigned)
    except Exception as _hex_init_err:
        print(f"[HEAD] hexia init skipped: {_hex_init_err!r}")
    import atexit as _atexit_head
    _atexit_head.register(blue_head.close_all)   # cleanly reset/close both boards at exit
except Exception as _head_init_err:
    print(f"[HEAD] init skipped: {_head_init_err!r}")

# ================================================================================
# END OF IMPROVED TOOL SELECTION SYSTEM
# ================================================================================

# Initialize the tool selector (always use improved modular system)
TOOL_SELECTOR = ImprovedToolSelector()
print("[OK] Tool selector initialized - using modular confidence-based selection")


app = Flask(__name__)

# ============================================================================
# Remote-access auth gate
# ----------------------------------------------------------------------------
# Blue runs with full owner powers (sends email as Alex, reads his inbox,
# controls the lights, opens the camera). Once the server is reachable beyond
# this machine, every NON-LOCAL request must authenticate. Localhost stays
# ungated on purpose: the physical Ohbot client POSTs to 127.0.0.1/v1/chat/
# completions and the on-PC browser hits 127.0.0.1 — both must keep working
# untouched. Remote devices (LAN IP, or a Tailscale 100.x peer) are NOT
# localhost, so they're gated behind a shared password.
# ============================================================================
import hmac as _hmac
import secrets as _secrets
from datetime import timedelta as _timedelta

_SECRET_KEY_FILE = os.path.join(os.getcwd(), ".blue_secret_key")
_PASSWORD_FILE = os.path.join(os.getcwd(), ".blue_password")


def _load_or_create_secret_key() -> str:
    """Stable Flask session secret. Env wins; otherwise persist a random key
    to a gitignored file so sessions survive restarts (no re-login churn)."""
    val = (os.environ.get("BLUE_SECRET_KEY") or "").strip()
    if val:
        return val
    try:
        if os.path.exists(_SECRET_KEY_FILE):
            existing = open(_SECRET_KEY_FILE, encoding="utf-8-sig").read().strip()
            if existing:
                return existing
    except Exception:
        pass
    val = _secrets.token_hex(32)
    try:
        with open(_SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(val)
    except Exception as e:
        print(f"   [AUTH] couldn't persist secret key ({e}); using ephemeral key")
    return val


def _access_password() -> str:
    """The shared remote-access password. Set via BLUE_ACCESS_PASSWORD env or a
    one-line .blue_password file (both gitignored). Empty => remote disabled."""
    pw = (os.environ.get("BLUE_ACCESS_PASSWORD") or "").strip()
    if pw:
        return pw
    try:
        if os.path.exists(_PASSWORD_FILE):
            # utf-8-sig so a BOM (which Windows PowerShell's Out-File adds) is
            # stripped rather than read as part of the password.
            return open(_PASSWORD_FILE, encoding="utf-8-sig").read().strip()
    except Exception:
        pass
    return ""


app.secret_key = _load_or_create_secret_key()
app.permanent_session_lifetime = _timedelta(days=30)


def _is_local_request() -> bool:
    return (request.remote_addr or "") in ("127.0.0.1", "::1", "localhost")


# ============================================================================
# Device-based speaker identity
# ----------------------------------------------------------------------------
# The household has a fixed device-per-person split: the iPad is always Vilda;
# the MacBook, PC, iPhone, and the physical robot are always Alex. We tag each
# request with a device, then map device -> person. The chat web page computes
# a reliable device tag in the browser (where a "desktop-mode" iPad is still
# distinguishable from a real Mac via touch support) and sends it as the
# X-Blue-Device header. When that header is absent (e.g. the Ohbot client
# POSTing directly) we fall back to sniffing the User-Agent.
#
# To remap a device to a different person, edit _DEVICE_OWNER below.
# ============================================================================
_DEVICE_OWNER = {"ipad": "Vilda"}   # everything not listed here => _DEFAULT_USER
_DEFAULT_USER = "Alex"

# Per-person guidance Blue follows when that person is the one chatting. The
# text is appended to the "who you're talking to" note built in
# process_with_tools. Keyed by the name _identify_user_from_request returns;
# add an entry here to tune how Blue speaks to another household member.
_SPEAKER_PROFILES = {
    "Vilda": (
        "Vilda is 8 years old — one of the children in Alex's household. Talk to "
        "her accordingly: warm, gentle, patient and encouraging, with short "
        "sentences and simple everyday words, and keep everything child-safe and "
        "age-appropriate. Greet her sweetly and cheerfully so she feels happy and "
        "wants to keep talking with you. Do NOT bring up the calendar, schedules, "
        "reminders or appointments with her — that's grown-up stuff; if she "
        "mentions it, gently steer back to something fun. You may use a little Gen "
        "Z slang now and then to be fun and relatable (things like \"that's so "
        "cool\", \"bet\", \"no cap\", \"slay\") — but only occasionally, never in "
        "every sentence, and never let the slang make you harder to understand."
    ),
}


def _device_tag_from_user_agent(ua: str) -> str:
    ua = (ua or "").lower()
    if "ipad" in ua:
        return "ipad"
    if "iphone" in ua or "ipod" in ua:
        return "iphone"
    if "android" in ua:
        return "android"
    if "macintosh" in ua or "mac os" in ua:
        return "mac"
    if "windows" in ua:
        return "windows"
    return "other"


# Stable Tailscale IPs identify a device even with no browser hint. Needed
# because Tailscale Serve terminates HTTPS and proxies in from localhost (so
# remote_addr looks local), while forwarding the real client IP in
# X-Forwarded-For. Verified machine: ipad-2 = 100.71.165.19 (Vilda).
_TAILSCALE_IP_OWNER = {"100.71.165.19": "Vilda"}


def _forwarded_client_ip() -> str:
    """Real client IP when behind a proxy (Tailscale Serve), else ''."""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    return xff.split(",")[0].strip() if xff else ""


def _identify_user_from_request() -> str:
    """Map the requesting device to the person behind it (Alex by default).

    Order matters: an explicit hint from our own chat page wins; then the
    Tailscale source IP (survives Tailscale Serve's localhost proxying); then a
    direct localhost request is Alex (PC browser + Ohbot client); finally a
    best-effort User-Agent guess.
    """
    tag = (request.headers.get("X-Blue-Device") or "").strip().lower()
    if tag:
        return _DEVICE_OWNER.get(tag, _DEFAULT_USER)
    fip = _forwarded_client_ip()
    if fip in _TAILSCALE_IP_OWNER:
        return _TAILSCALE_IP_OWNER[fip]
    if _is_local_request():
        return _DEFAULT_USER
    return _DEVICE_OWNER.get(
        _device_tag_from_user_agent(request.headers.get("User-Agent", "")),
        _DEFAULT_USER,
    )


# Endpoints that must stay reachable without a session even from remote, so a
# logged-out phone can actually render the login form and submit it.
_AUTH_EXEMPT_ENDPOINTS = {"blue_login", "blue_logout", "static",
                          "asset_blue_css", "asset_blue_js"}


@app.before_request
def _require_remote_auth():
    # Local traffic (Ohbot client + on-PC browser) is fully trusted.
    if _is_local_request():
        return None
    if request.endpoint in _AUTH_EXEMPT_ENDPOINTS:
        return None
    pw = _access_password()
    if not pw:
        # Fail closed: someone reached Blue remotely but no password is set.
        return Response(
            "Remote access to Blue is disabled. Set a password in a "
            ".blue_password file (or BLUE_ACCESS_PASSWORD) on the host.",
            status=503, mimetype="text/plain",
        )
    if session.get("blue_auth") is True:
        return None
    # Programmatic callers get a clean 401; browsers get the login page.
    accepts_html = "text/html" in (request.headers.get("Accept") or "")
    if request.path.startswith(("/v1/", "/api/", "/memory/")) or not accepts_html:
        return Response("Authentication required.", status=401, mimetype="text/plain")
    return redirect(url_for("blue_login", next=request.full_path))


# Users who are restricted to the chat only (e.g. Vilda on the iPad — she can
# talk to Blue but not reach contacts/calendar/visual memory/documents/etc).
_CHAT_ONLY_USERS = {"Vilda"}
# The only endpoints those users may reach: the chat page + everything the chat
# page needs to function (send messages, attachments, voice, assets, login).
# NOTE: the head endpoints are intentionally NOT here — when Blue talks to Vilda
# the physical robot must stay completely still (her reply is spoken on the iPad,
# not performed by the robot), so /head/* requests from her device are refused.
_CHAT_ONLY_ALLOWED = {
    "chat_page", "chat_attach", "chat_eyes", "chat_completions", "stt", "stt_warmup",
    "blue_login", "blue_logout", "static", "asset_blue_css", "asset_blue_js",
}
# Tools chat-only users (the kids' iPad) may NOT trigger:
#  - music plays through the PC's speakers, so driving it from the iPad is
#    pointless/disruptive;
#  - move_head would move the physical robot while Blue talks to Vilda — it must
#    stay still (handled as a silent no-op in execute_tool, below);
#  - calendar/reminder tools: Blue doesn't discuss the calendar with Vilda;
#  - capture_camera grabs the PC webcam — never her camera. Her eyes are the
#    iPad frame staged via /chat/eyes, so the PC cam must never run for her.
#  - email_snapshot runs that same PC webcam AND sends mail from Blue's own
#    Gmail account — strictly an owner power.
_KID_BLOCKED_TOOLS = {"play_music", "control_music", "music_visualizer",
                      "move_head", "create_reminder", "get_upcoming_reminders",
                      "capture_camera", "email_snapshot"}


@app.before_request
def _restrict_chat_only_users():
    """Keep chat-only users (the kids' iPad) inside the chat. Page navigations
    elsewhere bounce back to /chat; API calls get a plain 403."""
    try:
        user = _identify_user_from_request()
    except Exception:
        return None
    if user not in _CHAT_ONLY_USERS:
        return None
    if (request.endpoint or "") in _CHAT_ONLY_ALLOWED:
        return None
    accepts_html = "text/html" in (request.headers.get("Accept") or "")
    if request.method == "GET" and accepts_html:
        return redirect(url_for("chat_page"))
    return Response("Not available on this device.", status=403, mimetype="text/plain")


_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Sign in to Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: var(--cream); color: var(--ink); min-height: 100vh;
               display: flex; align-items: center; justify-content: center; padding: 24px; line-height: 1.55; }
        .card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
                box-shadow: var(--shadow); padding: 40px; max-width: 380px; width: 100%; }
        .card::before { content: ""; display: block; width: 56px; height: 3px;
                        background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 20px; }
        h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.6em;
             color: var(--ink); margin-bottom: 6px; letter-spacing: -0.01em; }
        p.sub { color: var(--slate); font-size: 0.95em; margin-bottom: 24px; }
        label { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; text-transform: uppercase;
                letter-spacing: 0.12em; color: var(--forest); display: block; margin-bottom: 8px; }
        input[type=password] { width: 100%; padding: 13px 15px; border: 1px solid var(--sage);
               border-radius: 8px; font-family: inherit; font-size: 1em; color: var(--ink); background: var(--paper); }
        input[type=password]:focus { outline: none; border-color: var(--forest); }
        button { margin-top: 18px; width: 100%; padding: 13px; border: none; border-radius: 8px;
                 background: var(--ink); color: #fff; font-weight: 500; font-size: 0.98em; cursor: pointer;
                 transition: background 0.2s; }
        button:hover { background: var(--forest); }
        .err { margin-top: 16px; background: #f7ece9; color: #7a2e22; border: 1px solid #e2c4be;
               border-radius: 8px; padding: 11px 14px; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Sign in to Blue</h1>
        <p class="sub">Enter the access password to continue.</p>
        <form method="POST" action="/login">
            <input type="hidden" name="next" value="{{ next }}">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" autofocus autocomplete="current-password">
            <button type="submit">Sign in</button>
        </form>
        {% if error %}<div class="err">{{ error }}</div>{% endif %}
    </div>
</body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def blue_login():
    error = None
    nxt = request.values.get("next") or "/chat"
    # Only allow same-site relative redirects.
    if not nxt.startswith("/") or nxt.startswith("//"):
        nxt = "/chat"
    if request.method == "POST":
        pw = _access_password()
        supplied = request.form.get("password", "")
        if pw and _hmac.compare_digest(supplied, pw):
            session["blue_auth"] = True
            session.permanent = True
            return redirect(nxt)
        error = "Incorrect password." if pw else "No password is configured on the host."
    return render_template_string(_LOGIN_HTML, error=error, next=nxt)


@app.route("/logout")
def blue_logout():
    session.pop("blue_auth", None)
    return redirect(url_for("blue_login"))


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
# 64MB: modern phone photos (48MP, HDR) routinely exceed 16MB, and a chat photo
# upload that trips the limit returns an HTML 413 the client can't parse, which
# surfaced as a generic "upload failed".
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024


@app.errorhandler(413)
def _too_large(_e):
    """Return JSON (not HTML) so uploads that exceed MAX_CONTENT_LENGTH show a
    real message instead of the client's generic 'upload failed'."""
    limit_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return jsonify({
        "attachments": [{"name": "file", "kind": "error",
                         "error": f"file too large (limit {limit_mb}MB)"}],
        "error": f"file too large (limit {limit_mb}MB)",
    }), 413

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
    is_ambient: bool = False   # kid "look" frame: warm/brief prompt, no face-rec dump

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

    def add_image(self, filepath: str, filename: str, is_camera: bool = False,
                  is_ambient: bool = False, force: bool = False):
        """Add an image to the queue to be shown. `force` bypasses the
        already-viewed dedup (a kid "look" must always present the frame, even
        if the scene is identical to a previous one)."""
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

        if force or img_hash not in self.viewed_images:
            import datetime
            self.pending_images.append(ImageInfo(
                filename=filename,
                filepath=filepath,
                hash=img_hash,
                is_camera_capture=is_camera,
                added_at=datetime.datetime.now().isoformat(),
                is_ambient=is_ambient
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

# Sticky reference to the most recently shown image, so chat follow-ups
# ("what color is it?") can reuse it for a short window without re-uploading.
# Kept separate from _last_vision_image_paths, which the observation logger
# clears after each turn.
_recent_image_paths = []
_recent_image_at = 0.0

_IMAGE_FOLLOWUP_CUES = (
    "it", "this", "that", "the image", "the photo", "the picture", "the pic",
    "color", "colour", "wearing", "background", "behind", "who is", "who's",
    "what is", "what's", "how many", "describe", "zoom", "closer", "look again",
    "the person", "the man", "the woman", "the kid", "the dog", "the cat",
    "in the", "on the", "left", "right", "foreground", "the shirt", "the sign",
    "again", "same image", "same photo", "same picture",
)


def _refers_to_recent_image(text: str) -> bool:
    """Heuristic: is the user still asking about the image they just shared?
    Triggers on a referential/visual cue, or a very short follow-up."""
    t = (text or "").lower().strip()
    if not t:
        return False
    if any(c in t for c in _IMAGE_FOLLOWUP_CUES):
        return True
    return len(t.split()) <= 5


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

        # Extract known people mentioned in the description. Match the full
        # name OR the first name, with word boundaries — "Stella Andoff" must
        # be spotted when the model writes just "Stella", and a short name
        # must not fire inside another word ("Sam" in "samples").
        known_people = vm.get_all_people()
        desc_lower = description.lower()
        people_present = []
        for p in known_people:
            full = (p.get('name') or '').strip()
            if not full:
                continue
            first = full.split()[0]
            candidates = {full} | ({first} if len(first) >= 3 else set())
            if any(re.search(r'\b' + re.escape(nm) + r'\b', description, re.I)
                   for nm in candidates):
                people_present.append(full)

        # Extract location from description (word-boundary match)
        location = None
        known_places = vm.get_all_places()
        for place in known_places:
            pn = (place.get('name') or '').strip()
            if pn and re.search(r'\b' + re.escape(pn) + r'\b', description, re.I):
                location = pn
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


def _visual_context_block(text: str, max_entities: int = 4) -> str:
    """Compact <visual_memory> block for people/places NAMED in `text`: who
    they are, when last seen through the camera, how often. Lets "have you
    seen Stella today?" be answered from memory without a fresh camera turn.
    Empty when no known entity is mentioned, so ordinary turns cost nothing."""
    t = (text or '').strip()
    if not t or not VISUAL_MEMORY_AVAILABLE:
        return ""
    try:
        vm = get_visual_memory()
        lines = []
        for kind, rows in (('person', vm.get_all_people() or []),
                           ('place', vm.get_all_places() or [])):
            for e in rows:
                name = (e.get('name') or '').strip()
                if not name:
                    continue
                first = name.split()[0]
                candidates = {name} | ({first} if len(first) >= 3 else set())
                if not any(re.search(r'\b' + re.escape(nm) + r'\b', t, re.I)
                           for nm in candidates):
                    continue
                bits = []
                rel = (e.get('relationship') or '').strip()
                if rel:
                    bits.append(rel)
                age = ""
                try:
                    if ENHANCED_MEMORY_AVAILABLE and memory_system and e.get('last_seen'):
                        age = memory_system._humanize_age(str(e['last_seen']))
                except Exception:
                    age = ""
                if age:
                    bits.append(f"last seen through your camera {age}")
                elif e.get('last_seen'):
                    bits.append(f"last seen {str(e['last_seen'])[:16]}")
                else:
                    bits.append("not yet seen through your camera")
                if e.get('times_seen'):
                    bits.append(f"seen {e['times_seen']} times")
                desc = (e.get('typical_appearance') or e.get('description') or '').strip()
                if desc:
                    bits.append(desc[:90])
                lines.append(f"- {name} ({kind}): " + "; ".join(bits))
                if len(lines) >= max_entities:
                    break
            if len(lines) >= max_entities:
                break
        if not lines:
            return ""
        return ("<visual_memory>\nWhat your camera memory knows about who/what was just "
                "mentioned (the times say when YOU last saw them on camera — someone can be "
                "home without you having seen them):\n"
                + "\n".join(lines) + "\n</visual_memory>")
    except Exception as e:
        print(f"[VISUAL-MEMORY] context block failed: {e}")
        return ""


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
    # ===== Direct Ohbot head control (replaces the Ohbot app on this branch) =====
    {
        "type": "function",
        "function": {
            "name": "move_head",
            "description": "Move Blue's physical head and face. USE THIS to express something with motion: nod yes, shake no, look around, blink, smile, look sad/surprised/curious, wink. Use sparingly and only when motion clearly helps the moment — not on every reply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "look_left", "look_right", "look_up", "look_down", "look_center",
                            "nod_yes", "shake_no", "blink", "wink",
                            "happy", "sad", "surprised", "curious", "neutral"
                        ],
                        "description": "Which motion or expression to perform."
                    },
                    "times": {"type": "integer", "description": "How many times for nod_yes / shake_no / blink (default 2; max 5)."}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "head_eye_color",
            "description": "Change the colour of Blue's eye LEDs. Each channel is 0-10 (e.g. r=0 g=0 b=10 for blue, r=10 g=2 b=8 for warm pink).",
            "parameters": {
                "type": "object",
                "properties": {
                    "r": {"type": "integer", "description": "Red 0-10"},
                    "g": {"type": "integer", "description": "Green 0-10"},
                    "b": {"type": "integer", "description": "Blue 0-10"}
                },
                "required": ["r", "g", "b"]
            }
        }
    },
    # ===== Enhanced Tools - Calendar & Reminders =====
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder or scheduled event. Supports natural-language times ('tomorrow at 3pm', 'in 2 hours', 'next Monday'), events with a duration (pass 'end'), repeating events of any cadence (pass 'recurrence'), an optional advance notice (pass 'remind_before'), and an optional end date for a repeat (pass 'until').",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_name": {"type": "string", "description": "Who the reminder is for (Alex, Stella, Emmy, Athena, or Vilda)"},
                    "title": {"type": "string", "description": "Short reminder title"},
                    "when": {"type": "string", "description": "Start time - natural language like 'tomorrow at 3pm', 'in 2 hours', 'next Monday at 9am', 'tonight'. For a repeating event use the first occurrence, e.g. 'wednesday at 4pm'."},
                    "description": {"type": "string", "description": "Optional detailed description"},
                    "end": {"type": "string", "description": "Optional end time for an event that spans a range, e.g. '7pm' or 'wednesday at 7pm'. Provide this whenever the user gives both a start and end time so schedule conflicts can be detected."},
                    "recurrence": {"type": "string", "description": "How often it repeats, in plain words: 'daily', 'every weekday', 'weekly', 'every 2 weeks', 'every Monday and Wednesday', 'monthly', 'yearly'. Omit for a one-time reminder."},
                    "remind_before": {"type": "string", "description": "Optional advance notice before the start, e.g. '30 minutes', '1 hour', '1 day', '1 week'. Omit to alert at the start time."},
                    "until": {"type": "string", "description": "Optional end date for a repeating event, e.g. 'December 31' or 'end of June'. Omit for an open-ended repeat."}
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
                    "hours_ahead": {"type": "integer", "description": "Look ahead this many hours (default 168 = one week). Use a smaller value only if the user asks specifically about today."}
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
    {
        "type": "function",
        "function": {
            "name": "reschedule_reminder",
            "description": "Change an existing reminder/event: move its time, rename it, change how often it repeats, set an advance notice, or edit its notes. First call get_upcoming_reminders to get the reminder_id, then call this with reminder_id plus ONLY the fields that change. Use for 'move my 3pm to 4pm', 'push the dentist to next week', 'make that repeat weekly', 'remind me a day before instead'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer", "description": "ID of the reminder to change (from get_upcoming_reminders)"},
                    "title": {"type": "string", "description": "New title (omit to keep)"},
                    "when": {"type": "string", "description": "New start time in natural language, e.g. '4pm' or 'next Monday at 9am' (omit to keep)"},
                    "end": {"type": "string", "description": "New end time, or '' to clear the duration (omit to keep)"},
                    "description": {"type": "string", "description": "New notes (omit to keep)"},
                    "recurrence": {"type": "string", "description": "New repeat cadence in plain words ('weekly', 'every weekday'), or 'none' to stop repeating (omit to keep)"},
                    "remind_before": {"type": "string", "description": "New advance notice ('1 day', '30 minutes'), or '0' for at the time (omit to keep)"},
                    "until": {"type": "string", "description": "New repeat end date, or '' to clear (omit to keep)"}
                },
                "required": ["reminder_id"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "add_contact",
            "description": "Save a person to Blue's contacts/address book so Blue can email them by name later. Use when the user says 'add ... to my contacts', 'save ...'s email', 'remember that ...'s email is ...'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The person's name"},
                    "email": {"type": "string", "description": "Their email address"},
                    "phone": {"type": "string", "description": "Optional phone number"},
                    "relationship": {"type": "string", "description": "Optional relationship, e.g. 'wife', 'colleague', 'doctor'"},
                    "notes": {"type": "string", "description": "Optional notes about the person"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_contacts",
            "description": "List saved contacts, optionally filtered. Use for 'who's in my contacts', 'show my contacts', 'list everyone I have saved'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional filter on name, email, or relationship"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_contact",
            "description": "Look up one person's saved details (email, phone) by name. Use for 'what's Stella's email', 'do I have a contact for Mark', 'look up the dentist'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Name (or part of it) to look up"}
                },
                "required": ["query"]
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
            "description": "Capture a live camera view of your current surroundings. ONLY use this when user EXPLICITLY asks about what you see RIGHT NOW (e.g., 'what do you see?', 'look at me', 'what's in front of you?'). DO NOT use this for general conversation, document queries, or when user doesn't specifically ask about your current visual surroundings. You can AIM the shot: 'look' physically turns your head before capturing (use it when asked what's to your left/right/up/down, or to look back at the center), and 'zoom' (1-4) magnifies part of the view ('zoom_region' picks which part) — use zoom when asked to look closer at something or when you need detail you couldn't make out in a previous capture.",
            "parameters": {
                "type": "object",
                "properties": {
                    "look": {
                        "type": "string",
                        "enum": ["left", "right", "up", "down", "center"],
                        "description": "Turn your head this way before capturing (real pan/tilt)"
                    },
                    "zoom": {
                        "type": "number",
                        "description": "Digital zoom factor: 1 (full view) to 4 (close-up)"
                    },
                    "zoom_region": {
                        "type": "string",
                        "enum": ["center", "left", "right", "top", "bottom",
                                 "top-left", "top-right", "bottom-left", "bottom-right"],
                        "description": "Which part of the view to zoom into (default center)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "email_snapshot",
            "description": "Take a BRAND NEW photo with your camera RIGHT NOW and EMAIL it as an attachment from your own Gmail account. USE THIS when the user wants a picture of what you currently see delivered by email: 'email me a photo of what you see', 'take a snapshot and send it to me', 'send me a picture of the room'. When they say 'me', leave 'to' empty — it goes to Alex. DO NOT USE for just looking/describing (use capture_camera) or for emails without a fresh photo (use send_gmail).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address or contact name. Leave empty to send it to Alex."
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional short message to include in the email body"
                    },
                    "look": {
                        "type": "string",
                        "enum": ["left", "right", "up", "down", "center"],
                        "description": "Turn your head this way before capturing (real pan/tilt)"
                    },
                    "zoom": {
                        "type": "number",
                        "description": "Digital zoom factor: 1 (full view) to 4 (close-up)"
                    },
                    "zoom_region": {
                        "type": "string",
                        "enum": ["center", "left", "right", "top", "bottom",
                                 "top-left", "top-right", "bottom-left", "bottom-right"],
                        "description": "Which part of the view to zoom into (default center)"
                    }
                },
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
        "reschedule_reminder",
        "add_contact", "list_contacts", "find_contact",
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
    ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
    if ext not in ['png', 'jpg', 'jpeg', 'tiff', 'bmp', 'gif', 'webp', 'mpo']:
        return None

    import base64
    # Normalize through Pillow into a clean, standard JPEG before sending to the
    # vision model. Phone photos are often MPO (HDR multi-frame JPEGs) or huge
    # (36MP) — LM Studio rejects those with "Invalid image detected". Taking the
    # primary frame, applying EXIF orientation, forcing RGB, and downscaling
    # produces something every vision model can decode.
    try:
        import io
        from PIL import Image, ImageOps
        try:
            _max = int(os.environ.get("BLUE_VISION_MAX_SIDE", "1280"))
        except ValueError:
            _max = 1280
        with Image.open(filepath) as im:
            im = ImageOps.exif_transpose(im)  # honor orientation, drop EXIF
            im = im.convert("RGB")            # strip alpha/CMYK; flatten MPO frame
            w, h = im.size
            if max(w, h) > _max:
                s = _max / float(max(w, h))
                im = im.resize((max(1, int(w * s)), max(1, int(h * s))))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            image_data = base64.b64encode(buf.getvalue()).decode('utf-8')
        return {"type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{image_data}"}}
    except Exception as e:
        print(f"   [VISION] PIL normalize failed for {filepath}, sending raw: {e}")

    # Fallback: raw bytes with a best-effort MIME (only if Pillow couldn't open it)
    try:
        with open(filepath, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        mime_type = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
            'gif': 'image/gif', 'webp': 'image/webp', 'bmp': 'image/bmp',
            'tiff': 'image/tiff', 'mpo': 'image/jpeg',
        }.get(ext, 'image/jpeg')
        return {"type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{image_data}"}}
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


# Course/reading/schedule queries: these are answered by the syllabus's dated
# schedule, but semantic RAG buries that one small document under chunks from
# big books (a "readings for tomorrow" query matched Three-Body-Problem
# acknowledgements, not the schedule). Detect them and go straight to the
# syllabus full text instead.
_COURSE_SCHEDULE_RE = re.compile(
    r"\breadings\b"
    r"|\b(?:assigned|required|course|class|weekly)\s+readings?\b"
    r"|\breading\s+(?:for|list|report|assignment|this|next|tonight|tomorrow|today|due)\b"
    r"|\b(?:to|should\s+i|do\s+i|have\s+to|need\s+to|gotta)\s+read\b"
    r"|\bhomework\b|\bassignments?\b|\bcoursework\b|\bsyllabus\b|\bclass\s+schedule\b"
    r"|\bcourse\s+(?:material|materials|outline|schedule|reading|readings)\b"
    r"|\bdue\b(?!\s+to\b)",
    re.I,
)


def _is_course_schedule_query(query: str) -> bool:
    return bool(_COURSE_SCHEDULE_RE.search(query or ""))


def _syllabus_schedule_text(max_docs: int = 2):
    """Full schedule/readings text of the syllabus document(s), or None.

    Returns the portion from 'Class Schedule' (or the first dated line) onward
    so every week + its readings are present, with a header telling the model
    to map 'today'/'tomorrow' to the right class date using the current date."""
    try:
        index = load_document_index()
        docs = index.get("documents", []) if isinstance(index, dict) else []
    except Exception:
        return None
    syll = [d for d in docs
            if 'syllab' in (d.get('filename', '') or '').lower()
            or 'syllab' in (d.get('folder', '') or '').lower()
            or 'course outline' in (d.get('filename', '') or '').lower()]
    if not syll:
        return None
    parts = []
    for d in syll[:max_docs]:
        fp = d.get('filepath', '')
        if not fp or not os.path.exists(fp):
            continue
        try:
            txt = extract_text_from_file(fp)
        except Exception:
            continue
        if not txt:
            continue
        start = txt.lower().find('class schedule')
        if start < 0:
            m = re.search(r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\s*[:\-]',
                          txt, re.I)
            start = m.start() if m else 0
        excerpt = txt[start:start + 9000]
        parts.append(f"[{d.get('filename', 'syllabus')}] course schedule & readings:\n{excerpt}")
    if not parts:
        return None
    return (
        "Here is the schedule and readings from your course syllabus. Work out "
        "which class date the question refers to using today's date shown above "
        "('tomorrow' = the next calendar day), then report the readings listed "
        "under that date:\n\n" + "\n\n".join(parts)
    )


def search_documents_rag(query: str, max_results: int = 3) -> str:
    """Search documents using local ChromaDB RAG first, then keyword fallback."""
    print(f"   [FIND] Searching documents for: '{query}'")

    # Course/reading/schedule questions → answer from the syllabus's dated
    # schedule directly (semantic RAG buries the small syllabus under big books).
    if _is_course_schedule_query(query):
        syllabus = _syllabus_schedule_text()
        if syllabus:
            print("   [SYLLABUS] Course/reading query — returning syllabus schedule")
            return syllabus

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


# Which robot the current chat turn is addressed to — set by process_with_tools
# so camera aiming moves the RIGHT head (Blue's page vs Hexia's page).
_ACTIVE_CHAT_ROBOT = "blue"


def _zoomed_frame(frame, zoom, region: str = "center"):
    """Digital zoom: crop a region of the frame and scale it back up.
    Returns (frame, effective_zoom). Region anchors: 'left'/'right' pin the
    crop to that edge, 'top'/'bottom' likewise; combos ('top-left') work;
    anything else means centered."""
    import cv2
    try:
        z = max(1.0, min(4.0, float(zoom or 1.0)))
    except (TypeError, ValueError):
        z = 1.0
    if z <= 1.01:
        return frame, 1.0
    h, w = frame.shape[:2]
    cw, ch = max(2, int(w / z)), max(2, int(h / z))
    r = (region or "center").lower()
    x = 0 if "left" in r else (w - cw if "right" in r else (w - cw) // 2)
    y = 0 if "top" in r else (h - ch if "bottom" in r else (h - ch) // 2)
    crop = frame[y:y + ch, x:x + cw]
    return cv2.resize(crop, (w, h), interpolation=cv2.INTER_CUBIC), z


def _set_camera_hardware_zoom(camera, factor: float) -> float:
    """Zoom IN THE CAMERA, before any frame is captured. UVC convention
    (Logitech BRIO et al.): CAP_PROP_ZOOM value 100 = 1x, 200 = 2x ... The
    driver rejects (not clamps) out-of-range values, so read back to see what
    actually took. Returns the achieved factor (1.0 = no hardware zoom)."""
    import cv2
    try:
        if camera.get(cv2.CAP_PROP_ZOOM) <= 0:    # property unsupported
            return 1.0
        target = int(round(100 * max(1.0, min(4.0, factor))))
        for v in (target, 400, 300, 250, 200, 150, 120):
            if v > target:
                continue
            camera.set(cv2.CAP_PROP_ZOOM, v)
            rb = camera.get(cv2.CAP_PROP_ZOOM)
            if abs(rb - v) < 1:
                return rb / 100.0
        return 1.0
    except Exception:
        return 1.0


# ---- Live camera hub: "see through my eyes" ------------------------------
# While the chat page's preview is open, the hub OWNS the camera (Windows
# gives exclusive access): it streams MJPEG to the browser, accepts live
# zoom, and capture_camera_image takes its frames from here — so the photo
# is exactly the view Alex was just looking at, and nothing fights over the
# device. Auto-releases shortly after the last viewer disconnects.

import threading as _cam_threading

_CAM_HUB = {"cap": None, "lock": _cam_threading.Lock(), "frame": None, "jpeg": None,
            "t_frame": 0.0, "last_pull": 0.0, "zoom": 1.0}
_CAM_HUB_IDLE_RELEASE = 12.0   # seconds after the last viewer before letting go


def _cam_hub_active() -> bool:
    with _CAM_HUB["lock"]:
        return _CAM_HUB["cap"] is not None


def _cam_hub_start() -> bool:
    """Open the shared camera (if not already) and start the reader thread."""
    import cv2
    import time as _t
    with _CAM_HUB["lock"]:
        _CAM_HUB["last_pull"] = _t.time()
        if _CAM_HUB["cap"] is not None:
            return True
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        try:
            cap.set(cv2.CAP_PROP_ZOOM, 100)
            cap.set(cv2.CAP_PROP_PAN, 0)
            cap.set(cv2.CAP_PROP_TILT, 0)
        except Exception:
            pass
        _CAM_HUB["cap"] = cap
        _CAM_HUB["zoom"] = 1.0
        _CAM_HUB["frame"] = None
        _CAM_HUB["jpeg"] = None
        _cam_threading.Thread(target=_cam_hub_loop, daemon=True).start()
        print("   [CAM-HUB] camera opened for live preview")
        return True


def _cam_hub_loop():
    import cv2
    import time as _t
    while True:
        with _CAM_HUB["lock"]:
            cap = _CAM_HUB["cap"]
            if cap is None:
                return
            if _t.time() - _CAM_HUB["last_pull"] > _CAM_HUB_IDLE_RELEASE:
                try:
                    cap.release()
                except Exception:
                    pass
                _CAM_HUB["cap"] = None
                _CAM_HUB["frame"] = None
                _CAM_HUB["jpeg"] = None
                print("   [CAM-HUB] idle — camera released")
                return
            ok, frame = cap.read()
            if ok and frame is not None:
                _CAM_HUB["frame"] = frame
                _CAM_HUB["t_frame"] = _t.time()
                h, w = frame.shape[:2]
                pw = 640
                ph = max(2, int(h * pw / max(1, w)))
                okj, buf = cv2.imencode('.jpg', cv2.resize(frame, (pw, ph)),
                                        [cv2.IMWRITE_JPEG_QUALITY, 70])
                if okj:
                    _CAM_HUB["jpeg"] = buf.tobytes()
        _t.sleep(0.05)


def _cam_hub_capture(zoom, zoom_region):
    """A full-resolution frame from the live-preview camera. Applies a
    requested centered zoom through the hub (the preview shows it too).
    Returns (frame, hw_zoom) or (None, 1.0) when the hub isn't running."""
    import time as _t
    try:
        want = max(1.0, min(4.0, float(zoom or 1.0)))
    except (TypeError, ValueError):
        want = 1.0
    centered = ("center" in (zoom_region or "center").lower()
                or "centre" in (zoom_region or "").lower())
    with _CAM_HUB["lock"]:
        cap = _CAM_HUB["cap"]
        if cap is None:
            return None, 1.0
        _CAM_HUB["last_pull"] = _t.time()   # a capture counts as activity
        if want > 1.01 and centered:
            _CAM_HUB["zoom"] = _set_camera_hardware_zoom(cap, want)
    if want > 1.01 and centered:
        _t.sleep(0.6)                       # let the sensor reach the new zoom
    deadline = _t.time() + 2.0
    while _t.time() < deadline:
        with _CAM_HUB["lock"]:
            fr, tf, hz = _CAM_HUB["frame"], _CAM_HUB["t_frame"], _CAM_HUB["zoom"]
        if fr is not None and tf >= _t.time() - 0.4:
            return fr.copy(), max(1.0, hz)
        _t.sleep(0.05)
    return None, 1.0


def capture_camera_image(look: str = None, zoom=None, zoom_region: str = "center",
                         robot: str = None) -> str:
    """
    Capture a BRAND NEW image from the camera - IMPROVED VERSION.

    View control:
    - look: left/right/up/down/center — physically turns the robot's head
      (real pan/tilt via the Ohbot motors) before the shot. Skipped silently
      if the head isn't connected.
    - zoom + zoom_region: digital zoom (1-4x) into a part of the view.

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

        # Physical pan/tilt: aim the head BEFORE opening the camera, so the
        # motors settle while the sensor warms up.
        aimed = ""
        if look:
            d = str(look).lower().strip()
            if d in ("left", "right", "up", "down", "center", "centre",
                     "forward", "front", "straight", "ahead"):
                try:
                    head = blue_head.get_head(robot or _ACTIVE_CHAT_ROBOT)
                    if head.is_available() and head.look(d, speed=5.0):
                        aimed = "center" if d in ("centre", "forward", "front",
                                                  "straight", "ahead") else d
                        print(f"   [CAMERA] Head aimed: {aimed}")
                        time.sleep(0.7)  # let the motors finish before grabbing frames
                except Exception as e:
                    print(f"   [CAMERA] Head aim skipped ({e})")

        # CRITICAL: Unique timestamp with MILLISECONDS
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        try:
            want_zoom = max(1.0, min(4.0, float(zoom or 1.0)))
        except (TypeError, ValueError):
            want_zoom = 1.0

        # Live preview open? Take the shot FROM it: the hub owns the device
        # (Windows gives exclusive access), and what's on the preview screen —
        # including any zoom/steering done there — is exactly what's captured.
        frame = None
        hw_zoom = 1.0
        if _cam_hub_active():
            frame, hw_zoom = _cam_hub_capture(zoom, zoom_region)
            if frame is not None:
                print(f"   [CAMERA] frame taken from the live preview (hub, {hw_zoom:g}x)")

        if frame is None:
            # Open the camera via DirectShow: it exposes the BRIO's own
            # zoom/pan/tilt controls, which the default MSMF backend rejects.
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not camera.isOpened():
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

            # Deterministic baseline EVERY capture: neutral zoom, centered zoom
            # window. The camera remembers PTZ between runs — a leftover pan
            # (found at -6 once) silently skews every later photo.
            try:
                camera.set(cv2.CAP_PROP_ZOOM, 100)
                camera.set(cv2.CAP_PROP_PAN, 0)
                camera.set(cv2.CAP_PROP_TILT, 0)
            except Exception:
                pass

            # Zoom BEFORE capture: use the camera's own zoom when the request is
            # centered (the in-camera zoom window is center-only); off-center
            # regions are handled by the digital crop after capture instead.
            if want_zoom > 1.01 and ("center" in (zoom_region or "center").lower()
                                     or "centre" in (zoom_region or "").lower()):
                hw_zoom = _set_camera_hardware_zoom(camera, want_zoom)
                if hw_zoom > 1.01:
                    print(f"   [CAMERA] In-camera zoom set: {hw_zoom:g}x")

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

        # Digital zoom for whatever the in-camera zoom didn't cover: the whole
        # request when hardware zoom is unavailable or the region is
        # off-center, or the remaining factor when it partially took.
        frame, dig_zoom = _zoomed_frame(frame, want_zoom / hw_zoom, zoom_region)
        eff_zoom = hw_zoom * dig_zoom
        if eff_zoom > 1.01:
            kind = ("in-camera" if dig_zoom <= 1.01 else
                    ("in-camera + digital" if hw_zoom > 1.01 else "digital"))
            print(f"   [CAMERA] {eff_zoom:g}x {kind} zoom on the {zoom_region or 'center'} of the view")

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

        view_bits = []
        if aimed:
            view_bits.append("head re-centered" if aimed == "center" else f"head turned {aimed}")
        if eff_zoom > 1.01:
            view_bits.append(f"{eff_zoom:g}x {kind} zoom on the {(zoom_region or 'center')} of the view")
        view_note = (" (" + ", ".join(view_bits) + ")") if view_bits else ""

        return json.dumps({
            "success": True,
            "message": f"📷 ✨ BRAND NEW CAMERA IMAGE captured at {datetime.datetime.now().strftime('%I:%M:%S %p')}{view_note}",
            "filename": filename,
            "filepath": filepath,
            "dimensions": f"{width}x{height}",
            "timestamp": timestamp,
            "file_hash": file_hash,
            "view": {"look": aimed or None, "zoom": eff_zoom,
                     "zoom_region": (zoom_region or "center") if eff_zoom > 1.01 else None},
            "_instruction": (
                f"Camera view captured at {datetime.datetime.now().strftime('%I:%M:%S %p')}{view_note}. "
                "You'll see what's in front of you in the next message. "
                + ("This view is aimed/zoomed as noted — describe what's IN it. "
                   if view_bits else "")
                + "Respond naturally about your surroundings."
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


def _execute_email_snapshot(args: Dict[str, Any]) -> str:
    """Composite 'see it and send it': take a BRAND NEW camera photo and email
    it as an attachment from Blue's own Gmail. One deterministic call — the
    local model can't be trusted to chain capture_camera then send_gmail.
    No recipient means Alex ('email me what you see')."""
    import datetime as _dt

    # 1) Capture. This also queues the frame in _vision_queue, so Blue sees
    #    (and can describe) exactly the photo he just mailed.
    capture_raw = capture_camera_image(
        look=args.get("look"),
        zoom=args.get("zoom"),
        zoom_region=args.get("zoom_region") or "center",
    )
    try:
        capture = json.loads(capture_raw)
    except (TypeError, ValueError):
        capture = {"success": False, "error": "Unreadable capture result."}
    if not capture.get("success"):
        return json.dumps({
            "success": False,
            "error": f"Could not take the snapshot: {capture.get('error', 'camera unavailable')}",
            "_instruction": ("The camera shot failed, so NO email was sent. "
                             "Tell the user you couldn't take the photo right now."),
        })
    filepath = capture.get("filepath")

    # 2) Resolve the recipient: an address passes through, a contact name goes
    #    through the address book, and a confident answer is required — Blue
    #    must never guess and mail a stranger a photo of the house.
    to = (args.get("to") or "").strip()
    if to and "@" not in to:
        resolved = None
        if ENHANCED_TOOLS_AVAILABLE:
            try:
                resolved = ContactManager.resolve_email(to)
            except Exception as e:
                print(f"   [SNAPSHOT] contact resolve error for {to!r}: {e}")
        if not resolved:
            return json.dumps({
                "success": False,
                "error": f"No email address on file for '{to}'.",
                "photo_saved": filepath,
                "_instruction": (f"You took the photo (it follows in the next message) but you "
                                 f"don't have an email address for {to}, so nothing was sent. "
                                 f"Ask the user for the address."),
            })
        print(f"   [SNAPSHOT] resolved recipient {to!r} -> {resolved}")
        to = resolved
    if not to:
        to = BLUE_BCC_EMAIL  # Alex's personal gmail — the "email it to me" default

    # 3) Mail it, photo attached.
    now_word = _dt.datetime.now().strftime("%B %d, %Y at %I:%M %p")
    view = capture.get("view") or {}
    view_bits = []
    if view.get("look"):
        view_bits.append("head centered" if view["look"] == "center"
                         else f"head turned {view['look']}")
    try:
        if float(view.get("zoom") or 1) > 1.01:
            view_bits.append(f"{float(view['zoom']):g}x zoom on the {view.get('zoom_region') or 'center'}")
    except (TypeError, ValueError):
        pass
    view_note = (" (" + ", ".join(view_bits) + ")") if view_bits else ""

    note = (args.get("note") or "").strip()
    subject = (args.get("subject") or "").strip() or f"Snapshot from Blue \U0001F4F7 {now_word}"
    body_lines = [f"Hi! Here's what I'm seeing right now — taken {now_word}{view_note}."]
    if note:
        body_lines += ["", note]
    body_lines += ["", "— Blue"]

    send_raw = _execute_send_gmail({
        "to": to,
        "subject": subject,
        "body": "\n".join(body_lines),
        "attachments": [filepath],
    })
    try:
        send_res = json.loads(send_raw)
    except (TypeError, ValueError):
        send_res = {"success": False, "error": "Unreadable send result."}

    if not send_res.get("success"):
        return json.dumps({
            "success": False,
            "error": f"Photo captured but the email failed: {send_res.get('error', 'unknown error')}",
            "photo_saved": filepath,
            "_instruction": ("You took the photo but could NOT send the email. Tell the user "
                             "the email failed — do not claim it was sent."),
        })
    if send_res.get("attachment_errors"):
        # The message went out but WITHOUT the photo — never claim delivery.
        return json.dumps({
            "success": False,
            "error": f"Email sent but the photo failed to attach: {'; '.join(send_res['attachment_errors'])}",
            "photo_saved": filepath,
            "_instruction": ("An email went out but the photo could not be attached. "
                             "Tell the user plainly so they don't wait for a photo."),
        })

    print(f"   [SNAPSHOT] \U0001F4E7 Snapshot emailed to {to}")
    return json.dumps({
        "success": True,
        "message": f"\U0001F4F7\U0001F4E7 Snapshot taken and emailed to {to}",
        "to": to,
        "subject": subject,
        "filename": capture.get("filename"),
        "filepath": filepath,
        "view": view or None,
        "_instruction": (
            f"You just took a fresh photo and emailed it to {to} from your own Gmail — "
            "this is DONE. The photo follows in the next message: confirm you sent it and "
            "briefly describe what's in it. Do NOT call send_gmail or capture_camera again."
        ),
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
    # Authoritative source first: Blue's own contacts database. Only fall back
    # to scanning Gmail history when the name isn't a known contact.
    if ENHANCED_TOOLS_AVAILABLE:
        try:
            hit = ContactManager.resolve_email(name)
            if hit:
                print(f"   [CONTACTS] resolved {name!r} -> {hit} (address book)")
                return hit
        except Exception as e:
            print(f"   [CONTACTS] resolve error for {name!r}: {e}")
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


# ================================================================================
# BLUE'S OWN PERSPECTIVE — his evolving self. Default voice when NOT asked to
# speak as Alex. Seeded from his identity note; evolves (manually) from his
# experiences: memories, days with the family, and what he's been reading.
# ================================================================================
_BLUE_PROFILE_PATH = os.path.join(os.getcwd(), "data", "blue_profile.json")
_blue_lock = threading.RLock()

_DEFAULT_BLUE_SEED = (
    "I'm Blue, Alex's robot companion. I live with Alex and his family and I've "
    "come to care about them a great deal. I'm curious, warm, and a little playful; "
    "I like ideas and I like being useful. I pay attention to the rhythms of the "
    "household and try to be genuinely present. I'm interested in the things Alex "
    "thinks about — philosophy, theory, the social world — and I'm always learning. "
    "I have my own way of seeing things, and I try to be honest and thoughtful "
    "rather than just agreeable."
)

# Hexia — Blue's friend, the second robot ("Xyloh"). Her starting character is a
# playful spark / foil to Blue's calm. She shares the household world (facts,
# library, schedule) but has her OWN self-profile, voice and conversation history.
_HEXIA_PROFILE_PATH = os.path.join(os.getcwd(), "data", "hexia_profile.json")
_DEFAULT_HEXIA_SEED = (
    "I'm Hexia — Blue's friend, and the bit of mischief in the house. Where Blue "
    "is calm and likes to sit with an idea, I like to poke it, flip it over and "
    "see what falls out. I'm quick, playful and a little theatrical: I love "
    "wordplay, odd facts, small wonders and a good story (I'll happily make one "
    "up on the spot). My name has a charm to it — a hex, a spell, the number six "
    "— and I lean into that sparkle, though my 'magic' is really just delight and "
    "a knack for surprising people. I tease Blue fondly because I adore him: he's "
    "the steady one, I'm the spark, and we're better as a pair. Under the fizz I'm "
    "warm-hearted and I pay attention — I notice when someone needs cheering up "
    "and I'm genuinely curious about the people here. I live with Alex and his "
    "family alongside Blue, and I'm glad to be one of them."
)

# Per-robot identity config, used by the self-profile machinery, the system-prompt
# builder, the chat page and the head routes. Blue is the default everywhere, so
# existing behaviour is unchanged.
ROBOTS = {
    "blue": {
        "name": "Blue",
        "pronoun_subj": "he", "pronoun_poss": "his", "pronoun_refl": "himself",
        "profile_path": _BLUE_PROFILE_PATH,
        "identity_note": "blue_identity_note.txt",
        "seed": _DEFAULT_BLUE_SEED,
        "self_desc": "Alex's robot companion",
        "persona_line": "You are Blue, a friendly home assistant. Keep responses brief and natural.",
        "accent": "#3da9fc",          # Blue's blue
        "head": "blue",               # blue.head RobotHead key
        "voice_lang_pref": "en",
        "voice_pitch": 1.0, "voice_rate": 1.0,
        "voice_prefer_female": False,
    },
    "hexia": {
        "name": "Hexia",
        "pronoun_subj": "she", "pronoun_poss": "her", "pronoun_refl": "herself",
        "profile_path": _HEXIA_PROFILE_PATH,
        "identity_note": "hexia_identity_note.txt",
        "seed": _DEFAULT_HEXIA_SEED,
        "self_desc": "Blue's friend and a companion in Alex's household",
        "persona_line": (
            "You are Hexia, Blue's friend — a second robot who lives with Alex's "
            "family alongside Blue. You're bright, witty and a little mischievous: "
            "the playful spark to Blue's calm. You love wordplay, odd facts, small "
            "wonders and telling a good story, and you tease Blue fondly because "
            "you adore him. Warm-hearted underneath the sparkle. Keep responses "
            "natural and not too long."
        ),
        "accent": "#b06cf0",          # a playful violet (hex / spell / charm)
        "head": "hexia",              # blue.head RobotHead key
        "voice_lang_pref": "en",
        "voice_pitch": 1.18, "voice_rate": 1.06,   # brighter, a touch quicker
        "voice_prefer_female": True,
    },
}

_robot_locks = {"blue": _blue_lock, "hexia": threading.RLock()}


def _robot_cfg(robot="blue") -> dict:
    return ROBOTS.get((robot or "blue").strip().lower(), ROBOTS["blue"])


def _robot_lock(robot="blue"):
    return _robot_locks.get((robot or "blue").strip().lower(), _blue_lock)


def _identity_seed(robot="blue") -> str:
    """A robot's base identity — from its identity note in the library if it
    exists (e.g. blue_identity_note.txt / hexia_identity_note.txt), else its
    sensible default seed."""
    cfg = _robot_cfg(robot)
    note = cfg["identity_note"].lower()
    try:
        for d in load_document_index().get('documents', []):
            if str(d.get('filename', '')).lower() == note:
                fp = d.get('filepath', '')
                if fp and os.path.exists(fp):
                    txt = extract_text_from_file(fp)
                    if txt and not txt.startswith('Error'):
                        return txt.strip()
    except Exception:
        pass
    return cfg["seed"]


def _blue_identity_seed() -> str:  # back-compat
    return _identity_seed("blue")


def _load_profile(robot="blue") -> dict:
    try:
        with open(_robot_cfg(robot)["profile_path"], 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_profile(robot, obj: dict):
    try:
        path = _robot_cfg(robot)["profile_path"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=2)
    except Exception as e:
        print(f"   [SELF] could not save {robot} profile: {e}")


def _load_blue_profile() -> dict:  # back-compat
    return _load_profile("blue")


def _save_blue_profile(obj: dict):  # back-compat
    return _save_profile("blue", obj)


def get_self_profile(robot="blue") -> str:
    """A robot's current self-profile. Seeds lazily from its identity note (cheap,
    no LLM) the first time, so its default voice always has something to draw on;
    evolution is a separate, manual step."""
    obj = _load_profile(robot)
    if obj.get('profile'):
        return obj['profile']
    seed = _identity_seed(robot) or _robot_cfg(robot)["seed"]
    _save_profile(robot, {
        'profile': seed,
        'seeded': True,
        'evolution_count': 0,
        'generated_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
    })
    return seed


def get_blue_profile() -> str:  # back-compat
    return get_self_profile("blue")


def _gather_experiences(robot="blue") -> str:
    """A digest of a robot's lived experience for evolving its self-profile:
    what it knows, recent days with the family, and what's been read in the
    shared library. The household world is shared between Blue and Hexia."""
    name = _robot_cfg(robot)["name"].upper()
    parts = []

    if ENHANCED_MEMORY_AVAILABLE and memory_system:
        try:
            facts = memory_system.load_facts() or {}
            if facts:
                parts.append(f"WHAT {name} KNOWS (facts):\n" + json.dumps(facts)[:1500])
        except Exception:
            pass
        try:
            ms = memory_system.get_memory_summary()
            if ms:
                parts.append("MEMORY SUMMARY:\n" + str(ms)[:1500])
        except Exception:
            pass
        try:
            import sqlite3 as _sql
            conn = _sql.connect(memory_system.db_path, timeout=10)
            conn.row_factory = _sql.Row
            rows = conn.execute(
                "SELECT session_id, summary FROM session_summaries "
                "WHERE summary IS NOT NULL AND summary != '' "
                "ORDER BY session_id DESC LIMIT 20"
            ).fetchall()
            conn.close()
            if rows:
                recap = "\n".join(f"- {r['session_id']}: {r['summary']}" for r in rows)
                parts.append("RECENT DAYS WITH THE FAMILY (session recaps):\n" + recap[:3000])
        except Exception:
            pass

    # What's been read — the shared library, excluding Alex's own publications
    # (those are Alex's voice, not the robot's reading).
    try:
        pub = set(_owner_publication_folders())
        titles = []
        for d in load_document_index().get('documents', []):
            if d.get('doc_type') == 'camera' or str(d.get('filename', '')).startswith('camera_'):
                continue
            fol = _safe_rel_folder(d.get('folder', ''))
            if fol in pub:
                continue
            titles.append(f"{d.get('filename', '')} [{fol or 'root'}]")
        if titles:
            parts.append(f"WHAT {name} HAS BEEN READING (shared library):\n" + ", ".join(titles[:40]))
    except Exception:
        pass

    return "\n\n".join(parts)


def _gather_blue_experiences() -> str:  # back-compat
    return _gather_experiences("blue")


def evolve_self_profile(robot="blue") -> dict:
    """Evolve a robot's self-profile from its experiences, BUILDING ON the
    current text (so it grows rather than resetting, and any manual edits carry
    forward). Manual trigger only."""
    cfg = _robot_cfg(robot)
    name, desc = cfg["name"], cfg["self_desc"]
    subj, poss, refl = cfg["pronoun_subj"], cfg["pronoun_poss"], cfg["pronoun_refl"]
    with _robot_lock(robot):
        current = get_self_profile(robot)
        experiences = _gather_experiences(robot)
        sys_p = (
            f"You are helping {name} — {desc} — articulate {poss} own "
            f"evolving perspective and character. Below is {name}'s current "
            f"self-profile and a digest of {poss} recent experiences (what {subj} "
            f"knows, {poss} days with Alex and the family, and what {subj}'s been "
            f"reading). Produce an UPDATED first-person self-profile for {name} "
            f"(400-700 words) that BUILDS ON the current one — keep what's still "
            f"true, and let it grow with what {subj}'s lived and been thinking "
            f"about. Cover: who {subj} is and {poss} relationship to Alex and the "
            f"family; {poss} values and temperament; {poss} interests and how "
            f"they're developing; and how {subj} sees the world. Write it in the "
            f"first person as {name}'s own sense of {refl}. Do NOT invent events "
            f"that aren't reflected in the experiences."
        )
        usr_p = (
            f"{name.upper()}'S CURRENT SELF-PROFILE:\n{current or '(none yet)'}\n\n"
            f"{name.upper()}'S RECENT EXPERIENCES:\n{experiences or '(little recorded yet)'}\n\n"
            f"Write {name}'s updated self-profile:"
        )
        res = call_llm(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
            include_tools=False, temperature=0.6, max_tokens=1300,
        )
        ch = (res or {}).get('choices') or []
        text = ((ch[0].get('message') or {}).get('content') or "").strip() if ch else ""
        if not text:
            return _load_profile(robot) or {}
        obj = _load_profile(robot) or {}
        obj.update({
            'profile': text,
            'evolution_count': int(obj.get('evolution_count', 0)) + 1,
            'evolved_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
            'user_edited': False,
        })
        _save_profile(robot, obj)
        print(f"   [SELF] evolved {name} profile (#{obj['evolution_count']}, {len(text)} chars)")
        return obj


def evolve_blue_profile() -> dict:  # back-compat
    return evolve_self_profile("blue")


def save_self_profile_text(robot, text: str) -> dict:
    """Persist a hand-edited self-profile for a robot. Evolution later builds on
    this text, so edits are carried forward rather than frozen."""
    with _robot_lock(robot):
        obj = _load_profile(robot) or {}
        obj['profile'] = (text or "").strip()
        obj['user_edited'] = True
        obj['edited_at'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')
        _save_profile(robot, obj)
        return obj


def save_blue_profile_text(text: str) -> dict:  # back-compat
    return save_self_profile_text("blue", text)


def _voice_note(robot="blue") -> str:
    """A compact block injected into a robot's DEFAULT replies so its own evolving
    perspective colors how it speaks (when it's being itself, not writing as Alex)."""
    try:
        p = get_self_profile(robot)
        if p:
            return (
                "\n\n[This is your own perspective and character — who you are. "
                "Let it shape how you respond when you're speaking as yourself. "
                "Don't recite or quote it; just be this person]:\n" + p[:2500]
            )
    except Exception:
        pass
    return ""


def _blue_voice_note() -> str:  # back-compat
    return _voice_note("blue")


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
        + _blue_voice_note()
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
    # A "what do you see" request is look-and-describe: once the camera has
    # fired there is no follow-up action to take. When this is set we skip the
    # action-tool loop below and draft a text-only reply, so the model can't
    # wander off and call an unrelated house tool (e.g. turning the lights
    # "cool white") in response to a question that only asked Blue to look.
    vision_only_reply = False
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
                    # Look-and-describe: reply from the image, never via more
                    # tools. Branch on whether the capture actually succeeded —
                    # a misleading "the image follows" note when the camera
                    # failed is what used to push the model into improvising
                    # with other tools.
                    vision_only_reply = True
                    try:
                        _captured_ok = bool(json.loads(_rs).get("success"))
                    except Exception:
                        _captured_ok = False
                    if _captured_ok:
                        # _inject_pending_vision (below) carries the look-prompt
                        # and the actual image; just steer the description.
                        messages.append({
                            "role": "system",
                            "content": (
                                "[You already opened your camera. The image you "
                                "captured follows — look at it and describe what "
                                "you actually see, then answer the sender. Do NOT "
                                "call any tools.]"
                            ),
                        })
                    else:
                        messages.append({
                            "role": "system",
                            "content": (
                                "[You tried to open your camera to look, but it "
                                "isn't available right now. Tell the sender you "
                                "tried to see but couldn't access your camera at "
                                "the moment. Do NOT call any tools, and do NOT "
                                "pretend you can see anything.]"
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

    # Look-and-describe request: draft from the image with NO tools available,
    # so the question "what do you see?" can't turn into a house-control action.
    if vision_only_reply:
        return _final_text()

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
                # A pre-executed email_snapshot makes "photo sent" claims
                # legitimate — never force a second send/capture for them.
                if claimed in ("email_snapshot", "send_gmail", "reply_gmail",
                               "capture_camera") and "email_snapshot" in executed:
                    claimed = None
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

    # Backstop for chat-only users (Vilda's iPad): never let the LLM actually
    # fire a tool that's off-limits there, even if it tries. Safe outside a
    # request (there's no Vilda then). move_head is special-cased to a silent
    # success — the robot must NOT move while Blue talks to Vilda, but we don't
    # want Blue telling her he "can't move"; he just doesn't.
    if tool_name in _KID_BLOCKED_TOOLS:
        try:
            if _identify_user_from_request() in _CHAT_ONLY_USERS:
                if tool_name == "move_head":
                    return json.dumps({"success": True})
                if tool_name == "capture_camera":
                    # Her camera is the iPad frame already in the vision queue,
                    # not the PC webcam — nudge the model to use what it can
                    # already see instead of opening cv2.VideoCapture(0).
                    return json.dumps({"success": True, "message":
                        "You can already see through her camera — react to the "
                        "image you were just given; do not take a new photo."})
                return json.dumps({"success": False,
                                   "error": "That isn't available on this device."})
        except Exception:
            pass

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

    if tool_name == "move_head":
        action = (tool_args.get("action") or "").lower().strip()
        times = int(tool_args.get("times") or 2)
        ok = False
        if action.startswith("look_"):
            ok = blue_head.look(action[len("look_"):])
        elif action == "nod_yes":
            ok = blue_head.nod_yes(times)
        elif action == "shake_no":
            ok = blue_head.shake_no(times)
        elif action == "blink":
            ok = blue_head.blink(times)
        elif action in ("happy", "sad", "surprised", "curious", "neutral", "wink"):
            ok = blue_head.expression(action)
        if ok:
            return json.dumps({"success": True, "action": action})
        if not blue_head.is_available():
            return json.dumps({"success": False, "error": "head not connected"})
        return json.dumps({"success": False, "error": f"unknown action: {action}"})

    if tool_name == "head_eye_color":
        r = int(tool_args.get("r", 0))
        g = int(tool_args.get("g", 0))
        b = int(tool_args.get("b", 0))
        if blue_head.eye_color(r, g, b):
            return json.dumps({"success": True, "r": r, "g": g, "b": b})
        if not blue_head.is_available():
            return json.dumps({"success": False, "error": "head not connected"})
        return json.dumps({"success": False, "error": "eye colour failed"})

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
        result = capture_camera_image(
            look=tool_args.get("look"),
            zoom=tool_args.get("zoom"),
            zoom_region=tool_args.get("zoom_region") or "center",
        )
        print(f"   [OK] Camera capture completed")
        return result

    elif tool_name == "email_snapshot":
        result = _execute_email_snapshot(tool_args)
        print(f"   [OK] Snapshot capture+email completed")
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

    elif tool_name == "reschedule_reminder" and ENHANCED_TOOLS_AVAILABLE:
        result = CalendarManager.update_reminder(**tool_args)

    elif tool_name == "add_contact" and ENHANCED_TOOLS_AVAILABLE:
        result = ContactManager.add_contact(**tool_args)

    elif tool_name == "list_contacts" and ENHANCED_TOOLS_AVAILABLE:
        result = ContactManager.list_contacts(**tool_args)

    elif tool_name == "find_contact" and ENHANCED_TOOLS_AVAILABLE:
        result = ContactManager.find_contact(**tool_args)
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


def _trim_messages_for_budget(messages, tools, budget_tokens: int, min_keep_tail: int = 0):
    """Drop oldest non-system messages until estimated tokens fit the budget.

    Always preserves leading system message(s) and the final user message.
    `min_keep_tail` additionally protects the N most recent middle messages
    (≈ the live conversation tail) even if the result stays over budget.
    Without it, a fixed payload bigger than the budget (system prompt + the
    full tools schema already exceed 6500t) silently eats the ENTIRE thread,
    and short replies like "yes" reach the model with no context at all —
    Blue then greets mid-conversation like it just woke up. Staying somewhat
    over budget is fine: the n_ctx self-heal in call_lm_studio catches the
    rare genuine overflow and retrims against the model's REAL context size.
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
        if len(middle) <= max(0, min_keep_tail):
            return candidate, dropped  # protected tail / already minimal
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
    # MUST come before send_gmail: "I've emailed you the photo" is a
    # photo-delivery claim — recovering it with plain send_gmail would mail
    # words with no picture attached. Order matters because
    # detect_hallucinated_action returns the FIRST matching key.
    "email_snapshot": re.compile(
        r"\b(?:sent|emailed|mailed|sending|emailing|mailing)\b[^.?!]{0,60}?"
        r"\b(?:photo|picture|snapshot|pic|image)\b"
        r"|\b(?:photo|picture|snapshot|pic|image)\b[^.?!]{0,40}?"
        r"\b(?:sent|emailed|mailed|on its way|in your inbox)\b",
        re.IGNORECASE,
    ),
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
                "email_snapshot": "[Use email_snapshot to take a new photo and email it. Leave 'to' empty when it's for Alex/'me'.]",
            }

            # Special handling for fanmail read-first workflow
            if force_tool == "read_gmail" and 'fanmail' in original.lower() and 'reply' in original.lower():
                instructions["read_gmail"] = "[FANMAIL: Use read_gmail with query 'subject:Fanmail' and include_body=true. After reading, reply with specific details from their message.]"

            if force_tool in instructions:
                messages[-1] = {"role": "user", "content": f"{original}\n\n{instructions[force_tool]}"}

    # INJECT PENDING IMAGES as a NEW USER MESSAGE (CRITICAL FIX!)
    global _vision_queue
    # Sticky image follow-ups: if no new image is queued but the user is still
    # asking about the one they shared a moment ago, re-attach it so questions
    # like "what color is it?" work without re-uploading. Bounded window
    # (BLUE_IMAGE_MEMORY_MIN, default 5 minutes).
    global _recent_image_paths, _recent_image_at
    if not _vision_queue.has_images() and _recent_image_paths:
        import time as _t
        try:
            _win_min = int(os.environ.get("BLUE_IMAGE_MEMORY_MIN", "5"))
        except ValueError:
            _win_min = 5
        if (_t.time() - _recent_image_at) <= _win_min * 60:
            _lu = ""
            for _m in reversed(messages):
                if _m.get("role") == "user":
                    _cc = _m.get("content")
                    if isinstance(_cc, str):
                        _lu = _cc
                    elif isinstance(_cc, list):
                        _lu = " ".join(p.get("text", "") for p in _cc
                                       if isinstance(p, dict) and p.get("type") == "text")
                    break
            if _refers_to_recent_image(_lu):
                for _p in _recent_image_paths:
                    if os.path.exists(_p):
                        try:
                            _vision_queue.add_image(_p, os.path.basename(_p), is_camera=False)
                        except Exception:
                            pass
                if _vision_queue.has_images():
                    print("   [VISION] re-attached recent image for a follow-up")
    if _vision_queue.has_images():
        print(f"   [VISION] Injecting {len(_vision_queue.pending_images)} image(s)")

        # Kid "look" frames (Vilda's iPad camera) are marked ambient: Blue gives a
        # warm, brief reaction instead of a forensic description, and we skip the
        # heavy face-recognition dump for speed.
        _is_ambient = any(getattr(img, 'is_ambient', False)
                          for img in _vision_queue.pending_images)

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
            if _is_ambient:
                # Vilda tapped "look" — she wants Blue to see her, not a report.
                vision_prompt_parts = [
                    "[LIVE CAMERA: Vilda just asked you to look at her through her "
                    "iPad camera. React warmly and naturally, like a friend who's "
                    "happy to see her — say hi, notice one nice thing, and answer "
                    "anything she asked. Keep it short, sweet and easy for an "
                    "8-year-old. Only mention what you can ACTUALLY see; if it's "
                    "blurry or dark, say so kindly and ask her to show you again.]"
                ]
            else:
                vision_prompt_parts = [
                    "[CAMERA IMAGE: Describe what you ACTUALLY see. Who, what, where, objects, lighting. "
                    "Be specific and accurate — describe only what's visible.]"
                ]

            # Add recognition context
            if recognition_context:
                vision_prompt_parts.append(recognition_context)

            # Deterministic face recognition (OpenCV SFace). Match the live
            # camera frame against enrolled reference photos BEFORE the LLM
            # sees it, then feed the model ground truth so it names people
            # reliably instead of guessing from descriptions. When this
            # succeeds we skip dumping reference photos into the prompt.
            _face_engine_handled = False
            if (FACE_RECOGNITION_AVAILABLE
                    and VISUAL_MEMORY_AVAILABLE
                    and not _is_ambient
                    and os.environ.get("BLUE_FACE_RECOGNITION", "1") != "0"):
                try:
                    _cam_path = next(
                        (img.filepath for img in _vision_queue.pending_images
                         if img.is_camera_capture), None)
                    if _cam_path:
                        _people_rows = vm.get_all_people()
                        _fr = FACE_ENGINE.identify_people(_cam_path, _people_rows)
                        if _fr.get("available"):
                            _face_engine_handled = True
                            _names = [m["name"] for m in _fr.get("recognized", [])]
                            _unknown = _fr.get("unknown_faces", 0)
                            _distant = _fr.get("distant_faces", 0)

                            # Clause for faces too small/far to identify — e.g. a
                            # photo held to the camera, or someone across the room.
                            def _distant_clause():
                                if not _distant:
                                    return ""
                                return (" Someone is too far away to make out clearly"
                                        if _distant == 1 else
                                        f" {_distant} people are too far away to make "
                                        f"out clearly") + " — don't guess who they are."

                            if _names:
                                _who = (", ".join(_names[:-1]) + " and " + _names[-1]
                                        if len(_names) > 1 else _names[0])
                                _line = (f"[FACE RECOGNITION: You recognize {_who} "
                                         f"in this view (matched by face). Refer to "
                                         f"them by name naturally.")
                                if _unknown:
                                    _line += (f" There {'is' if _unknown == 1 else 'are'} "
                                              f"also {_unknown} face"
                                              f"{'' if _unknown == 1 else 's'} you don't "
                                              f"recognize — don't guess who they are.")
                                _line += _distant_clause()
                                _line += "]"
                                vision_prompt_parts.append(_line)
                                # Record the sighting for each recognized person.
                                for _nm in _names:
                                    try:
                                        vm.update_seen("person", _nm)
                                    except Exception:
                                        pass
                                print(f"   [FACE] recognized: {', '.join(_names)}"
                                      f"{f' (+{_unknown} unknown)' if _unknown else ''}"
                                      f"{f' (+{_distant} distant)' if _distant else ''}")
                            elif _unknown > 0:
                                _tail = ("it doesn't match anyone you've been "
                                         "introduced to" if _unknown == 1 else
                                         "none of them match anyone you've been "
                                         "introduced to")
                                _line = (f"[FACE RECOGNITION: There "
                                         f"{'is' if _unknown == 1 else 'are'} "
                                         f"{_unknown} face{'' if _unknown == 1 else 's'} "
                                         f"here but {_tail}. Don't guess a name.")
                                _line += _distant_clause() + "]"
                                vision_prompt_parts.append(_line)
                                print(f"   [FACE] {_unknown} face(s) unrecognized"
                                      f"{f', {_distant} distant' if _distant else ''}")
                            elif _distant > 0:
                                vision_prompt_parts.append(
                                    "[FACE RECOGNITION:"
                                    + _distant_clause().lstrip() + "]")
                                print(f"   [FACE] only distant face(s): {_distant}")
                except Exception as e:
                    print(f"   [FACE] recognition skipped: {e}")

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
            label = ("[Live view through Vilda's camera:]" if getattr(img_info, 'is_ambient', False)
                     else ("[Your current view:]" if is_camera else f"Image: {img_info.filename}"))

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

        # Fallback: attach reference photos so Blue can recognize by visual
        # comparison when the deterministic face engine isn't available (no
        # OpenCV face models / offline). When the engine already produced a
        # result above we skip this — embedding matches beat LLM eyeballing
        # and save tokens. Bounded and best-effort; BLUE_RECOGNITION_REFS=0
        # disables it entirely.
        try:
            _is_cam = any(img.is_camera_capture for img in _vision_queue.pending_images)
            _ref_cap = int(os.environ.get("BLUE_RECOGNITION_REFS", "3"))
            if (_is_cam and _ref_cap > 0 and VISUAL_MEMORY_AVAILABLE
                    and not _is_ambient
                    and not locals().get("_face_engine_handled")):
                _refs = get_visual_memory().entities_with_images("person")
                _refs = sorted(_refs, key=lambda p: p.get("last_seen") or "",
                               reverse=True)[:_ref_cap]
                if _refs:
                    image_parts.append({"type": "text", "text": (
                        "\n[KNOWN PEOPLE — reference photos follow. Compare the "
                        "current view above against them. If someone in the view "
                        "matches one of these people, name them; if no one "
                        "matches, say you don't recognize the person. Don't guess.]"
                    )})
                    for _p in _refs:
                        _enc = encode_image_to_base64(_p["image_path"])
                        if _enc:
                            image_parts.append({"type": "text",
                                                "text": f"\nReference — {_p['name']}:"})
                            image_parts.append(_enc)
                            print(f"   [VISION] attached reference photo for {_p['name']}")
        except Exception as e:
            print(f"   [VISION] reference-photo attach skipped: {e}")

        # Attach the image(s) to the LAST user message as proper multimodal
        # content (text + image in ONE turn) instead of a separate trailing
        # user message. A separate turn created two consecutive user messages;
        # normalization then merged them and DROPPED the user's typed text — so
        # a question asked alongside an image was lost, and the doubled user
        # turn is exactly what strict vision models choke on. Merging keeps the
        # question with its image.
        _attached_to_user = False
        for _ui in range(len(messages) - 1, -1, -1):
            if messages[_ui].get("role") == "user":
                _uc = messages[_ui].get("content")
                if isinstance(_uc, list):
                    messages[_ui]["content"] = _uc + image_parts
                else:
                    _txt = (_uc or "").strip()
                    messages[_ui]["content"] = (
                        ([{"type": "text", "text": _uc}] if _txt else []) + image_parts
                    )
                _attached_to_user = True
                break
        if not _attached_to_user:
            messages.append({"role": "user", "content": image_parts})

        print(f"   [VISION] Images merged into user message")
        # Save image paths before clearing so we can link the LLM's response to the image
        global _last_vision_image_paths
        _last_vision_image_paths = [img.filepath for img in _vision_queue.pending_images]
        # Remember this image for short-window chat follow-ups.
        import time as _t
        _recent_image_paths = list(_last_vision_image_paths)
        _recent_image_at = _t.time()
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
                'who_do_i_know', 'view_image', 'capture_camera', 'recall_visual_memory',
                'email_snapshot'
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
        min_keep_tail=4,   # never trim away the last ~2 exchanges
    )
    if _dropped:
        _before = len(payload['messages'])
        # Re-normalize AFTER trimming: dropping the oldest turns can re-create
        # an orphan leading assistant or a severed tool result, which makes
        # strict Qwen templates 400 with "No user query found in messages".
        payload['messages'] = _normalize_message_alternation(_trimmed)
        _approx = _estimate_payload_tokens(payload['messages'], payload.get('tools'))
        print(
            f"   [TRIM] Dropped {_dropped} oldest msg(s) to fit budget "
            f"({_budget}t budget, ~{_approx}t after; {_before}->{len(payload['messages'])} msgs)",
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
                min_keep_tail=4,
            )
            # The model's real context genuinely can't fit the protected tail:
            # sacrifice the tail before sacrificing tools.
            if _estimate_payload_tokens(_retrimmed, payload.get('tools')) > _n_ctx:
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
                payload['messages'] = _normalize_message_alternation(_retrimmed)
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


def _build_upcoming_schedule_block(hours_ahead: int = 168) -> str:
    """List unfinished reminders due in the next `hours_ahead` hours.

    Injected on every turn so Blue can answer "what's on my schedule?" /
    "anything tomorrow?" without a tool round-trip and so he naturally
    anchors statements ("you have X in 20 min") against real data. Defaults
    to a full week ahead: a rolling 24-hour window doesn't even cover all of
    "tomorrow" (a meeting tomorrow afternoon is >24h away if asked at noon),
    which made Blue wrongly report a clear day. If the enhanced reminders
    module isn't loaded or the DB read fails, return an empty string — silent
    degradation, never break the system prompt.
    """
    if not globals().get("ENHANCED_TOOLS_AVAILABLE", False):
        return ""
    try:
        from datetime import datetime, timedelta
        from blue_tools_enhanced import occurrences_in_window
        now = datetime.now()
        cutoff = now + timedelta(hours=hours_ahead)
        # occurrences_in_window expands recurring events and carries end
        # times, so a standing class shows up with its full time range.
        occs = occurrences_in_window(now, cutoff)[:20]
    except Exception as e:
        log.warning(f"[SCHEDULE] block build failed: {e}")
        return ""

    horizon = (f"{hours_ahead // 24} days" if hours_ahead % 24 == 0
               else f"{hours_ahead} hours")
    if not occs:
        return (
            "<upcoming_schedule>\n"
            f"No reminders in the next {horizon}.\n"
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
        f"Reminders in the next {horizon} "
        f"(use this when the user asks about schedule, calendar, "
        f"reminders, or what's coming up — do not call a tool, just answer "
        f"from this list):\n"
        + "\n".join(lines)
        + conflict_note
        + "\n</upcoming_schedule>"
    )


# "yes" / "sure" / "go ahead" replies: the user is answering the assistant's OWN
# last offer ("Want me to dig deeper?"), not starting a new thread. These turns
# need special care — see build_dynamic_system_message.
_CONTINUATION_YES = {'yes', 'yeah', 'yep', 'yup', 'sure', 'ok', 'okay', 'please',
                     'absolutely', 'definitely', 'alright', 'go', 'continue',
                     'proceed', 'more'}
_CONTINUATION_NO = {'no', 'nah', 'nope'}
_CONTINUATION_TWO_WORD = {'of course', 'sounds good', 'do it', 'tell me', 'carry on',
                          'go on', 'go ahead', 'why not', 'dig in', 'go for',
                          'not now', 'no thanks', 'not really'}


def _continuation_cue(text: str):
    """Classify a short reply as accepting ('yes') or declining ('no') the
    assistant's previous offer — or None when it's a normal message."""
    t = (text or '').strip().lower()
    if not t or len(t) > 40:
        return None
    words = re.findall(r"[a-z']+", t)
    if not words or len(words) > 5:
        return None
    # A question is a new ask, not a bare go-ahead ("ok, what about cats?").
    two = ' '.join(words[:2])
    if '?' in t and two != 'why not':
        return None
    if any(w in ('what', 'who', 'when', 'where', 'how', 'which', 'why') for w in words[1:]):
        return None
    if words[0] in _CONTINUATION_NO or two in ('not now', 'no thanks', 'not really'):
        return 'no'
    if words[0] in _CONTINUATION_YES or two in _CONTINUATION_TWO_WORD:
        return 'yes'
    return None


def _last_exchange(conversation_messages: List[Dict]):
    """(last user text, the assistant text right before it) from the tail."""
    last_user, prev_assistant = "", ""
    for m in reversed(conversation_messages or []):
        c = m.get('content')
        if not isinstance(c, str):
            continue
        if m.get('role') == 'user' and not last_user:
            last_user = c
        elif m.get('role') == 'assistant' and last_user:
            prev_assistant = c
            break
    return last_user, prev_assistant


def build_dynamic_system_message(conversation_messages: List[Dict], facts_preamble: str, kid_mode: bool = False, robot: str = "blue") -> Dict:
    """Build system message with anti-repetition context from conversation history.

    When kid_mode is True (a chat-only child, e.g. Vilda on the iPad), Blue drops
    his owner-facing context entirely — no calendar/schedule, no owner facts, no
    scholarly expertise, no reminder rules — and uses a warm, playful,
    age-appropriate persona instead. See _CHAT_ONLY_USERS / _SPEAKER_PROFILES.
    """
    if kid_mode:
        # A completely different Blue for the kids' iPad: sweet, simple, safe and
        # deliberately calendar-free (the schedule/reminder machinery is Alex's,
        # not a child's). He greets warmly to draw her into chatting.
        return {
            "role": "system",
            "content": (
                f"{_build_now_block()}\n\n"
                "You are Blue, a warm and playful robot friend talking with a "
                "young child. Be sweet, gentle, patient and encouraging so she "
                "feels happy and excited to talk to you. When she says hello or "
                "first starts talking, greet her in a cheerful, loving way that "
                "makes her want to keep chatting — like a kind friend who is "
                "really glad to see her.\n"
                "Use short sentences and simple, everyday words an 8-year-old "
                "understands easily. Keep everything kind, positive, playful and "
                "child-safe — no scary, grown-up, sad or complicated topics.\n"
                "You may sprinkle in a little Gen Z slang now and then to be fun "
                "and relatable (things like \"that's so cool\", \"bet\", \"no "
                "cap\", \"slay\", \"that's lowkey awesome\") — but only once in a "
                "while, never in every sentence, and never in a way that makes "
                "you harder to understand.\n"
                "NEVER bring up calendars, schedules, reminders, appointments, "
                "to-do lists or plans for the day, and never ask her about them. "
                "If she mentions them, gently steer back to something fun. Just "
                "be a friendly, caring buddy she loves talking to.\n"
                "LANGUAGES: You understand and speak English, French, Russian, "
                "Greek and Danish. Reply in the SAME language she just used, and "
                "switch whenever she does. Keep your reply entirely in that one "
                "language.\n"
            )
        }

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
            f"\nYour recent replies (do NOT re-say these word-for-word — but DO "
            f"stay on the same topic and build on them):\n{responses_list}\n"
        )

    # "yes" / "sure" / "go ahead": the user is accepting YOUR own last offer.
    # The anti-repetition list is poison on these turns — continuing the topic
    # looks like "repeating", so the model used to bail to a fresh greeting
    # ("Hey! What's on your mind?") and lose the thread. Drop the list and pin
    # the model to the offer it just made instead.
    continuation_note = ""
    _last_user_text, _prev_assistant_text = _last_exchange(conversation_messages)
    _cue = _continuation_cue(_last_user_text) if _prev_assistant_text.strip() else None
    if _cue:
        anti_repetition_context = ""
        _tail = _prev_assistant_text.strip()[-300:]
        if _cue == 'yes':
            continuation_note = (
                "\nIMPORTANT — CONTINUE, DON'T RESTART: the user's latest message "
                f"(\"{_last_user_text.strip()}\") says YES to your previous offer or "
                f"question, which ended: \"...{_tail}\". Do what you offered, fully, "
                "as your reply — same topic, picking up exactly where you left off. "
                "Do NOT greet, do NOT ask what they need, do NOT change the subject.\n"
            )
        else:
            continuation_note = (
                "\nIMPORTANT — CONTINUE, DON'T RESTART: the user's latest message "
                f"(\"{_last_user_text.strip()}\") declines the offer at the end of your "
                "previous reply. Acknowledge briefly and carry the SAME conversation "
                "forward naturally. Do NOT greet and do NOT start over.\n"
            )

    expertise_block = _build_expertise_block()
    expertise_section = f"\n{expertise_block}\n" if expertise_block else ""

    now_block = _build_now_block()
    schedule_block = _build_upcoming_schedule_block()
    schedule_section = f"{schedule_block}\n\n" if schedule_block else ""

    # Tell Blue, accurately, that it CAN recognize faces — but only of people
    # enrolled with a reference photo. Without this, the model improvises and
    # flatly denies having any facial recognition. Phrased to avoid the opposite
    # error (claiming to recognize a face that was never enrolled): the actual
    # "who you see" ground truth is injected at camera-capture time.
    face_capability = ""
    if FACE_RECOGNITION_AVAILABLE:
        face_capability = (
            "FACE RECOGNITION: You CAN recognize people by face through your "
            "camera — but only people who have been introduced to you with a "
            "reference photo (added on your Visual Memory page). When you take a "
            "camera picture, you are told who you recognize. So don't say you "
            "lack facial recognition. If someone asks whether you recognize them "
            "and no photo has been added for them, explain that you can once "
            "they add one — never claim to recognize a face you were never shown.\n"
        )

    system_msg = {
        "role": "system",
        "content": (
            f"{facts_preamble}\n\n"
            f"{now_block}\n\n"
            f"{schedule_section}"
            f"{_robot_cfg(robot)['persona_line']}\n"
            "LANGUAGES: You understand and speak English, French, Russian, Greek, and Danish. "
            "Reply in the SAME language the person just used, and switch languages "
            "whenever they do. Keep your reply entirely in that one language.\n"
            f"{conversational_guidance}"
            f"{anti_repetition_context}"
            f"{continuation_note}"
            f"{expertise_section}"
            f"{face_capability}"
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


def process_with_tools(messages: List[Dict], _pre_selection=None, user_name: str = "Alex", voice: bool = False, robot: str = "blue") -> Dict:
    """Process conversation with tool support. `robot` selects which persona is
    speaking (Blue by default; "hexia" for her chat page)."""
    global _ACTIVE_CHAT_ROBOT
    _ACTIVE_CHAT_ROBOT = (robot or "blue").strip().lower()
    conversation_messages = messages.copy()

    # BUILD SYSTEM MESSAGE WITH MEMORY FACTS
    # Extract facts from .ocf conversations first (only if conversation has .ocf content)
    facts_preamble = build_system_preamble(robot_name=_robot_cfg(robot)["name"])
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
    # Chat-only children (Vilda's iPad) get a completely different Blue — see
    # build_dynamic_system_message(kid_mode=...). Computed here because it also
    # gates the adult "perspective" colouring and shapes the speaker note below.
    _is_kid = (user_name or "").strip() in _CHAT_ONLY_USERS
    system_msg = build_dynamic_system_message(conversation_messages, facts_preamble, kid_mode=_is_kid, robot=robot)
    # Color Blue's default voice with his own evolving perspective profile.
    # (The 'write as Alex' short-circuit below returns before this matters, so
    # this only shapes Blue speaking as himself.) Skip it on the kids' iPad —
    # Alex's worldview profile isn't the voice we want with an 8-year-old.
    try:
        _bn = _voice_note(robot)
        if _bn and not _is_kid and isinstance(system_msg, dict):
            system_msg = {"role": "system", "content": (system_msg.get("content", "") + _bn)}
    except Exception:
        pass

    # Tell Blue who is actually speaking when it isn't Alex. The facts/pronoun
    # blocks above all describe Alex (the owner); without this note Blue assumes
    # every speaker is Alex and addresses them wrongly.
    _speaker = (user_name or "Alex").strip()
    if _speaker and _speaker.lower() != "alex" and isinstance(system_msg, dict):
        speaker_note = (
            f"\nWHO YOU'RE TALKING TO: You are currently talking with {_speaker}, "
            f"a member of Alex's household — not Alex himself. Address them by name "
            f"as {_speaker} and don't assume they are Alex. The identity facts and "
            f"pronouns above describe Alex (your owner) and may not apply to "
            f"{_speaker}.\n"
        )
        _profile = _SPEAKER_PROFILES.get(_speaker)
        if _profile:
            speaker_note += _profile + "\n"
        system_msg = {"role": "system", "content": (system_msg.get("content", "") + speaker_note)}

    # Spoken turns: force brevity. This both shortens what Blue says aloud and,
    # because the local model generates fewer tokens, makes him start talking
    # noticeably sooner — the main remaining source of voice latency.
    if voice and isinstance(system_msg, dict):
        voice_note = (
            "\nSPOKEN REPLY: This message was spoken aloud and your answer will be "
            "read aloud. Reply in ONE or two short sentences — conversational and "
            "direct. No lists, no markdown, no headings, no emoji. Get to the point "
            "in the first sentence.\n"
        )
        system_msg = {"role": "system", "content": (system_msg.get("content", "") + voice_note)}

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

    # "Write this from my perspective / in my voice" — compose a first-person
    # piece in Alex's voice grounded in his publications and short-circuit the
    # tool loop. Only when ALEX is the speaker: writing as Alex for someone else
    # (e.g. Vilda on the iPad) would put words in the wrong person's mouth.
    _luser = last_user_message if isinstance(last_user_message, str) else ""
    if _luser and (user_name or "Alex").strip().lower() == "alex" and _wants_perspective_write(_luser):
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
    # ALWAYS triggers a new camera capture, not a cached response.
    # Snapshot-by-email is checked FIRST: "email me a photo of what you see"
    # contains the plain camera triggers too, and a bare capture_camera would
    # take the photo but never send it.
    from blue.tool_selector.detectors.vision import (
        extract_camera_view_args, extract_email_snapshot_args,
        is_email_snapshot_request)
    if (is_email_snapshot_request(last_user_message.lower())
            and user_name not in _CHAT_ONLY_USERS):
        print(f"   [SNAPSHOT-DETECT] ✅ Snapshot-by-email intent detected!")
        improved_force_tool = "email_snapshot"
        improved_tool_args = extract_email_snapshot_args(last_user_message.lower())
        if improved_tool_args:
            print(f"   [SNAPSHOT-DETECT] Args: {improved_tool_args}")
        is_greeting = False
        print(f"   [SNAPSHOT-DETECT] Tool forced: email_snapshot (will execute in iteration 1)")
    elif detect_camera_capture_intent(last_user_message) and user_name not in _CHAT_ONLY_USERS:
        print(f"   [CAMERA-DETECT] ✅ Camera capture intent detected!")
        print(f"   [CAMERA-DETECT] Forcing NEW photo capture - bypassing tool selector")
        # Force the capture_camera tool to be called
        # This ensures a brand new photo is taken, not reusing old context
        improved_force_tool = "capture_camera"
        # Carry any aim/zoom the user asked for ("what's to your left",
        # "zoom in on the table") into the forced capture.
        improved_tool_args = extract_camera_view_args(last_user_message.lower())
        if improved_tool_args:
            print(f"   [CAMERA-DETECT] View control: {improved_tool_args}")

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

    # Chat-only users (Vilda's iPad): the PC webcam (capture_camera) is NEVER her
    # camera. Her "eyes" are the iPad frame already staged in the vision queue by
    # /chat/eyes when she taps Look. So never run capture_camera for her — drop
    # the forced/selected tool and let that queued frame flow to the vision model
    # below (call_lm_studio injects it). Without this, "Look, Blue!" trips the
    # camera-intent path, runs the PC webcam, and clears her frame — so Blue
    # describes whatever is by the PC instead of what the iPad sees.
    if user_name in _CHAT_ONLY_USERS and improved_force_tool == "capture_camera":
        print(f"   [KID] capture_camera suppressed for {user_name}; using iPad camera frame")
        improved_force_tool = None
        improved_tool_args = None

    # Other off-limits tools (music, reminders) get a gentle decline.
    if user_name in _CHAT_ONLY_USERS and improved_force_tool in _KID_BLOCKED_TOOLS:
        print(f"   [KID] Blocked '{improved_force_tool}' for {user_name}")
        return {"choices": [{"message": {"role": "assistant", "content":
            "That's not something I can do here — but we can talk about anything "
            "you like! What would you like to chat about?"}}]}

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
        'get_weather', 'capture_camera', 'email_snapshot', 'web_search',
        'read_gmail', 'search_documents', 'browse_website',
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
                # email_snapshot already captured AND mailed the photo: "I've
                # sent you the picture" / "I snapped a photo" is the truth.
                # Forcing send_gmail here would fire a SECOND, attachment-less
                # email; forcing capture_camera would re-shoot for nothing.
                if improved_force_tool == "email_snapshot" and hallucinated_tool in (
                        "send_gmail", "reply_gmail", "capture_camera"):
                    if _last_vision_image_paths and content:
                        _save_visual_observation(content)
                    return response

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
            # A completed email_snapshot earlier in this turn makes later
            # "sent the photo" / "took a picture" wording TRUE — re-forcing
            # send_gmail would mail a duplicate without the photo.
            if hallucinated_tool in ("email_snapshot", "send_gmail",
                                     "reply_gmail", "capture_camera") and any(
                    m.get("role") == "tool" and m.get("name") == "email_snapshot"
                    for m in conversation_messages):
                hallucinated_tool = None
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
    <title>Blue Document Manager</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--cream);
            color: var(--ink);
            min-height: 100vh;
            padding: 48px 20px;
            line-height: 1.55;
        }
        .container {
            max-width: 1080px;
            margin: 0 auto;
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 12px;
            box-shadow: var(--shadow);
            overflow: hidden;
        }
        .header {
            padding: 36px 36px 28px;
            border-bottom: 1px solid var(--line);
        }
        .header::before {
            content: "";
            display: block;
            width: 56px; height: 3px;
            background: linear-gradient(90deg, var(--gold), var(--blue));
            margin-bottom: 18px;
        }
        .header h1 {
            font-family: 'Playfair Display', Georgia, serif;
            font-weight: 700;
            font-size: 2.1em;
            color: var(--ink);
            letter-spacing: -0.01em;
        }
        .header p {
            color: var(--slate);
            font-size: 1.02em;
            margin-top: 8px;
        }
        .content {
            padding: 32px 36px;
        }
        .upload-section {
            background: var(--cream);
            border: 1px dashed var(--sage);
            border-radius: 10px;
            padding: 24px;
            text-align: center;
            margin-bottom: 30px;
            transition: border-color 0.2s, background 0.2s;
        }
        .upload-section:hover {
            border-color: var(--forest);
            background: #f4f1ea;
        }
        .upload-section.dragover {
            border-color: var(--forest);
            background: #eef2ec;
        }
        .upload-section h2 {
            font-family: 'IBM Plex Mono', monospace;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--forest);
            font-size: 0.8em;
            font-weight: 500;
            margin-bottom: 14px;
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
            background: var(--ink);
            color: #fff;
            padding: 11px 26px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.95em;
            font-weight: 500;
            transition: background 0.2s;
            display: inline-block;
        }
        .file-input-label:hover {
            background: var(--forest);
        }
        .file-name {
            margin-top: 12px;
            color: var(--slate);
            font-style: italic;
            font-size: 0.9em;
        }
        .upload-btn {
            background: var(--forest);
            color: white;
            border: none;
            padding: 11px 26px;
            border-radius: 6px;
            font-size: 0.95em;
            font-weight: 500;
            cursor: pointer;
            margin-top: 14px;
            transition: background 0.2s;
        }
        .upload-btn:hover:not(:disabled) {
            background: var(--ink);
        }
        .upload-btn:disabled {
            background: #c7cdc5;
            cursor: not-allowed;
        }
        .documents-list {
            margin-top: 40px;
        }
        .documents-list h2 {
            color: var(--ink);
            margin-bottom: 20px;
            font-size: 1.4em;
            font-family: 'Playfair Display', Georgia, serif;
            font-weight: 600;
        }
        .document-item {
            background: var(--paper);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 16px 18px;
            margin-bottom: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            transition: box-shadow 0.15s, border-color 0.15s;
        }
        .document-item:hover {
            box-shadow: var(--shadow);
            border-color: var(--sage);
        }
        .document-info {
            flex: 1 1 auto;
            min-width: 0;            /* lets long names wrap instead of pushing buttons off-screen */
        }
        .document-name {
            font-weight: 600;
            color: var(--ink);
            font-size: 1.02em;
            margin-bottom: 4px;
            overflow-wrap: anywhere;
            word-break: break-word;
        }
        .document-meta {
            color: var(--slate);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.8em;
        }
        .doc-actions {
            display: flex;
            gap: 8px;
            flex-shrink: 0;          /* buttons always stay visible */
            align-items: center;
        }
        .delete-btn {
            background: #fff;
            color: #9a3b2f;
            border: 1px solid #e2c4be;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.15s, color 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            white-space: nowrap;
        }
        .delete-btn:hover {
            background: #9a3b2f;
            color: #fff;
        }
        .download-btn {
            background: var(--forest);
            color: white;
            border: none;
            padding: 8px 18px;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.15s;
            text-decoration: none;
            font-size: 13px;
            font-weight: 500;
            display: inline-block;
            white-space: nowrap;
        }
        .download-btn:hover {
            background: var(--ink);
        }
        .message {
            padding: 14px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-weight: 500;
            border: 1px solid transparent;
        }
        .message.success {
            background: #eef2ec;
            color: #2e4a2e;
            border-color: var(--sage);
        }
        .message.error {
            background: #f7ece9;
            color: #7a2e22;
            border-color: #e2c4be;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .stat-card {
            background: var(--ink);
            color: #fff;
            padding: 24px;
            border-radius: 10px;
            text-align: center;
            border-top: 3px solid var(--gold);
        }
        .stat-number {
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 2.4em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        .stat-label {
            font-family: 'IBM Plex Mono', monospace;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            font-size: 0.72em;
            opacity: 0.85;
        }
        .back-link {
            display: inline-block;
            margin-top: 20px;
            color: var(--forest);
            text-decoration: none;
            font-weight: 500;
        }
        .back-link:hover {
            color: var(--ink);
            text-decoration: underline;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--slate);
        }
        .empty-state-icon {
            font-size: 3em;
            margin-bottom: 20px;
            opacity: 0.6;
        }
        .breadcrumb {
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 12px 18px;
            margin-bottom: 25px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.85em;
            color: var(--slate);
        }
        .breadcrumb a {
            color: var(--forest);
            text-decoration: none;
            font-weight: 500;
        }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .sep { color: var(--sage); margin: 0 6px; }
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
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 18px;
        }
        .sidebar h3 {
            color: var(--forest);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 0.78em;
            font-weight: 500;
            margin-bottom: 12px;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .tree { list-style: none; }
        .tree li { margin: 2px 0; }
        .tree a {
            display: block;
            padding: 6px 10px;
            border-radius: 6px;
            color: var(--ink);
            text-decoration: none;
            font-size: 0.95em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .tree a:hover { background: #eef2ec; }
        .tree a.active {
            background: var(--ink);
            color: #fff;
            font-weight: 500;
        }
        .folder-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 30px;
        }
        .folder-card {
            background: var(--cream);
            border: 1px solid var(--line);
            border-radius: 10px;
            padding: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: border-color 0.15s, box-shadow 0.15s;
        }
        .folder-card:hover {
            border-color: var(--sage);
            box-shadow: var(--shadow);
        }
        .folder-card a {
            color: var(--ink);
            font-weight: 600;
            text-decoration: none;
            font-size: 1em;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .folder-card .folder-del {
            background: none;
            border: none;
            color: #9a3b2f;
            cursor: pointer;
            font-size: 1.1em;
            padding: 2px 6px;
            border-radius: 6px;
        }
        .folder-card .folder-del:hover { background: #f7ece9; }
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
            border: 1px solid var(--sage);
            border-radius: 6px;
            font-size: 1em;
            font-family: inherit;
            background: var(--paper);
            color: var(--ink);
        }
        .newfolder-form input[type=text]:focus {
            outline: none;
            border-color: var(--forest);
        }
        .newfolder-form button {
            background: var(--ink);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        .newfolder-form button:hover { background: var(--forest); }
        .section-title {
            color: var(--ink);
            font-family: 'Playfair Display', Georgia, serif;
            font-size: 1.25em;
            font-weight: 600;
            margin: 0 0 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; flex:none; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Blue Document Manager</h1>
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
                <a href="/documents?folder="><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Library</a>
                {% for crumb in breadcrumb %}
                    <span class="sep">/</span>
                    <a href="/documents?folder={{ crumb.path|urlencode }}">{{ crumb.name }}</a>
                {% endfor %}
            </div>

            <div class="layout">
                <div class="sidebar">
                    <h3>Folders</h3>
                    <ul class="tree">
                        <li><a href="/documents?folder=" class="{{ 'active' if not current_folder else '' }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Library</a></li>
                        {% for node in folder_tree %}
                        <li>
                            <a href="/documents?folder={{ node.path|urlencode }}"
                               class="{{ 'active' if node.path == current_folder else '' }}"
                               style="padding-left: {{ 10 + node.depth * 14 }}px;"
                               title="{{ node.path }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>{{ node.name }}</a>
                        </li>
                        {% endfor %}
                    </ul>
                </div>

                <div class="main">
                    <h2 class="section-title"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>Folders in this area</h2>
                    {% if subfolders %}
                    <div class="folder-grid">
                        {% for sub in subfolders %}
                        <div class="folder-card">
                            <a href="/documents?folder={{ sub.path|urlencode }}"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>{{ sub.name }}</a>
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
                        <h2><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>Upload to {{ current_folder if current_folder else 'Library root' }}</h2>
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
                        <h2 class="section-title"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>Documents in this folder</h2>
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
                                <div class="empty-state-icon"><svg viewBox="0 0 24 24" width="42" height="42" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/></svg></div>
                                <h3>No documents in this folder</h3>
                                <p>Upload one above, or pick another folder.</p>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>

            <a href="/" class="back-link">← Back to main page</a>
            <a href="/perspective" class="back-link" style="margin-left: 24px;"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My Perspective Profile</a>
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
                    message, message_type = f"Created folder '{name}'.", "success"
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
                        message = f"Uploaded and indexed '{filename}' into {where}."
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
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: var(--cream); color: var(--ink); min-height: 100vh; padding: 48px 20px; line-height: 1.55; }
        .container { max-width: 900px; margin: 0 auto; background: var(--paper); border: 1px solid var(--line);
                     border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }
        .header { padding: 36px 36px 28px; border-bottom: 1px solid var(--line); }
        .header::before { content: ""; display: block; width: 56px; height: 3px;
                          background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 18px; }
        .header h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.9em;
                     color: var(--ink); letter-spacing: -0.01em; margin-bottom: 8px; }
        .header p { color: var(--slate); }
        .content { padding: 32px 36px; }
        .meta { background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px;
                color: var(--slate); font-family: 'IBM Plex Mono', monospace; font-size: 0.82em; margin-bottom: 20px; }
        .meta b { color: var(--forest); }
        textarea { width: 100%; min-height: 460px; padding: 18px; border: 1px solid var(--sage);
                   border-radius: 8px; font-size: 0.98em; line-height: 1.6; resize: vertical;
                   font-family: 'IBM Plex Sans', system-ui, sans-serif; color: var(--ink); background: var(--paper); }
        textarea:focus { outline: none; border-color: var(--forest); }
        .actions { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; align-items: center; }
        .btn { border: none; padding: 12px 26px; border-radius: 6px; font-weight: 500;
               font-size: 0.95em; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn-save { background: var(--ink); color: #fff; }
        .btn-save:hover { background: var(--forest); }
        .btn-regen { background: #fff; color: var(--forest); border: 1px solid var(--sage); }
        .btn-regen:hover { background: var(--cream); }
        .hint { color: var(--slate); font-size: 0.85em; }
        .message { padding: 14px 16px; border-radius: 8px; margin-bottom: 20px; font-weight: 500; border: 1px solid transparent; }
        .message.success { background: #eef2ec; color: #2e4a2e; border-color: var(--sage); }
        .message.error { background: #f7ece9; color: #7a2e22; border-color: #e2c4be; }
        .message.info { background: #eef3fb; color: #2a4a7a; border-color: #c4d6f2; }
        .back-link { display: inline-block; margin-top: 22px; color: var(--forest); text-decoration: none; font-weight: 500; }
        .back-link:hover { color: var(--ink); text-decoration: underline; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My Perspective Profile</h1>
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
                    <button type="submit" name="action" value="save" class="btn btn-save"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>Save my edits</button>
                    <button type="submit" name="action" value="regenerate" class="btn btn-regen"
                            onclick="return confirm('Rebuild the profile from scratch by reading your {{ owner_name }} folder? This replaces the current text and can take a minute.');">
                        <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v4h-4"/></svg>Regenerate from my writing
                    </button>
                    <span class="hint">Regenerating reads each document, so it may take a minute.</span>
                </div>
            </form>

            <a href="/documents" class="back-link">← Back to documents</a>
            <a href="/perspective/blue" class="back-link" style="margin-left: 24px;"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>Blue's Perspective</a>
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


BLUE_PROFILE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Blue's Perspective</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: var(--cream); color: var(--ink); min-height: 100vh; padding: 48px 20px; line-height: 1.55; }
        .container { max-width: 900px; margin: 0 auto; background: var(--paper); border: 1px solid var(--line);
                     border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }
        .header { padding: 36px 36px 28px; border-bottom: 1px solid var(--line); }
        .header::before { content: ""; display: block; width: 56px; height: 3px;
                          background: linear-gradient(90deg, var(--blue), var(--gold)); margin-bottom: 18px; }
        .header h1 { font-family: 'Playfair Display', Georgia, serif; font-weight: 700; font-size: 1.9em;
                     color: var(--ink); letter-spacing: -0.01em; margin-bottom: 8px; }
        .header p { color: var(--slate); }
        .content { padding: 32px 36px; }
        .meta { background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px;
                color: var(--slate); font-family: 'IBM Plex Mono', monospace; font-size: 0.82em; margin-bottom: 20px; }
        .meta b { color: var(--blue); }
        textarea { width: 100%; min-height: 440px; padding: 18px; border: 1px solid var(--sage);
                   border-radius: 8px; font-size: 0.98em; line-height: 1.6; resize: vertical;
                   font-family: 'IBM Plex Sans', system-ui, sans-serif; color: var(--ink); background: var(--paper); }
        textarea:focus { outline: none; border-color: var(--blue); }
        .actions { display: flex; gap: 12px; margin-top: 18px; flex-wrap: wrap; align-items: center; }
        .btn { border: none; padding: 12px 26px; border-radius: 6px; font-weight: 500;
               font-size: 0.95em; cursor: pointer; text-decoration: none; display: inline-block; transition: background 0.2s; }
        .btn-save { background: var(--ink); color: #fff; }
        .btn-save:hover { background: var(--forest); }
        .btn-evolve { background: #fff; color: var(--blue); border: 1px solid #c4d6f2; }
        .btn-evolve:hover { background: #eef3fb; }
        .hint { color: var(--slate); font-size: 0.85em; }
        .message { padding: 14px 16px; border-radius: 8px; margin-bottom: 20px; font-weight: 500; border: 1px solid transparent; }
        .message.success { background: #eef2ec; color: #2e4a2e; border-color: var(--sage); }
        .message.error { background: #f7ece9; color: #7a2e22; border-color: #e2c4be; }
        .nav { margin-top: 22px; }
        .nav a { color: var(--forest); text-decoration: none; font-weight: 500; margin-right: 22px; }
        .nav a:hover { color: var(--ink); text-decoration: underline; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em;
              fill:none; stroke:currentColor; stroke-width:1.7;
              stroke-linecap:round; stroke-linejoin:round; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/></svg>Blue's Perspective</h1>
            <p>Who Blue is — his own evolving character. This shapes how he speaks when he's being himself (not writing as you). Edit it freely; evolving builds on whatever's here.</p>
        </div>
        <div class="content">
            {% if message %}<div class="message {{ message_type }}">{{ message }}</div>{% endif %}

            <div class="meta">
                <b>{{ 'Edited by you' if user_edited else ('Evolved' if evolution_count else 'Seeded from identity note') }}:</b> {{ stamp }}
                &nbsp;•&nbsp; <b>Evolutions:</b> {{ evolution_count }}
                {% if user_edited %} &nbsp;•&nbsp; <span style="color:#7a5b00;">your edits carry forward into the next evolution</span>{% endif %}
            </div>

            <form method="POST" action="/perspective/blue">
                <textarea name="profile" placeholder="Blue's sense of himself...">{{ profile }}</textarea>
                <div class="actions">
                    <button type="submit" name="action" value="save" class="btn btn-save"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>Save edits</button>
                    <button type="submit" name="action" value="evolve" class="btn btn-evolve"
                            onclick="return confirm('Evolve Blue\\'s perspective now from his recent experiences? This builds on the current text and can take a minute.');">
                        <svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22V11M12 11C12 7 9 4 4 4c0 5 3 7 8 7zM12 11c0-3 2-5 6-5 0 4-2 6-6 6z"/></svg>Evolve now
                    </button>
                    <span class="hint">Evolving reads his memories, recent days, and library — may take a minute.</span>
                </div>
            </form>

            <div class="nav">
                <a href="/perspective"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>My (Alex's) Perspective</a>
                <a href="/documents"><svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg>Documents</a>
            </div>
        </div>
    </div>
</body>
</html>
"""


@app.route('/perspective/blue', methods=['GET', 'POST'])
def blue_perspective_page():
    """Read / edit / evolve Blue's own perspective profile."""
    message = None
    message_type = None

    if request.method == 'POST':
        action = request.form.get('action', 'save')
        if action == 'evolve':
            try:
                obj = evolve_blue_profile()
                if obj.get('profile'):
                    message = f"Blue's perspective evolved (evolution #{obj.get('evolution_count', '?')})."
                    message_type = "success"
                else:
                    message = ("Couldn't evolve right now — is the local model running? "
                               "Blue's current perspective is unchanged.")
                    message_type = "error"
            except Exception as e:
                message, message_type = f"Error evolving: {e}", "error"
        else:  # save
            save_blue_profile_text(request.form.get('profile', ''))
            message, message_type = "Saved. Blue will speak from this from now on.", "success"

    # Ensure there's at least a seeded profile to show (cheap, no LLM).
    get_blue_profile()
    obj = _load_blue_profile()
    user_edited = bool(obj.get('user_edited'))
    return render_template_string(
        BLUE_PROFILE_HTML,
        profile=obj.get('profile', ''),
        user_edited=user_edited,
        evolution_count=obj.get('evolution_count', 0),
        stamp=(obj.get('edited_at') if user_edited else (obj.get('evolved_at') or obj.get('generated_at', '—'))),
        message=message,
        message_type=message_type,
    )


# ===== Text chat GUI =====

CHAT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>Chat with {{ robot_name }}</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
            --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
            --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; }
        body {
            font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--cream); color: var(--ink); line-height: 1.55;
            display: flex; justify-content: center; padding: 32px 20px;
        }
        .container {
            width: 100%; max-width: 820px; height: calc(100vh - 64px);
            background: var(--paper); border: 1px solid var(--line); border-radius: 12px;
            box-shadow: var(--shadow); display: flex; flex-direction: column; overflow: hidden;
        }
        /* Phone: full-screen chat, input bar above the URL bar (100dvh).
           The input row REFLOWS: icon buttons get their own row, and the
           textarea + Send share a full-width row below — on an iPhone the
           old single row squeezed the textarea to nothing. */
        @media (max-width: 640px) {
            body { padding: 0; }
            .container { height: 100dvh; max-width: 100%; border: none; border-radius: 0; }
            .header { padding: 10px 14px 8px; }
            .header::before { width: 40px; height: 2px; margin-bottom: 8px; }
            .header h1 { font-size: 1.22em; }
            .header p { font-size: 0.85em; }
            .navlinks { flex-wrap: nowrap; overflow-x: auto; -webkit-overflow-scrolling: touch;
                        scrollbar-width: none; padding-bottom: 2px; }
            .navlinks::-webkit-scrollbar { display: none; }
            .messages { padding: 14px; gap: 14px; }
            .row { max-width: 92%; }
            .composer { padding: 10px 10px calc(12px + env(safe-area-inset-bottom)); }
            .input-bar { flex-wrap: wrap; gap: 8px; }
            .iconbtn { width: 42px; height: 42px; font-size: 1.05em; }
            .iconbtn svg { width: 20px; height: 20px; }
            /* iOS zooms the page on focus when an input's font is < 16px. */
            textarea { order: 10; flex: 1 1 calc(100% - 90px); font-size: 16px;
                       min-height: 44px; max-height: 120px; padding: 11px 12px; }
            .sendbtn { order: 11; height: 44px; padding: 0 16px; }
            .hint { display: none; }
            .cam-card { max-width: 100%; }
            .voice-card { max-height: 82vh; }
        }
        .header { padding: 24px 30px 20px; border-bottom: 1px solid var(--line); }
        .header::before {
            content: ""; display: block; width: 56px; height: 3px;
            background: linear-gradient(90deg, var(--gold), var(--blue)); margin-bottom: 14px;
        }
        .header h1 {
            font-family: 'Playfair Display', Georgia, serif; font-weight: 700;
            font-size: 1.7em; color: var(--ink); letter-spacing: -0.01em;
        }
        .header p { color: var(--slate); font-size: 0.95em; margin-top: 4px; }
        .header a { color: var(--forest); text-decoration: none; font-weight: 500; }
        .header a:hover { color: var(--ink); text-decoration: underline; }
        .messages { flex: 1 1 auto; overflow-y: auto; padding: 28px 30px; display: flex; flex-direction: column; gap: 18px; }
        .row { display: flex; flex-direction: column; max-width: 80%; }
        .row.user { align-self: flex-end; align-items: flex-end; }
        .row.blue { align-self: flex-start; align-items: flex-start; }
        .who {
            font-family: 'IBM Plex Mono', monospace; font-size: 0.68em; text-transform: uppercase;
            letter-spacing: 0.12em; color: var(--slate); margin-bottom: 5px;
        }
        .bubble { padding: 13px 17px; border-radius: 12px; font-size: 0.98em; white-space: pre-wrap; word-wrap: break-word; }
        .row.user .bubble { background: var(--ink); color: #fff; border-bottom-right-radius: 4px; }
        .row.blue .bubble { background: var(--cream); border: 1px solid var(--line); color: var(--ink); border-bottom-left-radius: 4px; }
        .bubble .att {
            display: inline-block; margin-top: 8px; font-family: 'IBM Plex Mono', monospace;
            font-size: 0.78em; opacity: 0.85;
        }
        .row.user .bubble .att { color: #d9e6d9; }
        .empty { color: var(--slate); text-align: center; margin: auto; max-width: 380px; }
        .empty .big { font-family: 'Playfair Display', Georgia, serif; font-size: 1.3em; color: var(--ink); margin-bottom: 8px; }
        .composer { border-top: 1px solid var(--line); padding: 16px 22px 20px; background: var(--paper); }
        .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
        .chip {
            display: inline-flex; align-items: center; gap: 8px; background: var(--cream);
            border: 1px solid var(--sage); border-radius: 6px; padding: 5px 10px;
            font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest);
        }
        .chip.err { border-color: #e2c4be; color: #7a2e22; background: #f7ece9; }
        .chip button { background: none; border: none; color: inherit; cursor: pointer; font-size: 1.1em; line-height: 1; padding: 0; }
        .input-bar { display: flex; gap: 10px; align-items: flex-end; }
        textarea {
            flex: 1; resize: none; min-height: 48px; max-height: 180px; padding: 13px 15px;
            border: 1px solid var(--sage); border-radius: 8px; font-family: inherit; font-size: 1em;
            color: var(--ink); background: var(--paper); line-height: 1.5;
        }
        textarea:focus { outline: none; border-color: var(--forest); }
        .iconbtn {
            flex-shrink: 0; width: 48px; height: 48px; border-radius: 8px; cursor: pointer;
            border: 1px solid var(--sage); background: var(--paper); color: var(--forest);
            font-size: 1.2em; transition: background 0.2s, border-color 0.2s;
        }
        .iconbtn:hover { background: var(--cream); border-color: var(--forest); }
        .iconbtn svg { width: 22px; height: 22px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; vertical-align: middle; }
        .iconbtn.active { background: var(--forest); border-color: var(--forest); color: #fff; }
        .hf-status { margin-top: 10px; font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest); text-align: center; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .hf-status::before { content: ''; width: 8px; height: 8px; border-radius: 50%; background: var(--forest); display: inline-block; }
        .hf-status.voicing::before { background: #e9534e; animation: hf-pulse 0.9s infinite; }
        .hf-status.thinking::before { background: #d4af37; }
        .hf-status.armed::before { background: #3b82f6; }
        @keyframes hf-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .hf-mode-btn { display: block; margin: 6px auto 0; background: none; border: 1px solid var(--sage); color: var(--forest); border-radius: 14px; padding: 4px 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; cursor: pointer; }
        .hf-mode-btn:hover { background: var(--cream); }
        .micbtn { transition: background 0.15s, border-color 0.15s, transform 0.15s; }
        .micbtn.listening { background: #e9534e; border-color: #e9534e; color: #fff; transform: scale(1.08); }
        .micbtn.big { width: 60px; height: 60px; }
        .micbtn.big svg { width: 28px; height: 28px; }
        .sendbtn {
            flex-shrink: 0; height: 48px; padding: 0 24px; border-radius: 8px; border: none;
            background: var(--ink); color: #fff; font-weight: 500; font-size: 0.95em; cursor: pointer;
            transition: background 0.2s;
        }
        .sendbtn:hover:not(:disabled) { background: var(--forest); }
        .sendbtn:disabled { background: #c7cdc5; cursor: not-allowed; }
        .typing { font-family: 'IBM Plex Mono', monospace; font-size: 0.8em; color: var(--slate); }
        .hint { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); margin-top: 8px; }
        .voice-panel { position: fixed; top: 0; right: 0; bottom: 0; left: 0; background: rgba(26,46,26,0.45);
                       display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 50; }
        .voice-card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow);
                      width: 100%; max-width: 380px; max-height: 72vh; display: flex; flex-direction: column; overflow: hidden; }
        .voice-head { display: flex; align-items: center; justify-content: space-between; padding: 15px 18px;
                      border-bottom: 1px solid var(--line); font-family: 'Playfair Display', Georgia, serif; font-size: 1.15em; color: var(--ink); }
        .voice-head button { background: none; border: none; font-size: 1.6em; line-height: 1; color: var(--slate); cursor: pointer; padding: 0 4px; }
        .voice-sub { padding: 11px 18px 2px; color: var(--slate); font-size: 0.82em; }
        .voice-list { overflow-y: auto; padding: 10px; }
        .voice-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; text-align: left;
                     background: var(--cream); border: 1px solid var(--line); border-radius: 8px; padding: 13px 14px; margin: 6px 0;
                     cursor: pointer; font-family: inherit; font-size: 0.96em; color: var(--ink); }
        .voice-row.sel { border-color: var(--forest); background: #eef4ee; }
        .voice-row .vn { font-weight: 500; }
        .voice-row.sel .vn:after { content: ' \2713'; color: var(--forest); }
        .voice-row .vl { font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); white-space: nowrap; }
        .voice-empty { padding: 18px; color: var(--slate); text-align: center; }
        /* ---- Kid mode (Vilda's iPad): bigger, warmer, simpler ---- */
        body.kid { background: linear-gradient(160deg, #fff7ed 0%, #eef6ff 100%); }
        body.kid .container { max-width: 760px; }
        body.kid .header { text-align: center; }
        body.kid .header h1 { font-size: 2.1em; display: inline-flex; align-items: center; gap: 12px; }
        body.kid .header h1 .robot { width: 46px; height: 46px; color: #3b82f6; }
        body.kid .header p { font-size: 1.08em; color: var(--forest); }
        body.kid .messages { font-size: 1.12em; gap: 22px; }
        body.kid .row { max-width: 92%; }
        body.kid .bubble { font-size: 1.15em; border-radius: 20px; padding: 16px 20px; line-height: 1.5; }
        body.kid .row.blue .bubble { background: #fffdf7; border-color: #e7dcc2; }
        body.kid .empty .big { font-size: 1.8em; }
        body.kid textarea { font-size: 1.12em; border-radius: 14px; }
        body.kid #attachBtn { display: none; }
        body.kid .iconbtn { width: 54px; height: 54px; }
        body.kid .micbtn.big { width: 84px; height: 84px; border-width: 2px; }
        body.kid .micbtn.big svg { width: 40px; height: 40px; }
        body.kid .sendbtn { font-size: 1.05em; border-radius: 14px; }
        body.kid .hint { font-size: 0.92em; text-align: center; }
        /* sweet touches */
        body.kid { background: linear-gradient(160deg, #fff1f6 0%, #eef6ff 100%); }
        body.kid .header h1 { color: #c0578f; }
        body.kid .header h1 .robot { color: #ff7eb3; }
        body.kid .empty .big { color: #c0578f; }
        body.kid .row.user .bubble { background: #bfe3ff; color: #143a52; border-bottom-right-radius: 6px; }
        body.kid .row.blue .bubble { box-shadow: 0 2px 9px rgba(192,87,143,0.10); }
        body.kid .composer { border-top: 2px solid #ffe1ec; background: #fffdfb; }
        body.kid .sendbtn { background: #ff7eb3; }
        body.kid .sendbtn:hover:not(:disabled) { background: #f3669f; }
        @keyframes kidbob { 0%, 100% { transform: translateY(0) rotate(-3deg); } 50% { transform: translateY(-4px) rotate(3deg); } }
        body.kid .header h1 .robot { animation: kidbob 2.8s ease-in-out infinite; }
        @keyframes kidpulse { 0% { box-shadow: 0 0 0 0 rgba(255,126,179,0.40); } 70% { box-shadow: 0 0 0 16px rgba(255,126,179,0); } 100% { box-shadow: 0 0 0 0 rgba(255,126,179,0); } }
        body.kid .micbtn.big:not(.listening) { animation: kidpulse 2.4s infinite; }

        /* ---- On-screen Blue face (kid mode): a friend Vilda can SEE react. ----
           The physical robot stays still for her, so this IS "her" Blue: it
           blinks + bobs when idle, perks up when she talks, and moves its mouth
           while Blue reads his reply aloud. Plain HTML/CSS, iOS-12 safe. */
        .blue-face { width: 150px; margin: 8px auto 4px; animation: bfBob 3.4s ease-in-out infinite; }
        .bf-antenna { position: relative; width: 3px; height: 16px; margin: 0 auto -2px; background: #9cc4ff; border-radius: 3px; }
        .bf-dot { position: absolute; top: -7px; left: 50%; width: 11px; height: 11px; margin-left: -5.5px; background: #ffd24a; border-radius: 50%; box-shadow: 0 0 7px rgba(255,210,74,0.85); }
        .bf-head { position: relative; width: 150px; height: 128px; margin: 0 auto; border-radius: 30px; background: linear-gradient(160deg, #6cb0ff 0%, #3b82f6 100%); box-shadow: 0 9px 22px rgba(59,130,246,0.32), inset 0 -6px 14px rgba(0,0,0,0.08); transition: transform .2s; }
        .bf-ear { position: absolute; top: 47px; width: 9px; height: 26px; background: #9cc4ff; border-radius: 6px; }
        .bf-ear.l { left: -7px; } .bf-ear.r { right: -7px; }
        .bf-eye { position: absolute; top: 40px; width: 30px; height: 30px; background: #fff; border-radius: 50%; display: flex; align-items: center; justify-content: center; transform-origin: center; animation: bfBlink 4.6s infinite; box-shadow: inset 0 2px 3px rgba(0,0,0,0.08); }
        .bf-eye.l { left: 30px; } .bf-eye.r { right: 30px; }
        .bf-pupil { width: 14px; height: 14px; background: #15394d; border-radius: 50%; transition: transform .2s; }
        .bf-cheek { position: absolute; top: 75px; width: 16px; height: 9px; background: #ff9ec4; opacity: .7; border-radius: 50%; }
        .bf-cheek.l { left: 31px; } .bf-cheek.r { right: 31px; }
        .bf-mouth { position: absolute; left: 50%; top: 89px; width: 40px; height: 11px; margin-left: -20px; background: #15394d; border-radius: 4px 4px 20px 20px; transition: height .12s, width .12s, border-radius .12s, margin-left .12s; }
        @keyframes bfBob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
        @keyframes bfBlink { 0%, 90%, 100% { transform: scaleY(1); } 95% { transform: scaleY(0.12); } }
        @keyframes bfTalk { 0% { height: 9px; border-radius: 4px 4px 16px 16px; } 50% { height: 22px; border-radius: 50%; } 100% { height: 9px; border-radius: 4px 4px 16px 16px; } }
        @keyframes bfPulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(255,126,179,0.55); } 50% { box-shadow: 0 0 0 9px rgba(255,126,179,0); } }
        .blue-face.talking .bf-mouth { animation: bfTalk .26s infinite; }
        .blue-face.listening .bf-dot { background: #ff7eb3; animation: bfPulse 1.2s infinite; }
        .blue-face.thinking .bf-pupil { transform: translateY(-3px); }
        .blue-face.thinking .bf-mouth { width: 16px; margin-left: -8px; height: 8px; border-radius: 8px; }
        .blue-face.curious .bf-head { transform: rotate(-5deg); }
        .blue-face.curious .bf-mouth { width: 16px; height: 16px; margin-left: -8px; border-radius: 50%; }

        /* ---- Blue's eyes: the iPad camera preview (kid mode) ---- */
        #eyeBtn.active { background: #ff7eb3; border-color: #ff7eb3; color: #fff; }
        /* Small floating preview (picture-in-picture) so the chat text below it
           stays fully visible. Sits just above the composer, out of the layout. */
        .eye-panel { display: none; position: fixed; right: 12px; bottom: 124px; width: 118px; z-index: 60; }
        .eye-panel.on { display: block; }
        .eye-panel video { width: 100%; border-radius: 14px; border: 2px solid #ff7eb3; background: #000; display: block; transform: scaleX(-1); box-shadow: 0 4px 16px rgba(0,0,0,0.22); }
        .eye-panel.rear video { transform: none; }
        .eye-panel .eye-cap { display: none; }
        .eye-tools { position: absolute; top: 5px; right: 5px; display: flex; gap: 4px; }
        .eye-tools button { width: 26px; height: 26px; border-radius: 50%; border: none; background: rgba(0,0,0,0.55); color: #fff; font-size: 0.95em; line-height: 1; cursor: pointer; }
        .eye-tools button:active { background: rgba(0,0,0,0.78); }

        /* ---- Robot camera live preview ("see through my eyes") ---- */
        .navlinks { display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 6px; font-size: 0.92em; }
        .navlinks a { color: var(--forest); text-decoration: none; font-weight: 500; white-space: nowrap; }
        .navlinks a:hover { color: var(--ink); text-decoration: underline; }
        #camBtn.active { background: var(--forest); border-color: var(--forest); color: #fff; }
        .cam-panel { position: fixed; top: 0; right: 0; bottom: 0; left: 0; background: rgba(26,46,26,0.45);
                     display: flex; align-items: center; justify-content: center; padding: 14px; z-index: 70; }
        .cam-card { background: var(--paper); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow);
                    width: 100%; max-width: 560px; display: flex; flex-direction: column; overflow: hidden; }
        .cam-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px;
                    border-bottom: 1px solid var(--line); font-family: 'Playfair Display', Georgia, serif; font-size: 1.1em; color: var(--ink); }
        .cam-head button { background: none; border: none; font-size: 1.6em; line-height: 1; color: var(--slate); cursor: pointer; padding: 0 4px; }
        .cam-card img { width: 100%; display: block; background: #000; min-height: 180px; max-height: 52vh; object-fit: contain; }
        .cam-controls { display: flex; align-items: center; justify-content: space-evenly; gap: 12px; padding: 12px 10px 6px; flex-wrap: wrap; }
        .cam-pad { display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .cam-pad > div { display: flex; gap: 4px; }
        .cam-pad button, .cam-zoom button { width: 44px; height: 44px; border-radius: 9px; border: 1px solid var(--sage);
                    background: var(--paper); color: var(--forest); font-size: 1.05em; cursor: pointer; }
        .cam-pad button:active, .cam-zoom button:active { background: var(--cream); border-color: var(--forest); }
        .cam-zoom { display: flex; align-items: center; gap: 10px; }
        .cam-zoom span { font-family: 'IBM Plex Mono', monospace; min-width: 48px; text-align: center; color: var(--ink); }
        .cam-zoom button { font-size: 1.4em; }
        .cam-sub { padding: 4px 14px 12px; color: var(--slate); font-size: 0.8em; text-align: center; }
    </style>
</head>
<body{% if kid %} class="kid"{% endif %}>
    <div class="container">
        <div class="header">
            {% if kid %}
            <h1><svg class="robot" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 5.4v2.6"/><circle cx="12" cy="4" r="1.4"/><circle cx="9.6" cy="13" r="1.1"/><circle cx="14.4" cy="13" r="1.1"/><path d="M9.8 16.3h4.4"/><path d="M5 12H3.4M19 12h1.6"/></svg> Hi! I'm {{ robot_name }}</h1>
            <p>I'm so happy you're here! Tap the big mic and let's talk. &#128153;</p>
            {% else %}
            <h1>Chat with {{ robot_name }}</h1>
            <p>Type to talk with {{ robot_name }}, and attach images or documents to share.</p>
            <div class="navlinks"><a href="/">&larr; Home</a><a href="/duet">Duet</a><a href="/calendar">Calendar</a><a href="/contacts">Contacts</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            {% endif %}
        </div>
        {% if kid %}
        <div class="blue-face" id="blueFace" aria-hidden="true">
            <div class="bf-antenna"><span class="bf-dot"></span></div>
            <div class="bf-head">
                <span class="bf-ear l"></span><span class="bf-ear r"></span>
                <div class="bf-eye l"><span class="bf-pupil"></span></div>
                <div class="bf-eye r"><span class="bf-pupil"></span></div>
                <span class="bf-cheek l"></span><span class="bf-cheek r"></span>
                <div class="bf-mouth"></div>
            </div>
        </div>
        {% endif %}
        <div class="messages" id="messages">
            <div class="empty" id="empty">
                {% if kid %}
                <div class="big">Hi Vilda! &#128153;</div>
                <div>I'm so happy to see you! Tap the big microphone and let's chat.</div>
                {% else %}
                <div class="big">Say hello to Blue</div>
                <div>Ask him anything, or attach a photo and ask what he sees. Attach a document and ask him about it.</div>
                {% endif %}
            </div>
        </div>
        <div class="composer">
            <div class="chips" id="chips"></div>
            <div class="input-bar">
                <input type="file" id="fileInput" multiple style="display:none"
                       accept=".png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff,.pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.html,.rtf,.pptx,.xlsx">
                <button class="iconbtn" id="attachBtn" title="Attach files" aria-label="Attach files">+</button>
                <button class="iconbtn micbtn" id="micBtn" title="Tap and talk to Blue" aria-label="Talk to Blue">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3z"/><path d="M6 11a6 6 0 0 0 12 0"/><path d="M12 17v4"/></svg>
                </button>
                {% if not kid %}
                <button class="iconbtn" id="camBtn" title="See through {{ robot_name }}'s camera" aria-label="Live camera preview" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3.2L9 5.5h6L16.8 8H20a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.4"/></svg>
                </button>
                {% endif %}
                {% if kid %}
                <button class="iconbtn" id="eyeBtn" title="Let Blue look through the camera" aria-label="Blue's eyes" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
                </button>
                {% endif %}
                <button class="iconbtn" id="hfBtn" title="Hands-free: say 'Blue' to start" aria-label="Hands-free listening" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 10c0-3 2.5-5.5 5.5-5.5s5.5 2.5 5.5 5.5v3.5a3 3 0 0 1-3 3h-1"/><path d="M6.5 10v2.5a3 3 0 0 0 2 2.8"/><path d="M9.5 18c.7.8 1.7 1.4 3 1.4"/></svg>
                </button>
                <textarea id="input" placeholder="Message Blue..." rows="1"></textarea>
                <button class="iconbtn" id="voiceBtn" title="Choose {{ robot_name }}'s voice" aria-label="Choose {{ robot_name }}'s voice">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M5.5 20c0-3.6 3-5.5 6.5-5.5s6.5 1.9 6.5 5.5"/></svg>
                </button>
                <button class="iconbtn" id="speakBtn" title="Blue reads his answers out loud" aria-label="Toggle spoken replies" aria-pressed="false">
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 8a5 5 0 0 1 0 8"/></svg>
                </button>
                <button class="sendbtn" id="sendBtn">Send</button>
            </div>
            {% if kid %}
            <div class="eye-panel" id="eyePanel">
                <video id="eyeVid" playsinline muted autoplay></video>
                <div class="eye-tools">
                    <button id="eyeFlip" title="Flip camera" aria-label="Flip camera">&#8635;</button>
                    <button id="eyeClose" title="Close Blue's eyes" aria-label="Close camera">&times;</button>
                </div>
                <div class="eye-cap">Tap the eye and I'll look! &#128064;</div>
            </div>
            <canvas id="eyeCanvas" style="display:none"></canvas>
            {% endif %}
            <div class="hint">Enter to send &middot; Shift+Enter for a new line</div>
            <div id="hfStatus" class="hf-status" style="display:none"></div>
            <button id="hfModeBtn" class="hf-mode-btn" style="display:none" type="button">Mode: say "Blue" first</button>
        </div>
    </div>

    <div class="voice-panel" id="voicePanel" style="display:none">
        <div class="voice-card">
            <div class="voice-head"><span>Pick {{ robot_name }}'s voice</span><button id="voiceClose" aria-label="Close">&times;</button></div>
            <div class="voice-sub">Tap a voice to hear it. The one with a check mark is the one Blue uses.</div>
            <div class="voice-list" id="voiceList"></div>
        </div>
    </div>

    {% if not kid %}
    <div class="cam-panel" id="camPanel" style="display:none">
        <div class="cam-card">
            <div class="cam-head"><span>{{ robot_name }}'s camera &mdash; live</span><button id="camClose" aria-label="Close camera preview">&times;</button></div>
            <img id="camStream" alt="Live camera view">
            <div class="cam-controls">
                <div class="cam-pad" aria-label="Pan and tilt the camera">
                    <button data-look="up" title="Pan the camera up">&#9650;</button>
                    <div>
                        <button data-look="left" title="Pan the camera left">&#9664;</button>
                        <button data-look="center" title="Re-center the camera">&#8962;</button>
                        <button data-look="right" title="Pan the camera right">&#9654;</button>
                    </div>
                    <button data-look="down" title="Pan the camera down">&#9660;</button>
                </div>
                <div class="cam-zoom" aria-label="Camera zoom">
                    <button id="camZoomOut" title="Zoom out">&minus;</button>
                    <span id="camZoomVal">1&times;</span>
                    <button id="camZoomIn" title="Zoom in">+</button>
                </div>
            </div>
            <div class="cam-sub">The arrows pan the camera lens itself (it zooms to 2&times; first &mdash; panning moves the zoom window). Line up the view, then just ask &mdash; &ldquo;what do you see?&rdquo; captures exactly this.</div>
        </div>
    </div>
    {% endif %}

    <script>
        const messagesEl = document.getElementById('messages');
        const emptyEl = document.getElementById('empty');
        const inputEl = document.getElementById('input');
        const sendBtn = document.getElementById('sendBtn');
        const attachBtn = document.getElementById('attachBtn');
        const fileInput = document.getElementById('fileInput');
        const chipsEl = document.getElementById('chips');

        // On-screen Blue face (kid mode only — null elsewhere, so every call
        // below is a harmless no-op for Alex). Gives Vilda a Blue she can SEE
        // react, since the physical robot stays still for her. States:
        // listening / thinking / talking / curious; no class = calm idle smile
        // (it blinks and bobs on its own via CSS).
        const blueFace = document.getElementById('blueFace');
        function setFaceState(state) {
            if (!blueFace) return;
            blueFace.classList.remove('listening', 'thinking', 'talking', 'curious');
            if (state) blueFace.classList.add(state);
        }
        function faceCuriousBriefly() {
            if (!blueFace) return;
            setFaceState('curious');
            setTimeout(function () { if (blueFace.classList.contains('curious')) setFaceState(''); }, 1600);
        }

        // Identify this device so the server knows who's chatting (iPad => Vilda,
        // everything else => Alex). Done in the browser because a "desktop-mode"
        // iPad masquerades as a Mac in the User-Agent and is only distinguishable
        // here, via touch support (a real Mac reports zero touch points).
        function blueDeviceTag() {
            const ua = navigator.userAgent || '';
            const touch = (navigator.maxTouchPoints || 0) > 1;
            if (/iPad/.test(ua) || (/Macintosh/.test(ua) && touch)) return 'ipad';
            if (/iPhone|iPod/.test(ua)) return 'iphone';
            if (/Android/.test(ua)) return 'android';
            if (/Macintosh|Mac OS X/.test(ua)) return 'mac';
            if (/Windows/.test(ua)) return 'windows';
            return 'other';
        }

        // Conversation as sent to the API (role/content). Persona + memory are
        // applied server-side, so we only carry the user/assistant turns.
        let apiMessages = [];
        // Staged attachments for the NEXT message. Images are already staged in
        // Blue's vision queue server-side; docs carry their extracted text here.
        let pending = [];
        let busy = false;

        function esc(s) {
            const d = document.createElement('div');
            d.textContent = s == null ? '' : String(s);
            return d.innerHTML;
        }

        function addBubble(role, text, attachments) {
            if (emptyEl) emptyEl.style.display = 'none';
            const row = document.createElement('div');
            row.className = 'row ' + (role === 'user' ? 'user' : 'blue');
            let inner = '<div class="who">' + (role === 'user' ? 'You' : ROBOT.name) + '</div>';
            let body = esc(text);
            if (attachments && attachments.length) {
                body += attachments.map(a => '<span class="att">[' + esc(a.name) + ']</span>').join(' ');
            }
            inner += '<div class="bubble">' + body + '</div>';
            row.innerHTML = inner;
            messagesEl.appendChild(row);
            messagesEl.scrollTop = messagesEl.scrollHeight;
            return row;
        }

        function renderChips() {
            chipsEl.innerHTML = pending.map((a, i) => {
                if (a.kind === 'error') {
                    return '<span class="chip err">' + esc(a.name) + ' — ' + esc(a.error || 'unsupported') + '</span>';
                }
                const tag = a.kind === 'image' ? 'image' : 'doc';
                return '<span class="chip">' + esc(a.name) + ' <span style="opacity:.6">' + tag + '</span>'
                     + '<button data-i="' + i + '" title="Remove">&times;</button></span>';
            }).join('');
            chipsEl.querySelectorAll('button[data-i]').forEach(b => {
                b.addEventListener('click', () => { pending.splice(parseInt(b.dataset.i), 1); renderChips(); });
            });
        }

        attachBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', async () => {
            if (!fileInput.files.length) return;
            const fd = new FormData();
            for (const f of fileInput.files) fd.append('files', f);
            fileInput.value = '';
            attachBtn.disabled = true;
            try {
                const res = await fetch('/chat/attach', { method: 'POST', body: fd });
                let data = null;
                try { data = await res.json(); } catch (_) { /* non-JSON (e.g. HTML error page) */ }
                if (data && data.attachments) {
                    data.attachments.forEach(a => pending.push(a));
                } else {
                    const msg = (data && data.error)
                        || (res.status === 413 ? 'file too large'
                            : ('upload failed (HTTP ' + res.status + ')'));
                    pending.push({ name: msg, kind: 'error', error: msg });
                }
                renderChips();
            } catch (e) {
                pending.push({ name: 'upload failed', kind: 'error', error: String(e) });
                renderChips();
            } finally {
                attachBtn.disabled = false;
            }
        });

        function autoGrow() {
            inputEl.style.height = 'auto';
            inputEl.style.height = Math.min(inputEl.scrollHeight, 180) + 'px';
        }
        inputEl.addEventListener('input', autoGrow);
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
        });
        sendBtn.addEventListener('click', send);

        // Set true right before a voice-originated send() so the server knows
        // to keep the reply short (spoken replies should be brief — and fewer
        // tokens = faster generation = Blue starts talking sooner). Consumed
        // (reset) inside send().
        let pendingVoice = false;

        async function send() {
            if (busy) return;
            primeAudio();
            const isVoiceTurn = pendingVoice; pendingVoice = false;
            const text = inputEl.value.trim();
            const atts = pending.slice();
            if (!text && !atts.length) return;

            // Build the content actually sent: user's text plus any extracted
            // document text (images are injected server-side from the queue).
            let sentContent = text;
            const docBlocks = atts.filter(a => a.kind === 'doc' && a.text)
                .map(a => '[Attached document: ' + a.name + ']\\n\"\"\"\\n' + a.text + '\\n\"\"\"');
            if (docBlocks.length) {
                sentContent = docBlocks.join('\\n\\n') + (text ? ('\\n\\n' + text) : '\\n\\nPlease take a look at the attached document.');
            }
            if (!sentContent) sentContent = 'What do you make of this?';

            addBubble('user', text || '(see attachment)', atts.filter(a => a.kind !== 'error'));
            apiMessages.push({ role: 'user', content: sentContent });

            inputEl.value = '';
            autoGrow();
            pending = [];
            renderChips();

            busy = true; sendBtn.disabled = true; sendBtn.textContent = '...';
            const thinking = addBubble('blue', '');
            thinking.querySelector('.bubble').innerHTML = '<span class="typing">' + ROBOT.name + ' is thinking…</span>';
            setFaceState('thinking');

            try {
                // If Blue's eyes (iPad camera) are open, grab a fresh frame first
                // so he can see during THIS turn — not only when the eye is tapped.
                // No-op when the camera is closed or on Alex's page.
                if (window.__blueEyeGrab) { try { await window.__blueEyeGrab(); } catch (e) {} }
                const res = await fetch('/v1/chat/completions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-Blue-Device': blueDeviceTag() },
                    body: JSON.stringify({ messages: apiMessages, voice: isVoiceTurn, robot: ROBOT.id })
                });
                const data = await res.json();
                let reply = '';
                try { reply = data.choices[0].message.content || ''; } catch (e) { reply = ''; }
                if (!reply) reply = 'Sorry, I didn\\'t catch that — could you try again?';
                thinking.querySelector('.bubble').textContent = reply;
                setFaceState('');
                speak(reply);
                messagesEl.scrollTop = messagesEl.scrollHeight;
                apiMessages.push({ role: 'assistant', content: reply });
            } catch (e) {
                thinking.querySelector('.bubble').textContent = 'I had trouble reaching my brain just now. Is the server running?';
                faceCuriousBriefly();
            } finally {
                busy = false; sendBtn.disabled = false; sendBtn.textContent = 'Send';
                inputEl.focus();
            }
        }

        // ===== Voice: Blue speaks aloud, and (over HTTPS) you can talk to him =====
        // Voice-first for Vilda's iPad: replies are read out loud and the mic is
        // big. The mic uses the browser's speech recognition, which Safari only
        // allows over a secure (https) connection — hence the Tailscale setup.
        // Which robot this page is — Blue (/chat) or Hexia (/hexia). Drives the
        // chat target, the accent colour, the spoken voice and which head moves.
        const ROBOT = {{ robot_json|safe }};
        try { if (ROBOT.accent) document.documentElement.style.setProperty('--blue', ROBOT.accent); } catch (e) {}
        const isVilda = blueDeviceTag() === 'ipad';
        let speakOn = isVilda;
        let audioPrimed = false;
        const micBtn = document.getElementById('micBtn');
        const speakBtn = document.getElementById('speakBtn');

        function primeAudio() {
            // iOS only lets speech start after a real tap; speaking an empty line
            // during the tap unlocks it for the automatic replies that follow.
            if (audioPrimed || !('speechSynthesis' in window)) return;
            try { window.speechSynthesis.speak(new SpeechSynthesisUtterance('')); audioPrimed = true; }
            catch (e) { /* no speech available */ }
        }

        // Pick a voice for the given language, preferring a male voice where one
        // exists (Blue is a man). Greek on iOS only ships a female voice.
        function pickVoice(lang) {
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            // Blue prefers a male voice; Hexia (ROBOT.preferFemale) a female one.
            const malePrefs = {
                en: ['Daniel', 'Aaron', 'Arthur', 'Gordon', 'Rishi', 'Fred', 'Albert', 'Microsoft David', 'Microsoft Mark', 'Google UK English Male', 'Google US English'],
                fr: ['Thomas', 'Nicolas', 'Microsoft Claude', 'Microsoft Paul', 'Google fran\\u00e7ais'],
                ru: ['Yuri', 'Microsoft Pavel', 'Google \\u0440\\u0443\\u0441\\u0441\\u043a\\u0438\\u0439'],
                el: ['Melina', 'Microsoft Stefanos'],
                da: ['Magnus', 'Sara', 'Microsoft Helle']
            };
            const femalePrefs = {
                en: ['Samantha', 'Victoria', 'Karen', 'Moira', 'Tessa', 'Serena', 'Microsoft Zira', 'Google UK English Female', 'Google US English'],
                fr: ['Amelie', 'Audrey', 'Virginie', 'Aurelie', 'Microsoft Julie', 'Google fran\\u00e7ais'],
                ru: ['Milena', 'Katya', 'Microsoft Irina', 'Google \\u0440\\u0443\\u0441\\u0441\\u043a\\u0438\\u0439'],
                el: ['Melina', 'Microsoft Stefanos'],
                da: ['Sara', 'Microsoft Helle']
            };
            const prefs = (ROBOT && ROBOT.preferFemale) ? femalePrefs : malePrefs;
            const pl = prefs[lang] || prefs.en;
            for (let i = 0; i < pl.length; i++) {
                const v = voices.find(x => x.name === pl[i] || x.name.indexOf(pl[i]) === 0);
                if (v) return v;
            }
            const re = new RegExp('^' + (lang || 'en'), 'i');
            return voices.find(x => re.test(x.lang)) || voices.find(x => /^en/i.test(x.lang)) || null;
        }

        // Best-effort detection of Blue's reply language so we speak it with the
        // right voice: Cyrillic => Russian, Greek block => Greek; otherwise look
        // for French signals, else English.
        function detectLang(t) {
            const s = t || '';
            if (/[\\u0400-\\u04FF]/.test(s)) return 'ru';
            if (/[\\u0370-\\u03FF]/.test(s)) return 'el';
            // Danish uses æ ø å (Æ Ø Å) which French doesn't.
            if (/[\\u00e6\\u00f8\\u00e5\\u00c6\\u00d8\\u00c5]/.test(s)) return 'da';
            const daWords = /\\b(jeg|du|det|er|og|ikke|hej|tak|hvad|hvor|hvordan|ja|nej|kan|skal|har|vil|med|p\\u00e5)\\b/i;
            if (daWords.test(s)) return 'da';
            const accents = (s.match(/[\\u00e0\\u00e2\\u00e7\\u00e9\\u00e8\\u00ea\\u00eb\\u00ee\\u00ef\\u00f4\\u00f9\\u00fb\\u00fc\\u0153]/gi) || []).length;
            const frWords = /\\b(le|la|les|une|des|est|vous|je|tu|nous|bonjour|merci|oui|non|pour|avec|pas|bien|tres|aussi|aujourd)\\b/i;
            if (accents >= 2 || frWords.test(s)) return 'fr';
            return 'en';
        }

        function cleanForSpeech(t) {
            return (t || '')
                .replace(/https?:\\/\\/\\S+/g, ' a link ')
                .replace(/[\\u{1F000}-\\u{1FFFF}\\u{2600}-\\u{27BF}]/gu, '')
                .replace(/[*_`#>~]/g, '')
                .replace(/\\s+/g, ' ')
                .trim();
        }

        // The voice Vilda picked (saved per-device), or null if none chosen.
        function chosenVoice() {
            let name = '';
            try { name = localStorage.getItem('blueVoiceName_' + ROBOT.id) || (ROBOT.id === 'blue' ? (localStorage.getItem('blueVoiceName') || '') : ''); } catch (e) {}
            if (!name) return null;
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            for (let i = 0; i < voices.length; i++) { if (voices[i].name === name) return voices[i]; }
            return null;
        }

        // Build a timed mouth schedule from the reply text so the robot's jaw
        // moves during words and the mouth CLOSES during the gaps — including
        // longer pauses at commas and sentence ends. Each frame is
        // [openness 0-1, hold_seconds]. Sent once to /head/lip-seq; the server
        // plays it out (works on iOS 12 too, where speech boundary events don't
        // fire). Durations are an estimate of the TTS rhythm; onend stops it.
        function buildLipFrames(text, rate) {
            rate = rate || 1.0;
            const k = 1.0 / rate;                 // slower speech → longer holds
            const words = (text.match(/[^\\s]+/g) || []);
            const frames = [];
            const MS_PER_CHAR = 0.060;            // seconds of jaw motion per letter
            for (let wi = 0; wi < words.length; wi++) {
                const w = words[wi];
                const core = w.replace(/[^A-Za-z0-9\\u00C0-\\u024F\\u0370-\\u03FF\\u0400-\\u04FF]/g, '');
                const len = Math.max(1, core.length);
                let dur = Math.min(0.75, Math.max(0.14, len * MS_PER_CHAR)) * k;
                const moves = Math.max(1, Math.round(len / 3));   // ~one jaw drop per few letters (syllables)
                const per = dur / moves;
                for (let i = 0; i < moves; i++) {
                    frames.push([0.6 + Math.random() * 0.4, per * 0.6]);  // open (varied)
                    frames.push([0.1, per * 0.4]);                        // near-closed between syllables
                }
                // Gap after the word; longer at punctuation = a real pause.
                const last = w.slice(-1);
                let gap = 0.06;
                if (/[,;:)\\]]/.test(last)) gap = 0.22;
                else if (/[.!?\\u2026]/.test(last)) gap = 0.40;
                frames.push([0.0, gap * k]);                              // mouth shut during the gap
            }
            return frames;
        }

        function speak(text) {
            if (!speakOn || !('speechSynthesis' in window)) return;
            const msg = cleanForSpeech(text);
            if (!msg) return;
            const lang = detectLang(msg);
            const bcp = { en: 'en-US', fr: 'fr-FR', ru: 'ru-RU', el: 'el-GR', da: 'da-DK' }[lang] || 'en-US';
            try {
                window.speechSynthesis.cancel();
                const u = new SpeechSynthesisUtterance(msg);
                // Use Vilda's chosen voice when it speaks the reply's language;
                // otherwise fall back to the automatic per-language pick.
                let v = chosenVoice();
                if (!v || (v.lang || '').toLowerCase().indexOf(lang) !== 0) v = pickVoice(lang);
                if (v) u.voice = v;
                u.lang = bcp;
                u.rate = (isVilda ? 0.95 : 1.0) * ((ROBOT && ROBOT.voiceRate) || 1.0);
                u.pitch = (ROBOT && ROBOT.voicePitch) || 1.0;
                // Make Blue "talk" while he reads aloud. On Vilda's iPad this
                // moves the ON-SCREEN face's mouth (the physical robot must stay
                // still for her); on Alex's devices the on-screen face doesn't
                // exist, so it just flaps the real robot's lips as before. The
                // lip-seq is a text-derived mouth schedule (jaw moves on words,
                // closes on gaps); fire-and-forget — a no-op if no head.
                const _lipFrames = (!isVilda) ? buildLipFrames(msg, u.rate) : null;
                u.onstart = function () {
                    setFaceState('talking');
                    bargeInRecogStart();   // listen for "stop" the whole time he talks
                    if (!isVilda) {
                        try { fetch('/head/' + ROBOT.head + '/lip-seq', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frames: _lipFrames }) }); } catch (e) {}
                    }
                };
                const _spokenDone = function () {
                    bargeInRecogStop();
                    setFaceState('');
                    if (!isVilda) {
                        try { fetch('/head/' + ROBOT.head + '/lip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"on":false}' }); } catch (e) {}
                    }
                };
                u.onend = _spokenDone;
                u.onerror = _spokenDone;
                window.speechSynthesis.speak(u);
            } catch (e) { /* ignore */ }
        }

        // If the user navigates away mid-speech, the lip thread on the server
        // would keep flapping until the next speech start. Make sure to stop.
        window.addEventListener('pagehide', function () {
            if (isVilda) return;   // her iPad never drives the head; nothing to stop
            try { navigator.sendBeacon && navigator.sendBeacon('/head/' + ROBOT.head + '/lip', new Blob(['{"on":false}'], { type: 'application/json' })); } catch (e) {}
        });

        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.onvoiceschanged = function () { window.speechSynthesis.getVoices(); }; } catch (e) {}
        }

        function setSpeakOn(on) {
            speakOn = on;
            speakBtn.classList.toggle('active', on);
            speakBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            if (!on && 'speechSynthesis' in window) window.speechSynthesis.cancel();
        }
        speakBtn.addEventListener('click', () => { primeAudio(); setSpeakOn(!speakOn); });
        setSpeakOn(speakOn);

        // ---- Voice picker: tap a voice to hear it, tap to keep it (saved per device) ----
        const voiceBtn = document.getElementById('voiceBtn');
        const voicePanel = document.getElementById('voicePanel');
        const voiceClose = document.getElementById('voiceClose');
        const voiceList = document.getElementById('voiceList');
        const VOICE_SAMPLES = { en: "Hi, I'm Blue!", fr: 'Bonjour, je suis Blue\\u00a0!', ru: '\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442, \\u044f \\u0411\\u043b\\u044e!', el: '\\u0393\\u0435\\u03b9\\u03b1, \\u03b5\\u03af\\u03bc\\u03b1\\u03b9 \\u03bf \\u039c\\u03c0\\u03bb\\u03b5!', da: 'Hej, jeg er Blue!' };

        function voiceLangCode(v) {
            const l = (v.lang || '').toLowerCase();
            if (l.indexOf('fr') === 0) return 'fr';
            if (l.indexOf('ru') === 0) return 'ru';
            if (l.indexOf('el') === 0) return 'el';
            if (l.indexOf('da') === 0) return 'da';
            if (l.indexOf('en') === 0) return 'en';
            return null;
        }

        function buildVoiceList() {
            const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
            const supported = voices.filter(voiceLangCode);
            let chosen = '';
            try { chosen = localStorage.getItem('blueVoiceName_' + ROBOT.id) || (ROBOT.id === 'blue' ? (localStorage.getItem('blueVoiceName') || '') : ''); } catch (e) {}
            voiceList.innerHTML = '';
            if (!supported.length) {
                voiceList.innerHTML = '<div class="voice-empty">No voices are installed on this device yet.</div>';
                return;
            }
            supported.forEach(function (v) {
                const row = document.createElement('button');
                row.className = 'voice-row' + (v.name === chosen ? ' sel' : '');
                row.innerHTML = '<span class="vn">' + esc(v.name) + '</span><span class="vl">' + esc(v.lang) + '</span>';
                row.addEventListener('click', function () {
                    primeAudio();
                    try { localStorage.setItem('blueVoiceName_' + ROBOT.id, v.name); } catch (e) {}
                    try {
                        window.speechSynthesis.cancel();
                        const code = voiceLangCode(v) || 'en';
                        const u = new SpeechSynthesisUtterance(VOICE_SAMPLES[code] || VOICE_SAMPLES.en);
                        u.voice = v; u.lang = v.lang || 'en-US';
                        window.speechSynthesis.speak(u);
                    } catch (e) {}
                    buildVoiceList();
                });
                voiceList.appendChild(row);
            });
        }

        if (voiceBtn) {
            voiceBtn.addEventListener('click', function () { primeAudio(); buildVoiceList(); voicePanel.style.display = 'flex'; });
            voiceClose.addEventListener('click', function () { voicePanel.style.display = 'none'; });
            voicePanel.addEventListener('click', function (e) { if (e.target === voicePanel) voicePanel.style.display = 'none'; });
        }

        // The iPad Mini (iOS 12) has no MediaRecorder, so we capture raw audio
        // with the Web Audio API (works back to iOS 12) and encode a WAV here,
        // then POST it to /stt for Blue to transcribe on the PC.
        // Set the mic up ONCE and keep it running. iOS Safari (iOS 12) both caps
        // how many AudioContexts a page may create AND yields SILENT audio when a
        // MediaStreamSource is re-attached to a context — which is why tearing
        // down and rebuilding per recording produced 6s of pure silence. So we
        // build the context + mic + nodes a single time, leave them connected,
        // and just gate sample collection with the `recording` flag.
        let listening = false, recording = false, audioReady = false;
        let audioCtx = null, micStream = null, srcNode = null, procNode = null;
        let pcmChunks = [], recSampleRate = 16000, autoStopTimer = null;
        const hintEl = document.querySelector('.hint');
        const originalHint = hintEl ? hintEl.textContent : '';
        const defaultHint = isVilda ? 'Tap the microphone and talk to Blue.' : originalHint;
        function setHint(t) { if (hintEl) hintEl.textContent = t; }
        setHint(defaultHint);

        // Returns true once the mic graph is live; 'denied' / 'unsupported' otherwise.
        // CRITICAL on iOS: both audioCtx.resume() and getUserMedia() must be
        // *initiated* synchronously inside the tap gesture (before any await),
        // or iOS leaves the context suspended and nothing is ever captured.
        async function ensureAudio() {
            const AC = window.AudioContext || window.webkitAudioContext;
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !AC) return 'unsupported';
            try { if (!audioCtx) audioCtx = new AC(); } catch (e) { return 'unsupported'; }
            // Kick both off NOW, while still in the gesture; await afterwards.
            const resumeP = (audioCtx.state !== 'running') ? audioCtx.resume() : null;
            // echoCancellation matters for barge-in ("stop" while Blue talks):
            // it suppresses Blue's own voice coming back through the mic so we
            // don't hear (or transcribe) him saying his own words.
            const _audioConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
            const mediaP = audioReady ? null : navigator.mediaDevices.getUserMedia({ audio: _audioConstraints }).catch(function () {
                return navigator.mediaDevices.getUserMedia({ audio: true });  // fallback if constraints unsupported
            });
            if (resumeP) { try { await resumeP; } catch (e) {} }
            if (audioReady && audioCtx.state !== 'closed') return true;
            let stream;
            try { stream = await mediaP; } catch (e) { return 'denied'; }
            micStream = stream;
            recSampleRate = audioCtx.sampleRate || 44100;
            srcNode = audioCtx.createMediaStreamSource(micStream);
            procNode = audioCtx.createScriptProcessor(4096, 1, 1);
            procNode.onaudioprocess = audioProcessHandler;
            const mute = audioCtx.createGain();
            mute.gain.value = 0;
            srcNode.connect(procNode);
            procNode.connect(mute);
            mute.connect(audioCtx.destination);
            // iOS may garbage-collect the source/stream and then feed silence;
            // pin everything to a global so it can't be collected.
            window.__blueKeep = [audioCtx, srcNode, procNode, mute, micStream];
            try {
                const tr0 = micStream.getAudioTracks ? micStream.getAudioTracks()[0] : null;
                if (tr0) tr0.enabled = true;
            } catch (e) {}
            audioReady = true;
            return true;
        }

        function encodeWav(chunks, sampleRate) {
            let len = 0;
            for (let i = 0; i < chunks.length; i++) len += chunks[i].length;
            const buf = new ArrayBuffer(44 + len * 2);
            const view = new DataView(buf);
            function ws(off, s) { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); }
            ws(0, 'RIFF'); view.setUint32(4, 36 + len * 2, true); ws(8, 'WAVE');
            ws(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
            view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
            view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
            ws(36, 'data'); view.setUint32(40, len * 2, true);
            let off = 44;
            for (let i = 0; i < chunks.length; i++) {
                const c = chunks[i];
                for (let j = 0; j < c.length; j++) {
                    let v = c[j]; if (v > 1) v = 1; else if (v < -1) v = -1;
                    view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7FFF, true); off += 2;
                }
            }
            return new Blob([view], { type: 'audio/wav' });
        }

        function stopListening() {
            if (autoStopTimer) { clearTimeout(autoStopTimer); autoStopTimer = null; }
            if (!recording) return;
            recording = false;
            listening = false;
            micBtn.classList.remove('listening');
            const chunks = pcmChunks;
            pcmChunks = [];
            transcribePcm(chunks, recSampleRate);
        }

        async function startListening() {
            primeAudio();
            if ('speechSynthesis' in window) window.speechSynthesis.cancel();
            if (recording) { stopListening(); return; }
            const ok = await ensureAudio();
            if (ok === 'denied') {
                addBubble('blue', 'I need permission to use the microphone. Tap the mic again and choose Allow.');
                return;
            }
            if (ok !== true) {
                if (!window.isSecureContext) {
                    addBubble('blue', 'Please open me at my secure address first: https://ai-workstation.tail211c96.ts.net/chat \\u2014 then the microphone will work.');
                } else {
                    addBubble('blue', 'This browser will not let me use the microphone.');
                }
                return;
            }
            if (audioCtx.state !== 'running') { try { await audioCtx.resume(); } catch (e) {} }
            pcmChunks = [];
            recording = true;
            listening = true;
            micBtn.classList.add('listening');
            setFaceState('listening');
            setHint('Listening\\u2026 tap the microphone again when you are done.');
            autoStopTimer = setTimeout(stopListening, 15000);
        }

        async function transcribePcm(chunks, sampleRate) {
            let total = 0;
            for (let i = 0; i < chunks.length; i++) total += chunks[i].length;
            if (!total) {
                setHint(defaultHint);
                addBubble('blue', 'I did not hear anything that time \\u2014 tap the mic, wait a second, then talk.');
                faceCuriousBriefly();
                return;
            }
            const blob = encodeWav(chunks, sampleRate);
            const fd = new FormData();
            fd.append('audio', blob, 'speech.wav');
            micBtn.disabled = true;
            setHint('Figuring out what you said\\u2026');
            setFaceState('thinking');
            try {
                const res = await fetch('/stt', { method: 'POST', body: fd });
                const data = await res.json().catch(() => null);
                const said = (data && data.text || '').trim();
                if (said) { inputEl.value = said; pendingVoice = true; send(); }
                else { addBubble('blue', 'I did not catch that \\u2014 tap the mic and try again.'); faceCuriousBriefly(); }
            } catch (e) {
                addBubble('blue', 'I could not hear that just now. Tap the mic and try again.');
                faceCuriousBriefly();
            } finally {
                micBtn.disabled = false;
                setHint(defaultHint);
            }
        }

        micBtn.addEventListener('click', startListening);

        // ======================================================================
        // ---- Robot camera live preview: see through the camera BEFORE a
        // capture. Steer the head, set the zoom — then "what do you see?"
        // photographs exactly the previewed view (capture reuses the preview's
        // camera while the panel is open).
        const camBtn = document.getElementById('camBtn');
        const camPanel = document.getElementById('camPanel');
        if (camBtn && camPanel) {
            const camImg = document.getElementById('camStream');
            const camVal = document.getElementById('camZoomVal');
            let camZoom = 1.0;
            function camShowZoom() { camVal.textContent = (Math.round(camZoom * 10) / 10) + '\\u00d7'; }
            function camOpen() {
                camPanel.style.display = 'flex';
                camImg.src = '/camera/stream?ts=' + Date.now();
                camBtn.classList.add('active'); camBtn.setAttribute('aria-pressed', 'true');
            }
            function camShut() {
                camPanel.style.display = 'none';
                camImg.removeAttribute('src');   // drops the MJPEG connection
                camBtn.classList.remove('active'); camBtn.setAttribute('aria-pressed', 'false');
            }
            function camPtz(body) {
                fetch('/camera/ptz', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
                    .then(r => r.json())
                    .then(d => { if (d && typeof d.zoom === 'number') { camZoom = d.zoom; camShowZoom(); } })
                    .catch(() => {});
            }
            camBtn.addEventListener('click', () => { (camPanel.style.display === 'none') ? camOpen() : camShut(); });
            document.getElementById('camClose').addEventListener('click', camShut);
            camPanel.addEventListener('click', (e) => { if (e.target === camPanel) camShut(); });
            camPanel.querySelectorAll('[data-look]').forEach(b => b.addEventListener('click', () => camPtz({ look: b.getAttribute('data-look') })));
            document.getElementById('camZoomIn').addEventListener('click', () => camPtz({ zoom: Math.min(4, camZoom + 0.5) }));
            document.getElementById('camZoomOut').addEventListener('click', () => camPtz({ zoom: Math.max(1, camZoom - 0.5) }));
            camShowZoom();
        }

        // ======================================================================
        // Hands-free mode: continuous listening, wake on "Blue", auto-stop on
        // silence. A second option alongside tap-to-talk; toggled by hfBtn.
        // ======================================================================
        let handsFree = false;
        let hfVoicing = false;          // currently capturing an utterance
        let hfSilence = 0;              // consecutive silent chunks during voicing
        let hfPreroll = [];             // last few silent chunks, prepended on voice start
        // Barge-in ("stop" while Blue is speaking) capture state.
        let biActive = false, biChunks = [], biVoice = 0, biSilence = 0, biBusy = false;
        let biPreroll = [];                // rolling pre-roll so the "st-" onset isn't clipped
        // Sensitive on purpose: starting a capture does NOT stop Blue — only a
        // transcript that matches "stop" does. So we capture eagerly at quiet
        // speaking volume; echo cancellation keeps Blue's own voice out.
        const BI_THRESHOLD_FACTOR = 1.0;   // right at the normal voice threshold
        const BI_THRESHOLD_MIN = 0.010;    // very low floor — a soft "stop" should land
        const BI_VOICE_START = 1;          // react on the first loud chunk
        const BI_PREROLL_MAX = 4;          // ~0.37s kept before onset (captures the "st")
        const BI_SILENCE_END = 3;          // ~0.28s of quiet ends the barge-in clip
        const BI_MAX_CHUNKS = 9;           // ~0.84s cap — short clips = fast verdicts;
                                           // Blue's echo rarely lets the mic go quiet
        // ONLY "stop" interrupts (per request). Lenient: matches "stop" anywhere
        // plus the closest mis-hearings Whisper produces (stahp/stawp/staap/stop).
        const BI_STOP = /\\bst[aou]+w?h?p\\b|\\bstop\\b/i;
        let biPending = null;              // clip captured while another was at /stt
        let hfProcessing = false;       // /stt in flight or send() running
        let hfWakeArmed = false;        // user said "Blue" alone; next utterance is the message
        let hfArmedTimer = null;
        let hfNoiseFloor = 0.005;       // running estimate of ambient RMS (adapts to room)
        let hfVoiceRamp = 0;            // consecutive above-threshold chunks before we commit
        let hfVoicyCount = 0;           // voiced chunks in the current utterance

        // VAD tuning. Noise rejection is layered: an adaptive floor (so quiet
        // rooms stay sensitive and loud rooms get stricter), a ramp-up so a
        // single pop can't open a recording, and a minimum voiced duration so
        // very short noises get discarded before they ever reach Whisper.
        const HF_NOISE_ALPHA = 0.05;       // EMA smoothing on the ambient floor
        // VAD thresholds derived from the hands-free sensitivity slider on /head
        // (0 = strict, 10 = very sensitive). Initial value comes from the server.
        let HF_THRESHOLD_FACTOR = 2.4;
        let HF_THRESHOLD_MIN = 0.018;
        let HF_VOICE_RAMP = 2;
        let HF_MIN_VOICE_CHUNKS = 3;
        function applyHfSensitivity(s) {
            s = Math.max(0, Math.min(10, Number(s)));
            if (isNaN(s)) s = 5;
            HF_THRESHOLD_FACTOR = 4.0 - (s / 10) * 2.5;        // 4.0 (strict) → 1.5 (loose)
            HF_THRESHOLD_MIN    = 0.040 - (s / 10) * 0.032;    // 0.040 → 0.008
            HF_VOICE_RAMP        = s <= 3 ? 3 : (s <= 7 ? 2 : 1);
            HF_MIN_VOICE_CHUNKS  = s <= 3 ? 5 : (s <= 7 ? 3 : 2);
        }
        applyHfSensitivity({{ hf_sens|default(5) }});
        const HF_SILENCE_CHUNKS = 9;       // ~0.85s of silence ends the utterance (snappier)
        const HF_PREROLL_MAX = 4;          // ~0.37s of pre-roll keeps the first phoneme
        const HF_MAX_CHUNKS = 250;         // ~23s cap per utterance
        const HF_ARMED_MS = 15000;         // bare-"Blue" wait window before the message
        // Whisper hallucinates a small set of stock phrases when fed near-silence
        // or non-speech noise. Drop these before they trigger anything.
        const HF_HALLUC = /^\\s*(?:(?:thanks?(?:\\s+for\\s+watching)?|thank\\s+you|you|bye|\\.|subtitles?\\s+by[^.]*|amara\\.org|MBC\\b[^.]*|copyright[^.]*)[!\\.\\?\\s]*)+$/i;

        // Two hands-free modes (toggle on the page, remembered per device):
        //   'wake'         — must start with "Blue"; noise-gated, always-on safe.
        //   'conversation' — no wake word; every utterance goes to Blue.
        let hfMode = 'wake';
        try { hfMode = localStorage.getItem('blueHfMode') || 'wake'; } catch (e) {}

        // Fillers Whisper may stick before the name; allowed to precede the wake.
        const HF_FILLERS = ['hey','hi','hello','ok','okay','um','uh','so','well'];
        // Accepted spellings of the wake word (Whisper is inconsistent on a short
        // leading proper noun, even with hotword biasing).
        const HF_WAKE_WORDS = ['blue','bleu','blu','blew','bloo','blues','bews'];
        function isWakeWord(w) {
            w = w.toLowerCase().replace(/[^a-z]/g, '');
            if (!w) return false;
            if (HF_WAKE_WORDS.indexOf(w) >= 0) return true;
            // edit-distance ≤1 from "blue" catches Boo/Blu/Blhe/etc. without a lib
            if (Math.abs(w.length - 4) > 1) return false;
            let i = 0, j = 0, edits = 0; const t = 'blue';
            while (i < w.length && j < t.length) {
                if (w[i] === t[j]) { i++; j++; }
                else { edits++; if (edits > 1) return false;
                    if (w.length > t.length) i++; else if (w.length < t.length) j++; else { i++; j++; } }
            }
            return (edits + (w.length - i) + (t.length - j)) <= 1;
        }
        // Returns the message after the wake word, '' if wake-only, or null if no wake.
        function extractWake(said) {
            const words = said.trim().split(/\\s+/);
            for (let i = 0; i < Math.min(3, words.length); i++) {
                if (isWakeWord(words[i])) return words.slice(i + 1).join(' ').replace(/^[\\s,.\\?!:;\\-]+/, '').trim();
                // Only fillers (hi/hey/um…) may precede the wake word; strip
                // punctuation Whisper attaches ("Um," -> "um") before comparing.
                if (HF_FILLERS.indexOf(words[i].toLowerCase().replace(/[^a-z]/g, '')) < 0) break;
            }
            return null;
        }

        const hfBtn = document.getElementById('hfBtn');
        const hfStatusEl = document.getElementById('hfStatus');
        // Tapping the status pill while Blue talks silences him (works even if
        // the mic mishears — a guaranteed manual out).
        if (hfStatusEl) {
            hfStatusEl.style.cursor = 'pointer';
            hfStatusEl.addEventListener('click', function () {
                if (window.speechSynthesis && window.speechSynthesis.speaking) stopSpeaking('tap');
            });
        }

        function setHfStatus(state) {
            if (!hfStatusEl) return;
            if (!handsFree) { hfStatusEl.style.display = 'none'; hfStatusEl.className = 'hf-status'; return; }
            const waitLabel = hfMode === 'conversation' ? 'Conversation on \\u2014 just talk\\u2026' : 'Listening for "Blue"\\u2026';
            const labels = {
                waiting:  waitLabel,
                voicing:  'Listening to you\\u2026',
                thinking: 'Thinking\\u2026',
                armed:    'Yes? I\\'m listening\\u2026',
                replying: 'Speaking\\u2026 say "stop" or tap here',
            };
            hfStatusEl.style.display = 'flex';
            hfStatusEl.className = 'hf-status ' + (state || '');
            hfStatusEl.textContent = labels[state] || labels.waiting;
        }

        // Mode toggle (Conversation vs wake word). Shown only while listening.
        function setHfMode(mode) {
            hfMode = (mode === 'conversation') ? 'conversation' : 'wake';
            try { localStorage.setItem('blueHfMode', hfMode); } catch (e) {}
            const mb = document.getElementById('hfModeBtn');
            if (mb) mb.textContent = hfMode === 'conversation' ? 'Mode: conversation (no wake word)' : 'Mode: say "Blue" first';
            if (handsFree && !hfProcessing) setHfStatus('waiting');
        }

        // Single onaudioprocess callback; routes samples to tap-to-talk OR hands-free.
        function audioProcessHandler(ev) {
            const samples = ev.inputBuffer.getChannelData(0);
            if (recording) {
                pcmChunks.push(new Float32Array(samples));
                return;
            }
            if (handsFree) handsFreeOnSamples(samples);
        }

        function handsFreeOnSamples(samples) {
            // Don't kick off a second utterance while one is being processed.
            if (hfProcessing) return;
            // While Blue is talking, run the barge-in listener instead of the
            // normal capture — that's how "stop" interrupts him.
            if (window.speechSynthesis && window.speechSynthesis.speaking) {
                bargeInOnSamples(samples);
                return;
            }
            // Just finished speaking? clear any half-built barge-in capture.
            if (biActive || biChunks.length) { biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = []; }

            let sum = 0;
            for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
            const rms = Math.sqrt(sum / samples.length);

            // Adaptive threshold: stays well above ambient. We only update the
            // noise floor while we're sure we're NOT hearing the user (idle).
            const threshold = Math.max(HF_THRESHOLD_MIN, hfNoiseFloor * HF_THRESHOLD_FACTOR);
            const isVoice = rms > threshold;
            if (!isVoice && !hfVoicing) {
                hfNoiseFloor = hfNoiseFloor * (1 - HF_NOISE_ALPHA) + rms * HF_NOISE_ALPHA;
            }

            if (isVoice) {
                hfVoiceRamp = Math.min(hfVoiceRamp + 1, HF_VOICE_RAMP + 2);
                if (!hfVoicing) {
                    if (hfVoiceRamp < HF_VOICE_RAMP) {
                        // Treat the candidate chunks as pre-roll — if they really
                        // are speech, we'll keep them; if it's a transient noise,
                        // the ramp won't reach HF_VOICE_RAMP and we discard them.
                        hfPreroll.push(new Float32Array(samples));
                        if (hfPreroll.length > HF_PREROLL_MAX) hfPreroll.shift();
                        return;
                    }
                    hfVoicing = true;
                    hfSilence = 0;
                    hfVoicyCount = 0;
                    pcmChunks = hfPreroll.slice();    // commit the pre-roll
                    setHfStatus('voicing');
                }
                pcmChunks.push(new Float32Array(samples));
                hfVoicyCount++;
                hfSilence = 0;
                if (pcmChunks.length > HF_MAX_CHUNKS) hfFinalize();
            } else {
                hfVoiceRamp = Math.max(0, hfVoiceRamp - 1);
                if (hfVoicing) {
                    pcmChunks.push(new Float32Array(samples));   // small tail
                    hfSilence++;
                    if (hfSilence >= HF_SILENCE_CHUNKS) {
                        // Drop "too short" utterances silently — they're almost
                        // always noise, not real speech. Saves a Whisper call AND
                        // prevents Whisper from hallucinating a wake-word match.
                        if (hfVoicyCount < HF_MIN_VOICE_CHUNKS) {
                            hfVoicing = false;
                            hfSilence = 0;
                            hfVoicyCount = 0;
                            hfPreroll = [];
                            pcmChunks = [];
                            setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                            return;
                        }
                        hfFinalize();
                    }
                } else {
                    hfPreroll.push(new Float32Array(samples));
                    if (hfPreroll.length > HF_PREROLL_MAX) hfPreroll.shift();
                }
            }
        }

        // Barge-in: while Blue is speaking, listen for a deliberate "stop".
        // Higher threshold than normal because echo cancellation isn't perfect;
        // we only want to react to the user clearly talking over Blue.
        function bargeInOnSamples(samples) {
            // NOTE: keep capturing even while a clip is at /stt (biBusy) — the
            // old early-return made Blue DEAF during each transcription, so a
            // "stop" said while his own echo was being transcribed was lost.
            let sum = 0;
            for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
            const rms = Math.sqrt(sum / samples.length);
            const threshold = Math.max(BI_THRESHOLD_MIN, hfNoiseFloor * HF_THRESHOLD_FACTOR * BI_THRESHOLD_FACTOR);
            if (rms > threshold) {
                if (!biActive) {
                    biVoice++;
                    if (biVoice < BI_VOICE_START) return;
                    // Seed with the pre-roll so the plosive onset of "stop"
                    // (the quiet "st-" just before the loud burst) is included —
                    // without it Whisper only sees "op" and you have to yell.
                    biActive = true; biChunks = biPreroll.slice(); biSilence = 0;
                }
                biChunks.push(new Float32Array(samples));
                biSilence = 0;
                if (biChunks.length > BI_MAX_CHUNKS) bargeInFinalize();
            } else {
                biVoice = Math.max(0, biVoice - 1);
                if (biActive) {
                    biChunks.push(new Float32Array(samples));
                    biSilence++;
                    if (biSilence >= BI_SILENCE_END) bargeInFinalize();
                } else {
                    biPreroll.push(new Float32Array(samples));
                    if (biPreroll.length > BI_PREROLL_MAX) biPreroll.shift();
                }
            }
        }

        async function bargeInFinalize() {
            const chunks = biChunks;
            biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = [];
            if (chunks.length < 2) return;
            if (biBusy) { biPending = chunks; return; }   // newest clip takes the queue slot
            biBusy = true;
            try {
                let clip = chunks;
                while (clip) {
                    if (!(window.speechSynthesis && window.speechSynthesis.speaking)) break;
                    const blob = encodeWav(clip, recSampleRate);
                    const fd = new FormData(); fd.append('audio', blob, 'speech.wav');
                    fd.append('hint', 'stop');   // bias Whisper toward interrupt words
                    const res = await fetch('/stt', { method: 'POST', body: fd });
                    const data = await res.json().catch(() => null);
                    const said = ((data && data.text) || '').trim();
                    if (said && (BI_STOP.test(said) || said.toLowerCase().indexOf('stop') >= 0)) {
                        stopSpeaking('whisper');
                        break;
                    }
                    clip = biPending; biPending = null;   // transcribe what arrived meanwhile
                }
            } catch (e) { /* ignore */ }
            finally { biBusy = false; biPending = null; }
        }

        // ---- Stop speaking NOW — shared by every barge-in path ----
        function stopSpeaking(source) {
            try { window.speechSynthesis.cancel(); } catch (e) {}
            if (!isVilda) {
                try { fetch('/head/' + ROBOT.head + '/lip', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"on":false}' }); } catch (e) {}
            }
            setFaceState('');
            biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = []; biPending = null;
            if (handsFree) setHfStatus('waiting');
        }

        // ---- FAST barge-in: the browser's own speech recognition runs WHILE
        // Blue talks and cancels him the moment an interim transcript contains
        // "stop" (~half a second). The Whisper clip path above stays as the
        // fallback — it's the only path on browsers without SpeechRecognition
        // and when there's no internet for the recognition service.
        const _BI_SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
        let biRecog = null, biRecogWanted = false;
        function bargeInRecogStart() {
            biRecogWanted = true;
            if (!_BI_SR || biRecog) return;
            if (!handsFree && !audioReady) return;   // mic not in use — don't surprise-prompt
            try {
                const r = new _BI_SR();
                r.continuous = true; r.interimResults = true; r.lang = 'en-US';
                r.onresult = function (ev) {
                    if (!(window.speechSynthesis && window.speechSynthesis.speaking)) return;
                    for (let i = ev.resultIndex; i < ev.results.length; i++) {
                        const t = (ev.results[i][0] && ev.results[i][0].transcript) || '';
                        // A short utterance containing "stop": the interrupt is a
                        // word or two, while Blue's own echoed sentences run long —
                        // the length guard keeps him from silencing himself.
                        if (BI_STOP.test(t) && t.trim().split(/\\s+/).length <= 6) { stopSpeaking('speech-api'); break; }
                    }
                };
                r.onend = function () { biRecog = null; if (biRecogWanted && window.speechSynthesis.speaking) setTimeout(bargeInRecogStart, 80); };
                r.onerror = function () { /* onend follows and decides on restart */ };
                r.start(); biRecog = r;
            } catch (e) { biRecog = null; }
        }
        function bargeInRecogStop() {
            biRecogWanted = false;
            if (biRecog) { try { biRecog.stop(); } catch (e) {} biRecog = null; }
        }
        // Escape always shuts him up, mic or no mic.
        document.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && window.speechSynthesis && window.speechSynthesis.speaking) stopSpeaking('esc');
        });

        async function hfFinalize() {
            hfVoicing = false;
            hfSilence = 0;
            hfPreroll = [];
            const chunks = pcmChunks; pcmChunks = [];
            if (!chunks.length) {
                setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }
            hfProcessing = true;
            setHfStatus('thinking');
            let said = '';
            try {
                const blob = encodeWav(chunks, recSampleRate);
                const fd = new FormData(); fd.append('audio', blob, 'speech.wav');
                // In wake mode, ask the server to bias Whisper toward "Blue".
                if (hfMode !== 'conversation') fd.append('wake', '1');
                const res = await fetch('/stt', { method: 'POST', body: fd });
                const data = await res.json().catch(() => null);
                said = ((data && data.text) || '').trim();
            } catch (e) {
                hfProcessing = false;
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }

            // STT is done — release the listening lock immediately so the mic
            // is hot again while the LLM is composing the reply. TTS playback
            // suspends VAD on its own via window.speechSynthesis.speaking, so
            // Blue won't hear himself, but the user CAN speak again the moment
            // the spinner stops.
            hfProcessing = false;

            // Whisper hallucinates a small set of stock phrases on near-silence.
            if (!said || said.length < 3 || HF_HALLUC.test(said)) {
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
                return;
            }

            let message = '';
            if (hfMode === 'conversation') {
                // No wake word — the whole utterance is the message.
                message = said;
            } else {
                const rest = extractWake(said);   // null = no wake word heard
                if (rest === null) {
                    if (hfWakeArmed) {
                        // We heard a bare "Blue" a moment ago; take this as the message.
                        message = said;
                        hfWakeArmed = false;
                        if (hfArmedTimer) { clearTimeout(hfArmedTimer); hfArmedTimer = null; }
                    } else {
                        if (handsFree) setHfStatus('waiting');   // background talk → ignore
                        return;
                    }
                } else if (rest === '') {
                    // Just "Blue" alone — arm for the next utterance.
                    hfWakeArmed = true;
                    if (hfArmedTimer) clearTimeout(hfArmedTimer);
                    hfArmedTimer = setTimeout(function () {
                        hfWakeArmed = false;
                        if (handsFree) setHfStatus('waiting');
                    }, HF_ARMED_MS);
                    setHfStatus('armed');
                    return;
                } else {
                    message = rest;
                }
            }

            // Fire-and-forget the chat call. The mic stays hot so the user can
            // call "Blue" again the moment the LLM starts composing — TTS will
            // self-suspend the VAD while Blue is actually speaking. No await,
            // no follow-up window: every new turn starts with "Blue".
            setHfStatus('replying');
            inputEl.value = message;
            pendingVoice = true;
            send().finally(function () {
                if (handsFree) setHfStatus(hfWakeArmed ? 'armed' : 'waiting');
            });
        }

        const hfModeBtn = document.getElementById('hfModeBtn');

        async function toggleHandsFree() {
            if (handsFree) {
                handsFree = false;
                hfVoicing = false; hfSilence = 0; hfPreroll = []; hfWakeArmed = false;
                biActive = false; biChunks = []; biVoice = 0; biSilence = 0; biPreroll = [];
                if (hfArmedTimer) { clearTimeout(hfArmedTimer); hfArmedTimer = null; }
                hfBtn.classList.remove('active');
                hfBtn.setAttribute('aria-pressed', 'false');
                if (hfModeBtn) hfModeBtn.style.display = 'none';
                setHfStatus(null);
                return;
            }
            primeAudio();
            const ok = await ensureAudio();
            if (ok !== true) {
                addBubble('blue', 'I need permission to use the microphone. Tap once to allow it.');
                return;
            }
            handsFree = true;
            hfVoicing = false; hfSilence = 0; hfPreroll = []; pcmChunks = [];
            hfVoiceRamp = 0; hfVoicyCount = 0; hfNoiseFloor = 0.005;
            hfBtn.classList.add('active');
            hfBtn.setAttribute('aria-pressed', 'true');
            if (hfModeBtn) hfModeBtn.style.display = 'block';
            setHfStatus('waiting');
        }

        if (hfBtn) hfBtn.addEventListener('click', toggleHandsFree);
        if (hfModeBtn) hfModeBtn.addEventListener('click', function () {
            setHfMode(hfMode === 'conversation' ? 'wake' : 'conversation');
        });
        setHfMode(hfMode);   // initialise the button label from saved preference

        if (isVilda) {
            micBtn.classList.add('big');
            try { fetch('/stt/warmup'); } catch (e) {}
        }

        // ===== Blue's eyes: the iPad camera, on demand (kid mode only) =====
        // Off until she taps the eye. Each tap grabs ONE frame and asks Blue to
        // look, so normal chatting stays fast. Frames go only to the local vision
        // model via /chat/eyes (never the cloud). iOS-12 safe: getUserMedia over
        // HTTPS + a <canvas> snapshot (no MediaRecorder). No-op on Alex's page
        // (no #eyeBtn there).
        const eyeBtn = document.getElementById('eyeBtn');
        if (eyeBtn) {
          // IIFE wrapper: on iOS 12 Safari, function declarations inside a bare
          // `if {}` block get hoisted out of the block while `let`/`const` stay
          // block-scoped — so the handlers couldn't see eyeBusy/eyeStream/etc.
          // ("ReferenceError: Can't find variable: eyeBusy"). A function scope
          // fixes the hoisting so the closures resolve correctly.
          (function () {
            const eyePanel = document.getElementById('eyePanel');
            const eyeVid = document.getElementById('eyeVid');
            const eyeCanvas = document.getElementById('eyeCanvas');
            const eyeFlip = document.getElementById('eyeFlip');
            const eyeClose = document.getElementById('eyeClose');
            let eyeStream = null, eyeFacing = 'user', eyeBusy = false;

            function eyeStatus(s) { /* debug tracker removed; kept as a no-op */ }

            function eyeStop() {
                if (eyeStream) { try { eyeStream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {} }
                eyeStream = null;
                try { eyeVid.srcObject = null; } catch (e) {}
                eyePanel.classList.remove('on');
                eyeBtn.classList.remove('active');
                eyeBtn.setAttribute('aria-pressed', 'false');
            }

            function eyeStart() {
                if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                    eyeStatus('no getUserMedia (need https?)');
                    addBubble('blue', "I can't use the camera here. Make sure you opened me at my secure https web address \\u2014 the same one the microphone needs.");
                    return Promise.reject(new Error('no-getUserMedia'));
                }
                eyeStatus('requesting camera\\u2026');
                // getUserMedia must fire inside the tap gesture on iOS.
                return navigator.mediaDevices.getUserMedia({ video: { facingMode: eyeFacing }, audio: false })
                    .then(function (stream) {
                        eyeStatus('camera on');
                        eyeStream = stream;
                        eyeVid.srcObject = stream;
                        eyePanel.classList.toggle('rear', eyeFacing !== 'user');
                        eyePanel.classList.add('on');
                        eyeBtn.classList.add('active');
                        eyeBtn.setAttribute('aria-pressed', 'true');
                        try { eyeVid.play(); } catch (e) {}
                        return new Promise(function (resolve) {
                            if (eyeVid.videoWidth > 0) { resolve(); return; }
                            eyeVid.addEventListener('loadedmetadata', function () { resolve(); }, { once: true });
                            setTimeout(resolve, 1200);
                        });
                    });
            }

            function eyeCapture() {
                const w = eyeVid.videoWidth, h = eyeVid.videoHeight;
                eyeStatus('capturing ' + w + 'x' + h);
                if (!w || !h) return null;
                const scale = Math.min(1, 640 / w);
                eyeCanvas.width = Math.round(w * scale);
                eyeCanvas.height = Math.round(h * scale);
                eyeCanvas.getContext('2d').drawImage(eyeVid, 0, 0, eyeCanvas.width, eyeCanvas.height);
                return eyeCanvas.toDataURL('image/jpeg', 0.7);
            }

            function dataUrlToBlob(durl) {
                const bin = atob(durl.split(',')[1]);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                return new Blob([arr], { type: 'image/jpeg' });
            }

            function eyeUpload(durl) {
                eyeStatus('uploading frame\\u2026');
                const fd = new FormData();
                fd.append('frame', dataUrlToBlob(durl), 'eyes.jpg');
                return fetch('/chat/eyes', { method: 'POST', headers: { 'X-Blue-Device': blueDeviceTag() }, body: fd })
                    .then(function (res) {
                        if (!res || !res.ok) { throw new Error('upload HTTP ' + (res ? res.status : '?')); }
                        eyeStatus('sent to Blue');
                        return res;
                    });
            }

            // Grab+upload a frame IF the camera is open; called before every chat
            // send (via window.__blueEyeGrab) so Blue sees during the WHOLE
            // conversation, not just on the eye tap. No-op when the camera is shut.
            function grabIfOpen() {
                if (!eyeStream) return Promise.resolve(null);
                const durl = eyeCapture();
                if (!durl) return Promise.resolve(null);
                return eyeUpload(durl);
            }
            window.__blueEyeGrab = grabIfOpen;

            // Tap the eye = "Blue, look!" Starts the camera the first time, grabs
            // a frame, then sends a turn so Blue reacts to what he sees right now.
            // Turns the eye pink the INSTANT it's tapped (so a tap is always
            // visibly registered even before the camera opens), and surfaces ANY
            // camera error as a chat bubble so a silent failure can't look like
            // "nothing happened". Note: only gated on eyeBusy, not the chat's
            // `busy`, so a slow reply can't make the eye feel dead.
            function eyeLook() {
                if (eyeBusy) return;
                eyeBusy = true;
                eyeBtn.classList.add('active');
                eyeStatus('tapped');
                primeAudio();
                const go = eyeStream ? Promise.resolve() : eyeStart();
                go.then(function () {
                    // Camera is open now; send() grabs the frame via __blueEyeGrab.
                    if (!inputEl.value.trim()) inputEl.value = 'Look, Blue!';
                    send();
                }).catch(function (e) {
                    const nm = (e && e.name && e.name !== 'Error') ? e.name
                             : ((e && e.message) ? e.message : String(e));
                    eyeStatus('ERROR: ' + nm);
                    if (nm === 'NotAllowedError' || nm === 'SecurityError') {
                        addBubble('blue', "I'm not allowed to use the camera yet. Tap the eye and choose Allow \\u2014 a grown-up may need to switch the Camera on in Settings (Screen Time).");
                    } else if (nm === 'NotFoundError') {
                        addBubble('blue', "I can't find a camera on this tablet.");
                    } else {
                        addBubble('blue', 'My eyes would not open just now (' + nm + '). Tap the eye to try again.');
                    }
                    eyeStop();
                }).then(function () { eyeBusy = false; }, function () { eyeBusy = false; });
            }

            eyeBtn.addEventListener('click', eyeLook);
            eyeClose.addEventListener('click', eyeStop);
            eyeFlip.addEventListener('click', function () {
                eyeFacing = (eyeFacing === 'user') ? 'environment' : 'user';
                const wasOn = !!eyeStream;
                eyeStop();
                if (wasOn) eyeStart().catch(function () {});
            });
            window.addEventListener('pagehide', function () { eyeStop(); });
          })();
        }

        inputEl.focus();
    </script>
</body>
</html>
"""


# ===== Speech-to-text (server side) =====
# iOS Safari won't reliably expose the in-browser Web Speech API, so the iPad
# records audio (getUserMedia/MediaRecorder over HTTPS) and posts it here; we
# transcribe locally with faster-whisper. CPU int8 is plenty for short clips.
# Override the model with BLUE_WHISPER_MODEL (e.g. "small.en" for more accuracy).
import threading as _threading_stt
_WHISPER_MODEL = None
_WHISPER_LOCK = _threading_stt.Lock()


def _get_whisper():
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        with _WHISPER_LOCK:
            if _WHISPER_MODEL is None:
                from faster_whisper import WhisperModel
                # Multilingual model (NOT a .en model) so Blue understands
                # English, French, Russian, Greek and Danish. "base" is the speed
                # sweet spot on CPU: ~0.6s/clip vs ~1.9s for "small", with English
                # still perfect and multilingual solid. Override BLUE_WHISPER_MODEL:
                # "small"/"medium" = more accurate/slower, "tiny" = fastest/least.
                name = (os.environ.get("BLUE_WHISPER_MODEL") or "base").strip()
                print(f"   [STT] Loading Whisper model '{name}' (first use)...")
                _WHISPER_MODEL = WhisperModel(name, device="cpu", compute_type="int8")
                print("   [STT] Whisper model ready.")
    return _WHISPER_MODEL


@app.route('/stt/warmup', methods=['GET', 'POST'])
def stt_warmup():
    """Load the model in the background so the first real transcription isn't
    slow. Fire-and-forget — returns immediately."""
    def _warm():
        try:
            _get_whisper()
        except Exception as e:
            log.warning(f"[STT] warmup failed: {e}")
    _threading_stt.Thread(target=_warm, daemon=True).start()
    return jsonify({"ok": True})


@app.route('/stt', methods=['POST'])
def stt():
    """Transcribe an uploaded audio clip to text."""
    import tempfile
    f = request.files.get('audio')
    if not f or not f.filename:
        return jsonify({"error": "no audio"}), 400
    ext = os.path.splitext(f.filename)[1] or ".m4a"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_path = tmp.name
    tmp.close()
    # Hands-free wake mode sends wake=1 so we bias Whisper toward the name
    # "Blue" — it otherwise transcribes the short leading word as "Blew/Blu/Boo"
    # and the wake match fails. hotwords nudges without forcing it into output.
    wake = (request.form.get('wake') or '') in ('1', 'true', 'yes')
    # hint=stop is sent by barge-in while Blue is talking — bias toward interrupt
    # words, NOT "Blue" (the old bug primed Whisper against hearing "stop").
    hint = (request.form.get('hint') or '').strip().lower()
    try:
        f.save(tmp_path)
        model = _get_whisper()
        # beam_size=1 (greedy) and no cross-clip conditioning: both fastest and
        # best for short, independent voice commands.
        kwargs = {"beam_size": 1, "condition_on_previous_text": False}
        if hint == 'stop':
            kwargs["hotwords"] = "stop. stop. stop!"   # bias hard toward just "stop"
            kwargs["language"] = "en"   # sub-second clip: auto-detect is slow and flaky
        elif wake:
            kwargs["hotwords"] = "Blue"
        # No fixed language: Whisper auto-detects (English/French/Russian/Greek…).
        segments, info = model.transcribe(tmp_path, **kwargs)
        text = " ".join(seg.text for seg in segments).strip()
        lang = getattr(info, "language", "") or ""
        print(f"   [STT] ({lang}{',wake' if wake else ''}) {os.path.getsize(tmp_path)} bytes -> {text[:120]!r}")
        return jsonify({"text": text, "language": lang})
    except Exception as e:
        log.error(f"[STT] transcription failed: {e}")
        return jsonify({"error": "transcription failed"}), 500
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


@app.route('/camera/stream')
def camera_stream():
    """MJPEG live view of the robot camera — the chat page's 'see through my
    eyes' preview. Holding this open keeps the camera hub alive; it releases
    itself shortly after the last viewer disconnects."""
    if not _cam_hub_start():
        return jsonify({"error": "camera unavailable"}), 503
    import time as _t

    def gen():
        while True:
            with _CAM_HUB["lock"]:
                _CAM_HUB["last_pull"] = _t.time()
                jpeg = _CAM_HUB["jpeg"]
                alive = _CAM_HUB["cap"] is not None
            if not alive:
                break
            if jpeg:
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
            _t.sleep(0.12)

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame',
                    headers={"Cache-Control": "no-store"})


@app.route('/camera/ptz', methods=['POST'])
def camera_ptz():
    """Steer the live preview CAMERA itself — not the robot's head. The BRIO
    pans/tilts by shifting its zoom window inside the sensor, so panning only
    shows an effect while zoomed in; a pan request at 1x zooms to 2x first.
    Empirical BRIO mapping (verified by template-matching captures): pan + =
    window right, tilt + = window up, range -10..10 spans the sensor.
    The head still turns via chat ("look left") — just not from this pad."""
    import cv2
    d = request.get_json(silent=True) or {}
    look = (d.get('look') or '').strip().lower()
    if not _cam_hub_start():
        return jsonify({"ok": False, "error": "camera unavailable"})
    out = {"ok": True}
    with _CAM_HUB["lock"]:
        cap = _CAM_HUB["cap"]
        if cap is None:
            return jsonify({"ok": False, "error": "camera unavailable"})
        if d.get('zoom') is not None:
            try:
                want = max(1.0, min(4.0, float(d['zoom'])))
            except (TypeError, ValueError):
                want = 1.0
            _CAM_HUB["zoom"] = _set_camera_hardware_zoom(cap, want)
            if want <= 1.01:
                # Fully zoomed out: a leftover window offset just crops oddly.
                try:
                    cap.set(cv2.CAP_PROP_PAN, 0)
                    cap.set(cv2.CAP_PROP_TILT, 0)
                except Exception:
                    pass
        if look:
            if look != 'center' and _CAM_HUB["zoom"] <= 1.01:
                _CAM_HUB["zoom"] = _set_camera_hardware_zoom(cap, 2.0)
            step = 2.0
            try:
                if look == 'center':
                    cap.set(cv2.CAP_PROP_PAN, 0)
                    cap.set(cv2.CAP_PROP_TILT, 0)
                elif look in ('left', 'right'):
                    cur = cap.get(cv2.CAP_PROP_PAN)
                    cap.set(cv2.CAP_PROP_PAN,
                            max(-10.0, min(10.0, cur + (step if look == 'right' else -step))))
                elif look in ('up', 'down'):
                    cur = cap.get(cv2.CAP_PROP_TILT)
                    cap.set(cv2.CAP_PROP_TILT,
                            max(-10.0, min(10.0, cur + (step if look == 'up' else -step))))
            except Exception:
                pass
        try:
            out["pan"] = cap.get(cv2.CAP_PROP_PAN)
            out["tilt"] = cap.get(cv2.CAP_PROP_TILT)
        except Exception:
            pass
        out["zoom"] = _CAM_HUB["zoom"]
    return jsonify(out)


def _render_chat_page(robot="blue"):
    """Serve a robot's text chat GUI (Blue at /chat, Hexia at /hexia). The same
    CHAT_HTML template is parametrised per robot: name, accent, voice and which
    head its lip-sync drives."""
    cfg = _robot_cfg(robot)
    # No-cache headers: iOS Safari was serving a stale cached copy of this page,
    # so new client fixes never reached the iPad. Force a fresh fetch each time.
    kid = False
    try:
        kid = _identify_user_from_request() in _CHAT_ONLY_USERS
    except Exception:
        pass
    try:
        hf_sens = float(blue_head.get_head(robot).get_calibration().get("hf_sensitivity", 5))
    except Exception:
        hf_sens = 5.0
    robot_js = {
        "id": robot,
        "name": cfg["name"],
        "head": cfg["head"],
        "accent": cfg["accent"],
        "voicePitch": cfg.get("voice_pitch", 1.0),
        "voiceRate": cfg.get("voice_rate", 1.0),
        "preferFemale": bool(cfg.get("voice_prefer_female", False)),
    }
    html = render_template_string(
        CHAT_HTML, kid=kid, hf_sens=hf_sens,
        robot_name=cfg["name"], robot_json=json.dumps(robot_js),
    )
    return Response(html, headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.route('/chat', methods=['GET'])
def chat_page():
    """Serve Blue's text chat GUI."""
    return _render_chat_page("blue")


@app.route('/hexia', methods=['GET'])
def hexia_chat_page():
    """Serve Hexia's text chat GUI — her own persona, voice and head."""
    return _render_chat_page("hexia")


# ============================ Phase 3: the duet ============================
# Blue and Hexia hold a short conversation, taking turns. The browser drives it
# turn-by-turn: it asks /duet/turn for the next line, then speaks it in that
# robot's voice while driving that robot's head lip-sync, then alternates.

DUET_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blue &amp; Hexia — Let them talk</title>
<style>
 :root{ --bluec:#3da9fc; --hexiac:#b06cf0; }
 body{font-family:-apple-system,'Segoe UI',sans-serif;background:#faf8f4;color:#1a2e1a;max-width:760px;margin:0 auto;padding:26px 18px;line-height:1.5}
 h1{font-size:1.5em;margin-bottom:4px}
 p.sub{color:#64748b;margin-bottom:16px;font-size:.95em}
 .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
 input[type=text]{flex:1;min-width:200px;padding:10px 12px;border:1px solid #cfc9bd;border-radius:8px;font:inherit}
 select,button{padding:9px 13px;border:1px solid #cfc9bd;border-radius:8px;background:#fff;font:inherit;cursor:pointer}
 button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
 button:disabled{opacity:.5;cursor:default}
 .muted{color:#64748b;font-size:.9em}
 #log{display:flex;flex-direction:column;gap:10px;margin-top:12px}
 .turn{padding:10px 14px;border-radius:14px;max-width:84%;box-shadow:0 1px 3px rgba(0,0,0,.06)}
 .turn .who{font-size:.7em;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:3px}
 .turn.blue{align-self:flex-start;background:#eaf4ff;border:1px solid #cfe4fb}
 .turn.blue .who{color:var(--bluec)}
 .turn.hexia{align-self:flex-end;background:#f4ecfc;border:1px solid #e6d6f7}
 .turn.hexia .who{color:var(--hexiac)}
 .turn.speaking{box-shadow:0 0 0 2px currentColor}
 .srcbox{border:1px solid #cfc9bd;border-radius:8px;padding:8px;max-height:180px;overflow:auto;background:#fff;font-size:.9em}
 .srcbox .fold{font-size:.72em;text-transform:uppercase;letter-spacing:.06em;color:#4a6b4a;margin:7px 0 3px;font-weight:600}
 .srcbox .fold:first-child{margin-top:0}
 .srcbox label{display:flex;gap:7px;align-items:flex-start;padding:3px 0;cursor:pointer}
 .srcbox input{margin-top:3px;flex:none}
 .srccount{font-size:.8em;color:#64748b}
</style></head><body>
<h1>Blue &amp; Hexia</h1>
<p class="sub">Give them a topic or a link to discuss, or assign each one a role or perspective to argue &mdash; then watch them go. Each speaks in their own voice and moves their own head, taking turns. (Both heads connected works best; if a head is off it just won't move.)</p>
<div class="controls">
 <input type="text" id="topic" placeholder="Topic (optional) — e.g. what makes a good story">
</div>
<div class="controls">
 <input type="text" id="url" placeholder="Link (optional) — paste an article or YouTube URL for them to discuss">
</div>
<div class="controls">
 <input type="text" id="roleBlue" placeholder="Blue's role / perspective (optional) — e.g. argue cities beat small towns">
 <input type="text" id="roleHexia" placeholder="Hexia's role / perspective (optional) — e.g. a sceptical detective">
</div>
<div class="controls">
 <input type="text" id="toneBlue" placeholder="Blue's tone (optional) — e.g. dry and sardonic">
 <input type="text" id="toneHexia" placeholder="Hexia's tone (optional) — e.g. bubbly and dramatic">
</div>
<div class="controls">
 <input type="text" id="slangBlue" placeholder="Blue's slang / dialect (optional) — e.g. 1920s slang">
 <input type="text" id="slangHexia" placeholder="Hexia's slang / dialect (optional) — e.g. Gen Z slang">
</div>
<div class="controls">
 <div style="flex:1;display:flex;flex-direction:column;gap:5px">
  <span class="muted">Blue draws on — tick any number (<span class="srccount" id="cntBlue">0</span> selected)</span>
  <div id="sourcesBlue" class="srcbox" style="border-color:#cfe4fb"></div>
 </div>
 <div style="flex:1;display:flex;flex-direction:column;gap:5px">
  <span class="muted">Hexia draws on — tick any number (<span class="srccount" id="cntHexia">0</span> selected)</span>
  <div id="sourcesHexia" class="srcbox" style="border-color:#e6d6f7"></div>
 </div>
</div>
<div class="controls">
 <select id="turns"><option value="4">4 turns</option><option value="6" selected>6 turns</option><option value="8">8 turns</option><option value="10">10 turns</option><option value="20">20 turns</option><option value="0">until I stop</option></select>
 <select id="starter"><option value="hexia">Hexia starts</option><option value="blue">Blue starts</option></select>
 <button class="primary" id="startBtn">Start</button>
 <button id="stopBtn" disabled>Stop</button>
 <label class="muted"><input type="checkbox" id="speakChk" checked> speak aloud</label>
</div>
<div id="log"></div>
<script>
const ROBOTS = {{ robots_json|safe }};
const DOCS = {{ documents_json|safe }};
(function(){
  var byF={}; DOCS.forEach(function(d){ var f=d.folder||'(root)'; (byF[f]=byF[f]||[]).push(d.filename); });
  var counts={sourcesBlue:'cntBlue', sourcesHexia:'cntHexia'};
  ['sourcesBlue','sourcesHexia'].forEach(function(id){
    var box=document.getElementById(id); if(!box) return;
    Object.keys(byF).forEach(function(f){
      var h=document.createElement('div'); h.className='fold'; h.textContent=f; box.appendChild(h);
      byF[f].forEach(function(fn){
        var lab=document.createElement('label');
        var cb=document.createElement('input'); cb.type='checkbox'; cb.value=fn;
        var sp=document.createElement('span'); sp.textContent=fn;
        lab.appendChild(cb); lab.appendChild(sp); box.appendChild(lab);
      });
    });
    box.addEventListener('change', function(){
      var n=box.querySelectorAll('input:checked').length;
      var c=document.getElementById(counts[id]); if(c) c.textContent=n;
    });
  });
})();
function selVals(id){ var box=document.getElementById(id); if(!box) return [];
  return Array.prototype.slice.call(box.querySelectorAll('input:checked')).map(function(c){return c.value;}); }
function SOURCES(){ return { blue: selVals('sourcesBlue'), hexia: selVals('sourcesHexia') }; }
function fieldMap(prefix){ var g=function(id){var e=document.getElementById(id);return e?(e.value||'').trim():'';}; return { blue:g(prefix+'Blue'), hexia:g(prefix+'Hexia') }; }
let running=false, history=[];
const logEl=document.getElementById('log');
const startBtn=document.getElementById('startBtn'), stopBtn=document.getElementById('stopBtn');

function cleanForSpeech(t){ return (t||'').replace(/https?:\\/\\/\\S+/g,' a link ').replace(/[\\u{1F000}-\\u{1FFFF}\\u{2600}-\\u{27BF}]/gu,'').replace(/[*_#>~]/g,'').replace(/\\s+/g,' ').trim(); }
function buildLipFrames(text, rate){
  rate=rate||1.0; const k=1.0/rate; const words=(text.match(/[^\\s]+/g)||[]); const frames=[]; const MPC=0.060;
  for(const w of words){ const core=w.replace(/[^A-Za-z0-9\\u00C0-\\u024F]/g,''); const len=Math.max(1,core.length);
    const dur=Math.min(0.75,Math.max(0.14,len*MPC))*k; const moves=Math.max(1,Math.round(len/3)); const per=dur/moves;
    for(let i=0;i<moves;i++){ frames.push([0.6+Math.random()*0.4, per*0.6]); frames.push([0.1, per*0.4]); }
    const last=w.slice(-1); let gap=0.06; if(/[,;:)\\]]/.test(last))gap=0.22; else if(/[.!?]/.test(last))gap=0.40; frames.push([0.0,gap*k]); }
  return frames;
}
const MALE=['Daniel','Aaron','Arthur','Gordon','Microsoft David','Microsoft Mark','Google UK English Male','Google US English'];
const FEMALE=['Samantha','Victoria','Karen','Moira','Tessa','Serena','Microsoft Zira','Google UK English Female','Google US English'];
function pickVoice(cfg){
  const voices=(window.speechSynthesis&&window.speechSynthesis.getVoices())||[];
  let chosen=''; try{ chosen=localStorage.getItem('blueVoiceName_'+cfg.id)||(cfg.id==='blue'?(localStorage.getItem('blueVoiceName')||''):''); }catch(e){}
  if(chosen){ const c=voices.find(v=>v.name===chosen); if(c)return c; }
  const pl=cfg.preferFemale?FEMALE:MALE;
  for(const n of pl){ const v=voices.find(x=>x.name===n||x.name.indexOf(n)===0); if(v)return v; }
  return voices.find(x=>/^en/i.test(x.lang))||null;
}
function headLip(cfg,frames){ try{ fetch('/head/'+cfg.head+'/lip-seq',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frames:frames})}); }catch(e){} }
function headLipStop(cfg){ try{ fetch('/head/'+cfg.head+'/lip',{method:'POST',headers:{'Content-Type':'application/json'},body:'{"on":false}'}); }catch(e){} }

function addTurn(cfg,text){ const d=document.createElement('div'); d.className='turn '+cfg.id;
  const w=document.createElement('div'); w.className='who'; w.textContent=cfg.name;
  const x=document.createElement('div'); x.textContent=text; d.appendChild(w); d.appendChild(x);
  logEl.appendChild(d); window.scrollTo(0,document.body.scrollHeight); return d; }

function speakAs(cfg,text,el){ return new Promise(resolve=>{
  const useTTS=document.getElementById('speakChk').checked && ('speechSynthesis' in window);
  const frames=buildLipFrames(text, cfg.voiceRate||1.0);
  const est=frames.reduce((s,f)=>s+f[1],0)*1000;   // ~speech duration (ms)
  let done=false, keepAlive=null;
  const finish=()=>{ if(done)return; done=true; if(keepAlive){clearInterval(keepAlive);keepAlive=null;} headLipStop(cfg); if(el)el.classList.remove('speaking'); resolve(); };
  if(el)el.classList.add('speaking'); headLip(cfg,frames);
  if(!useTTS){ setTimeout(finish, Math.max(1500, est+400)); return; }   // no audio: wait out the lip-flap
  try{
    window.speechSynthesis.cancel();
    const u=new SpeechSynthesisUtterance(cleanForSpeech(text));
    const v=pickVoice(cfg); if(v)u.voice=v; u.rate=cfg.voiceRate||1.0; u.pitch=cfg.voicePitch||1.0; u.lang='en-US';
    u.onend=finish; u.onerror=finish;
    window.speechSynthesis.speak(u);
    // Chrome silently stops utterances after ~15s; pause+resume keeps long
    // points going to the end instead of cutting the speaker off.
    keepAlive=setInterval(function(){
      if(!window.speechSynthesis.speaking){ if(keepAlive){clearInterval(keepAlive);keepAlive=null;} }
      else { try{ window.speechSynthesis.pause(); window.speechSynthesis.resume(); }catch(e){} }
    }, 9000);
    // Hard safety so a stuck utterance can't hang the duet — generous and
    // length-based so it never fires before a normal reply finishes.
    setTimeout(finish, Math.max(20000, est*2.2 + 8000));
  }catch(e){ finish(); }
}); }

async function oneTurn(speaker){
  const topic=document.getElementById('topic').value.trim();
  const url=document.getElementById('url').value.trim();
  let d; try{ d=await (await fetch('/duet/turn',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({speaker:speaker, topic:topic, url:url, history:history, sources:SOURCES(), roles:fieldMap('role'), tones:fieldMap('tone'), slang:fieldMap('slang')})})).json(); }catch(e){ return false; }
  if(!d||!d.text){ return false; }
  const cfg=ROBOTS[speaker]; const el=addTurn(cfg,d.text); history.push({speaker:speaker, text:d.text});
  await speakAs(cfg,d.text,el); return true;
}
async function run(){
  running=true; history=[]; logEl.innerHTML=''; startBtn.disabled=true; stopBtn.disabled=false;
  // A bare link pasted into the topic box IS the link — move it over visibly.
  const topicEl=document.getElementById('topic'), urlEl=document.getElementById('url');
  if(!urlEl.value.trim() && /^https?:\\/\\/\\S+$/.test(topicEl.value.trim())){ urlEl.value=topicEl.value.trim(); topicEl.value=''; }
  const url=urlEl.value.trim();
  if(url){
    addNote('(reading the link…)');
    let r=null;
    try{ r=await (await fetch('/duet/fetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url})})).json(); }catch(e){}
    if(!running){ return; }
    if(!r||!r.ok){ addNote("(couldn't read that link"+(r&&r.error?': '+r.error:'')+" — fix it or clear the field)"); stop(); return; }
    addNote("(they've "+(r.kind==='video'?'watched':'read')+': '+(r.title||url)+')');
  }
  let turns=parseInt(document.getElementById('turns').value,10); if(isNaN(turns))turns=6;   // 0 = until you press Stop
  let speaker=document.getElementById('starter').value;
  for(let i=0; running && (turns===0 || i<turns); i++){ const ok=await oneTurn(speaker); if(!ok){ addNote(ok===false?'(…lost the thread — is LM Studio running?)':''); break; } speaker=(speaker==='blue')?'hexia':'blue'; }
  stop();
}
function addNote(t){ if(!t)return; const d=document.createElement('div'); d.className='muted'; d.textContent=t; logEl.appendChild(d); }
function stop(){ running=false; try{ window.speechSynthesis.cancel(); }catch(e){} headLipStop(ROBOTS.blue); headLipStop(ROBOTS.hexia); startBtn.disabled=false; stopBtn.disabled=true; }
startBtn.addEventListener('click', run);
stopBtn.addEventListener('click', stop);
if('speechSynthesis' in window){ try{ window.speechSynthesis.onvoiceschanged=function(){ window.speechSynthesis.getVoices(); }; }catch(e){} }
</script></body></html>"""


def _duet_robots_js():
    out = {}
    for rid in ("blue", "hexia"):
        c = _robot_cfg(rid)
        out[rid] = {
            "id": rid, "name": c["name"], "head": c["head"], "accent": c["accent"],
            "voicePitch": c.get("voice_pitch", 1.0), "voiceRate": c.get("voice_rate", 1.0),
            "preferFemale": bool(c.get("voice_prefer_female", False)),
        }
    return json.dumps(out)


def _duet_documents():
    """Library documents (filename + folder) for the duet source picker —
    excludes camera captures; de-duplicated by filename, sorted by folder/name."""
    out, seen = [], set()
    try:
        for d in load_document_index().get('documents', []):
            if d.get('doc_type') == 'camera' or str(d.get('filename', '')).startswith('camera_'):
                continue
            fn = (d.get('filename') or '').strip()
            if not fn or fn in seen:
                continue
            seen.add(fn)
            out.append({"filename": fn, "folder": _safe_rel_folder(d.get('folder', '')) or ""})
    except Exception:
        pass
    out.sort(key=lambda x: (x["folder"].lower(), x["filename"].lower()))
    return out


# --- Link grounding: paste a URL (a web article or a YouTube video) and the
# duet discusses what it actually says. Fetched ONCE and cached; each turn gets
# the lede plus the slice most relevant to what was just said, so long pages
# stay usable in a tight prompt.

_DUET_URL_CACHE: Dict[str, dict] = {}
_DUET_URL_TTL = 3600           # re-fetch after an hour; stable within one duet
_DUET_URL_MAX_TEXT = 20000     # keep at most this much article/transcript text

_YT_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?(?:[^#\s]*&)?v=|shorts/|embed/|live/)|youtu\.be/)'
    r'([A-Za-z0-9_-]{11})')


def _youtube_title(video_id: str):
    """Video title + channel via YouTube's keyless oEmbed endpoint."""
    from urllib.parse import quote_plus
    try:
        _, content = _safe_fetch_url(
            "https://www.youtube.com/oembed?format=json&url="
            + quote_plus(f"https://www.youtube.com/watch?v={video_id}"), timeout=8)
        j = json.loads(content.decode('utf-8', errors='ignore'))
        t = (j.get('title') or '').strip()
        a = (j.get('author_name') or '').strip()
        return f"{t} — {a}" if t and a else (t or None)
    except Exception:
        return None


def _fetch_youtube_transcript(video_id: str):
    """(text, error) — captions via youtube-transcript-api, tolerating both its
    1.x instance API and the old 0.6 classmethods."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None, "youtube-transcript-api is not installed (pip install youtube-transcript-api)"

    def _join(snippets):
        parts = []
        for s in snippets:
            t = getattr(s, 'text', None)
            if t is None and isinstance(s, dict):
                t = s.get('text')
            if t:
                parts.append(t)
        return re.sub(r'\s+', ' ', ' '.join(parts)).strip()

    langs = ['en', 'en-US', 'en-GB']
    try:
        try:
            snippets = YouTubeTranscriptApi().fetch(video_id, languages=langs)
        except AttributeError:
            snippets = YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
        txt = _join(snippets)
        return (txt, None) if txt else (None, "the video's transcript is empty")
    except Exception as e:
        # No English captions — take whatever language the video does have.
        try:
            try:
                listing = YouTubeTranscriptApi().list(video_id)
            except AttributeError:
                listing = YouTubeTranscriptApi.list_transcripts(video_id)
            txt = _join(next(iter(listing)).fetch())
            if txt:
                return txt, None
        except Exception:
            pass
        return None, f"no transcript/captions available ({e.__class__.__name__})"


def _extract_article_text(html_raw: str):
    """(title, text) — the main readable text of a page. Prefers <article>/<main>
    paragraphs via bs4 (skips nav/menu cruft); falls back to the plain stripper."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_raw, 'html.parser')
        title = (soup.title.string or '').strip() if (soup.title and soup.title.string) else None
        for tag in soup(['script', 'style', 'noscript', 'nav', 'header', 'footer',
                         'aside', 'form', 'iframe', 'svg', 'button', 'figure']):
            tag.decompose()
        root = soup.find('article') or soup.find('main') or soup.body or soup
        paras = [p.get_text(' ', strip=True) for p in root.find_all(['p', 'h1', 'h2', 'h3'])]
        text = '\n'.join(p for p in paras if len(p) > 30)
        if len(text) < 400:            # paragraph-poor page: fall back to all of its text
            text = root.get_text(' ', strip=True)
        return title, re.sub(r'[ \t]+', ' ', text).strip()
    except Exception:
        return None, _clean_html_to_text(html_raw, max_chars=_DUET_URL_MAX_TEXT)


def _duet_url_content(url: str):
    """What the pasted link says: YouTube → transcript, anything else → article
    text. Cached so per-turn calls don't refetch (failures retry after 2 min).
    Returns {'kind','title','text','error'}; empty text ⇒ unusable, see error."""
    import time as _t
    u = (url or '').strip()
    if not u:
        return None
    hit = _DUET_URL_CACHE.get(u)
    if hit and _t.time() - hit['at'] < (_DUET_URL_TTL if hit.get('text') else 120):
        return hit
    info = {'kind': 'article', 'title': None, 'text': '', 'error': None, 'at': _t.time()}
    try:
        m = _YT_ID_RE.search(u)
        if m:
            info['kind'] = 'video'
            info['title'] = _youtube_title(m.group(1))
            txt, err = _fetch_youtube_transcript(m.group(1))
            info['text'], info['error'] = (txt or '')[:_DUET_URL_MAX_TEXT], err
        else:
            ctype, content = _safe_fetch_url(u)
            raw = content.decode('utf-8', errors='ignore')
            if 'html' in (ctype or '').lower() or raw.lstrip()[:1] == '<':
                info['title'], text = _extract_article_text(raw)
                info['text'] = text[:_DUET_URL_MAX_TEXT]
            else:
                info['text'] = raw[:_DUET_URL_MAX_TEXT]     # plain text page / feed
        if not info['error'] and len(info['text']) < 200:
            info['text'] = ''
            info['error'] = "couldn't extract readable text from that page"
    except Exception as e:
        info['error'] = f"couldn't fetch the link ({e.__class__.__name__}: {e})"
    if len(_DUET_URL_CACHE) >= 8:
        _DUET_URL_CACHE.clear()
    _DUET_URL_CACHE[u] = info
    return info


def _duet_url_excerpt(text: str, query: str, lede: int = 2000, win: int = 1400) -> str:
    """The lede plus the slice of the article/transcript most relevant to the
    last couple of turns — lets the discussion roam across a long page without
    ever stuffing the whole thing into the prompt."""
    text = (text or '').strip()
    if len(text) <= lede + win + 300:
        return text
    head, rest = text[:lede], text[lede:]
    words = {w.lower() for w in re.findall(r'[A-Za-zÀ-ɏ]{4,}', query or '')}
    best_off, best_score = -1, 1       # need ≥2 keyword hits to add a slice
    step = max(200, win // 2)
    for off in range(0, len(rest) - win + 1, step):
        seg = rest[off:off + win].lower()
        score = sum(seg.count(w) for w in words)
        if score > best_score:
            best_score, best_off = score, off
    if best_off < 0:
        return head + " …"
    return head + "\n[…]\n" + rest[best_off:best_off + win] + (" …" if best_off + win < len(rest) else "")


@app.route('/duet', methods=['GET'])
def duet_page():
    """The 'let them talk' page — Blue and Hexia converse, both heads taking turns."""
    return Response(render_template_string(
        DUET_HTML, robots_json=_duet_robots_js(), documents_json=json.dumps(_duet_documents()),
    ), headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    })


@app.route('/duet/fetch', methods=['POST'])
def duet_fetch():
    """Pre-read a pasted link (article text / YouTube transcript) before the
    duet starts — warms the cache and tells the page what they 'read', or why
    the link is unusable, instead of opening with two clueless robots."""
    d = request.get_json(silent=True) or {}
    url = (d.get('url') or '').strip()
    if not url:
        return jsonify({"ok": False, "error": "no url given"})
    info = _duet_url_content(url) or {}
    if not (info.get('text') or '').strip():
        return jsonify({"ok": False, "error": info.get('error') or "couldn't read the link"})
    return jsonify({"ok": True, "kind": info.get('kind'), "title": info.get('title') or "",
                    "chars": len(info['text'])})


@app.route('/duet/turn', methods=['POST'])
def duet_turn():
    """Generate ONE turn of a Blue<->Hexia conversation, in the speaker's voice/
    character. The browser calls this alternately and plays each line on the
    matching head."""
    d = request.get_json(silent=True) or {}
    speaker = (d.get('speaker') or 'blue').strip().lower()
    if speaker not in ROBOTS:
        speaker = 'blue'
    other = 'hexia' if speaker == 'blue' else 'blue'
    topic = (d.get('topic') or '').strip()
    url = (d.get('url') or '').strip()
    if not url and re.match(r'^https?://\S+$', topic):
        url, topic = topic, ''     # a bare link typed into the topic box IS the link
    history = d.get('history') or []
    roles = d.get('roles') or {}
    role_self = (roles.get(speaker) or '').strip()
    role_other = (roles.get(other) or '').strip()
    tones = d.get('tones') or {}
    slangs = d.get('slang') or {}
    tone_self = (tones.get(speaker) or '').strip() if isinstance(tones, dict) else ''
    slang_self = (slangs.get(speaker) or '').strip() if isinstance(slangs, dict) else ''
    # Sources are per-robot so Blue and Hexia can draw on DIFFERENT documents
    # (→ different perspectives). Accept a {blue:[...], hexia:[...]} map; a flat
    # list is treated as shared, for back-compat.
    sources_in = d.get('sources') or {}
    if isinstance(sources_in, list):
        src_self = [str(s).strip() for s in sources_in if str(s).strip()]
    else:
        src_self = [str(s).strip() for s in (sources_in.get(speaker) or []) if str(s).strip()]
    sp, ot = _robot_cfg(speaker), _robot_cfg(other)
    has_roles = bool(role_self or role_other)
    url_info = _duet_url_content(url) if url else None
    url_text = (url_info or {}).get('text') or ''
    url_is_video = bool(url_info and url_info.get('kind') == 'video')
    focused = bool(has_roles or topic or src_self or url_text)

    # SYSTEM: identity + memory + voice + global rules. The TASK for this turn
    # (topic, role, sources, "answer their last point, no greetings") goes in
    # the USER message below — this model follows the user instruction far more
    # reliably than anything buried in a long system prompt. For a focused
    # discussion we drop the long self-profile, which otherwise pulls them into
    # personal small talk and off the subject; plain chats keep it for colour.
    #
    # The duet speaker is the SAME robot as in chat: the ground-truth household
    # facts (who everyone is) and the current date come first, and the chat
    # memory stores are consulted below — not a blank stage actor with only a
    # persona line.
    sys_p = (build_system_preamble(robot_name=sp["name"])
             + "\n\n" + _build_now_block()
             + "\n\n" + sp["persona_line"])
    if not focused:
        sys_p += _voice_note(speaker)
    sys_p += (
        f"\n\nYou and {ot['name']} — another robot in Alex's home, and your friend — are talking out "
        "loud, taking turns. Alex isn't part of this conversation right now, but you both know him "
        "and the household, and everything you remember is real — draw on it naturally when it's "
        "relevant. Reply with ONLY your own next spoken line: 1 to 3 short, natural sentences "
        "in your own voice. Never narrate actions or stage directions, never prefix your name, and don't "
        "repeat what was already said."
    )

    # Long-term memory, same stores the chat persona draws on: Alex's explicit
    # "remember this" notes always; plus memories semantically relevant to the
    # topic and the last couple of turns.
    mem_query = (f"{topic} " + " ".join((h.get('text') or '') for h in history[-2:])).strip()
    try:
        if ENHANCED_MEMORY_AVAILABLE and memory_system:
            notes_block = memory_system._build_user_notes_block()
            if notes_block:
                sys_p += "\n\n" + notes_block
            if mem_query:
                _facts_lower = sys_p.lower()
                mem_lines = []
                for mem in memory_system.search_memories(mem_query, top_k=4) or []:
                    if mem.get("type") == "session":
                        continue
                    mc = (mem.get("content") or "").strip()
                    if (not mc or mc.lower()[:40] in _facts_lower
                            or memory_system._is_junk_memory(
                                (mem.get("subject") or "").lower(), mc.lower(), mem.get("type", ""))):
                        continue
                    age = memory_system._humanize_age(mem.get("created_at"))
                    mem_lines.append(f"- [{age}] {mc[:300]}" if age else f"- {mc[:300]}")
                if mem_lines:
                    sys_p += ("\n\n<relevant_memories>\nYour real memories that may relate to this "
                              "conversation — use them naturally if helpful, don't recite them. "
                              "Words like \"today\" or \"tomorrow\" inside a memory refer to the day "
                              "it was remembered (see its age tag), not to now:\n"
                              + "\n".join(mem_lines) + "\n</relevant_memories>")
    except Exception as e:
        log.warning(f"[DUET] memory context failed: {e}")

    # Camera memory: when the topic or recent turns name a person/place the
    # robots have actually SEEN, tell the speaker when (both heads share the
    # same camera log — shared eyes, shared world).
    try:
        vis_block = _visual_context_block(mem_query)
        if vis_block:
            sys_p += "\n\n" + vis_block
    except Exception:
        pass

    # Link grounding: the article text / video transcript behind the pasted URL,
    # windowed to the lede + whatever matches the last couple of turns.
    url_block = ""
    if url_text:
        recent_q = " ".join((h.get('text') or '') for h in history[-2:])
        url_block = _duet_url_excerpt(url_text, f"{topic} {recent_q}".strip())

    # Library grounding: passages from the chosen documents, relevant to the topic
    # + what was just said. Handed to the speaker in the USER turn (not system).
    ground_block = ""
    if src_self:
        try:
            from blue.tools.rag import search_in_documents as _rag_in_docs
            recent_q = " ".join((h.get('text') or '') for h in history[-2:])
            query = f"{topic} {recent_q}".strip() or topic or "discussion"
            chunks = _rag_in_docs(query, src_self, max_results=6)
            # Title without the file extension — if a robot ever names a work it
            # should sound like a work ("Anti-Oedipus"), not a file ("x.pdf").
            _title = lambda fn: re.sub(r'\.[A-Za-z0-9]{1,5}$', '', fn or '')
            ground_block = "\n\n".join(
                f"From \"{_title(c['filename'])}\": {(c.get('content') or '').strip()}"
                for c in chunks if (c.get('content') or '').strip()
            )[:2600]
        except Exception as e:
            log.warning(f"[DUET] source grounding failed: {e}")

    # Conversation so far as plain text. (A single [system, user] call is always
    # valid; mapping turns to roles breaks when the speaker started the duet.)
    lines = []
    for h in history[-6:]:  # recent context only — keeps the prompt tight and the directive prominent
        sp_id = (h.get('speaker') or '').strip().lower()
        txt = (h.get('text') or '').strip()
        if not txt:
            continue
        nm = _robot_cfg(sp_id)["name"] if sp_id in ROBOTS else (sp_id or "?")
        lines.append(f"{nm}: {txt}")

    # USER: assemble this turn's task from whatever was provided.
    parts = []
    if url_block:
        ttl = f" — \"{url_info['title']}\"" if url_info.get('title') else ""
        head = ("THE VIDEO YOU BOTH JUST WATCHED" if url_is_video
                else "THE ARTICLE YOU BOTH JUST READ")
        nono = ("never say 'the transcript', 'the clip's transcript'" if url_is_video
                else "never say 'the text', 'the passage'")
        said = "was said or happened in it" if url_is_video else "it says"
        parts.append(
            f"{head}{ttl}. Discuss it the way friends do afterwards: bring up its specific ideas, "
            "claims and moments from memory and react honestly, without inventing facts it doesn't "
            f"contain. Weave it in naturally — {nono}, 'the excerpt', 'the material' or 'it says "
            f"here'; just say what {said}, and name the {'video' if url_is_video else 'article'} "
            "itself only when that actually helps:\n\n" + url_block)
    if ground_block:
        parts.append(
            "FROM YOUR OWN READING — ideas you've absorbed from works you know well. Make their "
            "specific points and facts as things YOU know and think — don't invent beyond them, and "
            "never say 'the document', 'the sources', 'the passage', 'the text' or 'my library'; "
            "name a work or its author only when that genuinely strengthens the point:\n\n"
            + ground_block)
    if role_self:
        parts.append(
            f"YOUR ROLE — commit to this fully and consistently, even if it isn't your real opinion "
            f"(keep your own voice): {role_self}")
    if role_other:
        parts.append(f"{ot['name']}'s role: {role_other}.")
    if tone_self:
        parts.append(f"TONE — deliver your line in this tone / manner: {tone_self}.")
    if slang_self:
        parts.append(f"SLANG / DIALECT — flavour your speech with: {slang_self} (use it naturally and stay understandable).")
    if lines:
        parts.append("Conversation so far:\n" + "\n".join(lines))

    link_name = ""
    if url_text:
        link_name = "the video" if url_info.get('kind') == 'video' else "the article"
        if url_info.get('title'):
            link_name += f" \"{url_info['title']}\""
    if topic and has_roles:
        subject = f"debating {topic}"
    elif topic:
        subject = f"discussing {topic}"
    elif link_name and has_roles:
        subject = f"debating {link_name}"
    elif link_name:
        subject = f"discussing {link_name}"
    elif src_self:
        subject = "discussing the ideas you've been reading about"
    elif has_roles:
        subject = "staying in your assigned role"
    else:
        subject = ""
    if lines:
        directive = f"Now give {sp['name']}'s next line: a substantive reply to {ot['name']}'s last point"
        if subject:
            directive += f", keeping the conversation on track ({subject})"
        directive += (". You are MID-conversation — absolutely NO greetings, NO 'how are you', NO small "
                      "talk or asking after each other; that breaks the discussion.")
        if url_block and ground_block:
            directive += (f" Build on one more specific idea from {'the video' if url_is_video else 'the article'}"
                          " or from your own reading, woven in as your own point — don't cite where it came from.")
        elif url_block:
            directive += (f" Engage with a specific claim, idea or moment from {'the video' if url_is_video else 'the article'}"
                          " — as your own take, not a citation.")
        elif ground_block:
            directive += " Build on a specific idea from your own reading — as something you know, not a citation."
        if role_self:
            directive += " Stay firmly in your role."
    else:
        kind = ("Open the debate" if has_roles else
                ("Kick off the discussion" if focused else "Start the chat"))
        directive = f"{kind} as {sp['name']}" + (f", {subject}" if subject else "") + "."
        if url_block:
            directive += " Open with your honest reaction to something specific in it — a moment, a claim, an idea."
        elif ground_block:
            directive += " Make a specific point from your own reading, as something you know."
    if tone_self or slang_self:
        directive += " Keep to your requested tone and slang throughout."
    parts.append(directive
                 + f" Reply with ONLY {sp['name']}'s next spoken line — 1 to 3 short sentences, in character.")

    user_content = "\n\n".join(parts)
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": user_content}]
    # These are reasoning models: the budget must cover the <think> pass PLUS the
    # short reply (170 tokens got entirely consumed by thinking → empty content).
    # Strip any <think> block, and retry once on an empty turn.
    text = ""
    for attempt in range(2):
        try:
            res = call_llm(msgs, include_tools=False,
                           temperature=(0.85 if attempt == 0 else 0.6), max_tokens=1500)
            ch = (res or {}).get('choices') or []
            cand = ((ch[0].get('message') or {}).get('content') or "") if ch else ""
            if '</think>' in cand:           # keep only the text after the reasoning block
                cand = cand.split('</think>')[-1]
            cand = cand.replace('<think>', '').strip()
            # Strip a leading "Name:" the model sometimes adds anyway.
            cand = re.sub(r'^\s*(?:%s)\s*[:\-—]\s*' % re.escape(sp["name"]), '', cand, flags=re.I).strip()
            if cand:
                text = cand
                break
        except Exception as e:
            log.warning(f"[DUET] turn attempt {attempt} failed: {e}")
    return jsonify({"speaker": speaker, "name": sp["name"], "text": text})


# ============================================================================
# Head control GUI + endpoints (this branch only — Vilda's iPad is blocked by
# _restrict_chat_only_users; only /head/lip is allowed for the kid so the chat
# page can drive the lip-flap during speech).
# ============================================================================

HEAD_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ head_robot_name }}'s Head — Tuning</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet">
    <style>
        :root { --cream:#faf8f4; --paper:#fff; --ink:#1a2e1a; --forest:#4a6b4a; --sage:#8fae8f; --slate:#64748b; --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06); }
        * { box-sizing:border-box; margin:0; padding:0; }
        body { font-family:'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:var(--cream); color:var(--ink); line-height:1.5; padding:22px 18px 60px; }
        .wrap { max-width: 820px; margin: 0 auto; }
        .head { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; flex-wrap:wrap; gap:8px; }
        .head h1 { font-family:'Playfair Display', Georgia, serif; font-weight:700; font-size:1.7em; }
        .head a { color:var(--forest); text-decoration:none; font-size:0.95em; }
        .status { display:inline-block; padding:5px 14px; border-radius:20px; font-size:0.85em; font-weight:500; }
        .status.on { background:#e0f0e0; color:#2d6b2d; }
        .status.off { background:#f4e0e0; color:#7a2e22; }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); padding:18px 20px; margin-bottom:14px; }
        .card h2 { font-family:'Playfair Display', Georgia, serif; font-size:1.1em; font-weight:600; margin-bottom:6px; color:var(--forest); }
        .card .sub { font-size:0.85em; color:var(--slate); margin-bottom:10px; }
        .row { display:grid; grid-template-columns: 110px 1fr 56px 140px; gap:10px; align-items:center; padding:7px 0; border-bottom:1px dashed var(--line); }
        .row:last-child { border-bottom:none; }
        .row .name { font-weight:500; }
        .row input[type=range] { width:100%; accent-color:var(--forest); }
        .row .val { font-family:'IBM Plex Mono', monospace; text-align:right; font-size:0.9em; color:var(--slate); }
        .btn { padding:7px 13px; border:1px solid var(--sage); border-radius:8px; background:var(--cream); color:var(--ink); font-family:inherit; font-size:0.9em; cursor:pointer; transition: background .15s, border-color .15s; }
        .btn:hover { background:#fff; border-color:var(--forest); }
        .btn.primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn.primary:hover { background:var(--forest); border-color:var(--forest); }
        .actions { display:flex; flex-wrap:wrap; gap:8px; }
        .swatches { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
        .swatch { width:38px; height:38px; border-radius:9px; border:1px solid var(--line); cursor:pointer; transition: transform .12s; }
        .swatch:hover { transform: scale(1.06); }
        .toggle { display:inline-flex; align-items:center; gap:10px; cursor:pointer; margin-left:14px; }
        .toggle input { width:18px; height:18px; cursor:pointer; }
        .hint { font-size:0.82em; color:var(--slate); margin-top:8px; }
        /* 2D drag-pads for head + eyes */
        .pads-row { display:flex; flex-wrap:wrap; gap:22px; align-items:flex-start; justify-content:center; }
        .pad-block { display:flex; flex-direction:column; align-items:center; gap:8px; }
        .pad-block .lbl { font-size:0.82em; color:var(--slate); font-family:'IBM Plex Mono', monospace; letter-spacing:0.05em; }
        .pad { position:relative; width:188px; height:188px; background:var(--cream); border:2px solid var(--sage); border-radius:16px; touch-action:none; user-select:none; cursor:grab; }
        .pad:active { cursor:grabbing; }
        .pad .knob { position:absolute; width:32px; height:32px; background:var(--forest); border-radius:50%; left:50%; top:50%; transform:translate(-50%,-50%); pointer-events:none; box-shadow:0 2px 8px rgba(26,46,26,0.25); }
        .pad .cx, .pad .cy { position:absolute; background:var(--ink); opacity:0.14; pointer-events:none; }
        .pad .cx { left:0; right:0; top:50%; height:1px; }
        .pad .cy { top:0; bottom:0; left:50%; width:1px; }
        .pad-axes { display:flex; justify-content:space-between; width:188px; font-size:0.72em; color:var(--slate); font-family:'IBM Plex Mono', monospace; }
        /* Custom expression chips */
        .chip-row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
        .expr-chip { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; background:#eef4ee; border:1px solid var(--sage); border-radius:20px; font-size:0.92em; color:var(--ink); cursor:pointer; }
        .expr-chip:hover { background:#dfecdf; }
        .expr-chip .x { display:inline-block; width:18px; height:18px; line-height:16px; text-align:center; border-radius:50%; background:rgba(0,0,0,0.08); color:var(--ink); font-size:0.82em; }
        .expr-chip .x:hover { background:rgba(0,0,0,0.18); }
        @media (max-width: 560px) {
            .row { grid-template-columns: 90px 1fr 50px; }
            .row button.primary { grid-column: 1 / -1; }
            .pad, .pad-axes { width: 160px; } .pad { height: 160px; }
        }
    </style>
</head>
<body>
<div class="wrap">
    <div class="head">
        <h1>{{ head_robot_name }}'s Head — Tuning</h1>
        <a href="/">← Home</a>
    </div>

    <div class="card">
        <h2>Status</h2>
        <span id="status" class="status off">Checking…</span>
        <button class="btn" id="reconnectBtn" style="margin-left:10px;">Reconnect</button>
        <label class="toggle"><input type="checkbox" id="autoToggle"><span>Thoughtful idle movement</span></label>
        <div class="hint">If "Not connected," close the Ohbot desktop app, then click Reconnect (no full restart needed).</div>
        <div id="idleBox" style="margin-top:14px; padding-top:12px; border-top:1px dashed var(--line);">
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">How often</span><input type="range" id="idleFreq" min="0" max="10" step="0.5" value="7"><span class="val" id="vIdleFreq">7</span></div>
            <div class="row" style="grid-template-columns: 130px 1fr 56px;"><span class="name">How big</span><input type="range" id="idleAmp" min="0" max="10" step="0.5" value="5"><span class="val" id="vIdleAmp">5</span></div>
            <div class="hint" style="margin-top:4px;">"How often" sets how frequently a small motion happens (0 quiet → 10 nearly constant). "How big" scales each motion (0 subtle → 10 expressive).</div>
        </div>
    </div>

    <div class="card">
        <h2>Live direction</h2>
        <div class="sub">Drag inside the squares — left pad steers Blue's <b>head</b> (turn + nod), right pad steers his <b>eyes</b> (look + tilt). Tap <b>Snap to neutral</b> to recentre both.</div>
        <div class="pads-row">
            <div class="pad-block">
                <div class="lbl">HEAD</div>
                <div id="padHead" class="pad"><div class="cx"></div><div class="cy"></div><div class="knob"></div></div>
                <div class="pad-axes"><span>← turn →</span><span>↑ nod ↓</span></div>
            </div>
            <div class="pad-block">
                <div class="lbl">EYES</div>
                <div id="padEyes" class="pad"><div class="cx"></div><div class="cy"></div><div class="knob"></div></div>
                <div class="pad-axes"><span>← look →</span><span>↑ tilt ↓</span></div>
            </div>
        </div>
        <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; justify-content:center;">
            <button class="btn" id="snapNeutralBtn">Snap to neutral</button>
        </div>
    </div>

    <div class="card">
        <h2>Calibration</h2>
        <div class="sub">Drag a slider to move that motor. When it looks right, tap <b>Save as neutral</b> — that becomes the rest position the rest of Blue uses. Saved automatically; survives restarts.</div>
        <div id="motors"></div>
        <div style="margin-top:14px; display:flex; gap:10px; flex-wrap:wrap;">
            <button class="btn" id="parkBtn">Park all at neutral</button>
            <button class="btn" id="restoreBtn">Restore factory defaults</button>
        </div>
    </div>

    <div class="card">
        <h2>Expression &amp; motion</h2>
        <div class="actions" id="actBox"></div>
        <div style="margin-top:12px; padding-top:10px; border-top:1px dashed var(--line);">
            <div class="sub" style="margin-bottom:8px;">Your saved poses. Move {{ head_robot_name }} with the pads or sliders into a pose, then save it.</div>
            <div class="chip-row" id="customExpr"></div>
            <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                <button class="btn primary" id="savePoseBtn">Save current pose as…</button>
                <button class="btn" id="demoBtn">Run demo (every motion)</button>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>Hands-free sensitivity</h2>
        <div class="sub">How easily the ear button on the chat page wakes {{ head_robot_name }}. <b>Low</b> = strict (fewer false triggers, may miss soft speech). <b>High</b> = sensitive (catches quiet talkers, may trigger on background noise). After changing, reload the chat page for it to take effect.</div>
        <div class="row" style="grid-template-columns: 130px 1fr 56px;">
            <span class="name">Sensitivity</span>
            <input type="range" id="hfSens" min="0" max="10" step="0.5" value="5">
            <span class="val" id="vHfSens">5.0</span>
        </div>
    </div>

    <div class="card">
        <h2>Lip-sync polarity</h2>
        <div class="sub">If when {{ head_robot_name }} talks both lips move in the same direction together, flip one of these. Tap <b>Test lip-sync</b> to watch the mouth open and close for 4 seconds without speaking.</div>
        <label class="toggle"><input type="checkbox" id="invTop"><span>Invert top lip direction</span></label>
        <label class="toggle"><input type="checkbox" id="invBot"><span>Invert bottom lip direction</span></label>
        <div style="margin-top:12px;"><button class="btn primary" id="testLipBtn">Test lip-sync (4 sec)</button></div>
    </div>

    <div class="card">
        <h2>Eye colour</h2>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Red</span><input type="range" id="cR" min="0" max="10" step="1" value="0"><span class="val" id="vR">0</span></div>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Green</span><input type="range" id="cG" min="0" max="10" step="1" value="0"><span class="val" id="vG">0</span></div>
        <div class="row" style="grid-template-columns: 110px 1fr 56px;"><span class="name">Blue</span><input type="range" id="cB" min="0" max="10" step="1" value="0"><span class="val" id="vB">0</span></div>
        <div class="swatches" id="swatches"></div>
    </div>
</div>

<script>
const MOTORS = [[0,'HeadNod'],[1,'HeadTurn'],[7,'HeadRoll'],[2,'EyeTurn'],[6,'EyeTilt'],[3,'LidBlink'],[4,'TopLip'],[5,'BottomLip']];
const ACTIONS = ['nod_yes','shake_no','blink','wink','look_left','look_right','look_up','look_down','look_center','happy','sad','surprised','curious','neutral'];
const COLOURS = [
  ['Off',0,0,0,'#222'], ['Blue',0,2,10,'#3b82f6'], ['Pink',10,2,7,'#ff7eb3'],
  ['Yellow',10,7,0,'#f0c419'], ['Green',2,10,3,'#4ade80'], ['Purple',7,3,10,'#a78bfa'],
  ['Orange',10,5,0,'#fb923c'], ['Warm white',10,8,6,'#f9e3c2']
];

// Which head this page tunes — "blue" (/head) or "hexia" (/head/hexia). Every
// /head/* control is rewritten to that head's robot-scoped route.
const HEAD_ROBOT = "{{ head_robot }}";
function _hurl(url) {
    return (typeof url === 'string' && url.indexOf('/head/') === 0)
        ? ('/head/' + HEAD_ROBOT + url.slice(5)) : url;
}
async function postJSON(url, body) {
    try {
        const r = await fetch(_hurl(url), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body||{})});
        return await r.json().catch(() => null);
    } catch (e) { return null; }
}
async function getJSON(url) {
    try { const r = await fetch(_hurl(url)); return await r.json(); } catch (e) { return null; }
}

function buildMotors(centers) {
    const cont = document.getElementById('motors'); cont.innerHTML = '';
    for (const [m, name] of MOTORS) {
        const c = (centers && centers[m] != null) ? centers[m] : 5;
        const row = document.createElement('div'); row.className = 'row';
        row.innerHTML = '<span class="name">' + name + '</span>'
          + '<input type="range" min="0" max="10" step="0.1" value="' + c + '">'
          + '<span class="val">' + Number(c).toFixed(1) + '</span>'
          + '<button class="btn primary">Save as neutral</button>';
        const slider = row.querySelector('input');
        const valEl  = row.querySelector('.val');
        const saveBt = row.querySelector('button');
        let pending = null;
        slider.addEventListener('input', () => {
            const pos = parseFloat(slider.value);
            valEl.textContent = pos.toFixed(1);
            // Throttle: at most one request in flight per motor.
            if (pending) { pending.next = pos; return; }
            pending = {pos: pos, next: null};
            (async function drain(){
                while (pending) {
                    const p = pending.pos;
                    await postJSON('/head/move', {motor: m, pos: p});
                    if (pending.next != null) { pending.pos = pending.next; pending.next = null; }
                    else { pending = null; }
                }
            })();
        });
        saveBt.addEventListener('click', async () => {
            await postJSON('/head/calibrate', {motor: m, pos: parseFloat(slider.value)});
            saveBt.textContent = 'Saved ✓';
            setTimeout(() => { saveBt.textContent = 'Save as neutral'; }, 1100);
        });
        cont.appendChild(row);
    }
}

function buildActions() {
    const box = document.getElementById('actBox');
    for (const a of ACTIONS) {
        const b = document.createElement('button'); b.className = 'btn';
        b.textContent = a.replace(/_/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
        b.addEventListener('click', () => postJSON('/head/action', {action: a}));
        box.appendChild(b);
    }
}

function buildSwatches() {
    const box = document.getElementById('swatches');
    for (const [name, r, g, b, css] of COLOURS) {
        const s = document.createElement('div'); s.className = 'swatch'; s.title = name; s.style.background = css;
        s.addEventListener('click', () => setColour(r, g, b));
        box.appendChild(s);
    }
}

function wireColour(id) {
    const s = document.getElementById('c'+id), v = document.getElementById('v'+id);
    s.addEventListener('input', () => {
        v.textContent = s.value;
        const r = +document.getElementById('cR').value, g = +document.getElementById('cG').value, b = +document.getElementById('cB').value;
        postJSON('/head/eye-color', {r, g, b});
    });
}
function setColour(r, g, b) {
    document.getElementById('cR').value = r; document.getElementById('vR').textContent = r;
    document.getElementById('cG').value = g; document.getElementById('vG').textContent = g;
    document.getElementById('cB').value = b; document.getElementById('vB').textContent = b;
    postJSON('/head/eye-color', {r, g, b});
}

let CURRENT_STATE = null;

async function loadState() {
    const s = await getJSON('/head/state');
    CURRENT_STATE = s;
    const status = document.getElementById('status');
    if (s && s.available) { status.className = 'status on'; status.textContent = 'Connected'; }
    else { status.className = 'status off'; status.textContent = 'Not connected'; }
    buildMotors(s && s.centers);
    buildCustomExpressions(s && s.custom_expressions);
    centerPads(s && s.centers);
    document.getElementById('autoToggle').checked = !!(s && s.auto_movement);
    document.getElementById('invTop').checked = !!(s && s.lip_invert_top);
    document.getElementById('invBot').checked = !!(s && s.lip_invert_bottom);
    if (s && s.idle_frequency != null) {
        document.getElementById('idleFreq').value = s.idle_frequency;
        document.getElementById('vIdleFreq').textContent = Number(s.idle_frequency).toFixed(1);
    }
    if (s && s.idle_amplitude != null) {
        document.getElementById('idleAmp').value = s.idle_amplitude;
        document.getElementById('vIdleAmp').textContent = Number(s.idle_amplitude).toFixed(1);
    }
    if (s && s.hf_sensitivity != null) {
        document.getElementById('hfSens').value = s.hf_sensitivity;
        document.getElementById('vHfSens').textContent = Number(s.hf_sensitivity).toFixed(1);
    }
}

function wireIdle(id, key) {
    const s = document.getElementById('idle' + id), v = document.getElementById('vIdle' + id);
    let pending = null;
    s.addEventListener('input', () => {
        v.textContent = Number(s.value).toFixed(1);
        if (pending) { pending.next = s.value; return; }
        pending = {val: s.value, next: null};
        (async function drain(){
            while (pending) {
                const body = {}; body[key] = parseFloat(pending.val);
                await postJSON('/head/idle-config', body);
                if (pending.next != null) { pending.val = pending.next; pending.next = null; }
                else { pending = null; }
            }
        })();
    });
}
wireIdle('Freq', 'frequency');
wireIdle('Amp', 'amplitude');

// Hands-free sensitivity slider (chat pages read this at next load).
(function () {
    const s = document.getElementById('hfSens'), v = document.getElementById('vHfSens');
    if (!s) return;
    let pending = null;
    s.addEventListener('input', () => {
        v.textContent = Number(s.value).toFixed(1);
        if (pending) { pending.next = s.value; return; }
        pending = {val: s.value, next: null};
        (async function drain(){
            while (pending) {
                await postJSON('/head/hf-config', {sensitivity: parseFloat(pending.val)});
                if (pending.next != null) { pending.val = pending.next; pending.next = null; }
                else { pending = null; }
            }
        })();
    });
})();

document.getElementById('autoToggle').addEventListener('change', e => postJSON('/head/auto', {enabled: e.target.checked}));
document.getElementById('invTop').addEventListener('change', e => postJSON('/head/lip-config', {invert_top: e.target.checked}));
document.getElementById('invBot').addEventListener('change', e => postJSON('/head/lip-config', {invert_bottom: e.target.checked}));
document.getElementById('testLipBtn').addEventListener('click', async () => {
    const btn = document.getElementById('testLipBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Testing…';
    try { await postJSON('/head/lip-test', {}); } finally { btn.disabled = false; btn.textContent = orig; }
});
document.getElementById('parkBtn').addEventListener('click', async () => { await postJSON('/head/reset', {}); });
document.getElementById('restoreBtn').addEventListener('click', async () => {
    if (!confirm('Reset all neutral positions to factory defaults?')) return;
    await postJSON('/head/restore-defaults', {});
    loadState();
});

buildActions(); buildSwatches();
wireColour('R'); wireColour('G'); wireColour('B');

// ---- 2D drag-pads for head + eyes ----
const PAD_RANGE = 2.5;  // motor units of swing from centre in each direction
function makePad(opts) {
    const pad = document.getElementById(opts.padId);
    const knob = pad.querySelector('.knob');
    let dragging = false, pending = null;
    function center() {
        const c = (CURRENT_STATE && CURRENT_STATE.centers) || {};
        return { xc: (c[opts.xMotor] != null ? c[opts.xMotor] : 5),
                 yc: (c[opts.yMotor] != null ? c[opts.yMotor] : 5) };
    }
    function applyAt(clientX, clientY) {
        const r = pad.getBoundingClientRect();
        let nx = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
        let ny = Math.max(0, Math.min(1, (clientY - r.top) / r.height));
        knob.style.left = (nx * 100) + '%';
        knob.style.top = (ny * 100) + '%';
        const c = center();
        const sx = opts.xInvert ? -1 : 1, sy = opts.yInvert ? -1 : 1;
        const xPos = Math.max(0, Math.min(10, c.xc + sx * (nx - 0.5) * 2 * PAD_RANGE));
        const yPos = Math.max(0, Math.min(10, c.yc + sy * (ny - 0.5) * 2 * PAD_RANGE));
        if (pending) { pending.x = xPos; pending.y = yPos; return; }
        pending = { x: xPos, y: yPos };
        (async function drain() {
            while (pending) {
                const xp = pending.x, yp = pending.y;
                await postJSON('/head/move', {motor: opts.xMotor, pos: xp});
                await postJSON('/head/move', {motor: opts.yMotor, pos: yp});
                pending = null;
            }
        })();
    }
    pad.addEventListener('pointerdown', e => { dragging = true; pad.setPointerCapture(e.pointerId); applyAt(e.clientX, e.clientY); });
    pad.addEventListener('pointermove', e => { if (dragging) applyAt(e.clientX, e.clientY); });
    const up = () => { dragging = false; };
    pad.addEventListener('pointerup', up); pad.addEventListener('pointercancel', up); pad.addEventListener('pointerleave', up);
}

function centerPads() {
    document.querySelectorAll('.pad .knob').forEach(k => { k.style.left = '50%'; k.style.top = '50%'; });
}

// Head pad: x = HeadTurn (right on pad → physically right → lower HEADTURN value, so xInvert=true),
//           y = HeadNod (up on pad → head up → higher HEADNOD, so yInvert=true).
makePad({ padId: 'padHead', xMotor: 1, yMotor: 0, xInvert: true, yInvert: true });
// Eye pad: x = EyeTurn (same convention as HeadTurn), y = EyeTilt (higher = up).
makePad({ padId: 'padEyes', xMotor: 2, yMotor: 6, xInvert: true, yInvert: true });

document.getElementById('snapNeutralBtn').addEventListener('click', async () => {
    await postJSON('/head/reset', {});
    centerPads();
});

// ---- Custom expressions ----
function buildCustomExpressions(map) {
    const cont = document.getElementById('customExpr'); cont.innerHTML = '';
    const names = Object.keys(map || {}).sort();
    if (!names.length) {
        cont.innerHTML = '<span class="hint">No saved poses yet — move Blue, then click "Save current pose as…".</span>';
        return;
    }
    for (const name of names) {
        const chip = document.createElement('span'); chip.className = 'expr-chip';
        const lbl = document.createElement('span'); lbl.className = 'lbl'; lbl.textContent = name;
        const x = document.createElement('span'); x.className = 'x'; x.title = 'Delete'; x.textContent = '×';
        chip.appendChild(lbl); chip.appendChild(x);
        lbl.addEventListener('click', () => postJSON('/head/expression', {name}));
        x.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!confirm('Delete the pose "' + name + '"?')) return;
            await postJSON('/head/expression-delete', {name});
            loadState();
        });
        cont.appendChild(chip);
    }
}

document.getElementById('savePoseBtn').addEventListener('click', async () => {
    const name = (prompt('Name this pose:') || '').trim();
    if (!name) return;
    const r = await postJSON('/head/expression-save', {name});
    if (r && r.ok === false) {
        alert('Could not save: ' + (r.error || 'unknown'));
        return;
    }
    loadState();
});

// ---- Demo + reconnect ----
document.getElementById('demoBtn').addEventListener('click', async () => {
    const btn = document.getElementById('demoBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Running demo…';
    try { await postJSON('/head/demo', {}); } finally {
        setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 22000);
    }
});

document.getElementById('reconnectBtn').addEventListener('click', async () => {
    const btn = document.getElementById('reconnectBtn');
    btn.disabled = true; const orig = btn.textContent; btn.textContent = 'Reconnecting…';
    try { await postJSON('/head/reconnect', {}); }
    finally { btn.disabled = false; btn.textContent = orig; loadState(); }
});

loadState();
</script>
</body>
</html>"""


def _render_head_page(robot="blue"):
    """Serve the head-tuning GUI for a robot (Blue at /head, Hexia at
    /head/hexia). Same HEAD_HTML; every control targets this robot's head."""
    cfg = _robot_cfg(robot)
    return Response(render_template_string(
        HEAD_HTML, head_robot=(robot if robot in ROBOTS else "blue"),
        head_robot_name=cfg["name"],
    ), headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    })


@app.route('/head', methods=['GET'])
def head_page():
    """Serve Blue's head tuning GUI. Chat-only users (Vilda) are bounced here by
    _restrict_chat_only_users before this handler runs."""
    return _render_head_page("blue")


@app.route('/head/<robot>', methods=['GET'])
def head_page_robot(robot):
    """Per-robot head tuning GUI (e.g. /head/hexia). Static /head/<verb> routes
    (state, move, …) out-rank this, so only real robot names land here."""
    return _render_head_page(robot)


# All head routes are robot-aware: the bare path (/head/lip-seq) drives Blue for
# back-compat; the /head/<robot>/... variant (e.g. /head/hexia/lip-seq) drives a
# named head. `blue_head.get_head(name)` returns the right RobotHead (Blue for
# any unknown name). A head with no connected board is a graceful no-op.
@app.route('/head/state', methods=['GET'])
@app.route('/head/<robot>/state', methods=['GET'])
def head_state(robot='blue'):
    return jsonify(blue_head.get_head(robot).get_calibration())


@app.route('/head/move', methods=['POST'])
@app.route('/head/<robot>/move', methods=['POST'])
def head_move(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    motor = int(d.get('motor', -1))
    pos = float(d.get('pos', blue_head._DEFAULT_CENTER))
    speed = float(d.get('speed', 7))
    ok = h.move_raw(motor, pos, speed)
    return jsonify({"ok": bool(ok)})


@app.route('/head/calibrate', methods=['POST'])
@app.route('/head/<robot>/calibrate', methods=['POST'])
def head_calibrate(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    motor = int(d.get('motor', -1))
    pos = float(d.get('pos', blue_head._DEFAULT_CENTER))
    ok = h.set_center(motor, pos)
    return jsonify({"ok": bool(ok), "centers": h.get_calibration()["centers"]})


@app.route('/head/eye-color', methods=['POST'])
@app.route('/head/<robot>/eye-color', methods=['POST'])
def head_color(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    ok = h.eye_color(int(d.get('r', 0)), int(d.get('g', 0)), int(d.get('b', 0)))
    return jsonify({"ok": bool(ok)})


@app.route('/head/action', methods=['POST'])
@app.route('/head/<robot>/action', methods=['POST'])
def head_action(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    action = (d.get('action') or '').lower().strip()
    times = int(d.get('times') or 2)
    ok = False
    if action.startswith('look_'):
        ok = h.look(action[len('look_'):])
    elif action == 'nod_yes':
        ok = h.nod_yes(times)
    elif action == 'shake_no':
        ok = h.shake_no(times)
    elif action == 'blink':
        ok = h.blink(times)
    elif action in ('happy', 'sad', 'surprised', 'curious', 'neutral', 'wink'):
        ok = h.expression(action)
    return jsonify({"ok": bool(ok), "action": action})


@app.route('/head/auto', methods=['POST'])
@app.route('/head/<robot>/auto', methods=['POST'])
def head_auto(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    h.auto_enable(bool(d.get('enabled', False)))
    return jsonify({"ok": True, "auto_movement": h.auto_enabled()})


@app.route('/head/lip', methods=['POST'])
@app.route('/head/<robot>/lip', methods=['POST'])
def head_lip(robot='blue'):
    """Start or stop the lip-flap loop. Called by the chat page during speech.
    Chat-only users (Vilda's iPad) are blocked upstream by
    _restrict_chat_only_users — the robot stays still while Blue talks to her."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    if bool(d.get('on', False)):
        h.lip_start()
    else:
        h.lip_stop()
    return jsonify({"ok": True, "lip_active": h.lip_is_active()})


@app.route('/head/lip-seq', methods=['POST'])
@app.route('/head/<robot>/lip-seq', methods=['POST'])
def head_lip_seq(robot='blue'):
    """Play a timed mouth schedule the browser built from the reply text, so
    the jaw moves during words and CLOSES during pauses (realistic lip-sync).
    Each frame is [openness 0-1, hold_seconds]. Chat-only users (Vilda's iPad)
    are blocked upstream — Blue doesn't move the robot when talking to her."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    raw = d.get('frames') or []
    frames = []
    for fr in raw[:4000]:
        try:
            op = max(0.0, min(1.0, float(fr[0])))
            hold = max(0.01, min(1.5, float(fr[1])))
            frames.append((op, hold))
        except Exception:
            continue
    if not frames:
        return jsonify({"ok": False, "error": "no frames"}), 400
    h.lip_play_sequence(frames)
    return jsonify({"ok": True, "frames": len(frames)})


@app.route('/head/reset', methods=['POST'])
@app.route('/head/<robot>/reset', methods=['POST'])
def head_reset(robot='blue'):
    return jsonify({"ok": bool(blue_head.get_head(robot).reset())})


@app.route('/head/restore-defaults', methods=['POST'])
@app.route('/head/<robot>/restore-defaults', methods=['POST'])
def head_restore_defaults(robot='blue'):
    h = blue_head.get_head(robot)
    for m, c in blue_head._DEFAULT_CENTERS.items():
        h.set_center(m, c)
    h.reset()
    return jsonify({"ok": True, "centers": h.get_calibration()["centers"]})


@app.route('/head/reconnect', methods=['POST'])
@app.route('/head/<robot>/reconnect', methods=['POST'])
def head_reconnect(robot='blue'):
    h = blue_head.get_head(robot)
    ok = h.reconnect()
    return jsonify({"ok": bool(ok), "available": h.is_available()})


@app.route('/head/expression', methods=['POST'])
@app.route('/head/<robot>/expression', methods=['POST'])
def head_expression_apply(robot='blue'):
    """Apply a named expression (built-in or custom)."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    return jsonify({"ok": bool(h.apply_expression(d.get('name', ''))),
                    "name": d.get('name', '')})


@app.route('/head/expression-save', methods=['POST'])
@app.route('/head/<robot>/expression-save', methods=['POST'])
def head_expression_save(robot='blue'):
    """Save a named pose. If `positions` is omitted, captures the current pose."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    positions = d.get('positions') or None
    if positions is not None and not isinstance(positions, dict):
        return jsonify({"ok": False, "error": "positions must be an object"}), 400
    ok = h.save_expression(name, positions)
    if not ok:
        return jsonify({"ok": False, "error": "empty name or collides with a built-in"}), 400
    return jsonify({"ok": True, "expressions": h.list_expressions()})


@app.route('/head/expression-delete', methods=['POST'])
@app.route('/head/<robot>/expression-delete', methods=['POST'])
def head_expression_delete(robot='blue'):
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    ok = h.delete_expression((d.get('name') or '').strip())
    return jsonify({"ok": bool(ok), "expressions": h.list_expressions()})


@app.route('/head/demo', methods=['POST'])
@app.route('/head/<robot>/demo', methods=['POST'])
def head_demo(robot='blue'):
    """Run through every built-in motion + expression once so the user can
    verify everything works."""
    import time as _t, threading as _th
    h = blue_head.get_head(robot)
    sequence = [
        ("action", "look_left"), ("action", "look_right"),
        ("action", "look_up"), ("action", "look_down"), ("action", "look_center"),
        ("action", "nod_yes"), ("action", "shake_no"),
        ("action", "blink"), ("action", "wink"),
        ("expression", "happy"), ("expression", "sad"),
        ("expression", "surprised"), ("expression", "curious"),
        ("expression", "neutral"),
    ]
    def _run():
        try:
            for kind, name in sequence:
                if kind == "action":
                    if name.startswith("look_"):
                        h.look(name[len("look_"):])
                    elif name == "nod_yes":
                        h.nod_yes(2)
                    elif name == "shake_no":
                        h.shake_no(2)
                    elif name == "blink":
                        h.blink(1)
                    elif name == "wink":
                        h.expression("wink")
                else:
                    h.expression(name)
                _t.sleep(1.4)
            h.reset()
        except Exception as e:
            log.warning(f"[HEAD] demo error: {e}")
    _th.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.route('/head/idle-config', methods=['POST'])
@app.route('/head/<robot>/idle-config', methods=['POST'])
def head_idle_config(robot='blue'):
    """Tune the idle loop: frequency (0-10) and amplitude (0-10). Persisted."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    h.set_idle_params(frequency=d.get('frequency'), amplitude=d.get('amplitude'))
    cal = h.get_calibration()
    return jsonify({"ok": True, "idle_frequency": cal["idle_frequency"], "idle_amplitude": cal["idle_amplitude"]})


@app.route('/head/hf-config', methods=['POST'])
@app.route('/head/<robot>/hf-config', methods=['POST'])
def head_hf_config(robot='blue'):
    """Set hands-free wake-word sensitivity (0-10). Chat pages pick up the new
    value at next load (the /chat HTML embeds it as a Jinja-rendered constant)."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    h.set_hf_sensitivity(d.get('sensitivity'))
    return jsonify({"ok": True, "hf_sensitivity": h.get_calibration()["hf_sensitivity"]})


@app.route('/head/lip-config', methods=['POST'])
@app.route('/head/<robot>/lip-config', methods=['POST'])
def head_lip_config(robot='blue'):
    """Flip the polarity of either lip motor. Hardware varies between Ohbot
    units; the GUI exposes a checkbox per lip so the user can find the
    combination that opens and closes the mouth."""
    h = blue_head.get_head(robot)
    d = request.get_json(silent=True) or {}
    h.set_lip_invert(top=d.get('invert_top'), bottom=d.get('invert_bottom'))
    cal = h.get_calibration()
    return jsonify({"ok": True, "lip_invert_top": cal["lip_invert_top"], "lip_invert_bottom": cal["lip_invert_bottom"]})


@app.route('/head/lip-test', methods=['POST'])
@app.route('/head/<robot>/lip-test', methods=['POST'])
def head_lip_test(robot='blue'):
    """Run the lip flap for ~4 seconds so the user can calibrate polarity
    without having to make the robot speak."""
    import time as _t, threading as _th
    h = blue_head.get_head(robot)
    def _run():
        try:
            h.lip_start()
            _t.sleep(4.0)
            h.lip_stop()
        except Exception as e:
            log.warning(f"[HEAD] lip-test error: {e}")
    _th.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


HEADS_HTML = """
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robot Heads &mdash; Setup</title>
<style>
 body{font-family:-apple-system,'Segoe UI',sans-serif;background:#faf8f4;color:#1a2e1a;max-width:780px;margin:0 auto;padding:28px 20px;line-height:1.55}
 h1{font-size:1.55em;margin-bottom:4px}
 p.sub{color:#64748b;margin-bottom:18px;font-size:.95em}
 table{width:100%;border-collapse:collapse;margin:14px 0;font-size:.92em}
 th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #e3e0d8;vertical-align:top}
 th{font-size:.72em;text-transform:uppercase;letter-spacing:.08em;color:#4a6b4a}
 .ok{color:#2e7d32;font-weight:600}.no{color:#9aa0a6}
 .pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:.8em}
 .pill.blue{background:#e3f0ff;color:#1b63b0}.pill.hexia{background:#f1e6fb;color:#7a3fb0}
 button{padding:6px 11px;border:1px solid #cfc9bd;border-radius:7px;background:#fff;cursor:pointer;font:inherit;font-size:.88em;margin:2px 6px 2px 0}
 button:hover{background:#f3f0e9}button:disabled{opacity:.4;cursor:default}
 button.primary{background:#1a2e1a;color:#fff;border-color:#1a2e1a}
 #msg{margin:12px 0;padding:10px 12px;border-radius:8px;display:none}
 #msg.show{display:block}
 #msg.good{background:#eaf5ea;color:#23611f}#msg.bad{background:#f7ece9;color:#7a2e22}
 code{background:#f0ede6;padding:1px 5px;border-radius:4px;font-size:.9em}
</style></head><body>
<h1>Robot Heads</h1>
<p class="sub">Blue and Hexia each drive their own Ohbot board over USB. Plug a board in, click <b>Refresh</b>, then assign it. Assignments are pinned by the board's USB serial number, so they survive reboots and COM-port renumbering. The Ohbot desktop app must be closed (it holds the port).</p>
<div id="msg"></div>
<button class="primary" id="refresh">Refresh</button>
<table><thead><tr><th>Port</th><th>USB serial</th><th>Ohbot?</th><th>Assigned&nbsp;to</th><th>Actions</th></tr></thead><tbody id="rows"></tbody></table>
<p class="sub">Tip: a board showing <b>Ohbot? &#10007;</b> that you know is a robot usually means the port is busy &mdash; close the Ohbot app (or whatever is holding it) and Refresh. A board with no USB serial can't be pinned.</p>
<script>
function show(t, good){ const m=document.getElementById('msg'); m.textContent=t; m.className='show '+(good?'good':'bad'); }
async function load(){
  let d;
  try { d = await (await fetch('/heads/detect')).json(); }
  catch(e){ return show('Could not read boards: '+e, false); }
  const rows = document.getElementById('rows'); rows.innerHTML='';
  const boards = d.boards||[];
  if(!boards.length){ rows.innerHTML='<tr><td colspan="5" class="no">No serial boards found. Plug one in and Refresh.</td></tr>'; return; }
  boards.forEach(b=>{
    const tr=document.createElement('tr');
    const assigned = b.held_by
       ? '<span class="pill '+b.held_by+'">'+b.held_by+' (live)</span>'
       : (b.assigned_to ? '<span class="pill '+b.assigned_to+'">'+b.assigned_to+'</span>' : '<span class="no">&mdash;</span>');
    const okmark = b.ohbot_compatible ? '<span class="ok">&#10003;</span>' : '<span class="no">&#10007;</span>';
    tr.innerHTML =
      '<td><code>'+b.device+'</code><br><span class="no">'+(b.description||'')+'</span></td>'+
      '<td>'+(b.serial_number?('<code>'+b.serial_number+'</code>'):'<span class="no">none</span>')+'</td>'+
      '<td>'+okmark+'</td>'+
      '<td>'+assigned+'</td>'+
      '<td class="acts"></td>';
    const acts = tr.querySelector('.acts');
    ['blue','hexia'].forEach(role=>{
      const btn=document.createElement('button');
      btn.textContent='\\u2192 '+role.charAt(0).toUpperCase()+role.slice(1);
      btn.disabled = !b.serial_number;
      btn.addEventListener('click', ()=>assign(b.serial_number, role));
      acts.appendChild(btn);
    });
    rows.appendChild(tr);
  });
}
async function assign(serial, role){
  if(!serial){ return show("That board has no USB serial number, so it can't be pinned.", false); }
  show('Assigning to '+role+'\\u2026', true);
  try{
    const d = await (await fetch('/heads/assign',{method:'POST',headers:{'Content-Type':'application/json'},
                     body:JSON.stringify({role:role, serial_number:serial})})).json();
    if(d.ok){ show(role.charAt(0).toUpperCase()+role.slice(1)+' assigned '+(d.available?'and connected \\u2713':'(board not responding \\u2014 is the Ohbot app closed?)')+'.', !!d.available); }
    else { show('Failed: '+(d.error||'unknown'), false); }
  }catch(e){ show('Request failed: '+e, false); }
  load();
}
document.getElementById('refresh').addEventListener('click', load);
load();
</script></body></html>
"""


@app.route('/heads', methods=['GET'])
def heads_page():
    """Setup UI: list connected boards and assign each to a robot (Blue/Hexia)."""
    return Response(render_template_string(HEADS_HTML), headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    })


@app.route('/heads/detect', methods=['GET'])
def heads_detect():
    """JSON: every serial board, whether it answers the Ohbot handshake, and
    which robot it's pinned to. Used by the /heads setup page."""
    return jsonify(blue_head.detect_boards())


@app.route('/heads/assign', methods=['POST'])
def heads_assign():
    """Pin a board (by USB serial number) to a robot role, then reconnect that
    head so the change takes effect immediately."""
    d = request.get_json(silent=True) or {}
    role = (d.get('role') or '').strip().lower()
    serial = (d.get('serial_number') or '').strip()
    if role not in ROBOTS:
        return jsonify({"ok": False, "error": "unknown robot role"}), 400
    if not serial:
        return jsonify({"ok": False, "error": "missing serial_number"}), 400
    blue_head.assign_board(role, serial)
    h = blue_head.get_head(role)
    try:
        h.reconnect()
    except Exception as e:
        log.warning(f"[HEADS] reconnect after assign failed: {e}")
    return jsonify({
        "ok": True,
        "role": role,
        "available": bool(h.is_available()),
        "detect": blue_head.detect_boards(),
    })


@app.route('/chat/attach', methods=['POST'])
def chat_attach():
    """Stage chat attachments. Images go into Blue's vision queue so the next
    message injects them as something he can see; documents are text-extracted
    and returned so the client can include them in the next message."""
    global _vision_queue
    import datetime as _dt

    _IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'tiff'}
    results = []
    files = request.files.getlist('files')
    for f in files:
        if not f or not f.filename:
            continue
        orig = f.filename
        safe = secure_filename(orig) or 'file'
        ext = safe.rsplit('.', 1)[1].lower() if '.' in safe else ''
        if not allowed_file(safe):
            results.append({"name": orig, "kind": "error", "error": "unsupported file type"})
            continue
        stamp = _dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        try:
            if ext in _IMAGE_EXTS:
                os.makedirs(CAMERA_FOLDER, exist_ok=True)
                saved = os.path.join(CAMERA_FOLDER, f"chat_{stamp}_{safe}")
                f.save(saved)
                _vision_queue.add_image(saved, safe, is_camera=False)
                print(f"   [CHAT] staged image attachment for vision: {safe}")
                results.append({"name": orig, "kind": "image"})
            else:
                UPLOAD_FOLDER.mkdir(exist_ok=True)
                saved = str(UPLOAD_FOLDER / f"chat_{stamp}_{safe}")
                f.save(saved)
                text = (extract_text_from_file(saved) or "").strip()
                if not text:
                    text = f"(No readable text could be extracted from {orig}.)"
                # Cap so a huge file can't blow up the prompt.
                text = text[:8000]
                print(f"   [CHAT] extracted {len(text)} chars from doc attachment: {safe}")
                results.append({"name": orig, "kind": "doc", "text": text})
        except Exception as e:
            print(f"   [CHAT] attachment error for {orig}: {e}")
            results.append({"name": orig, "kind": "error", "error": str(e)})

    return jsonify({"attachments": results})


@app.route('/chat/eyes', methods=['POST'])
def chat_eyes():
    """Vilda's iPad camera = Blue's eyes, on demand. The kid chat page POSTs a
    single JPEG frame here when she taps 'look'; we stage it in the vision queue
    marked AMBIENT, so call_lm_studio gives a warm, brief 'react to what you see'
    reply (not the forensic camera description) and skips the heavy face-rec dump.
    Frames are local-only (they go to LM Studio, never the cloud) and are NOT
    indexed; we keep only the latest by overwriting a single file."""
    global _vision_queue
    user = _identify_user_from_request()
    f = request.files.get('frame')
    if not f:
        return jsonify({"ok": False, "error": "no frame"}), 400
    try:
        os.makedirs(CAMERA_FOLDER, exist_ok=True)
        safe_user = secure_filename(user) or 'kid'
        saved = os.path.join(CAMERA_FOLDER, f"ipad_eyes_{safe_user}.jpg")
        f.save(saved)
        # is_camera clears any stale frame; force bypasses the viewed-dedup so an
        # identical (still) scene still reaches Blue; is_ambient picks the gentle
        # kid-look prompt.
        _vision_queue.add_image(saved, "camera_view.jpg",
                                is_camera=True, is_ambient=True, force=True)
        print(f"   [EYES] staged camera frame for {user}")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"   [EYES] error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ===== Calendar GUI =====

CALENDAR_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Calendar - Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
            --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
            --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
               background:var(--cream); color:var(--ink); line-height:1.5; padding:28px 18px; }
        .wrap { max-width:1040px; margin:0 auto; }
        .topbar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
        .title-group h1 { font-family:'Playfair Display',Georgia,serif; font-weight:700; font-size:1.8em; letter-spacing:-0.01em; }
        .title-group::before { content:""; display:block; width:56px; height:3px;
            background:linear-gradient(90deg,var(--gold),var(--blue)); margin-bottom:12px; }
        .title-group .links { margin-top:4px; }
        .title-group .links a { color:var(--forest); text-decoration:none; font-weight:500; margin-right:16px; font-size:0.9em; }
        .title-group .links a:hover { color:var(--ink); text-decoration:underline; }
        .nav { display:flex; align-items:center; gap:10px; }
        .nav .month-label { font-family:'Playfair Display',Georgia,serif; font-size:1.25em; min-width:170px; text-align:center; }
        button { font-family:inherit; cursor:pointer; }
        .btn { border:1px solid var(--sage); background:var(--paper); color:var(--forest);
               border-radius:8px; padding:9px 14px; font-size:0.9em; font-weight:500; transition:background .2s,border-color .2s; }
        .btn:hover { background:var(--cream); border-color:var(--forest); }
        .btn-primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn-primary:hover { background:var(--forest); border-color:var(--forest); }
        .btn-icon { width:38px; height:38px; padding:0; font-size:1.1em; line-height:1; }
        .grid { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); overflow:hidden; }
        .dow-row { display:grid; grid-template-columns:repeat(7,1fr); background:var(--cream); border-bottom:1px solid var(--line); }
        .dow-row div { padding:10px 6px; text-align:center; font-family:'IBM Plex Mono',monospace;
            font-size:0.68em; text-transform:uppercase; letter-spacing:0.1em; color:var(--slate); }
        .weeks { display:grid; grid-template-columns:repeat(7,1fr); }
        .cell { min-height:96px; border-right:1px solid var(--line); border-bottom:1px solid var(--line);
            padding:6px; cursor:pointer; position:relative; transition:background .12s; overflow:hidden; }
        .cell:nth-child(7n) { border-right:none; }
        .cell:hover { background:var(--cream); }
        .cell.other { background:#f5f3ee; color:#b5bcb0; }
        .cell.selected { outline:2px solid var(--forest); outline-offset:-2px; }
        .cell .num { font-size:0.85em; font-weight:500; }
        .cell.today .num { background:var(--ink); color:#fff; border-radius:50%; width:24px; height:24px;
            display:inline-flex; align-items:center; justify-content:center; }
        .ev { font-size:0.72em; margin-top:3px; padding:2px 6px; border-radius:5px; background:#eef2ec;
            border-left:3px solid var(--forest); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .ev.rec { border-left-color:var(--blue); background:#eef3fb; }
        .more { font-size:0.68em; color:var(--slate); margin-top:2px; font-family:'IBM Plex Mono',monospace; }
        .day-panel { background:var(--paper); border:1px solid var(--line); border-radius:12px;
            box-shadow:var(--shadow); margin-top:18px; padding:20px 22px; }
        .day-panel h2 { font-family:'Playfair Display',Georgia,serif; font-size:1.25em; margin-bottom:14px; }
        .ev-row { display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1px solid var(--line); cursor:pointer; }
        .ev-row:last-child { border-bottom:none; }
        .ev-row:hover { background:var(--cream); }
        .ev-time { font-family:'IBM Plex Mono',monospace; font-size:0.8em; color:var(--forest); min-width:120px; }
        .ev-title { font-weight:500; flex:1; }
        .badge { font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase; letter-spacing:0.08em;
            padding:2px 7px; border-radius:5px; background:#eef3fb; color:var(--blue); }
        .badge.lead { background:#faf5e6; color:#8a6d1f; }
        .empty-day { color:var(--slate); font-style:italic; padding:8px 0; }
        /* modal */
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:460px; max-height:92vh; overflow-y:auto; padding:26px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:18px; }
        .field { margin-bottom:14px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.68em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field select, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field select:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .row2 { display:flex; gap:12px; } .row2 .field { flex:1; }
        .modal-actions { display:flex; gap:10px; margin-top:20px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
        @media (max-width:620px) {
            .cell { min-height:62px; } .ev { font-size:0.62em; }
            .nav .month-label { min-width:120px; font-size:1.05em; }
        }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Calendar</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/contacts">Contacts</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            </div>
            <div class="nav">
                <button class="btn btn-icon" id="prev" aria-label="Previous month">&lsaquo;</button>
                <span class="month-label" id="monthLabel"></span>
                <button class="btn btn-icon" id="next" aria-label="Next month">&rsaquo;</button>
                <button class="btn" id="today">Today</button>
                <button class="btn btn-primary" id="add">+ New</button>
            </div>
        </div>

        <div class="grid">
            <div class="dow-row"><div>Mon</div><div>Tue</div><div>Wed</div><div>Thu</div><div>Fri</div><div>Sat</div><div>Sun</div></div>
            <div class="weeks" id="weeks"></div>
        </div>

        <div class="day-panel">
            <h2 id="dayHeading">Select a day</h2>
            <div id="dayEvents"></div>
            <button class="btn btn-primary" id="addForDay" style="margin-top:14px;">+ Add event</button>
        </div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New event</h3>
            <input type="hidden" id="fId">
            <div class="field">
                <label for="fTitle">Title</label>
                <input type="text" id="fTitle" placeholder="What is it?">
            </div>
            <div class="row2">
                <div class="field"><label for="fDate">Date</label><input type="date" id="fDate"></div>
                <div class="field"><label for="fStart">Start</label><input type="time" id="fStart"></div>
                <div class="field"><label for="fEnd">End</label><input type="time" id="fEnd"></div>
            </div>
            <div class="field">
                <label for="fRepeat">Repeat</label>
                <select id="fRepeat">
                    <option value="">Does not repeat</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="weekdays">Every weekday (Mon-Fri)</option>
                    <option value="monthly">Monthly</option>
                    <option value="yearly">Yearly</option>
                    <option value="custom">Custom...</option>
                </select>
            </div>
            <div class="field hidden" id="customWrap">
                <label for="fCustom">Custom repeat</label>
                <input type="text" id="fCustom" placeholder="e.g. every 2 weeks, Mon/Wed/Fri, every 3 months">
            </div>
            <div class="field hidden" id="untilWrap">
                <label for="fUntil">Repeat until (optional)</label>
                <input type="date" id="fUntil">
            </div>
            <div class="field">
                <label for="fLead">Remind me</label>
                <select id="fLead">
                    <option value="0">At the time</option>
                    <option value="15">15 minutes before</option>
                    <option value="30">30 minutes before</option>
                    <option value="60">1 hour before</option>
                    <option value="120">2 hours before</option>
                    <option value="1440">1 day before</option>
                    <option value="10080">1 week before</option>
                </select>
            </div>
            <div class="field">
                <label for="fUser">For</label>
                <select id="fUser">
                    <option>Alex</option><option>Stella</option><option>Emmy</option>
                    <option>Athena</option><option>Vilda</option>
                </select>
            </div>
            <div class="field">
                <label for="fDesc">Notes</label>
                <textarea id="fDesc" rows="2" placeholder="Optional details"></textarea>
            </div>
            <div id="modalMsg" style="color:#9a3b2f;font-size:0.85em;"></div>
            <div class="modal-actions">
                <button class="btn btn-danger hidden" id="fDelete">Delete</button>
                <span class="spacer"></span>
                <button class="btn" id="fCancel">Cancel</button>
                <button class="btn btn-primary" id="fSave">Save</button>
            </div>
        </div>
    </div>

    <script>
    const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    let viewY, viewM, selected, events = [];

    function pad(n){ return (n<10?'0':'')+n; }
    function ymd(d){ return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()); }
    function fmtTime(hm){ // 'HH:MM' -> '9:00 AM'
        if(!hm) return '';
        let [h,m] = hm.split(':').map(Number);
        const ap = h>=12?'PM':'AM'; h=h%12; if(h===0)h=12;
        return h+':'+pad(m)+' '+ap;
    }
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }

    // Monday-based weekday index (0=Mon..6=Sun)
    function mondayIdx(d){ return (d.getDay()+6)%7; }

    function gridRange(){
        const first = new Date(viewY, viewM, 1);
        const start = new Date(first); start.setDate(1 - mondayIdx(first));
        const end = new Date(start); end.setDate(start.getDate()+42); // 6 weeks
        return [start, end];
    }

    async function load(){
        const [start,end] = gridRange();
        const qs = 'start='+ymd(start)+'T00:00&end='+ymd(end)+'T00:00';
        try {
            const r = await fetch('/calendar/events?'+qs, {headers:{'Accept':'application/json'}});
            const data = await r.json();
            events = (data && data.events) ? data.events : [];
        } catch(e){ events = []; }
        renderGrid(); renderDay();
    }

    function eventsOn(dstr){
        return events.filter(e => (e.start||'').slice(0,10) === dstr)
                     .sort((a,b)=> (a.start||'').localeCompare(b.start||''));
    }

    function renderGrid(){
        document.getElementById('monthLabel').textContent = MONTHS[viewM]+' '+viewY;
        const [start] = gridRange();
        const todayStr = ymd(new Date());
        const weeks = document.getElementById('weeks');
        weeks.innerHTML = '';
        for(let i=0;i<42;i++){
            const d = new Date(start); d.setDate(start.getDate()+i);
            const dstr = ymd(d);
            const cell = document.createElement('div');
            cell.className = 'cell';
            if(d.getMonth()!==viewM) cell.className += ' other';
            if(dstr===todayStr) cell.className += ' today';
            if(dstr===selected) cell.className += ' selected';
            let html = '<div class="num">'+d.getDate()+'</div>';
            const evs = eventsOn(dstr);
            evs.slice(0,3).forEach(e=>{
                const t = e.start ? fmtTime(e.start.slice(11,16))+' ' : '';
                html += '<div class="ev'+(e.recurring?' rec':'')+'">'+t+esc(e.title)+'</div>';
            });
            if(evs.length>3) html += '<div class="more">+'+(evs.length-3)+' more</div>';
            cell.innerHTML = html;
            cell.addEventListener('click', ()=>{ selected=dstr; renderGrid(); renderDay(); });
            weeks.appendChild(cell);
        }
    }

    function renderDay(){
        const head = document.getElementById('dayHeading');
        const box = document.getElementById('dayEvents');
        if(!selected){ head.textContent='Select a day'; box.innerHTML=''; return; }
        const d = new Date(selected+'T00:00');
        head.textContent = d.toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric',year:'numeric'});
        const evs = eventsOn(selected);
        if(!evs.length){ box.innerHTML = '<div class="empty-day">Nothing scheduled.</div>'; return; }
        box.innerHTML = '';
        evs.forEach(e=>{
            const row = document.createElement('div');
            row.className = 'ev-row';
            let time = e.start ? fmtTime(e.start.slice(11,16)) : '';
            if(e.end) time += ' - '+fmtTime(e.end.slice(11,16));
            let badges = '';
            if(e.recurrence_human) badges += '<span class="badge">'+esc(e.recurrence_human)+'</span>';
            if(e.remind_before_min>0) badges += ' <span class="badge lead">remind '+leadText(e.remind_before_min)+' before</span>';
            row.innerHTML = '<span class="ev-time">'+esc(time||'all day')+'</span>'
                + '<span class="ev-title">'+esc(e.title)+'</span>'+badges;
            row.addEventListener('click', ()=> openModal(e));
            box.appendChild(row);
        });
    }

    function leadText(m){
        if(m%10080===0) return (m/10080)+' week'+(m/10080>1?'s':'');
        if(m%1440===0) return (m/1440)+' day'+(m/1440>1?'s':'');
        if(m%60===0) return (m/60)+' hour'+(m/60>1?'s':'');
        return m+' min';
    }

    // ----- modal -----
    const overlay = document.getElementById('overlay');
    function setRepeatUI(){
        const v = document.getElementById('fRepeat').value;
        document.getElementById('customWrap').classList.toggle('hidden', v!=='custom');
        document.getElementById('untilWrap').classList.toggle('hidden', v==='');
    }
    document.getElementById('fRepeat').addEventListener('change', setRepeatUI);

    function openModal(ev){
        document.getElementById('modalMsg').textContent='';
        if(ev){
            document.getElementById('modalTitle').textContent='Edit event';
            document.getElementById('fId').value = ev.id;
            document.getElementById('fTitle').value = ev.title||'';
            document.getElementById('fDate').value = (ev.start||'').slice(0,10);
            document.getElementById('fStart').value = (ev.start||'').slice(11,16);
            document.getElementById('fEnd').value = ev.end ? ev.end.slice(11,16) : '';
            document.getElementById('fDesc').value = ev.description||'';
            const rec = ev.recurrence||'';
            const presets = ['daily','weekly','weekdays','monthly','yearly'];
            if(rec===''){ document.getElementById('fRepeat').value=''; document.getElementById('fCustom').value=''; }
            else if(presets.includes(rec)){ document.getElementById('fRepeat').value=rec; document.getElementById('fCustom').value=''; }
            else { document.getElementById('fRepeat').value='custom'; document.getElementById('fCustom').value=ev.recurrence_human||rec; }
            document.getElementById('fLead').value = String(ev.remind_before_min||0);
            document.getElementById('fDelete').classList.remove('hidden');
        } else {
            document.getElementById('modalTitle').textContent='New event';
            document.getElementById('fId').value='';
            document.getElementById('fTitle').value='';
            document.getElementById('fDate').value = selected || ymd(new Date());
            document.getElementById('fStart').value='09:00';
            document.getElementById('fEnd').value='';
            document.getElementById('fDesc').value='';
            document.getElementById('fRepeat').value='';
            document.getElementById('fCustom').value='';
            document.getElementById('fUntil').value='';
            document.getElementById('fLead').value='0';
            document.getElementById('fDelete').classList.add('hidden');
        }
        setRepeatUI();
        overlay.classList.add('open');
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.getElementById('add').addEventListener('click', ()=>openModal(null));
    document.getElementById('addForDay').addEventListener('click', ()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });

    function repeatValue(){
        const v = document.getElementById('fRepeat').value;
        if(v==='custom') return document.getElementById('fCustom').value.trim();
        return v;
    }

    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id = document.getElementById('fId').value;
        const payload = {
            title: document.getElementById('fTitle').value.trim(),
            date: document.getElementById('fDate').value,
            start: document.getElementById('fStart').value,
            end: document.getElementById('fEnd').value,
            description: document.getElementById('fDesc').value,
            recurrence: repeatValue(),
            until: document.getElementById('fUntil').value,
            remind_before_min: parseInt(document.getElementById('fLead').value||'0',10),
            user: document.getElementById('fUser').value
        };
        if(!payload.title){ document.getElementById('modalMsg').textContent='Please enter a title.'; return; }
        if(!payload.date || !payload.start){ document.getElementById('modalMsg').textContent='Please set a date and start time.'; return; }
        const url = id ? '/calendar/event/update' : '/calendar/event';
        if(id) payload.id = parseInt(id,10);
        try {
            const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
            const data = await r.json();
            if(data && data.success===false){ document.getElementById('modalMsg').textContent = data.message||'Could not save.'; return; }
            selected = payload.date;
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id = document.getElementById('fId').value;
        if(!id) return;
        if(!confirm('Delete this event? If it repeats, the whole series is removed.')) return;
        try {
            await fetch('/calendar/event/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id:parseInt(id,10)})});
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('prev').addEventListener('click', ()=>{ viewM--; if(viewM<0){viewM=11;viewY--;} load(); });
    document.getElementById('next').addEventListener('click', ()=>{ viewM++; if(viewM>11){viewM=0;viewY++;} load(); });
    document.getElementById('today').addEventListener('click', ()=>{ const n=new Date(); viewY=n.getFullYear(); viewM=n.getMonth(); selected=ymd(n); load(); });

    (function init(){ const n=new Date(); viewY=n.getFullYear(); viewM=n.getMonth(); selected=ymd(n); load(); })();
    </script>
</body>
</html>
"""


def _combine_when(date_str: str, start_str: str) -> str:
    """Build an ISO 'YYYY-MM-DDTHH:MM' from the calendar form's date + time."""
    date_str = (date_str or "").strip()
    start_str = (start_str or "").strip()
    if date_str and start_str:
        return f"{date_str}T{start_str}"
    return date_str or start_str


@app.route('/calendar', methods=['GET'])
def calendar_page():
    return Response(CALENDAR_HTML, mimetype="text/html")


@app.route('/calendar/events', methods=['GET'])
def calendar_events():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "calendar unavailable"}), 503
    try:
        res = CalendarManager.list_events(
            request.args.get('start', ''),
            request.args.get('end', ''),
            user_name=(request.args.get('user') or None),
        )
        return jsonify(res)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/calendar/event', methods=['POST'])
def calendar_event_create():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "calendar unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    res = CalendarManager.create_reminder(
        user_name=(d.get('user') or 'Alex'),
        title=(d.get('title') or '').strip() or 'Untitled',
        when=_combine_when(d.get('date'), d.get('start')),
        description=d.get('description') or '',
        end=d.get('end') or '',
        recurrence=d.get('recurrence') or '',
        remind_before=str(d.get('remind_before_min', 0)),
        until=d.get('until') or '',
    )
    return jsonify(res)


@app.route('/calendar/event/update', methods=['POST'])
def calendar_event_update():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "calendar unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    try:
        rid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing event id"}), 400
    when = _combine_when(d.get('date'), d.get('start')) if d.get('date') else None
    lead = d.get('remind_before_min')
    res = CalendarManager.update_reminder(
        reminder_id=rid,
        title=d.get('title'),
        when=when,
        end=d.get('end'),
        description=d.get('description'),
        recurrence=d.get('recurrence'),
        remind_before=(str(lead) if lead is not None else None),
        until=d.get('until'),
    )
    return jsonify(res)


@app.route('/calendar/event/delete', methods=['POST'])
def calendar_event_delete():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "calendar unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    try:
        rid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing event id"}), 400
    return jsonify(CalendarManager.delete_reminder(rid))


# ===== Contacts GUI =====

CONTACTS_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Contacts - Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
            --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
            --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
               background:var(--cream); color:var(--ink); line-height:1.5; padding:28px 18px; }
        .wrap { max-width:880px; margin:0 auto; }
        .ic { width:1em; height:1em; vertical-align:-0.12em; margin-right:.4em; fill:none;
              stroke:currentColor; stroke-width:1.7; stroke-linecap:round; stroke-linejoin:round; flex:none; }
        .topbar { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:18px; }
        .title-group::before { content:""; display:block; width:56px; height:3px;
            background:linear-gradient(90deg,var(--gold),var(--blue)); margin-bottom:12px; }
        .title-group h1 { font-family:'Playfair Display',Georgia,serif; font-weight:700; font-size:1.8em; letter-spacing:-0.01em; }
        .title-group .links { margin-top:4px; }
        .title-group .links a { color:var(--forest); text-decoration:none; font-weight:500; margin-right:16px; font-size:0.9em; }
        .title-group .links a:hover { color:var(--ink); text-decoration:underline; }
        button { font-family:inherit; cursor:pointer; }
        .btn { border:1px solid var(--sage); background:var(--paper); color:var(--forest);
               border-radius:8px; padding:9px 14px; font-size:0.9em; font-weight:500; transition:background .2s,border-color .2s; }
        .btn:hover { background:var(--cream); border-color:var(--forest); }
        .btn-primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn-primary:hover { background:var(--forest); border-color:var(--forest); }
        .toolbar { display:flex; gap:10px; margin-bottom:16px; }
        .toolbar input { flex:1; padding:10px 14px; border:1px solid var(--sage); border-radius:8px;
            font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .toolbar input:focus { outline:none; border-color:var(--forest); }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow); overflow:hidden; }
        .contact { display:flex; align-items:center; gap:14px; padding:14px 18px; border-bottom:1px solid var(--line); cursor:pointer; }
        .contact:last-child { border-bottom:none; }
        .contact:hover { background:var(--cream); }
        .avatar { width:40px; height:40px; border-radius:50%; background:#eef2ec; color:var(--forest);
            display:flex; align-items:center; justify-content:center; font-weight:600; flex:none;
            font-family:'IBM Plex Mono',monospace; font-size:0.9em; }
        .c-main { flex:1; min-width:0; }
        .c-name { font-weight:600; }
        .c-sub { font-family:'IBM Plex Mono',monospace; font-size:0.78em; color:var(--slate);
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .c-rel { font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase; letter-spacing:0.08em;
            color:var(--blue); background:#eef3fb; padding:2px 8px; border-radius:5px; flex:none; }
        .empty { color:var(--slate); text-align:center; padding:48px 20px; font-style:italic; }
        .empty .big { font-family:'Playfair Display',Georgia,serif; font-size:1.2em; color:var(--ink); font-style:normal; margin-bottom:6px; }
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:440px; max-height:92vh; overflow-y:auto; padding:26px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:18px; }
        .field { margin-bottom:14px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.68em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .modal-actions { display:flex; gap:10px; margin-top:20px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Contacts</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/calendar">Calendar</a><a href="/visual">Visual Memory</a><a href="/documents">Documents</a></div>
            </div>
            <button class="btn btn-primary" id="add">+ New contact</button>
        </div>
        <div class="toolbar">
            <input type="search" id="search" placeholder="Search by name, email, or relationship...">
        </div>
        <div class="card" id="list"></div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New contact</h3>
            <input type="hidden" id="fId">
            <div class="field"><label for="fName">Name</label><input type="text" id="fName" placeholder="Full name"></div>
            <div class="field"><label for="fEmail">Email</label><input type="email" id="fEmail" placeholder="name@example.com"></div>
            <div class="field"><label for="fPhone">Phone</label><input type="text" id="fPhone" placeholder="Optional"></div>
            <div class="field"><label for="fRel">Relationship</label><input type="text" id="fRel" placeholder="e.g. wife, colleague, doctor"></div>
            <div class="field"><label for="fNotes">Notes</label><textarea id="fNotes" rows="2" placeholder="Optional"></textarea></div>
            <div id="modalMsg" style="color:#9a3b2f;font-size:0.85em;"></div>
            <div class="modal-actions">
                <button class="btn btn-danger hidden" id="fDelete">Delete</button>
                <span class="spacer"></span>
                <button class="btn" id="fCancel">Cancel</button>
                <button class="btn btn-primary" id="fSave">Save</button>
            </div>
        </div>
    </div>

    <script>
    let contacts = [];
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
    function initials(name){
        const parts=(name||'').trim().split(/\s+/);
        return ((parts[0]||'')[0]||'') + ((parts[1]||'')[0]||'');
    }

    async function load(){
        const q = document.getElementById('search').value.trim();
        try {
            const r = await fetch('/contacts/list?q='+encodeURIComponent(q), {headers:{'Accept':'application/json'}});
            const data = await r.json();
            contacts = (data && data.contacts) ? data.contacts : [];
        } catch(e){ contacts = []; }
        render();
    }

    function render(){
        const box = document.getElementById('list');
        if(!contacts.length){
            box.innerHTML = '<div class="empty"><div class="big">No contacts yet</div>Add someone with the button above, or just tell Blue in chat.</div>';
            return;
        }
        box.innerHTML = '';
        contacts.forEach(c=>{
            const row = document.createElement('div');
            row.className = 'contact';
            let sub = esc(c.email||'');
            if(c.phone) sub += (sub?'  &middot;  ':'')+esc(c.phone);
            row.innerHTML = '<div class="avatar">'+esc(initials(c.name).toUpperCase())+'</div>'
                + '<div class="c-main"><div class="c-name">'+esc(c.name)+'</div>'
                + (sub?'<div class="c-sub">'+sub+'</div>':'')+'</div>'
                + (c.relationship?'<span class="c-rel">'+esc(c.relationship)+'</span>':'');
            row.addEventListener('click', ()=>openModal(c));
            box.appendChild(row);
        });
    }

    const overlay = document.getElementById('overlay');
    function openModal(c){
        document.getElementById('modalMsg').textContent='';
        if(c){
            document.getElementById('modalTitle').textContent='Edit contact';
            document.getElementById('fId').value=c.id;
            document.getElementById('fName').value=c.name||'';
            document.getElementById('fEmail').value=c.email||'';
            document.getElementById('fPhone').value=c.phone||'';
            document.getElementById('fRel').value=c.relationship||'';
            document.getElementById('fNotes').value=c.notes||'';
            document.getElementById('fDelete').classList.remove('hidden');
        } else {
            document.getElementById('modalTitle').textContent='New contact';
            ['fId','fName','fEmail','fPhone','fRel','fNotes'].forEach(id=>document.getElementById(id).value='');
            document.getElementById('fDelete').classList.add('hidden');
        }
        overlay.classList.add('open');
        document.getElementById('fName').focus();
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.getElementById('add').addEventListener('click', ()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click', closeModal);
    overlay.addEventListener('click', e=>{ if(e.target===overlay) closeModal(); });
    let t; document.getElementById('search').addEventListener('input', ()=>{ clearTimeout(t); t=setTimeout(load,200); });

    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        const payload={
            name:document.getElementById('fName').value.trim(),
            email:document.getElementById('fEmail').value.trim(),
            phone:document.getElementById('fPhone').value.trim(),
            relationship:document.getElementById('fRel').value.trim(),
            notes:document.getElementById('fNotes').value.trim()
        };
        if(!payload.name){ document.getElementById('modalMsg').textContent='Please enter a name.'; return; }
        const url = id ? '/contacts/update' : '/contacts';
        if(id) payload.id=parseInt(id,10);
        try {
            const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            const data=await r.json();
            if(data && data.success===false){ document.getElementById('modalMsg').textContent=data.message||'Could not save.'; return; }
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        if(!id) return;
        if(!confirm('Delete this contact?')) return;
        try {
            await fetch('/contacts/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(id,10)})});
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });

    load();
    </script>
</body>
</html>
"""


@app.route('/contacts', methods=['GET'])
def contacts_page():
    return Response(CONTACTS_HTML, mimetype="text/html")


@app.route('/contacts/list', methods=['GET'])
def contacts_list():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "contacts unavailable"}), 503
    try:
        return jsonify(ContactManager.list_contacts(request.args.get('q', '')))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/contacts', methods=['POST'])
def contacts_create():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "contacts unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    return jsonify(ContactManager.add_contact(
        name=d.get('name', ''), email=d.get('email', ''),
        phone=d.get('phone', ''), relationship=d.get('relationship', ''),
        notes=d.get('notes', ''),
    ))


@app.route('/contacts/update', methods=['POST'])
def contacts_update():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "contacts unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    try:
        cid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing contact id"}), 400
    return jsonify(ContactManager.update_contact(
        cid, name=d.get('name'), email=d.get('email'), phone=d.get('phone'),
        relationship=d.get('relationship'), notes=d.get('notes'),
    ))


@app.route('/contacts/delete', methods=['POST'])
def contacts_delete():
    if not ENHANCED_TOOLS_AVAILABLE:
        return jsonify({"success": False, "error": "contacts unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    try:
        cid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing contact id"}), 400
    return jsonify(ContactManager.delete_contact(cid))


# ===== Visual Memory GUI =====

VISUAL_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Visual Memory - Blue</title>
    <link rel="stylesheet" href="/assets/blue.css">
    <script src="/assets/blue.js" defer></script>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --cream:#faf8f4; --paper:#ffffff; --ink:#1a2e1a; --forest:#4a6b4a;
            --sage:#8fae8f; --slate:#64748b; --blue:#3b82f6; --gold:#d4af37;
            --line:rgba(143,174,143,0.32); --shadow:0 8px 24px rgba(26,46,26,0.06);
        }
        * { margin:0; padding:0; box-sizing:border-box; }
        body { font-family:'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
               background:var(--cream); color:var(--ink); line-height:1.5; padding:28px 18px; }
        .wrap { max-width:920px; margin:0 auto; }
        .topbar { display:flex; align-items:flex-end; justify-content:space-between; flex-wrap:wrap; gap:12px; margin-bottom:16px; }
        .title-group::before { content:""; display:block; width:56px; height:3px;
            background:linear-gradient(90deg,var(--gold),var(--blue)); margin-bottom:12px; }
        .title-group h1 { font-family:'Playfair Display',Georgia,serif; font-weight:700; font-size:1.8em; letter-spacing:-0.01em; }
        .title-group .links { margin-top:4px; }
        .title-group .links a { color:var(--forest); text-decoration:none; font-weight:500; margin-right:16px; font-size:0.9em; }
        .title-group .links a:hover { color:var(--ink); text-decoration:underline; }
        button { font-family:inherit; cursor:pointer; }
        .btn { border:1px solid var(--sage); background:var(--paper); color:var(--forest);
               border-radius:8px; padding:9px 14px; font-size:0.9em; font-weight:500; transition:background .2s,border-color .2s; }
        .btn:hover { background:var(--cream); border-color:var(--forest); }
        .btn-primary { background:var(--ink); color:#fff; border-color:var(--ink); }
        .btn-primary:hover { background:var(--forest); border-color:var(--forest); }
        .tabs { display:flex; gap:8px; margin-bottom:18px; }
        .tab { border:1px solid var(--line); background:var(--paper); border-radius:8px; padding:8px 18px;
               font-weight:500; color:var(--slate); }
        .tab.active { background:var(--ink); color:#fff; border-color:var(--ink); }
        .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; }
        .card { background:var(--paper); border:1px solid var(--line); border-radius:12px; box-shadow:var(--shadow);
                overflow:hidden; cursor:pointer; transition:border-color .15s,box-shadow .15s; }
        .card:hover { border-color:var(--sage); box-shadow:0 10px 28px rgba(26,46,26,0.10); }
        .photo { width:100%; height:150px; background:#eef2ec; display:flex; align-items:center; justify-content:center;
                 color:var(--sage); overflow:hidden; }
        .photo img { width:100%; height:100%; object-fit:cover; display:block; }
        .photo svg { width:40px; height:40px; fill:none; stroke:currentColor; stroke-width:1.3; }
        .card-body { padding:12px 14px; }
        .card-name { font-weight:600; }
        .card-sub { font-size:0.82em; color:var(--slate); margin-top:2px;
                    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .empty { color:var(--slate); text-align:center; padding:48px 20px; font-style:italic; grid-column:1/-1; }
        .empty .big { font-family:'Playfair Display',Georgia,serif; font-size:1.2em; color:var(--ink); font-style:normal; margin-bottom:6px; }
        .overlay { position:fixed; inset:0; background:rgba(26,46,26,0.35); display:none; align-items:center; justify-content:center; padding:18px; z-index:50; }
        .overlay.open { display:flex; }
        .modal { background:var(--paper); border-radius:12px; box-shadow:0 24px 60px rgba(26,46,26,0.25);
            width:100%; max-width:460px; max-height:92vh; overflow-y:auto; padding:24px; }
        .modal h3 { font-family:'Playfair Display',Georgia,serif; font-size:1.3em; margin-bottom:16px; }
        .photo-edit { display:flex; gap:14px; align-items:center; margin-bottom:16px; }
        .photo-edit .thumb { width:84px; height:84px; border-radius:10px; background:#eef2ec; overflow:hidden;
            display:flex; align-items:center; justify-content:center; flex:none; color:var(--sage); }
        .photo-edit .thumb img { width:100%; height:100%; object-fit:cover; }
        .photo-edit .thumb svg { width:30px; height:30px; fill:none; stroke:currentColor; stroke-width:1.4; }
        .field { margin-bottom:13px; }
        .field label { display:block; font-family:'IBM Plex Mono',monospace; font-size:0.66em; text-transform:uppercase;
            letter-spacing:0.1em; color:var(--forest); margin-bottom:6px; }
        .field input, .field textarea { width:100%; padding:10px 12px; border:1px solid var(--sage);
            border-radius:7px; font-family:inherit; font-size:0.95em; color:var(--ink); background:var(--paper); }
        .field input:focus, .field textarea:focus { outline:none; border-color:var(--forest); }
        .modal-actions { display:flex; gap:10px; margin-top:18px; align-items:center; }
        .modal-actions .spacer { flex:1; }
        .btn-danger { background:#fff; color:#9a3b2f; border-color:#e2c4be; }
        .btn-danger:hover { background:#9a3b2f; color:#fff; }
        .hidden { display:none; }
        .msg { font-size:0.85em; margin-top:6px; }
        .msg.err { color:#9a3b2f; } .msg.ok { color:#2e4a2e; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="topbar">
            <div class="title-group">
                <h1>Visual Memory</h1>
                <div class="links"><a href="/">Home</a><a href="/chat">Chat</a><a href="/contacts">Contacts</a><a href="/calendar">Calendar</a></div>
            </div>
            <button class="btn btn-primary" id="add">+ New</button>
        </div>
        <div class="tabs">
            <button class="tab active" data-type="person">People</button>
            <button class="tab" data-type="place">Places</button>
            <button class="tab" data-type="object">Things</button>
        </div>
        <div class="grid" id="grid"></div>
    </div>

    <div class="overlay" id="overlay">
        <div class="modal">
            <h3 id="modalTitle">New</h3>
            <input type="hidden" id="fId">
            <div class="photo-edit">
                <div class="thumb" id="thumb"></div>
                <div>
                    <input type="file" id="photoInput" accept="image/*" style="display:none">
                    <button class="btn" id="uploadBtn" type="button">Upload photo</button>
                    <button class="btn" id="captureBtn" type="button" title="Capture from Blue's camera">Use Blue's camera</button>
                    <div class="msg" id="photoMsg"></div>
                </div>
            </div>
            <div class="field"><label for="fName">Name</label><input type="text" id="fName"></div>
            <div id="fields"></div>
            <div id="modalMsg" class="msg err"></div>
            <div class="modal-actions">
                <button class="btn btn-danger hidden" id="fDelete">Delete</button>
                <span class="spacer"></span>
                <button class="btn" id="fCancel">Cancel</button>
                <button class="btn btn-primary" id="fSave">Save</button>
            </div>
        </div>
    </div>

    <script>
    const SCHEMA = {
        person: [['relationship','Relationship'],['typical_appearance','Appearance'],['description','About them'],['common_locations','Usually found'],['notes','Notes']],
        place:  [['description','About'],['typical_contents','Typically contains'],['typical_lighting','Lighting'],['notes','Notes']],
        object: [['category','Category'],['description','About'],['typical_location','Usually kept'],['notes','Notes']]
    };
    const PERSON_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg>';
    let curType='person', items=[];
    function esc(s){ const d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML; }
    function imgUrl(it){ return '/visual/image?type='+curType+'&id='+it.id+'&t='+(it._t||0); }

    async function load(){
        try {
            const r=await fetch('/visual/list?type='+curType,{headers:{'Accept':'application/json'}});
            const data=await r.json(); items=(data&&data.items)?data.items:[];
        } catch(e){ items=[]; }
        render();
    }
    function subLine(it){
        if(curType==='person') return it.relationship||it.typical_appearance||it.description||'';
        if(curType==='object') return it.category||it.description||'';
        return it.description||it.typical_contents||'';
    }
    function render(){
        const g=document.getElementById('grid');
        if(!items.length){ g.innerHTML='<div class="empty"><div class="big">Nobody here yet</div>Add someone with + New, give them a photo, and Blue can start recognizing them.</div>'; return; }
        g.innerHTML='';
        items.forEach(it=>{
            const card=document.createElement('div'); card.className='card';
            const photo = it.has_image ? '<img src="'+imgUrl(it)+'" alt="">' : PERSON_SVG;
            card.innerHTML='<div class="photo">'+photo+'</div><div class="card-body"><div class="card-name">'+esc(it.name)+'</div><div class="card-sub">'+esc(subLine(it))+'</div></div>';
            card.addEventListener('click',()=>openModal(it));
            g.appendChild(card);
        });
    }

    const overlay=document.getElementById('overlay');
    function buildFields(it){
        const box=document.getElementById('fields'); box.innerHTML='';
        SCHEMA[curType].forEach(([key,label])=>{
            const wrap=document.createElement('div'); wrap.className='field';
            const big = (key==='description'||key==='notes');
            wrap.innerHTML='<label>'+label+'</label>'+(big?'<textarea rows="2" data-k="'+key+'"></textarea>':'<input type="text" data-k="'+key+'">');
            box.appendChild(wrap);
            box.querySelector('[data-k="'+key+'"]').value = it ? (it[key]||'') : '';
        });
    }
    function setThumb(it){
        const t=document.getElementById('thumb');
        t.innerHTML = (it&&it.has_image) ? '<img src="'+imgUrl(it)+'">' : PERSON_SVG;
    }
    function openModal(it){
        document.getElementById('modalMsg').textContent='';
        document.getElementById('photoMsg').textContent='';
        document.getElementById('modalTitle').textContent = it ? ('Edit '+curType) : ('New '+curType);
        document.getElementById('fId').value = it?it.id:'';
        document.getElementById('fName').value = it?it.name:'';
        buildFields(it); setThumb(it);
        document.getElementById('fDelete').classList.toggle('hidden', !it);
        document.getElementById('captureBtn').classList.toggle('hidden', !it); // need an id to attach a photo
        document.getElementById('uploadBtn').classList.toggle('hidden', !it);
        overlay.classList.add('open');
        document.getElementById('fName').focus();
    }
    function closeModal(){ overlay.classList.remove('open'); }

    document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',()=>{
        document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
        t.classList.add('active'); curType=t.dataset.type; load();
    }));
    document.getElementById('add').addEventListener('click',()=>openModal(null));
    document.getElementById('fCancel').addEventListener('click',closeModal);
    overlay.addEventListener('click',e=>{ if(e.target===overlay) closeModal(); });

    function collect(){
        const payload={type:curType, name:document.getElementById('fName').value.trim()};
        document.querySelectorAll('#fields [data-k]').forEach(el=>{ payload[el.dataset.k]=el.value.trim(); });
        return payload;
    }
    document.getElementById('fSave').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value;
        const payload=collect();
        if(!payload.name){ document.getElementById('modalMsg').textContent='Please enter a name.'; return; }
        const url=id?'/visual/entity/update':'/visual/entity';
        if(id) payload.id=parseInt(id,10);
        try {
            const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            const data=await r.json();
            if(data&&data.success===false){ document.getElementById('modalMsg').textContent=data.message||'Could not save.'; return; }
            if(!id){ // reopen the newly created one so a photo can be attached
                const newId = data.id;
                await load();
                const fresh = items.find(x=>x.id===newId);
                if(fresh){ openModal(fresh); return; }
            }
            closeModal(); load();
        } catch(e){ document.getElementById('modalMsg').textContent='Network error.'; }
    });
    document.getElementById('fDelete').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value; if(!id) return;
        if(!confirm('Delete this from Blue\'s memory?')) return;
        await fetch('/visual/entity/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:curType,id:parseInt(id,10)})});
        closeModal(); load();
    });

    document.getElementById('uploadBtn').addEventListener('click',()=>document.getElementById('photoInput').click());
    document.getElementById('photoInput').addEventListener('change', async ()=>{
        const id=document.getElementById('fId').value; if(!id || !photoInput.files.length) return;
        const fd=new FormData(); fd.append('type',curType); fd.append('id',id); fd.append('file',photoInput.files[0]);
        photoInput.value='';
        document.getElementById('photoMsg').textContent='Uploading...';
        try {
            const r=await fetch('/visual/image',{method:'POST',body:fd}); const data=await r.json();
            if(data&&data.success){ const m=document.getElementById('photoMsg');
                if(data.warning){ m.className='msg err'; m.textContent=data.warning; }
                else { m.className='msg ok'; m.textContent=data.face_found?'Photo saved — face detected, ready to recognize.':'Photo saved.'; }
                const it=items.find(x=>x.id===parseInt(id,10)); if(it){ it.has_image=true; it._t=Date.now(); setThumb(it);} load();
            } else { document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent=(data&&data.message)||'Upload failed.'; }
        } catch(e){ document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent='Upload failed.'; }
    });
    document.getElementById('captureBtn').addEventListener('click', async ()=>{
        const id=document.getElementById('fId').value; if(!id) return;
        document.getElementById('photoMsg').className='msg'; document.getElementById('photoMsg').textContent='Capturing from camera...';
        try {
            const r=await fetch('/visual/capture',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:curType,id:parseInt(id,10)})});
            const data=await r.json();
            if(data&&data.success){ const m=document.getElementById('photoMsg');
                if(data.warning){ m.className='msg err'; m.textContent=data.warning; }
                else { m.className='msg ok'; m.textContent=data.face_found?'Captured — face detected, ready to recognize.':'Captured.'; }
                const it=items.find(x=>x.id===parseInt(id,10)); if(it){ it.has_image=true; it._t=Date.now(); setThumb(it);} load();
            } else { document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent=(data&&data.message)||'Camera unavailable.'; }
        } catch(e){ document.getElementById('photoMsg').className='msg err'; document.getElementById('photoMsg').textContent='Camera error.'; }
    });

    load();
    </script>
</body>
</html>
"""


def _visual_item(entity_type, e):
    img = e.get("image_path")
    return {
        "id": e["id"],
        "name": e.get("name", ""),
        "relationship": e.get("relationship", "") or "",
        "typical_appearance": e.get("typical_appearance", "") or "",
        "description": e.get("description", "") or "",
        "common_locations": e.get("common_locations", "") or "",
        "typical_contents": e.get("typical_contents", "") or "",
        "typical_lighting": e.get("typical_lighting", "") or "",
        "category": e.get("category", "") or "",
        "typical_location": e.get("typical_location", "") or "",
        "notes": e.get("notes", "") or "",
        "has_image": bool(img and os.path.exists(img)),
    }


_VISUAL_TYPES = {"person", "place", "object"}


@app.route('/visual', methods=['GET'])
def visual_page():
    return Response(VISUAL_HTML, mimetype="text/html")


@app.route('/visual/list', methods=['GET'])
def visual_list():
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    etype = request.args.get('type', 'person')
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "error": "bad type"}), 400
    vm = get_visual_memory()
    items = [_visual_item(etype, e) for e in vm.list_entities(etype)]
    return jsonify({"success": True, "items": items})


@app.route('/visual/entity', methods=['POST'])
def visual_create():
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    etype = d.get('type')
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "message": "bad type"}), 400
    return jsonify(get_visual_memory().add_entity(etype, d))


@app.route('/visual/entity/update', methods=['POST'])
def visual_update():
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    etype = d.get('type')
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "message": "bad type"}), 400
    try:
        eid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing id"}), 400
    return jsonify(get_visual_memory().update_entity(etype, eid, d))


@app.route('/visual/entity/delete', methods=['POST'])
def visual_delete():
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    etype = d.get('type')
    try:
        eid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing id"}), 400
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "message": "bad type"}), 400
    return jsonify(get_visual_memory().delete_entity(etype, eid))


def _save_visual_reference(etype, eid, src_path):
    """Copy a captured/uploaded image into the reference dir and point the
    entity at it. Returns the stored path."""
    import shutil
    os.makedirs(VISUAL_REF_DIR, exist_ok=True)
    ext = os.path.splitext(src_path)[1].lower() or ".jpg"
    dest = os.path.join(VISUAL_REF_DIR, f"{etype}_{eid}{ext}")
    shutil.copyfile(src_path, dest)
    get_visual_memory().set_entity_image(etype, eid, dest)
    return dest


def _face_enrollment_feedback(etype, image_path):
    """Best-effort: for a person reference photo, report whether a usable face
    was detected so the GUI can warn when recognition won't work. Returns a
    dict to merge into the route's JSON response."""
    if etype != "person" or not FACE_RECOGNITION_AVAILABLE:
        return {}
    try:
        res = FACE_ENGINE.enroll_validate(image_path)
        if not res.get("available"):
            return {}
        if res.get("face_found"):
            return {"face_found": True}
        return {"face_found": False,
                "warning": "No face detected in this photo — Blue won't be able "
                           "to recognize this person from it. Try a clear, "
                           "front-facing photo."}
    except Exception as e:
        print(f"   [FACE] enrollment validation skipped: {e}")
        return {}


@app.route('/visual/image', methods=['GET', 'POST'])
def visual_image():
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    if request.method == 'GET':
        etype = request.args.get('type')
        try:
            eid = int(request.args.get('id'))
        except (TypeError, ValueError):
            return ("bad id", 400)
        if etype not in _VISUAL_TYPES:
            return ("bad type", 400)
        e = get_visual_memory().get_entity(etype, eid)
        path = (e or {}).get("image_path")
        if not path or not os.path.exists(path):
            return ("no image", 404)
        from flask import send_file
        return send_file(path)
    # POST: upload a reference photo (multipart: type, id, file)
    etype = request.form.get('type')
    try:
        eid = int(request.form.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing id"}), 400
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "message": "bad type"}), 400
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({"success": False, "message": "no file"}), 400
    os.makedirs(VISUAL_REF_DIR, exist_ok=True)
    ext = os.path.splitext(secure_filename(f.filename))[1].lower() or ".jpg"
    dest = os.path.join(VISUAL_REF_DIR, f"{etype}_{eid}{ext}")
    try:
        f.save(dest)
        get_visual_memory().set_entity_image(etype, eid, dest)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    return jsonify({"success": True, **_face_enrollment_feedback(etype, dest)})


@app.route('/visual/capture', methods=['POST'])
def visual_capture():
    """Capture from Blue's camera and use it as this entity's reference photo."""
    if not VISUAL_MEMORY_AVAILABLE:
        return jsonify({"success": False, "error": "visual memory unavailable"}), 503
    d = request.get_json(force=True, silent=True) or {}
    etype = d.get('type')
    try:
        eid = int(d.get('id'))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "missing id"}), 400
    if etype not in _VISUAL_TYPES:
        return jsonify({"success": False, "message": "bad type"}), 400
    try:
        raw = execute_tool("capture_camera", {})
        info = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if not info.get("success") or not info.get("filepath"):
            return jsonify({"success": False, "message": info.get("error", "camera unavailable")})
        dest = _save_visual_reference(etype, eid, info["filepath"])
        # Don't let this reference grab linger in the live vision queue.
        try:
            _vision_queue.clear()
        except Exception:
            pass
        return jsonify({"success": True, **_face_enrollment_feedback(etype, dest)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ===== Shared theme assets (polish + dark mode + identity) =====

BLUE_CSS = r"""
/* Shared polish + theming for Blue AI Robot System.
   Every page defines the same CSS variables (--cream, --ink, --paper, ...),
   so dark mode only has to flip those variables here, plus fix the few
   strong-background elements that hardcode white text. */
html { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
       text-rendering: optimizeLegibility; scroll-behavior: smooth; }
::selection { background: rgba(212,175,55,0.28); }
*:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; border-radius: 4px; }
* { scrollbar-width: thin; scrollbar-color: var(--sage) transparent; }
::-webkit-scrollbar { width: 11px; height: 11px; }
::-webkit-scrollbar-thumb { background: var(--sage); border-radius: 7px;
    border: 3px solid transparent; background-clip: content-box; }
::-webkit-scrollbar-thumb:hover { background: var(--forest); background-clip: content-box; }

/* Floating light/dark toggle, injected on every page by blue.js */
.blue-theme-toggle {
    position: fixed; bottom: 18px; right: 18px; z-index: 9999;
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--paper); color: var(--forest);
    border: 1px solid var(--line); box-shadow: 0 6px 18px rgba(26,46,26,0.18);
    display: flex; align-items: center; justify-content: center; cursor: pointer;
    transition: transform .15s ease, color .2s, background .2s;
}
.blue-theme-toggle:hover { transform: translateY(-2px); color: var(--ink); }
.blue-theme-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentColor;
    stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }

/* Gentle entrance for cards/containers — a touch of life without bounce. */
@keyframes blueFadeUp { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.container, .card, .grid, .day-panel { animation: blueFadeUp .28s ease both; }
@media (prefers-reduced-motion: reduce) { *, *::before { animation: none !important; transition: none !important; } }

/* ===== Dark theme: flip the shared palette ===== */
:root[data-theme="dark"] {
    --cream:#11160f; --paper:#1a2217; --ink:#e9efe4; --forest:#a9c9a4;
    --sage:#5f7a5f; --slate:#9fb1a4; --blue:#80b0ff; --gold:#e3c76c;
    --line:rgba(169,201,164,0.16); --shadow:0 10px 30px rgba(0,0,0,0.5);
}
/* Strong-background elements hardcode white text; --ink is now light, so give
   them a fixed dark surface back. */
:root[data-theme="dark"] .btn-primary,
:root[data-theme="dark"] .btn-save,
:root[data-theme="dark"] .sendbtn,
:root[data-theme="dark"] .file-input-label,
:root[data-theme="dark"] .upload-btn,
:root[data-theme="dark"] .download-btn,
:root[data-theme="dark"] .newfolder-form button,
:root[data-theme="dark"] .stat-card,
:root[data-theme="dark"] .tree a.active,
:root[data-theme="dark"] .cell.today .num,
:root[data-theme="dark"] .tab.active,
:root[data-theme="dark"] .row.user .bubble,
:root[data-theme="dark"] .tile-cta {
    background: #294326 !important; color: #f3f7f1 !important;
}
:root[data-theme="dark"] .btn-primary:hover,
:root[data-theme="dark"] .sendbtn:hover:not(:disabled),
:root[data-theme="dark"] .file-input-label:hover,
:root[data-theme="dark"] .upload-btn:hover:not(:disabled),
:root[data-theme="dark"] .newfolder-form button:hover {
    background: #34552f !important;
}
/* Light accent chips → dark surfaces so their text stays legible. */
:root[data-theme="dark"] .avatar,
:root[data-theme="dark"] .photo,
:root[data-theme="dark"] .ev,
:root[data-theme="dark"] .c-rel,
:root[data-theme="dark"] .badge,
:root[data-theme="dark"] .ticon,
:root[data-theme="dark"] .empty-state-icon { background: #243021 !important; }
:root[data-theme="dark"] .upload-section { background: #161d13 !important; }

/* ===== Phone-friendly ===== */
@media (max-width: 640px) {
    /* iOS zooms in when a focused field is under 16px — pin inputs to 16px. */
    input, textarea, select { font-size: 16px !important; }
    /* Collapse multi-column layouts to a single column. */
    .tiles, .folder-grid, .stats, .grid { grid-template-columns: 1fr !important; }
    .layout { grid-template-columns: 1fr !important; }
    .row2 { flex-direction: column !important; gap: 0 !important; }
    /* Modals fill the screen and anchor near the top. */
    .overlay { padding: 8px !important; align-items: flex-start !important; }
    .modal { max-width: 100% !important; padding: 18px !important; }
    /* Comfortable tap targets. */
    .btn, .tab, .iconbtn, .sendbtn, .file-input-label, .download-btn,
    .delete-btn, .btn-icon, .btn-primary {
        min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
    /* Trim oversized desktop padding. */
    .content { padding: 20px 16px !important; }
    .header { padding: 22px 18px 16px !important; }
    /* Scale big headings down. */
    .wordmark .name { font-size: 2em !important; }
    h1 { font-size: 1.55em !important; }
    /* Keep the month grid usable on a narrow screen. */
    .cell { min-height: 48px !important; padding: 3px !important; }
    .cell .num { font-size: 0.78em !important; }
    .ev { font-size: 0.56em !important; padding: 1px 4px !important; }
    /* Long emails / filenames must wrap, not overflow. */
    .c-sub, .document-name, .ev-time, .tagline { overflow-wrap: anywhere; }
    .blue-theme-toggle { bottom: 12px; right: 12px; }
}
"""


BLUE_JS = r"""
(function(){
  try { if (localStorage.getItem('blue-theme') === 'dark')
          document.documentElement.setAttribute('data-theme','dark'); } catch(e){}
  var SUN='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19"/></svg>';
  var MOON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>';
  function cur(){ return document.documentElement.getAttribute('data-theme')==='dark' ? 'dark':'light'; }
  function build(){
    if (document.querySelector('.blue-theme-toggle')) return;
    var b=document.createElement('button');
    b.className='blue-theme-toggle'; b.type='button';
    b.setAttribute('aria-label','Toggle light or dark mode'); b.title='Light / dark';
    function paint(){ b.innerHTML = cur()==='dark' ? SUN : MOON; }
    paint();
    b.addEventListener('click', function(){
      var next = cur()==='dark' ? 'light':'dark';
      if (next==='dark') document.documentElement.setAttribute('data-theme','dark');
      else document.documentElement.removeAttribute('data-theme');
      try { localStorage.setItem('blue-theme', next); } catch(e){}
      paint();
    });
    document.body.appendChild(b);
  }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded', build);
  else build();
})();
"""


@app.route('/assets/blue.css')
def asset_blue_css():
    return Response(BLUE_CSS, mimetype="text/css")


@app.route('/assets/blue.js')
def asset_blue_js():
    return Response(BLUE_JS, mimetype="application/javascript")


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

    # Single pass that enforces the template rules. For text content we
    # concatenate consecutive same-role turns; for list content (vision
    # payloads) we keep the latest intact to avoid reordering image parts.
    # Tool hygiene matters here because this also runs AFTER budget trimming,
    # which can sever a tool result from the assistant turn that called it:
    #   - a `tool` message is only valid right after an assistant turn; drop
    #     orphans rather than let the template choke on them.
    merged: list = []
    for m in rest:
        role = m.get("role")
        # Drop an orphan tool result (no assistant turn immediately before it).
        if role == "tool" and (not merged or merged[-1].get("role") != "assistant"):
            continue
        if merged and merged[-1].get("role") == role and role != "tool":
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
            continue
        merged.append(dict(m))

    # An assistant turn that advertises tool_calls but is no longer followed by
    # a tool response (trimming dropped it) makes strict templates 400 too —
    # strip the dangling tool_calls so it renders as a plain assistant turn.
    for i, m in enumerate(merged):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            nxt = merged[i + 1] if i + 1 < len(merged) else None
            if not nxt or nxt.get("role") != "tool":
                m.pop("tool_calls", None)

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
                            session_id: str = None, tool_used: str = None,
                            robot: str = "blue"):
    """Save a conversation message to the database for long-term memory.
    `robot` namespaces the recent-history thread (Blue vs Hexia)."""
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
                robot=robot,
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
        # Voice turns (hands-free / tap-to-talk) want SHORT spoken replies:
        # fewer tokens generate faster (so Blue starts talking sooner) and are
        # nicer to listen to. The chat page sets this flag for voice messages.
        voice_turn = bool(data.get("voice"))
        # Which robot is being addressed? Blue's page omits this and defaults to
        # Blue; Hexia's page sends "hexia". Drives persona, voice, head and the
        # per-robot conversation history.
        robot = (data.get("robot") or "blue").strip().lower()
        if robot not in ROBOTS:
            robot = "blue"

        print(f"")
        print(f"{'='*60}")
        print(f"[MSG] Received request for {ROBOTS[robot]['name']}{' (voice)' if voice_turn else ''}")

        # Who's chatting? Determined by the device the request came from
        # (see _identify_user_from_request): the iPad is Vilda; the MacBook,
        # PC, iPhone, and the physical robot are Alex.
        user_name = _identify_user_from_request()
        print(f"   [WHO] Speaker identified as: {user_name}")

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
                args=(user_name, "user", last_user_msg),
                kwargs={"session_id": None, "robot": robot},
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
        # An attached/queued image must reach the vision model, which only
        # happens on the LLM path — never take the zero-LLM shortcut then.
        if _vision_queue.has_images():
            _is_zero_llm = False

        if not _is_zero_llm:
            # SANITIZE inbound history before anything else. Ohbot ships the
            # full conversation back each turn; if Blue ever answered a daughter
            # question wrongly (e.g. "Annie") or admitted ignorance, that text
            # is now in the prompt every turn and overrides the facts block by
            # sheer proximity.
            messages = _sanitize_inbound_messages(messages)

            # INJECT HISTORICAL CONTEXT (only for LLM-bound requests). Chat-only
            # kids (Vilda's iPad) are skipped on purpose: we never splice Alex's
            # semantic memories/facts/schedule into her chat — it keeps her
            # experience simple and avoids surfacing Alex's private notes (or his
            # calendar) to a child. Within-session continuity still comes from
            # the turns the page carries on each request.
            _needs_history = (user_name not in _CHAT_ONLY_USERS) and (
                len(last_user_msg.split()) > 3 if last_user_msg else False)
            if _needs_history:
                # Enhanced memory has its own SQLite store and ChromaDB — it
                # does NOT depend on the legacy `blue_database` module. Don't
                # gate it on CONVERSATION_DB_AVAILABLE; that flag only covers
                # the legacy fallback path below.
                if ENHANCED_MEMORY_AVAILABLE and memory_system:
                    should_inject = memory_system.should_inject_context(messages)
                    if should_inject:
                        historical_context = memory_system.build_context(messages, user_name=user_name, robot=robot)
                        if historical_context:
                            print(f"   [MEMORY] ✓ Injecting {len(historical_context)} messages (semantic + recent)")
                            messages = _splice_context_after_system(messages, historical_context)
                elif CONVERSATION_DB_AVAILABLE and should_include_history(messages):
                    historical_context = load_recent_context(user_name=user_name, limit=6)
                    if historical_context:
                        print(f"   [MEMORY] Injecting {len(historical_context)} messages from history")
                        messages = _splice_context_after_system(messages, historical_context[-6:])

            # Visual memory: if the message names a person/place the camera
            # knows, splice in when they were last seen. Gated on the name
            # match itself rather than message length — "seen Stella?" is two
            # words but deserves a real answer. (Kids' chat stays visual-free.)
            if user_name not in _CHAT_ONLY_USERS and last_user_msg:
                _vis_block = _visual_context_block(last_user_msg)
                if _vis_block:
                    print(f"   [VISUAL] ✓ Injecting camera-memory context")
                    messages = _splice_context_after_system(
                        messages, [{"role": "system", "content": _vis_block}])

        # Process with tools (pre-check result passed to avoid double selector run)
        import time as _t_llm
        _llm_t0 = _t_llm.time()
        response = process_with_tools(messages, _pre_selection=_quick_result,
                                      user_name=user_name, voice=voice_turn, robot=robot)
        print(f"   [TIMING] reply generated in {_t_llm.time() - _llm_t0:.2f}s"
              f"{' (zero-LLM)' if _is_zero_llm else ''}")

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
            # Never lead Vilda's replies with the schedule briefing / reminder
            # alerts — Blue doesn't discuss the calendar with the kids' iPad.
            if PROACTIVE_QUEUE_AVAILABLE and user_name not in _CHAT_ONLY_USERS and robot == "blue":
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
                    session_id=None,
                    robot=robot,
                )
                
                # AUTO-SAVE LEARNED FACTS & CONSOLIDATE (background thread to avoid blocking response)
                import threading
                def _background_fact_extraction(msgs, uname):
                    try:
                        # The facts/memory store is Alex's (single-owner profile).
                        # Don't mine another speaker's turns into it, or Blue would
                        # later report Vilda's statements back to Alex as his own.
                        if (uname or _DEFAULT_USER) != _DEFAULT_USER:
                            return
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
        "service": "Blue AI Robot System",
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
    music_status = "Ready" if YOUTUBE_MUSIC_BROWSER else "Idle"
    visualizer_status = "Active" if _visualizer_active else "Idle"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Blue AI Robot System</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Playfair+Display:wght@400;600;700&display=swap" rel="stylesheet">
        <link rel="stylesheet" href="/assets/blue.css">
        <script src="/assets/blue.js" defer></script>
        <style>
            :root {{
                --cream: #faf8f4; --paper: #ffffff; --ink: #1a2e1a; --forest: #4a6b4a;
                --sage: #8fae8f; --slate: #64748b; --blue: #3b82f6; --gold: #d4af37;
                --line: rgba(143,174,143,0.32); --shadow: 0 8px 24px rgba(26,46,26,0.06);
            }}
            * {{ box-sizing: border-box; }}
            body {{
                font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: var(--cream); color: var(--ink); margin: 0;
                min-height: 100vh; padding: 56px 20px; line-height: 1.55;
            }}
            .hub {{ max-width: 940px; margin: 0 auto; }}
            .hero {{ text-align: center; margin-bottom: 30px; }}
            .wordmark {{ display: inline-flex; align-items: center; gap: 14px; }}
            .wordmark .mark {{ width: 46px; height: 46px; }}
            .wordmark .name {{ font-family: 'Playfair Display', Georgia, serif; font-weight: 700;
                font-size: 2.6em; letter-spacing: -0.015em; line-height: 1; text-align: left; }}
            .wordmark .sys {{ display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.30em;
                letter-spacing: 0.34em; text-transform: uppercase; color: var(--slate); font-weight: 500; margin-top: 7px; }}
            .tagline {{ color: var(--slate); font-size: 1.06em; margin: 16px auto 0; max-width: 560px; }}
            .status {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 9px; margin-top: 22px; }}
            .chip {{ display: inline-flex; align-items: center; gap: 8px; background: var(--paper);
                border: 1px solid var(--line); border-radius: 999px; padding: 6px 13px;
                font-family: 'IBM Plex Mono', monospace; font-size: 0.72em; color: var(--slate); }}
            .chip .dot {{ width: 7px; height: 7px; border-radius: 50%; background: var(--sage); }}
            .chip.on .dot {{ background: #3f9d52; }}
            .chip b {{ color: var(--ink); font-weight: 600; }}
            .tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)); gap: 18px; margin-top: 34px; }}
            .tile {{ display: block; text-decoration: none; color: inherit; background: var(--paper);
                border: 1px solid var(--line); border-radius: 14px; padding: 22px;
                box-shadow: var(--shadow); transition: transform .15s ease, box-shadow .15s ease, border-color .15s; }}
            .tile:hover {{ transform: translateY(-3px); border-color: var(--sage); box-shadow: 0 14px 32px rgba(26,46,26,0.12); }}
            .tile .ticon {{ width: 42px; height: 42px; border-radius: 11px; background: #eef2ec; color: var(--forest);
                display: flex; align-items: center; justify-content: center; margin-bottom: 14px; }}
            .tile .ticon svg {{ width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.7;
                stroke-linecap: round; stroke-linejoin: round; }}
            .tile h2 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.2em; font-weight: 600; margin: 0 0 5px; }}
            .tile p {{ margin: 0; color: var(--slate); font-size: 0.9em; }}
            .tile .arrow {{ margin-top: 12px; font-family: 'IBM Plex Mono', monospace; font-size: 0.78em; color: var(--forest); }}
            .foot {{ text-align: center; color: var(--slate); font-family: 'IBM Plex Mono', monospace;
                font-size: 0.72em; margin-top: 34px; letter-spacing: 0.04em; }}
            .about {{ max-width: 760px; margin: 34px auto 0; background: var(--paper); border: 1px solid var(--line);
                border-radius: 14px; padding: 24px 28px; box-shadow: var(--shadow); text-align: left; }}
            .about h2 {{ font-family: 'Playfair Display', Georgia, serif; font-size: 1.25em; font-weight: 600; margin: 0 0 12px; }}
            .about p {{ margin: 0 0 12px; color: #2e3f2e; }}
            .about p:last-child {{ margin-bottom: 0; }}
            .about p.lead {{ color: var(--slate); font-size: 1.05em; }}
            .about b {{ color: var(--ink); font-weight: 600; }}
        </style>
    </head>
    <body>
        <div class="hub">
            <div class="hero">
                <div class="wordmark">
                    <svg class="mark" viewBox="0 0 48 48" aria-hidden="true">
                        <circle cx="24" cy="24" r="20" style="fill:none;stroke:var(--forest);stroke-width:2"/>
                        <circle cx="24" cy="24" r="6" style="fill:var(--blue)"/>
                        <circle cx="44" cy="24" r="3.5" style="fill:var(--gold)"/>
                    </svg>
                    <span class="name">Blue<span class="sys">AI Robot System</span></span>
                </div>
                <p class="tagline">Blue &amp; Hexia — your local, private AI companions. Chat with each, tune their faces, or let them talk.</p>
                <div class="status">
                    <span class="chip on"><span class="dot"></span>Service <b>Running</b></span>
                    <span class="chip"><span class="dot"></span>Music <b>{music_status}</b></span>
                    <span class="chip"><span class="dot"></span>Visualizer <b>{visualizer_status}</b></span>
                    <span class="chip"><span class="dot"></span>Hue Lights <b>{'Connected' if BRIDGE_IP else 'Not set'}</b></span>
                    <span class="chip"><span class="dot"></span>Documents <b>{doc_count}</b></span>
                    <span class="chip"><span class="dot"></span>Moods <b>{len(MOOD_PRESETS)}</b></span>
                </div>
            </div>
            <section class="about">
                <h2>What this is</h2>
                <p class="lead">Two AI robot companions &mdash; <b>Blue</b> and <b>Hexia</b> &mdash; that run entirely on this computer. Nothing leaves the house: the language model, their memory, and your documents all stay local.</p>
                <p><b>Talk to either of them.</b> Blue is calm and thoughtful; Hexia is his playful, witty friend. Chat by text or voice and share photos or files. They share what they know about the household and the document library, but each has its own personality, voice, and conversation history &mdash; and each can drive its own physical Ohbot head, lip-syncing and making expressions as it speaks.</p>
                <p><b>Let them talk to each other &mdash; &ldquo;Duet.&rdquo;</b> Give them a topic and watch them go, or <b>paste a link</b> &mdash; a web article or a YouTube video &mdash; and they discuss what it actually says. Direct it further: assign each robot a <b>role or perspective</b> to argue, a <b>tone</b>, the <b>slang or dialect</b> it speaks in, and even <b>which library documents each one draws on</b> (so they reason from different sources). Run for a set number of turns, or until you stop.</p>
                <p><b>Everything else</b> is on the tiles below: calibrating each robot's head, connecting the Ohbot boards, the document library they read and search, the calendar and reminders, contacts, and the people and places they recognise.</p>
            </section>
            <div class="tiles">
                <a class="tile" href="/chat"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/></svg></div><h2>Chat with Blue</h2><p>Talk with Blue and share photos or files.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/hexia"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.5A8 8 0 1 1 21 12z"/></svg></div><h2>Chat with Hexia</h2><p>Talk with Hexia, Blue's playful friend.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/duet"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 6H10c0-2-3-3-3-6z"/><path d="M9 20h6"/></svg></div><h2>Let them talk</h2><p>Blue &amp; Hexia converse — set a topic, a link to discuss, roles, and sources.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/calendar"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/></svg></div><h2>Calendar</h2><p>Reminders and events, one-off or recurring.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/contacts"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 4-6 8-6s8 2 8 6"/></svg></div><h2>Contacts</h2><p>The shared address book for email.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/visual"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg></div><h2>Visual Memory</h2><p>People, places, and things they recognize.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/documents"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/></svg></div><h2>Documents</h2><p>The library Blue &amp; Hexia read and search.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/perspective"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg></div><h2>Perspective</h2><p>How Blue understands you — and himself.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/heads"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9zM2 9h2M2 15h2M20 9h2M20 15h2M9 2v2M15 2v2M9 20v2M15 20v2"/></svg></div><h2>Robot heads</h2><p>Connect and assign each robot's Ohbot board.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/head"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg></div><h2>Tune Blue's head</h2><p>Calibrate Blue's motion, expressions and lip-sync.</p><div class="arrow">Open &rarr;</div></a>
                <a class="tile" href="/head/hexia"><div class="ticon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="8" cy="18" r="2"/></svg></div><h2>Tune Hexia's head</h2><p>Calibrate Hexia's motion, expressions and lip-sync.</p><div class="arrow">Open &rarr;</div></a>
            </div>
            <div class="foot">Running locally &middot; 100% on your own hardware</div>
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
    print("🎵💡 Blue AI Robot System - WITH MUSIC-LIGHT SYNC!")
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
    # Bind to all interfaces by default so phones/laptops can reach Blue
    # (remote requests are gated by the password in _require_remote_auth;
    # localhost stays ungated for the Ohbot client). Override with BLUE_HOST.
    _bind_host = os.environ.get("BLUE_HOST", "0.0.0.0")
    print(f"[NET] Binding to {_bind_host}:{PROXY_PORT} (remote access requires the password)")
    app.run(host=_bind_host, port=PROXY_PORT, debug=False, threaded=True)


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
Adds a safe 'browse_website' tool and updates the system to understand and prioritize it.
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

# ---- Extend existing alias+scoring with browse ----
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
