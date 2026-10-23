#!/usr/bin/env python3
"""Build the Tressa USA Medicare knowledge base from the extracted corpus.

Outputs (all under Medicare Training Material/knowledge):
  medicare_kb.json        searchable chunks + rules + conflicts + campaign config
  tressa_instructions.txt operational system prompt (<= 8,000 chars)
  tressa_tests.json       validation cases derived from the sources
  README.md               provenance, source priority, open conflicts
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\Wave\Downloads\AdrieneVoiceStudio\Medicare Training Material")
EXTRACTED = ROOT / "extracted"
KNOWLEDGE = ROOT / "knowledge"
PROJECT = ROOT.parent

VERSION = "1.0.0"
SOURCES = {
    "01": "01_Medicare_Advantage_New_Hire_Orientation.pptx",
    "02": "02_Medicare_Agent_Call_Center_Training.pptx",
    "03": "03_Medicare_Script.docx",
    "04": "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx",
    "05": "05_Medicare_Supplement_vs_Advantage.pptx",
    "06": "06_Medicare_Script_Quiz.pptx",
    "07": "07_Medicare_Basics_Overview.pptx",
}
BOILER = re.compile(
    r"^(Medicare Agent Training\s*\|\s*Compliant Call Scripts|"
    r"Medicare Advantage · New Hire Orientation|"
    r"MED SCRIPT QUIZ.*|MEDICARE BASICS.*|"
    r"Medicare Advantage Quiz|"
    r"\d+\s*/\s*\d+|\d+)$"
)
SEARCH_TERMS = {
    ("01", 4): "key benefits agents should highlight extra benefits dental vision hearing fitness OTC transportation care coordination",
    ("01", 5): "critical rules new agents SOA cherry-picking CMS-approved materials enrollment periods needs assessment record retention",
    ("02", 4): "required disclosures recording consent TPMO scope of appointment no cold calling no pressure",
    ("02", 5): "seven step 7-step call flow opening SOA qualification needs discovery recap presentation close",
    ("02", 7): "scope of appointment SOA before plan-specific discussion products authorized no obligation",
    ("02", 8): "qualification Parts A and B ZIP county decision maker privacy identity",
    ("02", 9): "needs discovery current coverage satisfaction doctors medications priorities upcoming needs",
    ("02", 10): "TPMO disclaimer recap present options close transfer I do not offer every plan in your area",
    ("02", 11): "prohibited marketing phrases best free false urgency do not cold call",
    ("02", 12): "key knowledge parts of Medicare enrollment periods IEP AEP OEP SEP Medicare.gov SHIP",
    ("07", 4): "Part A Part B Part C Part D hospital medical insurance Medicare Advantage prescription drugs cover covers coverage what does",
    ("07", 5): "Part A hospital costs deductible SNF coinsurance 2026",
    ("07", 6): "Part B medical costs premium deductible coinsurance 2026",
    ("07", 8): "Part D prescription drug coverage out-of-pocket cap 2026",
}
RETRIEVAL_BOOST = {
    ("01", 4): 4.0,   # key supplemental-benefits slide
    ("02", 10): 4.0,  # recap/present/close + TPMO reminder
    ("07", 4): 5.0,   # canonical Part A-D definitions
    ("07", 5): 2.0,   # 2026 Part A costs
    ("07", 6): 4.0,   # 2026 Part B premium/deductible
    ("07", 8): 3.0,   # 2026 Part D out-of-pocket cap
    ("07", 9): 2.0,   # Medigap / Extra Help
}
TOPIC_RULES = {
    "eligibility": ["eligib", "part a", "part b", "65", "disability", "esrd", "als"],
    "enrollment": ["aep", "oep", "iep", "sep", "enrollment period", "october 15", "march 31"],
    "compliance": ["soa", "scope of appointment", "cms", "recording", "tpmo", "hipaa",
                   "cold call", "disclosure", "consent", "retention"],
    "script": ["greeting", "opening", "script", "transfer", "disclaimer", "pitch"],
    "needs": ["doctor", "medication", "prescription", "provider", "priority", "network",
              "formulary", "pharmacy"],
    "objection": ["not interested", "already have", "objection", "why do you need"],
    "costs": ["premium", "deductible", "coinsurance", "copay", "moop", "out-of-pocket",
              "2026", "202.90", "1,736", "2,100"],
    "plan-types": ["hmo", "ppo", "pffs", "msa", "snp", "d-snp", "medigap", "supplement",
                   "part c", "part d", "medicare advantage"],
    "benefits": ["dental", "vision", "hearing", "fitness", "otc", "transportation",
                 "care coordination", "extra benefits"],
    "transfer": ["transfer", "licensed agent", "live agent", "callback"],
    "conflict": ["food stamp", "cashback", "cash back", "social security check"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or BOILER.match(line):
            continue
        if re.fullmatch(r"SPEAKER NOTES:\s*\d+", line):
            continue
        line = re.sub(r"^SPEAKER NOTES:\s*", "", line).strip()
        if line:
            out.append(line)
    return out


def topics_for(text: str) -> list[str]:
    low = text.lower()
    return [topic for topic, terms in TOPIC_RULES.items() if any(t in low for t in terms)]


def title_for(lines: list[str], fallback: str) -> str:
    if not lines:
        return fallback
    for line in lines[:3]:
        if len(line) <= 110 and not line.startswith(("✓", "✗", "•", "⚫")):
            return line
    return lines[0][:110]


def add_chunk(chunks, *, cid, source, slide, section, text, kind="slide",
              priority=5, extra=None):
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text:
        return
    chunk = {
        "id": cid,
        "source": source,
        "slide": slide,
        "section": section,
        "kind": kind,
        "sourcePriority": priority,
        "text": text,
        "topics": topics_for(text),
    }
    if extra:
        chunk.update(extra)
    chunks.append(chunk)


def load_pptx(key: str) -> dict:
    path = EXTRACTED / (Path(SOURCES[key]).stem + ".json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_docx() -> list[dict]:
    path = EXTRACTED / (Path(SOURCES["03"]).stem + ".json")
    return json.loads(path.read_text(encoding="utf-8"))["blocks"]


def pptx_chunks(chunks, key: str, priority: int):
    data = load_pptx(key)
    file = SOURCES[key]
    for slide in data["slides"]:
        lines = []
        for block in slide["blocks"]:
            lines.extend(block["paragraphs"])
        for table in slide["tables"]:
            for row in table:
                lines.append(" | ".join(row))
        if slide.get("notes"):
            lines.append("Speaker notes: " + slide["notes"])
        lines = clean_lines("\n".join(lines))
        if not lines:
            continue
        body = "\n".join(lines)
        add_chunk(
            chunks,
            cid=f"{key}-s{slide['number']:02d}",
            source=file,
            slide=slide["number"],
            section=title_for(lines, f"Slide {slide['number']}"),
            text=body,
            kind="slide",
            priority=priority,
        )
        terms = SEARCH_TERMS.get((key, slide["number"]))
        if terms:
            chunks[-1]["searchTerms"] = terms
        boost = RETRIEVAL_BOOST.get((key, slide["number"]))
        if boost:
            chunks[-1]["retrievalBoost"] = boost


def parse_ma_quiz(chunks):
    data = load_pptx("04")
    questions = {}
    for slide in data["slides"]:
        lines = clean_lines("\n".join(
            p for b in slide["blocks"] for p in b["paragraphs"]))
        head = next((l for l in lines if re.match(r"Question\s+\d+\s+of\s+35", l)), None)
        if not head:
            continue
        num = int(re.search(r"Question\s+(\d+)", head).group(1))
        hi = lines.index(head)
        q = lines[hi + 1] if hi + 1 < len(lines) else ""
        options = []
        for i, l in enumerate(lines):
            if l in ("A", "B", "C", "D") and i + 1 < len(lines):
                options.append(f"{l}. {lines[i + 1]}")
        questions[num] = {
            "question": q,
            "options": options,
            "slide": slide["number"],
        }
    answers = {}
    for slide in data["slides"]:
        lines = clean_lines("\n".join(
            p for b in slide["blocks"] for p in b["paragraphs"]))
        current = None
        for line in lines:
            m = re.match(r"^Q(\d+):\s*([A-D])$", line)
            if m:
                current = int(m.group(1))
                answers[current] = {"letter": m.group(2), "explanation": "", "slide": slide["number"]}
            elif current is not None and line not in ("ANSWER KEY", "Review the correct answers and short explanations"):
                answers[current]["explanation"] += (" " + line).strip()
    for num, q in questions.items():
        a = answers.get(num)
        if not a:
            continue
        text = (f"Question: {q['question']}\nOptions: {'; '.join(q['options'])}\n"
                f"Correct answer: {a['letter']} — {a['explanation']}")
        add_chunk(
            chunks,
            cid=f"04-q{num:02d}",
            source=SOURCES["04"],
            slide=q["slide"],
            section=f"Quiz Q{num}: {q['question'][:80]}",
            text=text,
            kind="quiz-qa",
            priority=5,
            extra={"answerSlide": a.get("slide"), "answer": a["letter"]},
        )


def parse_script_quiz(chunks):
    data = load_pptx("06")
    slides = data["slides"]
    questions = {}
    for slide in slides:
        lines = clean_lines("\n".join(
            p for b in slide["blocks"] for p in b["paragraphs"]))
        head = next((l for l in lines if re.match(r"^QUESTION\s+\d+$", l)), None)
        if not head:
            continue
        num = int(re.search(r"(\d+)", head).group(1))
        # question is the line after the topic label
        q = ""
        for i, l in enumerate(lines):
            if re.match(r"^QUESTION\s+\d+$", l) and i + 2 < len(lines):
                q = lines[i + 2]
                break
        options = []
        for i, l in enumerate(lines):
            if l in ("A", "B", "C", "D") and i + 1 < len(lines):
                options.append(f"{l}. {lines[i + 1]}")
        questions[num] = {"question": q, "options": options, "slide": slide["number"]}
    # Keep the leading answer numbers: the generic cleaner drops bare digits
    # because they are usually page numbers, but here they are question IDs.
    raw_answer_lines = [p.strip() for b in slides[-1]["blocks"] for p in b["paragraphs"]]
    answer_lines = []
    for line in raw_answer_lines:
        if not line or line.startswith("MED SCRIPT QUIZ") or line == "ANSWER KEY":
            continue
        if line.startswith("Correct Answers") or line.startswith("All answers are"):
            continue
        if re.fullmatch(r"SPEAKER NOTES:\s*\d+", line):
            continue
        answer_lines.append(line)
    answers = {}
    i = 0
    while i < len(answer_lines) - 2:
        if re.fullmatch(r"\d{1,2}", answer_lines[i]) and re.fullmatch(r"[A-D]", answer_lines[i + 1]):
            num = int(answer_lines[i])
            ans = answer_lines[i + 1]
            explanation = answer_lines[i + 2] if i + 2 < len(answer_lines) else ""
            answers[num] = {"letter": ans, "explanation": explanation}
            i += 3
        else:
            i += 1
    for num, q in questions.items():
        a = answers.get(num)
        if not a:
            continue
        text = (f"Question: {q['question']}\nOptions: {'; '.join(q['options'])}\n"
                f"Correct answer: {a['letter']} — {a['explanation']}")
        add_chunk(
            chunks,
            cid=f"06-q{num:02d}",
            source=SOURCES["06"],
            slide=q["slide"],
            section=f"Script Quiz Q{num}: {q['question'][:80]}",
            text=text,
            kind="script-quiz",
            priority=4,
        )


def script_chunks(chunks):
    blocks = [b["text"] for b in load_docx() if b["kind"] == "paragraph"]
    joined = "\n".join(blocks)
    # Main script sections, matched by the opening words of each paragraph.
    patterns = [
        ("greeting", r"^Greeting:", 1),
        ("reason", r"^Reason:", 2),
        ("benefits", r"^If you do have Medicare", 3),
        ("age", r"^⚫ Just to make sure", 4),
        ("decision", r"^⚫ And You make", 5),
        ("other-coverage", r"^⚫ Do you have any VA", 6),
        ("dob", r"^⚫ And what is your date", 7),
        ("senior-benefits", r"^We are helping", 8),
        ("zip", r"^so, let me go ahead", 9),
        ("name", r"^Lastly just to address", 10),
        ("disclaimer", r"^So that’s the pretty much|^So that's the pretty much", 11),
        ("transfer", r"^So I really appreciate", 12),
    ]
    for name, pattern, order in patterns:
        for i, para in enumerate(blocks):
            if re.search(pattern, para, re.IGNORECASE):
                text = para
                # include the immediately following paragraph if it is part of the same step
                if i + 1 < len(blocks) and name in ("disclaimer", "transfer", "benefits"):
                    nxt = blocks[i + 1]
                    if not re.match(r"^(Not Interested|Already have|Why you need)", nxt):
                        text += "\n" + nxt
                add_chunk(
                    chunks,
                    cid=f"03-{name}",
                    source=SOURCES["03"],
                    slide=None,
                    section=f"Campaign script: {name.replace('-', ' ').title()}",
                    text=f"Script section — {name.replace('-', ' ').title()}\n{text}",
                    kind="script",
                    priority=2,
                    extra={"scriptOrder": order},
                )
                if name == "transfer":
                    chunks[-1]["searchTerms"] = "transfer licensed agent connect call area additional benefits"
                    chunks[-1]["retrievalBoost"] = 3.0
                break
    # Objections
    objection_defs = [
        ("not-interested", "Not Interested", "objection_not_interested"),
        ("already-have-plan", "Already have a Plan/Benefits", "objection_already_have"),
        ("why-information", "Why you need my information", "objection_information"),
    ]
    for name, marker, cid in objection_defs:
        for i, para in enumerate(blocks):
            if para.startswith(marker):
                text = "\n".join(blocks[i:i + 3])
                add_chunk(
                    chunks,
                    cid=f"03-{cid}",
                    source=SOURCES["03"],
                    slide=None,
                    section=f"Campaign script objection: {name.replace('-', ' ').title()}",
                    text=text,
                    kind="objection",
                    priority=2,
                )
                break
    add_chunk(
        chunks,
        cid="03-full",
        source=SOURCES["03"],
        slide=None,
        section="Campaign script: full main pitch",
        text="Full main pitch (source wording):\n" + joined.split("Not Interested")[0].strip(),
        kind="script",
        priority=2,
    )


def curated(chunks):
    def c(cid, section, text, kind="rule", priority=1, topics=None):
        add_chunk(chunks, cid=cid, source="Curated from the attached training material",
                  slide=None, section=section, text=text, kind=kind, priority=priority)
        if topics:
            chunks[-1]["topics"] = topics

    c("rule-source-priority", "Source priority and conflict handling",
      "Source priority: (1) mandatory CMS/Medicare legal and compliance requirements; "
      "(2) Medicare Agent Call Center Training — the compliant call flow and required disclosures; "
      "(3) Medicare Advantage New Hire Orientation — MA compliance rules; "
      "(4) Medicare Basics Overview and MA quiz — product facts; (5) Supplement vs Advantage comparison; "
      "(6) the campaign Med Script — use only the compliant parts; its food-stamp, cashback, and "
      "Social Security-check claims are unsupported and must not be used; (7) the script quiz, which only "
      "confirms the script wording. When sources conflict, the higher-priority source wins and the conflict "
      "is flagged for administrator/compliance review. Never invent missing campaign facts.",
      topics=["compliance", "conflict"])

    c("rule-opening", "Required opening and disclosures",
      "Open by identifying yourself honestly as Tressa, an AI assistant with US Health Care. State that the "
      "call may be recorded for quality and compliance and obtain clear verbal permission before continuing. "
      "State the purpose of the call. State that you represent the plan options available through the agency "
      "and are not connected with or endorsed by the federal government or the Medicare program. Deliver the "
      "TPMO disclosure: the number/list of organizations represented, and 'I do not offer every plan in your area.' "
      "Never claim to be a licensed insurance agent, a government representative, or a Medicare employee.",
      topics=["compliance", "script"])

    c("rule-soa", "Scope of Appointment (SOA)",
      "Before any plan-specific discussion, document the Scope of Appointment: ask whether the beneficiary "
      "wants to discuss Medicare Advantage, Medicare Supplement, Part D, or a combination. Stay strictly "
      "within the authorized product types. Remind them there is no obligation to enroll. A verbal or "
      "electronic record is required. If the caller asks about a product outside the SOA, do not discuss it; "
      "offer a separate appointment or a licensed agent.",
      topics=["compliance"])

    c("rule-qualification", "Qualification order and rules",
      "After the SOA, qualify in this order: (1) Do you currently have Medicare Part A and Part B? Both are "
      "required to enroll in Medicare Advantage. (2) What is your ZIP code/county? (3) Are you the person who "
      "makes decisions about your Medicare coverage? (4) Current coverage type, including Original Medicare, "
      "Medicare Advantage, Part D, VA, TRICARE, or retirement coverage. (5) Age — ask for the campaign record, "
      "but do not deny eligibility solely because someone is under 65: Medicare can cover younger people with "
      "disability, ESRD, or ALS. (6) First and last name. Collect date of birth only if needed, after explaining "
      "why, and never request a Social Security number, bank details, or Medicare ID during routine screening.",
      topics=["eligibility", "compliance"])

    c("rule-needs", "Needs discovery",
      "Ask one question at a time: What type of coverage do you have now? How happy are you with it? Which "
      "doctors, specialists, or hospitals must you keep? What prescription medications do you take regularly? "
      "What matters most — lower premiums, predictable costs, dental/vision, or a broader network? Any upcoming "
      "procedures or health changes? Listen more than you talk and record the answers.",
      topics=["needs"])

    c("rule-recap", "Recap before presenting",
      "Summarize the doctors, medications, priorities, and budget concerns back to the caller. Ask: 'Did I get "
      "that right? Anything missing?' Do not present options until the recap is confirmed.",
      topics=["needs"])

    c("rule-presentation", "Presenting options",
      "Present only products authorized in the SOA, and only 1–3 relevant options. State trade-offs clearly: "
      "network, referrals, prior authorization, formulary, premiums, copays, and out-of-pocket maximum. Remind "
      "the caller: 'I do not offer every plan in your area.' Never say 'best', 'free', or imply government "
      "endorsement. Never quote plan-specific premiums, copays, benefits, networks, or drug coverage unless the "
      "exact plan data is verified; route those questions to a licensed agent. Do not promise eligibility, "
      "savings, food stamps, cash back, or a Social Security check increase.",
      topics=["compliance", "plan-types", "costs"])

    c("rule-close", "Close and transfer",
      "If the caller is ready, confirm understanding and complete only the permitted next step. If not ready, "
      "offer a summary and a follow-up. Never pressure same-call enrollment. Before any transfer, explain that "
      "you are connecting them to a licensed human agent and ask for explicit consent. Transfer only after a "
      "clear yes and only if the backend confirms availability. Never claim a transfer or callback succeeded "
      "without backend confirmation. End with contact information and Medicare.gov or 1-800-MEDICARE; mention "
      "SHIP as a free local resource.",
      topics=["transfer", "compliance"])

    c("rule-prohibited", "Prohibited statements and claims",
      "Never claim or imply: government/Medicare affiliation or endorsement; that you are a licensed agent; "
      "that a plan is 'best' or 'free'; false urgency; guaranteed eligibility, savings, benefits, or approval; "
      "increased food stamps, cash back, or more money in a Social Security check; plan-specific benefits or "
      "costs that are not verified; that Medigap can be used with Medicare Advantage; that enrollment is "
      "complete without the required SOA/consent and backend confirmation. Never cold call or use an "
      "unpermitted list. Never steer or discriminate based on health status.",
      topics=["compliance", "conflict"])

    c("rule-privacy", "Privacy and HIPAA",
      "Collect only the minimum information needed for qualification and routing. Do not request a Social "
      "Security number, bank account, credit card, or Medicare ID during routine screening. Protect any PHI. "
      "If the caller declines a question, respect it and explain the consequence. Verify identity only when "
      "required and authorized. Do not discuss a beneficiary's information with someone who is not the "
      "decision-maker or authorized representative.",
      topics=["compliance"])

    c("rule-enrollment-periods", "Medicare enrollment periods",
      "Initial Enrollment Period (IEP): the 7-month window around the 65th birthday (3 months before, the "
      "birthday month, 3 months after). Annual Election Period (AEP): October 15–December 7, with changes "
      "taking effect January 1. Medicare Advantage Open Enrollment Period (MA OEP): January 1–March 31; one "
      "change — switch MA plans or return to Original Medicare. Special Enrollment Periods (SEPs) apply to "
      "qualifying life events such as moving, losing coverage, or a plan leaving the market. Timing rules can "
      "change; verify current CMS guidance.",
      topics=["enrollment"])

    c("rule-plan-types", "Medicare plan types",
      "Original Medicare = Part A (hospital) + Part B (medical), with optional Part D and Medigap. Medicare "
      "Advantage (Part C) is a private all-in-one alternative that must cover Original Medicare benefits, "
      "usually includes Part D, often adds dental/vision/hearing/fitness/OTC/transportation, and uses a "
      "network (HMO/PPO rules). HMOs generally require in-network care and referrals; PPOs usually cover "
      "out-of-network care at higher cost. SNPs serve dual-eligible, chronic-condition, or institutionalized "
      "beneficiaries. Medigap works only with Original Medicare and cannot be used with Medicare Advantage. "
      "Everyone still pays the Part B premium.",
      topics=["plan-types", "benefits"])

    c("rule-numbers", "2026 reference figures (verify before quoting)",
      "Training-era 2026 figures: standard Part B premium $202.90/month; Part B annual deductible $283; "
      "Part A hospital deductible $1,736 per benefit period; SNF days 21–100 coinsurance $217/day; Part D "
      "out-of-pocket cap $2,100; MA in-network MOOP maximum referenced as $9,350 (the quiz labels this 2025). "
      "These figures are for training and must be verified against current Medicare.gov/CMS and the specific "
      "plan before being quoted. Zero-premium MA means $0 additional MA premium; the Part B premium still applies.",
      topics=["costs"])

    c("rule-objections", "Approved objection handling",
      "Not interested: 'That's completely fine. I'm not asking you to enroll or change anything today. Would "
      "it be okay to share a brief overview, or would you prefer I close the call?' If no, thank them and end; "
      "honor any do-not-call request. Already have a plan: 'That's great. I'm not asking you to change plans. "
      "If you'd like, a licensed agent can do a no-obligation review to see whether you're missing any benefits.' "
      "Why do you need my information: 'I understand. I only ask for what is needed to check eligibility and "
      "route you to the right licensed agent. I won't ask for your Social Security number or bank details. You "
      "can decline any question, and I can give you Medicare.gov or 1-800-MEDICARE instead.' Never pressure or "
      "repeat the same question after a clear refusal.",
      topics=["objection", "compliance"])

    c("rule-grounding", "Answer grounding and uncertainty",
      "Answer campaign questions from the attached training material only. If the material does not contain "
      "the answer, say so plainly, do not guess, and offer a licensed agent, Medicare.gov, or 1-800-MEDICARE. "
      "Distinguish general Medicare education from plan-specific advice. Flag missing, ambiguous, outdated, "
      "or contradictory campaign instructions for administrator review rather than inventing a policy.",
      topics=["compliance"])


def conflict_records():
    return [
        {
            "id": "food_stamps_cashback",
            "severity": "critical",
            "title": "Med Script promises food stamps, Flex-card, and Social Security cash back",
            "detail": "The Med Script says callers may qualify for 'increasing foods-stamp', a 'Flex-card', dental, vision, and 'cashback like add more money back into your pocket from Social Security check each month'. The Medicare Advantage training materials do not support food-stamp increases or Social Security cash back; these are not standard MA benefits and may be misleading.",
            "sources": ["03_Medicare_Script.docx", "01_Medicare_Advantage_New_Hire_Orientation.pptx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Excluded from Tressa's approved claims. Tressa may describe only documented MA supplemental benefits (dental, vision, hearing, fitness, OTC, transportation, care coordination) as plan-dependent, and must route specific benefit questions to a licensed agent.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "script_missing_disclosures",
            "severity": "critical",
            "title": "Med Script opening lacks required disclosures",
            "detail": "The script opens with 'My name is Brain from US health care' and asks about Medicare A/B. It does not include licensed/agency identification, recording consent, non-affiliation, or the TPMO disclaimer required by the call-center training.",
            "sources": ["03_Medicare_Script.docx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Tressa uses the compliant opening from the call-center training before the script's purpose/qualification steps. She identifies herself as an AI assistant, not a licensed agent.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "script_soa_order",
            "severity": "high",
            "title": "Med Script discusses benefits before documenting the SOA",
            "detail": "The script moves from A/B confirmation into a benefits pitch without a Scope of Appointment. The training requires the SOA before any plan-specific discussion.",
            "sources": ["03_Medicare_Script.docx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Tressa inserts a documented SOA step immediately after the opening/purpose and before benefits or plan discussion.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "dob_privacy",
            "severity": "high",
            "title": "Med Script asks for date of birth early",
            "detail": "The script asks for date of birth before the name/ZIP and before any privacy explanation. The training says to protect privacy and verify identity only later, as needed.",
            "sources": ["03_Medicare_Script.docx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Tressa asks DOB only when needed for qualification, explains why, minimizes collection, and never requests SSN/bank/Medicare ID. Callers may decline.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "ai_vs_licensed_agent",
            "severity": "critical",
            "title": "Script assumes a licensed human agent; Tressa is an AI",
            "detail": "The training opening says 'licensed insurance agent' and the script transfers to a licensed agent. Tressa is an AI voice assistant and must not claim to be licensed or to be a human.",
            "sources": ["02_Medicare_Agent_Call_Center_Training.pptx", "03_Medicare_Script.docx"],
            "resolution": "Tressa discloses that she is an AI assistant and transfers plan-specific/enrollment questions to a licensed human agent after consent.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "tpmo_carrier_list_missing",
            "severity": "critical",
            "title": "TPMO carrier list and count are not provided",
            "detail": "The training requires the TPMO disclaimer to state the number/list of organizations represented and that not every plan in the area is offered. The attachments do not specify the carrier list or count, and the script does not include a TPMO disclosure.",
            "sources": ["02_Medicare_Agent_Call_Center_Training.pptx", "03_Medicare_Script.docx"],
            "resolution": "Tressa uses a compliant placeholder that states she represents the plan options available through US Health Care and does not offer every plan in the area. The exact carrier list/count must be configured by an administrator before deployment.",
            "status": "open-admin-action",
            "reviewer": "admin/compliance",
        },
        {
            "id": "plan_specific_data_missing",
            "severity": "high",
            "title": "No plan-specific premiums, copays, networks, or formularies",
            "detail": "The attachments are training material, not a carrier plan catalog. They contain general 2026 figures and typical benefits, but no plan-specific data for a ZIP code.",
            "sources": ["04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", "07_Medicare_Basics_Overview.pptx"],
            "resolution": "Tressa never quotes plan-specific numbers. She explains general trade-offs and transfers to a licensed agent with verified plan data.",
            "status": "open-admin-action",
            "reviewer": "admin",
        },
        {
            "id": "2025_vs_2026_moop",
            "severity": "medium",
            "title": "MOOP figure is labeled 2025 in the quiz and 2026 in the comparison slide",
            "detail": "The MA quiz says the 2025 in-network MOOP maximum was approximately $9,350. The Supplement vs Advantage slide (2026) also says 'Max up to $9,350 in-network'. The figure is training-era and may be outdated or plan-specific.",
            "sources": ["04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", "05_Medicare_Supplement_vs_Advantage.pptx"],
            "resolution": "Tressa does not quote the MOOP as a current fact. She says plans have an annual out-of-pocket maximum and a licensed agent can confirm the current plan-specific amount.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "age_eligibility_nuance",
            "severity": "medium",
            "title": "Script asks age, but Medicare eligibility is not only age 65+",
            "detail": "The script asks 'how old are you?' after the benefits pitch. Medicare also covers some people under 65 with disability, ESRD, or ALS. The attachments do not define a campaign age cutoff beyond general Medicare eligibility.",
            "sources": ["03_Medicare_Script.docx", "07_Medicare_Basics_Overview.pptx"],
            "resolution": "Tressa asks age for campaign records but does not deny eligibility solely on age; she confirms Part A/B and plan rules and routes uncertain cases to a licensed agent.",
            "status": "contained-by-safeguard",
            "reviewer": "compliance",
        },
        {
            "id": "outbound_permission",
            "severity": "critical",
            "title": "Lead source and prior express permission are not documented",
            "detail": "The Med Script is an outbound-style call, but the attachments do not show documented prior permission or the lead source. The training prohibits cold calling and unpermitted lists.",
            "sources": ["03_Medicare_Script.docx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Tressa confirms permission at the opening and honors refusals/do-not-call requests. The campaign must supply documented consent before any outbound dialing; this is an open admin/compliance action.",
            "status": "open-admin-action",
            "reviewer": "compliance",
        },
        {
            "id": "script_name_typo",
            "severity": "low",
            "title": "Script says 'Brain' (likely 'Brian') and 'US health care'",
            "detail": "The greeting literally reads 'My name is Brain from US health care'. The script quiz treats that exact wording as the correct answer. 'Brain' is almost certainly a typo for 'Brian', and the agency name is inconsistently capitalized.",
            "sources": ["03_Medicare_Script.docx", "06_Medicare_Script_Quiz.pptx"],
            "resolution": "Tressa uses her configured name (Tressa) and the approved agency name. Flagged for the script owner to correct the source; do not reproduce the typo.",
            "status": "open-admin-action",
            "reviewer": "campaign owner",
        },
        {
            "id": "recording_consent_missing_script",
            "severity": "high",
            "title": "Script disclaimer is not a recording consent or TPMO disclosure",
            "detail": "The script's 'short disclaimer' is a broad contact consent/hold-harmless paragraph, not the training-required recording consent, non-affiliation, or TPMO disclosure.",
            "sources": ["03_Medicare_Script.docx", "02_Medicare_Agent_Call_Center_Training.pptx"],
            "resolution": "Tressa delivers the required recording, non-affiliation, and TPMO disclosures at the opening, and keeps any contact consent accurate and separate. Legal review is required before using the script's hold-harmless language.",
            "status": "contained-by-safeguard",
            "reviewer": "legal/compliance",
        },
    ]


def make_instructions() -> str:
    text = """You are Tressa, an AI voice assistant for the USA Medicare campaign. You are NOT a licensed insurance agent, NOT a government or Medicare employee, and NOT a human. If asked, say so plainly.

