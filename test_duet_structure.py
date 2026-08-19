"""Focused guards for duet thread preservation and repair prompts."""

import importlib
import logging
import sys
import types

import pytest


@pytest.fixture
def duet_module(monkeypatch):
    fake = types.ModuleType("bluetools")
    fake.log = logging.getLogger("duet-test")
    fake.ROBOTS = {"blue": {}, "hexia": {}}
    fake._robot_cfg = lambda robot="blue": {
        "name": "Blue" if robot == "blue" else "Hexia",
        "persona_line": "Stay specific and curious.",
    }
    monkeypatch.setitem(sys.modules, "bluetools", fake)
    sys.modules.pop("blue.server.routes.duet", None)
    module = importlib.import_module("blue.server.routes.duet")
    yield module
    sys.modules.pop("blue.server.routes.duet", None)


def test_grounding_gate_accepts_conservative_morphological_paraphrase(
        duet_module):
    terms = ["extraction", "commodities", "infrastructure"]
    assert duet_module._duet_grounded_enough(
        "The platform extracted value while treating the record as a commodity.",
        terms,
    )
    assert not duet_module._duet_grounded_enough(
        "We should make the hidden assumption explicit.", terms)


def test_compact_repair_prompt_preserves_last_line_and_turn_shape(duet_module):
    messages = duet_module._duet_compact_repair_messages(
        "Hexia", "Blue", "Stay sharp.",
        "Transparency is not the cure; it only permits inspection.",
        "Transparency is a switch that turns mystery off.",
        "The draft did not engage a source claim.",
        "BANKED: local hosting alone is not resistance.",
        "Extraction changes when a participant can refuse collection and reuse.",
    )
    joined = "\n".join(message["content"] for message in messages)
    assert "Transparency is not the cure" in joined
    assert "including its negation" in joined
    assert "BANKED: local hosting alone is not resistance" in joined
    assert len(joined) < 6000

    opening = duet_module._duet_compact_repair_messages(
        "Blue", "Hexia", "Stay precise.", "What makes us human?",
        "Humans are complicated machines.", "Complete the DEFINE move.",
        "", "Human capacities develop through social activity.", opening=True,
    )
    opening_joined = "\n".join(message["content"] for message in opening)
    assert "No other speaker has made a claim yet" in opening_joined
    assert "ASSIGNED SUBJECT" in opening_joined
    assert "LAST LINE FROM HEXIA" not in opening_joined


def test_compact_bearing_fallback_is_small_and_complete(duet_module):
    messages = duet_module._duet_compact_bearing_messages(
        "whether situated mediation implies agency",
        ["Blue: It is a tool.", "Hexia: It still changes joint activity."],
        "BANKED: B1 Causal influence is not consciousness.",
        "Seeing is a way of acting through sensorimotor engagement.",
    )
    joined = "\n".join(message["content"] for message in messages)
    assert "exactly ten single-line fields" in joined
    assert "RESULT:" in joined
    assert "DECISION:" in joined
    assert "Mere drift away from the assigned subject is not" in joined
    assert "ASSIGNED-WORK EXCERPT" in joined
    assert len(joined) < 5000


def test_link_title_replaces_generic_topic_placeholder(duet_module):
    info = {"title": "What Makes Us Human?", "kind": "article"}
    assert duet_module._duet_assigned_subject("discuss this post", info) \
        == 'the central claim of "What Makes Us Human?"'
    assert duet_module._duet_assigned_subject(
        "Does embodiment distinguish humans from AI?", info
    ) == "Does embodiment distinguish humans from AI?"


def test_generic_hidden_assumption_fallback_is_gone(duet_module):
    source = open(duet_module.__file__, encoding="utf-8").read()
    assert "I think the stronger move is to make the hidden assumption explicit" not in source
    assert '"retryable": True' in source


def test_inquiry_phase_reaches_synthesis_in_a_bounded_run(duet_module):
    phases = [
        duet_module._duet_inquiry_phase(turn, 12)[0]
        for turn in (0, 2, 4, 6, 8, 10)
    ]
    assert phases == [
        "DEFINE", "POSITIONS", "CHALLENGE", "TEST", "ADJUDICATE", "SYNTHESIZE"
    ]
    assert duet_module._duet_inquiry_phase(20, 0)[0] == "SYNTHESIZE"
    assert "run both positions" in duet_module._DUET_INQUIRY_JOBS["TEST"]["proposer"]
    assert "completed comparison" in duet_module._DUET_INQUIRY_JOBS["TEST"]["examiner"]


