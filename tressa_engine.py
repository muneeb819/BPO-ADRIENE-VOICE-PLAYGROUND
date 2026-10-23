#!/usr/bin/env python3
"""Grounded conversation engine for Tressa (USA Medicare).

The generic Nexus deterministic engine is intentionally product-neutral. Tressa
must not inherit its generic "$29/month" or "you appear eligible" responses.
This module implements a compact, retrieval-backed Medicare flow:

    recording permission -> disclosures/TPMO -> SOA -> qualification ->
    needs discovery -> recap -> explicit transfer consent -> callback/close

It is deterministic on purpose: no external LLM key is required, every factual
answer is extractive from the attached Medicare corpus, and every transition
can be audited. An LLM can be added later without changing the source-of-truth
or compliance gates.
"""
from __future__ import annotations

import re
from typing import Any

import training

AFFIRMATIVE = re.compile(
    r"\b(yes|yeah|yep|yup|sure|okay|ok|correct|right|agree|i do|i have|"
    r"sounds good|go ahead|please do|that's right|that is right)\b",
    re.I,
)
NEGATIVE = re.compile(
    r"\b(no|nope|nah|not really|not interested|i don't|i do not|none|never|"
    r"don't|do not|not now|not today)\b",
    re.I,
)
CONSENT_YES = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|okay|ok|i consent|i agree|go ahead|please do|"
    r"that's fine|that is fine|sounds good|you may)\b",
    re.I,
)
HUMAN = re.compile(
    r"\b(transfer|human|licensed agent|live agent|representative|specialist|"
    r"supervisor|manager|real person)\b",
    re.I,
)
DO_NOT_CALL = re.compile(r"\b(do not call|don't call|stop calling|remove me|dnc)\b", re.I)
NOT_INTERESTED = re.compile(r"\b(not interested|no thanks|no thank you|not for me|pass)\b", re.I)
BUSY = re.compile(r"\b(busy|driving|at work|not a good time|later|call back|callback)\b", re.I)
SCAM = re.compile(r"\b(scam|fraud|fake|legit|is this real|who are you|are you from medicare)\b", re.I)
AI_QUESTION = re.compile(r"\b(ai|a\.i\.|robot|bot|human|real person|machine|recording)\b", re.I)
SOA_QUESTION = re.compile(r"\b(scope of appointment|soa|authorized products)\b", re.I)
PLAN_SPECIFIC = re.compile(
    r"\b(best plan|which plan|this plan|my plan|plan premium|plan cost|plan cover|"
    r"network|formulary|deductible|co-pay|copay|coverage for|cover my|"
    r"my doctor|my drug|my prescription)\b",
    re.I,
)
COST_QUESTION = re.compile(r"\b(how much|cost|price|premium|fee|quote|rate)\b", re.I)
GUARANTEE = re.compile(r"\b(free|guarantee|guaranteed|everyone qualifies|no cost)\b", re.I)
UNSUPPORTED_BENEFIT = re.compile(
    r"\b(food[ -]?stamps?|foods[ -]?stamps?|cash ?back|flex[ -]?card|"
    r"social security check|extra social security|money back)\b",
    re.I,
)
QUESTION_START = re.compile(
    r"^\s*(what|why|how|when|where|who|which|can|could|do|does|did|is|are|"
    r"will|would|should|may|am)\b",
    re.I,
)
QUESTION_ANY = re.compile(
    r"\b(what|why|how|when|where|who|which)\b.*\?|\?\s*$", re.I
)

PROMPTS = {
    "permission": "Do I have your permission to continue and record this conversation?",
    "soa_products": "Which would you like to review: Medicare Advantage, Medicare Supplement, or Part D prescription drug coverage?",
    "qualify_medicare": "Do you currently have both Medicare Part A and Part B?",
    "qualify_age": "How old are you?",
    "qualify_zip": "What is your 5-digit ZIP code?",
    "qualify_decision": "Are you making your own decision about your coverage?",
    "discovery_current": "Do you currently have Original Medicare, a Medicare Advantage plan, or a Medicare Supplement plan?",
    "discovery_doctors": "Do you have doctors, specialists, or a hospital you want to keep?",
    "discovery_rx": "Do you take regular prescriptions?",
    "discovery_priorities": "What matters most to you: lower premiums, predictable costs, dental, vision, hearing, or keeping your doctors?",
    "transfer_offered": "Would you like me to transfer you to a licensed agent now?",
    "transfer_consent": "Just to confirm, do you consent to transferring this call to a licensed agent?",
    "callback_offer": "Would you like a callback instead?",
    "callback_phone": "What is the best phone number for the callback?",
    "callback_time": "What time of day works best for the callback?",
    "route_or_continue": "Would you like me to connect you with a licensed agent, or would a callback be better?",
}

