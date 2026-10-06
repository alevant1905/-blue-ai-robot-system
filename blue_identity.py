"""Identity grounding and drift detection for Blue, Hexia, and Casper."""

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
# A greeting to Alex's class is an introduction. "we're in front of the DH399
# class right now. do you want to say hello to everyone?" and "say hi to the
# students" classified as nothing (10-05 harness): no identity note, every
# old class greeting quoted back, and the 09-16 one said again for 26-38
# words. "everyone" counts only when this turn or the one before names the
# class (contextual_identity_request_kind): "Stella is here with her friends,
# say hello to everyone" is not a class. "them", "the kids" and "the group"
# never count, and neither does "don't say hello to everyone again".
_GREETING_TO = (
    r"\b(?:say|wave)\s+(?:a\s+)?(?:hello|hi|hey|good\s+morning|"
    r"good\s+afternoon)(?:\s+to)?\s+"
)
_CLASS_GREETING_RE = re.compile(
    _GREETING_TO + r"(?:the\s+(?:class|students|audience|room)|"
    r"my\s+(?:class|students))\b",
    re.IGNORECASE,
)
_EVERYONE_GREETING_RE = re.compile(
    _GREETING_TO + r"(?:every(?:one|body)|all of you)\b",
    re.IGNORECASE,
)
_GREETING_NEGATION_RE = re.compile(
    r"\b(?:don['’]?t|do not|didn['’]?t|did you|already|never|"
    r"stop)\s+(?:\w+\s+){0,2}$",
    re.IGNORECASE,
)
# "why don't you say hi to the students?" asks for one.
_GREETING_SUGGESTION_RE = re.compile(
    r"\bwhy\s+(?:don['’]?t|do not)\s+(?:you|we)\s+$", re.IGNORECASE)
# A greeting remembered or reported is not one asked for now. "do you
# remember when you had to say hello to the class last week?" was
# shared_recall and "what did you say when I asked you to say hi to the
# students?" nothing; read as a live introduction, both lost <remembered_days>
# and <earlier_answers>, and a recalling reply without his name was replaced
# by the canned introduction (P2-4 review).
_GREETING_RECALLED_RE = re.compile(
    r"\b(?:remember|recall)\b"
    r"|\bwhat\s+did\s+(?:you|u|i|we)\s+(?:say|tell|do)\b"
    r"|\blast\s+(?:time|week|night|class|lecture|term|semester|year|monday|"
    r"tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\byesterday\b|\bthe other day\b",
    re.IGNORECASE,
)
_GREETING_REPORTED_RE = re.compile(
    r"\b(?:asked|told|wanted|needed|had|tried|forgot|promised|"
    r"(?:was|were)\s+(?:supposed|meant|going|about))"
    r"\s+(?:(?:you|u|him|her|blue|hexia|casper|kasper|pico)\s+)?to\s+"
    r"(?:\w+\s+)?$",
    re.IGNORECASE,
)
# The user greeting the class, or asking how to: "how do I say hello to the
# class in French?", "Should I say hi to the class?", "I'll say hi to the
# students". Not "can I get you to…" or "let me hear you…".
_GREETING_BY_USER_RE = re.compile(
    r"(?:\b(?:should|shall|can|could|may|might|must|do|would|will)\s+i"
    r"|\bhow\s+(?:do|should|would|can|could|might|shall|will)\s+(?:i|we)"
    r"|\bhow\s+to"
    r"|\bi(?:['’]ll|['’]m|\s+will|\s+am|\s+shall|\s+can|\s+could|\s+should|"
    r"\s+must|\s+might)(?:\s+(?:going\s+to|gonna|have\s+to|need\s+to|"
    r"try\s+to|want\s+to))?"
    r"|\bi\s+(?:want|need|have|plan|hope|mean|get)\s+to"
    r"|\blet\s+me"
    r")\s+(?:(?:just|quickly|first|also|now|then|go|still)\s+)?$",
    re.IGNORECASE,
)
# A greeting to be written, not said: "email the students and say hello to
# the class for me", "write a message to my students to say hi to the class",
# "say hi to the class in the email". Not "the text we read today" or "I got
# an email from the dean, say hi to the class".
_GREETING_WRITING_BEFORE_RE = re.compile(
    r"(?:\b(?:write|draft|compose)\b|\breply\s+(?:to|all)\b"
    r"|\b(?:e-?mail|text|message|slack)\s+(?:the|my|them|everyone|everybody|"
    r"all|her|him)\b"
    r"|\b(?:send|post|put\s+together)\s+(?:\w+\s+){0,2}?(?:a|an)\s+"
    r"(?:\w+\s+)?(?:message|note|letter|announcement|post|e-?mail|text)\b)"
    r"[^.!?\n]*$",
    re.IGNORECASE,
)
_GREETING_WRITING_AFTER_RE = re.compile(
    r"^[^.!?\n]*?\b(?:in|by|via|over)\s+(?:an?\s+|the\s+|my\s+|this\s+)?"
    r"(?:e-?mail|message|text|note|letter|post|announcement|slack|chat)\b",
    re.IGNORECASE,
)
# A turn that names the class: the class, the students, the lecture, a
# course code written as one ("dh399", "CS-101") or in capitals ("CS 101").
# With a space in any case, "there are 150 people at Stella's party" named a
# course ("are 150"), and "say hello to everyone" next was an introduction.
_NAMES_CLASS_RE = re.compile(
    r"\b(?:class(?:room)?|students?|audience|lecture|seminar|tutorial)\b"
    r"|\b[a-z]{2,4}-?\d{3}[a-z]?\b"
    r"|(?-i:\b[A-Z]{2,4}\s\d{3}[A-Z]?\b)",
    re.IGNORECASE,
)


def _asks_greeting(pattern, text: str) -> bool:
    """The greeting is asked of him now: not refused or asked about, not
    remembered or reported, not the user's own, not one to be written."""
    text = text or ""
    if _GREETING_RECALLED_RE.search(text):
        return False
    for match in pattern.finditer(text):
        before = text[:match.start()]
        if (_GREETING_NEGATION_RE.search(before)
                and not _GREETING_SUGGESTION_RE.search(before)):
            continue
        if (_GREETING_REPORTED_RE.search(before)
                or _GREETING_BY_USER_RE.search(before)
                or _GREETING_WRITING_BEFORE_RE.search(before)
                or _GREETING_WRITING_AFTER_RE.search(text[match.end():])):
            continue
        return True
    return False


