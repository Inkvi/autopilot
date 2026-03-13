from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_automations.models import BackendResult


class ClaudeSDKBackend:
    async def run(
        self,
        prompt: str,
        *,
        cwd: Path,
        timeout_seconds: int,
        model: str | None,
        reasoning_effort: str | None,
        skip_permissions: bool,
        max_turns: int,
    ) -> BackendResult:
        started = datetime.now(UTC)
        try:
            from anyio import fail_after
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )

            permission_mode = "bypassPermissions" if skip_permissions else "default"
            options = ClaudeAgentOptions(
                cwd=cwd,
                permission_mode=permission_mode,
                max_turns=max_turns,
                model=model,
                effort=reasoning_effort,
                env={"CLAUDECODE": ""},
            )

            parts: list[str] = []
            final_result: str | None = None

            with fail_after(timeout_seconds):
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                parts.append(block.text)
                    elif isinstance(message, ResultMessage):
                        if message.result:
                            final_result = message.result

            merged = (final_result or "\n".join(parts)).strip()
            if not merged:
                raise RuntimeError("Claude SDK returned an empty response")

            return BackendResult(
                status="ok",
                output=merged,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except TimeoutError:
            return BackendResult(
                status="error",
                output="",
                error=f"Claude SDK timed out after {timeout_seconds}s",
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except Exception as exc:
            return BackendResult(
                status="error",
                output="",
                error=str(exc),
                started_at=started,
                ended_at=datetime.now(UTC),
            )
