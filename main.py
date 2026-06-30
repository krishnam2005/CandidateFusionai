"""
main.py — CandidateFusion AI CLI entry point.

Built with Typer for a polished, self-documented CLI experience.

Usage:
    python main.py --csv inputs/recruiter.csv --ats inputs/ats.json \\
                   --resume inputs/resume.pdf --github https://github.com/octocat \\
                   --notes inputs/notes.txt --config config/default.json

All source arguments are optional — you can run with any combination.
At least one source is required.
"""

from __future__ import annotations

import sys

# Ensure UTF-8 output on Windows consoles that default to a legacy charmap codec.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from config.settings import get_settings
from services.pipeline import Pipeline, PipelineInput
from utils.logging import get_logger, setup_logging

app = typer.Typer(
    name="candidate-fusion",
    help="CandidateFusion AI — Multi-Source Candidate Data Transformer",
    add_completion=True,
    rich_markup_mode="rich",
)
console = Console()


def _setup_logging_from_settings() -> None:
    """Initialize logging from application settings."""
    settings = get_settings()
    setup_logging(
        log_level=settings.log_level.value,
        log_format=settings.log_format.value,
        log_dir=settings.pipeline_log_dir,
    )


@app.command()
def transform(
    csv: Annotated[
        Optional[Path],
        typer.Option("--csv", help="Path to recruiter CSV file", exists=False, dir_okay=False),
    ] = None,
    ats: Annotated[
        Optional[Path],
        typer.Option("--ats", help="Path to ATS JSON file", exists=False, dir_okay=False),
    ] = None,
    resume: Annotated[
        Optional[Path],
        typer.Option("--resume", help="Path to resume PDF file", exists=False, dir_okay=False),
    ] = None,
    github: Annotated[
        Optional[str],
        typer.Option("--github", help="GitHub profile URL or username"),
    ] = None,
    notes: Annotated[
        Optional[Path],
        typer.Option("--notes", help="Path to recruiter notes TXT file", exists=False, dir_okay=False),
    ] = None,
    config: Annotated[
        Optional[Path],
        typer.Option("--config", help="Path to output config JSON file", exists=False, dir_okay=False),
    ] = None,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output JSON file path (default: stdout)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable verbose (DEBUG) logging"),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option("--strict", help="Fail on any validation error"),
    ] = False,
) -> None:
    """
    Transform candidate data from multiple sources into a canonical profile.

    [bold]Examples:[/bold]

    [green]# All sources[/green]
    python main.py --csv inputs/recruiter.csv --ats inputs/ats.json \\
                   --resume inputs/resume.pdf --github https://github.com/octocat \\
                   --notes inputs/notes.txt

    [green]# ATS only[/green]
    python main.py --ats inputs/ats.json --config config/minimal.json

    [green]# Save to file[/green]
    python main.py --ats inputs/ats.json --output outputs/candidate.json
    """
    # ── Logging setup ─────────────────────────────────────────────────────
    settings = get_settings()
    setup_logging(
        log_level="DEBUG" if verbose else settings.log_level.value,
        log_format="console" if sys.stderr.isatty() else settings.log_format.value,
        log_dir=settings.pipeline_log_dir,
    )
    log = get_logger(__name__)

    # ── Validate at least one source ──────────────────────────────────────
    if not any([csv, ats, resume, github, notes]):
        console.print(
            Panel(
                "[red]Error:[/red] At least one input source is required.\n\n"
                "Provide one or more of: [bold]--csv[/bold], [bold]--ats[/bold], "
                "[bold]--resume[/bold], [bold]--github[/bold], [bold]--notes[/bold]",
                title="CandidateFusion AI",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # ── Print header ──────────────────────────────────────────────────────
    console.print(
        Panel(
            "[bold blue]CandidateFusion AI[/bold blue]\n"
            "[dim]Multi-Source Candidate Data Transformer[/dim]",
            border_style="blue",
        )
    )

    # ── Show inputs ────────────────────────────────────────────────────────
    _print_input_table(console, csv=csv, ats=ats, resume=resume, github=github, notes=notes, config=config)

    # ── Run pipeline ──────────────────────────────────────────────────────
    pipeline_inputs = PipelineInput(
        csv_path=csv,
        ats_path=ats,
        resume_path=resume,
        github_url=github,
        notes_path=notes,
        output_config_path=config or settings.pipeline_default_config_path,
    )

    try:
        pipeline = Pipeline(settings=settings)
        with console.status("[bold green]Running transformation pipeline...[/bold green]"):
            result = pipeline.run(pipeline_inputs)

    except ValueError as exc:
        console.print(f"[red]Pipeline error:[/red] {exc}")
        log.error("pipeline_input_error", error=str(exc))
        raise typer.Exit(code=1) from exc

    except Exception as exc:
        console.print(f"[red]Unexpected error:[/red] {exc}")
        log.error("pipeline_unexpected_error", error=str(exc), exc_info=True)
        raise typer.Exit(code=1) from exc

    # ── Print results summary ─────────────────────────────────────────────
    _print_results_summary(console, result)

    # ── Output JSON ───────────────────────────────────────────────────────
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(result.output_json)
        console.print(f"\n[green]✓[/green] Output written to [bold]{output}[/bold]")
        log.info("output_written", path=str(output), size_bytes=len(result.output_json))
    else:
        # Print to stdout
        sys.stdout.buffer.write(result.output_json)
        sys.stdout.buffer.write(b"\n")

    # ── Exit code ─────────────────────────────────────────────────────────
    if strict and not result.validation_report.is_valid:
        console.print(
            f"\n[red]Strict mode: {len(result.validation_report.errors)} validation error(s) found.[/red]"
        )
        raise typer.Exit(code=2)


def _print_input_table(
    console: Console,
    *,
    csv: Optional[Path],
    ats: Optional[Path],
    resume: Optional[Path],
    github: Optional[str],
    notes: Optional[Path],
    config: Optional[Path],
) -> None:
    """Print a Rich table showing all provided inputs."""
    table = Table(title="Input Sources", show_header=True, header_style="bold cyan")
    table.add_column("Source", style="dim")
    table.add_column("Input")
    table.add_column("Status")

    rows = [
        ("ATS JSON", str(ats) if ats else None),
        ("Recruiter CSV", str(csv) if csv else None),
        ("Resume PDF", str(resume) if resume else None),
        ("GitHub Profile", github),
        ("Recruiter Notes", str(notes) if notes else None),
        ("Output Config", str(config) if config else "(default)"),
    ]

    for source_name, value in rows:
        if value:
            exists = Path(value).exists() if not value.startswith("http") and value != "(default)" else True
            status = "[green]✓[/green]" if exists else "[yellow]⚠ not found[/yellow]"
            table.add_row(source_name, value, status)
        else:
            table.add_row(source_name, "[dim]—[/dim]", "[dim]not provided[/dim]")

    console.print(table)


def _print_results_summary(console: Console, result: object) -> None:
    """Print a summary of pipeline results."""
    candidate = result.candidate
    meta = result.metadata
    conf = candidate.confidence

    table = Table(title="Pipeline Results", show_header=True, header_style="bold green")
    table.add_column("Field", style="dim")
    table.add_column("Value")

    table.add_row("Candidate", f"[bold]{candidate.display_name}[/bold]")
    table.add_row("Run ID", str(meta.run_id))
    table.add_row("Duration", f"{meta.duration_ms:.0f}ms" if meta.duration_ms else "—")
    table.add_row("Sources Succeeded", f"[green]{len(meta.sources_succeeded)}[/green]")
    table.add_row(
        "Sources Failed",
        f"[red]{len(meta.sources_failed)}[/red]" if meta.sources_failed else "[green]0[/green]",
    )
    table.add_row("Emails", str(len(candidate.emails)))
    table.add_row("Phones", str(len(candidate.phones)))
    table.add_row("Skills", str(len(candidate.skills)))
    table.add_row("Experience Entries", str(len(candidate.experience)))
    table.add_row("Education Entries", str(len(candidate.education)))
    table.add_row("Projects", str(len(candidate.projects)))

    if conf:
        score_str = f"{conf.overall_score:.3f}"
        if conf.overall_score >= 0.90:
            table.add_row("Overall Confidence", f"[green]{score_str}[/green]")
        elif conf.overall_score >= 0.70:
            table.add_row("Overall Confidence", f"[yellow]{score_str}[/yellow]")
        else:
            table.add_row("Overall Confidence", f"[red]{score_str}[/red]")

    validation_status = "[green]✓ Passed[/green]" if meta.validation_passed else "[red]✗ Failed[/red]"
    if result.validation_report.warnings:
        validation_status += f" [yellow]({len(result.validation_report.warnings)} warnings)[/yellow]"
    table.add_row("Validation", validation_status)

    console.print(table)

    # Show validation warnings/errors
    if result.validation_report.errors:
        console.print("\n[red]Validation Errors:[/red]")
        for finding in result.validation_report.errors:
            console.print(f"  [red]✗[/red] [{finding.field}] {finding.message}")

    if result.validation_report.warnings:
        console.print("\n[yellow]Validation Warnings:[/yellow]")
        for finding in result.validation_report.warnings:
            console.print(f"  [yellow]⚠[/yellow] [{finding.field}] {finding.message}")


if __name__ == "__main__":
    app()
