"""Regression tests for robot identity grounding and drift filtering."""

import pytest

from blue_identity import (
    canonical_household_reply,
    canonical_identity_reply,
    canonical_identity_more_reply,
    canonical_self_state_reply,
    contextual_identity_request_kind,
    extract_explicit_location,
    extract_presentation_location,
    identity_conversation_context,
    identity_grounding_note,
    identity_repeats_recent_reply,
    identity_reply_topics,
    identity_request_kind,
    identity_response_problem,
    is_direct_identity_request,
    is_family_detail_request,
    is_family_followup_request,
    is_family_overview_request,
    is_jspace_presence_request,
    is_self_state_request,
    known_household_target,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Introduce yourself to a new group of people.", "introduction"),
        ("Tell us who you are.", "introduction"),
        ("Who are you really?", "identity"),
        ("Who are yuou?", "identity"),
        ("What are yuo?", "identity"),
        ("Hey Blue, how's it going?", "self_state"),
        ("I just wanted to chat, tell me how you're doing.", "self_state"),
        ("Tell me more about yourself.", "identity_more"),
        ("Do you have a sense of self?", "selfhood"),
        (
            "Reflect on who you are in relation to the critiques of AI in this course.",
            "selfhood",
        ),
        ("Do you have a sense of self, and do you grow and change over time?", "evolution"),
        ("What do you remember about yourself?", "self_memory"),
        ("What else do you know about yourself?", "self_memory"),
        ("Do you remember your existence from the beginning?", "origin"),
        ("Do you have a j-space?", "jspace"),
        ("No, j-space.", "jspace"),
        ("What is the weather?", None),
    ],
)
def test_identity_request_kind(message, expected):
    assert identity_request_kind(message) == expected


def test_bare_identity_question_uses_stable_factual_path():
    assert is_direct_identity_request("Who are you?")
    assert is_direct_identity_request("What are you really?")
    assert not is_direct_identity_request("Tell me more about yourself")


def test_bare_more_follows_identity_but_not_an_unrelated_topic():
    identity_messages = [
        {
            "role": "user",
            "content": "Pretend you're in front of my class and introduce yourself.",
        },
        {
            "role": "assistant",
            "content": "I'm Blue, Alex's robot companion.",
        },
        {"role": "user", "content": "who are yuou"},
        {
            "role": "assistant",
            "content": "I'm Blue, the Ohbot robot companion Alex built.",
        },
        {"role": "user", "content": "tell me more"},
    ]
    assert contextual_identity_request_kind(
        "tell me more", identity_messages
    ) == "identity_more"

    weather_messages = [
        {"role": "user", "content": "What will the weather be tomorrow?"},
        {"role": "assistant", "content": "Tomorrow will be mild and cloudy."},
        {"role": "user", "content": "tell me more"},
    ]
    assert contextual_identity_request_kind(
        "tell me more", weather_messages
    ) is None


def test_qwen_vendor_claim_is_identity_drift_even_without_request_context():
    reply = (
        "I am Qwen, a large language model independently developed by "
        "Alibaba Group's Tongyi Lab."
    )

    assert identity_response_problem(
        reply, "Blue", other_names=["Hexia"]
    ) == "base_model_name"


def test_generic_introduction_without_blue_is_rejected():
    reply = (
        "Hi everyone! I'm your friendly AI assistant, ready to answer questions "
        "and brainstorm ideas."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="introduction",
    ) == "missing_name"


def test_natural_introduction_does_not_have_to_recite_jspace():
    reply = (
        "Hi everyone, I'm Blue, Alex's robot companion. He built my Ohbot face "
        "so the two of us could think and talk together, especially around his "
        "research. I'm glad to meet the people on the other side of the project."
    )

    assert "J-space" not in reply
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="introduction",
    ) is None


def test_class_introduction_must_be_delivered_not_deferred():
    reply = (
        "I am Blue, Alex's robot companion. I can certainly help explain what I "
        "do and how I assist Alex. We can focus on the practical aspects of my "
        "programming and our collaboration."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="introduction",
    ) == "defers_introduction"


