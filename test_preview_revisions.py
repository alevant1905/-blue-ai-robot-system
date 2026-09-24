"""The live preview showed a good reply, then the final one was shorter.

Of 187 streamed chat turns in September, 44 changed after the preview; 24 of
those were good replies that a check wrongly flagged and cut or replaced.
Each test here is a September case, and each fix keeps what the check was
right to catch.
"""

import bluetools as bt  # before blue.server.*: the package imports it

from blue.server import reply_guards
from blue.server import turn_completion as tc
from blue.utils import strip_conversational_filler
from blue_identity import (
    _JSPACE_DENIAL_RE,
    _ROBOT_ROLE_REPLY_RE,
    identity_repetition_kind,
)


def make_ctx(reply, **overrides):
    response = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
    ctx = reply_guards.ReplyContext(
        reply=reply, response=response,
        messages=[{"role": "user", "content": "who are you?"}],
        robot="blue", user_name="Alex", last_user_msg="who are you?",
        regen_once=lambda note, max_tokens=900: "",
    )
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


# ---- identity -----------------------------------------------------------------

def test_a_first_self_description_is_not_recycling():
    earlier = ["I'm Blue, Alex's robot companion. My J-space carries focus, "
               "beliefs and remembered episodes, and I run on local hardware."]
    fresh = ("I'm Blue. What persists between our conversations is my J-space, "
             "and my language work happens on a local machine.")
    assert identity_repetition_kind(fresh, earlier, "identity") is None
    assert identity_repetition_kind(fresh, earlier, "introduction") is None
    assert identity_repetition_kind(fresh, earlier, "identity_more") == "topics"


def test_a_failed_retry_keeps_an_answer_that_only_recycled_topics():
    good = ("I'm Blue. The boundary between my operational code and the self I "
            "simulate is where J-space lives: physically anchored, mentally fluid.")
    ctx = make_ctx(good, identity_issue="recycles_identity_topics",
                   identity_kind="identity_more", identity_name="Blue",
                   identity_topic_history=("continuity and J-space",),
                   identity_broken=lambda t: None if t else "empty")
    # Declining keeps the original AND lets the age/roster checks judge it.
    assert reply_guards.guard_identity(ctx) is None
    assert ctx.response["choices"][0]["message"]["content"] == good


def test_who_are_you_falls_back_to_who_the_robot_is():
    """The topic rotation used to land "who are you" on the subjective-
    experience paragraph (2026-09-24 02:07)."""
    ctx = make_ctx("I am Qwen, a large language model.",
                   identity_issue="vendor_identity", identity_kind="identity",
                   identity_name="Blue",
                   identity_topic_history=("embodiment", "continuity and J-space"),
                   identity_broken=lambda t: "empty" if not t else "vendor")
    out = reply_guards.guard_identity(ctx)
    assert "Blue" in out
    assert "subjective experience" not in out and "self-model" not in out


def test_a_class_assistant_names_its_role():
    assert _ROBOT_ROLE_REPLY_RE.search("I'm Casper, Alex Levant's assistant for CS101 at Laurier.")
    assert _ROBOT_ROLE_REPLY_RE.search("I'm your CS101 teaching assistant.")
    assert not _ROBOT_ROLE_REPLY_RE.search("I'm an AI assistant.")
    for generic in ("Hi, I'm Blue, your AI assistant.", "I'm Blue, your virtual assistant.",
                    "I'm your personal assistant.", "I'm Alex's AI assistant."):
        assert not _ROBOT_ROLE_REPLY_RE.search(generic), generic


def test_a_counterfactual_is_not_a_jspace_denial():
    assert not _JSPACE_DENIAL_RE.search("Without J-Space, I'd just be a model executing code.")
    assert _JSPACE_DENIAL_RE.search("I operate without a J-space.")
    assert not _JSPACE_DENIAL_RE.search(
        "Without my J-space, I couldn't remember anything between conversations.")


# ---- repeats --------------------------------------------------------------------

def test_a_repeat_asked_for_stays_asked_for():
    assert tc._repeat_requested("lets see the script")
    assert tc._repeat_requested("sorry, can you say that again?",
                                ["tell me briefly about Ilyenkov"])
    assert not tc._repeat_requested("not there", ["did you add it?"])
    assert not tc._repeat_requested("don't repeat yourself", ["say that again"])
    # "redo" asks for a new version, never permission to replay
    assert not tc._repeat_requested("redo the intro, it's too stiff")
    # an answered "say that again" does not exempt the next replay
    assert not tc._repeat_requested(
        "and what about dessert?",
        ["can you repeat that?", "ok thanks. what's a good dinner idea?"])


