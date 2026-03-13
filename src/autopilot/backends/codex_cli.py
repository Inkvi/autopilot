from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from autopilot.models import BackendResult
from autopilot.shell import run_command_async


def _sanitize_output(text: str) -> str:
    if not text:
        return ""
    skip_prefixes = (
        "Failed to write last message file ",
        "Warning: no last agent message; wrote empty content to ",
    )
    lines = []
    for line in text.splitlines():
        if line.startswith(skip_prefixes):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _build_command(
    prompt: str,
    *,
    model: str | None,
    reasoning_effort: str | None,
    output_last_message_path: Path,
) -> list[str]:
    args = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_last_message_path),
    ]
    if model:
        args.extend(["-m", model])
    if reasoning_effort:
        args.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    args.append(prompt)
    return args


def _extract_fallback_text(stdout: str, stderr: str) -> str:
    stdout_text = stdout.strip()
    if stdout_text:
        return _sanitize_output(stdout_text)
    lines = stderr.splitlines()
    for marker in ("codex", "assistant"):
        indices = [i for i, line in enumerate(lines) if line.strip() == marker]
        if indices:
            start = indices[-1] + 1
            candidate = "\n".join(lines[start:]).strip()
            if candidate:
                return _sanitize_output(candidate)
    return ""


class CodexCLIBackend:
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
        output_path = cwd / f".codex-last-message-{uuid4().hex}.md"
        try:
            args = _build_command(
                prompt,
                model=model,
                reasoning_effort=reasoning_effort,
                output_last_message_path=output_path,
            )
            code, raw_stdout, stderr = await run_command_async(
                args,
                cwd=cwd,
                timeout=timeout_seconds,
                log_file=log_file,
                on_output=on_output,
            )

            markdown = ""
            if output_path.exists():
                markdown = output_path.read_text(encoding="utf-8", errors="replace")
                output_path.unlink(missing_ok=True)
            markdown = _sanitize_output(markdown)

            if not markdown:
                markdown = _extract_fallback_text(raw_stdout, stderr)
            if code != 0:
                raise RuntimeError(f"codex exited with status {code}: {stderr.strip()}")
            if not markdown:
                raise RuntimeError("Codex returned an empty response")

            return BackendResult(
                status="ok",
                output=markdown,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except TimeoutError:
            output_path.unlink(missing_ok=True)
            return BackendResult(
                status="error",
                output="",
                error=f"codex timed out after {timeout_seconds}s",
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            return BackendResult(
                status="error",
                output="",
                error=str(exc),
                started_at=started,
                ended_at=datetime.now(UTC),
            )
