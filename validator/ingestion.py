"""
ingestion.py — AI-powered document ingestion for the AI Compliance Validator

Pipeline:
  1. Raw extraction   — pypdf / plain text read (minimal, format-agnostic)
  2. Encoding fixes   — ligatures, control chars, non-breaking spaces (regex, fast)
  3. AI normalisation — vLLM cleans structure, layout noise, broken words (smart)
  4. AI chunking      — vLLM splits into semantically meaningful sections (context-aware)

Why AI normalisation instead of pure regex?
  - Regex can't understand context: it can't tell a "1." that's a list item from
    one that's part of a policy number or a date.
  - LLMs handle multi-column PDF reflow, garbled OCR, language-mixed docs, and
    arbitrary formatting styles without needing hand-crafted rules per format.
  - For a hackathon demo, it's more impressive and more robust.
"""

import re
import json
import unicodedata
from pathlib import Path

from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── vLLM client (shared with agent.py, imported lazily to avoid circular import)
_vllm_client: OpenAI | None = None
_vllm_model: str = ""


def init_llm(client: OpenAI, model: str) -> None:
    """Call this once from main.py after the vLLM client is set up."""
    global _vllm_client, _vllm_model
    _vllm_client = client
    _vllm_model  = model


# ── Step 1: Raw extraction ────────────────────────────────────────────────────