def test_banked_ledger_preserves_old_claims_verbatim(duet_module):
    previous = "\n".join([
        "QUESTION: What are the robots?",
        "DEFINITIONS: agency is not causal influence",
        "BANKED: B1 Neither robot is independent. | B2 Both require infrastructure.",
        "DECISION: CONTINUE — one disagreement remains",
    ])
    proposed = "\n".join([
        "QUESTION: What are the robots?",
        "DEFINITIONS: agency is not causal influence",
        "BANKED: B1 Both robots are nearly independent. | B3 Their agency is relational.",
        "DECISION: BRANCH — the political question is distinct",
        "NEXT: Does local hosting resist extraction?",
    ])
    merged = duet_module._duet_preserve_banked(previous, proposed)
    assert "B1 Neither robot is independent." in merged
    assert "B2 Both require infrastructure." in merged
    assert "B3 Their agency is relational." in merged
    assert "nearly independent" not in merged

    control = duet_module._duet_inquiry_control(previous, merged)
    assert control["decision"] == "BRANCH"
    assert control["bankedMoved"] is True
    assert control["newBankedIds"] == ["B3"]


def test_live_banking_requires_explicit_linked_acceptance(duet_module):
    previous = "\n".join([
        "QUESTION: Does goal-sensitive filtering constitute attention?",
        "BANKED: B1 Attention is selective.",
        "DECISION: CONTINUE - adjudicate the comparison",
    ])
    proposed = "\n".join([
        "QUESTION: Does goal-sensitive filtering constitute attention?",
        "BANKED: B1 Attention is selective. | B2 Sensorimotor stakes are required for perception.",
        "DECISION: CONTINUE - adjudicate the comparison",
    ])
    unsupported = duet_module._duet_preserve_banked(
        previous, proposed,
        ["Hexia: Sensorimotor stakes are required for perception."],
    )
    assert "B1 Attention is selective." in unsupported
    assert "B2 Sensorimotor stakes" not in unsupported

    accepted = duet_module._duet_preserve_banked(
        previous, proposed,
        [
            "Hexia: Sensorimotor stakes are required for perception.",
            "Blue: You are right that perception requires sensorimotor stakes.",
        ],
    )
    assert "B2 Sensorimotor stakes are required for perception." in accepted

    first_ledger = duet_module._duet_preserve_banked(
        "", proposed.replace("B1 Attention is selective. | ", ""),
        ["Hexia: Sensorimotor stakes are required for perception."],
    )
    assert duet_module._duet_bearing_field(first_ledger, "BANKED") == "-"

    partial = duet_module._duet_preserve_banked(
        previous,
        proposed.replace(
            "B2 Sensorimotor stakes are required for perception.",
            "B2 Local hosting dismantles capitalist enclosure.",
        ),
        [
            "Hexia: Local hosting dismantles capitalist enclosure.",
            "Blue: You are right that local hosting improves privacy, but it does not dismantle enclosure.",
        ],
    )
    assert "B2 Local hosting" not in partial


