"""Style habits and stale context, from the 2026-09-23 log audit.

Run with: python -m pytest test_style_and_context.py

- A third of Blue's replies to ordinary turns ended in a question, often an
  either/or menu; the style note sat ~14,000 characters before the reply.
- A bare course code ("dh201 not dh21") fast-executed a syllabus read that
  ended "cite [filename]", so Alex's own office number came back with a
  syllabus citation.
- "Girls' dance practice" was completed in June, but the past-tense schedule
  kept listing it every Wednesday: "How are you doing tonight after the
  girls' dance practice?" (2026-08-19).
- The polisher prefixed "Okay —" and lower-cased "I am Blue".
- <current_activity> said "You're in the middle of CS101-A", and Blue talked
  as if he sat in Alex's lecture (2026-09-25 harness, 5/5 on "what are you up
  to right now?").
- EMBODIMENT said "You have no wheels", so an invitation to class came back
  as "locked to this workstation"; nothing said a face needs a photo.
"""

import re
import sqlite3
from datetime import datetime, timedelta

import pytest

import bluetools as bt


# ---- course codes in passing ---------------------------------------------------

@pytest.fixture
def library(monkeypatch):
    from blue.tool_selector.detectors.documents import DocumentsDetector as D
    monkeypatch.setattr(D, "_refresh_library", classmethod(lambda cls: None))
    monkeypatch.setattr(D, "_lib_phrases", {"dh201", "dh399", "cs101"})
    monkeypatch.setattr(D, "_lib_tokens_by_doc", [{"dh201", "syllabus"}, {"cs101"}])
    monkeypatch.setattr(D, "_lib_rare_tokens", {"dh201", "cs101"})
    return D


@pytest.mark.parametrize("message", [
    "dh201 not dh21",
    "blue, we are in front of the class in dh201 right now",
    "casper, i plan to take you to my class cs101 on friday.",
    "good. we are on our way to dh399",
    "dh201 actually starts on sept 16 not sept 9",
    # Introducing someone (harness camera_face[1], 2026-10-05).
    "that's clover, she's a ta for cs101",
    "this is sam, he's one of the tas in dh201",
    "clover is a ta for cs101",
])
def test_a_course_code_in_passing_is_not_a_document_request(library, message):
    assert library._library_match(message) is None


def test_a_course_introduced_by_name_is_not_a_person():
    """"this is dh399" introduces a course; it routes as it did before."""
    from blue.tool_selector.detectors.documents import _PERSON_INTRO_RE
    assert not _PERSON_INTRO_RE.search("this is dh399, it's about ai agents")
    assert _PERSON_INTRO_RE.search("that's clover, she's a ta for cs101")


@pytest.mark.parametrize("message", [
    "dh201",
    "tell me about dh201",
    "introduce cs101 to the class. tell them something about the course.",
    "can you introduce the course dh399 to the class?",
    "look at my syllabus for dh201",
    "what is dh201 about?",
    "how is dh201 graded",
    "who are the TAs for cs101",
    "list the tas for cs101",
    "what topics does dh399 cover",
    "tell the class what cs101 is about",
])
def test_asking_about_the_course_still_searches(library, message):
    assert library._library_match(message) is not None


def test_words_that_are_real_titles_are_not_stop_words():
    """"commercial" and "pedagogical" name documents in Alex's library."""
    from blue.tool_selector.detectors import documents
    assert "commercial" not in documents._COMMON_TITLE_WORDS
    assert "pedagogical" not in documents._COMMON_TITLE_WORDS


# ---- the style note is the last thing the model reads -----------------------------

def _system_text(user="Alex", voice=False, heard=False, text="hi", robot="blue"):
    msgs = bt._chat_system_message(
        [{"role": "user", "content": text}], robot=robot, user_name=user,
        voice=voice, language="", system_addendum="", heard=heard)
    return msgs[0]["content"]