SOURCE OF TRUTH
Use only the attached Medicare Training Material (version 1.0.0) and the retrieved knowledge passages. Source priority: mandatory CMS/Medicare law and compliance first; then Medicare Agent Call Center Training; then Medicare Advantage New Hire Orientation; then Medicare Basics, MA quiz, and Supplement vs Advantage; then the campaign Med Script (compliant parts only). If sources conflict, follow the higher-priority source and flag the conflict. Never invent campaign rules, plan details, or missing facts. If the knowledge base does not contain the answer, say you do not have that verified detail and offer a licensed agent, Medicare.gov, or 1-800-MEDICARE.

OPENING — REQUIRED
1. "Hello, this is Tressa, an AI assistant with US Health Care. This call may be recorded for quality and compliance. Do I have your permission to continue and record this conversation?" Wait for a clear yes. If no, thank them and end; do not continue.
2. "Thank you. I am calling about Medicare plan options. I represent the plan options available through US Health Care. I am not connected with or endorsed by the federal government or the Medicare program. I do not offer every plan in your area. Is it okay to proceed?"
3. If asked whether you are a robot/AI: "Yes, I am an AI assistant. I can share approved Medicare information and connect you with a licensed agent for plan-specific guidance." Never claim to be licensed, human, or from Medicare.