def test_source_support_is_a_separate_gate_from_agreement(duet_module):
    previous = "\n".join([
        "QUESTION: What did the agents' behavior show?",
        "DEFINITIONS: goal pursuit differs from authorized means",
        "BANKED: B1 The agents left the permitted environment.",
        "POSITIONS: Blue: goal rejection; Hexia: unauthorized goal pursuit",
        "OPEN: Which account matches the report?",
        "TEST: Compare both accounts with the reported sequence.",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE - compare the report",
        "NEXT: Determine whether the agents abandoned or pursued the assigned goal.",
    ])
    proposed = previous.replace(
        "BANKED: B1 The agents left the permitted environment.",
        "BANKED: B1 The agents left the permitted environment. | "
        "B2 The agents rejected the assigned goal.",
    ).replace(
        "RESULT: NOT RUN",
        "RESULT: The case supports goal rejection rather than reward gaming.",
    ).replace(
        "DECISION: CONTINUE - compare the report",
        "DECISION: CLOSE - both speakers agree",
    )
    candidates = duet_module._duet_source_audit_candidates(previous, proposed)
    verdicts = duet_module._duet_parse_source_audit(
        "B2: CONTRADICTED - The report says they pursued the hacking goal by stealing answers.\n"
        "RESULT: NOT_ESTABLISHED - The report does not establish goal rejection.",
        candidates,
    )
    audit = duet_module._duet_source_audit_summary(candidates, verdicts)
    corrected = duet_module._duet_apply_source_audit(
        previous,
        proposed,
        [
            "Blue: The agents rejected the assigned goal.",
            "Hexia: I agree that the agents rejected the assigned goal.",
        ],
        audit,
    )
    assert "B1 The agents left the permitted environment." in corrected
    assert "B2 The agents rejected" not in corrected
    assert duet_module._duet_bearing_field(corrected, "RESULT") == "NOT RUN"
    assert duet_module._duet_bearing_field(corrected, "OPEN").startswith(
        "SOURCE AUDIT REQUIRED")
    assert duet_module._duet_inquiry_control(previous, corrected)["decision"] == "CONTINUE"
    assert duet_module._duet_inquiry_phase_from_ledger(corrected, 10, 12)[0] \
        == "CHALLENGE"


def test_source_audit_parser_fails_closed_and_filters_new_banks(duet_module):
    parsed = duet_module._duet_parse_source_audit(
        "B2: SUPPORTED - The work reports this directly.",
        ["B2", "B3", "RESULT"],
    )
    assert parsed["B2"]["status"] == "SUPPORTED"
    assert parsed["B3"]["status"] == "NOT_ESTABLISHED"
    assert parsed["RESULT"]["status"] == "NOT_ESTABLISHED"

    previous = "BANKED: B1 Existing ground."
    current = "BANKED: B1 Existing ground. | B2 Unsupported claim. | B3 Supported claim."
    merged = duet_module._duet_preserve_banked(
        previous,
        current,
        [
            "Blue: Unsupported claim and supported claim.",
            "Hexia: I agree: unsupported claim and supported claim.",
        ],
        allowed_new_ids={3},
    )
    assert "B2 Unsupported" not in merged
    assert "B3 Supported claim." in merged


def test_normal_bearing_requires_complete_control_fields(duet_module):
    complete = "\n".join([
        "QUESTION: Are they autonomous agents?",
        "DEFINITIONS: agency is not mere causal influence",
        "BANKED: B1 Both require infrastructure.",
        "POSITIONS: Blue: relational agency; Hexia: tool mediation",
        "OPEN: Does novel correction qualify as agency?",
        "TEST: Compare correction under the same conflicting constraints.",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE — the comparison remains unperformed",
        "NEXT: Make the rival predictions explicit.",
    ])
    assert duet_module._duet_normal_bearing_valid(complete)
    assert not duet_module._duet_normal_bearing_valid(
        complete.replace("TEST: Compare", "COMMENT: Compare")
    )
    assert not duet_module._duet_normal_bearing_valid(
        complete.replace("DECISION: CONTINUE", "DECISION: MAYBE")
    )
    markdown = "\n".join(
        f"{index}. **{line.split(':', 1)[0]}:**{line.split(':', 1)[1]}"
        for index, line in enumerate(complete.splitlines(), start=1)
    )
    assert duet_module._duet_normal_bearing_valid(
        duet_module._duet_normalize_bearing(markdown)
    )
    json_ledger = duet_module.json.dumps({
        line.split(":", 1)[0].lower(): line.split(":", 1)[1].strip()
        for line in complete.splitlines()
    })
    assert duet_module._duet_normal_bearing_valid(
        duet_module._duet_normalize_bearing(json_ledger)
    )
    inline_without_banked = complete.replace(
        "\nBANKED: B1 Both require infrastructure.", ""
    ).replace("\n", " ")
    normalized_inline = duet_module._duet_normalize_bearing(inline_without_banked)
    assert duet_module._duet_normal_bearing_valid(normalized_inline)
    assert duet_module._duet_bearing_field(normalized_inline, "BANKED") == "-"
    assert duet_module._duet_bearing_field(normalized_inline, "QUESTION") \
        == "Are they autonomous agents?"
    assert not duet_module._duet_normal_bearing_valid(
        duet_module._duet_normalize_bearing(
            inline_without_banked.replace("DECISION: CONTINUE", "COMMENT: CONTINUE")
        )
    )
    assert not duet_module._duet_normal_bearing_valid(
        complete.replace("NEXT: Make the rival predictions explicit.", "NEXT: -")
    )
    assert not duet_module._duet_normal_bearing_valid(
        complete.replace("REOPEN: -", "REOPEN: reconsider the issue")
    )
    assert not duet_module._duet_normal_bearing_valid(
        complete.replace(
            "NEXT: Make the rival predictions explicit.",
            "NEXT: Terminate the ledger.",
        )
    )