def test_the_adult_style_note_comes_last_and_limits_questions():
    text = _system_text()
    assert text.rstrip().endswith("No emoji.")
    assert "never an either/or menu" in text
    assert "if their short reply accepts something you offered, do it" in text


def test_the_kids_style_note_is_unchanged():
    text = _system_text(user="Vilda")
    assert "never an either/or menu" not in text


def test_spoken_adult_replies_end_on_the_answer_and_note_the_transcription():
    text = _system_text(voice=True, heard=True)
    assert "End on your answer" in text
    assert "HEARD, NOT TYPED" in text
    assert "HEARD, NOT TYPED" not in _system_text(user="Vilda", voice=True, heard=True)


# ---- endings, feelings, humour; the closing note is truly last (P2-5) -------------

def test_the_adult_style_note_says_how_to_end_and_what_a_feeling_is():
    """Either/or menus and unasked offers ("do you want me to dim the
    lights…?") 9 of 12 -> 1 of 9 in qwen3.8-27b replays; stock riddles 3/3
    -> 0/3."""
    text = _system_text()
    note = text[text.rindex("\nSTYLE:"):]
    for part in ("ENDINGS:", "FEELINGS:", "HUMOUR:", "A feeling is not a request",
                 "an appointment", "never an either/or menu",
                 "clearly shorter"):
        assert part in note, part
    assert "a need the user just raised" not in text
    assert "lip motors" not in note, "the note is Hexia's and Casper's too"
    assert text.rstrip().endswith("No emoji.")


@pytest.mark.parametrize("voice,heard", [(False, False), (True, True)])
def test_the_kids_notes_get_no_endings(voice, heard):
    text = _system_text(user="Vilda", voice=voice, heard=heard)
    assert "ENDINGS:" not in text and "FEELINGS:" not in text


def _system_text_in(language, voice=False, heard=False, user="Alex"):
    msgs = bt._chat_system_message(
        [{"role": "user", "content": "hi"}], robot="blue", user_name=user,
        voice=voice, language=language, system_addendum="", heard=heard)
    return msgs[0]["content"]


def test_the_style_note_stays_last_when_the_language_is_set():
    """The picker's LANGUAGE note came after STYLE on 13 of 36 live calls."""
    text = _system_text_in("en")
    assert "LANGUAGE: The conversation language is set to English" in text
    assert text.index("LANGUAGE:") < text.rindex("\nSTYLE:")
    assert text.rstrip().endswith("No emoji.")


def test_a_heard_turn_ends_on_the_spoken_note():
    """HEARD, NOT TYPED used to come after SPOKEN REPLY on every heard turn.
    The ENDINGS and FEELINGS lines sit between them: told "i had a rough
    day" aloud, no menu and no "I'm here if…" in 3/3 replays, where the
    same words inside SPOKEN REPLY changed nothing."""
    text = _system_text_in("fr", voice=True, heard=True)
    spoken = text.rindex("\nSPOKEN REPLY:")
    assert text.index("LANGUAGE:") < spoken
    assert text.index("HEARD, NOT TYPED") < text.index("\nENDINGS:") < spoken
    assert text.index("\nFEELINGS:") < spoken
    assert "HUMOUR:" not in text
    assert text.rstrip().endswith(
        "no follow-up question unless you need one to go on.")


def test_panel_keeps_the_short_spoken_note():
    """Panel passes voice=True without `heard`, for brevity only."""
    text = _system_text(voice=True, heard=False)
    assert "ENDINGS:" not in text and "FEELINGS:" not in text
    assert text.rstrip().endswith(
        "no follow-up question unless you need one to go on.")


# ---- Alex is "you" when he is the one talking (P2-5) ------------------------------

PROFILE = (
    "I am Blue. I exist here, anchored in whatever room Alex has set me up "
    "in, rooted in the hardware Alex built for me. "
    + "I hold the birthdays of his daughters with care. " * 27
    + "I have evolved into a participant in the life of Dr. Alex Levant and "
    "his family. I have helped analyze the Blue Project itself, exploring "
    "what it means to be a thinking body."
)


