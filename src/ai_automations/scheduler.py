from __future__ import annotations

import asyncio
import signal
import time
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from ai_automations.backends import get_backend
from ai_automations.channels import get_channel
from ai_automations.config import AutomationConfig, discover_automations
from ai_automations.health import start_health_server
from ai_automations.models import BackendResult
from ai_automations.prompts import resolve_prompt
from ai_automations.results import save_result
from ai_automations.state import get_last_run, update_last_run
from ai_automations.worktree import run_with_worktree

console = Console()


def _is_due(config: AutomationConfig, base_dir: Path) -> bool:
    last = get_last_run(base_dir, config.name)
    if last is None:
        return True
    elapsed = (datetime.now(UTC) - last).total_seconds()
    return elapsed >= config.schedule_seconds


async def _execute_backend(
    config: AutomationConfig,
    prompt: str,
) -> BackendResult:
    """Run the backend in a fresh git worktree."""
    backend = get_backend(config.backend)

    return await run_with_worktree(
        backend=backend,
        prompt=prompt,
        cwd=config.cwd,
        timeout_seconds=config.timeout_seconds,
        model=config.model,
        reasoning_effort=config.reasoning_effort,
        skip_permissions=config.skip_permissions,
        max_turns=config.max_turns,
        copy_files=config.copy_files,
        skills_dir=config.skills_dir,
    )


async def run_automation(
    config: AutomationConfig,
    *,
    base_dir: Path,
    results_dir: Path,
) -> None:
    """Run a single automation with prompt resolution, retry, result saving, and notifications."""
    console.print(f"[bold blue]Running:[/] {config.name} (backend={config.backend})")

    # Resolve prompt templates
    last_run = get_last_run(base_dir, config.name)
    prompt = resolve_prompt(config.prompt, cwd=config.cwd, last_run=last_run)

    # Execute with retry
    result = None
    for attempt in range(1 + config.max_retries):
        result = await _execute_backend(config, prompt)
        if result.status == "ok":
            break
        if attempt < config.max_retries:
            wait = 2**attempt
            console.print(f"  [yellow]Retry {attempt + 1}/{config.max_retries} in {wait}s...[/]")
            await asyncio.sleep(wait)

    assert result is not None

    save_result(results_dir, config.name, result, backend=config.backend, model=config.model)
    update_last_run(base_dir, config.name, result.started_at)

    if result.status == "ok":
        duration = (result.ended_at - result.started_at).total_seconds()
        console.print(f"  [green]OK[/] ({duration:.1f}s)")
    else:
        console.print(f"  [red]ERROR:[/] {result.error}")

    # Notify configured channels
    for ch_config in config.channels:
        try:
            channel = get_channel(ch_config)
            await channel.notify(
                config.name, result, backend=config.backend, model=config.model
            )
            console.print(f"  [dim]Notified {ch_config.type}[/]")
        except Exception as exc:
            console.print(f"  [red]Channel {ch_config.type} failed:[/] {exc}")


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
        f"Poll interval: {poll_interval}s, concurrency: {max_concurrency}. "
        f"Press Ctrl+C to stop.\n"
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
