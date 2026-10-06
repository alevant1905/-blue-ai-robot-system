"""Whether Blue thinks before he answers: one decision per chat turn.

Left to itself, whether the model reasons first is not something to rely
on. Live Blue chat 2026-09-27..10-02: 0 of 36 calls reasoned. After LM Studio
reloaded qwen3.8-27b on 10-05: 116 of 116 harness calls did, and 81% of the
tokens generated were hidden reasoning. A spoken "what's your favorite
music?" spent 700 of 751 tokens thinking (17.5 s), and three calls came back
empty or cut because reasoning used the whole budget. That afternoon a short
test question with no field drew no reasoning at all. So the chat page
always says which it wants.

Alex's call (2026-10-05): no thinking for greetings, acknowledgements and
short replies, voice small talk and class introductions; thinking for real
questions, planning, opinions and discussion, and document work. The answer
goes out as the request field ``reasoning_effort`` ("none" or "medium"),
which is the switch LM Studio honours on this model: chat_template_kwargs
enable_thinking and a "/no_think" suffix do not, and "low" still reasons.

Pure text in, a word out — no bluetools import.
"""

from __future__ import annotations

import re
from typing import Optional

THINK_OFF = "none"
THINK_ON = "on"

# What thinking costs on top of the visible reply: reasoning is generated
# inside max_tokens, so without room for it the answer is what gets cut
# (longform_reading_report[3]: 2,048 of 2,048 tokens were reasoning).
THINKING_ALLOWANCE_TOKENS = 1536

# Forced tools whose call is the whole job: the words around it are a line
# of confirmation, and the reminder's 398 reasoning tokens bought nothing.
_ACTION_TOOLS = frozenset({
    "control_lights", "control_music", "play_music", "music_visualizer",
    "set_timer", "set_volume", "create_reminder", "get_local_time",
    "get_weather", "capture_camera", "email_snapshot", "take_screenshot",
    "remember_fact", "remember_person", "remember_place",
})
# Forced tools that bring back text to read or write a body: document work.
# The forced call itself never thinks (bluetools._lm_studio_payload); this
# is for the calls after the tool has run.
_WORK_TOOLS = frozenset({
    "search_documents", "read_document", "web_search", "browse_website",
    "search_scholar", "get_paper", "read_paper", "read_gmail", "send_gmail",
    "reply_gmail", "create_document", "create_note", "update_note",
    "write_file",
})

_NAMES = r"(?:blue|hexia|casper|caspar|pico|picoh)"
_GREETING_WORD = (
    r"(?:hi|hello|hey|yo|hiya|howdy|greetings|good (?:morning|afternoon|evening)"
    r"|morning|evening|bonjour|salut|hola|привет|здравствуй(?:те)?"
    r"|γει[αά](?: σου)?|hej|goddag)\b"
)
_GREETING_PREFIX_RE = re.compile(
    r"^(?:" + _GREETING_WORD + r"(?:\s+(?:there|again|everyone|everybody|all))?"
    r"(?:[\s,]+" + _NAMES + r")?[\s,.!]*)+")
_NAME_ONLY_RE = re.compile(r"^(?:" + _NAMES + r"[\s,.!?]*)+$")
_LEADING_NAME_RE = re.compile(r"^(?:" + _NAMES + r"\s*[,.!]+\s*)+")
_TRAILING_NAME_RE = re.compile(r",\s*" + _NAMES + r"\s*(?=[.!?]*$)")
# A name spoken with no comma after it: "blue what do you think…", "ok blue
# tell me about agents". Only dropped before an opener a statement about him
# can't continue with — "blue is great" and "hexia can see you" stay
# statements, and "blue tells" would need the -s.
_SPOKEN_NAME_RE = re.compile(
    r"^" + _NAMES + r"\s+(?=(?:what|what's|whats|when|where|who|why|how|which"
    r"|(?:do|does|did|can|could|would|will|are|have|should) (?:you|u)"
    r"|tell|explain|describe|give|show|help|write|draft|summari[sz]e|compare"
    r"|plan|list|read|find|search|check|look|remind|let'?s|please)\b)")
