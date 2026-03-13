from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from autopilot.models import BackendResult


class Backend(Protocol):
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
    ) -> BackendResult: ...