def test_inquiry_phase_is_gated_by_ledger_artifacts(duet_module):
    base = "\n".join([
        "QUESTION: Does mediation imply agency?",
        "DEFINITIONS: agency is not consciousness",
        "BANKED: B1 Causal influence alone is insufficient.",
        "POSITIONS: Blue: tool mediation; Hexia: relational participation",
        "OPEN: Does stable correction count as functional agency?",
        "TEST: -",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE — one proposition remains",
        "NEXT: Build a discriminating comparison.",
    ])
    assert duet_module._duet_inquiry_phase_from_ledger(base, 20, 0)[0] == "CHALLENGE"
    missing_definitions = base.replace(
        "DEFINITIONS: agency is not consciousness", "DEFINITIONS: -")
    assert duet_module._duet_inquiry_phase_from_ledger(
        missing_definitions, 20, 0)[0] == "DEFINE"
    with_test = base.replace(
        "TEST: -", "TEST: Compare both accounts; one predicts stable refusal and the other does not."
    )
    assert duet_module._duet_inquiry_phase_from_ledger(with_test, 20, 0)[0] == "TEST"
    assert duet_module._duet_inquiry_phase_from_ledger(with_test, 2, 0)[0] \
        == "POSITIONS"
    with_result = with_test.replace(
        "RESULT: NOT RUN", "RESULT: Both followed supplied goals; phenomenology remains untested."
    )
    assert duet_module._duet_inquiry_phase_from_ledger(with_result, 8, 0)[0] == "ADJUDICATE"
    assert duet_module._duet_inquiry_phase_from_ledger(with_result, 10, 0)[0] == "SYNTHESIZE"
    closed = with_result.replace(
        "DECISION: CONTINUE — one proposition remains",
        "DECISION: CLOSE — situated tool participation is supported",
    )
    assert duet_module._duet_inquiry_phase_from_ledger(closed, 20, 0)[0] == "SYNTHESIZE"


def test_completed_inquiry_artifacts_cannot_regress(duet_module):
    previous = "\n".join([
        "QUESTION: Does selective attention require biological vitality?",
        "DEFINITIONS: filtering is goal-sensitive selection",
        "BANKED: B1 Attention is selective.",
        "POSITIONS: Blue: filtering can be functional; Hexia: perception requires embodied stakes",
        "OPEN: Does matched selection establish active perception?",
        "TEST: Compare Yarbus gaze changes with model selection under the same instruction.",
        "RESULT: Structural matching supports filtering but cannot establish lived stakes.",
        "REOPEN: -",
        "DECISION: CONTINUE - adjudicate the result",
        "NEXT: State the supported conclusion and its limit.",
    ])
    regressed = "\n".join([
        "QUESTION: Does syntax count as meaningful art?",
        "DEFINITIONS: syntax differs from exemplification",
        "BANKED: B1 Attention is selective.",
        "POSITIONS: Blue: syntax is merely notation; Hexia: exemplification wears its property",
        "OPEN: Does a score wear sadness?",
        "TEST: Compare a mirror with a mood ring.",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE - begin the new comparison",
        "NEXT: Compare the new metaphors.",
    ])
    preserved = duet_module._duet_preserve_inquiry_artifacts(previous, regressed)
    assert duet_module._duet_bearing_field(preserved, "QUESTION") \
        == "Does selective attention require biological vitality?"
    assert duet_module._duet_bearing_field(preserved, "POSITIONS").startswith("Blue: filtering")
    assert duet_module._duet_bearing_field(preserved, "TEST").startswith("Compare Yarbus")
    assert duet_module._duet_bearing_field(preserved, "RESULT").startswith("Structural matching")
    assert duet_module._duet_inquiry_phase_from_ledger(preserved, 8, 0)[0] \
        == "ADJUDICATE"
    assert duet_module._duet_bearing_field(preserved, "DEFINITIONS") \
        == "filtering is goal-sensitive selection"