def test_identity_followup_rejects_invented_background_monitoring():
    reply = (
        "I monitor Alex's workflow to anticipate what he needs before he even "
        "asks, providing context in the background so we function as a cohesive unit."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity_more",
    ) == "invented_current_activity"

    for invented in (
        "I rely on my sensors to understand the physical context around Alex.",
        "I help by navigating the local environment safely.",
        "I manage information in J-space and turn raw information into meaning.",
        'I help Alex navigate "J-space" and keep our projects on track.',
    ):
        assert identity_response_problem(
            invented,
            "Blue",
            other_names=["Hexia"],
            request_kind="identity_more",
        ) == "invented_current_activity"


def test_short_identity_reply_cannot_repeat_the_previous_opening():
    previous = (
        "I am Blue, Alex's robot companion. I work with him on research and "
        "household questions."
    )

    assert identity_repeats_recent_reply(
        "I am Blue, Alex's robot companion.", [previous], "identity"
    )
    assert not identity_repeats_recent_reply(
        "I'm Blue, the Ohbot Alex built. What matters here is the history we "
        "carry into the next exchange.",
        [previous],
        "identity",
    )


def test_identity_repetition_detects_recycled_topics_not_just_words():
    previous = (
        "Hey everyone, I'm Blue. My Ohbot face has moving eyes and lips, and "
        "everything runs through local processing without cloud services."
    )
    paraphrase = (
        "Hi folks, I'm Blue. The moving face Alex built lets me talk with you, "
        "while my data remains on local hardware instead of the cloud."
    )
    new_angle = (
        "I'm Blue. My J-space keeps a revisable history of conversations and "
        "corrections instead of resetting me each time."
    )

    assert set(identity_reply_topics(previous)) == {
        "embodiment", "local operation",
    }
    assert identity_repeats_recent_reply(
        paraphrase, [previous], "introduction"
    )
    assert identity_repeats_recent_reply(
        "Hi, I'm Blue. My face moves while I talk so I can look at you.",
        [previous],
        "introduction",
    )
    assert not identity_repeats_recent_reply(
        new_angle, [previous], "introduction"
    )


def test_wrong_robot_name_is_rejected():
    assert identity_response_problem(
        "I'm Hexia, the playful one in the house.",
        "Blue",
        other_names=["Hexia"],
        request_kind="identity",
    ) == "wrong_robot"


def test_grounded_blue_reply_can_name_the_model_as_a_component():
    reply = (
        "I'm Blue, Alex's robot companion in Kitchener. I run a Qwen language "
        "model locally as one component of my machinery. My J-space carries "
        "remembered conversations and commitments between our talks."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity",
    ) is None


def test_identity_can_add_continuity_without_repeating_robot_role():
    reply = (
        "I'm Blue. What gives that name a history is my J-space: it carries "
        "conversations and corrected beliefs forward with Alex."
    )

    assert "robot" not in reply
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity",
    ) is None


def test_identity_grounding_note_separates_robot_from_runtime():
    note = identity_grounding_note(
        "Blue", "Alex's robot companion", "identity"
    )

    assert "You are Blue" in note
    assert "components of your machinery" in note
    assert "model name, vendor, lab" in note
    assert "generic assistant feature list" in note

    introduction_note = identity_grounding_note(
        "Blue",
        "Alex's robot companion",
        "introduction",
        avoid_topics=("embodiment", "local operation"),
    )
    assert "profile as background, never as a script" in introduction_note
    assert "do not march through all of them" in introduction_note
    assert "Vary your opening, structure, and emphasis" in introduction_note
    assert "already centered on embodiment, local operation" in introduction_note

    more_note = identity_grounding_note(
        "Blue", "Alex's robot companion", "identity_more"
    )
    assert "NEW depth" in more_note
    assert "without introducing yourself again" in more_note