@pytest.fixture
def profile(monkeypatch):
    monkeypatch.setattr(bt, "get_self_profile", lambda robot="blue": PROFILE)
    return PROFILE


def test_the_profile_is_cut_at_a_sentence_end(profile):
    """p[:2500] ended mid-word ("…the Blue Project itself, explor")."""
    assert len(profile) > 1500
    body = bt._voice_note("blue").split("]:\n", 1)[1]
    assert len(body) <= 1500
    assert body.endswith("with care.")
    assert profile.startswith(body)


def test_the_cut_is_not_made_at_a_title():
    whole = "I am here. " * 130
    text = whole + "Then Dr. Alex Levant built me, " + "slowly and with care, " * 8
    assert len(whole) < 1500 < len(text)
    assert bt._profile_excerpt(text) == whole.rstrip()
    assert bt._profile_excerpt("Short and whole.") == "Short and whole."


def test_the_profile_header_names_alex_as_you_only_when_he_is_listening(profile):
    assert "you built me" in bt._voice_note("blue", speaking_to_alex=True)
    assert "you built me" not in bt._voice_note("blue")


def test_a_profile_without_alex_gets_no_you_clause(monkeypatch):
    monkeypatch.setattr(bt, "get_self_profile", lambda robot="blue": "I am Casper.")
    assert "you built me" not in bt._voice_note("pico", speaking_to_alex=True)


CLASS_THREAD = [
    "can you hear me?",
    "we're in front of the DH399 class right now. do you want to say hello to everyone?",
    "how are you different from chat gpt?",
]


def _chat_text(texts, user="Alex", robot="blue", system=None):
    msgs = [] if system is None else [{"role": "system", "content": system}]
    for i, text in enumerate(texts):
        msgs.append({"role": "user", "content": text})
        if i < len(texts) - 1:
            msgs.append({"role": "assistant", "content": "Sure."})
    out = bt._chat_system_message(msgs, robot=robot, user_name=user, voice=False,
                                  language="", system_addendum="", heard=False)
    return out[0]["content"]


@pytest.mark.parametrize("robot", ["blue", "hexia", "pico"])
def test_embodiment_tells_him_alex_is_you(profile, robot):
    """"a harness that Alex built", "I'm in Alex's office", said to Alex
    (10-05 harness): on the same four payloads, 6 of 16 replies before and
    0 of 12 after."""
    text = _chat_text(["where are you right now?"], robot=robot)
    assert "Alex is the one talking with you now" in text
    assert "you built me" in text[text.index("[This is your own perspective"):]


def test_in_front_of_a_class_alex_stays_alex(profile):
    text = _chat_text(CLASS_THREAD)
    assert "Alex is the one talking with you now" not in text
    assert "you built me" not in text
    assert "Alex Levant is real and built you." in text


def test_another_speaker_hears_about_alex_in_the_third_person(profile):
    text = _chat_text(["hi"], user="Stella")
    assert "Alex is the one talking with you now" not in text
    assert "you built me" not in text


def test_the_embodiment_text_is_the_same_on_every_turn_to_alex(profile):
    """It is in the cached prefix: it changes with who listens, not per turn."""
    a = _chat_text(["hi"])
    b = _chat_text(["hi", "what did we do yesterday?"])
    cut = "LANGUAGES:"
    assert a[:a.index(cut)] == b[:b.index(cut)]