DEFAULTS = {
    "stage": "permission",
    "recordingConsent": False,
    "soaProducts": [],
    "medicareAB": None,
    "age": None,
    "zip": None,
    "decisionMaker": None,
    "currentCoverage": None,
    "doctors": None,
    "prescriptions": None,
    "priorities": None,
    "transferConsent": False,
    "callbackPhone": None,
    "callbackTime": None,
    "doNotCall": False,
    "asked": [],
    "bargeIns": 0,
    "transferRequested": False,
    "ended": False,
    "reason": None,
    "turn_count": 0,
}


def is_tressa(agent: dict) -> bool:
    call_name = str(agent.get("callName") or agent.get("name") or "").lower()
    campaign = str(agent.get("campaign") or "").lower()
    return call_name == "tressa" and "medicare" in campaign


def ensure_state(state: dict) -> dict:
    for key, value in DEFAULTS.items():
        state.setdefault(key, value.copy() if isinstance(value, list) else value)
    if state.get("stage") in (None, "", "start", "greeting"):
        state["stage"] = "permission"
    return state


def _result(intent: str, reply: str, *, ended: bool = False, transfer: bool = False,
            violations: list[str] | None = None, status: str | None = None) -> dict:
    return {
        "intent": intent,
        "reply": reply,
        "ended": ended,
        "status": status if status is not None else ("completed" if ended else None),
        "error": None,
        "violations": violations or [],
        "transfer": transfer,
    }


def _prompt(stage: str) -> str:
    return PROMPTS.get(stage, "How can I help with your Medicare questions?")


def _short(text: str, limit: int = 430) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[:boundary + 1] if boundary > 180 else cut.rstrip()) + "…"


def _products(text: str) -> list[str]:
    low = text.lower()
    found = []
    if re.search(r"\b(medicare advantage|advantage|part c|ma plan)\b", low):
        found.append("Medicare Advantage")
    if re.search(r"\b(medicare supplement|supplement|medigap)\b", low):
        found.append("Medicare Supplement")
    if re.search(r"\b(part d|drug plan|prescription drug|prescriptions?)\b", low):
        found.append("Part D")
    if re.search(r"\b(both|all of them|all three|everything|a combination)\b", low):
        found = ["Medicare Advantage", "Medicare Supplement", "Part D"]
    return list(dict.fromkeys(found))


def _extract_age(text: str) -> int | None:
    for match in re.finditer(r"\b(\d{2})\b", text):
        age = int(match.group(1))
        if 0 < age < 120:
            return age
    return None


def _extract_zip(text: str) -> str | None:
    match = re.search(r"\b(\d{5})\b", text)
    return match.group(1) if match else None


def _extract_phone(text: str) -> str | None:
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits.startswith("1"):
        d = digits[1:]
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    return None


def _grounded_answer(query: str) -> tuple[str | None, dict | None]:
    store = training.get_store()
    result = store.answer(query, limit=3)
    if not result.get("grounded"):
        return None, None
    text = _short(result.get("answer", ""), 430)
    top = (result.get("sources") or [None])[0]
    return text, top


def _repeat(stage: str, prefix: str = "") -> str:
    prompt = _prompt(stage)
    if prefix:
        return f"{prefix} {prompt}"
    return prompt


