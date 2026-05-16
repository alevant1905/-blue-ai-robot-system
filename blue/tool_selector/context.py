"""
Context extraction from conversation history.

Extracts contextual information from recent messages to improve
intent detection accuracy.
"""

import re
from typing import Dict, List
from .constants import MAX_CONTEXT_MESSAGES


def extract_context(conversation_history: List[Dict]) -> Dict:
    """
    Extract context from conversation history.

    Args:
        conversation_history: List of conversation messages with structure:
            [{'role': 'user'/'assistant', 'content': '...', 'tool_used': '...'}, ...]

    Returns:
        Context dictionary with flags and recency information:
        {
            'has_music_in_history': bool,
            'music_recency': int,  # How many messages ago
            'has_email_in_history': bool,
            'email_recency': int,
            # ... etc for each domain
            'recent_tools': List[str],  # Recently used tools
        }
    """
    context = {
        'recent_tools': [],
    }

    if not conversation_history:
        return context

    # Get recent messages (last N)
    recent = conversation_history[-MAX_CONTEXT_MESSAGES:]

    # Track tool usage and keywords
    tool_domains = {
        'music': ['play_music', 'control_music', 'music', 'song', 'artist'],
        'email': ['read_gmail', 'send_gmail', 'reply_gmail', 'email', 'inbox'],
        'lights': ['control_lights', 'light', 'lights', 'mood', 'brightness'],
        'camera': ['capture_camera', 'view_image', 'camera', 'picture'],
        'document': ['search_documents', 'create_document', 'document', 'file'],
        'weather': ['get_weather', 'weather', 'forecast'],
    }

    # Check for each domain
    for domain, keywords in tool_domains.items():
        has_flag = f'has_{domain}_in_history'
        recency_flag = f'{domain}_recency'

        context[has_flag] = False
        context[recency_flag] = 0

        # Search from most recent to oldest
        for i, msg in enumerate(reversed(recent)):
            content = msg.get('content', '').lower()
            tool_used = msg.get('tool_used', '')

            # Check if any keyword or tool matches this domain
            if any(kw in content or kw == tool_used for kw in keywords):
                context[has_flag] = True
                context[recency_flag] = i  # 0 = most recent
                break

    # Track recently used tools
    for msg in reversed(recent):
        tool_used = msg.get('tool_used')
        if tool_used and tool_used not in context['recent_tools']:
            context['recent_tools'].append(tool_used)
            if len(context['recent_tools']) >= 5:
                break

    return context


def _is_greeting(message: str) -> bool:
    """Check if message is PURELY a greeting/casual phrase (not a greeting + command).

    IMPORTANT: Only returns True when the ENTIRE message is conversational.
    "okay play music" should NOT be treated as a greeting — it's a command.
    "yeah turn on the lights" should NOT be skipped — it's an instruction.
    """
    from .constants import GREETING_PATTERNS, CASUAL_PATTERNS

    msg_lower = message.lower().strip()
    # Remove trailing punctuation for matching
    msg_clean = re.sub(r'[.!?,;]+$', '', msg_lower).strip()
    word_count = len(msg_clean.split())

    # Exact short greetings (1-2 words)
    if msg_clean in ['hi', 'hello', 'hey', 'yo', 'sup', 'hiya', 'howdy',
                     'hi there', 'hey there', 'hello there', 'good morning',
                     'good afternoon', 'good evening', 'good night',
                     'thanks', 'thank you', 'thx', 'ty', 'bye', 'goodbye',
                     'see you', 'see ya', 'later', 'cya', 'cool', 'nice',
                     'great', 'awesome', 'perfect', 'ok', 'okay', 'sure',
                     'yep', 'yeah', 'alright', 'sounds good', 'got it',
                     'understood', 'no problem', 'np']:
        return True

    # Short messages (≤6 words) that START with a greeting/casual pattern
    # These are things like "hey how are you" or "thanks for that"
    if word_count <= 6:
        greeting_starters = GREETING_PATTERNS + CASUAL_PATTERNS
        if any(msg_lower.startswith(p.strip()) for p in greeting_starters):
            # But NOT if it also contains an action verb/tool trigger
            action_words = [
                'play', 'turn', 'set', 'search', 'find', 'send', 'read',
                'check', 'open', 'close', 'start', 'stop', 'pause', 'skip',
                'show', 'tell me about', 'what', 'when', 'where', 'who',
                'how do', 'how to', 'can you', 'please', 'remind', 'timer',
                'email', 'light', 'music', 'weather', 'document', 'camera',
                'browse', 'volume', 'mute',
            ]
            if not any(word in msg_lower for word in action_words):
                return True

    return False


def _is_content_correction(message: str) -> bool:
    """Check if the message is a user correcting prior assistant content.

    Corrections are feedback, not commands. They should not trigger a tool
    call even if they contain trigger keywords (e.g. "the first class is
    not scheduled for today" contains "scheduled" + "today" but is a
    factual correction, not a calendar request). Returns False if the
    message also contains a clear action verb, since "no, play music
    instead" IS a new command.
    """
    msg_lower = message.lower().strip()

    correction_starters = (
        "that's all correct", "thats all correct",
        "all that is correct", "all of that is correct",
        "that's correct except", "thats correct except",
        "that's mostly correct", "thats mostly correct",
        "you're wrong", "youre wrong",
        "that's wrong", "thats wrong",
        "that's incorrect", "thats incorrect",
        "that's not right", "thats not right",
        "that's not correct", "thats not correct",
        "no, that's", "no thats", "no, that is",
        "no, it's not", "no its not", "no, it is not",
        "actually, that's not", "actually thats not",
        "actually, it's not", "actually its not",
        "actually no",
        "i never said", "i didn't say", "i did not say",
        "you got that wrong", "you got it wrong",
        "you misunderstood", "you misheard",
    )

    if not msg_lower.startswith(correction_starters):
        return False

    action_words = (
        'play ', 'turn ', 'search ', 'find ', 'send ', 'read ',
        'open ', 'close ', 'start ', 'stop ', 'pause ', 'skip ',
        'show ', 'remind ', 'create ', 'add ', 'delete ',
        'remove ', 'browse ', 'mute ',
    )
    if any(w in msg_lower for w in action_words):
        return False

    return True


def should_skip_tool_selection(message: str) -> bool:
    """
    Determine if tool selection should be skipped for this message.

    Returns True for greetings, casual chat, acknowledgments, and
    content corrections (e.g. "that's all correct except..."). Only
    skips when the ENTIRE message is conversational — not when a
    greeting/correction phrase appears alongside a real command.
    """
    if not message or len(message.strip()) < 2:
        return True

    if _is_greeting(message):
        return True

    if _is_content_correction(message):
        return True

    return False
