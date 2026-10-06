"""The part of a course syllabus a message asks about, cut out by heading.

"when is dh201 again?" was answered right, from the calendar; the next turn,
"and what room?", got "my search came up empty on a room number", though the
DH201 syllabus says "Wednesday 10:00am - 12:50pm in SB107." under its
"Lecture and location" heading (10-05 harness). Asked to "follow the specific
requirements of the assignment as stated in the syllabus" after a DH399
reading report, Blue said the syllabus lists none; its "Reading Report
(20%)" section lists items a) to f), and Alex had to paste it in himself
(live 10-01). Both times a document search ran on the question and found
nothing: a syllabus is one small file, and its sections are not what a
search for "DH201 room location" ranks.

asked_topics() says which parts a message asks about (where and when the
course meets, office hours, the instructor's email, grading and assignments,
a named assignment, the late policy, attendance); excerpts() cuts those
parts out of one syllabus's text by their headings, in the syllabus's own
words. bluetools._syllabus_section_note finds the course and puts the parts
in the prompt as <syllabus_section>.

The topics are narrow on purpose: the block is only for a question about a
course, and "where are you?", "what's your email?" or "your journal" are
not one; "what percentage...", "how can I reach..." or "which room..."
count only in a message tied to a course (tied_to_a_course). Without a
course (named in the message or the turns just before it, cited in his
last reply, picked in the Context panel, or on the calendar right now)
nothing is added at all.

Pure text in, text out — no bluetools import.
"""

from __future__ import annotations

import re
from typing import List, Tuple

_CLASS_WORDS = r"(?:class|classes|lectures?|seminars?|tutorials?|course)"
# A question, not "when I was in class" or "where I teach".
_WHEN_Q = r"\bwhen(?:['\u2019]s| is| are| does| do| was| were| will)\b"
_WHERE_Q = r"\bwhere(?:['\u2019]s| is| are| does| do| was| were| will)\b"
# A course code: "DH201", "dh 201", "CS-101".
COURSE_CODE_RE = re.compile(r"\b([a-z]{2,5})\s?-?(\d{3,4})[a-z]?\b", re.I)

# Each part has the forms that are about a course on their own ("what's the
# late policy?", "is attendance mandatory?") and loose ones that are just as
# often about anything else: "what percentage of jobs will AI agents
# replace?", "how can I reach Leo?", "what time does the movie start
# tonight?", "which room has the best light?", "what are the requirements
# for a passport?", "tell me about your final project". During DH399 on the
# calendar, or with one course picked in the Context panel, each of those
# got that course's grading, email or room (review of e897c8b). A loose
# form counts only when the message is tied to a course: a course code or
# a course word in it, or, right after a course question, a message that
# points back to it ("and what room?", "what time does it start?").
_COURSE_WORD_RE = re.compile(
    r"(?<!middle )(?<!working )(?<!upper )(?<!lower )(?<!-)\bclass(?:es|room)?\b"
    r"|\bcourses?\b|\blectures?\b|\bseminars?\b|\btutorials?\b|\bsyllab(?:us|i)\b"
    # not "what percentage of students use AI?"
    r"|(?<!\bof )\bstudents?\b"
    r"|\bassignments?\b|\bgrad(?:e|es|ed|ing)\b|(?<!question )\bmarks\b|\bmarking\b",
    re.I)
# Pointing back at the course question just before: a leading "and", a
# pronoun for it, or two or three words and nothing else ("what room?").
_REFERS_BACK_RE = re.compile(
    r"^\s*(?:and|also|plus|so|what about|how about)\b"
    r"|\b(?:it|its|it['\u2019]s|that|this|they|them|their|there|he|him|his|she|her)\b",
    re.I)

# Where and when a course meets. "where are you located?", "what's your
# location?" and "what room are you in?" ask about the robot, so "where" and
# "location" count only with a class word, or a course code in the same
# message. "what room are we in?" is asked in class, of the class's room;
# "which room has the best light?" is a loose form.
_ROOM_RE = re.compile(
    _WHERE_Q + r"[^?.!]{0,30}\b" + _CLASS_WORDS + r"\b"
    r"|\b(?:class|lecture|course|seminar|classroom) (?:location|room)\b"
    r"|\blocation of (?:the |my |our )?" + _CLASS_WORDS + r"\b"
    r"|\b(?:what|which)(?:['\u2019]s| is| was)?(?: the)? classroom\b"
    r"|\b(?:what|which) (?:room|building) (?:are|were) we in\b",
    re.I)