def _extract_pdf_text(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    pages  = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append(text)
    raw = "\n\n".join(pages)
    if not raw.strip():
        raise ValueError(
            f"No extractable text in PDF: {path}\n"
            "Scanned PDF? Run OCR first (e.g. ocrmypdf)."
        )
    return raw


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_html_file(path: Path) -> str:
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup(path.read_bytes(), "html.parser").get_text("\n")
    except ImportError:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", raw)


def _raw_extract(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(path)
    if suffix in {".html", ".htm"}:
        return _read_html_file(p)
    return _read_text_file(p)   # .txt, .md, .text, or unknown


# ── Step 2: Minimal encoding fixes (non-AI, must run before LLM sees text) ───

_LIGATURE_MAP = {
    "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
    "\u2019": "'",  "\u2018": "'",  "\u201c": '"',   "\u201d": '"',
    "\u2013": "-",  "\u2014": "-",  "\u00a0": " ",
}

def _fix_encoding(text: str) -> str:
    """Fix ligatures and remove invisible control characters — things the LLM can't see."""
    for bad, good in _LIGATURE_MAP.items():
        text = text.replace(bad, good)
    # Remove non-printable control chars except \n and \t
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    return text


# ── Step 3: AI normalisation ──────────────────────────────────────────────────

_NORMALISE_SYSTEM = """You are a document pre-processing assistant.
You will receive raw text extracted from a financial or insurance document.
The text may be messy: excessive whitespace, broken words from PDF line-wraps,
page numbers, running headers/footers, garbled multi-column reflow, mixed bullet
styles, inconsistent spacing, or OCR artefacts.

Your job is to return ONLY the cleaned, normalised document text. Rules:
- Fix broken hyphenated words split across lines (e.g. "insur-\\nance" → "insurance")
- Remove page numbers, running headers, footers, watermarks, and repeated section titles
- Normalise all bullet/list symbols (•, ►, ●, ▸, ◦, etc.) to a plain hyphen-space "- "
- Collapse excessive whitespace and blank lines; keep paragraph breaks as a single blank line
- Do NOT summarise, paraphrase, or remove any actual policy content
- Do NOT add anything that was not in the original text
- Return ONLY the cleaned text, nothing else — no preamble, no explanation"""


def _ai_normalise(raw: str) -> str:
    """
    Use vLLM to intelligently clean layout noise from raw extracted text.
    Falls back to lightly regex-cleaned text if LLM is unavailable.
    """
    if _vllm_client is None:
        # Graceful fallback: basic whitespace cleanup
        text = re.sub(r"\t+", " ", raw)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # If document is very long, process in page-sized windows to stay within context
    MAX_CHARS = 6000   # safe for most 8k-context models
    if len(raw) <= MAX_CHARS:
        return _normalise_chunk(raw)

    # Split on double newlines (page/section breaks) and normalise window by window
    paragraphs = raw.split("\n\n")
    windows, window = [], []
    size = 0
    for para in paragraphs:
        if size + len(para) > MAX_CHARS and window:
            windows.append("\n\n".join(window))
            window, size = [], 0
        window.append(para)
        size += len(para)
    if window:
        windows.append("\n\n".join(window))

    cleaned_windows = [_normalise_chunk(w) for w in windows]
    return "\n\n".join(cleaned_windows)


def _normalise_chunk(text: str) -> str:
    """Send a single chunk to vLLM for normalisation."""
    try:
        resp = _vllm_client.chat.completions.create(
            model=_vllm_model,
            messages=[
                {"role": "system", "content": _NORMALISE_SYSTEM},
                {"role": "user",   "content": text},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        # Don't crash the pipeline — return raw text with a warning
        print(f"  [warn] AI normalisation failed ({e}), using raw text.")
        return text


# ── Step 4: AI-powered semantic chunking ─────────────────────────────────────

_CHUNK_SYSTEM = """You are a document segmentation assistant for compliance analysis.

Given a cleaned insurance or financial policy document, split it into logical sections.
Each section should cover ONE coherent topic (e.g. Coverage Details, Exclusions, 
Premium Schedule, Cancellation Terms, Grievance Mechanism, etc.).

Return ONLY a valid JSON array of strings. Each string is one section's full text.
No preamble, no explanation, no markdown fences. Example output format:
["Section 1 full text here...", "Section 2 full text here...", "Section 3 full text..."]

Rules:
- Keep all original text intact — do not summarise or paraphrase
- A section should be 100-600 words; split large sections, merge tiny ones
- Preserve headings within each section string"""


def _ai_chunk(text: str) -> list[str]:
    """
    Use vLLM to split the document into semantically meaningful sections.
    Falls back to RecursiveCharacterTextSplitter if LLM is unavailable or fails.
    """
    if _vllm_client is None or len(text) > 8000:
        # Fallback for very long docs or missing LLM
        return _fallback_chunk(text)

    try:
        resp = _vllm_client.chat.completions.create(
            model=_vllm_model,
            messages=[
                {"role": "system", "content": _CHUNK_SYSTEM},
                {"role": "user",   "content": text},
            ],
            temperature=0.0,
            max_tokens=4096,
        )
        raw_json = resp.choices[0].message.content.strip()
        # Strip markdown fences if model wraps output
        raw_json = re.sub(r"```(?:json)?|```", "", raw_json).strip()
        chunks = json.loads(raw_json)

        if not isinstance(chunks, list) or not chunks:
            raise ValueError("LLM returned empty or non-list chunk response")

        # Validate and filter
        return [c.strip() for c in chunks if isinstance(c, str) and len(c.strip()) >= 20]

    except Exception as e:
        print(f"  [warn] AI chunking failed ({e}), falling back to text splitter.")
        return _fallback_chunk(text)


def _fallback_chunk(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """RecursiveCharacterTextSplitter fallback when AI chunking isn't available."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""],
    )
    chunks = splitter.split_text(text)
    seen, result = set(), []
    for c in chunks:
        c = c.strip()
        if c and len(c) >= 20 and c not in seen:
            seen.add(c)
            result.append(c)
    return result


# ── Public API ────────────────────────────────────────────────────────────────

def load_document(path: str) -> str:
    """
    Load a document and return AI-normalised plain text.

    Pipeline: raw extract → encoding fix → AI normalisation
    """
    raw     = _raw_extract(path)
    encoded = _fix_encoding(raw)
    clean   = _ai_normalise(encoded)
    return clean


def load_and_chunk(path: str) -> list[str]:
    """
    Load a document and return AI-generated semantic chunks ready for ChromaDB.

    This is the preferred entry point for the validation pipeline.
    Pipeline: raw extract → encoding fix → AI normalise → AI chunk
    """
    raw     = _raw_extract(path)
    encoded = _fix_encoding(raw)
    clean   = _ai_normalise(encoded)
    chunks  = _ai_chunk(clean)
    return chunks


def load_rules(path: str) -> list[dict]:
    """
    Load compliance rules — also AI-assisted for messy/unstructured rule files.

    Accepted input formats (all handled):
        RULE001: Policy must clearly state coverage limits
        1. Policy must clearly state coverage limits
        • Policy must clearly state coverage limits
        Plain sentence with no ID prefix

    Returns: [{"id": "RULE001", "text": "..."}, ...]
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")

    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = p.read_text(encoding="latin-1")

    # If vLLM available, use AI to extract rules — handles any format
    if _vllm_client is not None:
        return _ai_extract_rules(content)

    # Fallback: regex-based rule parser
    return _regex_extract_rules(content)


_RULES_SYSTEM = """You are a compliance rules parser.

Given text containing compliance rules (possibly formatted inconsistently, with 
bullet points, numbered lists, mixed IDs, or plain sentences), extract each 
distinct rule and return a JSON array.

Return ONLY valid JSON, no markdown fences, no preamble:
[
  {"id": "RULE001", "text": "Rule description here"},
  {"id": "RULE002", "text": "Another rule here"}
]

Rules:
- Assign sequential IDs: RULE001, RULE002, RULE003 ...
- Preserve the full original wording of each rule — do not paraphrase
- Ignore comment lines (starting with #), blank lines, and section headings
- If a line is clearly a heading (not a rule), skip it
- Each element must have exactly two keys: "id" and "text"
"""


def _ai_extract_rules(content: str) -> list[dict]:
    try:
        resp = _vllm_client.chat.completions.create(
            model=_vllm_model,
            messages=[
                {"role": "system", "content": _RULES_SYSTEM},
                {"role": "user",   "content": content},
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        raw_json = resp.choices[0].message.content.strip()
        raw_json = re.sub(r"```(?:json)?|```", "", raw_json).strip()
        rules = json.loads(raw_json)

        if not isinstance(rules, list) or not rules:
            raise ValueError("Empty rule list from LLM")

        # Validate structure
        validated = []
        for i, r in enumerate(rules):
            if isinstance(r, dict) and "text" in r:
                validated.append({
                    "id":   r.get("id", f"RULE{str(i+1).zfill(3)}"),
                    "text": r["text"].strip(),
                })
        if not validated:
            raise ValueError("No valid rules parsed")
        return validated

    except Exception as e:
        print(f"  [warn] AI rule extraction failed ({e}), using regex parser.")
        from validator.ingestion import _regex_extract_rules
        return _regex_extract_rules(content)


def _regex_extract_rules(content: str) -> list[dict]:
    """Fallback regex-based rule parser for when LLM is unavailable."""
    rules, auto_id = [], 1
    _id_pat = re.compile(
        r"^([A-Z]{1,6}\d{1,6}|[A-Z]\d+|\d{1,3})[:\-\.\)]\s*(.+)$", re.IGNORECASE
    )
    _bullet = re.compile(
        r"^[\u2022\u2023\u25E6\u2043\u2219\u00B7\u25AA\u25CF\u25CB●•◦‣⁃▪▸►]\s*"
    )
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = _bullet.sub("", line)
        m = _id_pat.match(line)
        if m:
            rid = m.group(1).upper()
            if not rid.startswith("RULE"):
                rid = f"RULE{rid.zfill(3)}"
            rules.append({"id": rid, "text": m.group(2).strip()})
        else:
            rules.append({"id": f"RULE{str(auto_id).zfill(3)}", "text": line})
        auto_id += 1
    if not rules:
        raise ValueError(f"No rules found")
    return rules


# Backward-compat alias — used in existing code that calls chunk_text() directly
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 80) -> list[str]:
    """Alias: AI chunk if LLM available, else fallback splitter."""
    return _ai_chunk(text)
