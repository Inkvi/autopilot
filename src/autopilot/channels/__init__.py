from __future__ import annotations

from autopilot.channels.base import Channel, ChannelConfig


def get_channel(config: ChannelConfig) -> Channel:
    """Return a channel instance for the given config."""
    match config.type:
        case "slack":
            from autopilot.channels.slack import SlackWebhookChannel

            return SlackWebhookChannel(config)
        case _:
            raise ValueError(f"Unknown channel type: {config.type!r}")


__all__ = ["Channel", "ChannelConfig", "get_channel"]