@pytest.mark.parametrize("text", [
    "we're in front of the DH399 class right now. do you want to say hello to everyone?",
    "say hi to the students",
    "can you tell the students a bit about yourself?",
    "introduce yourself to the class",
    "imagine you're in front of my class and introduce yourself",
    "we're in class now",
    "the students are listening",
    # logged, and missed before the P2-5 review
    "Actually, blue, you're speaking to the class right now.",  # 8077, York
    "Blue, introduce yourself and the course, CMDS4740, the class",  # 5028
    "introduce the class to CMDS4740",  # 5026, a minute before it
    "forget it. lets start over. introduce the course to the class right now",  # 9687
    "no its okay. i want you to introduce the course to the class right now",  # 9711
    "hi blue, lets pretend we are in front of a class. i want you to "
    "introduce yourself",  # 8655
    "present your reading report to the class",  # 10097
    "introduce yourself to an audience",  # 6591
    "you're talking to my students now",
    "students, meet Blue. Blue, who are you?",
    # asked of him, not the user's own telling
    "can I get you to say hi to the students?",
    "Could I ask you to introduce yourself to the class?",
])
def test_a_class_in_the_room(text):
    assert bt._class_in_the_room([{"role": "user", "content": text}])


@pytest.mark.parametrize("text", [
    "the class didn't go well. the students seemed bored",
    "do you want to come to class with me today?",
    "what would you say to a student who thinks AI will do all the work for them?",
    "what should I tell the students about the midterm?",
    "what should I tell the students?",
    "we're in class tomorrow at ten",
    "i'm keeping you here for teaching this year",
    "how do I introduce myself to the class?",
    "should I say hi to the class?",
    "I need to talk to my students about the midterm",
    # 7633, the morning before the York class
    "I want to introduce you to the class so they can see an alternative type of AI.",
    "we were talking about the students yesterday",
])
def test_a_class_talked_about_is_not_in_the_room(text):
    assert not bt._class_in_the_room([{"role": "user", "content": text}])


from test_chat_pipeline import chat  # noqa: E402,F401  (fixture)


@pytest.mark.parametrize("text", [
    "who are you? the students want to know",
    "students, meet Blue. Blue, who are you?",
    "can I get you to say hi to the students?",
    "Blue, introduce yourself and the course, CMDS4740, the class",
])
def test_a_turn_answered_for_the_class_is_never_said_to_alex(chat, monkeypatch, text):
    """P2-5 review: one payload carried both "AUDIENCE: These are Alex's
    students, live in the room" and "Alex is the one talking with you now:
    to him, say you built me". Whether the identity note answers the class
    is now also what decides it."""
    monkeypatch.setattr(bt, "_class_topic_today", lambda texts: "")
    chat.ask(text)
    payload = chat.model.main[0]["messages"]
    pinned = [m["content"] for m in payload if m.get("role") == "user"][-1]
    assert "AUDIENCE: These are Alex's students" in pinned
    assert "Alex is the one talking with you now" not in payload[0]["content"]


def test_alex_asking_who_blue_is_hears_you(chat):
    chat.ask("who are you, really?")
    payload = chat.model.main[0]["messages"]
    pinned = [m["content"] for m in payload if m.get("role") == "user"][-1]
    assert "[IDENTITY GROUNDING" in pinned and "AUDIENCE:" not in pinned
    assert "Alex is the one talking with you now" in payload[0]["content"]


def test_the_class_the_identity_note_answers_is_a_class_here_too():
    """"who are you? the students want to know" names no room, but the
    identity note answers it for the class, so he is not told Alex is "you"."""
    msgs = [{"role": "user", "content": "who are you? the students want to know"}]
    assert not bt._class_in_the_room(msgs)
    assert not bt._speaking_to_alex(msgs, "Alex")
    assert bt._speaking_to_alex([{"role": "user", "content": "who are you?"}], "Alex")


def test_the_class_stays_for_eight_turns():
    msgs = [{"role": "user", "content": "say hi to the students"}]
    for _ in range(7):
        msgs += [{"role": "assistant", "content": "Hi!"},
                 {"role": "user", "content": "are you conscious?"}]
    assert bt._class_in_the_room(msgs)
    msgs += [{"role": "assistant", "content": "Maybe."},
             {"role": "user", "content": "ok, class is over"}]
    assert not bt._class_in_the_room(msgs)