# Markdown around the words: "**what** do you think", "> what do you…".
_MARKDOWN_RE = re.compile(r"(?m)^[ \t]*(?:>+|[-•]|#{1,6})[ \t]+|\*{1,3}|_{2,3}")

# "how are you", "what have you been up to", "can you hear me": check-ins whose
# answer is a line, not an essay — in any of the household languages.
_CHECKIN_RE = re.compile(
    r"^(?:and )?(?:how (?:are|r) (?:you|u|yo+u?|yuo|yho)|you okay|you ok(?:ey)?"
    r"|(?:and|what about|how about) (?:you|u)"
    r"|are you (?:ok(?:ay)?|there|awake)|(?:are )?you there"
    r"|how(?:'s|s| is| was) (?:it going|things|everything|life)"
    r"|how(?:'s|s| is| was) (?:your|the) (?:day|night|morning|afternoon|evening|weekend)"
    r"(?: going| been)?"
    r"|how (?:have|has) (?:you|your day) been|how you doing"
    r"|how(?:'s|s| is) " + _NAMES + r"(?:'s (?:day|night)(?: going)?)?"
    r"|what(?:'s|s| is) (?:up|new|happening)|sup"
    r"|what (?:have|did|were) you (?:been )?(?:up to|doing|do|done)"
    r"|tell (?:me )?about your day"
    r"|what are you (?:up to|doing)"
    r"|can you (?:still )?hear me|do you hear me"
    r"|comment (?:ça|ca) va|(?:ça|ca) va|qu'est-ce que tu (?:as fait|fais)"
    r"|как (?:дела|ты|поживаешь)|τι κάνεις|hvordan (?:går det|har du det))"
    r"(?:\s+(?:doing|today|tonight|now|right now|this (?:morning|afternoon|evening)"
    r"|lately|recently|then|again|okay|ok|alright|going|feeling|with you"
    r"|aujourd'hui|" + _NAMES + r"))*"
    r"[\s,.!?]*$")

# A class demo's hello: "say hi to the students", "introduce yourself",
# "tell everyone a bit about yourself". Introducing a COURSE is document work.
_CLASS_GREETING_RE = re.compile(
    r"\b(?:say|wave) (?:hi|hello|hey|good (?:morning|afternoon)|goodbye|bye)\b"
    r"|\bintroduce (?:yourself|yourselves)\b"
    r"|\btell (?:us|them|everyone|everybody|the (?:class|students|kids|girls|group))"
    r"\b[^.?!]{0,30}\babout yourself\b")

# Bare acknowledgements and reactions. Matched as the WHOLE message.
_ACK_WORDS = (
    r"(?:ok(?:ay)?|k+|hm+|mhm+|mm+(?:-?hmm)?|uh[- ]?huh|cool|nice|great|good"
    r"|good (?:job|one)|well done|thanks?(?: you)?(?: so much| a lot)?|thx|ty"
    r"|never ?mind|nvm|yes|yeah|yep|yup|yea|ya|no|nope|nah|sure(?:ly)?|right"
    r"|exactly|correct|true|fine|perfect|lol|(?:ha)+h?|wow|oh|ah|aha|interesting"
    r"|got it|i see|makes sense|fair enough|sounds good|alright|all right"
    r"|awesome|no need|no worries|no problem|bye(?:[- ]bye)?|goodbye|good ?night"
    r"|see (?:you|ya)"
    r"|later|so true|sh+|love it|yay|oops|sorry|my bad|that helps"
    r"|that(?:'s| is) (?:great|good|nice|fine|cool|right|it|true|funny|fair)"
    # Agreeing is not arguing: "i agree", "i think so", "not bad".
    r"|i (?:totally |completely |fully )?agree(?: with (?:you|that))?"
    r"|i (?:think|guess|suppose|hope) so|i guess|that'?s what i thought"
    r"|(?:that'?s |that is )?not bad"
    r"|indeed|agreed|cheers|noted|understood|will do|same|me too|not sure"
    r"|i don'?t know|dunno|maybe|better|much better|beautiful|brilliant"
    r"|huh|what|pardon|eh)"
)
_ACK_RE = re.compile(r"^(?:" + _ACK_WORDS + r"(?:[\s,.!?;:)(]+|$))+$")

