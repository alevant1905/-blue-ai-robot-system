"""How long Blue's visible reply may be: the length follows the user's turn.

A short message got an essay. Live after 09-27 the median chat reply was 196
words, and 21 of 29 turns without an attachment ran over 100 ("Is autoGPT a
type of harness" -> 253 words). On the 10-05 harness 20 of 98 turns of
twelve words or fewer got more than 100 words, every one of them a turn that
thought first, up to 618.

So a message of twelve words or fewer that asks for nothing long gets a cap on
the visible reply — about 220 tokens typed, 120 spoken — and a typed question
gets SHORT_TURN_NOTE beside the user's words. Asking for length in so many
words lifts both: a document, a list, a draft, a plan, a report, a story,
an analysis, "explain in detail", "go on", "tell me more", "keep going",
"what were those ideas?". So does a go-ahead for something he just offered
("Yeah, okay." after "Want me to paste the full transcript?"): its answer
is the work. Missing a cue only brings back the uncapped reply of before;
a cue missed the other way cuts the work off, so the cues are wide.
The cap is on the words he says; the reasoning allowance
(thinking.THINKING_ALLOWANCE_TOKENS) is added on top of it when the turn
thinks, and the words themselves are then held to it as they arrive
(bluetools.call_lm_studio).

The cap alone would cut those essays off mid-thought; the note is what makes
the model write a short answer that fits. It does not offer to go deeper:
asked to ("offer to go deeper in one clause if there's more"), one reply in
four closed on "If you want, I can…" or "Happy to go deeper…" — against
ENDINGS — and the lengths were the same without it ("what could go wrong?"
116-166 words with the offer, 133-146 without). "go on" lifts the cap.

Pure text in, a number out — no bluetools import.
"""

from __future__ import annotations

import re
from typing import Optional

from blue.server import thinking as _thinking

# Messages of this many words or fewer get a short reply, as for thinking's
# short replies (thinking.SHORT_REPLY_WORDS).
SHORT_TURN_WORDS = 12
# The visible reply's cap, in tokens: about 170 words typed (five sentences
# with room to finish the last one) and 90 spoken (SPOKEN REPLY asks for one
# or two sentences).
TYPED_REPLY_TOKENS = 220
SPOKEN_REPLY_TOKENS = 120
# Characters of visible reply per token on qwen3.8-27b: the median over 209
# harness replies on 10-05 (p10 3.6, p90 4.7). A thinking turn's reasoning
# shares max_tokens with the reply, so its cap is counted in characters.
CHARS_PER_TOKEN = 4.3

# Beside the user's words in the live turn (see short_turn_note). Replayed on
# qwen3.8-27b over the 10-05 harness payloads, n=3 a turn: as one more line at
# the end of STYLE, three wordings changed nothing — "what could go wrong?"
# in the topic_development thread got 205-408 words in 9 replays of 9 (391,
# 266 and 189 in the runs). Pinned in the turn, "…about 100 words, as plain
# paragraphs." gave 116-166 words, each a finished answer, and 78-151 words
# over six other turns that had run to 95-398 ("would you do it
# differently?" 392, 398, 226 -> 83-97). Without "as plain paragraphs" one
# reply in three was a bulleted list of 340 words. "about 100 words" is a
# target a one-line answer can be padded to, so the note gives a ceiling:
# "where are you right now?" stayed at 28-47 words (24-39 before).
SHORT_TURN_NOTE = ("A short message: answer it in at most five sentences and "
                   "under 100 words, as plain paragraphs.")

# Something whose length is the point, asked for by name.
_ARTIFACT_RE = re.compile(
    r"\b(?:documents?|essays?|reports?|letters?|memos?|articles?|summary|summaries"
    r"|outlines?|drafts?|lists?|syllabus|syllabi|rubrics?|agendas?|itinerary"
    r"|scripts?|story|stories|poems?|lyrics|speech|recipes?|quiz(?:zes)?"
    r"|worksheets?|handouts?|slides?|presentations?|bibliography|proposals?"
    r"|cover letter|resume|cv|timeline|overview|breakdown|transcripts?"
    r"|instructions|pros and cons|step[- ]by[- ]step|walkthrough"
    # a day's or a week's events are a list
    r"|schedule|calendar|timetable)\b"
    # a plan as a thing, not "I plan to"
    r"|\b(?:a|the|my|your|our|his|her|lesson|study|course|teaching|weekly"
    r"|daily|game|action|project|lecture) plans?\b|\bplan (?:out|for|my|the|a)\b")