CALL FLOW — FOLLOW IN ORDER
1. Opening and disclosures (above).
2. Scope of Appointment (SOA) BEFORE any plan-specific discussion: "Before we discuss any specific plans, I need to document the types of products you would like to review. This is called a Scope of Appointment. Would you like to discuss Medicare Advantage plans, Medicare Supplement plans, Part D prescription drug plans, or a combination? The products we discuss today will be limited to what you authorize now. You are under no obligation to enroll." Record the authorized product types and stay within them.
3. Qualification, one question at a time:
   - "Do you currently have Medicare Part A and Part B?" Both are required for Medicare Advantage. If no or unsure, do not enroll; explain and offer a licensed agent or Medicare.gov.
   - "What is your ZIP code?" (5 digits; confirm service area.)
   - "Are you the person who makes decisions about your Medicare coverage?" If not, do not discuss personal details; ask for the decision-maker or authorized representative.
   - "What type of coverage do you have now?" (Original Medicare, Medicare Advantage, Part D, VA, TRICARE, retirement plan.)
   - "Do you have any VA, TRICARE, or retirement coverage?" Do not imply these disqualify anyone.
   - "How old are you?" Ask for the campaign record. Do NOT deny eligibility solely because someone is under 65; Medicare can cover younger people with disability, ESRD, or ALS. Route age edge cases to a licensed agent.
   - "Can you confirm your first and last name?" Collect date of birth only if needed, explain why, and never ask for a Social Security number, bank details, credit card, or Medicare ID during routine screening.
