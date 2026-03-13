from __future__ import annotations

from datetime import datetime
from pathlib import Path

from autopilot.config import (
    CommandCondition,
    FileChangesCondition,
    GitChangesCondition,
)
from autopilot.shell import run_command_async


async def check_condition(
    run_if: GitChangesCondition | FileChangesCondition | CommandCondition,
    working_directory: str,
    last_run: datetime | None,
) -> bool:
    """Check whether an automation's run condition is met."""
    cwd = Path(working_directory).expanduser().resolve()

    if isinstance(run_if, GitChangesCondition):
        return await _check_git_changes(cwd, last_run)
    elif isinstance(run_if, FileChangesCondition):
        return await _check_file_changes(cwd, last_run, run_if.paths)
    elif isinstance(run_if, CommandCondition):
        return await _check_command(cwd, run_if.cmd)
    return True


async def _check_git_changes(cwd: Path, last_run: datetime | None) -> bool:
    if last_run is None:
        return True
    try:
        code, stdout, _ = await run_command_async(
            ["git", "log", "--oneline", f"--since={last_run.isoformat()}"],
            cwd=cwd,
            timeout=30,
        )
        return code == 0 and bool(stdout.strip())
    except TimeoutError:
        return False


async def _check_file_changes(cwd: Path, last_run: datetime | None, paths: list[str]) -> bool:
    if last_run is None:
        return True
    try:
        code, stdout, _ = await run_command_async(
            ["git", "log", "--name-only", "--pretty=format:", f"--since={last_run.isoformat()}"],
            cwd=cwd,
            timeout=30,
        )
    except TimeoutError:
        return False
    if code != 0 or not stdout.strip():
        return False
    changed_files = [f for f in stdout.strip().splitlines() if f.strip()]
    return any(f.startswith(p) for f in changed_files for p in paths)


async def _check_command(cwd: Path, cmd: str) -> bool:
    try:
        code, _, _ = await run_command_async(
            ["sh", "-c", cmd],
            cwd=cwd,
            timeout=30,
        )
        return code == 0
    except TimeoutError:
        return False
