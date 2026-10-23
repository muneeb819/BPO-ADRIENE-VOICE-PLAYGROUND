"""Deterministic intake policy.

This module has no database, network, provider, or framework dependencies. Every
business decision is testable without mocking external services.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class AgentPolicy:
    transfers_enabled: bool = True
    require_consent: bool = True
    max_turns: int = 20
    purpose: str = "Inbound service qualification"
    tone: str = "professional"


@dataclass
class EngineResult:
    reply: str
    intent: str
    state: dict[str, Any]
    status: str = "active"
    events: list[dict[str, Any]] = field(default_factory=list)
    transfer: dict[str, str] | None = None


def initial_state() -> dict[str, Any]:
    """State after the configured greeting has been issued."""
    return {
        "stage": "account_holder",
        "accountHolder": None,
        "zip": None,
        "priorCoverage": None,
        "eligibility": "undetermined",
        "consent": None,
        "transferStatus": "not_requested",
        "outcome": None,
    }


def _yes_no(text: str) -> str:
    """Return affirmative, negative, or unknown without guessing."""
    lowered = text.lower().strip()
    if re.search(
        r"\b(not sure|unsure|don'?t know|do not know|maybe|unknown|can'?t say|cannot say)\b",
        lowered,
    ):
        return "unknown"

    negative = bool(re.search(
        r"\b(no|nope|not|never|negative|decline|refuse|don'?t|do not|doesn'?t|does not)\b",
        lowered,
    ))
    affirmative = bool(re.search(
        r"\b(yes|yeah|yep|sure|correct|absolutely|agree|consent|okay|ok|go ahead|"
        r"i am (?:the )?account holder|i'?m (?:the )?account holder|"
        r"i have (?:prior )?(?:coverage|insurance)|i do have)\b",
        lowered,
    ))

    if negative and affirmative:
        if re.search(r"\b(i am not|i'?m not|don'?t|do not|doesn'?t|does not|not the)\b", lowered):
            return "negative"
        return "unknown"
    if negative:
        return "negative"
    if affirmative:
        return "affirmative"
    return "unknown"


def _is_termination(text: str) -> bool:
    return bool(re.search(
        r"\b(bye|goodbye|good bye|hang up|end (the )?(call|session)|nothing else|that'?s all)\b",
        text.lower(),
    ))


def _is_transfer(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"\b(no|nope|don'?t|do not|never|not)\b.*\b(transfer|human|specialist|representative|supervisor|live agent|real person)\b",
        lowered,
    ):
        return False
    return bool(re.search(
        r"\b(transfer|human|specialist|representative|supervisor|live agent|real person)\b",
        lowered,
    ))


def _is_pricing(text: str) -> bool:
    return bool(re.search(r"\b(price|pricing|cost|fee|how much|quote)\b", text.lower()))


def _prompt_for_stage(state: dict[str, Any]) -> str:
    stage = state.get("stage")
    if stage == "account_holder":
        return "Are you the account holder? Please answer yes or no."
    if stage == "zip":
        return "What is your five-digit ZIP code?"
    if stage == "coverage":
        return "Do you currently have prior coverage or insurance? Please answer yes or no."
    if stage == "transfer_offer":
        return "Would you like a specialist review? Please answer yes or no."
    if stage == "consent_pending":
        return "Do I have your explicit consent to request a specialist transfer?"
    return "How can I help with your intake?"


def _pricing_reply(policy: AgentPolicy) -> str:
    purpose = policy.purpose.strip() or "this service"
    if policy.tone == "friendly":
        return f"Great question — pricing for {purpose} needs specialist confirmation, and I will not invent a quote. "
    if policy.tone == "empathetic":
        return f"I understand pricing matters for {purpose}. A specialist must confirm it, so I will not guess. "
    if policy.tone == "authoritative":
        return f"Pricing for {purpose} requires specialist confirmation. No quote will be invented. "
    if policy.tone == "cheerful":
        return f"Happy to help with {purpose}! Pricing needs specialist confirmation, so no made-up quotes. "
    return f"I cannot verify pricing for {purpose}, so I will not invent a quote. "


def _complete(
    state: dict[str, Any], reply: str, intent: str, outcome: str,
    events: list[dict[str, Any]],
) -> EngineResult:
    state["stage"] = "ended"
    state["outcome"] = outcome
    events.append({"type": "session_completed", "payload": {"reason": outcome}})
    return EngineResult(reply=reply, intent=intent, state=state, status="completed", events=events)


def _request_transfer(
    policy: AgentPolicy, state: dict[str, Any], events: list[dict[str, Any]],
) -> EngineResult:
    """The only function allowed to change transfer authorization state."""
    if not policy.transfers_enabled:
        state["transferStatus"] = "blocked"
        events.append({
            "type": "transfer_blocked",
            "payload": {"reason": "transfers_disabled"},
        })
        return EngineResult(
            reply="Transfers are disabled for this agent. No transfer was requested. "
                  + _prompt_for_stage(state),
            intent="transfer_blocked",
            state=state,
            events=events,
        )

    if policy.require_consent and state.get("consent") is not True:
        state["stage"] = "consent_pending"
        state["transferStatus"] = "awaiting_consent"
        events.append({"type": "consent_requested", "payload": {"purpose": "specialist_transfer"}})
        return EngineResult(
            reply=(
                f"I can request a specialist transfer for {policy.purpose}. Do I have your explicit consent "
                "to share this intake transcript and request that transfer? Please answer yes or no."
            ),
            intent="consent_request",
            state=state,
            events=events,
        )

    state["stage"] = "transfer_pending"
    state["transferStatus"] = "pending"
    state["outcome"] = None
    events.append({
        "type": "transfer_pending",
        "payload": {
            "consent": state.get("consent"),
            "consentRequired": policy.require_consent,
            "reason": "no_live_adapter_connected",
        },
    })
    return EngineResult(
        reply=(
            "Your transfer request is pending. No specialist has been connected yet. "
            "Stage 1 has no live telephony adapter, so I will not claim the transfer succeeded."
        ),
        intent="transfer_pending",
        state=state,
        status="pending_transfer",
        events=events,
        transfer={"status": "pending", "reason": "no_live_adapter_connected"},
    )


def engine_turn(
    policy: AgentPolicy,
    current_state: dict[str, Any],
    content: str,
    turn_number: int = 1,
) -> EngineResult:
    """Evaluate one caller turn without mutating the caller's state object."""
    text = content.strip()
    lowered = text.lower()
    state = deepcopy(current_state)
    events: list[dict[str, Any]] = []
    stage = state.get("stage", "account_holder")

    if _is_termination(lowered):
        result = _complete(
            state,
            "Thank you. Your session is now complete, and no transfer was requested.",
            "termination",
            "caller_ended",
            events,
        )
    elif _is_transfer(lowered):
        result = _request_transfer(policy, state, events)
    elif _is_pricing(lowered):
        result = EngineResult(
            reply=_pricing_reply(policy) + _prompt_for_stage(state),
            intent="pricing",
            state=state,
            events=events,
        )
    elif stage == "account_holder":
        answer = _yes_no(text)
        if answer == "affirmative":
            state["accountHolder"] = True
            state["stage"] = "zip"
            events.append({"type": "account_holder_recorded", "payload": {"value": True}})
            result = EngineResult(
                reply="Thank you for confirming. What is your five-digit ZIP code?",
                intent="account_holder_confirmed",
                state=state,
                events=events,
            )
        elif answer == "negative":
            state["accountHolder"] = False
            state["eligibility"] = "not_assessed"
            events.append({"type": "account_holder_recorded", "payload": {"value": False}})
            events.append({"type": "eligibility_not_assessed", "payload": {"reason": "not_account_holder"}})
            result = _complete(
                state,
                "Thanks for telling me. I cannot assess eligibility without the account holder. "
                "No eligibility approval or transfer has been made.",
                "account_holder_declined",
                "account_holder_unconfirmed",
                events,
            )
        else:
            result = EngineResult(
                reply="I need a clear answer before continuing. Are you the account holder? Please answer yes or no.",
                intent="clarification_required",
                state=state,
                events=events,
            )
    elif stage == "zip":
        match = re.search(r"\b(\d{5})\b", text)
        if match:
            state["zip"] = match.group(1)
            state["stage"] = "coverage"
            events.append({"type": "zip_recorded", "payload": {"valid": True}})
            result = EngineResult(
                reply=f"Thanks — ZIP {match.group(1)} is recorded. Do you currently have prior coverage or insurance?",
                intent="zip_confirmed",
                state=state,
                events=events,
            )
        else:
            events.append({"type": "validation_failed", "payload": {"field": "zip"}})
            result = EngineResult(
                reply="Please provide a valid five-digit ZIP code, for example 90210.",
                intent="zip_invalid",
                state=state,
                events=events,
            )
    elif stage == "coverage":
        answer = _yes_no(text)
        if answer == "unknown":
            result = EngineResult(
                reply="I will not guess your coverage status. Do you currently have prior coverage or insurance? Please answer yes or no.",
                intent="clarification_required",
                state=state,
                events=events,
            )
        else:
            has_coverage = answer == "affirmative"
            state["priorCoverage"] = has_coverage
            state["eligibility"] = "preliminary_eligible" if has_coverage else "manual_review"
            state["stage"] = "transfer_offer"
            events.append({
                "type": "eligibility_evaluated",
                "payload": {
                    "result": state["eligibility"],
                    "finalApproval": False,
                    "rule": "account_holder + valid_zip + prior_coverage",
                },
            })
            reply = (
                "You meet the Stage 1 demo criteria for a preliminary plan review. This is not a final approval. "
                if has_coverage else
                "Your answers require a manual specialist review rather than an automatic eligibility result. "
            )
            result = EngineResult(
                reply=reply + "Would you like a specialist review? Please answer yes or no.",
                intent="coverage_recorded",
                state=state,
                events=events,
            )
    elif stage == "transfer_offer":
        answer = _yes_no(text)
        if answer == "affirmative":
            result = _request_transfer(policy, state, events)
        elif answer == "negative":
            result = _complete(
                state,
                "Understood. No specialist transfer will be requested. Your intake is complete.",
                "transfer_declined",
                "no_transfer",
                events,
            )
        else:
            result = EngineResult(
                reply="Please answer yes or no. Would you like a specialist review?",
                intent="clarification_required",
                state=state,
                events=events,
            )
    elif stage == "consent_pending":
        answer = _yes_no(text)
        if answer == "affirmative":
            state["consent"] = True
            events.append({"type": "consent_recorded", "payload": {"value": True}})
            result = _request_transfer(policy, state, events)
        elif answer == "negative":
            state["consent"] = False
            state["transferStatus"] = "declined"
            events.append({"type": "consent_recorded", "payload": {"value": False}})
            result = _complete(
                state,
                "Understood. Consent was declined, so no transfer was requested. Your session is complete.",
                "consent_declined",
                "consent_declined",
                events,
            )
        else:
            result = EngineResult(
                reply="I need explicit consent before requesting a transfer. Please answer yes or no.",
                intent="clarification_required",
                state=state,
                events=events,
            )
    else:
        result = EngineResult(
            reply="This session is no longer accepting turns.",
            intent="session_closed",
            state=state,
            status="completed",
            events=events,
        )

    if result.status == "active" and turn_number >= policy.max_turns:
        state = result.state
        state["stage"] = "ended"
        state["outcome"] = "max_turns"
        if state.get("transferStatus") in {"awaiting_consent", "blocked"}:
            state["transferStatus"] = "not_requested"
        result.status = "completed"
        result.reply += " The session turn limit has been reached, so I am ending the session here."
        result.events.append({"type": "session_completed", "payload": {"reason": "max_turns"}})

    return result