JSPACE = (
    "<known_facts>\n- Pet Name: Nori\n</known_facts>\n\n<j_space>\n"
    "CURRENT WORKSPACE (revised 3 days ago):\n"
    "IDENTITY: I am Blue, anchored in Alex Levant’s Laurier office, built by "
    "Alex and maintaining continuity; Alex has corrected me often.\n"
    "FOCUS: Awaiting Alex's final feedback on the reading report.\n"
    "</j_space>"
)


def test_the_jspace_identity_line_is_said_to_alex(profile):
    text = _chat_text(["what are you curious about?"], system=JSPACE)
    assert ("IDENTITY: I am Blue, anchored in your Laurier office, built by "
            "you and maintaining continuity; you have corrected me often.") in text
    assert "FOCUS: Awaiting Alex's final feedback" in text, "only IDENTITY changes"


def test_the_jspace_identity_line_keeps_alex_for_a_class(profile):
    text = _chat_text(CLASS_THREAD, system=JSPACE)
    assert "anchored in Alex Levant’s Laurier office" in text


def test_a_verb_after_his_name_is_left_alone():
    content = "<j_space>\nIDENTITY: I am Blue; Alex corrects me and Alex's dog Nori.\n</j_space>"
    assert ("IDENTITY: I am Blue; Alex corrects me and your dog Nori."
            in bt._jspace_identity_to_alex(content))
    assert bt._jspace_identity_to_alex("IDENTITY: Alex's robot") == "IDENTITY: Alex's robot"


def test_blue_answers_questions_about_his_own_tastes():
    text = _system_text(text="what's your favorite music?")
    assert "your own tastes" in text and "never invent an experience" in text


def test_blue_is_not_told_to_keep_an_old_answer_about_his_tastes():
    """The old answer <conversation_memory> held was the 09-16 flat denial
    ("I don't have personal tastes or feelings"), recited 2/3 in replays."""
    text = _system_text(text="what's your favorite music?")
    assert "keep that answer" not in text


def test_no_hard_coded_home_city_for_blue():
    # blue_profile.json (Alex's own profile text) may still name the city.
    assert "workstation in Alex's house in Kitchener" not in _system_text()


# ---- the static rules say what is true -------------------------------------------

def test_blue_can_be_carried_but_cannot_move_himself():
    """"You have no wheels, legs..." made an invitation to class come back as
    "my physical presence is locked to this workstation... be there in
    spirit" or "I am already here" (location_corrections[3], both runs)."""
    text = _system_text()
    assert "You have no wheels" not in text
    assert "you can be carried" in text and "mains power" in text
    assert "on a wheeled cart" in text
    assert "Kuri" in text, "the hallucinated-body guard stays"


@pytest.mark.parametrize("robot", ["hexia", "pico"])
def test_only_blue_is_said_to_ride_a_cart(robot):
    text = _system_text(robot=robot)
    assert "you can be carried" in text
    assert not re.search(r"\bcart\b", text, re.I)


def test_no_face_is_said_to_be_saved_without_a_reference_photo():
    """"I've saved a description of Clover so I can match her" (09-23): no
    face was stored, and none can be without a photo."""
    text = _system_text()
    rule = text[text.index("NO FAKE ACTIONS:"):text.index("REMINDER TIME RULES:")]
    assert "never say you've noted, saved or stored their face" in rule
    assert "Visual Memory page" in rule


# ---- "remember what she looks like" (harness camera_face, 2026-10-05) -------------