_ROOM_LOOSE_RE = re.compile(
    r"\b(?:what|which)\s+(?:room|building|lecture hall|hall)\b"
    r"(?!\s+(?:are|were|is|was) (?:you|blue|hexia|casper)\b)"
    r"|\b(?:what|which)(?:['\u2019]s| is| was) the (?:room|building)\b"
    r"|\broom (?:number|no\b|#)",
    re.I)
_TIME_RE = re.compile(
    r"\bwhat time\b[^?.!]{0,30}\b" + _CLASS_WORDS + r"\b"
    r"|" + _WHEN_Q + r"[^?.!]{0,25}\b" + _CLASS_WORDS + r"\b",
    re.I)
_TIME_LOOSE_RE = re.compile(
    r"\bwhat time\b[^?.!]{0,30}\b(?:start|starts|end|ends|meet|meets)\b", re.I)
# With a course code in the message: "when is dh201 again?", "where is
# dh399?", "what time does CS101 start?", "dh201 location".
_CODE_WHEN_WHERE_RE = re.compile(
    _WHEN_Q + r"|" + _WHERE_Q
    + r"|\bwhat time\b|\b(?:what|which) days?\b|\blocation\b"
    r"|\b(?:what|which) room\b",
    re.I)
# "tell me the location of my office" (live 9631); not "your office",
# which is Blue's.
_OFFICE_HOURS_RE = re.compile(
    r"\boffice hours?\b|\b(?:location of|where(?:['\u2019]s| is)) (?:my|alex['\u2019]s|"
    r"his|the instructor['\u2019]s|the prof(?:essor)?['\u2019]s) office\b",
    re.I)
# The instructor and the course email. Not "what's your email" (Blue's
# own) and not "what email did you send".
_CONTACT_RE = re.compile(
    r"\b(?:instructor|professor|prof|teacher)(?:['\u2019]s)?\s+(?:e-?mail|contact|name)\b"
    r"|\b(?:course|class) e-?mail\b"
    r"|\be-?mail address(?:es)? (?:for|of) (?:the )?(?:course|class|instructor|prof)"
    r"|\b(?:the instructor|the prof(?:essor)?|dr\.? levant)['\u2019]?s? e-?mail\b"
    r"|\bwho(?:['\u2019]s| is) the (?:instructor|prof(?:essor)?)\b",
    re.I)
_CONTACT_LOOSE_RE = re.compile(
    r"\bcontact e-?mail\b"
    r"|\b(?:alex|his)['\u2019]?s? e-?mail\b"
    r"|\bhow (?:do|can|should|would) (?:students|they|i|we|people) "
    r"(?:contact|reach|e-?mail|get in touch with)\b"
    r"|\bwho (?:teaches|is teaching|instructs)\b"
    r"|\bwho(?:['\u2019]s| is) the teacher\b"
    r"|\bsubject line\b",
    re.I)
# How the course is graded, and what students hand in.
_ASSESSMENT_RE = re.compile(
    r"\bhow (?:is|are|will|was|were|do|does)\b[^?.!]{0,40}\b(?:graded|marked)\b"
    r"|\bhow (?:does|do|is|will|would) (?:the )?(?:grading|marking)\b"
    r"|\b(?:grading|marking) (?:scheme|breakdown|policy|criteria|rubric|system|"
    r"structure|weights?)\b"
    r"|\bgrade (?:breakdown|distribution|scheme|weights?|weighting)\b"
    r"|\bcourse requirements?\b"
    r"|\b(?:what|which)(?: are| were)?(?: the)?(?: main| major| key| big)? assignments\b"
    # "Go over the assignment with the class" (live 9469).
    r"|\b(?:go over|explain|describe|outline|review|walk (?:me|us|them) through|"
    r"tell (?:me|us|them) about|what(?:['\u2019]s| is| are)) the assignments?\b"
    r"|\b(?:requirements|instructions|guidelines|criteria|rubric) (?:of|for)\b"
    r"[^?.!]{0,30}\bassignments?\b"
    r"|\bassignments (?:are|is) (?:there|in|for)\b",
    re.I)
