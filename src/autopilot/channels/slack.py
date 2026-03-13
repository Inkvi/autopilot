from __future__ import annotations

import asyncio
import json
import urllib.request
from functools import partial

from autopilot.channels.base import ChannelConfig
from autopilot.models import BackendResult


def _format_message(
    automation_name: str,
    result: BackendResult,
    *,
    backend: str,
    model: str | None,
) -> dict:
    duration = (result.ended_at - result.started_at).total_seconds()
    model_str = model or "default"

    if result.status == "ok":
        emoji = ":white_check_mark:"
        title = f"{emoji} *{automation_name}* completed in {duration:.1f}s"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": title}},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Backend: `{backend}` | Model: `{model_str}`"}
                ],
            },
        ]
        # Include a truncated output snippet
        snippet = result.output.strip()
        if snippet:
            if len(snippet) > 500:
                snippet = snippet[:500] + "\n..."
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"```\n{snippet}\n```"}},
            )
    else:
        emoji = ":x:"
        title = f"{emoji} *{automation_name}* failed after {duration:.1f}s"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": title}},
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Backend: `{backend}` | Model: `{model_str}`"}
                ],
            },
        ]
        if result.error:
            error_text = result.error
            if len(error_text) > 500:
                error_text = error_text[:500] + "..."
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Error:* {error_text}"}},
            )

    return {"blocks": blocks, "text": title}


def _post_webhook(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status not in range(200, 300):
            body = resp.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Slack webhook returned {resp.status}: {body}")


class SlackWebhookChannel:
    def __init__(self, config: ChannelConfig) -> None:
        self._config = config

    async def notify(
        self,
        automation_name: str,
        result: BackendResult,
        *,
        backend: str,
        model: str | None,
    ) -> None:
        url = self._config.resolve_webhook_url()
        payload = _format_message(
            automation_name, result, backend=backend, model=model
        )
        await asyncio.to_thread(partial(_post_webhook, url, payload))
