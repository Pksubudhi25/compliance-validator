from pathlib import Path
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter


def load_document(path: str) -> str:
    """Load a document from a PDF or text file and return its full text."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {path}")

    if p.suffix.lower() == ".pdf":
        reader = PdfReader(path)
        text = "\n".join(
            page.extract_text() for page in reader.pages if page.extract_text()
        )
        if not text.strip():
            raise ValueError(f"Could not extract text from PDF: {path}")
        return text

    # Plain text fallback
    return p.read_text(encoding="utf-8")


def load_rules(path: str) -> list[dict]:
    """
    Load compliance rules from a text file.

    Expected format (one rule per line):
        RULE001: Policy must clearly state coverage limits
        RULE002: Document must include policyholder signature date
        # Lines starting with # are treated as comments and ignored.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rules file not found: {path}")

    rules = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                rule_id, desc = line.split(":", 1)
                rules.append({"id": rule_id.strip(), "text": desc.strip()})

    if not rules:
        raise ValueError(f"No rules found in: {path}")

    return rules


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split a long document into overlapping chunks for vector storage."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    chunks = splitter.split_text(text)
    return [c.strip() for c in chunks if c.strip()]
