"""
main.py — CLI entrypoint for the AI Compliance Validator

Usage:
    python main.py --doc documents/sample_policy.txt --rules rules/compliance_rules.txt
    python main.py --doc my.pdf --rules rules.txt --model "meta-llama/Llama-3-8B-Instruct" --out report.json
    python main.py --doc my.pdf --rules rules.txt --vllm-url http://localhost:9000/v1
"""

import argparse
import sys

from openai import OpenAI
from rich.console import Console

import validator.agent as ag
import validator.ingestion as ing
from validator.ingestion import load_and_chunk, load_rules
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
    parser.add_argument("--doc",       required=True, help="Path to document (PDF, TXT, HTML)")
    parser.add_argument("--rules",     required=True, help="Path to compliance rules file (TXT)")
    parser.add_argument("--model",     default="meta-llama/Llama-3-8B-Instruct",
                        help="vLLM model name")
    parser.add_argument("--vllm-url",  default="http://localhost:8000/v1",
                        help="vLLM server base URL")
    parser.add_argument("--out",       default="audit_report.json",
                        help="Output JSON report path")
    parser.add_argument("--top-k",     type=int, default=3,
                        help="Chunks retrieved per rule (default: 3)")
    parser.add_argument("--details",   action="store_true",
                        help="Print detailed failure evidence after summary")
    return parser.parse_args()


def main():
    args = parse_args()

    # ── Build shared vLLM client ──────────────────────────────────────────────
    client = OpenAI(base_url=args.vllm_url, api_key="dummy")
    model  = args.model

    # Share client with both ingestion (normalisation) and agent (validation)
    ing.init_llm(client, model)
    ag.client = client
    ag.MODEL   = model

    console.rule("[bold blue]AI Compliance Validator[/bold blue]")
    console.print(f"[dim]Model : {model}[/dim]")
    console.print(f"[dim]Server: {args.vllm_url}[/dim]")

    # ── Step 1 — AI-powered load + normalise + chunk ──────────────────────────
    console.print(f"\n[bold]📄 Loading & normalising document:[/bold] {args.doc}")
    try:
        chunks = load_and_chunk(args.doc)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    console.print(f"   → {len(chunks)} semantic chunks (AI-generated)")

    # ── Step 2 — Build vector store ───────────────────────────────────────────
    console.print("\n[bold]🗄  Building vector store...[/bold]")
    doc_collection = build_store(chunks)
    console.print(f"   → ChromaDB ready ({doc_collection.count()} chunks indexed)")

    # ── Step 3 — Load rules (AI-assisted parsing) ─────────────────────────────
    console.print(f"\n[bold]📋 Loading rules:[/bold] {args.rules}")
    try:
        rules = load_rules(args.rules)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]ERROR:[/red] {e}")
        sys.exit(1)
    console.print(f"   → {len(rules)} rules loaded")

    # ── Step 4 — Run validation ───────────────────────────────────────────────
    console.print(f"\n[bold]🤖 Running validation (top_k={args.top_k})...[/bold]")
    results = run_validation(rules, doc_collection, top_k=args.top_k)

    # ── Step 5 — Report ───────────────────────────────────────────────────────
    console.print()
    report = generate_report(results, doc_name=args.doc)
    print_terminal_report(report)
    if args.details:
        print_failed_details(report)
    save_report(report, out_path=args.out)
    console.rule("[bold blue]Done[/bold blue]")


if __name__ == "__main__":
    main()