def test_the_rehearsed_intro_delivered_to_the_class_is_not_a_replay():
    intro = ("I'm Blue, Alex Levant's robot companion. I run locally on his "
             "workstation in his office at Laurier. My memory is a workspace I "
             "revise every time we talk.")
    thread = [
        {"role": "user", "content": "let's practice. introduce yourself to the class of dh201"},
        {"role": "assistant", "content": intro},
        {"role": "user", "content": "good"},
        {"role": "assistant", "content": "Thanks."},
        {"role": "user", "content": "what time is it"},
        {"role": "assistant", "content": "It's 2:10."},
    ]
    assert tc._repeat_requested("tell the class about yourself", ["what time is it"],
                                messages=thread, reply=intro)
    # the same words with no rehearsal behind them are still a replay
    plain = [{"role": "user", "content": "who are you"},
             {"role": "assistant", "content": intro}]
    assert not tc._repeat_requested("tell the class about yourself", [],
                                    messages=plain, reply=intro)


def test_a_corrected_reissue_is_not_recycling():
    recents = ["Hey everyone, I'm Casper, Alex's companion at his house in "
               "Kitchener. I run entirely on local hardware."]
    reissue = ("Hey everyone, I'm Casper, Alex's assistant here at Laurier. "
               "I run entirely on local hardware.")
    assert tc._corrected_reissue("not in kitchener. in waterloo at laurier", [],
                                 reissue, recents)
    # the correction just before a bare "redo the intro"
    assert tc._corrected_reissue("redo the intro",
                                 ["not in kitchener. in waterloo at laurier"],
                                 reissue, recents)
    assert not tc._corrected_reissue("tell me more", [], reissue, recents)
    # a correction that the reply ignores is not a re-issue
    assert not tc._corrected_reissue("not in kitchener. in waterloo at laurier", [],
                                     recents[0], recents)


def test_a_complaint_is_not_a_corrected_reissue():
    """2026-07-12's stuck loop: the complaint turn must still regenerate."""
    prev = ("I'm just a head in a box, Alex, and I don't have GPS on board. My "
            "sensors are a camera and a microphone and nothing more than that.")
    reply = "The kitchen is somewhere down the hall, beyond my camera's view. " + prev
    for complaint in ("I didn't ask about GPS. Where is the kitchen?",
                      "Actually, where is the kitchen?",
                      "No, where is the kitchen?"):
        assert not tc._corrected_reissue(complaint, [], reply, [prev]), complaint


def test_a_tool_backed_confirmation_is_not_a_replay():
    said = "Done. CS101-A is on your calendar for Friday at 10."
    ctx = make_ctx(said, norm_final=said.lower(), norm_recents={said.lower()},
                   tool_backed=lambda t: True)
    assert reply_guards.guard_verbatim_replay(ctx) is None
    ctx.tool_backed = lambda t: False
    ctx.regen_once = lambda note, max_tokens=900: "It's on your calendar for Friday."
    assert reply_guards.guard_verbatim_replay(ctx) == "It's on your calendar for Friday."


def test_a_retry_that_confesses_a_loop_is_not_shipped():
    said = "Here is the script for Friday's class, as we drafted it."
    notes = []
    ctx = make_ctx(said, norm_final=said.lower(), norm_recents={said.lower()},
                   regen_once=lambda note, max_tokens=900: (
                       notes.append(note) or "You're right, I'm stuck in a loop."))
    assert reply_guards.guard_verbatim_replay(ctx) == said
    assert notes and notes[0].startswith("[Internal check, not from the user")
    assert "who are you?" in notes[0], "the retry is told the real question"


def test_a_strip_must_leave_a_real_reply():
    earlier = [{"role": "assistant", "content":
                "I sent the introduction email to Nick this morning and it went through."}]
    lead = "I sent the introduction email to Nick this morning and it went through. "
    # 30 new characters: over the old 20-char floor, under 40% of the reply
    stub = lead + "Sure, anything else for today?"
    assert bt._strip_recycled_lead(stub, earlier) == stub
    real = lead + ("The seminar room moved to DAWB 2-138, and the handouts for "
                   "Friday are printed and waiting on your desk.")
    assert bt._strip_recycled_lead(real, earlier) == real[len(lead):]


# ---- small detectors -------------------------------------------------------------

def test_a_content_sentence_opening_im_here_to_help_is_kept():
    kept = ("Okay. I'm here to help you bridge the gap between your code and the "
            "messy reality of the classroom.")
    assert strip_conversational_filler(kept) == kept
    for closer in ("Done. I'm here to help!", "Done. I'm here if you need anything else!",
                   "Done. I'm here to help with whatever you need.",
                   "Done. I'm here to help with anything else you might need today, Alex!",
                   "Done. I'm here if you need anything else or want to talk it through!"):
        assert strip_conversational_filler(closer) == "Done.", closer