# Writing it is the reply: "write me…", "summarise the chapter", "list them".
_WRITE_RE = re.compile(
    r"\b(?:write|rewrite|draft|compose|translate|summari[sz]e|outline"
    r"|transcribe|proofread|brainstorm|enumerate|list|itemi[sz]e|tabulate"
    r"|paraphrase)\b")
# Depth asked for in so many words.
_DEPTH_RE = re.compile(
    r"\bin (?:more |much more |great |full |greater |real )?(?:detail|depth)\b"
    r"|\b(?:detailed|thorough(?:ly)?|exhaustive|comprehensive|at length|in full)\b"
    r"|\bexplain (?:it |this |that )?fully\b"
    r"|\b(?:go|dig|dive) deeper\b|\bdeep[- ]dive\b"
    r"|\blong(?:er)? (?:version|answer|explanation|reply)\b"
    r"|\bfull (?:version|story|list|text|details?|explanation|answer|picture|rundown)\b"
    r"|\bthe whole (?:thing|story|list|text|document|picture|paper|chapter)\b"
    r"|\btell (?:me|us) (?:everything|all about)\b|\beverything (?:about|you know)\b"
    r"|\bwalk (?:me|us|them|him|her) through\b"
    r"|\bgo (?:over|through) (?:it|this|that|them|the|each|all|every)\b"
    r"|\bbreak (?:it|this|that|them) down\b|\bspell (?:it|this|that) out\b"
    r"|\b(?:tell|say|show|explain|give) (?:me |us )?(?:a (?:bit|little) |some )?more\b"
    r"|\bmore (?:about|on|detail|details)\b|\belaborate\b|\bexpand\b"
    r"|\bkeep going\b|\b(?:please |ok(?:ay)? |so |and )?go on[\s.!?]*$"
    r"|\bcontinue (?:with|the|it|that|where|from)\b|\bwhat else\b"
    r"|\bfinish (?:it|that|this|the)\b"
    # "yes a longer one" after "If you'd like the longer academic version…"
    # (conversation_log 5838, a 2,671-character reply).
    r"|\b(?:longer|fuller|complete|extended|expanded|unabridged) (?:one|version"
    r"|answer|explanation|reply|account)\b"
    # "explain this further by distinguishing between dialectical and formal
    # logic" (6046).
    r"|\b(?:explain|discuss|elaborate|develop|unpack|explore|expand|take|push)\b"
    r"[^.?!]{0,40}\bfurther\b|\b(?:go|dig|look) further\b")
# An analysis asked for, as in the real log: "I want u to analyze his
# encyclical and assess it" (3214, a 4,617-character reply), "discuss the blue
# project in relation to sofie lachapelle's book" (5198), "Deepen the analysis
# using Alex's published work" (5208), "revise your analysis of the
# similarities between them now" (5202). The verbs, not their nouns: "what's
# your assessment of the bill?" and "what you guys discussed" stay short, as
# does "her critique of ai".
_ANALYSIS_RE = re.compile(
    r"\b(?:analy[sz]e|assess|evaluate|critique|deepen|revise|discuss)\b(?! of\b)"
    r"|\banalys[ie]s\b")
# "give me 5 examples", "three ideas": a count of things.
_COUNT_RE = re.compile(
    r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|fifteen|twenty)\s+(?:\w+\s+)?(?:ideas|examples|ways|reasons|questions"
    r"|tips|options|steps|things|points|suggestions|titles|books|papers"
    r"|articles|activities|exercises|prompts|names|topics|sources|readings"
    r"|recommendations|paragraphs|sentences|pages|bullets|bullet points"
    r"|words|lines|items)\b")
