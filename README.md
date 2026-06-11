# AI Compliance Validator

AI Compliance Validator is a hackathon-ready audit assistant for financial and
insurance documents. It validates a document against a rule set using RAG, an
OpenAI-compatible vLLM judge, and produces an auditable report with confidence
scores, risk level, evidence, and remediation recommendations.

## Highlights

- Validates PDF, TXT, Markdown-like text, and HTML documents.
- Uses ChromaDB retrieval with SentenceTransformer embeddings.
- Uses vLLM as a strict JSON-output compliance judge.
- Produces a compliance score, risk label, and per-rule verdicts.
- Sorts findings by severity: `FAIL`, then `UNCLEAR`, then `PASS`.
- Adds actionable recommendations for failed or unclear requirements.
- Includes both CLI and Streamlit demo flows.

## Architecture

```text
Document (PDF / TXT / HTML)
        |
  Raw extraction
        |
  Encoding cleanup
        |
  AI normalisation with vLLM
        |
  AI semantic chunking / fallback splitter
        |
  ChromaDB vector index
        |
  RAG retrieval per rule
        |
  vLLM compliance judge
        |
  JSON report + terminal table + Streamlit UI
```

## Stack

- vLLM with OpenAI-compatible API
- OpenAI Python SDK
- ChromaDB
- SentenceTransformers (`all-MiniLM-L6-v2`)
- LangChain text splitters
- Rich terminal output
- Streamlit UI
- pypdf and BeautifulSoup for document ingestion

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start or Verify vLLM

The app expects an OpenAI-compatible vLLM server at:

```text
http://localhost:8000/v1
```

Check available models:

```bash
curl http://localhost:8000/v1/models
```

### 3. Run the CLI Demo

Compliant sample:

```bash
python main.py \
  --doc documents/sample_policy.txt \
  --rules rules/compliance_rules.txt \
  --model "meta-llama/Llama-3-8B-Instruct"
```

Non-compliant sample with detailed failure evidence:

```bash
python main.py \
  --doc documents/non_compliant_sample.txt \
  --rules rules/compliance_rules.txt \
  --model "meta-llama/Llama-3-8B-Instruct" \
  --details
```

### 4. Run the Streamlit UI

```bash
streamlit run app.py
```

Upload a document and a rules file, then run validation. The UI shows:

- Compliance score
- Risk level
- Pass/fail/unclear counts
- Severity-sorted findings
- Evidence, explanation, and recommendation per rule
- Downloadable JSON audit report

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--doc` | required | Path to document (`.pdf`, `.txt`, `.md`, `.html`) |
| `--rules` | required | Path to compliance rules file (`.txt`) |
| `--model` | `meta-llama/Llama-3-8B-Instruct` | vLLM model name |
| `--vllm-url` | `http://localhost:8000/v1` | vLLM OpenAI-compatible base URL |
| `--out` | `audit_report.json` | Output JSON report path |
| `--top-k` | `3` | Chunks retrieved per rule |
| `--details` | off | Print detailed failure evidence and recommendations |

## Rules File Format

Lines starting with `#` are ignored. Rules may be explicit IDs, numbered lines,
bullets, or plain sentences.

```text
RULE001: Document must explicitly state the coverage start and end date
RULE002: Policy must include the full legal name of the insured party
RULE003: Document must disclose all exclusion clauses clearly
```

## Output Format

```json
{
  "metadata": {
    "document": "sample_policy.txt",
    "timestamp": "2026-06-11T20:30:00",
    "engine": "vLLM + ChromaDB RAG"
  },
  "summary": {
    "total_rules": 15,
    "passed": 13,
    "failed": 1,
    "unclear": 1,
    "compliance_score": 86.67,
    "risk_label": "Low Risk",
    "avg_confidence": 0.88
  },
  "findings": [
    {
      "rule_id": "RULE006",
      "rule_text": "Document must disclose all exclusion clauses clearly",
      "verdict": "FAIL",
      "confidence": 0.91,
      "evidence": "Some conditions may not be covered. Please read the fine print carefully.",
      "explanation": "The document references exclusions vaguely but does not disclose them clearly.",
      "recommendation": "Add or update the document so it clearly satisfies: Document must disclose all exclusion clauses clearly.",
      "supporting_chunks": [
        "Coverage includes hospitalization and surgery. Some conditions may not be covered."
      ]
    }
  ]
}
```

## Risk Labels

| Compliance Score | Risk Label |
|------------------|------------|
| `>= 80%` | Low Risk |
| `>= 50%` and `< 80%` | Medium Risk |
| `< 50%` | High Risk |

## Project Structure

```text
compliance-validator/
|-- app.py                         # Streamlit UI
|-- main.py                        # CLI entrypoint
|-- requirements.txt
|-- README.md
|-- documents/
|   |-- sample_policy.txt          # Compliant test document
|   |-- non_compliant_sample.txt   # Non-compliant test document
|   `-- messy_policy.txt           # Messy document sample
|-- rules/
|   `-- compliance_rules.txt       # Default insurance compliance rules
`-- validator/
    |-- __init__.py
    |-- agent.py                   # RAG + vLLM validation logic
    |-- ingestion.py               # Extraction, cleanup, AI chunking, rules parsing
    |-- reporter.py                # Report, risk label, sorting, recommendations
    `-- vector_store.py            # ChromaDB setup and retrieval
```

## Hackathon Demo Script

1. Show the non-compliant sample document.
2. Run the validator with `--details`.
3. Point out the risk label, failed rules first, and recommendations.
4. Run the compliant sample to show the score improves.
5. Open the Streamlit UI for the same workflow in a judge-friendly interface.

## AMD GPU / vLLM Tuning

| Parameter | Recommendation |
|-----------|----------------|
| `--top-k` | Lower to `2` if inference is slow or context is too large |
| `max_tokens` in `validator/agent.py` | Reduce to `200` for faster judging |
| AI chunking fallback | Automatically uses text splitter when vLLM chunking is unavailable |
| Embedding model | `all-MiniLM-L6-v2` is lightweight and works well for demos |

## Notes

- Scanned PDFs need OCR before validation because `pypdf` can only extract embedded text.
- vLLM should expose an OpenAI-compatible `/v1` endpoint.
- The report is designed for auditability, not as legal advice.

## License

MIT