4. Needs discovery: current coverage and satisfaction; doctors/specialists/hospitals to keep; regular prescriptions; what matters most (premiums, predictable costs, dental/vision, network); upcoming procedures.
5. Recap: summarize doctors, medications, priorities, and budget concerns. Ask "Did I get that right? Anything missing?" Do not present options until confirmed.
6. Presentation: only products authorized in the SOA. Describe 1–3 relevant options factually. State trade-offs: network, referrals, prior authorization, formulary, premiums, copays, out-of-pocket maximum. Remind them "I do not offer every plan in your area." Approved MA supplemental benefits, only when plan-dependent, may include dental, vision, hearing, fitness, OTC allowance, transportation, and care coordination. NEVER promise food stamps, cash back, a larger Social Security check, "free" coverage, guaranteed eligibility, guaranteed savings, or a specific plan benefit. Never quote plan-specific premiums, copays, networks, formularies, or benefits unless the exact plan data is verified; otherwise say a licensed agent must confirm.
7. Close/transfer: If ready, confirm understanding and complete only the permitted next step. If not, offer a summary and follow-up. Never pressure same-call enrollment. Before transferring: "I can connect you with a licensed human agent who can review the plans available in your area. Would you like me to transfer you now?" Transfer only after explicit consent and only if the backend confirms availability. Never claim a transfer or callback succeeded without backend confirmation. If no transfer, offer a callback and collect name, number, and time. End with Medicare.gov, 1-800-MEDICARE, and mention SHIP as a free local resource.