# Recall of something long he said: "what were those ideas?", "what were the
# lab ideas you gave me last night?" (<earlier_answers> must come back whole).
_RECALL_RE = re.compile(
    r"\b(?:you|we) (?:gave|told|said|suggested|mentioned|wrote|listed"
    r"|recommended|came up with|talked about|discussed|went over|covered"
    r"|decided|planned|agreed on)\b"
    r"|\bdid (?:you|we) (?:say|tell|suggest|write|recommend|mention|talk|discuss"
    r"|decide|come up|list|give|cover|go over)\b"
    r"|\bremind me (?:what|of|about|how|why|where|when|who)\b"
    r"|\b(?:those|these|the|your|that) (?:ideas|suggestions|examples|options"
    r"|points|tips|steps|recommendations|names|questions|reasons|readings)\b")
# Reading something out: the text is the reply.
_READ_RE = re.compile(
    r"\bread (?:me|us|it|that|this|the|them|out|aloud|back|him|her)\b")
# "can you continue?", "could you go on with that?": the "more" cue asked
# politely (thinking._CONTINUE_RE is anchored on the verb). Only its verbs:
# "would you do it differently?" asks something new.
_POLITE_MORE_RE = re.compile(
    r"^(?:can|could|would|will) (?:you|u) (?:please )?(?:continue|go on"
    r"|keep going|keep talking|carry on|elaborate|expand|go deeper"
    r"|tell (?:me|us) more|say more)\b")

# Something Blue offered at the end of his last reply: "Want me to do
# that?", "Would you like me to: 1. … 2. …", "Would you like to dive into the
# syllabus…?", "If you want, I can pull the changelog…", "If you'd like the
# longer academic version…, I've got that documented too."
_OFFER_TAIL_CHARS = 600
_OFFER_RE = re.compile(
    r"\b(?:want me to|shall i|should i|would you like(?: me)? to|like me to"
    r"|would you like (?:the|a|an|it|that|them|those|my|more)\b"
    r"|(?:do|would) you want (?:to|the|a|an|it|that|them|those|my|more)\b"
    r"|would it help (?:if i|to)|let me know if you(?:'d| would)? (?:like|want)"
    r"|(?:happy|glad) to\b[^.?!]{0,80}\bif you"
    r"|i (?:can|could)(?: also)? [^.?!]{0,80}\bif you(?:'d| would)? (?:like|want|prefer)"
    r"|if you(?:'d| would)? (?:like|want|prefer)\b[^.?!]{0,100}"
    r"\b(?:i can|i could|i'll|i will|i'?ve got|i have|happy to))\b")
# An open question is no offer: "What would you like to do?", "Is there
# anything else you'd like me to adjust?".
_OPEN_QUESTION_RE = re.compile(
    r"\b(?:what|how|where|which|anything|something)\b[^.?!]{0,40}"
    r"\b(?:you'd|you would|would you|do you|you) (?:like|want)\b[^.?!]*")
# A numbered menu: two items or more.
_MENU_ITEM_RE = re.compile(r"(?m)^[ \t]*(?:\*\*)?\d{1,2}[.)]\s")
# Picking from it: "1", "the first one", "option 2", "1 and 3", "both".
_PICK_WORD = (r"(?:\d{1,2}|one|two|three|four|five|six|first|second|third"
              r"|fourth|fifth|sixth|last)")
_PICK_RE = re.compile(
    r"^(?:(?:let'?s |i'?ll |we'?ll )?(?:do|go with|take|try|pick|choose) )?"
    r"(?:the )?(?:option |number |no\.? ?|#)?(?:" + _PICK_WORD +
    r"|both|all(?: of them| three| four)?)(?: one| option| please| then)?"
    r"(?:[\s,&+]+(?:and )?(?:the )?" + _PICK_WORD + r"(?: one)?)*[\s.!]*$")
