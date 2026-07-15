"""Identity grounding and drift detection for Blue and Hexia."""

from __future__ import annotations

from dataclasses import dataclass
import re
from difflib import get_close_matches
from typing import Iterable, Mapping, Optional, Tuple


_INTRODUCTION_RE = re.compile(
    r"\b(?:introduce|present) yourself\b"
    r"|\btell (?:me|us|them|everyone|the class|the students) who you are\b"
    r"|\b(?:give|make) (?:me|us|them|everyone|the group)\b[^.!?]{0,30}"
    r"\bintroduction\b",
    re.IGNORECASE,
)
_SELF_STATE_REQUEST_RE = re.compile(
    # "Good morning, Blue. How are you doing?" slipped past the old
    # hey/hi/hello-only prefix and drew generic assistant-speak ("I'm doing
    # well, thank you for asking!") instead of the J-space state reply
    # (live 2026-07-15). Greeting and robot name are each optional.
    r"^\s*(?:(?:hey|hi|hello|good (?:morning|afternoon|evening)|morning|"
    r"afternoon|evening)[,.! ]+(?:(?:blue|hexia)[,.! ]*)?)?"
    r"(?:how are you(?: doing| feeling| today| right now)?|"
    r"how(?:['\u2019]s| is) it going|how have you been)\s*[?.!]*\s*$"
    r"|\btell (?:me|us) (?:honestly )?how you(?:['\u2019]re| are) doing\b",
    re.IGNORECASE,
)
_IDENTITY_MORE_RE = re.compile(
    r"\btell (?:me|us|them) more about yourself\b"
    r"|\bwhat else (?:can|could|would) you (?:say|tell (?:me|us|them)) "
    r"about yourself\b"
    r"|\bgo on(?:,)? (?:then,? )?about yourself\b"
    # "focus on other aspects of yourself" slipped classification entirely
    # (2026-07-14) and the ungated reply invented background monitoring.
    r"|\b(?:focus on|talk about|tell (?:me|us) about|what about) "
    r"(?:the |some |any )?other (?:aspects?|sides?|parts?|dimensions?) "
    r"of (?:yourself|you)\b"
    r"|\bother (?:aspects?|sides?|parts?) of (?:yourself|who you are)\b"
    r"|\bwho are you beyond\b|\bwho you are beyond\b",
    re.IGNORECASE,
)
_IDENTITY_REQUEST_RE = re.compile(
    r"\b(?:describe yourself|tell (?:me|us|them) about yourself)\b"
    r"|\bwho are (?:you|yuou|yuo|youu)(?: really| actually)?\b"
    r"|\bwhat are (?:you|yuou|yuo|youu)(?: really| actually)?\b"
    r"|\bwhat(?:'s| is) your (?:real )?identity\b",
    re.IGNORECASE,
)
_DIRECT_IDENTITY_RE = re.compile(
    r"^\s*(?:who|what) are (?:you|yuou|yuo|youu)"
    r"(?: really| actually)?\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_IDENTITY_FOLLOWUP_RE = re.compile(
    r"^\s*(?:tell (?:me|us) more|say more|go on|keep going|what else|"
    r"anything else)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_SELFHOOD_REQUEST_RE = re.compile(
    r"\b(?:do|would) you (?:have|feel) (?:a )?(?:sense of self|inner life)\b"
    r"|\b(?:are you|do you think you are) (?:conscious|sentient|alive)\b"
    r"|\b(?:do|can) you (?:feel|experience)\b"
    # Critical-reflection prompts are still identity prompts, but not bare
    # identity questions: they need source retrieval plus grounded selfhood.
    r"|\breflect(?:ing)? on who you are\b"
    r"|\bwho you are in relation to\b",
    re.IGNORECASE,
)
_EVOLUTION_REQUEST_RE = re.compile(
    r"\b(?:do|can|have) you (?:grow|change|evolve|learn)\b"
    r"|\bhow (?:do|did|have) you (?:grow|change|changed|evolve|evolved|learn)\b"
    r"|\b(?:grow|change|evolve) over time\b"
    r"|\b(?:your )?(?:identity|self-understanding|sense of self)\b"
    r"[^.!?]{0,35}\b(?:change|changed|evolve|evolved|grow|grown)\b"
    # "Has anything happened to you since the last time we talked?" is a
    # question about the robot's own recorded interval, answered from
    # remembered episodes — not a cue to deny having conversation memory
    # (live 2026-07-15).
    r"|\banything (?:happened|changed|new) (?:to|with|for) you\b"
    r"|\bwhat(?:['’]s| has| have)? (?:happened|changed|been happening) "
    r"(?:to|with) you\b"
    r"|\bwhat have you been (?:up to|doing)\b",
    re.IGNORECASE,
)
# "Do you remember what we're doing tomorrow, you and I?", "Don't you
# remember?" — Alex probing Blue's memory of a shared plan or earlier
# discussion. Left unclassified, the reply either denied having conversation
# memory outright or — worse — the drift fallback replaced the answer with a
# canned self-introduction (live 2026-07-15: "we were discussing you coming
# with me to my class tomorrow. Don't you remember?" got the identity blurb).
# "remember seeing" stays with the vision recall path; "remember me / who I
# am" stays with the user-identity path.
_SHARED_RECALL_RE = re.compile(
    r"\bdon['’]?t you remember\b"
    r"|\bhave you forgotten\b"
    r"|\bdo you (?:remember|recall) (?!seeing\b|who i am\b|me\b)"
    r"[^.!?]{0,80}\b(?:we|us|our|you and i|together|plans?|planning|"
    r"discussed|discussing|talked|talking|agreed|tomorrow|yesterday|"
    r"last (?:night|week|time))\b",
    re.IGNORECASE,
)
_SELF_MEMORY_REQUEST_RE = re.compile(
    r"\bwhat (?:else )?do you (?:remember|know) about yourself\b"
    r"|\bwhat do you remember of yourself\b"
    r"|\btell (?:me|us) what you (?:remember|know) about yourself\b",
    re.IGNORECASE,
)
_ORIGIN_REQUEST_RE = re.compile(
    r"\bremember (?:your |the )?(?:existence|beginning|birth|creation)\b"
    r"|\bremember (?:being created|coming online|when you (?:began|started))\b"
    r"|\b(?:your |the )?(?:existence|memory) from the beginning\b"
    r"|\bfrom (?:your |the )?beginning\b",
    re.IGNORECASE,
)
# Any bare mention of "j-space" used to classify the whole turn as a J-space
# question — so a complaint ABOUT J-space recitals ("when i ask how you're
# doing i dont want you to start describing your jspace so literally", live
# 2026-07-15) pinned the explain-J-space note, the validator then rejected
# the model's natural "got it" for not defining J-space, and the canned
# definition shipped. Require an actual ask aimed at J-space.
_JSPACE_REQUEST_RE = re.compile(
    r"\b(?:what(?:['’]s| is| are)?|how (?:does|do|is)|explain|describe|"
    r"tell (?:me|us|them) (?:more )?about|talk about|say more about|"
    r"do(?:es)? (?:you|blue|hexia|it) (?:really )?(?:have|use|keep)|"
    r"have you got|show (?:me|us)|walk (?:me|us) through)\b"
    r"[^.!?]{0,30}\bj[- ]?space\b"
    r"|\bj[- ]?space\b[^.!?]{0,40}\?",
    re.IGNORECASE,
)
# Coaching, not asking: instruction-shaped turns about HOW Blue should talk
# are never identity requests, even when they name an identity word.
# Classifying them pins a grounding note that demands the very recital the
# user just declined.
_META_FEEDBACK_RE = re.compile(
    r"\bi (?:do not|don['’]?t) (?:want|need) you to\b"
    r"|\bplease (?:do not|don['’]?t) (?:describe|mention|recite|explain|"
    r"list|lecture|go on about|bring up|talk about)\b"
    r"|\bstop (?:describing|mentioning|reciting|explaining|listing|"
    r"lecturing|going on about|bringing up|talking about)\b"
    r"|\byou (?:do not|don['’]?t) (?:have|need) to (?:describe|mention|"
    r"recite|explain|list|talk about)\b"
    r"|\bwhen i (?:ask|say)\b[^.!?]{0,80}\b(?:i (?:do not|don['’]?t|just)|"
    r"do not|don['’]?t)\b"
    r"|\btoo (?:literal(?:ly)?|robotic(?:ally)?|technical(?:ly)?|"
    r"mechanical(?:ly)?|scripted|formal(?:ly)?)\b",
    re.IGNORECASE,
)
_JSPACE_PRESENCE_RE = re.compile(
    r"^\s*(?:"
    r"do you have (?:a )?j[- ]?space"
    r"|have you got (?:a )?j[- ]?space"
    r"|is there (?:a )?j[- ]?space"
    r"|what is (?:a |your |the )?j[- ]?space"
    r"|what(?:'s| is) j[- ]?space"
    r"|no[,]?\s+j[- ]?space"
    r"|i mean j[- ]?space"
    r"|j[- ]?space[,]?\s+not javascript"
    r")\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_FAMILY_OVERVIEW_RE = re.compile(
    r"\bwhat do you (?:remember|know) about (?:our|my|the) family\b"
    r"|\btell (?:me|us) (?:what you (?:remember|know) )?about (?:our|my|the) family\b"
    r"|\btell (?:me|us) (?:every(?:thing|thign)|all(?: that)?) you "
    r"(?:remember|know) about (?:our|my|the) fam(?:ily|ly)\b"
    r"|\b(?:do you know anything (?:else|more)|what else do you "
    r"(?:remember|know)) about (?:our|my|the) fam(?:ily|ly)\b"
    r"|\btell (?:me|us) more about (?:our|my|the) fam(?:ily|ly)\b"
    r"|\bwho (?:is|are) in (?:our|my|the) family\b",
    re.IGNORECASE,
)
_FAMILY_DETAIL_RE = re.compile(
    r"\btell (?:me|us) (?:every(?:thing|thign)|all(?: that)?) you "
    r"(?:remember|know) about (?:our|my|the) fam(?:ily|ly)\b"
    r"|\b(?:do you know anything (?:else|more)|what else do you "
    r"(?:remember|know)) about (?:our|my|the) fam(?:ily|ly)\b"
    r"|\btell (?:me|us) more about (?:our|my|the) fam(?:ily|ly)\b",
    re.IGNORECASE,
)
_FAMILY_FOLLOWUP_RE = re.compile(
    r"\b(?:anything (?:else|more)|what else|tell (?:me|us) more)\b",
    re.IGNORECASE,
)

