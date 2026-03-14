from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from autopilot.models import BackendResult, TokenUsage
from autopilot.shell import run_command_async


def _build_command(
    prompt: str,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    reasoning_effort: str | None = None,
    skip_permissions: bool = True,
) -> list[str]:
    args = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if skip_permissions:
        args.append("--dangerously-skip-permissions")
    if model:
        args.extend(["--model", model])
    if max_turns is not None:
        args.extend(["--max-turns", str(max_turns)])
    if reasoning_effort:
        args.extend(["--effort", reasoning_effort])
    return args


def _parse_stream_json(raw: str) -> tuple[str, list[dict], TokenUsage | None]:
    """Parse stream-json output into (result_text, conversation_events, usage).

    Real stream-json format from Claude CLI:
    - type:"system" (subtype:"init"|"hook_*") — session init / hook events
    - type:"assistant" — message.content[] with text/tool_use/thinking blocks
    - type:"user" — tool results (message.content[].type:"tool_result")
    - type:"rate_limit_event" — rate limit info
    - type:"result" — final result with total_cost_usd, usage.input_tokens/output_tokens
    """
    events: list[dict] = []
    result_text = ""
    usage = None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            events.append(event)
            if event.get("type") == "result":
                result_text = event.get("result", "")
                cost = event.get("total_cost_usd") or event.get("cost_usd")
                result_usage = event.get("usage", {})
                tokens_in = result_usage.get("input_tokens")
                tokens_out = result_usage.get("output_tokens")
                if cost is not None or tokens_in is not None:
                    usage = TokenUsage(
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        cost_usd=cost,
                    )
        except json.JSONDecodeError:
            continue
    return result_text, events, usage


class ClaudeCLIBackend:
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
        log_file: Path | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> BackendResult:
        started = datetime.now(UTC)
        try:
            args = _build_command(
                prompt,
                model=model,
                max_turns=max_turns,
                reasoning_effort=reasoning_effort,
                skip_permissions=skip_permissions,
            )
            code, stdout, stderr = await run_command_async(
                args,
                cwd=cwd,
                timeout=timeout_seconds,
                env={"CLAUDECODE": ""},
                log_file=log_file,
                on_output=on_output,
            )
            if code != 0:
                raise RuntimeError(f"claude CLI exited with status {code}: {stderr.strip()}")

            text, conversation, usage = _parse_stream_json(stdout)
            if not text:
                raise RuntimeError("Claude CLI returned an empty response")

            return BackendResult(
                status="ok",
                output=text,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
                conversation=conversation or None,
                usage=usage,
            )
        except TimeoutError:
            return BackendResult(
                status="error",
                output="",
                error=f"claude CLI timed out after {timeout_seconds}s",
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