_ASSESSMENT_LOOSE_RE = re.compile(
    r"\bhow (?:is|are|will|was|were|do|does)\b[^?.!]{0,40}\b"
    r"(?:evaluated|assessed|weighted)\b"
    r"|\bhow (?:does|do|is|will|would) (?:the )?evaluation\b"
    r"|\b(?:evaluation|assessment) (?:scheme|breakdown|policy|criteria|rubric|system|"
    r"structure|weights?)\b"
    r"|\bhow much (?:is|are|does|do)\b[^?.!]{0,40}\b(?:worth|count|weigh)\b"
    r"|\bwhat (?:percent(?:age)?|weight(?:ing)?)\b"
    r"|\bworth\b[^?.!]{0,12}(?:%|\bpercent\b|\bmarks?\b|\bpoints?\b)"
    r"|\bdeliverables\b"
    r"|\b(?:what|which)(?: are| were)?(?: the)?(?: main| major| key| big)? requirements\b"
    r"|\b(?:go over|explain|describe|outline|review|walk (?:me|us|them) through|"
    r"tell (?:me|us|them) about|what(?:['\u2019]s| is| are)) the requirements\b",
    re.I)
_LATE_RE = re.compile(
    r"\blate (?:policy|penalty|penalties|assignments?|journals?|essays?)\b"
    r"|\bextensions? policy\b",
    re.I)
_LATE_LOOSE_RE = re.compile(
    r"\blate (?:work|submissions?|papers?|reports?)\b"
    r"|\b(?:submit|submitted|submitting|hand(?:ed|ing)? in|turn(?:ed|ing)? in|"
    r"accept(?:ed|s)?)\b[^?.!]{0,30}\blate\b"
    r"|\b(?:get|give|grant|ask for|asking for|request|allow)(?:s|ed|ing)? "
    r"(?:an |any |for )?extensions?\b"
    r"|\bextensions? (?:allowed|possible|available)\b",
    re.I)
_ATTENDANCE_RE = re.compile(
    r"\battendance\b"
    r"|\b(?:is|are) (?:the )?(?:class|classes|lectures?|tutorials?) "
    r"(?:mandatory|required|compulsory)\b"
    r"|\bmiss(?:es|ed|ing)? (?:a |the |one |two )?" + _CLASS_WORDS + r"\b",
    re.I)
_ATTENDANCE_LOOSE_RE = re.compile(
    r"\bparticipation\b"
    r"|\b(?:mandatory|required|compulsory) to (?:attend|come)\b"
    r"|\b(?:have|need) to (?:attend|come to|show up)\b",
    re.I)

# A named assignment: (topic, how a message names it, the looser names that
# need a course tie, how the syllabus heads or lists it). "journal" alone is
# Blue's own journal (J-space), so a message must say which; "project" alone
# is any project, and "final project", "research paper" or "bibliography"
# are as often his or Alex's own work.
ASSIGNMENTS = (
    ("the reading report",
     re.compile(r"\breading reports?\b", re.I),
     None,
     re.compile(r"reading reports?\b", re.I)),
    ("the journal",
     re.compile(r"(?<!\byour )\b(?:personal|reflection|reflective|weekly|course|reading)"
                r" journals?\b|\bjournals? of reflections?\b"
                r"|\bjournal (?:entries|entry|assignment)\b"
                r"|\b(?:the|their|students['\u2019]?) journals?\b(?=[^?.!]{0,30}\b"
                r"(?:due|worth|submit|words?|marks?|graded|requirements?)\b)", re.I),
     None,
     re.compile(r"(?:personal )?journal\b", re.I)),
    ("the project",
     re.compile(r"\b(?:course|class) projects?\b"
                r"|\bprojects? and presentations?\b"
                r"|\b(?:class|student) presentations\b", re.I),
     re.compile(r"\b(?:final|group|team) projects?\b"
                r"|\b(?:final|group) presentations\b", re.I),
     re.compile(r"(?:final |group |course )?project\b", re.I)),
    ("the annotated bibliography",
     re.compile(r"\bannotated bibliograph(?:y|ies)\b", re.I),
     re.compile(r"\bbibliograph(?:y|ies)\b", re.I),
     re.compile(r"(?:annotated )?bibliograph", re.I)),
    ("the research paper",
     re.compile(r"\bterm papers?\b", re.I),
     re.compile(r"\bresearch (?:paper|essay)s?\b|\bfinal (?:paper|essay)s?\b", re.I),
     re.compile(r"research (?:paper|essay)|(?:final |term )?(?:paper|essay)\b", re.I)),
    ("the midterm",
     re.compile(r"\bmid-?terms?\b(?!\s+elections?\b)", re.I),
     None,
     re.compile(r"mid-?term", re.I)),
    ("the final exam",
     re.compile(r"\bfinal exam(?:s|ination)?\b", re.I),
     None,
     re.compile(r"final exam", re.I)),
)