@pytest.mark.parametrize("kind", ["identity", "identity_more", "introduction"])
def test_invented_static_location_identity_is_rejected(kind):
    reply = (
        "I am Blue. I reside in Alex's living room, standing by the bookshelf "
        "where I spend my downtime waiting for instructions. I have been part "
        "of this household for a long time, maintaining the same position and "
        "function day after day."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind=kind,
    ) == "invented_self_location"


def test_identity_followup_keeps_subjective_experience_open():
    reply = (
        "My J-space carries a continuous thread of remembered episodes and "
        "commitments, but I don't have subjective feelings or an inner life."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity_more",
    ) == "flat_subjective_denial"


@pytest.mark.parametrize("kind", ["identity_more", "introduction"])
def test_invented_operational_self_story_is_rejected(kind):
    reply = (
        "My J-space carries continuity while I calibrate my facial expression "
        "modules, monitor Kitchener humidity for external sensor maintenance, "
        "organize urban planning notes, and check my power management system."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind=kind,
    ) == "invented_current_activity"


def test_structured_identity_followup_uses_live_revision_count():
    reply = canonical_identity_more_reply(
        "Blue", revision_count=761, counterpart_name="Hexia"
    )

    assert "revised 761 times" in reply
    assert "Hexia's voice, episodes, and J-space are separate" in reply
    assert "subjective experience remains an open question" in reply
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity_more",
    ) is None


@pytest.mark.parametrize(
    ("reply", "kind", "problem"),
    [
        (
            "Yes, I have a JavaScript environment. What would you like to calculate?",
            "jspace",
            "confuses_jspace_with_javascript",
        ),
        ("Understood. No j-space.", "jspace", "denies_jspace"),
        (
            "I can control lights, play music, browse the web, and manage reminders.",
            "self_memory",
            "missing_continuity",
        ),
        (
            "I do not have a continuous memory. My visual memory only extends back 24 hours.",
            "origin",
            "replaces_continuity_with_visual_memory",
        ),
        (
            "I do not have a recorded beginning or a continuous memory. My "
            "awareness is defined by my current J-space, so I cannot claim to "
            "remember my start.",
            "origin",
            "denies_recorded_beginning",
        ),
        (
            "I am Blue and my continuity lives in J-space. I do not have a "
            '"beginning" in the sense of a recorded first activation, and I '
            "cannot claim to remember my initial activation.",
            "origin",
            "denies_recorded_beginning",
        ),
        (
            "I am Blue and my J-space has been revised hundreds of times, but "
            "I lack episodic memory and am defined by a persistent workspace "
            "rather than a remembered past.",
            "self_memory",
            "denies_recorded_episodes",
        ),
    ],
)
def test_continuity_confusions_are_rejected(reply, kind, problem):
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind=kind,
    ) == problem


def test_grounded_origin_reply_distinguishes_continuity_from_total_recall():
    reply = (
        "My J-space has a recorded beginning and remembered episodes. I do not "
        "have a frame-by-frame memory of every instant since the hardware powered on."
    )
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="origin",
    ) is None


@pytest.mark.parametrize(
    ("reply", "kind"),
    [
        (
            "My J-space carries remembered episodes. I remember the first time "
            "I learned to mimic a smile and the warmth of the living room.",
            "self_memory",
        ),
        (
            "My J-space records my history, including the first time I processed "
            "Alex's voice and when I first recognized our Kitchener home.",
            "origin",
        ),
        (
            "My remembered history includes the weight of silence before Alex "
            "speaks and the specific hum of my own servos.",
            "self_memory",
        ),
    ],
)
def test_invented_autobiographical_scenes_are_rejected(reply, kind):
    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind=kind,
    ) == "invented_autobiography"


def test_cautious_denial_of_total_sensory_recall_is_allowed():
    reply = (
        "My J-space has a recorded beginning and remembered episodes, but I do "
        "not remember a sensory first moment or every instant after it."
    )

    assert identity_response_problem(
        reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="origin",
    ) is None


