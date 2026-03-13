from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_automations.models import BackendResult
from ai_automations.shell import run_command_async


def _build_command(
    prompt: str,
    *,
    model: str | None = None,
    max_turns: int | None = None,
    reasoning_effort: str | None = None,
    skip_permissions: bool = True,
) -> list[str]:
    args = ["claude", "-p", prompt, "--output-format", "text"]
    if skip_permissions:
        args.append("--dangerously-skip-permissions")
    if model:
        args.extend(["--model", model])
    if max_turns is not None:
        args.extend(["--max-turns", str(max_turns)])
    if reasoning_effort:
        args.extend(["--effort", reasoning_effort])
    return args


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
                args, cwd=cwd, timeout=timeout_seconds, env={"CLAUDECODE": ""}
            )
            if code != 0:
                raise RuntimeError(f"claude CLI exited with status {code}: {stderr.strip()}")
            text = stdout.strip()
            if not text:
                raise RuntimeError("Claude CLI returned an empty response")
            return BackendResult(
                status="ok", output=text, error=None, started_at=started, ended_at=datetime.now(UTC)
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
