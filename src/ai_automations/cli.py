from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ai_automations.config import discover_automations, load_automation
from ai_automations.results import load_history
from ai_automations.scheduler import daemon_loop, run_automation
from ai_automations.state import get_last_run

app = typer.Typer(name="autopilot", help="AI Automations CLI — run AI tasks on a schedule.")
console = Console()

DirOption = typer.Option("./automations", help="Path to automations directory")
ResultsDirOption = typer.Option("./results", help="Path to results directory")


@app.command()
def run(
    name: str = typer.Argument(help="Name of the automation to run"),
    dir: Path = DirOption,
    results_dir: Path = ResultsDirOption,
) -> None:
    """Run a specific automation once."""
    toml_path = dir / f"{name}.toml"
    if not toml_path.exists():
        console.print(f"[red]Automation not found:[/] {toml_path}")
        raise typer.Exit(1)

    config = load_automation(toml_path)
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
        console.print(f"Create .toml files in {dir} or run: autopilot init <name>")
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
) -> None:
    """Start the scheduler daemon (runs forever)."""
    base_dir = Path(".")
    asyncio.run(
        daemon_loop(dir, base_dir=base_dir, results_dir=results_dir, poll_interval=poll_interval)
    )


@app.command()
def init(
    name: str = typer.Argument(help="Name for the new automation"),
    dir: Path = DirOption,
) -> None:
    """Create a template automation config."""
    dir.mkdir(parents=True, exist_ok=True)
    toml_path = dir / f"{name}.toml"
    if toml_path.exists():
        console.print(f"[yellow]Already exists:[/] {toml_path}")
        raise typer.Exit(1)

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
# use_worktree = false
'''
    toml_path.write_text(template, encoding="utf-8")
    console.print(f"[green]Created:[/] {toml_path}")
    console.print("Edit the file to configure your automation, then run:")
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