# "go on", "try again, simpler", "what else?" ask for more of what was just
# said — the long-form turns, where reasoning earns its keep.
_CONTINUE_RE = re.compile(
    r"^(?:please\s+)?(?:go on|keep going|continue|carry on|more|tell me more"
    r"|say more|and then|what else|what more|try (?:it |that )?again|again"
    r"|one more time|do it|go ahead|redo|finish|keep talking|elaborate"
    r"|expand|go deeper|let'?s (?:try|do) (?:it|that) again|do the whole thing)\b")
# "say that again but shorter" asks for a redo; "we're celebrating her
# birthday again tomorrow" (conversation_log 9179) is news.
_AGAIN_RE = re.compile(
    r"\b(?:say|do|try|tell|explain|read|write|answer|give|show|run|start"
    r"|repeat|redo|rewrite|summari[sz]e|describe|go over|introduce|check|look"
    r"|hear|play|sing)\b[^.?!]{0,40}\bagain\b"
    r"|\b(?:one more time|repeat (?:it|that))\b|\bwrong again\b")
# A bare yes is an ack — unless it accepts something Blue just offered to do.
_ACCEPT_RE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please|go ahead|do it|go for it"
    r"|sure thing|why not|let'?s do it|sounds good|please do"
    r"|i'?d (?:like|love) (?:that|it)|that would be (?:great|nice|good|helpful))"
    r"(?:[\s,.!]+(?:please|thanks|do it|go ahead|yes))*[\s.!]*$")
_OFFER_RE = re.compile(
    r"\b(?:want me to|shall i|should i|would you like me to|like me to"
    r"|i (?:can|could) [^.?!]{0,60}\bif you(?:'d| would)? like)\b")

_URL_RE = re.compile(r"https?://|www\.\w")
# A trailing tag doesn't make a statement a question: "you know that?".
_TAG_QUESTION_RE = re.compile(
    r"[,\s]+(?:right|you know(?: that)?|isn't it|ain't it|huh|eh|no|yeah"
    r"|ok(?:ay)?)\s*\?+\s*$")
_FILLER_PREFIX_RE = re.compile(
    r"^(?:(?:ok(?:ay)?|so|well|and|but|oh|ooh|ah|huh|um+|uh+|hm+|yeah|yes|yep"
    r"|yup|alright|all right|now|then|great|good|cool|fine|sure|please)\b[\s,.!]*)+")
_PRONOUN = (r"(?:you|u|i|we|it|they|he|she|this|that|there|these|those|my|your"
            r"|our|the|a|an|any|anyone|blue|hexia|casper)")
_QUESTION_START_RE = re.compile(
    r"^(?:what|what's|whats|when|where|who|whom|whose|which|why|how|wht|wat"
    # Statements don't open on these: "is autoGPT a type of harness".
    r"|(?:do|does|did|is|are|can|could|would|will|should|shall|may|might|has)\s+\w+"
    r"|(?:was|were|have|had|must|wanna|want)\s+" + _PRONOUN +
    r"|(?:don|doesn|didn|isn|aren|wasn|weren|can|couldn|wouldn|won|shouldn|haven"
    r"|hasn)'?t\s+" + _PRONOUN + r")\b")
_REQUEST_START_RE = re.compile(
    r"^(?:tell|explain|describe|write|draft|summari[sz]e|compare|plan|help|give"
    r"|list|show|review|analy[sz]e|present|search|find|check|look|read|create"
    r"|make|translate|suggest|recommend|outline|revise|rewrite|edit|fix|think"
    r"|consider|imagine|brainstorm|critique|evaluate|push back|argue|define"
    r"|go over|walk (?:me|us) through|introduce|follow|produce|prepare"
    r"|generate|build|design|propose|develop|teach|remind|add|update|save|try|use"
    r"|send|email|open|play|zoom|correct|double check|let'?s|let me|i want you"
    r"|i'?d like you|i need you|could you|can you|would you|will you|please)\b")