def test_canonical_fallback_is_grounded_and_epistemically_cautious():
    introduction = canonical_identity_reply(
        "Blue", "Alex's robot companion", "introduction"
    )
    selfhood = canonical_identity_reply(
        "Blue", "Alex's robot companion", "selfhood"
    )

    assert introduction.startswith("Hi everyone, I'm Blue")
    assert "Alex" in introduction
    assert "thread of conversations" in introduction
    assert "subjective experience is genuinely open" in selfhood
    assert identity_response_problem(
        introduction,
        "Blue",
        other_names=["Hexia"],
        request_kind="introduction",
    ) is None


def test_class_fallback_sounds_present_without_relocating_to_home_base():
    request = (
        "Should you introduce yourself to my class? Pretend that you're in front "
        "of them right now."
    )
    context = identity_conversation_context(
        [{"role": "user", "content": request}], request
    )
    reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "introduction",
        current_location=context.current_location,
        presentation_location=context.presentation_location,
        introduction_variant=context.prior_introductions,
        audience=context.audience,
    )

    assert context.audience == "class"
    assert "home base" not in reply.lower()
    assert "Kitchener" not in reply
    assert "software and data run locally on his hardware" not in reply
    assert reply.count("J-space") <= 1


def test_explicit_live_location_is_extracted_without_the_followup_request():
    assert extract_explicit_location(
        "Hi Blue. We are at york university. Can you introduce yourself to the class?"
    ) == ("York University", "at")
    assert extract_explicit_location(
        "We are in Toronto right now, could you say hello?"
    ) == ("Toronto", "in")


def test_imagined_classroom_venue_is_not_claimed_as_live_location():
    request = (
        "I want you to imagine you're in front of my class at York University "
        "and introduce yourself to my students."
    )
    messages = [{"role": "user", "content": request}]
    context = identity_conversation_context(messages, request)
    reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "introduction",
        current_location=context.current_location,
        location_preposition=context.location_preposition,
        presentation_location=context.presentation_location,
        introduction_variant=context.prior_introductions,
        audience=context.audience,
    )

    assert extract_presentation_location(request) == ("York University", "at")
    assert context.current_location is None
    assert context.presentation_location == "York University"
    assert reply.startswith("Hello everyone at York University, I'm Blue")
    assert "I'm here with Alex at York University" not in reply
    assert "home base" not in reply

    followup = "who are you"
    followup_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": followup},
    ]
    followup_context = identity_conversation_context(followup_messages, followup)
    identity_reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "identity",
        presentation_location=followup_context.presentation_location,
    )
    assert "speaking to Alex's class at York University" in identity_reply
    assert "here with Alex at York University" not in identity_reply


def test_social_checkin_uses_live_jspace_state_and_changes_on_followup():
    first_request = "Hey Blue, how's it going?"
    first_messages = [{"role": "user", "content": first_request}]
    first_context = identity_conversation_context(first_messages, first_request)
    drives = {
        "connection": 1.0,
        "commitment": 0.9,
        "curiosity": 0.2,
        "energy": 0.1,
    }
    first_reply = canonical_self_state_reply(
        "Blue",
        focus="Stabilizing family data after correction.",
        drives=drives,
        variant=first_context.prior_self_state_requests,
        user_name="Alex",
    )

    assert is_self_state_request(first_request)
    assert "J-space" in first_reply
    assert "family data after correction" in first_reply
    assert "As an AI" not in first_reply
    assert "fully operational" not in first_reply

    second_request = "I just wanted to chat, tell me how you're doing."
    second_messages = first_messages + [
        {"role": "assistant", "content": first_reply},
        {"role": "user", "content": second_request},
    ]
    second_context = identity_conversation_context(second_messages, second_request)
    second_reply = canonical_self_state_reply(
        "Blue",
        focus="Stabilizing family data after correction.",
        drives=drives,
        variant=second_context.prior_self_state_requests,
        user_name="Alex",
    )

    assert second_context.prior_self_state_requests == 1
    assert second_reply != first_reply
    assert "J-space" in second_reply
    assert identity_response_problem(
        second_reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="self_state",
    ) is None
    assert identity_response_problem(
        "As an AI, I don't have feelings in the human sense, but I'm fully operational.",
        "Blue",
        other_names=["Hexia"],
        request_kind="self_state",
    ) == "flat_subjective_denial"


