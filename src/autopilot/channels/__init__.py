from __future__ import annotations

from autopilot.channels.base import Channel, ChannelConfig


def get_channel(config: ChannelConfig) -> Channel:
    """Return a channel instance for the given config."""
    match config.type:
        case "slack":
            from autopilot.channels.slack import SlackWebhookChannel

            return SlackWebhookChannel(config)
        case "github_issue":
            from autopilot.channels.github_issue import GitHubIssueChannel

            return GitHubIssueChannel(config)
        case "github_pr":
            from autopilot.channels.github_pr import GitHubPRChannel

            return GitHubPRChannel(config)
        case _:
            raise ValueError(f"Unknown channel type: {config.type!r}")


__all__ = ["Channel", "ChannelConfig", "get_channel"]