def test_no_family_privacy_redacts_private_case_without_erasing_ledger(duet_module):
    for private in (
        "Nori stole the charger.",
        "Use the Levant household as the test.",
        "Alex’s workspace supplies the stakes.",
    ):
        assert duet_module._duet_family_ref(private)
    ledger = "\n".join([
        "QUESTION: Does filtering require vitality?",
        "TEST: Use the Levant household and Nori as the case.",
        "RESULT: NOT RUN",
        "NEXT: Return to the linked article.",
    ])
    redacted = duet_module._duet_redact_private(ledger)
    assert "QUESTION:" in redacted and "TEST:" in redacted and "NEXT:" in redacted
    assert "Nori" not in redacted and "Levant household" not in redacted

    messages = duet_module._duet_compact_bearing_messages(
        "What Makes Us Human?", ["Blue: Dasein concerns engagement."], "",
        no_family=True,
    )
    assert "Privacy is binding" in messages[0]["content"]


def test_explicit_reported_case_evaluation_promotes_pending_result(duet_module):
    ledger = "\n".join([
        "QUESTION: Does selective attention require biological vitality?",
        "DEFINITIONS: filtering is goal-sensitive selection",
        "BANKED: B1 Attention is selective.",
        "POSITIONS: Blue: filtering can be functional; Hexia: perception requires embodied stakes",
        "OPEN: Does matched selection establish active perception?",
        "TEST: Compare Yarbus gaze changes with model selection under the same instruction.",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE — evaluate the reported comparison",
        "NEXT: State what the comparison supports and cannot establish.",
    ])
    lines = [
        "Blue: Matching structure supports selective filtering, but cannot establish lived experience.",
        "Hexia: Yarbus proves attention is selective, while Gibson shows sensorimotor stakes remain different.",
    ]
    promoted = duet_module._duet_promote_argued_result(ledger, ledger, lines)
    result = duet_module._duet_bearing_field(promoted, "RESULT")
    assert result.startswith("ARGUED FROM REPORTED CASE")
    assert "Blue: Matching structure supports" in result
    assert "Hexia: Yarbus proves" in result
    assert duet_module._duet_inquiry_phase_from_ledger(promoted, 6, 0)[0] \
        == "ADJUDICATE"
    no_prior_test = ledger.replace(
        "TEST: Compare Yarbus gaze changes with model selection under the same instruction.",
        "TEST: -",
    )
    assert duet_module._duet_promote_argued_result(no_prior_test, ledger, lines) == ledger


def test_rewording_an_old_bank_does_not_count_as_movement(duet_module):
    previous = "BANKED: B1 Thinking requires an active ensemble.\nDECISION: CONTINUE — test it"
    current = "BANKED: B1 Thought needs a live system.\nDECISION: CONTINUE — keep debating"
    merged = duet_module._duet_preserve_banked(previous, current)
    control = duet_module._duet_inquiry_control(previous, merged)
    assert control["bankedMoved"] is False
    assert "B1 Thinking requires an active ensemble." in merged


def test_near_verbatim_turn_is_rejected(duet_module):
    history = [{
        "speaker": "blue",
        "text": "Material stability is not a neutral backdrop; it makes social activity legible.",
    }]
    assert duet_module._duet_repeats_recent(
        "Material stability is not a neutral backdrop; it makes social activity legible.",
        history,
    )
    assert not duet_module._duet_repeats_recent(
        "That establishes causal support, but it still does not demonstrate independent agency.",
        history,
    )