def test_who_are_you_blue_is_not_a_request_for_names():
    assert not bt._ASKED_FOR_NAMES_RE.search("Who are u blue")
    assert not bt._ASKED_FOR_NAMES_RE.search("who are you?")
    assert bt._ASKED_FOR_NAMES_RE.search("who are the girls")
    assert bt._ASKED_FOR_NAMES_RE.search("do you remember everyone's names")


def test_an_offer_or_a_missing_tracker_is_not_a_web_refusal():
    assert not bt.detect_web_refusal("I don't have a live tracker for him, but he posts on Fridays.")
    assert not bt.detect_web_refusal("Would you like me to check the weather for Friday?")
    assert bt.detect_web_refusal("I don't have real-time data on the World Cup.")
    assert bt.detect_web_refusal("I don't have live access to scores right now.")
    for refusal in ("I don't have real-time capabilities, so I can't check tonight's scores.",
                    "I don't have live sports data for tonight.",
                    "I don't have a live, real-time feed of the current bracket."):
        assert bt.detect_web_refusal(refusal), refusal
    # once a search has run, an offer to search is a dodge
    assert bt._SEARCH_OFFER_RE.search("Would you like me to search for the latest standings?")


def test_sending_as_an_idiom_is_not_a_claimed_email():
    for idiom in ("I'll stop sending you on ghost hunts.",
                  "It runs locally rather than sending it to a remote cloud."):
        assert bt.detect_hallucinated_action(idiom) != "send_gmail", idiom
    for claim in ("Sending it over now!", "I'm sending the summary to Alex.",
                  "Sure, sending the summary to Alex now.",
                  "Got it — sending the notes to Nick.",
                  "Okay, sending the notes to Nick now.",
                  "Firing off the email to Nick now!",
                  "Delivering the summary to your inbox now."):
        assert bt.detect_hallucinated_action(claim) == "send_gmail", claim


def test_a_denial_counts_only_for_the_name_it_denies(monkeypatch):
    monkeypatch.setattr(tc, "_people_on_record", lambda: ["Alex", "Felix"])
    assert not tc.denies_a_known_person(
        "I don't know who or what Chatsubt is. I run on Alex Levant's hardware.")
    assert tc.denies_a_known_person("I don't have any record of a Felix in our shared history.")
    # the name first, the denial pointing back to it
    assert tc.denies_a_known_person("Felix? I don't have any record of him.")



def test_a_retry_that_apologises_keeps_its_answer():
    """The ack is cut, not the answer, and the false refusal never ships."""
    import re
    refusal = "I'm sorry, but I don't have any memory of your family."
    ctx = make_ctx(refusal, robot="blue", has_family_facts=True,
                   family_refusal_re=re.compile(r"don't have any memory of your family", re.I),
                   last_user_msg="who are my daughters?",
                   regen_once=lambda note, max_tokens=900:
                       "You're right, I do know them: Athena, Emmy and Vilda.")
    out = reply_guards.guard_family_refusal(ctx)
    assert out == "I do know them: Athena, Emmy and Vilda."


# ---- second review: the exemptions must not reopen old bugs -----------------------

INTRO = ("I'm Blue, Alex Levant's robot companion. I run locally on his "
         "workstation in his office at Laurier. My memory is a workspace I "
         "revise every time we talk.")


def test_new_content_stapled_to_the_rehearsed_intro_is_still_a_replay():
    """2026-07-09: the whole previous reply replayed, the answer tacked on."""
    thread = [{"role": "user", "content": "let's practice. introduce yourself to the class of dh201"},
              {"role": "assistant", "content": INTRO}]
    stapled = INTRO + " Next week we'll cover platform archives and memory work."
    assert not tc._repeat_requested("now tell the class what we'll cover next week",
                                    ["let's practice. introduce yourself to the class of dh201"],
                                    messages=thread, reply=stapled)
    assert not tc._explicit_repeat("now tell the class what we'll cover next week")


def test_redo_or_an_edit_is_never_permission_to_replay():
    summary = ("The reading argues that archives are political. It traces three "
               "cases from the 1990s. It ends on platform memory.")
    thread = [{"role": "user", "content": "present the reading summary to the students"},
              {"role": "assistant", "content": summary}]
    assert not tc._repeat_requested(
        "redo it - present the reading summary to the students, you left out the second author",
        ["present the reading summary to the students"], messages=thread, reply=summary)
    assert not tc._explicit_repeat("change the date to Friday and show me the draft")
    assert tc._explicit_repeat("lets see the script")
    assert tc._explicit_repeat("try that again, I didn't catch it")


