from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from autopilot.config import (
    discover_automations,
    load_automation,
    load_base_config,
    parse_name_list,
    parse_schedule,
)
from autopilot.prompts import resolve_prompt
from autopilot.results import load_history, prune_results
from autopilot.scheduler import run_automation
from autopilot.state import get_last_run

load_dotenv()

app = typer.Typer(name="autopilot", help="AI Automations CLI — run AI tasks on a schedule.")
console = Console()

DirOption = typer.Option("./automations", help="Path to automations directory")
ResultsDirOption = typer.Option("./results", help="Path to results directory")
BaseDirOption = typer.Option(
    None, "--base-dir", help="Writable dir for state, repos, etc. (defaults to --dir)"
)


def _format_backends(config) -> str:
    return " -> ".join(config.backends)


def _format_model(config) -> str:
    return config.model_display


@app.command()
def run(
    name: str = typer.Argument(help="Name of the automation to run"),
    dir: Path = DirOption,
    results_dir: Path = ResultsDirOption,
    base_dir: Path | None = BaseDirOption,
    dry_run: bool = typer.Option(False, "--dry-run", help="Show resolved prompt without executing"),
    stream: bool = typer.Option(False, "--stream", help="Stream backend output in real-time"),
) -> None:
    """Run a specific automation once."""
    auto_dir = dir / name
    if not (auto_dir / "config.toml").exists():
        console.print(f"[red]Automation not found:[/] {auto_dir}")
        raise typer.Exit(1)

    base_config = load_base_config(dir)
    config = load_automation(auto_dir, base_config=base_config)

    if dry_run:
        last_run = get_last_run(dir, config.name)
        prompt = resolve_prompt(config.prompt, cwd=config.cwd, last_run=last_run)
        console.print(f"[bold]Automation:[/] {config.name}")
        console.print(f"[bold]Backend:[/] {_format_backends(config)}")
        console.print(f"[bold]Model:[/] {_format_model(config)}")
        console.print(f"[bold]System prompt:[/] {config.system_prompt or '(none)'}")
        console.print(f"[bold]Working dir:[/] {config.cwd or '(none — temp dir)'}")
        console.print(f"[bold]Timeout:[/] {config.timeout_seconds}s")
        console.print(f"[bold]Max retries:[/] {config.max_retries}")
        if config.skills_dir:
            skills = [
                d.name
                for d in config.skills_dir.iterdir()
                if d.is_dir() and (d / "SKILL.md").exists()
            ]
            console.print(f"[bold]Skills:[/] {', '.join(skills) if skills else 'none'}")
        if config.skills:
            remote_names = []
            for url in config.skills:
                # Last path component is the skill name
                remote_names.append(url.rstrip("/").split("/")[-1])
            console.print(f"[bold]Remote skills:[/] {', '.join(remote_names)}")
        console.print(f"\n[bold]Resolved prompt:[/]\n{prompt}")
        return

    asyncio.run(
        run_automation(config, base_dir=base_dir or dir, results_dir=results_dir, stream=stream)
    )


@app.command("list")
def list_automations(
    dir: Path = DirOption,
    include: str | None = typer.Option(
        None,
        "--include",
        envvar="AUTOPILOT_INCLUDE",
        help="Comma-separated automation names to include",
    ),
    exclude: str | None = typer.Option(
        None,
        "--exclude",
        envvar="AUTOPILOT_EXCLUDE",
        help="Comma-separated automation names to exclude",
    ),
) -> None:
    """List all configured automations."""
    include_list = parse_name_list(include)
    exclude_list = parse_name_list(exclude)
    if include_list and exclude_list:
        console.print("[red]Cannot specify both --include and --exclude[/]")
        raise typer.Exit(1)
    configs = discover_automations(dir, include=include_list, exclude=exclude_list)
    if not configs:
        console.print("[yellow]No automations found.[/]")
        console.print(f"Create automation folders in {dir} or run: autopilot init <name>")
        return

    base_dir = Path(".")
    table = Table(title="Automations")
    table.add_column("Name", style="bold")
    table.add_column("Enabled")
    table.add_column("Backend")
    table.add_column("Schedule")
    table.add_column("Model")
    table.add_column("Working Dir")
    table.add_column("Last Run")

    for config in configs:
        last = get_last_run(base_dir, config.name)
        last_str = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        enabled_str = "[green]yes[/]" if config.enabled else "[red]no[/]"
        table.add_row(
            config.name,
            enabled_str,
            _format_backends(config),
            config.schedule,
            _format_model(config),
            str(config.working_directory),
            last_str,
        )

    console.print(table)