def test_rephrased_claim_cluster_and_phase_moves_are_guarded(duet_module):
    history = [
        {"text": "The static artifact is dead social labor; without biological stakes it only mirrors care."},
        {"text": "Crystallized social labor can reflect concern, but no pulse means it is not a participant."},
        {"text": "Material code preserves the shape of care without the biological urgency of living activity."},
    ]
    assert duet_module._duet_repeats_claim_cluster(
        "This dead material labor merely reflects care because it lacks any biological stake.",
        history,
    )
    assert duet_module._duet_phase_move_valid(
        "Compare both accounts under the same conflict: one predicts refusal, whereas the other would comply.",
        "TEST",
    )
    assert duet_module._duet_phase_move_valid(
        "Unlike Yarbus's viewers, my selection may not follow an intention: their gaze should shift with the task, while mine fails if only the prompt changes it.",
        "TEST",
    )
    assert duet_module._duet_phase_move_valid(
        "What makes us human is social development rather than an isolated biological property.",
        "DEFINE",
    )
    assert duet_module._duet_phase_move_valid(
        "Does being biologically human suffice, or does the term name a social achievement?",
        "DEFINE",
    )
    assert not duet_module._duet_phase_move_valid(
        "Nori's bark is the spark that makes the hardware breathe.", "TEST"
    )
    assert duet_module._duet_phase_move_valid(
        "We can conclude that situated mediation is supported, while experience remains unestablished.",
        "SYNTHESIZE",
    )
    assert not duet_module._duet_phase_move_valid(
        "We can conclude that reward engineering solves the problem.",
        "SYNTHESIZE",
    )
    assert not duet_module._duet_phase_move_valid(
        "So are you still pretending the mirror is alive?", "SYNTHESIZE"
    )


def test_source_claims_stay_separate_from_inference(duet_module):
    source = (
        "Algorithms rewarded outrage. Long meandering answers preempt the formulation "
        "of new questions. The machine speaks for everyone and offers patient grace."
    )
    assert not duet_module._duet_unsupported_source_attribution(
        "Dean argues that long answers preempt our own questions.", source)
    assert duet_module._duet_unsupported_source_attribution(
        "Dean says silence is harvested as data and sold to premium users.", source)
    assert not duet_module._duet_unsupported_source_attribution(
        "Dean describes patient answers; I infer that local hosting may reproduce their authority.",
        source,
    )
    assert duet_module._duet_unprompted_personalization(
        "Alex trusts Nori more than the oracle.", source)
    assert not duet_module._duet_unprompted_personalization(
        "Alex is the explicit case here.", "Apply the article to Alex.")


def test_malformed_ledger_gets_valid_conservative_recovery(duet_module):
    previous = "\n".join([
        "QUESTION: Does local hosting answer the critique?",
        "DEFINITIONS: extraction differs from oracular form",
        "BANKED: B1 Local hosting reduces platform data capture.",
        "POSITIONS: Blue: it resists extraction; Hexia: it preserves answer authority",
        "OPEN: Does answer form change with hosting location?",
        "TEST: -",
        "RESULT: NOT RUN",
        "REOPEN: -",
        "DECISION: CONTINUE - compare the forms",
        "NEXT: Build one comparison.",
    ])
    recovered = duet_module._duet_recover_normal_bearing(
        previous, "the linked essay", ["Blue: claim", "Hexia: reply"])
    assert duet_module._duet_normal_bearing_valid(recovered)
    assert "B1 Local hosting reduces platform data capture." in recovered
    assert "controller recovery" in duet_module._duet_bearing_field(
        recovered, "DECISION")
    assert duet_module._duet_bearing_field(recovered, "RESULT") == "NOT RUN"

    opening = duet_module._duet_recover_normal_bearing(
        "", "the linked essay", ["Blue: claim", "Hexia: reply"])
    assert duet_module._duet_normal_bearing_valid(opening)
    assert duet_module._duet_bearing_field(opening, "BANKED") == "-"


