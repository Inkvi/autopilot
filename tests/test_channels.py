from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from autopilot.channels import get_channel
from autopilot.channels.base import ChannelConfig
from autopilot.channels.github_issue import GitHubIssueChannel
from autopilot.channels.github_pr import GitHubPRChannel
from autopilot.channels.slack import SlackWebhookChannel, _format_message
from autopilot.models import BackendResult

# --- ChannelConfig ---


class TestChannelConfig:
    def test_slack_with_url(self):
        cfg = ChannelConfig(type="slack", webhook_url="https://hooks.slack.com/x")
        assert cfg.resolve_webhook_url() == "https://hooks.slack.com/x"

    def test_slack_with_env(self, monkeypatch):
        monkeypatch.setenv("TEST_HOOK", "https://hooks.slack.com/env")
        cfg = ChannelConfig(type="slack", webhook_url_env="TEST_HOOK")
        assert cfg.resolve_webhook_url() == "https://hooks.slack.com/env"

    def test_slack_env_not_set(self):
        cfg = ChannelConfig(type="slack", webhook_url_env="NONEXISTENT_VAR_12345")
        with pytest.raises(RuntimeError, match="not set"):
            cfg.resolve_webhook_url()

    def test_slack_requires_url_or_env(self):
        with pytest.raises(ValidationError, match="webhook_url"):
            ChannelConfig(type="slack")

    def test_url_preferred_over_env(self, monkeypatch):
        monkeypatch.setenv("TEST_HOOK", "https://env-url")
        cfg = ChannelConfig(
            type="slack", webhook_url="https://direct-url", webhook_url_env="TEST_HOOK"
        )
        assert cfg.resolve_webhook_url() == "https://direct-url"

    def test_no_url_no_env_resolve_raises(self):
        # Use a non-slack type to bypass the validator
        cfg = ChannelConfig(type="other")
        with pytest.raises(RuntimeError, match="No webhook URL"):
            cfg.resolve_webhook_url()


# --- GitHub ChannelConfig ---


class TestGitHubChannelConfig:
    def test_github_issue_requires_repo(self):
        with pytest.raises(ValidationError, match="repo"):
            ChannelConfig(type="github_issue")

    def test_github_issue_valid(self):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        assert cfg.repo == "owner/repo"

    def test_github_issue_with_labels(self):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo", labels=["autopilot", "bug"])
        assert cfg.labels == ["autopilot", "bug"]

    def test_github_pr_requires_repo(self):
        with pytest.raises(ValidationError, match="repo"):
            ChannelConfig(type="github_pr")

    def test_github_pr_valid(self):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        assert cfg.repo == "owner/repo"
        assert cfg.draft is False

    def test_github_pr_draft(self):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo", draft=True)
        assert cfg.draft is True


# --- get_channel factory ---


class TestGetChannel:
    def test_slack(self):
        cfg = ChannelConfig(type="slack", webhook_url="https://example.com")
        ch = get_channel(cfg)
        assert isinstance(ch, SlackWebhookChannel)

    def test_unknown_raises(self):
        cfg = ChannelConfig(type="unknown_type")
        with pytest.raises(ValueError, match="Unknown channel type"):
            get_channel(cfg)


# --- _format_message ---