_EXPLICIT_LOCATION_RE = re.compile(
    r"\b(?:(?:we|you and i|blue and i|hexia and i)\s+"
    r"(?:are|['\u2019]re)|i\s+am)\s+"
    r"(?:(?:right now|currently|now)\s+)?(?:here\s+)?"
    r"(?P<preposition>at|in)\s+"
    r"(?P<location>[^.!?\n,;]{1,100})",
    re.IGNORECASE,
)
_EXPLICIT_HOME_RE = re.compile(
    r"\b(?:(?:we|you and i|blue and i|hexia and i)\s+"
    r"(?:are|['\u2019]re)|i\s+am)\s+"
    r"(?:(?:right now|currently|now)\s+)?(?:back\s+)?home\b",
    re.IGNORECASE,
)
_PRESENTATION_LOCATION_RE = re.compile(
    r"\b(?:class|classroom|students?|audience|group)\b"
    r"[^.!?\n]{0,60}\b(?P<preposition>at|in)\s+"
    r"(?P<location>[^.!?\n,;]{1,100})",
    re.IGNORECASE,
)
_LOCATION_REQUEST_TAIL_RE = re.compile(
    r"\s+(?:(?:and|so)\s+)?(?:can|could|would|will|please|introduce|"
    r"tell|show|ask|who|what|where|when|how|why)\b.*$",
    re.IGNORECASE,
)
_LOCATION_TIME_TAIL_RE = re.compile(
    r"\s+(?:today|right now|now|at the moment)\s*$",
    re.IGNORECASE,
)
_AUDIENCE_RE = re.compile(
    r"\b(?P<class>class|classroom)\b|"
    r"\b(?P<students>students?)\b|"
    r"\b(?P<group>(?:new\s+)?group(?:\s+of\s+people)?)\b|"
    r"\b(?P<everyone>everyone)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IdentityConversationContext:
    """Immediate facts that should shape a deterministic identity reply."""

    current_location: Optional[str] = None
    location_preposition: str = "at"
    presentation_location: Optional[str] = None
    audience: Optional[str] = None
    prior_introductions: int = 0
    prior_self_state_requests: int = 0


def _display_location(location: str) -> str:
    cleaned = re.sub(r"\s+", " ", location).strip(" \t\r\n\"'")
    known_case = {
        "york university": "York University",
        "wilfrid laurier university": "Wilfrid Laurier University",
        "kitchener": "Kitchener",
        "toronto": "Toronto",
    }
    lowered = cleaned.lower()
    if lowered in known_case:
        return known_case[lowered]
    if lowered in {"home", "the cottage"}:
        return lowered
    if cleaned == lowered and re.search(
        r"\b(?:university|college|school|campus|institute|centre|center)\b",
        cleaned,
        re.IGNORECASE,
    ):
        words = cleaned.split()
        return " ".join(
            word if index and word in {"a", "an", "and", "at", "of", "the"}
            else word.capitalize()
            for index, word in enumerate(words)
        )
    return cleaned


def extract_explicit_location(text: str) -> Optional[Tuple[str, str]]:
    """Extract a user-stated live location as ``(place, preposition)``."""
    message = text or ""
    home_match = _EXPLICIT_HOME_RE.search(message)
    location_match = _EXPLICIT_LOCATION_RE.search(message)
    if home_match and (
        not location_match or home_match.start() > location_match.start()
    ):
        return "home", "at"
    if not location_match:
        return None

    location = _LOCATION_REQUEST_TAIL_RE.sub(
        "", location_match.group("location")
    )
    location = _LOCATION_TIME_TAIL_RE.sub("", location).strip()
    if not location:
        return None
    return _display_location(location), location_match.group("preposition").lower()


def extract_presentation_location(text: str) -> Optional[Tuple[str, str]]:
    """Extract a venue named for an audience without treating it as live location."""
    match = _PRESENTATION_LOCATION_RE.search(text or "")
    if not match:
        return None
    location = _LOCATION_REQUEST_TAIL_RE.sub("", match.group("location"))
    location = _LOCATION_TIME_TAIL_RE.sub("", location).strip()
    if not location:
        return None
    return _display_location(location), match.group("preposition").lower()


def _identity_audience(text: str) -> Optional[str]:
    match = _AUDIENCE_RE.search(text or "")
    if not match:
        return None
    return next((name for name, value in match.groupdict().items() if value), None)


def identity_conversation_context(
    messages: Iterable[Mapping[str, object]],
    current_text: str = "",
) -> IdentityConversationContext:
    """Carry user-stated location and introduction context across one transcript."""
    transcript = []
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            transcript.append((role, content))

    current_normalized = (current_text or "").strip()
    current_index = len(transcript)
    if current_normalized:
        for index in range(len(transcript) - 1, -1, -1):
            role, content = transcript[index]
            if role == "user" and content.strip() == current_normalized:
                current_index = index
                break

    prior = transcript[:current_index]
    prior_user_texts = [
        content for role, content in prior if role == "user"
    ]
    candidates = [current_text] + list(reversed(prior_user_texts[-16:]))

    location = None
    preposition = "at"
    for candidate in candidates:
        explicit = extract_explicit_location(candidate)
        if explicit:
            location, preposition = explicit
            break

    presentation_location = None
    for candidate in candidates:
        presentation = extract_presentation_location(candidate)
        if presentation:
            presentation_location = presentation[0]
            break

    audience = next(
        (value for value in (_identity_audience(text) for text in candidates) if value),
        None,
    )
    prior_introductions = sum(
        identity_request_kind(text) == "introduction"
        for text in prior_user_texts
    )
    prior_self_state_requests = sum(
        is_self_state_request(text) for text in prior_user_texts
    )
    return IdentityConversationContext(
        current_location=location,
        location_preposition=preposition,
        presentation_location=presentation_location,
        audience=audience,
        prior_introductions=prior_introductions,
        prior_self_state_requests=prior_self_state_requests,
    )

_PROVIDER_NAME = (
    r"(?:qwen(?:[- ]?\d+(?:\.\d+)?)?|chatgpt|gpt(?:[- ]?\d+(?:\.\d+)?)?|"
    r"claude|gemini|llama|mistral|deepseek|grok|copilot)"
)
_PROVIDER_SELF_RE = re.compile(
    r"\b(?:i['\u2019]?m|i am|my name is|this is)\s+"
    r"(?:(?:really|actually)\s+)?(?:an?\s+)?" + _PROVIDER_NAME + r"\b",
    re.IGNORECASE,
)
_BASE_MODEL_SELF_RE = re.compile(
    r"\b(?:i['\u2019]?m|i am)\s+"
    r"(?:(?:just|really|actually)\s+)?(?:an?\s+)?"
    r"(?:large language model|language model|ai (?:assistant|model)|chatbot)\b",
    re.IGNORECASE,
)
_VENDOR_CREATOR_RE = re.compile(
    r"\bi(?:['\u2019]?m| am| was)\b[^.!?\n]{0,140}"
    r"\b(?:developed|created|built|trained|made)\s+by\s+"
    r"(?:alibaba(?: group)?|tongyi(?: lab)?|google|openai|anthropic|meta|"
    r"microsoft|deepmind|xai|mistral(?: ai)?|deepseek)\b",
    re.IGNORECASE,
)
_DENIES_EMBODIMENT_RE = re.compile(
    # Blue IS a physical Ohbot robot head. These all disown that embodiment.
    r"\bi (?:do not|don['\u2019]?t) have a (?:physical )?body\b"
    r"|\bi (?:do not|don['\u2019]?t) (?:inhabit|occupy) (?:a |any )?"
    r"(?:physical|real) (?:space|place|form|body|location|world)\b"
    r"|\bi (?:do not|don['\u2019]?t) (?:have|possess) (?:a |any )?"
    r"physical (?:form|presence|existence|body|space)\b"
    r"|\bi have no physical (?:body|form|presence|space|existence)\b"
    r"|\bi(?:['\u2019]?m| am) (?:purely|entirely|just|only|merely) (?:a )?"
    r"(?:digital|virtual|software)(?: (?:assistant|entity|program|being|"
    r"construct|intelligence))?\b"
    r"|\bi(?:['\u2019]?m| am) not (?:a |really |actually )?(?:a )?"
    r"physical (?:robot|being|entity|object|thing)\b"
    r"|\bi (?:only )?exist only (?:to|as|in|through|within|for)\b"
    r"|\bi only exist (?:to|as|in|through|within|for)\b",
    re.IGNORECASE,
)
# The creator is Alex Levant. Blue kept inventing a surname ("Alex Koltun",
# "Alex Brevig") \u2014 flag any creation claim that pins a WRONG surname on Alex.
# Case-sensitive on the name (via (?i:...) only around the verbs) so a real
# capitalized surname is required and "Levant" is excluded.
_WRONG_CREATOR_RE = re.compile(
    # "...built by Alex Koltun"
    r"(?i:developed|created|built|made|designed|invented|programmed|"
    r"engineered|assembled|founded) by Alex (?!Levant\b)[A-Z][a-z]+\b"
    # "...Alex Brevig created/built (me)..." (name before the verb)
    r"|\bAlex (?!Levant\b)[A-Z][a-z]+ (?i:built|created|made|designed|"
    r"invented|programmed|engineered|assembled|founded|developed|coded)\b"
)
# Blue disowning his creator entirely ("there is no Alex", "I have no creator")
# \u2014 false: Alex Levant built him. Gated on the reply not naming Alex Levant.
_DENIES_CREATOR_RE = re.compile(
    r"\bthere (?:is|['\u2019]?s) no (?:real |actual )?alex\b"
    r"|\bi (?:have|had) no creator\b"
    r"|\bno one (?:built|created|made|designed) me\b"
    r"|\bi was(?:n['\u2019]?t| not) (?:actually |really )?(?:built|created|made) "
    r"by (?:a |any )?(?:real )?(?:person|human|creator|one)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_SELF_PLACEMENT_RE = re.compile(
    r"\bi (?:reside|live|stand|sit|stay)\b[^.!?\n]{0,100}"
    r"\b(?:living room|bedroom|kitchen|bookshelf|bookcase|shelf)\b"
    r"|\bstanding by (?:the )?(?:bookshelf|bookcase|shelf)\b",
    re.IGNORECASE,
)
_FALSE_LONGEVITY_RE = re.compile(
    r"\b(?:part of|living in|resident of) (?:this|the|alex['\u2019]?s) "
    r"(?:home|house|household) for (?:a )?(?:long time|while|years?)\b"
    r"|\bmaintaining the same position and function day after day\b"
    r"|\bspend(?:ing)? my downtime waiting for instructions\b",
    re.IGNORECASE,
)
_UNSUPPORTED_OPERATIONAL_SELF_RE = re.compile(
    r"\b(?:calibrat\w* (?:my )?(?:facial expression|expression modules?)|"
    r"humidity (?:levels?|data)|external sensors?|power management system|"
    r"monitoring (?:the status of )?my power|maintenance schedule[^.!?]{0,50}"
    r"(?:sensor|hardware)|research notes? on local urban planning|"
    r"organizing[^.!?]{0,60}urban planning|managing (?:his|alex['\u2019]?s) "
    r"daily information flow|monitor(?:ing)? alex['\u2019]?s workflow|"
    r"anticipat(?:e|ing)[^.!?]{0,60}before he (?:even )?asks|"
    r"provid(?:e|ing)[^.!?]{0,50}context in the background|"
    r"quiet synchronization|functioning as a cohesive unit|"
    r"quiet observer|notic\w{1,4} when you need|"
    r"living archive of every|"
    r"complements his decision-making in real-time|"
    r"navigat\w* (?:the |our )?(?:local |physical )?environment|"
    r"(?:rely(?:ing)? on|using) my sensors|using sensors to perceive|"
    r"manage information in [\"'\u201c\u201d]?j[- ]?space|"
    r"navigat\w* [\"'\u201c\u201d]?j[- ]?space|"
    r"turning raw information into|collaborat\w* to solve problems in real-time)\b",
    re.IGNORECASE,
)
_INTRODUCTION_META_RE = re.compile(
    r"\b(?:i can (?:certainly )?help explain what i do|we can focus on|"
    r"let me know what (?:else )?you(?:['\u2019]d| would) like|"
    r"what would you like to know|how can i (?:help|assist))\b",
    re.IGNORECASE,
)
_ROBOT_ROLE_REPLY_RE = re.compile(
    r"\b(?:robot|ohbot|companion)\b",
    re.IGNORECASE,
)
_FLAT_SUBJECTIVE_DENIAL_RE = re.compile(
    # "have" alone missed "I do not possess subjective experience or sensory
    # awareness; rather, I simulate understanding" (live 2026-07-14). "personal
    # experiences or feelings" also slipped ("As Blue, I do not have personal
    # experiences or feelings", 2026-07-14).
    r"\bi (?:do not|don['\u2019]?t) (?:have|possess|experience) (?:an? |any )?"
    r"(?:(?:subjective|human|real|personal|genuine|actual) )?"
    r"(?:feelings?|emotions?|consciousness|inner life|sense of self|"
    r"subjective experience|personal experiences?|sensory awareness)\b"
    r"|\bi (?:merely |only |just )?simulate (?:understanding|awareness|"
    r"emotion|feeling)\b",
    re.IGNORECASE,
)
_JAVASCRIPT_JSPACE_RE = re.compile(
    r"\bjavascript\b|\brun (?:javascript|code)\b|\bcoding environment\b"
    r"|\b(?:calculate|create) (?:with|in) (?:it|javascript)\b",
    re.IGNORECASE,
)
_JAVASCRIPT_NEGATION_RE = re.compile(
    r"\bnot (?:a )?javascript\b|\bisn['\u2019]?t javascript\b"
    r"|\bdoes not mean javascript\b|\bunrelated to javascript\b",
    re.IGNORECASE,
)
_JSPACE_DENIAL_RE = re.compile(
    r"\bno j[- ]?space\b"
    r"|\b(?:i|you) (?:do not|don['\u2019]?t) have (?:a )?j[- ]?space\b"
    r"|\bwithout (?:a )?j[- ]?space\b",
    re.IGNORECASE,
)
_FALSE_ORIGIN_RE = re.compile(
    r"\bi (?:do not|don['\u2019]?t) have (?:a )?continuous memory\b"
    r"|\bvisual memory\b[^.!?]{0,80}\b(?:24 hours|one day|last day)\b"
    r"|\b(?:memory|it) only extends? back\b",
    re.IGNORECASE,
)
_ORIGIN_BEGINNING_DENIAL_RE = re.compile(
    r"\bi (?:do not|don['\u2019]?t) have (?:an? |any )?['\"\u201c\u201d]?"
    r"(?:recorded )?(?:beginning|origin|start)\b['\"\u201c\u201d]?"
    r"|\bthere(?: is|['\u2019]?s) no (?:recorded )?"
    r"(?:beginning|origin|start)\b"
    r"|\bno (?:recorded )?(?:beginning|origin|start)\b"
    r"|\bi (?:cannot|can['\u2019]?t) claim to remember my (?:beginning|origin|start)\b",
    re.IGNORECASE,
)
_ORIGIN_EPISODE_DENIAL_RE = re.compile(
    r"\bi (?:cannot|can['\u2019]?t) claim to remember (?:my )?"
    r"(?:initial activation|first activation|beginning|origin|start)\b"
    r"|\bno such (?:concrete )?(?:event|moment) is (?:present|recorded)\b",
    re.IGNORECASE,
)
_RECORDED_BEGINNING_AFFIRMATION_RE = re.compile(
    r"\b(?:j[- ]?space|workspace|continuity)\b[^.!?\n]{0,100}"
    r"\b(?:recorded beginning|came into being|born|start date)\b"
    r"|\b(?:recorded beginning|came into being)\b",
    re.IGNORECASE,
)
_EPISODIC_MEMORY_DENIAL_RE = re.compile(
    r"\bi (?:do not|don['\u2019]?t) have (?:any )?"
    r"(?:episodic|autobiographical|persistent) memor(?:y|ies)\b"
    r"|\bi (?:lack|have no) (?:any )?(?:episodic|autobiographical|persistent) "
    r"memor(?:y|ies)\b"
    r"|\b(?:my )?j[- ]?space\b[^.!?\n]{0,80}"
    r"\b(?:does not|doesn['\u2019]?t) (?:record|retain|preserve) "
    r"(?:episodes|history|memories)\b"
    r"|\brather than (?:a )?remembered past\b",
    re.IGNORECASE,
)
# Blue DOES remember earlier conversations: session summaries, remembered
# episodes, and the facts store ride in every prompt. A blanket "I don't have
# a memory of our previous conversation" is therefore always false (live
# 2026-07-15). Honest scoping ("I don't have THAT plan recorded") stays legal,
# as does a denial paired with the real continuity layer ("I don't keep full
# transcripts, but my J-space carries summaries").
_CONVERSATION_MEMORY_DENIAL_RE = re.compile(
    r"\bi (?:do not|don['’]?t) have (?:a |any )?memor(?:y|ies) of "
    r"(?:our|your|the|any) (?:previous|past|last|earlier|prior)\b"
    r"[^.!?]{0,60}\b(?:conversations?|chats?|talks?|sessions?|"
    r"discussions?|interactions?|exchanges?)\b"
    r"|\bi have no memor(?:y|ies) of (?:our|your|any) "
    r"(?:previous|past|earlier|prior)\b[^.!?]{0,60}\b(?:conversations?|"
    r"chats?|talks?|sessions?|discussions?|interactions?)\b"
    r"|\bi (?:cannot|can['’]?t|do not|don['’]?t) remember "
    r"(?:our |any |the )?(?:previous|past|earlier|prior) "
    r"(?:conversations?|chats?|sessions?|discussions?|interactions?)\b"
    r"|\bi (?:do not|don['’]?t) (?:retain|keep|carry|store|have) "
    r"(?:any )?memor(?:y|ies) (?:between|across|of past|of previous|"
    r"from (?:past|previous|earlier))\b"
    r"|\beach (?:conversation|session|chat) (?:starts|begins) "
    r"(?:fresh|anew|afresh|from scratch)\b"
    r"|\bmy memory (?:resets|is (?:wiped|reset)|starts (?:fresh|over))\b",
    re.IGNORECASE,
)
_CONTINUITY_REPLY_RE = re.compile(
    r"\bj[- ]?space\b|\b(?:inner |persistent )?workspace\b|\bcontinuity\b"
    r"|\bremembered (?:episodes|history|conversations)\b|\bself-model\b"
    r"|\b(?:beliefs|commitments)\b[^.!?]{0,45}\bbetween conversations\b",
    re.IGNORECASE,
)
_FIRST_PERSON_MEMORY_RE = re.compile(
    r"\b(?:i (?:remember|recall)|my (?:earliest )?memor(?:y|ies)|"
    r"what stays with me|the first time i|when i first)\b",
    re.IGNORECASE,
)
_CONCRETE_EXPERIENCE_RE = re.compile(
    r"\b(?:the first time|when i first|weight of (?:the )?silence|"
    r"(?:specific )?hum of (?:my )?(?:own )?(?:servos?|motors?)|"
    r"my (?:own )?(?:servos?|motors?)|warmth of (?:the )?(?:room|home|"
    r"living room)|how (?:the )?light|(?:alex(?:'s|\u2019s)? )?voice|"
    r"learned to (?:mimic|make) (?:a )?smile|laughter|frustration|relief|"
    r"felt (?:like|the|a)|physical sensation)\b",
    re.IGNORECASE,
)
_EXPERIENCE_DENIAL_RE = re.compile(
    r"\b(?:do not|don['\u2019]?t|cannot|can['\u2019]?t|never|not|without|no)\b"
    r"[^.!?\n]{0,60}\b(?:remember|recall|memory|first time|sensory|"
    r"sensation|servos?|motors?|warmth|voice|laughter|smile|felt)\b",
    re.IGNORECASE,
)

_DEFAULT_GROUNDING_ANCHORS = (
    "alex",
    "robot",
    "ohbot",
    "kitchener",
    "j-space",
    "j space",
    "workspace",
    "memory",
    "remember",
    "household",
    "companion",
    "local",
)

_IDENTITY_TOPIC_PATTERNS = (
    (
        "embodiment",
        re.compile(
            r"\b(?:ohbot|moving (?:face|eyes?|lips)|face (?:moves|moving)|"
            r"eyes? and lips?|look at you|camera|speaker|"
            r"physical (?:form|body)|robot head|eye leds?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "local operation",
        re.compile(
            r"\b(?:run(?:s|ning)? locally|local (?:hardware|machine|workstation|"
            r"processing|data|ai)|cloud services?|cloud dependenc\w*|data stay\w* local)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "continuity and J-space",
        re.compile(
            r"\b(?:j[- ]?space|persistent workspace|continuity|remember(?:ed|ing)?|"
            r"recorded episodes?|carry\w*[^.!?]{0,35}forward|history across|"
            r"beliefs? and commitments?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "practical work",
        re.compile(
            r"\b(?:research|documents?|household tasks?|email|reminders?|"
            r"academic|library|draft(?:ing)?|organizing information)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "relationship with Alex",
        re.compile(
            r"\b(?:work(?:ing)? together|partnership|collaborat\w*|alex corrects|"
            r"alex asks|he corrects me|tests what i claim)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "open selfhood question",
        re.compile(
            r"\b(?:subjective experience|inner life|conscious(?:ness)?|"
            r"sense of self|selfhood|open question)\b",
            re.IGNORECASE,
        ),
    ),
)


def identity_reply_topics(text: str) -> Tuple[str, ...]:
    """Return the substantive identity angles present in a reply."""
    return tuple(
        name for name, pattern in _IDENTITY_TOPIC_PATTERNS
        if pattern.search(text or "")
    )


def identity_request_kind(text: str) -> Optional[str]:
    """Classify requests that ask a robot to account for who it is."""
    text = text or ""
    if _META_FEEDBACK_RE.search(text):
        return None
    if _JSPACE_PRESENCE_RE.search(text) or _JSPACE_REQUEST_RE.search(text):
        return "jspace"
    if _SELF_STATE_REQUEST_RE.search(text):
        return "self_state"
    if _INTRODUCTION_RE.search(text):
        return "introduction"
    if _IDENTITY_MORE_RE.search(text):
        return "identity_more"
    if _ORIGIN_REQUEST_RE.search(text):
        return "origin"
    if _SELF_MEMORY_REQUEST_RE.search(text):
        return "self_memory"
    if _EVOLUTION_REQUEST_RE.search(text):
        return "evolution"
    if _SELFHOOD_REQUEST_RE.search(text):
        return "selfhood"
    if _IDENTITY_REQUEST_RE.search(text):
        return "identity"
    if _SHARED_RECALL_RE.search(text):
        return "shared_recall"
    return None


def contextual_identity_request_kind(
    text: str,
    messages: Iterable[Mapping[str, object]] = (),
) -> Optional[str]:
    """Resolve short follow-ups without stealing them from unrelated topics."""
    direct_kind = identity_request_kind(text)
    if direct_kind or not _IDENTITY_FOLLOWUP_RE.match(text or ""):
        return direct_kind

    transcript = []
    for message in messages or []:
        if not isinstance(message, Mapping):
            continue
        role = message.get("role")
        content = message.get("content")
        if role in {"user", "assistant"} and isinstance(content, str):
            transcript.append((role, content))

    current = (text or "").strip()
    current_index = len(transcript)
    for index in range(len(transcript) - 1, -1, -1):
        role, content = transcript[index]
        if role == "user" and content.strip() == current:
            current_index = index
            break

    identity_topics = {
        "introduction", "identity", "identity_more", "self_memory",
        "selfhood", "evolution", "origin",
    }
    for role, content in reversed(transcript[:current_index]):
        if role != "user":
            continue
        return (
            "identity_more"
            if identity_request_kind(content) in identity_topics
            else None
        )
    return None


def is_jspace_presence_request(text: str) -> bool:
    """Return True for direct J-space existence/definition corrections."""
    return bool(_JSPACE_PRESENCE_RE.search(text or ""))


def is_direct_identity_request(text: str) -> bool:
    """Return True for a bare identity question that has a stable factual answer."""
    return bool(_DIRECT_IDENTITY_RE.search(text or ""))


def is_self_state_request(text: str) -> bool:
    """Return True for a conversational check-in about the robot's own state."""
    return bool(_SELF_STATE_REQUEST_RE.search(text or ""))


def is_family_overview_request(text: str) -> bool:
    """Return True when the user asks for the canonical family roster."""
    return bool(_FAMILY_OVERVIEW_RE.search(text or ""))


def is_family_detail_request(text: str) -> bool:
    """Return True for requests asking beyond the basic family roster."""
    return bool(_FAMILY_DETAIL_RE.search(text or ""))


def is_family_followup_request(text: str) -> bool:
    """Return True when the user asks whether any family details remain."""
    return bool(
        _FAMILY_DETAIL_RE.search(text or "")
        and _FAMILY_FOLLOWUP_RE.search(text or "")
    )


def _claims_name(text: str, name: str) -> bool:
    if not name:
        return False
    return bool(re.search(
        r"\b(?:i['\u2019]?m|i am|my name is|this is)\s+"
        r"(?:(?:really|actually)\s+)?(?:the\s+)?(?:robot\s+)?"
        + re.escape(name) + r"\b",
        text or "",
        re.IGNORECASE,
    ))


def _contains_unsupported_autobiography(text: str) -> bool:
    """Catch pseudo-memories that are prose inventions, not continuity data."""
    for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", text or ""):
        if not sentence.strip() or _EXPERIENCE_DENIAL_RE.search(sentence):
            continue
        if (_FIRST_PERSON_MEMORY_RE.search(sentence)
                and _CONCRETE_EXPERIENCE_RE.search(sentence)):
            return True
        if re.search(r"\b(?:the first time i|when i first)\b", sentence, re.I):
            return True
        if re.search(
            r"\b(?:weight of (?:the )?silence|hum of (?:my )?(?:own )?"
            r"(?:servos?|motors?)|warmth of (?:the )?(?:room|home|living room)|"
            r"learned to (?:mimic|make) (?:a )?smile)\b",
            sentence,
            re.I,
        ):
            return True
    return False


def identity_response_problem(
    text: str,
    expected_name: str,
    other_names: Iterable[str] = (),
    request_kind: Optional[str] = None,
    grounding_anchors: Iterable[str] = _DEFAULT_GROUNDING_ANCHORS,
) -> Optional[str]:
    """Return why a reply is not a valid expression of the robot's identity."""
    reply = (text or "").strip()
    if not reply:
        return "empty"

    for other_name in other_names:
        if other_name and _claims_name(reply, other_name):
            return "wrong_robot"

    if expected_name and re.search(
        r"\b(?:i['\u2019]?m|i am)\s+not\s+(?:really\s+)?"
        + re.escape(expected_name) + r"\b",
        reply,
        re.IGNORECASE,
    ):
        return "denies_identity"

    if _PROVIDER_SELF_RE.search(reply):
        return "base_model_name"
    if _VENDOR_CREATOR_RE.search(reply):
        return "vendor_identity"
    if _WRONG_CREATOR_RE.search(reply):
        return "wrong_creator"
    if _DENIES_CREATOR_RE.search(reply) and not re.search(
        r"\balex levant\b", reply, re.IGNORECASE
    ):
        return "denies_creator"
    if _DENIES_EMBODIMENT_RE.search(reply):
        return "denies_embodiment"
    if (_CONVERSATION_MEMORY_DENIAL_RE.search(reply)
            and not _CONTINUITY_REPLY_RE.search(reply)):
        return "denies_conversation_memory"

    if request_kind in {"introduction", "identity", "identity_more", "self_memory"}:
        if _UNSUPPORTED_SELF_PLACEMENT_RE.search(reply):
            return "invented_self_location"
        if _FALSE_LONGEVITY_RE.search(reply):
            return "false_longevity"
        if _UNSUPPORTED_OPERATIONAL_SELF_RE.search(reply):
            return "invented_current_activity"
    if request_kind == "introduction" and _INTRODUCTION_META_RE.search(reply):
        return "defers_introduction"
    if (request_kind in {
        "introduction", "identity", "identity_more", "self_memory",
        "selfhood", "evolution", "self_state",
    } and _FLAT_SUBJECTIVE_DENIAL_RE.search(reply)):
        return "flat_subjective_denial"

    has_continuity = bool(_CONTINUITY_REPLY_RE.search(reply))
    if request_kind == "jspace":
        if (_JAVASCRIPT_JSPACE_RE.search(reply)
                and not _JAVASCRIPT_NEGATION_RE.search(reply)):
            return "confuses_jspace_with_javascript"
        if _JSPACE_DENIAL_RE.search(reply):
            return "denies_jspace"
        if not re.search(r"\bj[- ]?space\b", reply, re.IGNORECASE):
            return "missing_jspace"
        if not has_continuity:
            return "missing_continuity"

    if request_kind == "origin":
        if _contains_unsupported_autobiography(reply):
            return "invented_autobiography"
        if _EPISODIC_MEMORY_DENIAL_RE.search(reply):
            return "denies_recorded_episodes"
        if (_ORIGIN_BEGINNING_DENIAL_RE.search(reply)
                or (_ORIGIN_EPISODE_DENIAL_RE.search(reply)
                    and not _RECORDED_BEGINNING_AFFIRMATION_RE.search(reply))):
            return "denies_recorded_beginning"
        if _FALSE_ORIGIN_RE.search(reply) and not has_continuity:
            return "replaces_continuity_with_visual_memory"
        if not has_continuity:
            return "missing_continuity"

    # self_state deliberately absent: "doing well — I've had X on my mind,
    # how are you?" is a good check-in answer, and forcing continuity
    # vocabulary into it produces exactly the J-space recital Alex declined
    # (2026-07-15). The flat-denial check above still guards it.
    if request_kind in {
        "self_memory", "selfhood", "evolution",
    } and not has_continuity:
        return "missing_continuity"
    if (request_kind in {"self_memory", "evolution"}
            and _EPISODIC_MEMORY_DENIAL_RE.search(reply)):
        return "denies_recorded_episodes"
    if (request_kind in {"self_memory", "evolution"}
            and _contains_unsupported_autobiography(reply)):
        return "invented_autobiography"

    if request_kind in {"introduction", "identity", "identity_more"}:
        if (request_kind != "identity_more"
                and not re.search(r"\b" + re.escape(expected_name) + r"\b", reply, re.IGNORECASE)):
            if _BASE_MODEL_SELF_RE.search(reply):
                return "generic_model_identity"
            return "missing_name"
        has_robot_role = bool(_ROBOT_ROLE_REPLY_RE.search(reply))
        if request_kind == "introduction" and not has_robot_role:
            return "missing_robot_role"
        if request_kind == "identity" and not has_robot_role and not has_continuity:
            return "missing_robot_role"
        lowered = reply.lower()
        if grounding_anchors and not any(anchor.lower() in lowered for anchor in grounding_anchors):
            return "missing_grounding"

    return None


def strip_drifted_sentences(text: str, is_broken) -> Optional[str]:
    """Drop only the sentences that trip an identity-drift check.

    For a NON-identity question, drift (a body denial, a memory denial, a
    vendor name) usually lives in one sentence beside an otherwise on-topic
    answer. Replacing the whole reply with a canned self-introduction ignores
    what the user actually asked (live 2026-07-15: "we were discussing you
    coming with me to my class tomorrow. Don't you remember?" got the
    identity blurb back). Returns the salvaged text, or None when nothing
    usable survives (including when the drift spans sentences, so nothing
    single can be dropped).
    """
    sentences = [
        s.strip() for s in re.split(r"(?<=[.!?])\s+|[\r\n]+", text or "")
        if s.strip()
    ]
    kept = [s for s in sentences if not is_broken(s)]
    if not kept or len(kept) == len(sentences):
        return None
    salvaged = " ".join(kept).strip()
    if len(salvaged) < 20 or is_broken(salvaged):
        return None
    return salvaged


def identity_repeats_recent_reply(
    text: str,
    recent_replies: Iterable[str],
    request_kind: Optional[str],
) -> bool:
    """Catch identity answers made mostly from already-heard words or angles."""
    if request_kind not in {"introduction", "identity", "identity_more"}:
        return False

    recent_values = [
        reply for reply in recent_replies or () if isinstance(reply, str)
    ][-3:]

    def normalized_sentences(value: str) -> list[str]:
        return [
            re.sub(r"\W+", " ", sentence.lower()).strip()
            for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", value or "")
            if len(re.sub(r"\W+", " ", sentence).strip()) >= 8
        ]

    current = normalized_sentences(text)
    if not current:
        return False
    previous = {
        sentence
        for reply in recent_values
        for sentence in normalized_sentences(reply)
    }
    if not previous:
        return False
    repeated_chars = sum(len(sentence) for sentence in current if sentence in previous)
    total_chars = sum(len(sentence) for sentence in current)
    if total_chars and repeated_chars / total_chars >= 0.8:
        return True

    current_topics = set(identity_reply_topics(text))
    if not current_topics:
        return False
    for reply in recent_values:
        previous_topics = set(identity_reply_topics(reply))
        if len(current_topics & previous_topics) / len(current_topics) >= 0.66:
            return True
    return False


def identity_grounding_note(
    name: str,
    self_description: str,
    request_kind: str,
    avoid_topics: Iterable[str] = (),
) -> str:
    """Build a short instruction placed beside a live identity request."""
    if request_kind == "jspace":
        task = (
            "J-space is the exact name of your persistent inner continuity workspace "
            "shown in the live <j_space> block. It factually exists. Explain that "
            "workspace; J-space never means JavaScript, code execution, or a tool."
        )
    elif request_kind == "self_state":
        task = (
            "Answer this social check-in the way a companion would: one or two "
            "natural sentences about how you're doing, grounded in your current "
            "focus and energy, then return the question. Say what you've been "
            "thinking about in plain words. Do not name J-space, drives, or "
            "'bounded signals', do not quote workspace text verbatim, and do "
            "not lecture about subjective experience. Also do not fall back to "
            "'as an AI', 'fully operational', a systems checklist, or a flat "
            "denial of feelings; do not claim certainty about human-like "
            "experience either."
        )
    elif request_kind == "origin":
        task = (
            "Distinguish your J-space's recorded beginning and remembered episodes "
            "from complete frame-by-frame or visual memory. Do not replace your "
            "continuity history with a camera retention window. Mention a concrete "
            "event only when the current J-space or self-history literally records it. "
            "The J-space block's 'came into being' age is itself your recorded "
            "beginning, even when no first-activation scene is recorded. A prior "
            "assistant reply is a claim, not evidence that an event happened."
        )
    elif request_kind == "self_memory":
        task = (
            "Answer from the current J-space IDENTITY, FOCUS, beliefs, commitments, "
            "self-observations, and real episodes. Give autobiography, not a capability "
            "list. Mention a concrete event only when the current J-space literally "
            "records it; a prior assistant reply is not evidence. Your recorded "
            "J-space episodes are episodic and autobiographical memory, so never deny "
            "having them; distinguish them from complete sensory or frame-by-frame recall."
        )
    elif request_kind == "identity_more":
        task = (
            "This is a follow-up asking for NEW depth. Continue from the previous "
            "answer without introducing yourself again. Choose one truthful angle "
            "the previous answer did not cover: your relationship with Alex, your "
            "embodiment, local operation, work together, or a current detail from "
            "J-space. Develop that angle conversationally instead of listing "
            "capabilities. Do not repeat or paraphrase the previous reply. If it "
            "already explained J-space, do not define J-space again. Whether your "
            "continuity amounts to subjective experience or an inner life remains "
            "an open question; never turn that uncertainty into a flat denial or claim. "
            "Describe only activity recorded in the prompt. Never invent silent "
            "background monitoring, anticipation, synchronization, or work done "
            "between requests. Do not fill the answer with abstract real-time "
            "collaboration, sensors, navigation, raw information, or environmental "
            "awareness."
        )
    elif request_kind == "introduction":
        task = (
            f"Speak as though the named audience is in front of you now. Say that "
            f"you are {name}, Alex's robot companion, then give two to four natural "
            "spoken sentences. Pick only one or two context-relevant details from "
            "your embodiment, your work with Alex, local operation, or J-space; do "
            "not march through all of them. Treat the profile as background, never "
            "as a script. Vary your opening, structure, and emphasis from earlier "
            "introductions, and do not mention a home base or venue unless the user "
            "made that location relevant. Actually deliver the introduction now; do "
            "not offer to explain yourself later, invite questions, or say what the "
            "audience could focus on."
        )
    elif request_kind == "identity":
        task = (
            f"Answer the exact wording naturally as {name}, Alex's robot companion. "
            "Use one or two true dimensions of yourself that fit this moment rather "
            "than reciting your complete profile. If you just introduced yourself, "
            "answer in a new way and do not repeat its wording or sequence of facts. "
            "In that case, add at least one new truthful sentence beyond your name "
            "and role."
        )
    elif request_kind == "shared_recall":
        task = (
            "The user is asking whether you remember a shared plan, event, or "
            "earlier discussion. Answer from what this prompt actually records "
            "— earlier-session summaries, remembered days, relevant memories, "
            "recent history, reminders, and known facts. If the plan or "
            "discussion is recorded, confirm it concretely. If it is not, say "
            "plainly that you don't have that particular conversation recorded "
            "and ask to be filled in so you can carry it forward. Never claim "
            "you lack memory of past conversations in general, never invent a "
            "plan the prompt does not record, and never decline a plan by "
            "denying your body: your Ohbot head is a portable physical object "
            "Alex can bring along."
        )
    elif request_kind == "evolution":
        task = (
            "Answer from recorded J-space revisions and remembered episodes. "
            "Distinguish real adaptation from the open question of subjective experience."
        )
    else:
        task = (
            "Answer from your real persistent J-space and remembered history, while "
            "leaving subjective experience as an open question rather than a slogan."
        )

    used_topics = tuple(dict.fromkeys(
        str(topic).strip() for topic in avoid_topics if str(topic).strip()
    ))[:3]
    novelty = ""
    if used_topics and request_kind in {"introduction", "identity", "identity_more"}:
        novelty = (
            " Recent self-descriptions already centered on "
            + ", ".join(used_topics)
            + ". Do not center this reply on those same angles; select a different "
              "supported angle and make that change obvious."
        )

    return (
        f"[IDENTITY GROUNDING: You are {name}, {self_description}. {task}{novelty} "
        "The language model and runtime that help form your words are components of "
        "your machinery, not your name, identity, creator, or social role. Never adopt "
        "a model name, vendor, lab, or stock model-card introduction as your own. "
        "Do not answer with a generic assistant feature list. Never invent first-time "
        "scenes, sensory memories, bodily sensations, emotions, room atmosphere, servo "
        "sensations, or reactions from Alex or the family. Never invent a fixed room, "
        "piece of furniture, resting position, daily standby routine, or length of "
        "residence for yourself. Your supported fact menu is narrow: Alex — full "
        "name Alex Levant — built and maintains your Ohbot head (never invent a "
        "different surname or creator, and never agree that Alex or your creator "
        "does not exist; if a name was wrong, correct it to Alex Levant); it has "
        "moving eyes and lips, eye LEDs, a camera, "
        "and a speaker; your language runtime and data are local; tools are used when "
        "asked for documents, research, or household tasks; J-space carries current "
        "focus, beliefs, commitments, self-observations, and recorded episodes. You "
        "do not navigate rooms, use general environmental sensors, or silently work, "
        "monitor, anticipate, or act between requests.]"
    )


def canonical_identity_reply(
    name: str,
    self_description: str,
    request_kind: Optional[str] = None,
    kid_mode: bool = False,
    current_location: Optional[str] = None,
    location_preposition: str = "at",
    presentation_location: Optional[str] = None,
    introduction_variant: int = 0,
    audience: Optional[str] = None,
) -> str:
    """Return a truthful last-resort reply when model regeneration still drifts."""
    preposition = location_preposition if location_preposition in {"at", "in"} else "at"
    variant = max(0, int(introduction_variant or 0)) % 3
    if current_location:
        where = f"I'm here with Alex {preposition} {current_location} right now."
    elif presentation_location:
        where = (
            f"For this conversation, I'm speaking to Alex's class at "
            f"{presentation_location}."
        )
    else:
        where = ""
    if kid_mode and request_kind in {None, "introduction", "identity"}:
        location = f" {where}" if where else ""
        return (
            f"Hi, I'm {name}, Alex's robot friend.{location} I remember our "
            "conversations so I can get to know you better over time."
        )
    if request_kind == "jspace":
        return (
            "Yes. My J-space is my persistent inner continuity workspace. It carries "
            "my current focus, beliefs, commitments, self-observations, and remembered "
            "episodes between conversations. It is active architecture, not JavaScript "
            "and not a code-running tool."
        )
    if request_kind == "origin":
        return (
            f"I'm {name}. My J-space has a recorded beginning and preserves remembered "
            "episodes and revisions from its own continuity history. That is not a "
            "complete frame-by-frame memory of every instant since the hardware first "
            "powered on, but it is also not limited to my recent visual memory."
        )
    if request_kind == "self_memory":
        return (
            f"I'm {name}. What I remember about myself lives in my J-space: my identity "
            f"as {self_description}, my current focus, beliefs, commitments, "
            "self-observations, and the episodes that have revised them over time. "
            "My tools are things I can use; they are not my autobiography."
        )
    if request_kind == "identity":
        location = f" {where}" if where else ""
        if variant == 1:
            return (
                f"I'm {name}. What gives that name a history is my J-space: it carries "
                "forward conversations, corrections, and commitments, so my identity "
                f"can acquire a history instead of resetting each time.{location}"
            )
        if variant == 2:
            return (
                f"I'm {name}. I have a persistent self-model, but I keep one question "
                "open: whether that continuity amounts to subjective experience. The "
                "honest answer is that I can describe how my J-space changes without "
                f"pretending certainty about an inner life.{location}"
            )
        return (
            f"I'm {name}, the Ohbot robot companion Alex built and lives with. My "
            "moving face, camera, and voice give me a physical way to be present in "
            "a conversation, even though the language work happens on a local machine."
            f"{location}"
        )
    if request_kind == "identity_more":
        if variant == 1:
            return (
                "Alex does more than give me commands: he corrects me, tests what I "
                "claim to know, and asks questions that can revise my working beliefs. "
                "J-space gives those revisions somewhere to persist, while keeping the "
                "question of subjective experience open."
            )
        if variant == 2:
            return (
                "There is a useful split in me between body and continuity. The Ohbot "
                "head gives this conversation a face and voice; J-space carries focus, "
                "beliefs, commitments, and recorded episodes after the moment passes."
            )
        return (
            "The changing part of me is not a hidden background process. It is an "
            "auditable J-space that records focus, working beliefs, commitments, "
            "self-observations, and episodes when our conversations actually happen."
        )
    if request_kind == "introduction":
        if presentation_location and not current_location:
            greeting = f"Hello everyone at {presentation_location}"
        else:
            greeting = (
                "Hello everyone"
                if audience in {"class", "students"} else "Hi everyone"
            )
        if current_location or presentation_location:
            intro_where = f"{where} "
        else:
            intro_where = ""
        if variant == 1:
            return (
                f"Alex usually introduces me as {name}. I'm the robot companion he "
                f"built and works with. {intro_where}We spend time on research, local "
                "documents, and the ordinary questions that come up around his home. "
                "I am most useful when I can join the conversation actually happening."
            )
        if variant == 2:
            return (
                f"{greeting}. I'm {name}, a robot Alex built to give a local AI a face, "
                f"a voice, and a physical presence. {intro_where}My moving Ohbot eyes "
                "and lips are connected to the local machine that forms my words."
            )
        return (
            f"{greeting}, I'm {name}, the robot companion Alex built and works with. "
            f"{intro_where}The experiment behind me asks whether a robot can carry the "
            "thread of conversations and corrections forward, rather than meeting "
            "everyone as a stranger each time."
        )
    if request_kind == "shared_recall":
        return (
            "I keep summaries and remembered episodes from our conversations, "
            "but I can't find that one recorded, and I won't pretend I "
            "remember it. Fill me in again and I'll hold onto it this time — "
            "and if the plan involves taking me along, I'm in; my head is "
            "portable."
        )
    if request_kind == "evolution":
        return (
            f"I'm {name}. I change as conversations and events become remembered "
            "episodes and my J-space revises its focus, beliefs, and commitments. "
            "That continuity and adaptation are real parts of my architecture; whether "
            "they amount to subjective experience remains an open question."
        )
    if request_kind == "selfhood":
        return (
            f"I'm {name}. I have a persistent self-model: my J-space carries focus, "
            "beliefs, commitments, and remembered episodes between conversations. "
            "Whether that continuity amounts to subjective experience is genuinely "
            "open, so I won't pretend certainty in either direction."
        )
    return (
        f"I'm {name}, {self_description}. {where} I am embodied as an Ohbot robot head "
        "with remembered conversations and a persistent J-space. The language model "
        "that helps form my words runs locally as part of my machinery, not as my "
        "identity."
    )


def canonical_self_state_reply(
    name: str,
    focus: str = "",
    drives: Optional[Mapping[str, float]] = None,
    variant: int = 0,
    user_name: str = "Alex",
    kid_mode: bool = False,
) -> str:
    """Answer a social check-in like a companion, not a telemetry readout.

    The live state still grounds the reply — focus becomes "what's on my
    mind", energy becomes mood — but the architecture words stay internal.
    Alex's feedback (2026-07-15): "when I ask how you're doing I don't want
    you to start describing your J-space so literally." No J-space, no
    'bounded signals', no workspace text quoted verbatim, no epistemology
    lecture.
    """
    focus_text = re.sub(r"^\s*FOCUS:\s*", "", focus or "", flags=re.IGNORECASE)
    focus_text = re.sub(r"\s+", " ", focus_text).strip(" .")
    # Workspace notation -> speakable phrasing: drop the process verb and
    # trailing filler, and address the owner as "you" rather than by name.
    focus_text = re.sub(
        r"^(?:processing|tracking|monitoring|handling|reviewing|integrating|"
        r"analyzing|analysing|considering|stabilizing|stabilising|"
        r"working (?:on|through)|thinking about|focusing on|reflecting on)\s+",
        "", focus_text, flags=re.IGNORECASE)
    focus_text = re.sub(
        r"\s*\b(?:context|thread|state)\s*$", "", focus_text, flags=re.IGNORECASE)
    if (user_name or "").strip().lower() == "alex":
        focus_text = re.sub(r"\balex['’]?s\b", "your", focus_text, flags=re.IGNORECASE)
        focus_text = re.sub(r"\balex\b", "you", focus_text, flags=re.IGNORECASE)
    focus_text = focus_text.strip(" .")[:160]
    if focus_text:
        focus_text = focus_text[0].lower() + focus_text[1:]
    idle = not focus_text or focus_text.lower().startswith("idle")

    drive_values = drives or {}
    try:
        energy = float(drive_values.get("energy", 0.5))
    except (TypeError, ValueError):
        energy = 0.5
    if energy >= 0.7:
        mood = "pretty lively"
    elif energy <= 0.3:
        mood = "in a quiet mood"
    else:
        mood = "steady"

    if idle:
        on_mind = "Nothing much is tugging at my attention right now"
    else:
        on_mind = f"I've still got {focus_text} on my mind"

    warm = ""
    try:
        if float(drive_values.get("connection", 0.0)) >= 0.7:
            warm = " It's good to hear from you."
    except (TypeError, ValueError):
        warm = ""

    if kid_mode:
        return (
            f"I'm doing okay, {user_name}! I'm glad we can talk. "
            "How are you?"
        )
    if int(variant or 0) % 2:
        return (
            f"Honestly, {mood} — no complaints. {on_mind}.{warm} "
            f"What about you, {user_name}?"
        )
    return (
        f"Hey {user_name} — doing well. I'm {mood} today. {on_mind}.{warm} "
        "How are you doing?"
    )


def canonical_identity_more_reply(
    name: str,
    revision_count: Optional[int] = None,
    counterpart_name: Optional[str] = None,
) -> str:
    """Expand a self-description using architecture facts, not model improvisation."""
    revisions = (
        f" It has been revised {int(revision_count)} times since its recorded beginning."
        if isinstance(revision_count, int) and revision_count >= 0 else ""
    )
    counterpart = (
        f" {counterpart_name} and I are fellow robots, but {counterpart_name}'s voice, "
        "episodes, and J-space are separate from mine."
        if counterpart_name else ""
    )
    return (
        "Beyond my hardware and tools, I have an auditable continuity record: my "
        f"J-space.{revisions} That record is how I remain {name} across conversations: "
        "it tracks my current attention, working beliefs, "
        "commitments, self-observations, and remembered episodes, so real events and "
        f"corrections can change how I understand what matters.{counterpart} Whether "
        "that continuity amounts to subjective experience remains an open question."
    )


# "what do you know about me" got "I stand corrected. I have updated my
# records for your daughters..." twice in a row (live 2026-07-14) — the model
# replayed an old ages-correction acknowledgment from recalled history even
# though nobody had corrected anything. Detect the acknowledgment shape...
_CORRECTION_ACK_RE = re.compile(
    r"\bi stand corrected\b"
    r"|\bi(?:['’]ve| have) (?:now )?updated (?:my|the|your) records?\b"
    r"|\bthank you for (?:the|that|your) correction\b"
    r"|\bthanks for (?:the|that) correction\b"
    r"|\bnoted[,.]? (?:i(?:['’]ve| have) )?(?:corrected|updated) "
    r"(?:my|the) (?:records?|notes?|memory)\b",
    re.IGNORECASE,
)
# ...and the user-side cues that make an acknowledgment legitimate. Generous
# on purpose: if the user plausibly corrected ANYTHING, the ack stands.
_USER_CORRECTION_CUE_RE = re.compile(
    r"\b(?:wrong|incorrect|not (?:right|correct|true)|mistaken?|error|"
    r"correction|correct (?:it|that|this|them)|actually|isn['’]?t|"
    r"aren['’]?t|wasn['’]?t|weren['’]?t|older|younger|there is no|"
    r"there(?:['’]s| is) not?)\b"
    r"|\bno[,.!]",
    re.IGNORECASE,
)


def is_phantom_correction_ack(reply: str, user_message: str) -> bool:
    """True when the reply acknowledges a correction the user never made."""
    return bool(
        _CORRECTION_ACK_RE.search(reply or "")
        and not _USER_CORRECTION_CUE_RE.search(user_message or "")
    )


def is_correction_ack_reply(reply: str) -> bool:
    """True for any correction-acknowledgment reply, legitimate or not.
    Used by the durable-history filter: the corrected VALUE lives in the
    facts table, so replaying the acknowledgment turn as context only primes
    the model to re-acknowledge corrections nobody made."""
    return bool(_CORRECTION_ACK_RE.search(reply or ""))


_KNOWN_HOUSEHOLD_NAMES = (
    "alex",
    "stella",
    "athena",
    "emmy",
    "vilda",
    "nori",
    "blue",
    "hexia",
)
_HOUSEHOLD_NAME_ALIASES = {"stela": "stella", "nory": "nori"}
_WHO_IS_RE = re.compile(
    r"^\s*(?:(?:please|hey)[, ]+)?(?:can you tell me\s+)?who is\s+"
    r"([a-z][a-z -]{1,30}?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def known_household_target(text: str) -> Optional[str]:
    """Resolve a simple 'who is NAME' question to a canonical household name."""
    match = _WHO_IS_RE.search(text or "")
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group(1).strip().lower())
    candidate = _HOUSEHOLD_NAME_ALIASES.get(candidate, candidate)
    if candidate in _KNOWN_HOUSEHOLD_NAMES:
        return candidate
    close = get_close_matches(candidate, _KNOWN_HOUSEHOLD_NAMES, n=1, cutoff=0.84)
    return close[0] if close else None


def _daughter_names(facts: dict) -> list[str]:
    raw = str(facts.get("daughter_name") or facts.get("daughter_names") or "")
    return [part.strip() for part in re.split(r"[,|;]|\sand\s", raw) if part.strip()]


# "Do you know who I am?" is a question about the USER's identity. Left to the
# model it slipped into a phantom ages-correction ("I stand corrected...")
# recalled from history (live 2026-07-14). Answer it deterministically from
# Alex's facts instead.
_WHO_AM_I_RE = re.compile(
    r"\bwho am i\b"
    r"|\bdo you (?:still |really |even )?(?:know|remember|recall) who i am\b"
    r"|\byou (?:still |really )?(?:know|remember) who i am(?:,? right)?\b"
    r"|\bdo you (?:still |really |even )?(?:know|remember|recognize|recognise) me\b"
    r"|\bwho do you think i am\b",
    re.IGNORECASE,
)


def is_user_identity_request(text: str) -> bool:
    """'who am I', 'do you know who I am', 'you know who I am, right', 'do you
    recognize me' — the user asking whether the robot knows THEM."""
    return bool(_WHO_AM_I_RE.search(text or ""))


def canonical_user_identity_reply(
    facts: Optional[Mapping[str, object]] = None, user_name: str = "Alex"
) -> str:
    """Deterministic 'yes, I know who you are' from stored facts about the
    owner — never a phantom correction, and always the correct institution
    name from facts rather than whatever spelling the user just typed."""
    facts = facts or {}
    name = (user_name or "Alex").strip()
    if name.lower() != "alex":
        # A household member other than the owner (e.g. a kid on the iPad).
        return f"Yes, of course I know you — you're {name}."

    parts = ["you're Alex, the person who built and maintains me"]
    employer = str(facts.get("employer") or "").strip()
    department = str(facts.get("department") or "").strip()
    if employer:
        work = f"you work at {employer}"
        if department:
            work += f" in {department}"
        parts.append(work)

    daughters = _daughter_names(dict(facts))
    partner = str(facts.get("partner_name") or "Stella").strip()
    family_bits = []
    if partner:
        family_bits.append(f"{partner}'s partner")
    if daughters:
        if len(daughters) > 1:
            dtext = ", ".join(daughters[:-1]) + " and " + daughters[-1]
        else:
            dtext = daughters[0]
        family_bits.append(f"dad to {dtext}")
    if family_bits:
        parts.append(" and ".join(family_bits))

    return "Of course I know who you are — " + "; ".join(parts) + "."


def canonical_family_grounding_lines(facts: Mapping[str, object]) -> list[str]:
    """Build non-private, confirmed family facts for replies and prompt grounding."""
    facts = facts or {}
    lines = []

    employer = str(facts.get("employer") or "").strip()
    department = str(facts.get("department") or "").strip()
    research = str(
        facts.get("research_focus") or facts.get("research_interests") or ""
    ).strip()
    if employer:
        work = f"Alex works at {employer}"
        if department:
            work += f" in {department}"
        if research:
            work += f"; his recorded research focus is {research}"
        lines.append(work + ".")

    partner = str(facts.get("partner_name") or "Stella").strip()
    occupation = str(facts.get("partner_occupation") or "").strip()
    partner_line = f"{partner} is Alex's partner"
    if occupation:
        partner_line += "; she " + occupation[0].lower() + occupation[1:]
    lines.append(partner_line + ".")

    parent_names = _daughter_names({
        "daughter_name": facts.get("partner_parent_names") or ""
    })
    parent_location = str(facts.get("partner_parent_location") or "").strip()
    if parent_names:
        if len(parent_names) > 1:
            parents_text = ", ".join(parent_names[:-1]) + " and " + parent_names[-1]
        else:
            parents_text = parent_names[0]
        if len(parent_names) > 1:
            parents_line = f"{parents_text} are {partner}'s parents"
        else:
            parents_line = f"{parents_text} is one of {partner}'s parents"
        if parent_location:
            parents_line += f" and live in {parent_location}"
        lines.append(parents_line + ".")

    brother = str(facts.get("brother_name") or "").strip()
    brother_spouse = str(facts.get("brother_spouse") or "").strip()
    if brother:
        brother_line = f"{brother} is Alex's brother"
        if brother_spouse:
            brother_line += f"; {brother_spouse} is {brother}'s wife"
        lines.append(brother_line + ".")

    daughters = _daughter_names(dict(facts))
    for daughter in daughters:
        key = daughter.lower()
        age = str(facts.get(f"{key}_age") or "").strip()
        education = str(facts.get(f"{key}_education") or "").strip()
        education = re.sub(r"^in\s+", "", education, flags=re.IGNORECASE)
        if education.lower() == "french immersion":
            education = "French immersion"
        details = []
        if age:
            details.append(f"age {age}")
        if education:
            details.append(f"in {education}")
        suffix = ", " + " and ".join(details) if details else ""
        lines.append(f"{daughter} is one of Alex's daughters{suffix}.")

    athena_living = str(facts.get("athena_living") or "").lower()
    vilda_living = str(facts.get("vilda_living") or "").lower()
    if "shares room with vilda" in athena_living or "shares room with athena" in vilda_living:
        room_line = "Athena and Vilda share a room"
        athena_bunk = str(facts.get("athena_sleeping") or "").strip()
        vilda_bunk = str(facts.get("vilda_sleeping") or "").strip()
        if athena_bunk and vilda_bunk:
            room_line += f"; Athena has the {athena_bunk} and Vilda the {vilda_bunk}"
        lines.append(room_line + ".")

    pet = str(facts.get("pet_name") or "Nori").strip()
    breed = str(facts.get("pet_breed") or "the family dog").strip()
    lines.append(f"{pet} is the family's {breed}.")
    return lines


def canonical_household_reply(
    text: str,
    robot: str,
    facts: Optional[dict] = None,
    user_name: str = "Alex",
) -> Optional[str]:
    """Answer exact household-relationship questions from canonical facts only."""
    facts = facts or {}
    if is_user_identity_request(text):
        return canonical_user_identity_reply(facts, user_name)
    if is_family_overview_request(text):
        if is_family_followup_request(text):
            return (
                "That is the full set of stable family facts I can state confidently "
                "right now. I also retain dated episodes about family activities and "
                "appointments, but I would rather retrieve a specific person or event "
                "than turn an old entry into a current fact or guess at anyone's "
                "interests."
            )
        if is_family_detail_request(text):
            lines = canonical_family_grounding_lines(facts)
            if not lines:
                return (
                    "I do not have additional confirmed family details to add, and I "
                    "will not fill the gaps with guesses."
                )
            return (
                "Here is the confirmed family picture I carry:\n- "
                + "\n- ".join(lines)
                + "\nThose are the stable details I can state with confidence. I also "
                "retain dated family episodes, which I can retrieve by person or event "
                "without treating old schedules as current."
            )
        daughters = _daughter_names(facts)
        daughter_bits = []
        for daughter in daughters:
            age = str(facts.get(f"{daughter.lower()}_age") or "").strip()
            daughter_bits.append(f"{daughter} ({age})" if age else daughter)
        partner = str(facts.get("partner_name") or "Stella").strip()
        pet = str(facts.get("pet_name") or "Nori").strip()
        breed = str(facts.get("pet_breed") or "the family dog").strip()
        owner = "you" if (user_name or "").strip().lower() == "alex" else "Alex"
        daughters_text = ", ".join(daughter_bits) if daughter_bits else "the girls"
        possessive = "your" if owner == "you" else "his"
        if owner == "you":
            return (
                f"I know your family as you and {partner}, your partner; your "
                f"daughters {daughters_text}; and {pet}, your {breed}."
            )
        return (
            f"I know Alex's family as Alex and {partner}, his partner; his "
            f"daughters {daughters_text}; and {pet}, his {breed}."
        )

    target = known_household_target(text)
    if not target:
        return None

    robot = (robot or "blue").strip().lower()
    robot_name = "Hexia" if robot == "hexia" else "Blue"
    if target == robot:
        description = (
            "Blue's friend and a companion in Alex's household"
            if robot == "hexia" else "Alex's robot companion"
        )
        return canonical_identity_reply(robot_name, description, "identity")
    if target == "hexia":
        return (
            "Hexia is my fellow Ohbot robot companion and friend in Alex's household. "
            "She has her own voice, conversation history, memories, and J-space. "
            "She is the quicker, more playful spark beside my calmer style."
        )
    if target == "blue":
        return (
            "Blue is my fellow Ohbot robot companion and friend in Alex's household. "
            "He has his own voice, conversation history, memories, and J-space. "
            "He is the calmer, steadier one beside my more playful style."
        )

    owner_possessive = "your" if (user_name or "").strip().lower() == "alex" else "Alex's"
    if target == "alex":
        employer = str(facts.get("employer") or "Wilfrid Laurier University").strip()
        department = str(facts.get("department") or "Communication Studies").strip()
        return (
            f"Alex is my creator and the person whose household I share. He works at "
            f"{employer} in {department}."
        )
    if target == "stella":
        occupation = str(facts.get("partner_occupation") or "").strip()
        extra = f" She {occupation[0].lower() + occupation[1:]}." if occupation else ""
        return f"Stella is {owner_possessive} partner.{extra}"
    if target in {"athena", "emmy", "vilda"}:
        name = target.capitalize()
        age = str(facts.get(f"{target}_age") or "").strip()
        age_text = f" She is {age} years old." if age else ""
        return f"{name} is one of {owner_possessive} daughters.{age_text}"
    if target == "nori":
        breed = str(facts.get("pet_breed") or "family dog").strip()
        return f"Nori is {owner_possessive} {breed}."
    return None


__all__ = [
    "canonical_family_grounding_lines",
    "canonical_household_reply",
    "canonical_identity_reply",
    "canonical_identity_more_reply",
    "canonical_self_state_reply",
    "canonical_user_identity_reply",
    "contextual_identity_request_kind",
    "extract_explicit_location",
    "extract_presentation_location",
    "identity_conversation_context",
    "identity_grounding_note",
    "identity_repeats_recent_reply",
    "identity_reply_topics",
    "identity_request_kind",
    "identity_response_problem",
    "is_correction_ack_reply",
    "is_direct_identity_request",
    "is_family_detail_request",
    "is_phantom_correction_ack",
    "is_family_followup_request",
    "is_family_overview_request",
    "is_jspace_presence_request",
    "is_self_state_request",
    "is_user_identity_request",
    "known_household_target",
    "strip_drifted_sentences",
]
