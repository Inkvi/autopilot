from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from rich.console import Console

from autopilot.config import AutomationConfig
from autopilot.simulate import simulate_pipeline


def _make_config(tmp_path: Path, **overrides) -> AutomationConfig:
    """Build an AutomationConfig with sensible defaults for testing."""
    defaults = {
        "name": "test-auto",
        "prompt": "Do something on {{date}}",
        "schedule": "1h",
        "backend": "claude_cli",
    }
    return AutomationConfig(**(defaults | overrides))


def _capture_console() -> tuple[Console, StringIO]:
    buf = StringIO()
    return Console(file=buf, force_terminal=False, width=200, no_color=True), buf


class TestSimulateConditions:
    async def test_no_condition_configured(self, tmp_path: Path):
        config = _make_config(tmp_path)
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_conditions=True,
            console=con,
        )
        output = buf.getvalue()
        assert "No run_if condition" in output
        assert "would always run" in output

    async def test_git_changes_pass(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "git_changes"})
        con, buf = _capture_console()
        with patch("autopilot.simulate.check_condition", new_callable=AsyncMock, return_value=True):
            await simulate_pipeline(
                config,
                base_dir=tmp_path,
                simulate_conditions=True,
                console=con,
            )
        output = buf.getvalue()
        assert "PASS" in output
        assert "git_changes" in output

    async def test_git_changes_skip(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "git_changes"})
        con, buf = _capture_console()
        with patch(
            "autopilot.simulate.check_condition", new_callable=AsyncMock, return_value=False
        ):
            await simulate_pipeline(
                config,
                base_dir=tmp_path,
                simulate_conditions=True,
                console=con,
            )
        output = buf.getvalue()
        assert "SKIP" in output

    async def test_command_condition(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "command", "cmd": "true"})
        con, buf = _capture_console()
        with patch("autopilot.simulate.check_condition", new_callable=AsyncMock, return_value=True):
            await simulate_pipeline(
                config,
                base_dir=tmp_path,
                simulate_conditions=True,
                console=con,
            )
        output = buf.getvalue()
        assert "command" in output
        assert "PASS" in output

    async def test_file_changes_condition(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "file_changes", "paths": ["src/"]})
        con, buf = _capture_console()
        with patch(
            "autopilot.simulate.check_condition", new_callable=AsyncMock, return_value=False
        ):
            await simulate_pipeline(
                config,
                base_dir=tmp_path,
                simulate_conditions=True,
                console=con,
            )
        output = buf.getvalue()
        assert "file_changes" in output
        assert "src/" in output
        assert "SKIP" in output

    async def test_condition_error(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "git_changes"})
        con, buf = _capture_console()
        with patch(
            "autopilot.simulate.check_condition",
            new_callable=AsyncMock,
            side_effect=RuntimeError("git not found"),
        ):
            await simulate_pipeline(
                config,
                base_dir=tmp_path,
                simulate_conditions=True,
                console=con,
            )
        output = buf.getvalue()
        assert "ERROR" in output
        assert "git not found" in output

    async def test_conditions_skipped_when_flag_off(self, tmp_path: Path):
        config = _make_config(tmp_path, run_if={"type": "git_changes"})
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_conditions=False,
            console=con,
        )
        output = buf.getvalue()
        assert "use --simulate-conditions" in output


