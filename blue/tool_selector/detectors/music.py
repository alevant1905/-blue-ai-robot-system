"""
Music intent detector.

Detects:
- play_music: Play songs, artists, genres, playlists
- control_music: Pause, stop, skip, volume, etc.
- music_visualizer: Sync lights with music

ENHANCED v7: Better false positive filtering for non-music "play" contexts
"""

import re
from typing import Dict, List, Optional

from .base import BaseDetector
from ..models import ToolIntent
from ..constants import ToolPriority
from ..utils import fuzzy_match
from ..data.music_data import (
    NON_MUSIC_PLAY_PHRASES,
    PLAY_SIGNALS,
    MUSIC_NOUNS,
    GENRES,
    ARTISTS,
    CONTROL_SIGNALS,
    VISUALIZER_SIGNALS,
    INFO_REQUEST_WORDS,
    NON_MUSIC_CONTEXT_WORDS,
)

def _compile_terms(terms):
    """Whole-word alternation for a term list. Substring matching burned us
    live (2026-07-10): 'intere-STING' matched the artist Sting and
    'SOME-thing' matched the quantity word 'some' — together they turned
    'tell me something interesting' into play_music at 0.85."""
    escaped = sorted((re.escape(t) for t in terms if t), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b")


_ARTISTS_RE = _compile_terms(ARTISTS)
_GENRES_RE = _compile_terms(GENRES)

# "I didn't ask you to play anything" is a complaint about playback, not a
# request for it (live 2026-07-10: it fuzzy-matched 'just wanted' to Justin
# Bieber and played him).
_NEGATED_PLAY_RE = re.compile(
    r"\b(?:didn'?t|did not|don'?t|do not|never|wasn'?t|not)\b"
    r"[^.!?]{0,40}\bplay(?:ing)?\b"
)

# Pre-compiled regex for non-music usage of ambiguous control words
_NON_MUSIC_FOLLOW_RE = re.compile(
    r'\bstop\s+(?:using|doing|saying|being|making|asking|telling|showing|giving|that)'
    r'|\bnext\s+(?:question|topic|time|step|one|page|slide|chapter|item|thing)'
    r'|\bskip\s+(?:this|that|the\s+(?!song|track))'
    r'|\bpause\s+(?:the\s+(?:game|video|movie|show)|for|that)'
    r'|\bback\s+(?:to|up|off|away|home)'
    r'|\bmute\s+(?:the\s+(?!music|song|audio)|your|his|her|my)'
)


class MusicDetector(BaseDetector):
    """Detects music playback and control intents."""

    def detect(
        self,
        message: str,
        msg_lower: str,
        context: Dict
    ) -> List[ToolIntent]:
        """Detect music-related intents."""
        intents = []

        # Early exit: non-music "play" contexts
        if self._is_non_music_context(msg_lower):
            return intents

        # Detect play music intent
        play_intent = self._detect_play_intent(msg_lower, context)
        if play_intent:
            intents.append(play_intent)

        # Detect control music intent
        control_intent = self._detect_control_intent(msg_lower, context)
        if control_intent:
            intents.append(control_intent)

        # Detect visualizer intent
        visualizer_intent = self._detect_visualizer_intent(msg_lower)
        if visualizer_intent:
            intents.append(visualizer_intent)

        return intents

    def _is_non_music_context(self, msg_lower: str) -> bool:
        """Check if message contains non-music 'play' context."""
        return any(phrase in msg_lower for phrase in NON_MUSIC_PLAY_PHRASES)

    def _detect_play_intent(
        self,
        msg_lower: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect play music intent."""

        # A negated "play" is a complaint, never a request.
        if _NEGATED_PLAY_RE.search(msg_lower):
            return None

        # Check for artists and genres (whole words only — see _compile_terms)
        has_artist = bool(_ARTISTS_RE.search(msg_lower))
        has_genre = bool(_GENRES_RE.search(msg_lower))

        # Fuzzy match for artist names (handles typos)
        matched_artist = None
        if not has_artist and any(signal in msg_lower for signal in PLAY_SIGNALS):
            matched_artist = self._fuzzy_match_artist(msg_lower)
            if matched_artist:
                has_artist = True

        # Detect play signals and music nouns
        has_play = any(signal in msg_lower for signal in PLAY_SIGNALS)
        has_music = any(noun in msg_lower for noun in MUSIC_NOUNS)

        # Calculate confidence
        confidence, reasons = self._calculate_play_confidence(
            msg_lower, has_play, has_artist, has_genre, has_music,
            matched_artist, context
        )

        if confidence <= 0:
            return None

        # Extract query
        query = self._extract_music_query(msg_lower, matched_artist)

        return ToolIntent(
            tool_name='play_music',
            confidence=confidence,
            priority=ToolPriority.HIGH,
            reason=' | '.join(reasons),
            extracted_params={'query': query if query else msg_lower}
        )

    def _fuzzy_match_artist(self, msg_lower: str) -> Optional[str]:
        """Fuzzy match artist names to handle typos."""
        from ..constants import COMPOUND_CONJUNCTIONS

        # Skip fuzzy matching if this looks like a compound request
        # to avoid false positives like "turn on lights and play" -> "ike turner"
        if any(conj in msg_lower for conj in COMPOUND_CONJUNCTIONS):
            # Only fuzzy match the part after the conjunction if "play" appears there
            for conj in COMPOUND_CONJUNCTIONS:
                if conj in msg_lower:
                    parts = msg_lower.split(conj)
                    # Check if "play" is in the second part
                    if len(parts) > 1 and 'play' in parts[-1]:
                        msg_lower = parts[-1]  # Only search in the music part
                        break
                    else:
                        return None  # Don't fuzzy match compound requests

        # Remove play signals
        msg_without_signals = msg_lower
        for signal in PLAY_SIGNALS:
            msg_without_signals = msg_without_signals.replace(signal, ' ')

        words = msg_without_signals.split()
        words = [w for w in words if len(w) > 2]  # Skip short words

        # Try single words and pairs
        for i in range(len(words)):
            for length in [1, 2, 3]:
                if i + length <= len(words):
                    phrase = ' '.join(words[i:i+length])
                    if len(phrase) >= 4:  # At least 4 characters
                        # 0.74: at 0.60 ordinary phrases matched artists
                        # ("just wanted" → Justin Bieber, live 2026-07-10);
                        # genuine typos ("the beetles") still clear 0.74.
                        match = fuzzy_match(phrase, ARTISTS, threshold=0.74)
                        if match:
                            return match
        return None

    def _calculate_play_confidence(
        self,
        msg_lower: str,
        has_play: bool,
        has_artist: bool,
        has_genre: bool,
        has_music: bool,
        matched_artist: Optional[str],
        context: Dict
    ) -> tuple[float, List[str]]:
        """Calculate confidence score for play intent."""
        confidence = 0.0
        reasons = []

        # Direct "play [artist]" or "play [genre]"
        if has_play and (has_artist or has_genre):
            confidence = 0.98
            if matched_artist:
                reasons.append(f"play + fuzzy matched artist: {matched_artist}")
            else:
                reasons.append("play + artist/genre detected")

        # "play music"
        elif has_play and has_music:
            # Check if it's about searching for info
            if any(word in msg_lower for word in INFO_REQUEST_WORDS):
                confidence = 0.2
                reasons.append("play+music but info request detected")
            elif any(word in msg_lower for word in NON_MUSIC_CONTEXT_WORDS):
                confidence = 0.25
                reasons.append("play detected but non-music context")
            else:
                confidence = 0.95
                reasons.append("clear play + music intent")

        # "play" with music context from history
        elif has_play and context.get('has_music_in_history'):
            recency = context.get('music_recency', 0)
            if recency <= 3:  # Lower number = more recent
                confidence = 0.50
                reasons.append("play verb with RECENT music context")
            else:
                confidence = 0.30
                reasons.append("play verb but music context too old")

        # Music noun with play indicators
        elif has_music and any(word in msg_lower for word in ['play', 'start', 'queue']):
            if context.get('has_music_in_history') or any(g in msg_lower for g in GENRES[:20]):
                confidence = 0.60
                reasons.append("music noun with play indicators + context")
            else:
                confidence = 0.35
                reasons.append("music noun + play but no context")

        # "put on some [genre/artist/music]"
        elif 'put on' in msg_lower and (has_artist or has_genre or has_music):
            confidence = 0.92
            reasons.append("put on + music/artist/genre")

        # Artist mention with quantity words (whole words — 'something' is
        # not 'some')
        elif has_artist and re.search(r"\bsome\b|\blittle\b|\bbit of\b", msg_lower):
            confidence = 0.85
            reasons.append("artist + quantity word suggests play intent")

        # Just artist name (might be info request)
        elif has_artist and not has_play:
            if any(w in msg_lower for w in ['who', 'what', 'when', 'where', 'how', 'tell me']):
                confidence = 0.2
                reasons.append("artist mentioned but seems like info request")
            elif context.get('has_music_in_history'):
                confidence = 0.7
                reasons.append("artist mentioned with music context")

        # Narrative/past "playing" with no bare imperative "play" is a REPORT
        # about playback, not a request for it. Live 2026-07-10: "...and you
        # gave me sections of the text and started playing music" re-started
        # the music it was complaining about. \b keeps "play jazz" unaffected
        # ("playing" has no word boundary after "play").
        if confidence > 0.3 and not re.search(r'\bplay\b|\bput on\b|\blisten to\b', msg_lower):
            if re.search(r'\b(?:started|stopped|was|were|been|kept|keeps?|you|he|she|it)\s+playing\b', msg_lower):
                confidence = 0.2
                reasons.append("narrative 'playing', not a request")

        return confidence, reasons

    def _extract_music_query(
        self,
        msg_lower: str,
        matched_artist: Optional[str]
    ) -> str:
        """Extract clean music query."""
        if matched_artist:
            return matched_artist

        query = msg_lower
        for signal in PLAY_SIGNALS:
            query = query.replace(signal, '').strip()

        return query

    def _detect_control_intent(
        self,
        msg_lower: str,
        context: Dict
    ) -> Optional[ToolIntent]:
        """Detect music control intent (pause, skip, etc.)."""

        if not any(signal in msg_lower for signal in CONTROL_SIGNALS):
            return None

        # Ambiguous single-word signals that commonly appear in non-music sentences
        # These need music context or music-specific phrasing to trigger
        ambiguous_signals = {'stop', 'pause', 'back', 'next', 'skip', 'mute', 'resume'}
        # Multi-word signals that can appear as substrings of non-music phrases
        # e.g., "skip this part" matches "skip this" but isn't about music
        ambiguous_multi = {'skip this', 'go back'}
        matched_signals = [s for s in CONTROL_SIGNALS if s in msg_lower]

        # Check if ONLY ambiguous signals matched (no definitive music phrases)
        all_ambiguous = all(s in ambiguous_signals or s in ambiguous_multi for s in matched_signals)

        if all_ambiguous:
            # For ambiguous words, require either:
            # 1. Very short standalone command (e.g. "stop", "pause", "stop it"), OR
            # 2. Music-related words nearby (song, music, track, etc.)
            # "stop using emojis" and "next question" are NOT music commands
            has_music_words = any(w in msg_lower for w in [
                'music', 'song', 'track', 'playlist', 'album', 'playing',
                'audio', 'spotify', 'radio', 'the music', 'it'
            ])

            # Check if the ambiguous word is followed by a non-music object
            # e.g., "stop using", "next question", "skip this part", "pause the game"
            is_non_music_usage = bool(_NON_MUSIC_FOLLOW_RE.search(msg_lower))

            if is_non_music_usage:
                return None

            # For standalone usage without music words, only allow very short (≤2 words)
            is_standalone_command = len(msg_lower.split()) <= 2
            if not (is_standalone_command or has_music_words):
                return None

        confidence = 0.95
        reasons = ["explicit control keyword"]

        # Reduce confidence if no music context
        if (not context.get('has_music_in_history') and
            context.get('music_recency', 0) < 3):
            confidence = 0.75
            reasons.append("reduced: no recent music context")

        # Map control signals to actions
        action = self._extract_control_action(msg_lower)

        return ToolIntent(
            tool_name='control_music',
            confidence=confidence,
            priority=ToolPriority.HIGH,
            reason=' | '.join(reasons),
            extracted_params={'action': action}
        )

    def _extract_control_action(self, msg_lower: str) -> str:
        """Extract control action from message."""
        if 'skip' in msg_lower or 'next' in msg_lower:
            return 'next'
        elif 'previous' in msg_lower or 'back' in msg_lower:
            return 'previous'
        elif 'resume' in msg_lower:
            return 'resume'
        elif 'stop' in msg_lower:
            return 'pause'
        elif 'volume up' in msg_lower or 'louder' in msg_lower or 'turn up' in msg_lower or 'turn it up' in msg_lower:
            return 'volume_up'
        elif 'volume down' in msg_lower or 'quieter' in msg_lower or 'softer' in msg_lower or 'turn down' in msg_lower or 'turn it down' in msg_lower:
            return 'volume_down'
        elif 'mute' in msg_lower:
            return 'mute'
        else:
            return 'pause'

    def _detect_visualizer_intent(self, msg_lower: str) -> Optional[ToolIntent]:
        """Detect music visualizer intent."""
        if not any(signal in msg_lower for signal in VISUALIZER_SIGNALS):
            return None

        return ToolIntent(
            tool_name='music_visualizer',
            confidence=0.95,
            priority=ToolPriority.HIGH,
            reason="explicit visualizer keywords",
            extracted_params={
                'action': 'start',
                'duration': 300,
                'style': 'party'
            }
        )