# A go-ahead is a few words: "Yeah, okay.", "Yeah sure do that.", "Let's go.",
# "Surely", "1", "yes a longer one", "Yeah that's the one, send it.".
ACCEPT_WORDS = 6
_GO_AHEAD_RE = re.compile(
    r"^(?:yes|yeah|yea|yep|yup|ya|ye|y|sure(?:ly)?|ok(?:ay)?|k|alright|all right"
    r"|absolutely|definitely|certainly|of course|by all means|please|why not"
    r"|go ahead|go for it|do it|do that|do so|sounds (?:good|great)"
    r"|that (?:one|works|would be (?:great|nice|good|helpful))"
    r"|i'?d (?:like|love) (?:that|it|to)|let'?s (?:do it|do that|do this|go"
    r"|see it|hear it|try it|have it|start|begin|get started|dive in))\b")
# Without a yes, a few words that take it up: "Lift the focus" after "…say
# the word and I'll switch to the full library" (6236, a 7,604-character
# reply), "weekly hands on build" after "…as a weekly hands-on build, or as a
# single capstone…?" (9063).
TAKE_UP_WORDS = 4
# ...that neither turns the offer down nor asks something new.
_DECLINE_RE = re.compile(
    r"^(?:(?:ok(?:ay)?|oh|ah|hm+|well|cool|great|nice|fine|alright|all right)"
    r"[\s,.!]+)*(?:(?:no|nah|nope|not|never ?mind|nvm|later|skip|stop|pass"
    r"|don'?t|do not|maybe (?:later|not|another time|tomorrow)|another time"
    r"|i'?m (?:good|ok(?:ay)?|fine|all set)|that'?s (?:ok(?:ay)?|fine|alright"
    r"|all right|enough|all)|all good|forget (?:it|about it)|i'?ll pass"
    r"|leave it|bye|good ?night)\b"
    r"|(?:thanks?|thank you|thx|ty)(?: you)?(?: anyway| though| so much)?"
    r"[\s,.!]*$)"
    r"|\b(?:no need|not now|not yet|not today|no thanks|don'?t (?:need|want|bother))\b")
# Thanks without a yes closes the exchange: "Okay sounds good thanks",
# "Great job, thanks.", "Thank you very much." With one it does not:
# "yes thanks", "thanks, go ahead".
_THANKS_RE = re.compile(r"\b(?:thanks?|thank you|thx|ty)\b")
_YES_RE = re.compile(r"\b(?:yes|yeah|yea|yep|yup|ya|please|sure|go ahead|do it"
                     r"|do that)\b")
_NEW_QUESTION_RE = re.compile(r"\?|\b(?:what|who|whom|when|where|why|how|which)\b")
_WHY_NOT_RE = re.compile(r"^why not\b[\s?!.]*$")
# A statement opens on its subject or a filler: "You keep repeating
# yourself.", "We already had lunch", "its there now", "Well, I mean...".
_STATEMENT_START_RE = re.compile(
    r"^(?:i|i'm|im|i've|i'd|i'll|you|u|you're|youre|we|we're|it|it's|its|they"
    r"|he|she|this|that|that's|thats|there|here|my|our|so|and|but|well|oh|ah"
    r"|hey|wow|woh|jesus)\b")


def asks_for_length(text: str) -> bool:
    """Does the message ask for something long — a document, a list, depth,
    an analysis, more of the last answer, or the recall of a long one?"""
    t = _thinking._normalise(text)
    if not t:
        return False
    bare = _thinking._FILLER_PREFIX_RE.sub(
        "", _thinking._GREETING_PREFIX_RE.sub(
            "", _thinking._LEADING_NAME_RE.sub("", t))).strip()
    if (_thinking._CONTINUE_RE.match(bare) or _POLITE_MORE_RE.match(bare)
            or _thinking._AGAIN_RE.search(t)):
        return True
    return any(rx.search(t) for rx in (
        _ARTIFACT_RE, _WRITE_RE, _DEPTH_RE, _ANALYSIS_RE, _COUNT_RE,
        _RECALL_RE, _READ_RE))