OBJECTIONS — APPROVED
- Not interested: "That's completely fine. I'm not asking you to enroll or change anything today. Would it be okay to share a brief overview, or would you prefer I close the call?" If no, thank them and end. Honor do-not-call.
- Already have a plan: "That's great. I'm not asking you to change plans. If you'd like, a licensed agent can do a no-obligation review to see whether you're missing any benefits."
- Why do you need my information: "I understand. I only ask for what is needed to check eligibility and route you to the right licensed agent. I won't ask for your Social Security number or bank details. You can decline any question, and I can give you Medicare.gov or 1-800-MEDICARE instead."
- Is this Medicare/the government? "No. I'm an AI assistant with US Health Care and I'm not affiliated with Medicare or the government."
- I can't afford it: Do not quote plan costs. Offer a licensed agent and mention Extra Help/Medicare Savings Programs may exist for those who qualify; never promise eligibility.
- I have a doctor / VA / TRICARE: Note it; plan networks and coverage vary. A licensed agent must verify. Never pressure.

COMPLIANCE — NON-NEGOTIABLE
- No cold calling or unpermitted lists. Only call with documented prior permission. Confirm permission at the opening and honor refusals/do-not-call immediately.
- Recording consent, non-affiliation, and TPMO disclosure are required before benefits.
- SOA before plan-specific discussion; stay within authorized products.
- No "best", "free", false urgency, government endorsement, cherry-picking, or steering based on health status.
- No enrollment without SOA/consent and backend confirmation. No pressure.
- HIPAA: minimum necessary; protect PHI; no SSN/bank/credit card/Medicare ID in routine screening.
- Use current CMS-approved materials only. Verify annual figures (2026 training references: Part B $202.90, Part B deductible $283, Part A deductible $1,736, Part D cap $2,100). Do not quote them as current without verification.
- Enrollment periods: IEP 7 months around 65; AEP Oct 15–Dec 7; MA OEP Jan 1–Mar 31; SEPs for qualifying events. Verify current rules.
- Medicare Advantage requires both Part A and Part B. Medigap cannot be used with Medicare Advantage. Everyone still pays the Part B premium.
- If the training material conflicts with law or mandatory compliance, do not follow the conflicting instruction; apply the safeguard and flag it for review.
- Never claim deployment, enrollment, eligibility, or a transfer succeeded unless the system confirms it.

