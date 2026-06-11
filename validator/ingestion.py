"""
ingestion.py — Robust document ingestion for the AI Compliance Validator

Handles real-world documents that come in inconsistent, messy formats:
  - PDFs: scanned, multi-column, garbled whitespace, header/footer noise
  - Text files: various encodings, CRLF/LF, mixed indentation
  - Common formatting noise: excessive blank lines, page numbers, running headers,
    broken hyphenation, unicode garbage, bullet/list symbol variants
"""

import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ── PDF extraction ────────────────────────────────────────────────────────────

def _extract_pdf_text(path: str) -> str:
    """
    Extract text from a PDF page by page.
    Falls back to a blank string per page if extraction fails (e.g. scanned pages).
    """
    reader = PdfReader(path)
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text)

    raw = "\n\n".join(pages)

    if not raw.strip():
        raise ValueError(
            f"No extractable text found in PDF: {path}\n"
            "If this is a scanned PDF, consider running OCR first "
            "(e.g. pytesseract, ocrmypdf)."
        )
    return raw


# ── Text normalisation ────────────────────────────────────────────────────────

# Patterns compiled once at module level for performance
_RE_PAGE_NUMBER      = re.compile(r"^\s*-?\s*\d+\s*-?\s*$", re.MULTILINE)
_RE_RUNNING_HEADER   = re.compile(r"^.{0,60}(?:page|confidential|draft|internal use only).{0,60}$",
                                   re.IGNORECASE | re.MULTILINE)
_RE_BROKEN_HYPHEN    = re.compile(r"(\w)-\n(\w)")          # word-\nword → wordword
_RE_SOFT_NEWLINE     = re.compile(r"(?<!\n)\n(?!\n)")       # single newline inside paragraph
_RE_MULTI_BLANK      = re.compile(r"\n{3,}")               # 3+ blank lines → 2
_RE_LEADING_SPACES   = re.compile(r"^ +", re.MULTILINE)    # leading spaces per line
_RE_TABS             = re.compile(r"\t+")                   # tabs → space
_RE_MULTI_SPACE      = re.compile(r" {2,}")                 # multiple spaces → one
_RE_BULLETS          = re.compile(                          # unicode bullet variants → "-"
    r"^[\u2022\u2023\u25E6\u2043\u2219\u00B7\u25AA\u25CF\u25CB●•◦‣⁃▪▸►]\s*",
    re.MULTILINE,
)
_RE_LIGATURES = {                                            # common PDF ligatures
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u00a0": " ",   # non-breaking space
}


def _fix_ligatures(text: str) -> str:
    for bad, good in _RE_LIGATURES.items():
        text = text.replace(bad, good)
    return text


def _remove_control_chars(text: str) -> str:
    """Remove non-printable control characters except newlines and tabs."""
    return "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )


def normalise_text(text: str) -> str:
    """
    Clean and normalise raw extracted text regardless of its original formatting.

    Order matters — each step feeds into the next.
    """
    # 1. Fix common PDF encoding artefacts
    text = _fix_ligatures(text)
    text = _remove_control_chars(text)

    # 2. Strip page numbers and running headers/footers
    text = _RE_PAGE_NUMBER.sub("", text)
    text = _RE_RUNNING_HEADER.sub("", text)

    # 3. Reunite words broken across lines with a hyphen (PDF line-wrap artefact)
    text = _RE_BROKEN_HYPHEN.sub(r"\1\2", text)

    # 4. Normalise whitespace
    text = _RE_TABS.sub(" ", text)
    text = _RE_LEADING_SPACES.sub("", text)
    text = _RE_MULTI_SPACE.sub(" ", text)

    # 5. Normalise bullet symbols to a plain dash
    text = _RE_BULLETS.sub("- ", text)

    # 6. Collapse excessive blank lines (keep paragraph breaks as double newline)
    text = _RE_SOFT_NEWLINE.sub(" ", text)   # join soft-wrapped lines first
    text = _RE_MULTI_BLANK.sub("\n\n", text)

    return text.strip()


