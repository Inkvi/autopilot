from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ai_automations.models import BackendResult
from ai_automations.shell import run_command_async


def _build_command(prompt: str, *, model: str | None) -> list[str]:
    args = [
        "gemini",
        "-p",
        prompt,
        "--approval-mode",
        "yolo",
        "--output-format",
        "json",
    ]
    if model:
        args.extend(["-m", model])
    return args


def _extract_markdown_from_payload(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("response", "text", "output", "result", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    parts = payload.get("parts")
    if isinstance(parts, list):
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())
        if text_parts:
            return "\n".join(text_parts)
    return ""


def _iter_json_payloads(text: str) -> list[object]:
    payloads: list[object] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start == -1:
            break
        try:
            payload, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        payloads.append(payload)
        index = end
    return payloads


def _extract_text(stdout: str, stderr: str) -> str:
    for payload in reversed(_iter_json_payloads(stdout)):
        md = _extract_markdown_from_payload(payload)
        if md:
            return md
    if stdout.strip():
        return stdout.strip()
    lines = stderr.splitlines()
    for marker in ("gemini", "assistant", "model"):
        indices = [i for i, line in enumerate(lines) if line.strip() == marker]
        if indices:
            start = indices[-1] + 1
            candidate = "\n".join(lines[start:]).strip()
            if candidate:
                return candidate
    return ""


def _summarize_error(stderr: str) -> str:
    lines = stderr.strip().splitlines()
    for line in lines:
        stripped = line.strip()
        if "Error:" in stripped and not stripped.startswith("at "):
            return stripped
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return stderr.strip()[:200]


class GeminiCLIBackend:
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
            args = _build_command(prompt, model=model)
            code, raw_stdout, stderr = await run_command_async(
                args, cwd=cwd, timeout=timeout_seconds
            )
            if code != 0:
                raise RuntimeError(
                    f"gemini exited with status {code}: {_summarize_error(stderr)}"
                )
            text = _extract_text(raw_stdout, stderr)
            if not text:
                raise RuntimeError("Gemini returned an empty response")
            return BackendResult(
                status="ok",
                output=text,
                error=None,
                started_at=started,
                ended_at=datetime.now(UTC),
            )
        except TimeoutError:
            return BackendResult(
                status="error",
                output="",
                error=f"gemini timed out after {timeout_seconds}s",
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
