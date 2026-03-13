from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from ai_automations.channels import get_channel
from ai_automations.channels.base import ChannelConfig
from ai_automations.channels.slack import SlackWebhookChannel, _format_message
from ai_automations.models import BackendResult

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

        with patch("ai_automations.channels.slack._post_webhook") as mock_post:
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

        with patch("ai_automations.channels.slack._post_webhook") as mock_post:
            await channel.notify("scan", ok_result, backend="claude_cli", model=None)

        assert mock_post.call_args[0][0] == "https://hooks.slack.com/from-env"