@app.command()
def daemon(
    dir: Path = DirOption,
    results_dir: Path = ResultsDirOption,
    base_dir: Path | None = BaseDirOption,
    poll_interval: int = typer.Option(60, help="Seconds between schedule checks"),
    max_concurrency: int = typer.Option(5, help="Max automations to run in parallel"),
    health_port: int | None = typer.Option(
        None, help="Port for web dashboard and health endpoint (disabled if unset)"
    ),
    include: str | None = typer.Option(
        None,
        "--include",
        envvar="AUTOPILOT_INCLUDE",
        help="Comma-separated automation names to include",
    ),
    exclude: str | None = typer.Option(
        None,
        "--exclude",
        envvar="AUTOPILOT_EXCLUDE",
        help="Comma-separated automation names to exclude",
    ),
) -> None:
    """Start the scheduler daemon (runs forever)."""
    import os

    include_list = parse_name_list(include)
    exclude_list = parse_name_list(exclude)
    if include_list and exclude_list:
        console.print("[red]Cannot specify both --include and --exclude[/]")
        raise typer.Exit(1)

    effective_base = base_dir or dir

    if health_port is not None:
        import uvicorn

        # Pass config to the app factory via environment variables
        os.environ["AUTOPILOT_DIR"] = str(dir)
        os.environ["AUTOPILOT_BASE_DIR"] = str(effective_base)
        os.environ["AUTOPILOT_RESULTS_DIR"] = str(results_dir)
        os.environ["AUTOPILOT_CONCURRENCY"] = str(max_concurrency)
        os.environ["AUTOPILOT_POLL"] = str(poll_interval)
        if include:
            os.environ["AUTOPILOT_INCLUDE"] = include
        if exclude:
            os.environ["AUTOPILOT_EXCLUDE"] = exclude

        uvicorn.run(
            "autopilot.api.app:create_app",
            factory=True,
            host="0.0.0.0",
            port=health_port,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
    else:
        from autopilot.scheduler import daemon_loop

        asyncio.run(
            daemon_loop(
                dir,
                base_dir=effective_base,
                results_dir=results_dir,
                poll_interval=poll_interval,
                max_concurrency=max_concurrency,
                include=include_list,
                exclude=exclude_list,
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
backend = "claude_cli"  # or ["claude_cli", "gemini_cli"] for fallback
# enabled = true
# model = "claude-sonnet-4-5"
# model = {{ claude_cli = "claude-sonnet-4-5", gemini_cli = "gemini-2.5-pro" }}
# reasoning_effort = "medium"
# timeout_seconds = 900
# skip_permissions = true
# max_turns = 10
# max_retries = 0
# copy_files = [".env", ".env.local", ".envrc"]
# skills = [
#   "https://github.com/org/repo/tree/main/skills/my-skill",
# ]
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

    auto_dirs = sorted(d for d in dir.iterdir() if d.is_dir() and (d / "config.toml").exists())
    if not auto_dirs:
        console.print(f"[yellow]No automation folders found in {dir}[/]")
        raise typer.Exit(1)

    # Warn about old flat TOML files (exclude base.toml)
    flat_tomls = sorted(p for p in dir.glob("*.toml") if p.name != "base.toml")
    for ft in flat_tomls:
        warnings.append(
            f"Found flat .toml file: {ft.name}. Migrate to folder format: {ft.stem}/config.toml"
        )

    base_config = load_base_config(dir)

    backend_binaries = {
        "claude_cli": "claude",
        "codex_cli": "codex",
        "gemini_cli": "gemini",
    }
    checked_binaries: dict[str, bool] = {}

    for auto_dir in auto_dirs:
        label = auto_dir.name
        try:
            config = load_automation(auto_dir, base_config=base_config)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            continue

        # Check working directory exists (if set)
        if config.cwd is not None and not config.cwd.is_dir():
            errors.append(f"{label}: working_directory does not exist: {config.working_directory}")

        # Check schedule parses
        if config.schedule is not None:
            try:
                parse_schedule(config.schedule)
            except ValueError as exc:
                errors.append(f"{label}: {exc}")

        # Check backend binaries
        for b in config.backends:
            binary = backend_binaries.get(b)
            if binary and binary not in checked_binaries:
                checked_binaries[binary] = shutil.which(binary) is not None
            if binary and not checked_binaries.get(binary):
                warnings.append(f"{label}: backend '{b}' requires '{binary}' but it's not in PATH")

        # Check gh CLI for GitHub channels
        has_github_channel = any(ch.type in ("github_issue", "github_pr") for ch in config.channels)
        if has_github_channel and "gh" not in checked_binaries:
            checked_binaries["gh"] = shutil.which("gh") is not None
        if has_github_channel and not checked_binaries.get("gh"):
            warnings.append(f"{label}: GitHub channels require 'gh' CLI but it's not in PATH")

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

        # Check remote skills URLs
        if config.skills:
            for url in config.skills:
                try:
                    from autopilot.repos import parse_github_tree_url

                    parse_github_tree_url(url)
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")

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
def costs(
    results_dir: Path = ResultsDirOption,
    name: str | None = typer.Option(None, "--name", help="Filter by automation name"),
    since: str = typer.Option("30d", "--since", help="Show costs since (e.g. 7d, 24h)"),
) -> None:
    """Show token usage and costs across automations."""
    import json
    from datetime import UTC, datetime, timedelta

    try:
        cutoff_seconds = parse_schedule(since)
    except ValueError:
        console.print(f"[red]Invalid duration:[/] {since}")
        raise typer.Exit(1) from None

    cutoff = datetime.now(UTC) - timedelta(seconds=cutoff_seconds)

    if not results_dir.is_dir():
        console.print("[yellow]No cost data found.[/]")
        return

    # Collect costs per automation
    totals: dict[str, dict] = {}
    for auto_dir in sorted(results_dir.iterdir()):
        if not auto_dir.is_dir():
            continue
        if name and auto_dir.name != name:
            continue

        auto_name = auto_dir.name
        totals[auto_name] = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "runs": 0}

        for meta_path in auto_dir.glob("*.meta.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                started = datetime.fromisoformat(meta["started_at"])
                if started < cutoff:
                    continue
                totals[auto_name]["runs"] += 1
                totals[auto_name]["tokens_in"] += meta.get("tokens_in") or 0
                totals[auto_name]["tokens_out"] += meta.get("tokens_out") or 0
                totals[auto_name]["cost_usd"] += meta.get("cost_usd") or 0.0
            except (json.JSONDecodeError, KeyError, OSError):
                continue

    # Filter out automations with no runs in the period
    totals = {k: v for k, v in totals.items() if v["runs"] > 0}

    if not totals:
        console.print("[yellow]No cost data found.[/]")
        return

    table = Table(title=f"Costs (since {since})")
    table.add_column("Automation", style="bold")
    table.add_column("Runs", justify="right")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Out", justify="right")
    table.add_column("Cost (USD)", justify="right")

    grand_in = grand_out = 0
    grand_cost = 0.0
    grand_runs = 0

    for auto_name, data in sorted(totals.items()):
        table.add_row(
            auto_name,
            str(data["runs"]),
            f"{data['tokens_in']:,}",
            f"{data['tokens_out']:,}",
            f"${data['cost_usd']:.2f}",
        )
        grand_in += data["tokens_in"]
        grand_out += data["tokens_out"]
        grand_cost += data["cost_usd"]
        grand_runs += data["runs"]

    if len(totals) >= 1:
        table.add_section()
        table.add_row(
            "Total",
            str(grand_runs),
            f"{grand_in:,}",
            f"{grand_out:,}",
            f"${grand_cost:.2f}",
            style="bold",
        )

    console.print(table)


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