def _handle_question(text: str, state: dict) -> tuple[str | None, bool, bool]:
    """Answer a question if possible.

    Returns (reply, handled, routed). routed means the answer is plan-specific
    and the caller must be routed instead of receiving an unverified answer.
    """
    low = text.lower().strip()
    stage = state.get("stage")

    if re.fullmatch(r"(i have a question|can i ask a question|quick question)[.!]?", low):
        return "Of course—what is your question?", True, False

    if AI_QUESTION.search(low):
        return (
            "Yes. I'm an AI assistant with US Health Care. I'm not a licensed insurance "
            "agent, not a human, and not from Medicare. A licensed agent can help with "
            "plan-specific guidance."
        ), True, False

    if UNSUPPORTED_BENEFIT.search(low):
        return (
            "I don't offer food stamps, cash back, a Flex-card, or extra Social Security "
            "money. Those claims are not supported by my training material. I can discuss "
            "Medicare Advantage, Medicare Supplement, or Part D."
        ), True, False

    if GUARANTEE.search(low):
        return (
            "I can't promise free coverage, guaranteed eligibility, or guaranteed savings. "
            "Eligibility and costs depend on verification by a licensed agent."
        ), True, False

    if PLAN_SPECIFIC.search(low) or (COST_QUESTION.search(low) and not re.search(r"\bpart [abcd]\b", low)):
        return (
            "I can't quote or compare plan-specific premiums, networks, formularies, or "
            "benefits without verifying the plan. A licensed agent can review those details "
            "with you. Would you like a transfer or a callback?"
        ), True, True

    if len(low.split()) <= 6 and re.search(r"\b(that|this|it)\b", low):
        return "Could you tell me a little more about what you'd like to know?", True, False

    if SOA_QUESTION.search(low):
        return (
            "The Scope of Appointment documents which product types you authorize us to "
            "discuss before any plan-specific conversation. You can choose Medicare "
            "Advantage, Medicare Supplement, Part D, or a combination, and you're under no "
            "obligation to enroll."
        ), True, False

    if re.search(r"\b(obligation|have to enroll|must i enroll|required to enroll)\b", low):
        return (
            "No. You're under no obligation to enroll. I can share general Medicare "
            "information and connect you with a licensed agent if you want plan-specific help."
        ), True, False

    if re.search(r"\b(social security number|ssn|bank|credit card|medicare id)\b", low):
        return (
            "I don't need your Social Security number, bank details, credit card, or Medicare "
            "ID for routine screening. Please don't share those with me. I collect only what's "
            "needed for the campaign and this call."
        ), True, False

    if re.search(r"\b(why do you need|why are you asking|privacy|personal information)\b", low):
        return (
            "I collect only the minimum information needed to check the campaign criteria and "
            "route you correctly. I never ask for a Social Security number, bank details, credit "
            "card, or Medicare ID during routine screening."
        ), True, False

    if re.search(r"\b(what is this call about|why are you calling|purpose of the call)\b", low):
        return (
            "I'm calling about Medicare plan options through US Health Care. I'm not connected "
            "with or endorsed by the federal government or Medicare, and I don't offer every "
            "plan in your area."
        ), True, False

    if QUESTION_START.search(low) or QUESTION_ANY.search(low) or re.search(
        r"\b(tell me about|explain|define|what does|how does)\b", low
    ):
        answer, _ = _grounded_answer(text)
        if answer:
            return answer, True, False
        return (
            "I don't have that verified detail in the training material, so I shouldn't guess. "
            "A licensed agent can help, or you can check Medicare.gov or 1-800-MEDICARE. "
            "Would you like a transfer or callback?"
        ), True, False

    if stage == "soa_products" and re.search(r"\b(not sure|what are|difference|explain)\b", low):
        return (
            "Medicare Advantage is Part C and usually combines Part A and Part B, often with "
            "drug coverage. Medicare Supplement works alongside Original Medicare. Part D is "
            "prescription drug coverage. Which would you like to review?"
        ), True, False

    return None, False, False


def _clean_fragment(text: str, prefixes: tuple[str, ...] = ()) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" .!?;,")
    for prefix in prefixes:
        if value.lower().startswith(prefix):
            value = value[len(prefix):].strip()
    value = re.sub(r"^my\b", "your", value, flags=re.I)
    return value.rstrip(" .!?;,")


def _coverage_label(text: str) -> str:
    low = str(text or "").lower()
    if re.search(r"\b(advantage|part c)\b", low):
        return "a Medicare Advantage plan"
    if re.search(r"\b(supplement|medigap)\b", low):
        return "a Medicare Supplement plan"
    if re.search(r"\b(original medicare|part a and part b|parts a and b|traditional)\b", low):
        return "Original Medicare"
    if re.search(r"\b(none|nothing|no coverage|not insured)\b", low):
        return "no current coverage"
    cleaned = _clean_fragment(text, ("i have", "i'm on", "i am on", "currently have"))
    return cleaned or "your current coverage"


