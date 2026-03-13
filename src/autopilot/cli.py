from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from autopilot.config import discover_automations, load_automation, parse_schedule
from autopilot.prompts import resolve_prompt
from autopilot.results import load_history, prune_results
from autopilot.scheduler import daemon_loop, run_automation
from autopilot.state import get_last_run

load_dotenv()

app = typer.Typer(name="autopilot", help="AI Automations CLI — run AI tasks on a schedule.")
console = Console()

DirOption = typer.Option("./automations", help="Path to automations directory")
ResultsDirOption = typer.Option("./results", help="Path to results directory")


@app.command()
def run(
    name: str = typer.Argument(help="Name of the automation to run"),
    dir: Path = DirOption,
    results_dir: Path = ResultsDirOption,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show resolved prompt without executing"),
) -> None:
    """Run a specific automation once."""
    auto_dir = dir / name
    if not (auto_dir / "config.toml").exists():
        console.print(f"[red]Automation not found:[/] {auto_dir}")
        raise typer.Exit(1)

    config = load_automation(auto_dir)

    if dry_run:
        last_run = get_last_run(Path("."), config.name)
        prompt = resolve_prompt(config.prompt, cwd=config.cwd, last_run=last_run)
        console.print(f"[bold]Automation:[/] {config.name}")
        console.print(f"[bold]Backend:[/] {config.backend}")
        console.print(f"[bold]Model:[/] {config.model or 'default'}")
        console.print(f"[bold]Working dir:[/] {config.cwd}")
        console.print(f"[bold]Timeout:[/] {config.timeout_seconds}s")
        console.print(f"[bold]Max retries:[/] {config.max_retries}")
        if config.skills_dir:
            skills = [
                d.name for d in config.skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            console.print(f"[bold]Skills:[/] {', '.join(skills) if skills else 'none'}")
        console.print(f"\n[bold]Resolved prompt:[/]\n{prompt}")
        return

    base_dir = Path(".")
    asyncio.run(run_automation(config, base_dir=base_dir, results_dir=results_dir))


@app.command("list")
def list_automations(
    dir: Path = DirOption,
) -> None:
    """List all configured automations."""
    configs = discover_automations(dir)
    if not configs:
        console.print("[yellow]No automations found.[/]")
        console.print(f"Create automation folders in {dir} or run: autopilot init <name>")
        return

    base_dir = Path(".")
    table = Table(title="Automations")
    table.add_column("Name", style="bold")
    table.add_column("Backend")
    table.add_column("Schedule")
    table.add_column("Model")
    table.add_column("Working Dir")
    table.add_column("Last Run")

    for config in configs:
        last = get_last_run(base_dir, config.name)
        last_str = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        table.add_row(
            config.name,
            config.backend,
            config.schedule,
            config.model or "-",
            str(config.working_directory),
            last_str,
        )

    console.print(table)


@app.command()
def daemon(
    dir: Path = DirOption,
    results_dir: Path = ResultsDirOption,
    poll_interval: int = typer.Option(60, help="Seconds between schedule checks"),
    max_concurrency: int = typer.Option(5, help="Max automations to run in parallel"),
    health_port: int | None = typer.Option(
        None, help="Port for health endpoint (disabled if unset)"
    ),
) -> None:
    """Start the scheduler daemon (runs forever)."""
    base_dir = Path(".")
    asyncio.run(
        daemon_loop(
            dir,
            base_dir=base_dir,
            results_dir=results_dir,
            poll_interval=poll_interval,
            max_concurrency=max_concurrency,
            health_port=health_port,
        )
    )


@app.command()
def init(
    name: str = typer.Argument(help="Name for the new automation"),
    dir: Path = DirOption,
) -> None:
    """Create a template automation config."""
    auto_dir = dir / name
    if auto_dir.exists():
        console.print(f"[yellow]Already exists:[/] {auto_dir}")
        raise typer.Exit(1)

    auto_dir.mkdir(parents=True)
    (auto_dir / "skills").mkdir()

    template = f'''\
name = "{name}"
prompt = """
Describe what this automation should do.
"""
working_directory = "."
schedule = "24h"
backend = "claude_cli"
# model = "claude-sonnet-4-5"
# reasoning_effort = "medium"
# timeout_seconds = 900
# skip_permissions = true
# max_turns = 10
# max_retries = 0
# copy_files = [".env", ".env.local", ".envrc"]
'''
    (auto_dir / "config.toml").write_text(template, encoding="utf-8")
    console.print(f"[green]Created:[/] {auto_dir}/")
    console.print("Edit config.toml and optionally add skills to the skills/ directory.")
    console.print(f"  autopilot run {name}")


@app.command()
def history(
    name: str = typer.Argument(help="Name of the automation"),
    results_dir: Path = ResultsDirOption,
    limit: int = typer.Option(20, help="Number of recent runs to show"),
) -> None:
    """Show run history for an automation."""
    entries = load_history(results_dir, name)
    if not entries:
        console.print(f"[yellow]No history found for {name}.[/]")
        return

    table = Table(title=f"History: {name}")
    table.add_column("Started At")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Backend")
    table.add_column("Model")
    table.add_column("Error")

    for entry in entries[:limit]:
        status_style = "green" if entry["status"] == "ok" else "red"
        error = entry.get("error") or ""
        if len(error) > 60:
            error = error[:57] + "..."
        table.add_row(
            entry.get("started_at", "?"),
            f"[{status_style}]{entry['status']}[/{status_style}]",
            f"{entry.get('duration_s', '?')}s",
            entry.get("backend", "?"),
            entry.get("model") or "-",
            error,
        )

    console.print(table)


@app.command()
def validate(
    dir: Path = DirOption,
) -> None:
    """Validate all automation configs and check backend availability."""
    errors: list[str] = []
    warnings: list[str] = []

    if not dir.is_dir():
        console.print(f"[red]Automations directory not found:[/] {dir}")
        raise typer.Exit(1)

    auto_dirs = sorted(
        d for d in dir.iterdir() if d.is_dir() and (d / "config.toml").exists()
    )
    if not auto_dirs:
        console.print(f"[yellow]No automation folders found in {dir}[/]")
        raise typer.Exit(1)

    # Warn about old flat TOML files
    flat_tomls = sorted(dir.glob("*.toml"))
    for ft in flat_tomls:
        warnings.append(
            f"Found flat .toml file: {ft.name}. "
            f"Migrate to folder format: {ft.stem}/config.toml"
        )

    backend_binaries = {
        "claude_cli": "claude",
        "codex_cli": "codex",
        "gemini_cli": "gemini",
    }
    checked_binaries: dict[str, bool] = {}

    for auto_dir in auto_dirs:
        label = auto_dir.name
        try:
            config = load_automation(auto_dir)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue

        # Check working directory exists
        if not config.cwd.is_dir():
            errors.append(f"{label}: working_directory does not exist: {config.working_directory}")

        # Check schedule parses
        try:
            parse_schedule(config.schedule)
        except ValueError as exc:
            errors.append(f"{label}: {exc}")

        # Check backend binary
        binary = backend_binaries.get(config.backend)
        if binary and binary not in checked_binaries:
            checked_binaries[binary] = shutil.which(binary) is not None
        if binary and not checked_binaries.get(binary):
            warnings.append(
                f"{label}: backend '{config.backend}' "
                f"requires '{binary}' but it's not in PATH"
            )

        # Check channel webhook URLs
        for i, ch in enumerate(config.channels):
            try:
                ch.resolve_webhook_url()
            except RuntimeError as exc:
                warnings.append(f"{label}: channel[{i}] ({ch.type}): {exc}")

        # Check skills/ subfolders
        skills_path = auto_dir / "skills"
        if skills_path.is_dir():
            for entry in sorted(skills_path.iterdir()):
                if entry.is_dir() and not (entry / "SKILL.md").exists():
                    warnings.append(f"{label}: skills/{entry.name}/ has no SKILL.md")

        console.print(f"  [green]OK[/] {label}")

    if warnings:
        console.print(f"\n[yellow]{len(warnings)} warning(s):[/]")
        for w in warnings:
            console.print(f"  [yellow]![/] {w}")

    if errors:
        console.print(f"\n[red]{len(errors)} error(s):[/]")
        for e in errors:
            console.print(f"  [red]x[/] {e}")
        raise typer.Exit(1)

    total = len(auto_dirs)
    console.print(f"\n[green]All {total} automation(s) valid.[/]")


@app.command()
def prune(
    older_than: str = typer.Argument(
        help="Remove results older than this duration (e.g. 30d, 720h)"
    ),
    results_dir: Path = ResultsDirOption,
) -> None:
    """Remove old run results."""
    try:
        seconds = parse_schedule(older_than)
    except ValueError:
        console.print(f"[red]Invalid duration:[/] {older_than}. Use e.g. '30d', '720h'.")
        raise typer.Exit(1) from None

    removed = prune_results(results_dir, seconds)
    if removed:
        console.print(f"[green]Pruned {removed} result(s) older than {older_than}.[/]")
    else:
        console.print("[dim]Nothing to prune.[/]")
