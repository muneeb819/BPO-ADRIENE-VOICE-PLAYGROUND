#!/usr/bin/env python3
"""Extract Medicare training attachments into a versioned, structured corpus.

Standard library only: PPTX/DOCX are OOXML zip containers. We preserve slide
order, paragraph order, tables, and speaker notes so the resulting knowledge
base is traceable back to the exact source slide.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

DOWNLOADS = Path(r"C:\Users\Wave\Downloads")
PROJECT = DOWNLOADS / "AdrieneVoiceStudio"
ROOT = PROJECT / "Medicare Training Material"
SRC = ROOT / "source"
EXTRACTED = ROOT / "extracted"
KNOWLEDGE = ROOT / "knowledge"

SOURCES = [
    "Medicare_Advantage_New_Hire_Orientation (1).pptx",
    "Medicare_Agent_Call_Center_Training.pptx",
    "Medicare_Agent_Call_Center_Training (1) (1).pptx",
    "Med Script 1 (1).docx",
    "Medicare_Advantage_MA_Plan_Quiz_35Q (1).pptx",
    "Medicare_Supplement_vs_Advantage (2).pptx",
    "Med_Script_Quiz (1).pptx",
    "Medicare_Basics_Overview 1 (1).pptx",
]

# Clean destination names keep provenance but remove download suffixes.
CLEAN_NAMES = {
    "Medicare_Advantage_New_Hire_Orientation (1).pptx": "01_Medicare_Advantage_New_Hire_Orientation.pptx",
    "Medicare_Agent_Call_Center_Training.pptx": "02_Medicare_Agent_Call_Center_Training.pptx",
    "Medicare_Agent_Call_Center_Training (1) (1).pptx": "02b_Medicare_Agent_Call_Center_Training_duplicate.pptx",
    "Med Script 1 (1).docx": "03_Medicare_Script.docx",
    "Medicare_Advantage_MA_Plan_Quiz_35Q (1).pptx": "04_Medicare_Advantage_MA_Plan_Quiz_35Q.pptx",
    "Medicare_Supplement_vs_Advantage (2).pptx": "05_Medicare_Supplement_vs_Advantage.pptx",
    "Med_Script_Quiz (1).pptx": "06_Medicare_Script_Quiz.pptx",
    "Medicare_Basics_Overview 1 (1).pptx": "07_Medicare_Basics_Overview.pptx",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def text_of(el) -> str:
    return "".join(t.text or "" for t in el.iter(A + "t")).strip()


def slide_order(zf: zipfile.ZipFile) -> list[str]:
    pres = ET.fromstring(zf.read("ppt/presentation.xml"))
    rels = ET.fromstring(zf.read("ppt/_rels/presentation.xml.rels"))
    rid_to_target = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    out = []
    for sld in pres.find(P + "sldIdLst") or []:
        rid = sld.attrib.get(R + "id")
        target = rid_to_target.get(rid, "")
        if target:
            out.append("ppt/" + target.lstrip("/").removeprefix("ppt/"))
    return out


def notes_for(zf: zipfile.ZipFile, slide_path: str) -> str:
    # slides/_rels/slideN.xml.rels -> notesSlide
    name = Path(slide_path).name
    rel_path = f"ppt/slides/_rels/{name}.rels"
    if rel_path not in zf.namelist():
        return ""
    rels = ET.fromstring(zf.read(rel_path))
    for rel in rels:
        target = rel.attrib.get("Target", "")
        if "notesSlide" in target:
            path = "ppt/" + target.replace("../", "").lstrip("/")
            if path in zf.namelist():
                root = ET.fromstring(zf.read(path))
                chunks = []
                for sp in root.iter(P + "sp"):
                    paras = [text_of(p) for p in sp.iter(A + "p")]
                    paragraphs = [p for p in paras if p]
                    if paragraphs:
                        chunks.append("\n".join(paragraphs))
                return "\n".join(chunks).strip()
    return ""


def extract_slide(zf: zipfile.ZipFile, path: str) -> dict:
    root = ET.fromstring(zf.read(path))
    blocks = []
    tables = []
    for sp in root.iter(P + "sp"):
        name = ""
        nv = sp.find(".//" + P + "cNvPr")
        if nv is not None:
            name = nv.attrib.get("name", "")
        paras = []
        for p in sp.iter(A + "p"):
            t = text_of(p)
            if t:
                paras.append(t)
        if paras:
            blocks.append({"shape": name, "paragraphs": paras})
    for tbl in root.iter(A + "tbl"):
        rows = []
        for tr in tbl.iter(A + "tr"):
            cells = []
            for tc in tr.iter(A + "tc"):
                cell = " ".join(text_of(p) for p in tc.iter(A + "p")).strip()
                cells.append(cell)
            if any(cells):
                rows.append(cells)
        if rows:
            tables.append(rows)
    images = len([n for n in zf.namelist() if path.startswith("ppt/media/")])
    return {
        "path": path,
        "blocks": blocks,
        "tables": tables,
        "notes": notes_for(zf, path),
        "imageAssetsInDeck": images,
    }


def parse_pptx(path: Path) -> dict:
    zf = zipfile.ZipFile(path)
    slides = []
    for idx, slide_path in enumerate(slide_order(zf), 1):
        data = extract_slide(zf, slide_path)
        data["number"] = idx
        slides.append(data)
    return {"type": "pptx", "slides": slides}


def docx_blocks(path: Path) -> list[dict]:
    zf = zipfile.ZipFile(path)
    root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(W + "body")
    blocks = []
    if body is None:
        return blocks
    for child in body:
        if child.tag == W + "p":
            text = "".join(t.text or "" for t in child.iter(W + "t")).strip()
            if text:
                blocks.append({"kind": "paragraph", "text": text})
        elif child.tag == W + "tbl":
            rows = []
            for tr in child.iter(W + "tr"):
                cells = []
                for tc in tr.iter(W + "tc"):
                    cell = " ".join("".join(t.text or "" for t in p.iter(W + "t")).strip()
                                    for p in tc.iter(W + "p")).strip()
                    cells.append(cell)
                if any(cells):
                    rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
    return blocks


def slide_text(slide: dict) -> str:
    parts = []
    for block in slide["blocks"]:
        parts.extend(block["paragraphs"])
    for table in slide["tables"]:
        for row in table:
            parts.append(" | ".join(row))
    if slide["notes"]:
        parts.append("SPEAKER NOTES: " + slide["notes"])
    return "\n".join(p for p in parts if p).strip()


def main() -> None:
    for d in (SRC, EXTRACTED, KNOWLEDGE):
        d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "name": "Medicare Training Material",
        "version": "1.0.0",
        "createdAt": now(),
        "sourceCount": len(SOURCES),
        "documents": [],
        "duplicates": [],
        "warnings": [],
    }
    combined = []
    hashes = {}
    for original in SOURCES:
        src = DOWNLOADS / original
        if not src.exists():
            manifest["warnings"].append(f"Missing attachment: {original}")
            continue
        dest_name = CLEAN_NAMES[original]
        dest = SRC / dest_name
        shutil.copy2(src, dest)
        digest = sha256(dest)
        if digest in hashes:
            manifest["duplicates"].append({
                "file": dest_name,
                "duplicateOf": hashes[digest],
                "sha256": digest,
                "note": "Byte-identical duplicate; retained for provenance but excluded from knowledge indexing.",
            })
            doc = {
                "file": dest_name,
                "originalFile": original,
                "kind": "duplicate",
                "sha256": digest,
                "bytes": dest.stat().st_size,
                "slides": 0,
                "characters": 0,
            }
            manifest["documents"].append(doc)
            continue
        hashes[digest] = dest_name

        if src.suffix.lower() == ".pptx":
            parsed = parse_pptx(dest)
            slides = parsed["slides"]
            txt_lines = [f"# {dest_name}", f"Source: {original}", ""]
            for s in slides:
                body = slide_text(s)
                txt_lines.append(f"## Slide {s['number']}")
                txt_lines.append(body if body else "[NO EXTRACTABLE TEXT]")
                txt_lines.append("")
            characters = sum(len(slide_text(s)) for s in slides)
            empty = [s["number"] for s in slides if not slide_text(s)]
            doc = {
                "file": dest_name,
                "originalFile": original,
                "kind": "pptx",
                "sha256": digest,
                "bytes": dest.stat().st_size,
                "slides": len(slides),
                "emptySlides": empty,
                "characters": characters,
                "imageAssetsInDeck": slides[0]["imageAssetsInDeck"] if slides else 0,
            }
            (EXTRACTED / (dest.stem + ".txt")).write_text("\n".join(txt_lines), encoding="utf-8")
            (EXTRACTED / (dest.stem + ".json")).write_text(
                json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
        elif src.suffix.lower() == ".docx":
            blocks = docx_blocks(dest)
            txt_lines = [f"# {dest_name}", f"Source: {original}", ""]
            for block in blocks:
                if block["kind"] == "paragraph":
                    txt_lines.append(block["text"])
                else:
                    txt_lines.append("[TABLE]")
                    for row in block["rows"]:
                        txt_lines.append(" | ".join(row))
                    txt_lines.append("[/TABLE]")
            characters = sum(len(b.get("text", "")) + sum(len(c) for r in b.get("rows", []) for c in r)
                             for b in blocks)
            doc = {
                "file": dest_name,
                "originalFile": original,
                "kind": "docx",
                "sha256": digest,
                "bytes": dest.stat().st_size,
                "paragraphs": sum(1 for b in blocks if b["kind"] == "paragraph"),
                "tables": sum(1 for b in blocks if b["kind"] == "table"),
                "characters": characters,
            }
            (EXTRACTED / (dest.stem + ".txt")).write_text("\n".join(txt_lines), encoding="utf-8")
            (EXTRACTED / (dest.stem + ".json")).write_text(
                json.dumps({"type": "docx", "blocks": blocks}, indent=2, ensure_ascii=False),
                encoding="utf-8")
        else:
            manifest["warnings"].append(f"Unsupported attachment type: {original}")
            continue
        manifest["documents"].append(doc)
        combined.append((dest_name, (EXTRACTED / (dest.stem + ".txt")).read_text(encoding="utf-8")))

    manifest["totalCharacters"] = sum(d.get("characters", 0) for d in manifest["documents"])
    manifest["totalSlides"] = sum(d.get("slides", 0) for d in manifest["documents"])
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    all_text = "\n\n" + ("\n\n" + "=" * 100 + "\n\n").join(f"{n}\n\n{t}" for n, t in combined)
    (EXTRACTED / "ALL_TRAINING_TEXT.txt").write_text(all_text, encoding="utf-8")
    print(json.dumps({
        "documents": manifest["documents"],
        "duplicates": manifest["duplicates"],
        "warnings": manifest["warnings"],
        "totalCharacters": manifest["totalCharacters"],
        "totalSlides": manifest["totalSlides"],
        "output": str(ROOT),
    }, indent=2))


if __name__ == "__main__":
    main()
