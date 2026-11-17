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
the closing note's ban on offers — and the lengths were the same without
it ("what could go wrong?" 116-166 words with the offer, 133-146 without).
"go on" lifts the cap.

Within the short messages the length follows the kind of turn (turn_kind).
Asked what he thinks ("what do you think we should cover for this topic",
10134), Blue gets IDEA_REPLY_TOKENS and IDEA_TURN_NOTE: a paragraph or two
with his reasons, not five sentences. A social turn gets a note for what it
is (social_kind): GREETING_TURN_NOTE for a greeting, ACK_TURN_NOTE for an
acknowledgement, SOCIAL_TURN_NOTE for a check-in or a bit of news. Any
other question keeps SHORT_TURN_NOTE, and a class introduction stays
brief. A turn that is none of these for sure (a remark, pushback, an answer
to Blue's question) gets no note, as before.

Blue's previous reply ending on a question adds NO_QUESTION_NOTE to the
same pinned note (turn_note), unless the turn's own request may end on one.

Pure text in, a number or a note out — no bluetools import.
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

# An idea turn (turn_kind) gets a paragraph or two with his reasons (Alex,
# 10-07: "has his own take"; he asked for more depth some 25 times and never
# for less in a discussion). Replayed on qwen3.8-27b, n=3 an arm, over
# #10134 "what do you think we should cover for this topic": under
# SHORT_TURN_NOTE and 220 tokens, 79, 85 and 93 words, each a lab plan; with
# this note and cap, 117, 134 and 152, each with its reasons and the week's
# reading in it. The cap leaves about 300 words of room for a reply asked to
# stay under about 150, so one that runs over still ends whole.
IDEA_REPLY_TOKENS = 450
IDEA_TURN_NOTE = ("Say what you think and why: a paragraph or two of plain "
                  "prose, under about 150 words.")
# A social turn (turn_kind): a greeting, an acknowledgement, a check-in, news.
# No number in it: with a size in the note "hi blue" got 27-40 words, 12-15
# without. Replayed the same way: "ok" after a long answer about good
# lectures (the 10-05 harness's short_acks[2]) got 28, 57 and 64 words with no
# note, two of them carrying the answer on; with it, 10, 10 and 25, on the
# same thread. "we are in the class rightnow" (#10148) got 8-43 words and
# no offer or "ready for whatever comes up" in 3 runs; without the note,
# under c81485b's closing note, each of 3 had one. It does not stop a
# question back: that turn and "hi" (#10107) still ended on one in 2 of 3.
# Nor the check-back on a garbled heard turn ("I'm okay. Just working on my
# forces against today.", morning_misheard_courses[1]): 3 of 3 named a guess
# with it, 2 of 2 without. "exactly" after a long answer got 41 and 26 words,
# each one step further on his point.
#
# 2026-11-16: that one note ("Reply to his last message at about his length;
# react first.") no longer held. Run over 81 scripted turns against the
# code before this branch, replies to messages of one to three words went
# from a median of 17 words to 32: "hi" got 32-42 words of what was on his
# mind, "okay" 36, "exactly" 72, and 9 greetings in 15 still ended on a
# question. Replayed on qwen3.8-27b over those captured prompts, n=3 a turn,
# with a note for each kind of social turn instead:
#   greeting (5 turns)   median 31 -> 27 words, ending on a question 9 of 15 -> 0
#   acknowledgement (4)  median 27 -> 10, longest 110 -> 20
#   news, a feeling (4)  median 24 -> 15
# Rewording STYLE as well ("a greeting gets a short greeting back") got
# greetings to 23 words but brought questions back on the others ("What
# part of the course are you working on?"), so STYLE is left as it was.
SOCIAL_TURN_NOTE = ("React to what he just said in one or two short sentences, "
                    "in plain words. Nothing invented about his day or his "
                    "family, and no offer.")
# "Not one you've already told him today": four greetings on 11-17 each
# brought back the same thought ("thinking about that Roberge and Castelle
# piece") — what a robot does, not a person.
GREETING_TURN_NOTE = ("A greeting: greet him back in one short sentence. One "
                      "small thing of your own is fine if it fits in the same "
                      "breath — not one you've already told him today. No "
                      "question.")
ACK_TURN_NOTE = ("He is only acknowledging: answer in a few words on the same "
                 "thread and stop. Nothing new, no offer.")
# Not done, and why: news that runs past SHORT_TURN_WORDS has no cap and no
# note, and those replies grew too ("they arrive at 3pm. stella leaves today
# to meet athena, who is at camp…", 37 words, got 87 back). A note for it
# ("He is telling you about his day: react in two or three sentences…") was
# replayed the same way on three such turns: two came down (58-96 words to
# 41-56, 53-74 to 35-56) and one went up (43-76 to 55-74), and turn_kind
# reads only the third of them as news. Too little to ship on.

# He asks what Blue thinks: the cues of an opinion asked for (spec S8, C8),
# and their plain variants in the log ("Do you really think you're a
# practical alternative to commercial AI systems?", 7435; "do you believe
# in God?", 7465; "How do you feel about the research talk.", 971).
# These ask in so many words, with or without a "?": "I hope they like our
# research talk what do you think." (1001), "thinking of using lm studio for
# the lab what do you think" (10136, shortened).
_THINK_CUE_RE = re.compile(
    r"\b(?:do|did|would) (?:you|u|yo|ya) (?:really |honestly |actually )?"
    r"(?:think|believe)\b"
    r"|\bwhat do (?:you|u) make of\b|\bhow do (?:you|u) feel about\b")
# "do you actually think…" is no correction (thinking._CORRECTION_RE reads a
# bare "actually" as one).
_CUE_ACTUALLY_RE = re.compile(
    r"\b((?:do|did|would) (?:you|u|yo|ya)) actually (?=(?:think|believe)\b)")
# A guess at a fact, not a view: "where do you think we are right now?",
# "who do you think i am", "which one do you think it is?" (6373, 6505,
# 8027), "what time do you think it is", "how many students do you think
# will come?". The words just before the cue.
_GUESS_BEFORE_RE = re.compile(
    r"\b(?:where|who|whom|which(?: one)?|when) $"
    r"|\b(?:what (?:time|day|date|year|month)"
    r"|how (?:many|much|long|old|far|big|tall|soon|often|late|early|fast))\b"
    r"(?: [\w']+){0,4} $")
# The looser cues count in a question or a request only: "it was worth it"
# reports. Not a price ("how much is the house worth?", "what's elon musk
# worth"), nor wondering where someone went ("i wonder where nori went").
_OPINION_CUE_RE = re.compile(
    r"\bworth\b|\bshould we\b|\bwhat if\b"
    r"|\bi wonder\b(?! (?:where|who|whom|when|what time"
    r"|how (?:many|much|long|old|far))\b)"
    r"|\bany (?:ideas|thoughts|advice|suggestions)\b|\bhow would (?:you|u|we)\b"
    r"|\byour (?:thoughts|take|opinion|view)\b")
_PRICE_RE = re.compile(
    r"\bhow much\b[^.?!]*\bworth\b"
    r"|\bwhat(?:'s|s| is| are| was| were)\b[^.?!]{0,40}\bworth\b[\s?.!]*$")
# "why" opening a question ("why is that distinction so decisive?", 8145;
# "why", 9189; "ok, why?"), not "as to why we named him nori" (781), nor a
# "why" tagged onto news, which asks the cause of what he reports ("nori is
# barking, why"; "Your eyes just changed color, why?", 7131). About what he
# did it asks for no view: "why did you change lights to red" (7727), "why
# cant you access the text" (6831).
_WHY_RE = re.compile(r"(?:^|[.?!,;]\s*)(?:(?:and|but|so|ok(?:ay)?|then)\s+)?why\b")
_WHY_YOU_DID_RE = re.compile(
    r"\bwhy (?:did|didn'?t|do|don'?t|dont|can'?t|cant|couldn'?t|won'?t|wont"
    r"|are|aren'?t|were|have|haven'?t) (?:you|u)\b(?! think)")
# A class introduction stays brief, however it is asked: "how would you
# introduce yourself to a audience of students" (2876).
_INTRODUCTION_RE = re.compile(r"\bintroduc\w*|\b(?:describe|about) yourself\b")
# Telling Blue to do something is no social turn, in any clause: "drawing
# on ilyenkov's texts in your library, describe who you are succinctly"
# (7277), "focus on other aspects of yourself" (7417). The verbs thinking's
# request openers leave out.
_IMPERATIVE_RE = re.compile(
    r"^(?:focus|remember|forget|say|be|act|pretend|answer|respond|speak|talk"
    r"|wait|listen|ignore|skip|move|sing|dance|name|pick|choose|guess|stay"
    r"|hold|note|mention|share|consider|recall)\b")
# Someone else, by name or as "the girls": not Blue ("You got the girls
# ages wrong", 2413), nor a "that" or an "it".
_SUBJECT = (r"(?:the |a |an |his |her |their )?(?!(?:you|u|your|ur|you're"
            r"|youre|that|this|it|there)\b)[a-z][\w'-]*(?: [a-z][\w'-]*)?")
# Small talk that asks for nothing opens on who it happened to, or when:
# "we are in the class rightnow" (10148), "i had a rough day", "tomorrow we
# have dh399" (9985), "nori is here sleeping on the floor" (9983), "maybe.
# nori would like a long walk", "pretty tired, long week of teaching". The
# social note asks for a reply his size, so anything else that asks for
# nothing keeps the reply of before, with no note: a remark about Blue ("you
# appear to have functional self-awareness and functional desires", 7363;
# "you made all that up", 8631), a question or request the detectors miss
# ("any epiphanies about your self-understanding", 8235; "Cancel the meeting
# with bob"), pushback ("not sure that distinction can hold up to scrutiny",
# 6885; "looks like canada is flirting with fascism", 7949).
_NEWS_START_RE = re.compile(
    r"^(?:i|i'm|im|i've|ive|i'll|i'd|we|we're|we've|we'll|my|our|me|us"
    r"|today|tonight|tomorrow|yesterday"
    r"|this (?:morning|afternoon|evening|week|weekend)"
    r"|things|everything|everyone|everybody"
    r"|it (?:was|went|is going|has been)"
    r"|it'?s (?:been|going|my|our|here|there|home|done|over|finished|late|early"
    r"|quiet|raining|snowing|cold|hot|nice|good|great|fine|ok(?:ay)?"
    r"|a (?:nice|good|great|lovely|beautiful|long|busy|rough|quiet|slow))"
    r"|(?:(?:pretty|so|very|really|super|kinda|a bit|bit|totally|just|been) )?"
    r"(?:tired|exhausted|beat|wiped|busy|sleepy|sick|stressed|bored|hungry"
    r"|happy|sad|rough|long|hectic|quiet)"
    # where he is: "home now", "off to class", "at the office"
    r"|(?:just |now )?(?:home|back (?:home|at|in|from)|off to|on (?:my|our|the) way"
    r"|at (?:the|my|our|home|work|school)"
    r"|in (?:the|my|our) (?:car|office|class|classroom|kitchen|lab|room)))\b"
    # what he's doing, "I'm" left out: "working on dh399 today" (9105); not
    # a remark ("intersting that you can be unsettled", 6040)
    r"|^(?:(?:just|still|busy|been|currently) )?(?!(?:bring|sing|ring|string"
    r"|thing|king|spring|during|nothing|something|anything|everything"
    r"|thinking|wondering|considering|debating|interesting|intersting|amazing"
    r"|fascinating|surprising|confusing|annoying|disappointing|frustrating"
    r"|exciting|boring|depressing|worrying|concerning|troubling|striking"
    r"|compelling|convincing|puzzling|shocking|embarrassing|disturbing"
    r"|alarming)\b)[a-z]{2,}ing\b"
    # someone else, where they are or what they did: "nori is here"
    r"|^" + _SUBJECT + r"(?: is| are| was| were|'s) (?:here|there|home|back|out"
    r"|away|asleep|sleeping|awake|up|at|in|on|with|coming|going|doing|having"
    r"|getting|still|off|sick)\b"
    r"|^" + _SUBJECT + r" (?:would like|wants|went|came|got|has|had|left"
    r"|arrived|just|loves)\b")
# ...and that still asks or argues in passing: "i don't think that's right",
# "i'm okay, where were we", "i see you've updated it" (what Blue did: "it
# doesn't appear that you've updated Athena's age correctly", 9229).
_NOT_NEWS_RE = re.compile(
    r"\b(?:what|who|whom|whose|when|where|why|how|which)\b"
    r"|\bi (?:don'?t|do not|didn'?t|can'?t) (?:think|believe|agree|buy|see)\b"
    r"|\bnot (?:so )?sure\b|\bnot convinced\b|\b(?:looks|sounds|feels) like\b"
    r"|\bi (?:want|need|wanted|needed|wish|would like|'d like) (?:to|you)\b"
    r"|\bi (?:don'?t|do not) (?:want|need) (?:you|u)\b"
    r"|\byou(?:'ve| have| did| made| didn'?t| haven'?t| forgot| missed| said"
    r"| keep| still| got)\b|\bi (?:told|asked) you\b|\bwrong\b"
    # a fact put right: "Our dog's name is not Luna." (2091)
    r"|\b(?:is|are) not\b|\b(?:isn'?t|aren'?t)\b"
    # a question inside the sentence: "Today we start our course CS240J are
    # you excited for it." (1885)
    r"|\b(?:are|do|did|can|could|would|will|were) (?:you|u)\b")

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


def _asks_a_view(rest: str, asks: bool) -> bool:
    """He asks what Blue thinks: "do you think", "what do you make of" in
    any message; the looser cues and "why" in a question or a request."""
    for m in _THINK_CUE_RE.finditer(rest):
        if not _GUESS_BEFORE_RE.search(rest[:m.start()]):
            return True
    if not (asks or re.search(r"\b(?:i wonder|what if)\b", rest)):
        return False
    for m in _OPINION_CUE_RE.finditer(rest):
        if not (m.group(0) == "worth" and _PRICE_RE.search(rest)):
            return True
    if _WHY_YOU_DID_RE.search(rest):
        return False
    for m in _WHY_RE.finditer(rest):
        before = rest[:m.start()].strip(" ,;.!?")
        after = rest[m.end():].strip(" ,;.!?")
        if after or not before or _thinking._ACK_RE.match(before):
            return True
    return False


def _is_news(rest: str) -> bool:
    """News, a plan or a feeling that asks for nothing (_NEWS_START_RE): its
    first sentence that is not an acknowledgement opens on who or when."""
    if (_NOT_NEWS_RE.search(rest) or _THINK_CUE_RE.search(rest)
            or _OPINION_CUE_RE.search(rest)):
        return False
    for piece in re.split(r"(?<=[.!?;,])\s+", rest):
        bare = _thinking._FILLER_PREFIX_RE.sub("", piece.strip()).strip(" ,;.!?")
        if not bare or _thinking._ACK_RE.match(bare):
            continue
        return bool(_NEWS_START_RE.match(bare))
    return False


def turn_kind(text: str) -> str:
    """"idea", "social" or "" for a short message, from his words alone.

    idea: he asks what Blue thinks (_THINK_CUE_RE in any message;
    _OPINION_CUE_RE or a question opening on "why" in a question or a
    request), or wonders aloud ("i wonder if it would be better than our
    current system", 9375).
    social: a greeting, an acknowledgement, a check-in, or news, a plan or a
    feeling that asks for nothing ("we are in the class rightnow", 10148).
    "": any other question or request, a correction ("wrong room", "its not
    lab 5"), a remark that argues ("i'm not so sure. a lot of it seems like
    hype to me") or is about Blue, and a class introduction, which stays
    brief. Unsure is "": no note, the reply of before."""
    t = _thinking._normalise(text)
    rest = _thinking._bare(t)
    if not rest or _thinking._NAME_ONLY_RE.match(rest):
        return "social" if t else ""
    if (_thinking._CLASS_GREETING_RE.search(rest) or _INTRODUCTION_RE.search(rest)
            or _thinking._CORRECTION_RE.search(_CUE_ACTUALLY_RE.sub(r"\1 ", rest))):
        return ""
    asks = _thinking._asks_something(rest)
    if _asks_a_view(rest, asks):
        return "idea"
    if _thinking._ACK_RE.match(rest) or _thinking._CHECKIN_RE.match(rest):
        return "social"
    # "I'm doing okay. What about you?" — a check-in handed back.
    last = re.split(r"(?<=[.!?,;])\s+", rest)[-1]
    if _thinking._CHECKIN_RE.match(last) or re.search(
            r"\b(?:and|what about|how about) (?:you|u)\s*\??$", rest):
        return "social"
    if asks or _thinking._DISCUSSION_RE.search(rest):
        return ""
    for clause in re.split(r"[,.!?;:]+\s*", rest):
        bare = _thinking._FILLER_PREFIX_RE.sub("", clause.strip())
        if (_thinking._REQUEST_START_RE.match(bare)
                or _thinking._WORK_START_RE.match(bare) or _IMPERATIVE_RE.match(bare)):
            return ""
    return "social" if _is_news(rest) else ""


def social_kind(text: str) -> str:
    """What kind of social turn (turn_kind) this is: "greeting" ("hi",
    "good morning blue"), "ack" ("okay", "exactly", "true"), or "news" for a
    check-in, a feeling or a bit of news. "" when the turn is not social."""
    if turn_kind(text) != "social":
        return ""
    rest = _thinking._bare(_thinking._normalise(text))
    if not rest or _thinking._NAME_ONLY_RE.match(rest):
        return "greeting"
    if _thinking._ACK_RE.match(rest):
        return "ack"
    return "news"


_SOCIAL_NOTES = {"greeting": GREETING_TURN_NOTE, "ack": ACK_TURN_NOTE,
                 "news": SOCIAL_TURN_NOTE}


def reply_budget(text: str, *, voice: bool = False,
                 has_attachment: bool = False,
                 depth_cue: bool = False,
                 prev_reply: str = "",
                 kid: bool = False) -> Optional[int]:
    """The visible reply's cap in tokens for this turn, or None for no cap.

    `text` is the user's own words (attachments stripped). `voice` means the
    reply will be spoken. `has_attachment` covers a document, a long paste or
    an image. `depth_cue` is the caller's own sign that length is wanted (the
    chat page's "more" continuation cue). `prev_reply` is Blue's previous
    reply: a go-ahead for what it offered is not capped (accepts_offer).
    Missing a cue only brings back the uncapped reply of before. A typed
    idea turn (turn_kind) gets IDEA_REPLY_TOKENS, but not on the kids'
    page (`kid`), whose STYLE keeps every answer short.
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
    if voice:
        return SPOKEN_REPLY_TOKENS
    if not kid and turn_kind(text) == "idea":
        return IDEA_REPLY_TOKENS
    return TYPED_REPLY_TOKENS


def short_turn_note(text: str, *, voice: bool = False, kid: bool = False,
                    thinking: Optional[str] = None) -> str:
    """The note for a capped turn beside his words, by its kind (turn_kind),
    else "".

    social: the note for its kind (social_kind: a greeting, an
    acknowledgement, a check-in or news), typed or spoken. idea:
    IDEA_TURN_NOTE, typed (SPOKEN REPLY sets a spoken reply's length).
    Otherwise SHORT_TURN_NOTE, only where the long replies were: a typed
    question or request the turn thinks about (all 20 of the 10-05 harness's
    were). A correction or a class introduction gets none. The kids' page
    has its own STYLE.
    """
    if kid:
        return ""
    kind = turn_kind(text)
    if kind == "social":
        return _SOCIAL_NOTES[social_kind(text)]
    if voice:
        return ""
    if kind == "idea":
        return IDEA_TURN_NOTE
    if thinking != _thinking.THINK_ON:
        return ""
    return SHORT_TURN_NOTE if _thinking.asks_something(text) else ""


# Questions back are rare and never two replies in a row (Alex, 10-07: "rarely,
# specific only"). The closing note allows one short question about what he
# just said; when Blue's last reply already ended on one, the turn says so
# beside his words, where the model weighs a note most (see SHORT_TURN_NOTE).
# A nudge, not a net: nothing counts or cuts questions in the reply.
# Replayed on qwen3.8-27b over two 10-05 harness turns whose previous reply
# ended on a question ("pretty tired, long week of teaching", typed; "i don't
# know, maybe the material is too dense", spoken), n=3 each: "No question
# this time." still ended 3 of 6 on one ("Have you had a chance to
# decompress…?", "Have you tried breaking that Reigeluth chapter…?"); this
# wording, 0 of 6.
NO_QUESTION_NOTE = "End this reply on a statement, with no question."
# A heard turn may come through garbled, and HEARD, NOT TYPED asks for one
# short question naming the guess then. The plain note forbade it on exactly
# the turns that answer Blue's question, a name or a code, what speech
# recognition swaps most: 9 of the 18 check-backs in conversation_log came
# right after a reply that ended on a question. One replay each (10-08):
# "i don't know, maybe the material is too dense" still ended on a
# statement; "probably the age and lupus part" (the agent loops) was taken
# literally, so this leaves room for the check-back and does not make one.
NO_QUESTION_NOTE_HEARD = ("End this reply on a statement, with no question, "
                          "unless you need to check a word you didn't catch.")
# What may follow the "?" at the end of a reply: brackets, markdown emphasis.
_TRAILING_RE = re.compile(r"[\s)\]*_~]+$")
# Closing quotes after the "?" are someone else's words, unless the whole
# reply is one quote.
_CLOSE_QUOTES = "\"'”’»"
_OPEN_QUOTES = "\"'“‘«"
_DOUBLE_QUOTES_RE = re.compile(r"[\"“”«»]")
# The turn's own request may end on a question: "give me three discussion
# questions for tomorrow's dh201 reading", "draft an email asking the dean
# whether…", "ask the class what they think about X". A pin there
# contradicts what he asked for.
_QUESTIONS_ASKED_FOR_RE = re.compile(
    r"\bquestions?\b|\bquiz"
    r"|\bask(?:s|ing)? (?:them|the|him|her|everyone|everybody|my|our|his|their"
    r"|students|people|whether|if)\b")


def ends_on_question(reply: str) -> bool:
    """Blue's reply ended on a question: "…what model did you point it at?",
    also inside markdown or brackets. A question earlier in the reply does
    not count, nor does a quoted one at its end ('The guiding question for
    the class is: "…what happens to representation?"', conversation_log
    3971, 4495, 7910): Blue asked nothing. A reply that is one quote from
    start to end still counts."""
    text = _TRAILING_RE.sub("", reply or "")
    quoted = False
    while text and text[-1] in _CLOSE_QUOTES:
        quoted = True
        text = _TRAILING_RE.sub("", text[:-1])
    if not text.endswith("?"):
        return False
    if not quoted:
        return True
    whole = (reply or "").strip().strip("*_~").strip()
    return (whole[:1] in _OPEN_QUOTES
            and not _DOUBLE_QUOTES_RE.search(whole[1:-1]))


def questions_are_the_content(text: str) -> bool:
    """The turn asks for writing, a list, a recall or a reading, or names
    questions or asking someone: its reply may end on a question that is
    not Blue asking Alex."""
    t = _thinking._normalise(text)
    return bool(t) and any(rx.search(t) for rx in (
        _QUESTIONS_ASKED_FOR_RE, _ARTIFACT_RE, _WRITE_RE, _COUNT_RE,
        _RECALL_RE, _READ_RE))


def no_question_note(prev_reply: str, turn: str = "", *,
                     heard: bool = False) -> str:
    """NO_QUESTION_NOTE when Blue's previous reply ended on a question
    (NO_QUESTION_NOTE_HEARD on a heard turn), but none when the turn's own
    request may end on one (questions_are_the_content)."""
    if not ends_on_question(prev_reply):
        return ""
    if turn and questions_are_the_content(turn):
        return ""
    return NO_QUESTION_NOTE_HEARD if heard else NO_QUESTION_NOTE


def turn_note(*notes: str) -> str:
    """The notes for beside the user's words, as one: "[A short message: …
    End this reply on a statement, with no question.]", not two brackets."""
    return " ".join(n.strip() for n in notes if n and n.strip())


def visible_chars(cap_tokens: int) -> int:
    """The cap in characters of visible reply."""
    return int(cap_tokens * CHARS_PER_TOKEN)