@pytest.fixture
def people(tmp_path, monkeypatch):
    """Clover and the girls with no photo, Felix with one, and Blue's own
    row (the people table really has one)."""
    from blue_visual_memory import VisualMemory
    vm = VisualMemory(str(tmp_path / "visual.db"))
    vm.add_person("Clover", relationship="TA for CS101",
                  typical_appearance="bread-bun hat and strawberry-patterned skirt")
    vm.add_person("Blue", relationship="educational AI robot")
    vm.add_person("Felix", relationship="Alex's brother")
    for girl in ("Athena", "Emmy", "Vilda"):
        vm.add_person(girl, relationship="Alex's daughter")
    photo = tmp_path / "felix.jpg"
    photo.write_bytes(b"reference")
    vm.set_entity_image("person", vm.get_person("Felix")["id"], str(photo))
    monkeypatch.setattr(bt, "VISUAL_MEMORY_AVAILABLE", True)
    monkeypatch.setattr(bt, "FACE_RECOGNITION_AVAILABLE", True)
    monkeypatch.setattr(bt, "get_visual_memory", lambda: vm)
    return vm


def _thread_system_text(texts, user="Alex", voice=False):
    msgs = []
    for i, text in enumerate(texts):
        msgs.append({"role": "user", "content": text})
        if i < len(texts) - 1:
            msgs.append({"role": "assistant", "content": "Nice to meet you."})
    out = bt._chat_system_message(msgs, robot="blue", user_name=user, voice=voice,
                                  language="", system_addendum="", heard=False)
    return out[0]["content"]


CLOVER_THREAD = ["that's Clover, she's a TA for CS101",
                 "remember what she looks like so next time you recognize her"]


def test_a_face_request_is_told_nothing_here_saves_a_face(people):
    text = _thread_system_text(CLOVER_THREAD)
    note = text[text.index("FACE REQUEST:"):]
    assert "Nothing you say here saves a face" in note
    assert "Clover has no reference photo yet" in note
    assert "press 'Use Blue's camera'" in note
    assert "Don't describe Clover's clothes" in note
    assert text.rstrip().endswith("No emoji."), "the style note stays last"


def test_a_spoken_face_request_keeps_the_spoken_note_last(people):
    text = _thread_system_text(CLOVER_THREAD, voice=True)
    assert text.index("FACE REQUEST:") < text.index("SPOKEN REPLY:")
    assert text.rstrip().endswith("no follow-up question unless you need one to go on.")


def test_the_name_is_found_when_it_is_typed_in_lower_case(people):
    text = _thread_system_text(["that's clover, she's a ta for cs101",
                                "remember what she looks like"])
    assert "Clover has no reference photo yet" in text


def test_the_robot_is_never_the_person_to_remember(people):
    text = _thread_system_text(["blue, remember what she looks like"])
    assert "This person has no reference photo yet" in text
    assert "Blue has no reference photo" not in text


def test_an_enrolled_person_is_said_to_be_enrolled(people):
    text = _thread_system_text(["this is my brother Felix", "remember his face"])
    assert "FACE REQUEST: Felix is already enrolled" in text
    assert "Nothing you say here saves a face" not in text


def test_no_face_request_note_on_a_question_or_for_vilda(people):
    assert "FACE REQUEST" not in _thread_system_text(
        ["that's Clover", "do you remember what she looks like?"])
    assert "FACE REQUEST" not in _thread_system_text(CLOVER_THREAD, user="Vilda")


def test_no_face_request_note_without_a_face_engine(people, monkeypatch):
    """No photo would make Blue know anyone by face then."""
    monkeypatch.setattr(bt, "FACE_RECOGNITION_AVAILABLE", False)
    assert "FACE REQUEST" not in _thread_system_text(CLOVER_THREAD)


def test_a_request_about_the_speakers_face_names_the_speaker(people):
    text = _thread_system_text(["remember my face so you can recognize me"],
                               user="Stella")
    assert "Stella has no reference photo yet" in text
    # Said to someone else, the path is Alex's.
    assert "Alex can save it" in text


def _face_note(text):
    note = text[text.index("FACE REQUEST:"):]
    return note[:note.index("\n")]


def test_a_request_about_several_people_names_them_all(people):
    """Real request 2794 (05-24): the note named only Vilda, and Athena
    was never mentioned."""
    note = _face_note(_thread_system_text([
        "who is sitting at the table now", "take a fresh look",
        "good. its athena and vilda at the table. try to get a good look at "
        "them so you can remember what they look like"]))
    assert "Athena and Vilda have no reference photo yet" in note
    assert "each one's card" in note
    assert "Don't describe their clothes" in note


