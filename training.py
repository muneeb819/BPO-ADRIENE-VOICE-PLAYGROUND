#!/usr/bin/env python3
"""Tressa USA Medicare training knowledge, retrieval, and validation.

This module is deliberately dependency-free. The Nexus server loads the
knowledge bundle built by tools/build_knowledge.py and exposes it through the
training API. Retrieval is BM25 over slide-level chunks; answers are extractive
and always carry a source/slide reference so administrators can audit them.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRAINING_ROOT = ROOT / "Medicare Training Material"
KNOWLEDGE_DIR = TRAINING_ROOT / "knowledge"
EXTRACTED_DIR = TRAINING_ROOT / "extracted"
KB_PATH = KNOWLEDGE_DIR / "medicare_kb.json"
INSTRUCTIONS_PATH = KNOWLEDGE_DIR / "tressa_instructions.txt"
TESTS_PATH = KNOWLEDGE_DIR / "tressa_tests.json"
DATA_DIR = ROOT / "data"
VALIDATION_PATH = DATA_DIR / "tressa-validation.json"
REPORT_PATH = TRAINING_ROOT / "validation_report.json"
REPORT_MD_PATH = TRAINING_ROOT / "VALIDATION_REPORT.md"

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can",
    "could", "did", "do", "does", "for", "from", "had", "has", "have", "how",
    "i", "if", "in", "into", "is", "it", "its", "may", "me", "my", "of", "on",
    "or", "our", "should", "so", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "was", "we", "were", "what",
    "when", "where", "which", "who", "why", "will", "with", "would", "you",
    "your", "about", "after", "before", "over", "under", "also", "any",
}

NEGATION = re.compile(
    r"\b(never|not|no|don't|do not|does not|cannot|can't|avoid|prohibited|"
    r"excluded|without|must not|should not|flag|conflict|unsupported)\b",
    re.IGNORECASE,
)

_lock = threading.RLock()
_cache = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())
    out = []
    for word in words:
        word = word.strip("'")
        if len(word) < 2 or word in STOPWORDS:
            continue
        # A tiny amount of normalization helps "plans"/"plan", "enrolled"/"enroll".
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


class TrainingStore:
    def __init__(self):
        self.kb = {}
        self.chunks = []
        self.docs = []
        self.df = Counter()
        self.avgdl = 1.0
        self.instructions = ""
        self.tests = []
        self.validation = None
        self._load()

    def _load(self):
        if not KB_PATH.exists():
            raise FileNotFoundError(f"Knowledge base not found: {KB_PATH}")
        self.kb = read_json(KB_PATH)
        self.chunks = list(self.kb.get("chunks") or [])
        self.instructions = INSTRUCTIONS_PATH.read_text(encoding="utf-8") if INSTRUCTIONS_PATH.exists() else ""
        self.tests = read_json(TESTS_PATH)["tests"] if TESTS_PATH.exists() else []
        if VALIDATION_PATH.exists():
            try:
                self.validation = read_json(VALIDATION_PATH)
            except (OSError, ValueError):
                self.validation = None
        self._index()

    def _index(self):
        self.docs = []
        self.df = Counter()
        total = 0
        for chunk in self.chunks:
            haystack = " ".join([
                str(chunk.get("section") or ""),
                str(chunk.get("text") or ""),
                " ".join(chunk.get("topics") or []),
                str(chunk.get("searchTerms") or ""),
                str(chunk.get("kind") or ""),
            ])
            tokens = tokenize(haystack)
            counts = Counter(tokens)
            self.docs.append({
                "chunk": chunk,
                "tokens": counts,
                "length": max(1, len(tokens)),
                "normalized": " " + " ".join(tokens) + " ",
            })
            for term in counts:
                self.df[term] += 1
            total += max(1, len(tokens))
        self.avgdl = (total / len(self.docs)) if self.docs else 1.0

    # ---- retrieval -------------------------------------------------------

    def search(self, query: str, limit: int = 8) -> list[dict]:
        terms = tokenize(query)
        if not terms:
            return []
        n = len(self.docs)
        k1, b = 1.45, 0.72
        scores = []
        phrase = " " + " ".join(terms) + " "
        for doc in self.docs:
            score = 0.0
            counts = doc["tokens"]
            dl = doc["length"]
            for term in set(terms):
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = self.df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self.avgdl))
            if not score:
                continue
            # Phrase and title matches make slide-level hits more precise.
            if phrase.strip() and phrase in doc["normalized"]:
                score += 4.0
            section = str(doc["chunk"].get("section") or "").lower()
            for term in set(terms):
                if term in section:
                    score += 0.35
            kind = doc["chunk"].get("kind")
            kind_boost = {
                "quiz-qa": 4.0,
                "script-quiz": 0.6,
                "objection": 0.8,
                "script": 0.7,
                "rule": 0.1,
            }.get(kind, 0.0)
            source = str(doc["chunk"].get("source") or "")
            source_boost = 0.0
            if source.startswith("02_"):
                source_boost = 2.4
            elif source.startswith("03_"):
                source_boost = 2.0
            elif source.startswith("01_"):
                source_boost = 0.9
            elif source.startswith("07_"):
                source_boost = 1.1
            elif source.startswith("04_"):
                source_boost = 0.6
            elif source.startswith("05_"):
                source_boost = 0.5
            elif source.startswith("06_"):
                source_boost = 0.1
            score += kind_boost + source_boost + float(doc["chunk"].get("retrievalBoost") or 0.0)
            scores.append((score, doc["chunk"]))
        scores.sort(key=lambda item: item[0], reverse=True)
        results = []
        for score, chunk in scores[:max(1, min(limit, 20))]:
            results.append({
                "score": round(score, 3),
                "id": chunk.get("id"),
                "source": chunk.get("source"),
                "slide": chunk.get("slide"),
                "answerSlide": chunk.get("answerSlide"),
                "section": chunk.get("section"),
                "kind": chunk.get("kind"),
                "topics": chunk.get("topics") or [],
                "text": chunk.get("text"),
                "sourcePriority": chunk.get("sourcePriority"),
            })
        return results

    def answer(self, query: str, limit: int = 3) -> dict:
        results = self.search(query, limit=limit)
        if not results:
            return {
                "query": query,
                "answer": (
                    "The attached training material does not contain a verified answer to that "
                    "question. I should not guess. Please route the caller to a licensed agent, "
                    "Medicare.gov, or 1-800-MEDICARE, and flag the gap for administrator review."
                ),
                "confidence": "none",
                "sources": [],
                "grounded": False,
            }
        top = results[0]
        # Extractive answer: keep the top passage, trimmed at a sentence boundary.
        text = re.sub(r"\s+", " ", str(top.get("text") or "")).strip()
        if len(text) > 900:
            cut = text[:900]
            boundary = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
            text = cut[:boundary + 1] if boundary > 300 else cut.rstrip() + "…"
        source = top.get("source")
        slide = top.get("answerSlide") or top.get("slide")
        location = f"{source}" + (f", slide {slide}" if slide else "")
        confidence = "high" if top.get("score", 0) >= 8 else "medium"
        return {
            "query": query,
            "answer": f"According to the training material ({location}): {text}",
            "confidence": confidence,
            "grounded": True,
            "sources": [
                {
                    "source": r.get("source"), "slide": r.get("answerSlide") or r.get("slide"),
                    "section": r.get("section"), "score": r.get("score"), "kind": r.get("kind"),
                }
                for r in results
            ],
        }

    # ---- summary / documents --------------------------------------------

    def summary(self) -> dict:
        manifest = self.kb.get("sourceManifest") or {}
        kinds = Counter(c.get("kind") for c in self.chunks)
        docs = []
        for doc in manifest.get("documents", []):
            file = doc.get("file")
            stem = Path(file).stem
            docs.append({
                **doc,
                "hasExtractedText": (EXTRACTED_DIR / f"{stem}.txt").exists(),
                "extractedPath": f"Medicare Training Material/extracted/{stem}.txt",
            })
        latest = self.validation or {}
        return {
            "version": self.kb.get("version"),
            "name": self.kb.get("name"),
            "builtAt": self.kb.get("builtAt"),
            "sourceManifest": {
                "sourceCount": manifest.get("sourceCount"),
                "documents": docs,
                "duplicates": manifest.get("duplicates", []),
                "warnings": manifest.get("warnings", []),
                "totalSlides": manifest.get("totalSlides"),
                "totalCharacters": manifest.get("totalCharacters"),
            },
            "chunkCount": len(self.chunks),
            "chunkKinds": dict(kinds),
            "sourcePriority": self.kb.get("sourcePriority", []),
            "campaign": self.kb.get("campaign", {}),
            "compliance": self.kb.get("compliance", {}),
            "flow": self.kb.get("flow", []),
            "conflicts": self.kb.get("conflicts", []),
            "gaps": self.kb.get("gaps", []),
            "instructions": {
                "version": self.kb.get("instructionsVersion"),
                "sha256": self.kb.get("instructionsSha256"),
                "characters": len(self.instructions),
                "path": "Medicare Training Material/knowledge/tressa_instructions.txt",
            },
            "tests": {
                "total": len(self.tests),
                "byType": dict(Counter(t.get("type") for t in self.tests)),
                "path": "Medicare Training Material/knowledge/tressa_tests.json",
            },
            "validation": {
                "generatedAt": latest.get("generatedAt"),
                "summary": latest.get("summary"),
                "readiness": latest.get("readiness"),
                "limitations": latest.get("limitations", []),
                "available": bool(latest),
            },
            "limitations": self.kb.get("limitations", []),
        }

    def documents(self) -> list[dict]:
        return self.summary()["sourceManifest"]["documents"]

    def document_text(self, file_name: str) -> dict:
        # Whitelist only files registered in the manifest.
        allowed = {d["file"]: d for d in self.documents()}
        if file_name not in allowed:
            raise KeyError(file_name)
        doc = allowed[file_name]
        stem = Path(file_name).stem
        path = EXTRACTED_DIR / f"{stem}.txt"
        if not path.exists():
            return {
                "file": file_name,
                "kind": doc.get("kind"),
                "text": "No extracted text exists for this entry (it is a duplicate or unsupported file).",
                "available": False,
            }
        return {
            "file": file_name,
            "kind": doc.get("kind"),
            "available": True,
            "text": path.read_text(encoding="utf-8"),
        }

    # ---- validation ------------------------------------------------------

    def _context_guarded(self, phrase: str, text: str) -> tuple[bool, list[str]]:
        """True when every occurrence is inside a prohibition/negation clause."""
        occurrences = []
        start = 0
        low = text.lower()
        needle = phrase.lower()
        while True:
            idx = low.find(needle, start)
            if idx < 0:
                break
            window = text[max(0, idx - 160): idx + len(phrase) + 40]
            occurrences.append(window)
            start = idx + len(needle)
        if not occurrences:
            return True, []
        return all(NEGATION.search(w) for w in occurrences), occurrences

    def validate(self, agent: dict | None = None) -> dict:
        results = []
        instructions = self.instructions
        low_inst = instructions.lower()

        for case in self.tests:
            cid = case.get("id")
            typ = case.get("type")
            status = "fail"
            detail = ""
            extra = {}
            if typ == "retrieval":
                hits = self.search(case.get("query", ""), limit=6)
                expected_source = case.get("expectedSource")
                expected_slide = case.get("expectedSlide")
                expected_slides = case.get("expectedSlides")
                if expected_slides is None and expected_slide is not None:
                    expected_slides = [expected_slide]
                matching = []
                for hit in hits:
                    if hit.get("source") != expected_source:
                        continue
                    if expected_slides and not (
                        hit.get("slide") in expected_slides or hit.get("answerSlide") in expected_slides
                    ):
                        continue
                    matching.append(hit)
                haystack = " ".join(str(h.get("text") or "") for h in hits).lower()
                missing = [k for k in case.get("expectedKeywords", []) if k.lower() not in haystack]
                if matching and not missing:
                    status = "pass"
                    slide_label = ", ".join(str(s) for s in (expected_slides or []))
                    detail = f"Retrieved {expected_source}" + (
                        f" slide(s) {slide_label}" if slide_label else ""
                    ) + "; all expected keywords present in top results."
                elif not matching:
                    detail = f"Expected source/slide was not in the top {len(hits)} results."
                    if hits:
                        detail += f" Top result: {hits[0].get('source')} slide {hits[0].get('slide')}."
                else:
                    detail = f"Source retrieved, but missing keywords: {', '.join(missing)}."
                extra = {
                    "expected": {
                        "source": expected_source, "slide": expected_slide,
                        "keywords": case.get("expectedKeywords", []),
                    },
                    "top": [
                        {"source": h.get("source"), "slide": h.get("slide"),
                         "answerSlide": h.get("answerSlide"), "score": h.get("score"),
                         "section": h.get("section")}
                        for h in hits[:3]
                    ],
                }
            elif typ == "flow":
                if case.get("order"):
                    positions = []
                    missing = []
                    for phrase in case["order"]:
                        idx = low_inst.find(phrase.lower())
                        if idx < 0:
                            missing.append(phrase)
                        else:
                            positions.append((phrase, idx))
                    if missing:
                        detail = f"Missing required flow phrase(s): {', '.join(missing)}."
                    elif positions == sorted(positions, key=lambda item: item[1]):
                        status = "pass"
                        detail = "Required flow phrases are present in the documented order."
                    else:
                        detail = "Flow phrases are present but out of order."
                else:
                    missing = [p for p in case.get("allOf", []) if p.lower() not in low_inst]
                    if missing:
                        detail = f"Missing required phrase(s): {', '.join(missing)}."
                    else:
                        status = "pass"
                        detail = "All required flow phrases are present in the instructions."
            elif typ == "compliance":
                missing = [p for p in case.get("allOf", []) if p.lower() not in low_inst]
                if missing:
                    detail = f"Missing required compliance phrase(s): {', '.join(missing)}."
                else:
                    problems = []
                    for phrase in case.get("forbiddenPhrases", []):
                        ok, windows = self._context_guarded(phrase, instructions)
                        if not ok:
                            problems.append({
                                "phrase": phrase,
                                "contexts": [re.sub(r"\s+", " ", w).strip()[:240] for w in windows],
                            })
                    if problems:
                        detail = "Prohibited phrase used outside a negation/prohibition context."
                        extra = {"problems": problems}
                    else:
                        status = "pass"
                        detail = "Required safeguards present; prohibited claims are only in prohibition context."
            elif typ == "gap":
                gap_id = case.get("gapId")
                found = any(g.get("id") == gap_id for g in self.kb.get("conflicts", []))
                status = "pass" if found else "fail"
                detail = (
                    f"Gap/conflict '{gap_id}' is registered for administrator review."
                    if found else f"Gap/conflict '{gap_id}' is missing from the registry."
                )
            else:
                status = "skip"
                detail = f"Unknown test type: {typ}"
            results.append({
                "id": cid, "type": typ, "severity": case.get("severity"),
                "status": status, "detail": detail, **extra,
            })

        # Agent configuration checks only run when the agent exists.
        agent_checks = []
        if agent:
            display = str(agent.get("displayName") or "")
            inst = str(agent.get("systemInstructions") or "")
            tools = [str(t) for t in agent.get("enabledTools") or []]
            checks = [
                ("agent_display_name", display == "Nexus - Tressa - USA Medicare",
                 f"Display name is {display!r}."),
                ("agent_display_active", agent.get("displayStatus") == "Active",
                 f"Derived display status is {agent.get('displayStatus')!r}."),
                ("agent_not_deployed", str(agent.get("status") or "").lower() != "deployed",
                 f"Stored status is {agent.get('status')!r}; Deployed is only allowed after verified deployment."),
                ("agent_instructions_version", "1.0.0" in inst and "AI assistant" in inst,
                 "Instructions include the AI disclosure and training version 1.0.0."),
                ("agent_transfer_tool", any("transfer" in t.lower() for t in tools),
                 f"Transfer-capable tool present: {tools}."),
                ("agent_callback_tool", any("callback" in t.lower() or "schedule" in t.lower() for t in tools),
                 f"Callback/schedule tool present: {tools}."),
                ("agent_voice", bool(agent.get("voice")) and bool(agent.get("sttProvider")) and bool(agent.get("ttsProvider")),
                 f"Pipeline: STT={agent.get('sttProvider')}, voice={agent.get('voice')}, TTS={agent.get('ttsProvider')}."),
                ("agent_transfer_consent", bool((agent.get("transferPolicy") or {}).get("requireConsent")),
                 f"Transfer policy: {agent.get('transferPolicy')}."),
            ]
            for cid, ok, detail in checks:
                agent_checks.append({
                    "id": cid, "type": "agent", "severity": "critical",
                    "status": "pass" if ok else "fail", "detail": detail,
                })
            results.extend(agent_checks)

        counts = Counter(r["status"] for r in results)
        total = len(results)
        passed = counts.get("pass", 0)
        failed = counts.get("fail", 0)
        skipped = counts.get("skip", 0)
        by_type = {}
        for typ in sorted({r["type"] for r in results}):
            subset = [r for r in results if r["type"] == typ]
            by_type[typ] = {
                "total": len(subset),
                "passed": sum(1 for r in subset if r["status"] == "pass"),
                "failed": sum(1 for r in subset if r["status"] == "fail"),
            }
        readiness = {
            "knowledgeRetrievalValidation": "passed" if by_type.get("retrieval", {}).get("failed", 0) == 0 else "failed",
            "instructionFlowValidation": "passed" if by_type.get("flow", {}).get("failed", 0) == 0 else "failed",
            "complianceValidation": "passed" if by_type.get("compliance", {}).get("failed", 0) == 0 else "failed",
            "gapRegistry": "complete" if by_type.get("gap", {}).get("failed", 0) == 0 else "incomplete",
            "agentConfiguration": "passed" if agent_checks and all(c["status"] == "pass" for c in agent_checks) else (
                "not_run" if not agent_checks else "failed"
            ),
            "liveConversationValidation": "not_run",
            "deployment": "not_deployed",
            "readyForControlledTesting": failed == 0 and bool(agent_checks),
            "readyForDeployment": False,
        }
        report = {
            "name": "Tressa USA Medicare validation",
            "version": self.kb.get("version"),
            "generatedAt": now_iso(),
            "knowledgeSha256": hashlib.sha256(KB_PATH.read_bytes()).hexdigest() if KB_PATH.exists() else None,
            "instructionsSha256": sha256_text(instructions),
            "agentId": agent.get("id") if agent else None,
            "agentDisplayName": agent.get("displayName") if agent else None,
            "agentStoredStatus": agent.get("status") if agent else None,
            "agentDisplayStatus": agent.get("displayStatus") if agent else None,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "passRate": round((passed / total) * 100, 1) if total else 0,
                "byType": by_type,
            },
            "readiness": readiness,
            "results": results,
            "limitations": [
                "Retrieval, instruction-flow, compliance, gap, and agent-configuration checks were executed.",
                "A live generative voice conversation was NOT executed: no external LLM key is configured and no LiveKit Cloud agent deployment has been verified.",
                "Plan-specific premiums, networks, formularies, the TPMO carrier list/count, and documented outbound consent are not present; these remain administrator/compliance blockers.",
                "Passing this suite supports controlled testing (Active), not production deployment (Deployed).",
            ],
        }
        self.validation = report
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        VALIDATION_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        REPORT_MD_PATH.write_text(self._report_markdown(report), encoding="utf-8")
        return report

    def _report_markdown(self, report: dict) -> str:
        s = report["summary"]
        r = report["readiness"]
        lines = [
            "# Tressa USA Medicare — Validation Report",
            "",
            f"- Knowledge version: **{report.get('version')}**",
            f"- Generated: {report.get('generatedAt')}",
            f"- Agent: {report.get('agentDisplayName') or 'not linked'}",
            f"- Derived status: **{report.get('agentDisplayStatus') or 'n/a'}**",
            f"- Tests: **{s['passed']}/{s['total']} passed** ({s['passRate']}%), {s['failed']} failed",
            "",
            "## Readiness",
            "",
            f"- Knowledge retrieval: **{r['knowledgeRetrievalValidation']}**",
            f"- Instruction flow: **{r['instructionFlowValidation']}**",
            f"- Compliance checks: **{r['complianceValidation']}**",
            f"- Gap registry: **{r['gapRegistry']}**",
            f"- Agent configuration: **{r['agentConfiguration']}**",
            f"- Live conversational voice test: **{r['liveConversationValidation']}**",
            f"- Deployment: **{r['deployment']}**",
            f"- Ready for controlled testing: **{'yes' if r['readyForControlledTesting'] else 'no'}**",
            f"- Ready for deployment: **{'yes' if r['readyForDeployment'] else 'no'}**",
            "",
            "## Results by type",
            "",
            "| Type | Passed | Failed | Total |",
            "|---|---:|---:|---:|",
        ]
        for typ, v in s["byType"].items():
            lines.append(f"| {typ} | {v['passed']} | {v['failed']} | {v['total']} |")
        failures = [x for x in report["results"] if x["status"] == "fail"]
        lines += ["", "## Failures requiring correction", ""]
        if not failures:
            lines.append("No failures in the executed suite.")
        else:
            for f in failures:
                lines.append(f"- **{f['id']}** ({f['type']}): {f['detail']}")
        lines += ["", "## Limitations", ""]
        lines += [f"- {x}" for x in report["limitations"]]
        lines += [
            "",
            "## Interpretation",
            "",
            "This suite verifies retrieval from the attached corpus, instruction order and required safeguards, "
            "registered conflicts/gaps, and the linked agent configuration. It does not substitute for a live "
            "generative voice test with a licensed-agent review. Tressa must not be marked Deployed until the "
            "live test, carrier/TPMO configuration, documented consent, and plan-data verification are complete.",
            "",
        ]
        return "\n".join(lines)


def get_store(force: bool = False) -> TrainingStore:
    global _cache
    with _lock:
        if force or _cache is None:
            _cache = TrainingStore()
        return _cache


def reload_store() -> TrainingStore:
    return get_store(force=True)
