from __future__ import annotations

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
    ) -> BackendResult: ...