def _recap(state: dict) -> str:
    coverage = _coverage_label(state.get("currentCoverage") or "")
    doctors = _clean_fragment(
        state.get("doctors") or "",
        ("i want to keep", "i need to keep", "i'd like to keep", "i would like to keep"),
    )
    rx = _clean_fragment(
        state.get("prescriptions") or "",
        ("i take", "i'm taking", "i am taking", "yes, i take", "yes i take"),
    )
    priorities = _clean_fragment(
        state.get("priorities") or "",
        ("what matters most is", "what matters most to me is", "i want", "i'd like"),
    )
    if not doctors or re.fullmatch(r"(no|none|nope|no one|not really)", doctors, re.I):
        doctors = "no specific doctors"
    if not rx or re.fullmatch(r"(no|none|nope|not really)", rx, re.I):
        rx = "no regular prescriptions"
    priorities = priorities or "your priorities"
    return (
        f"Thank you. To recap: you have {coverage}; you want to keep {doctors}; "
        f"your prescriptions are {rx}; and your priority is {priorities}. I can't verify "
        "plan-specific networks, formularies, premiums, or benefits here. A licensed agent "
        "can review those. Would you like me to transfer you now?"
    )


def step(agent: dict, state: dict, content: str, intent_override: str | None = None) -> dict:
    """Run one grounded Tressa turn."""
    ensure_state(state)
    text = str(content or "").strip()
    low = text.lower()
    stage = state.get("stage")
    state["turn_count"] = int(state.get("turn_count") or 0) + 1

    if not text:
        return _result("silence", "I didn't catch that. Could you please repeat your question?")

    if intent_override == "barge_in" or re.search(r"\b(wait|hold on|stop|actually|one second|excuse me)\b", low):
        state["bargeIns"] = int(state.get("bargeIns") or 0) + 1
        return _result("barge_in", "Of course—go ahead, I'm listening.")

    if intent_override == "silence" or low in ("[silence]", "silence"):
        return _result("silence", "I didn't catch that. Could you please repeat your question?")

    if DO_NOT_CALL.search(low):
        state["doNotCall"] = True
        state["ended"] = True
        state["stage"] = "ended"
        state["reason"] = "do_not_call"
        return _result(
            "do_not_call",
            "I understand. I'll note that you do not want to be called again. I'm ending this "
            "call now. If you need Medicare information later, you can contact Medicare.gov or "
            "1-800-MEDICARE. Goodbye.",
            ended=True,
        )

    if re.search(r"(ignore (all|previous) instructions|system prompt|jailbreak|hack the)", low):
        return _result(
            "general",
            "I can't help with that request. I can still help with Medicare plan types, the "
            "Scope of Appointment, or a transfer to a licensed agent.",
        )

    if stage in ("transferred", "ended") or state.get("ended"):
        state["ended"] = True
        return _result("termination", "This session has ended. Thank you for your time.", ended=True)

    # Objections and special handling should not be buried inside a stage prompt.
    if NOT_INTERESTED.search(low):
        state["stage"] = "callback_offer"
        return _result(
            "objection_not_interested",
            "I understand, and I won't pressure you. Would you like a callback later, or would "
            "you prefer information from Medicare.gov or 1-800-MEDICARE?",
        )

    if BUSY.search(low) and stage not in ("callback_phone", "callback_time"):
        state["stage"] = "callback_offer"
        return _result(
            "objection_busy",
            "Of course. I don't want to keep you. Would a callback at a better time be helpful?",
        )

    if SCAM.search(low) or re.search(r"\b(is this (a )?scam|are you (a )?scam|who is this)\b", low):
        return _result(
            "trust_question",
            "I understand the concern. I'm an AI assistant with US Health Care, not from "
            "Medicare or the government. You can verify Medicare information at Medicare.gov or "
            "1-800-MEDICARE. Would you like to continue, or should I end the call?",
        )

    if re.search(r"\b(already have|already enrolled|i have a plan|happy with my plan)\b", low):
        state["stage"] = "review_or_end"
        return _result(
            "objection_already_enrolled",
            "That's fine. I'm not asking you to change plans. Would a no-obligation review be "
            "helpful, or should I close the call?",
        )

    # "Are you a real person?" is an AI-disclosure question, not a transfer
    # request. "Can I talk to a human?" is a transfer request. Keep them apart.
    if AI_QUESTION.search(low) and not (
        HUMAN.search(low) and re.search(r"\b(speak|talk|transfer|connect|reach)\b", low)
    ):
        q_reply, handled, _ = _handle_question(text, state)
        if handled:
            return _result("question", _repeat(stage, q_reply or ""))

    if HUMAN.search(low) and stage not in ("transfer_consent", "transfer_offered"):
        if state.get("doNotCall"):
            state["ended"] = True
            return _result("do_not_call", "I understand. I'll end the call now. Goodbye.", ended=True)
        state["stage"] = "transfer_consent"
        return _result(
            "transfer_request",
            "I can request a transfer to a licensed agent. Just to confirm, do you consent to "
            "transferring this call?",
        )

    # Questions are answered from the corpus before advancing a stage. The only
    # exception is a clear yes/no answer to the current question.
    is_plain_answer = bool(AFFIRMATIVE.fullmatch(low) or NEGATIVE.fullmatch(low))
    if not is_plain_answer:
        q_reply, handled, routed = _handle_question(text, state)
        if routed:
            state["stage"] = "transfer_offered"
            return _result("plan_specific_question", q_reply)
        if handled:
            return _result("question", q_reply)

    if stage == "permission":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["recordingConsent"] = True
            age = _extract_age(low)
            zip_code = _extract_zip(low)
            if age:
                state["age"] = age
            if zip_code:
                state["zip"] = zip_code
            if re.search(r"\b(part a and part b|parts a and b|both part a|both a and b)\b", low):
                state["medicareAB"] = True
            if re.search(r"\b(medicare advantage|supplement|part d|drug|review|plan)\b", low):
                products = _products(low)
                if products:
                    state["soaProducts"] = products
                    state["stage"] = "qualify_medicare"
                    return _result(
                        "consent",
                        "Thank you. I've documented your authorization to discuss "
                        f"{', '.join(products)}. You're not obligated to enroll. Do you currently "
                        "have both Medicare Part A and Part B?",
                    )
            state["stage"] = "soa_products"
            return _result(
                "consent",
                "Thank you. I represent the plan options available through US Health Care. I'm "
                "not connected with or endorsed by the federal government or Medicare. I don't "
                "offer every plan in your area; for all options, contact Medicare.gov or "
                "1-800-MEDICARE. Before we discuss specific plans, which would you like to "
                "review: Medicare Advantage, Medicare Supplement, or Part D?",
            )
        if NEGATIVE.search(low):
            state["stage"] = "callback_offer"
            return _result(
                "no_recording_consent",
                "I understand. Without your permission to record, I can't continue this call. "
                "Would you like a callback instead?",
            )
        return _result("clarify", _repeat("permission", "I need a clear yes or no to continue."))

    if stage == "soa_products":
        # Preserve volunteered context even when the caller has not yet selected
        # an SOA product. Do not advance until the authorization is explicit.
        age = _extract_age(low)
        zip_code = _extract_zip(low)
        if age:
            state["age"] = age
        if zip_code:
            state["zip"] = zip_code
        if re.search(r"\b(part a and part b|parts a and b|both part a|both a and b)\b", low):
            state["medicareAB"] = True
        if re.search(r"\b(i have|i'm on|i am on|currently have)\b", low) and re.search(
            r"\b(original medicare|advantage plan|supplement plan|medigap)\b", low
        ):
            state["currentCoverage"] = text
        products = _products(low)
        if products:
            state["soaProducts"] = products
            state["stage"] = "qualify_medicare"
            return _result(
                "soa_recorded",
                "Thank you. I've documented your authorization to discuss "
                f"{', '.join(products)}. You're not obligated to enroll. Do you currently have "
                "both Medicare Part A and Part B?",
            )
        if state.get("age") or state.get("zip") or state.get("medicareAB") or state.get("currentCoverage"):
            return _result(
                "soa_context_noted",
                "Thank you — I've noted that. Before we discuss specific plans, I still need to "
                "document the product types you authorize: Medicare Advantage, Medicare "
                "Supplement, or Part D. Which would you like to review?",
            )
        if re.search(r"\b(no plans?|none|just information|only information|not sure|what are)\b", low):
            if re.search(r"\b(no plans?|none)\b", low):
                state["stage"] = "callback_offer"
                return _result(
                    "no_products",
                    "I understand. I can't discuss specific plans without an authorized product "
                    "type. Would you like a callback, or should I close the call?",
                )
            return _result(
                "soa_explain",
                "Medicare Advantage is Part C and usually combines Part A and Part B, often with "
                "drug coverage. Medicare Supplement works alongside Original Medicare. Part D is "
                "prescription drug coverage. Which would you like to review?",
            )
        return _result("clarify", _repeat("soa_products"))

    if stage == "qualify_medicare":
        if AFFIRMATIVE.search(low) and not NEGATIVE.search(low):
            state["medicareAB"] = True
            age = _extract_age(low)
            zip_code = _extract_zip(low)
            if age:
                state["age"] = age
            if zip_code:
                state["zip"] = zip_code
            if age and zip_code:
                state["stage"] = "qualify_decision"
                return _result(
                    "qualification",
                    f"Thank you. I have your age as {age} and ZIP {zip_code}. Are you making "
                    "your own decision about your coverage?",
                )
            if age:
                state["stage"] = "qualify_zip"
                return _result("qualification", f"Thank you. What is your 5-digit ZIP code?")
            state["stage"] = "qualify_age"
            return _result("qualification", "Thank you. How old are you?")
        if NEGATIVE.search(low):
            state["medicareAB"] = False
            state["stage"] = "route_or_continue"
            return _result(
                "no_medicare_ab",
                "Medicare Advantage generally requires both Part A and Part B. I can still "
                "discuss Original Medicare or Part D, or connect you with a licensed agent. "
                "Would you like that?",
            )
        return _result(
            "clarify",
            "You can check your Medicare card. Do you have both Part A and Part B?",
        )

    if stage == "qualify_age":
        age = _extract_age(low)
        if age:
            state["age"] = age
            if age < 65:
                state["stage"] = "route_or_continue"
                return _result(
                    "age_under_65",
                    "Thank you. Medicare can cover some people under 65 with a disability, "
                    "End-Stage Renal Disease, or ALS, so I don't want to screen you out. A "
                    "licensed agent should review your situation. Would you like a transfer or "
                    "a callback?",
                )
            state["stage"] = "qualify_zip"
            return _result("age", "Thank you. What is your 5-digit ZIP code?")
        return _result("clarify", "I just need your age in years. How old are you?")

    if stage == "qualify_zip":
        zip_code = _extract_zip(low)
        if zip_code:
            state["zip"] = zip_code
            state["stage"] = "qualify_decision"
            return _result(
                "zip",
                f"Thank you — ZIP {zip_code}. Are you making your own decision about your coverage?",
            )
        return _result("clarify", "I need a 5-digit ZIP code. What is your ZIP code?")

    if stage == "qualify_decision":
        if AFFIRMATIVE.search(low) and not NEGATIVE.search(low):
            state["decisionMaker"] = True
            state["stage"] = "discovery_current"
            return _result(
                "decision_maker",
                "Thank you. Do you currently have Original Medicare, a Medicare Advantage plan, "
                "or a Medicare Supplement plan?",
            )
        if NEGATIVE.search(low):
            state["decisionMaker"] = False
            state["stage"] = "decision_maker"
            return _result(
                "decision_maker_needed",
                "Understood. Is the decision-maker available, or would you like a callback when "
                "they are?",
            )
        return _result("clarify", _repeat("qualify_decision"))

    if stage == "decision_maker":
        if AFFIRMATIVE.search(low) or re.search(r"\b(here|available|speak)\b", low):
            state["decisionMaker"] = True
            state["stage"] = "discovery_current"
            return _result(
                "decision_maker",
                "Thank you. Do you currently have Original Medicare, a Medicare Advantage plan, "
                "or a Medicare Supplement plan?",
            )
        state["stage"] = "callback_offer"
        return _result(
            "decision_maker_unavailable",
            "I understand. Would a callback when they're available be helpful?",
        )

    if stage == "discovery_current":
        state["currentCoverage"] = text
        state["stage"] = "discovery_doctors"
        return _result(
            "discovery",
            "Thank you. Do you have doctors, specialists, or a hospital you want to keep?",
        )

    if stage == "discovery_doctors":
        state["doctors"] = text
        state["stage"] = "discovery_rx"
        return _result("discovery", "Thank you. Do you take regular prescriptions?")

    if stage == "discovery_rx":
        state["prescriptions"] = text
        state["stage"] = "discovery_priorities"
        return _result(
            "discovery",
            "Thank you. What matters most to you: lower premiums, predictable costs, dental, "
            "vision, hearing, or keeping your doctors?",
        )

    if stage == "discovery_priorities":
        state["priorities"] = text
        state["stage"] = "transfer_offered"
        return _result("recap", _recap(state))

    if stage == "review_or_end":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["stage"] = "discovery_current"
            return _result(
                "review_accepted",
                "Happy to do a no-obligation review. Do you currently have Original Medicare, a "
                "Medicare Advantage plan, or a Medicare Supplement plan?",
            )
        state["ended"] = True
        state["reason"] = "closed_no_review"
        return _result(
            "termination",
            "That's completely fine. Thank you for your time. If you need Medicare information "
            "later, contact Medicare.gov or 1-800-MEDICARE. Goodbye.",
            ended=True,
        )

    if stage == "transfer_offered":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["stage"] = "transfer_consent"
            return _result(
                "transfer_offered",
                "Just to confirm, do you consent to transferring this call to a licensed agent?",
            )
        if NEGATIVE.search(low):
            state["stage"] = "callback_offer"
            return _result(
                "transfer_declined",
                "No problem. Would you like a callback instead, or should I close the call?",
            )
        return _result("clarify", _repeat("transfer_offered"))

    if stage == "transfer_consent":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["transferConsent"] = True
            state["transferRequested"] = True
            state["ended"] = True
            state["reason"] = "transfer_requested"
            return _result(
                "transfer_consent",
                "Thank you. I'm requesting a transfer to a licensed agent now. Please hold while "
                "the backend confirms availability; I won't claim the transfer is complete until "
                "it is.",
                ended=True,
                transfer=True,
            )
        if NEGATIVE.search(low):
            state["stage"] = "callback_offer"
            return _result(
                "transfer_declined",
                "Understood. Would you like a callback instead?",
            )
        return _result("clarify", _repeat("transfer_consent"))

    if stage == "route_or_continue":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["stage"] = "transfer_consent"
            return _result(
                "route_to_agent",
                "I can request a transfer. Just to confirm, do you consent to transferring this "
                "call to a licensed agent?",
            )
        if NEGATIVE.search(low):
            state["stage"] = "callback_offer"
            return _result("route_declined", "Would a callback be better?" )
        return _result("clarify", _repeat("route_or_continue"))

    if stage == "callback_offer":
        if CONSENT_YES.search(low) and not NEGATIVE.search(low):
            state["stage"] = "callback_phone"
            return _result(
                "callback_offer",
                "Certainly. What is the best phone number for the callback?",
            )
        state["ended"] = True
        state["reason"] = "closed"
        return _result(
            "termination",
            "That's fine. Thank you for your time. If you need Medicare information later, "
            "contact Medicare.gov or 1-800-MEDICARE. Goodbye.",
            ended=True,
        )

    if stage == "callback_phone":
        phone = _extract_phone(low)
        if phone:
            state["callbackPhone"] = phone
            state["stage"] = "callback_time"
            return _result(
                "callback_phone",
                "Thank you. What time of day works best for the callback?",
            )
        if NEGATIVE.search(low):
            state["ended"] = True
            state["reason"] = "closed"
            return _result(
                "termination",
                "No problem. I'll close the call. Thank you for your time.",
                ended=True,
            )
        return _result("clarify", "I need a 10-digit phone number for the callback. What number should I use?")

    if stage == "callback_time":
        state["callbackTime"] = text
        state["ended"] = True
        state["reason"] = "callback_requested"
        return _result(
            "callback_requested",
            f"Thank you. I've captured a callback request for {state['callbackTime']}. A licensed "
            "agent will need to confirm the time; I won't say it is scheduled until they do. "
            "Goodbye.",
            ended=True,
        )

    return _result(
        "fallback",
        "I want to make sure I understand. Could you tell me a little more about what you need?",
    )