# ── Public API ────────────────────────────────────────────────────────────────

def load_document(path: str) -> str:
    """
    Load any supported document format and return clean, normalised plain text.

    Supported formats:
        .pdf  — native text PDF (not scanned)
        .txt  — plain text, any common encoding
        .md   — markdown (treated as plain text)
        .html / .htm — strips HTML tags, returns inner text

    If the file is a scanned/image PDF with no embedded text, raises ValueError
    with an actionable message.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".pdf":
        raw = _extract_pdf_text(path)

    elif suffix in {".txt", ".md", ".text"}:
        # Try UTF-8 first, fall back to latin-1 (covers most Western encodings)
        try:
            raw = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = p.read_text(encoding="latin-1")

    elif suffix in {".html", ".htm"}:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(p.read_bytes(), "html.parser")
            raw = soup.get_text(separator="\n")
        except ImportError:
            # BeautifulSoup not installed — strip tags with regex (basic fallback)
            raw = re.sub(r"<[^>]+>", " ", p.read_text(encoding="utf-8", errors="replace"))

    else:
        # Generic fallback — try reading as text
        raw = p.read_text(encoding="utf-8", errors="replace")

    return normalise_text(raw)


def load_rules(path: str) -> list[dict]:
    """
    Load compliance rules from a text file.

    Accepted formats (all are handled):
        RULE001: Policy must clearly state coverage limits
        RULE001 - Policy must clearly state coverage limits
        1. Policy must clearly state coverage limits
        • Policy must clearly state coverage limits
        # Lines starting with # are treated as comments and ignored.

    Returns a list of dicts: [{"id": "RULE001", "text": "..."}, ...]
    Auto-generates IDs (RULE001, RULE002 …) if the line has no explicit ID.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = p.read_text(encoding="latin-1")

    rules = []
    auto_id = 1

    # Matches:  RULE001: text  |  RULE001 - text  |  1. text  |  1) text  |  plain text
    _id_pattern = re.compile(
        r"^([A-Z]{1,6}\d{1,6}|[A-Z]\d+|\d{1,3})[:\-\.\)]\s*(.+)$", re.IGNORECASE
    )

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Strip leading bullet characters
        line = re.sub(
            r"^[\u2022\u2023\u25E6\u2043\u2219\u00B7\u25AA\u25CF\u25CB●•◦‣⁃▪▸►]\s*",
            "", line
        )

        m = _id_pattern.match(line)
        if m:
            rule_id = m.group(1).upper()
            if not rule_id.startswith("RULE"):
                rule_id = f"RULE{rule_id.zfill(3)}"
            rule_text = m.group(2).strip()
        else:
            # No explicit ID — treat the whole line as rule text
            rule_id   = f"RULE{str(auto_id).zfill(3)}"
            rule_text = line

        if rule_text:
            rules.append({"id": rule_id, "text": rule_text})
            auto_id += 1

    if not rules:
        raise ValueError(f"No rules found in: {path}")

    return rules


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 80,
) -> list[str]:
    """
    Split normalised document text into overlapping chunks for vector storage.

    Strategy:
    - Prefer splitting on paragraph boundaries (\n\n) first, then sentences,
      then words — so chunks are semantically coherent rather than mid-sentence.
    - Generous overlap (80 tokens default) ensures cross-boundary information
      is not lost when a compliance fact spans two chunks.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
    )
    chunks = splitter.split_text(text)

    # Final dedup and denoising pass
    seen   = set()
    result = []
    for c in chunks:
        c = c.strip()
        if not c or len(c) < 20:          # skip tiny/empty fragments
            continue
        if c in seen:                     # skip exact duplicates (repeated headers etc.)
            continue
        seen.add(c)
        result.append(c)

    return result
