from __future__ import annotations

import os
from typing import Protocol

from pydantic import BaseModel, model_validator

from autopilot.models import BackendResult


class ChannelConfig(BaseModel):
    type: str
    webhook_url: str | None = None
    webhook_url_env: str | None = None

    @model_validator(mode="after")
    def check_webhook(self) -> ChannelConfig:
        if self.type == "slack" and not self.webhook_url and not self.webhook_url_env:
            raise ValueError("Slack channel requires webhook_url or webhook_url_env")
        return self

    def resolve_webhook_url(self) -> str:
        """Resolve the webhook URL, checking env var if needed."""
        if self.webhook_url:
            return self.webhook_url
        if self.webhook_url_env:
            url = os.environ.get(self.webhook_url_env)
            if not url:
                raise RuntimeError(
                    f"Environment variable {self.webhook_url_env!r} is not set"
                )
            return url
        raise RuntimeError("No webhook URL configured")


class Channel(Protocol):
    async def notify(
        self,
        automation_name: str,
        result: BackendResult,
        *,
        backend: str,
        model: str | None,
    ) -> None: ...
