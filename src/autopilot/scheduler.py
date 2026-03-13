from __future__ import annotations

import asyncio
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from autopilot.backends import get_backend
from autopilot.channels import get_channel
from autopilot.conditions import check_condition
from autopilot.config import AutomationConfig, discover_automations
from autopilot.costs import parse_costs
from autopilot.health import start_health_server
from autopilot.models import BackendResult
from autopilot.prompts import resolve_prompt
from autopilot.results import save_result
from autopilot.state import get_last_run, update_last_run
from autopilot.worktree import cleanup_worktree, create_worktree

console = Console()


def _is_due(config: AutomationConfig, base_dir: Path) -> bool:
    last = get_last_run(base_dir, config.name)
    if last is None:
        return True
    elapsed = (datetime.now(UTC) - last).total_seconds()
    return elapsed >= config.schedule_seconds


async def run_automation(
    config: AutomationConfig,
    *,
    base_dir: Path,
    results_dir: Path,
    stream: bool = False,
) -> None:
    """Run a single automation with prompt resolution, retry, result saving, and notifications."""
    console.print(f"[bold blue]Running:[/] {config.name} (backend={config.backend})")

    # Resolve prompt templates
    last_run = get_last_run(base_dir, config.name)
    prompt = resolve_prompt(config.prompt, cwd=config.cwd, last_run=last_run)

    # Check run condition
    if config.run_if is not None:
        condition_met = await check_condition(config.run_if, config.working_directory, last_run)
        if not condition_met:
            console.print("  [dim]Skipped (condition not met)[/]")
            return

    # Create worktree
    wt_result = await create_worktree(
        cwd=config.cwd,
        copy_files=config.copy_files,
        skills_dir=config.skills_dir,
        prompt=prompt,
    )

    if wt_result is None:
        result = BackendResult(
            status="error",
            output="",
            error="Failed to create git worktree",
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
        )
        save_result(results_dir, config.name, result, backend=config.backend, model=config.model)
        console.print("  [red]ERROR:[/] Failed to create git worktree")
        return

    wt_path, branch_name = wt_result

    try:
        backend = get_backend(config.backend)

        # Set up log file for streaming
        log_dir = results_dir / config.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        log_path = log_dir / f"{log_ts}.log"

        on_output_fn = None
        if stream:
            console.print(f"  [dim]Log: {log_path}[/]\n")

            def _print_line(line: str) -> None:
                console.print(line, highlight=False)

            on_output_fn = _print_line

        # Execute with retry
        result = None
        for attempt in range(1 + config.max_retries):
            result = await backend.run(
                prompt,
                cwd=wt_path,
                timeout_seconds=config.timeout_seconds,
                model=config.model,
                reasoning_effort=config.reasoning_effort,
                skip_permissions=config.skip_permissions,
                max_turns=config.max_turns,
                log_file=log_path,
                on_output=on_output_fn,
            )
            if result.status == "ok":
                break
            if attempt < config.max_retries:
                wait = 2**attempt
                console.print(
                    f"  [yellow]Retry {attempt + 1}/{config.max_retries} in {wait}s...[/]"
                )
                await asyncio.sleep(wait)

        assert result is not None

        usage = parse_costs(config.backend, result.output)
        save_result(
            results_dir,
            config.name,
            result,
            backend=config.backend,
            model=config.model,
            usage=usage,
        )

        if stream:
            console.print()  # blank line after streaming output

        if result.status == "ok":
            update_last_run(base_dir, config.name, result.started_at)
            duration = (result.ended_at - result.started_at).total_seconds()
            console.print(f"  [green]OK[/] ({duration:.1f}s)")
        else:
            console.print(f"  [red]ERROR:[/] {result.error}")

        # Notify configured channels (worktree still exists here)
        context = {"worktree_path": str(wt_path)}
        for ch_config in config.channels:
            try:
                channel = get_channel(ch_config)
                await channel.notify(
                    config.name,
                    result,
                    backend=config.backend,
                    model=config.model,
                    context=context,
                )
                console.print(f"  [dim]Notified {ch_config.type}[/]")
            except Exception as exc:
                console.print(f"  [red]Channel {ch_config.type} failed:[/] {exc}")
    finally:
        await cleanup_worktree(config.cwd, wt_path, branch_name)


async def daemon_loop(
    automations_dir: Path,
    *,
    base_dir: Path,
    results_dir: Path,
    poll_interval: int = 60,
    max_concurrency: int = 5,
    health_port: int | None = None,
) -> None:
    """Run the scheduler daemon. Checks for due automations every poll_interval seconds."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        console.print("\n[yellow]Shutting down...[/]")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    # Health endpoint
    health_server = None
    daemon_state: dict = {"started_at": time.monotonic(), "automations_count": 0}
    if health_port is not None:
        health_server = await start_health_server(health_port, daemon_state)
        console.print(f"[dim]Health endpoint: http://0.0.0.0:{health_port}/health[/]")

    console.print(f"[bold]Daemon started.[/] Watching {automations_dir}")
    console.print(
        f"Poll interval: {poll_interval}s, concurrency: {max_concurrency}. Press Ctrl+C to stop.\n"
    )

    sem = asyncio.Semaphore(max_concurrency)

    async def _run_with_sem(config: AutomationConfig) -> None:
        async with sem:
            try:
                await run_automation(config, base_dir=base_dir, results_dir=results_dir)
            except Exception as exc:
                console.print(f"[red]Unhandled error running {config.name}:[/] {exc}")

    while not stop_event.is_set():
        try:
            configs = discover_automations(automations_dir)
            daemon_state["automations_count"] = len(configs)
        except Exception as exc:
            console.print(f"[red]Error loading configs:[/] {exc}")
            await asyncio.sleep(poll_interval)
            continue

        due = [c for c in configs if _is_due(c, base_dir)]
        if due:
            tasks = [asyncio.create_task(_run_with_sem(c)) for c in due]
            await asyncio.gather(*tasks)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            pass

    if health_server is not None:
        health_server.close()
        await health_server.wait_closed()

    console.print("[bold]Daemon stopped.[/]")