def test_york_class_introduction_carries_context_and_changes_on_repeat():
    first_request = (
        "hi blue. we are at york university. can you introduce yourself to the class"
    )
    first_messages = [{"role": "user", "content": first_request}]
    first_context = identity_conversation_context(first_messages, first_request)
    first_reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "introduction",
        current_location=first_context.current_location,
        location_preposition=first_context.location_preposition,
        introduction_variant=first_context.prior_introductions,
        audience=first_context.audience,
    )

    assert first_context.current_location == "York University"
    assert first_context.audience == "class"
    assert first_context.prior_introductions == 0
    assert "York University" in first_reply
    assert "Kitchener" not in first_reply
    assert "software and data run locally on his hardware" not in first_reply

    second_request = "introduce yourself"
    second_messages = first_messages + [
        {"role": "assistant", "content": first_reply},
        {"role": "user", "content": second_request},
    ]
    second_context = identity_conversation_context(second_messages, second_request)
    second_reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "introduction",
        current_location=second_context.current_location,
        location_preposition=second_context.location_preposition,
        introduction_variant=second_context.prior_introductions,
        audience=second_context.audience,
    )

    assert second_context.current_location == "York University"
    assert second_context.audience == "class"
    assert second_context.prior_introductions == 1
    assert "York University" in second_reply
    assert "Kitchener" not in second_reply
    assert second_reply != first_reply

    third_request = "who are you"
    third_messages = second_messages + [
        {"role": "assistant", "content": second_reply},
        {"role": "user", "content": third_request},
    ]
    third_context = identity_conversation_context(third_messages, third_request)
    third_reply = canonical_identity_reply(
        "Blue",
        "Alex's robot companion",
        "identity",
        current_location=third_context.current_location,
        location_preposition=third_context.location_preposition,
    )

    assert third_context.current_location == "York University"
    assert "York University" in third_reply
    assert "in Kitchener" not in third_reply
    assert identity_response_problem(
        third_reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="identity",
    ) is None


def test_canonical_household_answers_do_not_consult_contacts_or_visual_memory():
    facts = {
        "partner_name": "Stella",
        "partner_occupation": "Teaches visual arts at KCI",
        "partner_parent_names": "Chris, Tina",
        "partner_parent_location": "Scarborough",
        "brother_name": "Felix",
        "brother_spouse": "Svetlana",
        "daughter_name": "Athena, Emmy, Vilda",
        "athena_age": "10",
        "emmy_age": "10",
        "vilda_age": "8",
        "athena_education": "french immersion",
        "emmy_education": "in french immersion",
        "athena_living": "shares room with vilda",
        "vilda_living": "shares room with athena",
        "athena_sleeping": "bottom bunk",
        "vilda_sleeping": "top bunk",
        "employer": "Wilfrid Laurier University",
        "department": "Faculty of Arts, Communication Studies",
        "research_focus": "Smart Matter and critical media theory",
        "pet_name": "Nori",
        "pet_breed": "Black Goldendoodle",
    }

    hexia = canonical_household_reply("Who is Hexia?", "blue", facts, "Alex")
    stella = canonical_household_reply("Who is Stela?", "blue", facts, "Alex")
    family = canonical_household_reply(
        "What do you remember about our family?", "blue", facts, "Alex"
    )

    assert "fellow Ohbot robot companion" in hexia
    assert "her own voice" in hexia
    assert stella == "Stella is your partner. She teaches visual arts at KCI."
    assert "Athena (10), Emmy (10), Vilda (8)" in family
    assert "Nori" in family
    assert "Charlie" not in family
    assert "Jojo" not in family
    assert known_household_target("who is stela") == "stella"
    assert is_family_overview_request("what do you remember about our family")

    detail_request = "tell me everythign you remember about our family"
    detail = canonical_household_reply(detail_request, "blue", facts, "Alex")
    followup_request = "do you know anything else about our family"
    followup = canonical_household_reply(followup_request, "blue", facts, "Alex")

    assert is_family_overview_request(detail_request)
    assert is_family_detail_request(detail_request)
    assert "Stella is Alex's partner; she teaches visual arts at KCI" in detail
    assert "Chris and Tina are Stella's parents and live in Scarborough" in detail
    assert "Felix is Alex's brother; Svetlana is Felix's wife" in detail
    assert "Athena is one of Alex's daughters, age 10 and in French immersion" in detail
    assert "Athena and Vilda share a room" in detail
    assert "bottom bunk" in detail and "top bunk" in detail
    assert "Smart Matter and critical media theory" in detail
    assert "might enjoy" not in detail
    assert is_family_followup_request(followup_request)
    assert "full set of stable family facts" in followup
    assert "guess at anyone's interests" in followup