# A request worded as a statement, anywhere in the message: "I was
# wondering if you could help me plan the lecture", "I'd like a lesson plan
# for friday", "any thoughts on the reading". "I need a nap" is not one.
_INDIRECT_REQUEST_RE = re.compile(
    r"\b(?:i was|i'?m|just) wondering (?:if|whether|what|how|why)\b"
    r"|\b(?:i'?d|i would) (?:like|love|appreciate)\b(?! (?:that|it|this)\b)"
    r"|\bi (?:want|need) (?:you to|your|help|some help|to (?:know|understand"
    r"|figure|plan|write|learn|prepare))\b"
    r"|\bi (?:want|need) (?:a|an|some|the)(?: \w+)? (?:plan|draft|list|summary"
    r"|outline|lesson|lecture|quiz|rubric|email|letter|reply|review|story|poem"
    r"|idea|ideas|suggestions?|title|description|paragraph|script|schedule"
    r"|report|presentation|questions?|examples?|explanation|translation)\b"
    r"|\bhelp me\b|\b(?:any|your) (?:thoughts|ideas|suggestions|advice|take)\b"
    r"|\bcurious (?:what|how|why|whether|if|about)\b")
# A short statement that argues rather than reports.
_DISCUSSION_RE = re.compile(
    r"\b(?:i think|i thought|i wonder|i'?m (?:not )?(?:so )?sure|i believe"
    r"|i feel like|i guess|it seems|seems (?:like|to)|whether|hype"
    r"|i'?ve been thinking|i'?m thinking|what if|in my view|i disagree"
    r"|i agree|my (?:view|take|sense|worry|concern)|because|the problem is"
    r"|the question is|i doubt|i suspect|arguably|on the other hand)\b|^but\b")
# Being told he got something wrong: worth re-deriving, not just a line.
_CORRECTION_RE = re.compile(
    r"^(?:no|nope|wrong|incorrect)\b[\s,.!]+\S"
    r"|^(?:wrong|incorrect)\b"
    # Saying it twice: "I said I'm working on my courses again" (9103).
    r"|^i (?:just |already )?(?:said|meant|asked)\b"
    r"|\b(?:that'?s|thats|it'?s|its|that is|it is) (?:not|wrong|incorrect|outdated)\b"
    r"|\bnot (?:right|correct|true|accurate)\b"
    r"|\b(?:you'?re|youre|you are) (?:wrong|mistaken|confused|still)\b"
    r"|\b(?:outdated|misheard|actually)\b"
    # An action that didn't happen: "the calendar is still not updated".
    r"|\bstill (?:not|wrong|getting|confused)\b"
    r"|\bnot (?:there|updated|done|added|working|fixed|saved)\b|\bdon'?t see\b"
    r"|\b(?:didn'?t|haven'?t|hasn'?t) (?:actually |actaully )?"
    r"(?:add|save|update|do|done|change|fix|set|put)\b")
# Spoken small talk: the questions whose answer is a line of personality.
_SMALL_TALK_Q_RE = re.compile(
    r"\bfavou?rite\b|\bdo you (?:like|love|enjoy|miss)\b"
    r"|\bare you (?:happy|ok(?:ay)?|bored|tired|sad|lonely|excited|ready)\b"
    r"|\bdid you (?:have (?:a|any) (?:good|nice|fun|interesting)|sleep|miss me)\b"
    r"|\bwhat(?:'s| is) my name\b|\bhaving fun\b")

# Spoken turns of this many words or fewer are small talk unless they ask
# for something of substance.
VOICE_SMALL_TALK_WORDS = 10
# Typed statements of this many words or fewer are short replies — news, a
# reaction, a fact — unless they argue or correct.
SHORT_REPLY_WORDS = 12


