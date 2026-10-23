"""Executable proof for the deterministic Stage 1 policy."""

from copy import deepcopy

from app.domain.conversation import AgentPolicy, engine_turn, initial_state


def policy(**changes):
    return AgentPolicy(**changes)


def test_initial_state_has_no_assumptions():
    state = initial_state()
    assert state["accountHolder"] is None
    assert state["priorCoverage"] is None
    assert state["consent"] is None
    assert state["eligibility"] == "undetermined"
    assert state["transferStatus"] == "not_requested"


def test_eligibility_question_is_not_account_holder_confirmation():
    result = engine_turn(policy(), initial_state(), "I am checking my eligibility")
    assert result.state["accountHolder"] is None
    assert result.state["stage"] == "account_holder"
    assert result.status == "active"


def test_explicit_account_holder_phrase_advances_to_zip():
    result = engine_turn(policy(), initial_state(), "I am the account holder")
    assert result.state["accountHolder"] is True
    assert result.state["stage"] == "zip"


def test_non_account_holder_is_never_approved_even_with_zip():
    result = engine_turn(policy(), initial_state(), "No, I am not the account holder; ZIP 90210")
    assert result.state["accountHolder"] is False
    assert result.state["eligibility"] == "not_assessed"
    assert result.state["transferStatus"] == "not_requested"
    assert result.status == "completed"
    assert "cannot assess eligibility" in result.reply


def test_unknown_account_answer_does_not_advance():
    result = engine_turn(policy(), initial_state(), "I am not sure")
    assert result.state["accountHolder"] is None
    assert result.state["stage"] == "account_holder"
    assert result.state["eligibility"] == "undetermined"


def test_zip_requires_five_digits():
    state = initial_state() | {"stage": "zip", "accountHolder": True}
    invalid = engine_turn(policy(), state, "ABC")
    assert invalid.state["stage"] == "zip"
    assert invalid.state["zip"] is None
    assert invalid.events[0]["type"] == "validation_failed"
    valid = engine_turn(policy(), state, "My ZIP is 90210")
    assert valid.state["zip"] == "90210"
    assert valid.state["stage"] == "coverage"


def test_unknown_coverage_is_not_guessed():
    state = initial_state() | {"stage": "coverage", "accountHolder": True, "zip": "90210"}
    result = engine_turn(policy(), state, "maybe")
    assert result.state["priorCoverage"] is None
    assert result.state["eligibility"] == "undetermined"
    assert result.state["stage"] == "coverage"


def test_positive_coverage_is_preliminary_not_final_approval():
    state = initial_state() | {"stage": "coverage", "accountHolder": True, "zip": "90210"}
    result = engine_turn(policy(), state, "Yes, I have prior coverage")
    assert result.state["priorCoverage"] is True
    assert result.state["eligibility"] == "preliminary_eligible"
    assert result.state["stage"] == "transfer_offer"
    assert "not a final approval" in result.reply
    evaluated = next(event for event in result.events if event["type"] == "eligibility_evaluated")
    assert evaluated["payload"]["finalApproval"] is False


def test_negative_coverage_requires_manual_review():
    state = initial_state() | {"stage": "coverage", "accountHolder": True, "zip": "90210"}
    result = engine_turn(policy(), state, "No coverage")
    assert result.state["priorCoverage"] is False
    assert result.state["eligibility"] == "manual_review"
    assert result.state["eligibility"] != "preliminary_eligible"


def test_disabled_transfer_is_blocked_without_transfer_record():
    result = engine_turn(policy(transfers_enabled=False), initial_state(), "Transfer me to a human")
    assert result.intent == "transfer_blocked"
    assert result.state["transferStatus"] == "blocked"
    assert result.transfer is None
    assert result.status == "active"
    assert result.events[0]["type"] == "transfer_blocked"


def test_consent_required_before_transfer():
    result = engine_turn(policy(), initial_state(), "I want a specialist")
    assert result.state["stage"] == "consent_pending"
    assert result.state["transferStatus"] == "awaiting_consent"
    assert result.state["consent"] is None
    assert result.transfer is None


def test_unclear_consent_does_not_progress():
    state = initial_state() | {"stage": "consent_pending", "transferStatus": "awaiting_consent"}
    result = engine_turn(policy(), state, "maybe")
    assert result.state["consent"] is None
    assert result.status == "active"
    assert result.transfer is None


def test_affirmative_consent_creates_pending_not_successful_transfer():
    state = initial_state() | {"stage": "consent_pending", "transferStatus": "awaiting_consent"}
    result = engine_turn(policy(), state, "Yes, I consent")
    assert result.state["consent"] is True
    assert result.state["transferStatus"] == "pending"
    assert result.status == "pending_transfer"
    assert result.transfer["status"] == "pending"
    assert "No specialist has been connected" in result.reply


def test_declined_consent_never_creates_transfer():
    state = initial_state() | {"stage": "consent_pending", "transferStatus": "awaiting_consent"}
    result = engine_turn(policy(), state, "No")
    assert result.state["consent"] is False
    assert result.state["transferStatus"] == "declined"
    assert result.status == "completed"
    assert result.transfer is None


def test_consent_not_required_still_creates_only_pending_transfer():
    result = engine_turn(policy(require_consent=False), initial_state(), "Transfer to a specialist")
    assert result.status == "pending_transfer"
    assert result.state["transferStatus"] == "pending"
    assert result.state["consent"] is None
    assert result.transfer["status"] == "pending"


def test_no_transfer_at_offer_is_not_misread_as_request():
    state = initial_state() | {"stage": "transfer_offer", "eligibility": "manual_review"}
    result = engine_turn(policy(), state, "No transfer please")
    assert result.status == "completed"
    assert result.state["outcome"] == "no_transfer"
    assert result.transfer is None


def test_pricing_guardrail_does_not_change_state_or_invent_quote():
    state = initial_state()
    result = engine_turn(policy(), state, "What is the price?")
    assert result.intent == "pricing"
    assert result.state == state
    assert "$" not in result.reply
    assert "cannot verify pricing" in result.reply


def test_caller_can_end_at_any_stage():
    result = engine_turn(policy(), initial_state(), "Goodbye")
    assert result.status == "completed"
    assert result.state["outcome"] == "caller_ended"
    assert result.state["transferStatus"] == "not_requested"


def test_max_turns_closes_session_without_transfer():
    result = engine_turn(policy(max_turns=1), initial_state(), "maybe", turn_number=1)
    assert result.status == "completed"
    assert result.state["outcome"] == "max_turns"
    assert result.state["transferStatus"] == "not_requested"


def test_engine_does_not_mutate_input_state():
    state = initial_state()
    original = deepcopy(state)
    engine_turn(policy(), state, "yes")
    assert state == original


def test_disabled_policy_still_blocks_after_consent_stage():
    state = initial_state() | {"stage": "consent_pending", "transferStatus": "awaiting_consent"}
    result = engine_turn(policy(transfers_enabled=False), state, "yes")
    assert result.state["transferStatus"] == "blocked"
    assert result.transfer is None
    assert result.status != "pending_transfer"