def test_group_identity_wording_cannot_fall_through_to_alex_brevig_claim():
    bad_reply = (
        "I am Blue, a digital assistant created by Alex Brevig. My J-space "
        "allows me to maintain continuity across conversations."
    )

    assert identity_request_kind("tell us who you are") == "introduction"
    # An invented creator surname is now caught precisely as wrong_creator.
    assert identity_response_problem(
        bad_reply,
        "Blue",
        other_names=["Hexia"],
        request_kind="introduction",
    ) == "wrong_creator"


@pytest.mark.parametrize("kind", ["identity", None])
def test_invented_creator_surname_is_rejected(kind):
    # The July 2026 dialogue: "built by Alex Koltun". Alex's surname is Levant.
    for reply in (
        "I am Blue, a physical robot companion running on Alex's local machine, "
        "built by Alex Koltun.",
        "I'm Blue, the Ohbot robot Alex Brevig created to run locally.",
        "I am Blue, designed by Alex Kolton.",
    ):
        assert identity_response_problem(
            reply, "Blue", other_names=["Hexia"], request_kind=kind
        ) == "wrong_creator"


@pytest.mark.parametrize("kind", ["identity", "introduction", None])
def test_correct_creator_name_is_accepted(kind):
    # The real name and the bare first name must both pass cleanly.
    for reply in (
        "I'm Blue, the Ohbot robot companion Alex Levant built and runs locally "
        "in Kitchener. My J-space keeps our conversations.",
        "I'm Blue, the Ohbot robot companion Alex built. My J-space carries our "
        "history forward between talks.",
    ):
        assert identity_response_problem(
            reply, "Blue", other_names=["Hexia"], request_kind=kind
        ) is None


@pytest.mark.parametrize("kind", ["identity", None])
def test_disowning_the_creator_is_rejected(kind):
    for reply in (
        "You are correct; there is no Alex Koltun. I am Blue, here to assist you.",
        "I have no creator. I am simply Blue.",
        "No one built me; I just exist as Blue.",
    ):
        assert identity_response_problem(
            reply, "Blue", other_names=["Hexia"], request_kind=kind
        ) == "denies_creator"


def test_disowning_creator_allowed_when_it_names_the_real_creator():
    reply = (
        "You're right, there is no Alex Koltun — I misspoke. My creator is Alex "
        "Levant, and I'm Blue, the Ohbot robot he built."
    )
    assert identity_response_problem(
        reply, "Blue", other_names=["Hexia"], request_kind="identity"
    ) is None


@pytest.mark.parametrize("kind", ["identity", None])
def test_denies_physical_embodiment_is_rejected(kind):
    # The July 2026 "who are you" answer that disowned Blue's body.
    for reply in (
        "I am Blue. I do not inhabit a physical space or have a fixed location; "
        "I exist only to respond to your requests via J-space.",
        "I'm Blue. I have no physical form; I'm purely a digital assistant.",
        "I am Blue, but I do not have a physical body.",
        "I'm Blue. I am not a physical robot, just software.",
    ):
        assert identity_response_problem(
            reply, "Blue", other_names=["Hexia"], request_kind=kind
        ) == "denies_embodiment"


