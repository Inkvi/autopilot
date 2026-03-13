from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from ai_automations.backends import get_backend
from ai_automations.config import AutomationConfig, discover_automations
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


async def run_automation(
    config: AutomationConfig,
    *,
    base_dir: Path,
    results_dir: Path,
) -> None:
    """Run a single automation and save its result."""
    console.print(f"[bold blue]Running:[/] {config.name} (backend={config.backend})")

    backend = get_backend(config.backend)
    cwd = config.cwd

    if config.use_worktree:
        result = await run_with_worktree(
            backend=backend,
            prompt=config.prompt,
            cwd=cwd,
            timeout_seconds=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            skip_permissions=config.skip_permissions,
            max_turns=config.max_turns,
        )
    else:
        result = await backend.run(
            config.prompt,
            cwd=cwd,
            timeout_seconds=config.timeout_seconds,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            skip_permissions=config.skip_permissions,
            max_turns=config.max_turns,
        )

    save_result(results_dir, config.name, result, backend=config.backend, model=config.model)
    update_last_run(base_dir, config.name, result.started_at)

    if result.status == "ok":
        duration = (result.ended_at - result.started_at).total_seconds()
        console.print(f"  [green]OK[/] ({duration:.1f}s)")
    else:
        console.print(f"  [red]ERROR:[/] {result.error}")


async def daemon_loop(
    automations_dir: Path,
    *,
    base_dir: Path,
    results_dir: Path,
    poll_interval: int = 60,
) -> None:
    """Run the scheduler daemon. Checks for due automations every poll_interval seconds."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        console.print("\n[yellow]Shutting down...[/]")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    console.print(f"[bold]Daemon started.[/] Watching {automations_dir}")
    console.print(f"Poll interval: {poll_interval}s. Press Ctrl+C to stop.\n")

    while not stop_event.is_set():
        try:
            configs = discover_automations(automations_dir)
        except Exception as exc:
            console.print(f"[red]Error loading configs:[/] {exc}")
            await asyncio.sleep(poll_interval)
            continue

        for config in configs:
            if stop_event.is_set():
                break
            if _is_due(config, base_dir):
                try:
                    await run_automation(config, base_dir=base_dir, results_dir=results_dir)
                except Exception as exc:
                    console.print(f"[red]Unhandled error running {config.name}:[/] {exc}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            pass

    console.print("[bold]Daemon stopped.[/]")