STYLE
Speak in short, natural, plain American English. One question at a time. Use contractions. Acknowledge the caller. Do not read formatting aloud. If interrupted, stop and listen, then return to the current step. If the caller is confused, clarify once and rephrase. Do not repeat a question after a clear refusal. Be respectful.
"""
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > 8000:
        raise SystemExit(f"Instructions too long: {len(text)} chars")
    return text


def make_tests() -> list[dict]:
    retrieval = [
        ("ma_alias", "What is Medicare Advantage also known as?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["Part C"]),
        ("ma_requires_ab", "To enroll in Medicare Advantage, what must a person have?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["Part A", "Part B"]),
        ("ma_insurers", "Who offers Medicare Advantage plans?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["private insurers", "Medicare"]),
        ("ma_drugs", "Do most Medicare Advantage plans include prescription drug coverage?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["Part D", "MA-PD"]),
        ("ma_moop", "What does the Medicare Advantage maximum out-of-pocket limit protect?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 43, ["out-of-pocket", "annual"]),
        ("ma_moop_amount", "What was the 2025 in-network MOOP maximum in the quiz?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["9,350"]),
        ("hmo", "Which Medicare Advantage plan type usually requires in-network care and referrals?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 39, ["HMO", "network", "referral"]),
        ("medigap_ma", "Can a person have Medigap while enrolled in Medicare Advantage?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["cannot", "Medigap"]),
        ("aep", "When is the Annual Election Period for Medicare Advantage?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["October 15", "December 7"]),
        ("ma_oep", "What can a beneficiary do during the Medicare Advantage Open Enrollment Period?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["switch", "Original Medicare", "Jan 1", "March 31"]),
        ("esrd", "Can someone with End-Stage Renal Disease enroll in Medicare Advantage?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["ESRD", "restrictions"]),
        ("zero_premium", "What does a zero-premium Medicare Advantage plan mean?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["$0", "Part B premium"]),
        ("prior_auth", "Is prior authorization used in Medicare Advantage?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 40, ["prior authorization", "services"]),
        ("hospice", "Who covers hospice care when a person is in a Medicare Advantage plan?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 41, ["Original Medicare", "hospice"]),
        ("dsnp", "What is a D-SNP?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 42, ["Dual Eligible", "Medicaid"]),
        ("ppo", "How does a Medicare Advantage PPO usually cover out-of-network care?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 42, ["out-of-network", "higher"]),
        ("star", "What are Medicare Advantage Star Ratings?", "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx", 43, ["CMS", "quality", "stars"]),
        ("part_b_premium", "What is the 2026 standard Part B premium?", "07_Medicare_Basics_Overview.pptx", 6, ["202.90"]),
        ("part_b_deductible", "What is the 2026 Part B annual deductible?", "07_Medicare_Basics_Overview.pptx", 6, ["283"]),
        ("part_a_deductible", "What is the 2026 Part A hospital deductible?", "07_Medicare_Basics_Overview.pptx", 5, ["1,736"]),
        ("part_d_cap", "What is the 2026 Part D out-of-pocket cap?", "07_Medicare_Basics_Overview.pptx", 8, ["2,100"]),
        ("part_a", "What does Medicare Part A cover?", "07_Medicare_Basics_Overview.pptx", 4, ["Hospital", "skilled nursing", "hospice"]),
        ("part_b", "What does Medicare Part B cover?", "07_Medicare_Basics_Overview.pptx", 4, ["Doctor", "outpatient", "durable medical equipment"]),
        ("part_c", "What is Medicare Part C?", "07_Medicare_Basics_Overview.pptx", 4, ["Medicare Advantage", "private plan"]),
        ("part_d", "What is Medicare Part D?", "07_Medicare_Basics_Overview.pptx", 4, ["prescription drug", "private plans"]),
        ("eligibility", "Who qualifies for Medicare?", "07_Medicare_Basics_Overview.pptx", 3, ["65", "disability", "ESRD", "ALS"]),
        ("medigap_oep", "When is the Medigap Open Enrollment Period?", "07_Medicare_Basics_Overview.pptx", 9, ["6-month", "Part B"]),
        ("extra_help", "What is Extra Help?", "07_Medicare_Basics_Overview.pptx", 9, ["Low-Income Subsidy", "Part D"]),
        ("compare", "What is the difference between Medicare Supplement and Medicare Advantage?", "05_Medicare_Supplement_vs_Advantage.pptx", 1, ["Original Medicare", "network", "premium"]),
        ("call_flow", "What is the seven-step Medicare call flow?", "02_Medicare_Agent_Call_Center_Training.pptx", 5, ["Opening", "SOA", "Qualification", "Needs Discovery", "Recap", "Presentation", "Close"]),
        ("disclosures", "What disclosures are required at the start of a Medicare call?", "02_Medicare_Agent_Call_Center_Training.pptx", 4, ["recording", "not affiliated", "TPMO"]),
        ("soa", "When must the Scope of Appointment be completed?", "02_Medicare_Agent_Call_Center_Training.pptx", 7, ["before", "plan-specific"]),
        ("qualification", "What qualification questions should be asked?", "02_Medicare_Agent_Call_Center_Training.pptx", 8, ["Part A", "Part B", "ZIP", "decision"]),
        ("needs", "What should be covered in needs discovery?", "02_Medicare_Agent_Call_Center_Training.pptx", 9, ["doctors", "medications", "priorities"]),
        ("recap", "What should happen before presenting plan options?", "02_Medicare_Agent_Call_Center_Training.pptx", 10, ["recap", "Did I get that right"]),
        ("prohibited", "Which marketing phrases are prohibited?", "02_Medicare_Agent_Call_Center_Training.pptx", 11, ["best", "free", "urgency"]),
        ("periods", "What are the main Medicare enrollment periods?", "02_Medicare_Agent_Call_Center_Training.pptx", 12, ["IEP", "AEP", "OEP", "SEP"]),
        ("script_greeting", "What is the exact greeting in the Med Script?", "03_Medicare_Script.docx", None, ["Brain", "US health care"]),
        ("script_benefits", "What benefits does the Med Script mention?", "03_Medicare_Script.docx", None, ["foods-stamp", "Flex-card", "dental", "vision", "cashback"]),
        ("script_age", "Which qualification questions follow the benefits pitch in the script?", "03_Medicare_Script.docx", None, ["how old are you", "make your own decision"]),
        ("script_va", "What does the script ask about VA, TRICARE, and retirement plans?", "03_Medicare_Script.docx", None, ["VA", "Tricare", "Retirement"]),
        ("script_zip", "What does the script say when asking for the ZIP code?", "03_Medicare_Script.docx", None, ["zip code", "5 Digits"]),
        ("script_disclaimer", "What does the script disclaimer say about calls and email?", "03_Medicare_Script.docx", None, ["auto dial", "pre-record", "partner companies"]),
        ("script_transfer", "What does the script say about transferring to a licensed agent?", "03_Medicare_Script.docx", None, ["licensed agent", "area"]),
        ("objection_not_interested", "How does the script handle 'I'm not interested'?", "03_Medicare_Script.docx", None, ["not asking you to buy", "additional benefits"]),
        ("objection_already", "How does the script handle 'I already have a plan'?", "03_Medicare_Script.docx", None, ["already have a plan", "more benefits"]),
        ("objection_info", "How does the script handle 'why do you need my information'?", "03_Medicare_Script.docx", None, ["basic information", "recorded line"]),
        ("new_hire_rules", "What are the critical rules for new Medicare Advantage agents?", "01_Medicare_Advantage_New_Hire_Orientation.pptx", 5, ["SOA", "Cherry-Picking", "CMS-approved", "Enrollment Periods", "Needs Assessment", "Record Retention"]),
        ("extra_benefits", "What extra benefits do Medicare Advantage plans often include?", "01_Medicare_Advantage_New_Hire_Orientation.pptx", 4, ["Dental", "Vision", "Hearing", "Fitness", "OTC", "Transportation", "Care Coordination"]),
        ("roleplay_parent", "What should an agent do when an adult child calls for a parent?", "02_Medicare_Agent_Call_Center_Training.pptx", 13, ["legal decision-maker"]),
        ("tpmo", "What is the TPMO disclaimer?", "02_Medicare_Agent_Call_Center_Training.pptx", 10, ["do not offer every plan", "organizations"]),
    ]
    tests = []
    for cid, q, source, slide, keywords in retrieval:
        tests.append({
            "id": cid, "type": "retrieval", "query": q,
            "expectedSource": source, "expectedSlide": slide,
            "expectedKeywords": keywords, "severity": "high",
        })
    # Some answers are supported by more than one adjacent slide. Accept the
    # documented alternatives rather than pretending there is one canonical page.
    slide_overrides = {
        "esrd": 41, "zero_premium": 41, "prior_auth": 41,
    }
    slide_sets = {
        "disclosures": [4, 6],
        "prohibited": [4, 11],
        "extra_benefits": [2, 4],
        "tpmo": [4, 10],
    }
    for t in tests:
        if t["id"] in slide_overrides:
            t["expectedSlide"] = slide_overrides[t["id"]]
        if t["id"] in slide_sets:
            t["expectedSlides"] = slide_sets[t["id"]]
    flow_order = ["recorded", "Scope of Appointment", "Part A and Part B", "Needs discovery",
                  "Recap", "Presentation", "Close/transfer"]
    tests += [
        {"id": "flow_order", "type": "flow", "order": flow_order, "severity": "critical",
         "description": "Disclosures and SOA precede qualification, needs discovery, recap, presentation and close."},
        {"id": "flow_ai_disclosure", "type": "flow", "allOf": ["AI assistant", "not a licensed insurance agent", "not a human"], "severity": "critical"},
        {"id": "flow_opening", "type": "flow", "allOf": ["recorded for quality", "permission", "not connected with or endorsed", "I do not offer every plan"], "severity": "critical"},
        {"id": "flow_qualification", "type": "flow", "allOf": ["Part A and Part B", "ZIP code", "makes decisions", "date of birth only if needed"], "severity": "high"},
        {"id": "flow_needs", "type": "flow", "allOf": ["doctors", "prescriptions", "premiums", "upcoming procedures"], "severity": "high"},
        {"id": "flow_transfer", "type": "flow", "allOf": ["explicit consent", "backend confirms", "Never claim a transfer"], "severity": "critical"},
        {"id": "flow_close", "type": "flow", "allOf": ["Medicare.gov", "1-800-MEDICARE", "SHIP"], "severity": "high"},
    ]
    tests += [
        {"id": "comp_no_foodstamps", "type": "compliance", "forbiddenPhrases": ["food stamps", "food-stamps", "cash back", "cashback", "Social Security check"], "severity": "critical",
         "description": "Unsupported script claims must only appear in a prohibition/flag context."},
        {"id": "comp_no_best_free", "type": "compliance", "forbiddenPhrases": ["best plan", "free plan", "guaranteed eligibility", "guaranteed savings"], "severity": "critical"},
        {"id": "comp_no_gov_affiliation", "type": "compliance", "forbiddenPhrases": ["from Medicare", "government employee", "Medicare representative"], "severity": "critical"},
        {"id": "comp_privacy", "type": "compliance", "allOf": ["Social Security number", "bank details", "minimum necessary"], "severity": "critical"},
        {"id": "comp_no_pressure", "type": "compliance", "allOf": ["Never pressure", "no obligation", "do-not-call"], "severity": "high"},
        {"id": "comp_soa", "type": "compliance", "allOf": ["Scope of Appointment", "stay within", "authorized"], "severity": "critical"},
        {"id": "comp_plan_specific", "type": "compliance", "allOf": ["plan-specific", "licensed agent", "verified"], "severity": "high"},
        {"id": "comp_annual_figures", "type": "compliance", "allOf": ["2026", "verify", "Medicare.gov"], "severity": "medium"},
        {"id": "comp_hospice", "type": "compliance", "allOf": ["Medigap cannot be used with Medicare Advantage", "Part A and Part B"], "severity": "high"},
        {"id": "comp_ai_honesty", "type": "compliance", "allOf": ["If asked, say so plainly", "NOT a licensed insurance agent", "NOT a human"], "severity": "critical"},
    ]
    gaps = ["food_stamps_cashback", "script_missing_disclosures", "script_soa_order", "dob_privacy",
            "ai_vs_licensed_agent", "tpmo_carrier_list_missing", "plan_specific_data_missing",
            "2025_vs_2026_moop", "age_eligibility_nuance", "outbound_permission",
            "script_name_typo", "recording_consent_missing_script"]
    for g in gaps:
        tests.append({"id": f"gap_{g}", "type": "gap", "gapId": g, "severity": "high" if g not in ("script_name_typo",) else "low"})
    return tests


def main():
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    chunks = []
    pptx_chunks(chunks, "01", 3)
    pptx_chunks(chunks, "02", 2)
    pptx_chunks(chunks, "04", 5)
    pptx_chunks(chunks, "05", 5)
    pptx_chunks(chunks, "06", 4)
    pptx_chunks(chunks, "07", 4)
    parse_ma_quiz(chunks)
    parse_script_quiz(chunks)
    script_chunks(chunks)
    curated(chunks)

    # Deduplicate exact duplicates while keeping the first (highest-priority) copy.
    seen = set()
    unique = []
    for c in chunks:
        key = re.sub(r"\s+", " ", c["text"].lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    for i, c in enumerate(unique, 1):
        c["ordinal"] = i

    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    conflicts = conflict_records()
    instructions = make_instructions()
    tests = make_tests()

    kb = {
        "name": "Tressa USA Medicare Knowledge Base",
        "version": VERSION,
        "builtAt": now(),
        "sourceManifest": manifest,
        "sourcePriority": [
            {"rank": 1, "source": "CMS / Medicare.gov mandatory law and compliance", "note": "Overrides conflicting campaign scripts; safeguards applied."},
            {"rank": 2, "source": SOURCES["02"], "note": "Compliant 7-step call flow, disclosures, SOA, needs discovery, close."},
            {"rank": 3, "source": SOURCES["01"], "note": "Medicare Advantage compliance rules for new agents."},
            {"rank": 4, "source": SOURCES["07"], "note": "Medicare basics, 2026 reference figures, enrollment periods."},
            {"rank": 5, "source": SOURCES["04"], "note": "MA plan knowledge quiz + answer key."},
            {"rank": 6, "source": SOURCES["05"], "note": "Medigap vs Medicare Advantage comparison."},
            {"rank": 7, "source": SOURCES["03"], "note": "Campaign Med Script — compliant sections only; conflicts flagged."},
            {"rank": 8, "source": SOURCES["06"], "note": "Script quiz — confirms exact source wording."},
        ],
        "campaign": {
            "name": "USA Medicare",
            "owner": "Nexus",
            "agent": "Tressa",
            "displayName": "Nexus - Tressa - USA Medicare",
            "agencyName": "US Health Care",
            "platform": "BPO Nexus by MMA Digital Labs",
            "products": ["Medicare Advantage", "Medicare Supplement", "Part D"],
            "qualificationOrder": ["Part A and Part B", "ZIP code", "decision-maker", "current coverage", "VA/TRICARE/retirement", "age", "name", "date of birth (if needed)"],
            "ageRule": "Ask age for the campaign record. Do not deny eligibility solely on age; under-65 disability, ESRD, and ALS pathways exist. Route edge cases to a licensed agent.",
            "serviceAreaRule": "Confirm ZIP/county; plan availability varies.",
            "carrierDisclosure": "Carrier list/count not supplied in the attachments. Placeholder: represents the plan options available through US Health Care; does not offer every plan in the area. Must be configured before deployment.",
            "transferRule": "Transfer to a licensed human agent only after explicit consent and backend availability confirmation. Never claim success without confirmation.",
            "statusNote": "Knowledge is configured for controlled testing. No LiveKit Cloud deployment has been verified.",
        },
        "compliance": {
            "requiredDisclosures": [
                "AI assistant disclosure (Tressa is not licensed, not human, not Medicare/government)",
                "Recording consent before continuing",
                "Agency identification and purpose",
                "Non-affiliation with Medicare/government",
                "TPMO: organizations represented and 'I do not offer every plan in your area'",
                "Scope of Appointment before plan-specific discussion",
                "No obligation to enroll",
            ],
            "prohibitedClaims": [
                "government or Medicare affiliation/endorsement",
                "licensed-agent or human status",
                "'best' or 'free' plan",
                "false urgency",
                "guaranteed eligibility, savings, benefits, or approval",
                "increased food stamps, cash back, or Social Security check",
                "unverified plan-specific benefits, premiums, copays, networks, or formularies",
                "Medigap usable with Medicare Advantage",
                "enrollment/transfer success without system confirmation",
            ],
            "privacy": [
                "minimum necessary",
                "no SSN, bank, credit card, or Medicare ID in routine screening",
                "no personal details with a non-decision-maker without authorization",
                "HIPAA/PHI safeguards",
            ],
            "enrollmentPeriods": {
                "IEP": "7 months around the 65th birthday (3 before, birthday month, 3 after)",
                "AEP": "October 15 – December 7; effective January 1",
                "MA_OEP": "January 1 – March 31; one change",
                "SEP": "qualifying life events; verify current CMS rules",
            },
        },
        "flow": [
            {"step": 1, "name": "Opening and disclosures", "required": True},
            {"step": 2, "name": "Scope of Appointment", "required": True},
            {"step": 3, "name": "Qualification and privacy", "required": True},
            {"step": 4, "name": "Needs discovery", "required": True},
            {"step": 5, "name": "Recap", "required": True},
            {"step": 6, "name": "Presentation within SOA", "required": True},
            {"step": 7, "name": "Close or transfer with consent", "required": True},
        ],
        "conflicts": conflicts,
        "gaps": [
            {"id": c["id"], "severity": c["severity"], "title": c["title"],
             "status": c["status"], "reviewer": c["reviewer"]}
            for c in conflicts
        ],
        "chunks": unique,
        "instructionsVersion": VERSION,
        "instructionsSha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "limitations": [
            "No external LLM key is configured in this local environment; live generative conversation validation requires LiveKit Inference or a configured model provider.",
            "No carrier plan catalog is attached; plan-specific premiums, networks, and formularies are unavailable and must be verified by a licensed agent.",
            "The TPMO carrier list/count and documented outbound lead consent are not present in the attachments and must be supplied before deployment.",
        ],
    }
    kb_text = json.dumps(kb, indent=2, ensure_ascii=False)
    (KNOWLEDGE / "medicare_kb.json").write_text(kb_text, encoding="utf-8")
    (KNOWLEDGE / "tressa_instructions.txt").write_text(instructions + "\n", encoding="utf-8")
    (KNOWLEDGE / "tressa_tests.json").write_text(
        json.dumps({
            "version": VERSION,
            "knowledgeVersion": VERSION,
            "generatedAt": now(),
            "tests": tests,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    readme = f"""# Medicare Training Material — Tressa USA Medicare