class TestFormatMessage:
    def test_ok_message(self, ok_result: BackendResult):
        payload = _format_message("scan", ok_result, backend="claude_cli", model="sonnet")
        assert ":white_check_mark:" in payload["text"]
        assert "scan" in payload["text"]
        assert "blocks" in payload
        # Check context block has backend info
        context_block = payload["blocks"][1]
        assert "claude_cli" in context_block["elements"][0]["text"]
        assert "sonnet" in context_block["elements"][0]["text"]

    def test_ok_includes_snippet(self, ok_result: BackendResult):
        payload = _format_message("scan", ok_result, backend="claude_cli", model=None)
        # Output should appear in a code block
        assert any("All clear." in str(b) for b in payload["blocks"])

    def test_ok_truncates_long_output(self, ok_result: BackendResult):
        ok_result.output = "x" * 600
        payload = _format_message("scan", ok_result, backend="claude_cli", model=None)
        snippet_block = payload["blocks"][-1]
        text = snippet_block["text"]["text"]
        assert "..." in text

    def test_error_message(self, error_result: BackendResult):
        payload = _format_message("scan", error_result, backend="codex_cli", model=None)
        assert ":x:" in payload["text"]
        assert "failed" in payload["text"]
        # Error block
        assert any("CLI timed out" in str(b) for b in payload["blocks"])

    def test_error_truncates_long_error(self, error_result: BackendResult):
        error_result.error = "E" * 600
        payload = _format_message("scan", error_result, backend="codex_cli", model=None)
        error_block = payload["blocks"][-1]
        text = error_block["text"]["text"]
        assert "..." in text

    def test_default_model_string(self, ok_result: BackendResult):
        payload = _format_message("scan", ok_result, backend="claude_cli", model=None)
        context = payload["blocks"][1]["elements"][0]["text"]
        assert "default" in context


# --- SlackWebhookChannel.notify ---


class TestSlackWebhookChannelNotify:
    async def test_posts_to_webhook(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="slack", webhook_url="https://hooks.slack.com/test")
        channel = SlackWebhookChannel(cfg)

        with patch("autopilot.channels.slack._post_webhook") as mock_post:
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/test"
        payload = call_args[0][1]
        assert "blocks" in payload

    async def test_resolves_env_url(self, ok_result: BackendResult, monkeypatch):
        monkeypatch.setenv("HOOK_URL", "https://hooks.slack.com/from-env")
        cfg = ChannelConfig(type="slack", webhook_url_env="HOOK_URL")
        channel = SlackWebhookChannel(cfg)

        with patch("autopilot.channels.slack._post_webhook") as mock_post:
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        assert mock_post.call_args[0][0] == "https://hooks.slack.com/from-env"