# "the assignment" names none: the one the turns before it named, else the
# list of all of them.
_THE_ASSIGNMENT_RE = re.compile(r"\b(?:the|this|that) (?:assignment|report)\b", re.I)

# Asking what was said or decided: "what did you tell me last week about
# the reading report for dh399?", "what did we decide about the final
# project for dh201?". <earlier_answers> and the memory blocks answer that;
# a block saying the syllabus overrides his earlier replies would answer a
# different question. "do you remember what room dh201 is in?" asks for
# the room, and is not one.
_WHAT_WAS_SAID_RE = re.compile(
    r"\bwhat (?:did|have|had) (?:you|u|we|i|you and i) (?:just |already |ever )?"
    r"(?:say|said|tell|told|decide|agree|come up with|came up with|suggest|"
    r"recommend|write|wrote|draft|propose|mention|talk|discuss|chat|settle)\w*"
    r"|\bwhat (?:were|was) (?:your|those|these) (?:\w+ ){0,2}(?:ideas?|suggestions?|"
    r"answers?|repl(?:y|ies)|advice|points?|notes?)\b"
    r"|\bremember (?:what|how) (?:we|i|you|u) (?:just |already )?"
    r"(?:talk|discuss|chat|said|say|told|tell|decid|mention|agreed|came up)\w*",
    re.I)


def course_codes(text: str) -> List[str]:
    """'dh201' for "DH201", "dh 201" or "DH-201", in order, once each."""
    out: List[str] = []
    for m in COURSE_CODE_RE.finditer(text or ""):
        code = (m.group(1) + m.group(2)).lower()
        if code not in out:
            out.append(code)
    return out


# Words before a number that course_codes() reads as a code: "in 2026",
# "by 2030", "at 1030", "room 107".
_NOT_A_COURSE = frozenset((
    "in", "at", "on", "by", "to", "of", "for", "from", "til", "till", "until",
    "since", "after", "about", "circa", "ca", "than", "over", "under", "is",
    "was", "are", "and", "or", "the", "year", "years", "page", "pages", "pp",
    "room", "rm", "no", "jan", "feb", "mar", "apr", "may", "jun", "june", "jul",
    "july", "aug", "sep", "sept", "oct", "nov", "dec"))


def written_course_codes(text: str) -> List[str]:
    """'cs240' for "CS240J", "cmds4740" or "dh 201": every course the
    message names, whether or not its syllabus is in the library."""
    return [code for code in course_codes(text)
            if re.match(r"[a-z]+", code).group(0) not in _NOT_A_COURSE]


def named_assignments(text: str, tied: bool = True) -> List[str]:
    """The assignments a message names, in ASSIGNMENTS order. With `tied`
    False (no course in sight) only the names that are a course's own:
    "reading report", not "final project"."""
    t = text or ""
    return [name for name, said, loose, _h in ASSIGNMENTS
            if said.search(t) or (tied and loose is not None and loose.search(t))]


def asks_what_was_said(text: str) -> bool:
    """"what did we decide about the final project?" asks for the earlier
    talk, not the syllabus."""
    return bool(_WHAT_WAS_SAID_RE.search(text or ""))


def tied_to_a_course(text: str, after_course_question: bool = False) -> bool:
    """A course code or a course word in the message, or, right after a
    course question, a message that points back to it."""
    t = text or ""
    if written_course_codes(t) or _COURSE_WORD_RE.search(t):
        return True
    return after_course_question and (
        len(re.findall(r"[\w'\u2019]+", t)) <= 3 or bool(_REFERS_BACK_RE.search(t)))


