from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from autopilot.models import BackendResult
from autopilot.shell import run_command_async
from autopilot.skills import inject_skills


def _copy_dotfiles(source_cwd: Path, worktree_path: Path, copy_files: list[str]) -> None:
    """Copy dotfiles from source working directory into worktree."""
    for rel_path in copy_files:
        src = source_cwd / rel_path
        if not src.exists():
            continue
        dst = worktree_path / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


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
    copy_files: list[str],
    skills_dir: Path | None,
) -> BackendResult:
    """Create a temporary git worktree, set up environment, run backend, then clean up."""
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
            # Copy dotfiles from source repo
            _copy_dotfiles(cwd, wt_path, copy_files)

            # Inject skills
            if skills_dir is not None:
                inject_skills(skills_dir, wt_path)

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
            await run_command_async(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                cwd=cwd,
                timeout=30,
            )
            await run_command_async(
                ["git", "branch", "-D", branch_name],
                cwd=cwd,
                timeout=10,
            )

    return result
