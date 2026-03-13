from __future__ import annotations

from autopilot.channels.base import ChannelConfig
from autopilot.models import BackendResult
from autopilot.shell import run_command_async


class GitHubIssueChannel:
    def __init__(self, config: ChannelConfig) -> None:
        self._config = config

    async def notify(
        self,
        automation_name: str,
        result: BackendResult,
        *,
        backend: str,
        model: str | None,
        context: dict | None = None,
    ) -> None:
        status = result.status
        title = f"[autopilot] {automation_name}: {status}"

        body = result.output.strip() if result.output else ""
        if result.error:
            body = f"**Error:** {result.error}\n\n{body}"
        # Truncate body to stay within GitHub limits (~65536 chars)
        if len(body) > 60000:
            body = body[:60000] + "\n\n...(truncated)"

        repo = self._config.repo
        if not repo:
            raise RuntimeError("github_issue channel requires repo")

        args = [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
        ]

        if self._config.labels:
            for label in self._config.labels:
                args.extend(["--label", label])

        code, stdout, stderr = await run_command_async(args, timeout=30)
        if code != 0:
            raise RuntimeError(f"gh issue create failed: {stderr.strip()}")