def asked_topics(text: str, after_course_question: bool = False) -> List[str]:
    """The parts of a syllabus a message asks about.

    `text` is the user's own words (attachments and pastes stripped);
    `after_course_question` says the user turn just before it asked about a
    course. A named assignment replaces the overview: "how much is the
    reading report worth?" is about the reading report."""
    t = text or ""
    if not t.strip():
        return []
    has_code = bool(written_course_codes(t))
    tied = tied_to_a_course(t, after_course_question)

    def asks(strict, loose):
        return bool(strict.search(t) or (tied and loose is not None and loose.search(t)))

    named = named_assignments(t, tied)
    topics: List[str] = []
    if asks(_ROOM_RE, _ROOM_LOOSE_RE) or (has_code and re.search(_WHERE_Q, t, re.I)):
        topics.append("when_where")
    elif not named and (asks(_TIME_RE, _TIME_LOOSE_RE)
                        or (has_code and _CODE_WHEN_WHERE_RE.search(t))):
        # "when is the journal due?" asks about the journal, not when class
        # meets.
        topics.append("when_where")
    if _OFFICE_HOURS_RE.search(t):
        topics.append("office_hours")
    if asks(_CONTACT_RE, _CONTACT_LOOSE_RE):
        topics.append("contact")
    topics.extend(named)
    if asks(_LATE_RE, _LATE_LOOSE_RE):
        topics.append("late")
    if asks(_ATTENDANCE_RE, _ATTENDANCE_LOOSE_RE):
        topics.append("attendance")
    if asks(_ASSESSMENT_RE, _ASSESSMENT_LOOSE_RE) and not named:
        topics.append("assessment")
    return topics


def means_an_unnamed_assignment(text: str) -> bool:
    """"follow the requirements of the assignment" names no assignment."""
    return bool(_THE_ASSIGNMENT_RE.search(text or "")) and not named_assignments(text)


# ---------------------------------------------------------------- sections

_LIST_ITEM_RE = re.compile(
    r"^(?:\(?\d{1,2}[.)]\s|\(?[a-z][.)]\s|\(?[ivx]{1,4}\)\s|[\u2022\u2013\u00b7*-]\s|\d{1,3}\s*%)",
    re.I)
_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z /'-]{1,30}:\s*\S")


def _is_heading(line: str) -> bool:
    """'Lecture and location', 'Reading Report (20%):', 'Late policy'.

    A short line that starts with a capital and does not end a sentence.
    Not a list item ('1) Reading Report - 20%'), not a field ('Instructor:
    Dr. ...', 'Next steps: Sign up early...'), not a sign-up blank."""
    s = line.strip()
    if not (2 <= len(s) <= 70) or s[-1] in ".,;!?":
        return False
    if not s[0].isupper() or _LIST_ITEM_RE.match(s):
        return False
    if "http" in s or "___" in s or len(s.split()) > 9:
        return False
    _head, colon, rest = s.partition(":")
    return not (colon and rest.strip())


