from __future__ import annotations

import re
from pathlib import Path

from autopilot.channels.base import ChannelConfig
from autopilot.models import BackendResult
from autopilot.shell import run_command_async


class GitHubPRChannel:
    def __init__(self, config: ChannelConfig) -> None:
        self._config = config

    async def notify(
        self,
        automation_name: str,
        result: BackendResult,
        *,
        backend: str,
        model: str | None,
        context: dict | None = None,
    ) -> None:
        if not context or "worktree_path" not in context:
            return

        wt_path = Path(context["worktree_path"])
        if not wt_path.exists():
            return

        # Check for uncommitted changes
        code, stdout, _ = await run_command_async(
            ["git", "status", "--porcelain"],
            cwd=wt_path,
            timeout=15,
        )
        if code != 0 or not stdout.strip():
            return  # No changes

        # Sanitize name for git ref safety
        safe_name = re.sub(r"[^a-zA-Z0-9._-]", "-", automation_name)
        branch = f"autopilot/{safe_name}"
        repo = self._config.repo
        if not repo:
            raise RuntimeError("github_pr channel requires repo")

        # Stage and commit
        await run_command_async(
            ["git", "add", "-A"],
            cwd=wt_path,
            timeout=15,
        )
        code, _, stderr = await run_command_async(
            ["git", "commit", "-m", f"autopilot: {automation_name}"],
            cwd=wt_path,
            timeout=15,
        )
        if code != 0:
            raise RuntimeError(f"git commit failed: {stderr.strip()}")

        # Check if an open PR already exists for this branch
        code, pr_stdout, pr_stderr = await run_command_async(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--head",
                branch,
                "--state",
                "open",
                "--json",
                "number",
                "-q",
                ".[0].number",
            ],
            cwd=wt_path,
            timeout=30,
        )
        if code != 0:
            raise RuntimeError(f"gh pr list failed: {pr_stderr.strip()}")
        existing_pr = pr_stdout.strip()

        # Push branch (force to update existing)
        push_args = ["git", "push", "--force", "origin", f"HEAD:{branch}"]
        code, _, stderr = await run_command_async(
            push_args,
            cwd=wt_path,
            timeout=60,
        )
        if code != 0:
            raise RuntimeError(f"git push failed: {stderr.strip()}")

        body = result.output.strip() if result.output else ""
        if len(body) > 60000:
            body = body[:60000] + "\n\n...(truncated)"

        if existing_pr:
            # Update existing PR body
            code, _, stderr = await run_command_async(
                ["gh", "pr", "edit", existing_pr, "--repo", repo, "--body", body],
                cwd=wt_path,
                timeout=30,
            )
            if code != 0:
                raise RuntimeError(f"gh pr edit failed: {stderr.strip()}")
        else:
            # Create new PR
            pr_args = [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--head",
                branch,
                "--title",
                f"[autopilot] {automation_name}",
                "--body",
                body,
            ]
            if self._config.draft:
                pr_args.append("--draft")
            if self._config.labels:
                for label in self._config.labels:
                    pr_args.extend(["--label", label])

            code, _, stderr = await run_command_async(
                pr_args,
                cwd=wt_path,
                timeout=30,
            )
            if code != 0:
                raise RuntimeError(f"gh pr create failed: {stderr.strip()}")