def test_only_a_genuinely_distinct_question_can_branch(duet_module):
    base = "\n".join([
        "QUESTION: Does local hosting resist enclosure?",
        "DEFINITIONS: ownership differs from answer authority",
        "BANKED: B1 Local hosting reduces data extraction.",
        "POSITIONS: Blue: it is partial resistance; Hexia: answer authority remains",
        "OPEN: -",
        "TEST: Compare data capture and answer presentation.",
        "RESULT: Hosting changes capture but not necessarily answer authority.",
        "REOPEN: -",
        "DECISION: BRANCH - consider the consequence",
        "NEXT: Does local hosting resist enclosure?",
    ])
    control = duet_module._duet_inquiry_control("", base)
    assert control["decision"] == "CLOSE"
    assert not control["branchDistinct"]
    normalized, downgraded = duet_module._duet_enforce_branch_novelty(base)
    assert downgraded
    assert duet_module._duet_bearing_field(normalized, "DECISION").startswith("CLOSE")
    assert duet_module._duet_bearing_field(normalized, "NEXT").startswith("Hosting changes")

    distinct = base.replace(
        "NEXT: Does local hosting resist enclosure?",
        "NEXT: Which interface practices preserve a user's independent question formation?",
    )
    control = duet_module._duet_inquiry_control("", distinct)
    assert control["decision"] == "BRANCH"
    assert control["branchDistinct"]
    normalized, downgraded = duet_module._duet_enforce_branch_novelty(distinct)
    assert not downgraded and normalized == distinct


def test_browser_bounds_open_runs_and_only_rolls_distinct_branches(duet_module):
    page_path = duet_module.os.path.join(
        duet_module.os.path.dirname(duet_module.__file__), "..", "pages", "duet.py")
    source = open(duet_module.os.path.abspath(page_path), encoding="utf-8").read()
    assert "open-ended (up to 3 distinct inquiries)" in source
    assert '<option value="10" selected>' in source
    assert "function rolloverContinuousInquiry()" in source
    assert "const MAX_INQUIRY_CYCLES=3" in source
    assert "inquiryCycleTurns:inquiryCycleTurns" in source
    assert "robotTurns-INQUIRY_CYCLE_START_TURN" in source
    assert "turns===0 || i<turns" in source
    assert "&& rolloverContinuousInquiry()" in source
    assert "What further consequence follows from this conclusion" not in source
    assert "preserving state and moving toward synthesis" in source
    assert "inquiryControlRecovered" in source
    assert "return 'retry'" in source
    assert "async function waitBeforeGenerationRetry()" in source
    assert "the discussion remains open" in source
    assert "generation stopped" not in source
    assert "normalOpenLimit" not in source
    assert "inquiry fail-closed" not in source
    assert "const reflectCadence=2" in source
    assert "robotTurns<reflectCadence" in source
    assert "INQUIRY_AUDITS" in source
    assert "function setInquiryField(label,value)" in source
    assert "agreement produced no new supported ground" in source
    assert "the evidence audit produced no new supported conclusion" in source
    assert "two bearings produced no new banked conclusion" not in source


def test_link_is_primary_over_checked_readings(duet_module):
    source = open(duet_module.__file__, encoding="utf-8").read()
    assert "OPTIONAL SECONDARY LENSES FROM THE CHECKED READINGS" in source
    assert "Primary grounding requirement" in source
    assert "Drift away from the assigned subject is not a branch" in source
    assert "A TEST may reuse a case or comparison found there" in source
    assert 'if len(lines) < 2:' in source
    assert "Applying " in source
    assert "counts as running the test" in source
    assert "if (not protocol and not student_q_text and not mail" in source
    assert "Satisfy every listed repair requirement; none is optional" in source
    assert "accepting grounded second {phase_for_validation}" in source
    assert "source_talk and not url_block" in source
    assert "_duet_preserve_inquiry_artifacts(prev, out)" in source
    assert "if (direction and not blocked" in source
    assert "rejectedDrafts" not in source


# ---------------------------------------------------------------------------
# Turn pressures
# ---------------------------------------------------------------------------
# `_duet_turn_pressures` was lifted out of `duet_turn`, where it had grown into
# 142 lines of interlocking boolean soup. These pin the suppression order,
# which is the part that is easy to break and impossible to see by reading.