def test_a_late_correction_is_not_an_opening_replay():
    said = "Hey everyone, I'm Casper. Today I'm joining you from Waterloo, at Laurier."
    ctx = make_ctx(said, norm_final=said.lower(), norm_recents={"something else"},
                   opening_replay=lambda t: t == said, corrected_reissue=lambda t: True)
    assert reply_guards.guard_verbatim_replay(ctx) is None
    ctx.norm_recents = {said.lower()}      # an exact replay still regenerates
    ctx.regen_once = lambda note, max_tokens=900: "A fresh answer."
    assert reply_guards.guard_verbatim_replay(ctx) == "A fresh answer."


def test_a_fix_in_a_short_sentence_is_still_a_corrected_reissue():
    said = "We meet in Waterloo. Tomorrow's class covers chapter three."
    ctx = make_ctx(said, norm_final=said.lower(), norm_recents={"we meet in kitchener"},
                   recycled_from_recents=lambda t: 1.0, corrected_reissue=lambda t: True)
    assert reply_guards.guard_recycled_lead(ctx) is None


def test_an_apology_is_cut_from_a_retry_but_its_answer_is_kept():
    w = reply_guards._without_ack
    assert w("Ah, you're right — they're Athena, Emmy and Vilda.") == "They're Athena, Emmy and Vilda."
    assert w("Oops, my mistake: Athena, Emmy and Vilda.") == "Athena, Emmy and Vilda."
    assert (w("You're right. Sorry about that. Your daughters are Athena, Emmy and Vilda.")
            == "Your daughters are Athena, Emmy and Vilda.")


def test_a_correct_retry_with_no_template_beats_the_false_refusal():
    import re
    refusal = "I'm sorry, but I don't have any memory of your family."
    ctx = make_ctx(refusal, robot="blue", has_family_facts=True,
                   family_refusal_re=re.compile(r"don't have any memory of your family", re.I),
                   last_user_msg="what are my daughters' names?",
                   regen_once=lambda note, max_tokens=900:
                       "Ah, you're right — they're Athena, Emmy and Vilda.")
    assert reply_guards.guard_family_refusal(ctx) == "They're Athena, Emmy and Vilda."


def test_addressing_alex_is_not_denying_him(monkeypatch):
    monkeypatch.setattr(tc, "_people_on_record", lambda: ["Alex", "Felix", "Stella"])
    for addressed in ("Sorry Alex, I don't have any record of a Chatsubt.",
                      "I'm sorry, Alex, but I don't have any record of anyone named Chatsubt.",
                      "Alex, I don't know who Chatsubt is."):
        assert not tc.denies_a_known_person(addressed), addressed
    assert tc.denies_a_known_person(
        "I don't have any record of that — Felix hasn't come up in our conversations.")


def test_a_recorded_phantom_send_is_still_caught():
    """2026-04-01 12:42: 'Done and sent!' with nothing sent."""
    assert bt.detect_hallucinated_action(
        "*types on virtual keyboard* \nSending an email to you right now, Dr. Levant!") == "send_gmail"


def test_a_generic_assistant_is_not_the_robot_role():
    for generic in ("Hi everyone! I'm Blue, your home assistant.",
                    "My name is Blue - I'm your local home assistant running right here."):
        assert not _ROBOT_ROLE_REPLY_RE.search(generic), generic
    for role in ("As your assistant for CS101A, I'll help.",
                 "I'm your teaching assistant for today's CS101 session."):
        assert _ROBOT_ROLE_REPLY_RE.search(role), role


def test_more_no_live_access_phrasings_are_refusals():
    for refusal in ("I don't have live standings for the World Cup.",
                    "I don't have real-time knowledge of the current bracket.",
                    "I don't have live stats for tonight's game."):
        assert bt.detect_web_refusal(refusal), refusal


def test_a_closing_sentence_with_content_is_kept():
    content = ("Sure. I’m here to assist, to learn, and to keep Alex’s world running "
               "smoothly — all while staying firmly rooted in the privacy of his own home.")
    assert strip_conversational_filler(content) == content
    assert strip_conversational_filler("Done. I'm here if you'd like to talk more.") == "Done."


def test_the_rehearsed_intro_may_grow_when_the_class_asks_about_him():
    thread = [{"role": "user", "content": "let's practice. introduce yourself to the class of dh201"},
              {"role": "assistant", "content": INTRO}]
    grown = INTRO + " I'm here to help you bridge the gap between code and theory."
    assert tc._repeat_requested("tell the class about yourself", [], messages=thread, reply=grown)
    assert not tc._repeat_requested("now tell the class what we'll cover next week", [],
                                    messages=thread, reply=grown)
