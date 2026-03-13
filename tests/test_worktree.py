from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ai_automations.models import BackendResult
from ai_automations.worktree import run_with_worktree


class TestRunWithWorktree:
    def _fake_result(self) -> BackendResult:
        t = datetime(2026, 1, 1, tzinfo=UTC)
        return BackendResult(status="ok", output="done", error=None, started_at=t, ended_at=t)

    async def test_success_flow(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        call_log: list[list[str]] = []

        async def fake_run_cmd(args, *, cwd, timeout):
            call_log.append(args)
            return (0, "", "")

        with patch("ai_automations.worktree.run_command_async", side_effect=fake_run_cmd):
            result = await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
            )

        assert result.status == "ok"
        fake_backend.run.assert_called_once()

        # Should have: worktree add, worktree remove, branch delete
        assert any("worktree" in str(c) and "add" in str(c) for c in call_log)
        assert any("worktree" in str(c) and "remove" in str(c) for c in call_log)
        assert any("branch" in str(c) and "-D" in str(c) for c in call_log)

    async def test_worktree_create_fails(self, tmp_path: Path):
        fake_backend = AsyncMock()

        async def fail_git(args, *, cwd, timeout):
            return (1, "", "not a git repo")

        with patch("ai_automations.worktree.run_command_async", side_effect=fail_git):
            result = await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
            )

        assert result.status == "error"
        assert "worktree" in result.error.lower()
        fake_backend.run.assert_not_called()

    async def test_fallback_without_branch_flag(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        call_count = 0

        async def branching_logic(args, *, cwd, timeout):
            nonlocal call_count
            call_count += 1
            # First call (with -b) fails, second (without -b) succeeds
            if "-b" in args:
                return (1, "", "branch exists")
            return (0, "", "")

        with patch("ai_automations.worktree.run_command_async", side_effect=branching_logic):
            result = await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
            )

        assert result.status == "ok"

    async def test_cleanup_runs_on_backend_error(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.side_effect = RuntimeError("backend exploded")

        cleanup_calls: list[list[str]] = []

        async def track_git(args, *, cwd, timeout):
            if "remove" in args or "-D" in args:
                cleanup_calls.append(args)
            return (0, "", "")

        with patch("ai_automations.worktree.run_command_async", side_effect=track_git):
            try:
                await run_with_worktree(
                    backend=fake_backend,
                    prompt="scan",
                    cwd=tmp_path,
                    timeout_seconds=60,
                    model=None,
                    reasoning_effort=None,
                    skip_permissions=True,
                    max_turns=5,
                )
            except RuntimeError:
                pass

        # Cleanup should still have run
        assert len(cleanup_calls) == 2
