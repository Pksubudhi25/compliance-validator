# AI Compliance Validator 🔍

> **AMD Hackathon Project** — AI-Driven Audit & Compliance Validator  
> Validates financial/insurance documents against compliance rules using RAG and produces an auditable report with confidence scores.

---

## Architecture

```
Document (PDF / TXT)
        ↓
  [Chunker]  →  RecursiveCharacterTextSplitter
        ↓
  [ChromaDB]  ←  SentenceTransformer embeddings (all-MiniLM-L6-v2)
        ↓
  [RAG Retrieval]  →  top-k chunks per rule
        ↓
  [vLLM Judge]  →  structured JSON verdict per rule
        ↓
  [Reporter]  →  audit_report.json + rich terminal table
```

**Stack:** vLLM · ChromaDB · LangChain text splitters · SentenceTransformers · Rich · Streamlit (optional)

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Check your vLLM model name

```bash
curl http://localhost:8000/v1/models
```

### 3. Run the validator (terminal)

```bash
# Compliant document
python main.py \
  --doc documents/sample_policy.txt \
  --rules rules/compliance_rules.txt \
  --model "meta-llama/Llama-3-8B-Instruct"

# Non-compliant document (expect failures)
python main.py \
  --doc documents/non_compliant_sample.txt \
  --rules rules/compliance_rules.txt \
  --model "meta-llama/Llama-3-8B-Instruct" \
  --details
```

### 4. Optional — Streamlit UI

```bash
streamlit run app.py
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--doc` | *(required)* | Path to document (PDF or TXT) |
| `--rules` | *(required)* | Path to rules file (TXT) |
| `--model` | `meta-llama/Llama-3-8B-Instruct` | vLLM model name |
| `--vllm-url` | `http://localhost:8000/v1` | vLLM server URL |
| `--out` | `audit_report.json` | Output JSON path |
| `--top-k` | `3` | Chunks retrieved per rule |
| `--chunk-size` | `500` | Document chunk size |
| `--details` | off | Print detailed failure evidence |

---

## Rules File Format

```
# compliance_rules.txt
# Lines starting with # are ignored

RULE001: Document must explicitly state the coverage start and end date
RULE002: Policy must include the full legal name of the insured party
RULE003: Document must disclose all exclusion clauses clearly
```

---

## Output Format

```json
{
  "metadata": {
    "document": "sample_policy.txt",
    "timestamp": "2024-06-11T10:30:00",
    "engine": "vLLM + ChromaDB RAG"
  },
  "summary": {
    "total_rules": 15,
    "passed": 13,
    "failed": 1,
    "unclear": 1,
    "compliance_score": 86.67,
    "avg_confidence": 0.88
  },
  "findings": [
    {
      "rule_id": "RULE001",
      "rule_text": "Document must explicitly state the coverage start and end date",
      "verdict": "PASS",
      "confidence": 0.97,
      "evidence": "Coverage Start Date: February 1, 2024 / Coverage End Date: January 31, 2025",
      "explanation": "The document explicitly states both the coverage start and end dates."
    }
  ]
}
```

---

## Project Structure

```
compliance-validator/
├── rules/
│   └── compliance_rules.txt       # Default GDPR/insurance rules
├── documents/
│   ├── sample_policy.txt          # Compliant test document
│   └── non_compliant_sample.txt   # Intentionally non-compliant test doc
├── validator/
│   ├── __init__.py
│   ├── ingestion.py               # PDF/text loading + chunking
│   ├── vector_store.py            # ChromaDB setup + retrieval
│   ├── agent.py                   # RAG + vLLM validation logic
│   └── reporter.py                # Report generation + rich terminal output
├── main.py                        # CLI entrypoint
├── app.py                         # Streamlit UI (optional)
├── requirements.txt
└── README.md
```

---

## Tuning for AMD GPU Environment

| Parameter | Recommendation |
|-----------|----------------|
| `--top-k` | Lower to 2 if GPU memory is tight |
| `max_tokens` in `agent.py` | Reduce to 200 for faster inference |
| `--chunk-size` | Increase to 800 for fewer, larger chunks |
| Embedding model | Swap `all-MiniLM-L6-v2` for vLLM-served embeddings if available |

---

## License

MIT
