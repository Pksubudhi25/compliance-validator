import json
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def generate_report(results: list[dict], doc_name: str) -> dict:
    """
    Build the full audit report dictionary from validation results.
    Includes a summary with compliance score and per-rule findings.
    """
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"] == "FAIL")
    unclear = total - passed - failed
    avg_confidence = sum(r["confidence"] for r in results) / total if total else 0.0
    compliance_score = (passed / total * 100) if total else 0.0

    return {
        "metadata": {
            "document": doc_name,
            "timestamp": datetime.now().isoformat(),
            "engine": "vLLM + ChromaDB RAG",
        },
        "summary": {
            "total_rules": total,
            "passed": passed,
            "failed": failed,
            "unclear": unclear,
            "compliance_score": round(compliance_score, 2),
            "avg_confidence": round(avg_confidence, 4),
        },
        "findings": results,
    }


def print_terminal_report(report: dict) -> None:
    """Render a rich, colour-coded audit report to the terminal."""
    s = report["summary"]
    score = s["compliance_score"]
    score_color = "green" if score >= 80 else "yellow" if score >= 50 else "red"

    # ── Header panel ──────────────────────────────────────────────────────────
    console.print(
        Panel(
            f"[bold]Document:[/bold]   {report['metadata']['document']}\n"
            f"[bold]Timestamp:[/bold]  {report['metadata']['timestamp']}\n"
            f"[bold]Engine:[/bold]     {report['metadata']['engine']}\n\n"
            f"[bold {score_color}]Compliance Score: {score:.1f}%[/bold {score_color}]\n"
            f"✅ Passed : [green]{s['passed']}[/green]   "
            f"❌ Failed : [red]{s['failed']}[/red]   "
            f"❓ Unclear: [yellow]{s['unclear']}[/yellow]\n"
            f"Avg Confidence: {s['avg_confidence']:.2f}",
            title="[bold blue]╔═  AUDIT REPORT  ═╗[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # ── Findings table ────────────────────────────────────────────────────────
    table = Table(box=box.ROUNDED, show_lines=True, header_style="bold cyan")
    table.add_column("Rule ID",  style="cyan",  width=10, no_wrap=True)
    table.add_column("Rule",                    width=32)
    table.add_column("Verdict",                 width=9,  no_wrap=True)
    table.add_column("Conf.",                   width=6,  no_wrap=True)
    table.add_column("Explanation",             width=48)

    for f in report["findings"]:
        v = f["verdict"]
        color = {"PASS": "green", "FAIL": "red", "UNCLEAR": "yellow"}.get(v, "white")
        icon  = {"PASS": "✅",    "FAIL": "❌",   "UNCLEAR": "❓"}.get(v, "")
        table.add_row(
            f["rule_id"],
            f["rule_text"][:60],
            f"[{color}]{icon} {v}[/{color}]",
            f"{f['confidence']:.2f}",
            f.get("explanation", "")[:120],
        )

    console.print(table)


def print_failed_details(report: dict) -> None:
    """Print detailed evidence for every FAIL finding — useful for judges demo."""
    failed = [f for f in report["findings"] if f["verdict"] == "FAIL"]
    if not failed:
        console.print("\n[green]No failed rules — document is fully compliant![/green]")
        return

    console.print(f"\n[bold red]── Failure Details ({len(failed)} issues) ──[/bold red]")
    for f in failed:
        console.print(
            Panel(
                f"[bold]Rule:[/bold]        {f['rule_text']}\n"
                f"[bold]Confidence:[/bold]  {f['confidence']:.2f}\n"
                f"[bold]Evidence:[/bold]    {f.get('evidence', 'N/A')}\n"
                f"[bold]Explanation:[/bold] {f.get('explanation', 'N/A')}",
                title=f"[red]❌ {f['rule_id']}[/red]",
                border_style="red",
            )
        )


def save_report(report: dict, out_path: str = "audit_report.json") -> None:
    """Persist the full audit report as a JSON file."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    console.print(f"\n[green]✔  Report saved → {out.resolve()}[/green]")
