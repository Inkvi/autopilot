from __future__ import annotations

import asyncio
import signal
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from autopilot.backends import get_backend
from autopilot.channels import get_channel
from autopilot.conditions import check_condition
from autopilot.config import AutomationConfig, discover_automations
from autopilot.costs import parse_costs
from autopilot.models import BackendResult
from autopilot.prompts import resolve_prompt
from autopilot.repos import clone_or_update_repos, fetch_remote_skills, resolve_working_directory
from autopilot.results import save_result
from autopilot.skills import inject_skill_paths
from autopilot.state import get_last_run, update_last_run
from autopilot.worktree import cleanup_worktree, create_worktree

console = Console()


def _is_due(config: AutomationConfig, base_dir: Path) -> bool:
    from autopilot.config import is_cron_schedule

    last = get_last_run(base_dir, config.name)
    if last is None:
        return True

    if is_cron_schedule(config.schedule):
        from croniter import croniter

        # Check if a cron fire time has passed since the last run
        cron = croniter(config.schedule, last)
        next_fire = cron.get_next(datetime)
        return datetime.now(UTC) >= next_fire

    elapsed = (datetime.now(UTC) - last).total_seconds()
    return elapsed >= config.schedule_seconds


async def run_automation(
    config: AutomationConfig,
    *,
    base_dir: Path,
    results_dir: Path,
    stream: bool = False,
    update_state: bool = True,
    on_log_path: Callable[[Path], None] | None = None,
) -> None:
    """Run a single automation with prompt resolution, retry, result saving, and notifications."""
    console.print(f"[bold blue]Running:[/] {config.name} (backend={config.backend})")

    # Clone/update repos if configured
    cloned_repos: dict[str, Path] = {}
    if config.repos:
        cloned_repos = await clone_or_update_repos(config.repos, base_dir)

    # Resolve working directory (may reference a cloned repo by name)
    resolved_cwd = resolve_working_directory(config.working_directory, cloned_repos)

    # Resolve prompt templates
    last_run = get_last_run(base_dir, config.name)
    prompt = resolve_prompt(config.prompt, cwd=resolved_cwd, last_run=last_run)

    # Check run condition (skipped for on-demand/manual triggers)
    if update_state and config.run_if is not None:
        condition_cwd = str(resolved_cwd) if resolved_cwd else "."
        condition_met = await check_condition(config.run_if, condition_cwd, last_run)
        if not condition_met:
            console.print("  [dim]Skipped (condition not met)[/]")
            return

    # Fetch remote skills if configured
    remote_skill_paths: list[Path] = []
    if config.skills:
        try:
            remote_skill_paths = await fetch_remote_skills(config.skills, base_dir)
        except Exception as exc:
            result = BackendResult(
                status="error",
                output="",
                error=f"Failed to fetch remote skills: {exc}",
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
            )
            save_result(
                results_dir, config.name, result, backend=config.backend, model=config.model
            )
            console.print(f"  [red]ERROR:[/] Failed to fetch remote skills: {exc}")
            return

    # Determine execution directory: worktree if working_directory resolves, else temp dir
    use_worktree = resolved_cwd is not None
    wt_path = None
    branch_name = None
    tmp_dir = None

    if use_worktree:
        wt_result = await create_worktree(
            cwd=resolved_cwd,
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
            save_result(
                results_dir, config.name, result, backend=config.backend, model=config.model
            )
            console.print("  [red]ERROR:[/] Failed to create git worktree")
            return
        wt_path, branch_name = wt_result
        run_cwd = wt_path
        if remote_skill_paths:
            inject_skill_paths(remote_skill_paths, wt_path)
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="autopilot-run-"))
        run_cwd = tmp_dir
        if remote_skill_paths:
            inject_skill_paths(remote_skill_paths, run_cwd)

    try:
        backend = get_backend(config.backend)

        # Set up log file for streaming
        log_dir = results_dir / config.name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
        log_path = log_dir / f"{log_ts}.log"
        if on_log_path is not None:
            on_log_path(log_path)

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
                cwd=run_cwd,
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

        # Rename log file to match result timestamp (may differ after retries)
        result_ts = result.started_at.strftime("%Y-%m-%dT%H%M%SZ")
        final_log_path = log_dir / f"{result_ts}.log"
        if log_path != final_log_path and log_path.exists():
            log_path.rename(final_log_path)

        usage = result.usage or parse_costs(config.backend, result.output)
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
            if update_state:
                update_last_run(base_dir, config.name, result.started_at)
            duration = (result.ended_at - result.started_at).total_seconds()
            console.print(f"  [green]OK[/] ({duration:.1f}s)")
        else:
            console.print(f"  [red]ERROR:[/] {result.error}")

        # Notify configured channels
        context = {"worktree_path": str(run_cwd)}
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
        if use_worktree and wt_path is not None and resolved_cwd is not None:
            await cleanup_worktree(resolved_cwd, wt_path, branch_name)
        elif tmp_dir is not None:
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


