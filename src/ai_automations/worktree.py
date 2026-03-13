from __future__ import annotations

import tempfile
from pathlib import Path

from ai_automations.models import BackendResult
from ai_automations.shell import run_command_async


async def run_with_worktree(
    *,
    backend: object,
    prompt: str,
    cwd: Path,
    timeout_seconds: int,
    model: str | None,
    reasoning_effort: str | None,
    skip_permissions: bool,
    max_turns: int,
) -> BackendResult:
    """Create a temporary git worktree, run the backend in it, then clean up."""
    with tempfile.TemporaryDirectory(prefix="autopilot-wt-") as tmpdir:
        wt_path = Path(tmpdir) / "worktree"
        branch_name = f"autopilot-wt-{hash(prompt) & 0xFFFFFF:06x}"

        # Create worktree
        code, _, stderr = await run_command_async(
            ["git", "worktree", "add", "-b", branch_name, str(wt_path)],
            cwd=cwd,
            timeout=30,
        )
        if code != 0:
            # Branch might exist, try without -b
            code, _, stderr = await run_command_async(
                ["git", "worktree", "add", str(wt_path)],
                cwd=cwd,
                timeout=30,
            )
            if code != 0:
                from datetime import UTC, datetime

                return BackendResult(
                    status="error",
                    output="",
                    error=f"Failed to create git worktree: {stderr.strip()}",
                    started_at=datetime.now(UTC),
                    ended_at=datetime.now(UTC),
                )

        try:
            result = await backend.run(  # type: ignore[union-attr]
                prompt,
                cwd=wt_path,
                timeout_seconds=timeout_seconds,
                model=model,
                reasoning_effort=reasoning_effort,
                skip_permissions=skip_permissions,
                max_turns=max_turns,
            )
        finally:
            # Clean up worktree
            await run_command_async(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                cwd=cwd,
                timeout=30,
            )
            # Try to delete the temporary branch
            await run_command_async(
                ["git", "branch", "-D", branch_name],
                cwd=cwd,
                timeout=10,
            )

    return result
