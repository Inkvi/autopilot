from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from autopilot.channels.slack import _format_message as slack_format_message
from autopilot.conditions import check_condition
from autopilot.config import (
    AutomationConfig,
    CommandCondition,
    FileChangesCondition,
    GitChangesCondition,
)
from autopilot.models import BackendResult
from autopilot.prompts import resolve_prompt
from autopilot.repos import repo_name_from_url, resolve_working_directory
from autopilot.state import get_last_run


async def simulate_pipeline(
    config: AutomationConfig,
    *,
    base_dir: Path,
    simulate_conditions: bool = False,
    simulate_channels: bool = False,
    console: Console,
) -> None:
    """Walk through the automation pipeline, printing what each step would do."""
    console.print(f"\n[bold]=== Simulation: {config.name} ===[/]\n")

    # --- 1. Configuration ---
    console.print("[bold]\\[1/8] Configuration[/]")
    console.print(f"  Backend:      {config.backend}")
    console.print(f"  Model:        {config.model or 'default'}")
    console.print(f"  Timeout:      {config.timeout_seconds}s")
    console.print(f"  Max retries:  {config.max_retries}")
    console.print()

    # --- 2. Repos ---
    console.print("[bold]\\[2/8] Repos[/]")
    if config.repos:
        for url in config.repos:
            console.print(f"  Would clone/update: {url}")
    else:
        console.print("  (none configured)")
    console.print()

    # --- 3. Working directory ---
    console.print("[bold]\\[3/8] Working Directory[/]")
    # Build expected cloned_repos map so repo-name references resolve correctly
    cloned_repos: dict[str, Path] = {}
    if config.repos:
        cloned_repos = {
            repo_name_from_url(url): base_dir / ".repos" / repo_name_from_url(url)
            for url in config.repos
        }
    resolved_cwd = resolve_working_directory(config.working_directory, cloned_repos)
    if resolved_cwd is not None:
        if not resolved_cwd.exists():
            console.print(f"  Would resolve to: {resolved_cwd} (after cloning)")
        else:
            console.print(f"  Resolved: {resolved_cwd}")
    elif config.working_directory is None:
        console.print("  (temp dir — no working_directory set)")
    else:
        console.print(f"  Configured: {config.working_directory} (could not resolve)")
    console.print()

    # --- 4. Prompt ---
    console.print("[bold]\\[4/8] Prompt[/]")
    last_run = get_last_run(base_dir, config.name)
    prompt = resolve_prompt(config.prompt, cwd=resolved_cwd, last_run=last_run)
    console.print(f"  {prompt}")
    console.print()

    # --- 5. Conditions ---
    console.print("[bold]\\[5/8] Conditions[/]")
    if not simulate_conditions:
        console.print("  (skipped — use --simulate-conditions to evaluate)")
    elif config.run_if is None:
        console.print("  No run_if condition configured — would always run")
    else:
        await _simulate_condition(config, resolved_cwd, last_run, console)
    console.print()

    # --- 6. Skills ---
    console.print("[bold]\\[6/8] Skills[/]")
    local_skills: list[str] = []
    if config.skills_dir:
        local_skills = [
            d.name for d in config.skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()
        ]
    if local_skills:
        console.print(f"  Local:  {', '.join(local_skills)}")
    if config.skills:
        remote_names = [url.rstrip("/").split("/")[-1] for url in config.skills]
        console.print(f"  Remote: {', '.join(remote_names)}")
    if not local_skills and not config.skills:
        console.print("  (none)")
    console.print()

    # --- 7. Worktree ---
    console.print("[bold]\\[7/8] Worktree[/]")
    if resolved_cwd is not None:
        is_git = await _is_git_repo(resolved_cwd)
        if is_git:
            console.print(f"  Would create git worktree from {resolved_cwd}")
        else:
            console.print(
                f"  [yellow]Warning:[/] {resolved_cwd} is not inside a git repo"
                " — worktree creation would fail"
            )
        # Check copy_files
        existing = [f for f in config.copy_files if (resolved_cwd / f).exists()]
        missing = [f for f in config.copy_files if not (resolved_cwd / f).exists()]
        if existing:
            console.print(f"  Would copy: {', '.join(existing)}")
        if missing:
            console.print(f"  Not found (skip): {', '.join(missing)}")
        all_skills = local_skills + [url.rstrip("/").split("/")[-1] for url in config.skills]
        if all_skills:
            console.print(f"  Would inject skills: {', '.join(all_skills)}")
    else:
        console.print("  Would run in temporary directory")
    console.print()

    # --- 8. Channels ---
    console.print("[bold]\\[8/8] Channels[/]")
    if not simulate_channels:
        console.print("  (skipped — use --simulate-channels to preview)")
    elif not config.channels:
        console.print("  No channels configured")
    else:
        _simulate_channels(config, console)
    console.print()