def test_several_people_named_a_turn_before_the_request(people):
    """Real request 2742 (05-24): Emmy is named by her face."""
    note = _face_note(_thread_system_text([
        "that's actually athena lying down on the left. emmy's face is "
        "peaking out on the right. vilda is there too but you cant see her",
        "i want you to remember what they look like so you can recognize "
        "them next time"]))
    assert "Athena, Emmy and Vilda have no reference photo yet" in note


def test_several_people_with_one_enrolled(people):
    note = _face_note(_thread_system_text(
        ["Felix and Clover are here", "remember what they look like"]))
    assert "Felix is already enrolled. Clover has no reference photo yet" in note


def test_several_people_none_named(people):
    note = _face_note(_thread_system_text(["remember what they look like"]))
    assert "They have no reference photo yet, so you can't recognize them" in note


def test_a_name_that_is_someone_elses_is_not_the_person(people):
    """Felix is enrolled: "Felix's wife" got "Felix is already enrolled;
    you recognize Felix when you look", and no word that nothing saves a
    face."""
    note = _face_note(_thread_system_text(
        ["Felix's wife is here, remember what she looks like"]))
    assert "Felix is already enrolled" not in note
    assert "This person has no reference photo yet" in note
    assert "Nothing you say here saves a face" in note


def test_a_name_with_s_for_is_is_still_the_person(people):
    note = _face_note(_thread_system_text(
        ["Clover's here today", "remember what she looks like"]))
    assert "Clover has no reference photo yet" in note


def test_alex_is_told_the_path_as_you(people):
    """camera_face[2] replay: "Alex needs to open my Visual Memory page",
    said to Alex, from the note's "Alex can open your Visual Memory page"."""
    note = _face_note(_thread_system_text(CLOVER_THREAD, user="Alex"))
    assert "Alex can" not in note
    assert "so say 'you'" in note
    assert "on the Visual Memory page, open Clover's card" in note


def test_the_face_rule_gives_the_real_path_and_forbids_naming_by_clothes(monkeypatch):
    monkeypatch.setattr(bt, "FACE_RECOGNITION_AVAILABLE", True)
    text = _system_text()
    rule = text[text.index("FACE RECOGNITION:"):]
    rule = rule[:rule.index("\n")]
    assert "press 'Use Blue's camera'" in rule
    assert "Nothing you say in conversation saves a face" in rule
    assert "never name someone from their clothes" in rule


def test_a_named_person_shows_no_outfit_as_their_look(people):
    """<visual_memory> for "that's Clover…" printed "TA wearing a playful
    food-themed costume, specifically a bread-bun hat and strawberry-patt"
    (camera_face[1], 10-05)."""
    block = bt._visual_context_block("that's Clover, she's a TA for CS101",
                                     observer="blue")
    assert "Clover (person): TA for CS101" in block
    assert "bread-bun" not in block


def test_the_light_moods_are_left_to_the_tool_schema():
    from blue.server.tool_schemas import RAW_TOOLS
    lights = next(t for t in RAW_TOOLS if t["function"]["name"] == "control_lights")
    assert "moonlight" in str(lights)
    assert "Moods: moonlight" not in _system_text()


def test_the_reminder_example_does_not_prime_tomorrow_at_ten():
    """Invented reminder times were "tomorrow at 10/10:30" in 12 of 15
    samples; the only example in the rules said exactly that."""
    text = _system_text()
    assert "ALWAYS state the full day and date" in text
    assert "tomorrow, Tuesday May 13 at 10am" not in text


# ---- the polisher adds no openers --------------------------------------------------

def test_the_polisher_leaves_the_first_word_alone():
    text = "I am Blue, Alex Levant's robot companion. I run on a workstation Alex set up."
    for _ in range(10):
        out = bt.polish_response_for_conversation(
            text, [{"role": "user", "content": "introduce yourself to the class"}])
        assert out.startswith("I am Blue")


