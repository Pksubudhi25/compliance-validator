import json
import re
from openai import OpenAI

from .vector_store import retrieve

# ---------------------------------------------------------------------------
# vLLM connection — uses OpenAI-compatible API exposed by vLLM server
# Adjust base_url and MODEL to match your AMD hackathon environment.
# ---------------------------------------------------------------------------
VLLM_BASE_URL = "http://localhost:8000/v1"
MODEL = "meta-llama/Llama-3-8B-Instruct"  # override via CLI --model flag

client = OpenAI(
    base_url=VLLM_BASE_URL,
    api_key="dummy",  # vLLM does not require a real key
)

# ---------------------------------------------------------------------------
# System prompt — instructs the LLM to act as a strict compliance auditor
# and always return structured JSON output.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a strict compliance auditor specialising in financial and insurance documents.

Given a compliance rule and relevant excerpts from a document, determine whether the document 
PASSES or FAILS that rule, or if the evidence is UNCLEAR.

You MUST respond with ONLY valid JSON in this exact format — no preamble, no markdown fences:
{
  "verdict": "PASS" or "FAIL" or "UNCLEAR",
  "confidence": <float between 0.0 and 1.0>,
  "evidence": "<direct excerpt from the document that most strongly supports your verdict>",
  "explanation": "<single concise sentence explaining your decision>"
}

Rules:
- PASS  → The document clearly satisfies the rule.
- FAIL  → The document clearly violates or omits what the rule requires.
- UNCLEAR → The document partially addresses the rule or the evidence is ambiguous.
- confidence → How certain you are: 1.0 = completely certain, 0.0 = pure guess.
- evidence → Quote or paraphrase the most relevant passage from the excerpts.
- explanation → One sentence only. Be specific about what is present or missing."""


def _parse_llm_response(raw: str) -> dict:
    """Safely parse JSON from the LLM response, stripping markdown fences if present."""
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Fallback: extract first JSON-like block
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return {
        "verdict": "UNCLEAR",
        "confidence": 0.0,
        "evidence": "Could not parse model response.",
        "explanation": raw[:300],
    }


def validate_rule(
    rule: dict,
    doc_collection,
    top_k: int = 3,
) -> dict:
    """
    Validate a single compliance rule against the document using RAG + LLM.

    Steps:
    1. Retrieve top-k most relevant document chunks for the rule (RAG).
    2. Send rule + chunks to vLLM for structured verdict.
    3. Return a result dict with verdict, confidence, evidence, and explanation.
    """
    relevant_chunks = retrieve(doc_collection, rule["text"], n=top_k)
    context = "\n---\n".join(relevant_chunks)

    user_msg = f"""COMPLIANCE RULE [{rule['id']}]: {rule['text']}

RELEVANT DOCUMENT EXCERPTS:
{context}

Does this document comply with the above rule? Respond in JSON only."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,   # low temperature for deterministic, structured output
        max_tokens=350,
    )

    raw = response.choices[0].message.content.strip()
    parsed = _parse_llm_response(raw)

    return {
        "rule_id": rule["id"],
        "rule_text": rule["text"],
        "verdict": parsed.get("verdict", "UNCLEAR"),
        "confidence": float(parsed.get("confidence", 0.0)),
        "evidence": parsed.get("evidence", ""),
        "explanation": parsed.get("explanation", ""),
        "supporting_chunks": relevant_chunks,
    }


def run_validation(
    rules: list[dict],
    doc_collection,
    top_k: int = 3,
) -> list[dict]:
    """
    Run validation for all rules sequentially.
    Prints a live progress line for each rule.
    Returns a list of result dicts.
    """
    results = []
    for rule in rules:
        print(f"  Checking {rule['id']}...", end=" ", flush=True)
        result = validate_rule(rule, doc_collection, top_k=top_k)
        v = result["verdict"]
        c = result["confidence"]
        indicator = {"PASS": "✅", "FAIL": "❌", "UNCLEAR": "❓"}.get(v, "?")
        print(f"{indicator} {v} (confidence: {c:.2f})")
        results.append(result)
    return results
