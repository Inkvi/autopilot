from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from autopilot.models import BackendResult


def _block_to_dict(block) -> dict:
    """Convert an SDK content block to a serializable dict."""
    block_type = getattr(block, "type", "unknown")
    result: dict = {"type": block_type}
    if block_type == "text":
        result["text"] = getattr(block, "text", "")
    elif block_type == "tool_use":
        result["name"] = getattr(block, "name", "")
        result["input"] = getattr(block, "input", {})
        result["id"] = getattr(block, "id", "")
    elif block_type == "tool_result":
        result["tool_use_id"] = getattr(block, "tool_use_id", "")
        result["content"] = str(getattr(block, "content", ""))
    elif block_type == "thinking":
        result["text"] = getattr(block, "text", "")
    else:
        result["text"] = str(block)
    return result


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
        system_prompt: str | None = None,
        log_file: Path | None = None,
        on_output: Callable[[str], None] | None = None,
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
                system_prompt=system_prompt or "",
            )

            parts: list[str] = []
            final_result: str | None = None
            conversation: list[dict] = []
            fh = open(log_file, "w", encoding="utf-8") if log_file else None

            try:
                with fail_after(timeout_seconds):
                    async for message in query(prompt=prompt, options=options):
                        if isinstance(message, AssistantMessage):
                            content_blocks = [_block_to_dict(b) for b in message.content]
                            conversation.append(
                                {
                                    "type": "assistant",
                                    "message": {"content": content_blocks},
                                }
                            )
                            for block in message.content:
                                if isinstance(block, TextBlock) and block.text.strip():
                                    parts.append(block.text)
                                    if fh:
                                        fh.write(block.text + "\n")
                                        fh.flush()
                                    if on_output:
                                        for line in block.text.splitlines():
                                            on_output(line)
                        elif isinstance(message, ResultMessage):
                            if message.result:
                                final_result = message.result
                            conversation.append(
                                {
                                    "type": "result",
                                    "result": message.result or "",
                                }
                            )
            finally:
                if fh:
                    fh.close()

            merged = (final_result or "\n".join(parts)).strip()
            if not merged:
                raise RuntimeError("Claude SDK returned an empty response")

            return BackendResult(
                status="ok",
                output=merged,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
                conversation=conversation or None,
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