def _clip(text: str, limit: int) -> str:
    """Blank lines and runs of spaces closed up; at most `limit`
    characters, cut at a line end when there is one."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n\s*", "\n", text).strip()
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = text.rfind(" ", 0, limit)
    return text[:cut].rstrip() + " [\u2026]"


def _heading_section(lines: List[str], i: int) -> str:
    """The heading at lines[i] and everything up to the next heading."""
    body = [lines[i]]
    for line in lines[i + 1:]:
        if _is_heading(line):
            break
        body.append(line)
    return "\n".join(body)


def _field_line(lines: List[str], i: int, follow: int = 0) -> str:
    """A 'Label: text' line, and up to `follow` lines after it that are
    neither blank nor another field (the email's "Start the subject line of
    your email with ..." reads like a heading)."""
    out = [lines[i]]
    for line in lines[i + 1:i + 1 + follow]:
        if not line.strip() or _FIELD_RE.match(line.strip()):
            break
        out.append(line)
    return "\n".join(out)


def _listed_item(lines: List[str], i: int) -> str:
    """A list item ('15%  Midterm exam ...') and the lines that continue it."""
    out = [lines[i]]
    for line in lines[i + 1:i + 6]:
        s = line.strip()
        if not s or _is_heading(s) or _LIST_ITEM_RE.match(s):
            break
        out.append(line)
    return "\n".join(out)


_WHEN_WHERE_HEADING_RE = re.compile(
    r"\b(?:location|locations|room|time and place|when and where|meeting times?|"
    r"class times?|lecture times?)\b", re.I)
_WHEN_WHERE_FIELD_RE = re.compile(
    r"^(?:location|room|classroom|class time|lectures?|time|meets?|when)\s*:", re.I)
_ASSESSMENT_HEADING_RE = re.compile(
    r"^(?:course requirements|assignments and evaluation|assignments|"
    r"(?:grading|evaluation|assessment|marking)(?: scheme| breakdown)?|"
    r"grade breakdown|course evaluation|requirements)\b", re.I)
_ATTENDANCE_HEADING_RE = re.compile(r"\b(?:attendance|participation)\b", re.I)
_SCHEDULE_START_RE = re.compile(r"\s*(?:class|course|weekly) schedule\b", re.I)


def sections(text: str, topic: str) -> List[Tuple[str, str]]:
    """[(label, excerpt)] for `topic` in one syllabus's text, [] when the
    syllabus has no such part. The excerpt is the syllabus's own words."""
    lines = (text or "").splitlines()
    if not lines:
        return []
    # Assignments are described before the class schedule; inside it,
    # "Reading Reports:" heads every week's sign-up blanks.
    sched = next((n for n, line in enumerate(lines)
                  if _SCHEDULE_START_RE.match(line)), len(lines))

    def first_heading(pattern, stop, limit):
        for n in range(stop):
            if _is_heading(lines[n]) and pattern.search(lines[n].strip()):
                return _clip(_heading_section(lines, n), limit)
        return ""

    if topic == "when_where":
        part = first_heading(_WHEN_WHERE_HEADING_RE, sched, 700)
        if not part:
            n = next((n for n in range(sched)
                      if _WHEN_WHERE_FIELD_RE.match(lines[n].strip())), None)
            part = _clip(_field_line(lines, n), 400) if n is not None else ""
        return [("where and when it meets", part)] if part else []
    if topic == "office_hours":
        for n, line in enumerate(lines):
            if re.match(r"\s*office hours?\b", line, re.I):
                part = (_heading_section(lines, n) if _is_heading(line)
                        else _field_line(lines, n))
                return [("office hours", _clip(part, 500))]
        return []
    if topic == "contact":
        parts: List[str] = []
        for n in range(sched):
            s = lines[n].strip()
            if not parts and re.match(r"(?:course )?(?:instructor|professor)\s*:", s, re.I):
                parts.append(_field_line(lines, n))
            elif re.match(r"e-?mail\s*:", s, re.I):
                parts.append(_field_line(lines, n, follow=4))
                break
        return [("instructor and email", _clip("\n".join(parts), 700))] if parts else []
    if topic == "assessment":
        part = first_heading(_ASSESSMENT_HEADING_RE, sched, 1800)
        return [("assignments and grading", part)] if part else []
    if topic == "late":
        for n, line in enumerate(lines):
            if re.match(r"\s*late\b", line, re.I) and (
                    _is_heading(line) or _FIELD_RE.match(line.strip())):
                part = (_heading_section(lines, n) if _is_heading(line)
                        else _field_line(lines, n))
                return [("late policy", _clip(part, 1200))]
        return []
    if topic == "attendance":
        found: List[Tuple[str, str]] = []
        part = first_heading(_ATTENDANCE_HEADING_RE, len(lines), 900)
        if part:
            found.append(("attendance and participation", part))
        if "%" in part:
            # "Class Participation (20%):" already gives its weight.
            return found
        for n in range(sched):
            s = lines[n].strip()
            if _LIST_ITEM_RE.match(s) and _ATTENDANCE_HEADING_RE.search(s):
                found.append(("attendance and participation",
                              _clip(_listed_item(lines, n), 900)))
                break
        return found
    heads = next((h for name, _said, _loose, h in ASSIGNMENTS if name == topic), None)
    if heads is None:
        return []
    label = topic[4:] if topic.startswith("the ") else topic
    for n in range(sched):
        if _is_heading(lines[n]) and heads.match(lines[n].strip()):
            return [(label, _clip(_heading_section(lines, n), 1500))]
    # Listed, not headed: "15%  Midterm exam (one-hour) will be ...". An
    # item that starts with the name, before one that mentions it ("...
    # sources for your research paper" is the bibliography).
    items = [n for n in range(sched) if _LIST_ITEM_RE.match(lines[n].strip())]
    for n in items:
        if heads.match(_LIST_ITEM_RE.sub("", lines[n].strip(), count=1).strip()):
            return [(label, _clip(_listed_item(lines, n), 1200))]
    for n in items:
        if heads.search(lines[n]):
            return [(label, _clip(_listed_item(lines, n), 1200))]
    return []


def excerpts(text: str, topics: List[str], limit: int = 2600) -> List[Tuple[str, str]]:
    """The sections for `topics` in one syllabus, each once, within `limit`
    characters in all. A part already inside an earlier one (the office
    hours line under "Lecture and location") is left out."""
    out: List[Tuple[str, str]] = []
    used = 0
    for topic in topics:
        for label, part in sections(text, topic):
            if any(part in prev or prev in part for _l, prev in out):
                continue
            if used + len(part) > limit:
                return out
            out.append((label, part))
            used += len(part)
    return out
