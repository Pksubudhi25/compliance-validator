"""
main.py — CLI entrypoint for the AI Compliance Validator

Usage:
    python main.py --doc documents/sample_policy.txt --rules rules/compliance_rules.txt
    python main.py --doc my.pdf --rules rules.txt --model "meta-llama/Llama-3-8B-Instruct" --out report.json
    python main.py --doc my.pdf --rules rules.txt --vllm-url http://localhost:9000/v1
"""

import argparse
import sys

from rich.console import Console

import validator.agent as ag
from validator.ingestion import load_document, load_rules, chunk_text
from validator.vector_store import build_store
from validator.agent import run_validation
from validator.reporter import (
    generate_report,
    print_terminal_report,
    print_failed_details,
    save_report,
)

console = Console()


def parse_args():
    parser = argparse.ArgumentParser(
        description="AI-Driven Audit & Compliance Validator (AMD Hackathon)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--doc",
        required=True,
        help="Path to the document to validate (PDF or .txt)",
    )
    parser.add_argument(
        "--rules",
        required=True,
        help="Path to the compliance rules file (.txt)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="vLLM model name (e.g. 'meta-llama/Llama-3-8B-Instruct'). "
             "Overrides the default in agent.py.",
    )
    parser.add_argument(
        "--vllm-url",
        default="",
        help="vLLM server base URL (default: http://localhost:8000/v1)",
    )
    parser.add_argument(
        "--out",
        default="audit_report.json",
        help="Output path for the JSON audit report (default: audit_report.json)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="Number of document chunks to retrieve per rule (default: 3)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Token chunk size for document splitting (default: 500)",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print detailed evidence for each failed rule after the summary table",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Apply CLI overrides ───────────────────────────────────────────────────
    if args.model:
        ag.MODEL = args.model
        console.print(f"[dim]Model override: {ag.MODEL}[/dim]")

    if args.vllm_url:
        from openai import OpenAI
        ag.client = OpenAI(base_url=args.vllm_url, api_key="dummy")
        console.print(f"[dim]vLLM URL override: {args.vllm_url}[/dim]")

    console.rule("[bold blue]AI Compliance Validator[/bold blue]")

    # ── Step 1 — Load & chunk the document ───────────────────────────────────
    console.print(f"\n[bold]📄 Loading document:[/bold] {args.doc}")
    try:
        doc_text = load_document(args.doc)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)

    chunks = chunk_text(doc_text, chunk_size=args.chunk_size)
    console.print(f"   → {len(chunks)} chunks created (chunk_size={args.chunk_size})")

    # ── Step 2 — Build vector store ──────────────────────────────────────────
    console.print("\n[bold]🗄  Building vector store...[/bold]")
    doc_collection = build_store(chunks)
    console.print(f"   → ChromaDB in-memory collection ready ({doc_collection.count()} chunks)")

    # ── Step 3 — Load rules ──────────────────────────────────────────────────
    console.print(f"\n[bold]📋 Loading rules:[/bold] {args.rules}")
    try:
        rules = load_rules(args.rules)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    console.print(f"   → {len(rules)} rules loaded")

    # ── Step 4 — Run validation ──────────────────────────────────────────────
    console.print(f"\n[bold]🤖 Running validation (top_k={args.top_k})...[/bold]")
    results = run_validation(rules, doc_collection, top_k=args.top_k)

    # ── Step 5 — Generate & display report ───────────────────────────────────
    console.print()
    report = generate_report(results, doc_name=args.doc)
    print_terminal_report(report)

    if args.details:
        print_failed_details(report)

    save_report(report, out_path=args.out)
    console.rule("[bold blue]Done[/bold blue]")


if __name__ == "__main__":
    main()
