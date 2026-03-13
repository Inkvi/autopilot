from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from autopilot.models import BackendResult
from autopilot.worktree import cleanup_worktree, create_worktree, run_with_worktree


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

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            result = await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
                copy_files=[],
                skills_dir=None,
            )

        assert result.status == "ok"
        fake_backend.run.assert_called_once()
        assert any("worktree" in str(c) and "add" in str(c) for c in call_log)

    async def test_copies_dotfiles(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / ".env").write_text("SECRET=abc", encoding="utf-8")
        (source_dir / ".env.local").write_text("LOCAL=xyz", encoding="utf-8")

        assertions_ok = []

        async def fake_run_cmd(args, *, cwd, timeout):
            # Simulate git worktree add creating the directory
            if "worktree" in args and "add" in args:
                for a in args:
                    if a.startswith("/") and "worktree" in a:
                        Path(a).mkdir(parents=True, exist_ok=True)
            return (0, "", "")

        async def capturing_run(prompt, *, cwd, **kwargs):
            # Assert inside the callback while worktree temp dir still exists
            assert (cwd / ".env").read_text() == "SECRET=abc"
            assert (cwd / ".env.local").read_text() == "LOCAL=xyz"
            assert not (cwd / ".envrc").exists()
            assertions_ok.append(True)
            return self._fake_result()

        fake_backend.run = capturing_run

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=source_dir,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
                copy_files=[".env", ".env.local", ".envrc"],
                skills_dir=None,
            )

        assert assertions_ok == [True]

    async def test_injects_skills(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill = skills_dir / "code-review"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: code-review\ndescription: test\n---\n")

        assertions_ok = []

        async def fake_run_cmd(args, *, cwd, timeout):
            if "worktree" in args and "add" in args:
                for a in args:
                    if a.startswith("/") and "worktree" in a:
                        Path(a).mkdir(parents=True, exist_ok=True)
            return (0, "", "")

        async def capturing_run(prompt, *, cwd, **kwargs):
            link = cwd / ".agents" / "skills" / "code-review"
            assert link.is_symlink()
            assertions_ok.append(True)
            return self._fake_result()

        fake_backend.run = capturing_run

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
                copy_files=[],
                skills_dir=skills_dir,
            )

        assert assertions_ok == [True]

    async def test_worktree_create_fails(self, tmp_path: Path):
        fake_backend = AsyncMock()

        async def fail_git(args, *, cwd, timeout):
            return (1, "", "not a git repo")

        with patch("autopilot.worktree.run_command_async", side_effect=fail_git):
            result = await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=tmp_path,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
                copy_files=[],
                skills_dir=None,
            )

        assert result.status == "error"
        assert "worktree" in result.error.lower()
        fake_backend.run.assert_not_called()

    async def test_cleanup_runs_on_backend_error(self, tmp_path: Path):
        fake_backend = AsyncMock()
        fake_backend.run.side_effect = RuntimeError("backend exploded")

        cleanup_calls: list[list[str]] = []

        async def track_git(args, *, cwd, timeout):
            if "remove" in args or "-D" in args:
                cleanup_calls.append(args)
            return (0, "", "")

        with patch("autopilot.worktree.run_command_async", side_effect=track_git):
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
                    copy_files=[],
                    skills_dir=None,
                )
            except RuntimeError:
                pass

        assert len(cleanup_calls) == 2

    async def test_copies_nested_dotfile(self, tmp_path: Path):
        """copy_files with nested paths should create parent dirs."""
        fake_backend = AsyncMock()
        fake_backend.run.return_value = self._fake_result()

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / ".secrets").mkdir()
        (source_dir / ".secrets" / "keys").write_text("key=123", encoding="utf-8")

        assertions_ok = []

        async def fake_run_cmd(args, *, cwd, timeout):
            if "worktree" in args and "add" in args:
                for a in args:
                    if a.startswith("/") and "worktree" in a:
                        Path(a).mkdir(parents=True, exist_ok=True)
            return (0, "", "")

        async def capturing_run(prompt, *, cwd, **kwargs):
            assert (cwd / ".secrets" / "keys").read_text() == "key=123"
            assertions_ok.append(True)
            return self._fake_result()

        fake_backend.run = capturing_run

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            await run_with_worktree(
                backend=fake_backend,
                prompt="scan",
                cwd=source_dir,
                timeout_seconds=60,
                model=None,
                reasoning_effort=None,
                skip_permissions=True,
                max_turns=5,
                copy_files=[".secrets/keys"],
                skills_dir=None,
            )

        assert assertions_ok == [True]


class TestCreateCleanupWorktree:
    async def test_create_returns_path(self, tmp_path: Path):
        call_log: list[list[str]] = []

        async def fake_run_cmd(args, *, cwd, timeout):
            call_log.append(args)
            if "worktree" in args and "add" in args:
                for a in args:
                    if a.startswith("/") and "worktree" in a:
                        Path(a).mkdir(parents=True, exist_ok=True)
            return (0, "", "")

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            result = await create_worktree(
                cwd=tmp_path, copy_files=[], skills_dir=None, prompt="test"
            )

        assert result is not None
        wt_path, branch = result
        assert wt_path.exists()
        assert branch is not None

    async def test_create_copies_dotfiles(self, tmp_path: Path):
        source = tmp_path / "source"
        source.mkdir()
        (source / ".env").write_text("KEY=val", encoding="utf-8")

        async def fake_run_cmd(args, *, cwd, timeout):
            if "worktree" in args and "add" in args:
                for a in args:
                    if a.startswith("/") and "worktree" in a:
                        Path(a).mkdir(parents=True, exist_ok=True)
            return (0, "", "")

        with patch("autopilot.worktree.run_command_async", side_effect=fake_run_cmd):
            result = await create_worktree(
                cwd=source, copy_files=[".env"], skills_dir=None, prompt="test"
            )
            assert result is not None
            wt_path, _ = result
            assert (wt_path / ".env").read_text() == "KEY=val"

    async def test_cleanup_removes_worktree(self, tmp_path: Path):
        cleanup_calls: list[list[str]] = []

        async def track_git(args, *, cwd, timeout):
            cleanup_calls.append(args)
            return (0, "", "")

        with patch("autopilot.worktree.run_command_async", side_effect=track_git):
            await cleanup_worktree(tmp_path, tmp_path / "wt", "test-branch")

        assert any("remove" in str(c) for c in cleanup_calls)
        assert any("-D" in c for c in cleanup_calls)

    async def test_create_failure_returns_none(self, tmp_path: Path):
        async def fail_git(args, *, cwd, timeout):
            return (1, "", "not a git repo")

        with patch("autopilot.worktree.run_command_async", side_effect=fail_git):
            result = await create_worktree(
                cwd=tmp_path, copy_files=[], skills_dir=None, prompt="test"
            )

        assert result is None