def _normalise(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'")
    text = _MARKDOWN_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _asks_something(text: str) -> bool:
    """A question or a request — anything that wants more than a line back.

    Any sentence counts: "it looks fine. tell me her birthday" asks.
    """
    untagged = _TAG_QUESTION_RE.sub("", text)
    if "?" in untagged or _INDIRECT_REQUEST_RE.search(text):
        return True
    for sentence in re.split(r"(?<=[.!;])\s+", text):
        bare = _FILLER_PREFIX_RE.sub("", sentence.strip())
        bare = _SPOKEN_NAME_RE.sub("", bare)
        if _QUESTION_START_RE.match(bare) or _REQUEST_START_RE.match(bare):
            return True
    return False


def _bare(text: str) -> str:
    """The message without its markdown, a greeting or the robot's name."""
    t = _normalise(text)
    t = _TRAILING_NAME_RE.sub("", _LEADING_NAME_RE.sub("", t))
    return _GREETING_PREFIX_RE.sub("", t).strip()


def asks_something(text: str) -> bool:
    """A question or a request, in any sentence of the message."""
    return _asks_something(_bare(text))


def offer_accepted(text: str, prev_reply: str = "") -> bool:
    """"sure" after "want me to draft it?": the go-ahead for the work Blue
    just offered, not an acknowledgement."""
    return bool(_ACCEPT_RE.match(_bare(text))
                and _OFFER_RE.search((prev_reply or "")[-400:].lower()))


def thinking_for_turn(text: str, *, voice: bool = False, kid: bool = False,
                      is_greeting: bool = False,
                      identity_kind: Optional[str] = None,
                      forced_tool: Optional[str] = None,
                      has_attachment: bool = False,
                      prev_reply: str = "") -> str:
    """THINK_OFF ("none") or THINK_ON ("on") for one chat turn.

    `text` is the user's own words (attachments stripped). `voice` means the
    words were spoken — the chat page's voice turns, not Panel's brevity
    flag. `is_greeting` is the selector's flag or the greeting fast path's.
    The fast path's matches loosely ("sup" opens "supervised", any short
    message opening on "hi"), as the selector's did until 7a9f70b ("hey" in
    "they"), so it only counts on a message of a few words that asks nothing.
    `prev_reply` is Blue's previous reply: "sure" after "want me to draft
    it?" is the go-ahead for real work, not an acknowledgement.
    """
    if kid:
        return THINK_OFF
    if has_attachment:
        return THINK_ON
    if forced_tool in _ACTION_TOOLS:
        return THINK_OFF
    if forced_tool in _WORK_TOOLS:
        return THINK_ON
    t = _normalise(text)
    if not t or _NAME_ONLY_RE.match(t):
        return THINK_OFF
    if _URL_RE.search(t):
        return THINK_ON
    rest = _bare(t)
    if not rest or _NAME_ONLY_RE.match(rest):
        return THINK_OFF
    if _CONTINUE_RE.match(rest):
        return THINK_ON
    if offer_accepted(rest, prev_reply):
        return THINK_ON
    words = len(rest.split())
    if _ACK_RE.match(rest) or _CHECKIN_RE.match(rest):
        return THINK_OFF
    # "I'm doing okay. What about you?" — a check-in handed back.
    _last = re.split(r"(?<=[.!?,;])\s+", rest)[-1]
    if words <= SHORT_REPLY_WORDS and (
            _CHECKIN_RE.match(_last)
            or re.search(r"\b(?:and|what about|how about) (?:you|u)\s*\??$", rest)):
        return THINK_OFF
    if identity_kind in ("self_state", "introduction"):
        return THINK_OFF
    if _CLASS_GREETING_RE.search(rest):
        return THINK_OFF
    asks = _asks_something(rest)
    # Being told he got it wrong is the same turn spoken, typed or opened on
    # "hey": "the calendar is still not updated", "its not lab 5".
    if _CORRECTION_RE.search(rest):
        return THINK_ON
    # "are they conscious?", "what is supervised learning?" and "hey blue,
    # what's RAG?" all carried the greeting flag.
    if is_greeting and words <= 4 and not asks:
        return THINK_OFF
    if _AGAIN_RE.search(rest):
        return THINK_ON
    if voice and words <= VOICE_SMALL_TALK_WORDS:
        if not asks or _SMALL_TALK_Q_RE.search(rest):
            return THINK_OFF
        return THINK_ON
    if asks or _DISCUSSION_RE.search(rest):
        return THINK_ON
    return THINK_OFF if words <= SHORT_REPLY_WORDS else THINK_ON
