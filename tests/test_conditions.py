from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from autopilot.conditions import check_condition
from autopilot.config import CommandCondition, FileChangesCondition, GitChangesCondition


class TestGitChanges:
    async def test_returns_true_when_commits_exist(self, tmp_path):
        cond = GitChangesCondition(type="git_changes")
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "abc123 some commit\ndef456 another\n", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is True

    async def test_returns_false_when_no_commits(self, tmp_path):
        cond = GitChangesCondition(type="git_changes")
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False

    async def test_returns_true_on_first_run(self, tmp_path):
        cond = GitChangesCondition(type="git_changes")
        result = await check_condition(cond, str(tmp_path), None)
        assert result is True

    async def test_returns_true_on_git_error(self, tmp_path):
        """Non-zero git exit (e.g. not a repo) should run to be safe."""
        cond = GitChangesCondition(type="git_changes")
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (128, "", "fatal: not a git repository")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is True

    async def test_returns_false_on_timeout(self, tmp_path):
        cond = GitChangesCondition(type="git_changes")
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = TimeoutError()
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False


class TestFileChanges:
    async def test_returns_true_when_matching_files_changed(self, tmp_path):
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "src/main.py\ntests/test_main.py\n", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is True

    async def test_returns_false_when_no_matching_files(self, tmp_path):
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "docs/readme.md\n", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False

    async def test_returns_false_when_no_changes_at_all(self, tmp_path):
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False

    async def test_returns_true_on_first_run(self, tmp_path):
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        result = await check_condition(cond, str(tmp_path), None)
        assert result is True

    async def test_prefix_boundary_no_false_positive(self, tmp_path):
        """paths=["src"] should NOT match "src2/foo.py"."""
        cond = FileChangesCondition(type="file_changes", paths=["src"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "src2/foo.py\n", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False

    async def test_exact_file_match(self, tmp_path):
        """paths=["Makefile"] should match exactly "Makefile"."""
        cond = FileChangesCondition(type="file_changes", paths=["Makefile"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "Makefile\n", "")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is True

    async def test_returns_true_on_git_error(self, tmp_path):
        """Non-zero git exit should run to be safe."""
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (128, "", "fatal: not a git repository")
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is True

    async def test_returns_false_on_timeout(self, tmp_path):
        cond = FileChangesCondition(type="file_changes", paths=["src/"])
        last_run = datetime.now(UTC) - timedelta(hours=1)

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = TimeoutError()
            result = await check_condition(cond, str(tmp_path), last_run)

        assert result is False


class TestCommand:
    async def test_returns_true_on_exit_zero(self, tmp_path):
        cond = CommandCondition(type="command", cmd="test -f flag.txt")

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            result = await check_condition(cond, str(tmp_path), None)

        assert result is True

    async def test_returns_false_on_nonzero_exit(self, tmp_path):
        cond = CommandCondition(type="command", cmd="test -f flag.txt")

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (1, "", "")
            result = await check_condition(cond, str(tmp_path), None)

        assert result is False

    async def test_returns_false_on_timeout(self, tmp_path):
        cond = CommandCondition(type="command", cmd="sleep 999")

        with patch("autopilot.conditions.run_command_async", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = TimeoutError()
            result = await check_condition(cond, str(tmp_path), None)

        assert result is False