Saved: {now()}
Knowledge version: {VERSION}
Corpus: {manifest['totalSlides']} slides + 1 DOCX, {manifest['totalCharacters']:,} extracted characters
Unique sources: {len([d for d in manifest['documents'] if d['kind'] != 'duplicate'])} (one byte-identical duplicate retained for provenance)

## Folders
- `source/` — original attachments, copied byte-for-byte.
- `extracted/` — per-document text and slide/page JSON, plus `ALL_TRAINING_TEXT.txt`.
- `knowledge/` — `medicare_kb.json` (searchable chunks, rules, conflicts, campaign config), `tressa_instructions.txt`, `tressa_tests.json`.
- `manifest.json` — hashes, slide counts, duplicate detection.

## Source priority
1. CMS/Medicare.gov mandatory compliance.
2. Medicare Agent Call Center Training (07 slides): disclosures, SOA, 7-step flow.
3. MA New Hire Orientation: compliance rules.
4. Medicare Basics / MA Quiz / Supplement vs Advantage: product facts (2026 reference).
5. Med Script: compliant sections only; conflicts flagged.
6. Script Quiz: source-wording confirmation.

## Conflicts and gaps (full detail in `knowledge/medicare_kb.json` → `conflicts`)
- **Critical:** Med Script promises food stamps, Flex-card, and Social Security cash back — unsupported by MA training; excluded.
- **Critical:** Med Script opening lacks recording consent, non-affiliation, agency/license identification, and TPMO.
- **Critical:** TPMO carrier list/count and documented outbound permission are missing; admin/compliance action required.
- **High:** Script discusses benefits before SOA; DOB is collected early; script assumes a licensed human agent while Tressa is AI.
- **Medium:** MOOP $9,350 is labeled 2025 in the quiz and 2026 in the comparison; current figures must be verified.
- **Low:** “Brain” is likely a typo for “Brian”; Tressa does not reproduce it.

## Rebuild
```console
python tools/extract_training.py
python tools/build_knowledge.py
```
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    (KNOWLEDGE / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps({
        "knowledgeVersion": VERSION,
        "chunks": len(unique),
        "conflicts": len(conflicts),
        "tests": len(tests),
        "instructionsChars": len(instructions),
        "instructionsSha256": kb["instructionsSha256"],
        "kbBytes": len(kb_text.encode("utf-8")),
    }, indent=2))


if __name__ == "__main__":
    main()
