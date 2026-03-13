from __future__ import annotations

import os
from typing import Protocol

from pydantic import BaseModel, model_validator

from autopilot.models import BackendResult


class ChannelConfig(BaseModel):
    type: str
    # Slack fields
    webhook_url: str | None = None
    webhook_url_env: str | None = None
    # GitHub fields
    repo: str | None = None
    labels: list[str] | None = None
    draft: bool = False

    @model_validator(mode="after")
    def check_config(self) -> ChannelConfig:
        if self.type == "slack" and not self.webhook_url and not self.webhook_url_env:
            raise ValueError("Slack channel requires webhook_url or webhook_url_env")
        if self.type in ("github_issue", "github_pr") and not self.repo:
            raise ValueError(f"{self.type} channel requires repo")
        return self

    def resolve_webhook_url(self) -> str:
        """Resolve the webhook URL, checking env var if needed."""
        if self.webhook_url:
            return self.webhook_url
        if self.webhook_url_env:
            url = os.environ.get(self.webhook_url_env)
            if not url:
                raise RuntimeError(f"Environment variable {self.webhook_url_env!r} is not set")
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
        context: dict | None = None,
    ) -> None: ...