class TestSimulateChannels:
    async def test_no_channels(self, tmp_path: Path):
        config = _make_config(tmp_path)
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=True,
            console=con,
        )
        output = buf.getvalue()
        assert "No channels configured" in output

    async def test_slack_channel(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("TEST_SLACK_URL", "https://hooks.slack.com/test")
        config = AutomationConfig(
            name="test-auto",
            prompt="do things",
            schedule="1h",
            backend="claude_cli",
            channels=[{"type": "slack", "webhook_url_env": "TEST_SLACK_URL"}],
        )
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=True,
            console=con,
        )
        output = buf.getvalue()
        assert "Slack webhook" in output
        assert "Webhook URL: configured" in output
        assert "test-auto" in output

    async def test_slack_missing_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MISSING_WEBHOOK", raising=False)
        config = AutomationConfig(
            name="test-auto",
            prompt="do things",
            schedule="1h",
            backend="claude_cli",
            channels=[{"type": "slack", "webhook_url_env": "MISSING_WEBHOOK"}],
        )
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=True,
            console=con,
        )
        output = buf.getvalue()
        assert "MISSING_WEBHOOK" in output
        assert "Warning" in output

    async def test_github_issue_channel(self, tmp_path: Path):
        config = AutomationConfig(
            name="test-auto",
            prompt="do things",
            schedule="1h",
            backend="claude_cli",
            channels=[{"type": "github_issue", "repo": "org/repo", "labels": ["bug"]}],
        )
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=True,
            console=con,
        )
        output = buf.getvalue()
        assert "GitHub issue" in output
        assert "org/repo" in output
        assert "[autopilot] test-auto: ok" in output
        assert "bug" in output

    async def test_github_pr_channel(self, tmp_path: Path):
        config = AutomationConfig(
            name="test-auto",
            prompt="do things",
            schedule="1h",
            backend="claude_cli",
            channels=[{"type": "github_pr", "repo": "org/repo", "draft": True}],
        )
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=True,
            console=con,
        )
        output = buf.getvalue()
        assert "GitHub PR" in output
        assert "autopilot/test-auto" in output
        assert "Draft: yes" in output

    async def test_channels_skipped_when_flag_off(self, tmp_path: Path):
        config = AutomationConfig(
            name="test-auto",
            prompt="do things",
            schedule="1h",
            backend="claude_cli",
            channels=[{"type": "github_issue", "repo": "org/repo"}],
        )
        con, buf = _capture_console()
        await simulate_pipeline(
            config,
            base_dir=tmp_path,
            simulate_channels=False,
            console=con,
        )
        output = buf.getvalue()
        assert "use --simulate-channels" in output


class TestSimulateWorktree:
    async def test_with_git_repo(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        config = _make_config(tmp_path, working_directory=str(repo))
        con, buf = _capture_console()
        with patch("autopilot.simulate._is_git_repo", new_callable=AsyncMock, return_value=True):
            await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "Would create git worktree" in output

    async def test_without_git(self, tmp_path: Path):
        repo = tmp_path / "notgit"
        repo.mkdir()
        config = _make_config(tmp_path, working_directory=str(repo))
        con, buf = _capture_console()
        with patch("autopilot.simulate._is_git_repo", new_callable=AsyncMock, return_value=False):
            await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "not inside a git repo" in output

    async def test_no_working_dir(self, tmp_path: Path):
        config = _make_config(tmp_path, working_directory=None)
        con, buf = _capture_console()
        await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "temporary directory" in output

    async def test_copy_files_listed(self, tmp_path: Path):
        repo = tmp_path / "myrepo"
        repo.mkdir()
        (repo / ".env").write_text("SECRET=x")
        config = _make_config(tmp_path, working_directory=str(repo))
        con, buf = _capture_console()
        with patch("autopilot.simulate._is_git_repo", new_callable=AsyncMock, return_value=True):
            await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "Would copy: .env" in output
        assert ".env.local" in output  # listed as not found


class TestSimulateGeneral:
    async def test_header_and_config(self, tmp_path: Path):
        config = _make_config(tmp_path, model="sonnet-4", timeout_seconds=300, max_retries=2)
        con, buf = _capture_console()
        await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "Simulation: test-auto" in output
        assert "sonnet-4" in output
        assert "300s" in output
        assert "2" in output

    async def test_prompt_resolved(self, tmp_path: Path):
        config = _make_config(tmp_path, prompt="Run on {{date}}")
        con, buf = _capture_console()
        await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        # Template should be resolved, not raw
        assert "{{date}}" not in output
        assert "Prompt" in output

    async def test_repos_listed(self, tmp_path: Path):
        config = _make_config(
            tmp_path, repos=["https://github.com/org/repo1", "https://github.com/org/repo2"]
        )
        con, buf = _capture_console()
        await simulate_pipeline(config, base_dir=tmp_path, console=con)
        output = buf.getvalue()
        assert "Would clone/update" in output
        assert "repo1" in output
        assert "repo2" in output

    async def test_backend_never_called(self, tmp_path: Path):
        config = _make_config(tmp_path)
        con, buf = _capture_console()
        with patch("autopilot.backends.get_backend") as mock_backend:
            await simulate_pipeline(config, base_dir=tmp_path, console=con)
            mock_backend.assert_not_called()