class Scheduler:
    """Encapsulates daemon state: concurrency, running set, on-demand queue."""

    def __init__(
        self,
        automations_dir: Path,
        base_dir: Path,
        results_dir: Path,
        max_concurrency: int = 5,
    ) -> None:
        self.automations_dir = automations_dir
        self.base_dir = base_dir
        self.results_dir = results_dir
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.running: dict[str, Path | None] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.started_at = time.monotonic()
        self.automations_count = 0
        self.stop_event = asyncio.Event()

    def is_running(self, name: str) -> bool:
        return name in self.running

    def get_log_path(self, name: str) -> Path | None:
        return self.running.get(name)

    async def trigger_run(self, name: str) -> None:
        """Trigger an on-demand run immediately. Raises ValueError if already running."""
        if self.is_running(name):
            raise ValueError(f"{name} is already running")
        configs = discover_automations(self.automations_dir)
        config = next((c for c in configs if c.name == name), None)
        if config is None:
            raise ValueError(f"Automation '{name}' not found")
        task = asyncio.create_task(self._run_with_tracking(config, update_state=False))
        self._track_task(name, task)

    async def stop_run(self, name: str) -> None:
        """Stop a running automation. Raises ValueError if not running."""
        task = self._tasks.get(name)
        if task is None:
            raise ValueError(f"{name} is not running")
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _run_with_tracking(
        self, config: AutomationConfig, *, update_state: bool = True
    ) -> None:
        """Run an automation with semaphore and running-set tracking."""
        started = datetime.now(UTC)
        async with self.semaphore:
            self.running[config.name] = None
            try:

                def _on_log_path(path: Path) -> None:
                    self.running[config.name] = path

                await run_automation(
                    config,
                    base_dir=self.base_dir,
                    results_dir=self.results_dir,
                    update_state=update_state,
                    on_log_path=_on_log_path,
                )
            except asyncio.CancelledError:
                console.print(f"[yellow]Stopped:[/] {config.name}")
                result = BackendResult(
                    status="stopped",
                    output="",
                    error="Automation was stopped by user",
                    started_at=started,
                    ended_at=datetime.now(UTC),
                )
                save_result(
                    self.results_dir,
                    config.name,
                    result,
                    backend=config.backend,
                    model=config.model,
                )
            except Exception as exc:
                console.print(f"[red]Unhandled error running {config.name}:[/] {exc}")
            finally:
                self.running.pop(config.name, None)

    def _track_task(self, name: str, task: asyncio.Task) -> None:
        """Register a task for cancellation support."""
        self._tasks[name] = task
        task.add_done_callback(lambda _: self._tasks.pop(name, None))

    async def _drain_queue(self) -> None:
        """Process all queued on-demand runs."""
        while not self.queue.empty():
            try:
                name = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            configs = discover_automations(self.automations_dir)
            config = next((c for c in configs if c.name == name), None)
            if config is None:
                console.print(f"[red]Triggered automation not found:[/] {name}")
                continue
            task = asyncio.create_task(self._run_with_tracking(config, update_state=False))
            self._track_task(name, task)


async def daemon_loop(
    automations_dir: Path,
    *,
    base_dir: Path,
    results_dir: Path,
    poll_interval: int = 60,
    max_concurrency: int = 5,
    scheduler: Scheduler | None = None,
) -> None:
    """Run the scheduler daemon. Checks for due automations every poll_interval seconds."""
    if scheduler is None:
        scheduler = Scheduler(
            automations_dir=automations_dir,
            base_dir=base_dir,
            results_dir=results_dir,
            max_concurrency=max_concurrency,
        )

    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        console.print("\n[yellow]Shutting down...[/]")
        scheduler.stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    console.print(f"[bold]Daemon started.[/] Watching {automations_dir}")
    console.print(
        f"Poll interval: {poll_interval}s, concurrency: {max_concurrency}. Press Ctrl+C to stop.\n"
    )

    while not scheduler.stop_event.is_set():
        try:
            configs = discover_automations(automations_dir)
            scheduler.automations_count = len(configs)
        except Exception as exc:
            console.print(f"[red]Error loading configs:[/] {exc}")
            await asyncio.sleep(poll_interval)
            continue

        await scheduler._drain_queue()

        due = [c for c in configs if _is_due(c, base_dir)]
        if due:
            tasks = []
            for c in due:
                t = asyncio.create_task(scheduler._run_with_tracking(c))
                scheduler._track_task(c.name, t)
                tasks.append(t)
            await asyncio.gather(*tasks)

        try:
            await asyncio.wait_for(scheduler.stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            pass

    console.print("[bold]Daemon stopped.[/]")