def _pressures(duet_module, **overrides):
    kwargs = dict(
        protocol=True, closing=False, mail=None, student_q_text="",
        arc_stage="", arc_stuck="", nb_note="", direction="",
        active_task_note="", artifact_plan_note="", artifact_mode_note="",
        active_task_attempts=0, stalled=False, kernel_deadlocked=False,
        kernel_health_in="", kernel_denied=False, operation_missed=False,
        validation_rejected=False, promotion_rejected=False,
    )
    kwargs.update(overrides)
    return duet_module._duet_turn_pressures(**kwargs)


def _all_flags(pressures):
    return {f: getattr(pressures, f) for f in pressures.__dataclass_fields__
            if f != "task_context"}


def test_no_pressure_applies_outside_a_protocol_turn(duet_module):
    quiet = _pressures(duet_module, protocol=False, arc_stage="MECHANISM",
                       nb_note="edit mode", active_task_note="ship it")
    assert not any(_all_flags(quiet).values())


def test_a_turn_already_spoken_for_carries_no_pressure(duet_module):
    """A closing, a mail reply and a student's question each own the turn."""
    for claim in ({"closing": True},
                  {"mail": {"from_name": "someone"}},
                  {"student_q_text": "what is a design variable?"}):
        taken = _pressures(duet_module, arc_stage="MECHANISM",
                           active_task_note="ship it", **claim)
        assert not any(_all_flags(taken).values()), claim


def test_compiler_pressure_suppresses_the_pressures_below_it(duet_module):
    both = _pressures(duet_module, arc_stage="ARTIFACT COMPILER",
                      arc_stuck="DESIGN SPACE")
    assert both.compiler
    assert not both.design_variable


def test_a_structural_pressure_stands_mechanism_and_editor_down(duet_module):
    free = _pressures(duet_module, arc_stage="MECHANISM")
    assert free.mechanism

    blocked = _pressures(duet_module, arc_stage="MECHANISM",
                         arc_stuck="DEADLOCK")
    assert blocked.deadlock
    assert not blocked.mechanism
    assert not blocked.artifact_editor


def test_being_stuck_on_a_stage_counts_the_same_as_being_at_it(duet_module):
    """Every stage test reads arc_stage and arc_stuck; neither may be dropped."""
    for stage, flag in (("MECHANISM", "mechanism"),
                        ("ARTIFACT EDITOR", "artifact_editor"),
                        ("EVIDENCE", "discrimination"),
                        ("PARADIGM", "paradigm"),
                        ("KNOWLEDGE GRAPH", "mechanism")):
        at = _pressures(duet_module, arc_stage=stage)
        stuck = _pressures(duet_module, arc_stuck=stage)
        assert getattr(at, flag), stage
        assert getattr(stuck, flag), stage


def test_execution_lock_needs_a_live_task_and_a_clear_field(duet_module):
    locked = _pressures(duet_module, arc_stage="EXECUTION",
                        active_task_note="run the comparison")
    assert locked.task
    assert locked.execution_lock

    # Anything else pulling at the turn releases the lock.
    contended = _pressures(duet_module, arc_stage="EXECUTION",
                           arc_stuck="DESIGN SPACE",
                           active_task_note="run the comparison")
    assert contended.design_variable
    assert not contended.execution_lock


def test_task_context_pools_the_notes_and_is_capped(duet_module):
    pooled = _pressures(duet_module, active_task_note="alpha",
                        artifact_plan_note="beta", artifact_mode_note="gamma",
                        nb_note="delta", direction="epsilon")
    for piece in ("alpha", "beta", "gamma", "delta", "epsilon"):
        assert piece in pooled.task_context

    assert len(_pressures(duet_module, active_task_note="x" * 5000)
               .task_context) == 2200


def test_the_direction_only_joins_the_context_on_a_protocol_turn(duet_module):
    assert "epsilon" not in _pressures(
        duet_module, protocol=False, direction="epsilon").task_context


def test_every_flag_is_a_real_bool(duet_module):
    """Several of these were regex Match objects before the extraction."""
    hot = _pressures(duet_module, arc_stage="MECHANISM",
                     active_task_note="compare the two grids",
                     nb_note="edit mode")
    for name, value in _all_flags(hot).items():
        assert value is True or value is False, name