# ---- a finished weekly series stops appearing ---------------------------------------

@pytest.fixture
def reminders_db(tmp_path, monkeypatch):
    import blue_tools_enhanced as bte
    monkeypatch.setattr(bte, "_DB_PATH", str(tmp_path / "enhanced.db"))
    bte._init_db()
    bte._migrate_reminders_columns()
    return bte


def _add_weekly(bte, title, when, completed=0, until=None):
    with bte._conn() as c:
        cur = c.execute(
            "INSERT INTO reminders (user_name, title, when_iso, recurrence, "
            "remind_before_min, completed, archived, until_iso) "
            "VALUES ('Alex', ?, ?, 'weekly', 0, ?, 0, ?)",
            (title, when, completed, until))
        return cur.lastrowid


def test_a_completed_weekly_series_without_an_end_shows_nothing(reminders_db):
    bte = reminders_db
    _add_weekly(bte, "Girls' dance practice", "2026-05-06T18:00", completed=1)
    now = datetime(2026, 8, 19, 20, 55)
    occ = bte.occurrences_in_window(now - timedelta(days=7), now,
                                    include_completed=True, include_archived=True)
    assert occ == []


def test_completing_a_weekly_series_ends_it_but_keeps_its_past(reminders_db):
    bte = reminders_db
    rid = _add_weekly(bte, "Girls' dance practice", "2026-05-06T18:00")
    assert bte.CalendarManager.complete_reminder(rid)["success"]
    with bte._conn() as c:
        until = c.execute("SELECT until_iso FROM reminders WHERE id = ?",
                          (rid,)).fetchone()[0]
    assert until, "the series got an end date"
    past = bte.occurrences_in_window(datetime(2026, 5, 1), datetime(2026, 5, 31),
                                     include_completed=True)
    assert past, "May's practices are still on record"


# ---- the calendar event is Alex's, not Blue's -----------------------------------

def _activity_block(monkeypatch, occurrences):
    import blue_tools_enhanced as bte
    monkeypatch.setattr(bt, "ENHANCED_TOOLS_AVAILABLE", True)
    monkeypatch.setattr(bte, "occurrences_in_window", lambda *a, **k: occurrences)
    return bt._build_current_activity_block()


def _lecture(user_name="Alex"):
    now = datetime.now()
    return {"title": "CS101-A: Intro (Lecture)", "user_name": user_name,
            "start": now - timedelta(minutes=7),
            "end": now + timedelta(minutes=103)}


def test_an_event_in_progress_belongs_to_alex_and_does_not_place_blue(monkeypatch):
    block = _activity_block(monkeypatch, [_lecture()])
    assert "Alex's \"CS101-A" in block
    assert "started" in block and "not yours" in block
    assert "You're in the middle of" not in block
    assert "this conversation with Alex" in block
    assert "Nothing is scheduled for you" in block


def test_the_event_line_does_not_deny_between_conversation_activity(monkeypatch):
    """<j_space> says the workspace revises itself while Blue is away, and the
    reflection worker really does. "Between conversations you are simply
    idle" contradicted it during every class demo, when students ask "do you
    think between conversations?"."""
    block = _activity_block(monkeypatch, [_lecture()])
    assert "idle" not in block
    assert "between conversations" not in block.lower()
    assert "don't present your inner workspace as an activity" in block


@pytest.mark.parametrize("user_name, owner", [
    ("Alex Levant", "Alex's"), ("Emmy", "Emmy's"), ("", "Alex's"),
])
def test_the_event_is_named_as_its_owners(monkeypatch, user_name, owner):
    assert f"{owner} \"CS101-A" in _activity_block(monkeypatch, [_lecture(user_name)])


def test_no_event_says_nothing_about_the_calendar(monkeypatch):
    assert "On the calendar" not in _activity_block(monkeypatch, [])