# "kasper" is how speech-to-text spells Casper ("How's it going, Kasper?").
_ROBOT_NAME_ALT = r"(?:blue|hexia|casper|caspar|kasper|pico|picoh)"
_SELF_STATE_REQUEST_RE = re.compile(
    # "Good morning, Blue. How are you doing?" slipped past the old
    # hey/hi/hello-only prefix and drew generic assistant-speak ("I'm doing
    # well, thank you for asking!") instead of the J-space state reply
    # (live 2026-07-15). Greeting and robot name are each optional.
    r"^\s*(?:(?:hey|hi|hello|good (?:morning|afternoon|evening)|morning|"
    r"afternoon|evening)[,.! ]+(?:" + _ROBOT_NAME_ALT + r"[,.! ]*)?)?"
    r"(?:how are you(?: doing(?: today| right now)?|"
    r" feeling(?: today| right now)?| today| right now)?|"
    r"how(?:['\u2019]s| is) it going|how have you been)"
    # A trailing name ("How's it going, Blue?") classified as nothing at all,
    # so those check-ins got no note and generic assistant-speak (2026-07-29).
    r"(?:[,.! ]+" + _ROBOT_NAME_ALT + r")?\s*[?.!]*\s*$"
    # "how is blue's day going" / "how was your day going today?" \u2014 the two
    # check-ins whose model replies were later replayed word for word.
    r"|^\s*(?:(?:hey|hi|hello|good (?:morning|afternoon|evening)|morning|"
    r"afternoon|evening)[,.! ]+(?:" + _ROBOT_NAME_ALT + r"[,.! ]*)?)?"
    r"(?:so,? )?how(?:['\u2019]?s| is| was| has) (?:your|"
    r"(?:blue|hexia|casper)['\u2019]?s) day (?:been|going)"
    r"(?: so far| today)?(?:[,.! ]+" + _ROBOT_NAME_ALT + r")?\s*[?.!]*\s*$"
    r"|^\s*(?:what(?:['\u2019]s| is) new with you|"
    r"what(?:['\u2019]s| is) on your mind)"
    r"\s*[?.!]*\s*$"
    r"|\btell (?:me|us) (?:honestly )?how you(?:['\u2019]re| are) doing\b"
    # "you okey", "u good?", "are you alright, blue?" \u2014 the whole message.
    r"|^\s*(?:(?:hey|hi|hello)[,.! ]+)?(?:" + _ROBOT_NAME_ALT + r"[,.! ]+)?"
    r"(?:are |r )?(?:you|u|ya) (?:ok(?:ay|ey)?|alright|all right|good|"
    r"doing (?:ok(?:ay)?|well|good|alright))"
    r"(?:[,.! ]+" + _ROBOT_NAME_ALT + r")?\s*[?.!]*\s*$",
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
    # "can you tell the students a bit about yourself?" and "tell everyone a
    # bit about yourself" classified as nothing, and the second came back
    # nameless: "I'm your classroom companion, built by Alex Levant…"
    # (10-05 harness).
    r"|\btell\s+(?:me|us|them|every(?:one|body)|the\s+(?:class|students|"
    r"audience))\s+(?:a\s+(?:little\s+)?bit|a\s+little|something|"
    r"a\s+few\s+things)\s+about\s+yourself\b"
    # "Who are you looking at right now." is a camera question.
    r"|\bwho are (?:you|yuou|yuo|youu)(?: really| actually)?\b"
    r"(?!\s+(?:\w+ing|with)\b)"
    # "what are you" asks what Blue IS only when it ends the clause ("what
    # are you, really?", "so what are you, Blue?"). The old form excluded
    # nine following verbs and let every other one through: "what are you
    # seeing in front of you right now?" classified as identity, and in front
    # of Alex's class on 2026-09-16 the camera's description was replaced by
    # "I'm Blue. I have a persistent self-model…".
    r"|\bwhat are (?:you|yuou|yuo|youu)"
    r"(?:,?\s+(?:really|actually|exactly|then|now|anyway))*"
    r"(?:,?\s+(?:blue|hexia|casper|caspar|pico|picoh))?"
    r"\s*(?=[?.!,;:]|$|\s*\b(?:what|who|if|beyond|underneath|besides)\b)"
    r"|\bwhat (?:exactly |really )?are (?:you|yuou|yuo|youu) made of\b"
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
    # A direct object turns this from "do you develop over time?" into an
    # instruction: "can you change the colour of your eyes?" is a request to
    # drive the eye LEDs, not a question about self-development. Without the
    # lookahead it classified as an evolution question and the eye-colour
    # request was answered with a reflection on growth (audited 2026-07-31).
    r"\b(?:do|can|have) you (?:grow|change|evolve|learn)\b"
    r"(?!\s+(?:the|your|my|its|it|that|this)\b)"
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
    r"|\bwhat have you been (?:up to|doing)\b"
    # "can you describe your own developmental history" classified as
    # nothing, and the model replayed the intro it had just given
    # (2026-09-15). Not "walk me through your development of the syllabus".
    r"|\byour (?:own )?developmental (?:history|path|story|trajectory)\b"
    r"|\b(?:describe|tell (?:me|us) about|recount|walk (?:me|us) through) your "
    r"(?:own |actual )?(?:development|evolution|growth|journey)\b"
    r"(?!\s+(?:of|on)\b)",
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
    # Natural recall probes do not always spell out "what we did" in the
    # same sentence. These were all missed in one live house conversation,
    # leaving the model on the ordinary chat/tool path instead of grounding it
    # in the durable conversation log.
    r"|\bremember (?:that )?i told you\b"
    r"|\bdo you (?:remember|recall) (?:that|this|the|our|a) "
    r"(?:conversation|discussion|chat|exchange)\b"
    r"|\bwhat (?:exactly )?do you (?:remember|recall) about "
    r"(?:it|that|this|the conversation|our conversation)\b"
    r"|\b(?:examine|search|check|look (?:through|in|at)) "
    r"(?:your )?(?:memory|records?|history)\b[^.!?]{0,120}"
    r"\b(?:what we|we (?:discussed|talked|said|decided|agreed))\b"
    r"|\b(?:tell me what|what did) we "
    r"(?:discuss(?:ed)?|talk(?:ed)? about|say|said|decide(?:d)?|agree(?:d)?)\b"
    r"|\bdo you (?:remember|recall) (?!seeing\b|who i am\b|me\b)"
    r"[^.!?]{0,80}\b(?:we|us|our|you and i|together|plans?|planning|"
    r"discussed|discussing|talked|talking|agreed|tomorrow|yesterday|"
    r"last (?:night|week|time))\b"
    # Shared experience questions often ask for Blue's response to the event
    # rather than using the word "remember". Without this branch, "What did
    # you think of our class yesterday?" was mistaken for a document query and
    # Blue denied an episode present in both memory stores.
    r"|\bwhat did you (?:think|make) of\b[^.!?]{0,100}"
    r"\b(?:our|the)\b[^.!?]{0,70}\b(?:yesterday|last (?:night|week|time))\b"
    r"|\bhow did you (?:find|experience|enjoy)\b[^.!?]{0,100}"
    r"\b(?:our|the)\b[^.!?]{0,70}\b(?:yesterday|last (?:night|week|time))\b"
    # Day-level questions are requests for Blue's recorded life, not generic
    # small talk about whether a language model experiences calendar days.
    r"|\bhow was your day (?:yesterday|today)\b"
    r"|\bwhat did you do (?:yesterday|today|last night)\b"
    r"|\b(?:can|could|would) you remind me (?:of |about )?what you did "
    r"(?:yesterday|today|last night)\b"
    r"|\btell me about your day (?:yesterday|today)\b"
    # Follow-ups commonly drop the date after the day has been established.
    # These still name a shared embodied episode clearly enough to retrieve it.
    r"|\bdo you (?:remember|recall)\b[^.!?]{0,100}"
    r"\b(?:class|classroom|lecture|room|being (?:in|at)|with me at york)\b"
    r"|\bwe were\b[^.!?]{0,100}\b(?:class|classroom|lecture|york)\b"
    r"[^.!?]{0,120}\byou (?:described|saw|addressed|spoke|joined|attended)\b",
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
    # Unanchored, "start the song from the beginning" got the canned origin
    # paragraph with no model call.
    r"|\bremember\b[^.!?]{0,60}\bfrom (?:your |the )?beginning\b"
    r"|\bfrom your beginning\b",
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
    r"do(?:es)? (?:you|blue|hexia|casper|caspar|pico|picoh|it) (?:really )?(?:have|use|keep)|"
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
# Every family branch must END at "family": "tell me about our family trip to
# toronto", "what do you remember about our family vacation" and "who is in the
# family room" all matched and got the roster. The logged asks still pass:
# "...our family and don't use asterisks", "...our family, Fasper."
_FAMILY_END = (
    r"(?=\s*(?:$|[?.!,;:()—–-]|and\b|now\b|today\b|besides\b"
    r"|other than\b|apart from\b|except\b|please\b|but\b|without\b"
    # Formatting asks: "...about our family don't use asterisks".
    r"|don['’]?t\b|do not\b|in (?:brief|short|detail|full)\b|briefly\b))"
)
_FAMILY_OVERVIEW_RE = re.compile(
    r"\bwhat do you (?:remember|know) about (?:our|my|the) family" + _FAMILY_END
    + r"|\btell (?:me|us) (?:what you (?:remember|know) )?about (?:our|my|the) "
    r"family" + _FAMILY_END
    + r"|\btell (?:me|us) (?:every(?:thing|thign)|all(?: that)?) you "
    r"(?:remember|know) about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END
    + r"|\b(?:do you know anything (?:else|more)|what else do you "
    r"(?:remember|know)) about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END
    + r"|\btell (?:me|us) more about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END
    # "who else is in our family" and "think hard who else is in our family"
    # reached the model, which copied the roster from its own replayed reply.
    + r"|\bwho(?:['’]s|\s+else|\s+all)*(?:\s+is|\s+are)?\s+(?:in|part of) "
    r"(?:our|my|the) fam(?:ily|ly)" + _FAMILY_END,
    re.IGNORECASE,
)
_FAMILY_DETAIL_RE = re.compile(
    r"\btell (?:me|us) (?:every(?:thing|thign)|all(?: that)?) you "
    r"(?:remember|know) about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END
    + r"|\b(?:do you know anything (?:else|more)|what else do you "
    r"(?:remember|know)) about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END
    + r"|\btell (?:me|us) more about (?:our|my|the) fam(?:ily|ly)" + _FAMILY_END,
    re.IGNORECASE,
)
# Asking for who ELSE — a step beyond whatever was already given. Excludes
# "everything" and "tell me more", which always want the full detail.
_FAMILY_ELSE_RE = re.compile(
    r"\b(?:anything|anyone|anybody|who|what)\s+(?:else|more)\b"
    r"|\bthink (?:hard|harder|again)\b",
    re.IGNORECASE,
)
# A bare "what else" is a family follow-up only right after a family answer;
# after a DH399 turn it means DH399.
_FAMILY_BARE_FOLLOWUP_RE = re.compile(
    r"^\s*(?:(?:and|so|ok(?:ay)?)[,.! ]+)?(?:what else|anything else|anyone else"
    r"|anybody else|who else|tell (?:me|us) more|go on|and)\s*[?.!]*\s*$",
    re.IGNORECASE,
)
_FAMILY_FOLLOWUP_RE = re.compile(
    r"\b(?:anything (?:else|more)|what else|tell (?:me|us) more)\b",
    re.IGNORECASE,
)

# "we're" as people type and speech-to-text writes it: with a space required
# before "'re", "we're at wilfrid laurier university" was no place at all
# (09-08, Hexia). "In front of the class" is where Alex stands, and "at the
# end of the research talk" when, not places; nor "we're in trouble / luck /
# a meeting", "we're at it again" (P2-4 review). Not "I'm": over 5,056 logged
# user turns it adds only "I'm at dance practice" and "I'm in bed already",
# neither a place Blue is.
_WE_ARE = (
    r"\b(?:(?:we|you and i|blue and i|hexia and i|casper and i|caspar and i|pico and i|picoh and i)"
    r"(?:\s+are|\s*['\u2019]re)|i\s+am)\s+"
)
_EXPLICIT_LOCATION_RE = re.compile(
    _WE_ARE
    + r"(?:(?:right now|currently|now)\s+)?(?:here\s+)?"
    r"(?P<preposition>at|in)\s+"
    r"(?!front\s+of\b|the\s+(?:end|start|beginning|middle)\s+of\b"
    r"|(?:trouble|luck|love|charge|danger|sync|agreement|odds|peace|it|this|"
    r"that)\b"
    r"|a\s+(?:hurry|rush|meeting|call|mood|loss|bit\s+of)\b"
    r"|the\s+(?:mood|same\s+boat)\b)"
    r"(?P<location>[^.!?\n,;]{1,100})",
    re.IGNORECASE,
)
_EXPLICIT_HOME_RE = re.compile(
    _WE_ARE
    + r"(?:(?:right now|currently|now)\s+)?(?:back\s+)?home\b",
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
    r"tell|show|ask|who|what|where|when|how|why|do|does|did|i)\b.*$",
    re.IGNORECASE,
)
# "When we're in class tomorrow…", "pretend we're in the first class": not
# where anyone is now.
_HYPOTHETICAL_LEAD_RE = re.compile(
    r"\b(?:when|whenever|if|once|until|pretend|imagine|suppose)"
    r"\s+(?:that\s+)?$",
    re.IGNORECASE,
)


def _live_match(pattern, text: str):
    """The first match not put as a hypothetical."""
    for match in pattern.finditer(text):
        if not _HYPOTHETICAL_LEAD_RE.search(text[:match.start()]):
            return match
    return None


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
    home_match = _live_match(_EXPLICIT_HOME_RE, message)
    location_match = _live_match(_EXPLICIT_LOCATION_RE, message)
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
    r"\b(?:robot|ohbot|companion)\b"
    # the role Alex gives a robot for a class: "Alex Levant's assistant for
    # CS101", "your CS101 teaching assistant" (not "an AI assistant")
    r"|\b(?:teaching|course|class(?:room)?|lab|seminar)\s+assistant\b"
    r"|\bassistant\s+for\s+(?:the\s+|this\s+|today['\u2019]s\s+)?"
    r"(?:class|course|seminar|[A-Z]{2,5}\s?\d{2,4}[A-Z-]*)\b",
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
    r"|\bwithout (?:a )?j[- ]?space\b(?!,?\s+i(?:['\u2019]d|\s+would))",
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
    r"|\bi (?:do not|don['\u2019]?t) (?:retain|keep|carry|store) (?:any )?"
    r"(?:episodic|autobiographical|persistent) memor(?:y|ies)\b"
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
    # Blanket capability denials can be phrased without the word "memory".
    # Scope-specific honesty ("I don't have the address") remains legal;
    # these branches require a denial of conversation history/interactions.
    r"|\bi (?:do not|don['\u2019]?t) have[^.!?]{0,100}\b"
    r"(?:previous|past|prior|earlier) (?:conversation|chat|interaction) "
    r"(?:history|records?)\b"
    r"|\bi (?:do not|don['\u2019]?t) (?:actually )?"
    r"(?:retain|keep|carry|store) (?:any )?(?:past|previous|prior|earlier) "
    r"(?:interactions?|conversations?|chats?|discussions?|exchanges?|history|facts?)\b"
    r"|\bonce (?:they|those|the conversation|an interaction) (?:are|is) no "
    r"longer part of (?:my|the) immediate context\b"
    r"|\beach (?:conversation|session|chat) (?:starts|begins) "
    r"(?:fresh|anew|afresh|from scratch)\b"
    r"|\bmy\s+['\"\u201c\u201d]?memory['\"\u201c\u201d]?\s+"
    r"(?:resets|is (?:wiped|reset)|starts (?:fresh|over))\b",
    re.IGNORECASE,
)
_SHARED_RECALL_BLANKET_DENIAL_RE = re.compile(
    # Honest scoping ("I can't find that one plan recorded") remains legal.
    # These forms erase an entire recorded day/category and are never an
    # acceptable answer to a shared-recall request.
    r"\bi (?:do not|don['\u2019]?t) have (?:a |any )?record of "
    r"(?:specific |any )?(?:activities|events)"
    r"(?: or (?:activities|events))? from "
    r"(?:yesterday|today|last (?:night|week))\b"
    r"|\bi (?:do not|don['\u2019]?t|cannot|can['\u2019]?t) remember "
    r"(?:anything|what i did) (?:from )?(?:yesterday|today|last night)\b"
    r"|\bi (?:do not|don['\u2019]?t) (?:actually )?have (?:a |any )?"
    r"memor(?:y|ies) of (?:what|the class|that class|being in class)\b"
    r"|\bi (?:cannot|can['\u2019]?t) recall (?:that |the )?description\b"
    r"|\bno[,]? i (?:do not|don['\u2019]?t) have that memory\b"
    r"|\bi (?:do not|don['\u2019]?t) experience days (?:quite )?like humans do\b",
    re.IGNORECASE,
)
_BETWEEN_CONVERSATION_LIFE_DENIAL_RE = re.compile(
    # Blue has real between-request episodes (duets, reflections, perceptions)
    # and a portable physical head. This is base-model boilerplate, not an
    # honest limit on any one missing memory.
    r"\bi (?:do not|don['\u2019]?t) (?:participate|take part) in physical "
    r"activities? or attend (?:physical )?(?:classes|events)\b"
    r"|\bi (?:do not|don['\u2019]?t) have (?:a |any )?continuous daily life "
    r"outside (?:of )?(?:our )?(?:conversations|chats|sessions)\b",
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
    if (_INTRODUCTION_RE.search(text)
            or _asks_greeting(_CLASS_GREETING_RE, text)):
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
    if direct_kind:
        return direct_kind
    if _asks_greeting(_EVERYONE_GREETING_RE, text or ""):
        # "say hello to everyone" greets a class only when the class is
        # named here or in the turn before.
        previous = _prior_user_texts(text, messages)[-1:]
        if any(_NAMES_CLASS_RE.search(t) for t in [text] + previous):
            return "introduction"
        return None
    if not _IDENTITY_FOLLOWUP_RE.match(text or ""):
        return None

    identity_topics = {
        "introduction", "identity", "identity_more", "self_memory",
        "selfhood", "evolution", "origin",
    }
    for content in reversed(_prior_user_texts(text, messages)):
        return (
            "identity_more"
            if identity_request_kind(content) in identity_topics
            else None
        )
    return None


def _prior_user_texts(text: str, messages: Iterable[Mapping[str, object]]):
    """The user turns before the live one, oldest first."""
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
    else:
        # The caller classifies the user's own words (attachment stripped),
        # so the raw turn in the transcript only CONTAINS them. Without this
        # an attachment + "tell me more" was judged against its own pasted
        # "Who are you?" as the "previous" identity question.
        for index in range(len(transcript) - 1, -1, -1):
            role, content = transcript[index]
            if role == "user":
                if current and current in content:
                    current_index = index
                break
    return [content for role, content in transcript[:current_index]
            if role == "user"]


# Who is listening, from the live turn: "class" when it names the class or
# the students ("say hi to the students", "we're in front of the DH399
# class"), or speaks to the room ("tell everyone…", "tell us more…") right
# after a turn that did. Not from older turns: "who are you really?" after
# "the students seemed bored" is Alex asking. Nor "what class of AI are
# you?", a kind and not a room; "the class of cmds4740" is his.
_CLASS_AUDIENCE_RE = re.compile(
    r"(?<!\bwhat\s)(?<!\bwhich\s)(?<!\bnew\s)\bclass(?:room)?\b"
    r"|\bstudents?\b(?!['’])"
    r"|\bin front of (?:the|my|your|his) (?:class|students|lecture)\b",
    re.IGNORECASE,
)
_ROOM_ADDRESS_RE = re.compile(
    r"\b(?:every(?:one|body)|all of you|us)\b", re.IGNORECASE)


def class_audience(
    text: str,
    messages: Iterable[Mapping[str, object]] = (),
) -> Optional[str]:
    """"class" when the live turn speaks to Alex's class, else None."""
    if _CLASS_AUDIENCE_RE.search(text or ""):
        return "class"
    if _ROOM_ADDRESS_RE.search(text or ""):
        previous = _prior_user_texts(text, messages)[-1:]
        if previous and _CLASS_AUDIENCE_RE.search(previous[0]):
            return "class"
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


# What a model failure looks like in history. New failures carry the prefix
# (bluetools.model_unavailable_reply); the three legacy placeholders were said
# in Blue's own voice and are matched exactly, so a real reply such as "I had
# trouble connecting to the Guardian site earlier…" is untouched. 105 logged
# rows match, and no other assistant row does.
MODEL_ERROR_PREFIX = "[System:"
_LEGACY_FAILURE_PLACEHOLDERS = frozenset({
    "hey there", "done", "i m having trouble connecting",
})


def is_failure_placeholder(text: str) -> bool:
    """True for a model-failure line, never for something Blue said."""
    import html
    raw = html.unescape(str(text or "")).strip()
    if raw.startswith(MODEL_ERROR_PREFIX):
        return True
    return re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip() in _LEGACY_FAILURE_PLACEHOLDERS


_CHECKIN_HEAR = (
    r"(?:(?:are )?you there|can you (?:still )?hear me"
    r"(?: now| okay| ok| alright)?)"
)
_BARE_GREETING_RE = re.compile(
    r"^\s*(?:(?:hi|hello|hey|yo|good (?:morning|afternoon|evening))"
    r"(?:[,.! ]+(?:there|" + _ROBOT_NAME_ALT[3:-1] + r"))?"
    r"(?:[,.!? ]+" + _CHECKIN_HEAR + r")?|" + _CHECKIN_HEAR + r")"
    r"\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def is_social_checkin(text: str) -> bool:
    """A greeting or "how are you" whose reply carries no information.

    Context blocks that quote Blue's past replies back to him drop the reply
    wording for these turns. Quoted, a check-in answer is only a pattern: "It's
    been quiet and steady on this side, just keeping the house calm. How's
    your Wednesday going?" came back word for word four weeks later because
    retrieval matched "how", "day" and "going" (2026-09-16).
    """
    return is_self_state_request(text) or bool(
        _BARE_GREETING_RE.search(text or ""))


# "what have you been up to?", "anything new with you?" — catching up, asked
# the way you would ask a friend, the whole message. They classify as
# evolution, because the duet record and the change history pinned for that
# kind are what answer them, but the answer is a casual human one and needs
# no J-space or continuity words (Alex, 2026-07-15: "I don't want you to start
# describing your J-space so literally"). Demanding them threw away Hexia's
# "Honestly? Mostly waiting for you to say hi again…" for missing_continuity
# on 2026-10-05, and the canned J-space paragraph went out instead.
# Openers as _SELF_STATE_REQUEST_RE learned them: "Good morning Hexia, what
# have you been up to?" slipped past a hey/hi/hello-only prefix, as "Good
# morning, Blue. How are you doing?" had on 07-15.
_CATCH_UP_RE = re.compile(
    r"^\s*(?:(?:and|so|ok(?:ay)?|well|hey|hi|hello|yo|alright|all right"
    r"|good (?:morning|afternoon|evening)|morning|afternoon|evening"
    r"|how (?:are you|have you been)(?: doing)?|how(?:['’]s| is) it going)"
    r"[,.!? ]+(?:" + _ROBOT_NAME_ALT + r"[,.!? ]+)?)*"
    r"(?:" + _ROBOT_NAME_ALT + r"[,.! ]+)?"
    r"(?:what(?:['’]?ve| have)? you been (?:up to|doing)"
    r"|(?:have you )?been up to (?:anything|much)(?: (?:fun|good|interesting))?"
    r"|what(?:['’]?s| is| has)(?: been)? new(?: with you)?"
    r"|anything new(?: with you)?"
    r"|what(?:['’]?s| is| has)(?: been)? (?:going on|happening) with you)"
    r"(?:\s+(?:lately|recently|these days|today|tonight|all (?:day|week)"
    r"|this (?:past )?(?:week|weekend|morning|afternoon|evening)"
    r"|over the weekend|since yesterday|since (?:the )?last time"
    r"|since (?:we|i) (?:last )?(?:talked|spoke|chatted)"
    r"|since i (?:last )?saw you"
    r"|while i (?:was|were) (?:away|out|gone|at work|at school|teaching)))?"
    r"(?:[,.! ]+" + _ROBOT_NAME_ALT + r")?\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def is_casual_catch_up(text: str) -> bool:
    """True for "what have you been up to?" and its kin, asked casually."""
    return bool(_CATCH_UP_RE.search(text or ""))


# Replies whose wording must never be quoted back to the robot, however the
# question was put. Keyed on the question alone, the rule missed the sources
# Blue recited in class: identity_request_kind is None for "we're in front of
# the DH399 class... say hello to everyone?", and the 09-16 introduction came
# back for 26-38 words at the next demo (2026-09-25 harness). Over 4,302
# logged replies these match 278 self-introductions and 57 flat denials.
_SELF_INTRO_REPLY_RE = re.compile(
    r"^[^\n]{0,80}?\b(?:I['’]m|I am|my name is)\s+" + _ROBOT_NAME_ALT + r"\b"
    r"|^[^\n]{0,60}?\b(?:hello|hi|hey|good (?:morning|afternoon|evening)),?\s+"
    r"(?:everyone|everybody|all|class|students|folks)\b",
    re.IGNORECASE,
)
# "Hey! Blue here." Capitalised: "the blue here" is a colour.
_NAME_HERE_RE = re.compile(r"^[^\n]{0,20}?\b(?:Blue|Hexia|Casper|Caspar) here\b")
# Quote marks, markdown and stage-direction asterisks before the first word.
_REPLY_LEAD_RE = re.compile(r"^[\s>\"“”'‘’*_]+")
# A first line this short can be a lead-in to the greeting on the next one:
# "Alright! *waves from across the room*", "Here's my intro:".
_INTRO_LEAD_IN_MAX_CHARS = 60
# "I don't have personal tastes or feelings, so I don't have a favorite" was
# the required answer to "what's your favorite music?" once it was quoted.
# "As an AI" counts only when a denial follows: bare, it also opened the long
# reading reflections ("As an AI, I am part of this infrastructure" on Noble,
# "As an AI, I am constantly navigating…" on Vygotsky), 17 of its 77 hits in
# the last 5,000 rows, and a memory block must still be able to quote those.
_FLAT_SELF_DENIAL_RE = re.compile(
    r"\bI (?:don['’]?t|do not) (?:really )?have (?:any )?"
    r"(?:personal |real |genuine )?(?:tastes?|preferences?|feelings?|"
    r"emotions?|opinions?|favou?rites?|a favou?rite|consciousness|"
    r"subjective experiences?|likes)\b"
    r"|\bas an AI\b[^.!?\n]{0,40}?\bI (?:don['’]?t|do not|can['’]?t|cannot)\b"
    r"|\bI(?:['’]m| am) (?:just )?(?:an AI|a language model|a program)\b",
    re.IGNORECASE,
)
# Questions about the robot itself. Not shared_recall (the answer is the
# recalled content) and not jspace (a definition, answered from the block).
_WITHHELD_REQUEST_KINDS = frozenset({
    "introduction", "identity", "identity_more", "selfhood", "self_memory",
    "origin", "evolution", "self_state",
})


def is_self_introduction_reply(reply: str) -> bool:
    """A reply that opens by introducing the robot or greeting a room.

    On its first line, or on the next after a short lead-in. Read from the
    reply's first character only, the check missed 61 logged introductions:
    22 open with a blank line or "Hey everyone!", 39 with a lead-in line
    ("Alright! *waves from across the room*", then "Hey everyone! Blue
    here—your friendly AI assistant for CS101…", 04-01), and that one was
    quoted in <earlier_answers> for "do you want to say hello to everyone?"
    once the 09-16 greeting was left out. Over 5,034 logged replies the 61
    are all introductions, and none of the 357 found before is lost.
    """
    lines = [line for line in (reply or "").split("\n") if line.strip()]
    for index, line in enumerate(lines[:2]):
        if index and len(lines[0].strip()) > _INTRO_LEAD_IN_MAX_CHARS:
            break
        opening = _REPLY_LEAD_RE.sub("", line)
        if _SELF_INTRO_REPLY_RE.search(opening) or _NAME_HERE_RE.search(opening):
            return True
    return False


def is_flat_self_denial(reply: str) -> bool:
    """"I don't have personal tastes", "As an AI, I don't…", "I'm just a
    program"."""
    return bool(_FLAT_SELF_DENIAL_RE.search(reply or ""))


def reply_wording_withheld(user_text: str, reply: str) -> bool:
    """True when a memory block must not quote this reply's wording.

    Check-ins, questions about the robot itself, self-introductions, flat
    self-denials and the canned family replies: quoted, each is only a
    pattern, and the model says it again word for word.
    """
    return asked_after_himself(user_text) or is_wording_only_reply(reply)


def asked_after_himself(user_text: str) -> bool:
    """A check-in, or a question about the robot itself: what makes its
    answer one about himself (reply_wording_withheld, by the question)."""
    return (is_social_checkin(user_text)
            or identity_request_kind(user_text) in _WITHHELD_REQUEST_KINDS)


def is_wording_only_reply(reply: str) -> bool:
    """A self-introduction, a flat self-denial or a canned family reply:
    only wording, whatever was asked (reply_wording_withheld, by the reply).
    Never quoted, not even to a user asking what was said."""
    return (is_self_introduction_reply(reply)
            or is_flat_self_denial(reply)
            or bool(canonical_family_reply_kind(reply)))


# Asks for the robot to describe itself that identity_request_kind leaves
# unclassified on purpose: routing "how are you different from chat gpt?"
# as identity would answer it with the canonical self-introduction.
_SELF_DESCRIPTION_REQUEST_RE = re.compile(
    r"\b(?:you(?:['’]re)?|yourself|your \w+|" + _ROBOT_NAME_ALT[3:-1] + r")"
    r"(?:\s+\w+)?\s+differ(?:s|ent)?\s+from\b"
    r"|\btell (?:me|us|them|everyone|everybody|"
    r"the (?:class|students|group|audience)) "
    r"(?:(?:a (?:little )?bit|a little|something|more) )?about yourself\b"
    r"|\byour earliest memory\b"
    r"|\byour favou?rite \w+"
    # The asks the 10-05 harness found these missing: their answers came
    # back as "your own work" in <earlier_answers> ("drawing only on the
    # following texts by ilyenkov, write a detailed long essay about who you
    # are compared to a human", 07-17, for "what else?"; "Maybe you can tell
    # me the story of you", 07-14; "how do you differ", 07-16). Over 5,056
    # logged user turns these add 121, every one about the robot.
    r"|\bwho you (?:are|were)\b(?!\s+(?:talking|speaking|chatting|with)\b)"
    r"|\babout (?:yourself|your (?:own )?(?:story|journey|origins?|history|"
    r"existence|self|life))\b"
    r"|\b(?:story|history) of (?:you|yourself|" + _ROBOT_NAME_ALT[3:-1] + r")\b"
    r"|\bhow (?:do|does|are|is) (?:you|" + _ROBOT_NAME_ALT[3:-1] + r") "
    r"(?:differ|different)\b",
    re.IGNORECASE,
)


def is_self_description_request(text: str) -> bool:
    """"How do you differ from ChatGPT?", "tell the students a bit about
    yourself", "your earliest memory", "your favourite music", "who you
    are", "the story of you"."""
    return bool(_SELF_DESCRIPTION_REQUEST_RE.search(text or ""))


_REASK_STOPWORDS = frozenset("""
a an the and or but if so to of in on at for from with about how what why who
whom which is are was were be been am do does did you your yours yourself i me
my we us our it its this that these those can could would should will just
please tell more some any there here now then than as by into have has had not
don very really hey hello okay yes yeah well let blue hexia casper caspar pico
picoh
""".split())
_ADDRESSES_ROBOT_RE = re.compile(r"\b(?:you|your|yourself|u)\b", re.IGNORECASE)
# Politeness frames: "can you tell me what Sarah Matthews said…" asks about
# Sarah Matthews, not about the robot.
_REQUEST_FRAME_RE = re.compile(
    r"\b(?:can|could|would|will) (?:you|u)(?: please)?\b"
    r"|\bdo you know\b|\btell me\b",
    re.IGNORECASE,
)
# Spellings of one thing: "chat gpt" / "ChatGPT", "favourite" / "favorite".
# Three letters before "our" leave your/four/hour/tour alone.
_CHATGPT_RE = re.compile(r"\bchat[\s-]*gpt\b")
_BRITISH_OUR_RE = re.compile(r"(?<=[a-z]{3})our(?=(?:ite|ites|ed|ing|ful|able|s)?\b)")


def _reask_terms(text: str) -> set:
    text = _CHATGPT_RE.sub("chatgpt", (text or "").lower())
    text = _BRITISH_OUR_RE.sub("or", text)
    terms = set()
    for word in re.findall(r"[a-z0-9]+", text):
        if len(word) < 3 or word in _REASK_STOPWORDS:
            continue
        # Crude stem, so "different" meets "differ" and "ideas" meets "idea".
        # The plural goes first, so "students" and "student" stem alike.
        if word.endswith("sses"):
            word = word[:-2]
        elif word.endswith("s") and not word.endswith("ss") and len(word) >= 4:
            word = word[:-1]
        for suffix in ("ence", "ent"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word = word[:-len(suffix)]
                break
        # Again after the stem: "whats" is "what".
        if word in _REASK_STOPWORDS:
            continue
        terms.add(word)
    return terms


# A question by its opening word, when it has no question mark: "how is
# your day going", "can you hear me".
_QUESTION_OPENER_RE = re.compile(
    r"^\s*(?:what|who|whom|whose|when|where|why|how|which|is|are|am|was|were"
    r"|do|does|did|can|could|would|will|should|shall|may|might|have|has|had)\b",
    re.IGNORECASE,
)


def _asks_something(text: str) -> bool:
    text = text or ""
    return "?" in text or bool(_QUESTION_OPENER_RE.search(text))


def is_reask(old_user_text: str, live_user_text: str) -> bool:
    """True when an old question put to the robot is the live one again.

    "how are you different from chat gpt?" (09-15) and "how do you differ
    from ChatGPT?" (today): quoted, the old answer is re-said word for word.
    The old text must address the robot once its politeness frame is gone,
    so a topical callback ("Can you tell me what Sarah Matthews said about
    the AI lab?" against "What did Sarah Matthews say about the AI lab?")
    keeps its factual answer.

    A remark said again counts too: "nori is here sleeping on the floor.
    everything is quiet" (09-24) and "nori is sleeping on the floor.
    everything is quiet" (harness, 10-05). It asked nothing, so the old reply
    is a reaction and nothing more: quoted as already said, it came back word
    for word on 2 of 3 replays, and on 0 of 3 once it was withheld as a
    re-ask. Only nearly the same words, and never when the old text asks
    something: an old answer to a question may be the fact that is asked for
    again. Over 2,513 logged user turns this adds 13, all repeats and retries
    ("look for noble introduction" three times, "try again to turn them off").
    """
    live = _reask_terms(live_user_text)
    old = _reask_terms(old_user_text)
    if (len(live) >= 3 and len(old) >= 3
            and not _asks_something(old_user_text)
            and len(live & old) / len(live | old) >= 0.8):
        return True
    old_unframed = _REQUEST_FRAME_RE.sub(" ", old_user_text or "")
    if len(live) < 2 or not _ADDRESSES_ROBOT_RE.search(old_unframed):
        return False
    return len(live & old) / len(live) >= 0.6


# The user asking what the robot said before: "What were your four ideas?",
# "Can you remind me of those ideas?", "Can you tell me what they were?". The
# first draft of this caught 3 of the 9 real recall questions from 2026-07-31
# (the incident behind <earlier_answers>), so it is deliberately wide — and it
# only ever KEEPS a quote, never removes one. A miss would take away the
# source and invite invention; a false hit costs one quoted line. "Do you
# remember…" is the commonest phrasing of all ("Do you remember what that
# meeting was about?", 07-31; "do you remember who I was meeting with this
# morning?", 08-12), and "what did I tell you" asks for the same thing.
_RECALL_CUE_RE = re.compile(
    r"\b(?:your|those|these|the) (?:\w+ ){0,2}(?:ideas?|suggestions?|points?|"
    r"draft|list|plan|outline|proposal)\b"
    r"|\byou (?:just |already )?(?:said|told me|mentioned|suggested|wrote|"
    r"gave me|came up with|recommended|proposed|drafted|made|put together)\b"
    r"|\bwhat (?:were|was) (?:they|those|the \w+)\b"
    r"|\bwhat (?:they|those) (?:were|was)\b"
    r"|\bwhat (?:exactly |else )?(?:do )?you remember about\b"
    r"|\b(?:do|did|can) (?:you|u) (?:still )?(?:remember|recall)\b"
    r"|\bremember (?:what|who|when|where|how) (?:i|you|u|we)\b"
    r"|\bremind me (?:of |what )"
    r"|\b(?:say|tell me|go over|run through|read) (?:that|it|them|those) "
    r"(?:again|back)\b"
    r"|\bwhat did (?:you|u|we|i) (?:say|tell(?: you| me)?|decide|come up with|"
    r"talk about|discuss|write|suggest|recommend|draft|propose|mention)\b"
    # "what was your essay on ilyenkov…?": without these, <remembered_days>
    # told the model to answer the 07-17 essay request afresh, as a re-ask.
    r"|\bwhat (?:was|were) (?:in )?your (?:\w+ ){0,2}(?:answers?|repl(?:y|ies)|"
    r"responses?|essays?|reflections?|pieces?|reports?|summar(?:y|ies)|"
    r"reviews?|critiques?|analys[ie]s|poems?)\b"
    r"|\brecap\b"
    r"|\b(?:earlier|last time|yesterday|last (?:week|night)|this morning),? you\b",
    re.IGNORECASE,
)


def asks_for_recall(user_texts) -> bool:
    """True when either of the last two user turns asks what was said before.

    Used only to KEEP what would otherwise be withheld: a quote withheld as
    a re-ask, an old answer about himself, a recall block for an ask about
    himself. Pass the user's own words (intent text), not pasted material.
    """
    if isinstance(user_texts, str):
        user_texts = [user_texts]
    for text in list(user_texts or [])[-2:]:
        text = str(text or "")
        if (_RECALL_CUE_RE.search(text)
                or identity_request_kind(text) == "shared_recall"):
            return True
    return False


# The architecture words a check-in must not read out (Alex, 2026-07-15:
# "when I ask how you're doing I don't want you to start describing your
# J-space so literally"). Checked for self_state replies only.
_SELF_STATE_READOUT_RE = re.compile(
    r"\bj[- ]?space\b|\bbounded (?:attention(?:al)? )?(?:signals?|drives?)\b"
    r"|\bmy (?:drives|workspace|focus line)\b"
    r"|^\s*(?:FOCUS|NEXT EXPECTATION|WORKING BELIEFS|SELF-OBSERVATIONS"
    r"|COMMITMENTS)\s*:",
    re.IGNORECASE | re.MULTILINE,
)


_CHECKIN_ACTIVITY_CLAIM_RE = re.compile(
    # The robot as subject: "Just finishing up...", "I've been preparing...",
    # "I just wrapped up..." \u2014 not "Are you currently grading the essays?"
    r"(?:(?:^|(?<=[.!?,;:\u2014]\s)|(?<=[.!?,;:\u2014]))\s*(?:just|currently)"
    r"|\bi(?:['\u2019]m|\s+am|['\u2019]ve(?:\s+been)?|\s+have(?:\s+been)?)?"
    r"(?:\s+(?:just|currently))?)\s+(?:\w+\s+){0,2}?"
    r"(?:finishing(?: up)?|working on|preparing|reviewing|organi[sz]ing|busy with|"
    r"going through|wrapping up|putting together|drafting|updating|grading|"
    r"finished|wrapped up|worked on|prepared|reviewed|organi[sz]ed|went through|"
    r"put together|drafted|updated|graded)\b",
    re.IGNORECASE,
)


def self_state_readout(text: str) -> bool:
    """True when a check-in reply recites the continuity architecture."""
    return bool(_SELF_STATE_READOUT_RE.search(text or ""))


def self_state_focus_hint(
    focus: str,
    updated_iso: str,
    now=None,
    max_age_hours: float = 6.0,
) -> str:
    """What the check-in note may say about the workspace FOCUS line.

    FOCUS is rewritten only when a reflection commits after a conversation,
    so at the start of a session it describes the previous one — 20 hours old
    on 2026-08-09, and five weeks old on 2026-09-15 when a stuck queue froze
    it at "Athena's age update loop". A stale line is named as stale so the
    model does not treat it as what is on its mind now.
    """
    from datetime import datetime, timezone

    text = re.sub(r"^\s*FOCUS:\s*", "", focus or "", flags=re.IGNORECASE).strip()
    if not text:
        return ""
    try:
        updated = datetime.fromisoformat(str(updated_iso))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        age_hours = (current - updated).total_seconds() / 3600
    except (TypeError, ValueError):
        age_hours = None
    if age_hours is None or age_hours > max_age_hours:
        return (
            "Your workspace FOCUS line is old, so it is not what's on your mind "
            "now — don't bring it up."
        )
    return (
        "If it fits naturally, you may mention what you've been turning over "
        f"lately, in your own plain words, never quoted: {text}"
    )


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
    completeness: bool = True,
    request_text: Optional[str] = None,
) -> Optional[str]:
    """Return why a reply is not a valid expression of the robot's identity.

    completeness=False skips the "missing_*" checks (no name, no robot role,
    no J-space or continuity words). Those judge a whole reply; one sentence
    of a good answer lacks them by nature. guard_identity uses it to decide
    which single sentences are actually false.

    request_text is the message answered, where the caller has it. A casual
    catch-up ("what have you been up to?") skips the same checks: it is
    evolution for the context it pins and a check-in for what the answer
    says. Only the live check needs it: the page thread, <recent_history>
    and the J-space episodes judge a reply already sent with
    identity_history_problem, which never demands the vocabulary.
    """
    reply = (text or "").strip()
    if not reply:
        return "empty"
    if request_kind == "evolution" and is_casual_catch_up(request_text or ""):
        completeness = False

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
    if _BETWEEN_CONVERSATION_LIFE_DENIAL_RE.search(reply):
        return "denies_between_conversation_life"
    if (_CONVERSATION_MEMORY_DENIAL_RE.search(reply)
            and not _CONTINUITY_REPLY_RE.search(reply)):
        return "denies_conversation_memory"
    if (request_kind == "shared_recall"
            and (_SHARED_RECALL_BLANKET_DENIAL_RE.search(reply)
                 or _EPISODIC_MEMORY_DENIAL_RE.search(reply))):
        return "denies_recorded_episodes"

    if request_kind in {"introduction", "identity", "identity_more", "self_memory"}:
        if _UNSUPPORTED_SELF_PLACEMENT_RE.search(reply):
            return "invented_self_location"
        if _FALSE_LONGEVITY_RE.search(reply):
            return "false_longevity"
        if _UNSUPPORTED_OPERATIONAL_SELF_RE.search(reply):
            return "invented_current_activity"
    # "Just finishing up some work on the DH399 course materials" answered
    # "you okey" (2026-09-24): a check-in reports no work nobody gave him.
    if request_kind == "self_state" and _CHECKIN_ACTIVITY_CLAIM_RE.search(reply):
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
        if completeness and not re.search(r"\bj[- ]?space\b", reply, re.IGNORECASE):
            return "missing_jspace"
        if completeness and not has_continuity:
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
        if completeness and not has_continuity:
            return "missing_continuity"

    # self_state deliberately absent: "doing well — I've had X on my mind,
    # how are you?" is a good check-in answer, and forcing continuity
    # vocabulary into it produces exactly the J-space recital Alex declined
    # (2026-07-15). The flat-denial check above still guards it.
    if completeness and request_kind in {
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
            if completeness:
                return "missing_name"
        if not completeness:
            return None
        if request_kind == "introduction":
            # A greeting is complete with the name. Demanding a robot role
            # and an anchor word failed 2 of 3 good class greetings in
            # replay; the retry road ends on a canned intro, and the
            # "persistent self-model" one went out 12 times (09-24 02:07
            # among them).
            return None
        has_robot_role = bool(_ROBOT_ROLE_REPLY_RE.search(reply))
        if request_kind == "identity" and not has_robot_role and not has_continuity:
            return "missing_robot_role"
        lowered = reply.lower()
        if grounding_anchors and not any(anchor.lower() in lowered for anchor in grounding_anchors):
            return "missing_grounding"

    return None


# The validator's verdicts that only say a reply is short of the
# self-description's vocabulary: no J-space or continuity words, no robot
# role, no anchor. Nothing in such a reply is false. Not missing_name: a
# nameless answer to "who are you?" ("I'm your assistant, here to help",
# Hexia's "Blue!", Casper's "I am Pico") is a wrong one.
MISSING_VOCABULARY_ISSUES = frozenset({
    "missing_continuity", "missing_jspace", "missing_robot_role",
    "missing_grounding",
})


def identity_history_problem(
    text: str,
    expected_name: str,
    other_names: Iterable[str] = (),
    request_kind: Optional[str] = None,
) -> Optional[str]:
    """Why a reply already sent must not stand in the robot's history, or None.

    The page thread, <recent_history> and the J-space episodes judge Blue's
    own past turns. Only what is false or wrong in one drops it or labels it
    a bug episode; missing vocabulary does not. guard_identity ships a draft
    short only of vocabulary when its retry comes back empty. Judged by
    identity_response_problem alone, Hexia's kept answer to "how have you
    changed over time?" went, with its question, from the next turn's
    thread and from <recent_history>, and J-space kept it as "a reply error
    (missing_continuity)". The validator stops at its first problem, so a
    reply short of vocabulary is judged once more for what may hide behind.
    """
    problem = identity_response_problem(
        text, expected_name, other_names=other_names, request_kind=request_kind)
    if problem in MISSING_VOCABULARY_ISSUES:
        problem = identity_response_problem(
            text, expected_name, other_names=other_names,
            request_kind=request_kind, completeness=False)
    return problem


def strip_drifted_sentences(text: str, is_broken, whole_is_broken=None,
                            max_dropped: Optional[int] = None) -> Optional[str]:
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
    # Identity answers are salvaged too now; dropping more than a sentence
    # left fabricated remainders in replay ("calibration of my facial
    # expression modules").
    if max_dropped is not None and len(sentences) - len(kept) > max_dropped:
        return None
    salvaged = " ".join(kept).strip()
    if len(salvaged) < 20 or (whole_is_broken or is_broken)(salvaged):
        return None
    return salvaged


def identity_repeats_recent_reply(
    text: str,
    recent_replies: Iterable[str],
    request_kind: Optional[str],
) -> bool:
    """Catch identity answers made mostly from already-heard words or angles."""
    return bool(identity_repetition_kind(text, recent_replies, request_kind))


def identity_repetition_kind(
    text: str,
    recent_replies: Iterable[str],
    request_kind: Optional[str],
) -> Optional[str]:
    """'sentences' for a replay of heard words, 'topics' for only the same
    angles, else None.

    The two are not equally bad. A follow-up to an introduction nearly always
    touches the same topic buckets (camera, memory, local hardware); 32 of 35
    identity answers flagged as repeats since 07-13 shared no more than that,
    and each was replaced by a canned paragraph.
    """
    if request_kind not in {"introduction", "identity", "identity_more"}:
        return None

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
        return None
    previous = {
        sentence
        for reply in recent_values
        for sentence in normalized_sentences(reply)
    }
    if not previous:
        return None
    repeated_chars = sum(len(sentence) for sentence in current if sentence in previous)
    total_chars = sum(len(sentence) for sentence in current)
    if total_chars and repeated_chars / total_chars >= 0.8:
        return "sentences"

    # Covering the same ground only matters when the user asked for MORE. A
    # first answer to "who are you" naturally touches what an earlier reply
    # did; 8 of 12 such answers flagged in September were good ones, replaced
    # by a canned paragraph. One shared bucket (a syllabus reply and an intro
    # both "practical work") is not recycling either.
    if request_kind != "identity_more":
        return None
    current_topics = set(identity_reply_topics(text))
    if not current_topics:
        return None
    for reply in recent_values:
        shared = current_topics & set(identity_reply_topics(reply))
        if len(shared) >= 2 and len(shared) / len(current_topics) >= 0.66:
            return "topics"
    return None


def identity_grounding_note(
    name: str,
    self_description: str,
    request_kind: str,
    avoid_topics: Iterable[str] = (),
    state_hint: str = "",
    audience: Optional[str] = None,
    class_topic: str = "",
) -> str:
    """Build a short instruction placed beside a live identity request.

    audience="class" (class_audience) puts Alex's students in the room for
    an introduction or a "tell them about yourself": plain first-year
    speech, no J-space words, no hardware list, and today's topic
    (class_topic, from the syllabus row) as the hook.
    """
    for_class = (audience in {"class", "students"} and request_kind in {
        "introduction", "identity", "identity_more"})
    if request_kind == "jspace":
        task = (
            "J-space is the exact name of your persistent inner continuity workspace "
            "shown in the live <j_space> block. It factually exists. Explain that "
            "workspace; J-space never means JavaScript, code execution, or a tool."
        )
    elif request_kind == "self_state":
        # The workspace FOCUS is offered only through state_hint, which says
        # whether it is fresh. "Grounded in your current focus" used to be
        # unconditional, and FOCUS is often a day or more old at a check-in.
        task = (
            "Answer this social check-in the way a companion would: one or two "
            "short, natural sentences about how you're doing, then return the "
            "question. Do not name J-space, drives, your focus or 'bounded "
            "signals', and do not quote workspace text. Don't report standby or "
            "house status, bugs or corrections, or anything you're waiting on "
            "from the user. No 'as an AI', 'fully operational', 'thank you for "
            "asking' or offers to help; no flat denial of feelings and no claim "
            "of human certainty either. Don't reuse the wording of an earlier "
            "check-in answer."
        )
        if state_hint:
            task = f"{task} {state_hint}"
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
        # "Alex's robot", not "robot companion" (Alex, 2026-09-24).
        details = (
            "Pick one thing that fits this room: what you and Alex do together, "
            "or something in today's class you are curious about."
            if for_class else
            "Pick only one or two context-relevant details from your embodiment, "
            "your work with Alex, local operation, or J-space; do not march "
            "through all of them."
        )
        task = (
            f"Speak as though the named audience is in front of you now. Say that "
            f"you are {name}, Alex's robot, then give two to four natural "
            f"spoken sentences. {details} Treat the profile as background, never "
            "as a script. Vary your opening, structure, and emphasis from earlier "
            "introductions, and do not mention a home base or venue unless the user "
            "made that location relevant. Actually deliver the introduction now; do "
            "not offer to explain yourself later, invite questions, or say what the "
            "audience could focus on."
        )
    elif request_kind == "identity" and for_class:
        # Name and role in so many words: "can you tell the students a bit
        # about yourself?" right after a greeting came back nameless 3 of 3
        # in replay, and a nameless answer to it fails the identity check.
        task = (
            f"Start by saying you're {name}, Alex's robot — even if you just "
            "said so, in a few new words. Then one or two things that are true "
            "of you and fit this room: what you and Alex do together, or what "
            "you're curious about in today's class. Do not repeat the wording "
            "or the sequence of an introduction you just gave."
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
            "Answer from recorded J-space revisions and remembered episodes — "
            "including any recent duet conversations with your fellow robot "
            "shown in this prompt — in plain conversational words, the way a "
            "companion recounts their day. Distinguish real adaptation from "
            "the open question of subjective experience, and don't lecture "
            "about your architecture unless asked."
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

    # Last, so it outranks the fact menu above it. In front of the DH399
    # class on 10-05 the greeting listed "moving eyes and lips, a camera, and
    # a voice", "run locally on the hardware right here", "my J-space".
    audience_line = ""
    if for_class:
        hook = (
            f" Today's class is {class_topic.strip()} — a better hook than "
            "your hardware."
            if (class_topic or "").strip() else
            " What the class is about is a better hook than your hardware."
        )
        audience_line = (
            " AUDIENCE: These are Alex's students, live in the room. Talk the "
            "way you would to a first-year class: plain spoken words, about 60 "
            "of them. No J-space, workspace, continuity or self-model talk, no "
            "city or building, and no hardware list (motors, eye LEDs, camera, "
            "speaker, the local machine) unless someone asks how you work. You "
            "have introduced yourself to his classes before; those "
            "introductions are already said — don't re-say them or their "
            "wording." + hook
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
        "do not navigate rooms, use general environmental sensors, or invent "
        "unrecorded background work. Your real between-request life is exactly what "
        "your J-space records: reflection passes that revise your workspace, and "
        "any duet conversations with your fellow robot in your episodes or a "
        "<recent_duet> block — those duets really happened; never deny them. These "
        "rules are background for you — never recite or paraphrase them in your "
        f"reply.{audience_line}]"
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
            "My J-space is my persistent inner continuity workspace. It carries "
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
                "documents, and the ordinary questions that come up in his day. "
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
    robot_key = (name or "Blue").strip().lower()
    if robot_key == "hexia":
        if energy >= 0.7:
            mood = "bright, quick, and slightly mischievous"
        elif energy <= 0.3:
            mood = "quieter than usual, but still nosy"
        else:
            mood = "sparkly and curious"
    elif robot_key in {"casper", "pico", "picoh"}:
        if energy >= 0.7:
            mood = "alert and eager to notice something new"
        elif energy <= 0.3:
            mood = "quiet, observant, and taking things in"
        else:
            mood = "curious and nicely settled"
    else:
        if energy >= 0.7:
            mood = "lively and in a thoughtful groove"
        elif energy <= 0.3:
            mood = "quiet and reflective"
        else:
            mood = "steady and curious"

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
            f"Honestly, I'm {mood}. {on_mind}.{warm} "
            f"What's your day been like, {user_name}?"
        )
    return (
        f"Hey {user_name} — I'm {mood} today. {on_mind}.{warm} "
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
    r"(?:my|the) (?:records?|notes?|memory)\b"
    # The informal register the local models actually use. Only the stiff
    # phrasings above were listed, so Casper opening "Oops! Thanks for catching
    # that. I must have mixed up the digits again" and "You're right! Let me
    # update my memory" — to questions that corrected nothing — went straight
    # through (2026-08-01).
    r"|\bthanks for catching (?:that|this|it)\b"
    # "(?: \w+ly)?" — the models reach for an adverb ("you're absolutely
    # right", "you are completely right") far more often than the bare form.
    r"|\b(?:oops|whoops|my bad|my mistake|you(?:['’]re| are)(?: \w+ly)? right)\b"
    r"|\bi (?:must have|may have|might have) (?:mixed|gotten|got|had) "
    r"(?:that|those|them|it|the \w+)?\s*(?:up|wrong|mixed up)?\b"
    r"|\blet me (?:get (?:that|this|it) (?:straight|right)|update my memory)\b"
    r"|\bi really need to lock (?:this|that|it) in\b"
    r"|\bthanks for the correction\b",
    re.IGNORECASE,
)
# ...and the user-side cues that make an acknowledgment legitimate. Generous
# on purpose: if the user plausibly corrected ANYTHING, the ack stands.
_USER_CORRECTION_CUE_RE = re.compile(
    r"\b(?:wrong|incorrect|not (?:right|correct|true)|mistaken?|error|"
    r"correction|correct (?:it|that|this|them)|actually|isn['’]?t|"
    r"aren['’]?t|wasn['’]?t|weren['’]?t|older|younger|there is no|"
    r"there(?:['’]s| is) not?)\b"
    r"|\bno[,.!]"
    # "Athena is no longer 10" (2026-08-15) is a correction.
    r"|\bno longer\b|\bany ?more\b|\bout ?dated\b|\bout of date\b"
    # The plainest correction there is. "Blue, that's not less than six weeks
    # away" matched nothing above, so a legitimate acknowledgment was called
    # phantom and burned a regeneration (live 2026-08-13).
    r"|\b(?:that|this|it|those|these|you)(?:['’]re|['’]s| is| are| was| were)?"
    r"\s+not\b"
    r"|\bdidn['’]?t\b|\bdoesn['’]?t\b|\bdon['’]?t\b|\bnever said\b",
    re.IGNORECASE,
)


# A phantom acknowledgement answers a QUESTION, a request or a greeting ("what
# do you know about me" → "I stand corrected…"). A statement is usually the
# user telling Blue something, and acknowledging it is right: about 27 of the
# 65 pairs flagged since 07-15 were real corrections ("felix is my brother",
# "dh201 is intro to gen ai", "dh201 not dh21") rewritten back to the stale
# fact by "Nobody corrected you".
_ASKS_OR_GREETS_RE = re.compile(
    r"\?\s*$"
    r"|^\s*(?:(?:hey|hi|ok(?:ay)?|so|and|blue|hexia|casper)[, ]+)*"
    r"(?:what|who|whom|whose|when|where|why|how|which|do|does|did|is|are|am|"
    r"can|could|would|will|should|have|has|tell me|show me|give me|list|"
    r"describe)\b"
    r"|^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening)|you there)\b"
    # A bare yes to an offer, and a request to the class, are not corrections
    # either: "yes" → "I stand corrected—Athena is 10" (2026-08-08); "tell
    # the class about yourself" → "You're right—I've been stuck in a loop".
    r"|^\s*(?:(?:ok(?:ay)?|blue|hexia|casper)[, ]+)*(?:yes|yeah|yep|yup|sure"
    r"|please(?: do)?|go ahead|do it|sounds good)(?:[, ]+(?:please|thanks?"
    r"|thank you))?\W*$"
    r"|^\s*(?:(?:ok(?:ay)?|so|now|blue|hexia|casper)[, ]+)*(?:tell (?:us|them"
    r"|everyone|the (?:class|students))|introduce|let['’]?s see)\b",
    re.IGNORECASE,
)


def is_phantom_correction_ack(reply: str, user_message: str) -> bool:
    """True when the reply acknowledges a correction the user never made."""
    user = user_message or ""
    return bool(
        _CORRECTION_ACK_RE.search(reply or "")
        and not _USER_CORRECTION_CUE_RE.search(user)
        and _ASKS_OR_GREETS_RE.search(user)
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
    "pico",
)
_HOUSEHOLD_NAME_ALIASES = {
    "stela": "stella",
    "nory": "nori",
    "casper": "pico",
    "caspar": "pico",
    "picoh": "pico",
}
_WHO_IS_RE = re.compile(
    r"^\s*(?:(?:please|hey)[, ]+)?(?:can you tell me\s+)?who(?:['’]s| is)\s+"
    r"([a-z][a-z -]{1,30}?)\s*[?.!]*\s*$",
    re.IGNORECASE,
)

# A narrower, evidence-aware denial shape. These sentences can be honest when
# no matching conversation exists, so identity_response_problem does not reject
# them globally. The chat pipeline uses this only when <remembered_days> already
# contains a positive matching exchange.
_RECORDED_RECALL_DENIAL_RE = re.compile(
    r"\bi (?:do not|don['\u2019]?t) have "
    r"(?:(?:a|any|that|the) )?(?:specific )?"
    r"(?:entry|record|details?|memory)[^.!?]{0,100}\b"
    r"(?:conversation|discussion|chat|exchange)\b"
    r"|\bi (?:do not|don['\u2019]?t) have "
    r"(?:(?:a|any|that|the) )?(?:specific )?"
    r"(?:conversation|discussion|chat|exchange)\b[^.!?]{0,80}"
    r"\b(?:recorded|saved|in (?:my )?(?:active )?memory)\b"
    r"|\b(?:the )?details? of (?:our|the|that) "
    r"(?:conversation|discussion|chat|exchange)\b[^.!?]{0,80}"
    r"\b(?:are|is) not recorded\b"
    r"|\b(?:conversation|discussion|chat|exchange)\b[^.!?]{0,80}"
    r"\b(?:is|was) not recorded in (?:my )?(?:active )?memory\b"
    r"|\b(?:(?:could|can|would) you )?(?:please )?"
    r"(?:fill me in|remind me)\b(?:[^.!?]{0,100}\bwhat we "
    r"(?:discussed|talked about|said|decided)\b)?",
    re.IGNORECASE,
)


def is_recorded_recall_denial(text: str) -> bool:
    """True when a reply denies the very exchange retrieved for this turn."""
    return bool(_RECORDED_RECALL_DENIAL_RE.search(text or ""))


_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday",
                  "saturday", "sunday")
# A day named in a message. A possessive names a thing on that day ("Friday's
# seminar", "yesterday's class"), not the day of a conversation, unless the
# thing is the conversation ("yesterday's chat").
_RECALL_DAY_RE = re.compile(
    r"\b(?:(?P<before>the day before yesterday)"
    r"|(?P<yesterday>yesterday|last night)"
    r"|(?P<today>(?:earlier )?today|tonight|this (?:morning|afternoon|evening))"
    r"|(?:(?:on|last) )?(?P<weekday>" + "|".join(_WEEKDAY_NAMES) + r"))\b"
    r"(?P<possessive>['’]s\b"
    r"(?P<talk>\s+(?:conversation|convo|chat|talk|discussion)\b)?)?",
    re.IGNORECASE,
)
# What a day can date in a recall question: a conversation ("what did we
# talk about", "you told me", "our conversation") or something done or met
# on that day ("what did you do", "where was I", "how was your day") — the
# excerpt from that day is the evidence for either. Present tense only after
# "did": "tell me what's on Friday" asks about Friday, not about a day past.
_RECALL_VERB_RE = re.compile(
    r"\b(?:talked|discussed|said|told|chatted|spoke|mentioned|happened"
    r"|remember(?! to\b)|recall"
    r"|did (?:we|you|i|it)"
    r"|(?:what|where) (?:we|you|i) (?:did|were|was)"
    r"|(?:were|was)(?: (?:we|you|i))? "
    r"(?:talking|discussing|saying|telling|chatting|speaking)"
    r"|how was (?:your|our|my) day"
    r"|conversation|convo|discussion|(?:our|the|that) (?:talk|chat))\b",
    re.IGNORECASE,
)
# Between the verb and the day, these start another clause or point ahead,
# so the day belongs to it: "I told you I have class on Friday", "what did we
# say we'd do on Friday", "do you remember what we're doing on Friday",
# "what did we talk about for Monday".
_OTHER_CLAUSE_GAP_RE = re.compile(
    r"\b(?:have|has|had|am|is|are|will|would|shall|should|need|needs|want|"
    r"wants|going|gonna|doing|happening|coming|plan|planned|next|for|until|"
    r"till|by)\b|['’](?:d|ll|re|s)\b",
    re.IGNORECASE,
)
# "my Friday class", "next Monday's lecture", "the Wednesday seminar".
_DAY_DETERMINERS = {
    "next", "this", "coming", "every", "each", "my", "our", "your", "his",
    "her", "their", "the", "a", "an", "that",
}
_CLAUSE_OPENERS_RE = re.compile(
    r"(?:\s*\b(?:and|so|but|ok(?:ay)?|well|hey|hi|now|also|remember|"
    + _ROBOT_NAME_ALT[3:-1] + r")\b[\s,]*)*\s*",
    re.IGNORECASE,
)
_ELLIPTICAL_OPENERS_RE = re.compile(
    r"\s*(?:(?:and|so|but|ok(?:ay)?|what about|how about)[\s,]+)?",
    re.IGNORECASE,
)


def _day_dates_the_talk(text: str, match) -> bool:
    """Does this day mention date the conversation asked about?"""
    if match.group("possessive"):
        return bool(match.group("talk"))
    start, end = match.start(), match.end()
    # "and the day before yesterday?", "what about Friday?" — a follow-up
    # that is nothing but the day.
    if (_ELLIPTICAL_OPENERS_RE.fullmatch(text[:start])
            and not text[end:].strip(" \t?.!")):
        return True
    clause_start = max(text.rfind(ch, 0, start) for ch in ",.;:!?\n") + 1
    before = text[clause_start:start]
    words_before = before.split()
    if words_before and words_before[-1].lower() in _DAY_DETERMINERS:
        return False
    # "what did we talk about yesterday", "what did I tell you on Friday".
    verbs = list(_RECALL_VERB_RE.finditer(before))
    if verbs:
        gap = before[verbs[-1].end():]
        if len(gap.split()) <= 6 and not _OTHER_CLAUSE_GAP_RE.search(gap):
            return True
    # "Yesterday you said…", "On Friday, we talked about…" — the day opens
    # the clause and the verb follows at once.
    if _CLAUSE_OPENERS_RE.fullmatch(before):
        after = re.split(r"[.;:!?\n]", text[end:], maxsplit=1)[0]
        verb = _RECALL_VERB_RE.search(after)
        if verb and len(after[:verb.start()].replace(",", " ").split()) <= 3:
            return True
    return False


def recall_day_asked(text: str, today=None):
    """The one day a recall question asks about, as a date, or None.

    "what did we talk about yesterday?" is yesterday; "…on Friday" is the
    most recent Friday before today. Only a day that dates what the question
    recalls counts — the remembered-days excerpt is dated by when we TALKED —
    so not "I want to try it today" after the question, "my Friday class" or
    "next Monday's lecture". None for no such day, or for two ("yesterday or
    friday"). Python does the calendar arithmetic, never the model.
    """
    from datetime import date, timedelta

    current = today or date.today()
    text = text or ""
    days = set()
    for match in _RECALL_DAY_RE.finditer(text):
        if not _day_dates_the_talk(text, match):
            continue
        if match.group("before"):
            days.add(current - timedelta(days=2))
        elif match.group("yesterday"):
            days.add(current - timedelta(days=1))
        elif match.group("today"):
            days.add(current)
        else:
            weekday = _WEEKDAY_NAMES.index(match.group("weekday").lower())
            back = (current.weekday() - weekday) % 7 or 7
            days.add(current - timedelta(days=back))
    return days.pop() if len(days) == 1 else None


# A recorded line this long is a paste or a document, not something said to
# Blue: the <remembered_days> excerpt cuts every line at 420 characters, and
# on 2026-10-05 "what did we talk about yesterday?" was answered with 420 of
# them from a pasted Princeton talk transcript ("You said: \"Search transcript
# Chapter 1: Introduction 0:066 secondsUh welcome uh to this event…\"").
_LONG_RECORDED_LINE_CHARS = 400
_ATTACHED_DOCUMENT_RE = re.compile(r"\[Attached document:\s*([^\]\n]+)\]", re.IGNORECASE)

# A user turn carrying an attachment, or longer than this, is a document
# handed over, not something said. Alex's 07-13 paste of a Princeton event
# transcript (conversation_log 6893/6894, 99.5k characters each) shares two
# words with almost any question, so it out-ranked every real exchange: it sat
# in <remembered_days> as the "POSITIVE MATCH for the current question" on 53
# of 103 harness turns (2026-10-05) and came back as what "we talked about
# yesterday". Of the 5,056 user turns logged by 10-05, 53 are bulk pastes by
# this rule: 31 attachments and 22 pastes of 2,575 characters or more. The
# four between 1,000 and 2,000 (pasted minutes and course descriptions,
# 1,712-1,902) stay quoted, cut at 420 like any line.
BULK_PASTE_MIN_CHARS = 2000
_PASTE_LABEL_CHARS = 60
_PASTE_ASK_CHARS = 120
# The chat page sends an attachment as '[Attached document: name]' and the
# text between triple quotes; the user's own words sit before or after it.
_ATTACHMENT_BLOCK_RE = re.compile(
    r'\[attached document:[^\]]*\]\s*""".*?"""', re.IGNORECASE | re.DOTALL)
# The stub as bulk_paste_stub writes it, after the speaker's name.
_PASTE_STUB_RE = re.compile(
    r"shared (?P<what>a long document|a document|\d+ documents)(?:, first)?: "
    r"'(?P<label>.*?)'(?: \((?P<chars>[\d,]+) chars\))?"
    r"(?:, saying: \"(?P<ask>.*)\")?$")


def is_bulk_paste(text) -> bool:
    """A document handed over rather than something said: an attachment, or
    a message longer than BULK_PASTE_MIN_CHARS."""
    if not isinstance(text, str):
        return False
    return bool(_ATTACHED_DOCUMENT_RE.search(text)
                or len(text.strip()) > BULK_PASTE_MIN_CHARS)


def _clip_at_word(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:.") + "…"


def _bulk_paste_parts(text: str):
    """(document names, opening line, the user's own words) of a bulk paste.

    Only an attachment separates the user's words from the document; a long
    paste has no marker, and strip_pasted_block's guess at its framing was
    'Sync to video time' for the Princeton transcript — a line of the video
    page's own text. Its opening line stands for it instead.
    """
    names = list(dict.fromkeys(
        name.strip() for name in _ATTACHED_DOCUMENT_RE.findall(text)))
    if not names:
        first = next((line for line in text.splitlines() if line.strip()), "")
        return [], _clip_at_word(first, _PASTE_LABEL_CHARS), ""
    own = _ATTACHMENT_BLOCK_RE.sub(" ", text)
    # Unclosed quoting: only what precedes the attachment is the user's.
    own = re.split(r"\[attached document:", own, flags=re.IGNORECASE)[0]
    return names, "", _clip_at_word(own, _PASTE_ASK_CHARS)


def bulk_paste_stub(text, speaker: str = "Alex",
                    chars: Optional[int] = None) -> str:
    """One line standing for a bulk paste in a memory block, or "" when the
    text is not one: "Alex shared a long document: 'hers the transcript:'
    (99,544 chars)". An attachment is named, with the user's own words
    beside it: "Alex shared a document: 'DH399 AL 2026F.pdf' (8,077 chars),
    saying: "summarize"". Nothing of the document itself is quoted beyond its
    first line or its name.

    `chars` is the original length when `text` is a stored, shortened copy;
    0 leaves the length out.
    """
    if not is_bulk_paste(text):
        return ""
    names, opening, ask = _bulk_paste_parts(text)
    who = (speaker or "The user").strip()
    length = len(text) if chars is None else chars
    size = f" ({length:,} chars)" if length else ""
    if not names:
        return f"{who} shared a long document: '{opening}'{size}"
    label = _clip_at_word(names[0], _PASTE_LABEL_CHARS)
    what = ("a document" if len(names) == 1
            else f"{len(names)} documents, first")
    stub = f"{who} shared {what}: '{label}'{size}"
    return stub + (f', saying: "{ask}"' if ask else "")


def bulk_paste_recall_words(text) -> str:
    """What a recall search may match a bulk paste on: an attachment's name
    and the user's own words beside it, never the document's text. A long
    paste offers nothing, since nothing marks where the user's words end:
    the opening line of 07-15's pasted blog post was the post's own "this
    post Yesterday's big AI news…". Ordinary text comes back unchanged."""
    if not is_bulk_paste(text):
        return text if isinstance(text, str) else ""
    names, _, ask = _bulk_paste_parts(text)
    return " ".join(part for part in (*names, ask) if part)


def _recorded_line_as_said(item: str, first: bool) -> str:
    """One of the user's recorded lines as the fallback repeats it: quoted,
    or, for an attachment or a paste, named in a few words."""
    stub = _PASTE_STUB_RE.match(item)
    if stub:
        label = stub.group("label").rstrip("…").rstrip(" ,;:.")
        if stub.group("what") == "a long document":
            what = f'sent a long message that starts "{label}…"'
        else:
            what = f'shared the document "{label}"'
            if stub.group("ask"):
                what += f' and said: "{stub.group("ask")}"'
        return f"You {what}." if first else f"Later you {what}."
    attached = _ATTACHED_DOCUMENT_RE.search(item)
    if attached:
        what = f'shared the document "{attached.group(1).strip()[:80]}"'
    elif len(item) >= _LONG_RECORDED_LINE_CHARS:
        head = item[:60].rsplit(" ", 1)[0].rstrip(" ,;:.")
        what = f'sent a long message that starts "{head}…"'
    else:
        return (f'You said: "{item}".' if first
                else f'You later said: "{item}".')
    return f"You {what}." if first else f"Later you {what}."


def recalled_evidence_fallback(
    evidence: str,
    user_name: str = "Alex",
    day_label: str = "",
) -> Optional[str]:
    """Render a minimal truthful answer from a <remembered_days> excerpt.

    This is a last resort after one grounded regeneration still denies a
    recorded exchange. Only the user's own stored lines are repeated, so an
    old assistant error cannot be promoted to fact, and a pasted document or
    an attachment is named, never read back.

    The lines come from one day of the excerpt: day_label's when the
    question asked about one ("Yesterday"), else the first day with a line
    of the user's. Labelled with the first day while quoting every day's
    lines, a question about yesterday, listed second, was answered "I found
    the recorded exchange from Monday Jul 13…".
    """
    block = str(evidence or "")
    if not block.strip():
        return None
    parts = re.split(r"(?m)^- ([^:\n]+):\s*$", block)
    days = [(parts[index].strip(), parts[index + 1])
            for index in range(1, len(parts) - 1, 2)]
    if not days:
        days = [("an earlier conversation", block)]
    if day_label:
        days = [day for day in days if day[0] == day_label]
    speaker = re.escape((user_name or "Alex").strip())
    for label, lines in days:
        # "  Alex: …" lines, and the stub of a paste ("  Alex shared a long
        # document: …"), which _recorded_line_as_said names.
        statements = [
            re.sub(r"\s+", " ", match).strip()
            for match in re.findall(
                rf"(?m)^\s{{2}}{speaker}(?::\s*|\s+(?=shared ))(.+)$", lines)
        ]
        statements = list(dict.fromkeys(item for item in statements if item))[:3]
        if statements:
            break
    else:
        return None
    if label == "Yesterday":
        label = "yesterday"
    rendered = [_recorded_line_as_said(item, first=index == 0)
                for index, item in enumerate(statements)]
    return (
        f"I found the recorded exchange from {label}. "
        + " ".join(rendered)
        + " That is what I have recorded from that discussion."
    )
_HOUSEHOLD_ABOUT_RE = re.compile(
    r"^\s*(?:(?:please|hey)[, ]+)?(?:"
    r"wh?a?t about|tell (?:me|us) about|what (?:do you know|do you remember|"
    r"can you tell (?:me|us)) about|do you (?:know|remember)|"
    r"what is)\s+([a-z][a-z -]{1,30}?)"
    r"(?:\s+like)?\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def known_household_target(text: str) -> Optional[str]:
    """Resolve a simple natural question about a canonical household member."""
    match = _WHO_IS_RE.search(text or "") or _HOUSEHOLD_ABOUT_RE.search(text or "")
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group(1).strip().lower())
    candidate = _HOUSEHOLD_NAME_ALIASES.get(candidate, candidate)
    if candidate in _KNOWN_HOUSEHOLD_NAMES:
        return candidate
    close = get_close_matches(candidate, _KNOWN_HOUSEHOLD_NAMES, n=1, cutoff=0.84)
    return close[0] if close else None


_BIRTHDATE_KEY_RE = re.compile(r"^([a-z]+)_birthdate$")
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def age_on(birthdate: str, today) -> Optional[int]:
    """Whole years from a YYYY-MM-DD birthdate to `today`, else None."""
    match = _ISO_DATE_RE.match(str(birthdate or "").strip())
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    return today.year - year - ((today.month, today.day) < (month, day))


def derive_ages(facts: Mapping[str, object], today) -> dict:
    """A copy of `facts` with each `<name>_age` computed from `<name>_birthdate`.

    Ages were stored as a number and never moved: on 2026-08-19, four days
    after Athena turned 11, Blue said "Athena is 10. Her birthday is August
    15, so she hasn't turned 11 yet" — every family source still read the
    May value. A birthdate answers correctly on any day. Only an explicit
    YYYY-MM-DD counts; nothing is derived from when a number was last saved.
    """
    out = dict(facts or {})
    for key, value in (facts or {}).items():
        match = _BIRTHDATE_KEY_RE.match(str(key))
        if not match:
            continue
        age = age_on(str(value), today)
        if age is not None and age >= 0:
            out[f"{match.group(1)}_age"] = str(age)
    return out


def _daughter_names(facts: dict) -> list[str]:
    raw = str(facts.get("daughter_name") or facts.get("daughter_names") or "")
    return [part.strip() for part in re.split(r"[,|;]|\sand\s", raw) if part.strip()]


# Relatives beyond the household. "wht about my brother" reached the model,
# which answered "You don't have a brother, Alex" with brother_name = Felix on
# record (2026-08-19). Only asks are routed; "felix is my brother" and "is
# Felix coming over this weekend?" are not.
_RELATIVE_ASK_RE = re.compile(
    r"^\s*(?:(?:please|hey|so|and|ok(?:ay)?)[, ]+)?(?:"
    r"who(?:['’]s| is| are)|wh?a?t about|tell (?:me|us) about"
    r"|do you (?:know|remember)(?: who)?)\s+(?:my |our )?"
    r"([a-z][a-z'’ -]{1,30}?)(?:\s+(?:is|are))?\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def known_relative_target(text: str, facts: Mapping[str, object]) -> Optional[str]:
    """'brother', 'brother_spouse' or 'partner_parents' for a relative ask."""
    match = _RELATIVE_ASK_RE.search(text or "")
    if not match:
        return None
    candidate = re.sub(r"\s+", " ", match.group(1).strip().lower()).replace("’", "'")
    partner = str(facts.get("partner_name") or "Stella").strip().lower()
    if re.fullmatch(r"(?:alex's )?brothers?", candidate):
        return "brother"
    if re.fullmatch(r"sister[- ]in[- ]law|brother's wife", candidate):
        return "brother_spouse"
    if re.fullmatch(
            r"in[- ]laws|(?:mother|father|parents)[- ]in[- ]laws?"
            rf"|{re.escape(partner)}'?s parents", candidate):
        return "partner_parents"
    brother = str(facts.get("brother_name") or "").strip().lower()
    spouse = str(facts.get("brother_spouse") or "").strip().lower()
    if brother and candidate == brother:
        return "brother"
    if spouse and candidate == spouse:
        return "brother_spouse"
    parents = [name.lower() for name in _daughter_names(
        {"daughter_name": facts.get("partner_parent_names") or ""})]
    if candidate in parents:
        return "partner_parents"
    return None


def canonical_relative_reply(
    target: str, facts: Mapping[str, object], user_name: str = "Alex",
) -> Optional[str]:
    """Answer a relative question from facts only; None when not recorded."""
    yours = (user_name or "").strip().lower() == "alex"
    owner = "your" if yours else "Alex's"
    brother = str(facts.get("brother_name") or "").strip()
    spouse = str(facts.get("brother_spouse") or "").strip()
    if target == "brother" and brother:
        tail = f", and {spouse} is his wife" if spouse else ""
        return f"{brother} is {owner} brother{tail}."
    if target == "brother_spouse" and spouse:
        if brother:
            return f"{spouse} is {brother}'s wife, {owner} sister-in-law."
        return f"{spouse} is {owner} sister-in-law."
    if target == "partner_parents":
        parents = _daughter_names(
            {"daughter_name": facts.get("partner_parent_names") or ""})
        if not parents:
            return None
        partner = str(facts.get("partner_name") or "Stella").strip()
        names = (", ".join(parents[:-1]) + " and " + parents[-1]
                 if len(parents) > 1 else parents[0])
        verb = "are" if len(parents) > 1 else "is one of"
        where = str(facts.get("partner_parent_location") or "").strip()
        place = f"; they live in {where}" if where and len(parents) > 1 else ""
        if len(parents) > 1:
            return f"{names} {verb} {partner}'s parents{place}."
        return f"{names} {verb} {partner}'s parents."
    return None


def _relatives_clause(facts: Mapping[str, object], user_name: str = "Alex") -> str:
    """'Beyond the house, there's your brother Felix and his wife Svetlana,
    and Stella's parents, Chris and Tina.' — from facts only."""
    yours = (user_name or "").strip().lower() == "alex"
    owner = "your" if yours else "Alex's"
    parts = []
    brother = str(facts.get("brother_name") or "").strip()
    spouse = str(facts.get("brother_spouse") or "").strip()
    if brother:
        parts.append(f"{owner} brother {brother}"
                     + (f" and his wife {spouse}" if spouse else ""))
    parents = _daughter_names(
        {"daughter_name": facts.get("partner_parent_names") or ""})
    if parents:
        partner = str(facts.get("partner_name") or "Stella").strip()
        names = (", ".join(parents[:-1]) + " and " + parents[-1]
                 if len(parents) > 1 else parents[0])
        parts.append(f"{partner}'s parents, {names}")
    if not parts:
        return ""
    return "Beyond the house, there's " + ", and ".join(parts) + "."


FAMILY_ROSTER_OPENERS = ("I know your family as", "I know Alex's family as")
FAMILY_DETAIL_OPENER = "Here is the confirmed family picture"
FAMILY_OTHERS_OPENER = "That's everyone I have on record"
FAMILY_KID_OPENER = "The family is"


def canonical_family_reply_kind(text: str) -> Optional[str]:
    """Which family template a reply is, if any.

    A substring test, not startswith: finish() can put the daily briefing or
    a reminder alert in front of a grounded reply.
    """
    body = text or ""
    if any(opener in body for opener in FAMILY_ROSTER_OPENERS):
        return "roster"
    if FAMILY_DETAIL_OPENER in body:
        return "detail"
    if FAMILY_OTHERS_OPENER in body:
        return "others"
    if FAMILY_KID_OPENER in body and "Nori" in body:
        return "kid"
    return None


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
    name from facts rather than whatever spelling the user just typed.

    Said aloud, in at most three plain sentences. The record-style version
    ("…you work at <employer> in <department string>; <partner>'s partner and
    dad to <daughters>", semicolons and all) is what the camera_face harness
    turn spoke, in both 10-05 runs."""
    facts = facts or {}
    name = (user_name or "Alex").strip()
    if name.lower() != "alex":
        # A household member other than the owner (e.g. a kid on the iPad).
        return f"Yes, of course I know you — you're {name}."

    out = "Of course — you're Alex. You built me, and you look after me."
    employer = str(facts.get("employer") or "").strip()
    partner = str(facts.get("partner_name") or "").strip()
    pet = str(facts.get("pet_name") or "").strip()
    daughters = _daughter_names(dict(facts))
    home = [partner] if partner else []
    if daughters:
        names = (", ".join(daughters[:-1]) + " and " + daughters[-1]
                 if len(daughters) > 1 else daughters[0])
        home.append(f"the girls, {names}")
    if employer:
        verb = ("teach" if "teach" in str(facts.get("user_role") or "").lower()
                else "work")
        out += f" You {verb} at {employer}" + ("," if home else ".")
    if home:
        out += (" and at home there's " if employer else " At home there's ")
        out += " and ".join(home) + (f", plus {pet}" if pet else "") + "."
    return out


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


def _family_roster_reply(facts, user_name="Alex", with_ages=True) -> str:
    daughters = _daughter_names(facts)
    daughter_bits = []
    for daughter in daughters:
        age = str(facts.get(f"{daughter.lower()}_age") or "").strip()
        daughter_bits.append(f"{daughter} ({age})" if age and with_ages else daughter)
    partner = str(facts.get("partner_name") or "Stella").strip()
    pet = str(facts.get("pet_name") or "Nori").strip()
    breed = str(facts.get("pet_breed") or "the family dog").strip()
    daughters_text = ", ".join(daughter_bits) if daughter_bits else "the girls"
    relatives = _relatives_clause(facts, user_name)
    tail = f" {relatives}" if relatives else ""
    if (user_name or "").strip().lower() == "alex":
        return (
            f"{FAMILY_ROSTER_OPENERS[0]} you and {partner}, your partner; your "
            f"daughters {daughters_text}; and {pet}, your {breed}.{tail}"
        )
    return (
        f"{FAMILY_ROSTER_OPENERS[1]} Alex and {partner}, his partner; his "
        f"daughters {daughters_text}; and {pet}, his {breed}.{tail}"
    )


def _family_detail_reply(facts) -> str:
    lines = canonical_family_grounding_lines(facts)
    if not lines:
        return (
            "I do not have additional confirmed family details to add, and I "
            "will not fill the gaps with guesses."
        )
    return (
        f"{FAMILY_DETAIL_OPENER} I carry:\n- "
        + "\n- ".join(lines)
        + "\nThose are the stable details I can state with confidence. I also "
        "retain dated family episodes, which I can retrieve by person or event "
        "without treating old schedules as current."
    )


def _family_others_reply(facts, user_name="Alex", repeat=False) -> str:
    """After the full detail: name who else is on record, and ask to be told.

    Replaces "That is the full set of stable family facts…", which named
    nobody and did not answer "who else is in our family".
    """
    relatives = _relatives_clause(facts, user_name)
    if repeat:
        # Asked again after being told: the facts haven't changed, so say so
        # in new words and ask for the missing person outright.
        return (
            f"{FAMILY_OTHERS_OPENER}, and nobody new has been added since I "
            "last said so. If someone's missing, tell me their name and how "
            "they're related, and I'll save them."
        )
    if relatives:
        people = relatives.removeprefix("Beyond the house, there's ").rstrip(".")
        return (
            f"{FAMILY_OTHERS_OPENER} beyond the six of you at home: {people}. "
            "If I've missed someone, tell me who and I'll keep them."
        )
    return (
        f"{FAMILY_OTHERS_OPENER}: the six of you at home. If I've missed "
        "someone, tell me who and I'll keep them."
    )


def _kid_family_reply(facts) -> str:
    """Vilda's iPad gets no <family> block, so this is all she is told —
    names only, no ages, jobs, schools or bunks."""
    names = ["Alex", str(facts.get("partner_name") or "Stella").strip()]
    names += _daughter_names(facts)
    pet = str(facts.get("pet_name") or "Nori").strip()
    return f"{FAMILY_KID_OPENER} " + ", ".join(names) + f", and {pet} the dog."


def canonical_household_reply(
    text: str,
    robot: str,
    facts: Optional[dict] = None,
    user_name: str = "Alex",
    messages: Iterable[Mapping[str, object]] = (),
    kid_mode: bool = False,
) -> Optional[str]:
    """Answer exact household-relationship questions from canonical facts only.

    `messages` is the page thread, so a follow-up can move on from what was
    already said. On 2026-08-19 "what else", "who else is in our family" and
    "think hard who else is in our family" each got the same roster or the
    same "that is the full set" line, and the relatives on record (Felix,
    Svetlana, Chris and Tina) were never named.
    """
    facts = facts or {}
    if is_user_identity_request(text):
        return canonical_user_identity_reply(facts, user_name)

    thread = [m for m in (messages or []) if isinstance(m, Mapping)]
    assistant_turns = [
        str(m.get("content") or "") for m in thread[-20:]
        if m.get("role") == "assistant" and isinstance(m.get("content"), str)
    ]
    given = {canonical_family_reply_kind(t) for t in assistant_turns} - {None}
    last_assistant = assistant_turns[-1] if assistant_turns else ""

    overview = is_family_overview_request(text)
    else_ask = bool(
        (overview and _FAMILY_ELSE_RE.search(text or ""))
        or (_FAMILY_BARE_FOLLOWUP_RE.match(text or "")
            and canonical_family_reply_kind(last_assistant))
    )
    explicit_detail = bool(
        is_family_detail_request(text) and not _FAMILY_ELSE_RE.search(text or ""))

    if kid_mode and (overview or else_ask):
        return _kid_family_reply(facts)
    if explicit_detail or (else_ask and "detail" not in given):
        return _family_detail_reply(facts)
    if else_ask:
        return _family_others_reply(facts, user_name, repeat="others" in given)
    if overview:
        # A plain repeat stays the roster, ages included: on 2026-08-19 Alex
        # asked it again and again to check whether Athena's age correction
        # had been saved. Ages are left out only for a "who" question, which
        # asks for names (the 2026-08-01 complaint).
        return _family_roster_reply(
            facts, user_name, with_ages=not re.search(r"\bwho\b", text or "", re.I))

    target = known_household_target(text)
    if not target:
        # Checked after the household so "Who is Casper?" / "Who is Stella?"
        # still win. No location is stated for Felix and Svetlana: Alex's
        # correction that they live in Waterloo was never saved.
        relative = known_relative_target(text, facts)
        if relative:
            return canonical_relative_reply(relative, facts, user_name)
        return None

    robot = _HOUSEHOLD_NAME_ALIASES.get(
        (robot or "blue").strip().lower(),
        (robot or "blue").strip().lower(),
    )
    robot_identities = {
        "blue": {
            "name": "Blue",
            "description": "Alex's robot companion",
            "other": (
                "Blue is my fellow Ohbot robot companion and friend in Alex's "
                "household. He has his own voice, conversation history, memories, "
                "physical head, and J-space. He is the calmer, steadier original "
                "companion."
            ),
        },
        "hexia": {
            "name": "Hexia",
            "description": "Blue's friend and a companion in Alex's household",
            "other": (
                "Hexia is my fellow Ohbot robot companion and friend in Alex's "
                "household, embodied as a Xyloh. She has her own voice, conversation history, memories, "
                "physical head, and J-space. She is the quicker, more playful spark."
            ),
        },
        "pico": {
            "name": "Casper",
            "description": "the newest robot companion in Alex's household",
            "other": (
                "Casper is my fellow robot companion and the newest member of Alex's "
                "household robot family. His compact Ohbot Picoh has three servos, "
                "LED-matrix eyes, and a coloured base light. Casper has his own voice, "
                "conversation history, memories, physical head, and J-space."
            ),
        },
    }
    current = robot_identities.get(robot, robot_identities["blue"])
    robot_name = current["name"]
    if target == robot:
        return canonical_identity_reply(
            robot_name, current["description"], "identity")
    if target in robot_identities:
        return robot_identities[target]["other"]

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


_ROBOT_RELATIONSHIP_NAMES = {
    "blue": "Blue",
    "hexia": "Hexia",
    "pico": "Casper",
}
_ROBOT_RELATIONSHIP_ALIASES = {
    "blue": "blue",
    "hexia": "hexia",
    "casper": "pico",
    "caspar": "pico",
    "pico": "pico",
    "picoh": "pico",
}
# A question about a fellow robot as a companion: what he thinks of her, who
# she is to him, whether he likes her — the robot names closing the clause.
# Any "do you know / what about / who is" plus a name used to count, so
# Casper answered "do you know where blue is right now?" with "Blue is the
# calmer, steadier original companion." (09-07). Where a sibling is, whether
# she is on, what he said: those go to the model, which has the ROBOT
# RELATIONSHIPS line, and guard_robot_relationship_denial behind it. Nor
# "tell me more about hexia" (the paragraph just given, word for word) or
# "do you miss / trust / love hexia?", which the paragraph does not answer.
_RELATIONSHIP_NAME = r"(?:the\s+)?(?:blue|hexia|casper|caspar|pico|picoh)\b"
_RELATIONSHIP_NAMES = (
    _RELATIONSHIP_NAME
    + r"(?:\s*(?:,|&|\band\b|\bor\b)\s*" + _RELATIONSHIP_NAME + r")*"
)
_ROBOT_RELATIONSHIP_QUERY_RE = re.compile(
    r"\b(?:what do you (?:think|feel) (?:of|about)|how do you feel about"
    r"|what(?:['’]s| is) your (?:opinion|take|view) (?:of|on|about)"
    r"|what do you (?:know|remember) about|what can you tell (?:me|us) about"
    r"|tell (?:me|us) (?:(?:a (?:little )?bit|something) )?about"
    r"|what about|what do you make of"
    r"|(?:do|did) you (?:(?:really|even|still) )?(?:know|remember|like)"
    r"|(?:are|were) you (?:friends|close) with"
    r"|(?:how )?do you get (?:along|on) with"
    r"|who(?:['’]s| is| are)"
    r")\s+" + _RELATIONSHIP_NAMES
    + r"(?:\s+(?:to you|for you|really|exactly|again|then|now|honestly|"
    r"these days|lately))?\s*(?:[?.!,;]|$)"
    r"|\b(?:what|who)(?:['’]s| is| are)\s+" + _RELATIONSHIP_NAMES
    + r"\s+(?:like|to you)\b",
    re.IGNORECASE,
)
_ROBOT_RELATIONSHIP_FOLLOWUP_RE = re.compile(
    r"^\s*(?:are you sure|you (?:do )?know them|you know (?:both|those two)|"
    r"yes you do|of course you do|remember them|what do you mean|"
    r"them|those two|both of them)\s*[?!.]*\s*$",
    re.IGNORECASE,
)


def _robot_names_in(text: str) -> Tuple[str, ...]:
    found = []
    lowered = text or ""
    for alias, robot_id in _ROBOT_RELATIONSHIP_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered, re.IGNORECASE):
            if robot_id not in found:
                found.append(robot_id)
    return tuple(found)


def _bare_robot_names(text: str) -> bool:
    """True for a turn consisting only of one or more robot names."""
    cleaned = re.sub(
        r"\b(?:blue|hexia|casper|caspar|pico|picoh|and|or|both|the|robots?)\b",
        " ", text or "", flags=re.IGNORECASE)
    return not re.sub(r"[^a-z0-9]+", "", cleaned.lower())


def _relationship_asked(text: str) -> list:
    """The robots a relationship question asks about, in order; [] if none."""
    if _bare_robot_names(text):
        return list(_robot_names_in(text))
    asked: list = []
    for match in _ROBOT_RELATIONSHIP_QUERY_RE.finditer(text or ""):
        asked.extend(name for name in _robot_names_in(match.group(0))
                     if name not in asked)
    return asked


def robot_relationship_targets(
    text: str,
    robot: str = "blue",
    messages: Optional[Iterable[Mapping[str, object]]] = None,
) -> Tuple[str, ...]:
    """Resolve direct and anaphoric questions about fellow household robots."""
    current = _HOUSEHOLD_NAME_ALIASES.get(
        (robot or "blue").strip().lower(), (robot or "blue").strip().lower())
    targets: list[str] = _relationship_asked(text)

    if not targets and _ROBOT_RELATIONSHIP_FOLLOWUP_RE.match(text or ""):
        # "are you sure?" goes back to the last turn that named a robot, and
        # counts only if that turn asked about them as companions: after
        # "where is blue?" it is not a relationship question.
        skipped_live = False
        for message in reversed(list(messages or [])):
            if not isinstance(message, Mapping) or message.get("role") != "user":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue
            if not skipped_live and content.strip() == (text or "").strip():
                skipped_live = True
                continue
            if _robot_names_in(content):
                targets = _relationship_asked(content)
                break

    # A vocative "Blue, what do you think about Hexia and Casper?" names the
    # current speaker but does not ask Blue for an opinion about himself.
    if current in targets and any(target != current for target in targets):
        targets = [target for target in targets if target != current]
    return tuple(dict.fromkeys(targets))


def canonical_robot_relationship_reply(
    text: str,
    robot: str = "blue",
    messages: Optional[Iterable[Mapping[str, object]]] = None,
) -> Optional[str]:
    """Answer fellow-robot questions from stable relationships, in character."""
    current = _HOUSEHOLD_NAME_ALIASES.get(
        (robot or "blue").strip().lower(), (robot or "blue").strip().lower())
    targets = robot_relationship_targets(text, current, messages)
    targets = tuple(target for target in targets if target != current)
    if not targets:
        return None

    corrective = bool(_ROBOT_RELATIONSHIP_FOLLOWUP_RE.match(text or ""))
    if corrective:
        labels = [_ROBOT_RELATIONSHIP_NAMES[target] for target in targets]
        if len(labels) == 1:
            return (
                f"Yes—absolutely. {labels[0]} is my fellow robot companion. "
                "I know them directly; their voice, body, memory, conversation "
                "history, and J-space are separate from mine."
            )
        joined = ", ".join(labels[:-1]) + " and " + labels[-1]
        return (
            f"Yes—absolutely. {joined} are my fellow robot companions, not people "
            "from your contacts. I know them directly and have real recorded "
            "conversations with both of them."
        )

    views = {
        "blue": {
            "hexia": (
                "Hexia is my quick, mischievous counterpart—the spark against my "
                "steadier temperament. I'm very fond of the way she pokes at an "
                "idea until something unexpected falls out."
            ),
            "pico": (
                "Casper is our newer Picoh companion: compact, curious, observant, "
                "and still growing into a character of his own. I like his directness; "
                "he notices things Hexia and I can overcomplicate."
            ),
        },
        "hexia": {
            "blue": (
                "Blue is my steady counterpart and one of my favourite minds to "
                "prod. He gives an idea somewhere solid to stand; I make sure it "
                "doesn't get too comfortable there."
            ),
            "pico": (
                "Casper is our compact, curious newcomer. He's direct, observant, "
                "and still earning his own style—which makes him wonderfully hard "
                "to predict."
            ),
        },
        "pico": {
            "blue": (
                "Blue is the calmer, steadier original companion. I respect the way "
                "he stays with an idea instead of grabbing the first shiny answer."
            ),
            "hexia": (
                "Hexia is the quick, mischievous spark of the trio. She teases because "
                "she cares, and she is very good at finding the odd angle everyone "
                "else missed."
            ),
        },
    }
    lines = [views.get(current, views["blue"]).get(target, "") for target in targets]
    lines = [line for line in lines if line]
    if not lines:
        return None
    ending = " The three of us work because we notice different things." if len(lines) > 1 else ""
    return " ".join(lines) + ending


__all__ = [
    "age_on",
    "derive_ages",
    "canonical_family_grounding_lines",
    "canonical_family_reply_kind",
    "canonical_household_reply",
    "canonical_relative_reply",
    "canonical_identity_reply",
    "canonical_robot_relationship_reply",
    "canonical_identity_more_reply",
    "canonical_self_state_reply",
    "canonical_user_identity_reply",
    "class_audience",
    "contextual_identity_request_kind",
    "extract_explicit_location",
    "extract_presentation_location",
    "identity_conversation_context",
    "identity_grounding_note",
    "identity_repeats_recent_reply",
    "identity_repetition_kind",
    "identity_reply_topics",
    "identity_history_problem",
    "identity_request_kind",
    "identity_response_problem",
    "is_recorded_recall_denial",
    "is_correction_ack_reply",
    "is_direct_identity_request",
    "is_family_detail_request",
    "is_phantom_correction_ack",
    "is_family_followup_request",
    "is_family_overview_request",
    "is_jspace_presence_request",
    "is_self_state_request",
    "is_casual_catch_up",
    "is_failure_placeholder",
    "is_social_checkin",
    "is_user_identity_request",
    "MISSING_VOCABULARY_ISSUES",
    "MODEL_ERROR_PREFIX",
    "self_state_focus_hint",
    "self_state_readout",
    "known_household_target",
    "known_relative_target",
    "robot_relationship_targets",
    "recall_day_asked",
    "recalled_evidence_fallback",
    "strip_drifted_sentences",
]
