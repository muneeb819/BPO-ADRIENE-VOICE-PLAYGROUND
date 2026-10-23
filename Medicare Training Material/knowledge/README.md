# Medicare Training Material — Tressa USA Medicare

Saved: 2026-10-23T15:54:46.701907Z
Knowledge version: 1.0.0
Corpus: 88 slides + 1 DOCX, 43,602 extracted characters
Unique sources: 7 (one byte-identical duplicate retained for provenance)

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