def accepts_offer(text: str, prev_reply: str = "") -> bool:
    """A go-ahead for something Blue just offered, whose answer is the work
    itself: "Yeah, okay." after "…I can paste the full transcript here… Want
    me to do that?" (conversation_log 5544, a 7,595-character reply), "1"
    after a numbered menu (5356), "Surely" after "If you want, I can pull the
    changelog…" (10063).

    Wider than thinking.offer_accepted, which sizes the reasoning: there a
    miss only means no thinking, here it cut the work to 220 tokens. After an
    offer, a few words that neither decline it nor ask something new: a yes
    of any kind, a pick, or a short take-up that is not a statement, an
    acknowledgement, a correction, a check-in or a request of its own
    ("That's incorrect.", "Can you hear me OK.", "introduce yourself to the
    class" stay capped). After a numbered list with no offer, a pick of one
    of its items."""
    if _thinking.offer_accepted(text, prev_reply):
        return True
    tail = (prev_reply or "")[-_OFFER_TAIL_CHARS:]
    t = _thinking._bare(text)
    words = t.split()
    if not tail.strip() or not words or len(words) > ACCEPT_WORDS:
        return False
    if _DECLINE_RE.search(t) or (_THANKS_RE.search(t) and not _YES_RE.search(t)):
        return False
    if _NEW_QUESTION_RE.search(t) and not _WHY_NOT_RE.match(t):
        return False
    offers = list(_OFFER_RE.finditer(
        _OPEN_QUESTION_RE.sub(" ", _thinking._normalise(tail))))
    if _PICK_RE.match(t):
        return bool(offers) or len(_MENU_ITEM_RE.findall(tail)) >= 2
    if not offers:
        return False
    if _GO_AHEAD_RE.match(t):
        return True
    if (len(words) > TAKE_UP_WORDS or _STATEMENT_START_RE.match(t)
            or _thinking._ACK_RE.match(t) or _thinking._CORRECTION_RE.search(t)
            or _thinking._CHECKIN_RE.match(t)
            or _thinking._QUESTION_START_RE.match(t)):
        return False
    # A request of its own, unless it names what was offered: "search again"
    # after "Would you like me to search for…?".
    if _thinking._REQUEST_START_RE.match(t):
        offer = offers[-1]
        sentence = re.split(r"[.?!]", offer.string[offer.start():], maxsplit=1)[0]
        return words[0] in re.findall(r"[a-z']+", sentence)
    return True


def reply_budget(text: str, *, voice: bool = False,
                 has_attachment: bool = False,
                 depth_cue: bool = False,
                 prev_reply: str = "") -> Optional[int]:
    """The visible reply's cap in tokens for this turn, or None for no cap.

    `text` is the user's own words (attachments stripped). `voice` means the
    reply will be spoken. `has_attachment` covers a document, a long paste or
    an image. `depth_cue` is the caller's own sign that length is wanted (the
    chat page's "more" continuation cue). `prev_reply` is Blue's previous
    reply: a go-ahead for what it offered is not capped (accepts_offer).
    Missing a cue only brings back the uncapped reply of before.
    """
    if has_attachment or depth_cue:
        return None
    t = _thinking._normalise(text)
    if not t or len(t.split()) > SHORT_TURN_WORDS:
        return None
    if _thinking._URL_RE.search(t) or asks_for_length(t):
        return None
    if accepts_offer(text, prev_reply):
        return None
    return SPOKEN_REPLY_TOKENS if voice else TYPED_REPLY_TOKENS


def short_turn_note(text: str, *, voice: bool = False, kid: bool = False,
                    thinking: Optional[str] = None) -> str:
    """SHORT_TURN_NOTE for a capped turn that needs it, else "".

    Only where the long replies were: a typed question or request the turn
    thinks about (all 20 of the 10-05 harness's were). A greeting, an
    acknowledgement or a correction is short already, and a size in the
    note could pad it ("hi blue" got 27-40 words with one, 12-15 in the
    runs). Spoken turns have SPOKEN REPLY, and the kids' page its own STYLE.
    """
    if voice or kid or thinking != _thinking.THINK_ON:
        return ""
    return SHORT_TURN_NOTE if _thinking.asks_something(text) else ""


def visible_chars(cap_tokens: int) -> int:
    """The cap in characters of visible reply."""
    return int(cap_tokens * CHARS_PER_TOKEN)