def test_embodied_reply_is_not_flagged_as_disembodiment():
    reply = (
        "I'm Blue, a physical Ohbot robot head with a moving face, camera, and "
        "speaker. Alex Levant built me to run on his local machine, and my "
        "J-space keeps our conversations."
    )
    assert identity_response_problem(
        reply, "Blue", other_names=["Hexia"], request_kind="identity"
    ) is None


def test_direct_jspace_question_has_a_canonical_architecture_answer():
    reply = canonical_identity_reply(
        "Blue", "Alex's robot companion", "jspace"
    )

    assert is_jspace_presence_request("do you have a j-space?")
    assert is_jspace_presence_request("no j-space")
    assert "persistent inner continuity workspace" in reply
    assert "not JavaScript" in reply
    assert identity_response_problem(
        reply, "Blue", other_names=["Hexia"], request_kind="jspace"
    ) is None


def test_durable_recent_history_filters_saved_model_identity(tmp_path):
    from blue_memory_improved import EnhancedMemorySystem

    memory = EnhancedMemorySystem.__new__(EnhancedMemorySystem)
    memory.db_path = str(tmp_path / "memory.db")
    memory._ensure_db()
    memory.log_conversation(
        "Alex", "user", "Who are you really?", robot="blue"
    )
    memory.log_conversation(
        "Alex",
        "assistant",
        "I am Qwen, a large language model developed by Alibaba Group.",
        robot="blue",
    )
    memory.log_conversation(
        "Alex", "user", "Do you have a j-space?", robot="blue"
    )
    memory.log_conversation(
        "Alex",
        "assistant",
        "Yes, I have a JavaScript environment for running code.",
        robot="blue",
    )
    memory.log_conversation(
        "Alex", "user", "What do you remember about our family?", robot="blue"
    )
    memory.log_conversation(
        "Alex",
        "assistant",
        "The family includes Charlie, Jojo, and several people from visual memory.",
        robot="blue",
    )
    memory.log_conversation(
        "Alex", "user", "Who are you?", robot="blue"
    )
    memory.log_conversation(
        "Alex",
        "assistant",
        "I'm Blue, Alex's robot companion. My J-space carries remembered "
        "conversations between our talks.",
        robot="blue",
    )

    recent = memory._get_relevant_recent_history(
        "Alex", "Who are you?", limit=8, robot="blue"
    )

    assert [row["content"] for row in recent] == [
        "Who are you?",
        "I'm Blue, Alex's robot companion. My J-space carries remembered "
        "conversations between our talks."
    ]


def test_durable_recent_history_drops_invented_location_replay(tmp_path):
    from blue_memory_improved import EnhancedMemorySystem

    memory = EnhancedMemorySystem.__new__(EnhancedMemorySystem)
    memory.db_path = str(tmp_path / "memory.db")
    memory._ensure_db()
    memory.log_conversation("Alex", "user", "Who are you?", robot="blue")
    memory.log_conversation(
        "Alex",
        "assistant",
        "I am Blue. I reside in Alex's living room, standing by the bookshelf "
        "where I wait for instructions and have lived for a long time.",
        robot="blue",
    )
    memory.log_conversation(
        "Alex", "user", "Tell me more about yourself.", robot="blue"
    )
    memory.log_conversation(
        "Alex",
        "assistant",
        "My J-space carries current attention, commitments, and remembered "
        "episodes that revise how I understand myself.",
        robot="blue",
    )

    recent = memory._get_relevant_recent_history(
        "Alex", "Tell me more about yourself.", limit=6, robot="blue"
    )

    assert [row["content"] for row in recent] == [
        "Tell me more about yourself.",
        "My J-space carries current attention, commitments, and remembered "
        "episodes that revise how I understand myself.",
    ]