async def _is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository (handles subdirectories)."""
    if not path.exists():
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--git-dir",
            cwd=path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        code = await proc.wait()
        return code == 0
    except OSError:
        return False


async def _simulate_condition(
    config: AutomationConfig,
    resolved_cwd: Path | None,
    last_run: datetime | None,
    console: Console,
) -> None:
    """Evaluate the run_if condition and print the result."""
    run_if = config.run_if
    assert run_if is not None

    if isinstance(run_if, GitChangesCondition):
        console.print("  Type: git_changes")
    elif isinstance(run_if, FileChangesCondition):
        console.print(f"  Type: file_changes (paths: {run_if.paths})")
    elif isinstance(run_if, CommandCondition):
        console.print(f"  Type: command (cmd: {run_if.cmd})")

    condition_cwd = str(resolved_cwd) if resolved_cwd else "."
    try:
        result = await check_condition(run_if, condition_cwd, last_run)
        if result:
            console.print("  Result: [green]PASS[/] (condition met — would run)")
        else:
            console.print("  Result: [yellow]SKIP[/] (condition not met — would be skipped)")
    except Exception as exc:
        console.print(f"  Result: [red]ERROR[/] ({exc})")


def _simulate_channels(config: AutomationConfig, console: Console) -> None:
    """Preview what each channel notification would look like."""
    now = datetime.now(UTC)
    synthetic_result = BackendResult(
        status="ok",
        output="[simulated output]",
        error=None,
        started_at=now,
        ended_at=now,
    )

    for ch_config in config.channels:
        label = f"  [{ch_config.type}]"

        if ch_config.type == "slack":
            console.print(f"{label} Slack webhook notification")
            try:
                ch_config.resolve_webhook_url()
                console.print("    Webhook URL: configured")
            except RuntimeError as exc:
                console.print(f"    [yellow]Warning:[/] {exc}")
            payload = slack_format_message(
                config.name, synthetic_result, backend=config.backend, model=config.model
            )
            console.print(f"    Title: {payload['text']}")

        elif ch_config.type == "github_issue":
            console.print(f"{label} GitHub issue on {ch_config.repo}")
            title = f"\\[autopilot] {config.name}: ok"
            console.print(f"    Title: {title}")
            if ch_config.labels:
                console.print(f"    Labels: {', '.join(ch_config.labels)}")

        elif ch_config.type == "github_pr":
            console.print(f"{label} GitHub PR on {ch_config.repo}")
            import re

            safe_name = re.sub(r"[^a-zA-Z0-9._-]", "-", config.name)
            console.print(f"    Branch: autopilot/{safe_name}")
            console.print(f"    Title: \\[autopilot] {config.name}")
            if ch_config.draft:
                console.print("    Draft: yes")
            if ch_config.labels:
                console.print(f"    Labels: {', '.join(ch_config.labels)}")

        else:
            console.print(f"{label} Unknown channel type: {ch_config.type}")