class TestGitHubIssueChannel:
    async def test_creates_issue(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        channel = GitHubIssueChannel(cfg)

        with patch(
            "autopilot.channels.github_issue.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            mock_cmd.return_value = (0, "https://github.com/owner/repo/issues/1\n", "")
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        mock_cmd.assert_called_once()
        args = mock_cmd.call_args.kwargs.get("args") or mock_cmd.call_args[0][0]
        assert "gh" in args
        assert "issue" in args
        assert "create" in args

    async def test_issue_title_format(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        channel = GitHubIssueChannel(cfg)

        with patch(
            "autopilot.channels.github_issue.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        args = mock_cmd.call_args[0][0]
        title_idx = args.index("--title") + 1
        assert "[autopilot]" in args[title_idx]
        assert "scan" in args[title_idx]

    async def test_issue_with_labels(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo", labels=["autopilot", "bug"])
        channel = GitHubIssueChannel(cfg)

        with patch(
            "autopilot.channels.github_issue.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        args = mock_cmd.call_args[0][0]
        assert "--label" in args

    async def test_error_result(self, error_result: BackendResult):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        channel = GitHubIssueChannel(cfg)

        with patch(
            "autopilot.channels.github_issue.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            await channel.notify("scan", error_result, backend="claude_cli", model=None)

        args = mock_cmd.call_args[0][0]
        title_idx = args.index("--title") + 1
        assert "error" in args[title_idx].lower()

    async def test_truncates_long_body(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        channel = GitHubIssueChannel(cfg)
        ok_result.output = "x" * 70000

        with patch(
            "autopilot.channels.github_issue.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        args = mock_cmd.call_args[0][0]
        body_idx = args.index("--body") + 1
        assert len(args[body_idx]) < 65000
        assert "truncated" in args[body_idx]


class TestGetChannelGitHub:
    def test_github_issue(self):
        cfg = ChannelConfig(type="github_issue", repo="owner/repo")
        ch = get_channel(cfg)
        assert isinstance(ch, GitHubIssueChannel)


class TestGitHubPRChannel:
    async def test_skips_when_no_changes(self, ok_result: BackendResult, tmp_path: Path):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        channel = GitHubPRChannel(cfg)

        wt = tmp_path / "worktree"
        wt.mkdir()
        context = {"worktree_path": str(wt)}

        with patch(
            "autopilot.channels.github_pr.run_command_async", new_callable=AsyncMock
        ) as mock_cmd:
            # git status --porcelain returns empty (no changes)
            mock_cmd.return_value = (0, "", "")
            await channel.notify(
                "scan", ok_result, backend="claude_cli", model=None, context=context
            )

        # Only git status was called, no commit/push/PR
        assert mock_cmd.call_count == 1

    async def test_creates_pr_with_changes(self, ok_result: BackendResult, tmp_path: Path):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        channel = GitHubPRChannel(cfg)

        wt = tmp_path / "worktree"
        wt.mkdir()
        context = {"worktree_path": str(wt)}

        call_log: list[list[str]] = []

        async def fake_cmd(args, *, cwd=None, timeout=None):
            call_log.append(args)
            if "status" in args and "--porcelain" in args:
                return (0, " M src/main.py\n", "")
            if "pr" in args and "list" in args:
                return (0, "", "")  # no existing PR
            return (0, "", "")

        with patch("autopilot.channels.github_pr.run_command_async", side_effect=fake_cmd):
            await channel.notify(
                "scan", ok_result, backend="claude_cli", model=None, context=context
            )

        # Should have: status, add, commit, push, pr list, pr create
        assert any("commit" in str(c) for c in call_log)
        assert any("push" in str(c) for c in call_log)
        assert any("pr" in str(c) and "create" in str(c) for c in call_log)

    async def test_updates_existing_pr(self, ok_result: BackendResult, tmp_path: Path):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        channel = GitHubPRChannel(cfg)

        wt = tmp_path / "worktree"
        wt.mkdir()
        context = {"worktree_path": str(wt)}

        call_log: list[list[str]] = []

        async def fake_cmd(args, *, cwd=None, timeout=None):
            call_log.append(args)
            if "status" in args and "--porcelain" in args:
                return (0, " M src/main.py\n", "")
            if "pr" in args and "list" in args:
                return (0, "123\n", "")  # existing PR number
            return (0, "", "")

        with patch("autopilot.channels.github_pr.run_command_async", side_effect=fake_cmd):
            await channel.notify(
                "scan", ok_result, backend="claude_cli", model=None, context=context
            )

        # Should force-push + edit existing PR, not create new
        assert any("push" in str(c) and "--force" in str(c) for c in call_log)
        assert not any("pr" in str(c) and "create" in str(c) for c in call_log)
        assert any("pr" in str(c) and "edit" in str(c) for c in call_log)

    async def test_skips_without_context(self, ok_result: BackendResult):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        channel = GitHubPRChannel(cfg)

        # No context or no worktree_path — should skip silently
        await channel.notify("scan", ok_result, backend="claude_cli", model=None, context=None)

    async def test_draft_pr(self, ok_result: BackendResult, tmp_path: Path):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo", draft=True)
        channel = GitHubPRChannel(cfg)

        wt = tmp_path / "worktree"
        wt.mkdir()
        context = {"worktree_path": str(wt)}

        call_log: list[list[str]] = []

        async def fake_cmd(args, *, cwd=None, timeout=None):
            call_log.append(args)
            if "status" in args and "--porcelain" in args:
                return (0, " M file.py\n", "")
            if "pr" in args and "list" in args:
                return (0, "", "")
            return (0, "", "")

        with patch("autopilot.channels.github_pr.run_command_async", side_effect=fake_cmd):
            await channel.notify(
                "scan", ok_result, backend="claude_cli", model=None, context=context
            )

        assert any("--draft" in str(c) for c in call_log)


class TestGetChannelGitHubPR:
    def test_github_pr(self):
        cfg = ChannelConfig(type="github_pr", repo="owner/repo")
        ch = get_channel(cfg)
        assert isinstance(ch, GitHubPRChannel)
